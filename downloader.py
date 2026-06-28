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
        exists = os.path.exists(COOKIES_PATH)
        size = os.path.getsize(COOKIES_PATH) if exists else 0
        print(f"[cookies] path={COOKIES_PATH} exists={exists} size={size}", flush=True)
        if exists and size > 50:
            return ["--cookies", COOKIES_PATH]
        return []

    def _run_ytdlp(self, args: list, timeout: int = 60) -> Tuple[bool, str, str]:
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + args
        print(f"[yt-dlp cmd] {' '.join(cmd[-5:])}", flush=True)
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

    def _run_download(self, cmd: list, temp_dir: str) -> Optional[str]:
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            _, stderr = proc.communicate(timeout=self.timeout)
            if proc.returncode != 0:
                print(f"[yt-dlp dl error] rc={proc.returncode}", flush=True)
                if stderr:
                    for line in stderr.strip().split("\n")[-5:]:
                        print(f"  {line}", flush=True)
                return None
            for f in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, f)
                if os.path.isfile(fp):
                    size = os.path.getsize(fp)
                    print(f"[yt-dlp] success: {f} ({size} bytes)", flush=True)
                    return fp
            print("[yt-dlp] no output file in temp dir", flush=True)
            return None
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            print("[yt-dlp] download timed out", flush=True)
            return None
        except Exception as e:
            if proc:
                proc.kill()
            print(f"[yt-dlp] download error: {e}", flush=True)
            return None

    def _run_spotdl(self, url: str, output_dir: str) -> Tuple[bool, str, str]:
        cmd = [
            sys.executable, "-m", "spotdl",
            "download", url,
            "--output", output_dir,
            "--format", "mp3",
        ]
        print(f"[spotdl] running: {url}", flush=True)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            if result.returncode != 0:
                print(f"[spotdl error] rc={result.returncode}", flush=True)
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-5:]:
                        print(f"  {line}", flush=True)
            return result.returncode == 0, result.stdout, result.stderr
        except FileNotFoundError:
            print("[spotdl] not installed", flush=True)
            return False, "", "spotdl not installed"
        except subprocess.TimeoutExpired:
            print("[spotdl] timed out", flush=True)
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
                print(f"[spotdl info error] {result.stderr[:500]}", flush=True)
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
        except FileNotFoundError:
            print("[spotdl] not installed", flush=True)
            return None
        except Exception as e:
            print(f"[spotify info error] {e}", flush=True)
            return None

    def download_spotify_to_file(self, url: str) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        print(f"[spotdl] downloading: {url}", flush=True)
        ok, stdout, stderr = self._run_spotdl(url, temp_dir)

        if ok:
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    if f.endswith(('.mp3', '.m4a', '.opus', '.wav', '.flac')):
                        fp = os.path.join(root, f)
                        size = os.path.getsize(fp)
                        print(f"[spotdl] success: {f} ({size} bytes)", flush=True)
                        return fp

        print("[spotdl] failed, trying yt-dlp fallback", flush=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return self._download_spotify_ytdlp_fallback(url)

    def _download_spotify_ytdlp_fallback(self, url: str) -> Optional[str]:
        print(f"[yt-dlp spotify] fallback for: {url}", flush=True)
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--no-playlist",
            "--no-progress",
        ] + YTDLP_COMMON_ARGS + [url]
        result = self._run_download(cmd, temp_dir)
        if result:
            return result
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def download_soundcloud_to_file(self, url: str) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            "--no-playlist",
        ] + YTDLP_COMMON_ARGS + [url]
        print("[yt-dlp] downloading soundcloud", flush=True)
        result = self._run_download(cmd, temp_dir)
        if result:
            return result
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def get_video_info(self, url: str) -> Optional[dict]:
        ok, stdout, stderr = self._run_ytdlp([
            "--no-download",
            "--print-json",
            "--no-playlist",
            "--ignore-errors",
        ] + YTDLP_COMMON_ARGS + [url], timeout=90)

        if not ok or not stdout.strip():
            print(f"[yt-dlp info error] {stderr[:500]}", flush=True)
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
        heights = set()
        for fmt in formats:
            if fmt.get("vcodec") == "none":
                continue
            h = fmt.get("height")
            if h:
                heights.add(h)

        if not heights:
            return [{"label": "Best", "format_selector": "best", "height": 0, "filesize": 0}]

        options = []
        for h in sorted(heights, reverse=True):
            filesize = 0
            for fmt in formats:
                if fmt.get("height") == h and fmt.get("vcodec") != "none":
                    fs = fmt.get("filesize") or fmt.get("filesize_approx") or 0
                    if not fs and duration:
                        tbr = fmt.get("tbr") or 0
                        if tbr:
                            fs = int(tbr * 1000 / 8 * duration)
                    if fs > filesize:
                        filesize = fs
                    break
            options.append({
                "label": f"{h}p",
                "format_selector": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best",
                "height": h,
                "filesize": filesize,
            })

        return options[:8]

    def download_video_to_file(self, url: str, format_selector: str) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-progress",
        ] + YTDLP_COMMON_ARGS + [url]
        print(f"[yt-dlp] downloading: {format_selector}", flush=True)
        result = self._run_download(cmd, temp_dir)
        if result:
            return result

        print("[yt-dlp] format failed, trying best fallback", flush=True)
        fallback_dir = tempfile.mkdtemp()
        fallback_template = os.path.join(fallback_dir, "%(title).80s.%(ext)s")
        fallback_cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", "best",
            "--merge-output-format", "mp4",
            "-o", fallback_template,
            "--no-playlist",
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-progress",
        ] + YTDLP_COMMON_ARGS + [url]
        result = self._run_download(fallback_cmd, fallback_dir)
        if result:
            return result

        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def cleanup(self, file_path: str):
        if file_path and os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            shutil.rmtree(parent_dir, ignore_errors=True)
