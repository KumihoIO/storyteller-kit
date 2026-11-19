"""Decisions over pair signals: transitions (cuts, dissolves), camera motion
components, and subject motion. Pure numpy; every threshold comes from config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]


@dataclass
class Transition:
    kind: str  # "cut" | "dissolve" | "transition"
    start_s: float
    end_s: float
    first_pair: int
    last_pair: int
    score: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            **{k: round(v, 4) for k, v in self.score.items()},
        }


def _local_median(u: Any, gap: int = 3, span: int = 24) -> Any:
    n = len(u)
    out = np.empty(n)
    whole = float(np.median(u)) if n else 0.0
    for i in range(n):
        nb = np.concatenate([u[max(0, i - span) : max(0, i - gap)], u[i + gap + 1 : i + gap + 1 + span]])
        out[i] = float(np.median(nb)) if len(nb) >= 4 else whole
    return np.maximum(out, 1e-4)


def detect_transitions(sig: Any, cfg: dict[str, Any]) -> list[Transition]:
    """Hard cuts: one pair whose colour histogram jumps and whose change the dense
    flow cannot explain. Gradual transitions: a run of pairs with unexplained
    change; a dissolve/morph when motion is low relative to that change, else a
    "transition" (a cut hidden by fast motion, or a dissolve the flow reads as
    motion) when the content on either side of the run differs strongly."""
    c = cfg["cuts"]
    u, hd, hf, mag = sig.unexplained, sig.hist_d, sig.hist_far, sig.mag
    n = len(u)
    if n == 0:
        return []
    lm = _local_median(u)
    ratio = u / lm
    out: list[Transition] = []
    hard = set()
    for i in range(n):
        # A hard cut is one isolated jump; a run of jumps is a gradual transition.
        neighbours = max(hd[i - 1] if i > 0 else 0.0, hd[i + 1] if i + 1 < n else 0.0)
        if hd[i] >= c["hard_hist_min"] and ratio[i] >= c["hard_ratio_min"] and neighbours < 0.5 * hd[i]:
            hard.add(i)
            out.append(
                Transition(
                    "cut",
                    float(sig.t[i]),
                    float(sig.t[i]),
                    i,
                    i,
                    {"hist_d": float(hd[i]), "unexplained_ratio": float(ratio[i])},
                )
            )
    over = ratio >= c["run_ratio_min"]
    runs: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate([*over.tolist(), False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    for a, b in runs:
        if any(a <= h <= b for h in hard):
            continue
        length = b - a + 1
        hf_max = float(hf[a : b + 1].max())
        u_per_motion = float(u[a : b + 1].mean() / max(float(mag[a : b + 1].mean()), 1e-4))
        score = {
            "pairs": float(length),
            "hist_far": hf_max,
            "unexplained_ratio": float(ratio[a : b + 1].max()),
            "unexplained_per_motion": u_per_motion,
        }
        t0 = float(sig.t[a]) - 1.0 / sig.fps
        t1 = float(sig.t[b])
        if (
            length >= c["dissolve_min_pairs"]
            and u_per_motion >= c["dissolve_unexplained_per_motion"]
            and hf_max >= c["dissolve_hist_far_min"]
        ):
            out.append(Transition("dissolve", max(t0, 0.0), t1, a, b, score))
        elif length >= c["transition_min_pairs"] and hf_max >= c["transition_hist_far_min"]:
            out.append(Transition("transition", max(t0, 0.0), t1, a, b, score))
    out.sort(key=lambda tr: tr.start_s)
    return out


def _excluded_pairs(n: int, transitions: list[Transition]) -> Any:
    mask = np.zeros(n, dtype=bool)
    for tr in transitions:
        mask[tr.first_pair : tr.last_pair + 1] = True
    return mask


def _window_extremes(x: Any, w: int) -> tuple[float, int, float, int]:
    if len(x) == 0:
        return 0.0, 0, 0.0, 0
    if len(x) < w:
        s = float(x.sum())
        return s, 0, s, 0
    conv = np.convolve(x, np.ones(w), "valid")
    return float(conv.max()), int(conv.argmax()), float(conv.min()), int(conv.argmin())


def camera_summary(sig: Any, transitions: list[Transition], cfg: dict[str, Any]) -> dict[str, Any]:
    c = cfg["camera"]
    n = len(sig.t)
    ok = (sig.inliers >= c["min_inlier_ratio"]) & ~_excluded_pairs(n, transitions)
    zoom = np.where(ok, sig.log_scale, 0.0)
    pan = np.where(ok, sig.tx, 0.0)
    tilt = np.where(ok, sig.ty, 0.0)
    roll = np.where(ok, sig.rot_deg, 0.0)
    w = max(1, int(round(c["zoom_window_s"] * sig.fps)))
    zmax, zmax_i, zmin, zmin_i = _window_extremes(zoom, w)
    span = w / sig.fps

    def t_at(i: int) -> float:
        return float(sig.t[min(i, n - 1)]) if n else 0.0

    return {
        "usable_pair_fraction": round(float(ok.mean()) if n else 0.0, 3),
        "zoom_total_log": round(float(zoom.sum()), 4),
        "pan_total_frac_width": round(float(pan.sum()), 4),
        "tilt_total_frac_height": round(float(tilt.sum()), 4),
        "roll_total_deg": round(float(roll.sum()), 3),
        "zoom_in_peak_window_log": round(zmax, 4),
        "zoom_in_peak_window_s": [round(t_at(zmax_i) - 1 / sig.fps, 3), round(t_at(zmax_i) - 1 / sig.fps + span, 3)],
        "zoom_out_peak_window_log": round(zmin, 4),
        "zoom_out_peak_window_s": [round(t_at(zmin_i) - 1 / sig.fps, 3), round(t_at(zmin_i) - 1 / sig.fps + span, 3)],
    }


def observed_components(summary: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    c = cfg["camera"]
    out = []
    if summary["zoom_total_log"] >= c["zoom_in_total_flag"]:
        out.append("zoom_in")
    if summary["zoom_total_log"] <= -c["zoom_out_total_flag"]:
        out.append("zoom_out")
    if abs(summary["pan_total_frac_width"]) >= c["pan_total_flag"]:
        out.append("pan")
    if abs(summary["tilt_total_frac_height"]) >= c["tilt_total_flag"]:
        out.append("tilt")
    if abs(summary["roll_total_deg"]) >= c["roll_total_flag_deg"]:
        out.append("roll")
    return out


def motion_summary(sig: Any, transitions: list[Transition]) -> dict[str, Any]:
    n = len(sig.t)
    keep = ~_excluded_pairs(n, transitions)
    if not keep.any():
        keep = np.ones(n, dtype=bool)
    p95 = sig.mag_p95[keep]
    resid = sig.resid[keep]
    out: dict[str, Any] = {
        "whole_p95_of_p95": round(float(np.percentile(p95, 95)), 4),
        "whole_mean": round(float(sig.mag[keep].mean()), 4),
        "residual_mean": round(float(resid.mean()), 4),
        "residual_p95": round(float(np.percentile(resid, 95)), 4),
    }
    idx = np.arange(n)[keep]
    out["peak_whole_t_s"] = round(float(sig.t[idx[int(np.argmax(p95))]]), 3)
    if sig.region_resid is not None:
        rr = sig.region_resid[keep]
        out["region_residual_mean"] = round(float(rr.mean()), 4)
        out["region_residual_p95"] = round(float(np.percentile(rr, 95)), 4)
        out["peak_region_t_s"] = round(float(sig.t[idx[int(np.argmax(rr))]]), 3)
    return out
