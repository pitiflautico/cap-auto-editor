"""broll_planner — Phase 8 of v6 pipeline.

Second-pass LLM that takes:
  • analysis.json    — narrative + beats with visual_need / anchor_type / subject
  • capture_manifest — captured slugs + URLs + asset paths
  • visual_inventory — Haiku-vision tags per asset (subject, shot_type, best_for)

…and emits concrete broll_hints per beat following the editorial
hierarchy REAL > CAPTURED > DESIGNED:

  • web_capture / video / photo with source_ref → real anchored asset
  • pexels with motion-aware shot_type        → real stock
  • slide / mockup with kind + layout         → designed card (last resort)

Output: `analysis_with_broll.json` — same as analysis.json but each
beat's `broll_hints` filled in. Every downstream phase reads this.
"""
__version__ = "0.1.0"
