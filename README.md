# storyteller-kit

The open client side of **9miho Storyteller**: the contracts, host skills and
local tools an AI host needs to work with the hosted Storyteller service.

9miho Storyteller keeps a team's story as data (the Canon: characters, places,
props, scenes and Moments, with their revisions) and the production state of
every Moment (work orders, takes, reviews). The host (Claude Desktop, Claude
Code, ChatGPT, or any MCP client) is the agent: it reads the story, writes a
Direction, generates with its own connectors (or just writes text), checks its
result, and sends it back. Only people approve or reject.

This repository holds everything on the client side of that boundary. The
server is not here.

## What is in this kit

| Path | What it is |
|---|---|
| `schemas/mcp/` | The MCP tool contract: one file per tool (33 tools), with the tool profiles it is listed in (`guided`, `granular`), its annotations, and its input and output JSON Schemas exactly as the server lists them. |
| `schemas/api/` | The HTTP API contract the team's web app uses, one file per route. People's decisions (approve, reject, pick, restore, ...) live only here, never in the MCP tools. |
| `schemas/direct/` | The provider-neutral Direction document and the model-profile document. |
| `schemas/ledger/` | The ledger records a host reads or writes: work order, take, render receipt, submission, self-check, the `story_step` answer, and the shared enumerations. |
| `profiles/` | The baseline model profiles (54 profiles in 14 provider families): dialect, reference ports, mention rules and prompt limits per model and mode. Pure data; contributions welcome. |
| `skills/storyteller/` | A host skill stub: how to connect to the hosted MCP server and follow `storyteller_start` / `story_step`. |
| `tools/take-qc/` | A local, model-free first pass over generated video takes: format, motion, camera, cuts and dissolves, plus a review packet (frames, crops, contact sheets) for the host model to look at. |
| `fixtures/qc/` | The generic take-label schema used to measure a take checker against a person's labels. |

See [`schemas/README.md`](schemas/README.md) for identifiers, versioning and the
rules a schema cannot express.

## What is not here

The Storyteller server is closed source and runs as a hosted service: the story
core, the prompt renderer and its craft material, the work ledger, the media
gateway, tenancy, and the tuned profiles. The contracts here are what that
server serves and accepts; they are enough to write a host integration, not to
run the service.

## Connecting a host

Storyteller is a remote MCP server with OAuth sign-in. Add it as a custom
connector (Claude, ChatGPT) or an HTTP MCP server (Claude Code) with the
endpoint published at release, sign in, then ask the host to call
`storyteller_start` and follow it. [`skills/storyteller/SKILL.md`](skills/storyteller/SKILL.md)
has the details. Hosts without a skill system work from the server's own
instructions and the next action each `story_step` returns.

Generation is never done by Storyteller. The host uses its own connectors
(for example a ComfyUI or Higgsfield MCP server), and Storyteller renders the
prompt for the actual generation model through a model profile. Text output
(prose, screenplay) needs no generation at all.

## take-qc

take-qc runs on the machine where the takes are. It measures what needs no
model and prepares what the host model should look at; it never decides on
its own and never calls a generator.

```
cd tools/take-qc
python -m pip install -e ".[vision,dev]"     # numpy + OpenCV for the vision items; ffmpeg/ffprobe on PATH
take-qc check  take.mp4 --checklist checklist.json --direction direction.json --out result.json --frames-dir frames/
take-qc merge  result.json answers.json --out final.json
python -m pytest tests
```

The full usage, thresholds and limits are in
[`tools/take-qc/README.md`](tools/take-qc/README.md). Without numpy and OpenCV
the format, record and merge items still work and the vision tests are skipped.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The names
"9miho" and "Kumiho" and their logos are trademarks and are not licensed under
this license.

## 한국어 안내

storyteller-kit은 **9miho Storyteller**의 공개 클라이언트 쪽입니다. 호스트(Claude,
ChatGPT 등 MCP 클라이언트)가 호스팅된 스토리텔러 서비스와 함께 일하는 데 필요한
툴 계약(`schemas/mcp`), HTTP API 계약(`schemas/api`), Direction과 모델 프로필
스키마, 기본 모델 프로필(`profiles/`), 호스트용 스킬 스텁(`skills/`), 그리고 로컬
도구 take-qc를 담고 있습니다.

서버(스토리 코어, 프롬프트 렌더러, 작업 원장, 미디어 게이트웨이, 테넌시)는 이
리포에 없고 호스팅 서비스로만 운영됩니다. 생성은 호스트가 자기 커넥터로 하고,
승인과 거절은 사람만 합니다.

take-qc는 생성된 영상 테이크를 모델 없이 먼저 측정(형식, 움직임, 카메라, 컷과
디졸브)하고, 호스트 모델이 직접 볼 프레임·크롭·접촉 시트를 준비합니다. 사용법은
`tools/take-qc/README.md`에 있습니다. 라이선스는 Apache-2.0입니다.
