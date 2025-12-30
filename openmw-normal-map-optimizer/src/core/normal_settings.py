"""Normal map specific settings"""

from pathlib import Path
from dataclasses import dataclass
import importlib.util
import sys

# =============================================================================
# Shared Core Import
# =============================================================================
# Use importlib to avoid name collision with local 'core' package
# Register modules in sys.modules so they can be pickled for multiprocessing

_shared_core_path = Path(__file__).parent.parent.parent.parent / "openmw-texture-optimizer-core" / "src" / "core"

def _import_shared_module(module_name):
    """Import a module from the shared core package and register in sys.modules."""
    import types
    full_name = f"shared_core.{module_name}"

    # Return existing module if already imported
    if full_name in sys.modules:
        return sys.modules[full_name]

    # Ensure parent package exists in sys.modules
    if "shared_core" not in sys.modules:
        shared_core_pkg = types.ModuleType("shared_core")
        shared_core_pkg.__path__ = [str(_shared_core_path)]
        sys.modules["shared_core"] = shared_core_pkg

    spec = importlib.util.spec_from_file_location(
        full_name,
        _shared_core_path / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)

    # Register in sys.modules BEFORE executing (handles circular imports)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)

    # Also set as attribute on parent package
    setattr(sys.modules["shared_core"], module_name, module)

    return module

_base_settings = _import_shared_module("base_settings")
BaseProcessingSettings = _base_settings.BaseProcessingSettings


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

    # Passthrough output control
    copy_passthrough_files: bool = False  # Copy well-compressed files to output (vs skip them)

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
            'copy_passthrough_files': self.copy_passthrough_files,
        })
        return base_dict
