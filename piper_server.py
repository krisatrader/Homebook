#!/usr/bin/env python3
"""
Homebook Pro - Piper AI Magyar Neurális TTS & Web Alkalmazás Szerver
===================================================================
Egyetlen paranccsal elindítható, villámgyors helyi és felhős alkalmazás és TTS mikroszolgáltatás.
Kiszolgálja:
1. A Homebook Pro teljes Web App felületét (index.html, sw.js) a gyökér címen (/)
2. A Piper AI magyar neurális beszédmotor REST & OpenAI kompatibilis API-ját (/api/tts, /v1/audio/speech)

Támogatott magyar hangmodellek:
- hu_HU-imre-medium (Imre - Férfi)
- hu_HU-anna-medium (Anna - Női)
- hu_HU-berta-medium (Berta - Női)

Port: 5000 (vagy PORT környezeti változó)
"""

import os
import sys
import json
import urllib.request
import subprocess
import tempfile
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", 5000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "piper_models")

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

class HomebookServerHandler(BaseHTTPRequestHandler):
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
        path = parsed.path

        # 1. Piper AI TTS Szintézis Végpont
        if path in ["/api/tts", "/synthesize"]:
            params = parse_qs(parsed.query)
            text = params.get("text", [""])[0]
            voice = params.get("voice", ["hu_HU-imre-medium"])[0]
            speed = float(params.get("speed", [1.0])[0])

            if not text:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
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
            return

        # 2. Piper API Állapot / Egészségügyi Végpont
        if path in ["/api/status", "/health"]:
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "Homebook Piper TTS", "voices": ["hu_HU-imre-medium", "hu_HU-anna-medium", "hu_HU-berta-medium"]}')
            return

        # 3. Homebook Pro Web Alkalmazás Kiszolgálása (index.html, sw.js, stb.)
        if path == "/" or path == "/index.html":
            file_path = os.path.join(BASE_DIR, "index.html")
        else:
            rel_path = path.lstrip("/")
            file_path = os.path.join(BASE_DIR, rel_path)

        if os.path.exists(file_path) and os.path.isfile(file_path):
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                if file_path.endswith(".js"):
                    content_type = "application/javascript"
                elif file_path.endswith(".html"):
                    content_type = "text/html; charset=utf-8"
                else:
                    content_type = "application/octet-stream"

            with open(file_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            # Ha nincs ilyen fájl, visszairányítjuk az index.html-re (SPA viselkedés)
            index_path = os.path.join(BASE_DIR, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()

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
    print("🤖 HOMEBOOK PRO - WEB APP & PIPER NEURÁLIS TTS SZERVER")
    print(f"📡 Cím: http://localhost:{PORT}")
    print("📖 Web UI: http://localhost:{PORT}/")
    print("🎙️ Piper Modellek: hu_HU-imre-medium, hu_HU-anna-medium, hu_HU-berta-medium")
    print("=" * 60)
    
    # Előtöltjük az Imre magyar hangmodellt induláskor
    ensure_model("hu_HU-imre-medium")
    
    server = HTTPServer(("0.0.0.0", PORT), HomebookServerHandler)
    server.serve_forever()

if __name__ == "__main__":
    run_server()
