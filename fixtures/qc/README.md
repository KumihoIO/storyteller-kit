# Take QC labels

Ground-truth labels for generated video takes, used to measure automatic take checkers (such as take-qc) by agreement with a person.

- `schema/take_labels.schema.json`: the generic label schema. One file per take set. Each take has a key, a group (usually the cut), media paths under a root variable (`${QC_ROOT}/...`), technical facts (ffprobe), what the take was asked to be (recovered generator metadata), and one label per checklist item kind: `identity`, `hair`, `costume`, `prop_shape`, `on_screen_text`, `motion`, `camera`, `dialogue`, `lipsync`, `acting`, `format`.
- Each label has `verdict` (`pass` | `flag` | `unknown`), `confidence` (`high` | `medium` | `low`), optional `evidence` (frame times, normalized crop boxes, transcript excerpt, raw measurements), a free `note`, `labeled_by` (`agent-draft` | `person`) and `confirmed`.
- `unknown` means "could not be measured or judged". It never counts as a pass.
- `examples/<set>/labels.draft.json` (not shipped in this kit; keep your own sets locally): agent drafts. A draft becomes ground truth only after a person confirms or corrects each label (`labeled_by: "person"` or `confirmed: true`). Save the confirmed copy as `labels.json` next to the draft.

No media is stored here. Set the root variable on the host before resolving paths, for example `QC_ROOT=D:/comfyui/output/MY_SET`.

Validate with:

```
python -c "import json,jsonschema; s=json.load(open('fixtures/qc/schema/take_labels.schema.json')); jsonschema.validate(json.load(open('fixtures/qc/examples/my_set/labels.draft.json',encoding='utf-8')), s, format_checker=jsonschema.FormatChecker())"
```

Item kinds and verdicts are not tied to any project, character or model.
