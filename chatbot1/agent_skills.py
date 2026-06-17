import json
import os
import sys
from typing import Any


def _import_chatbot_module():
    try:
        from chatbot import chatbot as chatbot_mod  # type: ignore

        return chatbot_mod
    except ModuleNotFoundError:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from chatbot import chatbot as chatbot_mod  # type: ignore

        return chatbot_mod


def _safe_json_dumps(value: Any, *, max_chars: int = 20_000) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        s = str(value)
    if len(s) > max_chars:
        return s[:max_chars] + "\n...[truncated]..."
    return s


def _reviews_json_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "reviews.json")


def skill_rt_search_movies(*, query: str, limit: int = 10) -> list[dict]:
    chatbot_mod = _import_chatbot_module()
    return chatbot_mod.rt_search_movies(query, limit=int(limit))


def skill_rt_movie_overview(*, url: str) -> dict:
    chatbot_mod = _import_chatbot_module()
    return chatbot_mod.rt_movie_overview(url)


def skill_rt_fetch_reviews(
    *,
    url: str,
    kind: str = "audience",
    verified: bool | None = None,
    top_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    chatbot_mod = _import_chatbot_module()
    return chatbot_mod.rt_fetch_reviews_from_url(
        url,
        kind=kind,
        verified=verified,
        top_only=bool(top_only),
        limit=int(limit),
    )


def skill_save_audience_reviews_to_file(*, url: str, limit: int = 200) -> dict:
    # Reuse chatbot1 scraper normalization so UI continues to work.
    try:
        from chatbot1.scraper import _normalize_audience_review  # type: ignore
    except ModuleNotFoundError:
        from scraper import _normalize_audience_review  # type: ignore

    raw = skill_rt_fetch_reviews(url=url, kind="audience", verified=None, limit=int(limit))
    out: list[dict] = []
    for rv in raw:
        if not isinstance(rv, dict):
            continue
        norm = _normalize_audience_review(rv)
        if norm:
            out.append(norm)

    path = _reviews_json_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    return {"saved": len(out), "path": path}


def skill_load_saved_reviews() -> dict:
    path = _reviews_json_path()
    if not os.path.exists(path):
        return {"path": path, "exists": False, "count": 0}
    with open(path, "r", encoding="utf-8") as f:
        reviews = json.load(f) or []
    return {"path": path, "exists": True, "count": len(reviews)}


def skill_search_saved_reviews(*, query: str, top_k: int = 8) -> dict:
    path = _reviews_json_path()
    if not os.path.exists(path):
        return {"path": path, "exists": False, "results": []}

    with open(path, "r", encoding="utf-8") as f:
        reviews = json.load(f) or []

    if not isinstance(reviews, list):
        return {"path": path, "exists": True, "results": []}

    try:
        from chatbot1.vector_db import EphemeralVectorDB  # type: ignore
    except ModuleNotFoundError:
        from vector_db import EphemeralVectorDB  # type: ignore

    db = EphemeralVectorDB(dim=1024)
    docs = [r for r in reviews if isinstance(r, dict)]
    db.fit(docs, text_key="review")
    hits = db.search(query, top_k=int(top_k))

    results = []
    for h in hits:
        d = h.doc or {}
        txt = str(d.get("review") or "")
        results.append(
            {
                "score": round(float(h.score), 4),
                "name": d.get("name", ""),
                "rating": d.get("rating", ""),
                "date": d.get("date", ""),
                "review": (txt[:240] + ("..." if len(txt) > 240 else "")),
            }
        )

    return {"path": path, "exists": True, "results": results}


def skill_scrape_default_movie(*, max_clicks: int = 4) -> dict:
    try:
        from chatbot1.scraper import scrape_reviews  # type: ignore
    except ModuleNotFoundError:
        from scraper import scrape_reviews  # type: ignore

    reviews = scrape_reviews(max_clicks=int(max_clicks), headless=True)
    return {"saved": len(reviews), "path": _reviews_json_path()}


SKILLS: list[dict] = [
    {
        "name": "rt_search_movies",
        "description": "RottenTomatoes'da film arar ve sonuçları listeler.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Arama sorgusu"},
                "limit": {"type": "integer", "description": "Maksimum sonuç sayısı", "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rt_movie_overview",
        "description": "RottenTomatoes film sayfasından özet/metadata getirir.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "RT film veya reviews URL"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rt_fetch_reviews",
        "description": "RottenTomatoes NAPI üzerinden (critic/audience) yorumları getirir.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "RT film veya reviews URL"},
                "kind": {"type": "string", "enum": ["critic", "audience"], "default": "audience"},
                "verified": {"type": ["boolean", "null"], "description": "Sadece audience için", "default": None},
                "top_only": {"type": "boolean", "description": "Sadece critic için", "default": False},
                "limit": {"type": "integer", "description": "Maksimum yorum", "default": 50},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_audience_reviews_to_file",
        "description": "Audience yorumlarını çekip bu projedeki `chatbot1/reviews.json` dosyasına kaydeder.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "RT film veya reviews URL"},
                "limit": {"type": "integer", "description": "Maksimum yorum", "default": 200},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "load_saved_reviews",
        "description": "Projede kayıtlı `chatbot1/reviews.json` dosyasının durumunu döndürür.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search_saved_reviews",
        "description": "Kayıtlı `chatbot1/reviews.json` içinden vektör benzerliği ile ilgili yorumları bulur (anlık, kalıcı DB yok).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Arama sorgusu"},
                "top_k": {"type": "integer", "description": "Dönecek sonuç sayısı", "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scrape_default_movie",
        "description": "Bu projedeki varsayılan film (Normal 2025) için audience yorumlarını çekip `chatbot1/reviews.json` dosyasına kaydeder.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_clicks": {
                    "type": "integer",
                    "description": "Yaklaşık yorum sayısı kontrolü (1 ≈ 50 yorum).",
                    "default": 4,
                }
            },
            "additionalProperties": False,
        },
    },
]


def openai_tools() -> list[dict]:
    # OpenAI Responses API tool shape (flat), not Chat Completions shape.
    # Ref: openai.types.responses.FunctionToolParam fields: type/name/description/parameters/strict/...
    tools: list[dict] = []
    for s in SKILLS:
        tools.append(
            {
                "type": "function",
                "name": s["name"],
                "description": s.get("description"),
                "parameters": s.get("parameters"),
                # Keep non-strict to allow optional fields in JSON schema.
                "strict": False,
            }
        )
    return tools


def call_skill(name: str, args: dict) -> str:
    if name == "rt_search_movies":
        return _safe_json_dumps(skill_rt_search_movies(**args))
    if name == "rt_movie_overview":
        return _safe_json_dumps(skill_rt_movie_overview(**args))
    if name == "rt_fetch_reviews":
        return _safe_json_dumps(skill_rt_fetch_reviews(**args))
    if name == "save_audience_reviews_to_file":
        return _safe_json_dumps(skill_save_audience_reviews_to_file(**args))
    if name == "load_saved_reviews":
        return _safe_json_dumps(skill_load_saved_reviews())
    if name == "search_saved_reviews":
        return _safe_json_dumps(skill_search_saved_reviews(**args))
    if name == "scrape_default_movie":
        return _safe_json_dumps(skill_scrape_default_movie(**args))
    raise ValueError(f"Unknown skill: {name}")
