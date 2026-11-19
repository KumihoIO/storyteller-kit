from take_qc.probe import parse_ffprobe, parse_volumedetect


def test_parse_ffprobe_video_and_audio():
    data = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1088,
                "avg_frame_rate": "24/1",
                "nb_frames": "124",
                "duration": "5.166667",
            },
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "32000"},
        ],
        "format": {"duration": "5.2"},
    }
    p = parse_ffprobe(data)
    assert (p.width, p.height, p.fps, p.frames, p.duration_s) == (1920, 1088, 24.0, 124, 5.167)
    assert p.has_audio and p.audio_codec == "aac" and p.audio_sample_rate == 32000


def test_parse_ffprobe_frames_from_duration_and_no_audio():
    p = parse_ffprobe(
        {
            "streams": [{"codec_type": "video", "width": 2, "height": 2, "r_frame_rate": "30000/1001"}],
            "format": {"duration": "2.0"},
        }
    )
    assert p.frames == 60 and not p.has_audio and p.fps == 29.97


def test_parse_volumedetect():
    err = "[Parsed_volumedetect_0 @ 0x] mean_volume: -24.7 dB\n[Parsed_volumedetect_0 @ 0x] max_volume: -11.9 dB\n"
    assert parse_volumedetect(err) == (-24.7, -11.9)
    assert parse_volumedetect("mean_volume: -inf dB\nmax_volume: -inf dB") == (float("-inf"), float("-inf"))
