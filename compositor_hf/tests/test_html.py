"""Tests for compositor.html — HTML emission shape."""
from __future__ import annotations

from datetime import datetime, timezone

from compositor_hf.contracts import CompositionLayer, CompositionPlan
from compositor_hf.html import render_html


def _plan(layers, *, audio_rel=None, duration=10.0, w=1080, h=1920):
    return CompositionPlan(
        created_at=datetime.now(timezone.utc),
        duration_s=duration, width=w, height=h, fps=30,
        audio_rel=audio_rel, layers=layers,
    )


def _broll(start, end, asset_rel, asset_kind="image",
            layout="fullscreen", beat_id="b001"):
    return CompositionLayer(
        kind="broll", start_s=start, end_s=end,
        asset_rel=asset_rel, asset_kind=asset_kind, layout=layout,
        beat_id=beat_id,
    )


def _sub(start, end, text):
    return CompositionLayer(kind="subtitle", start_s=start, end_s=end, text=text)


def test_html_root_has_composition_metadata():
    html = render_html(_plan([], duration=12.5))
    assert 'data-composition-id="main"' in html
    assert 'data-duration="12.50"' in html
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html


def test_html_emits_one_div_per_broll_layer():
    html = render_html(_plan([
        _broll(0.0, 3.0, "media/x.mp4", asset_kind="video"),
        _broll(3.0, 6.0, "logo.png", asset_kind="image"),
    ]))
    assert 'id="layer-0"' in html
    assert 'id="layer-1"' in html
    # Video uses <source> with type to make Chromium fire loadedmetadata
    assert '<source src="media/x.mp4" type="video/mp4"' in html
    assert 'preload="auto"' in html
    assert '<img src="logo.png"' in html


def test_html_emits_subtitle_pill():
    html = render_html(_plan([_sub(0.5, 0.9, "hola")]))
    assert '<span class="pill">hola</span>' in html


def test_html_subtitle_text_is_html_escaped():
    html = render_html(_plan([_sub(0.0, 0.3, "<bad> & <worse>")]))
    assert "&lt;bad&gt; &amp; &lt;worse&gt;" in html
    # Raw markup must NOT have leaked through
    assert "<bad>" not in html


def test_html_includes_audio_tag_when_audio_rel_set():
    html = render_html(_plan([], audio_rel="audio.wav"))
    assert '<audio id="presenter_audio"' in html
    assert 'src="audio.wav"' in html


def test_html_omits_audio_tag_when_audio_rel_missing():
    html = render_html(_plan([], audio_rel=None))
    assert '<audio id="presenter_audio"' not in html


def test_html_layer_timing_table_drives_gsap():
    html = render_html(_plan([
        _broll(0.0, 2.5, "a.mp4", asset_kind="video"),
        _sub(0.0, 0.5, "hola"),
    ]))
    # The JS receives a JSON table the timeline iterates over.
    assert '"start": 0.0' in html
    assert '"end": 2.5' in html
    assert '"kind": "broll"' in html
    assert '"kind": "subtitle"' in html


def test_html_split_layout_classnames_normalised():
    html = render_html(_plan([
        _broll(0.0, 3.0, "x.png", asset_kind="image", layout="split_top"),
        _broll(3.0, 6.0, "y.png", asset_kind="image", layout="split_bottom"),
    ]))
    # CSS uses kebab-case selectors
    assert "broll split-top" in html
    assert "broll split-bottom" in html


def test_html_renders_dimensions_and_fps_into_root():
    html = render_html(_plan([], duration=4.0, w=720, h=1280))
    assert "width:720px" in html
    assert "height:1280px" in html
