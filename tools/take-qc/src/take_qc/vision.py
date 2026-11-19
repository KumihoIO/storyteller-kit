"""Per-frame-pair signals from decoded frames (needs numpy + OpenCV).

Frames are decoded by ffmpeg at a small analysis width, so the cost does not
grow with the source resolution. Every signal is resolution independent:
translations are fractions of the frame width/height, magnitudes are
fractions of the frame width per second.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

try:  # optional extra
    import numpy as np
except ImportError:  # pragma: no cover - exercised when the extra is absent
    np = None  # type: ignore[assignment]
try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]


def available() -> bool:
    return np is not None and cv2 is not None


def versions() -> dict[str, str]:
    out: dict[str, str] = {}
    if np is not None:
        out["numpy"] = np.__version__
    if cv2 is not None:
        out["opencv"] = cv2.__version__
    return out


def decode_frames(path: str, width: int, src_w: int, src_h: int, max_seconds: float = 0) -> Any:
    """Decode every frame as RGB at ``width`` px wide. Returns an (N, H, W, 3) uint8 array."""
    assert np is not None
    height = max(2, int(round(width * src_h / src_w / 2)) * 2)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = [ffmpeg, "-v", "error", "-i", path]
    if max_seconds and max_seconds > 0:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-an", "-vf", f"scale={width}:{height}:flags=area", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frame_bytes = width * height * 3
    n = len(raw) // frame_bytes
    return np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8).reshape(n, height, width, 3)


@dataclass
class PairSignals:
    """Arrays of length N-1; index i describes the change from frame i to i+1."""

    fps: float
    width: int
    height: int
    t: Any  # time of frame i+1 (s): where a cut between i and i+1 lands
    hist_d: Any  # Bhattacharyya distance of HSV histograms, 0..1
    unexplained: Any  # mean |f_i - warp(f_i+1, flow)| / 255 after dense-flow compensation
    tx: Any  # global horizontal shift, fraction of width per frame (+ = content moves right)
    ty: Any  # global vertical shift, fraction of height per frame (+ = content moves down)
    log_scale: Any  # ln(scale) per frame (+ = content grows: push-in / zoom-in)
    rot_deg: Any  # roll per frame (deg)
    inliers: Any  # RANSAC inlier ratio of the global model, 0..1
    mag: Any  # mean |flow|, fraction of width per second
    mag_p95: Any  # 95th percentile |flow|, fraction of width per second
    resid: Any  # mean |flow - global|, fraction of width per second
    region_resid: Any | None  # same, inside the motion region
    region_mag: Any | None
    hist_far: Any  # histogram distance between frame i-k and i+1+k (k = window)


def _hist(frame_rgb: Any) -> Any:
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def _box_slices(box: list[float] | None, h: int, w: int) -> tuple[slice, slice] | None:
    if not box:
        return None
    x0, y0, x1, y1 = box
    r0, r1 = int(round(y0 * h)), max(int(round(y1 * h)), int(round(y0 * h)) + 1)
    c0, c1 = int(round(x0 * w)), max(int(round(x1 * w)), int(round(x0 * w)) + 1)
    return slice(r0, r1), slice(c0, c1)


def pair_signals(frames: Any, fps: float, region: list[float] | None, window: int) -> PairSignals:
    assert np is not None and cv2 is not None
    n, h, w, _ = frames.shape
    m = max(n - 1, 0)
    gray = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in frames]
    hists = [_hist(f) for f in frames]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    step = 8
    gy, gx = np.mgrid[step // 2 : h : step, step // 2 : w : step]
    grid = np.stack([gx.ravel(), gy.ravel()], axis=1).astype(np.float32)
    center = np.array([w / 2.0, h / 2.0], dtype=np.float64)
    reg = _box_slices(region, h, w)

    out = {k: np.zeros(m) for k in ("hist_d", "unexplained", "tx", "ty", "ls", "rot", "inl", "mag", "p95", "resid")}
    region_resid = np.zeros(m) if reg else None
    region_mag = np.zeros(m) if reg else None
    per_s = fps / w  # px/frame -> fraction of width per second

    for i in range(m):
        g0, g1 = gray[i], gray[i + 1]
        out["hist_d"][i] = cv2.compareHist(hists[i], hists[i + 1], cv2.HISTCMP_BHATTACHARYYA)
        flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        warped = cv2.remap(g1, xs + flow[..., 0], ys + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out["unexplained"][i] = float(np.mean(np.abs(g0.astype(np.float32) - warped))) / 255.0
        fmag = np.hypot(flow[..., 0], flow[..., 1])
        out["mag"][i] = float(fmag.mean()) * per_s
        out["p95"][i] = float(np.percentile(fmag, 95)) * per_s

        # Flat regions (sky, bokeh, plain walls) report ~zero flow whatever the
        # camera does; fit the global model on textured points only.
        eig = cv2.cornerMinEigenVal(g0, 7)[grid[:, 1].astype(int), grid[:, 0].astype(int)]
        textured = eig >= max(float(eig.max()) * 0.05, 1e-6)
        pts = grid[textured] if int(textured.sum()) >= 30 else grid
        dst = pts + flow[pts[:, 1].astype(int), pts[:, 0].astype(int)]
        mat, inl = cv2.estimateAffinePartial2D(pts, dst, method=cv2.RANSAC, ransacReprojThreshold=1.0)
        if mat is None:
            mat = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
            out["inl"][i] = 0.0
        else:
            out["inl"][i] = float(inl.mean()) if inl is not None else 0.0
        a, b = mat[0, 0], mat[1, 0]
        scale = math.hypot(a, b)
        out["ls"][i] = math.log(scale) if scale > 0 else 0.0
        out["rot"][i] = math.degrees(math.atan2(b, a))
        moved = mat[:, :2] @ center + mat[:, 2]
        out["tx"][i] = (moved[0] - center[0]) / w
        out["ty"][i] = (moved[1] - center[1]) / h

        gfx = mat[0, 0] * xs + mat[0, 1] * ys + mat[0, 2] - xs
        gfy = mat[1, 0] * xs + mat[1, 1] * ys + mat[1, 2] - ys
        rmag = np.hypot(flow[..., 0] - gfx, flow[..., 1] - gfy)
        out["resid"][i] = float(rmag.mean()) * per_s
        if reg is not None and region_resid is not None and region_mag is not None:
            region_resid[i] = float(rmag[reg].mean()) * per_s
            region_mag[i] = float(fmag[reg].mean()) * per_s

    hist_far = np.zeros(m)
    for i in range(m):
        a_i, b_i = max(0, i - window), min(n - 1, i + 1 + window)
        hist_far[i] = cv2.compareHist(hists[a_i], hists[b_i], cv2.HISTCMP_BHATTACHARYYA)

    t = (np.arange(m) + 1) / fps
    return PairSignals(
        fps=fps,
        width=w,
        height=h,
        t=t,
        hist_d=out["hist_d"],
        unexplained=out["unexplained"],
        tx=out["tx"],
        ty=out["ty"],
        log_scale=out["ls"],
        rot_deg=out["rot"],
        inliers=out["inl"],
        mag=out["mag"],
        mag_p95=out["p95"],
        resid=out["resid"],
        region_resid=region_resid,
        region_mag=region_mag,
        hist_far=hist_far,
    )
