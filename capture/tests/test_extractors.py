"""Tests for extractors.text — main region detection, noise stripping."""
from __future__ import annotations

import textwrap

from capture.extractors.text import extract_text


_FILLER = (
    "This paragraph adds enough substance for the extractor to treat "
    "the region as a real article rather than a tiny widget wrapper. "
)


HTML_ARTICLE = textwrap.dedent(
    f"""
    <!doctype html>
    <html lang="en">
      <head><title>site</title></head>
      <body>
        <nav>Home | Subs | Login</nav>
        <script>var nav = 1;</script>
        <header>giant banner logo text</header>
        <article>
          <h1>Qwen 3.6 27B is a BEAST</h1>
          <p>Benchmarks show 85 TPS on a single RTX 3090.</p>
          <p>Claude and Anthropic are mentioned here.</p>
          <p>{_FILLER * 6}</p>
        </article>
        <aside>
          <article>ad: buy our pro plan now</article>
        </aside>
        <footer>© 2026 site footer</footer>
      </body>
    </html>
    """
).strip()


HTML_MAIN = textwrap.dedent(
    f"""
    <html><body>
      <nav>menu item 1 item 2</nav>
      <main>
        <h1>Intro to GPT-5.5</h1>
        <p>27 mil millones de parámetros.</p>
        <p>{_FILLER * 6}</p>
      </main>
      <footer>footer junk</footer>
    </body></html>
    """
).strip()


HTML_NO_SEMANTIC = textwrap.dedent(
    """
    <html><body>
      <div id="root">
        <h1>Qwen is a beast</h1>
        <p>Raw body content.</p>
      </div>
    </body></html>
    """
).strip()


class TestExtractText:
    def test_prefers_article_over_body(self):
        text = extract_text(HTML_ARTICLE)
        assert "Qwen 3.6 27B is a BEAST" in text
        assert "Benchmarks show 85 TPS" in text
        # Nav / header / footer / aside live OUTSIDE the picked article.
        assert "giant banner" not in text
        assert "site footer" not in text
        assert "Home | Subs | Login" not in text

    def test_picks_longest_article(self):
        # The main article wins over the ad-article inside <aside>.
        text = extract_text(HTML_ARTICLE)
        assert "buy our pro plan" not in text

    def test_falls_back_to_main(self):
        text = extract_text(HTML_MAIN)
        assert "Intro to GPT-5.5" in text
        assert "27 mil millones" in text
        assert "footer junk" not in text
        assert "menu item 1" not in text

    def test_falls_back_to_body(self):
        text = extract_text(HTML_NO_SEMANTIC)
        assert "Qwen is a beast" in text
        assert "Raw body content." in text

    def test_scripts_stripped(self):
        text = extract_text(HTML_ARTICLE)
        assert "var nav = 1" not in text

    def test_no_runaway_whitespace(self):
        text = extract_text(HTML_ARTICLE)
        assert "   " not in text
        assert "\n\n\n" not in text

    def test_empty_body(self):
        assert extract_text("<html><body></body></html>") == ""

    def test_idempotent(self):
        once = extract_text(HTML_ARTICLE)
        twice = extract_text(HTML_ARTICLE)
        assert once == twice

    def test_tiny_article_falls_back_to_body(self):
        # Real-world case (Reddit): <article> exists but wraps a tiny
        # widget. The real content lives elsewhere. Fallback must take
        # the body so we don't silently lose the content.
        long_body = "Body paragraph describing Qwen 3.6 27B in detail. " * 30
        html = f"""
        <html><body>
          <article>ad</article>
          <div>{long_body}</div>
        </body></html>
        """
        text = extract_text(html)
        assert "Qwen 3.6 27B" in text
        assert "ad" != text.strip()

    def test_substantial_article_still_wins(self):
        # Regression guard: a real article must still beat the body.
        article_body = "Real long article text. " * 40
        html = f"""
        <html><body>
          <nav>menu nav</nav>
          <article>{article_body}</article>
          <footer>footer junk</footer>
        </body></html>
        """
        text = extract_text(html)
        assert "Real long article" in text
        assert "footer junk" not in text
        assert "menu nav" not in text
