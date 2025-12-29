"""
Core processing logic for normal map optimization.

This module imports from the shared openmw-texture-optimizer-core package.
"""

# Import from local modules - these re-export the shared core types
from .processor import (
    NormalMapProcessor,
    ProcessingResult,
    AnalysisResult,
    format_size,
    format_time,
    get_parser_stats,
    reset_parser_stats,
)
from .normal_settings import NormalSettings

# For backwards compatibility, alias NormalSettings as ProcessingSettings
ProcessingSettings = NormalSettings

__all__ = [
    'NormalMapProcessor',
    'NormalSettings',
    'ProcessingSettings',  # Backwards compatibility alias
    'ProcessingResult',
    'AnalysisResult',
    'format_size',
    'format_time',
    'get_parser_stats',
    'reset_parser_stats',
]
