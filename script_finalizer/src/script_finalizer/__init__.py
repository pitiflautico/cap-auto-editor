"""script_finalizer — Phase 7 of v6 pipeline.

Final balancing pass over the editorial plan, applying industry-backed
baselines and adapting to the strength of the visual catalogue:

    Industry baselines (sources cited in the README):
      • B-roll coverage 35-50% of duration
      • real footage (video/web_capture/photo) ≥ 50% of all hints
      • slide/title fillers ≤ 30% of all hints
      • max consecutive talking-head ≈ 7s in short-form/hybrid
      • beat duration sweet spot 6-10s for hybrid (4-min) tech explainer

    Adaptive layer (visual_inventory-driven):
      material_score = weighted avg of (overall_quality * subject_match)
        for every asset segment relevant to a topic in the analysis

      score ≥ 0.8  → 'rich': broll target 50-65%, low merge aggressiveness
      score ≤ 0.4  → 'thin': broll target 25-35%, downgrade slides → titles
      else         → default 35-50%

The phase NEVER rewrites the narrative; it only:
  - merges adjacent beats with same editorial_function when both are weak
    on visual material AND combined duration ≤ 12s,
  - downgrades broll_hints whose declared type has no inventory backing,
  - drops broll_hints whose target subject has no visual match at all,
  - anchors strong matches to (slug, asset_path, t_start_s, t_end_s) on
    the segment with best subject_match × shot_type fit.
"""
__version__ = "0.1.0"
