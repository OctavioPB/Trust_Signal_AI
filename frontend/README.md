# TrustSignal AI — Recruiter Dashboard redesign

Drop-in files for `Trust_Signal_AI/frontend/src/`.

The redesign is **purely visual + compositional**. All back-end behaviour — API
auth, polling, demo store, PDF download, theme toggle — is preserved 1:1.
Every component prop signature matches the previous version, so the only file
you have to *read* before applying is `App.tsx` (one new component is mounted).

---

## What changes

| Surface | Before | After |
|---|---|---|
| **Shell** | 52px nav strip, 9px text, navy footer | `TopBar` with OPB monogram, product wordmark, page tabs, user chip; gradient accent bar; dark footer |
| **Sidebar** | Navy block with form fields | White rail with OPB eyebrows, monospaced inputs, gold primary CTA, animated polling pill |
| **Hero** | Cramped headline + 4 hero stats + small gauge | Navy hero with grid texture, big italic-gold title, meta strip, **300px speedometer gauge** with needle, active-zone arc, and gold `35 · FLAG` tick |
| **KPI row** | Plain cards, gold accent bar | Same idea — but bigger Fraunces 38 numbers, status badges in the top-right of each card, tier-coloured accent |
| **Signal Breakdown** | Single SVG bar chart | Two-column: per-signal list (raw + weighted bars + tier number) **and** a Contribution Mix donut with the suspicion index in the centre |
| **Alert** | Red-tinted box with bullet list | OPB callout — red left-border card with *top 3 contributing signals*. New "cleared" variant for non-flagged sessions |
| **Transcript** | Full-row red wash on suspicious turns | Subtle 4px coloured heat bar on the left of each turn — saturation scales with suspicion. Score chip on the right |
| **Tokens** | Limited palette | Full OPB families (`--rojo`, `--verde`, `--naranja`, `--morado`, `--rosa`, plus `--*-ice`, `--*-dark`); legacy aliases (`--red`, `--green`, `--orange`) preserved so any leftover code keeps resolving |

Nothing changes about: `services/api.ts`, `hooks/usePolling.ts`, `stores/*.ts`,
`types.ts`, the FastAPI back-end, the existing tests.

---

## Files in this drop

```
src/
├── App.tsx                                  REPLACES existing
├── styles/
│   ├── tokens.css                           REPLACES existing
│   └── dashboard.css                        NEW — must be imported
├── pages/
│   └── SessionPage.tsx                      REPLACES existing
└── components/
    ├── Eyebrow.tsx                          NEW
    ├── TopBar.tsx                           NEW
    ├── Sidebar.tsx                          REPLACES existing
    ├── TrustScoreGauge.tsx                  REPLACES existing
    ├── KpiRow.tsx                           REPLACES existing
    ├── SignalBreakdownChart.tsx             REPLACES existing
    ├── AlertPanel.tsx                       REPLACES existing
    └── TranscriptView.tsx                   REPLACES existing
```

---

## Apply

```bash
# from Trust_Signal_AI/
cp -r path/to/repo-handoff/src/* frontend/src/
```

Then add one import to `frontend/src/main.tsx`:

```diff
 import { StrictMode } from "react";
 import { createRoot } from "react-dom/client";
 import "./styles/tokens.css";
 import "./index.css";
+import "./styles/dashboard.css";
 import App from "./App.tsx";

 createRoot(document.getElementById("root")!).render(
   <StrictMode>
     <App />
   </StrictMode>,
 );
```

That's the only edit outside the dropped files.

---

## Run + verify

```bash
cd frontend
npm install              # no new deps were added
npm run dev
```

Then in the browser:

1. The page should load with the new navy `TopBar`, gradient strip, and white
   rail. Click **Load Demo** in the rail — the dashboard fills in with the
   flagged scenario from `demoStore`.
2. The gauge needle should point to ~31.5, in the red zone. The gold tick at
   `35 · FLAG` sits just to its right.
3. The Contribution Mix donut shows 24.6% / 15.6% / 14.2% / etc. The numbers
   are computed from `signal.weighted_contribution` divided by the sum — they
   should add to 100%.
4. Toggle theme via the `◑` button top-right. The hero stays dark (per
   `BRAND.md §Nav`); the body switches.
5. Run the existing test suite to confirm nothing in `services/api.ts` was
   touched:
   ```
   npm test
   ```

If anything looks off, the most likely culprit is missing CSS — make sure
`dashboard.css` is imported in `main.tsx` (step above).

---

## Notes for future work

- The rail has a commented `// TODO: real session list goes here` block. When
  you ship a `/sessions` endpoint, plug it in there — the supporting
  `.session-list` / `.session-item` styles are already in `dashboard.css`.
- The new `TopBar` exposes four pages (`session`, `analytics`, `models`,
  `settings`). Only `session` is wired today; the others show a placeholder.
- `SIGNAL_SUBS` in `SignalBreakdownChart.tsx` is a hand-curated sub-label map.
  If you'd rather drive these from the back-end, add `signal_sub: str` to
  `SignalDetail` in `types.ts` + `api/main.py` and remove the map.
- The TrustScore gauge's `FLAG_TICK` (35/100) must stay in sync with the
  back-end's `FLAG_THRESHOLD`. Both are documented in the file.

---

## Reference

`TrustSignal Dashboard.html` (in the design-system project) is the
fully-interactive prototype these files were built from. Use it to compare
the live React output against the design intent.
