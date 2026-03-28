FROM python:3.11-slim AS builder

RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/
RUN mkdir -p /app/uploads /app/outputs

ENV UPLOAD_DIR=/app/uploads
ENV OUTPUT_DIR=/app/outputs

EXPOSE 8000
CMD ["uvicorn", "autoclip.main:app", "--host", "0.0.0.0", "--port", "8000"]
