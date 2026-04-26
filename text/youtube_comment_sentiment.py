from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from textblob import TextBlob


_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class CommentRow:
    comment_id: str
    parent_id: str | None
    author: str
    like_count: int
    published_at: str
    updated_at: str
    text: str
    polarity: float
    subjectivity: float
    label: str


@dataclass(frozen=True)
class ThemeRow:
    theme_id: int
    size: int
    top_terms: str
    representative_comment: str
    avg_polarity: float
    positive_ratio: float
    neutral_ratio: float
    negative_ratio: float


def _extract_video_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("url/id boş olamaz")

    if _VIDEO_ID_RE.fullmatch(s):
        return s

    parsed = urlparse(s)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if "youtu.be" in host:
        candidate = path.strip("/").split("/")[0]
        if _VIDEO_ID_RE.fullmatch(candidate):
            return candidate

    if "youtube.com" in host or "m.youtube.com" in host:
        qs = parse_qs(parsed.query or "")
        if "v" in qs and qs["v"]:
            candidate = qs["v"][0]
            if _VIDEO_ID_RE.fullmatch(candidate):
                return candidate

        parts = [p for p in path.split("/") if p]
        # /shorts/<id>, /live/<id>, /embed/<id>
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            candidate = parts[1]
            if _VIDEO_ID_RE.fullmatch(candidate):
                return candidate

    raise ValueError(f"video id çıkarılamadı: {url_or_id}")


def _label_from_polarity(p: float, *, pos_th: float = 0.1, neg_th: float = -0.1) -> str:
    if p >= pos_th:
        return "positive"
    if p <= neg_th:
        return "negative"
    return "neutral"


def _analyze_sentiment(text: str) -> tuple[float, float, str]:
    blob = TextBlob(text or "")
    s = blob.sentiment
    p = float(s.polarity)
    subj = float(s.subjectivity)
    return p, subj, _label_from_polarity(p)


def _yt_get_comment_threads(
    *,
    api_key: str,
    video_id: str,
    page_token: str | None,
    max_results: int,
) -> dict[str, Any]:
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "key": api_key,
        "part": "snippet,replies",
        "videoId": video_id,
        "maxResults": max_results,
        "textFormat": "plainText",
        "order": "time",
    }
    if page_token:
        params["pageToken"] = page_token

    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code >= 400:
        # Quota/permission hatalarında JSON body çok yardımcı oluyor.
        raise RuntimeError(f"YouTube API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _iso_from_epoch(ts: int | float | None) -> str:
    if ts is None:
        return ""
    try:
        return dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).isoformat()
    except Exception:
        return ""


def _ensure_full_url(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("url/id boş olamaz")
    if _VIDEO_ID_RE.fullmatch(s):
        return f"https://www.youtube.com/watch?v={s}"
    return s


def _parse_ytdlp_comments_file(path: str) -> list[dict[str, Any]]:
    raw = open(path, "r", encoding="utf-8").read().strip()
    if not raw:
        return []
    # yt-dlp bazı modlarda JSON array, bazı modlarda JSON lines yazabiliyor.
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        if isinstance(obj, dict) and "comments" in obj and isinstance(obj["comments"], list):
            return [x for x in obj["comments"] if isinstance(x, dict)]
    except Exception:
        pass

    out: list[dict[str, Any]] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _scrape_comments_ytdlp(
    *,
    url_or_id: str,
    max_comments: int,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> list[dict[str, Any]]:
    url = _ensure_full_url(url_or_id)
    maxc = "all" if not max_comments or max_comments <= 0 else str(int(max_comments))

    with tempfile.TemporaryDirectory(prefix="yt_comments_") as tmp:
        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--skip-download",
            "--no-playlist",
            "--write-info-json",
            "--write-comments",
            "--extractor-args",
            f"youtube:max_comments={maxc};comment_sort=new",
            "-P",
            tmp,
            "-o",
            "%(id)s.%(ext)s",
            url,
        ]
        if cookies:
            cmd.extend(["--cookies", cookies])
        if cookies_from_browser:
            cmd.extend(["--cookies-from-browser", cookies_from_browser])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise RuntimeError("yt-dlp bulunamadı. `pip install -r text/requirements.txt`") from e
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or "").strip()
            raise RuntimeError(f"yt-dlp scrape başarısız: {msg or 'unknown error'}") from e

        candidates = glob.glob(os.path.join(tmp, "*.comments.json"))
        if not candidates:
            candidates = glob.glob(os.path.join(tmp, "**", "*.comments.json"), recursive=True)
        if not candidates:
            # Bazı durumlarda yt-dlp yorumları ayrı dosyaya yazmayabilir; info json içinde olabilir.
            info_files = glob.glob(os.path.join(tmp, "*.info.json")) + glob.glob(
                os.path.join(tmp, "**", "*.info.json"), recursive=True
            )
            for info_path in sorted(set(info_files)):
                try:
                    info = json.loads(open(info_path, "r", encoding="utf-8").read())
                except Exception:
                    continue
                comments = info.get("comments")
                if isinstance(comments, list) and comments:
                    return [c for c in comments if isinstance(c, dict)]
            return []

        comments: list[dict[str, Any]] = []
        for p in sorted(candidates):
            comments.extend(_parse_ytdlp_comments_file(p))
        return comments


def fetch_and_analyze(
    *,
    api_key: str | None,
    url_or_id: str,
    max_comments: int,
    include_replies: bool,
    sleep_seconds: float = 0.0,
    scrape_cookies: str | None = None,
    scrape_cookies_from_browser: str | None = None,
) -> list[CommentRow]:
    out: list[CommentRow] = []

    # API key varsa: YouTube Data API v3 kullan (opsiyonel).
    if api_key:
        video_id = _extract_video_id(url_or_id)
        page_token: str | None = None

        while True:
            if max_comments and len(out) >= max_comments:
                break

            chunk_limit = min(100, max(1, max_comments - len(out))) if max_comments else 100
            data = _yt_get_comment_threads(
                api_key=api_key,
                video_id=video_id,
                page_token=page_token,
                max_results=chunk_limit,
            )

            for item in data.get("items", []) or []:
                sn = (item.get("snippet") or {}).get("topLevelComment", {}).get("snippet") or {}
                top_comment = (item.get("snippet") or {}).get("topLevelComment") or {}
                comment_id = str(top_comment.get("id") or "")
                text = str(sn.get("textOriginal") or "")

                p, subj, label = _analyze_sentiment(text)
                out.append(
                    CommentRow(
                        comment_id=comment_id,
                        parent_id=None,
                        author=str(sn.get("authorDisplayName") or ""),
                        like_count=int(sn.get("likeCount") or 0),
                        published_at=str(sn.get("publishedAt") or ""),
                        updated_at=str(sn.get("updatedAt") or ""),
                        text=text,
                        polarity=p,
                        subjectivity=subj,
                        label=label,
                    )
                )
                if max_comments and len(out) >= max_comments:
                    break

                if include_replies:
                    replies = (item.get("replies") or {}).get("comments") or []
                    for rep in replies:
                        rep_sn = (rep.get("snippet") or {})
                        rep_id = str(rep.get("id") or "")
                        rep_text = str(rep_sn.get("textOriginal") or "")
                        rp, rsubj, rlabel = _analyze_sentiment(rep_text)
                        out.append(
                            CommentRow(
                                comment_id=rep_id,
                                parent_id=comment_id or None,
                                author=str(rep_sn.get("authorDisplayName") or ""),
                                like_count=int(rep_sn.get("likeCount") or 0),
                                published_at=str(rep_sn.get("publishedAt") or ""),
                                updated_at=str(rep_sn.get("updatedAt") or ""),
                                text=rep_text,
                                polarity=rp,
                                subjectivity=rsubj,
                                label=rlabel,
                            )
                        )
                        if max_comments and len(out) >= max_comments:
                            break

            page_token = data.get("nextPageToken")
            if not page_token:
                break
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        return out

    # API key yoksa: yt-dlp ile scrape et.
    scraped = _scrape_comments_ytdlp(
        url_or_id=url_or_id,
        max_comments=max_comments,
        cookies=scrape_cookies,
        cookies_from_browser=scrape_cookies_from_browser,
    )
    for c in scraped:
        text = str(c.get("text") or c.get("text_original") or c.get("textOriginal") or "")
        if not text:
            continue
        p, subj, label = _analyze_sentiment(text)
        out.append(
            CommentRow(
                comment_id=str(c.get("id") or ""),
                parent_id=str(c.get("parent") or c.get("parent_id") or "") or None,
                author=str(c.get("author") or c.get("author_display_name") or ""),
                like_count=int(c.get("like_count") or c.get("likeCount") or 0),
                published_at=_iso_from_epoch(c.get("timestamp")),
                updated_at="",
                text=text,
                polarity=p,
                subjectivity=subj,
                label=label,
            )
        )
        if max_comments and len(out) >= max_comments:
            break

    return out


def write_csv(rows: list[CommentRow], out_path: str) -> None:
    fields = [
        "comment_id",
        "parent_id",
        "author",
        "like_count",
        "published_at",
        "updated_at",
        "text",
        "polarity",
        "subjectivity",
        "label",
    ]
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "comment_id": r.comment_id,
                    "parent_id": r.parent_id or "",
                    "author": r.author,
                    "like_count": r.like_count,
                    "published_at": r.published_at,
                    "updated_at": r.updated_at,
                    "text": r.text,
                    "polarity": f"{r.polarity:.6f}",
                    "subjectivity": f"{r.subjectivity:.6f}",
                    "label": r.label,
                }
            )


def _truncate(s: str, n: int = 240) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"


def semantic_theme_extraction(
    rows: list[CommentRow],
    *,
    n_themes: int = 5,
    top_terms: int = 8,
    max_features: int = 5000,
) -> list[ThemeRow]:
    """
    Semantic (extractive) özet:
    - TF-IDF ile vektörleştir
    - KMeans ile temalara ayır
    - Her tema için: anahtar terimler + temayı temsil eden yorum
    """
    if not rows:
        return []

    try:
        import numpy as np  # type: ignore
        from sklearn.cluster import KMeans  # type: ignore
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("scikit-learn yüklü değil. `pip install -r text/requirements.txt`") from e

    filtered_rows = [r for r in rows if (r.text or "").strip()]
    texts = [r.text for r in filtered_rows]
    if not filtered_rows:
        return []

    k = max(1, min(int(n_themes or 1), len(filtered_rows)))

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=int(max_features),
        ngram_range=(1, 2),
        min_df=2 if len(texts) >= 30 else 1,
    )
    x = vectorizer.fit_transform(texts)
    if x.shape[0] == 0 or x.shape[1] == 0:
        return []

    model = KMeans(n_clusters=k, n_init="auto", random_state=42)
    labels = model.fit_predict(x)
    centers = model.cluster_centers_
    feature_names = vectorizer.get_feature_names_out()

    out: list[ThemeRow] = []
    for theme_id in range(k):
        idxs = np.where(labels == theme_id)[0].tolist()
        if not idxs:
            continue

        c = centers[theme_id]
        top_idx = np.argsort(c)[::-1][: int(top_terms)]
        terms = [str(feature_names[i]) for i in top_idx if c[i] > 0]
        terms_str = ";".join(terms)

        sub = x[idxs]
        # sparse.dot(dense_vector) -> numpy array
        scores = np.asarray(sub.dot(c)).reshape(-1)
        rep_local = int(np.argmax(scores))
        rep_i = idxs[rep_local]

        sub_rows = [filtered_rows[i] for i in idxs if i < len(filtered_rows)]
        denom = max(len(sub_rows), 1)
        avg_pol = sum(r.polarity for r in sub_rows) / denom
        pos = sum(1 for r in sub_rows if r.label == "positive")
        neu = sum(1 for r in sub_rows if r.label == "neutral")
        neg = sum(1 for r in sub_rows if r.label == "negative")

        out.append(
            ThemeRow(
                theme_id=theme_id,
                size=len(sub_rows),
                top_terms=terms_str,
                representative_comment=_truncate(texts[rep_i], 400),
                avg_polarity=float(avg_pol),
                positive_ratio=pos / denom,
                neutral_ratio=neu / denom,
                negative_ratio=neg / denom,
            )
        )

    out.sort(key=lambda r: r.size, reverse=True)
    return out


def write_themes_csv(*, themes: list[ThemeRow], out_path: str) -> None:
    fields = [
        "theme_id",
        "size",
        "top_terms",
        "representative_comment",
        "avg_polarity",
        "positive_ratio",
        "neutral_ratio",
        "negative_ratio",
    ]
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in themes:
            w.writerow(
                {
                    "theme_id": t.theme_id,
                    "size": t.size,
                    "top_terms": t.top_terms,
                    "representative_comment": t.representative_comment,
                    "avg_polarity": f"{t.avg_polarity:.6f}",
                    "positive_ratio": f"{t.positive_ratio:.6f}",
                    "neutral_ratio": f"{t.neutral_ratio:.6f}",
                    "negative_ratio": f"{t.negative_ratio:.6f}",
                }
            )


def sumy_summarize(
    rows: list[CommentRow],
    *,
    sentences: int = 5,
    language: str = "english",
    max_chars: int = 120_000,
) -> str:
    """
    Sumy ile (LSA) extractive özet:
    - Tüm yorumları tek bir doküman gibi birleştirir.
    - Çok uzun metinleri `max_chars` ile sınırlar.
    """
    texts = [r.text.strip() for r in rows if (r.text or "").strip()]
    if not texts:
        return ""

    document_text = "\n".join(texts)
    if len(document_text) > max_chars:
        document_text = document_text[:max_chars]

    try:
        from sumy.nlp.tokenizers import Tokenizer  # type: ignore
        from sumy.parsers.plaintext import PlaintextParser  # type: ignore
        from sumy.summarizers.lsa import LsaSummarizer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("sumy yüklü değil. `pip install -r text/requirements.txt`") from e

    def _run() -> str:
        parser = PlaintextParser.from_string(document_text, Tokenizer(language))
        summarizer = LsaSummarizer()
        out = [str(s) for s in summarizer(parser.document, sentences)]
        return " ".join(out).strip()

    try:
        return _run()
    except LookupError as e:
        # NLTK tokenizer datası sürüme göre değişebiliyor (punkt / punkt_tab).
        try:
            import nltk  # type: ignore

            nltk.download("punkt", quiet=True)
            nltk.download("punkt_tab", quiet=True)
            return _run()
        except Exception:
            raise RuntimeError(
                "NLTK data eksik görünüyor (punkt/punkt_tab).\n"
                "Çözüm:\n"
                "- `python -m nltk.downloader punkt`\n"
                "- `python -m nltk.downloader punkt_tab`"
            ) from e


def sumy_summarize_text(
    text: str,
    *,
    sentences: int = 1,
    language: str = "english",
    max_chars: int = 8_000,
) -> str:
    """
    Tek bir metni Sumy (LSA) ile extractive özetler.
    Kısa yorumlarda genelde aynı cümleyi döndürür; bu durumda kırpma uygularız.
    """
    s = (text or "").strip()
    if not s:
        return ""
    if len(s) > max_chars:
        s = s[:max_chars]

    try:
        from sumy.nlp.tokenizers import Tokenizer  # type: ignore
        from sumy.parsers.plaintext import PlaintextParser  # type: ignore
        from sumy.summarizers.lsa import LsaSummarizer  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("sumy yüklü değil. `pip install -r text/requirements.txt`") from e

    def _run() -> str:
        parser = PlaintextParser.from_string(s, Tokenizer(language))
        summarizer = LsaSummarizer()
        out = [str(x) for x in summarizer(parser.document, max(1, int(sentences or 1)))]
        return " ".join(out).strip()

    try:
        summarized = _run()
    except LookupError:
        import nltk  # type: ignore

        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
        summarized = _run()

    summarized = summarized.strip()
    if not summarized:
        return _truncate(s, 240)
    return _truncate(summarized, 240)


def write_per_comment_summary_csv(
    *,
    rows: list[CommentRow],
    out_path: str,
    limit: int = 10,
    sentences: int = 1,
    language: str = "english",
) -> None:
    fields = ["comment_id", "label", "polarity", "summary_sentence", "original_text"]
    subset = rows[: max(0, int(limit or 0))] if limit else rows
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in subset:
            summ = sumy_summarize_text(r.text, sentences=sentences, language=language)
            w.writerow(
                {
                    "comment_id": r.comment_id,
                    "label": r.label,
                    "polarity": f"{r.polarity:.6f}",
                    "summary_sentence": summ,
                    "original_text": _truncate(r.text, 500),
                }
            )


def write_sumy_summary_csv(*, summary_text: str, out_path: str, sentences: int) -> None:
    fields = ["sentences", "summary"]
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({"sentences": int(sentences), "summary": summary_text})


def build_summary(rows: list[CommentRow]) -> dict[str, Any]:
    if not rows:
        return {
            "comment_count": 0,
            "avg_polarity": 0.0,
            "avg_subjectivity": 0.0,
            "positive_count": 0,
            "neutral_count": 0,
            "negative_count": 0,
            "positive_ratio": 0.0,
            "neutral_ratio": 0.0,
            "negative_ratio": 0.0,
            "top_positive_example": "",
            "top_negative_example": "",
        }

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    pol_sum = 0.0
    subj_sum = 0.0
    for r in rows:
        counts[r.label] = counts.get(r.label, 0) + 1
        pol_sum += r.polarity
        subj_sum += r.subjectivity

    n = len(rows)
    top_pos = max(rows, key=lambda r: r.polarity)
    top_neg = min(rows, key=lambda r: r.polarity)

    return {
        "comment_count": n,
        "avg_polarity": pol_sum / n,
        "avg_subjectivity": subj_sum / n,
        "positive_count": counts["positive"],
        "neutral_count": counts["neutral"],
        "negative_count": counts["negative"],
        "positive_ratio": counts["positive"] / n,
        "neutral_ratio": counts["neutral"] / n,
        "negative_ratio": counts["negative"] / n,
        "top_positive_example": _truncate(top_pos.text),
        "top_negative_example": _truncate(top_neg.text),
    }


def write_summary_csv(*, summary: dict[str, Any], out_path: str) -> None:
    fields = [
        "comment_count",
        "avg_polarity",
        "avg_subjectivity",
        "positive_count",
        "neutral_count",
        "negative_count",
        "positive_ratio",
        "neutral_ratio",
        "negative_ratio",
        "top_positive_example",
        "top_negative_example",
    ]
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        row = dict(summary)
        for k in ("avg_polarity", "avg_subjectivity", "positive_ratio", "neutral_ratio", "negative_ratio"):
            if k in row and isinstance(row[k], (float, int)):
                row[k] = f"{float(row[k]):.6f}"
        w.writerow({k: row.get(k, "") for k in fields})


def print_summary(rows: list[CommentRow]) -> None:
    if not rows:
        print("0 comment")
        return

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    pol_sum = 0.0
    subj_sum = 0.0
    for r in rows:
        counts[r.label] = counts.get(r.label, 0) + 1
        pol_sum += r.polarity
        subj_sum += r.subjectivity

    n = len(rows)
    print(f"comments: {n}")
    print(f"avg_polarity: {pol_sum / n:.4f}")
    print(f"avg_subjectivity: {subj_sum / n:.4f}")
    print(f"positive: {counts['positive']} | neutral: {counts['neutral']} | negative: {counts['negative']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch YouTube comments and run TextBlob sentiment analysis.")
    ap.add_argument("--url", required=True, help="YouTube video URL or video id")
    ap.add_argument("--max-comments", type=int, default=200, help="Max comment count (top-level + replies)")
    ap.add_argument("--include-replies", action="store_true", help="Include reply comments")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between API pages")
    ap.add_argument("--out", default="outputs/comments_sentiment.csv", help="Output CSV path")
    ap.add_argument("--summary-out", default="outputs/comments_summary.csv", help="Output summary CSV path (empty to skip)")
    ap.add_argument("--themes-out", default="outputs/comments_themes.csv", help="Output semantic themes CSV path (empty to skip)")
    ap.add_argument("--themes", type=int, default=5, help="Number of themes for semantic extraction")
    ap.add_argument("--sumy-out", default="", help="Output Sumy summary CSV path (empty to skip)")
    ap.add_argument("--sumy-sentences", type=int, default=5, help="Sumy summary sentence count")
    ap.add_argument(
        "--sumy-per-comment-out",
        default="",
        help="Output per-comment 1-sentence summaries CSV (empty to skip)",
    )
    ap.add_argument("--sumy-per-comment-limit", type=int, default=10, help="How many comments to summarize one-by-one")
    ap.add_argument(
        "--api-key",
        default=os.getenv("YOUTUBE_API_KEY", ""),
        help="Optional YouTube Data API key (default: env YOUTUBE_API_KEY). Empty -> yt-dlp scrape.",
    )
    ap.add_argument(
        "--force-scrape",
        action="store_true",
        help="Ignore API key and scrape via yt-dlp (recommended if you don't want to use API key).",
    )
    ap.add_argument("--cookies", default="", help="yt-dlp cookies file path (optional)")
    ap.add_argument(
        "--cookies-from-browser",
        default="",
        help="yt-dlp cookies-from-browser value, e.g. 'chrome' or 'firefox' (optional)",
    )

    args = ap.parse_args(argv)

    rows = fetch_and_analyze(
        api_key=None if args.force_scrape else (args.api_key or None),
        url_or_id=args.url,
        max_comments=max(0, int(args.max_comments or 0)),
        include_replies=bool(args.include_replies),
        sleep_seconds=float(args.sleep or 0.0),
        scrape_cookies=(args.cookies or None),
        scrape_cookies_from_browser=(args.cookies_from_browser or None),
    )
    write_csv(rows, args.out)
    print_summary(rows)
    print(f"saved: {args.out}")

    if (args.summary_out or "").strip():
        summary = build_summary(rows)
        write_summary_csv(summary=summary, out_path=args.summary_out)
        print(f"saved: {args.summary_out}")

    if (args.themes_out or "").strip():
        themes = semantic_theme_extraction(rows, n_themes=int(args.themes or 5))
        write_themes_csv(themes=themes, out_path=args.themes_out)
        print(f"saved: {args.themes_out}")

    if (args.sumy_out or "").strip():
        summary_text = sumy_summarize(rows, sentences=int(args.sumy_sentences or 5))
        write_sumy_summary_csv(summary_text=summary_text, out_path=args.sumy_out, sentences=int(args.sumy_sentences or 5))
        print(f"saved: {args.sumy_out}")

    if (args.sumy_per_comment_out or "").strip():
        write_per_comment_summary_csv(
            rows=rows,
            out_path=args.sumy_per_comment_out,
            limit=int(args.sumy_per_comment_limit or 10),
            sentences=1,
        )
        print(f"saved: {args.sumy_per_comment_out}")

    if not rows:
        print(
            "\nNo comments extracted. Possible reasons:\n"
            "- The video has comments disabled.\n"
            "- yt-dlp couldn't access comments without cookies/consent.\n"
            "- The URL/ID is wrong or points to an unavailable video.\n\n"
            "Try:\n"
            "- `--force-scrape` (if you set YOUTUBE_API_KEY in env and want to ignore it)\n"
            "- `--cookies-from-browser chrome` or `--cookies /path/to/cookies.txt`\n"
            "- Another video ID with public comments.\n",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
