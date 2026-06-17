"""
app.py
Streamlit tabanlı film yorumu chatbot arayüzü.
Çalıştırmak için: streamlit run chatbot1.py
"""

import streamlit as st
import ollama
import os
import json
try:
    from chatbot1.scraper import load_reviews
    from chatbot1.scraper import OUTPUT_FILE as REVIEWS_JSON_PATH
except ModuleNotFoundError:
    from scraper import load_reviews
    from scraper import OUTPUT_FILE as REVIEWS_JSON_PATH
try:
    from chatbot1.agent_skills import openai_tools, call_skill, SKILLS
except ModuleNotFoundError:
    from agent_skills import openai_tools, call_skill, SKILLS


# Kullanılabilecek varsayılan model
DEFAULT_MODEL = "llama3.2"
DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1"


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def build_context(reviews: list, max_reviews: int = 30) -> str:
    """Yorumları LLM'e verilebilir bir bağlam metnine dönüştürür."""
    if not reviews:
        return "Henüz çekilmiş yorum bulunmamaktadır."

    context_lines = []
    for i, r in enumerate(reviews[:max_reviews], 1):
        rating = r.get("rating", "")
        rating_str = f" [Puan: {rating}]" if rating else ""
        context_lines.append(
            f"Yorum {i} - {r.get('name', 'Anonim')}{rating_str}:\n{r.get('review', '')}\n"
        )

    return "\n".join(context_lines)


def _get_vector_db(*, reviews_len: int):
    try:
        from chatbot1.vector_db import EphemeralVectorDB
    except ModuleNotFoundError:
        from vector_db import EphemeralVectorDB

    db = st.session_state.get("_vector_db")
    meta = st.session_state.get("_vector_db_meta") or {}

    try:
        mtime = os.path.getmtime(REVIEWS_JSON_PATH)
    except Exception:
        mtime = None

    signature = (int(reviews_len), mtime)
    if not db or meta.get("signature") != signature:
        db = EphemeralVectorDB(dim=1024)
        st.session_state["_vector_db"] = db
        st.session_state["_vector_db_meta"] = {"signature": signature}

    return db


def _select_relevant_reviews(reviews: list, query: str, *, top_k: int = 20) -> list:
    if not reviews:
        return []
    db = _get_vector_db(reviews_len=len(reviews))
    # fit once per loaded reviews
    if st.session_state.get("_vector_db_fitted_len") != len(reviews):
        db.fit(reviews, text_key="review")
        st.session_state["_vector_db_fitted_len"] = len(reviews)

    try:
        hits = db.search(query, top_k=int(top_k))
    except Exception:
        return reviews[:top_k]
    return [h.doc for h in hits]


def _build_evidence_note(hits, *, max_items: int = 5) -> str:
    items = list(hits or [])[: max(0, int(max_items))]
    if not items:
        return ""

    lines = ["**Not (Kanıtlar):** Bu cevap aşağıdaki izleyici yorumlarına dayanarak oluşturuldu:"]
    for i, h in enumerate(items, 1):
        d = getattr(h, "doc", None) or {}
        score = getattr(h, "score", None)
        name = d.get("name", "Anonim")
        rating = d.get("rating", "")
        date = d.get("date", "")
        review = str(d.get("review", "") or "")
        excerpt = (review[:220] + ("..." if len(review) > 220 else "")).replace("\n", " ").strip()

        meta_parts = [str(name)]
        if rating:
            meta_parts.append(f"Puan: {rating}")
        if date:
            meta_parts.append(f"Tarih: {date}")
        if score is not None:
            try:
                meta_parts.append(f"Skor: {float(score):.3f}")
            except Exception:
                pass
        meta = " | ".join(meta_parts)

        lines.append(f"{i}. {meta}\n   - {excerpt}")

    return "\n".join(lines)


def _select_relevant_reviews_with_evidence(reviews: list, query: str, *, top_k: int = 20):
    if not reviews:
        return [], ""

    db = _get_vector_db(reviews_len=len(reviews))
    if st.session_state.get("_vector_db_fitted_len") != len(reviews):
        db.fit(reviews, text_key="review")
        st.session_state["_vector_db_fitted_len"] = len(reviews)

    try:
        hits = db.search(query, top_k=int(top_k))
    except Exception:
        return reviews[:top_k], ""

    evidence_note = _build_evidence_note(hits, max_items=min(5, int(top_k)))
    return [h.doc for h in hits], evidence_note


def build_system_prompt(reviews: list) -> str:
    """Sistem prompt'unu hazırlar."""
    context = build_context(reviews)
    film = "Normal (2025)"

    return f"""Sen {film} filmi hakkında konuşan bir film eleştirmeni asistanısın.
	Aşağıda Rotten Tomatoes'tan toplanan gerçek izleyici yorumları var.
	Bu yorumlara dayanarak kullanıcının sorularını TÜRKÇE yanıtla.

KURALLAR:
- Yorumlardaki ortak temaları, olumlu/olumsuz noktaları özetleyebilirsin.
- Genel beğeni durumu hakkında konuşabilirsin.
- Yorumlardan örnekler verebilirsin (gerekirse parafraze ederek).
- Eğer bir bilgi yorumlarda yoksa, "Yorumlarda bu konuda bilgi yok" de.
- Cevaplarını net, samimi ve film eleştirmeni tonunda ver.
- Kullanıcı başka bir film bulmak/aramak isterse RottenTomatoes arama/yorum araçlarını kullanabilirsin.

=== İZLEYİCİ YORUMLARI ===
{context}
=== YORUMLAR SONU ===
"""


def build_tool_instructions() -> str:
    return """ARAÇ KULLANIMI (Tools / Skills)
- Araçları sadece gerektiğinde çağır.
- Film bulma: `rt_search_movies` → bir sonuç seç → `rt_movie_overview` / `rt_fetch_reviews`.
- Yorumları güncelleme: `save_audience_reviews_to_file` veya varsayılan film için `scrape_default_movie`.
- Kayıtlı yorumlarda semantik arama: `search_saved_reviews`.
- Araç çıktıları JSON döner; bu çıktıya dayanarak kısa ve net yanıt ver.

Mevcut araçlar:
- `rt_search_movies(query, limit=10)`
- `rt_movie_overview(url)`
- `rt_fetch_reviews(url, kind='audience'|'critic', verified?, top_only?, limit=50)`
- `save_audience_reviews_to_file(url, limit=200)`
- `load_saved_reviews()`
- `search_saved_reviews(query, top_k=8)`
- `scrape_default_movie(max_clicks=4)`"""


def chat_stream(user_message: str, history: list, reviews: list, model: str):
    """Ollama'dan streaming yanıt için generator."""
    use_vector = bool(st.session_state.get("use_vector_search", False))
    top_k = int(st.session_state.get("vector_top_k", 20) or 20)
    evidence_note = ""
    if use_vector:
        reviews_for_prompt, evidence_note = _select_relevant_reviews_with_evidence(
            reviews, user_message, top_k=top_k
        )
    else:
        reviews_for_prompt = reviews
    system_prompt = build_system_prompt(reviews_for_prompt)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    provider = (st.session_state.get("provider") or "ollama").strip().lower()
    try:

        if provider == "openai":
            try:
                from openai import OpenAI
            except Exception as e:
                yield f"❌ OpenAI SDK bulunamadı: {e}\n\nKomut: `pip install -r requirements.txt`"
                return

            api_key = os.getenv("OPENAI_API_KEY", "").strip() or st.secrets.get("OPENAI_API_KEY", "")  # type: ignore[attr-defined]
            if not api_key:
                yield (
                    "❌ `OPENAI_API_KEY` bulunamadı.\n\n"
                    "Terminalde:\n"
                    "`export OPENAI_API_KEY='...'`"
                )
                return

            client = OpenAI(api_key=api_key)

            use_skills = bool(st.session_state.get("agentic_tools_enabled", True))
            tools = openai_tools() if use_skills else None

            if use_skills:
                system_prompt = system_prompt + "\n\n" + build_tool_instructions()

            openai_input = [m for m in messages if m.get("role") != "system"]
            input_items = list(openai_input)
            previous_response_id = None
            max_steps = 6
            for _step in range(max_steps):
                with client.responses.stream(
                    model=model,
                    input=input_items,
                    tools=tools,
                    previous_response_id=previous_response_id,
                    instructions=system_prompt,
                ) as stream:
                    for event in stream:
                        if event.type in ("response.output_text.delta", "response.refusal.delta"):
                            yield event.delta
                        elif event.type == "response.error":
                            yield f"\n\n❌ OpenAI hatası: {getattr(event, 'error', event)}"
                    response = stream.get_final_response()

                tool_calls = [
                    item
                    for item in (getattr(response, "output", []) or [])
                    if getattr(item, "type", None) == "function_call"
                ]

                if not tool_calls:
                    if evidence_note and bool(st.session_state.get("include_evidence_note", True)):
                        yield "\n\n---\n" + evidence_note
                    return

                tool_outputs = []
                for tool_call in tool_calls:
                    name = getattr(tool_call, "name", "") or ""
                    arguments = getattr(tool_call, "arguments", "") or "{}"
                    call_id = getattr(tool_call, "call_id", None) or getattr(tool_call, "id", None)

                    if not call_id:
                        tool_outputs.append(
                            {
                                "type": "function_call_output",
                                "call_id": "missing_call_id",
                                "output": "Skill hata: tool call id bulunamadı.",
                            }
                        )
                        continue

                    try:
                        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
                        if not isinstance(args, dict):
                            args = {}
                        output = call_skill(name, args)
                    except Exception as e:
                        output = f"Skill hata: {type(e).__name__}: {e}"

                    tool_outputs.append(
                        {"type": "function_call_output", "call_id": call_id, "output": str(output)}
                    )

                previous_response_id = getattr(response, "id", None)
                input_items = tool_outputs

            yield "\n\n⚠️ Çok fazla araç çağrısı yapıldı, işlem durduruldu."
            if evidence_note and bool(st.session_state.get("include_evidence_note", True)):
                yield "\n\n---\n" + evidence_note
            return

        stream = ollama.chat(model=model, messages=messages, stream=True)
        for chunk in stream:
            if "message" in chunk and "content" in chunk["message"]:
                yield chunk["message"]["content"]
        if evidence_note and bool(st.session_state.get("include_evidence_note", True)):
            yield "\n\n---\n" + evidence_note
    except Exception as e:
        if provider == "openai":
            yield f"❌ OpenAI hatası: {e}"
        else:
            yield (
                f"❌ Ollama hatası: {e}\n\n"
                f"Lütfen Ollama'nın çalıştığından ve '{model}' modelinin yüklü "
                f"olduğundan emin olun.\nKomut: `ollama pull {model}`"
            )


@st.cache_data(show_spinner=False)
def get_available_models() -> list:
    """Sistemde yüklü Ollama modellerini listeler."""
    try:
        result = ollama.list()
        models = result.get("models", [])
        return [
            m.get("model", m.get("name", ""))
            for m in models
            if m.get("model") or m.get("name")
        ]
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def get_reviews() -> list:
    """Yorumları yükler ve cache'ler."""
    return load_reviews()


def run_app():
    # ---------------------------------------------------------------------------
    # Streamlit Sayfa Yapılandırması
    # ---------------------------------------------------------------------------

    st.set_page_config(
        page_title="Normal (2025) - Film Yorumu Chatbot",
        page_icon="🎬",
        layout="wide",
    )

    st.title("🎬 Normal (2025) - Film Yorumu Chatbot")
    st.caption("Rotten Tomatoes izleyici yorumlarına dayalı sohbet asistanı")

    # ---------------------------------------------------------------------------
    # Yorumları yükle
    # ---------------------------------------------------------------------------

    reviews = get_reviews()

    # ---------------------------------------------------------------------------
    # Kenar Çubuğu (Sidebar)
    # ---------------------------------------------------------------------------

    with st.sidebar:
        st.header("⚙️ Ayarlar")

        provider = st.selectbox("Provider", ["Ollama", "OpenAI"], index=0)
        st.session_state["provider"] = provider

        available_models = get_available_models()

        if provider == "OpenAI":
            st.caption("`OPENAI_API_KEY` env var veya Streamlit `secrets` kullanılacak.")
            st.checkbox("Agentic tools (skills)", value=True, key="agentic_tools_enabled")
            with st.expander("Skills"):
                for s in SKILLS:
                    st.markdown(f"- `{s['name']}`: {s['description']}")
            selected_model = st.text_input("OpenAI model", value=DEFAULT_OPENAI_MODEL)
        else:
            if available_models:
                default_index = (
                    available_models.index(DEFAULT_MODEL)
                    if DEFAULT_MODEL in available_models
                    else 0
                )
                selected_model = st.selectbox(
                    "Ollama Modeli",
                    available_models,
                    index=default_index,
                    help="Ollama'da yüklü modellerden birini seçin.",
                )
            else:
                st.warning(
                    "⚠️ Ollama'da yüklü model bulunamadı veya Ollama çalışmıyor. "
                    "Manuel olarak bir model adı girebilirsiniz."
                )
                selected_model = st.text_input("Model adı", value=DEFAULT_MODEL)

        st.divider()
        st.subheader("🔎 Vektör Arama (Anlık)")
        st.checkbox("Vektörle ilgili yorum seç", value=False, key="use_vector_search")
        st.slider("Top-K yorum", min_value=5, max_value=60, value=20, step=5, key="vector_top_k")
        st.checkbox("Cevaba kanıt notu ekle", value=True, key="include_evidence_note")

        st.divider()

        st.subheader("📊 Yorum Bilgisi")
        st.metric("Toplam Yorum", len(reviews))

        if reviews:
            ratings = [r.get("rating") for r in reviews if r.get("rating")]
            if ratings:
                try:
                    avg = sum(float(x) for x in ratings) / len(ratings)
                    st.metric("Ortalama Puan", f"{avg:.2f}")
                except (ValueError, TypeError):
                    pass

        st.divider()

        if st.button("🗑️ Sohbeti Temizle", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        with st.expander("📝 Yorumları Göster"):
            if reviews:
                for i, r in enumerate(reviews[:20], 1):
                    rating = r.get("rating", "")
                    rating_str = f" ⭐ {rating}" if rating else ""
                    st.markdown(
                        f"**{i}. {r.get('name', 'Anonim')}**{rating_str}\n\n"
                        f"{r.get('review', '')}"
                    )
                    st.divider()
            else:
                st.info("Henüz yorum yok.")

    # ---------------------------------------------------------------------------
    # Sohbet Mantığı
    # ---------------------------------------------------------------------------

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not reviews:
        st.warning(
            "⚠️ Yorum bulunamadı. Önce `scraper.py` ile yorumları çekmeniz gerekiyor."
        )

    # Geçmiş mesajları göster
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Kullanıcı girişi
    if prompt := st.chat_input("Film hakkında bir soru sor..."):
        # Kullanıcı mesajını göster ve kaydet
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Asistan yanıtı (streaming)
        with st.chat_message("assistant"):
            history = st.session_state.messages[:-1]  # son mesaj hariç tüm geçmiş
            response = st.write_stream(
                chat_stream(prompt, history, reviews, selected_model)
            )

        st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    run_app()
