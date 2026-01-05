"""Base settings class for texture processors"""

from dataclasses import dataclass, asdict, field
from multiprocessing import cpu_count
from typing import Optional, List, Tuple


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
    atlas_min_resolution: int = 2048
    atlas_max_resolution: int = 8192

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
    orig_dims: Optional[Tuple[int, int]] = None  # (width, height)
    new_dims: Optional[Tuple[int, int]] = None   # (width, height)
    orig_format: str = 'UNKNOWN'
    new_format: str = 'UNKNOWN'
    error_msg: Optional[str] = None


@dataclass
class AnalysisResult:
    """
    Result from analyzing a single file.

    Base fields are used by all optimizers. Optional fields are used by
    specific optimizers (normal map, regular texture) as needed.
    """
    # Required fields
    relative_path: str
    file_size: int

    # Core analysis fields
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = 'UNKNOWN'
    new_width: Optional[int] = None
    new_height: Optional[int] = None
    target_format: Optional[str] = None
    projected_size: int = 0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # Mipmap info (used by regular textures for passthrough detection)
    mipmap_count: int = 0

    # Passthrough detection (well-compressed textures that don't need reprocessing)
    is_passthrough: bool = False

    # Alpha channel info (used by regular textures for format selection)
    has_alpha: bool = False
    alpha_optimized: bool = False  # True if alpha was detected as unused and optimized away
    original_format: Optional[str] = None  # Original format before alpha optimization
    has_dxt1a: bool = False  # True if BC1/DXT1 uses 1-bit alpha (DXT1a mode)

    # Normal map specific (used by normal map optimizer)
    is_nh: bool = False  # True if this is an _nh (normal+height) texture
