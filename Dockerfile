# syntax=docker/dockerfile:1
# One image for the API (serves the built web app too) and the worker; compose picks the command.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy FRONTEND_DIST=/app/frontend/dist
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --system --uid 10001 gohigh
USER gohigh
ENV PATH=/app/backend/.venv/bin:$PATH
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
# X-Forwarded-For is trusted only from FORWARDED_ALLOW_IPS (default 127.0.0.1): set it to the load balancer's
# address, never "*", or any client can pick its own IP and dodge the sign-in throttle.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
