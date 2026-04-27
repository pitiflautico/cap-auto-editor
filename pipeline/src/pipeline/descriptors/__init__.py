"""Phase descriptor modules."""
from .capture import capture_descriptor
from .polish import polish_descriptor
from .analysis import analysis_descriptor
from .entity_enricher import entity_enricher_descriptor
from .auto_source import auto_source_descriptor
from .visual_inventory import visual_inventory_descriptor
from .script_finalizer import script_finalizer_descriptor
from .broll_resolver import broll_resolver_descriptor
from .acquisition import acquisition_descriptor
from .storyboard import storyboard_descriptor

__all__ = [
    "capture_descriptor",
    "polish_descriptor",
    "analysis_descriptor",
    "entity_enricher_descriptor",
    "auto_source_descriptor",
    "visual_inventory_descriptor",
    "script_finalizer_descriptor",
    "broll_resolver_descriptor",
    "acquisition_descriptor",
    "storyboard_descriptor",
]
