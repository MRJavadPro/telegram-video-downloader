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
            print("[yt-dlp] no output file found in temp dir", flush=True)
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
                if result.stdout:
                    for line in result.stdout.strip().split("\n")[-3:]:
                        print(f"  out: {line}", flush=True)
            return result.returncode == 0, result.stdout, result.stderr
        except FileNotFoundError:
            print("[spotdl] command not found - spotdl not installed", flush=True)
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
            print("[spotdl] command not found", flush=True)
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
        print(f"[yt-dlp] downloading soundcloud", flush=True)
        result = self._run_download(cmd, temp_dir)
        if result:
            return result
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def get_video_info(self, url: str) -> Optional[dict]:
        is_yt = "youtube.com" in url or "youtu.be" in url
        extra_args = ["--extractor-args", "youtube:player_client=ios,web"] if is_yt else []
        ok, stdout, stderr = self._run_ytdlp([
            "--no-download",
            "--print-json",
            "--no-playlist",
            "--ignore-errors",
        ] + extra_args + YTDLP_COMMON_ARGS + [url], timeout=90)

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

    def download_video_to_file(self, url: str, format_id: str) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")
        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", f"{format_id}+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-progress",
            "--extractor-args", "youtube:player_client=ios,web",
        ] + YTDLP_COMMON_ARGS + [url]
        print(f"[yt-dlp] downloading format: {format_id}", flush=True)
        result = self._run_download(cmd, temp_dir)
        if result:
            return result

        print("[yt-dlp] specific format failed, trying best fallback", flush=True)
        fallback_dir = tempfile.mkdtemp()
        fallback_template = os.path.join(fallback_dir, "%(title).80s.%(ext)s")
        fallback_cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", fallback_template,
            "--no-playlist",
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-progress",
            "--extractor-args", "youtube:player_client=ios,web",
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
