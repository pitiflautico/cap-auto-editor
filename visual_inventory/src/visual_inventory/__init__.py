"""visual_inventory — Phase 6 of v6 pipeline.

For every video MediaAsset across all captured slugs:
  1. Extract N keyframes with ffmpeg (uniformly spaced).
  2. Send each keyframe to a vision LLM with a short brief prompt.
  3. Aggregate per-frame results into per-asset metadata:
       - shot_types_seen (close_up / wide / logo_centered / screen_recording / …)
       - free_zones (top, bottom, left, right) — for overlay placement
       - has_baked_text (slide vs natural footage)
       - quality 1-5
       - editorial_summary
  4. Pick best_segments anchored at (t_start, t_end) for the broll planner.

Output: visual_inventory.json — a catalogue the broll planner reads to
plan beats with concrete (slug, start_s, end_s) coordinates instead of
abstract descriptions.
"""
__version__ = "0.1.0"
