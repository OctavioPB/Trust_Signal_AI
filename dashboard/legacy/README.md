# dashboard/legacy — Streamlit Dashboard (Deprecated)

> **Status: LEGACY — no new feature work.**
> Superseded by the React frontend (`frontend/`) as of Sprint 13.

## What this is

The original Streamlit recruiter dashboard built in Sprint 8. It connects to the same
FastAPI backend (`api/main.py`) and supports the same demo mode, live polling, and PDF
export as the React app.

## Why it was moved here

The React + Vite frontend (`frontend/`) delivers feature parity with a significantly better
developer experience (TypeScript strict mode, component isolation, Vitest unit tests,
Playwright e2e tests, dark mode). The Streamlit app receives no new feature work but
remains runnable for back-compat reference and regression comparison.

## Running it (reference only)

```bash
# From the project root
streamlit run dashboard/legacy/app.py
# → http://localhost:8501
```

Requires:
- `pip install streamlit plotly fpdf2` (or `pip install -r requirements.txt`)
- FastAPI backend running: `uvicorn api.main:app --reload`

## Preferred alternative

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The React app is the primary UI. Use it for all new development and demos.
