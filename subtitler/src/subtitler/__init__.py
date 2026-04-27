"""subtitler — Phase 12 of v6 pipeline.

Generate word-by-word karaoke subtitles from `transcript_polished.json`.

Style (BROLL_CREATIVE_SPEC.md v4 §4.2):
  • bold sans-serif (Inter Bold / Montserrat Bold)
  • pill negro semi-transparente (alpha ~0.75)
  • 1 word at a time, bottom third, centered
  • exact word-level timing, ALWAYS visible

Outputs:
    subtitles.srt          — one cue per word (standard SRT)
    subtitles.ass          — Advanced SubStation Alpha for CapCut/Remotion
    subtitle_clips.json    — structured cues for the compositor (Phase 13)

Pure determinista. No LLM calls. Single timing source = transcript_polished.
"""
__version__ = "0.1.0"
