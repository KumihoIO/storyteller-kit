"""take-qc: a local, model-free first pass over generated video takes.

Measures format, motion, camera movement and internal cuts/dissolves with
ffprobe/ffmpeg and (optionally) numpy + OpenCV. Items that need a model
(identity, hair, costume, prop shape, on-screen text, dialogue, lipsync,
acting) are reported as ``unknown``; they never pass.
"""

from take_qc.checker import ITEM_KINDS, check_take
from take_qc.config import load_config

__version__ = "0.1.0"

__all__ = ["ITEM_KINDS", "__version__", "check_take", "load_config"]
