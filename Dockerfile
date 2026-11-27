# One image for the pipeline's Python services (ledger mock now; posting service and relay in the next PRs).
# Synthetic data only. No secrets are baked in: they arrive as environment variables at run time (.dockerignore
# keeps .env and tests out of the build context).
FROM python:3.12.16-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/.venv

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY schemas ./schemas
COPY ops ./ops

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001
ENV PATH=/srv/.venv/bin:$PATH

CMD ["python", "-m", "app.ledger"]
