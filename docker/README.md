# Running the Revel8 agent in Docker

Everything is containerised: the **agent**, a local **Ollama** LLM, and a **web**
server for the live dashboard.

## 1. Configure

```bash
cp .env.example .env
# edit .env: REVEL8_API_KEY (team key), SEARCH_API_KEY (OSINT), and either the
# hosted LLM (LLM_BASE_URL/LLM_API_KEY/LLM_MODEL) or keep the local Ollama one.
```

`docker-compose.yml` overrides `LOCAL_LLM_BASE_URL` to `http://ollama:11434/v1`
inside the network, so you don't set that yourself.

## 2. Pick your LLM

The agent prefers the **hosted LLM** (`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`)
and falls back to a local Ollama only if those are unset.

**Default — the shared 48GB AMD cloud (recommended):** just fill the `LLM_*`
values in `.env`. 48GB VRAM runs `qwen3:32b`-class models comfortably, so no
local LLM container is needed. Start only the web dashboard:

```bash
docker compose build
docker compose up -d web
```

**Optional — a local Ollama** (e.g. offline, or self-hosting on a GPU box).
It lives behind a profile so it never starts by default:

```bash
docker compose --profile local-llm up -d ollama web
docker compose exec ollama ollama pull "${LOCAL_LLM_MODEL:-qwen3:8b}"
# leave LLM_* unset so the agent uses LOCAL_LLM_* (-> the ollama service)
```

> On macOS, in-container Ollama is CPU-only (slow), which is exactly why the
> AMD cloud is the default. To use a host/remote Ollama instead of the
> container, set `LOCAL_LLM_BASE_URL` (e.g. `http://host.docker.internal:11434/v1`).

## 3. Run the agent (one-off commands)

```bash
docker compose run --rm agent status
docker compose run --rm agent osint --scenario practice
docker compose run --rm agent run --target julius --touches 10
docker compose run --rm agent report          # rebuild runs/index.html
```

## 4. Watch it

Open **http://localhost:8080** — the dashboard auto-refreshes as the agent
writes each touch to `runs/`.

## 5. Just the tests (no stack needed)

```bash
docker build -t revel8-agent .
docker run --rm revel8-agent                   # runs pytest (109 tests)
```

## Stop

```bash
docker compose down            # add -v to also drop the pulled Ollama models
```
