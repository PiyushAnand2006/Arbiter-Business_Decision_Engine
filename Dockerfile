# Arbiter: one container serves the API and the built dashboard.
#   docker build -t arbiter . && docker run -p 7860:7860 arbiter   ->  http://localhost:7860
# Runs the mock provider by default (no API key). Set LLM_PROVIDER and a key as env vars to use a real model.

# 1) Build the React dashboard
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) Python runtime
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --disable-pip-version-check -r backend/requirements.txt
COPY --chown=user backend/ backend/
COPY --chown=user --from=web /web/dist frontend/dist
RUN mkdir -p data && chown user:user data
USER user
WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
