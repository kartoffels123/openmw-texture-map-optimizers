"""
Core logic for OpenMW Normal Map Optimizer.
Handles file processing, analysis, and conversion independently of UI.
"""

from pathlib import Path
import subprocess
import re
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable
import sys


# Get the directory where the tools are located
# When frozen (PyInstaller), use the exe directory
# When running as script, tools are in ../../tools relative to this file
if hasattr(sys, 'frozen'):
    SCRIPT_DIR = Path(sys.executable).parent
else:
    SCRIPT_DIR = Path(__file__).parent.parent.parent  # Go up to project root

TEXDIAG_EXE = str(SCRIPT_DIR / "tools" / "texdiag.exe")
TEXCONV_EXE = str(SCRIPT_DIR / "tools" / "texconv.exe")


@dataclass
class ProcessingSettings:
    """Configuration for texture processing"""
    n_format: str = "BC5/ATI2"
    nh_format: str = "BC3/DXT5"
    scale_factor: float = 1.0
    max_resolution: int = 2048
    min_resolution: int = 256
    invert_y: bool = False
    reconstruct_z: bool = True
    uniform_weighting: bool = True
    use_dithering: bool = False
    use_small_texture_override: bool = True
    small_nh_threshold: int = 256
    small_n_threshold: int = 128
    resize_method: str = "CUBIC"
    enable_parallel: bool = True
    max_workers: int = max(1, cpu_count() - 1)
    chunk_size_mb: int = 75
    preserve_compressed_format: bool = True
    auto_fix_nh_to_n: bool = True
    auto_optimize_n_alpha: bool = True
    allow_compressed_passthrough: bool = False
    enable_atlas_downscaling: bool = False
    atlas_max_resolution: int = 4096

    def to_dict(self) -> dict:
        """Convert settings to dictionary for multiprocessing"""
        return {
            'n_format': self.n_format,
            'nh_format': self.nh_format,
            'scale_factor': self.scale_factor,
            'max_resolution': self.max_resolution,
            'min_resolution': self.min_resolution,
            'invert_y': self.invert_y,
            'reconstruct_z': self.reconstruct_z,
            'uniform_weighting': self.uniform_weighting,
            'use_dithering': self.use_dithering,
            'use_small_texture_override': self.use_small_texture_override,
            'small_nh_threshold': self.small_nh_threshold,
            'small_n_threshold': self.small_n_threshold,
            'resize_method': self.resize_method,
            'preserve_compressed_format': self.preserve_compressed_format,
            'auto_fix_nh_to_n': self.auto_fix_nh_to_n,
            'auto_optimize_n_alpha': self.auto_optimize_n_alpha,
            'allow_compressed_passthrough': self.allow_compressed_passthrough,
            'enable_atlas_downscaling': self.enable_atlas_downscaling,
            'atlas_max_resolution': self.atlas_max_resolution
        }


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
    is_nh: bool
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = 'UNKNOWN'
    new_width: Optional[int] = None
    new_height: Optional[int] = None
    target_format: Optional[str] = None
    projected_size: int = 0
    error: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# Constants
FORMAT_MAP = {
    "BC5/ATI2": "BC5_UNORM",
    "BC1/DXT1": "BC1_UNORM",
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


# Import fast DDS header parser for dry runs
try:
    from .dds_parser import parse_dds_header as _parse_dds_header_fast
    _HAS_FAST_PARSER = True
except ImportError:
    _HAS_FAST_PARSER = False


# Counters for parser statistics (not thread-safe, but good enough for rough stats)
_fast_parser_hits = 0
_texdiag_fallbacks = 0


# Static helper functions for multiprocessing workers
def _get_dds_info_static(input_dds: Path, use_fast_parser: bool = True) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Get dimensions and format from DDS file in a single call. Returns ((width, height), format)

    Args:
        input_dds: Path to DDS file
        use_fast_parser: If True, use fast header parser when available (~100x faster for analysis).
                        If False, always use texdiag (slightly more reliable for edge cases).
    """
    global _fast_parser_hits, _texdiag_fallbacks

    # Try fast parser first if available and requested
    if use_fast_parser and _HAS_FAST_PARSER:
        try:
            dims, fmt = _parse_dds_header_fast(input_dds)
            if dims is not None and fmt != "UNKNOWN":
                _fast_parser_hits += 1
                return dims, fmt
            # Fall through to texdiag if parser fails
        except Exception:
            pass  # Fall through to texdiag

    # Fallback to texdiag subprocess
    _texdiag_fallbacks += 1
    try:
        result = subprocess.run(
            [TEXDIAG_EXE, "info", str(input_dds)],
            capture_output=True, text=True, timeout=30
        )

        width_match = re.search(r'width\s*=\s*(\d+)', result.stdout)
        height_match = re.search(r'height\s*=\s*(\d+)', result.stdout)
        format_match = re.search(r'format\s*=\s*(\S+)', result.stdout)

        dimensions = None
        if width_match and height_match:
            dimensions = (int(width_match.group(1)), int(height_match.group(1)))

        format_str = format_match.group(1) if format_match else "UNKNOWN"

        return dimensions, format_str
    except Exception:
        pass

    return None, "UNKNOWN"


def get_parser_stats() -> Tuple[int, int]:
    """Return (fast_parser_hits, texdiag_fallbacks) for debugging"""
    global _fast_parser_hits, _texdiag_fallbacks
    return _fast_parser_hits, _texdiag_fallbacks


def reset_parser_stats():
    """Reset parser statistics"""
    global _fast_parser_hits, _texdiag_fallbacks
    _fast_parser_hits = 0
    _texdiag_fallbacks = 0


def _get_dimensions_static(input_dds: Path) -> Optional[Tuple[int, int]]:
    """Get dimensions from DDS file. Returns (width, height) or None"""
    dimensions, _ = _get_dds_info_static(input_dds)
    return dimensions


def _get_format_static(input_dds: Path) -> str:
    """Get format from DDS file. Returns format string or 'UNKNOWN'"""
    _, format_str = _get_dds_info_static(input_dds)
    return format_str


def _is_texture_atlas(file_path: Path) -> bool:
    """Detect if a file is likely a texture atlas (should not be resized)"""
    path_str = str(file_path).lower()

    # Check for "atlas" in filename
    if 'atlas' in file_path.stem.lower():
        return True

    # Check for "ATL" or "atl" directory in path
    path_parts = [p.lower() for p in file_path.parts]
    if 'atl' in path_parts:
        return True

    return False


def _calculate_new_dimensions_static(orig_width: int, orig_height: int, settings: dict, file_path: Path = None, is_atlas: bool = False) -> Tuple[int, int]:
    """Calculate new dimensions based on scale factor and constraints

    Args:
        orig_width: Original width
        orig_height: Original height
        settings: Processing settings dict
        file_path: Optional path (for backward compatibility, prefer is_atlas)
        is_atlas: Whether this is a texture atlas (if True, overrides file_path check)
    """
    new_width, new_height = orig_width, orig_height

    # Determine if this is an atlas (prefer explicit flag, fallback to detection)
    if not is_atlas and file_path:
        is_atlas = _is_texture_atlas(file_path)

    # Skip resizing for texture atlases (unless explicitly enabled)
    if is_atlas and not settings.get('enable_atlas_downscaling', False):
        return new_width, new_height

    scale = settings['scale_factor']
    if scale != 1.0:
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)

    # Use atlas-specific max resolution if this is an atlas
    max_res = settings.get('atlas_max_resolution', 4096) if is_atlas else settings['max_resolution']
    if max_res > 0:
        max_dim = max(new_width, new_height)
        if max_dim > max_res:
            scale_factor = max_res / max_dim
            new_width = int(new_width * scale_factor)
            new_height = int(new_height * scale_factor)

    min_res = settings['min_resolution']
    if min_res > 0 and scale < 1.0:
        min_dim = min(new_width, new_height)
        if min_dim < min_res:
            scale_factor = min_res / min_dim
            new_width = int(new_width * scale_factor)
            new_height = int(new_height * scale_factor)

    return new_width, new_height


def _process_normal_map_static(input_dds: Path, output_dds: Path, is_nh: bool, settings: dict) -> bool:
    """Process a single normal map file using texconv. Static version for multiprocessing."""
    try:
        output_dds.parent.mkdir(parents=True, exist_ok=True)

        # Get both dimensions and format in a single subprocess call
        dimensions, format_name = _get_dds_info_static(input_dds)
        if not dimensions:
            return False

        orig_width, orig_height = dimensions
        new_width, new_height = _calculate_new_dimensions_static(orig_width, orig_height, settings, input_dds)

        # Check for compressed passthrough (fast path - just copy the file)
        # Only applies if texture is compressed AND correctly formatted AND won't be resized
        if settings.get('allow_compressed_passthrough', False):
            # Check if resize is needed
            will_resize = (new_width != orig_width) or (new_height != orig_height)

            # Passthrough only if no resize needed
            if not will_resize:
                format_to_standard = {
                    'BC5_UNORM': 'BC5/ATI2',
                    'BC3_UNORM': 'BC3/DXT5',
                    'BC1_UNORM': 'BC1/DXT1'
                }
                current_format_standard = format_to_standard.get(format_name, None)

                if current_format_standard in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']:
                    # Check if this compressed texture is "good" for its type
                    can_passthrough = False
                    needs_rename = False

                    # Check for mislabeling (NH textures without alpha)
                    if is_nh and settings.get('auto_fix_nh_to_n', True):
                        # NH texture in BC5/BC1 is mislabeled
                        if current_format_standard in ['BC5/ATI2', 'BC1/DXT1']:
                            can_passthrough = True  # Can copy as-is
                            needs_rename = True  # But rename _NH → _N
                        elif current_format_standard == 'BC3/DXT5':
                            can_passthrough = True  # BC3 is correct for NH
                            needs_rename = False
                    else:
                        # N texture - check for wasted alpha
                        if settings.get('auto_optimize_n_alpha', True):
                            if current_format_standard == 'BC3/DXT5':
                                can_passthrough = False  # BC3 N has wasted alpha - must optimize to BC1
                            else:
                                can_passthrough = True  # BC5 or BC1 are good for N
                        else:
                            can_passthrough = True  # Auto-optimize disabled, accept as-is

                    if can_passthrough:
                        # Handle renaming for mislabeled NH→N textures
                        if needs_rename:
                            # Change _nh.dds → _n.dds in the output path
                            output_path_str = str(output_dds)
                            if output_path_str.lower().endswith('_nh.dds'):
                                corrected_output = Path(output_path_str[:-7] + '_n.dds')
                                corrected_output.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(input_dds, corrected_output)
                                return True
                        else:
                            # Copy with same name
                            shutil.copy2(input_dds, output_dds)
                            return True

        # Check if we're resizing
        will_resize = (new_width != orig_width) or (new_height != orig_height)

        # Map format to standard names
        format_to_standard = {
            'BC5_UNORM': 'BC5/ATI2',
            'BC3_UNORM': 'BC3/DXT5',
            'BC1_UNORM': 'BC1/DXT1',
            'B8G8R8A8_UNORM': 'BGRA',
            'B8G8R8X8_UNORM': 'BGR'
        }
        current_format_standard = format_to_standard.get(format_name, format_name)

        # Determine target format with smart format handling
        target_format = settings['nh_format'] if is_nh else settings['n_format']

        # Auto-fix: NH-labeled textures with no-alpha formats should be treated as N
        if is_nh and settings['auto_fix_nh_to_n']:
            if current_format_standard in ['BGR', 'BC5/ATI2', 'BC1/DXT1']:
                # This is really an N texture, use N format
                target_format = settings['n_format']
                is_nh = False  # Update for later logic

        # Preserve compressed format when not resizing (but not if it needs optimization)
        should_preserve = False
        if settings['preserve_compressed_format'] and not will_resize:
            compressed_formats = ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']
            if current_format_standard in compressed_formats:
                # Check if this format is appropriate for the texture type
                if is_nh:
                    # NH textures: BC3 is good, BC5/BC1 have no alpha
                    if current_format_standard == 'BC3/DXT5':
                        should_preserve = True
                else:
                    # N textures: BC5 and BC1 are good, BC3 has wasted alpha
                    if current_format_standard in ['BC5/ATI2', 'BC1/DXT1']:
                        should_preserve = True

                if should_preserve:
                    target_format = current_format_standard

        # Auto-optimize: N textures with alpha formats can be optimized (only if not preserved)
        if not is_nh and settings['auto_optimize_n_alpha'] and not should_preserve:
            if current_format_standard == 'BGRA':
                # BGRA N texture should use the user's N format setting (BC5, BC1, or BGR)
                # Don't hardcode to BGR - let user settings determine the best compressed format
                target_format = settings['n_format']
            elif current_format_standard == 'BC3/DXT5':
                # BC3 N texture can become BC1 (half the size, same compression)
                # BC5 would be recompression with no benefit, BC1 is the clear choice
                target_format = 'BC1/DXT1'

        # Small texture override (only applies to uncompressed sources, not already-compressed)
        # Don't want to decompress small BC1/BC3/BC5 textures - wastes disk space
        # Should NOT apply to compressed→compressed conversions (BC3→BC1)
        if settings['use_small_texture_override']:
            is_already_compressed = current_format_standard in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']

            # Only override if source is truly uncompressed (BGRA/BGR)
            if not is_already_compressed:
                min_dim = min(new_width, new_height)
                if is_nh:
                    threshold = settings['small_nh_threshold']
                    if threshold > 0 and min_dim <= threshold:
                        target_format = "BGRA"
                else:
                    threshold = settings['small_n_threshold']
                    if threshold > 0 and min_dim <= threshold:
                        target_format = "BGR"

        texconv_format = FORMAT_MAP[target_format]

        # Build texconv command
        cmd = [
            TEXCONV_EXE,
            "-f", texconv_format,
            "-m", "0",
            "-alpha",
            "-dx9"
        ]

        if settings['invert_y']:
            cmd.append("-inverty")

        if target_format != "BC5/ATI2" and settings['reconstruct_z']:
            cmd.append("-reconstructz")

        if target_format in ["BC1/DXT1", "BC3/DXT5"]:
            bc_options = ""
            if settings['uniform_weighting']:
                bc_options += "u"
            if settings['use_dithering']:
                bc_options += "d"
            if bc_options:
                cmd.extend(["-bc", bc_options])

        if new_width != orig_width or new_height != orig_height:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])

            resize_method = settings['resize_method'].split()[0]
            if resize_method in FILTER_MAP:
                cmd.extend(["-if", FILTER_MAP[resize_method]])

        cmd.extend(["-o", str(output_dds.parent), "-y", str(input_dds)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            return False

        # Rename output file if needed
        generated_dds = output_dds.parent / input_dds.name
        if generated_dds != output_dds:
            if output_dds.exists():
                output_dds.unlink()
            generated_dds.rename(output_dds)

        return True

    except Exception:
        return False


def _process_file_worker(args):
    """Worker function for parallel processing. Must be at module level for pickling."""
    dds_file_path, source_dir_path, output_dir_path, is_nh, settings, cached_analysis = args

    dds_file = Path(dds_file_path)
    source_dir = Path(source_dir_path)
    output_dir = Path(output_dir_path)

    relative_path = dds_file.relative_to(source_dir)
    output_file = output_dir / relative_path

    result = ProcessingResult(
        success=False,
        relative_path=str(relative_path),
        input_size=dds_file.stat().st_size
    )

    try:
        # Use cached analysis data if available
        if cached_analysis:
            orig_dims = (cached_analysis['width'], cached_analysis['height'])
            orig_format = cached_analysis['format']
            result.orig_dims = orig_dims
            result.orig_format = orig_format
        else:
            # Fallback: Get both dimensions and format in a single subprocess call
            orig_dims, orig_format = _get_dds_info_static(dds_file)
            result.orig_dims = orig_dims
            result.orig_format = orig_format

        if not result.orig_dims:
            result.error_msg = "Could not determine dimensions"
            return result

        success = _process_normal_map_static(dds_file, output_file, is_nh, settings)

        if success and output_file.exists():
            result.success = True
            result.output_size = output_file.stat().st_size
            result.new_dims = _get_dimensions_static(output_file)
            result.new_format = _get_format_static(output_file)
        else:
            result.error_msg = "Processing failed or output missing"

    except Exception as e:
        result.error_msg = str(e)

    return result


def _analyze_file_worker(args):
    """Worker function for parallel analysis. Must be at module level for pickling."""
    dds_file_path, source_dir_path, settings = args

    dds_file = Path(dds_file_path)
    source_dir = Path(source_dir_path)
    relative_path = dds_file.relative_to(source_dir)
    file_size = dds_file.stat().st_size
    is_nh = dds_file.stem.lower().endswith('_nh')

    result = AnalysisResult(
        relative_path=str(relative_path),
        file_size=file_size,
        is_nh=is_nh
    )

    try:
        # Get both dimensions and format in a single subprocess call
        dimensions, format_name = _get_dds_info_static(dds_file)

        if not dimensions:
            result.error = "Could not determine dimensions"
            return result

        width, height = dimensions
        result.width = width
        result.height = height

        # Map common format names to our format identifiers
        format_to_standard = {
            'BC5_UNORM': 'BC5/ATI2',
            'BC3_UNORM': 'BC3/DXT5',
            'BC1_UNORM': 'BC1/DXT1',
            'B8G8R8A8_UNORM': 'BGRA',
            'B8G8R8X8_UNORM': 'BGR'
        }
        current_format_standard = format_to_standard.get(format_name, format_name)

        # Store normalized format name for consistent comparisons
        result.format = current_format_standard

        # Check if this is an atlas (do this once to avoid duplicate checks)
        is_atlas = _is_texture_atlas(dds_file)

        new_width, new_height = _calculate_new_dimensions_static(width, height, settings, is_atlas=is_atlas)
        result.new_width = new_width
        result.new_height = new_height

        # Check if we're resizing
        will_resize = (new_width != width) or (new_height != height)

        # Determine target format with smart format handling
        # Decision Priority Order:
        # 1. Format Options (_N and _NH)
        # 2. Mislabeled NH→N textures (changes is_nh flag)
        # 3. Preserve compressed formats when not downscaling (sets should_preserve flag)
        # 4. Auto-optimize formats with wasted alpha (only if not preserved)
        # 5. Small texture override (only for uncompressed sources - prevents decompressing small BC1/BC3/BC5)

        target_format = settings['nh_format'] if is_nh else settings['n_format']

        # Auto-fix: NH-labeled textures with no-alpha formats should be treated as N
        if is_nh and settings['auto_fix_nh_to_n']:
            if current_format_standard in ['BGR', 'BC5/ATI2', 'BC1/DXT1']:
                # This is really an N texture, use N format
                target_format = settings['n_format']
                is_nh = False  # Update for later logic

        # Preserve compressed format when not resizing (but not if it needs optimization)
        should_preserve = False
        if settings['preserve_compressed_format'] and not will_resize:
            compressed_formats = ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']
            if current_format_standard in compressed_formats:
                # Check if this format is appropriate for the texture type
                if is_nh:
                    # NH textures: BC3 is good, BC5/BC1 have no alpha
                    if current_format_standard == 'BC3/DXT5':
                        should_preserve = True
                else:
                    # N textures: BC5 and BC1 are good, BC3 has wasted alpha
                    if current_format_standard in ['BC5/ATI2', 'BC1/DXT1']:
                        should_preserve = True

                if should_preserve:
                    target_format = current_format_standard

        # Auto-optimize: N textures with alpha formats can be optimized (only if not preserved)
        if not is_nh and settings['auto_optimize_n_alpha'] and not should_preserve:
            if current_format_standard == 'BGRA':
                # BGRA N texture should use the user's N format setting (BC5, BC1, or BGR)
                # Don't hardcode to BGR - let user settings determine the best compressed format
                target_format = settings['n_format']
            elif current_format_standard == 'BC3/DXT5':
                # BC3 N texture can become BC1 (half the size, same compression)
                # BC5 would be recompression with no benefit, BC1 is the clear choice
                target_format = 'BC1/DXT1'

        # Small texture override (only applies to uncompressed sources, not already-compressed)
        # Don't want to decompress small BC1/BC3/BC5 textures - wastes disk space
        # Should NOT apply to compressed→compressed conversions (BC3→BC1)
        if settings['use_small_texture_override']:
            is_already_compressed = current_format_standard in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']

            # Only override if source is truly uncompressed (BGRA/BGR)
            if not is_already_compressed:
                min_dim_output = min(new_width, new_height)
                if is_nh:
                    threshold = settings['small_nh_threshold']
                    if threshold > 0 and min_dim_output <= threshold:
                        target_format = "BGRA"
                else:
                    threshold = settings['small_n_threshold']
                    if threshold > 0 and min_dim_output <= threshold:
                        target_format = "BGR"

        result.target_format = target_format

        # Detect warnings and informational messages
        warnings = []

        # Store the original is_nh value for warning detection
        original_is_nh = dds_file.stem.lower().endswith('_nh')

        # Info: Compressed passthrough (file will just be copied)
        # Only if texture is compressed AND correctly formatted (or fixable via rename)
        if settings.get('allow_compressed_passthrough', False):
            if current_format_standard in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']:
                can_passthrough = False
                needs_rename = False

                # Check for mislabeling (NH textures without alpha)
                if original_is_nh and settings.get('auto_fix_nh_to_n', True):
                    # NH texture in BC5/BC1 is mislabeled
                    if current_format_standard in ['BC5/ATI2', 'BC1/DXT1']:
                        can_passthrough = True  # Can copy as-is
                        needs_rename = True  # But rename _NH → _N
                    elif current_format_standard == 'BC3/DXT5':
                        can_passthrough = True  # BC3 is correct for NH
                        needs_rename = False
                else:
                    # N texture - check for wasted alpha
                    if not original_is_nh and settings.get('auto_optimize_n_alpha', True):
                        if current_format_standard == 'BC3/DXT5':
                            can_passthrough = False  # BC3 N has wasted alpha - must optimize to BC1
                        else:
                            can_passthrough = True  # BC5 or BC1 are good for N
                    else:
                        can_passthrough = True  # Auto-optimize disabled, accept as-is

                if can_passthrough:
                    if needs_rename:
                        warnings.append(f"Compressed passthrough with rename - copying _NH→_N (mislabeled, no reprocessing needed)")
                    else:
                        warnings.append(f"Compressed passthrough - file will be copied as-is (no Z-reconstruction or mipmap regen)")

        # Info: Auto-fixed mislabeled NH texture
        if original_is_nh and not is_nh and settings['auto_fix_nh_to_n']:
            warnings.append(f"NH-labeled texture stored as {current_format_standard} (no alpha) - auto-fixed to N texture")

        # Info: Auto-optimized N texture with wasted alpha
        if not original_is_nh and settings['auto_optimize_n_alpha'] and not should_preserve:
            if current_format_standard == 'BGRA' and target_format != 'BGRA':
                warnings.append(f"N texture with unused alpha in BGRA - auto-optimized to {target_format}")
            elif current_format_standard == 'BC3/DXT5' and target_format == 'BC1/DXT1':
                warnings.append(f"N texture with unused alpha in BC3 - auto-optimized to BC1")

        # Info: Preserved compressed format message is REMOVED
        # This was misleading - "preserve format" means keep the same format during reprocessing,
        # NOT that the file is being copied without processing.
        # Passthrough info messages (above) already cover the actual copy-without-processing case.

        # Info: Texture atlas detected (will not be resized)
        if is_atlas and width > 0 and height > 0:
            max_dim = max(width, height)
            if max_dim > settings['max_resolution'] and settings['max_resolution'] > 0:
                warnings.append(f"Texture atlas detected - resize skipped despite size {width}x{height} exceeding max resolution")

        # Warning: N texture saved to format with unused alpha channel (after auto-fix logic)
        if not is_nh and not settings['auto_optimize_n_alpha']:
            if target_format in ["BGRA", "BC3/DXT5"]:
                warnings.append(f"N texture will be saved as {target_format} - alpha channel will not be used (auto-optimize disabled)")

        # Warning: NH texture saved to format without alpha channel (that wasn't auto-fixed)
        if original_is_nh and is_nh:  # Still NH after auto-fix logic
            if target_format in ["BGR", "BC5/ATI2", "BC1/DXT1"]:
                warnings.append(f"NH texture will be saved as {target_format} - alpha channel not available")

        # Warning: Converting from compressed to larger/uncompressed format without resize benefit
        if not settings['preserve_compressed_format']:
            compressed_source_formats = ["BC3_UNORM", "BC1_UNORM", "BC5_UNORM"]
            if format_name in compressed_source_formats:
                # Check if converting to larger format
                size_increase_targets = []
                if format_name == "BC1_UNORM":
                    # BC1 is 4bpp, so BC3/BC5 (8bpp) and BGR/BGRA (24/32bpp) are larger
                    if target_format in ["BC3/DXT5", "BC5/ATI2", "BGR", "BGRA"]:
                        size_increase_targets.append(target_format)
                elif format_name in ["BC3_UNORM", "BC5_UNORM"]:
                    # BC3/BC5 are 8bpp, so BGR/BGRA (24/32bpp) are larger
                    if target_format in ["BGR", "BGRA"]:
                        size_increase_targets.append(target_format)

                if size_increase_targets and not will_resize:
                    for target in size_increase_targets:
                        warnings.append(f"Converting {format_name} to {target} will increase file size without quality gain (preserve format disabled)")

        result.warnings = warnings

        # Estimate output size
        num_pixels = new_width * new_height * 1.33
        bpp_map = {
            "BC5/ATI2": 8,
            "BC3/DXT5": 8,
            "BC1/DXT1": 4,
            "BGRA": 32,
            "BGR": 24
        }
        bpp = bpp_map.get(target_format, 32)
        total_bytes = int((num_pixels * bpp) / 8)
        result.projected_size = total_bytes + 128

    except Exception as e:
        result.error = str(e)

    return result


def _create_file_chunks(files_with_sizes: List[Tuple[str, int]], chunk_size_bytes: int) -> List[List[str]]:
    """Create chunks of files based on total size."""
    chunks = []
    current_chunk = []
    current_size = 0

    for file_path, file_size in files_with_sizes:
        if current_size + file_size > chunk_size_bytes and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(file_path)
        current_size += file_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class NormalMapProcessor:
    """Core processor for normal map optimization"""

    def __init__(self, settings: ProcessingSettings):
        self.settings = settings
        self.analysis_cache: Dict[str, AnalysisResult] = {}  # Cache analysis results by relative path
        self._settings_hash = None  # Track settings to invalidate cache

    def find_normal_maps(self, input_dir: Path) -> Tuple[List[Path], List[Path]]:
        """
        Find all normal map files in directory. Returns (n_files, nh_files)

        Optimized to search for specific patterns instead of scanning all DDS files.
        This is much faster when there are many non-normal-map DDS files in the directory.
        For example: 150,000 total DDS files with only 15,000 normal maps is 10x faster.
        """
        # Search for all files ending in _n.dds or _nh.dds (case-insensitive)
        # Note: On case-sensitive filesystems, glob is case-sensitive, so we need multiple patterns
        # On Windows (case-insensitive), lowercase pattern will match all cases
        import platform
        is_case_sensitive = platform.system() != 'Windows'

        if is_case_sensitive:
            # Case-sensitive filesystem: need to search for all case variations
            nh_candidates = list(input_dir.rglob("*_nh.dds")) + list(input_dir.rglob("*_NH.dds")) + \
                           list(input_dir.rglob("*_Nh.dds")) + list(input_dir.rglob("*_nH.dds"))
            n_candidates = list(input_dir.rglob("*_n.dds")) + list(input_dir.rglob("*_N.dds"))
        else:
            # Case-insensitive filesystem (Windows): single pattern matches all cases
            nh_candidates = list(input_dir.rglob("*_nh.dds"))
            n_candidates = list(input_dir.rglob("*_n.dds"))

        # Deduplicate and filter
        nh_files = list(set(nh_candidates))
        n_files = [f for f in set(n_candidates) if not f.stem.lower().endswith('_nh')]

        return n_files, nh_files

    def analyze_files(self, input_dir: Path, progress_callback: Optional[Callable[[int, int], None]] = None) -> List[AnalysisResult]:
        """Analyze all normal maps and return analysis results. Results are cached for processing."""
        n_files, nh_files = self.find_normal_maps(input_dir)
        all_files = n_files + nh_files

        if not all_files:
            return []

        settings_dict = self.settings.to_dict()

        # Store settings hash to detect changes
        import json
        self._settings_hash = hash(json.dumps(settings_dict, sort_keys=True))

        # For analysis (dry runs), use sequential if fast parser is available
        # Fast parser is ~0.08ms per file, so parallel overhead isn't worth it
        # Sequential: 6000 files * 0.08ms = 480ms
        # Parallel with Windows spawn overhead: 6000 task submissions = 60+ seconds
        use_parallel = self.settings.enable_parallel and len(all_files) > 1
        if use_parallel and _HAS_FAST_PARSER:
            # Fast parser makes sequential faster than parallel on Windows
            use_parallel = False

        if use_parallel:
            results = self._analyze_files_parallel(all_files, input_dir, settings_dict, progress_callback)
        else:
            results = self._analyze_files_sequential(all_files, input_dir, settings_dict, progress_callback)

        # Cache results by relative path
        self.analysis_cache.clear()
        for result in results:
            self.analysis_cache[result.relative_path] = result

        return results

    def process_files(self, input_dir: Path, output_dir: Path,
                     progress_callback: Optional[Callable[[int, int, ProcessingResult], None]] = None) -> List[ProcessingResult]:
        """Process all normal maps and return results. Requires analysis to be run first."""
        # Check if analysis has been run
        import json
        settings_dict = self.settings.to_dict()
        current_hash = hash(json.dumps(settings_dict, sort_keys=True))

        if not self.analysis_cache or self._settings_hash != current_hash:
            raise RuntimeError(
                "Analysis must be run before processing. Please run analyze_files() first, "
                "or re-run it if settings have changed."
            )

        n_files, nh_files = self.find_normal_maps(input_dir)
        total_files = len(n_files) + len(nh_files)

        if total_files == 0:
            return []

        if self.settings.enable_parallel and total_files > 1:
            results = self._process_files_parallel(n_files, nh_files, input_dir, output_dir,
                                                   settings_dict, progress_callback)
        else:
            results = self._process_files_sequential(n_files, nh_files, input_dir, output_dir,
                                                     settings_dict, progress_callback)

        return results

    def _analyze_files_parallel(self, all_files: List[Path], source_dir: Path,
                                settings: dict, progress_callback: Optional[Callable] = None) -> List[AnalysisResult]:
        """Analyze files in parallel"""
        results = []
        with ProcessPoolExecutor(max_workers=self.settings.max_workers) as executor:
            future_to_file = {}
            for f in all_files:
                future = executor.submit(_analyze_file_worker, (str(f), str(source_dir), settings))
                future_to_file[future] = f

            current = 0
            for future in as_completed(future_to_file):
                current += 1
                try:
                    result = future.result()
                    results.append(result)
                    if progress_callback:
                        progress_callback(current, len(all_files))
                except Exception as e:
                    file_path = future_to_file[future]
                    results.append(AnalysisResult(
                        relative_path=str(file_path.relative_to(source_dir)),
                        file_size=0,
                        is_nh=file_path.stem.lower().endswith('_nh'),
                        error=str(e)
                    ))

        return results

    def _analyze_files_sequential(self, all_files: List[Path], source_dir: Path,
                                  settings: dict, progress_callback: Optional[Callable] = None) -> List[AnalysisResult]:
        """Analyze files sequentially"""
        results = []
        for i, f in enumerate(all_files, 1):
            result = _analyze_file_worker((str(f), str(source_dir), settings))
            results.append(result)
            if progress_callback:
                progress_callback(i, len(all_files))
        return results

    def _process_files_parallel(self, n_files: List[Path], nh_files: List[Path],
                                source_dir: Path, output_dir: Path, settings: dict,
                                progress_callback: Optional[Callable] = None) -> List[ProcessingResult]:
        """Process files in parallel"""
        all_tasks = []
        for f in n_files:
            rel_path = str(f.relative_to(source_dir))
            cached = self._get_cached_analysis(rel_path)
            all_tasks.append((str(f), str(source_dir), str(output_dir), False, settings, cached))
        for f in nh_files:
            rel_path = str(f.relative_to(source_dir))
            cached = self._get_cached_analysis(rel_path)
            all_tasks.append((str(f), str(source_dir), str(output_dir), True, settings, cached))

        results = []
        current = 0
        total = len(all_tasks)

        with ProcessPoolExecutor(max_workers=self.settings.max_workers) as executor:
            future_to_file = {}
            for task in all_tasks:
                future = executor.submit(_process_file_worker, task)
                future_to_file[future] = task[0]

            for future in as_completed(future_to_file):
                current += 1
                try:
                    result = future.result()
                    results.append(result)
                    if progress_callback:
                        progress_callback(current, total, result)
                except Exception as e:
                    file_path = future_to_file[future]
                    error_result = ProcessingResult(
                        success=False,
                        relative_path=str(Path(file_path).name),
                        input_size=0,
                        error_msg=str(e)
                    )
                    results.append(error_result)

        return results

    def _process_files_sequential(self, n_files: List[Path], nh_files: List[Path],
                                  source_dir: Path, output_dir: Path, settings: dict,
                                  progress_callback: Optional[Callable] = None) -> List[ProcessingResult]:
        """Process files sequentially"""
        results = []
        current = 0
        total = len(n_files) + len(nh_files)

        for f in n_files:
            current += 1
            rel_path = str(f.relative_to(source_dir))
            cached = self._get_cached_analysis(rel_path)
            args = (str(f), str(source_dir), str(output_dir), False, settings, cached)
            result = _process_file_worker(args)
            results.append(result)
            if progress_callback:
                progress_callback(current, total, result)

        for f in nh_files:
            current += 1
            rel_path = str(f.relative_to(source_dir))
            cached = self._get_cached_analysis(rel_path)
            args = (str(f), str(source_dir), str(output_dir), True, settings, cached)
            result = _process_file_worker(args)
            results.append(result)
            if progress_callback:
                progress_callback(current, total, result)

        return results

    def _get_cached_analysis(self, relative_path: str) -> Optional[dict]:
        """Get cached analysis data for a file"""
        if relative_path in self.analysis_cache:
            result = self.analysis_cache[relative_path]
            return {
                'width': result.width,
                'height': result.height,
                'format': result.format,
                'target_format': result.target_format
            }
        return None


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
