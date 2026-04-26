"""analysis — Editorial analysis phase for myavatar v6.

Consumes transcript_polished.json + sources from capture;
produces arc + beats + topics + entities (analysis.json).

See INTERFACE.md for the frozen contract (v1.0).
"""
from .contracts import AnalysisResult, ArcAct, Beat, Entity, Narrative, Topic
from .analyzer import run

__version__ = "1.0.0"

__all__ = [
    "run",
    "AnalysisResult",
    "ArcAct",
    "Beat",
    "Entity",
    "Narrative",
    "Topic",
]
