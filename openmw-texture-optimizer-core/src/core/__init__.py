"""Core processing functionality shared across texture optimizers"""

from .base_settings import BaseProcessingSettings, ProcessingResult, AnalysisResult
from .file_scanner import FileScanner
from .utils import format_size, format_time
from .dds_parser import (
    parse_dds_header,
    parse_dds_header_extended,
    has_adequate_mipmaps,
    parse_tga_header,
    parse_tga_header_extended,
)

__all__ = [
    'BaseProcessingSettings',
    'ProcessingResult',
    'AnalysisResult',
    'FileScanner',
    'format_size',
    'format_time',
    'parse_dds_header',
    'parse_dds_header_extended',
    'has_adequate_mipmaps',
    'parse_tga_header',
    'parse_tga_header_extended',
]
