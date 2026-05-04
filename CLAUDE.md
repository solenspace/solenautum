## Application Building Context

This is the canonical entry file for **Autumn**, a concurrent AI scraping
agent. The repository is a Turborepo monorepo (`apps/web` + `apps/api` +
`packages/sse-protocol`); this root file applies to both apps. App-specific
overlays live in `apps/*/CLAUDE.md` and are read **after** this file —
overlays only exist when an app develops conventions that genuinely don't
apply to the other.

Read the following files in order before implementing or making any
architectural decision:

1. `context/project-overview.md` — product definition, goals, features,
   and scope
2. `context/architecture.md` — system structure, boundaries, storage model,
   and the **12 invariants** that govern every change
3. `context/ui-context.md` — theme, color tokens, typography, layout
   patterns, accessibility rules, keyboard shortcuts
4. `context/code-standards.md` — implementation rules and conventions
   for both web and api apps
5. `context/ai-workflow-rules.md` — development workflow, scoping rules,
   protected files, and verification gates
6. `context/progress-tracker.md` — current phase, completed work, open
   questions, architecture decisions, and next steps

Before any code change, re-read the **Invariants** section of
`context/architecture.md`. Invariants are non-negotiable; everything else
is convention.

Update `context/progress-tracker.md` after each meaningful implementation
change.

If implementation changes the architecture, scope, or standards documented
in the context files, update the relevant file **before** continuing.

## Branching (gitflow)

Two long-lived branches: `main` (production) and `development`
(integration). All feature work happens on a short-lived branch cut
from `development`.

Before implementing any new feature or spec:

1. `git checkout development && git pull --ff-only`
2. `git checkout -b <type>/<short-name>` — branch off `development`
   using a gitflow prefix:
   - `feature/<spec-or-feature-name>` — new functionality
   - `fix/<bug-summary>` — bug fix
   - `chore/<task>` — tooling, deps, config
   - `docs/<topic>` — docs only
3. Implement, commit (Conventional Commits), push.
4. Open a PR into `development`. Merge once green.
5. Promotion to `main` happens via a release PR (`development → main`)
   when a unit of work is shippable.

Never commit directly to `development` or `main`. Never open a PR from
a feature branch into `main`.

Commit messages follow Conventional Commits:
`<type>(<optional-scope>): <imperative summary>` —
allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`,
`build`, `ci`, `perf`, `style`, `revert`. Enforced by the
`commit-msg` hook in `lefthook.yml`.
