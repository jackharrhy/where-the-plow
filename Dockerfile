FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY CHANGELOG.md cli.py ./
RUN uv run python cli.py changelog

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "where_the_plow.main:app", "--host", "0.0.0.0", "--port", "8000"]
