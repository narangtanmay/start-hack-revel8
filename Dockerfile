# Containerised test/run image for the Revel8 agent.
# Build:  docker build -t revel8-agent .
# Test:   docker run --rm revel8-agent            # runs the test suite
# Shell:  docker run --rm -it revel8-agent bash
FROM python:3.13-slim

# uv for fast, locked dependency installs.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer first for caching.
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Full project (tests included) and dev deps for running pytest.
COPY . .
RUN uv sync --frozen || uv sync

# Default: run the test suite. Override the command to run the agent, e.g.
#   docker run --rm --env-file .env revel8-agent uv run python -m revel8_agent.cli status
CMD ["uv", "run", "pytest", "-q"]
