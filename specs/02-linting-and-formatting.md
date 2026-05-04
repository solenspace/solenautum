# 02 — linting-and-formatting

## Goal

Enforce code quality across the monorepo: Biome 2 for JS/TS lint +
format + import sort; ruff for Python lint + format; mypy `--strict`
with the `pydantic.mypy` plugin for Python type checking; strict
TypeScript inherited from `tsconfig.base.json` with no per-app
loosening. After this spec, `turbo lint`, `turbo format`, and
`turbo typecheck` all do real work and exit 0 on a clean tree.

## Dependencies

- `specs/01-monorepo-skeleton.md` — Turbo + pnpm + uv workspaces
  exist; `tsconfig.base.json` is the strict-TS baseline; placeholder
  `lint` / `format` Turbo tasks exist but are no-ops.

## Design Decisions

- **Biome 2.x** owns JS/TS linting, formatting, and import sorting.
  Single `biome.json` at the repo root applies to both `apps/web/`
  and `packages/sse-protocol/`. No Prettier, no ESLint, no
  `eslint-plugin-import` — Biome covers the 90% we need with one
  binary, ~10–20× faster than the ESLint+Prettier combo.
- **Biome rule set**: `linter.rules.recommended: true` plus
  explicit activation of `complexity`, `correctness`, `security`,
  `suspicious`, and `a11y` groups. The `nursery` group is **off**
  at this stage; we cherry-pick rules from it as they stabilize.
- **ruff** owns Python linting, formatting, and import sort. Single
  `[tool.ruff]` block in `apps/api/pyproject.toml`. ruff replaces
  black, isort, flake8, pyupgrade, and pydocstyle in one binary.
- **ruff rule families**: `E`, `F`, `I`, `B`, `C4`, `UP`, `N`,
  `ASYNC`, `S`, `ARG`, `PT`, `SIM`, `RUF` — a comprehensive but
  not paranoid set covering style, errors, imports, bugbear,
  comprehensions, pyupgrade, naming, async correctness, security,
  unused arguments, pytest style, simplifications, ruff-specific.
- **mypy `--strict`** with the `pydantic.mypy` plugin. Strict mode
  is the floor; the plugin gives us pydantic v2 model literal-type
  inference and `model_config` awareness — non-optional given our
  Pydantic AI stack.
- **Strict TypeScript** inherits unchanged from
  `tsconfig.base.json` (set up in Spec 01 with `strict`,
  `noUncheckedIndexedAccess`, `noImplicitOverride`,
  `verbatimModuleSyntax`, `isolatedModules`). Each app's
  `tsconfig.json` extends base; **no app overrides loosen
  strictness**.
- **Editor integration** committed via `.vscode/settings.json` —
  Biome as the default JS/TS formatter, ruff as the default Python
  formatter, format-on-save enabled. JetBrains and other editors
  still get coverage through the Spec 03 pre-commit hook.
- **No CI** in this spec. CI mirrors Spec 03's hooks; that mirror
  arrives after Spec 03 ships.
- **No `eslint-disable` / `# noqa` allowed without a justification
  comment.** This is a code-review rule, not a linter rule —
  noted in `code-standards.md`.

References:
- `context/code-standards.md` — TypeScript, Python sections
- `context/ai-workflow-rules.md` — Verification gates

## Implementation

### A. Repo-root Biome config

#### Install

From the repo root:

```bash
pnpm add -DwE @biomejs/biome
pnpm exec biome init
```

The `init` command creates `biome.json`. **Overwrite it** with the
config in the next step (the generated one is too permissive).

#### `biome.json`

```json
{
  "$schema": "https://biomejs.dev/schemas/2.4.14/schema.json",
  "vcs": {
    "enabled": true,
    "clientKind": "git",
    "useIgnoreFile": true
  },
  "files": {
    "ignoreUnknown": true,
    "includes": [
      "apps/web/**/*.{ts,tsx,js,jsx,json,jsonc}",
      "packages/**/*.{ts,tsx,js,jsx,json,jsonc}",
      "*.{json,jsonc}"
    ],
    "experimentalScannerIgnores": [
      "**/node_modules",
      "**/.next",
      "**/.turbo",
      "**/dist",
      "**/.venv",
      "**/__pycache__",
      "**/generated"
    ]
  },
  "formatter": {
    "enabled": true,
    "indentStyle": "space",
    "indentWidth": 2,
    "lineWidth": 100,
    "lineEnding": "lf"
  },
  "linter": {
    "enabled": true,
    "rules": {
      "recommended": true,
      "complexity": { "recommended": true },
      "correctness": {
        "recommended": true,
        "noUnusedVariables": "error",
        "noUnusedImports": "error",
        "useExhaustiveDependencies": "error"
      },
      "security": { "recommended": true },
      "suspicious": {
        "recommended": true,
        "noConsole": { "level": "warn", "options": { "allow": ["error", "warn"] } }
      },
      "a11y": { "recommended": true },
      "style": {
        "recommended": true,
        "useImportType": "error",
        "useExportType": "error",
        "noNonNullAssertion": "error"
      },
      "performance": { "recommended": true },
      "nursery": { "recommended": false }
    }
  },
  "javascript": {
    "formatter": {
      "quoteStyle": "double",
      "jsxQuoteStyle": "double",
      "trailingCommas": "all",
      "semicolons": "always",
      "arrowParentheses": "always"
    }
  },
  "json": {
    "formatter": {
      "indentWidth": 2,
      "trailingCommas": "none"
    }
  },
  "assist": {
    "enabled": true,
    "actions": {
      "source": {
        "organizeImports": "on"
      }
    }
  }
}
```

Key rule notes:
- `noConsole` is a `warn`, not `error`, with `console.error` /
  `console.warn` allowed — production code should use the structured
  logger but quick debugging shouldn't fail the linter.
- `useExhaustiveDependencies` is the React hooks deps-array check
  (Biome's equivalent of `react-hooks/exhaustive-deps`).
- `useImportType` / `useExportType` enforce `import type` /
  `export type` to keep `verbatimModuleSyntax` happy.
- `noNonNullAssertion` (`x!`) is `error`; if a real case needs it,
  use a typed narrowing helper instead.

#### `.biomeignore`

Not needed — Biome reads `.gitignore` via `vcs.useIgnoreFile`.

### B. Per-app Biome / TS hookup

#### `apps/web/package.json`

Replace the placeholder `lint` / `format` scripts:

```json
{
  "scripts": {
    "lint": "biome lint .",
    "format": "biome format --write .",
    "format:check": "biome format ."
  }
}
```

Other scripts (`dev`, `build`, `typecheck`, `clean`) stay as-is from
Spec 01.

#### `packages/sse-protocol/package.json`

Add the same scripts:

```json
{
  "scripts": {
    "lint": "biome lint .",
    "format": "biome format --write .",
    "format:check": "biome format ."
  }
}
```

`packages/sse-protocol/generated/` will hold codegen output later
(Spec 06); the Biome `experimentalScannerIgnores` rule already
excludes `**/generated` so it does not get linted or formatted.

#### `apps/web/tsconfig.json`

Confirm it extends `../../tsconfig.base.json` with **no
loosening flags**. Allowed app-specific additions: `paths`,
`plugins`, `include`, `exclude`. Forbidden: any field that disables
or weakens a strict flag set in base.

### C. Python linting and formatting (`apps/api/`)

#### Install

From `apps/api/`:

```bash
uv add --dev ruff mypy
```

#### `apps/api/pyproject.toml` — append

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["app", "tests"]

[tool.ruff.lint]
select = [
  "E",     # pycodestyle errors
  "F",     # pyflakes
  "I",     # isort
  "B",     # bugbear
  "C4",    # comprehensions
  "UP",    # pyupgrade
  "N",     # pep8-naming
  "ASYNC", # async correctness
  "S",     # bandit (security)
  "ARG",   # unused arguments
  "PT",    # pytest style
  "SIM",   # flake8-simplify
  "RUF",   # ruff-specific
]
ignore = [
  "E501",  # line length (formatter handles)
  "S101",  # assert used (fine in tests)
  "B008",  # function calls in defaults (FastAPI Depends pattern)
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ARG", "PT011"]

[tool.ruff.lint.isort]
known-first-party = ["app"]
combine-as-imports = true

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
warn_unreachable = true
warn_redundant_casts = true
warn_unused_ignores = true
disallow_any_unimported = true
no_implicit_reexport = true
exclude = ["build/", "dist/", "\\.venv/", "__pycache__/"]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

Notes:
- `S101` (assert) is ignored project-wide because pytest relies on
  `assert`; `B008` is ignored because FastAPI's `Depends()` pattern
  legitimately calls a function in a default value.
- `tests/**` overrides relax `ARG` (test fixtures often look unused
  to ruff) and `PT011` (broad `pytest.raises` is sometimes
  intentional in tests).
- `pydantic.mypy` plugin enforces `init_forbid_extra` and
  `init_typed` so model construction is fully type-checked.
- `disallow_any_unimported` catches missing stubs early — if a
  dependency lacks types, we explicitly add a typed wrapper or a
  `# type: ignore[import-untyped]` with justification.

#### `apps/api/package.json` — replace placeholders

```json
{
  "scripts": {
    "dev": "uv run uvicorn app.main:app --reload --port 8000",
    "build": "uv sync --frozen",
    "test": "uv run pytest -q",
    "typecheck": "uv run mypy app",
    "lint": "uv run ruff check app tests",
    "format": "uv run ruff format app tests",
    "format:check": "uv run ruff format --check app tests",
    "clean": "rm -rf .venv .pytest_cache .mypy_cache .ruff_cache __pycache__"
  }
}
```

The `|| true` tail on `typecheck` from Spec 01 is removed — mypy
is now installed and `app/main.py` plus `tests/test_smoke.py` must
type-check clean.

### D. Turbo task graph (re-wire)

#### `turbo.json` — update `lint` and `format` tasks

```json
{
  "lint": {
    "outputs": [],
    "inputs": [
      "$TURBO_DEFAULT$",
      "biome.json",
      "pyproject.toml",
      "**/*.{ts,tsx,js,jsx,json,jsonc,py}"
    ]
  },
  "format": {
    "cache": false
  },
  "format:check": {
    "outputs": [],
    "inputs": [
      "$TURBO_DEFAULT$",
      "biome.json",
      "pyproject.toml"
    ]
  }
}
```

Add `format:check` as a new task (used by Spec 03's CI mirror later).

### E. Editor integration

#### `.vscode/settings.json`

Committed to the repo. Editors that don't honor this still get
coverage via the Spec 03 pre-commit hook.

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports.biome": "explicit"
  },
  "[typescript]":   { "editor.defaultFormatter": "biomejs.biome" },
  "[typescriptreact]": { "editor.defaultFormatter": "biomejs.biome" },
  "[javascript]":   { "editor.defaultFormatter": "biomejs.biome" },
  "[javascriptreact]": { "editor.defaultFormatter": "biomejs.biome" },
  "[json]":         { "editor.defaultFormatter": "biomejs.biome" },
  "[jsonc]":        { "editor.defaultFormatter": "biomejs.biome" },
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": {
      "source.organizeImports": "explicit",
      "source.fixAll.ruff": "explicit"
    }
  },
  "python.analysis.typeCheckingMode": "strict"
}
```

#### `.vscode/extensions.json`

Recommended extensions (a one-time prompt for new contributors):

```json
{
  "recommendations": [
    "biomejs.biome",
    "charliermarsh.ruff",
    "ms-python.python",
    "ms-python.mypy-type-checker",
    "esbenp.prettier-vscode"
  ],
  "unwantedRecommendations": [
    "dbaeumer.vscode-eslint",
    "esbenp.prettier-vscode"
  ]
}
```

`prettier-vscode` is in `unwantedRecommendations` so VSCode warns
against installing it — Biome owns formatting.

### F. Order of operations

1. Install Biome at the repo root: `pnpm add -DwE @biomejs/biome`.
2. Write `biome.json` per section A. **Do not** run
   `biome format --write` yet — first verify Spec 01's generated
   files all conform; if they don't, fix the generator output, not
   the config.
3. Update `apps/web/package.json` and
   `packages/sse-protocol/package.json` per section B.
4. Verify `apps/web/tsconfig.json` extends base with no loosening
   per section B.
5. Add ruff and mypy to `apps/api/`: `cd apps/api && uv add --dev ruff mypy`.
6. Append the `[tool.ruff]` and `[tool.mypy]` blocks to
   `apps/api/pyproject.toml` per section C. Run `uv sync`.
7. Replace `apps/api/package.json` scripts per section C.
8. Update `turbo.json` `lint` / `format` tasks per section D.
9. Write `.vscode/settings.json` and `.vscode/extensions.json` per
   section E.
10. Run the verification block. Fix violations until clean.

### G. Fixing the initial wave

Generator output from Spec 01 (Next.js scaffold, FastAPI scaffold)
will likely have a handful of lint findings on first run — for
example, `app/page.tsx` may use single quotes where Biome wants
double, or `app/main.py` may have an unused import. Fix these in
this spec, not later. Each fix is small and bounded; the goal is a
clean tree at the end of Spec 02.

## Out of Scope

- **Git hooks** — Spec 03. `lefthook.yml` will reference the lint
  and format scripts this spec creates.
- **CI / GitHub Actions** — deferred until after Spec 03. The CI
  workflow mirrors `format:check`, `lint`, `typecheck`, `test`.
- **Stricter rule sets** (Biome `nursery`, ruff `D` for docstrings,
  `ANN` for type-annotations) — defer until violations would catch
  real bugs. We add rules when we've seen a class of issue twice.
- **Custom Biome / ruff rules** — none planned. The 90% coverage
  from defaults is enough; stop short of bespoke rule authoring.
- **Auto-fixing on push** — pre-commit fixes locally (Spec 03);
  CI never auto-fixes (it reports and fails).
- **Python type stubs for third-party libs** — handled per-spec as
  each integration introduces a typeless dep (e.g., Scrapling stubs
  may need to be authored in Spec 07).

## Files

### Create

- `biome.json`
- `.vscode/settings.json`
- `.vscode/extensions.json`

### Edit

- `apps/web/package.json` — add `lint`, `format`, `format:check`
- `apps/web/tsconfig.json` — verify no loosening; no functional change
- `packages/sse-protocol/package.json` — add `lint`, `format`,
  `format:check`
- `apps/api/pyproject.toml` — append `[tool.ruff]`, `[tool.mypy]`,
  `[tool.pydantic-mypy]`; add `ruff` and `mypy` to dev deps
- `apps/api/package.json` — replace placeholder scripts; remove
  `|| true` tail on `typecheck`
- `turbo.json` — flesh out `lint`, `format`; add `format:check`
- `apps/web/app/page.tsx`, `apps/web/app/layout.tsx`,
  `apps/api/app/main.py` — clean up any first-run findings (single
  → double quotes, missing trailing comma, unused imports, etc.)

### Protected (do not touch)

- `tsconfig.base.json` — strict baseline, edited only when the
  baseline itself changes (a separate decision)
- `CLAUDE.md`, `AGENTS.md`, `context/**`, `.claude/**`,
  `.agents/**`
- `apps/api/app/security.py` — does not exist yet; will be
  protected from Spec 04 onward
- `packages/sse-protocol/generated/**` — already excluded from
  Biome's scanner; will hold codegen output (Spec 06)

## Verification

Run from the repo root unless noted. Each line is a binary
pass/fail check.

- `pnpm install` exits 0.
- `pnpm exec biome --version` prints `2.x.x`.
- `cd apps/api && uv run ruff --version` prints `0.x.x` (≥ 0.8).
- `cd apps/api && uv run mypy --version` prints `1.x.x`.
- `turbo run lint` exits 0 across all workspaces.
- `turbo run format:check` exits 0 (tree is already formatted).
- `turbo run typecheck` exits 0 (web typechecks; api now runs real
  mypy with no `|| true` tail).
- `turbo run test` exits 0.
- `turbo run build` exits 0.
- `cd apps/api && uv run mypy app tests` exits 0 (direct invocation;
  same result as the Turbo task).
- `pnpm exec biome check apps packages` exits 0.

Manual:

- Open `apps/web/app/page.tsx` in VSCode with the Biome extension
  installed; saving the file should not produce a diff (already
  formatted).
- Open `apps/api/app/main.py` similarly with the ruff extension;
  same result.
- Introduce a deliberate violation in a scratch file (`let x = 1;`
  with `var` in TS, or an unused import in Python); save and confirm
  the lint warning surfaces in the editor and `turbo run lint`
  exits non-zero. Revert.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
- [ ] `apps/api/package.json` `typecheck` script no longer ends in
  `|| true`.
- [ ] No file has an `eslint-disable`, `// biome-ignore`, or
  `# noqa` without an inline justification.
- [ ] `context/progress-tracker.md` updated: move Spec 02 to
  "Completed"; promote Spec 03 to "In Progress"; update
  "Current Goal".
- [ ] `turbo run lint && turbo run format:check && turbo run typecheck && turbo run test && turbo run build`
  exits 0.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships no scraping behavior. Its contribution to scrape
reliability is **type safety at the I/O boundary** — the strict
mypy + `pydantic.mypy` plugin means that when Spec 07 introduces
the first scrape tool, the agent's tool inputs and outputs are
type-checked at write time, not just at runtime. A typo in a
Pydantic field name fails `turbo typecheck`, not a midnight
production scrape.
