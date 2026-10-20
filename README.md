# Prompt Search Agent

A local AIGC prompt retrieval and composition assistant built with LangChain
and LangGraph.

## Current Status

This repository currently contains only the project skeleton. Business logic
is intentionally not implemented yet.

## Setup

```powershell
uv sync
Copy-Item .env.example .env
```

Set `DEEPSEEK_API_KEY` in `.env`, then verify the environment:

```powershell
uv run python -c "import langchain, langgraph, langchain_deepseek; print('ok')"
```

## Planned Modules

- `config.py`: environment and application settings
- `llm.py`: DeepSeek chat model construction
- `models.py`: request and result models
- `search/`: search interfaces and the initial fake backend
- `chains/`: LangChain parsing and rendering chains
- `graph/`: LangGraph state, nodes, and workflow
- `cli.py`: command-line interface
