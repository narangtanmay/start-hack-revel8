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

## 2. Build & start the long-running services

```bash
docker compose build
docker compose up -d ollama web
docker compose exec ollama ollama pull "${LOCAL_LLM_MODEL:-qwen3:32b}"
```

> **Mac note:** Docker on macOS runs Ollama CPU-only, so a 32B model is slow.
> For real runs either pull a smaller model (e.g. `qwen3:8b`) and set
> `LOCAL_LLM_MODEL`, point `LOCAL_LLM_BASE_URL` at a host Ollama
> (`http://host.docker.internal:11434/v1`), or use the hosted `LLM_*` endpoint.

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
