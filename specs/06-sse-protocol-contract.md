# 06 — sse-protocol-contract

## Goal

Define the multiplexed SSE event contract once, in JSON Schema, and
generate both TypeScript and pydantic v2 models from it via
quicktype. After this spec, every event the api emits and every
event the web consumes goes through the same shape: `{type, content,
mission_id, task_id?, seq}`. The spec also pins the per-mission ring
buffer and `Last-Event-ID` resume protocol so Spec 07 (api emitter)
and the future web hook (Spec 08) both implement them identically.

## Dependencies

- `specs/01-monorepo-skeleton.md` — `packages/sse-protocol/` exists
  as an empty workspace member with a placeholder `index.ts`
- `specs/02-linting-and-formatting.md` — Biome ignores
  `packages/sse-protocol/generated/**` so codegen output is not
  linted; the manual schema and scripts are
- `specs/05-persistence-layer.md` — `apps/api/pyproject.toml` is
  ready to accept a path-based dep on the generated Python package

## Design Decisions

- **Single source of truth**: `packages/sse-protocol/schema.json`.
  Both TS and Python models are generated from it. Any change to
  the event shape changes the schema first; codegen runs second;
  consumers update third.
- **Codegen tool**: **quicktype** — one CLI, both targets. The
  Python output is slightly less idiomatic than
  `datamodel-code-generator`'s, but consistency across both
  targets and a single dependency wins.
- **`apps/api` consumes the generated Python package via uv path
  dep**. `packages/sse-protocol/generated/python/` is a tiny
  editable package (`pyproject.toml` + `__init__.py` + generated
  models). `apps/api/pyproject.toml` adds it as a path dep so
  imports stay clean (`from autumn_sse_protocol import ...`) and
  re-running codegen does not require reinstalling.
- **`apps/web` consumes the generated TS via workspace import**.
  `packages/sse-protocol/package.json` exports
  `./generated/types.ts`; web imports `from "@autumn/sse-protocol"`.
- **Versioning**: single `$id` URL,
  `https://autumn.local/sse/event.json`. Schema evolution is
  field-additive within the closed monorepo; a breaking change
  (renaming a type, removing a field) requires a single spec that
  updates schema, both apps, and tests in one PR. No `/v1`/`/v2`
  juggling.
- **Strict unknown-type rejection**: both producer (api emits
  through a pydantic-validated emitter) and consumer (web parses
  via the generated discriminated union; unknown `type` throws)
  fail loud. Drift surfaces immediately, not silently.
- **Discriminated union by `type`**: TS gets a clean
  `SseEvent =` union; pydantic gets a `RootModel[Union[...]]` with
  `discriminator='type'`.
- **Event types defined in this spec** (the locked set as of
  this contract):
  - `token` — streamed agent text
  - `tool_start` — agent calls a tool
  - `tool_end` — agent receives a tool result
  - `task_start` — a per-URL task begins
  - `task_end` — a per-URL task terminates
  - `url_discovered` — Tavily returned a URL during discovery
  - `selector_recovered` — adaptive selector matched and was
    re-used
  - `done` — mission terminates
  - `error` — mission-level or task-level error
- **`seq` is monotonic per `mission_id`**, starting at 0. The api
  assigns `seq`; the web reads it for resume.
- **Ring buffer** (specified here, implemented in Spec 07): per
  active mission, last 200 events held in-memory keyed by
  `mission_id`; evicted when mission terminates plus a 60s grace
  window.
- **`Last-Event-ID` resume protocol**: SSE clients reconnecting
  send `Last-Event-ID: <seq>` (the standard SSE header). The api
  parses the int, looks up the mission's ring buffer, replays
  every event with `seq > Last-Event-ID`, then resumes live
  forwarding. If the buffer has been evicted, the api emits a
  `error` event with `code: "resume_lost"` and closes.

References:
- `context/architecture.md` — Storage Model (SSE ring buffer),
  Invariants 4, 5
- `context/code-standards.md` — TypeScript (single source of
  truth), Python (pydantic v2 at boundaries)

## Implementation

### A. Package layout (final state after this spec)

```
packages/sse-protocol/
├── README.md
├── package.json
├── schema.json                     ← source of truth
├── tsconfig.json
├── biome.json                      ← Biome local override (ignore generated/)
├── scripts/
│   ├── generate.ts
│   └── postprocess-python.ts
├── tests/
│   └── round-trip.test.ts
└── generated/
    ├── types.ts                    ← TS output (committed)
    ├── index.ts                    ← re-exports types.ts
    └── python/
        ├── pyproject.toml
        ├── README.md
        └── autumn_sse_protocol/
            ├── __init__.py
            └── models.py            ← pydantic output (committed)
```

The `generated/` tree is committed to git. We do not generate at
build time on every machine — codegen runs locally when the
schema changes; the output is reviewed in PR alongside the schema
diff.

### B. `packages/sse-protocol/schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://autumn.local/sse/event.json",
  "title": "SseEvent",
  "description": "Multiplexed SSE event for Autumn missions.",
  "oneOf": [
    { "$ref": "#/$defs/Token" },
    { "$ref": "#/$defs/ToolStart" },
    { "$ref": "#/$defs/ToolEnd" },
    { "$ref": "#/$defs/TaskStart" },
    { "$ref": "#/$defs/TaskEnd" },
    { "$ref": "#/$defs/UrlDiscovered" },
    { "$ref": "#/$defs/SelectorRecovered" },
    { "$ref": "#/$defs/Done" },
    { "$ref": "#/$defs/SseError" }
  ],
  "$defs": {
    "BaseEvent": {
      "type": "object",
      "required": ["type", "content", "mission_id", "seq"],
      "properties": {
        "mission_id": { "type": "string", "format": "uuid" },
        "task_id":    { "type": "string", "format": "uuid" },
        "seq":        { "type": "integer", "minimum": 0 }
      }
    },
    "Token": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type":    { "const": "token" },
            "content": { "type": "string", "description": "Streamed text fragment" }
          }
        }
      ]
    },
    "ToolStart": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type": { "const": "tool_start" },
            "content": {
              "type": "object",
              "required": ["tool_name", "args"],
              "properties": {
                "tool_name": { "type": "string" },
                "args":      { "type": "object", "additionalProperties": true }
              }
            }
          }
        }
      ]
    },
    "ToolEnd": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type": { "const": "tool_end" },
            "content": {
              "type": "object",
              "required": ["tool_name", "duration_ms", "ok"],
              "properties": {
                "tool_name":   { "type": "string" },
                "duration_ms": { "type": "integer", "minimum": 0 },
                "ok":          { "type": "boolean" },
                "summary":     { "type": "string" }
              }
            }
          }
        }
      ]
    },
    "TaskStart": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type": { "const": "task_start" },
            "content": {
              "type": "object",
              "required": ["url", "tier"],
              "properties": {
                "url":  { "type": "string", "format": "uri" },
                "tier": { "enum": ["http", "stealth", "dynamic"] }
              }
            }
          }
        }
      ]
    },
    "TaskEnd": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type": { "const": "task_end" },
            "content": {
              "type": "object",
              "required": ["status"],
              "properties": {
                "status":      { "enum": ["succeeded", "failed", "cancelled"] },
                "latency_ms":  { "type": "integer", "minimum": 0 },
                "snapshot_key":{ "type": "string" },
                "preview":     { "type": "string", "description": "First N chars of parsed markdown" }
              }
            }
          }
        }
      ]
    },
    "UrlDiscovered": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "properties": {
            "type": { "const": "url_discovered" },
            "content": {
              "type": "object",
              "required": ["url", "source"],
              "properties": {
                "url":    { "type": "string", "format": "uri" },
                "source": { "type": "string", "description": "Provider name (e.g. tavily)" },
                "score":  { "type": "number", "minimum": 0, "maximum": 1 }
              }
            }
          }
        }
      ]
    },
    "SelectorRecovered": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "required": ["task_id"],
          "properties": {
            "type": { "const": "selector_recovered" },
            "content": {
              "type": "object",
              "required": ["domain", "purpose", "hit_count"],
              "properties": {
                "domain":    { "type": "string" },
                "purpose":   { "type": "string" },
                "hit_count": { "type": "integer", "minimum": 1 }
              }
            }
          }
        }
      ]
    },
    "Done": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "properties": {
            "type": { "const": "done" },
            "content": {
              "type": "object",
              "required": ["mission_status"],
              "properties": {
                "mission_status": { "enum": ["succeeded", "failed", "cancelled"] },
                "cost_cents":     { "type": "integer", "minimum": 0 }
              }
            }
          }
        }
      ]
    },
    "SseError": {
      "allOf": [
        { "$ref": "#/$defs/BaseEvent" },
        {
          "type": "object",
          "properties": {
            "type": { "const": "error" },
            "content": {
              "type": "object",
              "required": ["code", "message"],
              "properties": {
                "code":    { "type": "string", "description": "Machine code, e.g. resume_lost, ssrf_blocked, robots_disallowed, site_not_supported" },
                "message": { "type": "string" }
              }
            }
          }
        }
      ]
    }
  }
}
```

Notes:

- `BaseEvent` factors out `mission_id` and `seq` (always present).
- Per-task events declare `task_id` as required in the inner
  variant; mission-level events (`url_discovered`, `done`,
  `error`) leave `task_id` optional.
- `error.content.code` is an open-ended string in the schema but
  the code-standards rule is that codes are added to a closed
  enum-like list documented inline; new codes ride a spec.

### C. `packages/sse-protocol/package.json`

```json
{
  "name": "@autumn/sse-protocol",
  "version": "0.0.0",
  "private": true,
  "main": "./generated/index.ts",
  "types": "./generated/index.ts",
  "exports": {
    ".": "./generated/index.ts",
    "./schema.json": "./schema.json"
  },
  "scripts": {
    "generate": "tsx scripts/generate.ts",
    "test": "vitest run",
    "lint": "biome lint .",
    "format": "biome format --write .",
    "format:check": "biome format ."
  },
  "devDependencies": {
    "@types/node": "^22",
    "ajv": "^8",
    "ajv-formats": "^3",
    "quicktype": "^23",
    "tsx": "^4",
    "vitest": "^2"
  }
}
```

### D. Codegen script — `packages/sse-protocol/scripts/generate.ts`

```ts
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(__dirname, "..");
const schema = resolve(root, "schema.json");
const generated = resolve(root, "generated");
const generatedPython = resolve(generated, "python", "autumn_sse_protocol");

mkdirSync(generated, { recursive: true });
mkdirSync(generatedPython, { recursive: true });

// --- TypeScript ----------------------------------------------------------

execSync(
  `pnpm exec quicktype --src-lang schema --lang ts --just-types --no-runtime-typecheck --top-level SseEvent ${schema} -o ${resolve(
    generated,
    "types.ts",
  )}`,
  { stdio: "inherit", cwd: root },
);

writeFileSync(
  resolve(generated, "index.ts"),
  `export * from "./types";\nexport { default as schema } from "../schema.json";\n`,
);

// --- Python --------------------------------------------------------------

execSync(
  `pnpm exec quicktype --src-lang schema --lang python --pydantic-base-model --python-version 3.12 --top-level SseEvent ${schema} -o ${resolve(
    generatedPython,
    "models.py",
  )}`,
  { stdio: "inherit", cwd: root },
);

writeFileSync(
  resolve(generatedPython, "__init__.py"),
  `from .models import *  # noqa: F401, F403\n`,
);

console.log("✓ generated TS and Python from schema.json");
```

Quicktype's pydantic output uses pydantic v1 syntax by default; the
`postprocess-python.ts` script (next) rewrites it to v2 idioms.

### E. Postprocess pydantic output — `packages/sse-protocol/scripts/postprocess-python.ts`

quicktype's pydantic output is correct but uses pre-v2 patterns
(`BaseModel.Config`, `from typing import List`). Run a small
rewriter to bring it to pydantic v2 + modern typing.

```ts
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const file = resolve(__dirname, "..", "generated", "python", "autumn_sse_protocol", "models.py");
let src = readFileSync(file, "utf8");

// Replace v1 idioms with v2.
src = src
  .replace(/from typing import (List|Dict|Optional|Tuple)/g, () => "")
  .replace(/List\[/g, "list[")
  .replace(/Dict\[/g, "dict[")
  .replace(/Tuple\[/g, "tuple[")
  .replace(/Optional\[([^\]]+)\]/g, "$1 | None")
  .replace(/class Config:/g, "model_config = ConfigDict()")
  .replace(/from pydantic import BaseModel/g, "from pydantic import BaseModel, ConfigDict, Field");

// Prepend a top-of-file docstring + `from __future__`.
src = `"""Generated from packages/sse-protocol/schema.json. Do not edit by hand."""\nfrom __future__ import annotations\n\n${src}`;

writeFileSync(file, src);
console.log("✓ postprocessed python output to pydantic v2");
```

Wire it into `generate.ts` after the Python codegen step:

```ts
execSync(`pnpm exec tsx ${resolve(__dirname, "postprocess-python.ts")}`, { stdio: "inherit", cwd: root });
```

### F. Generated Python sub-package — `packages/sse-protocol/generated/python/pyproject.toml`

```toml
[project]
name = "autumn-sse-protocol"
version = "0.0.0"
description = "Generated pydantic v2 models for Autumn SSE protocol."
requires-python = ">=3.12"
dependencies = ["pydantic>=2.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["autumn_sse_protocol"]
```

### G. Wire `apps/api` to the path dep

#### `apps/api/pyproject.toml` — append

```toml
[tool.uv.sources]
autumn-sse-protocol = { path = "../../packages/sse-protocol/generated/python", editable = true }

[project]
dependencies = [
  # ... existing deps from spec 04/05 ...
  "autumn-sse-protocol",
]
```

Run `uv sync` from `apps/api/`.

The api now imports event types as:

```python
from autumn_sse_protocol import SseEvent, TaskStart, TaskEnd
```

Spec 07 uses these models in the SSE emitter; they validate at
construction time, so an invalid event raises before it leaves
the api.

### H. Wire `apps/web` to the workspace package

#### `apps/web/package.json` — add dep

```json
{
  "dependencies": {
    "@autumn/sse-protocol": "workspace:*"
  }
}
```

Run `pnpm install` at the repo root. The web side now imports as:

```ts
import type { SseEvent, TaskStart, TaskEnd } from "@autumn/sse-protocol";
```

Spec 08's `use-mission-stream.ts` parses every event into the
`SseEvent` discriminated union; an unknown `type` is an error, not
a warning.

### I. Round-trip test — `packages/sse-protocol/tests/round-trip.test.ts`

```ts
import { describe, expect, test } from "vitest";
import Ajv from "ajv";
import addFormats from "ajv-formats";
import schema from "../schema.json" with { type: "json" };
import type { SseEvent } from "../generated";


const ajv = addFormats(new Ajv({ allErrors: true, strict: true }));
const validate = ajv.compile(schema);


function example<T extends SseEvent>(value: T): T {
  return value;
}


describe("SSE event round-trip", () => {
  test("token event validates", () => {
    const event = example({
      type: "token",
      content: "hello",
      mission_id: "00000000-0000-0000-0000-000000000001",
      task_id:    "00000000-0000-0000-0000-000000000002",
      seq: 0,
    });
    expect(validate(event)).toBe(true);
  });

  test("rejects unknown type", () => {
    const bad = {
      type: "fabricated",
      content: "x",
      mission_id: "00000000-0000-0000-0000-000000000001",
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("rejects missing required mission_id", () => {
    const bad = {
      type: "done",
      content: { mission_status: "succeeded" },
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("rejects task event without task_id", () => {
    const bad = {
      type: "task_start",
      content: { url: "https://example.com/", tier: "http" },
      mission_id: "00000000-0000-0000-0000-000000000001",
      seq: 0,
    };
    expect(validate(bad)).toBe(false);
  });

  test("done event without task_id is fine", () => {
    const event = example({
      type: "done",
      content: { mission_status: "succeeded", cost_cents: 0 },
      mission_id: "00000000-0000-0000-0000-000000000001",
      seq: 5,
    });
    expect(validate(event)).toBe(true);
  });
});
```

Run `cd packages/sse-protocol && pnpm test`.

### J. Python round-trip test — `apps/api/tests/test_sse_protocol.py`

```python
from __future__ import annotations

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from autumn_sse_protocol import SseEvent


MISSION = UUID("00000000-0000-0000-0000-000000000001")
TASK = UUID("00000000-0000-0000-0000-000000000002")


def test_token_validates():
    event = SseEvent.model_validate({
        "type": "token",
        "content": "hello",
        "mission_id": str(MISSION),
        "task_id": str(TASK),
        "seq": 0,
    })
    assert event.root.type == "token"


def test_rejects_unknown_type():
    with pytest.raises(ValidationError):
        SseEvent.model_validate({
            "type": "fabricated",
            "content": "x",
            "mission_id": str(MISSION),
            "seq": 0,
        })


def test_round_trip_json():
    raw = {
        "type": "task_end",
        "content": {"status": "succeeded", "latency_ms": 250},
        "mission_id": str(MISSION),
        "task_id": str(TASK),
        "seq": 7,
    }
    event = SseEvent.model_validate(raw)
    assert json.loads(event.model_dump_json()) == raw
```

### K. Ring-buffer + Last-Event-ID protocol (specification, not implementation)

This section is a **contract**. The implementation lives in Spec 07
(`apps/api/app/sse.py`), enforced by the `sse-streaming-reviewer`
agent.

- **Ring buffer key**: `mission_id` (UUID).
- **Capacity**: 200 events per active mission, FIFO.
- **Eviction**: trigger on mission terminal event (`done` or
  mission-level `error`); evict from memory 60 seconds after the
  terminal.
- **Resume header**: clients reconnecting send the standard SSE
  `Last-Event-ID` header containing the int `seq` of the last
  event they observed. Spec compliance: any decimal integer
  string in the header is parsed; non-integer values trigger an
  immediate `error` event with `code: "resume_lost"` and close.
- **Replay**: on reconnect, the api emits every buffered event
  with `seq > Last-Event-ID` in order, then resumes live
  forwarding. If the buffer no longer contains the requested seq
  (mission terminated > 60s ago, or buffer overflowed), emit
  `error` with `code: "resume_lost"` and close.
- **Per-event SSE id field**: the api emits each event with the
  SSE `id:` field set to the event's `seq`. The browser
  EventSource sets `Last-Event-ID` automatically on reconnect.
- **Heartbeat**: every 15 seconds while a mission is running, the
  api emits an SSE comment line (`: ping\n\n`). Comments are not
  events; they keep proxies and client EventSource buffers alive
  without consuming a `seq`.

## Out of Scope

- **`apps/api/app/sse.py` implementation** — Spec 07. This spec
  ships the contract; Spec 07 enforces it at runtime.
- **`apps/web/.../use-mission-stream.ts` implementation** —
  Spec 08.
- **Compression of long token streams** — premature; the
  schema permits long strings and EventSource handles framing.
- **Multi-mission multiplexing on one connection** — out of
  scope. One SSE connection per mission is the contract.
- **Server push to multiple clients of the same mission** —
  fan-out is one-to-one for MVP.

## Files

### Create

- `packages/sse-protocol/schema.json`
- `packages/sse-protocol/scripts/generate.ts`
- `packages/sse-protocol/scripts/postprocess-python.ts`
- `packages/sse-protocol/tests/round-trip.test.ts`
- `packages/sse-protocol/tsconfig.json` (extends
  `../../tsconfig.base.json`; `module: "ESNext"`,
  `target: "ES2024"`)
- `packages/sse-protocol/biome.json` (local override; ignores
  `generated/`)
- `packages/sse-protocol/generated/types.ts` (generated, committed)
- `packages/sse-protocol/generated/index.ts`
- `packages/sse-protocol/generated/python/pyproject.toml`
- `packages/sse-protocol/generated/python/README.md`
- `packages/sse-protocol/generated/python/autumn_sse_protocol/__init__.py`
- `packages/sse-protocol/generated/python/autumn_sse_protocol/models.py` (generated, committed)
- `apps/api/tests/test_sse_protocol.py`

### Edit

- `packages/sse-protocol/package.json` — replace placeholder with
  the full content from section C
- `packages/sse-protocol/README.md` — update from Spec 01's
  placeholder to the real description
- `apps/api/pyproject.toml` — add `[tool.uv.sources]` block and
  `autumn-sse-protocol` to dependencies
- `apps/web/package.json` — add `@autumn/sse-protocol`
  workspace dep

### Protected (do not touch)

- `packages/sse-protocol/generated/**` — codegen output; regenerate
  via `pnpm --filter @autumn/sse-protocol generate`. Hand-edits
  are forbidden.
- All previous protected files (`apps/api/app/security.py`,
  `apps/api/alembic/versions/*` past migrations).

## Verification

Run from the repo root.

- `pnpm install` succeeds; `@autumn/sse-protocol` shows in
  `apps/web` and the workspace tree.
- `pnpm --filter @autumn/sse-protocol generate` exits 0; both
  `generated/types.ts` and
  `generated/python/autumn_sse_protocol/models.py` materialize.
- The generated TS file imports cleanly in `apps/web`:
  `pnpm --filter @autumn/web exec tsc --noEmit` exits 0.
- `cd apps/api && uv sync` resolves the path dep without errors.
- `pnpm --filter @autumn/sse-protocol test` exits 0 (the four TS
  round-trip cases pass).
- `cd apps/api && uv run pytest tests/test_sse_protocol.py -q`
  exits 0.
- `turbo run lint && turbo run typecheck && turbo run test`
  exits 0 across the whole repo.
- `git status` after codegen shows the generated files cleanly
  diffed (proving they are committed, not gitignored).

Manual:

- Open `packages/sse-protocol/generated/types.ts` and confirm:
  - A discriminated union `SseEvent` exists.
  - Each variant has its own interface with the right
    `type: "..."` literal.
- Open `models.py` and confirm:
  - All variants exist as pydantic v2 `BaseModel` subclasses.
  - The top-level `SseEvent` is a `RootModel` discriminated by
    `type`.
- Modify a field in `schema.json` (e.g., add a new optional
  field to `Token`), run `pnpm --filter @autumn/sse-protocol generate`, and confirm both
  generated files update. Revert.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
- [ ] Both apps reference the contract via the same source — no
  hand-rolled SSE event types anywhere in `apps/web` or
  `apps/api`.
- [ ] `packages/sse-protocol/generated/**` is committed.
- [ ] `context/progress-tracker.md` updated: Spec 06 to "Completed";
  Spec 07 to "In Progress"; Current Goal updated.
- [ ] `sse-streaming-reviewer` agent run on
  `packages/sse-protocol/**` finds zero violations.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

The contract this spec ships is the third-line defense for
reliability. When Spec 07 emits an event that violates the schema
(missing `task_id` on a `task_start`, unknown event type, malformed
seq), pydantic raises at construction time — the bad event never
reaches the SSE writer, never lands in the ring buffer, and never
reaches the web client. When Spec 08 receives an unknown event
type, the discriminated-union parse throws — the user sees a
visible error rather than a silently-dropped UI update.

The cost of strictness is one breaking-change ceremony per schema
mutation: schema → codegen → both apps → tests, in one PR. The
benefit is that drift is impossible: api and web cannot disagree
about what an event looks like, because they both read the same
generated types.
