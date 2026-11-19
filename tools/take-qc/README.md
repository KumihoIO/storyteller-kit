# take-qc

A local, model-free first pass over generated video takes. It runs on the host, next to the generator, never on the
storyteller server. It measures what can be measured without a model (format, motion, camera movement, internal cuts
and dissolves), prepares a review packet that the host's own multimodal model (Claude, ChatGPT, ...) looks at for the
visual items, and merges the host's answers into a self-check record.

It never judges identity, hair, costume, prop shape, on-screen text or acting itself, and it never runs a local ML
model for judgment. Dialogue and lipsync stay `unknown` for a person: the host cannot hear audio.

## Install

Python 3.12+. ffmpeg and ffprobe on `PATH`.

```
pip install -e tools/take-qc            # format only (stdlib)
pip install -e "tools/take-qc[vision]"  # + numpy and OpenCV: motion, camera, cuts, contact sheet
pip install -e "tools/take-qc[dev]"     # tests
```

Without the `vision` extra, `motion` and `camera` are reported `unknown` ("needs the optional 'vision' extra").
An existing environment that already has numpy and OpenCV works as is (`PYTHONPATH=tools/take-qc/src python -m take_qc ...`).

## Commands

```
take-qc check  <video> [--checklist c.json] [--direction d.json] [--config cfg.json] --out result.json
               [--frames-dir DIR] [--path-var NAME=DIR ...]
take-qc frames <result.json> --out-dir DIR [--checklist c.json] [--config cfg.json]
take-qc merge  <result.json> <answers.json> --out final.json [--allow-override]
take-qc crop   <video> --t SECONDS --box X0 Y0 X1 Y1 --out crop.jpg [--scale 2]
```

- `check` probes and measures the take and writes `result.json`. With `--frames-dir` it also builds the review packet.
  `--path-var QC_ROOT=D:/media/set` writes paths under that directory as `${QC_ROOT}/...`, so a result can be shared
  without host paths.
- `frames` builds the review packet from an existing result (see below).
- `crop` cuts one frame at the video's native resolution (keyframes are downscaled to 1280 px) and enlarges it.
- `merge` fills the `unknown` items with the host's answers and rebuilds the self-check record. Answers for measured
  items (format, motion, camera) are refused unless `--allow-override`.

Library: `take_qc.check_take(video, checklist=None, direction=None, cfg=None)`,
`take_qc.frames.build_packet(result, out_dir, cfg, checklist)`, `take_qc.record.merge(result, answers)`,
`take_qc.record.to_label(item)` (an item as a `fixtures/qc` take label).

## Inputs

Checklist (every key optional):

```json
{
  "expected": {"duration_s": 5.0, "frames": 124, "width": 1920, "height": 1088, "fps": 24, "audio": true},
  "dialogue": ["Hey! Don't touch that!"],
  "camera": {"movement": "slow push-in"},
  "shots": 1,
  "motion_region": [0.3, 0.0, 0.7, 0.4],
  "plan": "A medium close-up of her, 50mm. At 00:01.500 she says ...",
  "references": ["/abs/face_sheet.png"],
  "on_screen_text_allowlist": ["BAY 03"],
  "items": [{"id": "hair-1", "kind": "hair", "text": "half-up, never braided", "source": "server",
             "references": ["/abs/costume_sheet.png"], "boxes": [{"label": "head", "box": [0.3, 0.0, 0.7, 0.4]}]}]
}
```

- `motion_region`: a normalized box `[x0, y0, x1, y1]`, `"upper_third"` (default, a head/hair heuristic) or `"whole"`.
- `plan`: the shot as written (Direction or prompt); copied into the packet for acting and prop questions.
- `items`: checklist entries with their own id become extra result items of that kind (source `server`, `decision` or
  `memory`). An entry whose id is the kind itself (`"id": "hair"`) annotates that base item instead of adding one.
  Their `references` and `boxes` go into the review packet; `boxes` produce crops; `times_s` (e.g. a dialogue beat)
  adds keyframes at those times and lists them as the item's focus times.

Direction (the storyteller Direction document): `camera.movement`, `shots[].camera.movement`, the number of `shots`
(planned internal cuts = shots - 1) and `audio.dialogue[].line` are read. Checklist values win.

## Output

`result.json` (`take-qc/result/v1`): probe, expectations, transitions, camera and motion summaries, timing, and
`items`: one per item kind (plus checklist items), in the take-label item shape:

```json
{"item_id": "camera", "kind": "camera", "verdict": "flag", "confidence": "high",
 "evidence": {"frame_times_s": [3.375], "measurements": {"zoom_total_log": -0.124, "...": 0}},
 "note": "hard cut at 3.375 s in a take planned as 1 continuous shot(s)",
 "tool": {"name": "take-qc", "version": "0.1.0"}}
```

`verdict` is `pass`, `flag` or `unknown`; `unknown` never counts as a pass. Items still to be answered carry
`needs`: `host-vision` or `person-audio`.

`self_check` in the result is ready for the host to send:

- `verdicts`: today's `record_self_check` contract (`item_id`, `pass` / `fail` / `cannot_tell`, `reason`).
- `items`: the extended record (verdict, confidence, measurements, frame times, evidence media as local paths, tool
  and version, source) with a `recalled` list (empty by default) for the host to fill.
- `tool_versions`, `passed` (true only when every item passed), `notes`.

## Review packet (host vision)

`take-qc frames` (or `check --frames-dir`) writes:

- `frames/t<seconds>.jpg`: full-resolution keyframes (max width 1280) at evenly spaced times, plus frames just before,
  inside and after every detected transition, at peak whole-frame and peak region motion, and at the ends of a
  measured pull-back.
- `contact_sheet.jpg`: all keyframes with their times and why each was picked (needs OpenCV).
- `crops/`: crops of checklist `boxes` from every keyframe.
- `refs/`: viewable copies of the reference images (long side `frames.reference_max_side`, default 1024; reference
  sheets are often 10-20 MB PNGs a host cannot open), listed per item as `reference_images` in the same order as
  `references`.
- `packet.json` (`take-qc/review-packet/v1`): for each visual item (identity, hair, costume, prop_shape,
  on_screen_text, acting and checklist items of those kinds) the frames, focus times (detected transition times and
  checklist `times_s`), reference images and their viewable copies, crops and a one-line question, plus the plan,
  the answer format and the measured items for context.

The host answers each item with `pass` / `flag` / `unknown`, a confidence, the frame time(s) it relied on and a note,
with `tool: {"name": "host-vision:<model id>"}`, then runs `take-qc merge`.

## What each measured item does

| Item | Measurement | Flag when |
|---|---|---|
| format | ffprobe duration, size, fps, frames, audio stream; ffmpeg `volumedetect` mean/max | frames or duration off the expectation, wrong size/fps, no audio when audio or dialogue is expected, near-silent audio (`silence_mean_db` / `silence_max_db`) when dialogue is expected |
| motion | Farneback dense optical flow on every consecutive frame pair at 320 px wide. Whole-frame magnitude (p95 per pair, then p95 over the take) and, in the motion region, the local magnitude after removing the global camera model. Units: frame widths per second | whole-frame p95 >= `whole_p95_flag` or region local p95 >= `region_residual_p95_flag` |
| camera | A similarity transform (RANSAC) fitted to the flow at textured grid points per pair, summed over the take: zoom (log scale), pan (frame widths), tilt (frame heights), roll (degrees). Pairs inside transitions or with too few inliers are left out. The planned move comes from keywords in the Direction/checklist camera text (`move_keywords`), mapped to allowed and required components | an observed component the plan does not allow (e.g. an unplanned pull-back), a required one missing, a tilt/crane going the wrong way, or any internal transition beyond `shots - 1` |
| cuts and dissolves | Hard cut: one isolated pair whose HSV histogram jumps (`hard_hist_min`) and whose change the dense flow cannot explain (`hard_ratio_min` x the local median of the flow-compensated residual). Gradual: a run of pairs with elevated unexplained change; a dissolve/morph when that change is large relative to motion (`dissolve_unexplained_per_motion`) and the content either side differs (`dissolve_hist_far_min`); otherwise a gradual transition (a cut hidden by fast motion, or a dissolve the flow mistakes for motion) when the content either side differs strongly (`transition_hist_far_min`) | reported under camera; the times are also written into the packet as focus times |

## Configuration

Defaults are in `src/take_qc/default_config.json`; `--config` deep-merges a JSON file over them. Nothing is tuned per
project in code. Key thresholds:

| Key | Default | Meaning |
|---|---|---|
| `format.duration_tolerance_s` | 0.75 | allowed duration difference when no frame count is given (generators round the frame count up) |
| `format.frames_tolerance` | 1 | allowed frame difference when `expected.frames` is given |
| `format.silence_mean_db` / `silence_max_db` | -50 / -35 | silent audio when dialogue is expected |
| `format.quiet_mean_db` | -38 | adds a "quiet mix" note, does not flag |
| `motion.whole_p95_flag` | 2.0 | frame widths/s |
| `motion.region_residual_p95_flag` | 1.0 | frame widths/s, camera motion removed |
| `camera.zoom_in_total_flag` / `zoom_out_total_flag` | 0.40 / 0.11 | log scale over the take; an unplanned pull-back is flagged sooner than a slow creep-in |
| `camera.pan_total_flag` / `tilt_total_flag` | 0.30 / 0.45 | fraction of frame width / height |
| `camera.roll_total_flag_deg` | 10 | degrees |
| `camera.expected_move_min` | 0.08 | a planned move smaller than this counts as missing |
| `camera.default_expected_move` | static | used when the camera text names no move |
| `cuts.hard_hist_min`, `hard_ratio_min` | 0.25, 6 | hard cut |
| `cuts.dissolve_*`, `transition_*` | see file | gradual transitions |
| `frames.even_count` | 8 | evenly spaced keyframes in the packet |
| `frames.reference_max_side` | 1024 | long side of the viewable reference copies |

The defaults were set against a private 40-take example set (not published; it names a private project's
characters and media). That set has no take labelled for excessive motion, so the motion thresholds are only known
not to raise false flags; they have not been checked against a true positive.

## Limits

- Framing (who is in shot, shot size) is not measured: a static two-shot where a single close-up was planned passes
  camera. The host answers it from the packet.
- The size of a planned move is not read from the text: "a slow crane from the rafters to the floor" passes once any
  descent is measured.
- Optical flow underestimates motion on flat surfaces; the global model uses textured points only, and the take is
  `unknown` for camera when fewer than `min_usable_fraction` of pairs give a usable model.
- Runtime: about 3.5 s per 5-7 s 1080p take on CPU (decode at 320 px, flow on every pair).

## Tests

```
python -m pytest tools/take-qc/tests
```

Format, record, merge and config tests need only the stdlib and ffmpeg. The synthetic camera/cut/dissolve and packet
tests are skipped when numpy or OpenCV is missing.

## Evaluating against a label set

```
python tools/take-qc/scripts/eval_label_set.py path/to/labels.json \
    --root-var QC_ROOT=D:/comfyui/output/MY_SET \
    --run-out path/to/checker_run.json \
    --report-out path/to/agreement.json
```

The checklist for each take comes from the label file's generic `generation` block only (requested duration,
dialogue script, the first sentence of the prompt as the camera plan, one continuous shot, audio expected).
