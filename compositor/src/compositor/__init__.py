"""compositor — Phase 14 of v6 pipeline.

The "real" compositor: adapts the v6 outputs (broll_plan_complete +
subtitle_clips + analysis_with_broll + audio.wav + presenter video) to
the input format of `pipeline_v4_frozen_20260423/agent4_builder/`,
which produces a CapCut project (`draft_info.json` + Resources/).

The creator opens that project in CapCut Pro and gets ALL of the
editable layers: presenter (with eye_contact / remove_background),
b-roll (Ken Burns motion via keyframes), subtitles (karaoke word-by-
word with native CapCut text effects), title overlays (impacto /
stat / contexto / cinematic), color overlays, music, stickers.

The HyperFrames-based render lives in `compositor_hf` as an optional
preview / quick-share path.
"""
__version__ = "0.1.0"
