FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts

COPY piper_server.py /app/piper_server.py

EXPOSE 5000

ENV PORT=5000

CMD ["python", "piper_server.py"]
