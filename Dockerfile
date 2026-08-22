FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts

COPY . /app

# Előre letöltjük a magyar Imre modellt a Docker build fázisban curl -L segítségével
RUN mkdir -p /app/piper_models && \
    curl -L -o /app/piper_models/hu_HU-imre-medium.onnx "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/imre/medium/hu_HU-imre-medium.onnx" && \
    curl -L -o /app/piper_models/hu_HU-imre-medium.onnx.json "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/imre/medium/hu_HU-imre-medium.onnx.json"

EXPOSE 5000

ENV PORT=5000

CMD ["python", "piper_server.py"]
