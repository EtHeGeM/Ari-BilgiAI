"""
scraper.py
Rotten Tomatoes - Normal (2025) filminin izleyici yorumlarını çeker.
Bu proje için asıl scraping mantığı `../chatbot` klasöründeki modülden kullanılır.
"""

import json
import os
import sys
import socket
import traceback
from typing import Any

import requests
from bs4 import BeautifulSoup


URL = "https://www.rottentomatoes.com/m/normal_2025/reviews/all-audience"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reviews.json")
DEBUG = os.getenv("CHATBOT1_SCRAPER_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[scraper:debug] {msg}")


def _warn(msg: str) -> None:
    print(f"[scraper:warn] {msg}")


def _error(msg: str) -> None:
    print(f"[scraper:error] {msg}")


def _import_rt_fetcher():
    """
    `../chatbot/chatbot.py` içindeki `rt_fetch_reviews_from_url` fonksiyonunu import eder.

    Not: Streamlit bazen script'i `chatbot1/` içinden çalıştırıldığı için üst dizin
    `sys.path` içinde olmayabilir. Bu yüzden gerekirse parent dizini ekliyoruz.
    """
    try:
        from chatbot.chatbot import rt_fetch_reviews_from_url  # type: ignore

        return rt_fetch_reviews_from_url
    except ModuleNotFoundError:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from chatbot.chatbot import rt_fetch_reviews_from_url  # type: ignore

        return rt_fetch_reviews_from_url


def _best_effort_dns_check(hostname: str) -> None:
    try:
        ip = socket.gethostbyname(hostname)
        _debug(f"DNS OK: {hostname} -> {ip}")
    except Exception as e:
        _warn(f"DNS FAIL: {hostname} -> {type(e).__name__}: {e}")


def _debug_fetch_props(url: str) -> dict | None:
    """
    Basit bir şekilde reviews sayfasından props JSON'u çıkarır.
    `chatbot/chatbot.py` içindeki fonksiyonları import etmeye gerek kalmadan
    debug amaçlı kendi kendine yeter.
    """
    try:
        r = requests.get(
            url,
            timeout=30,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        _debug(f"props page status={r.status_code} len={len(r.text)} final_url={r.url}")
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        node = soup.select_one('script[type="application/json"][data-json="props"]')
        if not node:
            _warn("props JSON node bulunamadı: script[data-json=props] yok (RT HTML değişmiş olabilir).")
            return None
        try:
            return json.loads(node.get_text(strip=True))
        except Exception as e:
            _warn(f"props JSON parse edilemedi: {type(e).__name__}: {e}")
            return None
    except Exception as e:
        _warn(f"props fetch hata: {type(e).__name__}: {e}")
        if DEBUG:
            _debug(traceback.format_exc())
        return None


def _debug_probe_napi(ems_id: str) -> None:
    try:
        api_url = f"https://www.rottentomatoes.com/napi/rtcf/v1/movies/{ems_id}/reviews"
        r = requests.get(
            api_url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.rottentomatoes.com/",
            },
            params={"type": "audience", "pageSize": 10},
        )
        _debug(f"NAPI status={r.status_code} url={r.url}")
        r.raise_for_status()
        payload = r.json()
        reviews = payload.get("reviews") or []
        page_info = payload.get("pageInfo") or {}
        _debug(f"NAPI reviews_count={len(reviews)} pageInfo_keys={list(page_info.keys())}")
        if reviews:
            first = reviews[0]
            rid = first.get("reviewId")
            _debug(f"NAPI first_reviewId={rid} keys_sample={sorted(first.keys())[:25]}")
    except Exception as e:
        _warn(f"NAPI probe hata: {type(e).__name__}: {e}")
        if DEBUG:
            _debug(traceback.format_exc())


def _rating_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        # RottenTomatoes audience rating çoğunlukla 0-5 arası olur
        if 0 <= float(value) <= 5:
            return f"{float(value):g}/5"
        return f"{float(value):g}"
    s = str(value).strip()
    if s.startswith("STAR_"):
        # Örn: STAR_4_5 -> 4.5/5, STAR_3 -> 3/5
        parts = s.split("_")[1:]
        if parts and all(p.isdigit() for p in parts):
            if len(parts) == 1:
                return f"{int(parts[0])}/5"
            if len(parts) == 2:
                return f"{int(parts[0])}.{int(parts[1])}/5"
    return s


def _normalize_audience_review(rv: dict) -> dict | None:
    user = rv.get("user")
    name = ""
    if isinstance(user, dict):
        name = (user.get("displayName") or user.get("name") or user.get("username") or "").strip()
    elif isinstance(user, str):
        name = user.strip()

    if not name:
        name = (rv.get("userDisplayName") or rv.get("displayName") or rv.get("name") or rv.get("username") or "").strip()
    if not name:
        name = "Anonim"

    review_text = (
        (rv.get("reviewText") or rv.get("review") or rv.get("reviewQuote") or rv.get("quote") or rv.get("comment") or "")
    )
    if not isinstance(review_text, str):
        review_text = str(review_text or "")
    review_text = review_text.strip()
    if not review_text:
        return None

    rating = _rating_to_str(rv.get("rating") or rv.get("score") or rv.get("starRating") or rv.get("originalScore"))
    date = (
        (rv.get("createDate") or rv.get("publishDate") or rv.get("submissionDate") or rv.get("date") or "")
    )
    if not isinstance(date, str):
        date = str(date or "")
    date = date.strip()

    return {"name": name, "rating": rating, "date": date, "review": review_text}


def scrape_reviews(max_clicks: int = 10, headless: bool = True):
    """
    Ana scraping fonksiyonu.

    Geriye uyumluluk için `max_clicks` ve `headless` parametreleri korunur.
    `../chatbot` modülündeki NAPI tabanlı scraper kullanıldığı için bu parametreler
    sadece `limit` türetmekte kullanılır.
    """
    _ = headless  # `chatbot` scraper Selenium kullanmadığı için burada işlevsiz.
    limit = max(0, int(max_clicks or 0)) * 50 or 200

    print(f"[+] Rotten Tomatoes yorumları çekiliyor (chatbot scraper): {URL}")
    _debug(f"python={sys.version.split()[0]} cwd={os.getcwd()}")
    _debug(f"OUTPUT_FILE={OUTPUT_FILE}")
    _best_effort_dns_check("www.rottentomatoes.com")

    try:
        rt_fetch_reviews_from_url = _import_rt_fetcher()
        raw_reviews = rt_fetch_reviews_from_url(URL, kind="audience", limit=limit)
    except Exception as e:
        _error(f"rt_fetch_reviews_from_url hata: {type(e).__name__}: {e}")
        _error(traceback.format_exc())
        raise

    _debug(f"raw_reviews_type={type(raw_reviews).__name__} raw_reviews_len={len(raw_reviews or [])}")

    out: list[dict] = []
    for rv in raw_reviews or []:
        if not isinstance(rv, dict):
            continue
        norm = _normalize_audience_review(rv)
        if norm:
            out.append(norm)

    if not out:
        _warn("0 yorum normalize edildi. Detay teşhis başlatılıyor...")
        props = _debug_fetch_props("https://www.rottentomatoes.com/m/normal_2025/reviews")
        if props:
            vanity = props.get("vanity") or {}
            ems_id = (vanity.get("emsId") or "").strip() if isinstance(vanity, dict) else ""
            _debug(f"props vanity keys={list(vanity.keys()) if isinstance(vanity, dict) else type(vanity).__name__}")
            _debug(f"props emsId={ems_id!r}")
            if ems_id:
                _debug_probe_napi(ems_id)
        else:
            _warn("props alınamadı; RT sayfasına erişim/HTML sorunu olabilir.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[+] Toplam {len(out)} yorum kaydedildi: {OUTPUT_FILE}")
    return out


def load_reviews():
    """Daha önce çekilmiş yorumları yükler."""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


if __name__ == "__main__":
    reviews = scrape_reviews(max_clicks=10, headless=True)
    if reviews:
        print("\n--- İlk 3 Yorum Önizleme ---")
        for i, r in enumerate(reviews[:3], 1):
            print(f"\n{i}. {r['name']} ({r['rating']}) - {r['date']}")
            print(f"   {r['review'][:200]}...")
