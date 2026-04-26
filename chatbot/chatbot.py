import os
import hashlib
import json
import re
import shutil
import threading
import urllib.parse
import tempfile
import requests
from bs4 import BeautifulSoup


# --- 1. VERİ ÇEKME ---
def _fetch_html_requests(url: str) -> str:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )

    response = session.get(url, timeout=30, allow_redirects=True)
    if response.status_code == 403:
        response = session.get(url, timeout=30, allow_redirects=True, headers={"Referer": url})
    response.raise_for_status()
    return response.text


def _fetch_html_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
        )
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()
        return html


def _fetch_html(url: str) -> str:
    try:
        return _fetch_html_requests(url)
    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (403, 429):
            try:
                return _fetch_html_playwright(url)
            except ImportError as ie:
                raise RuntimeError(
                    "403/429 alındı ve site bot koruması uyguluyor olabilir. "
                    "Playwright yüklü değil. Çözüm: `pip install playwright` ve ardından "
                    "`playwright install chromium`."
                ) from ie
        raise


def _is_rotten_tomatoes_url(url: str) -> bool:
    return "rottentomatoes.com" in (url or "").lower()


def _rt_movie_reviews_page(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("/"):
        raw = "https://www.rottentomatoes.com" + raw

    # strip fragment
    raw = raw.split("#", 1)[0]

    m = re.search(r"rottentomatoes\.com/m/([^/?#]+)", raw, flags=re.I)
    if not m:
        return raw
    slug = m.group(1)
    return f"https://www.rottentomatoes.com/m/{slug}/reviews"


def _rt_load_props(reviews_page_url: str) -> dict:
    html = _fetch_html_requests(reviews_page_url)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one('script[type="application/json"][data-json="props"]')
    if not node:
        raise RuntimeError("Rotten Tomatoes sayfasında props JSON bulunamadı (HTML değişmiş olabilir).")
    try:
        return json.loads(node.get_text(strip=True))
    except Exception as e:
        raise RuntimeError("Rotten Tomatoes props JSON parse edilemedi.") from e


def _rt_fetch_critic_reviews(*, ems_id: str, page_size: int = 50, top_only: bool = False) -> list[dict]:
    return _rt_fetch_reviews(ems_id=ems_id, review_type="critic", page_size=page_size, top_only=top_only)


def _rt_reviews_to_texts(reviews: list[dict]) -> list[str]:
    out: list[str] = []
    for rv in reviews:
        quote = (rv.get("reviewQuote") or "").strip()
        if not quote:
            continue

        critic = rv.get("critic") or {}
        publication = rv.get("publication") or {}
        critic_name = (critic.get("displayName") or "").strip()
        publication_name = (publication.get("name") or "").strip()
        score = (rv.get("originalScore") or "").strip()
        sentiment = (rv.get("scoreSentiment") or "").strip()
        created = (rv.get("createDate") or "").strip()

        meta_parts = []
        if critic_name:
            meta_parts.append(critic_name)
        if publication_name:
            meta_parts.append(publication_name)
        if sentiment:
            meta_parts.append(sentiment)
        if score:
            meta_parts.append(score)
        if created:
            meta_parts.append(created[:10])

        meta = " | ".join(meta_parts)
        out.append(f"{quote}\n[{meta}]")

    return out


def rt_search_movies(query: str, *, limit: int = 10) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    url = "https://www.rottentomatoes.com/search?search=" + urllib.parse.quote(q)
    html = _fetch_html_requests(url)
    soup = BeautifulSoup(html, "html.parser")

    rows = soup.select("search-page-media-row")[: max(0, int(limit or 0))]
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        a = row.select_one('a[slot="title"][href]')
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href in seen:
            continue
        seen.add(href)

        title = a.get_text(" ", strip=True)
        year = (row.get("release-year") or "").strip()
        score = (row.get("tomatometer-score") or "").strip()
        sentiment = (row.get("tomatometer-sentiment") or "").strip()

        out.append(
            {
                "title": title,
                "year": year,
                "url": href,
                "tomatometer_score": score,
                "tomatometer_sentiment": sentiment,
            }
        )
    return out


def _rt_fetch_synopsis(movie_page_url: str) -> str:
    html = _fetch_html_requests(movie_page_url)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one('div[slot="description"] rt-text[slot="content"]')
    if node:
        return node.get_text(" ", strip=True)
    meta = soup.select_one('meta[name="description"]')
    if meta and meta.get("content"):
        return str(meta.get("content")).strip()
    return ""


def rt_movie_overview(url: str) -> dict:
    reviews_page_url = _rt_movie_reviews_page(url)
    props = _rt_load_props(reviews_page_url)
    media = props.get("media") or {}
    vanity = props.get("vanity") or {}

    href = (vanity.get("href") or media.get("link") or "").strip()
    if href.startswith("/"):
        movie_page_url = "https://www.rottentomatoes.com" + href
    elif href:
        movie_page_url = href
    else:
        movie_page_url = reviews_page_url.replace("/reviews", "")

    synopsis = _rt_fetch_synopsis(movie_page_url)

    directors = media.get("directors") or []
    if isinstance(directors, list):
        directors = [d for d in directors if isinstance(d, str) and d.strip()]
    else:
        directors = []

    return {
        "title": (media.get("title") or "").strip(),
        "release_year": str(media.get("releaseYear") or "").strip(),
        "rating": str(media.get("rating") or "").strip(),
        "runtime": str(media.get("runTime") or "").strip(),
        "genres": str(media.get("genreDisplayName") or "").strip(),
        "directors": directors,
        "theater_release_date": str(media.get("theaterReleaseDate") or "").strip(),
        "synopsis": synopsis.strip(),
        "movie_page_url": movie_page_url,
        "reviews_page_url": reviews_page_url,
        "prerelease_text": str(media.get("prereleaseText") or "").strip(),
    }


def _rt_fetch_reviews(
    *,
    ems_id: str,
    review_type: str,
    page_size: int = 50,
    top_only: bool = False,
    verified: bool | None = None,
) -> list[dict]:
    api_url = f"https://www.rottentomatoes.com/napi/rtcf/v1/movies/{ems_id}/reviews"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.rottentomatoes.com/",
    }

    after: str | None = None
    out: list[dict] = []
    seen_ids: set[str] = set()

    while True:
        params: dict = {"type": review_type, "pageSize": int(page_size)}
        if top_only:
            params["topOnly"] = "true"
        if verified is True:
            params["verified"] = "true"
        elif verified is False:
            params["verified"] = "false"
        if after:
            params["after"] = after

        r = requests.get(api_url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        reviews = payload.get("reviews") or []
        page_info = payload.get("pageInfo") or {}

        for rv in reviews:
            rid = str(rv.get("reviewId") or "").strip()
            if not rid or rid in seen_ids:
                continue
            seen_ids.add(rid)
            out.append(rv)

        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break

    return out


def rt_fetch_reviews_from_url(
    url: str,
    *,
    kind: str = "critic",
    top_only: bool = False,
    verified: bool | None = None,
    limit: int = 100,
) -> list[dict]:
    reviews_page_url = _rt_movie_reviews_page(url)
    props = _rt_load_props(reviews_page_url)
    ems_id = ((props.get("vanity") or {}).get("emsId") or "").strip()
    if not ems_id:
        raise RuntimeError("Rotten Tomatoes emsId bulunamadı.")

    kind_norm = (kind or "").strip().lower()
    if kind_norm not in {"critic", "audience"}:
        raise RuntimeError("kind sadece 'critic' veya 'audience' olabilir.")

    reviews = _rt_fetch_reviews(
        ems_id=ems_id,
        review_type=kind_norm,
        page_size=50,
        top_only=bool(top_only) if kind_norm == "critic" else False,
        verified=verified if kind_norm == "audience" else None,
    )
    return reviews[: max(0, int(limit or 0))]


def yorumlari_kaydet(url):
    print(f"URL taranıyor: {url}")
    try:
        data_dir = _data_dir()
        os.makedirs(data_dir, exist_ok=True)
        out_path = os.path.join(data_dir, "film_yorumlar.txt")

        if _is_rotten_tomatoes_url(url):
            reviews_page_url = _rt_movie_reviews_page(url)
            props = _rt_load_props(reviews_page_url)
            ems_id = ((props.get("vanity") or {}).get("emsId") or "").strip()
            if not ems_id:
                raise RuntimeError("Rotten Tomatoes emsId bulunamadı.")

            review_type = (props.get("reviewType") or "all-critics").strip()
            top_only = review_type == "top-critics"

            reviews = _rt_fetch_critic_reviews(ems_id=ems_id, page_size=50, top_only=top_only)
            yorumlar = _rt_reviews_to_texts(reviews)
            if not yorumlar:
                ov = rt_movie_overview(reviews_page_url)
                title = ov.get("title") or "This movie"
                synopsis = ov.get("synopsis") or ""
                prerelease = ov.get("prerelease_text") or ""
                lines = [f"No critic reviews found for: {title}."]
                if prerelease:
                    lines.append(prerelease)
                if synopsis:
                    lines.append(f"Synopsis: {synopsis}")
                if ov.get("movie_page_url"):
                    lines.append(f"Movie page: {ov['movie_page_url']}")
                yorumlar = ["\n".join(lines)]
        else:
            html = _fetch_html(url)
            soup = BeautifulSoup(html, "html.parser")
            # Siteye özel yorum alanı
            yorum_divleri = soup.select(
                ".yorum-icerik, .comment-body, #comment-list-container .content, .comment-item-content"
            )
            yorumlar = []
            seen = set()
            for div in yorum_divleri:
                text = div.get_text(" ", strip=True)
                if len(text) <= 10:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                yorumlar.append(text)

        if not yorumlar:
            print("Yorum bulunamadı! Lütfen manuel bir yorumlar.txt oluşturun veya URL'yi kontrol edin.")
            return False

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n---\n".join(yorumlar))
        print(f"Başarılı! {len(yorumlar)} adet yorum kaydedildi.")
        return True
    except Exception as e:
        print(f"Hata: {e}")
        return False


# --- 2. MODERN RAG CHATBOT ---
def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _chroma_paths() -> tuple[str, str]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    persist_dir = os.getenv("CHATBOT_CHROMA_DIR", "").strip() or os.path.join(base_dir, ".chroma_film_yorumlar")
    meta_path = os.path.join(persist_dir, "meta.json")
    return persist_dir, meta_path


def _data_dir() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.getenv("CHATBOT_DATA_DIR", "").strip() or os.path.join(base_dir, "data")


def _ollama_base_url() -> str:
    return (
        os.getenv("OLLAMA_BASE_URL", "").strip()
        or os.getenv("OLLAMA_HOST", "").strip()
        or os.getenv("OLLAMA_URL", "").strip()
    )


def _ollama_embed_model() -> str:
    return os.getenv("OLLAMA_EMBED_MODEL", "").strip() or "nomic-embed-text"


def _ollama_llm_model() -> str:
    return os.getenv("OLLAMA_LLM_MODEL", "").strip() or "llama3.2:1b"


def _ollama_kwargs() -> dict:
    base_url = _ollama_base_url()
    return {"base_url": base_url} if base_url else {}


def _rmtree_force(path: str) -> None:
    def _onerror(func, p, exc_info):  # noqa: ANN001
        try:
            os.chmod(p, 0o700)
        except Exception:
            pass
        try:
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, ignore_errors=False, onerror=_onerror)


def _normalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("/"):
        raw = "https://www.rottentomatoes.com" + raw
    raw = raw.split("#", 1)[0]
    if _is_rotten_tomatoes_url(raw):
        return _rt_movie_reviews_page(raw)
    return raw


def _vector_db_ready_for_url(*, expected_url: str, source_path: str) -> bool:
    persist_dir, meta_path = _chroma_paths()
    if not os.path.isdir(persist_dir) or not os.path.exists(meta_path):
        return False
    if not os.path.exists(os.path.join(persist_dir, "chroma.sqlite3")):
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return False

    try:
        src_hash = _sha256_of_file(source_path)
    except Exception:
        return False

    if meta.get("source_url") != expected_url:
        return False
    if meta.get("source_path") != os.path.abspath(source_path):
        return False
    if meta.get("source_sha256") != src_hash:
        return False
    if meta.get("collection_name") != "film_yorumlar":
        return False
    if meta.get("embedding_model") != "nomic-embed-text":
        return False
    if meta.get("chunk_size") != 500 or meta.get("chunk_overlap") != 50:
        return False

    return True


_INDEX_LOCK = threading.Lock()


def _resolve_source_path() -> str | None:
    data_path = os.path.join(_data_dir(), "film_yorumlar.txt")
    legacy_path = os.path.abspath("film_yorumlar.txt")
    if os.path.exists(data_path):
        return data_path
    if os.path.exists(legacy_path):
        return legacy_path
    return None


def ensure_index(url: str) -> dict:
    expected_url = _normalize_source_url(url)

    source_path = os.path.join(_data_dir(), "film_yorumlar.txt")
    legacy_path = os.path.abspath("film_yorumlar.txt")
    if not os.path.exists(source_path) and os.path.exists(legacy_path):
        source_path = legacy_path

    persist_dir, meta_path = _chroma_paths()
    scraped = False
    embedded = False

    with _INDEX_LOCK:
        ready_before = _vector_db_ready_for_url(expected_url=expected_url, source_path=source_path)
        if ready_before:
            return {"expected_url": expected_url, "reused_vectordb": True, "scraped": False, "embedded": False}

        scrape_needed = True
        if os.path.exists(meta_path) and os.path.exists(source_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("source_url") == expected_url:
                    scrape_needed = False
            except Exception:
                scrape_needed = True

        if scrape_needed:
            if not yorumlari_kaydet(url):
                raise RuntimeError("Yorumlar çekilemedi.")
            scraped = True

        # Ensure vectordb is ready for product-style usage (index endpoint).
        _ = get_vectorstore(expected_url=expected_url)
        embedded = True
        return {"expected_url": expected_url, "reused_vectordb": False, "scraped": scraped, "embedded": embedded}


def get_vectorstore(*, expected_url: str, _allow_tmp_fallback: bool = True):
    source_path = _resolve_source_path()
    if not source_path:
        raise RuntimeError("Yorum kaynağı bulunamadı (chatbot/data/film_yorumlar.txt yok).")

    from langchain_community.document_loaders import TextLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_chroma import Chroma
    from langchain_ollama import OllamaEmbeddings

    embed_kwargs = {"model": _ollama_embed_model(), **_ollama_kwargs()}
    try:
        embeddings = OllamaEmbeddings(**embed_kwargs)
    except TypeError:
        embeddings = OllamaEmbeddings(model=_ollama_embed_model())
    persist_dir, meta_path = _chroma_paths()
    src_path = os.path.abspath(source_path)
    src_hash = _sha256_of_file(source_path)
    collection_name = "film_yorumlar"

    vectorstore = None
    try:
        if os.path.isdir(persist_dir) and os.path.exists(meta_path) and _vector_db_ready_for_url(
            expected_url=expected_url, source_path=source_path
        ):
            vectorstore = Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
                collection_name=collection_name,
            )
    except Exception:
        vectorstore = None

    if vectorstore is None:
        if os.path.isdir(persist_dir):
            try:
                _rmtree_force(persist_dir)
            except Exception:
                shutil.rmtree(persist_dir, ignore_errors=True)
        os.makedirs(persist_dir, exist_ok=True)

        loader = TextLoader(source_path, encoding="utf-8")
        docs = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        splits = text_splitter.split_documents(docs)

        try:
            vectorstore = Chroma.from_documents(
                documents=splits,
                embedding=embeddings,
                persist_directory=persist_dir,
                collection_name=collection_name,
            )
        except Exception as e:
            msg = str(e).lower()
            if "readonly" in msg or "read only" in msg:
                if _allow_tmp_fallback and not os.getenv("CHATBOT_CHROMA_DIR", "").strip():
                    tmp_dir = os.path.join(tempfile.gettempdir(), "chatbot_chroma")
                    os.environ["CHATBOT_CHROMA_DIR"] = tmp_dir
                    return get_vectorstore(expected_url=expected_url, _allow_tmp_fallback=False)
                raise RuntimeError(
                    "Chroma sqlite veritabanı yazılamıyor (readonly). "
                    "Çözüm: `CHATBOT_CHROMA_DIR` env ile yazılabilir bir klasör verin "
                    "(örn. `export CHATBOT_CHROMA_DIR=/tmp/chatbot_chroma`) veya mevcut "
                    "persist klasörünü silin."
                ) from e
            raise
        if hasattr(vectorstore, "persist"):
            vectorstore.persist()

        os.makedirs(persist_dir, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "collection_name": collection_name,
                    "source_url": expected_url,
                    "source_path": src_path,
                    "source_sha256": src_hash,
                    "embedding_model": "nomic-embed-text",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    return vectorstore


def answer_question(*, expected_url: str, question: str, top_k: int = 6) -> dict:
    from langchain_ollama import ChatOllama
    from langchain_core.prompts import ChatPromptTemplate

    vectorstore = get_vectorstore(expected_url=expected_url)
    retriever = vectorstore.as_retriever(search_kwargs={"k": int(top_k or 6)})
    docs = retriever.invoke(question.strip())

    context = "\n\n---\n\n".join(d.page_content for d in docs)
    system_prompt = (
        "You're a film critique and review assistant. Answer the user's question based ONLY on the provided critic reviews.\n"
        "If you cannot find an answer in the reviews, say 'No reviews available on this topic.'\n"
        "Summarize the answer in at most 3 sentences.\n\n"
        "{context}"
    )
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
    llm_kwargs = {"model": _ollama_llm_model(), "temperature": 0, **_ollama_kwargs()}
    try:
        llm = ChatOllama(**llm_kwargs)
    except TypeError:
        llm = ChatOllama(model=_ollama_llm_model(), temperature=0)
    msg = llm.invoke(prompt.format_messages(context=context, input=question.strip()))

    return {
        "answer": (getattr(msg, "content", None) or str(msg)).strip(),
        "evidence": [{"content": d.page_content[:800], "metadata": d.metadata} for d in docs],
    }


def retrieve_evidence(*, expected_url: str, query: str, top_k: int = 8) -> list[dict]:
    vectorstore = get_vectorstore(expected_url=expected_url)
    retriever = vectorstore.as_retriever(search_kwargs={"k": int(top_k or 8)})
    docs = retriever.invoke((query or "").strip())
    return [{"content": d.page_content[:1200], "metadata": d.metadata} for d in docs]


def chat_baslat(*, expected_url: str = ""):
    if not _resolve_source_path():
        print("Yorum kaynağı bulunamadı. Önce bir URL seçin: /search <film adı> veya /set-url <url>")
        return

    current_url = expected_url.strip()
    last_results: list[dict] = []

    def _print_help() -> None:
        print(
            "\nKomutlar:\n"
            "  /help                     Komutları göster\n"
            "  /search <query>            RottenTomatoes'da film ara\n"
            "  /use <n>                   Son arama sonucundan seç (1..N)\n"
            "  /set-url <url>             Kaynak URL ayarla\n"
            "  /describe                 Filmi özetle (RT sayfasından)\n"
            "  /index                     URL için scrape+embedding (gerekirse)\n"
            "  /status                    Mevcut URL + index durumu\n"
            "  /ask <soru>                Soru sor (RAG)\n"
            "  /exit                      Çıkış\n"
            "\nNot: Komutsuz yazarsanız, mevcut URL üzerinden soru olarak çalışır.\n"
        )

    _print_help()
    print("BOT HAZIR!")
    while True:
        sorgu = input("\nSen> ").strip()
        if not sorgu:
            continue

        if sorgu.lower() in {"exit", "/exit", "quit", "/quit"}:
            break

        if sorgu.startswith("/help"):
            _print_help()
            continue

        if sorgu.startswith("/search"):
            q = sorgu[len("/search") :].strip()
            if not q:
                print("Kullanım: /search <film adı>")
                continue
            try:
                last_results = rt_search_movies(q, limit=10)
            except Exception as e:
                print(f"Hata (search): {e}")
                continue
            if not last_results:
                print("Sonuç bulunamadı.")
                continue
            print("\nSonuçlar:")
            for i, r in enumerate(last_results, start=1):
                bits = [r.get("title") or ""]
                if r.get("year"):
                    bits.append(str(r["year"]))
                if r.get("tomatometer_score"):
                    bits.append(f"TM={r['tomatometer_score']}%")
                if r.get("url"):
                    bits.append(r["url"])
                print(f"  {i}) " + " | ".join(b for b in bits if b))
            print("Seçmek için: /use <n>")
            continue

        if sorgu.startswith("/use"):
            if not last_results:
                print("Önce /search yapın.")
                continue
            n_raw = sorgu[len("/use") :].strip()
            try:
                n = int(n_raw)
            except Exception:
                print("Kullanım: /use <n>")
                continue
            if n < 1 or n > len(last_results):
                print(f"Geçersiz seçim. 1..{len(last_results)}")
                continue
            current_url = _normalize_source_url(last_results[n - 1]["url"])
            print(f"Seçildi: {current_url}")
            continue

        if sorgu.startswith("/set-url"):
            u = sorgu[len("/set-url") :].strip()
            if not u:
                print("Kullanım: /set-url <url>")
                continue
            current_url = _normalize_source_url(u)
            print(f"URL ayarlandı: {current_url}")
            continue

        if sorgu.startswith("/status"):
            if not current_url:
                print("URL seçilmedi. /search veya /set-url kullanın.")
                continue
            sp = _resolve_source_path()
            ready = False
            if sp:
                ready = _vector_db_ready_for_url(expected_url=current_url, source_path=sp)
            print(f"url: {current_url}")
            print(f"vectordb_ready: {ready}")
            continue

        if sorgu.startswith("/index"):
            if not current_url:
                print("URL seçilmedi. /search veya /set-url kullanın.")
                continue
            try:
                info = ensure_index(current_url)
                current_url = info["expected_url"]
                print(
                    f"index ok: reused_vectordb={info.get('reused_vectordb')} scraped={info.get('scraped')} embedded={info.get('embedded')}"
                )
            except Exception as e:
                print(f"Hata (index): {e}")
            continue

        if sorgu.startswith("/describe"):
            if not current_url:
                print("URL seçilmedi. /search veya /set-url kullanın.")
                continue
            if not _is_rotten_tomatoes_url(current_url):
                print("Şu an sadece RottenTomatoes URL’leri için /describe destekleniyor.")
                continue
            try:
                ov = rt_movie_overview(current_url)
            except Exception as e:
                print(f"Hata (describe): {e}")
                continue

            title = ov.get("title") or "(unknown)"
            bits = []
            if ov.get("release_year"):
                bits.append(str(ov["release_year"]))
            if ov.get("rating"):
                bits.append(str(ov["rating"]))
            if ov.get("runtime"):
                bits.append(str(ov["runtime"]))
            if ov.get("genres"):
                bits.append(str(ov["genres"]))
            print("\nFilm:")
            print(f"- {title}" + (f" | {' | '.join(bits)}" if bits else ""))
            if ov.get("directors"):
                print(f"- Directors: {', '.join(ov['directors'])}")
            if ov.get("synopsis"):
                print(f"- Synopsis: {ov['synopsis']}")
            else:
                print("- Synopsis: (bulunamadı)")
            continue

        if sorgu.startswith("/ask"):
            q = sorgu[len("/ask") :].strip()
            if not q:
                print("Kullanım: /ask <soru>")
                continue
            if not current_url:
                print("URL seçilmedi. /search veya /set-url kullanın.")
                continue
            try:
                info = ensure_index(current_url)
                current_url = info["expected_url"]
                response = answer_question(expected_url=current_url, question=q)
            except Exception as e:
                print(f"Hata (ask): {e}")
                continue
            print(f"\nBot: {response['answer']}")
            print("\n[KANITLAR]")
            for ev in response["evidence"]:
                print(f"- {ev['content'][:100]}...")
            continue

        # Agentic default: treat as question for current URL.
        if not current_url:
            print("URL seçilmedi. /search <film adı> ile bulun veya /set-url <url> ile ayarlayın.")
            continue

        try:
            info = ensure_index(current_url)
            current_url = info["expected_url"]
            response = answer_question(expected_url=current_url, question=sorgu)
        except Exception as e:
            print(f"Hata: {e}")
            continue
        print(f"\nBot: {response['answer']}")

        print("\n[KANITLAR]")
        for ev in response["evidence"]:
            print(f"- {ev['content'][:100]}...")


if __name__ == "__main__":
    url = "https://www.rottentomatoes.com/m/normal_2025#critics-reviews"
    try:
        info = ensure_index(url)
    except Exception as e:
        print(f"Hata: {e}")
        raise SystemExit(1)
    chat_baslat(expected_url=info["expected_url"])
