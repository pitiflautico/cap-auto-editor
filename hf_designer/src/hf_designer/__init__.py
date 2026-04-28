"""hf_designer — LLM-driven cards rendered through HyperFrames.

Two specialised prompts:
  • `slide`  — stat / comparison / list / ranking / progress
  • `mockup` — quote / thesis / manifesto / kicker

Public API:

    from hf_designer import design, render_to_mp4

    html = design(brief="...", kind="slide", layout="fullscreen", duration_s=6.0)
    res  = render_to_mp4(html, Path("/tmp/card.mp4"))
"""
from hf_designer.designer import design
from hf_designer.render import render_to_mp4

__version__ = "0.1.0"
__all__ = ["design", "render_to_mp4"]
