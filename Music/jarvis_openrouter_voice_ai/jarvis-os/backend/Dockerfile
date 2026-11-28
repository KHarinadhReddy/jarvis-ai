FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Never bake keys into the image; inject OPENROUTER_API_KEY / DEEPSEEK_API_KEY /
# DEVICE_TOKEN / ALLOW_MOCK / ALLOWED_ORIGINS at runtime on the hosting platform.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
