import os
import sys
import subprocess
import tempfile
import shutil
import re
import json
from pathlib import Path

import httpx


TEMP_DIR = tempfile.gettempdir()


def _is_youtube(url: str) -> bool:
    return bool(re.search(r'(youtube\.com|youtu\.be|music\.youtube\.com)', url))


def _is_soundcloud(url: str) -> bool:
    return bool(re.search(r'soundcloud\.com', url))


def _is_spotify(url: str) -> bool:
    return bool(re.search(r'spotify\.com', url))


def _is_instagram(url: str) -> bool:
    return bool(re.search(r'(instagram\.com|instagr\.am)', url))


def _is_pinterest(url: str) -> bool:
    return bool(re.search(r'(pinterest\.com|pin\.it)', url))


def detect_platform(url: str) -> str:
    if _is_youtube(url):
        return "youtube"
    if _is_spotify(url):
        return "spotify"
    if _is_instagram(url):
        return "instagram"
    if _is_soundcloud(url):
        return "soundcloud"
    if _is_pinterest(url):
        return "pinterest"
    return "unknown"


def get_info(url: str, cookies_file: str = None) -> dict:
    platform = detect_platform(url)

    if platform == "spotify":
        return _get_spotify_info(url)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-download",
        "--print-json",
        "--no-warnings",
        "--no-playlist",
        "-f", "best",
    ]

    if cookies_file:
        cmd += ["--cookies", cookies_file]

    cmd.append(url)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise Exception(result.stderr.strip() or "Failed to get info")

    info = json.loads(result.stdout)
    return {
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "filesize": info.get("filesize") or info.get("filesize_approx"),
        "platform": platform,
        "url": url,
    }


def _get_spotify_info(url: str) -> dict:
    try:
        result = subprocess.run(
            ["python", "-m", "spotdl", "save", url, "--output", "{title} - {artist}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        title = "Spotify Track"
        if result.stdout:
            lines = result.stdout.strip().split("\n")
            for line in reversed(lines):
                if line.strip():
                    title = line.strip()
                    break
        return {
            "title": title,
            "duration": None,
            "thumbnail": None,
            "filesize": None,
            "platform": "spotify",
            "url": url,
        }
    except Exception:
        return {
            "title": "Spotify Track",
            "duration": None,
            "thumbnail": None,
            "filesize": None,
            "platform": "spotify",
            "url": url,
        }


def download(url: str, cookies_file: str = None, max_height: int = 1080) -> tuple[str, str]:
    platform = detect_platform(url)
    outtmpl = os.path.join(TEMP_DIR, "%(id)s.%(ext)s")

    if platform == "spotify":
        return _download_spotify(url)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "--no-progress",
        "-o", outtmpl,
    ]

    if cookies_file and os.path.isfile(cookies_file):
        cmd += ["--cookies", cookies_file]

    if platform == "youtube":
        cmd += [
            "--extractor-args", "youtube:player_client=ios,web,mweb",
            "-f", "bestvideo[height<=1080]+bestaudio/best",
            "--merge-output-format", "mp4",
        ]
    elif platform == "instagram":
        cmd += ["-f", "best"]
    elif platform == "pinterest":
        cmd += ["-f", "best"]
    elif platform == "soundcloud":
        cmd += ["-f", "bestaudio/best", "--audio-format", "mp3"]

    cmd.append(url)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise Exception(result.stderr.strip() or "Download failed")

    filepath = _find_downloaded_file(TEMP_DIR, url)
    if not filepath:
        raise Exception("Downloaded file not found")

    ext = Path(filepath).suffix.lower()
    if platform == "soundcloud":
        final_ext = ".mp3"
    elif platform in ("youtube", "instagram"):
        final_ext = ".mp4"
    else:
        final_ext = ext

    final_path = filepath.replace(ext, final_ext) if ext != final_ext else filepath
    if filepath != final_path:
        os.rename(filepath, final_path)

    return final_path, final_ext


def _download_spotify(url: str) -> tuple[str, str]:
    outdir = os.path.join(TEMP_DIR, f"spotify_{os.urandom(4).hex()}")
    os.makedirs(outdir, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable, "-m", "spotdl", "download", url,
            "--output", outdir,
            "--format", "mp3",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise Exception(result.stderr.strip() or "Spotify download failed")

    for f in os.listdir(outdir):
        if f.endswith((".mp3", ".m4a", ".opus")):
            return os.path.join(outdir, f), ".mp3"

    raise Exception("No audio file found after Spotify download")


def _find_downloaded_file(directory: str, url: str) -> str | None:
    files = sorted(
        Path(directory).iterdir(),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for f in files:
        if f.is_file() and f.suffix in (
            ".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus",
            ".wav", ".flac", ".ogg",
        ):
            return str(f)
    return None
