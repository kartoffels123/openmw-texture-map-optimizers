"""
Core processing logic for normal map optimization
"""

from .processor import (
    NormalMapProcessor,
    ProcessingSettings,
    ProcessingResult,
    AnalysisResult,
    format_size,
    format_time,
    get_parser_stats,
    reset_parser_stats
)

# Also expose normal-specific settings
from .normal_settings import NormalSettings

__all__ = [
    'NormalMapProcessor',
    'ProcessingSettings',
    'NormalSettings',
    'ProcessingResult',
    'AnalysisResult',
    'format_size',
    'format_time',
    'get_parser_stats',
    'reset_parser_stats'
]
