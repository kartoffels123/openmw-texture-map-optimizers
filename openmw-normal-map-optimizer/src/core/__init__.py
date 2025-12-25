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

__all__ = [
    'NormalMapProcessor',
    'ProcessingSettings',
    'ProcessingResult',
    'AnalysisResult',
    'format_size',
    'format_time',
    'get_parser_stats',
    'reset_parser_stats'
]
