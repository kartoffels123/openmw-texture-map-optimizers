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


@dataclass
class RegularSettings(BaseProcessingSettings):
    """Configuration for regular texture processing"""

    # Regular texture format (single format for all textures)
    target_format: str = "BC1/DXT1"  # Can be BC1, BC2, BC3, BGRA, BGR

    # Small texture threshold (single threshold, not split like normal maps)
    small_texture_threshold: int = 128

    # Passthrough settings for well-compressed textures
    allow_well_compressed_passthrough: bool = True

    # Path filtering
    path_whitelist: list = None  # Default: ["Textures"]
    path_blacklist: list = None  # Default: ["icon", "icons", "bookart"]
    custom_blacklist: list = None  # User-added blacklist entries

    # File format support
    enable_tga_support: bool = True

    # Override defaults from base
    uniform_weighting: bool = False  # Default OFF for regular textures
    use_dithering: bool = False      # Default OFF for regular textures

    def __post_init__(self):
        """Set default lists after initialization"""
        if self.path_whitelist is None:
            self.path_whitelist = ["Textures"]
        if self.path_blacklist is None:
            self.path_blacklist = ["icon", "icons", "bookart"]
        if self.custom_blacklist is None:
            self.custom_blacklist = []

    def to_dict(self) -> dict:
        """Convert settings to dictionary for multiprocessing"""
        base_dict = super().to_dict()
        # Add regular texture specific fields
        base_dict.update({
            'target_format': self.target_format,
            'small_texture_threshold': self.small_texture_threshold,
            'allow_well_compressed_passthrough': self.allow_well_compressed_passthrough,
            'path_whitelist': self.path_whitelist,
            'path_blacklist': self.path_blacklist,
            'custom_blacklist': self.custom_blacklist,
            'enable_tga_support': self.enable_tga_support,
        })
        return base_dict
