"""auto_source — Phase 5 of v6 pipeline.

For every Topic role=main in an enriched analysis:
  1. neobrowser search '<topic.label> official' → first non-social URL
  2. capture run on that URL → screenshot + text + embedded media
  3. merge new captures into capture_manifest

Result: the broll_resolver downstream finds an official asset for every
main topic without the operator having to provide URLs.
"""
__version__ = "0.1.0"
