"""check_take: measure one video and return per-item results.

Item results use the take-label item shape (verdict, confidence, evidence,
note) plus ``item_id``, ``kind``, ``tool`` and ``needs``. ``needs`` names who
must still answer an ``unknown`` item: ``host-vision`` (the host's own
multimodal model looks at the review packet) or ``person-audio`` (a person
listens). Nothing here ever passes an item it did not measure.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from take_qc import expect, probe, record
from take_qc.config import load_config

ITEM_KINDS = (
    "identity",
    "hair",
    "costume",
    "prop_shape",
    "on_screen_text",
    "motion",
    "camera",
    "dialogue",
    "lipsync",
    "acting",
    "format",
)
MEASURED_KINDS = ("format", "motion", "camera")

HOST_VISION_REASON = "host vision: answer from the review packet (take-qc frames)"
PERSON_AUDIO_REASON = "host cannot hear audio; person checks"


def _tool_info() -> dict[str, Any]:
    from take_qc import __version__, vision

    comps: dict[str, str | None] = {"ffprobe": probe.tool_version("ffprobe")}
    comps.update(vision.versions())
    return {"name": "take-qc", "version": __version__, "components": comps}


def _item(
    item_id: str,
    kind: str,
    verdict: str,
    confidence: str,
    note: str,
    tool: dict[str, Any],
    measurements: dict[str, Any] | None = None,
    frame_times: list[float] | None = None,
    media: list[str] | None = None,
    needs: str | None = None,
    source: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    if frame_times:
        evidence["frame_times_s"] = [round(float(t), 3) for t in frame_times]
    if measurements:
        evidence["measurements"] = {
            k: v for k, v in measurements.items() if isinstance(v, (int, float, str, bool)) or v is None
        }
    if media:
        evidence["media"] = list(media)
    out: dict[str, Any] = {
        "item_id": item_id,
        "kind": kind,
        "verdict": verdict,
        "confidence": confidence,
        "evidence": evidence,
        "note": note,
        "tool": {"name": tool["name"], "version": tool["version"]},
    }
    if needs:
        out["needs"] = needs
    if source:
        out["source"] = source
    if text:
        out["text"] = text
    return out


def _format_item(pr: probe.Probe, ex: expect.Expectations, cfg: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    f = cfg["format"]
    problems: list[str] = []
    notes: list[str] = []
    m: dict[str, Any] = {k: v for k, v in pr.as_dict().items() if v is not None}
    if ex.frames is not None and pr.frames is not None:
        m["expected_frames"] = ex.frames
        if abs(pr.frames - ex.frames) > f["frames_tolerance"]:
            problems.append(f"{pr.frames} frames, expected {ex.frames}")
    elif ex.duration_s is not None and pr.duration_s is not None:
        m["expected_duration_s"] = ex.duration_s
        if abs(pr.duration_s - ex.duration_s) > f["duration_tolerance_s"]:
            problems.append(f"{pr.duration_s:.3f} s, expected {ex.duration_s} s +- {f['duration_tolerance_s']} s")
    for key in ("width", "height"):
        want = getattr(ex, key)
        if want is not None and getattr(pr, key) != want:
            problems.append(f"{key} {getattr(pr, key)}, expected {want}")
    if ex.fps is not None and pr.fps is not None and abs(pr.fps - ex.fps) > f["fps_tolerance"]:
        problems.append(f"{pr.fps} fps, expected {ex.fps}")
    if ex.audio and not pr.has_audio:
        problems.append("no audio stream")
    if ex.dialogue and pr.has_audio:
        mean, mx = pr.mean_volume_db, pr.max_volume_db
        if (mean is not None and mean <= f["silence_mean_db"]) or (mx is not None and mx <= f["silence_max_db"]):
            problems.append(
                f"silent audio (mean {mean} dB, max {mx} dB) where {len(ex.dialogue)} dialogue line(s) are expected"
            )
    if pr.has_audio and pr.mean_volume_db is not None and pr.mean_volume_db <= f["quiet_mean_db"]:
        notes.append(f"quiet mix (mean {pr.mean_volume_db} dB)")
    desc = f"{pr.width}x{pr.height} @ {pr.fps} fps, {pr.frames} frames ({pr.duration_s} s), audio: {pr.has_audio}"
    if problems:
        return _item("format", "format", "flag", "high", "; ".join(problems) + f". [{desc}]", tool, m)
    return _item("format", "format", "pass", "high", "; ".join([desc, *notes]), tool, m)


def _vision_unknown(kind: str, reason: str, tool: dict[str, Any]) -> dict[str, Any]:
    return _item(kind, kind, "unknown", "low", reason, tool)


def _camera_item(
    sig: Any, transitions: list[Any], ex: expect.Expectations, cfg: dict[str, Any], tool: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    from take_qc import measure

    c = cfg["camera"]
    summary = measure.camera_summary(sig, transitions, cfg)
    plan = expect.camera_plan(ex.camera_text, cfg)
    observed = measure.observed_components(summary, cfg)
    summary.update(
        {
            "planned_classes": ",".join(plan.classes),
            "planned_from_default": plan.from_default,
            "observed_components": ",".join(observed) or "none",
            "transitions": len(transitions),
            "planned_shots": ex.shots,
        }
    )
    problems: list[str] = []
    times: list[float] = []
    confidence = "medium"
    unplanned = list(transitions) if len(transitions) > ex.shots - 1 else []
    for tr in unplanned:
        label = {
            "cut": "hard cut",
            "dissolve": "dissolve/morph",
            "transition": "gradual transition (cut under motion or dissolve)",
        }[tr.kind]
        when = f"{tr.start_s:.3f} s" if tr.kind == "cut" else f"{tr.start_s:.2f}-{tr.end_s:.2f} s"
        problems.append(f"{label} at {when} in a take planned as {ex.shots} continuous shot(s)")
        times.extend([tr.start_s, tr.end_s] if tr.end_s != tr.start_s else [tr.start_s])
        if tr.kind == "cut":
            confidence = "high"
    usable = summary["usable_pair_fraction"]
    if usable < c["min_usable_fraction"] and not problems:
        note = f"global motion unreliable (usable pairs {usable:.0%})"
        return _item("camera", "camera", "unknown", "low", note, tool, summary), summary
    for comp in observed:
        if comp not in plan.allowed:
            name = {
                "zoom_in": "push-in/zoom-in",
                "zoom_out": "pull-back/zoom-out",
                "pan": "pan/track",
                "tilt": "tilt/vertical move",
                "roll": "roll",
            }[comp]
            plan_name = "/".join(plan.classes) + (" (no move named; default)" if plan.from_default else "")
            problems.append(f"unplanned {name} (planned: {plan_name})")
            if comp == "zoom_out":
                times.extend(summary["zoom_out_peak_window_s"])
            elif comp == "zoom_in":
                times.extend(summary["zoom_in_peak_window_s"])
    mins = c["expected_move_min"]
    for comp in sorted(plan.required):
        got = {
            "zoom_in": summary["zoom_total_log"],
            "pan": abs(summary["pan_total_frac_width"]),
            "tilt": abs(summary["tilt_total_frac_height"]),
        }.get(comp, 0.0)
        if got < mins:
            problems.append(f"planned {comp.replace('_', '-')} not measured ({got:.3f} < {mins})")
    tilt = summary["tilt_total_frac_height"]
    # A following move (track, handheld) goes where the subject goes; only a
    # pure tilt/crane plan fixes the vertical direction.
    following = {"track", "handheld"} & set(plan.classes)
    if plan.vertical_sign and not following and abs(tilt) >= mins and (tilt > 0) != (plan.vertical_sign > 0):
        problems.append("vertical move goes the opposite way to the plan")
    if problems:
        return _item(
            "camera", "camera", "flag", confidence, "; ".join(problems), tool, summary, sorted(set(times))
        ), summary
    return _item(
        "camera",
        "camera",
        "pass",
        "medium",
        f"observed {summary['observed_components']}; planned {'/'.join(plan.classes)}",
        tool,
        summary,
    ), summary


def _motion_item(
    sig: Any, transitions: list[Any], cfg: dict[str, Any], tool: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    from take_qc import measure

    mcfg = cfg["motion"]
    s = measure.motion_summary(sig, transitions)
    problems = []
    times = []
    if s["whole_p95_of_p95"] >= mcfg["whole_p95_flag"]:
        problems.append(
            f"whole-frame motion p95 {s['whole_p95_of_p95']:.2f} >= {mcfg['whole_p95_flag']} (frame widths/s)"
        )
        times.append(s["peak_whole_t_s"])
    if "region_residual_p95" in s and s["region_residual_p95"] >= mcfg["region_residual_p95_flag"]:
        problems.append(
            f"local motion in region p95 {s['region_residual_p95']:.2f} >= {mcfg['region_residual_p95_flag']}"
            " (frame widths/s, camera removed)"
        )
        times.append(s["peak_region_t_s"])
    if problems:
        return _item("motion", "motion", "flag", "medium", "; ".join(problems), tool, s, times), s
    return _item("motion", "motion", "pass", "medium", "motion below thresholds", tool, s), s


def check_take(
    video: str,
    checklist: dict[str, Any] | None = None,
    direction: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    keep_signals: bool = False,
) -> dict[str, Any]:
    from take_qc import measure, vision

    cfg = cfg or load_config()
    started = time.perf_counter()
    tool = _tool_info()
    ex = expect.build(checklist, direction, cfg)
    pr = probe.probe_video(video)
    items: dict[str, dict[str, Any]] = {"format": _format_item(pr, ex, cfg, tool)}
    result: dict[str, Any] = {
        "schema": "take-qc/result/v1",
        "video": video,
        "checked_at": _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat(),
        "tool": tool,
        "probe": pr.as_dict(),
        "expectations": ex.as_dict(),
    }
    transitions: list[Any] = []
    if vision.available() and pr.width and pr.height and pr.fps:
        frames = vision.decode_frames(
            video, cfg["analysis"]["width"], pr.width, pr.height, cfg["analysis"]["max_seconds"]
        )
        sig = vision.pair_signals(frames, pr.fps, ex.motion_region, cfg["cuts"]["window_frames"])
        transitions = measure.detect_transitions(sig, cfg)
        items["camera"], result["camera"] = _camera_item(sig, transitions, ex, cfg, tool)
        items["motion"], result["motion"] = _motion_item(sig, transitions, cfg, tool)
        result["transitions"] = [tr.as_dict() for tr in transitions]
        if keep_signals:
            result["_signals"] = sig
    else:
        reason = "needs the optional 'vision' extra (numpy + opencv) to measure"
        items["camera"] = _vision_unknown("camera", reason, tool)
        items["motion"] = _vision_unknown("motion", reason, tool)
        result["transitions"] = None

    hint_times = sorted({t for tr in result.get("transitions") or [] for t in (tr["start_s"], tr["end_s"])})
    for kind in expect.VISUAL_KINDS:
        it = _vision_unknown(kind, HOST_VISION_REASON, tool)
        it["needs"] = "host-vision"
        if kind == "identity" and hint_times:
            it["evidence"]["frame_times_s"] = hint_times
            it["note"] += "; detected transition times are listed as focus times"
        items[kind] = it
    for kind in expect.AUDIO_KINDS:
        it = _vision_unknown(kind, PERSON_AUDIO_REASON, tool)
        it["needs"] = "person-audio"
        if pr.has_audio:
            it["evidence"]["measurements"] = {
                "mean_volume_db": pr.mean_volume_db,
                "max_volume_db": pr.max_volume_db,
                "expected_lines": len(ex.dialogue),
            }
        items[kind] = it

    ordered = [items[k] for k in ITEM_KINDS]
    # Checklist items with their own ids become extra entries of their kind; an
    # item whose id is the kind itself (e.g. "hair") annotates that base item.
    for ci in ex.items:
        kind = ci.get("kind")
        if kind not in ITEM_KINDS or not ci.get("id"):
            continue
        if str(ci["id"]) == kind:
            if ci.get("source"):
                items[kind]["source"] = ci["source"]
            if ci.get("text"):
                items[kind]["text"] = ci["text"]
            continue
        base = dict(items[kind])
        base["evidence"] = dict(base.get("evidence", {}))
        base["item_id"] = str(ci["id"])
        if ci.get("source"):
            base["source"] = ci["source"]
        if ci.get("text"):
            base["text"] = ci["text"]
        ordered.append(base)
    result["items"] = ordered
    result["timing_s"] = round(time.perf_counter() - started, 3)
    result["self_check"] = record.self_check_record(result)
    return result
