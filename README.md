# 📚 Homebook Pro – Magyar E-Könyv Felolvasó

> Böngészőalapú e-könyv olvasó és természetes hangú Magyar felolvasó alkalmazás, Microsoft Edge Neural TTS hangokkal (Tamás & Noémi).

**🌐 Élő alkalmazás:** [krisatrader.github.io/Homebook](https://krisatrader.github.io/Homebook/)

---

## 🏗️ Architektúra

```
📱 iPhone / Mac / Böngésző
        │
        ▼
🌐 GitHub Pages (statikus hosting, CDN, ingyenes)
   └─ index.html  ← teljes PWA alkalmazás
   └─ sw.js       ← Service Worker (offline cache)
        │
        │  /api/tts?text=...&voice=hu-HU-TamasNeural
        ▼
☁️ Google Cloud Run – europe-west1 (ingyenes, ~2s cold start)
   └─ piper_server.py  ← Python TTS szerver (ThreadedHTTPServer)
        │
        │  WebSocket streaming
        ▼
⚡ Microsoft Azure Neural TTS
   └─ hu-HU-TamasNeural  (természetes férfi hang)
   └─ hu-HU-NoemiNeural  (természetes női hang)
        │
        ▼
🎧 MP3 blob → A/B Dupla Lejátszó puffer → azonnali lejátszás
```

### Miért ez a felépítés?
- **GitHub Pages:** villámgyors CDN, ingyenes HTTPS – a felhasználó csak a statikus oldalt tölti le
- **Google Cloud Run:** az Edge-TTS-hez Python szerver kell (WebSocket proxy). Cloud Run ~2-3s cold starttal ébred (Render.com free tier: ~30s). Ingyenes kvóta: 2M kérés/hó (~255 teljes könyv)
- **Edge-TTS:** Microsoft neural hangok, teljesen ingyenes és korlátlan, kiváló Magyar hangminőség

---

## ⚡ A/B Dupla Lejátszó Puffer (Double-Buffer architektúra)

A folyamatos, szünetmentes lejátszás kulcsa a **Ping-Pong dupla puffer**:

```
Mondat N lejátszik (playerA)
    └── Közben: playerB már betölti Mondat N+1 hangját a háttérben

Mondat N vége:
    └── Azonnali átkapcsolás: playerB → aktív (0ms szünet)
    └── playerA elkezdi betölteni Mondat N+2-t a háttérben

→ Eredmény: mondatok között 0ms szünet ⚡
```

**Globális változók:**
- `playerA`, `playerB` – két `<audio>` elem, felváltva aktív/standby
- `activePlayer`, `standbyPlayer` – mindenkori aktív és készenléti lejátszó
- `standbySentenceIdx`, `standbyBlobUrl` – melyik mondat van előkészítve

**Lookahead buffer:** a következő N mondat (beállítható csúszka) szintézis közben letöltődik az IndexedDB cache-be. Ismételt hallgatásnál 0ms a válaszidő.

---

## 🐛 Megoldott főbb problémák

### 1. ⭐ Mondaton belüli szünetek (a legfontosabb hiba!)

**Probléma:** 65 karakteres szövegdarabolás – Piper TTS-ből örökölt beállítás, ami minden mondatot ~3-4 részre vágott. Minden rész külön TTS kérés → szünet minden darabnál.

```
RÉGI (65 char limit):
"...mindenki elnéz"           → TTS kérés #1
"sokkal súlyosabb dolgokat is" → TTS kérés #2  ← 2-3 MÁSODPERCES SZÜNET!

ÚJ (500 char limit):
"...mindenki elnéz sokkal súlyosabb dolgokat is."  → TTS kérés #1 ✅
```

**Javítás:** `prepareTTSData()` és `splitLongTextIntoChunks()` – limit 65 → **500 karakter**.
Edge-TTS gond nélkül kezel 500+ karaktert; ez lefedi a könyvmondatok 99.9%-át.

---

### 2. A dupla puffer soha nem működött (stopAudioPlayback bug)

**Probléma:** `speakSentence()` minden hívásakor meghívta a `stopAudioPlayback()`-et, ami **mindkét lejátszót** leállította – beleértve a gondosan előkészített standby puffert is. Az A/B átadás sosem tudott ténylegesen megtörténni.

**Javítás:** Bevezettük a `softStopActivePlayer()` függvényt:

```javascript
// RÉGI – mondatváltásnál mindent törölt:
stopAudioPlayback();  // ← törölte a standby puffert is!

// ÚJ – csak az aktív lejátszót állítja le, standby érintetlen marad:
softStopActivePlayer();  // ← standby megmarad → 0ms átadás lehetséges ⚡
```

`stopAudioPlayback()` csak tényleges megállításkor/hangváltáskor hívódik.

---

### 3. Egyszálú szerver blokkolta a standby prefetch-et

**Probléma:** A Python szerver egyszálú `HTTPServer`-t használt. Miközben az aktív mondat szintézise zajlott (~300ms), a standby előtöltési kérés **sorban várt** → mire az aktív lejátszódott, a standby még nem volt kész → szünet.

```
RÉGI (egyszálú):
  Aktív szintézis:   [====300ms====] → lejátszik
  Standby prefetch:  ⏳ VÁR... → [====300ms====] → kész → de már késő!

ÚJ (ThreadedHTTPServer):
  Aktív szintézis:   [====300ms====] → lejátszik
  Standby prefetch:  [====300ms====] → kész! → 0ms átadás ⚡
```

**Javítás:**
```python
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True  # minden kérés saját szálban fut
```

---

### 4. Render → Google Cloud Run migráció

**Probléma:** Render.com ingyenes tier **~30 másodperces cold start** – 15 perc inaktivitás után az első mondatnál 30mp-et kellett várni.

**Javítás:** Google Cloud Run (europe-west1):
- Cold start: **~2-3 másodperc**
- Ingyenes kvóta: **2M kérés/hó** (~255 teljes könyv)
- Európai szerver → alacsony latencia Magyar felhasználóknak

---

### 5. Frontend → GitHub Pages szétválasztás

**Korábban:** Render szervelte az egész alkalmazást (HTML + TTS API egy helyen).

**Javítás:** Szétválasztás – jobb teljesítmény, kisebb terhelés a szerveren:
- **GitHub Pages** → statikus HTML/CSS/JS (CDN, azonnali betöltés)
- **Cloud Run** → csak a `/api/tts` végpont

```javascript
function getEffectiveServerUrl() {
  // Lokális fejlesztés esetén saját szerver
  if (hostname === 'localhost') return window.location.origin;
  // GitHub Pages-ről → Cloud Run API
  return 'https://homebook-23050689535.europe-west1.run.app';
}
```

---

## 🎙️ TTS Motor részletei

### Szöveg előkészítés (sanitize_text_for_tts – Python szerver)
- Markdown jelek eltávolítása (`*`, `_`, `#`, `>` stb.)
- Gondolatjelek normalizálása (`–` → ` - `)
- Idézőjel egységesítés
- Whitespace normalizálás

### Mondatdarabolás (JavaScript – prepareTTSData)
```javascript
// Mondatok szétválasztása mondatvégjeleken (.!?)
const rawSentences = p.match(/[^.!?]+[.!?]+/g) || [p];

// Ha a mondat >500 karakter → vesszőknél/pontosvesszőknél töri
splitLongTextIntoChunks(trimmed, 500);
```

### Sebesség- és hangbeállítás
- `ttsRate` (0.5–2.5x) → Edge-TTS `rate` paraméter (pl. `+25%`)
- Hangok: `hu-HU-TamasNeural` (férfi), `hu-HU-NoemiNeural` (női)

---

## 📦 Fájlszerkezet

```
Homebook/
├── index.html          ← Teljes PWA alkalmazás (önálló egyetlen fájl)
├── piper_server.py     ← Python Edge-TTS API szerver
├── requirements.txt    ← edge-tts>=6.1.19
├── Dockerfile          ← Google Cloud Run deploy konfigurálása
├── sw.js               ← Service Worker (offline cache, Network-First)
├── manifest.json       ← PWA manifest (ikon, téma)
├── icon.svg            ← Alkalmazás ikon
└── .nojekyll           ← GitHub Pages Jekyll feldolgozás tiltása
```

---

## 🚀 Deploy

### GitHub Pages (frontend – automatikus)
Minden `git push origin main` után automatikusan frissül ~1-2 perc múlva.

### Google Cloud Run (TTS backend)
```bash
# Google Cloud Shell-ben (console.cloud.google.com → >_ ikon):
git clone https://github.com/krisatrader/Homebook.git
cd Homebook
gcloud config set project homebook-506323
gcloud run deploy homebook \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --port 5000 \
  --memory 256Mi
```

### Lokális fejlesztés
```bash
pip install edge-tts
python piper_server.py
# Megnyitás: http://localhost:5000
```

---

## 🔧 Főbb konfigurációs értékek

| Beállítás | Érték | Hely |
|---|---|---|
| TTS chunk max méret | **500 karakter** | `prepareTTSData()` |
| Lookahead buffer méret | 1–10 mondat (UI csúszka) | Beállítások panel |
| Szerver fetch timeout | 8 másodperc | `playEdgeNeuralTTS()` |
| Standby prefetch | következő 1 mondat | `prepareStandbyAudio()` |
| IndexedDB audio cache | korlátlan (helyi tárhely) | `dbGetAudioCache()` |
| Cloud Run memória | 256MB | deploy parancs |
| Service Worker cache | Network-First stratégia | `sw.js` |

---

## 📄 Licenc
Személyes használatra készült projekt.
