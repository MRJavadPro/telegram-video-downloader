import io
import os
import re
import json
import sys
import subprocess
import tempfile
import shutil
from typing import Optional, Tuple


YTDLP_COMMON_ARGS = [
    "--no-warnings",
    "--no-check-certificates",
    "--extractor-retries", "3",
    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "--add-header", "Accept-Language:en-US,en;q=0.9",
]


class VideoDownloader:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def is_valid_url(self, url: str) -> bool:
        patterns = [
            r'https?://(?:www\.)?pornhub\.com/view_video\.php\?viewkey=[\w]+',
            r'https?://(?:www\.)?pornhub\.com/watch/[\w]+',
            r'https?://(?:www\.)?pornhub\.com/embed/[\w]+',
            r'https?://(?:www\.)?youtube\.com/watch\?v=[\w\-]+',
            r'https?://youtu\.be/[\w\-]+',
            r'https?://(?:www\.)?youtube\.com/shorts/[\w\-]+',
            r'https?://(?:www\.)?instagram\.com/reel/[\w\-]+',
            r'https?://(?:www\.)?instagram\.com/p/[\w\-]+',
            r'https?://(?:www\.)?tiktok\.com/@[\w.]+/video/\d+',
            r'https?://(?:vm|vt)\.tiktok\.com/[\w]+',
            r'https?://(?:www\.)?twitter\.com/\w+/status/\d+',
            r'https?://(?:www\.)?x\.com/\w+/status/\d+',
            r'https?://(?:www\.)?facebook\.com/.+/videos/\d+',
            r'https?://v\.redd\.it/[\w]+',
        ]
        return any(re.match(p, url) for p in patterns)

    def _run_ytdlp(self, args: list, timeout: int = 60) -> Tuple[bool, str, str]:
        cmd = [sys.executable, "-m", "yt_dlp"] + args
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
        cmd = [sys.executable, "-m", "yt_dlp"] + args
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            data = proc.stdout.read()
            proc.wait(timeout=timeout)
            if proc.returncode != 0 or not data:
                return None
            buf = io.BytesIO(data)
            buf.seek(0)
            return buf
        except (subprocess.TimeoutExpired, Exception):
            if proc:
                proc.kill()
            return None

    def get_video_info(self, url: str) -> Optional[dict]:
        ok, stdout, _ = self._run_ytdlp([
            "--no-download",
            "--print-json",
        ] + YTDLP_COMMON_ARGS + [url], timeout=60)

        if not ok:
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
        except (json.JSONDecodeError, Exception):
            return None

    def get_quality_options(self, formats: list) -> list:
        seen_qualities = {}
        for fmt in formats:
            if fmt.get("vcodec") == "none":
                continue
            height = fmt.get("height")
            if not height:
                continue
            quality_label = f"{height}p"
            if quality_label not in seen_qualities:
                seen_qualities[quality_label] = {
                    "label": quality_label,
                    "format_id": fmt["format_id"],
                    "height": height,
                    "filesize": fmt.get("filesize") or fmt.get("filesize_approx") or 0,
                    "ext": fmt.get("ext", "mp4"),
                }

        options = sorted(seen_qualities.values(), key=lambda x: x["height"], reverse=True)

        if not options:
            for fmt in formats:
                if fmt.get("format_id") and fmt.get("vcodec") != "none":
                    options.append({
                        "label": "Best Available",
                        "format_id": fmt["format_id"],
                        "height": 0,
                        "filesize": fmt.get("filesize") or 0,
                        "ext": fmt.get("ext", "mp4"),
                    })
                    break

        return options[:8]

    def download_video(self, url: str, format_id: str) -> Optional[io.BytesIO]:
        stream = self._run_ytdlp_stream([
            "-f", f"{format_id}+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", "-",
            "--socket-timeout", "15",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--http-chunk-size", "1048576",
            "--buffer-size", "16K",
        ] + YTDLP_COMMON_ARGS + [url], timeout=self.timeout)

        return stream

    def download_video_to_temp(self, url: str, format_id: str) -> Optional[str]:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "%(title).80s.%(ext)s")

        ok, _, _ = self._run_ytdlp([
            "-f", f"{format_id}+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--socket-timeout", "15",
            "--retries", "5",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--http-chunk-size", "1048576",
            "--buffer-size", "16K",
        ] + YTDLP_COMMON_ARGS + [url], timeout=self.timeout)

        if not ok:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                return file_path

        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    def cleanup(self, file_path: str):
        if file_path and os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            shutil.rmtree(parent_dir, ignore_errors=True)
