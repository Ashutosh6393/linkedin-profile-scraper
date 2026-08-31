# uv's own image, so there is no install step for uv itself.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependencies are their own layer. A code change then rebuilds in seconds
# instead of re-resolving the lock file.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# Only the two runtime modules. Nothing else is copied, so .env cannot end up
# in the image even by accident.
COPY linkedin.py main.py ./

# Nothing here handles secrets, but a dependency with an RCE should not get
# root either.
RUN useradd --create-home app && chown -R app /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
