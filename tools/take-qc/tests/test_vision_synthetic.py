"""Synthetic takes with known camera moves and transitions (needs numpy + OpenCV)."""

import json

import pytest
from conftest import ENC, ffmpeg, needs_ffmpeg

pytest.importorskip("numpy")
pytest.importorskip("cv2")

from take_qc import cli  # noqa: E402
from take_qc.checker import check_take  # noqa: E402

pytestmark = needs_ffmpeg


def _zoom(still, out, expr):
    vf = f"scale=1920:1080,zoompan=z='{expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=72:s=480x270:fps=24"
    ffmpeg("-loop", "1", "-i", str(still), "-vf", vf, "-frames:v", "72", *ENC, str(out))


def _cut(stills, out):
    ffmpeg(
        "-loop", "1", "-t", "1.5", "-i", str(stills["a"]), "-loop", "1", "-t", "1.5", "-i", str(stills["b"]),
        "-filter_complex", "[0]fps=24,format=yuv420p[a];[1]fps=24,format=yuv420p[b];[a][b]concat=n=2:v=1:a=0",
        *ENC, str(out),
    )  # fmt: skip


def _items(r):
    return {i["item_id"]: i for i in r["items"]}


def test_static_passes(tmp_path, stills):
    v = tmp_path / "static.mp4"
    ffmpeg("-loop", "1", "-i", str(stills["a"]), "-t", "3", *ENC, str(v))
    r = check_take(str(v), {"camera": {"movement": "static"}})
    it = _items(r)
    assert it["camera"]["verdict"] == "pass", it["camera"]["note"]
    assert it["motion"]["verdict"] == "pass"
    assert r["transitions"] == []


def test_unplanned_pull_back_flags_and_planned_one_passes(tmp_path, stills):
    v = tmp_path / "pull.mp4"
    _zoom(stills["a"], v, "1.5-0.006*on")
    flagged = check_take(str(v), {"camera": {"movement": "A close-up of her, 85mm"}})
    cam = _items(flagged)["camera"]
    assert cam["verdict"] == "flag" and "pull-back" in cam["note"], cam["note"]
    assert flagged["camera"]["zoom_total_log"] < -0.2
    ok = check_take(str(v), {"camera": {"movement": "slow pull back"}})
    assert _items(ok)["camera"]["verdict"] == "pass", _items(ok)["camera"]["note"]


def test_push_in_measured(tmp_path, stills):
    v = tmp_path / "push.mp4"
    _zoom(stills["a"], v, "1+0.006*on")
    r = check_take(str(v), {"camera": {"movement": "slow push-in"}})
    assert _items(r)["camera"]["verdict"] == "pass", _items(r)["camera"]["note"]
    assert r["camera"]["zoom_total_log"] > 0.2


def test_hard_cut_found(tmp_path, stills):
    v = tmp_path / "cut.mp4"
    _cut(stills, v)
    r = check_take(str(v), None)
    cuts = [t for t in r["transitions"] if t["kind"] == "cut"]
    assert len(cuts) == 1 and abs(cuts[0]["start_s"] - 1.5) <= 1 / 24 + 1e-6, r["transitions"]
    cam = _items(r)["camera"]
    assert cam["verdict"] == "flag" and cam["confidence"] == "high" and "hard cut" in cam["note"]
    two = check_take(str(v), {"shots": 2})
    assert _items(two)["camera"]["verdict"] == "pass"


def test_dissolve_found(tmp_path, stills):
    v = tmp_path / "dissolve.mp4"
    ffmpeg(
        "-loop", "1", "-t", "2", "-i", str(stills["a"]), "-loop", "1", "-t", "2", "-i", str(stills["b"]),
        "-filter_complex",
        "[0]fps=24,format=yuv420p[a];[1]fps=24,format=yuv420p[b];[a][b]xfade=transition=fade:duration=0.5:offset=1",
        *ENC, str(v),
    )  # fmt: skip
    r = check_take(str(v), None)
    # A pixel cross-fade between unrelated stills makes Farneback hallucinate
    # motion, so it may be typed "transition" rather than "dissolve"; either way
    # it is one gradual transition at the right time, never a hard cut.
    kinds = [t["kind"] for t in r["transitions"]]
    assert len(kinds) == 1 and kinds[0] in ("dissolve", "transition"), r["transitions"]
    d = r["transitions"][0]
    assert 0.9 <= d["start_s"] <= 1.2 and 1.3 <= d["end_s"] <= 1.6, d
    assert _items(r)["camera"]["verdict"] == "flag"
    assert _items(r)["identity"]["evidence"]["frame_times_s"]


def test_frames_packet(tmp_path, stills):
    v = tmp_path / "cut.mp4"
    _cut(stills, v)
    cl = tmp_path / "cl.json"
    cl.write_text(
        json.dumps(
            {
                "references": [str(stills["a"])],
                "on_screen_text_allowlist": ["BAY 03"],
                "items": [
                    {
                        "id": "hair-1",
                        "kind": "hair",
                        "text": "half-up",
                        "source": "server",
                        "references": [str(stills["b"])],
                        "boxes": [{"label": "head", "box": [0.3, 0.0, 0.7, 0.5]}],
                    }
                ],
            }
        )
    )
    res = tmp_path / "r.json"
    cli.main(["check", str(v), "--checklist", str(cl), "--out", str(res), "--frames-dir", str(tmp_path / "pk")])
    packet = json.loads((tmp_path / "pk" / "packet.json").read_text(encoding="utf-8"))
    assert (tmp_path / "pk" / "contact_sheet.jpg").exists()
    reasons = " ".join(f["reasons"] for f in packet["frames"])
    assert "before cut" in reasons and "after cut" in reasons
    from pathlib import Path

    assert all(Path(f["path"]).exists() for f in packet["frames"])
    by_id = {i["item_id"]: i for i in packet["items"]}
    assert set(by_id) >= {"identity", "hair", "costume", "prop_shape", "on_screen_text", "acting", "hair-1"}
    assert by_id["hair-1"]["references"] == [str(stills["b"])] and by_id["hair-1"]["crops"]
    assert by_id["identity"]["references"] == [str(stills["a"])]
    assert "BAY 03" in by_id["on_screen_text"]["question"]
    assert "dialogue" in packet["not_for_host_vision"]


def test_packet_plan_beats_and_viewable_references(tmp_path, stills):
    v = tmp_path / "cut.mp4"
    _cut(stills, v)
    big = tmp_path / "sheet.png"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=3000x4000:rate=1", "-frames:v", "1", str(big))
    cl = tmp_path / "cl.json"
    cl.write_text(
        json.dumps(
            {
                "plan": "She frowns, then at 1.0 s shouts.",
                "references": [str(stills["a"])],
                "items": [
                    {"id": "acting", "kind": "acting", "text": "a sharp shout, not a scream", "times_s": [1.0]},
                    {"id": "hair", "kind": "hair", "text": "half-up, never braided", "references": [str(big)]},
                ],
            }
        )
    )
    res = tmp_path / "r.json"
    cli.main(["check", str(v), "--checklist", str(cl), "--out", str(res), "--frames-dir", str(tmp_path / "pk")])
    result = json.loads(res.read_text(encoding="utf-8"))
    ids = [i["item_id"] for i in result["items"]]
    assert ids.count("acting") == 1 and ids.count("hair") == 1  # kind-named items annotate, never duplicate
    assert _items(result)["hair"]["text"] == "half-up, never braided"
    packet = json.loads((tmp_path / "pk" / "packet.json").read_text(encoding="utf-8"))
    assert packet["plan"].startswith("She frowns")
    by_id = {i["item_id"]: i for i in packet["items"]}
    assert "checklist acting" in " ".join(f["reasons"] for f in packet["frames"])
    assert 1.0 in by_id["acting"]["focus_times_s"]
    assert "a sharp shout" in by_id["acting"]["question"] and "plan" in by_id["acting"]["question"]
    from pathlib import Path

    small = by_id["hair"]["reference_images"][0]
    assert by_id["hair"]["references"] == [str(big)] and Path(small).exists()
    probe = json.loads(
        __import__("subprocess").run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", small],
            capture_output=True, text=True, check=True,
        ).stdout
    )["streams"][0]  # fmt: skip
    assert max(probe["width"], probe["height"]) <= 1024
    assert by_id["identity"]["reference_images"][0]
