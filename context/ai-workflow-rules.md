# AI Workflow Rules

Direct instructions to the AI coding agent. These are rules, not
guidelines.

## Approach

Build Autumn incrementally using a spec-driven workflow. The numbered
spec files in `specs/` define the build order and the per-unit
contract (goal, design, implementation, success criteria). Always
implement against the spec — do not infer or invent behavior. The
context files in this folder are read **before** any code change
and remain timeless; the specs define what is built and when.

## Scoping Rules

- Work on one unit at a time.
- Prefer small, verifiable increments over large speculative changes.
- Do not combine unrelated system boundaries in one implementation
  step.
- Do not mix `apps/web/` and `apps/api/` changes in one unit unless
  the unit is explicitly a "contract sync" unit (i.e., one that
  updates `packages/sse-protocol/`).

## When to Split Work

Split an implementation step if it combines:

- UI changes, API changes, and persistence changes in one pass
- A new tool tier added to the agent
- A mutation of the SSE event shape (this always crosses both apps)
- Changes to the concurrency model or the `TaskGroup` runner
- Adding a new LLM provider or modifying the provider chain
- Behavior not clearly defined in the context files or spec

If a change cannot be verified end to end quickly, the scope is
too broad — split it.

## Handling Missing Requirements

- Do not invent product behavior not defined in the context files
  or the unit spec.
- Specifically, never invent: SSE event types, tool names, search
  providers, Clerk claim shapes, LLM provider configs, Postgres
  table or column names, R2 object key formats, or invariants.
- If a requirement is ambiguous, resolve it in the relevant context
  file **before** implementing — and update the file in the same
  commit as the implementation.
- If a requirement is missing, add it as an open question in
  `progress-tracker.md` before continuing. Do not guess.

## Protected Files

Do not modify the following without explicit instruction:

- `apps/web/components/ui/*` — shadcn primitives, managed by the
  shadcn CLI
- `packages/sse-protocol/generated/*` — codegen output, regenerated
  from `schema.json`
- `node_modules/`, `.venv/`, `.next/`, `dist/`, `__pycache__/`
- `apps/api/app/security.py` — SSRF guard, JWT verification, rate
  limiter, robots.txt logic. Changes here require explicit approval
  because the file is load-bearing for invariants 1, 10, 11.
- `alembic/versions/*` after they have been merged — never edit a
  past migration; write a new one.

## Keeping Docs in Sync

Update the relevant context file **before** you finish the unit
that changes:

- An invariant — `architecture.md` first, code second
- System boundaries (a new folder, a renamed module) —
  `architecture.md` and `code-standards.md`
- Storage model (a new column, a new bucket) — `architecture.md`
- Coding conventions or new rules — `code-standards.md`
- A new keyboard shortcut, color token, or layout pattern —
  `ui-context.md`
- Feature scope (in or out) — `project-overview.md`

If the implementation contradicts a context file, the context file
wins. Either revert the implementation or update the context file
deliberately.

**Context files are append-only and timeless.** When implementation
reveals a new invariant, a new boundary, or a new convention, append
to the relevant section; never rewrite past content. The history of
decisions is part of the value. Phase-specific status (current goal,
what's next, what's in progress) lives in `specs/` and
`progress-tracker.md` only — never in the other context files.

## Before Moving to the Next Unit

A unit is complete only when **every** item below is true:

1. The current unit works end to end within its defined scope.
2. No invariant in `architecture.md` was violated. Re-read the
   invariants section and verify each one against the diff.
3. `progress-tracker.md` reflects the completed work, decisions
   made, and any newly surfaced open questions.
4. `turbo typecheck` passes.
5. `turbo test` passes (web Vitest + api pytest).
6. `turbo build` passes.
7. For UI-touching units: a 5-URL mission renders 5 task lanes; the
   SSE `Last-Event-ID` resume works after a forced disconnect; no
   ARIA assertive announcements fired during streaming.
8. For agent-touching units: the Langfuse trace contains every tool
   call, every retry, and any provider switch with `mission_id` /
   `task_id` metadata.
9. For schema-touching units: `packages/sse-protocol/` regenerates
   cleanly and round-trip validation tests pass.

If a unit cannot meet every gate, do not move on. Mark it
`in_progress` in `progress-tracker.md`, document the blocker, and
solve the blocker before starting the next unit.

## Verification Commands

Run from the repo root:

- `turbo typecheck` — TS strict + mypy strict on both apps
- `turbo test` — Vitest (web) + pytest (api)
- `turbo build` — Next.js build + uv sync + Docker build dry-run
- `turbo lint` — `ruff` + ESLint
- `turbo dev` — both apps boot; web on :3000, api on :8000

## Communication Rules

- When a unit is complete, update `progress-tracker.md` in the same
  commit as the unit's last change. Do not let progress and
  implementation drift apart.
- Surface architectural surprises (a library limitation, a free-tier
  cap hit) as a new open question, not as a silent workaround.
- Do not write commentary or summaries inside source files. The
  context files and `progress-tracker.md` are where commentary lives.
