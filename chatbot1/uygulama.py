"""
app.py
Streamlit arayüzü - Normal (2025) film yorumları chatbot'u.
Çalıştırmak için: streamlit run uygulama.py
"""

import os
import streamlit as st
try:
    from chatbot1.scraper import scrape_reviews, load_reviews, OUTPUT_FILE
    from chatbot1.chatbot1 import chat_stream, get_available_models, DEFAULT_MODEL
except ModuleNotFoundError:
    from scraper import scrape_reviews, load_reviews, OUTPUT_FILE
    from chatbot1 import chat_stream, get_available_models, DEFAULT_MODEL
try:
    from chatbot1.agent_skills import SKILLS
except ModuleNotFoundError:
    from agent_skills import SKILLS


# ============ SAYFA AYARLARI ============
st.set_page_config(
    page_title="🎬 Film Yorumu Chatbot",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============ ÖZEL CSS ============
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #e50914 0%, #b81d24 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .main-header h1 {
        color: white;
        margin: 0;
        font-size: 2.2rem;
    }
    .main-header p {
        color: #f5f5f5;
        margin: 0.5rem 0 0 0;
        font-size: 1rem;
    }
    .review-card {
        background: #f8f9fa;
        padding: 1rem;
        border-left: 4px solid #e50914;
        border-radius: 5px;
        margin-bottom: 0.8rem;
    }
    .review-name {
        font-weight: bold;
        color: #e50914;
    }
    .review-rating {
        color: #f5a623;
        font-weight: bold;
    }
    .stats-card {
        background: #1f1f1f;
        color: white;
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
    }
    div[data-testid="stChatMessage"] {
        padding: 0.8rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ============ BAŞLIK ============
st.markdown("""
<div class="main-header">
    <h1>🎬 Film Yorumu Chatbot</h1>
    <p>"Normal (2025)" filmi hakkında Rotten Tomatoes izleyici yorumlarına dayanarak sohbet edin.</p>
</div>
""", unsafe_allow_html=True)


# ============ SESSION STATE ============
if "messages" not in st.session_state:
    st.session_state.messages = []

if "reviews" not in st.session_state:
    st.session_state.reviews = load_reviews()


# ============ YAN PANEL ============
with st.sidebar:
    st.markdown("### ⚙️ Ayarlar")

    provider = st.selectbox("Provider", ["Ollama", "OpenAI"], index=0)
    st.session_state["provider"] = provider

    # Model seçimi
    if provider == "OpenAI":
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or st.secrets.get("OPENAI_API_KEY", "")  # type: ignore[attr-defined]
        if not api_key:
            st.error("`OPENAI_API_KEY` bulunamadı (env var veya Streamlit secrets).")
        st.checkbox("Agentic tools (skills)", value=True, key="agentic_tools_enabled")
        with st.expander("Skills"):
            for s in SKILLS:
                st.markdown(f"- `{s['name']}`: {s['description']}")
        selected_model = st.text_input("🤖 OpenAI Modeli", value=os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1")
    else:
        available_models = get_available_models()
        if available_models:
            default_idx = available_models.index(DEFAULT_MODEL) if DEFAULT_MODEL in available_models else 0
            selected_model = st.selectbox(
                "🤖 Ollama Modeli",
                options=available_models,
                index=default_idx,
                help="Lokal Ollama'da yüklü modeller"
            )
        else:
            st.warning("⚠️ Ollama'ya bağlanılamadı veya yüklü model yok.")
            st.info("Terminalde şunu çalıştırın: `ollama pull llama3.2`")
            selected_model = st.text_input("Model adı", value=DEFAULT_MODEL)

    st.markdown("---")
    st.markdown("### 🔎 Vektör Arama (Anlık)")
    st.checkbox("Vektörle ilgili yorum seç", value=False, key="use_vector_search")
    st.slider("Top-K yorum", min_value=5, max_value=60, value=20, step=5, key="vector_top_k")
    st.checkbox("Cevaba kanıt notu ekle", value=True, key="include_evidence_note")

    st.markdown("---")

    # Scraping bölümü
    st.markdown("### 🔄 Yorumları Güncelle")
    max_clicks = st.slider("Yüklenecek 'Load More' sayısı", 1, 20, 5,
                           help="Daha fazla = daha çok yorum, ama daha yavaş.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 Yorumları Çek", use_container_width=True):
            with st.spinner("Yorumlar çekiliyor... (1-2 dakika sürebilir)"):
                try:
                    reviews = scrape_reviews(max_clicks=max_clicks, headless=True)
                    st.session_state.reviews = reviews
                    st.success(f"✅ {len(reviews)} yorum çekildi!")
                except Exception as e:
                    st.error(f"❌ Hata: {e}")

    with col2:
        if st.button("🗑️ Sohbeti Temizle", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    st.markdown("---")

    # İstatistikler
    st.markdown("### 📊 İstatistikler")
    review_count = len(st.session_state.reviews)
    file_exists = "✅" if os.path.exists(OUTPUT_FILE) else "❌"

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Yorum Sayısı", review_count)
    with col_b:
        st.metric("Veri Dosyası", file_exists)

    st.markdown("---")

    # Yorum önizleme
    if st.session_state.reviews:
        with st.expander("📝 Çekilen Yorumları Görüntüle"):
            for i, r in enumerate(st.session_state.reviews[:10], 1):
                rating = r.get("rating", "")
                st.markdown(f"""
                <div class="review-card">
                    <div><span class="review-name">{i}. {r.get('name', 'Anonim')}</span>
                    <span class="review-rating">{rating}</span></div>
                    <div style="margin-top: 0.5rem; font-size: 0.9rem;">
                        {r.get('review', '')[:250]}{'...' if len(r.get('review', '')) > 250 else ''}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            if len(st.session_state.reviews) > 10:
                st.caption(f"... ve {len(st.session_state.reviews) - 10} yorum daha.")


# ============ ANA SOHBET ALANI ============
if not st.session_state.reviews:
    st.warning("⚠️ Henüz yorum çekilmemiş. Soldaki **'📥 Yorumları Çek'** butonuna tıklayın.")
    st.info("""
    **Başlamadan önce:**
    1. Ollama'nın yüklü ve çalışır durumda olduğundan emin olun → [ollama.com](https://ollama.com)
    2. Bir model indirin: terminalde `ollama pull llama3.2`
    3. Soldaki butondan yorumları çekin
    4. Sohbete başlayın!
    """)
else:
    st.success(f"✅ {len(st.session_state.reviews)} izleyici yorumu hazır. Sorunuzu yazın!")

    # Önerilen sorular
    st.markdown("**💡 Örnek sorular:**")
    suggestion_cols = st.columns(3)
    suggestions = [
        "Film hakkında genel izlenim nedir?",
        "İzleyiciler neyi beğenmiş?",
        "Olumsuz yorumlarda ne diyorlar?"
    ]
    for col, sug in zip(suggestion_cols, suggestions):
        if col.button(sug, use_container_width=True):
            st.session_state.pending_question = sug

    st.markdown("---")

    # Sohbet geçmişini göster
    for msg in st.session_state.messages:
        avatar = "🧑" if msg["role"] == "user" else "🎬"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Pending question varsa kullan, yoksa input al
    user_input = None
    if "pending_question" in st.session_state:
        user_input = st.session_state.pending_question
        del st.session_state.pending_question

    chat_input = st.chat_input("Film hakkında bir şey sorun...")
    if chat_input:
        user_input = chat_input

    if user_input:
        # Kullanıcı mesajını göster
        with st.chat_message("user", avatar="🧑"):
            st.markdown(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        # Bot yanıtını streaming ile göster
        with st.chat_message("assistant", avatar="🎬"):
            placeholder = st.empty()
            full_response = ""

            try:
                # Önceki mesajları (son 10 tanesini) gönder
                history = st.session_state.messages[:-1][-10:]

                for chunk in chat_stream(user_input, history, st.session_state.reviews, model=selected_model):
                    full_response += chunk
                    placeholder.markdown(full_response + "▌")

                placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"❌ Bir hata oluştu: {e}"
                placeholder.error(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})


# ============ FOOTER ============
st.markdown("---")
st.caption("🎬 Film Yorumu Chatbot | Veri: Rotten Tomatoes | Model: Lokal Ollama")
