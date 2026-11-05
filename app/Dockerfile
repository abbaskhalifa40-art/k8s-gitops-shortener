# syntax=docker/dockerfile:1

# ---- Stage 1: install dependencies into a virtualenv ----
FROM python:3.13-slim AS builder
WORKDIR /build
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: small runtime image ----
FROM python:3.13-slim
# Run as a non-root user with a fixed UID, so Kubernetes can enforce
# runAsNonRoot and the pod security "restricted" standard.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /venv /venv
COPY src/ /app/
WORKDIR /app
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
# exec form, so uvicorn is PID 1 and receives SIGTERM for a clean shutdown.
CMD ["uvicorn", "shortener.main:app", "--host", "0.0.0.0", "--port", "8000"]
