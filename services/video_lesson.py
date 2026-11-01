"""Video lesson specs (DeepTutor video-lesson method, clean rewrite).

Deterministic spec contract + verification gate + assembly. No audio
synthesis and no frame rendering: assembly returns scenes + captions +
narration text. Playback, rendering, and progress persistence are
frontend / follow-up work; progress state here is a pure in-memory
shape with a sequential-completion rule ("a scene counts only once the
previous one is done").
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from services.animate_service import SETTABLE, SHAPE_TYPES
from services.provenance import ProvenanceLabel

MAX_SCENES = 12
MAX_CAPTIONS = 40
MAX_SHAPES_PER_SCENE = 40
MAX_FRAMES_PER_SCENE = 60
MAX_SCENE_MS = 180_000
MAX_TOTAL_MS = 600_000
MAX_FRAME_MS = 60_000
MAX_NARRATION_CHARS = 2_000
MAX_TITLE_CHARS = 200


class VideoLessonIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


class VideoLessonCheck:
    def __init__(self, gates: dict[str, bool], issues: list[VideoLessonIssue]) -> None:
        self.gates = gates
        self.issues = issues

    @property
    def passed(self) -> bool:
        return all(self.gates.values()) and not self.issues


def _is_bilingual(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("zh"), str)
        and value["zh"].strip() != ""
        and isinstance(value.get("en"), str)
        and value["en"].strip() != ""
    )


def _check_shapes(scene: Mapping[str, Any], issues: list[VideoLessonIssue], prefix: str) -> set[str]:
    shapes = scene.get("shapes")
    declared: set[str] = set()
    if not isinstance(shapes, list):
        issues.append(VideoLessonIssue(f"{prefix}.shapes", "not_a_list", "shapes must be a list"))
        return declared
    if len(shapes) > MAX_SHAPES_PER_SCENE:
        issues.append(VideoLessonIssue(f"{prefix}.shapes", "too_many_shapes", "too many shapes"))
    for pos, shape in enumerate(shapes):
        field = f"{prefix}.shapes[{pos}]"
        if not isinstance(shape, dict):
            issues.append(VideoLessonIssue(field, "not_an_object", "shape must be an object"))
            continue
        sid = shape.get("id")
        if not isinstance(sid, str) or not sid:
            issues.append(VideoLessonIssue(field, "missing_id", "shape id must be a non-empty string"))
            continue
        if sid in declared:
            issues.append(VideoLessonIssue(field, "duplicate_id", "duplicate shape id"))
        declared.add(sid)
        stype = shape.get("type")
        if stype not in SHAPE_TYPES:
            issues.append(VideoLessonIssue(field, "bad_shape_type", "unknown shape type"))
            continue
        allowed = SHAPE_TYPES[stype]
        for key in shape:
            if key in ("id", "type"):
                continue
            if key not in allowed:
                issues.append(VideoLessonIssue(field, "bad_shape_attr", f"attribute {key!r} not allowed"))
    return declared


def _check_frames(scene: Mapping[str, Any], declared: set[str], issues: list[VideoLessonIssue], prefix: str) -> None:
    frames = scene.get("frames")
    if not isinstance(frames, list):
        issues.append(VideoLessonIssue(f"{prefix}.frames", "not_a_list", "frames must be a list"))
        return
    if len(frames) > MAX_FRAMES_PER_SCENE:
        issues.append(VideoLessonIssue(f"{prefix}.frames", "too_many_frames", "too many frames"))
    for pos, frame in enumerate(frames):
        field = f"{prefix}.frames[{pos}]"
        if not isinstance(frame, dict):
            issues.append(VideoLessonIssue(field, "not_an_object", "frame must be an object"))
            continue
        for key in ("show", "highlight"):
            refs = frame.get(key, [])
            if not isinstance(refs, list):
                issues.append(VideoLessonIssue(field, f"bad_{key}", f"{key} must be a list"))
                continue
            for ref in refs:
                if ref not in declared:
                    issues.append(VideoLessonIssue(field, "dangling_ref", f"{key} references undeclared shape"))
        set_map = frame.get("set", {})
        if not isinstance(set_map, dict):
            issues.append(VideoLessonIssue(field, "bad_set", "set must be an object"))
        else:
            for sid, attrs in set_map.items():
                if sid not in declared:
                    issues.append(VideoLessonIssue(field, "dangling_ref", "set references undeclared shape"))
                elif not isinstance(attrs, dict):
                    issues.append(VideoLessonIssue(field, "bad_set", "set value must be an object"))
                else:
                    for attr in attrs:
                        if attr not in SETTABLE:
                            issues.append(VideoLessonIssue(field, "not_settable", f"attribute {attr!r} is not settable"))
        duration = frame.get("duration_ms")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 100 <= duration <= MAX_FRAME_MS:
            issues.append(VideoLessonIssue(field, "bad_frame_duration", "frame duration_ms out of bounds"))


def verify_video_lesson(spec: Mapping[str, Any], known_ku_ids: Optional[set[str]] = None) -> VideoLessonCheck:
    """Ten gates; all must pass. Failures list every cause."""
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 11)}
    issues: list[VideoLessonIssue] = []

    def fail(gate: str, issue: VideoLessonIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    # g1: schema valid, id present, captions/scenes are lists.
    if not isinstance(spec, dict):
        return VideoLessonCheck(gates, [VideoLessonIssue("", "not_an_object", "spec must be an object")])
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id or len(spec_id) > 100:
        fail("g1", VideoLessonIssue("id", "bad_id", "id must be a non-empty string of at most 100 chars"))
    captions = spec.get("captions")
    scenes = spec.get("scenes")
    if not isinstance(captions, list) or not captions:
        fail("g1", VideoLessonIssue("captions", "missing_captions", "captions must be a non-empty list"))
        captions = []
    if len(captions) > MAX_CAPTIONS:
        fail("g1", VideoLessonIssue("captions", "too_many_captions", "too many captions"))
    if not isinstance(scenes, list) or not scenes:
        fail("g1", VideoLessonIssue("scenes", "missing_scenes", "scenes must be a non-empty list"))
        scenes = []
    if len(scenes) > MAX_SCENES:
        fail("g1", VideoLessonIssue("scenes", "too_many_scenes", "too many scenes"))

    # g2: language fields complete (bilingual title + language code).
    if not _is_bilingual(spec.get("title")):
        fail("g2", VideoLessonIssue("title", "bad_title", "title must carry non-empty zh and en"))
    title = spec.get("title")
    if isinstance(title, dict):
        for lang_key in ("zh", "en"):
            val = title.get(lang_key)
            if isinstance(val, str) and len(val) > MAX_TITLE_CHARS:
                fail("g2", VideoLessonIssue(f"title.{lang_key}", "title_too_long", "title too long"))
    if spec.get("language") not in ("zh", "en"):
        fail("g2", VideoLessonIssue("language", "bad_language", "language must be zh or en"))

    # g3: caption/scene index closure.
    caption_indices = set()
    for pos, cap in enumerate(captions):
        if not isinstance(cap, dict) or cap.get("index") != pos:
            fail("g3", VideoLessonIssue(f"captions[{pos}]", "bad_caption_index", "caption indices must be contiguous from 0"))
            continue
        caption_indices.add(pos)
        if not isinstance(cap.get("text"), str) or not cap["text"].strip():
            fail("g3", VideoLessonIssue(f"captions[{pos}].text", "empty_caption", "caption text must be non-empty"))
    referenced: set[int] = set()
    for pos, scene in enumerate(scenes):
        if not isinstance(scene, dict) or scene.get("index") != pos:
            fail("g3", VideoLessonIssue(f"scenes[{pos}]", "bad_scene_index", "scene indices must be contiguous from 0"))
            continue
        ref = scene.get("caption_ref")
        if not isinstance(ref, int) or ref not in caption_indices:
            fail("g3", VideoLessonIssue(f"scenes[{pos}].caption_ref", "dangling_caption", "caption_ref must resolve to a caption"))
        else:
            referenced.add(ref)
    for idx in sorted(caption_indices - referenced):
        fail("g3", VideoLessonIssue(f"captions[{idx}]", "orphan_caption", "caption is not referenced by any scene"))

    # g4: narration text present per scene.
    for pos, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        narration = scene.get("narration_text")
        if not isinstance(narration, str) or not narration.strip():
            fail("g4", VideoLessonIssue(f"scenes[{pos}].narration_text", "empty_narration", "narration_text must be non-empty"))
        elif len(narration) > MAX_NARRATION_CHARS:
            fail("g4", VideoLessonIssue(f"scenes[{pos}].narration_text", "narration_too_long", "narration_text too long"))

    # g5: frame vocabulary closure (shapes + frames).
    for pos, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        declared = _check_shapes(scene, issues, f"scenes[{pos}]")
        if any(i.field.startswith(f"scenes[{pos}].shapes") for i in issues):
            gates["g5"] = False
        before = len(issues)
        _check_frames(scene, declared, issues, f"scenes[{pos}]")
        if len(issues) > before:
            gates["g5"] = False

    # g6: durations bounded (per scene + total).
    total_ms = 0
    for pos, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        duration = scene.get("duration_ms")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 1000 <= duration <= MAX_SCENE_MS:
            fail("g6", VideoLessonIssue(f"scenes[{pos}].duration_ms", "bad_scene_duration", "scene duration_ms out of bounds"))
        else:
            total_ms += duration
    if total_ms > MAX_TOTAL_MS:
        fail("g6", VideoLessonIssue("scenes", "total_too_long", "total duration exceeds the bound"))

    # g7: provenance complete.
    provenance = spec.get("provenance")
    if not isinstance(provenance, dict):
        fail("g7", VideoLessonIssue("provenance", "missing_provenance", "provenance must be an object"))
    else:
        label = provenance.get("label")
        if label not in {item.value for item in ProvenanceLabel}:
            fail("g7", VideoLessonIssue("provenance.label", "bad_label", "provenance label is not one of the three tiers"))
        sources = provenance.get("sources")
        if not isinstance(sources, list):
            fail("g7", VideoLessonIssue("provenance.sources", "bad_sources", "provenance sources must be a list"))
        elif label == ProvenanceLabel.MATERIAL.value and not sources:
            fail("g7", VideoLessonIssue("provenance.sources", "material_needs_source", "MATERIAL provenance needs at least one source"))

    # g8: KU anchor exists when present (fail-closed).
    ku_id = spec.get("ku_id")
    if ku_id is not None:
        if not isinstance(ku_id, str) or not ku_id:
            fail("g8", VideoLessonIssue("ku_id", "bad_ku_id", "ku_id must be a non-empty string"))
        elif known_ku_ids is None:
            fail("g8", VideoLessonIssue("ku_id", "unknown_ku_set", "KU anchor cannot be verified without a known set"))
        elif ku_id not in known_ku_ids:
            fail("g8", VideoLessonIssue("ku_id", "unknown_ku", "KU anchor does not exist"))

    # g9: start_scene in bounds.
    start_scene = spec.get("start_scene", 0)
    if not isinstance(start_scene, int) or isinstance(start_scene, bool) or not 0 <= start_scene < max(len(scenes), 1):
        fail("g9", VideoLessonIssue("start_scene", "bad_start_scene", "start_scene must be a valid scene index"))

    # g10: verified is server-managed only.
    if "verified" in spec:
        fail("g10", VideoLessonIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))

    return VideoLessonCheck(gates, issues)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def assemble_video_lesson(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic assembly: scenes + captions + narration, no media."""
    captions = spec.get("captions", [])
    caption_by_index = {cap["index"]: cap["text"] for cap in captions if isinstance(cap, dict)}
    scenes_out = []
    total_ms = 0
    for scene in spec.get("scenes", []):
        total_ms += int(scene.get("duration_ms", 0))
        scenes_out.append(
            {
                "index": scene.get("index"),
                "caption": caption_by_index.get(scene.get("caption_ref")),
                "narration_text": scene.get("narration_text"),
                "shapes": scene.get("shapes", []),
                "frames": scene.get("frames", []),
                "duration_ms": scene.get("duration_ms"),
            }
        )
    start_scene = spec.get("start_scene", 0)
    return {
        "id": spec.get("id"),
        "ku_id": spec.get("ku_id"),
        "title": spec.get("title"),
        "language": spec.get("language"),
        "captions": captions,
        "scenes": scenes_out,
        "total_duration_ms": total_ms,
        "fingerprint": _fingerprint({"id": spec.get("id"), "captions": captions, "scenes": scenes_out}),
        "provenance": spec.get("provenance"),
        "progress": {"next_scene": start_scene, "completed": []},
    }


def advance_progress(progress: Mapping[str, Any], scene_index: int, total_scenes: int) -> tuple[dict[str, Any], Optional[str]]:
    """Sequential completion only: a scene counts once the previous one did."""
    completed = list(progress.get("completed", []))
    next_scene = int(progress.get("next_scene", 0))
    if scene_index != next_scene:
        return dict(progress), "out_of_order"
    if not 0 <= scene_index < total_scenes:
        return dict(progress), "out_of_range"
    completed.append(scene_index)
    return {"next_scene": next_scene + 1, "completed": completed}, None


def video_provenance(spec: Mapping[str, Any]) -> dict[str, Any]:
    provenance = spec.get("provenance") if isinstance(spec, dict) else None
    if not isinstance(provenance, dict):
        return {"label": None, "sources": []}
    return {"label": provenance.get("label"), "sources": provenance.get("sources", [])}


def triangle_angle_sum_spec(spec_id: str = "vl-triangle-angle-sum") -> dict[str, Any]:
    """Self-written reference lesson: triangle interior angles sum to 180."""
    return {
        "id": spec_id,
        "title": {"zh": "三角形内角和", "en": "Sum of Triangle Interior Angles"},
        "language": "zh",
        "captions": [
            {"index": 0, "text": "把三角形的三个角撕下来，拼在一起。"},
            {"index": 1, "text": "三个角拼成一条直线，拼出的角是平角。"},
            {"index": 2, "text": "所以三角形三个内角的和是 180 度。"},
        ],
        "scenes": [
            {
                "index": 0,
                "caption_ref": 0,
                "narration_text": "看这个三角形，三个角分别标为 A、B、C。把它们撕下来，准备拼在一起。",
                "shapes": [
                    {"id": "tri", "type": "polygon", "pts": [[10, 90], [90, 90], [50, 20]], "color": "curve"},
                    {"id": "la", "type": "text", "at": [50, 30], "text": "A", "color": "ink"},
                    {"id": "lb", "type": "text", "at": [18, 85], "text": "B", "color": "ink"},
                    {"id": "lc", "type": "text", "at": [82, 85], "text": "C", "color": "ink"},
                ],
                "frames": [
                    {"title": "triangle", "caption": "triangle", "show": ["tri", "la", "lb", "lc"], "highlight": [], "set": {}, "duration_ms": 2000},
                    {"title": "corners", "caption": "corners", "show": ["tri", "la", "lb", "lc"], "highlight": ["la", "lb", "lc"], "set": {}, "duration_ms": 2000},
                ],
                "duration_ms": 8000,
            },
            {
                "index": 1,
                "caption_ref": 1,
                "narration_text": "把三个角拼到一条直线上，中间没有空隙，拼出的正好是一个平角。",
                "shapes": [
                    {"id": "base", "type": "segment", "from": [10, 50], "to": [90, 50], "color": "axis"},
                    {"id": "arc", "type": "text", "at": [50, 40], "text": "180", "color": "ink"},
                ],
                "frames": [
                    {"title": "line", "caption": "line", "show": ["base", "arc"], "highlight": ["arc"], "set": {}, "duration_ms": 3000},
                ],
                "duration_ms": 8000,
            },
            {
                "index": 2,
                "caption_ref": 2,
                "narration_text": "平角是 180 度，所以三角形三个内角的和是 180 度。记住这个结论，后面会反复用到。",
                "shapes": [
                    {"id": "note", "type": "text", "at": [50, 50], "text": "A + B + C = 180", "color": "ink"},
                ],
                "frames": [
                    {"title": "sum", "caption": "sum", "show": ["note"], "highlight": ["note"], "set": {}, "duration_ms": 3000},
                ],
                "duration_ms": 6000,
            },
        ],
        "provenance": {"label": "generated", "sources": []},
    }


__all__ = [
    "VideoLessonCheck",
    "VideoLessonIssue",
    "advance_progress",
    "assemble_video_lesson",
    "triangle_angle_sum_spec",
    "verify_video_lesson",
    "video_provenance",
]
