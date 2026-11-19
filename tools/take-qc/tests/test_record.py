import json
from pathlib import Path

import pytest
from take_qc import record

SCHEMA = Path(__file__).resolve().parents[3] / "fixtures" / "qc" / "schema" / "take_labels.schema.json"
TOOL = {"name": "take-qc", "version": "0.1.0"}


def _item(item_id, kind, verdict, **extra):
    base = {
        "item_id": item_id,
        "kind": kind,
        "verdict": verdict,
        "confidence": "low",
        "evidence": {},
        "note": "",
        "tool": TOOL,
    }
    base.update(extra)
    return base


def _result():
    items = [
        _item("format", "format", "pass", confidence="high", evidence={"measurements": {"frames": 124}}, note="ok"),
        _item("camera", "camera", "flag", confidence="high", evidence={"frame_times_s": [3.375]}, note="hard cut"),
        _item("hair", "hair", "unknown", note="host vision", needs="host-vision"),
        _item("hair-braid", "hair", "unknown", note="host vision", needs="host-vision", source="memory"),
        _item("dialogue", "dialogue", "unknown", note="person", needs="person-audio"),
    ]
    r = {"tool": {**TOOL, "components": {"ffprobe": "9.0", "opencv": "5.0"}}, "items": items}
    r["self_check"] = record.self_check_record(r)
    return r


def test_self_check_record_shape():
    sc = _result()["self_check"]
    assert sc["passed"] is False
    assert [v["verdict"] for v in sc["verdicts"]] == ["pass", "fail", "cannot_tell", "cannot_tell", "cannot_tell"]
    assert sc["verdicts"][2]["reason"].startswith("[host-vision]")
    assert sc["recalled"] == [] and all(i["recalled"] == [] for i in sc["items"])
    assert sc["tool_versions"]["opencv"] == "5.0"
    assert sc["items"][3]["source"] == "memory" and sc["items"][0]["source"] == "server"


def test_merge_fills_unknowns_by_kind():
    answers = [
        {
            "kind": "hair",
            "verdict": "flag",
            "confidence": "medium",
            "note": "braided at 2.1 s",
            "evidence": {"frame_times_s": [2.1]},
            "tool": {"name": "host-vision:test-model"},
            "recalled": ["kref://mem/1"],
        }
    ]
    out = record.merge(_result(), answers)
    hairs = [i for i in out["items"] if i["kind"] == "hair"]
    assert len(hairs) == 2
    assert all(
        h["verdict"] == "flag" and h["tool"]["name"] == "host-vision:test-model" and "needs" not in h for h in hairs
    )
    sc = out["self_check"]
    assert "host-vision:test-model" in sc["tool_versions"]
    assert sc["items"][2]["recalled"] == ["kref://mem/1"]


def test_merge_refuses_measured_items_and_bad_answers():
    host = {"name": "host-vision:x"}
    with pytest.raises(record.MergeError):
        record.merge(_result(), [{"item_id": "camera", "verdict": "pass", "tool": host}])
    out = record.merge(_result(), [{"item_id": "camera", "verdict": "pass", "tool": host}], allow_override=True)
    assert out["items"][1]["verdict"] == "pass"
    for bad in (
        {"item_id": "hair", "verdict": "ok", "tool": host},
        {"item_id": "hair", "verdict": "pass"},
        {"item_id": "nope", "verdict": "pass", "tool": host},
        {"item_id": "hair", "verdict": "pass", "confidence": "sure", "tool": host},
    ):
        with pytest.raises(record.MergeError):
            record.merge(_result(), [bad])


def test_all_unknowns_answered_pass_makes_record_pass():
    r = _result()
    r["items"][1]["verdict"] = "pass"
    ans = {"items": [{"kind": k, "verdict": "pass", "tool": {"name": "host-vision:m"}} for k in ("hair", "dialogue")]}
    assert record.merge(r, ans)["self_check"]["passed"] is True


def test_rewrite_paths():
    obj = {"video": "D:\\media\\set\\c01.mp4", "list": ["D:/media/set/frames/a.jpg", "elsewhere/b.jpg"], "n": 1}
    out = record.rewrite_paths(obj, {"QC_ROOT": "D:/media/set"})
    assert out == {"video": "${QC_ROOT}/c01.mp4", "list": ["${QC_ROOT}/frames/a.jpg", "elsewhere/b.jpg"], "n": 1}


def test_to_label_validates_against_label_schema():
    jsonschema = pytest.importorskip("jsonschema")
    if not SCHEMA.exists():
        pytest.skip("label schema not in this checkout")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator({**schema["$defs"]["label"], "$defs": schema["$defs"]})
    for it in _result()["items"]:
        validator.validate(record.to_label(it))
