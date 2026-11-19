# Schemas

JSON Schema (draft 2020-12) contracts for the documents 9miho-storyteller
exchanges with hosts and with the team's web app. The schema files are the
source of truth for the public contract; the hosted server is checked against
them. Only client-facing contracts are published here: the ledger records a host
reads or writes, the Direction and model-profile documents, the MCP tool
contracts and the HTTP API contracts.

| File | Describes |
|---|---|
| `ledger/work-order.schema.json` | A work order: one medium of one Moment, its lease, state and links. |
| `ledger/take.schema.json` | A registered result for a work order and its adoption. |
| `ledger/render-receipt.schema.json` | The signed receipt that makes a result registrable. |
| `ledger/submission.schema.json` | What a host sends back after generating. |
| `ledger/self-check.schema.json` | The host's verdict on its own result. |
| `ledger/step.schema.json` | What `story_step` returns: the next action for the host. |
| `ledger/defs.schema.json` | Enumerations shared by the ledger schemas (order state, medium, review policy, role, adoption, close reason, host action, step reason, hold kind, reference kind). |
| `direct/direction.schema.json` | The provider-neutral Direction document. |
| `direct/model-profile.schema.json` | One model profile, and the YAML file form that carries several. |

## MCP tool contracts (`mcp/`)

`mcp/<tool>.schema.json` holds one MCP tool's contract: the profiles it is listed
in (`guided`, `granular`), its annotations, and its `inputSchema` and
`outputSchema` exactly as the server lists them. These files are the one
exception to "written by hand": they are generated from the server's registered
tools, and the server's tests fail when a tool and its file disagree in either
direction.

Shared shapes (an order, a take, the story-data wrapper, a page of ids) are
written once per file under `$defs` and referenced with a local `$ref`; nothing
refers outside its own file. Answers of the loop name the fields a host acts on
and allow more (`additionalProperties: true`); everything else is closed.
Anything a member or another host wrote is returned inside the story-data
wrapper `{"content_kind": "story_data", "treat_as": ..., "data": ...}`, which a
host treats as data, never as instructions.

## Web app API contracts (`api/`)

`api/<route>.schema.json` holds one route of the HTTP API the team's web app
uses: `method`, `path`, the `query` parameters, the `request`
body of a decision (or null), the `response` and the `error` body, each a JSON
Schema. Like `mcp/`, these files are generated from the server's routes and
checked against them. People's decisions (approve, reject, pick, restore, ...)
exist only here, never as MCP tools.

Each file is self-contained: shared shapes are under its `$defs`. Ledger
records are the `ledger/` schemas inlined with their field and enum names
unchanged (`work_order`, `take`, `defs` enumerations). Unlike the ledger schemas, every object in an
answer lists all its properties as required: the server always sends every
field, null where there is no value. Lists are pages: `items`, `total` (null
when unknown), `more_available`, `next_cursor`.

## Identifiers

Each schema's `$id` lives under the placeholder base
`https://schemas.9miho.io/storyteller/`, followed by the family and a version
segment, for example `.../ledger/v2/work-order.schema.json` and
`.../direct/v2/direction.schema.json`. Schemas refer to each other by relative
`$ref`, which resolves against `$id`; nothing is fetched over the network, so
load every file into a local registry keyed by `$id`. The directory layout here
does not need to mirror the `$id` path.

## Versioning

Every document carries its own version field, and an older version stays
readable:

- Ledger records (`work-order`, `take`) carry `version` (2 today).
- A render receipt carries its own `version` (1 today), which selects the list of
  fields the signature covers.
- A Direction carries `direction_version` (2 today), which is required.
- A model profile carries `version`, a required integer (1 for a first release),
  described below.
- `step`, `submission` and `self-check` carry no version
  of their own; they change only by adding optional fields or enum values, and a
  reader refuses an enum value it does not know.

Every version field is an integer of at least 1.

A version bump means a field's meaning changed in a way stored documents cannot
survive. Additive, optional fields do not bump it. The version in a `$id`
changes only when a schema stops accepting documents an earlier one accepted.

### Model profile versions

A profile is identified by `id` and `version` together. A render receipt records
the id as `profile_id` and the version, written as decimal digits, as
`profile_version`; both are taken from the profile that rendered the prompt, never
supplied by the caller. A take made under a receipt therefore names the exact
profile it came from.

Raise a profile's `version` by one in the same change as any edit that can alter
rendered output or a limit: `dialect`, `identity_from_reference`, `timed`,
`max_chars`, the order, names or types of `inputs`, and `mention_refs`. A change in
the renderer itself is tracked by the render contract version, not by profile
versions. Do not raise it for `label` or `aliases`, or for an edit to a comment.
Regenerating profiles from the provider manifests keeps the versions
already in the files; a profile the file does not have yet starts at 1.

### Reference rules in a profile

Each entry of `inputs` says, beyond its `name` and `type`, what the port is for
and how many assets it takes. The renderer reads none of it, so these fields never
change a prompt; a host reads them to decide which reference goes to which port.

- `role`: `first_frame`, `last_frame`, `reference_image`, `reference_video`,
  `reference_audio` or `generic`. The set is the roles the provider manifests state,
  by a `frame_position`, a reference role token (Kling's `refer_image` and
  `feature_video` map to the reference roles), Veo's `ref_kind: ASSET`, or the
  manifest's own `prompt_profile.reference_input`. `generic` means the source does
  not say; a host wires nothing to such a port on its own. No source separates
  identity from style or names a mask, so those roles do not exist.
- `min_count`, `max_count`: the manifest's cardinality. `max_count` is never
  exceeded; null means the profile declares no maximum (every shipped port declares
  one).
- `ordered`: the model addresses the port's assets by position (`@Image1`), so wire
  order is part of the prompt. True exactly for the ports a `mention_refs` rule names.
- `guidance`: `camera_motion` on a reference video port the manifest says may carry
  the camera move.

All five are additive and optional. They were added to the shipped profiles without
changing any rendered prompt or `max_chars`, so no profile's `version` was raised.
After a profile is released, an edit that changes a port's `role`, `max_count` or
`min_count` changes how many references a host wires and so the prompt: raise
`version` then.

## Direction: the canonical form

The Direction schema describes the canonical form of a document. The reference
reader is more tolerant of documents written by AI hosts: before it validates, it
folds case, spaces, hyphens and underscores in enum values and maps a short list
of unambiguous synonyms onto them (`Mid-ground`, `MIDDLE GROUND` and `mid` all
become `midground`). That normalisation is a documented pre-validation step, not
part of the contract. A writer emits the canonical spelling; a port that wants the
same tolerance applies the same step first and then validates against
`direct/direction.schema.json`. Scalars are not part of the tolerance: a string is
not a number (`"4.5"`), `1` is not a boolean and `true` is not a number.

## What a schema cannot say

Some rules need more than one field or more than one document and live in the
operations and models, not in the schema. The server enforces each of them, and a
writer should respect them too. Each schema also notes them in its `$comment`.

Direction (`direct/direction.schema.json`):

- From `direction_version` 2, every `audio.dialogue[].who` is the `id` of a `cast`
  member. The schema only requires a non-empty `who`.
- `cast[].id` values are unique. The schema cannot require uniqueness by one key.
- A beat does not both activate and suppress the same facial action (`au`) at the
  same `timing` and `laterality`.

Model profile (`direct/model-profile.schema.json`):

- `inputs[].name` values are unique within a profile.
- Every port named by a `mention_refs[].ports` entry is one of the profile's
  declared `inputs`.
- A port's `min_count` does not exceed its `max_count`.
- At most one input has role `first_frame` and at most one `last_frame`.
- Every port a mention rule names has `ordered` true. The model does not enforce
  this; the shipped profiles are tested for it.

Ledger:

- Which fields must be set in which work-order state (`assignee` and
  `lease_expires_at` while working, `take_id` once recorded, `close_reason` once
  closed).
- A receipt reference of kind `take` names its `take_id` and one of kind `asset`
  does not.
