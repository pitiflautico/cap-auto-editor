"""Tests for the browser_sdk backend settings — mobile viewport,
consent dismissal — without spinning up Chrome.
"""
from __future__ import annotations

from capture.backends import browser_sdk
from capture.backends.browser_sdk import BrowserSdkBackend


def test_default_viewport_is_mobile_portrait():
    """v6.1 default: iPhone 12 Pro logical dimensions with retina DPR.
    Captures must be portrait so screenshots tile cleanly into the
    1080×1920 video frame without crops."""
    b = BrowserSdkBackend()
    assert b.viewport_w == 390
    assert b.viewport_h == 844
    assert b.device_scale_factor == 3
    assert b.mobile is True


def test_consent_dismissal_enabled_by_default():
    assert BrowserSdkBackend().dismiss_consent is True


def test_consent_dismissal_can_be_disabled():
    b = BrowserSdkBackend(dismiss_consent=False)
    assert b.dismiss_consent is False


def test_consent_js_targets_known_vendors_and_keywords():
    """The injected JS must at least handle OneTrust / Cookiebot /
    Didomi / TrustArc / Quantcast (the dominant CMPs) and the
    English/Spanish accept-button text the heuristic matches against."""
    js = browser_sdk._CONSENT_DISMISSAL_JS
    for vendor in ("onetrust-banner-sdk", "CybotCookiebot",
                    "didomi-", "qc-cmp", "truste-consent"):
        assert vendor in js, f"vendor selector {vendor!r} missing"
    for word in ("aceptar", "acepto", "accept", "agree", "consent"):
        assert word in js.lower(), f"text token {word!r} missing"


def test_custom_viewport_overrides_defaults():
    b = BrowserSdkBackend(viewport_w=1080, viewport_h=1920,
                           device_scale_factor=1, mobile=False)
    assert b.viewport_w == 1080
    assert b.viewport_h == 1920
    assert b.device_scale_factor == 1
    assert b.mobile is False
