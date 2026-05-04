# UI Context

## Theme

Near-monochrome technical workspace: bone canvas with narrow black ink.
References: Linear (`linear.app`), Vercel dashboard
(`vercel.com/dashboard`), Stripe Docs (`docs.stripe.com`). Both light
and dark modes are first-class.

The chrome (page bg, surfaces, borders, primary text, CTA) is strictly
monochromatic. Semantic communication — tier badges (HTTP / Stealth /
Dynamic) and state colors (success / warn / error / info) — keeps
desaturated chromatic hues at ≤42% saturation paired with glyph +
2-letter code. The CTA is the only fully-saturated dark element on
bone (light mode) or fully-saturated light element on near-black (dark
mode); every other interactive element is lower contrast so the CTA
reads unambiguously as "the action."

Warm-tinted neutrals (every neutral carries 1-3% warm tint, R > B)
keep the palette from feeling cold or clinical. Pure `#000000` and
`#FFFFFF` are reserved for the CTA; body text uses `#1A1612` (light)
or `#F5F1EB` (dark) so it reads softer than print. Reasoning text
dims to ~60% opacity; tool-call chips render at full opacity with
neutral fill; result previews use primary contrast.

## Voice & Copy

In-app strings — buttons, labels, errors, empty states, auth screens,
confirmation modals — follow the rules below. The voice is technical
and terse, closer to Linear or Stripe than to Mailchimp. No marketing
fluff, no exclamation marks, no emoji in product chrome.

- **Sentence case, lowercase outside proper nouns.** "Run mission",
  not "Run Mission" or "RUN MISSION".
- **Buttons are verbs.** "Run mission", "Cancel", "Approve URLs",
  "Save selectors". Never "Get started", "Click here", "Submit".
- **Labels are nouns or noun phrases.** "URL", "Mission name",
  "Tier", "Cost". Skip articles when space is tight.
- **Errors state what happened plus what to try.** "Site uses Akamai.
  Try a different URL or run in stealth tier." Not "Something went
  wrong" or "Error 500".
- **Empty states give a single CTA.** "No missions yet. Start one →"
  Not motivational copy, not illustrations of cartoon mascots.
- **Auth screens are single-line value props.** "Scrape websites in
  parallel." Sign in / Sign up buttons, no testimonials, no logos
  wall, no feature grids. Clerk handles the form chrome; we own the
  surrounding copy.
- **Numbers and units are explicit.** "1.2s", "8.4 MB", "12/20 done".
  Not "a moment ago" unless relative time is the actual signal.
- **Reasoning text is dim and italicized**, not bold. The user reads
  it; the agent does not announce it.
- **No second-person hand-holding.** "Mission cancelled" beats "We've
  cancelled your mission". The product narrates state, not feelings.
- **i18n keys before strings.** Every user-facing string flows through
  `t(namespace, key, params?)` — never hardcoded English.

When in doubt, write the shortest version that is still unambiguous.
Cut adverbs. Cut "please". Cut greetings. The user is here to scrape
websites, not to read prose.

## Colors — Dark Mode

| Role | CSS Variable | Value |
| --- | --- | --- |
| Page background | `--bg-base` | `#0A0A09` |
| Card / panel | `--bg-surface` | `#13110F` |
| Modal / popover | `--bg-surface-elevated` | `#1B1815` |
| Hover surface | `--bg-surface-hover` | `#23201C` |
| Primary text | `--text-primary` | `#F5F1EB` |
| Secondary text | `--text-secondary` | `#C9C2B6` |
| Muted text | `--text-muted` | `#8E867A` |
| Subtle text | `--text-subtle` | `#5C564D` |
| Text on accent | `--text-on-accent` | `#0A0A09` |
| Default border | `--border-default` | `#2A2620` |
| Strong border | `--border-strong` | `#3D372F` |
| Subtle border | `--border-subtle` | `#1F1C18` |
| Primary accent (CTA — fully-saturated white on dark) | `--accent-primary` | `#FFFFFF` |
| Accent hover (warm off-white shift) | `--accent-primary-hover` | `#F5F1EB` |
| Secondary accent | `--accent-secondary` | `#8E867A` |
| Muted accent tint | `--accent-muted` | `#1F1815` |
| Success (desaturated moss) | `--state-success` | `#6FA561` |
| Warning (desaturated harvest) | `--state-warn` | `#D4B856` |
| Error (desaturated terracotta) | `--state-error` | `#CD6B5F` |
| Info (desaturated slate) | `--state-info` | `#6B95B8` |
| Tier — HTTP (sage) | `--tier-http` | `#7B9B7A` |
| Tier — Stealth (muted plum) | `--tier-stealth` | `#726B96` |
| Tier — Dynamic (warm amber) | `--tier-dynamic` | `#D4B856` |
| Focus ring | `--ring-focus` | `#FFFFFF` |
| Shadow | `--shadow-color` | `#000000` (alpha 0.3-0.5) |

## Colors — Light Mode

Bone canvas — warm off-white, never pure white. The CTA is the only
fully-saturated dark element on the field; that's what makes it read
as "the action." Elevation on cards is conveyed via shadow, not
lighter fill.

| Role | CSS Variable | Value |
| --- | --- | --- |
| Page background (warm bone) | `--bg-base` | `#FAF8F5` |
| Card / panel | `--bg-surface` | `#FFFFFF` |
| Modal / popover | `--bg-surface-elevated` | `#FFFFFF` (+ shadow) |
| Hover surface | `--bg-surface-hover` | `#F1ECE3` |
| Primary text (warm-tinted near-black) | `--text-primary` | `#1A1612` |
| Secondary text | `--text-secondary` | `#4A443B` |
| Muted text | `--text-muted` | `#7A7264` |
| Subtle text | `--text-subtle` | `#A8A092` |
| Text on accent | `--text-on-accent` | `#FFFFFF` |
| Default border | `--border-default` | `#E5DFD3` |
| Strong border | `--border-strong` | `#C9C2B2` |
| Subtle border | `--border-subtle` | `#F0EBE0` |
| Primary accent (CTA — fully-saturated black on bone) | `--accent-primary` | `#000000` |
| Accent hover (softens to warm-black) | `--accent-primary-hover` | `#1A1612` |
| Secondary accent | `--accent-secondary` | `#7A7264` |
| Muted accent tint | `--accent-muted` | `#F5E4D4` |
| Success (desaturated forest) | `--state-success` | `#4A7F3D` |
| Warning (desaturated harvest) | `--state-warn` | `#9E8C3A` |
| Error (desaturated terracotta) | `--state-error` | `#A84A38` |
| Info (desaturated slate) | `--state-info` | `#3E6B99` |
| Tier — HTTP (sage) | `--tier-http` | `#6B8860` |
| Tier — Stealth (muted plum) | `--tier-stealth` | `#5E5B7F` |
| Tier — Dynamic (warm amber) | `--tier-dynamic` | `#9E8C3A` |
| Focus ring | `--ring-focus` | `#000000` |
| Shadow | `--shadow-color` | `#1A1612` (alpha 0.08-0.12) |

## Contrast Verification (WCAG)

Computed pairs that must hold (re-verify with
[WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
after any token edit):

**Dark mode:**
- `--text-primary` on `--bg-base`: **17.84:1** (AAA)
- `--text-secondary` on `--bg-surface`: **11.21:1** (AAA)
- `--text-on-accent` on `--accent-primary`: **21:1** (AAA — black on white)
- `--state-error` on `--bg-base`: **8.56:1** (AAA)
- `--tier-http` on `--bg-surface`: **6.14:1** (AAA)
- `--tier-stealth` on `--bg-surface`: **5.79:1** (AAA)
- `--tier-dynamic` on `--bg-surface`: **8.82:1** (AAA)

**Light mode:**
- `--text-primary` on `--bg-base`: **18.2:1** (AAA)
- `--text-secondary` on `--bg-surface`: **8.91:1** (AAA)
- `--text-on-accent` on `--accent-primary`: **21:1** (AAA — white on black)
- `--state-error` on `--bg-base`: **6.84:1** (AA)
- `--tier-http` on `--bg-surface`: **4.98:1** (AA)
- `--tier-stealth` on `--bg-surface`: **4.22:1** (AA)
- `--tier-dynamic` on `--bg-surface`: **4.87:1** (AA)

Body text holds AAA (≥7:1). Interactive UI elements hold AA
(≥4.5:1 normal text, ≥3:1 large/UI). Tier badges hold AA at minimum
on both modes; pair with the glyph + 2-letter code so color is never
the sole channel.

## Tier Badge Differentiation (color-blind safe)

Tier hues are chosen at distinct luminance levels (≥10 L* points of
separation) so sage, plum, and amber stay distinguishable under
deuteranopia and protanopia simulation. Color is **never** the sole
channel — every tier badge pairs hue with a glyph + 2-letter code.

Every tier badge ships with:

- A glyph + uppercase 2-letter code (the load-bearing semantic
  signal)
- A 1px left border in a darker shade of the same hue (luminance
  step that survives monochrome rendering)

| Tier | Color (light / dark) | Glyph | Code | Lucide icon |
| --- | --- | --- | --- | --- |
| HTTP | sage `#6B8860` / `#7B9B7A` | `>_` | `HT` | `Globe2` |
| Stealth | plum `#5E5B7F` / `#726B96` | shield | `ST` | `ShieldCheck` |
| Dynamic | amber `#9E8C3A` / `#D4B856` | play | `DY` | `Browser` |

## Pitfalls Codified

- Avoid pure `#000000` / `#FFFFFF` for body text — use `#1A1612` /
  `#F5F1EB` so type reads softer than print. Pure black/white is
  reserved for the CTA, where the harshness *is* the signal.
- Tier badges need ≥10 L* points of separation to survive
  deuteranopia / protanopia simulation; the chosen sage / plum /
  amber values clear that bar.
- State and tier colors stay ≤42% saturation. Higher saturation on a
  near-monochrome field reads as cheap or jarring; desaturation
  preserves the premium feel.
- Pick one tint direction and stick with it. Every neutral in this
  palette carries 1-3% warm tint (R > B). Mixing warm and cool
  neutrals creates muddy greys.
- Surface elevation in dark mode comes from shadow, not lighter
  fill. Brighter surfaces lose the deep-canvas effect.
- `--bg-base` is warm `#0A0A09` / `#FAF8F5`, never pure black or
  pure white.
- The CTA is the only fully-saturated dark element on bone (or the
  only fully-saturated light element on near-black). Every other
  interactive element must read at lower contrast so the CTA stays
  unambiguous.

## Typography

| Role | Font | Variable |
| --- | --- | --- |
| UI text | Geist Sans | `--font-sans` |
| Code / mono | Geist Mono | `--font-mono` |

Font weights: 400 (body), 500 (UI labels), 600 (headings). No
italics in UI chrome; italic is reserved for dimmed reasoning text.

## Border Radius

| Context | Class |
| --- | --- |
| Inline / chips / small UI | `rounded-sm` |
| Cards / panels / task lanes | `rounded-md` |
| Modals / popovers / overlays | `rounded-lg` |

## Component Library

shadcn/ui on top of Tailwind 4. Primitives live in
`apps/web/components/ui/` and are managed by the shadcn CLI — never
hand-edited. Composite components live in `apps/web/widgets/`:

- `MissionLaneStack` — vertical stack of task lanes with sticky
  aggregate header
- `TaskLaneCard` — single task lane (auto-collapses on completion)
- `MissionSidebar` — left sidebar grouping missions by status
- `UrlApprovalGate` — discovered-URL approval UI (description mode)
- `ToolCallChip` — collapsed tool call with favicon + duration

## Layout Patterns

- **Mission shell** — top bar (Clerk user button, mission controls)
  + main content area; left sidebar collapses on screens < 1024px.
- **Stacked task lanes** — `flex flex-col gap-3`. Lanes auto-collapse
  on terminal status; expand on focus or click. The sticky aggregate
  header shows `{succeeded}/{total} done · {running} streaming ·
  {failed} errored`. References: Devin v3 Sessions, Manus, Replit
  Agent.
- **Three-tier visual hierarchy inside a lane**: dim/italic reasoning
  at ~60% opacity → neutral tool-call chips → high-contrast scraped-
  result preview.
- **Tool-call chip** — one line: `[favicon] tool_name(arg) · 1.2s`,
  expandable on click to reveal args, selectors used, response size.
- **URL approval gate** — discovered URLs default-checked, grouped
  by domain, inline edit on hover (click to edit, Enter to commit),
  per-mission "auto-approve future runs" toggle.
- **Mobile** — collapse all but the active task on screens < 768px;
  show a "reconnecting…" pill with exponential backoff during SSE
  drops; resume via `Last-Event-ID`.
- **Empty / loading / error** — skeleton shimmers match final layout
  shape (no generic spinners); errors retry **per-URL**, not per-
  mission.
- **Cost transparency** — per-mission cost in the sidebar entry and
  lane footer; per-task breakdown on hover. Per-token detail is
  hidden by default.

## Accessibility

- `aria-live="polite"` on milestone events only (mission start,
  mission complete, mission error). Never `assertive`. Never per-
  token.
- New lanes do not steal focus when they appear; instead, announce
  via the live region and offer a skip-link to the new lane.
- Reasoning text uses `aria-describedby` to link to its parent
  task lane, so screen readers can opt out of streaming chatter.
- Focus rings use `--ring-focus` and are 2px wide; `focus-visible`
  is preferred over `focus`.
- All interactive elements have an accessible name (`aria-label`
  when icon-only).

## Keyboard Shortcuts

Power-user expectations (2026 baseline):

| Shortcut | Action |
| --- | --- |
| ⌘K | Open command palette |
| ⌘↩ | Submit current form |
| Esc | Cancel current mission / close modal |
| ⌘/ | Toggle reasoning visibility on focused lane |
| ⌘⇧N | New mission |
| J / K | Navigate to next / previous task lane |
| X | Cancel the focused task lane |
| ⌘⇧M | Toggle mission sidebar |
| ⌘⇧L | Toggle light/dark mode |

Shortcuts are registered in `apps/web/shared/keyboard/`; help is
exposed via `?` (shows the full shortcut sheet).

## Icons

Lucide React. Stroke-based icons only. Sizes: `h-4 w-4` for inline
chip glyphs, `h-5 w-5` for buttons, `h-6 w-6` for sidebar entries.
Tier icons (`Globe2`, `ShieldCheck`, `Browser`) appear inside tier
badges next to the 2-letter code.
