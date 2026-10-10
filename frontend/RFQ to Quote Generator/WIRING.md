# Forgequote UI: live wiring notes (for Shuang)

Shuang's Figma Make design, now driven by the QuotePilot API in `api/` instead of hard-coded mock rows.
Layout and styles are unchanged; additions are at the end of `src/index.css`.

## Run

```bash
# terminal 1 - API (repo root). Needs NICRRON_API_KEY in the root .env (git-ignored)
python -m uvicorn app:app --port 8001
# terminal 2 - this folder
pnpm install
PORT=5173 pnpm dev          # http://localhost:5173
```

`vite.config.ts` proxies `/v1` and `/health` to `http://127.0.0.1:8001` (override with `QUOTE_API_URL`).

## What's live vs placeholder

| Area | State |
|---|---|
| Default screen | Shuang's original design with its example data (`src/Example.tsx`), until **New RFQ** or an upload |
| Paste RFQ / Browse files / drag-drop | Live: `POST /v1/rfqs`, `POST /v1/rfqs/upload` - **any file**: PDF (scans too), photos/screenshots, .docx, .xlsx, CSV, email, text. Images and scanned PDFs are transcribed by Nicrron's vision model first (`ai/gateway.py: transcribe_images`) |
| Line table, status chips, pipeline steps | Live from the RFQ response (no confidence % in the API, so the column shows status) |
| Needs-your-attention card | Live: clarification questions with answer inputs -> `PATCH .../lines/{id}` |
| Approve ready lines / Draft quote | Live: `.../approve`, `.../quotes/draft` (draft only after every line is approved) |
| Copy buyer email | Live: `GET .../clarifications/email-draft` (draft only, never sent) |
| Quote assistant (avatar) | `src/Assistant.tsx` + `public/avatar/` - talks through each step; layers are pixel-aligned, don't re-crop the images |
| Sidebar pages (Overview, Catalog, Quotes, Audit log), search, profile, Block Convey card | Placeholders (no pages yet) |

## Files

- `src/api.ts` - typed client for every endpoint the UI uses (X-API-Key `rudco-demo-key`)
- `src/App.tsx` - the workspace, wired to `api.ts`
- `src/Assistant.tsx` - the talking avatar card; give it `message={{id, text}}` to make it speak

Feel free to move the assistant card anywhere; it only needs the `message` prop.
