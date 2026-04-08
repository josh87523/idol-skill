"""Tests for quote_parser — TDD: written before implementation."""

from tools.quote_parser import parse_quotes


# ── 1. Plain text ────────────────────────────────────────────────
def test_parse_plain_text():
    raw = "我会努力的\n请多多关照"
    result = parse_quotes(raw)
    assert len(result) == 2
    assert result[0]["text"] == "我会努力的"
    assert result[0]["source"] is None
    assert result[0]["source_url"] is None
    assert result[0]["context"] == "未知"
    assert result[0]["confirmed"] is True
    assert result[1]["text"] == "请多多关照"


# ── 2. Source annotation ─────────────────────────────────────────
def test_parse_with_source_annotation():
    raw = '"我会一直唱下去" — 2024演唱会'
    result = parse_quotes(raw)
    assert len(result) == 1
    assert result[0]["text"] == "我会一直唱下去"
    assert result[0]["source"] == "2024演唱会"


# ── 3. Empty lines skipped ───────────────────────────────────────
def test_parse_empty_lines_skipped():
    raw = "第一句\n\n\n第二句\n   \n第三句"
    result = parse_quotes(raw)
    assert len(result) == 3
    texts = [q["text"] for q in result]
    assert texts == ["第一句", "第二句", "第三句"]


# ── 4. Context tag ───────────────────────────────────────────────
def test_parse_with_context_tag():
    raw = "[综艺] 我觉得可以\n[采访] 谢谢大家"
    result = parse_quotes(raw)
    assert result[0]["context"] == "综艺"
    assert result[0]["text"] == "我觉得可以"
    assert result[1]["context"] == "采访"
    assert result[1]["text"] == "谢谢大家"


# ── 5. Fan fiction contexts ──────────────────────────────────────
def test_parse_fan_fiction_context():
    raw = "[同人文] 他转过身去\n[捡手机文学] 我不是故意看到的"
    result = parse_quotes(raw)
    assert result[0]["context"] == "同人文"
    assert result[0]["text"] == "他转过身去"
    assert result[1]["context"] == "捡手机文学"
    assert result[1]["text"] == "我不是故意看到的"


# ── 6. Auto-increment IDs ───────────────────────────────────────
def test_id_auto_increment():
    raw = "a\nb\nc"
    result = parse_quotes(raw)
    ids = [q["id"] for q in result]
    assert ids == [1, 2, 3]
