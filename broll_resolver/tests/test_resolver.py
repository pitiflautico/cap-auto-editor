"""Tests for broll_resolver MVP cascade."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, BrollHint, BrollTiming, Narrative, Topic,
)
from broll_resolver.contracts import PendingHint, ResolvedAsset
from broll_resolver.resolver import resolve


def _hint(type_="video", subject="Foo", description="x", source_ref=None,
          query=None, shot_type=None, fallbacks=None):
    return BrollHint(
        type=type_, description=description, timing=BrollTiming(),
        energy_match="medium", source_ref=source_ref,
        subject=subject, query=query, shot_type=shot_type,
        queries_fallback=fallbacks or [],
    )


def _beat(beat_id, start, end, hints=None, ef="solution"):
    return Beat(
        beat_id=beat_id, start_s=start, end_s=end, text="x",
        editorial_function=ef, hero_text_candidate=None, energy="medium",
        references_topic_ids=[], broll_hints=hints or [],
    )


def _analysis(beats):
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=10,
                         purpose="Open the video.", topic_focus=[])],
        beats=beats, topics=[], entities=[],
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc), transcript_ref="/x",
        capture_manifest_ref=None, language="en",
        duration_s=beats[-1].end_s if beats else 60.0,
        llm_provider="x", llm_model="x", narrative=n,
    )


def _build_capture_dir(root: Path, slug: str,
                       *, video_path: str | None = None,
                       screenshot: bool = False) -> dict:
    """Create a captures/<slug>/ tree on disk, return manifest result dict."""
    cap = root / "captures" / slug
    cap.mkdir(parents=True, exist_ok=True)
    artifacts = {"text_path": "text.txt"}
    if screenshot:
        (cap / "screenshot.png").write_bytes(b"\x89PNG")
        artifacts["screenshot_path"] = "screenshot.png"
    assets = []
    if video_path:
        full = cap / video_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(b"FAKEMP4")
        assets.append({
            "kind": "video", "provider": "yt_dlp",
            "path": video_path, "source_url": "https://x.com",
            "bytes": len(b"FAKEMP4"),
            "duration_s": 12.0, "width": 1920, "height": 1080,
        })
    artifacts["assets"] = assets
    return {
        "request": {"slug": slug,
                    "url": f"https://example.com/{slug}",
                    "normalized_url": f"https://example.com/{slug}",
                    "priority": 0},
        "status": "ok", "backend": "browser_sdk",
        "captured_at": "2026-04-27T00:00:00", "duration_ms": 100,
        "artifacts": artifacts,
    }


# ── Cascade rule tests ─────────────────────────────────────────────

def test_inventory_anchor_resolves_to_segment(tmp_path: Path):
    """Hint with description carrying [@ media/foo.mp4 t1-t2s] resolves to abs path + segment."""
    result = _build_capture_dir(tmp_path, "acme",
                                 video_path="media/video_01.mp4")
    manifest = {"out_dir": str(tmp_path), "results": [result]}
    desc = "Hero shot  [@ media/video_01.mp4 1.0-5.5s]"
    a = _analysis([_beat("b001", 0, 8,
                          hints=[_hint(source_ref="acme", description=desc)])])
    plan, pending, _ = resolve(a, manifest, tmp_path)
    assert len(plan.resolved) == 1
    r = plan.resolved[0]
    assert r.kind == "video"
    assert r.source == "anchor_in_inventory"
    assert r.t_start_s == 1.0 and r.t_end_s == 5.5
    assert r.duration_s == 4.5
    assert r.abs_path.endswith("captures/acme/media/video_01.mp4")
    assert pending.pending == []


def test_source_ref_first_video_when_no_anchor(tmp_path: Path):
    result = _build_capture_dir(tmp_path, "acme",
                                 video_path="media/video_01.mp4")
    manifest = {"out_dir": str(tmp_path), "results": [result]}
    a = _analysis([_beat("b001", 0, 8,
                          hints=[_hint(source_ref="acme", description="no anchor here")])])
    plan, _, _ = resolve(a, manifest, tmp_path)
    r = plan.resolved[0]
    assert r.source == "source_ref_first_video"
    assert r.kind == "video"


def test_source_ref_screenshot_when_only_image(tmp_path: Path):
    result = _build_capture_dir(tmp_path, "blogpost", screenshot=True)
    manifest = {"out_dir": str(tmp_path), "results": [result]}
    a = _analysis([_beat("b001", 0, 8,
                          hints=[_hint(type_="web_capture", source_ref="blogpost",
                                        description="page screenshot")])])
    plan, _, _ = resolve(a, manifest, tmp_path)
    r = plan.resolved[0]
    assert r.source == "source_ref_screenshot"
    assert r.kind == "screenshot"
    assert r.abs_path.endswith("captures/blogpost/screenshot.png")


def test_title_falls_through_to_acquisition(tmp_path: Path):
    """Designed types (title/slide/mockup) without source_ref must go
    to acquisition — never resolve to a kind=title placeholder. The
    new text_card layouts in acquisition own the rendering of these
    slots."""
    manifest = {"out_dir": str(tmp_path), "results": []}
    a = _analysis([_beat("b001", 0, 5,
                          hints=[_hint(type_="title", description="Hero text overlay")])])
    plan, pending, _ = resolve(a, manifest, tmp_path)
    assert plan.resolved == []
    assert len(pending.pending) == 1
    p = pending.pending[0]
    assert p.type_ == "title"
    assert p.beat_id == "b001"


def test_pending_when_no_local_material(tmp_path: Path):
    manifest = {"out_dir": str(tmp_path), "results": []}
    a = _analysis([_beat("b001", 0, 5,
                          hints=[_hint(type_="video", subject="Llama 4",
                                        query="Llama 4 demo",
                                        fallbacks=["Llama 4 trailer"],
                                        shot_type="wide")])])
    plan, pending, report = resolve(a, manifest, tmp_path)
    assert len(plan.resolved) == 0
    assert len(pending.pending) == 1
    p = pending.pending[0]
    assert p.subject == "Llama 4"
    assert p.query == "Llama 4 demo"
    assert "Llama 4 trailer" in p.queries_fallback
    assert report.pending_count == 1
    assert report.pending_by_type["video"] == 1


def test_anchor_falls_back_when_path_missing(tmp_path: Path):
    """If anchor points at a path that doesn't exist on disk, we fall through
    to the next cascade rule (source_ref_first_video / screenshot / pending)."""
    # captures/acme/ exists but media/video_99.mp4 does NOT
    result = _build_capture_dir(tmp_path, "acme",
                                 video_path="media/video_01.mp4")
    manifest = {"out_dir": str(tmp_path), "results": [result]}
    desc = "[@ media/video_99.mp4 0.0-3.0s]"
    a = _analysis([_beat("b001", 0, 5,
                          hints=[_hint(source_ref="acme", description=desc)])])
    plan, _, _ = resolve(a, manifest, tmp_path)
    # falls through to source_ref_first_video on the existing video_01.mp4
    assert plan.resolved[0].source == "source_ref_first_video"


def test_report_counts_by_source_and_type(tmp_path: Path):
    """Mix of resolution paths reflected in report."""
    result = _build_capture_dir(tmp_path, "acme",
                                 video_path="media/video_01.mp4")
    manifest = {"out_dir": str(tmp_path), "results": [result]}
    a = _analysis([
        _beat("b001", 0, 5, hints=[
            _hint(type_="video", source_ref="acme",
                  description="x  [@ media/video_01.mp4 1.0-3.0s]"),
            _hint(type_="title", description="Big claim"),
            _hint(type_="video", subject="Other",
                  description="no source"),
        ]),
    ])
    _, _, report = resolve(a, manifest, tmp_path)
    # title now goes to acquisition (no more title_fallback) → 1 resolved + 2 pending
    assert report.resolved_count == 1
    assert report.pending_count == 2
    assert report.resolved_by_source.get("anchor_in_inventory", 0) == 1
    assert report.pending_by_type.get("video", 0) == 1
    assert report.pending_by_type.get("title", 0) == 1
