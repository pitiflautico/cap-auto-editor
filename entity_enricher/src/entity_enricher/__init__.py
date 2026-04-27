"""entity_enricher — Phase 4 of v6 pipeline.

Given an analysis.json (post LLM editorial pass) and the capture_manifest
URLs the operator supplied, derive deterministic official_handles per
entity for the broll_resolver to use.

Two sources, in order:
  1. URL extractor    — parse --sources URLs the operator gave; if a URL
                        is a known platform (x.com/handle, twitter.com/h,
                        reddit.com/r/sub, youtube.com/@h, etc.) lift the
                        handle from the path. Zero network, deterministic.
  2. Browser lookup   — for each entity that still lacks a handle, run a
                        neobrowser search ("<canonical> twitter") and
                        take the first verified result. Cached for 30
                        days at ~/myavatar/handle_cache.json.

The LLM never invents handles. Output is `analysis_enriched.json` —
identical to the input plus `entity.official_handles` populated.
"""
__version__ = "0.1.0"
