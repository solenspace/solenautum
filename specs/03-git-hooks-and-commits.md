# 03 — git-hooks-and-commits

## Goal

Wire Lefthook to enforce code quality and commit discipline before
changes leave the local machine. Three hooks fire automatically:
`pre-commit` (Biome + ruff on staged files), `pre-push`
(`turbo typecheck` + `turbo test`), and `commit-msg` (commitlint
with `@commitlint/config-conventional`). After this spec, a fresh
`git clone && pnpm install` installs hooks automatically, and broken
commits cannot land in local history.

## Dependencies

- `specs/01-monorepo-skeleton.md` — workspace structure
- `specs/02-linting-and-formatting.md` — Biome, ruff, mypy, and
  the `lint` / `format:check` / `typecheck` / `test` Turbo tasks
  that the hooks invoke

## Design Decisions

- **Lefthook** as the hook runner — single binary, fast, language-
  agnostic, one YAML config. Installed via `pnpm add -DwE lefthook`
  (not the standalone download) so contributors don't need a
  separate install step. Lefthook's npm package ships the Go binary
  and works identically.
- **Three hooks, no more.** `pre-commit`, `pre-push`, `commit-msg`.
  No `post-merge`, no `post-checkout`, no `prepare-commit-msg` —
  hooks are friction; we add them only when proven necessary.
- **`pre-commit` runs only on staged files** via Lefthook's
  `{staged_files}` expansion. Biome and ruff both accept file lists,
  so this is fast and avoids re-checking the whole tree on every
  commit.
- **`pre-push` runs the full `turbo typecheck` + `turbo test`.**
  Partial-file type checking is unreliable; running the full task
  graph at push time is the right friction-budget. Turbo's cache
  makes the second push of the same SHA near-instant.
- **`commit-msg` uses commitlint with
  `@commitlint/config-conventional`** — Conventional Commits is the
  baseline; we add a custom `scope-enum` covering our actual
  workspaces.
- **Custom scopes** are an explicit list: `web`, `api`,
  `sse-protocol`, `repo`, `specs`, `context`, `claude`, `deps`.
  Free-form scopes are rejected. New scopes require updating
  `commitlint.config.mjs` deliberately.
- **Auto-install on first `pnpm install`** via a root `prepare`
  script that runs `lefthook install`. A fresh clone wires hooks
  with no extra step — there is no "did you remember to run X?".
- **Hooks run locally only.** CI mirrors them in a separate
  workflow (deferred until after this spec). Hooks never auto-fix;
  if `biome format --write` would change a file, the hook fails
  and tells the developer to format-then-commit.
- **No `--no-verify` allowed in normal flow.** This is a
  social/code-review rule, not enforceable. The
  `ai-workflow-rules.md` already mandates "Never skip hooks
  unless explicitly requested" for the AI agent.

References:
- `context/code-standards.md` — General principles
- `context/ai-workflow-rules.md` — Verification gates, "Before
  Moving to the Next Unit"

## Implementation

### A. Install dependencies

From the repo root:

```bash
pnpm add -DwE lefthook @commitlint/cli @commitlint/config-conventional
```

Verify versions:

- `lefthook` ≥ 1.10
- `@commitlint/cli` ≥ 19
- `@commitlint/config-conventional` ≥ 19

### B. Auto-install on `pnpm install`

#### `package.json` — add `prepare` script

```json
{
  "scripts": {
    "prepare": "lefthook install"
  }
}
```

This runs after every `pnpm install`. Lefthook's `install` is
idempotent — a no-op if hooks are already wired. Contributors who
clone the repo and run `pnpm install` get hooks for free; no
mention in the README needed.

### C. `lefthook.yml`

At repo root:

```yaml
# Lefthook configuration — gates code quality before changes leave
# the local machine. See specs/03-git-hooks-and-commits.md for the
# rationale behind each hook.

assert_lefthook_installed: true

pre-commit:
  parallel: true
  jobs:
    - name: biome-staged
      run: pnpm exec biome check --write --no-errors-on-unmatched --files-ignore-unknown=true {staged_files}
      stage_fixed: true
      glob: "*.{ts,tsx,js,jsx,json,jsonc}"

    - name: ruff-lint-staged
      root: apps/api
      run: uv run ruff check --fix {staged_files}
      stage_fixed: true
      glob: "apps/api/**/*.py"

    - name: ruff-format-staged
      root: apps/api
      run: uv run ruff format {staged_files}
      stage_fixed: true
      glob: "apps/api/**/*.py"

pre-push:
  parallel: false
  jobs:
    - name: typecheck
      run: pnpm turbo run typecheck

    - name: test
      run: pnpm turbo run test

commit-msg:
  jobs:
    - name: commitlint
      run: pnpm exec commitlint --edit {1}
```

Notes:

- **`pre-commit` jobs run in parallel** — Biome and ruff don't
  contend for files (different languages).
- **`stage_fixed: true`** restages the files Biome / ruff fixed so
  the formatted version is what gets committed. This is the only
  place hooks auto-mutate code; pre-push never modifies files.
- **`glob:` filters limit each job's `{staged_files}` expansion**
  to its language. A commit that only touches `.md` files runs no
  jobs and passes through.
- **`pre-push` runs sequentially** — typecheck before test (fail
  fast on type errors before the slower test suite).
- **`assert_lefthook_installed: true`** — if a contributor's hooks
  drifted (e.g., they ran `git config core.hooksPath` manually),
  Lefthook complains loudly instead of silently failing.

### D. `commitlint.config.mjs`

At repo root:

```js
/** @type {import('@commitlint/types').UserConfig} */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",     // new user-facing feature
        "fix",      // bug fix
        "perf",     // performance improvement (no behavior change)
        "refactor", // code change that neither fixes nor adds
        "docs",     // documentation only (incl. context/, specs/)
        "test",     // adding or updating tests
        "build",    // build system, deps, package manager
        "ci",       // CI configuration
        "chore",    // tooling, configs, no production code
        "style",    // formatting only (rare — formatter runs auto)
        "revert",   // reverts a previous commit
      ],
    ],
    "scope-enum": [
      2,
      "always",
      [
        "web",          // apps/web
        "api",          // apps/api
        "sse-protocol", // packages/sse-protocol
        "repo",         // root tooling, monorepo config
        "specs",        // specs/
        "context",      // context/
        "claude",       // .claude/, .agents/, agents, skills
        "deps",         // dependency bumps
      ],
    ],
    "scope-empty": [2, "never"],
    "subject-case": [2, "always", "lower-case"],
    "subject-empty": [2, "never"],
    "subject-full-stop": [2, "never", "."],
    "header-max-length": [2, "always", 72],
    "body-leading-blank": [2, "always"],
    "footer-leading-blank": [2, "always"],
  },
};
```

Examples that **pass**:

- `feat(web): add mission lane card with tier badge`
- `fix(api): release browser semaphore on cancellation`
- `chore(repo): bump turbo to 2.4.0`
- `docs(specs): draft 04-clerk-auth-and-security-foundation`

Examples that **fail**:

- `Added the lane card.` — missing type, missing scope, capital A,
  trailing stop.
- `feat: add lane card` — missing scope.
- `feat(frontend): add lane card` — `frontend` is not in
  `scope-enum`.
- `feat(web): Add Mission Lane Card` — subject case violation.

### E. Update `.gitignore`

Add Lefthook's local cache directory if not present:

```
# Lefthook
.lefthook-local.yml
```

`.lefthook-local.yml` is the per-developer override file (Lefthook
reads it if present). It must never be committed.

### F. Smoke-test the hooks

Once the configs are in place, verify each hook fires:

1. `git checkout -b spec-03-smoke-test`
2. Touch a TS file with a deliberate format violation, stage,
   commit. Pre-commit should auto-fix and stage; commit-msg
   validates. Confirm the commit lands with the formatted version.
3. Touch a Python file with an unused import, stage, commit. ruff
   removes the import (`--fix`); commit lands clean.
4. Run `git commit --allow-empty -m "garbage"` — commit-msg
   rejects with a clear error.
5. Run `git commit --allow-empty -m "feat(unknown-scope): test"` —
   rejected with `scope must be one of ...`.
6. Stage a file that introduces a TS error, commit (passes
   pre-commit), then `git push` to a tracking branch. pre-push
   `typecheck` should fail and abort the push.
7. `git checkout main && git branch -D spec-03-smoke-test` — clean
   up.

### G. Order of operations

1. Install Lefthook + commitlint per section A.
2. Add the `prepare` script per section B.
3. Run `pnpm install` to trigger `prepare` and install hooks.
4. Write `lefthook.yml` per section C.
5. Write `commitlint.config.mjs` per section D.
6. Update `.gitignore` per section E.
7. Run `lefthook validate` to confirm the YAML parses.
8. Smoke-test per section F. Fix any hook misconfiguration.
9. Run the verification block.

## Out of Scope

- **CI / GitHub Actions** — separate spec after this one. CI mirrors
  Spec 02's `format:check` + `lint` + Spec 02's `typecheck` +
  `test`, plus `commitlint` over the PR's commits via
  `wagoid/commitlint-github-action` or equivalent. Not part of
  Spec 03 because hooks come first; CI is the second-line defense.
- **Changelog generation, semantic-release** — only useful when
  publishing. Autumn doesn't publish; we add it if/when that
  changes.
- **Pre-commit `format:write` on the entire tree** — only staged
  files. Whole-tree formatting belongs in `turbo run format`,
  invoked manually.
- **Branch-name enforcement** (e.g., `feat/...` prefix) — over-
  engineering for a one-developer repo today. Add later if
  contributor onboarding makes it useful.
- **Co-author / sign-off requirements** — not enforced by hook.
- **`prepare-commit-msg` template** — Conventional Commits is
  enough scaffolding; an extra template would be friction without
  payoff.

## Files

### Create

- `lefthook.yml`
- `commitlint.config.mjs`

### Edit

- `package.json` — add devDeps (`lefthook`,
  `@commitlint/cli`, `@commitlint/config-conventional`); add
  `prepare` script
- `.gitignore` — append `.lefthook-local.yml`

### Protected (do not touch)

- `biome.json`, `pyproject.toml` — owned by Spec 02; this spec
  only invokes the commands they configure
- `tsconfig.base.json`, all `tsconfig.json` — owned by Spec 01/02
- `apps/`, `packages/` — no source-code changes from this spec
- `CLAUDE.md`, `AGENTS.md`, `context/**`, `.claude/**`,
  `.agents/**`, `specs/tutorial.md`

## Verification

Run from the repo root.

- `pnpm install` exits 0 and the final lines include
  `lefthook installed`.
- `pnpm exec lefthook version` prints `1.x.x`.
- `pnpm exec commitlint --version` prints `19.x.x`.
- `pnpm exec lefthook validate` exits 0.
- `cat .git/hooks/pre-commit` shows a Lefthook-generated wrapper
  script (proof hooks installed).
- `cat .git/hooks/pre-push` and `cat .git/hooks/commit-msg`
  similarly.
- Empty-tree commit attempt with bad message:
  `git commit --allow-empty -m "garbage"` exits non-zero.
- Empty-tree commit with good message:
  `git commit --allow-empty -m "chore(repo): smoke test"`
  exits 0.
- Reset that smoke commit: `git reset --hard HEAD~1`.

Manual:

- Make a deliberate Biome violation (bad quote style) in a TS
  file, stage, commit. Hook auto-formats; commit lands clean.
- Revert.
- Make a deliberate ruff violation (unused import) in a Python
  file, stage, commit. Hook removes the import; commit lands clean.
- Revert.
- Stage a TS file that breaks the type checker. Pre-commit passes
  (it doesn't run typecheck). `git push` triggers pre-push and
  fails with the typecheck error. Reset.

## Done when

- [ ] Every Verification line passes.
- [ ] All three smoke-test scenarios in section F pass.
- [ ] No invariant in `context/architecture.md` violated.
- [ ] `context/progress-tracker.md` updated: move Spec 03 to
  "Completed"; promote Spec 04 to "In Progress"; update
  "Current Goal".
- [ ] `turbo run lint && turbo run format:check && turbo run typecheck && turbo run test && turbo run build`
  exits 0.
- [ ] A new contributor running `git clone && pnpm install` ends
  up with hooks installed without any extra step.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships no scraping behavior. Its contribution to scrape
reliability is **enforcement of the type-safety and lint
guarantees added in Spec 02 at the earliest possible moment** —
before code leaves the developer's machine. When Spec 07 adds the
first scrape tool, a typo in a Pydantic field name fails the
pre-push gate; a forgotten `await` on a Scrapling call fails the
ruff `ASYNC` rule at pre-commit. Local hooks catch it; CI catches
what the local hooks miss; production sees clean code only.
