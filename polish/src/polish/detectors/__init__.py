"""Detectors emit `CutRegion` candidates for the cut_planner.

Each detector is pure: same audio/transcript + same config = same output.
Detectors never mutate state; they append to a list.
"""
