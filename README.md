# MarketMind AI

MarketMind AI is a LangGraph-based multi-agent research system that turns a stock idea into a traceable, evidence-backed research and trading report.

## What This AI Agent Can Do

- Resolve a company name or noisy input into a validated ticker
- Check whether price data and fundamental data are available before running a full analysis
- Gather and combine market evidence, including:
  - price history
  - technical indicators
  - company fundamentals
  - company news
  - macro news
  - SEC filings
  - earnings transcripts
- Run a full multi-agent workflow with dedicated roles:
  - Market Analyst
  - Social Analyst
  - News Analyst
  - Fundamentals Analyst
  - Bull Researcher
  - Bear Researcher
  - Research Manager
  - Trader
  - Aggressive Risk Analyst
  - Conservative Risk Analyst
  - Neutral Risk Analyst
  - Portfolio Manager
- Generate:
  - market analysis
  - sentiment analysis
  - news event timelines
  - fundamentals analysis
  - bull and bear debate outputs
  - trading proposals
  - risk discussion outputs
  - final portfolio decisions
- Deterministically verify the final output before surfacing an actionable recommendation
- Save run history, decision memory, evaluation summaries, and state logs for later retrieval and review
- Resume interrupted runs with checkpoints
- Run from both the CLI and a browser-based web interface
- Support both offline mode and live provider mode

## How To Use

### 1. Install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You can also install the project as a local package:

```bash
pip install -e .
```

After that, you can use:

```bash
marketmind-ai
```

### 2. Run the full workflow in offline mode

Offline mode does not require API keys and runs the complete multi-agent flow locally:

```bash
marketmind-ai analyze NVDA --date 2026-06-12 --llm-provider offline --quick-model heuristic-fast --deep-model heuristic-deep
```

If you prefer the module entrypoint:

```bash
python -m marketmind_ai.cli analyze NVDA --date 2026-06-12 --llm-provider offline --quick-model heuristic-fast --deep-model heuristic-deep
```

### 3. Print the final result as JSON

```bash
marketmind-ai analyze NVDA --date 2026-06-12 --llm-provider offline --quick-model heuristic-fast --deep-model heuristic-deep --json
```

### 4. Use the interactive CLI

This mode walks you through ticker, provider, model, analyst selection, and research depth:

```bash
marketmind-ai interactive
```

### 5. Resolve a ticker without running a full analysis

```bash
marketmind-ai resolve "NVIDIA"
```

### 6. Validate a remote LLM provider

```bash
marketmind-ai validate-provider --llm-provider openai --quick-model gpt-5.4-mini --deep-model gpt-5.4 --api-key YOUR_KEY
```

### 7. Start the web interface

```bash
marketmind-ai serve --host 127.0.0.1 --port 8000
```

Then open:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

The web interface supports:

- submitting analysis runs
- streaming agent progress in real time
- inspecting tool calls
- reviewing intermediate report sections
- reading the final decision

### 8. Enable checkpoint-based resume

```bash
marketmind-ai analyze NVDA --date 2026-06-12 --llm-provider offline --quick-model heuristic-fast --deep-model heuristic-deep --checkpoint
```

### 9. Use live providers

Supported LLM providers include:

- OpenAI
- Anthropic
- Google
- OpenRouter
- Ollama
- Azure OpenAI
- xAI-compatible APIs
- DeepSeek-compatible APIs
- Qwen-compatible APIs
- GLM-compatible APIs

What changes in live mode:

- OpenAI, Anthropic, and Google switch the multi-agent reasoning and report generation from the local offline engine to real remote LLMs
- Alpha Vantage enables live market data enrichment for supported price, news, fundamentals, transcript, and related dataflow routes
- Live quality depends on your own provider account, quota, network access, and API key configuration

API key requirements:

- OpenAI: you must supply your own API key, either with `--api-key` in the CLI or in the web UI API key field
- Anthropic: you must supply your own API key, either with `--api-key` in the CLI or in the web UI API key field
- Google: you must supply your own API key, either with `--api-key` in the CLI or in the web UI API key field
- Alpha Vantage: you must supply your own API key through the `ALPHA_VANTAGE_API_KEY` environment variable

This repository does not ship with any real API keys. If you publish this project to a public GitHub repository, each user must configure their own OpenAI, Anthropic, Google, and Alpha Vantage credentials locally.

Example:

```bash
marketmind-ai analyze NVDA \
  --date 2026-06-12 \
  --llm-provider openai \
  --quick-model gpt-5.4-mini \
  --deep-model gpt-5.4 \
  --api-key YOUR_KEY
```

If you want to enable live Alpha Vantage data, set:

```bash
export ALPHA_VANTAGE_API_KEY=YOUR_KEY
```

You can also switch providers in the web interface and paste your own API key there for the current session.

### 10. Default storage location

Run outputs are stored under:

```text
~/.marketmind
```

This includes:

- runs
- checkpoints
- memory
- evaluation
- logs

To use a custom storage directory:

```bash
--storage-root /your/path
```

## Typical Use Cases

- Turn a stock idea into a full multi-agent research report
- Compare bull, bear, and risk views on the same instrument
- Run reproducible local multi-agent research experiments
- Observe a real-time agent workflow from the CLI or browser

## Notes

- `offline` mode is designed for local development, testing, and demos
- live data and remote LLM providers require your own network access and API keys
- this project is for research and engineering purposes and is not investment advice
