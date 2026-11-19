"""Threshold configuration. Defaults ship as ``default_config.json``; a user file
is deep-merged over them. Nothing project-specific lives in code."""

from __future__ import annotations

import copy
import json
from importlib import resources
from pathlib import Path
from typing import Any


def default_config() -> dict[str, Any]:
    text = resources.files("take_qc").joinpath("default_config.json").read_text(encoding="utf-8")
    return json.loads(text)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = default_config()
    if path is not None:
        cfg = _merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    if overrides:
        cfg = _merge(cfg, overrides)
    return cfg
