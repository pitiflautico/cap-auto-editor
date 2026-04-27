"""storyboard — Phase 10 of v6 pipeline.

Generate one preview thumbnail per ResolvedAsset in the broll plan so the
operator can validate visually what each beat will show before the
compositor renders the final video.

For each entry:
  • kind=video    → ffmpeg extract a frame at (t_start_s + t_end_s) / 2.
                    If t_start/t_end missing, picks 1s in.
  • kind=image    → reuse the image directly (resize down to ≤640w).
  • kind=screenshot → reuse, resize.
  • kind=title    → re-render a small preview of the text_card (read from
                    abs_path if .png exists; else generate a tiny placeholder).

Output:
    storyboard.json    — list of beat-keyed previews with metadata
    thumbs/<beat>.jpg  — actual thumbnail files for the viewer to serve

The viewer will then layout these frames as a true preview/storyboard
of the final composition (frame on top, metadata box below).
"""
__version__ = "0.1.0"
