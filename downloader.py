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

    if platform == "pinterest":
        return _get_pinterest_info(url)

    if platform == "instagram":
        try:
            return _get_instagram_info(url, cookies_file)
        except Exception:
            pass

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


def _get_instagram_info(url: str, cookies_file: str = None) -> dict:
    cookies_dict = {}
    if cookies_file and os.path.isfile(cookies_file):
        with open(cookies_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7 and "instagram.com" in parts[0]:
                    cookies_dict[parts[5]] = parts[6]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    resp = httpx.get(url, headers=headers, cookies=cookies_dict, timeout=20, follow_redirects=True)
    html = resp.text

    vid_match = re.search(r'"video_url"\s*:\s*"([^"]+)"', html)
    vid_url = vid_match.group(1).replace("\\u002F", "/") if vid_match else None

    title_match = re.search(r'"accessibility_caption"\s*:\s*"([^"]*)"', html)
    title = title_match.group(1) if title_match else "Instagram Reel"

    img_match = re.search(r'"display_url"\s*:\s*"([^"]+)"', html)
    img_url = img_match.group(1).replace("\\u002F", "/") if img_match else None

    return {
        "title": title[:100] if title else "Instagram Reel",
        "duration": None,
        "thumbnail": img_url,
        "filesize": None,
        "platform": "instagram",
        "url": url,
        "_ig_video": vid_url,
        "_ig_image": img_url,
    }


def _download_instagram(url: str, cookies_file: str = None) -> tuple[str, str]:
    info = _get_instagram_info(url, cookies_file)
    vid_url = info.get("_ig_video")
    img_url = info.get("_ig_image")

    cookies_dict = {}
    if cookies_file and os.path.isfile(cookies_file):
        with open(cookies_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7 and "instagram.com" in parts[0]:
                    cookies_dict[parts[5]] = parts[6]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    if vid_url:
        resp = httpx.get(vid_url, headers=headers, cookies=cookies_dict, timeout=60, follow_redirects=True)
        filepath = os.path.join(TEMP_DIR, f"instagram_{os.urandom(4).hex()}.mp4")
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, ".mp4"

    if img_url:
        resp = httpx.get(img_url, headers=headers, cookies=cookies_dict, timeout=30, follow_redirects=True)
        filepath = os.path.join(TEMP_DIR, f"instagram_{os.urandom(4).hex()}.jpg")
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, ".jpg"

    raise Exception("No downloadable content found on Instagram")


def _resolve_pinterest_url(url: str) -> str:
    if "pin.it" in url:
        resp = httpx.get(url, follow_redirects=True, timeout=15)
        return str(resp.url)
    return url


def _get_pinterest_info(url: str) -> dict:
    url = _resolve_pinterest_url(url)
    resp = httpx.get(url, timeout=15, follow_redirects=True)
    match = re.search(r'<meta property="og:title" content="([^"]*)"', resp.text)
    title = match.group(1) if match else "Pinterest Pin"
    img_match = re.search(r'<meta property="og:image" content="([^"]*)"', resp.text)
    img_url = img_match.group(1) if img_match else None
    vid_match = re.search(r'"video_url"\s*:\s*"([^"]+)"', resp.text)
    vid_url = vid_match.group(1).replace("\\u002F", "/") if vid_match else None
    return {
        "title": title,
        "duration": None,
        "thumbnail": img_url,
        "filesize": None,
        "platform": "pinterest",
        "url": url,
        "_pinterest_video": vid_url,
        "_pinterest_image": img_url,
    }


def _download_pinterest(url: str) -> tuple[str, str]:
    url = _resolve_pinterest_url(url)
    info = _get_pinterest_info(url)
    vid_url = info.get("_pinterest_video")
    img_url = info.get("_pinterest_image")
    if vid_url:
        resp = httpx.get(vid_url, timeout=30, follow_redirects=True)
        filepath = os.path.join(TEMP_DIR, f"pinterest_{os.urandom(4).hex()}.mp4")
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, ".mp4"
    if img_url:
        resp = httpx.get(img_url, timeout=30, follow_redirects=True)
        filepath = os.path.join(TEMP_DIR, f"pinterest_{os.urandom(4).hex()}.jpg")
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, ".jpg"
    raise Exception("No downloadable content found on Pinterest")


def download(url: str, cookies_file: str = None, max_height: int = 1080) -> tuple[str, str]:
    platform = detect_platform(url)
    outtmpl = os.path.join(TEMP_DIR, "%(id)s.%(ext)s")

    if platform == "spotify":
        return _download_spotify(url)

    if platform == "pinterest":
        return _download_pinterest(url)

    if platform == "instagram":
        try:
            return _download_instagram(url, cookies_file)
        except Exception:
            pass

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
            "-f", "best",
            "--merge-output-format", "mp4",
        ]
    elif platform == "soundcloud":
        cmd += ["-f", "bestaudio/best", "--audio-format", "mp3"]
    else:
        cmd += ["-f", "best"]

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
            ".wav", ".flac", ".ogg", ".jpg", ".jpeg", ".png", ".webp",
        ):
            return str(f)
    return None
