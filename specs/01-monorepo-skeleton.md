# 01 — monorepo-skeleton

## Goal

Stand up an empty Turborepo + pnpm workspaces monorepo with two
workspace apps (`apps/web` Next 16, `apps/api` FastAPI on `uv`) and
one empty shared package (`packages/sse-protocol`). After this spec,
`pnpm install && turbo dev` boots both apps simultaneously: the web
app on `http://localhost:3000` and the api on `http://localhost:8000`
answering `/health`.

## Dependencies

None — foundation spec.

## Design Decisions

- **Node 22 LTS** pinned via `.nvmrc` and `engines.node` in the root
  `package.json`. Required by Next.js 16; stable for the api host.
- **Python 3.12** pinned via `.python-version`. asyncio.TaskGroup
  is fully supported; better error messages than 3.11; default on
  Fly.io and Render.
- **pnpm 11.x** as the package manager, pinned via the
  `packageManager` field in root `package.json`. Workspaces declared
  in `pnpm-workspace.yaml`. Validated against the May 2026 release
  during the pre-implementation pass.
- **Turborepo 2.9.x** as the cross-app orchestrator. `turbo.json`
  defines `dev`, `build`, `test`, `typecheck`, `lint`, `format`,
  `clean` tasks; `dev` is persistent and runs concurrently.
- **TypeScript 6.x** as the language version. Strict-flag set
  unchanged from the original `tsconfig.base.json`; TS 6 added no
  breaking changes affecting our flag set.
- **uv** owns Python dependency management; the api ships a thin
  `package.json` wrapper exposing `dev` / `test` / `build` /
  `typecheck` scripts that shell out to `uv run`. This lets Turbo
  treat `apps/api` as a normal workspace member without forcing
  Python into the JS ecosystem.
- **Tailwind initialization is deferred to Spec 08**
  (`web-shell-and-stream-consumer`). `apps/web` is initialized
  without Tailwind and without ESLint (linting lands in Spec 02).
- **`packages/sse-protocol/` is created empty** with only a
  placeholder `package.json` and `README.md`. The schema and
  codegen ship in Spec 06.
- **`tsconfig.base.json` at the repo root** with strict mode and
  modern module resolution; each app's `tsconfig.json` extends it.
- **No CI configuration in this spec** — that lands later (after
  Spec 03 wires hooks).
- **Turbopack** for `apps/web` dev (Next.js 16 default).

References:
- `context/architecture.md` — Stack table, System Boundaries
- `context/code-standards.md` — TypeScript / Python rules (full
  enforcement comes in Spec 02; the skeleton is set up so those
  rules can attach cleanly)

## Implementation

### A. Repo root

#### `package.json`

```json
{
  "name": "autumn",
  "version": "0.0.0",
  "private": true,
  "packageManager": "pnpm@11.0.5",
  "engines": {
    "node": "22"
  },
  "scripts": {
    "dev": "turbo run dev",
    "build": "turbo run build",
    "test": "turbo run test",
    "typecheck": "turbo run typecheck",
    "lint": "turbo run lint",
    "format": "turbo run format",
    "clean": "turbo run clean && rm -rf node_modules .turbo"
  },
  "devDependencies": {
    "turbo": "^2.9.8",
    "typescript": "^6.0.0"
  }
}
```

The `packageManager` field is enforced by Corepack; the `engines.node`
field is enforced by pnpm.

#### `pnpm-workspace.yaml`

```yaml
packages:
  - "apps/*"
  - "packages/*"
```

#### `turbo.json`

```json
{
  "$schema": "https://turbo.build/schema.json",
  "ui": "tui",
  "tasks": {
    "dev": {
      "cache": false,
      "persistent": true
    },
    "build": {
      "dependsOn": ["^build"],
      "outputs": [".next/**", "!.next/cache/**", "dist/**"]
    },
    "test": {
      "dependsOn": ["^build"],
      "outputs": ["coverage/**"]
    },
    "typecheck": {
      "dependsOn": ["^typecheck"],
      "outputs": []
    },
    "lint": {
      "outputs": []
    },
    "format": {
      "cache": false
    },
    "clean": {
      "cache": false
    }
  }
}
```

#### `tsconfig.base.json`

```json
{
  "compilerOptions": {
    "target": "ES2024",
    "lib": ["ES2024", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true,
    "incremental": true,
    "jsx": "preserve"
  }
}
```

#### `.editorconfig`

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.{ts,tsx,js,jsx,json,jsonc,yaml,yml,md}]
indent_size = 2

[*.py]
indent_size = 4

[Makefile]
indent_style = tab
```

#### `.nvmrc`

```
22
```

#### `.python-version`

```
3.12
```

#### `.gitattributes`

```
* text=auto eol=lf

*.png  binary
*.jpg  binary
*.jpeg binary
*.webp binary
*.gif  binary
*.ico  binary
*.woff binary
*.woff2 binary
*.pdf  binary
```

#### `.gitignore`

The existing `.gitignore` already covers `.next/`, `.turbo/`, `.venv/`,
`__pycache__/`, `node_modules/`, `.env*`, `.DS_Store`. **Verify** the
`.turbo/` line is present; add it if missing. No other changes.

### B. `apps/web/` — Next 16

Run from repo root:

```bash
pnpm create next-app@latest apps/web \
  --typescript \
  --app \
  --no-tailwind \
  --no-eslint \
  --src-dir=false \
  --import-alias "@/*" \
  --use-pnpm \
  --turbopack \
  --skip-install \
  --yes
```

Then edit:

- `apps/web/package.json` — set `name: "@autumn/web"`. Confirm scripts
  exist: `dev`, `build`, `start`, `typecheck`. Add `clean` →
  `rm -rf .next .turbo`. Remove any `lint` / `format` script if
  generated (those land in Spec 02).
- `apps/web/tsconfig.json` — extend `../../tsconfig.base.json`. Keep
  the Next.js plugin entry the generator added. Strip duplicate
  flags now inherited from base.

  ```json
  {
    "extends": "../../tsconfig.base.json",
    "compilerOptions": {
      "plugins": [{ "name": "next" }],
      "paths": {
        "@/*": ["./*"]
      }
    },
    "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
    "exclude": ["node_modules"]
  }
  ```

- `apps/web/app/page.tsx` — replace the generated content with a
  single-line placeholder:

  ```tsx
  export default function Home() {
    return <main>Hello Autumn</main>;
  }
  ```

- `apps/web/app/layout.tsx` — keep the generator's structure;
  set the page title to `"Autumn"`.

The web app must boot to "Hello Autumn" at `:3000` after this spec;
no styling work is in scope.

### C. `apps/api/` — FastAPI on uv

Run from repo root:

```bash
mkdir -p apps/api && cd apps/api
uv init --no-readme --package autumn-api
```

Then create / edit:

- `apps/api/pyproject.toml` — append:

  ```toml
  [project]
  name = "autumn-api"
  version = "0.0.0"
  description = "Autumn FastAPI backend"
  requires-python = ">=3.12,<3.13"
  dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32"
  ]

  [tool.uv]
  package = true
  ```

  Lock with `uv sync` once the file is in place.

- `apps/api/.python-version` — `3.12` (mirrors the root for clarity
  inside the app folder).

- `apps/api/app/__init__.py` — empty file.

- `apps/api/app/main.py`:

  ```python
  from __future__ import annotations

  from fastapi import FastAPI


  app = FastAPI(title="Autumn API")


  @app.get("/health")
  async def health() -> dict[str, str]:
      return {"status": "ok"}
  ```

- `apps/api/package.json` — the Turbo wrapper:

  ```json
  {
    "name": "@autumn/api",
    "version": "0.0.0",
    "private": true,
    "scripts": {
      "dev": "uv run uvicorn app.main:app --reload --port 8000",
      "build": "uv sync --frozen",
      "test": "uv run pytest -q",
      "typecheck": "uv run mypy app || true",
      "clean": "rm -rf .venv .pytest_cache .mypy_cache .ruff_cache __pycache__"
    }
  }
  ```

  `typecheck` ends in `|| true` because mypy is not installed yet
  (lands in Spec 02). The script must exist now so Turbo's task graph
  resolves; once mypy is added the trailing `|| true` is removed.

  `test` similarly runs zero tests right now; it must not fail when
  pytest is uninstalled — add a noop `tests/test_smoke.py` that
  imports `app.main` and asserts the FastAPI app exists, so pytest
  has something to discover.

- `apps/api/tests/__init__.py` — empty.

- `apps/api/tests/test_smoke.py`:

  ```python
  from __future__ import annotations

  from app.main import app


  def test_app_exists() -> None:
      assert app.title == "Autumn API"
  ```

  Add `pytest>=8` to `[project.optional-dependencies].dev` in
  `pyproject.toml` and install with `uv sync --extra dev`.

### D. `packages/sse-protocol/` — empty placeholder

Create:

- `packages/sse-protocol/package.json`:

  ```json
  {
    "name": "@autumn/sse-protocol",
    "version": "0.0.0",
    "private": true,
    "main": "./generated/index.ts",
    "types": "./generated/index.ts"
  }
  ```

- `packages/sse-protocol/README.md`:

  ```markdown
  # @autumn/sse-protocol

  SSE event schema, generated TypeScript types, and generated
  pydantic models. Implementation lands in
  `specs/06-sse-protocol-contract.md`.
  ```

- `packages/sse-protocol/generated/index.ts` — single line:

  ```ts
  export {};
  ```

  Placeholder so the package resolves; real codegen replaces it
  in Spec 06.

### E. Order of operations

Run in this order; each step verifies before moving on:

1. Write the eight repo-root files (`package.json`,
   `pnpm-workspace.yaml`, `turbo.json`, `tsconfig.base.json`,
   `.editorconfig`, `.nvmrc`, `.python-version`, `.gitattributes`).
   Verify `.gitignore` has `.turbo/`.
2. Run `pnpm install` from repo root. Confirm Turbo + TypeScript
   land in `node_modules/`.
3. Scaffold `apps/web` with the `pnpm create next-app` command above.
   Edit `package.json`, `tsconfig.json`, `app/page.tsx`,
   `app/layout.tsx` per section B.
4. Scaffold `apps/api` with `uv init` per section C. Add
   `app/main.py`, `app/__init__.py`, `tests/test_smoke.py`,
   `package.json`. Run `uv sync --extra dev`.
5. Scaffold `packages/sse-protocol/` per section D.
6. Run `pnpm install` again from repo root to pick up the new
   workspace members.
7. Run the verification block below.

## Out of Scope

- **Linting / formatting / strict type-checking enforcement** — Spec
  02. Today's `lint` and `format` Turbo tasks are placeholders; the
  api `typecheck` ends in `|| true`.
- **Git hooks, commit-msg validation** — Spec 03. No Lefthook,
  no commitlint installed yet.
- **Tailwind 4, theme tokens, shadcn primitives** — Spec 08
  (web-shell-and-stream-consumer).
- **Clerk auth, middleware, JWKS verification** — Spec 04.
- **Database (Neon, sqlmodel, alembic)** — Spec 05.
- **SSE schema and codegen** — Spec 06.
- **Pydantic AI agent loop, LLM providers, scraping tools** —
  Spec 07.
- **CI / GitHub Actions** — deferred until after Spec 03 (hooks
  exist locally first; CI mirrors them).
- **Dockerfile** — Spec 15 (hardening-and-e2e).
- **`.env.example` files** — added per spec as each integration
  introduces env vars; nothing to seed in Spec 01.

## Files

### Create

- `package.json`
- `pnpm-workspace.yaml`
- `turbo.json`
- `tsconfig.base.json`
- `.editorconfig`
- `.nvmrc`
- `.python-version`
- `.gitattributes`
- `apps/web/` (entire Next 16 scaffold via `pnpm create next-app`)
- `apps/web/package.json` (overwrite generator output per section B)
- `apps/web/tsconfig.json` (overwrite generator output per section B)
- `apps/web/app/page.tsx` (overwrite generator output)
- `apps/api/pyproject.toml`
- `apps/api/.python-version`
- `apps/api/app/__init__.py`
- `apps/api/app/main.py`
- `apps/api/tests/__init__.py`
- `apps/api/tests/test_smoke.py`
- `apps/api/package.json`
- `packages/sse-protocol/package.json`
- `packages/sse-protocol/README.md`
- `packages/sse-protocol/generated/index.ts`

### Edit

- `.gitignore` — add `.turbo/` if missing (already present in most
  cases). No other edits.

### Protected (do not touch)

- `CLAUDE.md`, `AGENTS.md`, `context/**` — no edits as part of this
  spec. The skeleton must not change architectural decisions.
- `.claude/**`, `.agents/**` — already wired in Phase 2.
- `specs/tutorial.md` — kept until all specs are written, then
  deleted.

## Verification

Each line is a binary pass/fail check. Run from the repo root.

- `pnpm install` exits 0 with no `ERR_PNPM_*` warnings.
- `node --version` prints `v22.x`.
- `python --version` prints `Python 3.12.x` (when activated via the
  project virtualenv at `apps/api/.venv/`).
- `cd apps/api && uv sync --extra dev` exits 0.
- `cat tsconfig.base.json | jq .compilerOptions.strict` prints
  `true`.
- `turbo run build --dry-run=json | jq '.tasks | length'` prints
  `>= 3` (one per workspace).
- `turbo run typecheck` exits 0 (web typechecks; api `|| true`s
  through).
- `turbo run dev` starts both apps concurrently. Wait ~10s, then:
  - `curl -s http://localhost:3000 | grep -q "Hello Autumn"` → exit 0
  - `curl -s http://localhost:8000/health | jq -r .status` → `ok`
- `turbo run test` exits 0 (the api smoke test passes; web has no
  tests yet, which Turbo treats as "no work").
- `pnpm -w list --depth=0` shows `@autumn/web`, `@autumn/api`,
  `@autumn/sse-protocol`.

Manual checks:

- Open `apps/web` in the browser at `http://localhost:3000`. Page
  shows "Hello Autumn". Browser devtools console has no errors.
- Open `http://localhost:8000/docs`. FastAPI Swagger UI loads with
  the `/health` endpoint listed.
- `git status` after the spec is committed shows a clean tree;
  `.turbo/`, `node_modules/`, `.venv/`, `.next/` are all gitignored.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  (Spec 01 introduces no runtime behavior, so invariants 1–12 are
  unaffected; only the System Boundaries section must match the
  actual folders created.)
- [ ] `context/progress-tracker.md` updated: move Spec 01 from
  "In Progress" to "Completed"; promote Spec 02 to
  "In Progress"; update "Current Goal".
- [ ] `turbo run build` exits 0.
- [ ] `turbo run typecheck` exits 0.
- [ ] No file under `apps/web/components/ui/`,
  `packages/sse-protocol/generated/` (beyond the placeholder
  `index.ts`), or `apps/api/app/security.py` was created — those
  are owned by later specs.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships zero scraping behavior — there is nothing yet to be
reliable. The reliability work begins in Spec 04 (auth + SSRF guard)
and accelerates in Spec 07 (the first real scrape tool). Spec 01
contributes only by establishing the workspace boundary so future
specs can land Scrapling, Crawl4AI, and the LLM provider chain in
their proper places without reshaping the repo.
