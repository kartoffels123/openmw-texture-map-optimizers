"""Core processing functionality shared across texture optimizers"""

from .base_settings import BaseProcessingSettings, ProcessingResult, AnalysisResult
from .file_scanner import FileScanner
from .utils import (
    format_size,
    format_time,
    normalize_format,
    get_tool_paths,
    is_texture_atlas,
    calculate_new_dimensions,
    FORMAT_MAP,
    FILTER_MAP,
    FORMAT_TO_FRIENDLY,
)
from .dds_parser import (
    parse_dds_header,
    parse_dds_header_extended,
    has_adequate_mipmaps,
    parse_tga_header,
    parse_tga_header_extended,
    has_meaningful_alpha,
    analyze_bc1_alpha,
)

__all__ = [
    # Settings and results
    'BaseProcessingSettings',
    'ProcessingResult',
    'AnalysisResult',
    # File discovery
    'FileScanner',
    # Formatting utilities
    'format_size',
    'format_time',
    # Format handling
    'normalize_format',
    'FORMAT_MAP',
    'FILTER_MAP',
    'FORMAT_TO_FRIENDLY',
    # Tool paths
    'get_tool_paths',
    # Texture utilities
    'is_texture_atlas',
    'calculate_new_dimensions',
    # DDS/TGA parsing
    'parse_dds_header',
    'parse_dds_header_extended',
    'has_adequate_mipmaps',
    'parse_tga_header',
    'parse_tga_header_extended',
    # Alpha analysis
    'has_meaningful_alpha',
    'analyze_bc1_alpha',
]
