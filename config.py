"""
API key'leri environment variable'lardan okur.
GitHub Actions: Secrets olarak tanımla.
Local çalıştırma: .env dosyası veya terminalde export et.
"""
import os

GEMINI_KEY   = os.environ.get("GEMINI_KEY", "")
PIXABAY_KEY  = os.environ.get("PIXABAY_KEY", "")
NASA_KEY     = os.environ.get("NASA_KEY", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
