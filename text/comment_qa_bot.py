from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Comment:
    comment_id: str
    text: str
    label: str | None = None
    polarity: float | None = None


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def load_comments(csv_path: str, *, text_col: str = "text") -> list[Comment]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        out: list[Comment] = []
        for row in r:
            txt = (row.get(text_col) or "").strip()
            if not txt:
                continue
            out.append(
                Comment(
                    comment_id=str(row.get("comment_id") or row.get("id") or ""),
                    text=txt,
                    label=(row.get("label") or "").strip() or None,
                    polarity=_safe_float(row.get("polarity")),
                )
            )
    return out


def analyze_overall_sentiment(comments: list[Comment]) -> dict[str, Any]:
    if not comments:
        return {
            "comment_count": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "avg_polarity": None,
        }

    pos = sum(1 for c in comments if c.label == "positive")
    neu = sum(1 for c in comments if c.label == "neutral")
    neg = sum(1 for c in comments if c.label == "negative")
    pols = [c.polarity for c in comments if c.polarity is not None]
    avg_pol = (sum(pols) / len(pols)) if pols else None
    return {
        "comment_count": len(comments),
        "positive": pos,
        "neutral": neu,
        "negative": neg,
        "avg_polarity": avg_pol,
    }


def sumy_summary(comments: list[Comment], *, sentences: int = 6, language: str = "english") -> str:
    texts = [c.text.strip() for c in comments if c.text.strip()]
    if not texts:
        return ""

    document_text = "\n".join(texts)
    # sumy + punkt bazı ortamlarda hassas; youtube_comment_sentiment.py ile aynı yaklaşım
    from sumy.nlp.tokenizers import Tokenizer  # type: ignore
    from sumy.parsers.plaintext import PlaintextParser  # type: ignore
    from sumy.summarizers.lsa import LsaSummarizer  # type: ignore

    def _run() -> str:
        parser = PlaintextParser.from_string(document_text, Tokenizer(language))
        summarizer = LsaSummarizer()
        out = [str(s) for s in summarizer(parser.document, max(1, int(sentences)))]
        return " ".join(out).strip()

    try:
        return _run()
    except LookupError:
        import nltk  # type: ignore

        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
        return _run()


class CommentRetriever:
    def __init__(self, comments: list[Comment], *, language: str = "english"):
        try:
            import numpy as np  # noqa: F401
            from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
        except Exception as e:
            raise RuntimeError("scikit-learn yüklü değil. `pip install -r text/requirements.txt`") from e

        self._comments = comments
        stop_words = "english" if language.lower().startswith("en") else None
        self._vectorizer = TfidfVectorizer(stop_words=stop_words, ngram_range=(1, 2), max_features=20_000)
        self._x = self._vectorizer.fit_transform([c.text for c in comments])

    def search(self, query: str, *, top_k: int = 8) -> list[tuple[float, Comment]]:
        import numpy as np  # type: ignore

        q = (query or "").strip()
        if not q:
            return []
        qv = self._vectorizer.transform([q])
        # cosine similarity for tf-idf is dot product (vectors are L2-normalized by default)
        scores = (self._x @ qv.T).toarray().reshape(-1)
        idx = np.argsort(scores)[::-1][: int(top_k)]
        out: list[tuple[float, Comment]] = []
        for i in idx.tolist():
            s = float(scores[i])
            if s <= 0:
                continue
            out.append((s, self._comments[i]))
        return out

    def top_terms_for_subset(self, subset: list[Comment], *, top_n: int = 8) -> list[str]:
        import numpy as np  # type: ignore

        if not subset:
            return []
        x = self._vectorizer.transform([c.text for c in subset])
        weights = np.asarray(x.mean(axis=0)).reshape(-1)
        feats = self._vectorizer.get_feature_names_out()
        idx = np.argsort(weights)[::-1][: int(top_n)]
        return [str(feats[i]) for i in idx.tolist() if weights[i] > 0]


def _ollama_generate(*, model: str, prompt: str, timeout_s: int = 180) -> str:
    if not shutil.which("ollama"):
        raise RuntimeError("ollama bulunamadı. Kurulum: https://ollama.com/ (sonra `ollama pull <model>`).")
    try:
        proc = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=int(timeout_s),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ollama timeout ({timeout_s}s). Model indiriliyorsa daha uzun timeout deneyin.") from e

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise RuntimeError(f"ollama error (code={proc.returncode}): {err or out or 'unknown'}")
    return out


def answer_question_with_ollama(
    question: str,
    *,
    retriever: CommentRetriever,
    all_comments: list[Comment],
    model: str,
    top_k: int = 8,
    summary_sentences: int = 6,
    timeout_s: int = 180,
    language: str = "english",
) -> dict[str, Any]:
    hits = retriever.search(question, top_k=top_k)
    subset = [c for _s, c in hits]
    subset_stats = analyze_overall_sentiment(subset)
    overall_stats = analyze_overall_sentiment(all_comments)
    overall_sumy = sumy_summary(all_comments, sentences=summary_sentences, language=language)

    evidence_lines = []
    for score, c in hits:
        evidence_lines.append(
            f"- id={c.comment_id or 'n/a'} score={score:.3f} label={c.label or 'n/a'} polarity={c.polarity if c.polarity is not None else 'n/a'}\n"
            f"  text={c.text.replace(chr(10), ' ').replace(chr(13), ' ')[:500]}"
        )

    prompt = (
        "You are a strict Q&A assistant that answers questions ONLY using the provided YouTube comments.\n"
        "Rules (very important):\n"
        "- Use ONLY the content in 'Evidence Comments' and 'Overall Summary'. Do NOT use outside knowledge.\n"
        "- If the information is not present, say: \"This is not mentioned in the comments.\" (in Turkish).\n"
        "- Do NOT invent details about the video, the creator, dates, numbers, or facts.\n"
        "- When you make a claim, cite supporting comment ids like: [id=...].\n"
        "- Keep the answer short and concrete. Prefer quoting/paraphrasing what commenters said.\n"
        "- Output language: English.\n\n"
        f"Genel Duygu (ilk {overall_stats['comment_count']} yorum): "
        f"+{overall_stats['positive']} / ={overall_stats['neutral']} / -{overall_stats['negative']}"
        + (f" | avg_polarity={overall_stats['avg_polarity']:.3f}\n" if overall_stats["avg_polarity"] is not None else "\n")
        + "Genel Özet (Sumy/LSA):\n"
        + (overall_sumy or "(boş)")[:3000]
        + "\n\n"
        + "Soru:\n"
        + question.strip()
        + "\n\n"
        + "Evidence Comments (most relevant):\n"
        + ("\n".join(evidence_lines) if evidence_lines else "(hiçbiri)")
        + "\n\n"
        + "Required output format:\n"
        + "1) Kısa cevap (2-6 cümle)\n"
        + "2) Duygu özeti (bu soruya yakın yorumlar için): +/=/-, avg_polarity\n"
        + "3) Dayanak yorum id'leri: [id=..., id=...]\n"
    )

    answer = _ollama_generate(model=model, prompt=prompt, timeout_s=timeout_s)
    evidence = [
        {
            "score": score,
            "comment_id": c.comment_id,
            "label": c.label,
            "polarity": c.polarity,
            "text": c.text[:400].replace("\n", " ").replace("\r", " "),
        }
        for score, c in hits
    ]

    # model çıktısını bozmadan, istatistikleri ayrıca döndür
    return {
        "answer": answer.strip(),
        "evidence": evidence,
        "subset_sentiment": subset_stats,
        "overall_sentiment": overall_stats,
    }


def answer_question(
    question: str,
    *,
    retriever: CommentRetriever,
    all_comments: list[Comment],
    top_k: int = 8,
) -> dict[str, Any]:
    hits = retriever.search(question, top_k=top_k)
    subset = [c for _s, c in hits]
    subset_stats = analyze_overall_sentiment(subset)
    overall_stats = analyze_overall_sentiment(all_comments)
    top_terms = retriever.top_terms_for_subset(subset, top_n=8)

    # "çok basit dil modeli": retrieval + kısa sentez + kanıt örnekleri
    response_lines = []
    response_lines.append("Yorumlara göre kısa cevap:")
    if subset:
        if top_terms:
            response_lines.append(f"- Öne çıkan ifadeler: {', '.join(top_terms[:8])}")
        if subset_stats.get("avg_polarity") is not None:
            response_lines.append(
                f"- Bu konuya yakın yorumlarda ortalama duygu (polarity): {subset_stats['avg_polarity']:.3f}"
            )
        response_lines.append(
            f"- Yakın yorum duygu dağılımı: +{subset_stats['positive']} / ={subset_stats['neutral']} / -{subset_stats['negative']}"
        )
    else:
        response_lines.append("- Bu soruya doğrudan benzeyen yorum bulamadım; genel özet/durum aşağıda.")

    response_lines.append(
        f"Genel duygu dağılımı (tüm {overall_stats['comment_count']} yorum): "
        f"+{overall_stats['positive']} / ={overall_stats['neutral']} / -{overall_stats['negative']}"
    )

    evidence = [
        {
            "score": score,
            "comment_id": c.comment_id,
            "label": c.label,
            "polarity": c.polarity,
            "text": c.text[:400].replace("\n", " ").replace("\r", " "),
        }
        for score, c in hits
    ]

    return {
        "answer": "\n".join(response_lines),
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Very simple Q&A bot over YouTube comments (retrieval-based).")
    ap.add_argument("--comments", required=True, help="CSV path (e.g., comments_sentiment.csv or out.csv)")
    ap.add_argument("--question", default="", help="Ask a single question (non-interactive)")
    ap.add_argument("--lang", default="english", help="Tokenizer/stopwords language hint (english|turkish|...)")
    ap.add_argument("--top-k", type=int, default=8, help="How many comments to retrieve per question")
    ap.add_argument("--summary-out", default="", help="Write overall summary CSV (optional)")
    ap.add_argument("--summary-sentences", type=int, default=6, help="Sumy sentence count for overall summary")
    ap.add_argument("--ollama-model", default="", help="If set, use Ollama for answer generation (e.g. llama3.1)")
    ap.add_argument("--ollama-timeout", type=int, default=180, help="Ollama timeout seconds")
    args = ap.parse_args(argv)

    comments = load_comments(args.comments)
    if not comments:
        print("No comments loaded from CSV.", file=sys.stderr)
        return 2

    # optional overall summary export
    if (args.summary_out or "").strip():
        summ = sumy_summary(comments[:200], sentences=int(args.summary_sentences or 6), language=args.lang)
        stats = analyze_overall_sentiment(comments[:200])
        with open(args.summary_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "comment_count",
                    "positive",
                    "neutral",
                    "negative",
                    "avg_polarity",
                    "sumy_summary",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "comment_count": stats["comment_count"],
                    "positive": stats["positive"],
                    "neutral": stats["neutral"],
                    "negative": stats["negative"],
                    "avg_polarity": f"{stats['avg_polarity']:.6f}" if stats["avg_polarity"] is not None else "",
                    "sumy_summary": summ,
                }
            )

    retriever = CommentRetriever(comments[:200], language=args.lang)

    if (args.question or "").strip():
        if (args.ollama_model or "").strip():
            result = answer_question_with_ollama(
                args.question,
                retriever=retriever,
                all_comments=comments[:200],
                model=args.ollama_model.strip(),
                top_k=int(args.top_k),
                summary_sentences=int(args.summary_sentences or 6),
                timeout_s=int(args.ollama_timeout or 180),
                language=args.lang,
            )
        else:
            result = answer_question(args.question, retriever=retriever, all_comments=comments[:200], top_k=int(args.top_k))
        print(result["answer"])
        print("\nKanıt (en alakalı yorumlar):")
        for ev in result["evidence"][: int(args.top_k)]:
            print(f"- ({ev['score']:.3f}) [{ev.get('label')}] {ev['text']}")
        return 0

    # interactive loop
    print("Comment Q&A bot. Çıkmak için boş soru gönder.")
    while True:
        try:
            q = input("\nSoru> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            return 0
        if (args.ollama_model or "").strip():
            result = answer_question_with_ollama(
                q,
                retriever=retriever,
                all_comments=comments[:200],
                model=args.ollama_model.strip(),
                top_k=int(args.top_k),
                summary_sentences=int(args.summary_sentences or 6),
                timeout_s=int(args.ollama_timeout or 180),
                language=args.lang,
            )
        else:
            result = answer_question(q, retriever=retriever, all_comments=comments[:200], top_k=int(args.top_k))
        print("\n" + result["answer"])
        print("\nKanıt (en alakalı yorumlar):")
        for ev in result["evidence"][: int(args.top_k)]:
            print(f"- ({ev['score']:.3f}) [{ev.get('label')}] {ev['text']}")


if __name__ == "__main__":
    raise SystemExit(main())
