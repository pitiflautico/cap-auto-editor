"""broll_matcher — Phase 7.5 of v6 pipeline.

Replaces the deterministic anchor with a semantic LLM pick. Runs AFTER
script_finalizer (which has already chosen 'a' segment per beat) and
BEFORE broll_resolver. For every beat that already has an anchored
broll_hint:

  1. Collect candidate segments from visual_inventory whose
     deterministic score is within `_TOP_N_THRESHOLD` of the best.
  2. Ask the LLM (Haiku, parallel): given `beat.text` +
     `editorial_function` + a numbered list of candidate descriptions,
     pick the one that best illustrates what is said in the beat.
  3. Rewrite the hint's `[@ <path> t1-t2s]` anchor with the chosen
     segment.

Output: analysis_matched.json (same schema as analysis_balanced.json).
The variety penalty already applied by script_finalizer is preserved —
broll_matcher only narrows the pick within the candidate set.
"""
__version__ = "0.1.0"
