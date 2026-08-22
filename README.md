# Home E-Book Pro (Homebook)

Egy önálló, böngészőből futtatható e-könyv olvasó és felolvasó alkalmazás (.epub, .kepub, .pdf, .txt támogatással).

## Futtatás

Nyisd meg a böngésződben a [index.html](file:///Users/sebestyenkristof/.gemini/antigravity/scratch/homebook/index.html) fájlt, vagy indíts egy egyszerű helyi webszervert a mappában:

```bash
cd /Users/sebestyenkristof/.gemini/antigravity/scratch/homebook
python3 -m http.server 8080
```

Ezután nyisd meg: `http://localhost:8080`

## Főbb funkciók:
- 📚 Könyvtár kezelés (.epub, .pdf, .txt formátumok)
- 🎙️ Magyar felolvasó (iPhone natív beszédhangok + Google Translate TTS)
- 🇭🇺 Automatikus szakasz és teljes könyv fordítás
- 🌙 Elalvási időzítő (5, 15, 30, 45 perc, vagy fejezet végén)
- 🔖 Könyvjelzők, jegyzetek és szövegkiemelés
- ⚙️ Témák (Sötét, Szépia, Világos), egyéni betűméret és sorköz
- 💾 Offline IndexedDB mentés és biztonsági mentés export/import funkció
