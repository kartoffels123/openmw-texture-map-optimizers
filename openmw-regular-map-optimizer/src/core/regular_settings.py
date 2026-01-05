"""Regular texture specific settings"""

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


# Default paths to exclude entirely (UI elements, special files)
DEFAULT_BLACKLIST = [
    "icon", "icons", "bookart",  # Original defaults
    "menu_", "tx_menu_",         # Menu textures
    "cursor", "compass", "target",  # UI elements
    "hud", "splash", "logo", "font", "loading",  # Common UI patterns
]

# Aggressive blacklist (optional, disabled by default)
# These patterns may catch some legitimate 3D textures but are commonly UI-related
AGGRESSIVE_BLACKLIST = [
    "levelup", "char_", "scroll", "button", "bar_", "slot",  # UI elements
    "(openmw",  # OpenMW Lua mods often have UI textures (e.g., "(OpenMW 0.49) Floating Healthbars")
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
    copy_passthrough_files: bool = False  # Copy well-compressed files to output (vs skip them)

    # No-mipmap paths (process but skip mipmap generation)
    no_mipmap_paths: list = None  # Default: UI elements displayed at 1:1

    # Normal map exclusion (exclude _n, _nh suffixes)
    exclude_normal_maps: bool = True

    # File format support
    enable_tga_support: bool = True

    # Alpha optimization (RECOMMENDED - enabled by default)
    # When enabled, analyzes alpha channels to detect:
    # 1. Unused alpha: Textures with format-declared alpha but all-opaque pixels -> BC1
    # 2. DXT1a detection: BC1 textures using 1-bit alpha -> preserve as BC2 when reprocessing
    # This is the only reliable way to detect DXT1a textures which would otherwise lose alpha
    optimize_unused_alpha: bool = True  # Default ON - recommended for accurate processing
    alpha_threshold: int = 255  # Only pixels with alpha == 255 are considered "opaque"

    # Parallel analysis chunk size (batch size for alpha analysis)
    analysis_chunk_size: int = 100  # Number of files to submit per batch

    # Override defaults from base
    uniform_weighting: bool = False  # Default OFF for regular textures
    use_dithering: bool = False      # Default OFF for regular textures

    # Land texture handling
    # Land textures (LTEX) tile across terrain and should stay high-resolution
    # Use land_texture_scanner.py to generate the exclusion list from ESP/ESM files
    land_texture_file: str = None  # Path to txt file with land texture stems
    # Land textures are still processed (compression, alpha, mipmaps) but NOT resized by default
    resize_land_textures: bool = False  # If False, skip resizing. If True, use custom limits
    # TODO: Consider adding option to also protect related maps (_spec, _glow, _env, etc.)
    #       Currently uses exact stem match. Could add prefix matching or suffix stripping.
    land_texture_min_resolution: int = 2048  # Floor - don't go below this (only if resize enabled)
    land_texture_max_resolution: int = 8192  # Ceiling - don't go above this (only if resize enabled)

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
            'land_texture_file': self.land_texture_file,
            'resize_land_textures': self.resize_land_textures,
            'land_texture_min_resolution': self.land_texture_min_resolution,
            'land_texture_max_resolution': self.land_texture_max_resolution,
        })
        return base_dict
