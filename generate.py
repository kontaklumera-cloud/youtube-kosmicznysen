"""
Kosmiczny Sen — tam otomatik video üretici
Kullanım:
  python generate.py "Powierzchnia Księżyca"
  python generate.py "Wnętrze Czarnej Dziury" --duration 2700
"""
import argparse, asyncio, subprocess, json, urllib.request, urllib.parse
import time, shutil, re
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont
from google import genai

# ── Config ───────────────────────────────────────────────────────────────────

import os
GEMINI_KEY  = os.environ["GEMINI_KEY"]
PIXABAY_KEY = os.environ["PIXABAY_KEY"]
NASA_KEY    = os.environ.get("NASA_KEY", "DEMO_KEY")
VOICE       = "pl-PL-MarekNeural"
SR, FPS     = 44100, 25
W, H        = 1920, 1080

# ── 1. Script generation ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Jesteś autorem medytacyjnych opowiadań do zasypiania po polsku dla kanału "Kosmiczny Sen".

STYL NARRACJI:
- Piszesz w 2. osobie liczby pojedynczej ("ty", "jesteś", "czujesz", "widzisz")
- Płynna, wciągająca narracja — jak storyteller, nie wiersz
- Pełne, rozbudowane zdania połączone ze sobą, tworzące akapity
- Słuchacz musi czuć, że JEST w tej historii, że ją przeżywa
- Tempo spokojne, ale tekst ciągły — nie urywki, nie listy słów

FORMAT:
- Tekst podzielony na akapity (3-6 zdań każdy)
- Między akapitami jedna pusta linia
- ZAKAZ pisania pojedynczych słów lub półzdań jako osobnych linii
- ZAKAZ nagłówków, list, markdown, numerowania
- Tylko czysty, płynny tekst narracyjny

PRZYKŁAD DOBREGO STYLU:
Unosisz się delikatnie ponad powierzchnią planety, czując jak grawitacja powoli puszcza twoje ciało. Przed tobą rozciąga się ocean złotych chmur, mieniący się w świetle trzech odległych słońc. Powietrze jest ciepłe i lekkie, pachnie czymś słodkim, czego nie potrafisz nazwać, ale co od razu sprawia, że twoje ramiona opadają, a oddech staje się głębszy.

Gdzieś w dole, przez szczeliny w chmurach, dostrzegasz zarys ogromnych kryształowych wież. Są niebieskie i fioletowe, i dzwonią cicho, gdy wieje wiatr — jakby cały świat był jednym wielkim instrumentem muzycznym. Powoli opadasz ku nim, bez strachu, z poczuciem, że to miejsce czekało właśnie na ciebie.
"""

def _gemini_call(prompt: str, system: str, temperature=0.85, max_tokens=8000) -> str:
    """Gemini API çağrısı — rate limit retry ile."""
    client = genai.Client(api_key=GEMINI_KEY)
    for attempt in range(6):
        try:
            r = client.models.generate_content(
                model="models/gemini-2.5-flash-lite",
                contents=prompt,
                config={"system_instruction": system,
                        "temperature": temperature,
                        "max_output_tokens": max_tokens}
            )
            return r.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE" in str(e):
                wait = 40 * (attempt + 1)
                print(f"  Rate limit — {wait}s bekleniyor...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini API failed after retries")

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
            f"Zacznij od: 'Zamknij oczy...' Opisz dźwięki, zapachy, odczucia ciała.\n"
            f"Zakończ gdy słuchacz już zasypia. Tylko czysty tekst, bez nagłówków."
        )
        script = _gemini_call(prompt, SYSTEM_PROMPT, max_tokens=8000)
        print(f"  {len(script.split())} kelime üretildi")
        return script

    # Uzun (45 dk) — 3 parçada üret
    parts = []
    part_words = words_needed // 3
    extra       = words_needed - part_words * 3

    part_prompts = [
        (
            f"Napisz PIERWSZĄ CZĘŚĆ płynnego opowiadania do zasypiania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words} słów.\n"
            f"Zacznij od słów: 'Zamknij oczy i weź głęboki oddech.'\n"
            f"Wprowadź słuchacza w scenerię — płynna narracja w akapitach (3-6 zdań każdy).\n"
            f"Pisz jak storyteller, nie jak poeta. Pełne, rozbudowane zdania tworzące obraz.\n"
            f"Zakończ akapit w połowie eksploracji — kontynuacja nastąpi w następnej części."
        ),
        (
            f"Napisz ŚRODKOWĄ CZĘŚĆ opowiadania do zasypiania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words + extra} słów.\n"
            f"Kontynuuj płynnie od momentu, gdzie skończyła się pierwsza część.\n"
            f"Wchodź głębiej w scenerię — nowe miejsca, szczegóły, odczucia zmysłowe.\n"
            f"Akapity po 3-6 zdań. Słuchacz powoli odpływa w sen.\n"
            f"Zakończ akapit — kontynuacja nastąpi."
        ),
        (
            f"Napisz KOŃCOWĄ CZĘŚĆ opowiadania do zasypiania na temat: '{topic}'.\n"
            f"Dokładnie około {part_words} słów.\n"
            f"Słuchacz jest już bardzo senny. Narracja wciąż płynna, ale spokojniejsza.\n"
            f"Ostatnie obrazy są coraz bardziej mgławicowe, rozmyte jak sen.\n"
            f"Zakończ gdy słuchacz całkowicie zasypia — ostatnie zdanie bardzo spokojne."
        ),
    ]

    for i, prompt in enumerate(part_prompts, 1):
        print(f"  Parça {i}/3 üretiliyor...")
        part = _gemini_call(prompt, SYSTEM_PROMPT, temperature=0.88, max_tokens=8000)
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
    "cat","bird","sport","football","beach party","fireworks","office","business"
}

def _tags_ok(tags_str: str) -> bool:
    tags = {t.strip().lower() for t in tags_str.split(",")}
    return len(tags & BLACKLIST_TAGS) == 0

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
               f"&q={urllib.parse.quote(q)}&per_page=15"
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

async def gen_audio(script: str, out_path: Path):
    import edge_tts
    print("Generating audio...")
    tts = edge_tts.Communicate(script, voice=VOICE, rate="-12%", pitch="-3Hz")
    sentences = []
    with open(out_path, "wb") as f:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                sentences.append({
                    "text":  chunk["text"],
                    "start": chunk["offset"]  / 10_000_000,
                    "dur":   chunk["duration"] / 10_000_000,
                })
    print(f"  {len(sentences)} sentence timestamps")
    return sentences

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
        for p in [f"C:/Windows/Fonts/{'arialbd' if bold else 'arial'}.ttf"]:
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
    n   = len(raw)
    seg = duration / n
    ready = []
    print(f"Preparing {n} clips ({seg:.1f}s each)...")
    for i, src in enumerate(raw):
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",str(src)],
            capture_output=True, text=True)
        try: src_dur = float(r.stdout.strip())
        except: src_dur = seg
        start = max(0, (src_dur - seg) / 2)
        dest  = work_dir / f"_r{i:02d}.mp4"
        subprocess.run([
            "ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(seg),
            "-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
            "-c:v","libx264","-preset","fast","-crf","18","-an",str(dest)
        ], capture_output=True)
        if dest.exists(): ready.append(dest)
        print(f"  clip {i+1}/{n}")
    return ready

def concat_xfade(clips: list, duration: float, seg: float, work_dir: Path):
    if len(clips) == 1: return clips[0]
    print("Applying crossfades...")
    inputs = sum([["-i",str(c)] for c in clips],[])
    fade   = 0.8
    parts, cur = [], "[0:v]"
    for i in range(1, len(clips)):
        offset = i*seg - i*fade
        nxt = f"[v{i}]" if i < len(clips)-1 else "[vout]"
        parts.append(f"{cur}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}{nxt}")
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

def assemble(video, narration, music_path, ass, final):
    print("Assembling final video...")
    mixed = final.parent / "_mixed.aac"
    subprocess.run([
        "ffmpeg","-y","-i",str(narration),"-i",str(music_path),
        "-filter_complex","[0:a]volume=1.0[v];[1:a]volume=0.15[m];"
                          "[v][m]amix=inputs=2:duration=first:dropout_transition=4[o]",
        "-map","[o]","-c:a","aac","-b:a","192k",str(mixed)
    ], capture_output=True)

    ass_str = str(ass).replace("\\","/").replace(":","\\:")
    r = subprocess.run([
        "ffmpeg","-y","-i",str(video),"-i",str(mixed),
        "-vf",f"format=yuv420p,ass='{ass_str}'",
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
        print("  ASS filter failed — embedding as soft subtitle")
        subprocess.run([
            "ffmpeg","-y","-i",str(video),"-i",str(mixed),"-i",str(ass),
            "-vf","format=yuv420p",
            "-color_range","1","-colorspace","bt709",
            "-color_primaries","bt709","-color_trc","bt709",
            "-x264-params","colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=0",
            "-c:v","libx264","-profile:v","high","-level:v","4.1",
            "-preset","fast","-crf","20",
            "-c:a","copy","-c:s","mov_text",
            "-movflags","+faststart","-shortest",str(final)
        ], capture_output=True)
        if final.exists():
            print(f"  ✅ {final.name} (soft subs)  {final.stat().st_size/1024/1024:.1f}MB")

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

    # 3. Video clips
    clips = fetch_clips(topic, ep_dir/"clips", n=8)
    if not clips:
        print("ERROR: no clips"); return

    # 4. Music
    make_music(nar_dur, music_f)

    # 5. Thumbnail
    make_thumbnail(clips, topic, thumb_f, hook=hook)

    # 6. Build video
    seg   = nar_dur / len(clips)
    ready = prepare_clips(clips, nar_dur, ep_dir)
    video = concat_xfade(ready, nar_dur, seg, ep_dir)
    assemble(video, audio_f, music_f, ass_f, final_f)

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
