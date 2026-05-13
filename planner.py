"""
Kosmiczny Sen — otomatik konu planlayıcı
Gemini her kategori için taze, benzersiz konular üretir.
Kullanım:
  python planner.py               # sonraki konuyu seç ve videoyu üret
  python planner.py --list        # planlanmış konuları listele
  python planner.py --stats       # kategori performansını göster
"""
import json, time, argparse, asyncio
from pathlib import Path
import anthropic

import os
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SCHEDULE_F  = Path("schedule.json")
DURATION    = 1800  # 30 dk

# ── Kategoriler ───────────────────────────────────────────────────────────────

CATEGORIES = [
    {
        "id":    "kosmos",
        "name":  "Kosmos",
        "emoji": "🚀",
        "desc":  "Stacje kosmiczne, planety, podróże przez układ słoneczny",
        "weight": 1.0,
    },
    {
        "id":    "gleboki_kosmos",
        "name":  "Głęboki Kosmos",
        "emoji": "🌌",
        "desc":  "Mgławice, galaktyki, czarne dziury, kwazary, początki wszechświata",
        "weight": 1.0,
    },
    {
        "id":    "wyobraznia",
        "name":  "Wyobraźnia",
        "emoji": "✨",
        "desc":  "Wyobraźne światy: pływające wyspy, kryształowe jaskinie, zaczarowane lasy, podwodne miasta, światy z dwoma słońcami, planety z pierścieniami lodowymi",
        "weight": 1.0,
    },
    {
        "id":    "natura",
        "name":  "Natura",
        "emoji": "🌊",
        "desc":  "Zorza polarna, głębiny oceanu, jesienny las, góry w nocy, deszcz, rzeki",
        "weight": 1.0,
    },
    {
        "id":    "mistyczne",
        "name":  "Mistyczne",
        "emoji": "🔮",
        "desc":  "Starożytne świątynie, magiczne lasy, kryształowe groty, tajemnicze ogrody, ruiny w dżungli",
        "weight": 1.0,
    },
    {
        "id":    "podwodne",
        "name":  "Podwodne Światy",
        "emoji": "🐋",
        "desc":  "Głębiny oceanu, rafy koralowe, bioluminescencja, podwodne jaskinie, świt pod wodą",
        "weight": 1.0,
    },
]

# ── Schedule yönetimi ─────────────────────────────────────────────────────────

def load_schedule() -> dict:
    if SCHEDULE_F.exists():
        return json.loads(SCHEDULE_F.read_text(encoding="utf-8"))
    return {
        "episodes": [],
        "category_index": 0,
        "category_stats": {c["id"]: {"produced": 0, "views": 0, "likes": 0} for c in CATEGORIES}
    }

def save_schedule(data: dict):
    SCHEDULE_F.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def used_topics(data: dict) -> list:
    return [ep["topic"] for ep in data["episodes"]]

# ── Ağırlık hesaplama (YouTube analitikten) ───────────────────────────────────

def update_weights(data: dict) -> list:
    """
    Kategorilerin ağırlığını YouTube performansına göre güncelle.
    Yeterli veri yoksa eşit ağırlık kullan.
    """
    stats = data["category_stats"]
    cats  = [c.copy() for c in CATEGORIES]

    total_views = sum(s["views"] for s in stats.values())
    total_likes = sum(s["likes"] for s in stats.values())

    if total_views < 500:
        # Yeterli veri yok — eşit rotasyon
        return cats

    for cat in cats:
        s = stats.get(cat["id"], {"views": 0, "likes": 0, "produced": 1})
        produced = max(s["produced"], 1)
        avg_views = s["views"] / produced
        avg_likes = s["likes"] / produced
        # engagement score
        score = avg_views * 0.6 + avg_likes * 40
        cat["weight"] = max(0.3, score / (total_views / len(cats) + 1))

    return cats

# ── Sonraki kategoriyi seç ────────────────────────────────────────────────────

def pick_category(data: dict) -> dict:
    cats = update_weights(data)

    # Ağırlıklı round-robin: en az üretilmiş + en yüksek ağırlıklı
    stats = data["category_stats"]
    scored = []
    for cat in cats:
        produced = stats.get(cat["id"], {}).get("produced", 0)
        # Az üretilmiş kategorilere öncelik + ağırlık
        priority = cat["weight"] / (produced + 1)
        scored.append((priority, cat))

    scored.sort(key=lambda x: -x[0])
    chosen = scored[0][1]
    print(f"  Kategori seçildi: {chosen['emoji']} {chosen['name']}  (öncelik: {scored[0][0]:.3f})")
    return chosen

# ── Gemini: konu + arama terimleri üret ──────────────────────────────────────

def generate_topic(category: dict, used: list) -> dict:
    """
    Gemini'den şunu iste:
    - Lehçe konu başlığı (özgün, daha önce kullanılmamış)
    - 3 Pixabay arama terimi (İngilizce)
    - Kısa açıklama
    """
    print(f"  Claude konu üretiyor ({category['name']})...")

    used_str = "\n".join(f"- {t}" for t in used[-20:]) if used else "— henüz yok —"

    prompt = f"""Sen bir Polonyalı YouTube kanalı için uyku meditasyonu konuları üretiyorsun.
Kanal adı: "Kosmiczny Sen" (Kozmik Uyku)
Kategori: {category['emoji']} {category['name']} — {category['desc']}

Daha önce kullanılmış konular (bunları TEKRAR KULLANMA):
{used_str}

Görev: Bu kategori için YENİ, ORİJİNAL bir konu belirle.
Yanıtını SADECE aşağıdaki JSON formatında ver, başka hiçbir şey yazma:

{{
  "topic": "Konu başlığı Lehçe (örn: Pływające Wyspy nad Złotą Mgławicą)",
  "hook": "Kısa, ilgi çekici thumbnail hook metni Lehçe — max 5 kelime, merak uyandırsın (örn: 'Zaśnij Wśród Gwiazd', 'Dotknij Innych Światów', 'Dryfuj przez Galaktyki')",
  "description": "2 cümle — bu deneyim nasıl hissettiriyor",
  "pixabay_queries": ["ingilizce arama 1", "ingilizce arama 2", "ingilizce arama 3"],
  "mood": "serene/mystical/dreamy/cosmic"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    for attempt in range(5):
        try:
            r = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                temperature=0.95,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = r.content[0].text.strip()
            # JSON bloğunu çıkar
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            print(f"  Konu: {data['topic']}")
            print(f"  Sorgular: {data['pixabay_queries']}")
            return data
        except anthropic.RateLimitError:
            wait = 35 * (attempt + 1)
            print(f"  Rate limit — {wait}s bekleniyor...")
            time.sleep(wait)
        except Exception as e:
            print(f"  Hata: {e}")
            time.sleep(10)

    raise RuntimeError("Claude konu üretemedi")

# ── YouTube Analytics entegrasyonu (gelecek) ─────────────────────────────────

def sync_youtube_analytics(data: dict, yt_api_key: str = None) -> dict:
    """
    YouTube Data API v3 ile video performansını çek.
    Şimdilik manuel güncelleme — OAuth entegrasyonu sonraki aşama.
    """
    if not yt_api_key:
        print("  YouTube Analytics: henüz bağlı değil")
        return data

    # TODO: OAuth2 ile kanal videoları + istatistiklerini çek
    # Her video için: views, likes → category_stats'a yaz
    print("  YouTube Analytics sync: yakında...")
    return data

def manual_update_stats(video_id: str, views: int, likes: int):
    """Video performansını elle güncellemek için yardımcı fonksiyon."""
    data = load_schedule()
    for ep in data["episodes"]:
        if ep.get("video_id") == video_id or ep.get("topic_safe") in video_id:
            ep["views"] = views
            ep["likes"] = likes
            cat_id = ep["category_id"]
            data["category_stats"][cat_id]["views"] += views
            data["category_stats"][cat_id]["likes"] += likes
            print(f"  Güncellendi: {ep['topic']}  views={views}  likes={likes}")
            break
    save_schedule(data)

# ── Ana planlayıcı ────────────────────────────────────────────────────────────

async def plan_and_produce():
    from generate import run as produce_video
    import re

    data = load_schedule()

    print("\n" + "═"*55)
    print("  KOSMICZNY SEN — Otomatik Planlayıcı")
    print("═"*55)

    # YouTube analytics sync (bağlıysa)
    data = sync_youtube_analytics(data)

    # Kategori + konu seç
    category  = pick_category(data)
    topic_data = generate_topic(category, used_topics(data))

    topic     = topic_data["topic"]
    queries   = topic_data["pixabay_queries"]
    safe      = re.sub(r"[^\w\-]", "_", topic.lower())[:40]

    # Schedule'a kaydet
    episode = {
        "topic":       topic,
        "topic_safe":  safe,
        "category_id": category["id"],
        "category":    category["name"],
        "description": topic_data.get("description", ""),
        "mood":        topic_data.get("mood", ""),
        "queries":     queries,
        "produced_at": time.strftime("%Y-%m-%d %H:%M"),
        "views":       0,
        "likes":       0,
    }
    data["episodes"].append(episode)
    data["category_stats"][category["id"]]["produced"] += 1
    save_schedule(data)

    print(f"\n  Üretim başlıyor: {topic}")

    # generate.run'ı queries ile çağır
    import generate as gen
    safe_ep = __import__("re").sub(r"[^\w\-]", "_", topic.lower())[:40]
    ep_dir  = Path("episodes") / safe_ep
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / "clips").mkdir(exist_ok=True)

    # Script
    script_f = ep_dir / "script.txt"
    if not script_f.exists():
        script = gen.generate_script(topic, DURATION)
        script_f.write_text(script, encoding="utf-8")
    else:
        print("  Script önbellekte")
        script = script_f.read_text(encoding="utf-8")

    # Audio
    audio_f = ep_dir / "narration.mp3"
    sentences = await gen.gen_audio(script, audio_f)
    ass_f = ep_dir / "subtitles.ass"
    gen.make_ass(sentences, ass_f)

    import subprocess
    nar_dur = float(subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1", str(audio_f)],
        capture_output=True, text=True).stdout.strip())

    # Klipleri Gemini sorgularıyla indir
    clips = gen.fetch_clips(topic, ep_dir/"clips", n=15, extra_queries=queries)

    # Müzik + thumbnail + video
    music_f = ep_dir / "music.wav"
    gen.make_music(nar_dur, music_f)
    thumb_f = ep_dir / "thumbnail.jpg"
    hook = topic_data.get("hook", "")
    gen.make_thumbnail(clips, topic, thumb_f, hook=hook)

    ready = gen.prepare_clips(clips, nar_dur, ep_dir)
    video = gen.concat_xfade(ready, nar_dur, ep_dir)
    final = ep_dir / f"kosmiczny_sen_{safe_ep}.mp4"
    gen.assemble(video, audio_f, music_f, final)

    # YouTube Short üret
    await gen.make_short(clips, ep_dir, topic, hook=hook)

    for f in ep_dir.glob("_*.mp4"): f.unlink(missing_ok=True)
    for f in ep_dir.glob("_*.txt"): f.unlink(missing_ok=True)
    for f in ep_dir.glob("_*.aac"): f.unlink(missing_ok=True)

# ── CLI ───────────────────────────────────────────────────────────────────────

def print_list():
    data = load_schedule()
    eps  = data["episodes"]
    if not eps:
        print("Henüz üretilmiş bölüm yok.")
        return
    print(f"\n{'#':<4} {'Kategori':<18} {'Konu':<42} {'Tarih':<17} {'Views':>6} {'Likes':>5}")
    print("─"*95)
    for i, ep in enumerate(eps, 1):
        cat_emoji = next((c["emoji"] for c in CATEGORIES if c["id"]==ep["category_id"]), "")
        print(f"{i:<4} {cat_emoji+' '+ep['category']:<18} {ep['topic'][:40]:<42} "
              f"{ep['produced_at']:<17} {ep['views']:>6} {ep['likes']:>5}")

def print_stats():
    data = load_schedule()
    stats = data["category_stats"]
    print(f"\n{'Kategori':<20} {'Üretilen':>8} {'Views':>8} {'Likes':>7} {'Avg Views':>10} {'Ağırlık':>8}")
    print("─"*65)
    cats = update_weights(data)
    for cat in cats:
        s   = stats.get(cat["id"], {"produced":0,"views":0,"likes":0})
        avg = s["views"] / max(s["produced"],1)
        print(f"{cat['emoji']+' '+cat['name']:<20} {s['produced']:>8} {s['views']:>8} "
              f"{s['likes']:>7} {avg:>10.0f} {cat['weight']:>8.2f}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list",  action="store_true", help="Bölümleri listele")
    ap.add_argument("--stats", action="store_true", help="Kategori istatistikleri")
    ap.add_argument("--update", nargs=3, metavar=("TOPIC_SAFE","VIEWS","LIKES"),
                    help="Manuel istatistik güncelle")
    args = ap.parse_args()

    if args.list:
        print_list()
    elif args.stats:
        print_stats()
    elif args.update:
        manual_update_stats(args.update[0], int(args.update[1]), int(args.update[2]))
    else:
        asyncio.run(plan_and_produce())
