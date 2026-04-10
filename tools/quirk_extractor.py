"""Pure statistical text analysis for idol quotes — no LLM involved.

Takes a list of quote dicts (with "text" field) and outputs language mix,
average sentence length, tone particles, sentence types, and frequent
English phrases.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EN_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")

TONE_PARTICLES_CN: set[str] = {"吧", "呢", "嘛", "啊", "哦", "呀", "噢", "嗯", "哈", "诶", "哎"}
TONE_PARTICLES_EN: set[str] = {"yo", "man", "bro", "skr", "uh", "yeah", "ok"}

COMMON_EN_WORDS: set[str] = {
    "a", "the", "is", "am", "are", "i", "you", "he", "she", "it",
    "we", "they", "my", "your", "and", "or", "but", "in", "on", "at",
    "to", "for", "of", "with", "not", "no", "do", "don", "t", "s",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _language_mix(texts: list[str]) -> dict[str, float]:
    """Return ratio of CJK chars vs ASCII-word chars."""
    cn_count = 0
    en_count = 0
    for text in texts:
        cn_count += len(CJK_RE.findall(text))
        for word in EN_WORD_RE.findall(text):
            en_count += len(word)
    total = cn_count + en_count
    if total == 0:
        return {"cn": 0.0, "en": 0.0}
    return {"cn": cn_count / total, "en": en_count / total}


def _avg_sentence_length(texts: list[str]) -> float:
    """Average character count per quote (whitespace excluded)."""
    if not texts:
        return 0.0
    lengths = [len(t.replace(" ", "")) for t in texts]
    return sum(lengths) / len(lengths)


def _tone_particles(texts: list[str]) -> dict[str, int]:
    """Count Chinese single-char particles and English tone words."""
    counter: Counter[str] = Counter()
    for text in texts:
        # Chinese: per-character scan
        for ch in text:
            if ch in TONE_PARTICLES_CN:
                counter[ch] += 1
        # English: per-word scan
        for word in EN_WORD_RE.findall(text):
            w_lower = word.lower()
            if w_lower in TONE_PARTICLES_EN:
                counter[w_lower] += 1
    return dict(counter)


def _sentence_types(texts: list[str]) -> dict[str, float]:
    """Classify quotes by trailing punctuation."""
    if not texts:
        return {"statement": 0.0, "question": 0.0, "exclamation": 0.0}
    counts = {"statement": 0, "question": 0, "exclamation": 0}
    for text in texts:
        stripped = text.rstrip()
        if stripped.endswith("?") or stripped.endswith("\uff1f"):
            counts["question"] += 1
        elif stripped.endswith("!") or stripped.endswith("\uff01"):
            counts["exclamation"] += 1
        else:
            counts["statement"] += 1
    total = len(texts)
    return {k: v / total for k, v in counts.items()}


def _frequent_en_phrases(texts: list[str], min_count: int = 2) -> list[dict[str, Any]]:
    """English words appearing >= min_count times, excluding common words."""
    counter: Counter[str] = Counter()
    for text in texts:
        for word in EN_WORD_RE.findall(text):
            w_lower = word.lower()
            if w_lower not in COMMON_EN_WORDS and w_lower not in TONE_PARTICLES_EN:
                counter[w_lower] += 1
    results = [
        {"phrase": phrase, "count": count}
        for phrase, count in counter.most_common()
        if count >= min_count
    ]
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _data_quality(tone_particles: dict[str, int], avg_len: float) -> dict[str, Any]:
    """Flag likely edited/second-hand sources based on oral speech markers.

    Real oral speech has high tone-particle density and longer avg sentence
    length (due to self-corrections, repetitions, fillers).  Edited quotes
    strip these out, producing clean short sentences with almost no particles.
    """
    total_particles = sum(tone_particles.values())
    if total_particles < 5 and avg_len < 30:
        return {
            "flag": "likely_edited_source",
            "detail": (
                f"语气词仅 {total_particles} 个且平均句长 {avg_len:.1f} 字——"
                "疑似经过编辑的二手语录，口语特征可能丢失。"
                "建议补充 B站视频字幕数据。"
            ),
        }
    return {"flag": "ok", "detail": None}


def extract_quirks(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyse a list of quote dicts and return statistical quirks.

    Each quote dict must contain a "text" field.
    """
    texts = [q["text"] for q in quotes]
    tone = _tone_particles(texts)
    avg_len = _avg_sentence_length(texts)
    return {
        "language_mix": _language_mix(texts),
        "avg_sentence_length": avg_len,
        "tone_particles": tone,
        "sentence_types": _sentence_types(texts),
        "frequent_en_phrases": _frequent_en_phrases(texts),
        "data_quality": _data_quality(tone, avg_len),
    }
