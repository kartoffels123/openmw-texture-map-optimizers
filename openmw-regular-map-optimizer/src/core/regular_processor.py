"""
Core logic for OpenMW Regular Texture Optimizer.
Handles file processing, analysis, and conversion for regular (non-normal map) textures.

This module uses the shared core from openmw-texture-optimizer-core.
"""

from pathlib import Path
import subprocess
import shutil
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from typing import Optional, Tuple, List, Dict, Callable
import sys
import importlib.util

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

# Import shared core modules
_dds_parser = _import_shared_module("dds_parser")
_file_scanner = _import_shared_module("file_scanner")
_base_settings = _import_shared_module("base_settings")
_utils = _import_shared_module("utils")

# Re-export DDS parser functions
parse_dds_header = _dds_parser.parse_dds_header
parse_dds_header_extended = _dds_parser.parse_dds_header_extended
has_adequate_mipmaps = _dds_parser.has_adequate_mipmaps
parse_tga_header = _dds_parser.parse_tga_header
parse_tga_header_extended = _dds_parser.parse_tga_header_extended
has_meaningful_alpha = _dds_parser.has_meaningful_alpha
analyze_bc1_alpha = _dds_parser.analyze_bc1_alpha
strip_dx10_headers_batch = _dds_parser.strip_dx10_headers_batch
convert_bgrx32_to_bgr24 = _dds_parser.convert_bgrx32_to_bgr24

# Re-export file scanner
FileScanner = _file_scanner.FileScanner

# Re-export base settings
ProcessingResult = _base_settings.ProcessingResult
AnalysisResult = _base_settings.AnalysisResult

# Re-export utils
format_size = _utils.format_size
format_time = _utils.format_time
normalize_format = _utils.normalize_format
get_tool_paths = _utils.get_tool_paths
is_texture_atlas = _utils.is_texture_atlas
calculate_new_dimensions = _utils.calculate_new_dimensions
FORMAT_MAP = _utils.FORMAT_MAP
FILTER_MAP = _utils.FILTER_MAP

# Get tool paths - pass the optimizer's root directory
# This file is at: openmw-regular-map-optimizer/src/core/regular_processor.py
# Tools are at: openmw-regular-map-optimizer/tools/
_optimizer_root = Path(__file__).parent.parent.parent
_TEXCONV_EXE, _TEXDIAG_EXE, _CUTTLEFISH_EXE = get_tool_paths(_optimizer_root)
TEXCONV_EXE = _TEXCONV_EXE
TEXDIAG_EXE = _TEXDIAG_EXE
CUTTLEFISH_EXE = _CUTTLEFISH_EXE if _CUTTLEFISH_EXE else ""


# Format mapping for regular textures (no BC5)
# texconv format mapping (legacy, kept for reference)
REGULAR_FORMAT_MAP = {
    "BC1/DXT1": "BC1_UNORM",
    "BC2/DXT3": "BC2_UNORM",
    "BC3/DXT5": "BC3_UNORM",
    "BGRA": "B8G8R8A8_UNORM",
    "BGR": "B8G8R8X8_UNORM"
}

# Cuttlefish format mapping (BC formats only)
# BC1_RGB = opaque (no alpha), BC1_RGBA = 1-bit alpha
# Note: BGR and BGRA use texconv - cuttlefish outputs DX10 headers for uncompressed
CUTTLEFISH_FORMAT_MAP = {
    "BC1/DXT1": "BC1_RGB",      # Use BC1_RGB for opaque textures
    "BC1/DXT1a": "BC1_RGBA",    # Use BC1_RGBA for 1-bit alpha (punchthrough)
    "BC2/DXT3": "BC2",          # 4-bit alpha
    "BC3/DXT5": "BC3",          # Interpolated alpha
}

# Cuttlefish filter mapping (for resize operations)
# Cuttlefish supports: box, linear, cubic, catmull-rom
# We map UI options to cuttlefish equivalents
CUTTLEFISH_FILTER_MAP = {
    "BOX": "box",
    "LINEAR": "linear",
    "CUBIC": "cubic",
    "FANT": "catmull-rom",  # FANT (texconv) maps to catmull-rom (cuttlefish) - both preserve sharp details
}

# Formats that support alpha
ALPHA_FORMATS = ["BC2/DXT3", "BC3/DXT5", "BGRA", "RGBA"]
NO_ALPHA_FORMATS = ["BC1/DXT1", "BGR", "RGB"]


def _is_well_compressed(format_str: str, mipmap_count: int, width: int, height: int) -> bool:
    """
    Check if a texture is "well compressed" and can be passed through.

    A well-compressed texture:
    - Is in BC1, BC2, or BC3 format
    - Has adequate mipmaps (more than just base level for textures > 4x4)
    """
    normalized = normalize_format(format_str)

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
    normalized = normalize_format(format_str)
    # BC1/DXT1 might have 1-bit alpha (DXT1a) but we can't detect without scanning blocks
    # For passthrough, we treat BC1 as "handled" - don't upgrade to BC3
    return normalized in ['BC3/DXT5', 'BC2/DXT3', 'BGRA', 'RGBA']


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


def _process_texture_with_texconv(input_path: Path, output_path: Path, target_format: str,
                                   new_width: int, new_height: int, will_resize: bool,
                                   skip_mipmaps: bool, settings: dict) -> Tuple[bool, Optional[str]]:
    """
    Process texture using texconv.
    Used for BGR/BGRA uncompressed formats (cuttlefish outputs DX10 headers for these).
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

        # Alpha handling for BGRA - straight alpha, processed separately during mipmap generation
        # This prevents color bleeding and keeps alpha non-premultiplied
        if target_format == "BGRA":
            cmd.extend(["-alpha", "-sepalpha"])

        # Resize if needed
        if will_resize:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])
            # Apply resize filter
            resize_method = str(settings.get('resize_method', 'FANT')).split()[0].upper()
            if resize_method in FILTER_MAP:
                cmd.extend(["-if", FILTER_MAP[resize_method]])

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

        # Post-process: Convert 32-bit BGRX to true 24-bit BGR
        # texconv outputs B8G8R8X8_UNORM (32-bit with padding) for BGR format
        if target_format == "BGR":
            convert_bgrx32_to_bgr24(output_path)

        return True, None

    except Exception as e:
        return False, f"Exception: {str(e)}"


def _process_texture_static(input_path: Path, output_path: Path, settings: dict,
                            cached_analysis: dict = None) -> Tuple[bool, Optional[str]]:
    """
    Process a single texture file.

    Uses cuttlefish for BC compression (better PSNR, 2-5 dB higher than texconv).
    Falls back to texconv for BGR (24-bit) small textures since cuttlefish can't write 24-bit DDS.

    If cached_analysis is provided (from analyze_files), uses the pre-computed target_format
    to ensure processing matches the analysis predictions. This is critical for alpha
    optimization where analysis detects unused alpha and selects BC1 instead of BC3.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # === Use cached analysis if available ===
        if cached_analysis and 'target_format' in cached_analysis:
            # Use pre-computed values from analysis
            orig_width = cached_analysis['width']
            orig_height = cached_analysis['height']
            format_name = cached_analysis['format']
            target_format = cached_analysis['target_format']
            mipmap_count = cached_analysis.get('mipmap_count', 0)

            # Use pre-computed dimensions from analysis to ensure consistency
            new_width = cached_analysis.get('new_width', orig_width)
            new_height = cached_analysis.get('new_height', orig_height)
            will_resize = (new_width != orig_width) or (new_height != orig_height)

            # Check if this is a passthrough case
            is_compressed = format_name in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']
            has_valid_mipmaps = _is_well_compressed(format_name, mipmap_count, orig_width, orig_height)

            # Passthrough: compressed texture that doesn't need changes
            if is_compressed and not will_resize and has_valid_mipmaps and target_format == format_name:
                if settings.get('copy_passthrough_files', True):
                    shutil.copy2(input_path, output_path)
                return True, None

            # A8 format passthrough - rare specialty texture, copy as-is
            if target_format in ('A8_UNORM', 'A8'):
                if settings.get('copy_passthrough_files', True):
                    shutil.copy2(input_path, output_path)
                return True, None

        else:
            # === Fallback: Parse file header if no cached analysis ===
            if input_path.suffix.lower() == '.tga':
                dimensions, format_name, mipmap_count = parse_tga_header_extended(input_path)
                if not dimensions:
                    return False, "Could not parse TGA header"
                has_alpha = (format_name == 'TGA_RGBA')

                # Optional: Check if TGA alpha is actually used
                optimize_alpha = settings.get('optimize_unused_alpha', False)
                if optimize_alpha and has_alpha:
                    alpha_threshold = settings.get('alpha_threshold', 255)
                    actually_has_alpha = has_meaningful_alpha(input_path, format_name, alpha_threshold)
                    if not actually_has_alpha:
                        has_alpha = False
            else:
                dimensions, format_name, mipmap_count = parse_dds_header_extended(input_path)
                if not dimensions:
                    return False, "Could not parse DDS header"
                format_name = normalize_format(format_name)
                has_alpha = _has_alpha_channel(format_name)

            # Optional: Check if alpha is actually used (not just declared in format)
            optimize_alpha = settings.get('optimize_unused_alpha', False)
            if optimize_alpha and has_alpha:
                alpha_threshold = settings.get('alpha_threshold', 255)
                actually_has_alpha = has_meaningful_alpha(input_path, format_name, alpha_threshold)
                if not actually_has_alpha:
                    has_alpha = False

            orig_width, orig_height = dimensions
            new_width, new_height = calculate_new_dimensions(orig_width, orig_height, settings, input_path)
            will_resize = (new_width != orig_width) or (new_height != orig_height)

            # === Determine target format (fallback logic) ===
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

        # === Use texconv for uncompressed formats (BGR/BGRA) ===
        # Cuttlefish outputs DX10 headers for these, texconv writes legacy DDS
        if target_format in ("BGR", "BGRA"):
            return _process_texture_with_texconv(
                input_path, output_path, target_format,
                new_width, new_height, will_resize, skip_mipmaps, settings
            )

        # === Use cuttlefish for BC formats (better PSNR) ===
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
        resize_method = str(settings.get('resize_method', 'FANT')).split()[0].upper()
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

            # Handle passthrough files when copy_passthrough_files=False
            # These files are skipped entirely (no processing, no output file)
            is_passthrough = cached_analysis.get('is_passthrough', False)
            copy_passthrough = settings.get('copy_passthrough_files', False)

            if is_passthrough and not copy_passthrough:
                # Passthrough file with copying disabled - skip without error
                result.success = True
                result.new_dims = result.orig_dims
                result.new_format = cached_analysis.get('target_format', result.orig_format)
                result.output_size = 0  # No output file created
                return result
        else:
            dims, fmt = parse_dds_header(input_file)
            result.orig_dims = dims
            result.orig_format = fmt

        # Pass cached analysis to processing function so it uses pre-computed target format
        success, error_detail = _process_texture_static(input_file, output_file, settings, cached_analysis)

        if success:
            result.success = True
            if output_file.exists():
                result.output_size = output_file.stat().st_size
                new_dims, new_fmt = parse_dds_header(output_file)
                result.new_dims = new_dims
                result.new_format = new_fmt
            else:
                # Passthrough case where copy was skipped but processing reported success
                result.new_dims = result.orig_dims
                result.new_format = cached_analysis.get('target_format', result.orig_format) if cached_analysis else result.orig_format
                result.output_size = 0
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
            result.format = normalize_format(format_name)
            result.mipmap_count = mipmap_count

        # === Handle special formats that should passthrough ===
        # A8 textures are rare specialty textures (alpha-only), passthrough as-is
        if result.format == 'A8_UNORM' or result.format == 'A8':
            result.is_passthrough = True
            result.target_format = result.format
            result.new_width = result.width
            result.new_height = result.height
            result.projected_size = file_size
            result.warnings.append("A8 format (alpha-only) - passthrough")
            return result

        # Determine if source has alpha
        result.has_alpha = _has_alpha_channel(result.format)

        # Alpha optimization: detect unused alpha AND DXT1a textures
        optimize_alpha = settings.get('optimize_unused_alpha', False)

        if optimize_alpha:
            alpha_threshold = settings.get('alpha_threshold', 255)

            # Check BC1/DXT1 for DXT1a (1-bit alpha) - important for correct reprocessing
            if result.format == 'BC1/DXT1':
                # analyze_bc1_alpha returns True if DXT1a is used (has transparent pixels)
                if analyze_bc1_alpha(input_file):
                    result.has_dxt1a = True
                    result.has_alpha = True  # DXT1a does have meaningful alpha

            # Check other alpha formats for unused alpha
            elif result.has_alpha:
                # Check if alpha is actually meaningful (not all opaque)
                actually_has_alpha = has_meaningful_alpha(input_file, result.format, alpha_threshold)
                if not actually_has_alpha:
                    # Track the optimization
                    result.alpha_optimized = True
                    result.original_format = result.format
                    result.has_alpha = False
                    # Note: actual target format determined later (BC1 for normal size, BGR for small)

        # Calculate new dimensions (handles atlas protection, max/min resolution)
        is_atlas = is_texture_atlas(input_file)
        new_width, new_height = calculate_new_dimensions(
            result.width, result.height, settings, is_atlas=is_atlas
        )
        result.new_width = new_width
        result.new_height = new_height
        will_resize = (new_width != result.width) or (new_height != result.height)

        # === STEP 1: Handle compressed textures (BC1/BC2/BC3) ===
        is_compressed = result.format in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']
        has_valid_mipmaps = _is_well_compressed(result.format, result.mipmap_count, result.width, result.height)

        if is_compressed:
            # Determine target format based on alpha optimization and DXT1a detection
            if result.alpha_optimized:
                # Alpha was unused - downgrade to BC1
                target_format = 'BC1/DXT1'
            elif result.has_dxt1a:
                # DXT1a (BC1 with 1-bit alpha) - upgrade to BC2 when reprocessing
                # BC2 preserves the alpha better than BC3 for 1-bit transparency
                target_format = 'BC2/DXT3'
            else:
                # Keep original format
                target_format = result.format

            # Check for passthrough (DXT1a that doesn't need resize is still passthrough)
            if not will_resize and has_valid_mipmaps and not result.alpha_optimized:
                # Passthrough: already compressed with valid mipmaps, no resize needed, no alpha change
                result.is_passthrough = True
                result.target_format = result.format
                if result.has_dxt1a:
                    result.warnings.append(f"Compressed passthrough - DXT1a with valid mipmaps, no reprocessing needed")
                else:
                    result.warnings.append(f"Compressed passthrough - already optimized ({result.format}), no reprocessing needed")
                result.projected_size = file_size
                return result
            else:
                # Need to reprocess (resize, fix mipmaps, or alpha optimization)
                result.target_format = target_format
                if result.alpha_optimized:
                    result.warnings.append(f"Alpha unused ({result.original_format} → {target_format})")
                elif result.has_dxt1a:
                    # DXT1a needs reprocessing - explain why and that we're preserving alpha
                    if will_resize:
                        result.warnings.append("DXT1a detected (resize) - upgrading to BC2 to preserve 1-bit alpha")
                    else:
                        result.warnings.append("DXT1a detected (mipmap regen) - upgrading to BC2 to preserve 1-bit alpha")
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
                'excluded_tga_duplicates': 0,  # DDS files skipped because TGA exists
                'blacklist_examples': [],
                'whitelist_examples': [],
                # Full lists for export
                'normal_map_files': [],
                'blacklist_files': [],
                'tga_duplicate_files': [],  # DDS files that were skipped for TGA
            }

        exclude_normal = getattr(self.settings, 'exclude_normal_maps', True)
        whitelist = self.scanner.path_whitelist
        blacklist = self.scanner.path_blacklist

        included_files = []

        # Find all DDS files in one pass
        all_dds = list(input_dir.rglob("*.dds"))

        # Find all TGA files if enabled
        all_tga = []
        tga_stems = set()  # Track TGA stems to skip duplicate DDS files
        if hasattr(self.settings, 'enable_tga_support') and self.settings.enable_tga_support:
            all_tga = list(input_dir.rglob("*.tga"))
            # Build set of (parent_dir, stem) tuples for TGA files
            tga_stems = {(f.parent, f.stem.lower()) for f in all_tga}

        # Filter DDS files - skip if TGA with same stem exists in same directory
        # TGA is preferred as it's typically higher quality (lossless source)
        filtered_dds = []
        for dds_file in all_dds:
            key = (dds_file.parent, dds_file.stem.lower())
            if key in tga_stems:
                if track_filtered:
                    self.filter_stats['excluded_tga_duplicates'] += 1
                    self.filter_stats['tga_duplicate_files'].append(str(dds_file.relative_to(input_dir)))
                continue  # Skip DDS, TGA takes priority
            filtered_dds.append(dds_file)

        all_textures = filtered_dds + all_tga

        if track_filtered:
            # Total includes all found files before TGA deduplication
            self.filter_stats['total_textures_found'] = len(all_dds) + len(all_tga)

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

        # Filter out passthrough files if copy_passthrough_files is disabled
        copy_passthrough = settings_dict.get('copy_passthrough_files', False)
        if not copy_passthrough:
            files_to_process = []
            for f in all_files:
                rel_path = str(f.relative_to(input_dir))
                cached = self._get_cached_analysis(rel_path)
                if cached and cached.get('is_passthrough', False):
                    continue  # Skip passthrough files
                files_to_process.append(f)
            all_files = files_to_process

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

        # Post-processing: strip DX10 headers from cuttlefish output
        # Cuttlefish writes DX10 headers for BC formats which OpenMW doesn't support
        stripped, skipped, warnings = strip_dx10_headers_batch(output_dir)
        if warnings:
            # Log warnings but don't fail - these are non-critical
            for warning in warnings:
                print(f"DX10 strip warning: {warning}")

        return results

    def _get_cached_analysis(self, relative_path: str) -> Optional[dict]:
        """Get cached analysis data for a file"""
        if relative_path in self.analysis_cache:
            result = self.analysis_cache[relative_path]
            return {
                'width': result.width,
                'height': result.height,
                'new_width': result.new_width,
                'new_height': result.new_height,
                'format': result.format,
                'target_format': result.target_format,
                'mipmap_count': result.mipmap_count,
                'alpha_optimized': result.alpha_optimized,
                'is_passthrough': result.is_passthrough,
                'has_dxt1a': result.has_dxt1a,
            }
        return None
