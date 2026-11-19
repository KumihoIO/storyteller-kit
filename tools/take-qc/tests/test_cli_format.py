"""End to end through the CLI. Runs without the vision extra (camera and motion
then stay unknown); with it, they are measured."""

import json

from conftest import ENC, ffmpeg, needs_ffmpeg
from take_qc import cli, vision


@needs_ffmpeg
def test_check_format_and_silence(tmp_path, stills):
    video = tmp_path / "v.mp4"
    ffmpeg(
        "-loop", "1", "-i", str(stills["a"]), "-f", "lavfi", "-i", "anullsrc=r=32000:cl=mono",
        "-t", "2", *ENC, "-c:a", "aac", "-shortest", str(video),
    )  # fmt: skip
    cl = tmp_path / "cl.json"
    cl.write_text(
        json.dumps({"expected": {"duration_s": 2.0, "width": 480, "height": 270, "fps": 24}, "dialogue": ["Hello"]})
    )
    out = tmp_path / "r.json"
    assert (
        cli.main(["check", str(video), "--checklist", str(cl), "--out", str(out), "--path-var", f"ROOT={tmp_path}"])
        == 0
    )
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["video"] == "${ROOT}/v.mp4"
    items = {i["item_id"]: i for i in r["items"]}
    assert items["format"]["verdict"] == "flag" and "silent audio" in items["format"]["note"]
    for k in ("identity", "hair", "costume", "prop_shape", "on_screen_text", "acting"):
        assert items[k]["verdict"] == "unknown" and items[k]["needs"] == "host-vision"
    for k in ("dialogue", "lipsync"):
        assert items[k]["verdict"] == "unknown" and items[k]["needs"] == "person-audio"
        assert "cannot hear audio" in items[k]["note"]
    if not vision.available():
        assert items["camera"]["verdict"] == "unknown" and items["motion"]["verdict"] == "unknown"
    assert r["self_check"]["passed"] is False and r["self_check"]["recalled"] == []


@needs_ffmpeg
def test_check_format_duration_and_missing_audio(tmp_path, stills):
    video = tmp_path / "v.mp4"
    ffmpeg("-loop", "1", "-i", str(stills["a"]), "-t", "1", *ENC, str(video))
    cl = tmp_path / "cl.json"
    cl.write_text(json.dumps({"expected": {"duration_s": 3.0, "audio": True}}))
    out = tmp_path / "r.json"
    cli.main(["check", str(video), "--checklist", str(cl), "--out", str(out)])
    fmt = next(i for i in json.loads(out.read_text(encoding="utf-8"))["items"] if i["item_id"] == "format")
    assert fmt["verdict"] == "flag" and "no audio stream" in fmt["note"] and "expected 3.0 s" in fmt["note"]


@needs_ffmpeg
def test_merge_cli(tmp_path, stills):
    video = tmp_path / "v.mp4"
    ffmpeg("-loop", "1", "-i", str(stills["a"]), "-t", "1", *ENC, str(video))
    out = tmp_path / "r.json"
    cli.main(["check", str(video), "--out", str(out)])
    ans = tmp_path / "a.json"
    ans.write_text(
        json.dumps([{"kind": "identity", "verdict": "pass", "confidence": "high", "tool": {"name": "host-vision:m"}}])
    )
    final = tmp_path / "f.json"
    assert cli.main(["merge", str(out), str(ans), "--out", str(final)]) == 0
    sc = json.loads(final.read_text(encoding="utf-8"))["self_check"]
    assert next(v for v in sc["verdicts"] if v["item_id"] == "identity")["verdict"] == "pass"
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps([{"kind": "format", "verdict": "flag", "tool": {"name": "host-vision:m"}}]))
    assert cli.main(["merge", str(out), str(bad), "--out", str(final)]) == 2


@needs_ffmpeg
def test_crop_native_resolution(tmp_path, stills):
    import subprocess

    v = tmp_path / "still.mp4"
    ffmpeg("-loop", "1", "-i", str(stills["b"]), "-t", "1", *ENC, str(v))
    out = tmp_path / "c.jpg"
    assert cli.main(["crop", str(v), "--t", "0.5", "--box", "0.5", "0.5", "1", "1", "--out", str(out)]) == 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    s = json.loads(probe.stdout)["streams"][0]
    assert s["width"] == 480 and abs(s["height"] - 270) <= 2  # a quarter of 480x270, enlarged x2 (even rounding)
    assert cli.main(["crop", str(v), "--t", "0.5", "--box", "0.6", "0", "0.4", "1", "--out", str(out)]) == 2
