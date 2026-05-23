# UI Decisions — Synthetic Persona Sandbox

> This document captures every design and engineering decision made for the Synthetic Persona
> Sandbox dashboard. It serves as a reference for maintaining the existing UI and as a migration
> guide for applying the same system to any new application.

---

## Table of Contents

1. [Philosophy](#1-philosophy)
2. [Technology Choices](#2-technology-choices)
3. [Design Tokens](#3-design-tokens)
4. [Typography System](#4-typography-system)
5. [Color Palette](#5-color-palette)
6. [Spacing and Layout Scale](#6-spacing-and-layout-scale)
7. [Navigation](#7-navigation)
8. [Page Structure Pattern](#8-page-structure-pattern)
9. [Component Catalogue](#9-component-catalogue)
10. [Dark Mode](#10-dark-mode)
11. [State Management](#11-state-management)
12. [API Layer](#12-api-layer)
13. [Inline Styles vs CSS Modules vs Tailwind](#13-inline-styles-vs-css-modules-vs-tailwind)
14. [Migration Guide](#14-migration-guide)

---

## 1. Philosophy

The visual identity is **OPB** — Octavio Pérez Bravo, Data & AI Strategy Architect. The design
goal is described as:

> "Corporate authority without excess decoration. Technical precision + executive clarity."

This translates into three practical rules applied everywhere in the dashboard:

**Restraint over decoration.** No gradients on fills, no shadows heavier than `0 1px 6px`,
no rounded corners above `14px`. Every decorative element — the gold eyebrow line, the grid
texture on hero sections, the ghosted large numerals — serves a structural purpose rather than
adding visual noise.

**Typography does the hierarchy work.** Two font families carry the entire visual weight.
Fraunces (a variable serif) handles titles and display text. Plus Jakarta Sans handles all
interface copy, labels, and data. Weight and size variation within these two fonts eliminates
the need for colour-based hierarchy beyond a handful of defined tokens.

**Colour signals meaning, not style.** The primary navy (#003366) and gold (#c8982a) are brand
colours. All other colours in the system are semantic — green for success, orange for warning,
red for error. Using a colour outside this system requires explicit justification.

**Navy is dominant; gold is the only structural accent.** Navy fills backgrounds, hero sections,
table headers, and primary text. Gold marks structural accent lines (card `borderTop`, stat
card `borderLeft`), eyebrows, active states, and the primary action button. Status colours
(green, orange, red) are reserved exclusively for KPI values that communicate a risk or
performance signal — they are **never** applied to structural elements like card borders,
eyebrow bars, or categorical labels. The hierarchy is: navy first, gold second, status colours
only when the data demands them.

---

## 2. Technology Choices

### React 18 + TypeScript

React 18 is used because concurrent rendering and the hooks model support the real-time
WebSocket update pattern (simulation progress streaming) without class component lifecycle
management. Functional components only — no class components exist anywhere in the codebase.

TypeScript strict mode (`"strict": true`) is required. Every API response, store slice, and
component prop is statically typed. This is not optional hygiene — a class of bugs (the
`stimulus_type` / `latency_ms` mismatch in the analytics page that caused blank tab renders)
was caused directly by an interface that did not match the actual API response shape. Strict
typing would have caught it at compile time.

### Vite 5

Chosen over webpack/CRA for native ESM in development. Hot module replacement completes in
50–200ms instead of full rebundling. The proxy configuration in `vite.config.ts` forwards
`/api/*` and `/ws/*` to the FastAPI backend, so the frontend makes same-origin requests during
development and there is no CORS issue in browser.

```ts
// vite.config.ts — proxy section
proxy: {
  '/api': { target: 'http://localhost:8001', changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
  '/ws':  { target: 'ws://localhost:8001',  ws: true },
}
```

### Zustand (state management)

Redux would be over-engineered for this scope. Zustand has no Provider wrapping, no action
creators, and no reducers. Two stores exist:

- `authStore` — holds the JWT token, user object (`email`, `role`), and `clearAuth()`
- `campaignStore` — holds the campaign launcher form state across the multi-step flow

All other state is local to the component via `useState`. Data fetching is done directly with
`useEffect` + the `api` service, not via a caching layer like React Query. This is appropriate
for the current data volume and update frequency.

### No external UI library

No Shadcn, no MUI, no Ant Design. All components are written from scratch using inline styles
and the design token system. This was a deliberate choice to maintain full design fidelity to
the OPB brand system without fighting against a third-party component library's opinions on
spacing, colour, or typography.

---

## 3. Design Tokens

All values live in `dashboard/src/styles/tokens.css` as CSS custom properties. **No value is
ever hardcoded anywhere else in the application.** Using a raw hex colour in a component is
a bug.

```css
:root {
  /* Colour */
  --primary:    #003366;   /* Navy — primary brand + nav background */
  --primary-80: #1a4d80;   /* Navy 80% — hover states, secondary headers */
  --primary-60: #336699;   /* Navy 60% — links, mid-weight accents */
  --primary-30: #99bbdd;   /* Navy 30% — decorative accents, diagram arrows */
  --primary-10: #e0eaf4;   /* Navy 10% — card backgrounds, table stripes */
  --gold:       #c8982a;   /* Brand gold — eyebrows, accent bars, borders */
  --gold-light: #e8c46a;   /* Gold light — active nav links, hero italic text */
  --dark:       #1c1c2e;   /* Near-black — primary body text */
  --mid:        #6b7280;   /* Grey — secondary text, captions, metadata */
  --light:      #f4f6f9;   /* Off-white — page background, card backgrounds */
  --white:      #ffffff;   /* Pure white — card surfaces */

  /* Typography */
  --fd: 'Fraunces', Georgia, serif;       /* Display / titles */
  --fb: 'Plus Jakarta Sans', sans-serif;  /* Interface / body */

  /* Spacing */
  --space-4: 4px;   --space-8: 8px;   --space-12: 12px;
  --space-16: 16px; --space-24: 24px; --space-32: 32px;
  --space-40: 40px; --space-48: 48px; --space-64: 64px;

  /* Border radius */
  --radius-sm:   6px;
  --radius-md:   12px;
  --radius-lg:   14px;
  --radius-pill: 20px;

  /* Shadows */
  --shadow-card: 0 1px 4px rgba(0, 51, 102, 0.08);
  --shadow-soft: 0 1px 6px rgba(0, 51, 102, 0.09);

  /* Layout */
  --max-width-content:   1200px;   /* Info / content-heavy pages */
  --max-width-dashboard: 1300px;   /* Data dashboard pages */
  --nav-height: 52px;
}
```

### Semantic status colours

These are defined in tokens and always used for their assigned meaning:

| Token | Hex | Use |
|---|---|---|
| `--status-green` | `#27b97c` | Completed, positive, on-track |
| `--status-red` | `#e03448` | Error, alert, critical |
| `--status-orange` | `#f07020` | Warning, pending, at-risk |
| `--status-purple` | `#7c4dbd` | Analytics, projections, AI |
| `--status-blue` | `#003366` | Primary, corporate default |

Each semantic colour has a `*-bg` (light background) and `*-text` (readable text on white)
variant for use in badges and pills.

---

## 4. Typography System

Two fonts are loaded via a single Google Fonts `<link>` in `index.html`:

```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;1,9..144,300;1,9..144,400&display=swap" rel="stylesheet">
```

### Fraunces — display font (`var(--fd)`)

Used exclusively for titles, hero headings, and large decorative numerals. Never used for body
copy or interface labels.

| Context | Size | Weight | Notes |
|---|---|---|---|
| Hero / page titles | 36–48px | 300 | Key word in italic + `var(--gold-light)` |
| Section titles (H2) | 22px | 300 | Italic on emphasis word when needed |
| Widget / card headers | 16–20px | 300–400 | |
| KPI callout values | 28–34px | 300 | `var(--dark)` on cards, `var(--gold-light)` on dark backgrounds |
| Decorative numerals | 44px | 300 | `var(--primary-30)` — ghosted watermark, not content |

**Critical rule:** Never bold Fraunces. Use weight 300 or 400. The optical size axis (`opsz`)
adjusts automatically; combined with italic for emphasis, it renders at sufficient weight
without needing 600+.

### Plus Jakarta Sans — interface font (`var(--fb)`)

Used for everything else: body copy, labels, buttons, captions, table cells, form inputs.

| Context | Size | Weight | Style |
|---|---|---|---|
| Body text | 13–15px | 400 | `line-height: 1.7`, `color: var(--dark)` or `#475569` |
| Section captions | 13–14px | 400 | `color: var(--mid)` |
| Labels / eyebrows | 9–11px | 500–700 | UPPERCASE, `letter-spacing: 2–4px` |
| Button text | 9–11px | 700 | UPPERCASE, `letter-spacing: 1.5px` |
| Table headers | 10px | 600 | UPPERCASE, `letter-spacing: 2px` |
| Metadata / timestamps | 10–12px | 400 | `color: var(--mid)` |
| Code / endpoints | Courier New, 12–13px | 400 | Not Plus Jakarta — inline code uses `Courier New` |

**Letter spacing rule:** Any text rendered at ≤11px uppercase **must** have `letterSpacing`
of at least `2px`. Below 11px, zero letter spacing makes uppercase text illegible.

### Italic as a signature mark

The italic Fraunces variant is used in one specific pattern: the key word or phrase in a hero
title is wrapped in `<em>` with `fontStyle: 'italic'` and `color: 'var(--gold-light)'`. This
is the single most identifiable visual element of the OPB brand system.

```jsx
// Correct
<h1>Simulate before you <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>spend.</em></h1>

// Also used in section sub-titles
<h2>Database <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>controls</em></h2>
```

---

## 5. Color Palette

### How to use primary colours

| Token | Where |
|---|---|
| `var(--primary)` | Nav background, hero backgrounds, table `<thead>` background |
| `var(--primary-80)` | Rarely used; available for hover on dark surfaces |
| `var(--primary-60)` | Links, mid-weight code labels, stack table accents |
| `var(--primary-30)` | Diagram arrows, decorative borders, ghosted elements |
| `var(--primary-10)` | Card background alternate, table row stripes, divider lines |

### How to use gold

| Token | Where |
|---|---|
| `var(--gold)` | Eyebrow lines and text, `borderLeft` on hero stat cards (always 2–3px), `borderTop` on KPI/score cards (always 3px), accent bars, left-border callouts |
| `var(--gold-light)` | Active nav links, hero italic words, stat values on dark backgrounds |

Gold is never used as a button background except for primary action buttons (`primaryBtn`),
where it signals the highest-priority action on the page.

**`borderLeft` rule:** Every stat card rendered inside a hero section uses `borderLeft: '2px solid var(--gold)'` — no exceptions. Status colours are never used for this structural accent, regardless of the metric's risk level.

**`borderTop` rule:** Every KPI card and score card in the body uses `borderTop: '3px solid var(--gold)'` — no exceptions. If the metric value represents a critical risk (e.g., attrition probability, budget overrun), the *value text* colour may contextually use a status colour (e.g., `var(--status-red)`). The border itself always stays gold.

### Data visualisation series

When multiple data series need distinct colours in charts, use the navy gradient sequence, with gold reserved for the highest-impact or highlight series:

1. `#003366` — navy (primary, dominant)
2. `#1a4d80` — navy 80%
3. `#336699` — navy 60%
4. `#4d7099` — navy muted
5. `#99bbdd` — navy 30% (lightest)
6. `#c8982a` — gold (highlight / top bucket / emphasis only)

**Do not use green, purple, orange, or pink for categorical chart series.** Those are semantic status colours — their presence in a chart implies a specific meaning (success, analytics, warning, error). Using them as arbitrary data series creates false associations. The navy gradient provides sufficient visual distinction for 3–5 series; gold marks the one series that deserves emphasis.

For SVG charts specifically: `fill=""` and `stroke=""` attributes cannot use CSS custom properties. Use the raw hex values from the series above. Any hex value not in this list is a bug.

### Color hierarchy and restriction rules

Three tiers, strict priority:

| Tier | Colours | Purpose |
|---|---|---|
| **1 — Navy (dominant)** | `--primary`, `--primary-80`, `--primary-60`, `--primary-30`, `--primary-10` | Structural mass: hero backgrounds, nav, table headers, body text, decorative accents |
| **2 — Gold (structural accent)** | `--gold`, `--gold-light` | Accent-only: eyebrow bars, `borderLeft` on stat cards, `borderTop` on KPI cards, active states, primary action button |
| **3 — Status colours (data signals only)** | `--status-green`, `--status-red`, `--status-orange`, `--status-purple` | KPI value text and status badges when the value communicates a specific risk or performance signal |

**Never apply a Tier 3 status colour to a structural element.** Card `borderTop`, card `borderLeft`, eyebrow bars, section dividers, and categorical chart labels are structural — they must use Tier 1 or Tier 2 colours only. Status colours may appear in: value text, progress bars, risk indicators, and status badges.

**Permitted and prohibited use matrix:**

| Element | Permitted | Prohibited |
|---|---|---|
| Hero stat card `borderLeft` | `var(--gold)` only | Any status colour, any navy variant |
| KPI / score card `borderTop` | `var(--gold)` only | Any status colour, any navy variant |
| KPI value text | `var(--gold-light)` on dark; `var(--dark)` on light; status colour if critical KPI | Purple, orange, pink as decoration |
| Categorical chart series | Navy gradient + gold highlight | Green, purple, orange, pink |
| Status badge dot + label | Status colours matched to semantic meaning | Gold or navy as badge colour |
| Section eyebrow bar | `var(--gold)` / `var(--gold-light)` | Any status colour |
| Nav active state | `var(--gold-light)` | Green, red, purple |

---

## 6. Spacing and Layout Scale

### Spacing tokens

The spacing scale is an 8-point grid: `4 / 8 / 12 / 16 / 24 / 32 / 40 / 48 / 64 / 96px`.
Use `var(--space-N)` for margins and paddings in CSS. In inline styles, use the raw pixel value
but always from this scale — no `7px`, `11px`, or arbitrary values.

### Content width constraints

Every page body wraps its content with a `maxWidth` constraint and `margin: 0 auto`:

- `var(--max-width-dashboard)` — 1300px for data-heavy pages (Analytics, Segments, Campaigns)
- `var(--max-width-content)` — 1200px for reading-oriented pages (Info, Admin)

### Grid patterns

| Columns | Use case |
|---|---|
| 2-col `1fr 1fr` | Side-by-side charts, compare panels |
| 3-col `repeat(3, 1fr)` | Value pillar cards, feature descriptions |
| 4-col `repeat(4, 1fr)` | KPI stat rows |
| `300px 1fr` | Selection list + detail / chart panels |
| `repeat(auto-fill, minmax(280px, 1fr))` | Responsive card grids |

### Standard card padding

Cards use `28px` padding. Hero sections and information pages use `32px` card padding.
Never less than `20px` for interactive cards; never more than `40px`.

---

## 7. Navigation

### Structure

The navigation bar is sticky at the top, `52px` tall (`var(--nav-height)`), on a navy
background with a 12px backdrop blur and a subtle bottom border:

```
[OPB monogram] ············ [App title] ······ [Nav links] [User info] [Logout] [Theme]
left                         centre-ish                                          right
```

**Left:** OPB monogram rendered in Fraunces — `O` in white weight 300, `PB` in italic
`var(--gold-light)` weight 300. Always inline styles, never Tailwind or className. The
monogram is purely decorative (no click handler).

**Centre:** App title in 9px uppercase Plus Jakarta, `letter-spacing: 3px`, `rgba(255,255,255,0.4)`.

**Right cluster:** Nav page links → user email and role metadata → Logout button → Theme toggle.

### Nav links — inline style pattern

Nav links are `<button>` elements. Active state is applied by spreading `navLinkActive` over
`navLinkBase` via the ternary pattern — never via a className or CSS class toggle:

```tsx
const navLinkBase: React.CSSProperties = {
  background: 'none',
  backgroundColor: 'transparent',   // explicit — prevents browser default white bg
  border: 'none',
  color: 'rgba(255,255,255,0.45)',
  cursor: 'pointer',
  fontFamily: 'var(--fb)',
  fontSize: 9,
  letterSpacing: '2px',
  textTransform: 'uppercase',
  padding: '5px 8px',
  borderRadius: 6,
  transition: 'color 0.15s, background-color 0.15s',
}

const navLinkActive: React.CSSProperties = {
  color: 'var(--gold-light)',
  backgroundColor: 'rgba(201,168,76,0.12)',
}

// Usage
<button style={currentPage === id ? { ...navLinkBase, ...navLinkActive } : navLinkBase}>
  {label}
</button>
```

**Why `backgroundColor: 'transparent'` in base?** Without it, browsers apply their default
button background (white in light mode) when the component re-renders from active to inactive.
The explicit transparent value prevents the white flash.

### Page routing — no router library

Navigation is managed with a single `useState<Page>` in `App.tsx`. The `Page` union type
lists every valid route. Adding a new page requires:

1. Adding the string literal to the `Page` union in `App.tsx`
2. Adding a `case` to the `renderPage()` switch
3. Adding the entry to the `pages` array in `Nav.tsx`

No URL changes, no history API, no `react-router-dom`. This is appropriate for a dashboard
used as a single-tab tool where deep-linking is not required.

### Current pages

| ID | Label | Component |
|---|---|---|
| `dashboard` | Dashboard | `DashboardPage` |
| `segments` | Segments | `SegmentsPage` |
| `campaign-launcher` | Campaigns | `CampaignLauncherPage` |
| `analytics` | Analytics | `AnalyticsPage` |
| `info` | Info | `InfoPage` |
| `admin` | Admin | `AdminPage` |

Pages not shown in nav (no nav entry): `segment-builder`, `segment-detail`,
`simulation-results`, `login`.

---

## 8. Page Structure Pattern

Every page follows the same vertical structure:

```
┌──────────────────────────────────┐
│  HERO SECTION (dark navy)        │  ← always dark, grid texture
│  Eyebrow (light variant)         │
│  H1 with italic gold keyword     │
│  Subtitle in rgba white          │
│  [Optional: stat row / tab bar]  │
├──────────────────────────────────┤
│  BODY (var(--light) background)  │
│                                  │
│  [KPI row if applicable]         │
│                                  │
│  SECTION                         │
│    Eyebrow (dark variant)        │
│    H2 section title              │
│    Body content                  │
│                                  │
│  SECTION                         │
│    ...                           │
│                                  │
└──────────────────────────────────┘
│  FOOTER (dark navy)              │
└──────────────────────────────────┘
```

### Hero section

```tsx
const heroStyle: React.CSSProperties = {
  backgroundColor: 'var(--primary)',
  backgroundImage: `
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
  `,
  backgroundSize: '48px 48px',
  padding: '48px 48px 0',  // bottom 0 when a tab bar attaches at the bottom
  // or '56px 48px' when the hero is self-contained
}
```

The `backgroundImage` grid texture is the same across every hero on every page. The grid
lines are `rgba(255,255,255,0.025)` — barely visible, but they give the navy a woven
structure at high brightness.

**`padding-bottom: 0`** when the page has a tab bar (Analytics, Info). The tab bar's
`marginBottom: -1` on the active tab merges its bottom border with the section divider,
creating a visual connection between the nav and the content below. If the hero has no
tab bar, use `padding: '56px 48px'`.

### Body section

The body sits on `var(--light)` (`#f4f6f9`). Each section uses:

```tsx
const section: React.CSSProperties = {
  maxWidth: 'var(--max-width-dashboard)',
  margin: '0 auto',
  padding: '40–56px 48px',
}
```

### Eyebrow placement rule

- On dark (hero) backgrounds → `<Eyebrow light>Label</Eyebrow>` — renders in `var(--gold-light)`
- On light (`var(--light)` or `var(--white)`) backgrounds → `<Eyebrow>Label</Eyebrow>` — renders in `var(--gold)`

**Never** use the dark variant on a light background or the light variant on a dark background.
The contrast ratios are designed for their respective contexts.

### Tab bar pattern

Used on Analytics and Info pages. The tab bar sits at the bottom of the hero, visually
bridging it to the body:

```tsx
<button style={{
  ...
  borderBottom: `2px solid ${active === id ? 'var(--gold-light)' : 'transparent'}`,
  marginBottom: -1,   // merges with hero's bottom edge
  color: active === id ? 'var(--gold-light)' : 'rgba(255,255,255,0.4)',
}}>
```

---

## 9. Component Catalogue

### `Eyebrow`

`dashboard/src/components/Eyebrow.tsx`

Renders a gold horizontal rule + uppercase label. Props: `children`, `light?: boolean`.

```tsx
<Eyebrow>Section name</Eyebrow>      // gold, for light backgrounds
<Eyebrow light>Section name</Eyebrow> // gold-light, for dark backgrounds
```

Eyebrow labels are max 4 words. No leading numbers (not "01 · Metrics" — just "Metrics").

### Card

No shared `Card` component exists — cards are inline style objects defined per-page as
`const card: React.CSSProperties`. The standard values are:

```tsx
const card: React.CSSProperties = {
  backgroundColor: 'var(--white)',
  borderRadius: 'var(--radius-md)',   // 12px
  padding: '28px',
  boxShadow: 'var(--shadow-card)',    // 0 1px 4px rgba(0,51,102,0.08)
  border: '1px solid var(--primary-10)',
}
```

Danger zone cards add `border: '1px solid rgba(176,53,53,0.18)'` and a reddish background
tint. Callout / note cards add `borderLeft: '3px solid var(--gold)'`.

### KPI stat card (dashboard variant)

```tsx
function KpiCard({ label, value, sub, valueColor }: { label: string; value: string; sub?: string; valueColor?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 16, ...card }}>
      <div style={{ width: 3, backgroundColor: 'var(--gold)', borderRadius: 2, flexShrink: 0 }} />
      <div>
        <div style={{ fontFamily: 'var(--fd)', fontSize: 30, fontWeight: 300,
                      color: valueColor ?? 'var(--dark)' }}>{value}</div>
        <div style={{ fontFamily: 'var(--fb)', fontSize: 10, textTransform: 'uppercase',
                      letterSpacing: '3px', color: 'var(--mid)', marginTop: 5 }}>{label}</div>
      </div>
    </div>
  )
}
```

The left accent bar (`width: 3, height: 100%`) always uses `var(--gold)`. Do not use per-KPI status colours for the structural accent bar, regardless of what the metric represents. If a KPI value represents a critical risk, express it in the value text colour (`valueColor` prop) — not the bar colour.

### KPI stat (hero / banner variant)

Used inside dark hero sections — no card wrapper:

```tsx
<div style={{ borderLeft: '2px solid var(--gold)', paddingLeft: 18 }}>
  <div style={{ fontFamily: 'var(--fd)', fontSize: 34, fontWeight: 300,
                color: 'var(--gold-light)', lineHeight: 1, marginBottom: 8 }}>
    {value}
  </div>
  <div style={{ fontFamily: 'var(--fb)', fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>
    {label}
  </div>
</div>
```

The `borderLeft` is always `2px solid var(--gold)`. Every hero stat card across every page uses the same accent — do not vary by metric type, severity, or department. The value text uses `var(--gold-light)` uniformly on dark backgrounds.

### Score / KPI card (body variant with `borderTop`)

Used for standalone metric cards in the body sections (not in the hero). The top accent border is always gold — it is structural, not semantic:

```tsx
<div style={{
  ...card,                                  // base card style
  borderTop: '3px solid var(--gold)',       // always gold — never a status colour
  paddingTop: 20,
}}>
  <div style={{ fontFamily: 'var(--fb)', fontSize: 9, textTransform: 'uppercase',
                letterSpacing: '3px', color: 'var(--mid)', marginBottom: 8 }}>
    {label}
  </div>
  <div style={{ fontFamily: 'var(--fd)', fontSize: 28, fontWeight: 300,
                color: valueColor }}>       {/* valueColor may be a status colour for critical KPIs */}
    {value}
  </div>
</div>
```

The `valueColor` may contextually use a status colour (e.g., `var(--status-red)` for critical attrition rates, `var(--status-orange)` for budget warnings) — but only on the value numeral, never the label, the card border, or any surrounding structural element.

### Status badge / sentiment pill

Pill-shaped indicator with a 5px dot + label:

```tsx
<div style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
              backgroundColor: bg, borderRadius: 'var(--radius-pill)',
              padding: '2px 8px' }}>
  <div style={{ width: 5, height: 5, borderRadius: '50%', backgroundColor: color }} />
  <span style={{ fontFamily: 'var(--fb)', fontSize: 10, textTransform: 'capitalize',
                 fontWeight: 600, color }}>{label}</span>
</div>
```

The `bg` and `color` values come from the semantic status colour system, never from
arbitrary values.

### Tables

All data tables follow the same pattern:

- `<thead>`: `backgroundColor: 'var(--primary)'`, `color: '#fff'`, `10px uppercase`,
  `letterSpacing: '2px'`, `padding: '12px 16px'`
- `<tbody>` rows: alternating `var(--white)` / `var(--primary-10)` via `i % 2 === 0`
- Cell padding: `10px 16px`
- Sort buttons are `<th>` elements with `onClick` — the sort indicator is a plain `▾` or `▴`
  character appended to the label string

### Toast / feedback message

```tsx
function Toast({ msg, ok }: { msg: string; ok: boolean }) {
  return (
    <div style={{
      fontFamily: 'var(--fb)', fontSize: 12,
      color:           ok ? '#22943a' : '#b03535',
      backgroundColor: ok ? 'rgba(34,148,58,0.07)' : 'rgba(176,53,53,0.07)',
      border:          `1px solid ${ok ? 'rgba(34,148,58,0.2)' : 'rgba(176,53,53,0.2)'}`,
      borderRadius: 8, padding: '10px 16px', marginTop: 16,
    }}>
      {msg}
    </div>
  )
}
```

### Confirm modal

Destructive actions (delete, clear) open a confirmation modal rather than executing
immediately. The modal uses a fixed-position overlay at `zIndex: 200`:

```tsx
// Overlay
position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.45)',
display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200

// Modal panel
backgroundColor: '#fff', borderRadius: 14, padding: '32px 36px',
maxWidth: 400, width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.2)'
```

The modal has a Cancel (ghost) button and a destructive action button (red background `#b03535`).

### Decorative section numerals

Used on cards that have a numbered sequence (capability cards on Dashboard, step cards on Info):

```tsx
<div style={{
  fontFamily: 'var(--fd)', fontSize: 44, fontWeight: 300,
  color: 'var(--primary-30)',   // ← navy-tinted, not grey
  lineHeight: 1, marginBottom: 2, userSelect: 'none',
}}>
  {num}
</div>
<div style={{ width: 36, height: 3, backgroundColor: 'var(--gold)', borderRadius: 2, margin: '6px 0 12px' }} />
```

The number is decorative — it identifies the card's position without being the focal point.
`userSelect: 'none'` prevents accidental selection on click. The 3px gold accent bar sits
between the number and the title.

---

## 10. Dark Mode

### Implementation

Theme is stored in `localStorage` under the key `spb-theme`. It is read once on mount in
`useTheme.ts` and applied by setting `data-theme` on `document.documentElement`:

```ts
function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}
```

CSS overrides are then applied via the attribute selector in `tokens.css`:

```css
html[data-theme="dark"] {
  --light:      #0f1117;   /* Page background darkens */
  --white:      #1a1d27;   /* Card surfaces darken */
  --dark:       #e2e8f0;   /* Text lightens */
  --mid:        #8b9099;   /* Secondary text lightens */
  --primary-10: rgba(255,255,255,0.07);  /* Subtle light tint on dark surfaces */
  --shadow-card: 0 1px 4px rgba(0,0,0,0.35);
  --shadow-soft: 0 1px 6px rgba(0,0,0,0.3);
}
```

The primary navy, gold, and status colours are **not** overridden in dark mode — they remain
the same. The nav, heroes, and footers use the navy background in both modes; dark mode only
affects the body (light) and card (white) surfaces.

### Default theme

The application defaults to **light mode**. The fallback in `getInitialTheme()` returns
`'light'` unconditionally when no stored preference exists — the OS `prefers-color-scheme`
preference is ignored. The user can toggle with the `◑ Dark` / `☀ Light` button in the
nav bar.

### What components need to do to support dark mode

Because all colours use `var(--token)` references, most components get dark mode for free.
The only patterns to watch:

- **Hardcoded `#ffffff`**: Anywhere the code uses literal `#ffffff` instead of `var(--white)`,
  that surface will not darken. Always use `var(--white)` for card surfaces.
- **Hardcoded `#f4f6f9`** or `#F4F6F9`: Use `var(--light)` instead.
- **Hardcoded `rgba(0,51,102,0.XX)`**: For subtle navy tints, use `var(--primary-10)` or the
  appropriate opacity variant. On dark mode, `--primary-10` is overridden to a light white
  tint that achieves the same visual effect on dark surfaces.

---

## 11. State Management

### Auth store (`authStore.ts`)

```ts
interface AuthState {
  token: string | null
  user: { email: string; role: string } | null
  setAuth: (token: string, user: { email: string; role: string }) => void
  clearAuth: () => void
}
```

The token is persisted to `localStorage` under `spb_auth_token`. `clearAuth()` removes both
the store state and the `localStorage` entry. The `user` object is populated from the JWT
payload on login.

`App.tsx` reads `token` to decide whether to render the `LoginPage` or the main app.

### Campaign store (`campaignStore.ts`)

Holds the multi-step campaign launcher form across page navigations. The `resetForm()` method
is called when the user starts a new campaign after viewing simulation results.

### No server state library

There is no React Query, SWR, or similar caching layer. Each page's `useEffect` fetches
directly from the `api` service on mount. This is sufficient for the current use case —
simulation results are not frequently updated in the background and the data volume does not
require pagination beyond the 100-item server cap.

---

## 12. API Layer

All HTTP calls go through `dashboard/src/services/api.ts`. **No component imports `fetch`
directly.** This is enforced by convention, not tooling.

### Structure

```ts
export const api = {
  health: () => request<HealthResponse>('/health'),

  segments: {
    list: () => request<{ items: SegmentSummary[] }>('/segments?size=100').then((r) => r.items),
  },

  simulations: {
    run:  (body) => request<SimulationRunResponse>('/simulate/run', { method: 'POST', body }),
    get:  (id)   => request<SimulationRunResponse>(`/simulate/runs/${id}`),
    list: (params) => request<{ items: ... }>(`/simulate/runs?...`).then((r) => r.items),
  },

  admin: { stats, seed, clear },
  auth:  { devToken, createKey, listKeys, revokeKey },
  org:   { get, listMembers, inviteMember, removeMember },
}
```

### Pagination unwrapping

All list endpoints on the backend return `{ items: T[], total, page, size }`. The `api` layer
unwraps this transparently — calling code receives `T[]` directly. This avoids the `.items`
access being scattered across every component that calls a list endpoint.

### Auth headers

The `request()` function reads `spb_auth_token` from `localStorage` and adds
`Authorization: Bearer <token>` to every request. The backend's `AUTH_REQUIRED=false` default
means this header is optional in development.

### Interface discipline

The TypeScript interfaces in `api.ts` must exactly match the backend Pydantic response models.
Invented fields (fields that exist in the interface but not in the API response) will be
`undefined` at runtime but typed as their declared type — TypeScript will not catch this.
Before adding a field to an interface, verify it in the actual API response JSON.

---

## 13. Inline Styles vs CSS Modules vs Tailwind

The application uses **inline styles exclusively**. No Tailwind, no CSS Modules, no styled-components.

### Rationale

1. **Design token enforcement**: Inline styles that reference `var(--token)` names make it
   immediately visible when a hardcoded value is used instead. In a Tailwind class like
   `text-blue-800`, the actual hex value is invisible and designers cannot audit it.

2. **No CSS specificity battles**: Every style is scoped to the exact element it is applied to.
   There is no class specificity cascade to debug.

3. **TypeScript coverage**: `React.CSSProperties` catches misspelled property names and invalid
   values at compile time. `className` strings have no type safety.

4. **Design fidelity**: The OPB design system uses precise values (e.g., `rgba(201,168,76,0.12)`
   for active nav backgrounds) that have no Tailwind equivalent. Approximating them with utility
   classes would break the visual system.

### Style object pattern

Styles are defined as `const` objects at the top of each file, outside the component function.
This prevents recreation on every render. Large shared style objects (like `heroStyle`,
`card`, `section`) are defined once and spread or referenced by multiple elements:

```tsx
// Define outside component
const card: React.CSSProperties = {
  backgroundColor: 'var(--white)',
  borderRadius: 'var(--radius-md)',
  padding: '28px',
  boxShadow: 'var(--shadow-card)',
}

// Use in component
<div style={card}>...</div>

// Extend for variants
<div style={{ ...card, borderLeft: '3px solid var(--gold)' }}>...</div>
```

---

## 14. Migration Guide

This section explains exactly how to apply the OPB design system to a new or existing React
application.

### Step 1 — Fonts

Add to `<head>` in `index.html`:

```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;1,9..144,300;1,9..144,400&display=swap" rel="stylesheet">
```

### Step 2 — Tokens

Copy `dashboard/src/styles/tokens.css` verbatim into the new project. Import it once at the
top of the entry file (`main.tsx` or equivalent). Do not modify the token values — they are
the brand.

### Step 3 — Base reset

The CSS reset is included in `tokens.css` after the token definitions. It sets:
- `box-sizing: border-box` on everything
- `body` to `background-color: var(--light)`, `font-family: var(--fb)`, `font-size: 15px`,
  `line-height: 1.7`

### Step 4 — Copy the Eyebrow component

Copy `dashboard/src/components/Eyebrow.tsx` to the new project unchanged. It has no
dependencies beyond React. Use it as the section label on every content section.

### Step 5 — Build the Nav

Follow the Nav pattern from `dashboard/src/components/Nav.tsx`:

```tsx
// Minimum required nav structure
<nav style={navStyle}>                          {/* sticky, dark navy, 52px */}
  <span>[OPB Monogram]</span>                  {/* Fraunces O + italic gold PB */}
  <span style={appTitleStyle}>[App Name]</span> {/* 9px uppercase, muted */}
  <div style={{ display: 'flex', gap: 16 }}>
    {pages.map(({ id, label }) => (
      <button style={currentPage === id ? {...navLinkBase, ...navLinkActive} : navLinkBase}
              onClick={() => navigate(id)}>
        {label}
      </button>
    ))}
    {/* Theme toggle, logout, user info as needed */}
  </div>
</nav>
```

**Critical:** Include `backgroundColor: 'transparent'` in `navLinkBase`. Without it, inactive
nav buttons show a white background in light mode when transitioning from active state.

### Step 6 — Build a page

Every page follows this template:

```tsx
export default function MyPage() {
  return (
    <div>
      {/* 1. Hero */}
      <div style={heroStyle}>
        <div style={{ maxWidth: 'var(--max-width-dashboard)', margin: '0 auto' }}>
          <Eyebrow light>Section eyebrow</Eyebrow>
          <h1 style={{ fontFamily: 'var(--fd)', fontSize: 36, fontWeight: 300, color: '#fff' }}>
            Title with <em style={{ fontStyle: 'italic', color: 'var(--gold-light)' }}>italic</em>
          </h1>
          <p style={{ fontFamily: 'var(--fb)', fontSize: 14, color: 'rgba(255,255,255,0.55)' }}>
            Subtitle text.
          </p>
        </div>
      </div>

      {/* 2. Body */}
      <div style={{ backgroundColor: 'var(--light)', minHeight: '70vh' }}>
        <div style={{ maxWidth: 'var(--max-width-dashboard)', margin: '0 auto', padding: '40px 48px' }}>

          {/* Section */}
          <div style={card}>
            <Eyebrow>Section label</Eyebrow>
            <h2 style={{ fontFamily: 'var(--fd)', fontSize: 22, fontWeight: 300, color: 'var(--dark)' }}>
              Section title
            </h2>
            <p style={{ fontFamily: 'var(--fb)', fontSize: 14, color: '#475569', lineHeight: 1.75 }}>
              Body text.
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
```

### Step 7 — Wire routing

In `App.tsx`:

```tsx
export type Page = 'home' | 'my-page' | 'login'

export default function App() {
  const [page, setPage] = useState<Page>('home')

  const renderPage = () => {
    switch (page) {
      case 'home':    return <HomePage />
      case 'my-page': return <MyPage />
      case 'login':   return <LoginPage />
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Nav currentPage={page} onNavigate={setPage} />
      <main style={{ flex: 1 }}>{renderPage()}</main>
      <Footer />
    </div>
  )
}
```

### Step 8 — API service

Create `src/services/api.ts` following the pattern in this project:

1. A base `request<T>(path, options)` function that handles auth headers, JSON
   serialisation, and error throwing
2. Domain-grouped methods: `api.things.list()`, `api.things.create(body)`, etc.
3. Pagination unwrapping done inside `api.ts` — components receive `T[]`, not `{ items: T[] }`
4. TypeScript interfaces that exactly match the backend response shapes

### Step 9 — Dark mode

Copy `useTheme.ts` and add the dark mode overrides from `tokens.css` to your token file.
Add the toggle button to the nav. That is all — as long as every component uses token
references (`var(--white)`, `var(--light)`) instead of hardcoded hex values, dark mode works
without any component-level changes.

### Common mistakes to avoid

| Mistake | Correct approach |
|---|---|
| Hardcoding `#ffffff` in a card | Use `var(--white)` |
| Hardcoding `#f4f6f9` as a background | Use `var(--light)` |
| Using `rgba(0,51,102,0.X)` directly | Use `var(--primary-10)` or the closest token |
| Setting `color: 'gold'` or `color: 'navy'` | Use `var(--gold)` and `var(--primary)` |
| Creating a new status colour | Use the five semantic status tokens |
| Using Fraunces for body text | Fraunces is display-only |
| Bolding a Fraunces title | Use weight 300 or 400, never 700 |
| Applying an Eyebrow without the line | Use the `<Eyebrow>` component — it renders the line |
| Omitting `backgroundColor: 'transparent'` on nav links | Causes white flash on inactive buttons in light mode |
| Adding `stimulus_type` to `SimulationRunResponse` interface without verifying the actual API response | Type-safe undefined at runtime |
| Using a status colour (`--status-red`, `--status-orange`, `--status-green`, `--status-purple`) for a card `borderLeft` or `borderTop` | Use `var(--gold)` for all structural accent borders — status colours belong only in value text and status badges |
| Varying `borderLeft` colour across hero stat cards by metric type or severity | All hero stat cards use `borderLeft: '2px solid var(--gold)'` uniformly — no per-metric colour variation |
| Using green, purple, or orange in a categorical chart series | Use the navy gradient series + gold highlight only; status colours in charts imply semantic meaning (success, analytics, warning) and confuse readers when used decoratively |
| Using hex values not in the design system in SVG `fill` or `stroke` attributes | SVG attributes cannot use CSS custom properties — use the exact hex values from the design token list (e.g., `#003366`, `#c8982a`, `#99bbdd`); values like `#c0cfe0` or `#00a86b` are bugs |
| Building a variance badge background by string-manipulating a CSS `var()` name (e.g., appending `14` to `var(--status-red)`) | CSS `var()` names cannot be concatenated to produce valid CSS — define a proper helper function that returns valid `rgba()` or semantic background tokens based on a numeric condition |
| Passing `accent` colour prop to a stat or KPI card component and using it for `borderTop` or `borderLeft` | Remove the structural colour prop; hardcode `var(--gold)` for the border; pass a separate `valueColor` prop only if the value numeral needs a contextual status colour |

---

*Last updated: 2026-05-18. Maintained by Octavio Pérez Bravo.*
