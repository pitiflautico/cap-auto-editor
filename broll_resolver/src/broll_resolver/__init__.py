"""broll_resolver — Phase 8 of v6 pipeline (MVP).

Walks every broll_hint of the balanced analysis and either:

  • RESOLVES the hint to an absolute asset path on disk (kind, t_start_s,
    t_end_s, duration_s, source). Three sources in the MVP:
       1. anchor_in_inventory   — hint description carries the segment
                                   "[@ <path> <t1>-<t2>s]" written by the
                                   script_finalizer. We translate to abs path.
       2. source_ref_first_video — hint has source_ref but no anchor;
                                   pick the slug's first video asset.
       3. source_ref_screenshot  — hint has source_ref pointing at a slug
                                   without video; use that slug's
                                   screenshot.png (Ken Burns later).

  • Lists the hint as PENDING_ACQUISITION with everything an external
    asset acquisition step (Pexels API, yt-dlp ytsearch, text_card,
    operator drag-drop…) needs to complete it: query, fallback queries,
    type target, subject, beat_id, beat editorial_function.

Outputs:
    broll_plan.json          — list of resolved hints
    pending_acquisition.json — list of hints awaiting material
    broll_resolver_report.json — counts + per-hint trace
"""
__version__ = "0.1.0"
