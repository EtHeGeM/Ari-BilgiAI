# ArıBilgi Örnek Proje Koleksiyonu

Bu repo, aynı klasör altında birden fazla küçük deneme/proje içerir.

## Klasörler

- `chatbot/`: Film/critic yorumlarından RAG chatbot (LangChain + Ollama + Chroma).
- `text/`: YouTube yorum scrape + duygu analizi + basit Q&A araçları.
- `youtube/`, `opencv/`, `TrafikTanıma/`, `Movie/`, `Kuru Temizlemeci/`, `su_seviye/`: Diğer örnek çalışmalar.

## Çıktılar

- `outputs/`: CLI’ların ürettiği CSV vb. çıktılar (git’te takip edilmez).
- `chatbot/data/film_yorumlar.txt`: Chatbot’un kullandığı yorum metni (git’te takip edilmez).

## Temizlik

Cache temizliği için:

```bash
./scripts/cleanup_repo.sh
```

## Chatbot API

API’yi çalıştırmak için (örnek):

```bash
pip install -r chatbot/requirements.txt
uvicorn chatbot.api_server:app --host 127.0.0.1 --port 8000
```

Otomatik çalıştırma (venv + install + run):

```bash
./scripts/run_chatbot_api.sh
```

Index + soru sormak için:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/ask \\
  -H 'content-type: application/json' \\
  -d '{\"url\":\"https://www.rottentomatoes.com/m/normal_2025#critics-reviews\",\"question\":\"Eleştirmenler en çok neyi övüyor?\"}'
```

Film arama:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/search \\
  -H 'content-type: application/json' \\
  -d '{\"query\":\"normal\",\"limit\":5}'
```

Film açıklaması (synopsis):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/describe \\
  -H 'content-type: application/json' \\
  -d '{\"url\":\"https://www.rottentomatoes.com/m/captain_america_civil_war_reenactors\"}'
```

Vectordb retrieve (RAG kanıtlarını getir):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/retrieve \\
  -H 'content-type: application/json' \\
  -d '{\"url\":\"https://www.rottentomatoes.com/m/normal_2025#critics-reviews\",\"query\":\"pacing\",\"top_k\":5}'
```

RottenTomatoes ham review çekme:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/rt/reviews \\
  -H 'content-type: application/json' \\
  -d '{\"url\":\"https://www.rottentomatoes.com/m/normal_2025\",\"kind\":\"critic\",\"top_only\":false,\"limit\":5}'
```

## Agent (toolcalling)

Tool listesi:

```bash
curl -s http://127.0.0.1:8000/v1/agent/tools
```

Agent chat (tool call döngüsü):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/agent/chat \\
  -H 'content-type: application/json' \\
  -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Search Normal on Rotten Tomatoes and summarize the synopsis.\"}],\"max_steps\":6}'
```

## Notlar

- Ollama lokalde çalışmalı (varsayılan port `11434`).
