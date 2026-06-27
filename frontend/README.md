# MarketMind AI Frontend

This is the Next.js frontend for the MarketMind AI Web MVP.

It provides the browser-facing layer for the local stock-research workflow:

- enter an API key for the selected provider
- choose LLM provider and quick/deep models
- select which analysts to run
- validate the stock symbol before research starts
- watch live agent progress, tool activity, staged reports, and the final decision

This frontend is meant to work with the FastAPI backend in the main `marketmind_ai` package.

## What This App Covers

The current frontend focuses on a single guided research flow rather than a full multi-user product.

It is designed for:

- local development
- product prototyping
- end-to-end stock research runs against the existing MarketMind graph

It is not yet intended to be:

- a production multi-user dashboard
- a full portfolio-management UI
- a visual drag-and-drop workflow builder

## Local Development

### 1. Start the backend

From the project root:

```bash
source .venv/bin/activate
marketmind-ai serve --host 127.0.0.1 --port 8000
```

You can also use:

```bash
python -m marketmind_ai.cli serve --host 127.0.0.1 --port 8000
```

### 2. Configure the frontend

From the `frontend/` directory:

```bash
cp .env.local.example .env.local
```

By default, the frontend expects the backend at:

- `http://localhost:8000`

If needed, change `NEXT_PUBLIC_API_BASE_URL` in `.env.local`.

### 3. Install dependencies and run

```bash
npm install
npm run dev
```

Then open:

- [http://localhost:3000](http://localhost:3000)

## Expected Backend Integration

The frontend depends on the backend for:

- provider/model catalog loading
- symbol search and symbol resolution
- run creation
- SSE-based progress streaming
- final snapshot retrieval
- API key validation

Important routes used by the frontend include:

- `GET /providers/models`
- `POST /api/symbols/resolve`
- `POST /runs`
- `GET /runs/{id}/stream`
- `GET /runs/{id}/result`
- `GET /runs/{id}/report`
- `POST /validate-key`

## Product Notes

- API keys entered in the UI are intended for per-run use and are not part of a full credential-management system.
- Run state is currently optimized for local development and MVP workflows.
- The UI is designed around the existing stock-research graph, including symbol validation, staged reports, and final recommendation gating.

## Related Paths

- [`../marketmind_ai/web`](../marketmind_ai/web) — FastAPI backend
- [`../marketmind_ai/graph`](../marketmind_ai/graph) — orchestration logic
- [`../marketmind_ai/symbols`](../marketmind_ai/symbols) — symbol resolution and validation
- [`../README.md`](../README.md) — project overview
