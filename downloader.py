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

    def _run_ytdlp(self, args: list, timeout: int = 60, use_cookies: bool = True) -> Tuple[bool, str, str]:
        cookie_args = self._get_cookies_args() if use_cookies else []
        cmd = [sys.executable, "-m", "yt_dlp"] + cookie_args + args
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
                print(f"[yt-dlp stream error] rc={proc.returncode} {stderr[:200]}", flush=True)
                return None
            buf = io.BytesIO(data)
            buf.seek(0)
            return buf
        except (subprocess.TimeoutExpired, Exception):
            if proc:
                proc.kill()
            return None

    def download_video_to_file(self, url: str, format_id: str, has_audio: bool = True) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")

        if has_audio:
            fmt_str = format_id
        else:
            fmt_str = f"{format_id}+bestaudio/{format_id}"

        cmd = [sys.executable, "-m", "yt_dlp"] + self._get_cookies_args() + [
            "-f", fmt_str,
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
            "--socket-timeout", "15",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-progress",
        ] + [a for a in YTDLP_COMMON_ARGS if a not in ("--no-warnings",)] + [url]
        print(f"[yt-dlp] downloading: {fmt_str}", flush=True)
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            stderr_lines = []
            for line in proc.stderr:
                stripped = line.strip()
                if stripped:
                    stderr_lines.append(stripped)
                    if len(stderr_lines) > 50:
                        stderr_lines = stderr_lines[-50:]
            proc.wait(timeout=self.timeout)
            if proc.returncode != 0:
                print(f"[yt-dlp file error] rc={proc.returncode}", flush=True)
                for line in stderr_lines[-10:]:
                    print(f"  {line}", flush=True)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None
            for f in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, f)
                if os.path.isfile(fp):
                    size = os.path.getsize(fp)
                    print(f"[yt-dlp] success: {f} ({size} bytes)", flush=True)
                    return fp
            print("[yt-dlp] no output file found in temp dir", flush=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            print("[yt-dlp] download timed out", flush=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        except Exception as e:
            if proc:
                proc.kill()
            print(f"[yt-dlp] download error: {e}", flush=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
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
        ] + [a for a in YTDLP_COMMON_ARGS if a != "--no-warnings"] + [url], timeout=90, use_cookies=False)

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
        best_by_height = {}
        for fmt in formats:
            if fmt.get("vcodec") == "none":
                continue
            height = fmt.get("height")
            if not height:
                continue

            acodec = fmt.get("acodec")
            has_audio = bool(acodec and acodec != "none")
            protocol = fmt.get("protocol", "")
            is_direct = protocol in ("https", "http")

            quality_label = f"{height}p"

            filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            if not filesize and duration:
                tbr = fmt.get("tbr") or 0
                vbr = fmt.get("vbr") or 0
                abr = fmt.get("abr") or 0
                bitrate = tbr or (vbr + abr)
                if bitrate:
                    filesize = int(bitrate * 1000 / 8 * duration)

            if quality_label not in best_by_height:
                best_by_height[quality_label] = {
                    "label": quality_label,
                    "format_id": fmt["format_id"],
                    "height": height,
                    "filesize": filesize,
                    "ext": fmt.get("ext", "mp4"),
                    "has_audio": has_audio,
                    "is_direct": is_direct,
                }
            else:
                existing = best_by_height[quality_label]
                prefer_direct = is_direct and not existing["is_direct"]
                prefer_audio = has_audio and not existing["has_audio"]
                if prefer_direct or prefer_audio:
                    best_by_height[quality_label] = {
                        "label": quality_label,
                        "format_id": fmt["format_id"],
                        "height": height,
                        "filesize": filesize or existing["filesize"],
                        "ext": fmt.get("ext", "mp4"),
                        "has_audio": has_audio,
                        "is_direct": is_direct,
                    }
                elif filesize and filesize > existing["filesize"]:
                    best_by_height[quality_label]["filesize"] = filesize

        options = sorted(best_by_height.values(), key=lambda x: x["height"], reverse=True)

        if not options:
            for fmt in formats:
                if fmt.get("format_id") and fmt.get("vcodec") != "none":
                    filesize = fmt.get("filesize") or 0
                    if not filesize and duration:
                        tbr = fmt.get("tbr") or 0
                        if tbr:
                            filesize = int(tbr * 1000 / 8 * duration)
                    acodec = fmt.get("acodec")
                    has_audio = acodec and acodec != "none"
                    options.append({
                        "label": "Best Available",
                        "format_id": fmt["format_id"],
                        "height": 0,
                        "filesize": filesize,
                        "ext": fmt.get("ext", "mp4"),
                        "has_audio": has_audio,
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
        ] + YTDLP_COMMON_ARGS + [url], timeout=self.timeout)
        return stream

    def cleanup(self, file_path: str):
        if file_path and os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            shutil.rmtree(parent_dir, ignore_errors=True)
