"""Review packet: what the host's own multimodal model looks at.

Keyframes (evenly spaced, plus frames around detected transitions and peak
motion), a timestamped contact sheet, optional crops from checklist boxes,
and ``packet.json`` listing per visual item the frames, the reference images
and the exact question to answer. take-qc never judges these items itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

_ANSWER = " Answer pass/flag/unknown with evidence frame time."
QUESTIONS = {
    "identity": "Does each person match the reference image(s)?" + _ANSWER,
    "hair": "Does each person's hair match the reference?" + _ANSWER,
    "costume": "Does each person's costume match the reference?" + _ANSWER,
    "prop_shape": "Do the props and vehicles match the reference?" + _ANSWER,
    "on_screen_text": "Does any visible text match the reference or the allowlist?" + _ANSWER,
    "acting": "Does the performance match the plan?" + _ANSWER,
}
PLAN_HINT = " Compare with the plan (packet 'plan')."
PLAN_KINDS = ("acting", "prop_shape")

ANSWER_FORMAT = {
    "item_id": "<item_id from this packet>",
    "verdict": "pass | flag | unknown",
    "confidence": "high | medium | low",
    "evidence": {"frame_times_s": ["<seconds>"], "boxes": [{"t_s": 0.0, "box": [0, 0, 1, 1], "label": "<what>"}]},
    "note": "<one or two sentences: what you saw and where>",
    "tool": {"name": "host-vision:<model id>", "version": "<optional>"},
    "recalled": ["<optional kref>"],
}

INSTRUCTIONS = (
    "Answer each item from the frames and the contact sheet, next to the item's reference_images (viewable "
    "copies of its references, same order). Unknown never counts as a pass. Cite the frame time(s) relied on. "
    "A native-resolution crop: 'take-qc crop <video> --t <s> --box x0 y0 x1 y1 --out <jpg>'. "
    "Save the answers as a JSON list and run: take-qc merge <result.json> <answers.json> --out <final.json>."
)


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found on PATH")
    return path


def _checklist_times(checklist: dict[str, Any] | None) -> list[tuple[float, str]]:
    """Times a checklist asks to see: ``items[].times_s`` (e.g. a planned beat or line)."""
    out = []
    for ci in (checklist or {}).get("items") or []:
        for t in ci.get("times_s") or []:
            out.append((float(t), f"checklist {ci.get('id', ci.get('kind', ''))}"))
    return out


def pick_times(
    result: dict[str, Any], cfg: dict[str, Any], checklist: dict[str, Any] | None = None
) -> list[tuple[float, str]]:
    fc = cfg["frames"]
    pr = result["probe"]
    duration = float(pr.get("duration_s") or 0.0)
    fps = float(pr.get("fps") or 24.0)
    last = max(0.0, duration - 1.0 / fps)
    n = max(2, int(fc["even_count"]))
    picks: list[tuple[float, str]] = [(round(last * i / (n - 1), 3), "even") for i in range(n)]
    for tr in result.get("transitions") or []:
        a, b = tr["start_s"], tr["end_s"]
        picks += [(max(0.0, a - 2.0 / fps), f"before {tr['kind']}"), (min(last, b + 1.0 / fps), f"after {tr['kind']}")]
        if b - a > 2.0 / fps:
            picks.append(((a + b) / 2.0, f"inside {tr['kind']}"))
    motion = result.get("motion") or {}
    for key, why in (("peak_whole_t_s", "peak motion"), ("peak_region_t_s", "peak region motion")):
        if motion.get(key) is not None:
            picks.append((float(motion[key]), why))
    cam = result.get("camera") or {}
    obs = str(cam.get("observed_components", ""))
    if "zoom_out" in obs and cam.get("zoom_out_peak_window_s"):
        w = cam["zoom_out_peak_window_s"]
        picks += [(max(0.0, w[0]), "zoom-out start"), (min(last, w[1]), "zoom-out end")]
    picks += _checklist_times(checklist)
    picks.sort()
    merged: list[tuple[float, str]] = []
    for t, why in picks:
        t = round(min(max(t, 0.0), last), 3)
        if merged and t - merged[-1][0] < fc["min_gap_s"]:
            if why != "even" and why not in merged[-1][1]:
                merged[-1] = (merged[-1][0], merged[-1][1] + ", " + why)
            continue
        merged.append((t, why))
    return merged


def extract_frame(video: str, t: float, out: Path, max_width: int, quality: int) -> None:
    q = max(2, min(31, round(31 - quality * 29 / 100)))
    cmd = [
        _ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
        "-vf", f"scale='min({max_width},iw)':-2", "-q:v", str(q), str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)


def _contact_sheet(frames: list[dict[str, Any]], out: Path, cfg: dict[str, Any]) -> bool:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False
    fc = cfg["frames"]
    tw = int(fc["sheet_thumb_width"])
    cols = int(fc["sheet_columns"])
    thumbs = []
    for fr in frames:
        img = cv2.imread(fr["path"])
        if img is None:
            continue
        h = int(round(img.shape[0] * tw / img.shape[1]))
        img = cv2.resize(img, (tw, h), interpolation=cv2.INTER_AREA)
        label = f"{fr['t_s']:.2f}s {fr['reasons']}"[:48]
        cv2.rectangle(img, (0, h - 24), (tw, h), (0, 0, 0), -1)
        cv2.putText(img, label, (6, h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        thumbs.append(img)
    if not thumbs:
        return False
    th = max(t.shape[0] for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = np.zeros((rows * (th + 4), cols * (tw + 4), 3), dtype=np.uint8)
    for i, img in enumerate(thumbs):
        r, c = divmod(i, cols)
        y, x = r * (th + 4), c * (tw + 4)
        sheet[y : y + img.shape[0], x : x + tw] = img
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, int(fc["jpeg_quality"])])
    return True


def crop_from_video(video: str, t: float, box: list[float], out: str | Path, scale: float = 2.0) -> Path:
    """A crop of one frame at the video's native resolution (keyframes are downscaled), optionally enlarged."""
    x0, y0, x1, y1 = (float(v) for v in box)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f"box must be normalized [x0, y0, x1, y1] with x0 < x1, y0 < y1: {box}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"crop=iw*{x1 - x0:.4f}:ih*{y1 - y0:.4f}:iw*{x0:.4f}:ih*{y0:.4f}"
    if scale and scale != 1.0:
        vf += f",scale=iw*{scale:g}:-2:flags=lanczos"
    cmd = [
        _ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
        "-vf", vf, "-q:v", "2", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def reference_image(src: str, out_dir: Path, max_side: int, cache: dict[str, str]) -> str | None:
    """A viewable copy of a reference (sheets are often 10-20 MB PNGs), long side <= ``max_side``."""
    if src in cache:
        return cache[src]
    if not Path(src).is_file():
        cache[src] = None  # type: ignore[assignment]
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"r{len(cache):02d}_{Path(src).stem}.jpg"
    cmd = [
        _ffmpeg(), "-v", "error", "-y", "-i", src, "-frames:v", "1",
        "-vf", f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease", "-q:v", "3", str(out),
    ]  # fmt: skip
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        cache[src] = None  # type: ignore[assignment]
        return None
    cache[src] = str(out)
    return str(out)


def _crop(src: str, box: list[float], out: Path) -> bool:
    try:
        import cv2
    except ImportError:
        return False
    img = cv2.imread(src)
    if img is None:
        return False
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(round(v * s)) for v, s in zip(box, (w, h, w, h), strict=True))
    if x1 <= x0 or y1 <= y0:
        return False
    cv2.imwrite(str(out), img[y0:y1, x0:x1])
    return True


def _visual_items(result: dict[str, Any], checklist: dict[str, Any] | None) -> list[dict[str, Any]]:
    listed = {ci["id"]: ci for ci in (checklist or {}).get("items", []) if ci.get("id")}
    out = []
    for it in result["items"]:
        if it.get("needs") != "host-vision":
            continue
        ci = listed.get(it["item_id"], {})
        out.append({"item": it, "check": ci})
    return out


def build_packet(
    result: dict[str, Any], out_dir: str | Path, cfg: dict[str, Any], checklist: dict[str, Any] | None = None
) -> dict[str, Any]:
    out = Path(out_dir).resolve()
    (out / "frames").mkdir(parents=True, exist_ok=True)
    fc = cfg["frames"]
    video = result["video"]
    frames = []
    for t, why in pick_times(result, cfg, checklist):
        path = out / "frames" / f"t{t:07.3f}.jpg"
        extract_frame(video, t, path, int(fc["max_width"]), int(fc["jpeg_quality"]))
        frames.append({"t_s": t, "path": str(path), "reasons": why})
    sheet = out / "contact_sheet.jpg"
    has_sheet = _contact_sheet(frames, sheet, cfg)

    checklist = checklist or {}
    shared_refs = list(checklist.get("references") or [])
    plan = str(checklist.get("plan") or "")
    ref_cache: dict[str, str] = {}
    max_side = int(fc.get("reference_max_side", 1024))
    items = []
    for entry in _visual_items(result, checklist):
        it, ci = entry["item"], entry["check"]
        kind = it["kind"]
        question = QUESTIONS.get(kind, "Does the take satisfy this item?")
        if ci.get("text"):
            question += f" Checklist: {ci['text']}"
        if plan and kind in PLAN_KINDS:
            question += PLAN_HINT
        if kind == "on_screen_text" and checklist.get("on_screen_text_allowlist") is not None:
            question += f" Allowlist: {json.dumps(checklist['on_screen_text_allowlist'], ensure_ascii=False)}"
        crops = []
        for b in ci.get("boxes") or []:
            for fr in frames:
                cp = out / "crops" / f"{it['item_id']}_{b.get('label', 'box')}_t{fr['t_s']:07.3f}.jpg"
                cp.parent.mkdir(exist_ok=True)
                if _crop(fr["path"], b["box"], cp):
                    crops.append({"t_s": fr["t_s"], "label": b.get("label", ""), "path": str(cp)})
        focus = [t for t in (it.get("evidence") or {}).get("frame_times_s", [])]
        focus += [float(t) for t in ci.get("times_s") or []]
        refs = list(ci.get("references") or shared_refs)
        items.append(
            {
                "item_id": it["item_id"],
                "kind": kind,
                "source": ci.get("source", it.get("source", "server")),
                "question": question,
                "references": refs,
                "reference_images": [reference_image(r, out / "refs", max_side, ref_cache) for r in refs],
                "frames": [fr["path"] for fr in frames],
                "focus_times_s": sorted(set(focus)),
                "crops": crops,
            }
        )
    packet = {
        "schema": "take-qc/review-packet/v1",
        "video": video,
        "duration_s": result["probe"].get("duration_s"),
        "plan": plan,
        "contact_sheet": str(sheet) if has_sheet else None,
        "frames": frames,
        "transitions": result.get("transitions") or [],
        "measured": {
            it["item_id"]: {"verdict": it["verdict"], "note": it["note"]}
            for it in result["items"]
            if it["kind"] in ("format", "motion", "camera")
        },
        "items": items,
        "instructions": INSTRUCTIONS,
        "answer_format": ANSWER_FORMAT,
        "not_for_host_vision": [it["item_id"] for it in result["items"] if it.get("needs") == "person-audio"],
    }
    (out / "packet.json").write_text(
        json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return packet


__all__ = ["ANSWER_FORMAT", "QUESTIONS", "build_packet", "crop_from_video", "pick_times", "reference_image"]
