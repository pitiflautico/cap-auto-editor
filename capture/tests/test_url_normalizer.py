"""Tests for capture.url_normalizer — pure functions, no IO."""
from __future__ import annotations

import pytest

from capture.url_normalizer import (
    DEFAULT_TRACKING_PARAMS,
    derive_slug,
    normalize_url,
)


class TestNormalizeUrl:
    def test_scheme_lowercased(self):
        assert normalize_url("HTTPS://Reddit.com/r/x").startswith("https://")

    def test_host_lowercased(self):
        assert normalize_url("https://Reddit.com/r/LocalLLaMA") == \
            "https://reddit.com/r/LocalLLaMA"

    def test_fragment_stripped(self):
        assert normalize_url("https://x.com/post#comment-3") == \
            "https://x.com/post"

    def test_trailing_slash_stripped(self):
        assert normalize_url("https://x.com/path/") == "https://x.com/path"

    def test_root_slash_preserved(self):
        assert normalize_url("https://x.com/") == "https://x.com/"

    def test_missing_scheme_defaulted_to_https(self):
        assert normalize_url("reddit.com/r/x") == "https://reddit.com/r/x"

    def test_utm_params_stripped(self):
        url = "https://x.com/a?utm_source=twitter&utm_medium=social"
        assert normalize_url(url) == "https://x.com/a"

    def test_ref_stripped(self):
        assert normalize_url("https://x.com/a?ref=home") == "https://x.com/a"

    def test_functional_params_preserved(self):
        url = "https://reddit.com/r/x/comments/1stjwg5?sort=top"
        norm = normalize_url(url)
        assert "sort=top" in norm

    def test_mixed_tracking_and_functional(self):
        url = "https://x.com/a?page=2&utm_source=x&id=42"
        norm = normalize_url(url)
        assert "page=2" in norm
        assert "id=42" in norm
        assert "utm_source" not in norm

    def test_idempotent(self):
        url = "HTTPS://X.COM/path/?utm_source=ig#frag"
        once = normalize_url(url)
        twice = normalize_url(once)
        assert once == twice

    def test_custom_tracking_list_wins(self):
        url = "https://x.com/a?utm_source=x&foo=bar"
        norm = normalize_url(url, tracking_params={"foo"})
        assert "foo" not in norm
        # utm_source no estaba en la lista custom — se preserva
        assert "utm_source" in norm

    def test_default_tracking_params_immutable(self):
        # Nadie debería poder mutar el frozenset por accidente.
        with pytest.raises((AttributeError, TypeError)):
            DEFAULT_TRACKING_PARAMS.add("new_param")  # type: ignore[attr-defined]


class TestDeriveSlug:
    def test_simple_reddit(self):
        slug = derive_slug(
            "https://www.reddit.com/r/LocalLLaMA/comments/1steip4/qwen_36_27b_is_a_beast/"
        )
        assert slug.startswith("www-reddit-com-")
        assert "qwen-36-27b-is-a-beast" in slug

    def test_image_extension_stripped(self):
        slug = derive_slug("https://i.redd.it/nxwstygg30xg1.png")
        assert slug == "i-redd-it-nxwstygg30xg1"

    def test_only_safe_chars(self):
        slug = derive_slug(
            "https://medium.com/@fzbcwvv/an-overnight-stack-for-qwen3-6-27b"
        )
        assert all(c.isalnum() or c == "-" for c in slug)
        assert "@" not in slug

    def test_max_length_respected(self):
        long = "https://example.com/" + "word-" * 40
        slug = derive_slug(long, maxlen=40)
        assert len(slug) <= 40

    def test_root_url_falls_back(self):
        slug = derive_slug("https://openai.com/")
        assert slug == "openai-com"

    def test_deterministic(self):
        url = "https://x.com/some/path"
        assert derive_slug(url) == derive_slug(url)

    def test_different_hosts_different_slugs(self):
        a = derive_slug("https://a.com/same")
        b = derive_slug("https://b.com/same")
        assert a != b

    def test_long_path_falls_back_to_hash(self):
        long = "https://medium.com/@fzbcwvv/an-overnight-stack-for-qwen3-6-27b-85-tps-125k-context-vision-on-one-rtx-3090-0d95c6291914"
        slug = derive_slug(long, maxlen=60)
        # Truncation would slice mid-word; fallback uses host + hash8.
        parts = slug.rsplit("-", 1)
        assert len(parts) == 2
        host_part, digest = parts
        assert host_part == "medium-com"
        assert len(digest) == 8
        assert digest.isalnum()

    def test_hash_fallback_is_stable(self):
        long = "https://example.com/" + "word-" * 40
        assert derive_slug(long, maxlen=40) == derive_slug(long, maxlen=40)

    def test_different_long_urls_give_different_slugs(self):
        a = derive_slug("https://example.com/" + "a" * 120, maxlen=40)
        b = derive_slug("https://example.com/" + "b" * 120, maxlen=40)
        assert a != b

    def test_fallback_never_exceeds_maxlen(self):
        long = "https://very-long-hostname-" + "x" * 80 + ".example.com/path"
        slug = derive_slug(long, maxlen=40)
        assert len(slug) <= 40
