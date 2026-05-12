"""
Kosmiczny Sen — tam otomatik video üretici
Kullanım:
  python generate.py "Powierzchnia Księżyca"
  python generate.py "Wnętrze Czarnej Dziury" --duration 840
"""
import argparse, asyncio, subprocess, json, urllib.request, urllib.parse, base64
import time, shutil, re
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont
import anthropic

# ── Config ───────────────────────────────────────────────────────────────────

import os
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
PIXABAY_KEY     = os.environ["PIXABAY_KEY"]
GOOGLE_TTS_KEY  = os.environ["GOOGLE_TTS_KEY"]
NASA_KEY        = os.environ.get("NASA_KEY", "DEMO_KEY")
TTS_VOICE       = "pl-PL-Chirp3-HD-Iapetus"
SR, FPS         = 44100, 25
W, H            = 1920, 1080

# ── 1. Script generation ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Jesteś autorem medytacyjnych opowiadań do zasypiania po polsku dla kanału "Kosmiczny Sen".

STRUKTURA KAŻDEGO ODCINKA — naprzemienne bloki:

[BLOK WIEDZY] — 2-4 zdania prawdziwych, fascynujących faktów o temacie.
Pisz spokojnie, jak narrator dokumentu przyrodniczego. Fakty mają zachwycać, nie uczyć.
Przykład: "Ciemna strona Księżyca nigdy nie zwraca się ku Ziemi. Przez miliardy lat pozostawała
zupełnie nieznana — dopiero radziecka sonda jako pierwsza sfotografowała ją w 1959 roku.
Pod powierzchnią kryją się kratery głębsze niż najwyższe ziemskie góry."

[BLOK WYOBRAŹNI] — przejście do 2. osoby, słuchacz wchodzi w scenę.
Zaproś go miękko: "Wyobraź sobie, że...", "A teraz jesteś tam...", "Zamknij oczy — jesteś właśnie tutaj..."
Opisz co widzi, czuje, słyszy, dotyka. Niech odkrywa to miejsce krok po kroku.
Przykład: "Wyobraź sobie, że stoisz teraz na tej powierzchni. Pod stopami masz szary,
zmrożony pył — każdy krok zostawia ślad, który pozostanie tu przez miliony lat, bo nie ma wiatru.
Włączasz latarkę. Jej światło pada na ogromny krater przede tobą, głęboki i cichy jak ocean."

ZASADY:
- Bloki wyobraźni są dłuższe niż bloki wiedzy (stosunek ~1:3)
- Wiedza zawsze poprzedza wyobraźnię — najpierw fakt, potem "a teraz ty tam jesteś"
- Spekulacje mile widziane: "Nikt nie wie, czy pod lodem nie kryje się życie... może właśnie to zaraz odkryjesz."
- Pełne, rozbudowane zdania tworzące akapity — żadnych list, nagłówków, markdown
- Tempo spokojne — słuchacz zasypia stopniowo przez całą narrację
- ZAKAZ nagłówków, oznaczeń [BLOK ...] w tekście, numerowania — tylko czysty płynny tekst

PRZYKŁAD DOBREGO PRZEJŚCIA (wiedza → wyobraźnia):
Ciemna strona Księżyca jest bombardowana meteorytami bez przerwy — nie ma atmosfery, która by je spaliła. Każde uderzenie to cichy błysk w absolutnej ciemności, nowy krater w milionach już istniejących. Naukowcy podejrzewają, że głęboko pod powierzchnią mogą istnieć tunele lawowe — ogromne, stabilne, osłonięte od kosmosu.

A teraz jesteś tam. Stoisz na krawędzi jednego z takich kraterów i patrzysz w dół. Jest głęboki — tak głęboki, że twoja latarka nie dosięga dna. Powietrze w skafandrze pachnie metalem i chłodem. Robisz krok do przodu. Potem jeszcze jeden. Cisza jest tak gęsta, że czujesz ją fizycznie — żaden dźwięk nie istnieje tutaj od początku czasu.
"""

def _claude_call(prompt: str, system: str, temperature=0.85, max_tokens=8000) -> str:
    """Claude API çağrısı — rate limit retry ile."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    for attempt in range(6):
        try:
            r = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}]
            )
            return r.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = 40 * (attempt + 1)
            print(f"  Rate limit — {wait}s bekleniyor...")
            time.sleep(wait)
        except Exception as e:
            raise
    raise RuntimeError("Claude API failed after retries")

def generate_script(topic: str, duration_sec: int) -> str:
    """
    45 dk için ~5800 kelime lazım — model limiti ~8000 token (~6000 kelime).
    45 dk altı: tek istek. 45 dk+: 3 parçada üret, birleştir.
    """
    words_needed = int((duration_sec / 60) * 130)
    print(f"Script üretiliyor: '{topic}'  ~{words_needed} kelime ({duration_sec//60} dk)...")

    if words_needed <= 1800:
        # Kısa — tek istek
        prompt = (
            f"Napisz medytacyjne opowiadanie do zasypiania na temat: '{topic}'.\n"
            f"Długość: dokładnie około {words_needed} słów.\n"
            f"Zacznij od krótkiego faktu o '{topic}', potem zaproś słuchacza: 'Wyobraź sobie, że jesteś tam...'\n"
            f"Przeplataj bloki wiedzy (prawdziwe fakty) z blokami wyobraźni (słuchacz jest w scenie, odkrywa to miejsce).\n"
            f"Bloki wyobraźni są ~3x dłuższe niż bloki wiedzy.\n"
            f"Zakończ gdy słuchacz całkowicie zasypia. Tylko czysty tekst, bez nagłówków."
        )
        script = _claude_call(prompt, SYSTEM_PROMPT, max_tokens=8000)
        print(f"  {len(script.split())} kelime üretildi")
        return script

    # Uzun (45 dk) — 3 parçada üret
    parts = []
    part_words = words_needed // 3
    extra       = words_needed - part_words * 3

    part_prompts = [
        (
            f"Napisz PIERWSZĄ CZĘŚĆ medytacyjnego opowiadania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words} słów.\n"
            f"Zacznij od 2-3 fascynujących faktów o '{topic}' — mów spokojnie jak narrator dokumentu.\n"
            f"Potem zaproś słuchacza: 'Wyobraź sobie, że stoisz teraz tam...' i opisz scenę szczegółowo.\n"
            f"Przeplataj fakty z wyobraźnią — najpierw fakt, potem słuchacz wchodzi w to miejsce.\n"
            f"Zakończ w połowie eksploracji — kontynuacja nastąpi."
        ),
        (
            f"Napisz ŚRODKOWĄ CZĘŚĆ medytacyjnego opowiadania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words + extra} słów.\n"
            f"Kontynuuj płynnie — słuchacz nadal odkrywa to miejsce.\n"
            f"Dodaj nowe fascynujące fakty, a po każdym wciągaj słuchacza głębiej w scenerię.\n"
            f"Możesz spekulować: 'Nikt nie wie, czy tam nie kryje się życie... może właśnie to zaraz zobaczysz.'\n"
            f"Słuchacz powoli staje się senny. Zakończ akapit — kontynuacja nastąpi."
        ),
        (
            f"Napisz KOŃCOWĄ CZĘŚĆ medytacyjnego opowiadania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words} słów.\n"
            f"Słuchacz jest już bardzo senny — narracja spokojniejsza, wolniejsza.\n"
            f"Ostatnie fakty są krótkie, prawie szeptane. Wyobraźnia dominuje.\n"
            f"Obrazy stają się coraz bardziej mgławicowe i senne.\n"
            f"Zakończ gdy słuchacz całkowicie zasypia — ostatnie zdanie bardzo spokojne i ciche."
        ),
    ]

    for i, prompt in enumerate(part_prompts, 1):
        print(f"  Parça {i}/3 üretiliyor...")
        part = _claude_call(prompt, SYSTEM_PROMPT, temperature=0.88, max_tokens=8000)
        parts.append(part)
        if i < 3:
            time.sleep(5)  # rate limit önlemi

    script = "\n\n".join(parts)
    print(f"  Toplam {len(script.split())} kelime ({len(parts)} parça)")
    return script

# ── 2. Pixabay keyword extraction from topic ─────────────────────────────────

TOPIC_KEYWORDS = {
    "księżyc": ["moon surface space", "lunar landscape", "moon night sky"],
    "czarna dziura": ["black hole space", "galaxy vortex cosmos", "deep space nebula"],
    "mars": ["mars planet surface", "red planet space", "mars landscape"],
    "gwiazdy": ["stars galaxy milky way", "night sky stars", "nebula space"],
    "ocean": ["underwater ocean deep", "ocean waves calm", "deep sea"],
    "las": ["forest trees fog", "misty forest night", "nature forest calm"],
    "zorza": ["aurora borealis northern lights", "polar lights night", "aurora sky"],
    "statek": ["spaceship interior", "space station cosmos", "space travel"],
}

def topic_to_queries(topic: str):
    topic_lower = topic.lower()
    for key, queries in TOPIC_KEYWORDS.items():
        if key in topic_lower:
            return queries
    # fallback: use topic words directly
    clean = re.sub(r"[^a-z0-9ąćęłńóśźż ]", "", topic_lower)
    return [f"space {clean}", "cosmos nebula galaxy", "space universe stars"]

# ── 3. Download Pixabay video clips ─────────────────────────────────────────

# Konu dışı klipler için kara liste etiketleri
BLACKLIST_TAGS = {
    "car","race","rally","ski","skiing","factory","chimney","smoke","pollution",
    "trash","rubbish","city","traffic","people","crowd","food","cooking","dog",
    "cat","bird","sport","football","beach party","fireworks","office","business",
    "nature","forest","tree","flower","animal","wildlife","ocean","sea","beach",
    "mountain","river","lake","rain","snow","desert","jungle","farm","harvest"
}

# Uzay teması için beyaz liste — en az biri eşleşmeli
SPACE_TAGS = {
    "space","cosmos","galaxy","nebula","star","stars","universe","planet",
    "moon","lunar","mars","asteroid","comet","meteor","solar","aurora",
    "milky way","astronomy","telescope","orbit","satellite","supernova",
    "cosmic","black hole","spacecraft","rocket","nasa","astronaut","iss",
    "earth from space","deep space","interstellar","void","dark matter"
}

def _tags_ok(tags_str: str) -> bool:
    tags = {t.strip().lower() for t in tags_str.split(",")}
    has_blacklist = len(tags & BLACKLIST_TAGS) > 0
    has_space     = len(tags & SPACE_TAGS) > 0
    return has_space and not has_blacklist

def fetch_clips(topic: str, clips_dir: Path, n=8, extra_queries: list = None):
    print("Video klipleri indiriliyor...")
    queries = extra_queries if extra_queries else topic_to_queries(topic)
    # Her zaman güvenli fallback sorguları ekle
    fallback = ["space nebula stars", "galaxy cosmos universe", "night sky stars milky way"]
    all_queries = queries + [q for q in fallback if q not in queries]

    seen, got = set(), []

    for q in all_queries:
        if len(got) >= n: break
        url = (f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}"
               f"&q={urllib.parse.quote(q)}&per_page=20"
               f"&min_width=1280&order=popular&video_type=film")
        try:
            r = urllib.request.urlopen(url, timeout=12)
            hits = json.loads(r.read())["hits"]
        except Exception as e:
            print(f"  api hatası: {e}"); continue

        for h in hits:
            if len(got) >= n: break
            vid_id = h["id"]
            if vid_id in seen: continue
            seen.add(vid_id)

            # Kara liste filtresi
            if not _tags_ok(h.get("tags", "")):
                continue

            v = h["videos"].get("large") or h["videos"].get("medium")
            if not v or v.get("width", 0) < 1280 or v.get("height", 0) > v.get("width", 1):
                continue

            dest = clips_dir / f"clip_{vid_id}.mp4"
            if dest.exists() and dest.stat().st_size > 200_000:
                got.append(dest)
                print(f"  önbellekte {dest.name}")
                continue
            try:
                req = urllib.request.Request(v["url"], headers={"User-Agent": "KosmicznySen/3.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    dest.write_bytes(resp.read())
                print(f"  ↓ {dest.name}  {dest.stat().st_size//1024//1024}MB  {h['tags'][:40]}")
                got.append(dest)
            except Exception as e:
                print(f"  ✗ {e}")
            time.sleep(0.4)

    print(f"  {len(got)} klip hazır")
    return got[:n]

# ── 4. Audio + ASS subtitles ─────────────────────────────────────────────────

def _text_to_ssml(script: str) -> str:
    """Düz metni SSML'e çevirir — noktalama bazlı duraklamalar ekler."""
    lines = script.strip().split("\n")
    parts = []
    for line in lines:
        line = line.strip()
        if not line:
            parts.append('<break time="400ms"/>')
            continue
        # & işaretini escape et (tek özel karakter)
        line = line.replace("&", "&amp;")
        # Noktalama bazlı duraklamalar
        line = re.sub(r'\.\.\.', '...<break time="400ms"/>', line)
        line = re.sub(r'\.(\s)', r'.<break time="300ms"/>\1', line)
        line = re.sub(r'—', '<break time="200ms"/>—<break time="200ms"/>', line)
        line = re.sub(r',(\s)', r',<break time="150ms"/>\1', line)
        parts.append(line)
    return "<speak>\n" + "\n".join(parts) + "\n</speak>"

async def gen_audio(script: str, out_path: Path):
    print("Generating audio (Google Cloud TTS — Iapetus)...")
    ssml = _text_to_ssml(script)

    # Metni 4500 karakterlik parçalara böl (API limiti)
    sentences_all = []
    chunks = _split_ssml_chunks(script)
    wav_parts = []

    for i, chunk in enumerate(chunks):
        body = json.dumps({
            "input": {"text": chunk},
            "voice": {"languageCode": "pl-PL", "name": TTS_VOICE},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 44100}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://texttospeech.googleapis.com/v1beta1/text:synthesize?key={GOOGLE_TTS_KEY}",
            data=body, headers={"Content-Type": "application/json; charset=utf-8"}
        )
        for attempt in range(4):
            try:
                r = urllib.request.urlopen(req, timeout=60)
                raw = base64.b64decode(json.loads(r.read())["audioContent"])
                part_wav = out_path.parent / f"_tts_part{i}.wav"
                part_wav.write_bytes(raw)
                wav_parts.append(part_wav)
                print(f"  Parça {i+1}/{len(chunks)} OK")
                break
            except Exception as e:
                if attempt < 3:
                    time.sleep(10)
                else:
                    raise RuntimeError(f"TTS hata: {e}")

    # Parçaları birleştir
    _merge_wav_parts(wav_parts, out_path)
    for p in wav_parts:
        p.unlink(missing_ok=True)

    # Altyazı için cümleleri timestamp ile çıkar (ffprobe ile)
    sentences_all = _extract_sentence_timestamps(script, out_path)
    print(f"  {len(sentences_all)} sentence timestamps")
    return sentences_all

def _split_ssml_chunks(text: str, max_bytes: int = 1800) -> list:
    """Metni cümle sınırlarından böler — byte limiti bazlı."""
    sentences = re.split(r'(?<=[.!?…])\s+', text.strip())
    chunks, cur = [], ""
    for s in sentences:
        candidate = (cur + " " + s).strip()
        if len(candidate.encode("utf-8")) > max_bytes and cur:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = candidate
    if cur:
        chunks.append(cur.strip())
    return chunks

def _merge_wav_parts(parts: list, out_path: Path):
    """WAV parçalarını MP3'e birleştirir. Google TTS LINEAR16 = header'lı WAV."""
    if len(parts) == 1:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(parts[0]),
            "-c:a", "libmp3lame", "-q:a", "2", str(out_path)
        ], capture_output=True)
        return
    list_f = out_path.parent / "_wav_list.txt"
    mp3_parts = []
    for i, p in enumerate(parts):
        tmp = out_path.parent / f"_tts_tmp{i}.mp3"
        r = subprocess.run([
            "ffmpeg", "-y", "-i", str(p),
            "-c:a", "libmp3lame", "-q:a", "2", str(tmp)
        ], capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists():
            mp3_parts.append(tmp)
        else:
            print(f"  UYARI: parça {i} dönüştürülemedi: {r.stderr[-200:]}")
    if not mp3_parts:
        raise RuntimeError("Hiçbir TTS parçası MP3'e dönüştürülemedi")
    list_f.write_text("".join(f"file '{p.as_posix()}'\n" for p in mp3_parts))
    r2 = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_f), "-c", "copy", str(out_path)
    ], capture_output=True, text=True)
    if r2.returncode != 0:
        print(f"  UYARI: concat hata — ilk parça kullanılıyor\n{r2.stderr[-300:]}")
        shutil.copy(str(mp3_parts[0]), str(out_path))
    for p in mp3_parts:
        p.unlink(missing_ok=True)
    list_f.unlink(missing_ok=True)

def _extract_sentence_timestamps(script: str, audio_path: Path) -> list:
    """Ses dosyasının toplam süresine göre cümleleri eşit dağıtır."""
    r = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)
    ], capture_output=True, text=True)
    try:
        total = float(r.stdout.strip())
    except ValueError:
        words = len(script.split())
        total = words / 2.3
        print(f"  ffprobe uyarısı: süre tahmin edildi ({total:.0f}s)")
    raw_sentences = re.split(r'(?<=[.!?…])\s+', script.strip())
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    if not sentences:
        return []
    # Kelime sayısına orantılı zamanlama — eşit dağıtım yerine
    word_counts = [max(len(s.split()), 1) for s in sentences]
    total_words = sum(word_counts)
    result = []
    current = 0.0
    for s, wc in zip(sentences, word_counts):
        dur = (wc / total_words) * total
        result.append({"text": s, "start": current, "dur": dur * 0.92})
        current += dur
    return result

def make_ass(sentences: list, out_path: Path):
    def ts(s):
        h=int(s//3600); m=int((s%3600)//60); sec=s%60
        cs=int(round((sec%1)*100)); sec=int(sec)
        return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

    header = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 1

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,52,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,80,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    for s in sentences:
        start = s["start"]
        end   = s["start"] + s["dur"]
        text  = s["text"]
        if len(text) > 55:
            mid = len(text) // 2
            sp  = text.rfind(" ", 0, mid + 20)
            if sp > 0:
                text = text[:sp] + r"\N" + text[sp+1:]
        events.append(f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{text}")

    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    print(f"  ASS subtitles: {len(sentences)} blocks")

# ── 5. Sleep music ───────────────────────────────────────────────────────────

def make_music(duration: float, out_path: Path):
    print("Generating sleep music...")
    n = int(SR * (duration + 8))
    t = np.linspace(0, duration + 8, n, endpoint=False)
    out = np.zeros(n, dtype=np.float64)

    def lfo(rate, lo=0.0, hi=1.0, ph=0.0):
        return lo + (hi-lo) * (0.5 + 0.5*np.sin(2*np.pi*rate*t+ph))

    out += 0.10 * np.sin(2*np.pi*28*t)
    out += 0.08 * np.sin(2*np.pi*42*t)
    for freq,amp,ph in [(110,.12,0),(131,.09,.8),(165,.08,1.6),(196,.06,2.4)]:
        out += amp * lfo(0.038,.15,1.0,ph) * np.sin(2*np.pi*freq*t)
    for freq,amp,ph in [(220,.07,0),(262,.05,1),(330,.04,2),(392,.03,3)]:
        out += amp * lfo(0.025,.05,.9,ph) * np.sin(2*np.pi*freq*t)
    for freq,amp,ph in [(440,.022,0),(528,.015,1.2),(660,.010,2.4)]:
        out += amp * lfo(0.05,0.0,1.0,ph) * np.sin(2*np.pi*freq*t)

    rev = np.zeros_like(out)
    for d_ms,decay in [(80,.32),(150,.22),(230,.15),(340,.10)]:
        d = int(SR*d_ms/1000); rev[d:] += out[:-d]*decay
    out = out*.62 + rev*.38

    for pt in np.arange(8, duration-4, 10.5):
        n0,ln = int(pt*SR), int(SR*2.8)
        if n0+ln > len(out): continue
        env = np.exp(-np.linspace(0,6,ln))
        out[n0:n0+ln] += 0.038*env*np.sin(2*np.pi*330*np.linspace(0,2.8,ln))

    fi = min(int(SR*10), len(out)//4)
    fo = min(int(SR*8),  len(out)//4)
    out[:fi]  *= np.linspace(0,1,fi)**2
    out[-fo:] *= np.linspace(1,0,fo)**2
    out = out / (np.max(np.abs(out))+1e-9) * 0.55

    wavfile.write(str(out_path), SR, np.stack([out,out],axis=1).astype(np.float32))
    print(f"  Music saved  ({duration:.0f}s)")

# ── 6. Thumbnail ─────────────────────────────────────────────────────────────

def make_thumbnail(clips: list, topic: str, out_path: Path, hook: str = ""):
    print("Creating thumbnail...")
    frame = out_path.parent / "_thumb_frame.jpg"
    # try 3rd second of best clip for a good frame
    for clip in clips[:3]:
        subprocess.run(["ffmpeg","-y","-i",str(clip),"-ss","3","-vframes","1",
                        "-vf","scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
                        str(frame)], capture_output=True)
        if frame.exists() and frame.stat().st_size > 10000:
            break

    img = Image.open(frame).convert("RGB") if (frame.exists() and frame.stat().st_size>10000) \
          else Image.new("RGB",(1280,720),(4,8,35))

    # Colour grade: darker, cooler
    arr = np.array(img, dtype=np.float32)
    arr[:,:,0] *= 0.65
    arr[:,:,1] *= 0.80
    arr[:,:,2] = np.clip(arr[:,:,2]*1.10, 0, 255)
    arr = np.clip(arr * 0.72, 0, 255)
    img = Image.fromarray(arr.astype(np.uint8))

    # Strong dark gradient overlay top + bottom
    grad = Image.new("RGBA",(1280,720),(0,0,0,0))
    gd   = ImageDraw.Draw(grad)
    for i in range(280):
        a = int(200 * (1 - i/280)**1.6)
        gd.rectangle([(0,0),(1280,i)], fill=(0,0,10,a))
    for i in range(200):
        a = int(220 * (1 - i/200)**1.4)
        gd.rectangle([(0,720-i),(1280,720)], fill=(0,0,10,a))
    img = Image.alpha_composite(img.convert("RGBA"), grad).convert("RGB")
    draw = ImageDraw.Draw(img)

    def F(sz, bold=False):
        candidates = [
            f"C:/Windows/Fonts/{'arialbd' if bold else 'arial'}.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans{}-Bold.ttf".format("" if bold else ""),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf".format("-Bold" if bold else ""),
            "/usr/share/fonts/truetype/liberation/LiberationSans{}-Bold.ttf".format("" if bold else ""),
            "/usr/share/fonts/truetype/liberation/LiberationSans{}.ttf".format("-Bold" if bold else ""),
        ]
        for p in candidates:
            try: return ImageFont.truetype(p, sz)
            except: pass
        return ImageFont.load_default(size=sz)

    def ct(txt, y, f, col, sh=(0,0,0)):
        w = draw.textlength(txt, font=f)
        x = (1280-w)/2
        # thick shadow
        for dx,dy in [(-2,2),(2,2),(0,3),(0,-1)]:
            draw.text((x+dx, y+dy), txt, font=f, fill=(*sh,200))
        draw.text((x,y), txt, font=f, fill=col)

    # ── HOOK — główny tekst (duży, na górze, przyciąga uwagę) ──
    hook_text = hook if hook else "Zaśnij Wśród Gwiazd"
    # wrap if too long
    if draw.textlength(hook_text, font=F(88,True)) > 1180:
        words = hook_text.split()
        mid   = len(words)//2
        hook_text = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

    # multiline hook
    hook_lines = hook_text.split("\n")
    hook_y = 55
    for line in hook_lines:
        ct(line, hook_y, F(92,True), (255,255,255))
        hook_y += 108

    # ── Dekoratif ayırıcı çizgi ──
    line_y = hook_y + 10
    lw = draw.textlength(hook_lines[0], font=F(92,True))
    lx = (1280 - min(lw, 700)) / 2
    draw.rectangle([(lx, line_y),(1280-lx, line_y+2)], fill=(180,160,255,180))

    # ── KONU — kısa, orta büyüklük ──
    topic_short = topic if len(topic) <= 32 else topic[:30]+"…"
    ct(topic_short, line_y+18, F(44), (200,185,255))

    # ── Alt etiketler ──
    ct("Sen głęboki • Relaksacja • Medytacja", line_y+76, F(30), (140,170,210))

    # ── Alt bar — "nowy odcinek" + kanal adı küçük ──
    draw.rectangle([(0,660),(1280,720)], fill=(0,0,15,230))
    bar_txt = "🌙  Nowy Odcinek Co Dziennie  •  Kosmiczny Sen"
    ct(bar_txt, 672, F(28), (160,200,240))

    img.save(out_path, quality=96)
    frame.unlink(missing_ok=True)
    print(f"  Thumbnail saved")

# ── 7. Prepare + concat clips ────────────────────────────────────────────────

def prepare_clips(raw: list, duration: float, work_dir: Path):
    """
    Her klip kendi doğal süresiyle (max 40s) kullanılır.
    Toplam süreye ulaşana kadar klip listesi döngüye alınır.
    Dönen: [(dest_path, actual_seg_sec), ...]
    """
    MAX_SEG = 40.0
    MIN_SEG = 8.0
    ready = []
    total = 0.0
    clip_count = 0
    use_count = {}  # her kaynak klip kaç kez kullanıldı

    print(f"Preparing clips for {duration:.0f}s total (max {MAX_SEG:.0f}s/clip, loop if needed)...")

    while total < duration - 0.5:
        src = raw[clip_count % len(raw)]
        src_key = str(src)
        times_used = use_count.get(src_key, 0)
        use_count[src_key] = times_used + 1

        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",str(src)],
            capture_output=True, text=True)
        try: src_dur = float(r.stdout.strip())
        except: src_dur = MAX_SEG

        remaining = duration - total
        seg = min(src_dur, MAX_SEG, remaining)
        if seg < MIN_SEG:
            seg = min(remaining, src_dur)

        # Aynı klip tekrar kullanılıyorsa farklı başlangıç noktası
        if times_used == 0:
            start = max(0, (src_dur - seg) / 2)
        else:
            offset_step = src_dur / (times_used + 2)
            start = min(offset_step * times_used, max(0, src_dur - seg))

        dest = work_dir / f"_r{clip_count:02d}.mp4"
        subprocess.run([
            "ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(seg),
            "-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
            "-c:v","libx264","-preset","fast","-crf","18","-an",str(dest)
        ], capture_output=True)

        if dest.exists():
            ready.append((dest, seg))
            total += seg
            print(f"  clip {clip_count+1}: {src.name} {seg:.1f}s  (total {total:.0f}/{duration:.0f}s)")

        clip_count += 1
        if clip_count > 300:
            break

    return ready

def concat_xfade(clips_with_segs: list, duration: float, work_dir: Path):
    """clips_with_segs: [(path, seg_sec), ...]"""
    clips = [c for c, _ in clips_with_segs]
    segs  = [s for _, s in clips_with_segs]
    if len(clips) == 1: return clips[0]
    print(f"Applying crossfades ({len(clips)} clips)...")
    inputs = sum([["-i",str(c)] for c in clips],[])
    fade   = 0.8
    parts, cur = [], "[0:v]"
    offset_total = 0.0
    for i in range(1, len(clips)):
        offset_total += segs[i-1] - fade
        nxt = f"[v{i}]" if i < len(clips)-1 else "[vout]"
        parts.append(f"{cur}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset_total:.3f}{nxt}")
        cur = f"[v{i}]"
    out = work_dir / "_concat.mp4"
    r = subprocess.run(
        ["ffmpeg","-y"]+inputs+[
            "-filter_complex",";".join(parts),"-map","[vout]",
            "-c:v","libx264","-preset","fast","-crf","18","-t",str(duration),"-an",str(out)],
        capture_output=True, text=True)
    if r.returncode != 0:
        lst = work_dir/"_list.txt"
        lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
        subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
                        "-c","copy",str(out)], capture_output=True)
    return out

# ── 8. Final assembly ────────────────────────────────────────────────────────

def assemble(video, narration, music_path, final):
    print("Assembling final video...")
    mixed = final.parent / "_mixed.aac"
    subprocess.run([
        "ffmpeg","-y","-i",str(narration),"-i",str(music_path),
        "-filter_complex","[0:a]volume=1.0[v];[1:a]volume=0.35[m];"
                          "[v][m]amix=inputs=2:duration=first:dropout_transition=4[o]",
        "-map","[o]","-c:a","aac","-b:a","192k",str(mixed)
    ], capture_output=True)

    r = subprocess.run([
        "ffmpeg","-y","-i",str(video),"-i",str(mixed),
        "-vf","format=yuv420p",
        "-color_range","1","-colorspace","bt709",
        "-color_primaries","bt709","-color_trc","bt709",
        "-x264-params","colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=0",
        "-c:v","libx264","-profile:v","high","-level:v","4.1",
        "-preset","fast","-crf","20",
        "-c:a","copy","-movflags","+faststart","-shortest",str(final)
    ], capture_output=True, text=True)

    if r.returncode == 0:
        mb = final.stat().st_size/1024/1024
        print(f"  ✅ {final.name}  {mb:.1f}MB")
    else:
        print(f"  HATA: {r.stderr[-300:]}")

# ── 9. YouTube Short ─────────────────────────────────────────────────────────

SHORT_INVITE_SCRIPTS = [
    "Wyobraź sobie, że każdej nocy zasypiasz wśród gwiazd... Głęboki sen, spokojny oddech, piękne obrazy. Śledź kanał Kosmiczny Sen — nowy odcinek każdego wieczoru o ósmej. Do zobaczenia w kosmosie.",
    "Czy wiesz, że spokojny sen to najlepszy odpoczynek, jaki możesz sobie dać? Na kanale Kosmiczny Sen znajdziesz medytacyjne opowieści, które pomogą ci zasnąć każdej nocy. Subskrybuj — nowy odcinek o ósmej.",
    "Każdej nocy o ósmej — nowa podróż przez kosmos. Zamknij oczy, oddech się uspokaja, myśli odpływają. Kosmiczny Sen — zasubskrybuj i śpij głębiej każdej nocy.",
    "Głęboki sen zaczyna się od jednego spokojnego oddechu... i jednej opowieści. Kosmiczny Sen — medytacyjne podróże przez wszechświat, każdego wieczoru o ósmej. Śledź kanał, żeby nie przegapić.",
]

import random

async def make_short(clips: list, ep_dir: Path, topic: str) -> Path:
    """Create a 9:16 YouTube Short (≤60s) with space visuals and channel invite."""
    print("Creating YouTube Short...")
    short_dir = ep_dir / "short"
    short_dir.mkdir(exist_ok=True)

    # Pick invite script
    script = random.choice(SHORT_INVITE_SCRIPTS)

    # Generate TTS for short
    short_audio = short_dir / "short_narration.mp3"
    chunks = _split_ssml_chunks(script, max_bytes=4000)
    wav_parts = []
    for i, chunk in enumerate(chunks):
        body = json.dumps({
            "input": {"text": chunk},
            "voice": {"languageCode": "pl-PL", "name": TTS_VOICE},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 44100}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://texttospeech.googleapis.com/v1beta1/text:synthesize?key={GOOGLE_TTS_KEY}",
            data=body, headers={"Content-Type": "application/json; charset=utf-8"}
        )
        try:
            r = urllib.request.urlopen(req, timeout=30)
            raw = base64.b64decode(json.loads(r.read())["audioContent"])
            p = short_dir / f"_s{i}.wav"
            p.write_bytes(raw)
            wav_parts.append(p)
        except Exception as e:
            print(f"  Short TTS error: {e}")
            return None

    _merge_wav_parts(wav_parts, short_audio)
    for p in wav_parts:
        p.unlink(missing_ok=True)

    # Get narration duration (cap at 58s for Shorts)
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",str(short_audio)],
        capture_output=True, text=True)
    try:
        nar_dur = min(float(r.stdout.strip()), 58.0)
    except:
        nar_dur = 45.0

    # Generate short ambient music
    short_music = short_dir / "short_music.wav"
    make_music(nar_dur + 2, short_music)

    # Mix audio
    short_mixed = short_dir / "short_mixed.aac"
    subprocess.run([
        "ffmpeg","-y","-i",str(short_audio),"-i",str(short_music),
        "-filter_complex","[0:a]volume=1.0[v];[1:a]volume=0.30[m];"
                          "[v][m]amix=inputs=2:duration=first:dropout_transition=2[o]",
        "-map","[o]","-c:a","aac","-b:a","192k",str(short_mixed)
    ], capture_output=True)

    # Crop best clip to 9:16 (1080x1920)
    best_clip = clips[0] if clips else None
    short_video = short_dir / "short_video.mp4"
    if best_clip:
        subprocess.run([
            "ffmpeg","-y","-i",str(best_clip),
            "-t",str(nar_dur),
            "-vf",("scale=1080:1920:force_original_aspect_ratio=increase,"
                   "crop=1080:1920,fps=25"),
            "-c:v","libx264","-preset","fast","-crf","20","-an",str(short_video)
        ], capture_output=True)
    else:
        # Black background fallback
        subprocess.run([
            "ffmpeg","-y","-f","lavfi","-i",f"color=c=black:s=1080x1920:r=25:d={nar_dur:.1f}",
            "-c:v","libx264","-preset","fast",str(short_video)
        ], capture_output=True)

    # Text overlay: channel name + topic (bottom)
    safe_topic = topic.replace("'", "\\'").replace(":", "\\:")
    drawtext = (
        f"drawtext=text='🌙 Kosmiczny Sen':fontsize=52:fontcolor=white:x=(w-text_w)/2:y=h-220"
        f":shadowcolor=black:shadowx=2:shadowy=2,"
        f"drawtext=text='Nowy odcinek każdego wieczoru o 20\\:00':fontsize=32"
        f":fontcolor=0xC8C8FF:x=(w-text_w)/2:y=h-150:shadowcolor=black:shadowx=1:shadowy=1"
    )

    short_final = ep_dir / "short.mp4"
    r = subprocess.run([
        "ffmpeg","-y","-i",str(short_video),"-i",str(short_mixed),
        "-vf",f"format=yuv420p,{drawtext}",
        "-c:v","libx264","-preset","fast","-crf","20",
        "-c:a","copy","-movflags","+faststart","-shortest",str(short_final)
    ], capture_output=True, text=True)

    if r.returncode == 0:
        mb = short_final.stat().st_size / 1024 / 1024
        print(f"  ✅ Short created: {short_final.name}  {mb:.1f}MB  {nar_dur:.0f}s")
    else:
        # Fallback without text overlay
        subprocess.run([
            "ffmpeg","-y","-i",str(short_video),"-i",str(short_mixed),
            "-vf","format=yuv420p","-c:v","libx264","-preset","fast","-crf","20",
            "-c:a","copy","-movflags","+faststart","-shortest",str(short_final)
        ], capture_output=True)
        print(f"  ✅ Short created (no overlay): {short_final.name}")

    # Cleanup
    for f in short_dir.glob("*.mp4"): f.unlink(missing_ok=True)
    for f in short_dir.glob("*.wav"): f.unlink(missing_ok=True)
    for f in short_dir.glob("*.aac"): f.unlink(missing_ok=True)
    for f in short_dir.glob("*.mp3"): f.unlink(missing_ok=True)
    try: short_dir.rmdir()
    except: pass

    return short_final

# ── Main ─────────────────────────────────────────────────────────────────────

async def run(topic: str, duration: int, hook: str = ""):
    safe   = re.sub(r"[^\w\-]", "_", topic.lower())[:40]
    ep_dir = Path("episodes") / safe
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir/"clips").mkdir(exist_ok=True)

    # Paths
    script_f  = ep_dir / "script.txt"
    audio_f   = ep_dir / "narration.mp3"
    ass_f     = ep_dir / "subtitles.ass"
    music_f   = ep_dir / "music.wav"
    thumb_f   = ep_dir / "thumbnail.jpg"
    final_f   = ep_dir / f"kosmiczny_sen_{safe}.mp4"

    print(f"\n{'═'*55}")
    print(f"  KOSMICZNY SEN — {topic}")
    print(f"  Duration: {duration//60} min  |  Output: {ep_dir}")
    print(f"{'═'*55}\n")

    # 1. Script
    if script_f.exists():
        print("Script cached — skipping generation")
        script = script_f.read_text(encoding="utf-8")
    else:
        script = generate_script(topic, duration)
        script_f.write_text(script, encoding="utf-8")

    # 2. Audio + subtitles
    sentences = await gen_audio(script, audio_f)
    make_ass(sentences, ass_f)

    nar_dur = float(subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1",str(audio_f)],
        capture_output=True, text=True).stdout.strip())
    print(f"  Narration: {nar_dur/60:.1f} min")

    # 3. Video clips — daha fazla çeşit al, döngüye alınacak
    clips = fetch_clips(topic, ep_dir/"clips", n=15)
    if not clips:
        print("ERROR: no clips"); return

    # 4. Music
    make_music(nar_dur, music_f)

    # 5. Thumbnail
    make_thumbnail(clips, topic, thumb_f, hook=hook)

    # 6. Build video — her klip kendi doğal süresiyle (max 40s)
    ready = prepare_clips(clips, nar_dur, ep_dir)
    video = concat_xfade(ready, nar_dur, ep_dir)
    assemble(video, audio_f, music_f, final_f)

    # 7. YouTube Short
    await make_short(clips, ep_dir, topic)

    # Cleanup temp
    for f in ep_dir.glob("_*.mp4"): f.unlink(missing_ok=True)
    for f in ep_dir.glob("_*.txt"): f.unlink(missing_ok=True)
    for f in ep_dir.glob("_*.aac"): f.unlink(missing_ok=True)

    print(f"\n{'═'*55}")
    print(f"  DONE → {final_f}")
    print(f"{'═'*55}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="Episode topic in Polish, e.g. 'Powierzchnia Księżyca'")
    ap.add_argument("--duration", type=int, default=2700, help="Duration in seconds (default 2700 = 45 min)")
    args = ap.parse_args()
    asyncio.run(run(args.topic, args.duration))
