"""
API key'leri buradan yönet.
VM'de: environment variable olarak set edilir.
Local: direkt buraya yaz (git'e gitmez).
"""
import os

GEMINI_KEY  = os.environ.get("GEMINI_KEY",  "AIzaSyB9WWEDjEVK9tU9ToSQOoNMzH1be6EjxMg")
PIXABAY_KEY = os.environ.get("PIXABAY_KEY", "55660544-40e38f4b37085fea779630d17")
NASA_KEY    = os.environ.get("NASA_KEY",    "u29vv3BjmHNj1Pjtbrsc1N6fOaJIJWg1ekZGRXF1")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
