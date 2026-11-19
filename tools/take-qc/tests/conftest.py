import shutil
import subprocess
from pathlib import Path

import pytest

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


@pytest.fixture(scope="session")
def stills(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not on PATH")
    d = tmp_path_factory.mktemp("stills")
    a, b = d / "a.png", d / "b.png"
    ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=480x270:rate=24", "-frames:v", "1", str(a))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=480x270:rate=24", "-frames:v", "1", str(b))
    return {"a": a, "b": b}


ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24"]
