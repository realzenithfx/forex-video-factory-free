import os, textwrap, datetime, io, random
from pathlib import Path
import numpy as np
import pandas as pd
from pytz import timezone, UTC
import requests

# MoviePy (no ImageMagick needed – we use PIL for text)
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, ColorClip
from moviepy.audio.AudioClip import CompositeAudioClip

# Free TTS (uses espeak-ng on Linux runner)
import pyttsx3

# PIL for drawing text panels safely
from PIL import Image, ImageDraw, ImageFont

# YouTube API client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# -------- ENV --------
PEXELS_API_KEY   = os.getenv("PEXELS_API_KEY", "")
YT_CLIENT_ID     = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN")

PT = timezone("America/Los_Angeles")
RENDERS = Path("renders"); RENDERS.mkdir(exist_ok=True)
TMP     = Path("tmp"); TMP.mkdir(exist_ok=True)
MUSIC_DIR = Path("music")  # optional

# -------- HELPERS --------
def yt_client():
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    return build("youtube","v3",credentials=creds, cache_discovery=False)

def schedule_to_iso_utc(pacific_str):
    dt = PT.localize(datetime.datetime.strptime(pacific_str, "%Y-%m-%d %H:%M"))
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def pexels_portrait_video(query):
    if not PEXELS_API_KEY: return None
    r = requests.get("https://api.pexels.com/videos/search",
                     params={"query":query, "per_page":5},
                     headers={"Authorization": PEXELS_API_KEY}, timeout=30)
    if r.status_code != 200: return None
    data = r.json()
    # pick a portrait file (h > w) if possible
    for v in data.get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: f.get("width",0))
        for f in files:
            if f.get("height",0) > f.get("width",0) and f.get("link"):
                return f["link"]
    return None  # fallback later
# Pexels API & license are free for commercial use.  #   
- We **don’t** use `TextClip` (which often needs ImageMagick); we render text with **PIL** instead.  
- We schedule by uploading **private** and setting **`publishAt`** (ISO-8601 UTC) — this is the official method; each `videos.insert` costs **1600 quota**. :contentReference[oaicite:14]{index=14}

**Commit new file.**

## 2.4 Workflow file: `.github/workflows/make-videos.yml`
Click **Add file → Create new file** → name: `.github/workflows/make-videos.yml` → paste:

```yaml
name: Make & Upload Forex Videos (FREE)

on:
  schedule:
    # Runs hourly at minute 5 (in UTC). GitHub schedules are always UTC.
    - cron: "5 * * * *"
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install system tools (FFmpeg + eSpeak for free TTS)
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg espeak-ng

      - name: Install Python packages
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt

      - name: Generate & upload videos (schedule)
        env:
          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
          YT_CLIENT_ID: ${{ secrets.YT_CLIENT_ID }}
          YT_CLIENT_SECRET: ${{ secrets.YT_CLIENT_SECRET }}
          YT_REFRESH_TOKEN: ${{ secrets.YT_REFRESH_TOKEN }}
        run: python make_videos.py
