"""Base settings class for texture processors"""

from dataclasses import dataclass, asdict
from multiprocessing import cpu_count


@dataclass
class BaseProcessingSettings:
    """Base configuration for texture processing - shared across all optimizers"""

    # Resizing settings
    scale_factor: float = 1.0
    max_resolution: int = 2048
    min_resolution: int = 256
    resize_method: str = "CUBIC"
    enforce_power_of_2: bool = True

    # Compression settings
    uniform_weighting: bool = True
    use_dithering: bool = False

    # Small texture handling
    use_small_texture_override: bool = True

    # Atlas handling
    enable_atlas_downscaling: bool = False
    atlas_max_resolution: int = 4096

    # Performance settings
    enable_parallel: bool = True
    max_workers: int = max(1, cpu_count() - 1)
    chunk_size_mb: int = 75

    def to_dict(self) -> dict:
        """Convert settings to dictionary for multiprocessing"""
        return asdict(self)


@dataclass
class ProcessingResult:
    """Result from processing a single file"""
    success: bool
    relative_path: str
    input_size: int
    output_size: int = 0
    orig_dims: tuple = None  # (width, height)
    new_dims: tuple = None   # (width, height)
    orig_format: str = 'UNKNOWN'
    new_format: str = 'UNKNOWN'
    error_msg: str = None


@dataclass
class AnalysisResult:
    """Result from analyzing a single file"""
    relative_path: str
    file_size: int
    width: int = None
    height: int = None
    format: str = 'UNKNOWN'
    new_width: int = None
    new_height: int = None
    target_format: str = None
    projected_size: int = 0
    error: str = None
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
