#!/usr/bin/env python3
"""
Homebook Pro - Microsoft Edge Neural TTS & Web Alkalmazás Szerver
=================================================================
Villámgyors, in-memory streaming neurális beszédszintetizátor és PWA szerver.
- Microsoft Edge Neural TTS (Tamás & Noémi) -> ~150ms válaszidő, 24kHz stúdióminőség
- Intelligens szövegtisztítás (sanitize_text_for_tts)
- Teljes Homebook Pro Web UI kiszolgálása a gyökér címen (/)

Port: 5000 (vagy PORT környezeti változó)
"""

import os
import sys
import re
import json
import asyncio
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

PORT = int(os.environ.get("PORT", 5000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
    if voice in ["hu-HU-Tamas", "tamas", "default"]:
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
            await asyncio.sleep(0.15 * (attempt + 1))
    return None, None

def perform_tts_synthesis(text: str, voice: str = "hu-HU-TamasNeural", speed: float = 1.0):
    """Központi Edge-TTS szintézis választó."""
    if HAS_EDGE_TTS:
        try:
            return asyncio.run(synthesize_edge_tts(text, voice, speed))
        except Exception as e:
            print(f"[!] Asyncio Edge TTS hiba: {e}")
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
                "service": "Homebook Edge Neural TTS",
                "has_edge_tts": HAS_EDGE_TTS,
                "voices": ["hu-HU-TamasNeural", "hu-HU-NoemiNeural", "en-US-GuyNeural", "en-US-JennyNeural", "de-DE-KatjaNeural"]
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

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Párhuzamos kéréskezelés – minden TTS kérés saját szálban fut (0ms standby blokkolás)."""
    daemon_threads = True

def run_server():
    print("=" * 60)
    print("🌟 HOMEBOOK PRO - EDGE NEURAL TTS & WEB APP SZERVER")
    print(f"📡 Cím: http://localhost:{PORT}")
    print("📖 Web UI: http://localhost:{PORT}/")
    print("🎙️ Motor: Microsoft Edge-TTS (Tamás & Noémi)")
    print("⚡ Mód: Párhuzamos (ThreadedHTTPServer)")
    print("=" * 60)
    server = ThreadedHTTPServer(("0.0.0.0", PORT), HomebookServerHandler)
    server.serve_forever()

if __name__ == "__main__":
    run_server()
