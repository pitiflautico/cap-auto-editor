"""Media URL detector — pure HTML/text parsing, no I/O.

Given the raw HTML of a captured page (and its base URL for resolving
relative paths), enumerate every embedded media URL we can plausibly
download for downstream broll reuse. The downloader (media_downloader.py)
turns these candidates into MediaAsset entries.

Detection sources (in priority order — see ``detect_media``):

  1. yt-dlp candidates  — page IS a known platform (YouTube / Twitter
     / TikTok / Instagram / Reddit video). The whole page URL is passed
     to yt-dlp; it resolves the underlying media.
  2. og:video[:secure_url]  — explicit video meta tag.
  3. <video><source>  — HTML5 player.
  4. og:image  — only when likely large (no width hint or > 1080).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse


_YT_DLP_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "twitter.com", "x.com", "mobile.twitter.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "instagram.com", "www.instagram.com",
    "v.redd.it",
}


CandidateKind = Literal["video", "og_image", "gif"]
CandidateProvider = Literal[
    "og_video", "video_tag", "og_image", "yt_dlp", "http_direct",
]


@dataclass(frozen=True)
class MediaCandidate:
    """A detected media URL not yet downloaded."""
    url: str               # absolute URL (already resolved against base)
    kind: CandidateKind
    provider: CandidateProvider
    width: int | None = None
    height: int | None = None


_RE_META = re.compile(
    r"""<meta\s+[^>]*?
        (?:property|name)\s*=\s*["']([^"']+)["']
        [^>]*?
        content\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE | re.VERBOSE,
)
_RE_META_REVERSE = re.compile(
    r"""<meta\s+[^>]*?
        content\s*=\s*["']([^"']+)["']
        [^>]*?
        (?:property|name)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE | re.VERBOSE,
)
_RE_VIDEO_TAG = re.compile(r"<video\b[^>]*>(.*?)</video>", re.IGNORECASE | re.DOTALL)
_RE_VIDEO_SRC = re.compile(r'src\s*=\s*["\']([^"\']+\.(?:mp4|webm|mov))', re.IGNORECASE)
_RE_SOURCE_TAG = re.compile(r'<source\b[^>]*src\s*=\s*["\']([^"\']+)', re.IGNORECASE)
# Hero videos in corporate landings are usually embedded as iframes pointing
# to YouTube / Vimeo. The yt-dlp downloader can resolve them.
_RE_IFRAME_SRC = re.compile(r'<iframe\b[^>]*src\s*=\s*["\']([^"\']+)', re.IGNORECASE)


def _meta_value(html: str, key: str) -> str | None:
    """Return the content of <meta property|name="key" content="...">."""
    key_low = key.lower()
    for m in _RE_META.finditer(html):
        if m.group(1).lower() == key_low:
            return m.group(2).strip()
    for m in _RE_META_REVERSE.finditer(html):
        if m.group(2).lower() == key_low:
            return m.group(1).strip()
    return None


def _is_yt_dlp_target(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in _YT_DLP_HOSTS


def detect_media(html: str, base_url: str) -> list[MediaCandidate]:
    """Enumerate downloadable media candidates from the captured HTML.

    Pure function. The downloader decides what to actually fetch.
    Order of returned list is also the priority order for the resolver.
    Duplicates by URL are removed.
    """
    candidates: list[MediaCandidate] = []
    seen_urls: set[str] = set()

    def _add(c: MediaCandidate) -> None:
        if c.url in seen_urls:
            return
        seen_urls.add(c.url)
        candidates.append(c)

    # 1) yt-dlp target — the page itself
    if _is_yt_dlp_target(base_url):
        _add(MediaCandidate(url=base_url, kind="video", provider="yt_dlp"))

    # 2) og:video — explicit
    og_video = _meta_value(html, "og:video:secure_url") or _meta_value(html, "og:video")
    if og_video:
        abs_url = urljoin(base_url, og_video)
        provider: CandidateProvider = "yt_dlp" if _is_yt_dlp_target(abs_url) else "og_video"
        _add(MediaCandidate(url=abs_url, kind="video", provider=provider))

    # 3) <iframe> embeds pointing to a yt-dlp host (hero videos: youtube embed).
    # Higher priority than <video> because hero videos are the most editorially
    # valuable shot per landing.
    for src in _RE_IFRAME_SRC.findall(html):
        abs_url = urljoin(base_url, src)
        if _is_yt_dlp_target(abs_url):
            # Strip ?enablejsapi=… so yt-dlp gets a clean canonical URL
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(abs_url)
            clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            _add(MediaCandidate(url=clean, kind="video", provider="yt_dlp"))

    # 4) <video> tags + nested <source>
    for video_block in _RE_VIDEO_TAG.findall(html):
        for src in _RE_VIDEO_SRC.findall(video_block):
            _add(MediaCandidate(url=urljoin(base_url, src), kind="video",
                                provider="video_tag"))
        for src in _RE_SOURCE_TAG.findall(video_block):
            if not src.lower().endswith((".mp4", ".webm", ".mov")):
                continue
            _add(MediaCandidate(url=urljoin(base_url, src), kind="video",
                                provider="video_tag"))

    # 5) og:image (large enough to crop to 9:16 portrait)
    og_image = _meta_value(html, "og:image:secure_url") or _meta_value(html, "og:image")
    if og_image:
        abs_url = urljoin(base_url, og_image)
        w = _meta_value(html, "og:image:width")
        h = _meta_value(html, "og:image:height")
        try:
            wi = int(w) if w else None
            hi = int(h) if h else None
        except ValueError:
            wi = hi = None
        # Skip tiny share thumbnails. If no size hint we accept and let the
        # downloader decide post-fetch.
        if wi is None or wi >= 720 or (hi is not None and hi >= 720):
            _add(MediaCandidate(url=abs_url, kind="og_image",
                                provider="og_image", width=wi, height=hi))

    return candidates
