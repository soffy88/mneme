"""嫁接 3：讲义 / 题目插图裁剪。

夹具 PDF 由本测试现场拼装（标准 14 号字体 + 矢量矩形 / 全页图片），
不依赖任何外部文件。pypdfium2 缺失时真实裁图用例跳过，降级用例必跑。
"""

from __future__ import annotations

import pytest

from services import figure_crop


def _build_pdf(objects: list[bytes]) -> bytes:
    """拼一个最小合法 PDF：objects[0] 为 Catalog，其余按序编号。"""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _vector_page_pdf() -> bytes:
    content = b"BT /F1 24 Tf 100 700 Td (a^2 + b^2 = c^2) Tj ET 100 500 200 100 re f"
    return _build_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        ]
    )


def _scanned_page_pdf() -> bytes:
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    img = b"\x00\x00\x00"
    return _build_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n" + img + b"\nendstream",
        ]
    )


needs_pdfium = pytest.mark.skipif(
    not figure_crop.pypdfium2_available(), reason="pypdfium2 未安装，真实裁图跳过"
)


@needs_pdfium
def test_vector_page_crops_figure_png():
    res = figure_crop.crop_page_figures(_vector_page_pdf(), 0)
    assert res.available is True and res.skipped is False
    assert len(res.figures) >= 1
    fig = res.figures[0]
    assert fig.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    left, bottom, right, top = fig.bbox
    assert abs(left - 100) < 6 and abs(bottom - 500) < 6
    assert abs(right - 300) < 6 and abs(top - 600) < 6
    assert fig.width_px == 400 and fig.height_px == 200  # scale=2.0


@needs_pdfium
def test_scanned_page_skipped_not_shown_as_answer():
    res = figure_crop.crop_page_figures(_scanned_page_pdf(), 0)
    assert res.available is True
    assert res.skipped is True and res.skip_reason == "scanned_page"
    assert res.figures == []


@needs_pdfium
def test_page_out_of_range_does_not_raise():
    res = figure_crop.crop_page_figures(_vector_page_pdf(), 99)
    assert res.skipped is True and res.skip_reason == "page_out_of_range"


def test_missing_pypdfium2_degrades_without_crash(monkeypatch):
    monkeypatch.setattr(figure_crop, "_PDFIUM", None)
    monkeypatch.setattr(figure_crop, "_PDFIUM_TRIED", True)
    res = figure_crop.crop_page_figures(_vector_page_pdf(), 0)
    assert res.available is False and res.figures == []
    assert res.skip_reason == "pypdfium2_missing"
    assert figure_crop.crop_document(_vector_page_pdf())[0].available is False


def test_cluster_merges_overlap_keeps_separate():
    merged = figure_crop._cluster_boxes(
        [(0, 0, 50, 50), (40, 40, 90, 90), (200, 200, 250, 250)], margin=4.0
    )
    assert len(merged) == 2
    assert (0, 0, 90, 90) in merged and (200, 200, 250, 250) in merged


def test_figure_object_key_is_safe_and_prefixed():
    fig = figure_crop.CroppedFigure(
        page_index=2, index=0, bbox=(0, 0, 10, 10), png_bytes=b"", width_px=1, height_px=1
    )
    key = figure_crop.figure_object_key("lec 1/chapter.pdf", fig)
    assert key == "figures/lec_1_chapter_pdf/p2_0.png"


def test_figures_for_message_shape():
    out = figure_crop.figures_for_message([("figures/lec1/p0_0.png", 0)])
    assert out == [{"key": "figures/lec1/p0_0.png", "page": 0}]
