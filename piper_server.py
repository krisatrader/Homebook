#!/usr/bin/env python3
"""
Homebook Pro - Piper AI Magyar Neurális TTS Szerver
===================================================
Egyetlen paranccsal elindítható, villámgyors helyi és felhős TTS mikroszolgáltatás.
Támogatott magyar hangmodellek:
- hu_HU-imre-medium (Imre - Férfi)
- hu_HU-anna-medium (Anna - Női)
- hu_HU-berta-medium (Berta - Női)

Használat:
  pip install piper-tts
  python piper_server.py

Port: 5000 (vagy PORT környezeti változó)
"""

import os
import sys
import json
import urllib.request
import subprocess
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", 5000))
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper_models")

VOICE_URLS = {
    "hu_HU-imre-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/imre/medium/hu_HU-imre-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/imre/medium/hu_HU-imre-medium.onnx.json"
    },
    "hu_HU-anna-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/anna/medium/hu_HU-anna-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/anna/medium/hu_HU-anna-medium.onnx.json"
    },
    "hu_HU-berta-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/berta/medium/hu_HU-berta-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hu/hu_HU/berta/medium/hu_HU-berta-medium.onnx.json"
    }
}

def ensure_model(voice_name="hu_HU-imre-medium"):
    if voice_name not in VOICE_URLS:
        voice_name = "hu_HU-imre-medium"
    
    os.makedirs(MODELS_DIR, exist_ok=True)
    onnx_path = os.path.join(MODELS_DIR, f"{voice_name}.onnx")
    json_path = os.path.join(MODELS_DIR, f"{voice_name}.onnx.json")

    if not os.path.exists(onnx_path):
        print(f"[*] Piper modell letöltése: {voice_name}.onnx...")
        urllib.request.urlretrieve(VOICE_URLS[voice_name]["onnx"], onnx_path)
    
    if not os.path.exists(json_path):
        print(f"[*] Piper konfiguráció letöltése: {voice_name}.onnx.json...")
        urllib.request.urlretrieve(VOICE_URLS[voice_name]["json"], json_path)

    return onnx_path

def synthesize_speech(text, voice_name="hu_HU-imre-medium", speed=1.0):
    onnx_path = ensure_model(voice_name)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_wav:
        wav_filename = out_wav.name

    try:
        length_scale = str(1.0 / max(0.5, min(2.0, float(speed))))
        cmd = [
            "piper",
            "--model", onnx_path,
            "--output_file", wav_filename,
            "--length_scale", length_scale
        ]
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate(input=text.encode("utf-8"))

        if os.path.exists(wav_filename) and os.path.getsize(wav_filename) > 0:
            with open(wav_filename, "rb") as f:
                return f.read()
    except Exception as e:
        print(f"[!] Hiba a szintézisnél: {e}")
    finally:
        if os.path.exists(wav_filename):
            try:
                os.remove(wav_filename)
            except:
                pass
    return None

class PiperHTTPHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ["/api/tts", "/synthesize"]:
            params = parse_qs(parsed.query)
            text = params.get("text", [""])[0]
            voice = params.get("voice", ["hu_HU-imre-medium"])[0]
            speed = float(params.get("speed", [1.0])[0])

            if not text:
                self.send_response(400)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(b'{"error": "Hianyzo text parameter"}')
                return

            audio_data = synthesize_speech(text, voice, speed)
            if audio_data:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(audio_data)))
                self.end_headers()
                self.wfile.write(audio_data)
            else:
                self.send_response(500)
                self._send_cors_headers()
                self.end_headers()
        else:
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "Homebook Piper TTS", "voices": ["hu_HU-imre-medium", "hu_HU-anna-medium", "hu_HU-berta-medium"]}')

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8")

        text = ""
        voice = "hu_HU-imre-medium"
        speed = 1.0

        try:
            data = json.loads(post_body)
            text = data.get("input") or data.get("text") or ""
            voice = data.get("voice") or data.get("model") or "hu_HU-imre-medium"
            speed = float(data.get("speed", 1.0))
        except:
            pass

        if not text:
            self.send_response(400)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Hianyzo szoveg"}')
            return

        audio_data = synthesize_speech(text, voice, speed)
        if audio_data:
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio_data)))
            self.end_headers()
            self.wfile.write(audio_data)
        else:
            self.send_response(500)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Szintezis hiba"}')

def run_server():
    print("=" * 60)
    print("🤖 HOMEBOOK PRO - PIPER AI MAGYAR NEURÁLIS TTS SZERVER")
    print(f"📡 Cím: http://localhost:{PORT}")
    print("🎙️ Elérhető modellek: hu_HU-imre-medium (Férfi), hu_HU-anna-medium (Női)")
    print("=" * 60)
    server = HTTPServer(("0.0.0.0", PORT), PiperHTTPHandler)
    server.serve_forever()

if __name__ == "__main__":
    run_server()
