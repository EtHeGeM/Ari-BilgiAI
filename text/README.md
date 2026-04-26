# YouTube Comment Sentiment (TextBlob)

Bu klasör, **YouTube yorumlarını scrape edip** (`yt-dlp`) **TextBlob** ile basit duygu analizi yapan küçük bir CLI içerir.

## Kurulum

Bağımlılıkları kurun:

```bash
pip install -r text/requirements.txt
```

## Kullanım

Bir video URL’si veya video id ile:

```bash
python3 text/youtube_comment_sentiment.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --max-comments 300 --out outputs/out.csv
```

Reply’leri de dahil etmek için:

```bash
python3 text/youtube_comment_sentiment.py --url "VIDEO_ID" --max-comments 300 --include-replies --out outputs/out.csv
```

Cookie gerekiyorsa (YouTube consent/login durumları için):

```bash
python3 text/youtube_comment_sentiment.py --url "VIDEO_ID" --max-comments 300 --cookies-from-browser chrome --out outputs/out.csv
```

Semantic extraction (tema özetleri) için:

```bash
python3 text/youtube_comment_sentiment.py --url "VIDEO_ID" --max-comments 200 --themes 5 --themes-out outputs/themes.csv
```

Sumy ile (LSA) metin özetleme için:

```bash
python3 text/youtube_comment_sentiment.py --url "VIDEO_ID" --max-comments 200 --sumy-out outputs/sumy_summary.csv --sumy-sentences 5
python -m nltk.downloader punkt
python -m nltk.downloader punkt_tab
```

İlk 10 yorumu tek tek 1 cümleyle özetlemek için:

```bash
python3 text/youtube_comment_sentiment.py --url "VIDEO_ID" --max-comments 200 --sumy-per-comment-out outputs/per_comment_summary.csv --sumy-per-comment-limit 10
```

## Basit Soru-Cevap (200 yorum üzerinden)

Yorumlar üzerinden çok basit bir “dil modeli” (retrieval tabanlı) ile soru cevap:

```bash
python3 text/comment_qa_bot.py --comments outputs/comments_sentiment.csv
```

Tek seferlik soru:

```bash
python3 text/comment_qa_bot.py --comments outputs/comments_sentiment.csv --question "İnsanlar en çok neyden şikayet ediyor?"
```

Ollama ile daha doğal cevap üretmek için:

```bash
ollama pull llama3.1
python3 text/comment_qa_bot.py --comments outputs/comments_sentiment.csv --ollama-model llama3.1
```

Özet CSV üretmek isterseniz:

```bash
python3 text/comment_qa_bot.py --comments outputs/comments_sentiment.csv --summary-out outputs/qa_overview.csv
```

## Notlar

- TextBlob duygu modeli İngilizce için daha anlamlı sonuç verir; Türkçe yorumlarda doğruluk sınırlı olabilir.
- Scrape işlemi YouTube tarafındaki değişikliklere bağlı olarak zaman zaman bozulabilir; bazı videolarda cookie gerekebilir.
