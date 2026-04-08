"""Tests for quirk_extractor — pure statistical text analysis."""

import pytest

from tools.quirk_extractor import extract_quirks

SAMPLE_QUOTES = [
    {"id": 1, "text": "你有 freestyle 吗"},
    {"id": 2, "text": "我觉得这个很 real"},
    {"id": 3, "text": "skr skr skr"},
    {"id": 4, "text": "其实我是一个很 chill 的人"},
    {"id": 5, "text": "你看这个面它又长又宽"},
    {"id": 6, "text": "我觉得挺 real 的吧"},
]


class TestLanguageMix:
    def test_language_mix_sums_to_one(self):
        result = extract_quirks(SAMPLE_QUOTES)
        mix = result["language_mix"]
        assert pytest.approx(mix["cn"] + mix["en"], abs=1e-6) == 1.0

    def test_language_mix_cn_dominant(self):
        result = extract_quirks(SAMPLE_QUOTES)
        assert result["language_mix"]["cn"] > result["language_mix"]["en"]


class TestAvgSentenceLength:
    def test_avg_sentence_length_positive(self):
        result = extract_quirks(SAMPLE_QUOTES)
        assert result["avg_sentence_length"] > 0

    def test_avg_sentence_length_reasonable(self):
        result = extract_quirks(SAMPLE_QUOTES)
        # Average should be between 3 and 20 for these quotes
        assert 3 < result["avg_sentence_length"] < 20


class TestToneParticles:
    def test_detects_ba(self):
        result = extract_quirks(SAMPLE_QUOTES)
        assert "吧" in result["tone_particles"]
        assert result["tone_particles"]["吧"] >= 1

    def test_detects_skr(self):
        result = extract_quirks(SAMPLE_QUOTES)
        assert "skr" in result["tone_particles"]
        assert result["tone_particles"]["skr"] >= 3


class TestSentenceTypes:
    def test_sentence_types_sum_to_one(self):
        result = extract_quirks(SAMPLE_QUOTES)
        types = result["sentence_types"]
        total = sum(types.values())
        assert pytest.approx(total, abs=1e-6) == 1.0

    def test_has_all_three_types(self):
        result = extract_quirks(SAMPLE_QUOTES)
        types = result["sentence_types"]
        for key in ("statement", "question", "exclamation"):
            assert key in types


class TestFrequentEnPhrases:
    def test_detects_real(self):
        result = extract_quirks(SAMPLE_QUOTES)
        phrases = result["frequent_en_phrases"]
        phrase_words = [p["phrase"] for p in phrases]
        assert "real" in phrase_words

    def test_real_count_at_least_two(self):
        result = extract_quirks(SAMPLE_QUOTES)
        phrases = result["frequent_en_phrases"]
        real_entry = next(p for p in phrases if p["phrase"] == "real")
        assert real_entry["count"] >= 2

    def test_excludes_common_words(self):
        result = extract_quirks(SAMPLE_QUOTES)
        phrases = result["frequent_en_phrases"]
        phrase_words = [p["phrase"] for p in phrases]
        for common in ("a", "the", "is", "i", "you", "my", "and"):
            assert common not in phrase_words


class TestEmptyInput:
    def test_empty_input_returns_zeroed_structure(self):
        result = extract_quirks([])
        assert result["language_mix"] == {"cn": 0.0, "en": 0.0}
        assert result["avg_sentence_length"] == 0.0
        assert result["tone_particles"] == {}
        assert result["sentence_types"] == {"statement": 0.0, "question": 0.0, "exclamation": 0.0}
        assert result["frequent_en_phrases"] == []
