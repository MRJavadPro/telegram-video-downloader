import io
import os
import re
import json
import sys
import subprocess
import tempfile
import shutil
from typing import Optional, Tuple
from urllib.parse import urlparse


YTDLP_COMMON_ARGS = [
    "--no-warnings",
    "--no-check-certificates",
    "--extractor-retries", "5",
    "--legacy-server-connect",
    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "--add-header", "Accept-Language:en-US,en;q=0.9",
]

COOKIES_PATH = os.getenv("COOKIES_PATH", "/tmp/cookies.txt")


def is_spotify_url(url: str) -> bool:
    return bool(re.match(r'https?://open\.spotify\.com/(track|album|playlist)/[\w]+', url))


def is_soundcloud_url(url: str) -> bool:
    return bool(re.match(r'https?://(?:www\.|on\.)?soundcloud\.com/[\w\-]+', url))


class VideoDownloader:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def is_valid_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def _get_cookies_args(self) -> list:
        if os.path.exists(COOKIES_PATH):
            return ["--cookies", COOKIES_PATH]
        return []

    def _run_ytdlp(self, args: list, timeout: int = 60) -> Tuple[bool, str, str]:
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Timeout"

    def _run_ytdlp_stream(self, args: list, timeout: int = 300) -> Optional[io.BytesIO]:
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + args
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            data, stderr = proc.communicate(timeout=timeout)
            if proc.returncode != 0 or not data:
                return None
            buf = io.BytesIO(data)
            buf.seek(0)
            return buf
        except (subprocess.TimeoutExpired, Exception):
            if proc:
                proc.kill()
            return None

    def _run_spotdl(self, url: str, output_dir: str) -> Tuple[bool, str, str]:
        cmd = [
            sys.executable, "-m", "spotdl",
            "download", url,
            "--output", output_dir,
            "--format", "mp3",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Timeout"

    def get_spotify_info(self, url: str) -> Optional[dict]:
        cmd = [
            sys.executable, "-m", "spotdl",
            "save", url,
            "--format", "json",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                print(f"[spotdl error] {result.stderr[:500]}", flush=True)
                return None

            output = result.stdout.strip()
            if not output:
                return None

            tracks = json.loads(output)
            if not tracks:
                return None

            track = tracks[0] if isinstance(tracks, list) else tracks
            return {
                "title": track.get("name", "Unknown"),
                "artist": track.get("artist", "Unknown"),
                "album": track.get("album_name", "Unknown"),
                "duration": track.get("duration", 0),
                "thumbnail": track.get("cover_url", ""),
                "url": url,
                "is_spotify": True,
            }
        except Exception as e:
            print(f"[spotify error] {e}", flush=True)
            return None

    def download_spotify(self, url: str) -> Optional[io.BytesIO]:
        temp_dir = tempfile.mkdtemp()
        ok, stdout, stderr = self._run_spotdl(url, temp_dir)

        if not ok:
            print(f"[spotdl error] {stderr[:500]}", flush=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                if f.endswith(('.mp3', '.m4a', '.opus', '.wav', '.flac')):
                    file_path = os.path.join(root, f)
                    with open(file_path, "rb") as fp:
                        data = fp.read()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    buf = io.BytesIO(data)
                    buf.seek(0)
                    return buf

        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def get_video_info(self, url: str) -> Optional[dict]:
        ok, stdout, stderr = self._run_ytdlp([
            "--no-download",
            "--print-json",
            "--no-playlist",
            "--ignore-errors",
            "--no-warnings",
        ] + [a for a in YTDLP_COMMON_ARGS if a != "--no-warnings"] + [url], timeout=90)

        if not ok:
            print(f"[yt-dlp error] {stderr[:500]}", flush=True)
            return None

        try:
            info = json.loads(stdout)
            return {
                "title": info.get("title", "Unknown"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "view_count": info.get("view_count", 0),
                "uploader": info.get("uploader", "Unknown"),
                "formats": info.get("formats", []),
                "url": url
            }
        except (json.JSONDecodeError, Exception) as e:
            print(f"[parse error] {e}", flush=True)
            return None

    def get_quality_options(self, formats: list, duration: int = 0) -> list:
        seen_qualities = {}
        for fmt in formats:
            if fmt.get("vcodec") == "none":
                continue
            height = fmt.get("height")
            if not height:
                continue
            quality_label = f"{height}p"
            if quality_label not in seen_qualities:
                filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
                if not filesize and duration:
                    tbr = fmt.get("tbr") or 0
                    vbr = fmt.get("vbr") or 0
                    abr = fmt.get("abr") or 0
                    bitrate = tbr or (vbr + abr)
                    if bitrate:
                        filesize = int(bitrate * 1000 / 8 * duration)
                seen_qualities[quality_label] = {
                    "label": quality_label,
                    "format_id": fmt["format_id"],
                    "height": height,
                    "filesize": filesize,
                    "ext": fmt.get("ext", "mp4"),
                }

        options = sorted(seen_qualities.values(), key=lambda x: x["height"], reverse=True)

        if not options:
            for fmt in formats:
                if fmt.get("format_id") and fmt.get("vcodec") != "none":
                    filesize = fmt.get("filesize") or 0
                    if not filesize and duration:
                        tbr = fmt.get("tbr") or 0
                        if tbr:
                            filesize = int(tbr * 1000 / 8 * duration)
                    options.append({
                        "label": "Best Available",
                        "format_id": fmt["format_id"],
                        "height": 0,
                        "filesize": filesize,
                        "ext": fmt.get("ext", "mp4"),
                    })
                    break

        return options[:8]

    def download_soundcloud(self, url: str) -> Optional[io.BytesIO]:
        stream = self._run_ytdlp_stream([
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", "-",
            "--no-playlist",
        ] + YTDLP_COMMON_ARGS + [url], timeout=self.timeout)
        return stream

    def download_video(self, url: str, format_id: str) -> Optional[io.BytesIO]:
        stream = self._run_ytdlp_stream([
            "-f", f"{format_id}+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", "-",
            "--no-playlist",
            "--socket-timeout", "15",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--http-chunk-size", "1048576",
            "--buffer-size", "16K",
        ] + YTDLP_COMMON_ARGS + [url], timeout=self.timeout)

        return stream

    def cleanup(self, file_path: str):
        if file_path and os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            shutil.rmtree(parent_dir, ignore_errors=True)
