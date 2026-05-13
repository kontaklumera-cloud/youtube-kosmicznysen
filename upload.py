"""YouTube'a otomatik video yükleme."""
import os, json, time, datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

TOKEN_FILE  = Path("token.json")
SECRET_FILE = Path("client_secret.json")

def get_youtube():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def _schedule_time(hour: int, minute: int) -> str:
    """Return ISO 8601 UTC timestamp for next occurrence of given Warsaw hour:minute."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    # Poland: UTC+2 (CEST, Apr–Oct) or UTC+1 (CET, Nov–Mar)
    month = now_utc.month
    utc_offset = 2 if 3 < month < 11 else 1
    target_utc_hour = hour - utc_offset
    publish = now_utc.replace(hour=target_utc_hour, minute=minute, second=0, microsecond=0)
    # If the time has already passed (or within 15 min), push to next day
    if publish <= now_utc + datetime.timedelta(minutes=15):
        publish += datetime.timedelta(days=1)
    return publish.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def upload(video_path: Path, title: str, description: str,
           tags: list, thumbnail_path: Path = None,
           publish_at: str = None, is_short: bool = False):
    """
    publish_at: ISO 8601 UTC string — if set, video is scheduled (private until then).
    is_short: if True, adds #Shorts to title and sets category to 22.
    """
    yt = get_youtube()

    full_title = (title + " #Shorts")[:100] if is_short else title[:100]

    body = {
        "snippet": {
            "title": full_title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
            "defaultLanguage": "pl",
            "defaultAudioLanguage": "pl",
        },
        "status": {
            "privacyStatus": "private" if publish_at else "public",
            "selfDeclaredMadeForKids": False,
        }
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(str(video_path), chunksize=5*1024*1024, resumable=True,
                            mimetype="video/mp4")
    print(f"Yükleniyor: {video_path.name}")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retry = 0
    while response is None:
        try:
            status, response = req.next_chunk()
            if status:
                print(f"  %{int(status.progress()*100)}", end="\r")
            retry = 0
        except Exception as e:
            retry += 1
            if retry > 10:
                raise
            wait = min(60, 5 * retry)
            print(f"\n  Ağ hatası ({e.__class__.__name__}), {wait}s sonra tekrar...")
            time.sleep(wait)

    video_id = response["id"]
    if publish_at:
        print(f"  ✅ Zamanlandı ({publish_at}): https://youtube.com/watch?v={video_id}")
    else:
        print(f"  ✅ Yüklendi: https://youtube.com/watch?v={video_id}")

    if thumbnail_path and thumbnail_path.exists():
        yt.thumbnails().set(videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path))).execute()
        print(f"  ✅ Thumbnail ayarlandı")

    return video_id

def upload_latest():
    """En son üretilen bölümü ve Short'u yükle — ana video 20:00, Short 20:15."""
    schedule_f = Path("schedule.json")
    if not schedule_f.exists():
        print("schedule.json bulunamadı"); return

    data = json.loads(schedule_f.read_text(encoding="utf-8"))
    episodes = data.get("episodes", [])

    pending = [ep for ep in episodes if not ep.get("video_id")]
    if not pending:
        print("Yüklenecek bölüm yok"); return

    ep = pending[-1]
    safe   = ep["topic_safe"]
    ep_dir = Path("episodes") / safe

    # Main video (not the short)
    main_videos = [f for f in ep_dir.glob("*.mp4") if f.name != "short.mp4"]
    video_f = main_videos[0] if main_videos else None
    short_f = ep_dir / "short.mp4"
    thumb_f = ep_dir / "thumbnail.jpg"

    if not video_f:
        print(f"Video bulunamadı: {ep_dir}"); return

    hook  = ep.get("hook", ep["topic"])
    title = f"{hook} | Kosmiczny Sen 🌙 | Sen & Relaksacja"

    description = f"""{hook}

{ep.get('description', '')}

Zamknij oczy i pozwól się ponieść w głąb tej opowieści...

────────────────────────────
🌙 Kosmiczny Sen — Zaśnij wśród gwiazd
Nowy odcinek każdego wieczoru o 20:00.
Subskrybuj i włącz powiadomienia 🔔
────────────────────────────

#sen #relaksacja #medytacja #kosmicznySen #zasypianie #spokojnySen #{ep['category'].replace(' ','')}"""

    tags = [
        "sen", "relaksacja", "medytacja", "zasypianie", "kosmiczny sen",
        "opowiadanie do snu", "muzyka relaksacyjna", "głęboki sen",
        "bezsenność", "spokojny sen", "kosmos", "przestrzeń",
        ep["category"], "sleep meditation", "polish sleep story"
    ]

    # Upload main video — scheduled 20:00
    main_publish = _schedule_time(20, 0)
    print(f"Ana video yükleniyor → {main_publish}")
    video_id = upload(video_f, title, description, tags, thumb_f,
                      publish_at=main_publish)

    ep["video_id"] = video_id
    ep["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M")
    ep["publish_at"] = main_publish

    # Upload Short — scheduled 20:15
    if short_f.exists():
        short_title = f"{hook} | Kosmiczny Sen 🌙"
        short_desc = (
            f"Zaśnij wśród gwiazd 🌙\n\n"
            f"Pełny odcinek na kanale Kosmiczny Sen — nowy każdego wieczoru o 20:00!\n\n"
            f"#sen #kosmos #relaksacja #zasypianie #kosmicznySen"
        )
        short_tags = ["sen", "shorts", "relaksacja", "kosmos", "kosmiczny sen",
                      "zasypianie", "medytacja", "sleep", "space"]
        short_publish = _schedule_time(22, 0)
        print(f"Short yükleniyor → {short_publish}")
        short_id = upload(short_f, short_title, short_desc, short_tags,
                          publish_at=short_publish, is_short=True)
        ep["short_id"] = short_id
        ep["short_publish_at"] = short_publish
        print(f"  Short: https://youtube.com/shorts/{short_id}")
    else:
        print("  Short bulunamadı, atlanıyor")

    schedule_f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n  Kaydedildi: {ep['topic']} → {video_id}")

if __name__ == "__main__":
    upload_latest()
