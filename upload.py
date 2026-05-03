"""YouTube'a otomatik video yükleme."""
import os, json, time
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

def upload(video_path: Path, title: str, description: str,
           tags: list, thumbnail_path: Path = None):
    yt = get_youtube()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs (uyku içeriği için)
            "defaultLanguage": "pl",
            "defaultAudioLanguage": "pl",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    print(f"Yükleniyor: {video_path.name}")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"  %{int(status.progress()*100)}", end="\r")

    video_id = response["id"]
    print(f"  ✅ Yüklendi: https://youtube.com/watch?v={video_id}")

    if thumbnail_path and thumbnail_path.exists():
        yt.thumbnails().set(videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path))).execute()
        print(f"  ✅ Thumbnail ayarlandı")

    return video_id

def upload_latest():
    """En son üretilen bölümü yükle."""
    schedule_f = Path("schedule.json")
    if not schedule_f.exists():
        print("schedule.json bulunamadı"); return

    data = json.loads(schedule_f.read_text(encoding="utf-8"))
    episodes = data.get("episodes", [])

    # video_id olmayan son bölümü bul
    pending = [ep for ep in episodes if not ep.get("video_id")]
    if not pending:
        print("Yüklenecek bölüm yok"); return

    ep = pending[-1]
    safe  = ep["topic_safe"]
    ep_dir = Path("episodes") / safe

    video_f = next(ep_dir.glob("*.mp4"), None)
    thumb_f = ep_dir / "thumbnail.jpg"

    if not video_f:
        print(f"Video bulunamadı: {ep_dir}"); return

    # Başlık + açıklama
    hook  = ep.get("hook", ep["topic"])
    title = f"{hook} | Kosmiczny Sen 🌙 | Sen & Relaksacja"

    description = f"""{hook}

{ep.get('description', '')}

Zamknij oczy i pozwól się ponieść w głąb tej opowieści...

────────────────────────────
🌙 Kosmiczny Sen — Zaśnij wśród gwiazd
Nowy odcinek każdego dnia.
Subskrybuj i włącz powiadomienia 🔔
────────────────────────────

#sen #relaksacja #medytacja #kosmicznySen #zasypianie #spokojnySen #{ep['category'].replace(' ','')}"""

    tags = [
        "sen", "relaksacja", "medytacja", "zasypianie", "kosmiczny sen",
        "opowiadanie do snu", "muzyka relaksacyjna", "głęboki sen",
        "bezsenność", "spokojny sen", "kosmos", "przestrzeń",
        ep["category"], "sleep meditation", "polish sleep story"
    ]

    video_id = upload(video_f, title, description, tags, thumb_f)

    # schedule.json'a kaydet
    ep["video_id"] = video_id
    ep["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M")
    schedule_f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n  Kaydedildi: {ep['topic']} → {video_id}")

if __name__ == "__main__":
    upload_latest()
