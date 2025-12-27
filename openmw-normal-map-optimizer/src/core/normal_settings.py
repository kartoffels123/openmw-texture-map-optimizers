"""Normal map specific settings"""

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
class NormalSettings(BaseProcessingSettings):
    """Configuration for normal map processing"""

    # Normal map specific format settings
    n_format: str = "BC5/ATI2"
    nh_format: str = "BC3/DXT5"

    # Normal map specific processing
    invert_y: bool = False
    reconstruct_z: bool = True

    # Small texture thresholds (separate for _N and _NH)
    small_nh_threshold: int = 256
    small_n_threshold: int = 128

    # Format handling
    preserve_compressed_format: bool = True
    auto_fix_nh_to_n: bool = True
    auto_optimize_n_alpha: bool = True
    allow_compressed_passthrough: bool = False

    # Override defaults from base
    uniform_weighting: bool = True  # Default ON for normal maps

    def to_dict(self) -> dict:
        """Convert settings to dictionary for multiprocessing"""
        base_dict = super().to_dict()
        # Add normal map specific fields
        base_dict.update({
            'n_format': self.n_format,
            'nh_format': self.nh_format,
            'invert_y': self.invert_y,
            'reconstruct_z': self.reconstruct_z,
            'small_nh_threshold': self.small_nh_threshold,
            'small_n_threshold': self.small_n_threshold,
            'preserve_compressed_format': self.preserve_compressed_format,
            'auto_fix_nh_to_n': self.auto_fix_nh_to_n,
            'auto_optimize_n_alpha': self.auto_optimize_n_alpha,
            'allow_compressed_passthrough': self.allow_compressed_passthrough,
        })
        return base_dict
