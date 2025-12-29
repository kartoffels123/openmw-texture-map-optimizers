"""
Core processing logic for regular texture optimization.

This module imports from the shared openmw-texture-optimizer-core package.
"""

# Import from local modules - these re-export the shared core types
from .regular_processor import (
    RegularTextureProcessor,
    ProcessingResult,
    AnalysisResult,
    format_size,
    format_time,
    parse_dds_header,
)
from .regular_settings import RegularSettings

__all__ = [
    'RegularTextureProcessor',
    'RegularSettings',
    'ProcessingResult',
    'AnalysisResult',
    'format_size',
    'format_time',
    'parse_dds_header',
]
