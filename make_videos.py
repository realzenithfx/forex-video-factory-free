# make_videos.py  (ASCII only)
import os
import datetime
import random
from pathlib import Path

import numpy as np
import pandas as pd
from pytz import timezone, UTC
import requests

from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, ColorClip
from moviepy.audio.AudioClip import CompositeAudioClip, AudioClip  # for silence

import pyttsx3
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---- ENV ----
PEXELS_API_KEY   = os.getenv("PEXELS_API_KEY", "")
YT_CLIENT_ID     = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN")

PT = timezone("America/Los_Angeles")
RENDERS = Path("renders"); RENDERS.mkdir(exist_ok=True)
TMP     = Path("tmp"); TMP.mkdir(exist_ok=True)
MUSIC_DIR = Path("music")  # optional

# ---- YouTube client ----
def yt_client():
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        raise RuntimeError("Missing YouTube OAuth secrets.")
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def schedule_to_iso_utc(pacific_str):
    dt_pt = PT.localize(datetime.datetime.strptime(pacific_str, "%Y-%m-%d %H:%M"))
    return dt_pt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---- Pexels ----
def pexels_portrait_video(query):
    if not PEXELS_API_KEY:
        return None
    r = requests.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "per_page": 5},
        headers={"Authorization": PEXELS_API_KEY},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    for v in data.get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: f.get("width", 0))
        for f in files:
            if f.get("height", 0) > f.get("width", 0) and f.get("link"):
                return f["link"]
    return None

def download_to_tmp(url, suffix):
    p = TMP / f"dl_{random.randint(100000, 999999)}{suffix}"
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(p, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk: f.write(chunk)
    return str(p)

# ---- Text (PIL -> ImageClip) ----
def make_text_panel(text, width=980, font_size=64, pad=20,
                    fg=(255,255,255,255), bg=(11,31,59,200)):
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGB", (width, 10))
    draw = ImageDraw.Draw(dummy)
    words = (text or "").split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) > width - 2*pad:
            if line: lines.append(line)
            line = w
        else:
            line = test
    if line: lines.append(line)

    height = pad*2 + int(len(lines) * max(font_size * 1.2, font_size))
    img = Image.new("RGBA", (width, max(height, font_size + 2*pad)), (0,0,0,0))
    d = ImageDraw.Draw(img)
    d.rectangle([0,0,width,img.size[1]], fill=bg)
    y = pad
    for ln in lines:
        d.text((pad,y), ln, font=font, fill=fg)
        y += int(max(font_size * 1.2, font_size))
    return np.array(img)

def pick_music():
    try:
        return str(next(MUSIC_DIR.glob("*.mp3")))
    except StopIteration:
        return None

def synthesize_tts(script_text, out_wav_path):
    eng = pyttsx3.init()
    eng.setProperty("rate", 170)
    eng.save_to_file(script_text, out_wav_path)
    eng.runAndWait()

# ---- Audio helpers ----
def make_silence(duration, fps=44100, nch=2):
    def frame_fn(t):
        return np.zeros((nch,), dtype=np.float32)
    return AudioClip(make_frame=frame_fn, duration=duration, fps=fps)

# ---- Build video ----
def build_video(title, overlay, script, broll_kw, music_path=None):
    # Background 1080x1920
    clip_url = pexels_portrait_video(broll_kw or "forex charts")
    if clip_url:
        local = download_to_tmp(clip_url, ".mp4")
        bg = VideoFileClip(local).without_audio().resize(height=1920)
        if bg.w != 1080:
            x1 = max(0, (bg.w - 1080)//2)
            bg = bg.crop(x1=x1, y1=0, x2=x1+1080, y2=1920)
        bg = bg.subclip(0, min(bg.duration, 45))
    else:
        bg = ColorClip(size=(1080,1920), color=(10,10,10)).set_duration(30)

    dur = min(bg.duration, 60)

    # Voice (natural length, then clamp safely)
    vo_wav = TMP / "voice.wav"
    synthesize_tts(script or title, str(vo_wav))
    voice_file = AudioFileClip(str(vo_wav))
    vdur = float(voice_file.duration or 0.0)
    safe_end = max(0.0, min(vdur, dur) - 0.10)  # small margin
    voice = voice_file.set_start(0).set_end(safe_end)

    # Music underlay + silent bed so mixer never queries beyond end
    bed = make_silence(dur, fps=44100, nch=2)
    if music_path and Path(music_path).exists():
        mus = AudioFileClip(music_path).volumex(0.2).audio_fadein(0.3).audio_fadeout(0.3).set_duration(dur)
        audio = CompositeAudioClip([bed, mus, voice]).set_duration(dur)
    else:
        audio = CompositeAudioClip([bed, voice]).set_duration(dur)

    # Text overlays
    top_img = make_text_panel(overlay or title)
    top = ImageClip(top_img).set_duration(dur).set_position(("center", 80))
    cta_img = make_text_panel("ZenithFX.com", width=600, font_size=56)
    cta = ImageClip(cta_img).set_duration(dur).set_position(("center", "bottom"))

    out = CompositeVideoClip([bg, top, cta], size=(1080,1920)).set_audio(audio)
    return out.set_duration(dur)

# ---- Upload (private + publishAt) ----
def upload_scheduled(youtube, mp4_path, title, desc, hashtags, publish_at_iso, link):
    body = {
        "snippet": {
            "title": title,
            "description": f"{desc}\n\nThis video features content by Forex Voyage.\n{link or 'https://zenithfx.com/'}\n{hashtags or ''}",
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_iso,
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(str(mp4_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
    return resp.get("id")

# ---- Main ----
def main():
    df = pd.read_csv("prompts.csv")
    now_pt = datetime.datetime.now(PT)

    df["dt"] = df["PublishTime_Pacific"].apply(
        lambda s: PT.localize(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M"))
    )
    future = df[df["dt"] > now_pt].sort_values("dt").head(5)
    if future.empty:
        print("No future rows to process.")
        return

    yt = yt_client()

    for _, row in future.iterrows():
        title   = str(row.get("Title", "Forex Voyage"))
        script  = str(row.get("Script", title))
        overlay = str(row.get("OverlayText", title))
        broll   = str(row.get("Broll_Keywords", "forex charts"))
        tags    = str(row.get("Hashtags", ""))
        link    = str(row.get("ZenithFX_Link", "https://zenithfx.com/"))
        publish_iso = schedule_to_iso_utc(str(row["PublishTime_Pacific"]))

        music = pick_music()
        clip = build_video(title, overlay, script, broll, music)

        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:30]
        out_path = RENDERS / f"{row['PublishTime_Pacific'].replace(' ', '_')}_{safe_title}.mp4"
        clip.write_videofile(
            str(out_path),
            fps=30,
            audio_fps=44100,
            audio_codec="aac",
            codec="libx264",
            preset="medium"
        )
        vid = upload_scheduled(yt, out_path, title, script, tags, publish_iso, link)
        print("Uploaded:", vid)

if __name__ == "__main__":
    main()
