import pytest
from take_qc import expect
from take_qc.config import load_config

CFG = load_config()


@pytest.mark.parametrize(
    ("text", "classes", "allowed"),
    [
        ("", ["static"], set()),
        ("A close-up of her, 85mm", ["static"], set()),
        ("slow push-in on his face", ["push_in"], {"zoom_in"}),
        ("the camera dollying back in front of her", ["pull_back"], {"zoom_out", "zoom_in"}),
        ("A wide tracking shot moving sideways", ["track"], {"pan", "tilt", "zoom_in", "zoom_out"}),
        ("A slow upward tilt from the feet to the head", ["tilt"], {"tilt"}),
    ],
)
def test_camera_plan_keywords(text, classes, allowed):
    plan = expect.camera_plan(text, CFG)
    assert plan.classes == classes
    assert plan.allowed == allowed


def test_camera_plan_vertical_sign():
    assert expect.camera_plan("slow crane up", CFG).vertical_sign == 1
    assert expect.camera_plan("a slow descending crane move", CFG).vertical_sign == -1
    assert expect.camera_plan("static", CFG).vertical_sign == 0


def test_build_reads_direction_and_checklist_wins():
    direction = {
        "direction_version": 2,
        "camera": {"movement": "static"},
        "shots": [{"id": "a"}, {"id": "b", "cut_in": "HARD CUT", "camera": {"movement": "push in"}}],
        "audio": {"dialogue": [{"who": "x", "line": "Hello"}]},
    }
    ex = expect.build(None, direction, CFG)
    assert ex.shots == 2 and ex.dialogue == ["Hello"] and ex.audio is True
    assert "push in" in ex.camera_text
    assert ex.motion_region == [0.0, 0.0, 1.0, 1.0 / 3.0]
    ex2 = expect.build(
        {"camera": {"movement": "pan left"}, "shots": 1, "motion_region": "whole", "dialogue": []}, direction, CFG
    )
    assert ex2.camera_text == "pan left" and ex2.shots == 1 and ex2.motion_region is None and ex2.dialogue == []


def test_build_rejects_bad_region():
    with pytest.raises(ValueError):
        expect.build({"motion_region": [0, 1]}, None, CFG)


def test_config_override_merges():
    cfg = load_config(overrides={"camera": {"zoom_out_total_flag": 0.2}})
    assert cfg["camera"]["zoom_out_total_flag"] == 0.2
    assert cfg["camera"]["zoom_in_total_flag"] == CFG["camera"]["zoom_in_total_flag"]
