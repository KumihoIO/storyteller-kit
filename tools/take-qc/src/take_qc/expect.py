"""What a take was supposed to be, from a checklist and/or a Direction document.

Checklist (all keys optional)::

    {
      "expected": {"duration_s": 5.0, "frames": 124, "width": 1920, "height": 1088,
                   "fps": 24, "audio": true},
      "dialogue": ["line one", "line two"],
      "camera": {"movement": "slow push-in"},
      "shots": 1,
      "motion_region": [0.3, 0.0, 0.7, 0.4] | "upper_third" | "whole" | null,
      "items": [{"id": "hair-1", "kind": "hair", "text": "half-up, never braided",
                 "source": "server", "references": ["/path/costume_sheet.png"],
                 "boxes": [{"label": "head", "box": [0.3, 0.0, 0.7, 0.4]}]}]
    }

Direction: ``camera.movement`` (and per-shot ``shots[].camera.movement``),
the number of ``shots`` and ``audio.dialogue[].line`` are read. Checklist
values win over Direction values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VISUAL_KINDS = ("identity", "hair", "costume", "prop_shape", "on_screen_text", "acting")
AUDIO_KINDS = ("dialogue", "lipsync")


@dataclass
class Expectations:
    duration_s: float | None = None
    frames: int | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    audio: bool | None = None
    dialogue: list[str] = field(default_factory=list)
    camera_text: str = ""
    shots: int = 1
    motion_region: list[float] | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "frames": self.frames,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "audio": self.audio,
            "dialogue_lines": len(self.dialogue),
            "camera_text": self.camera_text,
            "shots": self.shots,
            "motion_region": self.motion_region,
        }


def _region(value: Any, default: str | None) -> list[float] | None:
    if value is None:
        value = default
    if value in (None, "whole", ""):
        return None
    if value == "upper_third":
        return [0.0, 0.0, 1.0, 1.0 / 3.0]
    if isinstance(value, list) and len(value) == 4:
        return [float(v) for v in value]
    raise ValueError(f"motion_region must be a 4-number box, 'upper_third', 'whole' or null, not {value!r}")


def build(checklist: dict[str, Any] | None, direction: dict[str, Any] | None, cfg: dict[str, Any]) -> Expectations:
    checklist = checklist or {}
    direction = direction or {}
    ex = Expectations()

    shots = direction.get("shots") or []
    if shots:
        ex.shots = len(shots)
    moves = [str((direction.get("camera") or {}).get("movement") or "")]
    for shot in shots:
        cam = shot.get("camera") if isinstance(shot, dict) else None
        if isinstance(cam, dict) and cam.get("movement"):
            moves.append(str(cam["movement"]))
    ex.camera_text = "; ".join(m for m in moves if m)
    lines = (direction.get("audio") or {}).get("dialogue") or []
    ex.dialogue = [str(d.get("line", "")) for d in lines if isinstance(d, dict) and d.get("line")]

    exp = checklist.get("expected") or {}
    for key in ("duration_s", "frames", "width", "height", "fps", "audio"):
        if key in exp and exp[key] is not None:
            setattr(ex, key, exp[key])
    if "dialogue" in checklist:
        ex.dialogue = [str(x) for x in checklist["dialogue"] or []]
    cam = checklist.get("camera") or {}
    if cam.get("movement"):
        ex.camera_text = str(cam["movement"])
    if checklist.get("shots"):
        ex.shots = int(checklist["shots"])
    ex.motion_region = _region(checklist.get("motion_region", None), cfg["motion"].get("default_region"))
    ex.items = list(checklist.get("items") or [])
    if ex.audio is None and ex.dialogue:
        ex.audio = True
    return ex


@dataclass
class CameraPlan:
    classes: list[str]
    allowed: set[str]
    required: set[str]
    vertical_sign: int  # +1 content moves down (tilt/crane up), -1 up, 0 unknown
    from_default: bool


def camera_plan(text: str, cfg: dict[str, Any]) -> CameraPlan:
    c = cfg["camera"]
    low = f" {text.lower()} "
    classes = [name for name, words in c["move_keywords"] if any(w in low for w in words)]
    from_default = not classes
    if from_default:
        classes = [c["default_expected_move"]]
    allowed: set[str] = set()
    required: set[str] = set()
    for name in classes:
        allowed.update(c["allowed_components"].get(name, []))
        required.update(c["required_components"].get(name, []))
    if "static" in classes and len(classes) > 1:
        # "static" next to a real move word means the rest of the frame holds; the move wins.
        classes = [k for k in classes if k != "static"]
    up = any(w in low for w in c["vertical_up_words"])
    down = any(w in low for w in c["vertical_down_words"])
    sign = 1 if up and not down else (-1 if down and not up else 0)
    return CameraPlan(classes, allowed, required, sign, from_default)
