# Contributing

Thanks for helping. Issues and pull requests are welcome.

- **Model profiles** (`profiles/`): a new model or mode, or a corrected port,
  limit or mention rule. Each file must validate against
  `schemas/direct/model-profile.schema.json` (the `profile_file` form). Raise a
  profile's `version` with any edit that can change a rendered prompt; the rules
  are in `schemas/README.md`.
- **take-qc** (`tools/take-qc/`): keep it model-free and standalone (stdlib,
  optional numpy and OpenCV, ffmpeg). Add a test with every change and run
  `python -m pytest tools/take-qc/tests`.
- **Schemas** (`schemas/mcp/`, `schemas/api/`): these are generated from the
  hosted server. Open an issue rather than editing them by hand.

Never include media, credentials, tokens, or host paths. Use path variables
such as `${QC_ROOT}` in anything you share.

By submitting a contribution you agree that it is licensed under the Apache
License, Version 2.0.
