"""acquisition — Phase 9 of v6 pipeline.

Read pending_acquisition.json from broll_resolver and fulfil every entry
with an absolute asset path. Cascade per hint type:

  type=video       → Pexels video → Ken Burns over Pexels image (TODO)
                     → text_card
  type=photo /
  type=web_capture → Pexels image → text_card
  type=mockup /
  type=pexels      → Pexels (image or video) → text_card
  type=slide /
  type=title       → text_card local (PIL+ffmpeg, never fails)

Output:
    pending_acquired.json     — same shape as broll_plan.resolved
    broll_plan_complete.json  — broll_plan.resolved + pending_acquired merged
    acquisition_report.json   — per-hint provider trace + costs

ENV:
    PEXELS_API_KEY    — required for Pexels provider; if absent, falls back
                        to text_card. Loaded from .env (project root).
"""
__version__ = "0.1.0"
