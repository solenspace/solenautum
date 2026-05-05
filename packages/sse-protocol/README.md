# @autumn/sse-protocol

Single source of truth for Autumn's multiplexed SSE event contract.

`schema.json` is the authoritative shape. Both the TypeScript types
consumed by `apps/web` and the pydantic v2 models consumed by
`apps/api` are generated from it via quicktype:

```sh
pnpm --filter @autumn/sse-protocol generate
```

The `generated/` tree is committed to git. Codegen runs locally when
the schema changes; the diff is reviewed in PR alongside the schema
diff. Hand edits to `generated/**` are forbidden — regenerate.

Consumers:

- `apps/web` imports the discriminated union via the workspace dep
  `@autumn/sse-protocol`.
- `apps/api` imports the pydantic models via a uv path dep on the
  generated `autumn-sse-protocol` Python sub-package
  (`generated/python/`).

The runtime that emits these events (per-mission ring buffer, single
queue, `Last-Event-ID` resume) lives in Spec 07's
`apps/api/app/sse.py`. Spec 06 (this package) ships only the schema,
the generated models, and the round-trip tests that pin them.
