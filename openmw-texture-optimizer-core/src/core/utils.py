"""Shared utility functions for texture optimizers"""

import sys
from pathlib import Path
from typing import Tuple, Optional


def format_size(bytes_size: int) -> str:
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def format_time(seconds: float) -> str:
    """Format time in human-readable format"""
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.0f}s"


# Format mapping constants
FORMAT_MAP = {
    "BC5/ATI2": "BC5_UNORM",
    "BC1/DXT1": "BC1_UNORM",
    "BC2/DXT3": "BC2_UNORM",
    "BC3/DXT5": "BC3_UNORM",
    "BGRA": "B8G8R8A8_UNORM",
    "BGR": "B8G8R8X8_UNORM"
}

FILTER_MAP = {
    "FANT": "FANT",
    "CUBIC": "CUBIC",
    "BOX": "BOX",
    "LINEAR": "LINEAR"
}

# Reverse format map: DXGI names -> friendly names
FORMAT_TO_FRIENDLY = {
    'BC5_UNORM': 'BC5/ATI2',
    'BC3_UNORM': 'BC3/DXT5',
    'BC2_UNORM': 'BC2/DXT3',
    'BC1_UNORM': 'BC1/DXT1',
    'B8G8R8A8_UNORM': 'BGRA',
    'R8G8B8A8_UNORM': 'RGBA',
    'B8G8R8X8_UNORM': 'BGR',
    'B8G8R8_UNORM': 'BGR',
    'R8G8B8_UNORM': 'RGB',
    # 16-bit formats
    'B5G6R5_UNORM': 'RGB565',
    'B5G5R5A1_UNORM': 'RGB5A1',
    'B4G4R4A4_UNORM': 'RGBA4',
    'RGB16_UNORM': 'RGB16',
    # Special formats (passthrough)
    'A8_UNORM': 'A8_UNORM',  # Alpha-only texture
}


def normalize_format(fmt: str) -> str:
    """
    Normalize format names to friendly format (e.g., BC1_UNORM -> BC1/DXT1).

    Args:
        fmt: Format string (e.g., 'BC1_UNORM', 'BC3_UNORM', 'B8G8R8A8_UNORM')

    Returns:
        Normalized format string (e.g., 'BC1/DXT1', 'BC3/DXT5', 'BGRA')
    """
    return FORMAT_TO_FRIENDLY.get(fmt, fmt)


def get_tool_paths(script_dir: Path = None) -> Tuple[str, str, Optional[str]]:
    """
    Get paths to texture processing tools.

    Handles both frozen (PyInstaller) and script execution modes.

    Args:
        script_dir: Optional override for the script directory. If None, auto-detects.
                   Callers should pass the root directory of their optimizer
                   (e.g., openmw-normal-map-optimizer/).

    Returns:
        Tuple of (texconv_path, texdiag_path, cuttlefish_path)
        cuttlefish_path may be None if not found.
    """
    if script_dir is None:
        if hasattr(sys, 'frozen'):
            # PyInstaller frozen executable
            script_dir = Path(sys.executable).parent
        else:
            # Running as script from shared core - look for tools in parent optimizer directories
            # This file is at: openmw-texture-optimizer-core/src/core/utils.py
            # Tools are at: openmw-texture-map-optimizers/tools/ (shared location)
            # or in each optimizer's tools/ directory
            shared_core_dir = Path(__file__).parent.parent.parent.parent  # openmw-texture-map-optimizers/
            script_dir = shared_core_dir

    tools_dir = script_dir / "tools"

    texconv_path = str(tools_dir / "texconv.exe")
    texdiag_path = str(tools_dir / "texdiag.exe")
    cuttlefish_path = tools_dir / "cuttlefish.exe"

    # Only return cuttlefish path if it exists
    cuttlefish_str = str(cuttlefish_path) if cuttlefish_path.exists() else None

    return texconv_path, texdiag_path, cuttlefish_str


def is_texture_atlas(file_path: Path) -> bool:
    """
    Detect if a file is likely a texture atlas (should not be resized).

    Checks for:
    - 'atlas' in filename
    - 'atl' as a directory component in path

    Args:
        file_path: Path to the texture file

    Returns:
        True if file appears to be a texture atlas
    """
    # Check for "atlas" in filename
    if 'atlas' in file_path.stem.lower():
        return True

    # Check for "ATL" or "atl" directory in path
    path_parts = [p.lower() for p in file_path.parts]
    if 'atl' in path_parts:
        return True

    return False


def _round_down_to_power_of_2(n: int) -> int:
    """Round down to nearest power of 2."""
    if n <= 0:
        return 1
    # Find highest set bit position
    power = 1
    while power * 2 <= n:
        power *= 2
    return power


def calculate_new_dimensions(
    orig_width: int,
    orig_height: int,
    settings: dict,
    file_path: Path = None,
    is_atlas: bool = False
) -> Tuple[int, int]:
    """
    Calculate new dimensions based on scale factor and constraints.

    Args:
        orig_width: Original texture width
        orig_height: Original texture height
        settings: Dict containing scale_factor, max_resolution, min_resolution,
                  enable_atlas_downscaling, atlas_max_resolution, enforce_power_of_2
        file_path: Optional path for atlas auto-detection (prefer is_atlas flag)
        is_atlas: Whether this is a texture atlas (if True, overrides file_path check)

    Returns:
        Tuple of (new_width, new_height)

    Raises:
        ValueError: If orig_width or orig_height <= 0
    """
    # Guard against invalid dimensions
    if orig_width <= 0 or orig_height <= 0:
        raise ValueError(f"Invalid texture dimensions: {orig_width}x{orig_height}")

    new_width, new_height = orig_width, orig_height

    # Determine if this is an atlas (prefer explicit flag, fallback to detection)
    if not is_atlas and file_path:
        is_atlas = is_texture_atlas(file_path)

    # Skip resizing for texture atlases (unless explicitly enabled)
    if is_atlas and not settings.get('enable_atlas_downscaling', False):
        return new_width, new_height

    scale = settings.get('scale_factor', 1.0)
    min_res = settings.get('min_resolution', 0)

    # Apply scale factor, but respect min_resolution as a floor
    if scale != 1.0:
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)

        # If downscaling (scale < 1.0), enforce minimum resolution as a floor
        if scale < 1.0 and min_res > 0:
            if new_width < min_res or new_height < min_res:
                # Don't downscale - keep original dimensions
                new_width = orig_width
                new_height = orig_height

        # Ensure dimensions don't become 0 after scaling
        new_width = max(1, new_width)
        new_height = max(1, new_height)

    # Use atlas-specific max resolution if this is an atlas
    max_res = settings.get('atlas_max_resolution', 4096) if is_atlas else settings.get('max_resolution', 0)
    if max_res > 0:
        max_dim = max(new_width, new_height)
        if max_dim > max_res and max_dim > 0:
            scale_factor = max_res / max_dim
            new_width = int(new_width * scale_factor)
            new_height = int(new_height * scale_factor)
            new_width = max(1, new_width)
            new_height = max(1, new_height)

    # Enforce power of 2 dimensions if requested
    if settings.get('enforce_power_of_2', False):
        new_width = _round_down_to_power_of_2(new_width)
        new_height = _round_down_to_power_of_2(new_height)

    return new_width, new_height
