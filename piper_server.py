#!/usr/bin/env python3
"""
Homebook Pro - Neurális TTS & Web Alkalmazás Szerver (Edge-TTS & Piper AI)
==========================================================================
Villámgyors felhős és helyi beszédszintetizátor mikroszolgáltatás.
Támogatott motorok:
1. Microsoft Edge Neural TTS (Tamás & Noémi) -> 150ms válaszidő, 24kHz stúdióminőség
2. Piper AI Helyi Neurális Modellek (Imre, Anna, Berta)

Port: 5000 (vagy PORT környezeti változó)
"""

import os
import sys
import re
import json
import asyncio
import urllib.request
import subprocess
import tempfile
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# edge-tts importálása ha elérhető
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

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

TTS_SEMAPHORE = asyncio.Semaphore(6) if HAS_EDGE_TTS else None

def sanitize_text_for_tts(text: str) -> str:
    """Megtisztítja a szöveget az Edge TTS számára a természetes és zavartalan kiejtéshez."""
    if not text:
        return ""
    # Felesleges markdown vagy formázási jelek eltávolítása
    t = re.sub(r'[*_~`#>]', ' ', text)
    # Többszörös pontozások egyszerűsítése
    t = re.sub(r'\.{4,}', '...', t)
    # Gondolatjelek normalizálása
    t = re.sub(r'[\u2013\u2014\u2015]', ' - ', t)
    # Idézőjelek tisztítása
    t = re.sub(r'[\u201E\u201D\u201C\u00AB\u00BB"]', '"', t)
    # Szóközök normalizálása
    t = re.sub(r'[ \t]+', ' ', t)
    return t.strip()

def format_rate(rate_multiplier: float) -> str:
    """Átváltja a szorzót (pl. 1.25) Edge TTS formátumra (+25%)."""
    percent = int(round((rate_multiplier - 1.0) * 100))
    return f"+{percent}%" if percent >= 0 else f"{percent}%"

async def synthesize_edge_tts(text: str, voice: str = "hu-HU-TamasNeural", speed: float = 1.0, pitch: str = "+0Hz"):
    """Microsoft Edge Neural TTS szintézis in-memory MP3 folyamként."""
    clean_t = sanitize_text_for_tts(text)
    if not clean_t:
        clean_t = "..."

    # Hang kód normalizálás
    if voice.startswith("edge-"):
        voice = voice.replace("edge-", "")
    if voice in ["hu-HU-Tamas", "tamas"]:
        voice = "hu-HU-TamasNeural"
    elif voice in ["hu-HU-Noemi", "noemi"]:
        voice = "hu-HU-NoemiNeural"

    rate_str = format_rate(speed)

    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(clean_t, voice=voice, rate=rate_str, pitch=pitch)
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            audio_bytes = b"".join(audio_chunks)
            if len(audio_bytes) > 100:
                return audio_bytes, "audio/mpeg"
        except Exception as e:
            print(f"[!] Edge TTS hiba (próbálkozás {attempt+1}/3): {e}")
            await asyncio.sleep(0.2 * (attempt + 1))
    return None, None

def ensure_piper_model(voice_name="hu_HU-imre-medium"):
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

def synthesize_piper(text, voice_name="hu_HU-imre-medium", speed=1.0):
    """Piper AI szintézis WAV formátumban."""
    onnx_path = ensure_piper_model(voice_name)
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
                return f.read(), "audio/wav"
    except Exception as e:
        print(f"[!] Piper szintézis hiba: {e}")
    finally:
        if os.path.exists(wav_filename):
            try:
                os.remove(wav_filename)
            except:
                pass
    return None, None

def perform_tts_synthesis(text: str, voice: str = "hu-HU-TamasNeural", speed: float = 1.0):
    """Központi TTS szintézis választó."""
    voice_lower = voice.lower()
    
    # 1. Ha Microsoft Edge Neural hangot kérünk (vagy ez az alapértelmezett)
    if "neural" in voice_lower or voice.startswith("edge-") or voice.startswith("hu-HU") or voice.startswith("en-US") or voice.startswith("de-DE"):
        if HAS_EDGE_TTS:
            try:
                return asyncio.run(synthesize_edge_tts(text, voice, speed))
            except Exception as e:
                print(f"[!] Asyncio Edge TTS hiba: {e}")
    
    # 2. Ha Piper hangot kérünk
    if "piper" in voice_lower or "imre" in voice_lower or "anna" in voice_lower or "berta" in voice_lower:
        piper_voice = voice.replace("piper-", "")
        return synthesize_piper(text, piper_voice, speed)
    
    # Fallback: Edge TTS ha elérhető
    if HAS_EDGE_TTS:
        return asyncio.run(synthesize_edge_tts(text, "hu-HU-TamasNeural", speed))
    
    return None, None

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

        # 1. TTS Szintézis Végpont (/api/tts vagy /synthesize)
        if path in ["/api/tts", "/synthesize"]:
            params = parse_qs(parsed.query)
            text = params.get("text", [""])[0]
            voice = params.get("voice", ["hu-HU-TamasNeural"])[0]
            speed = float(params.get("speed", [1.0])[0])

            if not text:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Hianyzo text parameter"}')
                return

            audio_data, content_type = perform_tts_synthesis(text, voice, speed)
            if audio_data:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", content_type or "audio/mpeg")
                self.send_header("Content-Length", str(len(audio_data)))
                self.end_headers()
                self.wfile.write(audio_data)
            else:
                self.send_response(500)
                self._send_cors_headers()
                self.end_headers()
            return

        # 2. Állapot / Healthcheck Végpont
        if path in ["/api/status", "/health"]:
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_data = {
                "status": "ok",
                "service": "Homebook Universal Neural TTS",
                "has_edge_tts": HAS_EDGE_TTS,
                "voices": ["hu-HU-TamasNeural", "hu-HU-NoemiNeural", "hu_HU-imre-medium", "hu_HU-anna-medium"]
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
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
        voice = "hu-HU-TamasNeural"
        speed = 1.0

        try:
            data = json.loads(post_body)
            text = data.get("input") or data.get("text") or ""
            voice = data.get("voice") or data.get("model") or "hu-HU-TamasNeural"
            speed = float(data.get("speed", 1.0))
        except Exception:
            pass

        if not text:
            self.send_response(400)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "Hianyzo szoveg"}')
            return

        audio_data, content_type = perform_tts_synthesis(text, voice, speed)
        if audio_data:
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type or "audio/mpeg")
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
    print("🌟 HOMEBOOK PRO - UNIVERSAL NEURAL TTS & WEB APP SZERVER")
    print(f"📡 Cím: http://localhost:{PORT}")
    print("📖 Web UI: http://localhost:{PORT}/")
    print("🎙️ Motorok: Microsoft Edge-TTS (Tamás & Noémi) + Piper AI")
    print("=" * 60)
    server = HTTPServer(("0.0.0.0", PORT), HomebookServerHandler)
    server.serve_forever()

if __name__ == "__main__":
    run_server()
