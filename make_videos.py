import os, textwrap, datetime
from pathlib import Path
import pandas as pd
from pytz import timezone, UTC
import requests
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, TextClip
import pyttsx3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

PEXELS_API_KEY   = os.getenv("PEXELS_API_KEY", "")
YT_CLIENT_ID     = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN")

RENDERS = Path("renders"); RENDERS.mkdir(exist_ok=True)
MUSIC_DIR = Path("music")
PT = timezone("America/Los_Angeles")

def yt_client():
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def pexels_portrait_video(query):
    if not PEXELS_API_KEY: return None
    r = requests.get("https://api.pexels.com/videos/search",
                     params={"query":query, "per_page":3},
                     headers={"Authorization": PEXELS_API_KEY}, timeout=30)
    if r.status_code != 200: return None
    data = r.json()
    for v in data.get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: f.get("width",0))
        for f in files:
            if f.get("height",0) > f.get("width",0) and f.get("link"):
                return f["link"]
    return None

def synthesize_tts(text, outfile):
    eng = pyttsx3.init()
    eng.setProperty('rate', 170)
    eng.save_to_file(text, outfile)
    eng.runAndWait()

def build_video(title, overlay, script, broll_kw, music_path=None):
    # background
    clip_url = pexels_portrait_video(broll_kw or "forex charts")
    if clip_url:
        bg = VideoFileClip(clip_url).without_audio().resize(height=1920).crop(width=1080, height=1920, x_center=540)
        bg = bg.subclip(0, min(bg.duration, 45))
    else:
        bg = ImageClip(color=(10,10,10), size=(1080,1920)).set_duration(30)

    # voice
    vo = RENDERS / "tmp_voice.mp3"
    synthesize_tts(script, str(vo))
    voice = AudioFileClip(str(vo))

    # optional music
    audio = voice
    try:
        m = next(MUSIC_DIR.glob("*.mp3"))
        music = AudioFileClip(str(m)).volumex(0.2)
        from moviepy.audio.AudioClip import CompositeAudioClip
        audio = CompositeAudioClip([music.set_duration(voice.duration), voice])
    except StopIteration:
        pass

    # text overlays
    lines = textwrap.fill(overlay or title, 28)
    txt = TextClip(lines, fontsize=70, color="white", font="Arial-Bold", method='caption', size=(980,None)).set_position(("center","top"))
    cta = TextClip("ZenithFX.com", fontsize=56, color="white", font="Arial-Bold").set_position(("center","bottom"))
    dur = min(bg.duration, 60)
    out = CompositeVideoClip([bg.set_duration(dur), txt.set_duration(dur).margin(top=120), cta.set_duration(dur).margin(bottom=120)], size=(1080,1920))
    return out.set_audio(audio.set_duration(dur))

def schedule_to_iso_utc(pacific_str):
    dt = PT.localize(datetime.datetime.strptime(pacific_str, "%Y-%m-%d %H:%M"))
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def upload_scheduled(youtube, mp4_path, title, desc, hashtags, publish_at_iso, link):
    body = {
        "snippet": {
            "title": title,
            "description": f"{desc}\n\nThis video features content by Forex Voyage.\n{link or 'https://zenithfx.com/'}\n{hashtags or ''}",
            "categoryId": "27"
        },
        "status": {"privacyStatus": "private", "publishAt": publish_at_iso, "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(str(mp4_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
    return resp.get("id")

def main():
    df = pd.read_csv("prompts.csv")
    now_pt = datetime.datetime.now(PT)
    df["dt"] = df["PublishTime_Pacific"].apply(lambda s: PT.localize(datetime.datetime.strptime(s,"%Y-%m-%d %H:%M")))
    if "YouTubeId" in df.columns:
        df = df[df["YouTubeId"].isna()]
    batch = df[df["dt"] > now_pt].sort_values("dt").head(5)
    if batch.empty:
        print("No future rows to process.")
        return
    ytc = yt_client()
    for _, row in batch.iterrows():
        title   = str(row.get("Title","Forex Voyage"))
        script  = str(row.get("Script", title))
        overlay = str(row.get("OverlayText", title))
        broll   = str(row.get("Broll_Keywords","forex"))
        tags    = str(row.get("Hashtags",""))
        link    = str(row.get("ZenithFX_Link","https://zenithfx.com/"))
        publish_iso = schedule_to_iso_utc(str(row["PublishTime_Pacific"]))
        music = next(MUSIC_DIR.glob("*.mp3"), None)
        clip = build_video(title, overlay, script, broll, str(music) if music else None)
        out = RENDERS / f"{row['PublishTime_Pacific'].replace(' ','_')}_{title[:30]}.mp4"
        clip.write_videofile(str(out), fps=30, audio_codec="aac", codec="libx264", preset="medium")
        yt_id = upload_scheduled(ytc, out, title, script, tags, publish_iso, link)
        print("Uploaded:", yt_id)

if __name__ == "__main__":
    main()
