"""take-qc command line.

take-qc check  <video> [--checklist c.json] [--direction d.json] [--config cfg.json] --out result.json
take-qc frames <result.json> --out-dir DIR [--checklist c.json]
take-qc merge  <result.json> <answers.json> --out final.json
take-qc crop   <video> --t SECONDS --box X0 Y0 X1 Y1 --out crop.jpg [--scale 2]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from take_qc import record
from take_qc.config import load_config


def _read(path: str | None) -> Any:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _path_vars(values: list[str] | None) -> dict[str, str]:
    out = {}
    for v in values or []:
        name, _, path = v.partition("=")
        if not name or not path:
            raise SystemExit(f"--path-var expects NAME=DIR, got {v!r}")
        out[name] = path
    return out


def cmd_check(args: argparse.Namespace) -> int:
    from take_qc.checker import check_take

    cfg = load_config(args.config)
    checklist = _read(args.checklist)
    result = check_take(args.video, checklist, _read(args.direction), cfg)
    if args.frames_dir:
        from take_qc.frames import build_packet

        result["review_packet"] = str(Path(args.frames_dir) / "packet.json")
        build_packet(result, args.frames_dir, cfg, checklist)
    result = record.rewrite_paths(result, _path_vars(args.path_var))
    _write(args.out, result)
    flagged = [i["item_id"] for i in result["items"] if i["verdict"] == "flag"]
    print(f"{args.video}: {len(flagged)} flagged {flagged} in {result['timing_s']} s -> {args.out}")
    return 0


def cmd_frames(args: argparse.Namespace) -> int:
    from take_qc.frames import build_packet

    cfg = load_config(args.config)
    packet = build_packet(_read(args.result), args.out_dir, cfg, _read(args.checklist))
    print(f"{len(packet['frames'])} frames, {len(packet['items'])} items -> {Path(args.out_dir) / 'packet.json'}")
    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    from take_qc.frames import crop_from_video

    try:
        out = crop_from_video(args.video, args.t, args.box, args.out, args.scale)
    except ValueError as exc:
        print(f"crop refused: {exc}", file=sys.stderr)
        return 2
    print(f"{args.video} @ {args.t} s {args.box} -> {out}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    try:
        merged = record.merge(_read(args.result), _read(args.answers), allow_override=args.allow_override)
    except record.MergeError as exc:
        print(f"merge refused: {exc}", file=sys.stderr)
        return 2
    _write(args.out, merged)
    sc = merged["self_check"]
    print(f"passed={sc['passed']}; {sc['notes']} -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="take-qc", description="Local, model-free take checker.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="measure a video and write the per-item result")
    c.add_argument("video")
    c.add_argument("--checklist")
    c.add_argument("--direction")
    c.add_argument("--config")
    c.add_argument("--out", required=True)
    c.add_argument("--frames-dir", help="also build the host review packet here")
    c.add_argument("--path-var", action="append", help="NAME=DIR: write paths under DIR as ${NAME}/...")
    c.set_defaults(func=cmd_check)

    f = sub.add_parser("frames", help="build the host review packet (keyframes, contact sheet, crops, questions)")
    f.add_argument("result")
    f.add_argument("--out-dir", required=True)
    f.add_argument("--checklist")
    f.add_argument("--config")
    f.set_defaults(func=cmd_frames)

    m = sub.add_parser("merge", help="fill unknown items with the host's answers and write the final self_check record")
    m.add_argument("result")
    m.add_argument("answers")
    m.add_argument("--out", required=True)
    m.add_argument("--allow-override", action="store_true", help="let answers replace measured items")
    m.set_defaults(func=cmd_merge)

    k = sub.add_parser("crop", help="crop one frame at native resolution")
    k.add_argument("video")
    k.add_argument("--t", type=float, required=True, help="time in seconds")
    k.add_argument("--box", type=float, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"), help="normalized")
    k.add_argument("--out", required=True)
    k.add_argument("--scale", type=float, default=2.0, help="enlarge the crop (default 2)")
    k.set_defaults(func=cmd_crop)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
