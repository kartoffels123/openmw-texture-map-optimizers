"""Regular texture specific settings"""

import sys
from pathlib import Path
from dataclasses import dataclass
from multiprocessing import cpu_count

# Add core package to path
core_path = Path(__file__).parent.parent.parent.parent / "openmw-texture-optimizer-core" / "src"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from core.base_settings import BaseProcessingSettings


# Default paths to exclude entirely (UI elements, special files)
DEFAULT_BLACKLIST = [
    "icon", "icons", "bookart",  # Original defaults
    "menu_", "tx_menu_",         # Menu textures
    "cursor", "compass", "target",  # UI elements
]

# Default paths that should NOT have mipmaps generated
# These are typically displayed at 1:1 scale (UI, splash screens, etc.)
DEFAULT_NO_MIPMAPS = [
    "birthsigns", "levelup", "splash",  # Folders
    "scroll.*", "tx_scroll.*"            # File patterns
]


@dataclass
class RegularSettings(BaseProcessingSettings):
    """Configuration for regular texture processing

    Format is auto-selected based on alpha channel:
    - No alpha -> BC1/DXT1
    - Has alpha -> BC3/DXT5
    - Small textures -> BGR/BGRA uncompressed
    """

    # Small texture threshold (single threshold, not split like normal maps)
    small_texture_threshold: int = 128

    # Passthrough settings for well-compressed textures
    allow_well_compressed_passthrough: bool = True

    # Preserve compressed format (BC1→BC1, BC2→BC2, BC3→BC3)
    # When True: keeps source format for already-compressed textures
    # When False: recompresses to target format (may waste alpha channel)
    preserve_compressed_format: bool = True

    # Path filtering
    path_whitelist: list = None  # Default: ["Textures"]
    path_blacklist: list = None  # Default: folders to exclude entirely
    custom_blacklist: list = None  # User-added blacklist entries

    # Passthrough output control
    copy_passthrough_files: bool = True  # Copy well-compressed files to output (vs skip them)

    # No-mipmap paths (process but skip mipmap generation)
    no_mipmap_paths: list = None  # Default: UI elements displayed at 1:1

    # Normal map exclusion (exclude _n, _nh suffixes)
    exclude_normal_maps: bool = True

    # File format support
    enable_tga_support: bool = True

    # Alpha optimization (optional, more aggressive compression)
    # When enabled, analyzes alpha channels to detect unused alpha
    # Textures with format-declared alpha but all-opaque pixels can be compressed to BC1
    optimize_unused_alpha: bool = False  # Default OFF - optional feature
    alpha_threshold: int = 255  # Only pixels with alpha == 255 are considered "opaque"

    # Parallel analysis chunk size (batch size for alpha analysis)
    analysis_chunk_size: int = 100  # Number of files to submit per batch

    # Override defaults from base
    uniform_weighting: bool = False  # Default OFF for regular textures
    use_dithering: bool = False      # Default OFF for regular textures

    def __post_init__(self):
        """Set default lists after initialization"""
        if self.path_whitelist is None:
            self.path_whitelist = ["Textures"]
        if self.path_blacklist is None:
            self.path_blacklist = DEFAULT_BLACKLIST.copy()
        if self.custom_blacklist is None:
            self.custom_blacklist = []
        if self.no_mipmap_paths is None:
            self.no_mipmap_paths = DEFAULT_NO_MIPMAPS.copy()

    def to_dict(self) -> dict:
        """Convert settings to dictionary for multiprocessing"""
        base_dict = super().to_dict()
        # Add regular texture specific fields
        base_dict.update({
            'small_texture_threshold': self.small_texture_threshold,
            'allow_well_compressed_passthrough': self.allow_well_compressed_passthrough,
            'preserve_compressed_format': self.preserve_compressed_format,
            'path_whitelist': self.path_whitelist,
            'path_blacklist': self.path_blacklist,
            'custom_blacklist': self.custom_blacklist,
            'copy_passthrough_files': self.copy_passthrough_files,
            'no_mipmap_paths': self.no_mipmap_paths,
            'exclude_normal_maps': self.exclude_normal_maps,
            'enable_tga_support': self.enable_tga_support,
            'optimize_unused_alpha': self.optimize_unused_alpha,
            'alpha_threshold': self.alpha_threshold,
            'analysis_chunk_size': self.analysis_chunk_size,
        })
        return base_dict
