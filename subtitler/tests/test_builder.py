"""Tests for the subtitler builder + renderers."""
from __future__ import annotations

from subtitler.builder import (
    MIN_DUR_S,
    _fmt_ass_time,
    _fmt_srt_time,
    build_clips,
    render_ass,
    render_srt,
)
from subtitler.contracts import SubtitleStyle


def _t(language="es", duration=10.0, segments=None):
    return {
        "schema_version": "1.0",
        "language": language,
        "duration_s": duration,
        "segments": segments or [],
    }


def _seg(words):
    return {"start_s": None, "end_s": None, "text": " ".join(w["text"] for w in words),
            "words": words, "no_speech_prob": 0.0}


def _w(text, s, e):
    return {"text": text, "start_s": s, "end_s": e, "probability": 0.99}


def test_flatten_words_in_order():
    tp = _t(segments=[_seg([_w("hola", 0.0, 0.4), _w("mundo", 0.4, 0.9)]),
                      _seg([_w("ya", 1.0, 1.2)])])
    out = build_clips(tp)
    assert [c.text for c in out.clips] == ["hola", "mundo", "ya"]
    assert [c.index for c in out.clips] == [1, 2, 3]
    assert out.clips[0].segment_index == 0
    assert out.clips[2].segment_index == 1
    assert out.language == "es"


def test_drops_empty_text_and_missing_timestamps():
    tp = _t(segments=[_seg([
        _w("ok", 0.0, 0.3),
        _w("", 0.3, 0.4),                # empty → dropped silently
        _w("nope", None, 0.6),           # missing start → noted
        _w("end", 0.7, 0.9),
    ])])
    out = build_clips(tp)
    assert [c.text for c in out.clips] == ["ok", "end"]
    assert any("nope" in n for n in out.notes)


def test_end_clamped_to_next_word_start():
    tp = _t(segments=[_seg([
        _w("a", 0.0, 0.5),     # accidental overlap with b
        _w("b", 0.4, 0.8),
    ])])
    out = build_clips(tp)
    assert out.clips[0].end_s == 0.4   # clamped
    assert out.clips[1].end_s == 0.8


def test_micro_gap_filled_to_next():
    tp = _t(segments=[_seg([
        _w("a", 0.0, 0.30),
        _w("b", 0.32, 0.50),    # 20ms gap → fill
    ])])
    out = build_clips(tp)
    assert out.clips[0].end_s == 0.32


def test_min_duration_floor():
    # word would be 30ms long but next word starts well after → floor to MIN_DUR_S
    tp = _t(segments=[_seg([
        _w("a", 0.0, 0.03),
        _w("b", 1.0, 1.2),
    ])])
    out = build_clips(tp)
    assert out.clips[0].end_s >= 0.0 + MIN_DUR_S


def test_drops_negative_duration():
    tp = _t(segments=[_seg([_w("bad", 1.0, 0.5), _w("ok", 1.0, 1.2)])])
    out = build_clips(tp)
    assert [c.text for c in out.clips] == ["ok"]
    assert any("end<start" in n for n in out.notes)


def test_srt_format():
    tp = _t(segments=[_seg([_w("hola", 0.0, 0.4)])])
    out = build_clips(tp)
    srt = render_srt(out)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:00,400\nhola\n")
    assert srt.endswith("\n")


def test_ass_header_and_dialogue():
    tp = _t(segments=[_seg([_w("hola", 0.0, 0.4), _w("mundo", 0.5, 0.9)])])
    out = build_clips(tp, style=SubtitleStyle(font="Inter"))
    ass = render_ass(out)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "Style: Pill,Inter," in ass
    assert "Dialogue: 0,0:00:00.00,0:00:00.40,Pill" in ass
    assert "{\\fad(40,40)}hola" in ass
    assert ass.count("Dialogue:") == 2


def test_srt_time_rounding_edge():
    # 0.9995 rounds to 1.000 → seconds carry
    assert _fmt_srt_time(0.9995) == "00:00:01,000"
    assert _fmt_ass_time(0.9999) == "0:00:01.00"


def test_empty_transcript_yields_empty_clips():
    out = build_clips(_t())
    assert out.clips == []
    assert out.notes == []


def test_ass_escapes_comma_in_text():
    tp = _t(segments=[_seg([_w("hola,mundo", 0.0, 0.4)])])
    out = build_clips(tp)
    ass = render_ass(out)
    # commas would break ASS field parsing — replaced with arabic comma
    assert "hola,mundo" not in ass
    assert "hola،mundo" in ass


def test_text_whitespace_normalised():
    tp = _t(segments=[_seg([_w("  hola\t\n ", 0.0, 0.4)])])
    out = build_clips(tp)
    assert out.clips[0].text == "hola"
