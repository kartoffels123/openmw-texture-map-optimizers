"""
Core processing logic for regular texture optimization
"""

from .regular_processor import (
    RegularTextureProcessor,
    ProcessingResult,
    AnalysisResult,
)
from .regular_settings import RegularSettings

# Re-export utilities from core
import sys
from pathlib import Path
core_path = Path(__file__).parent.parent.parent.parent / "openmw-texture-optimizer-core" / "src"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from core.utils import format_size, format_time
from core.dds_parser import parse_dds_header

__all__ = [
    'RegularTextureProcessor',
    'RegularSettings',
    'ProcessingResult',
    'AnalysisResult',
    'format_size',
    'format_time',
    'parse_dds_header',
]
