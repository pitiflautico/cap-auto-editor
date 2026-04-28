"""browser_sdk backend: neobrowser v4 via sys.path.

Launches Chrome (managed by neobrowser) on a configurable profile,
navigates to the URL, extracts outerHTML, runs extractors, saves a
screenshot, and returns a CaptureResult.

Inherits the zombie-singleton purge from the battle-tested
``pipeline/src/myavatar/providers/broll/web_capture.py`` pattern.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from capture.contracts import (
    CaptureArtifacts,
    CaptureRequest,
    CaptureResult,
    ErrorClass,
)
from capture.extractors.text import extract_text

log = logging.getLogger("capture.backends.browser_sdk")


_NEO_V4_DEFAULT = "/Volumes/DiscoExterno2/mac_offload/Projects/meta-agente/lab/neorender-v2"


def _resolve_neo_path() -> str:
    path = os.environ.get("MYAVATAR_NEO_V4_PATH", _NEO_V4_DEFAULT)
    if not Path(path).exists():
        raise ImportError(
            f"neobrowser v4 not found at {path!r}. "
            "Set MYAVATAR_NEO_V4_PATH or install neorender-v2."
        )
    return path


def _ensure_on_syspath() -> None:
    path = _resolve_neo_path()
    if path not in sys.path:
        sys.path.insert(0, path)


_PROFILES_BASE = Path.home() / ".neorender" / "profiles"


def _purge_stale_singleton(profile: str) -> None:
    """Chrome refuses to launch if SingletonLock points at a live PID
    that doesn't match the profile dir, or blocks for 10s if the
    target is dead. Kill-and-clean before Browser() so ensure()
    succeeds. Copied from pipeline's web_capture battle-tested path.
    """
    prof_dir = _PROFILES_BASE / profile
    lock = prof_dir / "SingletonLock"
    if not lock.is_symlink():
        return
    try:
        target = os.readlink(lock)
    except OSError:
        return
    m = re.search(r"-(\d+)$", target)
    if not m:
        return
    pid = int(m.group(1))
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False

    if alive:
        try:
            cmdline = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="],
                text=True, timeout=3,
            )
        except Exception:
            cmdline = ""
        if str(prof_dir) in cmdline:
            log.warning("killing zombie Chrome PID=%s holding %s", pid, profile)
            try:
                os.kill(pid, 9)
                time.sleep(0.3)
            except OSError:
                pass

    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (prof_dir / name).unlink()
        except (FileNotFoundError, IsADirectoryError, OSError):
            pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_CLOUDFLARE_MARKERS = (
    "Just a moment...",
    "cf-chl",
    "Checking your browser",
    "challenge-platform",
)


# Best-effort cookie / GDPR / consent banner dismissal. We:
#   1. Click any visible button whose text matches an accept pattern
#      (English / Spanish / French / German). Top-frame only — many
#      banners live in iframes (OneTrust) which a JS-only pass cannot
#      reach, so step 2 also brute-hides them by selector.
#   2. Hide any element matching the well-known consent vendor IDs +
#      any fixed/sticky element whose text contains "cookie" /
#      "consent" / "privacy" — but only if it covers > 8% of the
#      viewport, to avoid hiding inline content.
# This runs INSIDE the page (Chrome devtools `tab.js`) — pure DOM,
# no playwright required.
_CONSENT_DISMISSAL_JS = r"""
(() => {
  const ACCEPT_PATTERNS = [
    /^\s*(accept(\s+all)?|allow(\s+all)?|agree|got\s+it|i\s+agree)\s*$/i,
    /^\s*(aceptar( todo)?|acepto|entendido|de acuerdo)\s*$/i,
    /^\s*(accepter( tout)?|d['’]accord|j['’]accepte)\s*$/i,
    /^\s*(akzeptieren( alle)?|verstanden|einverstanden)\s*$/i,
  ];
  const VENDOR_SELECTORS = [
    "#onetrust-banner-sdk", "#onetrust-consent-sdk",
    "#CybotCookiebotDialog", "#cookiebot",
    "#truste-consent-track", "#truste-consent-content",
    "[id^='didomi-']", "[class*='didomi-']",
    "[id^='qc-cmp']", "[class*='qc-cmp']",
    "[id*='cookie-consent']", "[class*='cookie-consent']",
    "[id*='cookieConsent']", "[class*='cookieConsent']",
    "[aria-label*='consent' i]", "[aria-label*='cookie' i]",
    ".cc-window", ".cc-banner",
    "ot-sdk-row", ".consent-banner",
    "#gdpr-cookie-message", "#gdpr-banner",
  ];
  const TEXT_KEYWORDS = ["cookie", "consent", "privacy", "gdpr", "rgpd"];
  let clicks = 0, hides = 0;

  // 1. Try to click an accept button.
  const buttons = Array.from(document.querySelectorAll(
    "button, [role='button'], a.btn, input[type='button'], input[type='submit']"
  ));
  for (const b of buttons) {
    const t = (b.innerText || b.value || "").trim();
    if (!t || t.length > 40) continue;
    if (ACCEPT_PATTERNS.some(re => re.test(t))) {
      try { b.click(); clicks++; } catch (e) { /* swallow */ }
    }
  }

  // 2. Hide vendor-known banners regardless.
  for (const sel of VENDOR_SELECTORS) {
    document.querySelectorAll(sel).forEach(el => {
      el.style.setProperty("display", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
      hides++;
    });
  }

  // 3. Heuristic sweep: hide fixed/sticky elements that look like
  //    overlays (cover ≥ 8% of the viewport) and contain consent text.
  const vw = window.innerWidth, vh = window.innerHeight;
  const minArea = vw * vh * 0.08;
  document.querySelectorAll("body *").forEach(el => {
    try {
      const cs = getComputedStyle(el);
      if (!["fixed", "sticky"].includes(cs.position)) return;
      const r = el.getBoundingClientRect();
      if (r.width * r.height < minArea) return;
      const txt = (el.innerText || "").toLowerCase();
      if (!TEXT_KEYWORDS.some(k => txt.includes(k))) return;
      el.style.setProperty("display", "none", "important");
      hides++;
    } catch (e) { /* ignore */ }
  });

  // 4. Restore body scroll if a banner locked it.
  document.documentElement.style.removeProperty("overflow");
  document.body.style.removeProperty("overflow");

  return { clicks, hides };
})();
"""


def _looks_like_cloudflare(html: str, title: str | None) -> bool:
    if title and title.strip() in ("Just a moment...",):
        return True
    snippet = html[:5000]
    return any(m in snippet for m in _CLOUDFLARE_MARKERS)


class BrowserSdkBackend:
    name = "browser_sdk"

    def __init__(
        self,
        *,
        profile: str = "default",
        viewport_w: int = 390,        # iPhone 12 Pro logical width
        viewport_h: int = 844,        # iPhone 12 Pro logical height
        device_scale_factor: int = 3,    # retina → physical 1170×2532
        mobile: bool = True,             # request mobile-formatted pages
        wait_s: float = 3.0,
        save_raw_html: bool = False,
        media: bool = True,
        max_media_per_capture: int = 3,
        dismiss_consent: bool = True,
    ) -> None:
        self.profile = profile
        self.viewport_w = viewport_w
        self.viewport_h = viewport_h
        self.device_scale_factor = device_scale_factor
        self.mobile = mobile
        self.wait_s = wait_s
        self.save_raw_html = save_raw_html
        self.media = media
        self.max_media_per_capture = max_media_per_capture
        self.dismiss_consent = dismiss_consent

    def accepts(
        self, request: CaptureRequest, content_type: str | None
    ) -> bool:
        # Default handler for anything http_direct didn't claim.
        if content_type is None:
            return True
        if content_type.startswith("image/"):
            return False
        if content_type == "text/plain":
            return False
        return True

    def capture(
        self,
        request: CaptureRequest,
        artifact_dir: Path,
    ) -> CaptureResult:
        t0 = time.monotonic()
        artifact_dir.mkdir(parents=True, exist_ok=True)

        def _fail(error_class: ErrorClass, msg: str) -> CaptureResult:
            return CaptureResult(
                request=request,
                status="failed",
                backend="browser_sdk",
                captured_at=datetime.now(timezone.utc),
                duration_ms=int((time.monotonic() - t0) * 1000),
                attempts=1,
                error=msg,
                error_class=error_class,
            )

        try:
            _ensure_on_syspath()
            from tools.v4.browser import Browser  # type: ignore
        except ImportError as e:
            return _fail("chrome_launch_failed", f"import failed: {e}")

        _purge_stale_singleton(self.profile)

        html: str = ""
        page_title: str | None = None
        screenshot_path = artifact_dir / "screenshot.png"

        try:
            with Browser(
                profile=self.profile, pool_size=1, visible=False
            ) as b:
                tab = b.open(request.normalized_url, wait_s=self.wait_s)
                try:
                    tab.send("Emulation.setDeviceMetricsOverride", {
                        "width": self.viewport_w,
                        "height": self.viewport_h,
                        "deviceScaleFactor": self.device_scale_factor,
                        "mobile": self.mobile,
                    })
                    time.sleep(0.5)
                except Exception as e:
                    log.warning("setDeviceMetricsOverride failed: %s", e)

                # Dismiss cookie / GDPR / consent banners before screenshot.
                # We try common selectors plus a heuristic that hides any
                # fixed/sticky element matching the typical patterns. Best
                # effort — failure is non-fatal.
                if self.dismiss_consent:
                    try:
                        tab.js(_CONSENT_DISMISSAL_JS)
                        time.sleep(0.4)
                    except Exception as e:
                        log.warning("consent dismissal failed: %s", e)

                try:
                    html = tab.js(
                        "return document.documentElement.outerHTML"
                    ) or ""
                    page_title = tab.js("return document.title") or None
                except Exception as e:
                    b.close_tab(tab)
                    return _fail(
                        "unknown", f"HTML extraction failed: {e}"
                    )

                try:
                    b.screenshot_save(
                        tab,
                        path=str(screenshot_path),
                        format="png",
                        base_dir=artifact_dir.resolve(),
                    )
                except Exception as e:
                    log.warning("screenshot failed: %s", e)

                b.close_tab(tab)
        except Exception as e:
            name = type(e).__name__
            # Neobrowser surfaces Chrome startup races as RuntimeError
            # or ConnectionError — classify so retry picks it up.
            if "Chrome" in str(e) or "ensure" in str(e).lower():
                return _fail(
                    "chrome_launch_failed", f"{name}: {e}"
                )
            return _fail("unknown", f"{name}: {e}")

        if not html:
            return _fail("unknown", "empty HTML after navigation")

        if _looks_like_cloudflare(html, page_title):
            return _fail(
                "cloudflare_challenge",
                f"cloudflare challenge detected (title={page_title!r})",
            )

        try:
            text = extract_text(html)
        except Exception as e:
            return _fail("unknown", f"text extraction: {e}")

        artifacts = CaptureArtifacts()

        text_path = artifact_dir / "text.txt"
        text_path.write_text(text, encoding="utf-8")
        artifacts.text_path = "text.txt"
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        screenshot_sha: str | None = None
        if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
            artifacts.screenshot_path = "screenshot.png"
            screenshot_sha = _sha256_file(screenshot_path)

        if self.save_raw_html:
            raw_path = artifact_dir / "raw.html"
            raw_path.write_text(html, encoding="utf-8")
            artifacts.raw_html_path = "raw.html"

        if self.media:
            try:
                from ..extractors.media import detect_media
                from ..media_downloader import DownloadContext, download_candidates
                from ..media_audit import audit_capture, write_audit
                cands = detect_media(html, request.normalized_url)
                if cands:
                    artifacts.assets = download_candidates(
                        cands,
                        DownloadContext(out_dir=artifact_dir),
                        max_per_capture=self.max_media_per_capture,
                    )
                # Always audit — even when no candidates were found that's a
                # signal the page only exposes text+screenshot.
                audit = audit_capture(
                    html, request.normalized_url, request.slug,
                    artifacts.assets,
                    max_per_capture=self.max_media_per_capture,
                )
                write_audit(audit, artifact_dir)
                artifacts.media_audit_path = "media_audit.json"
                if audit.warnings:
                    import logging
                    logging.getLogger("capture.media").warning(
                        "media audit for %s: %s",
                        request.slug, "; ".join(audit.warnings),
                    )
            except Exception as exc:
                # Media + audit are opportunistic: never fail the capture.
                import logging
                logging.getLogger("capture.media").warning(
                    "media extraction failed for %s: %s", request.slug, exc
                )

        return CaptureResult(
            request=request,
            status="ok",
            backend="browser_sdk",
            captured_at=datetime.now(timezone.utc),
            duration_ms=int((time.monotonic() - t0) * 1000),
            attempts=1,
            artifacts=artifacts,
            text_sha256=text_sha,
            screenshot_sha256=screenshot_sha,
        )
