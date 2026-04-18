from __future__ import annotations

import re
import subprocess


_YOUTUBE_RE = re.compile(
    r"^(https?://)?((www|m)\.)?(youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_RE.match(url.strip()))


def resolve_video_source(url_or_path: str) -> str:
    """
    - Yerel dosya yolu -> aynı döner
    - Doğrudan stream URL (m3u8/http) -> aynı döner
    - YouTube URL -> yt-dlp ile oynatılabilir (genelde m3u8) URL'e çevirir
    """
    s = (url_or_path or "").strip()
    if not s:
        raise ValueError("Boş kaynak")

    if not is_youtube_url(s):
        return s

    try:
        proc = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "--quiet",
                "-f",
                "best[protocol^=m3u8]/best",
                "-g",
                s,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:  # pragma: no cover
        raise RuntimeError("yt-dlp bulunamadı. `pip install -e .[youtube]`") from e
    except subprocess.CalledProcessError as e:  # pragma: no cover
        msg = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(f"yt-dlp kaynak çözümleyemedi: {msg or 'unknown error'}") from e

    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("yt-dlp boş çıktı döndü")
    # Bazı formatlarda video+audio iki satır gelebilir; OpenCV/Ultralytics genelde video URL'i ile çalışır.
    return lines[0]
