"""Self-audit for capture media extraction.

Compares what ``detect_media`` found in the HTML with what
``download_candidates`` actually persisted, and emits explicit warnings
when something looks editorially relevant but is missing — most often
a YouTube/Vimeo iframe (the hero video on corporate landings) that we
did not download.

Output: a ``media_audit.json`` sidecar in the slug directory. The viewer
can render it as a red warning banner. Downstream phases
(broll_resolver, broll_analyzer) can read it to know what's missing.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .contracts import MediaAsset
from .extractors.media import MediaCandidate, detect_media


@dataclass
class _ScannedItem:
    url: str
    found_in_html: bool = True
    downloaded: bool = False
    skip_reason: str | None = None


@dataclass
class MediaAudit:
    """Summary of detected vs downloaded media for a single capture."""
    slug: str
    page_url: str

    iframes_yt_dlp:  list[_ScannedItem] = field(default_factory=list)
    video_tags:      list[_ScannedItem] = field(default_factory=list)
    og_video:        list[_ScannedItem] = field(default_factory=list)
    og_image:        list[_ScannedItem] = field(default_factory=list)
    yt_dlp_page:     list[_ScannedItem] = field(default_factory=list)

    candidates_total: int = 0
    downloaded_total: int = 0

    missed: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _category_for_candidate(c: MediaCandidate, page_url: str) -> str:
    """Map a MediaCandidate into one of the audit buckets."""
    if c.provider == "yt_dlp":
        # Two flavours: the page itself was a yt-dlp host (rare for landings)
        # or an iframe on a non-yt-dlp page.
        if c.url.rstrip("/") == page_url.rstrip("/"):
            return "yt_dlp_page"
        return "iframes_yt_dlp"
    if c.provider == "video_tag":
        return "video_tags"
    if c.provider == "og_video":
        return "og_video"
    if c.provider == "og_image":
        return "og_image"
    return "video_tags"


def audit_capture(
    html: str,
    page_url: str,
    slug: str,
    downloaded: list[MediaAsset],
    *,
    max_per_capture: int,
) -> MediaAudit:
    """Build a MediaAudit comparing detect_media output with what was saved."""
    candidates = detect_media(html, page_url)
    audit = MediaAudit(slug=slug, page_url=page_url)
    audit.candidates_total = len(candidates)
    audit.downloaded_total = len(downloaded)

    downloaded_urls = {a.source_url.rstrip("/") for a in downloaded}

    for c in candidates:
        item = _ScannedItem(
            url=c.url,
            downloaded=c.url.rstrip("/") in downloaded_urls,
        )
        bucket = _category_for_candidate(c, page_url)
        getattr(audit, bucket).append(item)

    # Missed list: candidates that did not end up as assets
    for c in candidates:
        if c.url.rstrip("/") in downloaded_urls:
            continue
        # Most likely cause: cap on max_per_capture or download failure.
        # We can't tell which, but flag both.
        audit.missed.append({
            "url": c.url,
            "kind": c.kind,
            "provider": c.provider,
            "reason": (
                "exceeded_max_per_capture"
                if audit.downloaded_total >= max_per_capture
                else "download_failed_or_filtered"
            ),
        })

    # Editorial warnings
    iframe_missed = [it for it in audit.iframes_yt_dlp if not it.downloaded]
    if iframe_missed:
        audit.warnings.append(
            f"hero_iframe_missing: {len(iframe_missed)} youtube/vimeo embed(s) "
            "found in HTML but not downloaded — likely the hero video"
        )

    og_video_missed = [it for it in audit.og_video if not it.downloaded]
    if og_video_missed:
        audit.warnings.append(
            f"og_video_missing: og:video meta declared {len(og_video_missed)} "
            "video(s) that were not downloaded"
        )

    if audit.candidates_total > max_per_capture and audit.downloaded_total >= max_per_capture:
        audit.warnings.append(
            f"max_per_capture_reached: {audit.candidates_total} candidates detected "
            f"but only {max_per_capture} downloaded — consider raising the cap"
        )

    if audit.candidates_total == 0:
        audit.warnings.append(
            "no_media_candidates: page exposes no <video>, <iframe>, og:video or "
            "og:image — only text+screenshot will be available downstream"
        )

    return audit


def write_audit(audit: MediaAudit, slug_dir: Path) -> Path:
    path = slug_dir / "media_audit.json"
    path.write_text(json.dumps(audit.to_dict(), indent=2), encoding="utf-8")
    return path
