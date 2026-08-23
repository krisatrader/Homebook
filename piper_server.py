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
import time
import threading
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

PORT = int(os.environ.get("PORT", 5000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYNC_STORE_PATH = os.path.join(BASE_DIR, "sync_store.json")
SYNC_LOCK = threading.Lock()
SYNC_DATA = {}

def load_sync_store():
    global SYNC_DATA
    if os.path.exists(SYNC_STORE_PATH):
        try:
            with open(SYNC_STORE_PATH, "r", encoding="utf-8") as f:
                SYNC_DATA = json.load(f)
        except Exception as e:
            print(f"[!] Hiba a sync_store betöltésekor: {e}")
            SYNC_DATA = {}

def save_sync_store():
    try:
        with open(SYNC_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(SYNC_DATA, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Hiba a sync_store mentésekor: {e}")

load_sync_store()

def normalize_hungarian_encoding(text: str) -> str:
    """Javítja a sérült vagy nem szabványos TTF betűkészletből (Q/q, õ/û, UTF-8 mojibake) származó karaktereket."""
    if not text:
        return ""
    t = text

    # 1. Mojibake UTF-8 kettős kódolás javítása
    mojibake = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ã¶': 'ö', 'Å‘': 'ő', 'Ãº': 'ú', 'Ã¼': 'ü', 'Å±': 'ű',
        'Ã\x81': 'Á', 'Ã\x89': 'É', 'Ã\x8d': 'Í', 'Ã\x93': 'Ó', 'Ã\x96': 'Ö', 'Å\x90': 'Ő', 'Ã\x9a': 'Ú', 'Ã\x9c': 'Ü', 'Å\x91': 'Ű'
    }
    for k, v in mojibake.items():
        t = t.replace(k, v)

    # 2. Hibás hullámos / kalapos ékezetek (ISO-8859-1 -> Latin-2)
    t = t.replace('õ', 'ő').replace('Õ', 'Ő').replace('û', 'ű').replace('Û', 'Ű')

    # 3. Nem szabványos TTF betűkészlet Q/q ékezet-helyettesítés
    def fix_word(match):
        w = match.group(0)
        low = w.lower()
        if low.startswith('qu') or low in {'sql', 'faq', 'iraq', 'nasdaq', 'status quo'}:
            return w
        res = []
        for i, ch in enumerate(w):
            if ch == 'Q':
                if i == 0 and len(w) > 1 and w[1].islower():
                    res.append('Ő')
                elif i == 0 and len(w) == 1:
                    res.append('Ő')
                elif w.isupper():
                    res.append('Ő')
                else:
                    res.append('ő')
            elif ch == 'q':
                res.append('ű')
            else:
                res.append(ch)
        return "".join(res)

    t = re.sub(r'[a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+', fix_word, t)
    return t

def sanitize_text_for_tts(text: str) -> str:
    """Megtisztítja a szöveget az Edge TTS számára a természetes és zavartalan kiejtéshez."""
    if not text:
        return ""
    # Magyar ékezet- és kódolás javítás
    t = normalize_hungarian_encoding(text)
    # XML és SSML tiltott karakterek tisztítása
    t = t.replace('&', ' és ').replace('<', ' ').replace('>', ' ')
    # Felesleges markdown vagy formázási jelek eltávolítása
    t = re.sub(r'[*_~`#]', ' ', t)
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
                "sync_enabled": True,
                "voices": ["hu-HU-TamasNeural", "hu-HU-NoemiNeural", "en-US-GuyNeural", "en-US-JennyNeural", "de-DE-KatjaNeural"]
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        # 3. Felhő Szinkronizáció Lekérdezés (/api/sync/progress vagy /api/sync)
        if path in ["/api/sync/progress", "/api/sync"]:
            params = parse_qs(parsed.query)
            sync_id = params.get("syncId", [""])[0].strip()
            title = params.get("title", [""])[0].strip().lower()

            if not sync_id:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Hianyzo syncId parameter"}')
                return

            with SYNC_LOCK:
                user_books = SYNC_DATA.get(sync_id, {})
                if title:
                    norm_query = re.sub(r'[^a-zA-Z0-9áéíóöőúüűÁÉÍÓÖŐÚÜŰ]+', '', title)
                    matched = user_books.get(norm_query)
                    if not matched:
                        for k, v in user_books.items():
                            if norm_query in k or k in norm_query:
                                matched = v
                                break
                    resp_data = {"status": "ok", "syncId": sync_id, "book": matched}
                else:
                    resp_data = {"status": "ok", "syncId": sync_id, "books": user_books}

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(resp_data, ensure_ascii=False).encode("utf-8"))
            return

        # 4. Homebook Pro Web Alkalmazás Kiszolgálása (index.html, sw.js, stb.)
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
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8")

        # 1. Felhő Szinkronizáció Mentés (/api/sync/progress vagy /api/sync)
        if path in ["/api/sync/progress", "/api/sync"]:
            try:
                data = json.loads(post_body)
                sync_id = (data.get("syncId") or "").strip()
                book_title = (data.get("bookTitle") or data.get("title") or "").strip()
                last_p = int(data.get("lastSeenPIdx", 0))
                last_s = int(data.get("lastSeenSentenceIdx", 0))
                pct = int(data.get("percent", 0))
                ts = int(data.get("timestamp", 0)) or int(time.time() * 1000)
            except Exception:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Ervenytelen JSON"}')
                return

            if not sync_id or not book_title:
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "syncId es bookTitle szukseges"}')
                return

            norm_title = re.sub(r'[^a-zA-Z0-9áéíóöőúüűÁÉÍÓÖŐÚÜŰ]+', '', book_title.lower())
            with SYNC_LOCK:
                if sync_id not in SYNC_DATA:
                    SYNC_DATA[sync_id] = {}
                
                existing = SYNC_DATA[sync_id].get(norm_title)
                # Mindig csak az időpontban frissebb rekordot fogadjuk el
                if not existing or ts >= existing.get("timestamp", 0):
                    SYNC_DATA[sync_id][norm_title] = {
                        "bookTitle": book_title,
                        "lastSeenPIdx": last_p,
                        "lastSeenSentenceIdx": last_s,
                        "percent": pct,
                        "timestamp": ts,
                        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    save_sync_store()

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "synced": true}')
            return

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
