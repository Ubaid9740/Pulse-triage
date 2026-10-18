# Multi-stage Dockerfile: Builds Dashboard + Runs FastAPI Backend
FROM node:20-slim AS frontend-builder
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Install Python requirements
COPY server/requirements.txt ./server/
RUN pip install --no-cache-dir -r server/requirements.txt

# Copy backend, shared schemas, scenario packs and built dashboard
COPY shared/ ./shared/
COPY server/ ./server/
COPY scenario/ ./scenario/
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

ENV PYTHONUNBUFFERED=1
ENV PT_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "server"]
