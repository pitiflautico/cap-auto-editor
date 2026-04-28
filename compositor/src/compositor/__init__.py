"""compositor — Phase 14 of v6 pipeline.

MVP: composes the final 1080×1920 9:16 MP4 from:
  • broll_plan_complete.json (acquisition output) — assets per beat
  • subtitle_clips.json (subtitler output) — word-by-word cues
  • audio.wav (original presenter narration)
  • analysis.json (for beat timings + duration)

Renderer: HyperFrames CLI (`npx hyperframes render`). The MVP keeps
the presenter OFF the canvas — assets fill fullscreen during their
beats, subtitles overlay bottom-third, audio is the original WAV.

A second iteration adds the matted presenter, split layouts, and
capcut_effect transitions.
"""
__version__ = "0.1.0"
