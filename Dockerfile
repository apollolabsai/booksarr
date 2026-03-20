# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /config/cache/authors /config/cache/books

ARG BUILD_BRANCH=unknown
ARG BUILD_COMMIT=unknown
ARG BUILD_DATE=unknown

ENV PYTHONPATH=/app
ENV CONFIG_DIR=/config
ENV BOOKS_DIR=/books
ENV PORT=8889
ENV BUILD_BRANCH=$BUILD_BRANCH
ENV BUILD_COMMIT=$BUILD_COMMIT
ENV BUILD_DATE=$BUILD_DATE

EXPOSE 8889

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8889"]
