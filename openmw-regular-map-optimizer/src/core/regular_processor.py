"""
Core logic for OpenMW Regular Texture Optimizer.
Handles file processing, analysis, and conversion for regular (non-normal map) textures.
"""

from pathlib import Path
import subprocess
import shutil
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable
import sys

# Get the directory where the tools are located
if hasattr(sys, 'frozen'):
    SCRIPT_DIR = Path(sys.executable).parent
else:
    SCRIPT_DIR = Path(__file__).parent.parent.parent  # Go up to project root

TEXDIAG_EXE = str(SCRIPT_DIR / "tools" / "texdiag.exe")
TEXCONV_EXE = str(SCRIPT_DIR / "tools" / "texconv.exe")
CUTTLEFISH_EXE = str(SCRIPT_DIR / "tools" / "cuttlefish.exe")

# Add core package to path
core_path = Path(__file__).parent.parent.parent.parent / "openmw-texture-optimizer-core" / "src"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

# Import from shared core
from core.dds_parser import (
    parse_dds_header,
    parse_dds_header_extended,
    has_adequate_mipmaps,
    parse_tga_header,
    parse_tga_header_extended,
    has_meaningful_alpha,
    analyze_bc1_alpha,
)
from core.file_scanner import FileScanner
from core.utils import format_size, format_time, FORMAT_MAP, FILTER_MAP


@dataclass
class ProcessingResult:
    """Result from processing a single file"""
    success: bool
    relative_path: str
    input_size: int
    output_size: int = 0
    orig_dims: Optional[Tuple[int, int]] = None
    new_dims: Optional[Tuple[int, int]] = None
    orig_format: str = 'UNKNOWN'
    new_format: str = 'UNKNOWN'
    error_msg: Optional[str] = None


@dataclass
class AnalysisResult:
    """Result from analyzing a single file"""
    relative_path: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = 'UNKNOWN'
    mipmap_count: int = 0
    new_width: Optional[int] = None
    new_height: Optional[int] = None
    target_format: Optional[str] = None
    projected_size: int = 0
    error: Optional[str] = None
    warnings: List[str] = None
    is_passthrough: bool = False
    has_alpha: bool = False
    # Alpha optimization tracking
    alpha_optimized: bool = False  # True if alpha was detected as unused and optimized away
    original_format: str = None  # Original format before alpha optimization (e.g., BC3/DXT5 -> BC1/DXT1)
    has_dxt1a: bool = False  # True if BC1/DXT1 uses 1-bit alpha (DXT1a mode)

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# Format mapping for regular textures (no BC5)
# texconv format mapping (legacy, kept for reference)
REGULAR_FORMAT_MAP = {
    "BC1/DXT1": "BC1_UNORM",
    "BC2/DXT3": "BC2_UNORM",
    "BC3/DXT5": "BC3_UNORM",
    "BGRA": "B8G8R8A8_UNORM",
    "BGR": "B8G8R8X8_UNORM"
}

# Cuttlefish format mapping
# BC1_RGB = opaque (no alpha), BC1_RGBA = 1-bit alpha
# Note: BGR uses texconv fallback since cuttlefish can't write 24-bit DDS
CUTTLEFISH_FORMAT_MAP = {
    "BC1/DXT1": "BC1_RGB",      # Use BC1_RGB for opaque textures
    "BC1/DXT1a": "BC1_RGBA",    # Use BC1_RGBA for 1-bit alpha (punchthrough)
    "BC2/DXT3": "BC2",          # 4-bit alpha
    "BC3/DXT5": "BC3",          # Interpolated alpha
    "BGRA": "B8G8R8A8",         # Uncompressed with alpha
}

# Cuttlefish filter mapping (for resize operations)
# Cuttlefish supports: box, linear, cubic, b-spline, catmull-rom (default)
CUTTLEFISH_FILTER_MAP = {
    "BOX": "box",
    "LINEAR": "linear",
    "CUBIC": "cubic",
    "B-SPLINE": "b-spline",
    "CATMULL-ROM": "catmull-rom",
}

# Formats that support alpha
ALPHA_FORMATS = ["BC2/DXT3", "BC3/DXT5", "BGRA", "RGBA"]
NO_ALPHA_FORMATS = ["BC1/DXT1", "BGR", "RGB"]


def _normalize_format(fmt: str) -> str:
    """Normalize format names for comparison"""
    format_map = {
        'BC5_UNORM': 'BC5/ATI2',
        'BC3_UNORM': 'BC3/DXT5',
        'BC2_UNORM': 'BC2/DXT3',
        'BC1_UNORM': 'BC1/DXT1',
        'B8G8R8A8_UNORM': 'BGRA',
        'R8G8B8A8_UNORM': 'RGBA',
        'B8G8R8X8_UNORM': 'BGR',
        'B8G8R8_UNORM': 'BGR',
        'R8G8B8_UNORM': 'RGB',
    }
    return format_map.get(fmt, fmt)


def _is_well_compressed(format_str: str, mipmap_count: int, width: int, height: int) -> bool:
    """
    Check if a texture is "well compressed" and can be passed through.

    A well-compressed texture:
    - Is in BC1, BC2, or BC3 format
    - Has adequate mipmaps (more than just base level for textures > 4x4)
    """
    normalized = _normalize_format(format_str)

    # Must be a compressed format
    if normalized not in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']:
        return False

    # Must have adequate mipmaps
    return has_adequate_mipmaps(width, height, mipmap_count)


def _has_alpha_channel(format_str: str) -> bool:
    """
    Check if a format has an alpha channel.

    Note: BC1/DXT1 can have 1-bit alpha (DXT1a) but detecting it requires
    scanning the compressed block data. We treat BC1 as opaque for passthrough
    purposes - if it has DXT1a, it should stay as BC1.
    """
    # Handle TGA formats directly
    if format_str == 'TGA_RGBA':
        return True
    if format_str in ('TGA_RGB', 'TGA'):
        return False
    normalized = _normalize_format(format_str)
    # BC1/DXT1 might have 1-bit alpha (DXT1a) but we can't detect without scanning blocks
    # For passthrough, we treat BC1 as "handled" - don't upgrade to BC3
    return normalized in ['BC3/DXT5', 'BC2/DXT3', 'BGRA', 'RGBA']


def _is_texture_atlas(file_path: Path) -> bool:
    """Detect if a file is likely a texture atlas"""
    if 'atlas' in file_path.stem.lower():
        return True
    path_parts = [p.lower() for p in file_path.parts]
    if 'atl' in path_parts:
        return True
    return False


def _matches_pattern(file_path: Path, patterns: list) -> bool:
    """
    Check if a file matches any of the given patterns.

    Patterns can be:
    - Folder names: "birthsigns", "splash" (matches any file in that folder)
    - File patterns with wildcards: "scroll.*", "cursor*", "menu_*"
    """
    import fnmatch

    if not patterns:
        return False

    path_str = str(file_path).lower()
    filename = file_path.name.lower()
    stem = file_path.stem.lower()
    path_parts = [p.lower() for p in file_path.parts]

    for pattern in patterns:
        pattern_lower = pattern.lower()

        # Check if it's a wildcard pattern (contains * or ?)
        if '*' in pattern_lower or '?' in pattern_lower:
            # Match against filename
            if fnmatch.fnmatch(filename, pattern_lower):
                return True
            # Also match against stem (without extension)
            if fnmatch.fnmatch(stem, pattern_lower):
                return True
        else:
            # It's a folder/path component match
            if pattern_lower in path_parts:
                return True
            # Also check if filename starts with pattern (for menu_, tx_menu_, etc.)
            if filename.startswith(pattern_lower) or stem.startswith(pattern_lower):
                return True

    return False


def _should_skip_mipmaps(file_path: Path, settings: dict) -> bool:
    """Check if mipmaps should be skipped for this file."""
    no_mipmap_paths = settings.get('no_mipmap_paths', [])
    return _matches_pattern(file_path, no_mipmap_paths)


def _calculate_new_dimensions(orig_width: int, orig_height: int, settings: dict,
                              file_path: Path = None, is_atlas: bool = False) -> Tuple[int, int]:
    """Calculate new dimensions based on scale factor and constraints"""
    if orig_width <= 0 or orig_height <= 0:
        raise ValueError(f"Invalid texture dimensions: {orig_width}x{orig_height}")

    new_width, new_height = orig_width, orig_height

    if not is_atlas and file_path:
        is_atlas = _is_texture_atlas(file_path)

    # Skip resizing for texture atlases unless enabled
    if is_atlas and not settings.get('enable_atlas_downscaling', False):
        return new_width, new_height

    scale = settings['scale_factor']
    min_res = settings['min_resolution']

    if scale != 1.0:
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)

        if scale < 1.0 and min_res > 0:
            if new_width < min_res or new_height < min_res:
                new_width = orig_width
                new_height = orig_height

        new_width = max(1, new_width)
        new_height = max(1, new_height)

    max_res = settings.get('atlas_max_resolution', 4096) if is_atlas else settings['max_resolution']
    if max_res > 0:
        max_dim = max(new_width, new_height)
        if max_dim > max_res and max_dim > 0:
            scale_factor = max_res / max_dim
            new_width = int(new_width * scale_factor)
            new_height = int(new_height * scale_factor)
            new_width = max(1, new_width)
            new_height = max(1, new_height)

    return new_width, new_height


def _process_texture_with_texconv(input_path: Path, output_path: Path, target_format: str,
                                   new_width: int, new_height: int, will_resize: bool,
                                   skip_mipmaps: bool, settings: dict) -> Tuple[bool, Optional[str]]:
    """
    Process texture using texconv (legacy tool).
    Used for BGR (24-bit) textures since cuttlefish can't write 24-bit DDS.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # texconv format
        texconv_format = REGULAR_FORMAT_MAP.get(target_format, "B8G8R8X8_UNORM")

        cmd = [
            TEXCONV_EXE,
            "-nologo",
            "-y",  # Overwrite
            "-f", texconv_format,
            "-o", str(output_path.parent),
        ]

        # Resize if needed
        if will_resize:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])

        # Mipmaps
        if skip_mipmaps:
            cmd.extend(["-m", "1"])

        cmd.append(str(input_path))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"texconv failed (exit {result.returncode}): {error_msg.strip()}"

        # texconv outputs to directory with original filename, need to rename if different
        texconv_output = output_path.parent / input_path.with_suffix('.dds').name
        if texconv_output != output_path and texconv_output.exists():
            shutil.move(texconv_output, output_path)

        if not output_path.exists():
            return False, f"Output file not created: {output_path}"

        return True, None

    except Exception as e:
        return False, f"Exception: {str(e)}"


def _process_texture_static(input_path: Path, output_path: Path, settings: dict) -> Tuple[bool, Optional[str]]:
    """
    Process a single texture file.

    Uses cuttlefish for BC compression (better PSNR, 2-5 dB higher than texconv).
    Falls back to texconv for BGR (24-bit) small textures since cuttlefish can't write 24-bit DDS.

    Decision Priority Order (matches _analyze_file_worker):
    1. Compressed (BC1/BC2/BC3): passthrough if valid, else reprocess keeping format
    2. Uncompressed: small -> BGR/BGRA, normal -> BC1/BC3 based on alpha
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # === STEP 0: Parse file header ===
        if input_path.suffix.lower() == '.tga':
            dimensions, format_name, mipmap_count = parse_tga_header_extended(input_path)
            if not dimensions:
                return False, "Could not parse TGA header"
            has_alpha = (format_name == 'TGA_RGBA')

            # Optional: Check if TGA alpha is actually used
            optimize_alpha = settings.get('optimize_unused_alpha', False)
            if optimize_alpha and has_alpha:
                alpha_threshold = settings.get('alpha_threshold', 250)
                actually_has_alpha = has_meaningful_alpha(input_path, format_name, alpha_threshold)
                if not actually_has_alpha:
                    has_alpha = False
        else:
            dimensions, format_name, mipmap_count = parse_dds_header_extended(input_path)
            if not dimensions:
                return False, "Could not parse DDS header"
            format_name = _normalize_format(format_name)
            has_alpha = _has_alpha_channel(format_name)

        # Optional: Check if alpha is actually used (not just declared in format)
        optimize_alpha = settings.get('optimize_unused_alpha', False)
        if optimize_alpha and has_alpha:
            alpha_threshold = settings.get('alpha_threshold', 250)
            actually_has_alpha = has_meaningful_alpha(input_path, format_name, alpha_threshold)
            if not actually_has_alpha:
                has_alpha = False

        orig_width, orig_height = dimensions
        new_width, new_height = _calculate_new_dimensions(orig_width, orig_height, settings, input_path)
        will_resize = (new_width != orig_width) or (new_height != orig_height)

        # === STEP 1: Handle compressed textures (BC1/BC2/BC3) ===
        is_compressed = format_name in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']
        has_valid_mipmaps = _is_well_compressed(format_name, mipmap_count, orig_width, orig_height)

        if is_compressed:
            if not will_resize and has_valid_mipmaps:
                # Passthrough: copy as-is if enabled
                if settings.get('copy_passthrough_files', True):
                    shutil.copy2(input_path, output_path)
                return True, None
            else:
                # Reprocess but keep same format
                target_format = format_name

        # === STEP 2: Handle uncompressed textures ===
        else:
            small_threshold = settings.get('small_texture_threshold', 128)
            use_small_override = settings.get('use_small_texture_override', True)
            min_dim = min(new_width, new_height)

            if use_small_override and small_threshold > 0 and min_dim <= small_threshold:
                # Small texture: keep uncompressed
                target_format = "BGRA" if has_alpha else "BGR"
            else:
                # Normal size: compress based on alpha
                target_format = 'BC3/DXT5' if has_alpha else 'BC1/DXT1'

        # Check if mipmaps should be skipped for this file
        skip_mipmaps = _should_skip_mipmaps(input_path, settings)

        # === Use texconv for BGR (24-bit) - cuttlefish can't write 24-bit DDS ===
        if target_format == "BGR":
            return _process_texture_with_texconv(
                input_path, output_path, target_format,
                new_width, new_height, will_resize, skip_mipmaps, settings
            )

        # === Use cuttlefish for everything else (better PSNR) ===
        cuttlefish_format = CUTTLEFISH_FORMAT_MAP.get(target_format, "BC1_RGB")

        # Build cuttlefish command
        cmd = [
            CUTTLEFISH_EXE,
            "-i", str(input_path),
            "-o", str(output_path),
            "-f", cuttlefish_format,
            "-Q", "highest",  # Use highest quality for best PSNR
            "--create-dir",   # Create output directory if needed
        ]

        # Resize handling
        resize_method = str(settings.get('resize_method', 'CATMULL-ROM')).split()[0].upper()
        cuttlefish_filter = CUTTLEFISH_FILTER_MAP.get(resize_method, "catmull-rom")
        enforce_po2 = settings.get('enforce_power_of_2', True)

        if will_resize:
            cmd.extend(["-r", str(new_width), str(new_height), cuttlefish_filter])
        elif enforce_po2:
            cmd.extend(["-r", "nearestpo2", "nearestpo2"])

        # Mipmap generation
        if not skip_mipmaps:
            cmd.append("-m")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"cuttlefish failed (exit {result.returncode}): {error_msg.strip()}\nCommand: {' '.join(cmd)}"

        if not output_path.exists():
            return False, f"Output file not created: {output_path}"

        return True, None

    except Exception as e:
        return False, f"Exception: {str(e)}"


def _process_file_worker(args):
    """Worker function for parallel processing."""
    file_path, source_dir_path, output_dir_path, settings, cached_analysis = args

    input_file = Path(file_path)
    source_dir = Path(source_dir_path)
    output_dir = Path(output_dir_path)

    relative_path = input_file.relative_to(source_dir)

    # Output is always .dds even if input was .tga
    output_relative = relative_path.with_suffix('.dds')
    output_file = output_dir / output_relative

    result = ProcessingResult(
        success=False,
        relative_path=str(relative_path),
        input_size=input_file.stat().st_size
    )

    try:
        if cached_analysis:
            result.orig_dims = (cached_analysis['width'], cached_analysis['height'])
            result.orig_format = cached_analysis['format']
        else:
            dims, fmt = parse_dds_header(input_file)
            result.orig_dims = dims
            result.orig_format = fmt

        success, error_detail = _process_texture_static(input_file, output_file, settings)

        if success and output_file.exists():
            result.success = True
            result.output_size = output_file.stat().st_size
            new_dims, new_fmt = parse_dds_header(output_file)
            result.new_dims = new_dims
            result.new_format = new_fmt
        else:
            result.error_msg = error_detail or "Processing failed or output missing"

    except Exception as e:
        result.error_msg = str(e)

    return result


def _analyze_file_worker(args):
    """
    Worker function for parallel analysis.

    Decision Priority Order (simplified for regular textures):
    =========================================================
    1. Compressed textures (BC1/BC2/BC3):
       - If NOT resizing AND has valid mipmaps -> passthrough (copy as-is or skip)
       - If resizing OR invalid mipmaps -> reprocess, keep same format
    2. Uncompressed textures (TGA, BGR, BGRA):
       - Small textures (below threshold) -> keep uncompressed (BGR/BGRA)
       - RGB (no alpha) -> BC1
       - RGBA (has alpha) -> BC3
    """
    file_path, source_dir_path, settings = args

    input_file = Path(file_path)
    source_dir = Path(source_dir_path)
    relative_path = input_file.relative_to(source_dir)
    file_size = input_file.stat().st_size

    result = AnalysisResult(
        relative_path=str(relative_path),
        file_size=file_size
    )

    try:
        # === STEP 0: Parse file header ===
        if input_file.suffix.lower() == '.tga':
            dimensions, format_name, mipmap_count = parse_tga_header_extended(input_file)
            if not dimensions:
                result.error = "Could not parse TGA header"
                return result
            result.width, result.height = dimensions
            result.format = format_name  # TGA_RGBA or TGA_RGB
            result.mipmap_count = 1  # TGA never has mipmaps
        else:
            dimensions, format_name, mipmap_count = parse_dds_header_extended(input_file)
            if not dimensions:
                result.error = "Could not determine dimensions"
                return result
            result.width, result.height = dimensions
            result.format = _normalize_format(format_name)
            result.mipmap_count = mipmap_count

        # Determine if source has alpha
        result.has_alpha = _has_alpha_channel(result.format)

        # Check for BC1/DXT1 with 1-bit alpha (DXT1a mode)
        if result.format == 'BC1/DXT1':
            try:
                if analyze_bc1_alpha(input_file):
                    result.has_dxt1a = True
                    result.warnings.append("BC1/DXT1 uses 1-bit alpha (DXT1a mode)")
            except Exception:
                pass  # Ignore errors, assume no DXT1a

        # Optional: Check if alpha is actually used (not just declared in format)
        optimize_alpha = settings.get('optimize_unused_alpha', False)
        if optimize_alpha and result.has_alpha:
            alpha_threshold = settings.get('alpha_threshold', 255)
            # Check if alpha is actually meaningful (not all opaque)
            actually_has_alpha = has_meaningful_alpha(input_file, result.format, alpha_threshold)
            if not actually_has_alpha:
                # Track the optimization
                result.alpha_optimized = True
                result.original_format = result.format
                result.has_alpha = False
                # Note: actual target format determined later (BC1 for normal size, BGR for small)

        # Calculate new dimensions (handles atlas protection, max/min resolution)
        is_atlas = _is_texture_atlas(input_file)
        new_width, new_height = _calculate_new_dimensions(
            result.width, result.height, settings, is_atlas=is_atlas
        )
        result.new_width = new_width
        result.new_height = new_height
        will_resize = (new_width != result.width) or (new_height != result.height)

        # === STEP 1: Handle compressed textures (BC1/BC2/BC3) ===
        is_compressed = result.format in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']
        has_valid_mipmaps = _is_well_compressed(result.format, result.mipmap_count, result.width, result.height)

        if is_compressed:
            # Determine target format based on alpha optimization
            if result.alpha_optimized:
                # Alpha was unused - downgrade to BC1
                target_format = 'BC1/DXT1'
            else:
                # Keep original format
                target_format = result.format

            if not will_resize and has_valid_mipmaps and not result.alpha_optimized:
                # Passthrough: already compressed with valid mipmaps, no resize needed, no alpha change
                result.is_passthrough = True
                result.target_format = result.format
                result.warnings.append(f"Passthrough: {result.format} with valid mipmaps")
                result.projected_size = file_size
                return result
            else:
                # Need to reprocess (resize, fix mipmaps, or alpha optimization)
                result.target_format = target_format
                if result.alpha_optimized:
                    result.warnings.append(f"Alpha unused ({result.original_format} → {target_format})")
                elif will_resize:
                    result.warnings.append(f"Reprocessing {result.format}: resize required")
                else:
                    result.warnings.append(f"Reprocessing {result.format}: mipmap regeneration")

        # === STEP 2: Handle uncompressed textures (TGA, BGR, BGRA) ===
        else:
            # Check small texture threshold first
            small_threshold = settings.get('small_texture_threshold', 128)
            use_small_override = settings.get('use_small_texture_override', True)
            min_dim = min(new_width, new_height)

            if use_small_override and small_threshold > 0 and min_dim <= small_threshold:
                # Small texture: keep uncompressed
                result.target_format = "BGRA" if result.has_alpha else "BGR"
                if result.alpha_optimized:
                    result.warnings.append(f"Small texture ({min_dim}px) - alpha unused, using BGR")
                else:
                    result.warnings.append(f"Small texture ({min_dim}px) - keeping uncompressed as {result.target_format}")
            else:
                # Normal size: compress based on alpha
                if result.has_alpha:
                    result.target_format = 'BC3/DXT5'
                else:
                    result.target_format = 'BC1/DXT1'
                    if result.alpha_optimized:
                        result.warnings.append(f"Alpha unused ({result.original_format} → BC1/DXT1)")

        # === STEP 4: Check mipmap status ===
        skip_mipmaps = _should_skip_mipmaps(input_file, settings)

        if skip_mipmaps:
            result.warnings.append("No-mipmap path - mipmaps skipped")
        elif result.mipmap_count == 1 and max(result.width, result.height) > 4:
            result.warnings.append("Missing mipmaps - will regenerate")

        # === STEP 5: Estimate output size ===
        mipmap_factor = 1.0 if skip_mipmaps else 1.33
        num_pixels = new_width * new_height * mipmap_factor
        bpp_map = {
            "BC1/DXT1": 4,
            "BC2/DXT3": 8,
            "BC3/DXT5": 8,
            "BGRA": 32,
            "BGR": 24
        }
        bpp = bpp_map.get(result.target_format, 8)
        result.projected_size = int((num_pixels * bpp) / 8) + 128

    except Exception as e:
        result.error = str(e)

    return result


class RegularTextureProcessor:
    """Core processor for regular texture optimization"""

    def __init__(self, settings):
        self.settings = settings
        self.analysis_cache: Dict[str, AnalysisResult] = {}
        self._settings_hash = None

        # Initialize file scanner with path filtering
        whitelist = settings.path_whitelist if hasattr(settings, 'path_whitelist') else ["Textures"]
        blacklist = settings.path_blacklist if hasattr(settings, 'path_blacklist') else ["icon", "icons", "bookart"]

        # Add custom blacklist items
        if hasattr(settings, 'custom_blacklist') and settings.custom_blacklist:
            blacklist = list(blacklist) + list(settings.custom_blacklist)

        self.scanner = FileScanner(
            path_whitelist=whitelist,
            path_blacklist=blacklist
        )

    def find_textures(self, input_dir: Path, track_filtered: bool = False) -> List[Path]:
        """
        Find all regular texture files in directory.

        - Includes: .dds, .tga files
        - Excludes: Files ending in _n, _nh (normal maps) if exclude_normal_maps is True
        - Applies: Path whitelist (Textures) and blacklist (icon, icons, bookart)

        If track_filtered=True, also populates self.filter_stats with counts.
        """
        # Initialize filter stats if tracking
        if track_filtered:
            self.filter_stats = {
                'total_textures_found': 0,
                'included': 0,
                'excluded_normal_maps': 0,
                'excluded_whitelist': 0,
                'excluded_blacklist': 0,
                'blacklist_examples': [],
                'whitelist_examples': [],
                # Full lists for export
                'normal_map_files': [],
                'blacklist_files': [],
            }

        exclude_normal = getattr(self.settings, 'exclude_normal_maps', True)
        whitelist = self.scanner.path_whitelist
        blacklist = self.scanner.path_blacklist

        included_files = []

        # Find all DDS files in one pass
        all_dds = list(input_dir.rglob("*.dds"))

        # Find all TGA files if enabled
        all_tga = []
        if hasattr(self.settings, 'enable_tga_support') and self.settings.enable_tga_support:
            all_tga = list(input_dir.rglob("*.tga"))

        all_textures = all_dds + all_tga

        if track_filtered:
            self.filter_stats['total_textures_found'] = len(all_textures)

        # Filter in a single pass
        for f in all_textures:
            stem_lower = f.stem.lower()
            path_parts = [p.lower() for p in f.parts]

            # Check normal map exclusion
            if exclude_normal and (stem_lower.endswith('_n') or stem_lower.endswith('_nh')):
                if track_filtered:
                    self.filter_stats['excluded_normal_maps'] += 1
                    self.filter_stats['normal_map_files'].append(str(f.relative_to(input_dir)))
                continue

            # Check whitelist
            if whitelist:
                if not any(any(w in part for part in path_parts) for w in whitelist):
                    if track_filtered:
                        self.filter_stats['excluded_whitelist'] += 1
                        if len(self.filter_stats['whitelist_examples']) < 5:
                            self.filter_stats['whitelist_examples'].append(str(f.relative_to(input_dir)))
                    continue

            # Check blacklist
            excluded_by_blacklist = False
            if blacklist:
                for blocked in blacklist:
                    if any(blocked in part for part in path_parts):
                        if track_filtered:
                            self.filter_stats['excluded_blacklist'] += 1
                            self.filter_stats['blacklist_files'].append(str(f.relative_to(input_dir)))
                            if len(self.filter_stats['blacklist_examples']) < 5:
                                self.filter_stats['blacklist_examples'].append(str(f.relative_to(input_dir)))
                        excluded_by_blacklist = True
                        break
                if excluded_by_blacklist:
                    continue

            included_files.append(f)

        if track_filtered:
            self.filter_stats['included'] = len(included_files)

        return included_files

    def analyze_files(self, input_dir: Path,
                     progress_callback: Optional[Callable[[int, int], None]] = None) -> List[AnalysisResult]:
        """Analyze all textures and return analysis results."""
        all_files = self.find_textures(input_dir, track_filtered=True)

        if not all_files:
            return []

        settings_dict = self.settings.to_dict()

        # Store settings hash
        import json
        self._settings_hash = hash(json.dumps(settings_dict, sort_keys=True))

        # Use parallel processing when alpha optimization is enabled (I/O heavy)
        use_parallel = (
            getattr(self.settings, 'optimize_unused_alpha', False) and
            getattr(self.settings, 'enable_parallel', True) and
            len(all_files) > 10
        )
        max_workers = getattr(self.settings, 'max_workers', max(1, cpu_count() - 1))
        chunk_size = getattr(self.settings, 'analysis_chunk_size', 100)

        results = []

        if use_parallel:
            # Parallel analysis with chunked submission
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                completed = 0
                total_files = len(all_files)

                # Process in chunks to control memory usage
                for chunk_start in range(0, total_files, chunk_size):
                    chunk_end = min(chunk_start + chunk_size, total_files)
                    chunk = all_files[chunk_start:chunk_end]

                    # Submit chunk
                    futures = {}
                    for f in chunk:
                        args = (str(f), str(input_dir), settings_dict)
                        future = executor.submit(_analyze_file_worker, args)
                        futures[future] = f

                    # Collect results from this chunk
                    for future in as_completed(futures):
                        completed += 1
                        try:
                            result = future.result()
                            results.append(result)
                        except Exception as e:
                            # Create error result for failed analysis
                            file_path = futures[future]
                            error_result = AnalysisResult(
                                relative_path=str(file_path.relative_to(input_dir)),
                                file_size=file_path.stat().st_size if file_path.exists() else 0,
                                error=str(e)
                            )
                            results.append(error_result)

                        if progress_callback:
                            progress_callback(completed, total_files)
        else:
            # Sequential analysis (fast DDS parser makes this efficient for non-alpha cases)
            for i, f in enumerate(all_files, 1):
                result = _analyze_file_worker((str(f), str(input_dir), settings_dict))
                results.append(result)
                if progress_callback:
                    progress_callback(i, len(all_files))

        # Cache results
        self.analysis_cache.clear()
        for result in results:
            self.analysis_cache[result.relative_path] = result

        return results

    def process_files(self, input_dir: Path, output_dir: Path,
                     progress_callback: Optional[Callable[[int, int, ProcessingResult], None]] = None) -> List[ProcessingResult]:
        """Process all textures and return results."""
        import json
        settings_dict = self.settings.to_dict()
        current_hash = hash(json.dumps(settings_dict, sort_keys=True))

        if not self.analysis_cache or self._settings_hash != current_hash:
            raise RuntimeError(
                "Analysis must be run before processing. Please run analyze_files() first."
            )

        all_files = self.find_textures(input_dir)

        if not all_files:
            return []

        results = []
        total = len(all_files)

        # Check if parallel processing is enabled
        use_parallel = getattr(self.settings, 'enable_parallel', True) and total > 1
        max_workers = getattr(self.settings, 'max_workers', max(1, cpu_count() - 1))

        if use_parallel:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for f in all_files:
                    rel_path = str(f.relative_to(input_dir))
                    cached = self._get_cached_analysis(rel_path)
                    args = (str(f), str(input_dir), str(output_dir), settings_dict, cached)
                    future = executor.submit(_process_file_worker, args)
                    futures[future] = f

                current = 0
                for future in as_completed(futures):
                    current += 1
                    try:
                        result = future.result()
                        results.append(result)
                        if progress_callback:
                            progress_callback(current, total, result)
                    except Exception as e:
                        file_path = futures[future]
                        error_result = ProcessingResult(
                            success=False,
                            relative_path=str(file_path.name),
                            input_size=0,
                            error_msg=str(e)
                        )
                        results.append(error_result)
        else:
            for i, f in enumerate(all_files, 1):
                rel_path = str(f.relative_to(input_dir))
                cached = self._get_cached_analysis(rel_path)
                args = (str(f), str(input_dir), str(output_dir), settings_dict, cached)
                result = _process_file_worker(args)
                results.append(result)
                if progress_callback:
                    progress_callback(i, total, result)

        return results

    def _get_cached_analysis(self, relative_path: str) -> Optional[dict]:
        """Get cached analysis data for a file"""
        if relative_path in self.analysis_cache:
            result = self.analysis_cache[relative_path]
            return {
                'width': result.width,
                'height': result.height,
                'format': result.format,
                'target_format': result.target_format,
                'mipmap_count': result.mipmap_count
            }
        return None
