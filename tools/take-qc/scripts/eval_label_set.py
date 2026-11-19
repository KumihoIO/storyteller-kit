"""Run take-qc over a labelled take set and measure agreement with the labels.

    python eval_label_set.py LABELS.json --root-var QC_ROOT=D:/media/set \
        --run-out checker_run.json --report-out agreement.json [--md-out agreement.md]

The checklist for each take is built only from the label file's generic
``generation`` block: requested duration, dialogue script, the first
sentence of the prompt summary as the camera plan, one continuous shot, and
audio expected. Nothing here is specific to a project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from take_qc import __version__  # noqa: E402
from take_qc.checker import ITEM_KINDS, check_take  # noqa: E402
from take_qc.config import load_config  # noqa: E402
from take_qc.record import rewrite_paths  # noqa: E402


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return m.group(1) if m else text.strip()


def checklist_for(take: dict[str, Any]) -> dict[str, Any]:
    gen = take.get("generation") or {}
    cl: dict[str, Any] = {"expected": {"audio": True}, "shots": 1}
    if gen.get("requested_duration_s") is not None:
        cl["expected"]["duration_s"] = gen["requested_duration_s"]
    cl["dialogue"] = list(gen.get("dialogue_script") or [])
    if gen.get("prompt_summary"):
        cl["camera"] = {"movement": first_sentence(gen["prompt_summary"])}
    return cl


def resolve(path: str, var: str, root: str) -> str:
    return path.replace("${" + var + "}", root.rstrip("/\\"))


def agreement(labels: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_item: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    for kind in ITEM_KINDS:
        c: Counter[str] = Counter()
        for take in labels["takes"]:
            lab = take["labels"].get(kind)
            res = results.get(take["take_key"])
            if lab is None or res is None:
                continue
            if lab.get("applicable", True) is False:
                c["not_applicable"] += 1
                continue
            got = next(i for i in res["items"] if i["item_id"] == kind)
            lv, cv = lab["verdict"], got["verdict"]
            c[f"label_{lv}"] += 1
            c[f"checker_{cv}"] += 1
            if cv == "unknown":
                c["checker_unknown"] += 0  # counted above
                continue
            if lv == "unknown":
                c["label_unknown_checker_decided"] += 1
                continue
            c["decided"] += 1
            if lv == cv:
                c["agree"] += 1
            elif cv == "flag":
                c["false_flags"] += 1
                cases.append(
                    {
                        "take": take["take_key"],
                        "item": kind,
                        "type": "false_flag",
                        "checker": got["note"],
                        "label": lab.get("note", ""),
                    }
                )
            else:
                c["misses"] += 1
                cases.append(
                    {
                        "take": take["take_key"],
                        "item": kind,
                        "type": "miss",
                        "checker": got["note"],
                        "label": lab.get("note", ""),
                    }
                )
        decided = c["decided"]
        per_item[kind] = {
            "applicable": sum(c[f"label_{v}"] for v in ("pass", "flag", "unknown")),
            "label": {v: c[f"label_{v}"] for v in ("pass", "flag", "unknown")},
            "checker": {v: c[f"checker_{v}"] for v in ("pass", "flag", "unknown")},
            "decided_by_both": decided,
            "agree": c["agree"],
            "agreement": round(c["agree"] / decided, 3) if decided else None,
            "false_flags": c["false_flags"],
            "misses": c["misses"],
            "label_unknown_checker_decided": c["label_unknown_checker_decided"],
            "not_applicable": c["not_applicable"],
        }
    return {"per_item": per_item, "disagreements": cases}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--root-var", required=True, help="VAR=DIR")
    ap.add_argument("--config")
    ap.add_argument("--run-out", required=True)
    ap.add_argument("--report-out", required=True)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    var, _, root = args.root_var.partition("=")
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    cfg = load_config(args.config)
    results: dict[str, dict[str, Any]] = {}
    rows = []
    t_all = time.perf_counter()
    for take in labels["takes"]:
        key = take["take_key"]
        if args.only and key not in args.only:
            continue
        media = take["media"]
        video = resolve(media.get("video_with_audio") or media["video"], var, root)
        res = check_take(video, checklist_for(take), None, cfg)
        res = rewrite_paths(res, {var: root})
        results[key] = res
        flagged = [i["item_id"] for i in res["items"] if i["verdict"] == "flag"]
        print(f"{key}: {res['timing_s']:.2f} s flagged={flagged}", flush=True)
        rows.append(
            {
                "take_key": key,
                "video": res["video"],
                "timing_s": res["timing_s"],
                "checklist": checklist_for(take),
                "probe": res["probe"],
                "transitions": res.get("transitions"),
                "camera": res.get("camera"),
                "motion": res.get("motion"),
                "items": [i for i in res["items"]],
            }
        )
    wall = time.perf_counter() - t_all
    first_tool = next(iter(results.values()))["tool"] if results else {}
    timings = sorted(r["timing_s"] for r in rows)
    runtime = {
        "takes": len(rows),
        "wall_s": round(wall, 2),
        "mean_s_per_take": round(sum(timings) / len(timings), 3) if timings else None,
        "min_s": timings[0] if timings else None,
        "max_s": timings[-1] if timings else None,
        "device": "CPU",
        "cpu_count": os.cpu_count(),
    }
    run = {
        "schema": "take-qc/label-set-run/v1",
        "set_id": labels.get("set_id"),
        "labels_file": Path(args.labels).name,
        "media_root_var": var,
        "tool": first_tool,
        "take_qc_version": __version__,
        "config": cfg,
        "runtime": runtime,
        "takes": rows,
    }
    Path(args.run_out).write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    report = {
        "schema": "take-qc/agreement/v1",
        "set_id": labels.get("set_id"),
        "labels_file": Path(args.labels).name,
        "reference": "labels drafted by an agent and confirmed by a person (labeled_by: agent-draft, confirmed: true)",
        "take_qc_version": __version__,
        "runtime": runtime,
        **agreement(labels, results),
    }
    Path(args.report_out).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    for kind, v in report["per_item"].items():
        print(kind, json.dumps(v))
    print(json.dumps(runtime))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
