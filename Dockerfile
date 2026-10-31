# --- сборка SPA ---
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- приложение ---
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Omsk
WORKDIR /srv/app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY app/ ./app/
COPY tests/ ./tests/
COPY conftest.py ./
COPY --from=frontend /build/dist ./static
RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /srv/app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
