"""讲义 / 题目 PDF 按页裁图，供 tutor 讲题时展示。

Exam Cram Coach 方法论的 Mneme 干净实现（方法可学，代码自己写）：
- 用 pypdfium2（可选依赖）：缺失时优雅降级——返回 available=False，
  其余功能照常，绝不崩溃（照 Exam Cram 的降级口径）。
- 只裁向量图区域：讲义里的示意图、题目里的配图；扫描 / 手写页故意
  跳过，绝不把学生手写当答案展示。
- 存储走仓内既有 MinIO 约定（services.storage 的 lesson-figures 私有
  桶，只存对象键，不出签名 URL）。

本模块除 pypdfium2 / Pillow 外无重依赖；裁图函数是纯字节进出，
可脱服务直测。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional, Sequence

_PDFIUM = None
_PDFIUM_TRIED = False

# 扫描页判定：可抽文字少于该阈值，且单张图覆盖页面积超过该比例 → 扫描页。
SCANNED_TEXT_MAX = 20
SCANNED_COVERAGE = 0.60
# 过滤噪点：边长小于该值（pt）的图形不裁；整页底图（覆盖超该比例）不裁。
MIN_SIDE_PT = 12.0
FULL_PAGE_COVERAGE = 0.95
CLUSTER_MARGIN_PT = 4.0


def pypdfium2_available() -> bool:
    """pypdfium2 是否可用（惰性导入一次并缓存）。"""
    global _PDFIUM, _PDFIUM_TRIED
    if not _PDFIUM_TRIED:
        _PDFIUM_TRIED = True
        try:
            import pypdfium2 as _mod  # type: ignore[import-not-found]

            _PDFIUM = _mod
        except Exception:  # noqa: BLE001 - 可选依赖缺失即降级
            _PDFIUM = None
    return _PDFIUM is not None


def _pageobj_types() -> tuple[int, int, int]:
    """页面对象类型常量：pypdfium2 的常量在 raw 子模块，不在模块顶层。

    返回 (IMAGE, PATH, SHADING)；raw 取不到时回落 PDFium 公开值
    （TEXT=1, PATH=2, IMAGE=3, SHADING=4, FORM=5）。
    """
    try:
        import pypdfium2.raw as _raw  # type: ignore[import-not-found]

        return (
            _raw.FPDF_PAGEOBJ_IMAGE,
            _raw.FPDF_PAGEOBJ_PATH,
            _raw.FPDF_PAGEOBJ_SHADING,
        )
    except Exception:  # noqa: BLE001
        return (3, 2, 4)


@dataclass
class CroppedFigure:
    """一处裁出的图：bbox 为 PDF 点坐标（左、下、右、上，原点左下）。"""

    page_index: int
    index: int
    bbox: tuple[float, float, float, float]
    png_bytes: bytes
    width_px: int
    height_px: int


@dataclass
class CropResult:
    """一页的裁图结果：available=False 表示 pypdfium2 缺失（降级）；"""

    available: bool
    skipped: bool
    skip_reason: Optional[str]
    figures: list[CroppedFigure] = field(default_factory=list)


def _cluster_boxes(
    boxes: list[tuple[float, float, float, float]],
    margin: float,
) -> list[tuple[float, float, float, float]]:
    """把重叠 / 靠近的图形框并成区域（并查集 + 外扩 margin 再合并）。"""

    def _overlap(a: tuple, b: tuple) -> bool:
        return not (
            a[2] + margin < b[0]
            or b[2] + margin < a[0]
            or a[3] + margin < b[1]
            or b[3] + margin < a[1]
        )

    parent = list(range(len(boxes)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i], boxes[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[tuple]] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    merged = []
    for bs in groups.values():
        merged.append(
            (
                min(b[0] for b in bs),
                min(b[1] for b in bs),
                max(b[2] for b in bs),
                max(b[3] for b in bs),
            )
        )
    return merged


def crop_page_figures(
    pdf_bytes: bytes,
    page_index: int,
    *,
    scale: float = 2.0,
    max_figures: int = 20,
) -> CropResult:
    """裁一页的图。pypdfium2 缺失 / 页码越界时不抛异常，只返回空结果。"""
    if not pypdfium2_available():
        return CropResult(available=False, skipped=False, skip_reason="pypdfium2_missing")
    assert _PDFIUM is not None
    try:
        doc = _PDFIUM.PdfDocument(pdf_bytes)
    except Exception:  # noqa: BLE001 - 坏 PDF 也只返回空结果
        return CropResult(available=True, skipped=True, skip_reason="unreadable_pdf")
    try:
        if page_index < 0 or page_index >= len(doc):
            return CropResult(available=True, skipped=True, skip_reason="page_out_of_range")
        page = doc[page_index]
        page_w, page_h = page.get_size()
        page_area = max(1.0, page_w * page_h)
        try:
            text = page.get_textpage().get_text_range() or ""
        except Exception:  # noqa: BLE001 - 取不到文字按无文字处理
            text = ""
        text_len = len("".join(text.split()))
        try:
            objects = list(page.get_objects())
        except Exception:  # noqa: BLE001
            objects = []
        path_boxes: list[tuple[float, float, float, float]] = []
        image_boxes: list[tuple[float, float, float, float]] = []
        _t_image, _t_path, _t_shading = _pageobj_types()
        for obj in objects:
            try:
                otype = obj.type
                left, bottom, right, top = obj.get_bounds()
            except Exception:  # noqa: BLE001 - 单个对象读失败就跳过
                continue
            if right <= left or top <= bottom:
                continue
            if otype == _t_image:
                image_boxes.append((left, bottom, right, top))
            elif otype in (_t_path, _t_shading):
                path_boxes.append((left, bottom, right, top))
        # 扫描页：几乎无可抽文字 + 单张图盖住大半页 → 跳过整页。
        for b in image_boxes:
            if (b[2] - b[0]) * (b[3] - b[1]) / page_area >= SCANNED_COVERAGE and text_len < SCANNED_TEXT_MAX:
                return CropResult(available=True, skipped=True, skip_reason="scanned_page")
        # 候选：向量框 + 非整页图框；滤掉噪点与整页底图。
        candidates: list[tuple[float, float, float, float]] = []
        for b in path_boxes + image_boxes:
            w, h = b[2] - b[0], b[3] - b[1]
            if w < MIN_SIDE_PT or h < MIN_SIDE_PT:
                continue
            if w * h / page_area >= FULL_PAGE_COVERAGE:
                continue
            candidates.append(b)
        if not candidates:
            return CropResult(available=True, skipped=False, skip_reason=None, figures=[])
        regions = _cluster_boxes(candidates, CLUSTER_MARGIN_PT)
        regions.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
        regions = regions[: max(1, int(max_figures))]
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        figures: list[CroppedFigure] = []
        for idx, (left, bottom, right, top) in enumerate(regions):
            x0 = max(0, int(left * scale))
            y0 = max(0, int((page_h - top) * scale))
            x1 = min(pil.width, int(right * scale))
            y1 = min(pil.height, int((page_h - bottom) * scale))
            if x1 <= x0 or y1 <= y0:
                continue
            crop = pil.crop((x0, y0, x1, y1))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            figures.append(
                CroppedFigure(
                    page_index=page_index,
                    index=idx,
                    bbox=(left, bottom, right, top),
                    png_bytes=buf.getvalue(),
                    width_px=x1 - x0,
                    height_px=y1 - y0,
                )
            )
        return CropResult(available=True, skipped=False, skip_reason=None, figures=figures)
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def crop_document(
    pdf_bytes: bytes,
    *,
    pages: Optional[Sequence[int]] = None,
    scale: float = 2.0,
    max_figures_per_page: int = 20,
) -> list[CropResult]:
    """整本裁图：pages 为 None 时裁全部页（页数多时调用方应先限页）。"""
    if not pypdfium2_available():
        return [CropResult(available=False, skipped=False, skip_reason="pypdfium2_missing")]
    assert _PDFIUM is not None
    try:
        total = len(_PDFIUM.PdfDocument(pdf_bytes))
    except Exception:  # noqa: BLE001
        return [CropResult(available=True, skipped=True, skip_reason="unreadable_pdf")]
    targets = list(pages) if pages is not None else list(range(total))
    return [
        crop_page_figures(pdf_bytes, p, scale=scale, max_figures=max_figures_per_page)
        for p in targets
    ]


def figure_object_key(doc_key: str, figure: CroppedFigure) -> str:
    """MinIO 对象键：只存键，不出签名 URL（同 question-images 约定）。"""
    safe_doc = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in doc_key)
    return f"figures/{safe_doc}/p{figure.page_index}_{figure.index}.png"


def save_figure(doc_key: str, figure: CroppedFigure) -> str:
    """把裁出的图存进 lesson-figures 私有桶，返回对象键。"""
    from services.storage import upload_lesson_figure

    key = figure_object_key(doc_key, figure)
    upload_lesson_figure(key, figure.png_bytes, "image/png")
    return key


def figures_for_message(saved: Sequence[tuple[str, int]]) -> list[dict]:
    """tutor 聊天消息里的图引用字段：前端按 key 经鉴权接口取字节渲染。

    saved 为 (object_key, page_index) 序列。前端接点（待接）：tutor 聊天
    消息组件渲染 figures[]，每项经鉴权图片接口取字节（同 question-images
    的私有图片接口模式，不直接拼签名 URL）。
    """
    return [{"key": key, "page": page} for key, page in saved]
