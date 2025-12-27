FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy configuration
COPY pyproject.toml .

# Install dependencies
RUN uv sync --no-dev --no-install-project

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

ENTRYPOINT ["python", "/app/src/ai_review/review.py"]
