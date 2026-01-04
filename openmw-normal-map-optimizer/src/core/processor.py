"""
Core logic for OpenMW Normal Map Optimizer.
Handles file processing, analysis, and conversion independently of UI.

This module uses the shared core from openmw-texture-optimizer-core.
"""

from pathlib import Path
import subprocess
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
import platform
from typing import Optional, Tuple, List, Dict, Callable
import sys
import json
import importlib.util

# =============================================================================
# Shared Core Import
# =============================================================================
# Use importlib to avoid name collision with local 'core' package
# Register modules in sys.modules so they can be pickled for multiprocessing

_shared_core_path = Path(__file__).parent.parent.parent.parent / "openmw-texture-optimizer-core" / "src" / "core"

def _import_shared_module(module_name):
    """Import a module from the shared core package and register in sys.modules."""
    full_name = f"shared_core.{module_name}"

    # Return existing module if already imported
    if full_name in sys.modules:
        return sys.modules[full_name]

    # Ensure parent package exists in sys.modules
    if "shared_core" not in sys.modules:
        import types
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

# Re-export for external use
parse_dds_header = _dds_parser.parse_dds_header
get_parser_stats = _dds_parser.get_parser_stats
reset_parser_stats = _dds_parser.reset_parser_stats
convert_bgrx32_to_bgr24 = _dds_parser.convert_bgrx32_to_bgr24
FileScanner = _file_scanner.FileScanner
ProcessingResult = _base_settings.ProcessingResult
AnalysisResult = _base_settings.AnalysisResult
format_size = _utils.format_size
format_time = _utils.format_time
normalize_format = _utils.normalize_format
get_tool_paths = _utils.get_tool_paths
is_texture_atlas = _utils.is_texture_atlas
calculate_new_dimensions = _utils.calculate_new_dimensions
FORMAT_MAP = _utils.FORMAT_MAP
FILTER_MAP = _utils.FILTER_MAP

# Import settings from local module
from .normal_settings import NormalSettings

# Get tool paths - pass the optimizer's root directory
# This file is at: openmw-normal-map-optimizer/src/core/processor.py
# Tools are at: openmw-normal-map-optimizer/tools/
_optimizer_root = Path(__file__).parent.parent.parent
_TEXCONV_EXE, _TEXDIAG_EXE, _ = get_tool_paths(_optimizer_root)
TEXCONV_EXE = _TEXCONV_EXE
TEXDIAG_EXE = _TEXDIAG_EXE

# Fast parser is always available (via shared core)
_HAS_FAST_PARSER = True


# =============================================================================
# DDS Info Helper (uses shared parser, with texdiag fallback)
# =============================================================================

def _get_dds_info(input_dds: Path) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Get dimensions and format from DDS file using the shared fast parser.

    Returns:
        ((width, height), format_string) or (None, "UNKNOWN") on error
    """
    try:
        dims, fmt = parse_dds_header(input_dds)
        if dims is not None and fmt != "UNKNOWN":
            # Normalize format to friendly name
            return dims, normalize_format(fmt)
    except Exception:
        pass

    return None, "UNKNOWN"


def _get_dimensions(input_dds: Path) -> Optional[Tuple[int, int]]:
    """Get dimensions from DDS file. Returns (width, height) or None"""
    dimensions, _ = _get_dds_info(input_dds)
    return dimensions


def _get_format(input_dds: Path) -> str:
    """Get format from DDS file. Returns format string or 'UNKNOWN'"""
    _, format_str = _get_dds_info(input_dds)
    return format_str


# =============================================================================
# Normal Map Processing Logic
# =============================================================================

def _process_normal_map(input_dds: Path, output_dds: Path, is_nh: bool, settings: dict) -> bool:
    """Process a single normal map file using texconv."""
    try:
        output_dds.parent.mkdir(parents=True, exist_ok=True)

        # Get both dimensions and format
        dimensions, format_name = _get_dds_info(input_dds)
        if not dimensions:
            return False

        orig_width, orig_height = dimensions
        new_width, new_height = calculate_new_dimensions(orig_width, orig_height, settings, input_dds)

        # Check for compressed passthrough (fast path - just copy the file)
        if settings.get('allow_compressed_passthrough', False):
            will_resize = (new_width != orig_width) or (new_height != orig_height)

            if not will_resize:
                current_format = normalize_format(format_name)

                if current_format in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']:
                    can_passthrough = False
                    needs_rename = False

                    # Check for mislabeling (NH textures without alpha)
                    if is_nh and settings.get('auto_fix_nh_to_n', True):
                        if current_format in ['BC5/ATI2', 'BC1/DXT1']:
                            can_passthrough = True
                            needs_rename = True
                        elif current_format == 'BC3/DXT5':
                            can_passthrough = True
                            needs_rename = False
                    else:
                        # N texture - check for wasted alpha
                        if settings.get('auto_optimize_n_alpha', True):
                            if current_format == 'BC3/DXT5':
                                can_passthrough = False
                            else:
                                can_passthrough = True
                        else:
                            can_passthrough = True

                    if can_passthrough:
                        # Only copy if copy_passthrough_files is enabled
                        if settings.get('copy_passthrough_files', False):
                            if needs_rename:
                                output_path_str = str(output_dds)
                                if output_path_str.lower().endswith('_nh.dds'):
                                    corrected_output = Path(output_path_str[:-7] + '_n.dds')
                                    corrected_output.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(input_dds, corrected_output)
                            else:
                                shutil.copy2(input_dds, output_dds)
                        # Return True either way - passthrough means "no processing needed"
                        return True

        # Check if we're resizing
        will_resize = (new_width != orig_width) or (new_height != orig_height)

        # Normalize format for comparison
        current_format = normalize_format(format_name)

        # Determine target format with smart format handling
        target_format = settings['nh_format'] if is_nh else settings['n_format']

        # Auto-fix: NH-labeled textures with no-alpha formats should be treated as N
        if is_nh and settings.get('auto_fix_nh_to_n', True):
            if current_format in ['BGR', 'BC5/ATI2', 'BC1/DXT1']:
                target_format = settings['n_format']
                is_nh = False

        # Preserve compressed format when not resizing
        should_preserve = False
        if settings.get('preserve_compressed_format', True) and not will_resize:
            compressed_formats = ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']
            if current_format in compressed_formats:
                if is_nh:
                    if current_format == 'BC3/DXT5':
                        should_preserve = True
                else:
                    if current_format in ['BC5/ATI2', 'BC1/DXT1']:
                        should_preserve = True

                if should_preserve:
                    target_format = current_format

        # Auto-optimize: N textures with alpha formats can be optimized
        if not is_nh and settings.get('auto_optimize_n_alpha', True) and not should_preserve:
            if current_format == 'BGRA':
                target_format = settings['n_format']
            elif current_format == 'BC3/DXT5':
                target_format = 'BC1/DXT1'

        # Small texture override (only for uncompressed sources)
        if settings.get('use_small_texture_override', True):
            is_already_compressed = current_format in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']

            if not is_already_compressed:
                min_dim = min(new_width, new_height)
                if is_nh:
                    threshold = settings.get('small_nh_threshold', 256)
                    if threshold > 0 and min_dim <= threshold:
                        target_format = "BGRA"
                else:
                    threshold = settings.get('small_n_threshold', 128)
                    if threshold > 0 and min_dim <= threshold:
                        target_format = "BGR"

        texconv_format = FORMAT_MAP[target_format]

        # Build texconv command
        cmd = [
            TEXCONV_EXE,
            "-f", texconv_format,
            "-m", "0",
            "-alpha",     # Straight alpha (not premultiplied)
            "-sepalpha",  # Process alpha separately during mipmap generation
            "-dx9"
        ]

        if settings.get('invert_y', False):
            cmd.append("-inverty")

        if target_format != "BC5/ATI2" and settings.get('reconstruct_z', True):
            cmd.append("-reconstructz")

        # Force BC1 to fully opaque mode (no punch-through alpha)
        # This prevents unused alpha data from triggering DXT1a transparency
        if target_format == "BC1/DXT1":
            cmd.extend(["-at", "0"])

        if target_format in ["BC1/DXT1", "BC3/DXT5"]:
            bc_options = ""
            if settings.get('uniform_weighting', True):
                bc_options += "u"
            if settings.get('use_dithering', False):
                bc_options += "d"
            if bc_options:
                cmd.extend(["-bc", bc_options])

        if new_width != orig_width or new_height != orig_height:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])

            resize_method = str(settings.get('resize_method', 'CUBIC')).split()[0]
            if resize_method in FILTER_MAP:
                cmd.extend(["-if", FILTER_MAP[resize_method]])

        if settings.get('enforce_power_of_2', False):
            cmd.append("-pow2")

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

        # Post-process: Convert 32-bit BGRX to true 24-bit BGR
        # texconv outputs B8G8R8X8_UNORM (32-bit with padding) for BGR format
        if target_format == "BGR":
            convert_bgrx32_to_bgr24(output_dds)

        return True

    except Exception:
        return False


# =============================================================================
# Worker Functions (for multiprocessing)
# =============================================================================

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
        if cached_analysis:
            orig_dims = (cached_analysis['width'], cached_analysis['height'])
            orig_format = cached_analysis['format']
            result.orig_dims = orig_dims
            result.orig_format = orig_format

            # Handle passthrough files when copy_passthrough_files=False
            # These files are skipped entirely (no processing, no output file)
            is_passthrough = cached_analysis.get('is_passthrough', False)
            copy_passthrough = settings.get('copy_passthrough_files', False)

            if is_passthrough and not copy_passthrough:
                # Passthrough file with copying disabled - skip without error
                result.success = True
                result.new_dims = (cached_analysis.get('new_width', orig_dims[0]),
                                   cached_analysis.get('new_height', orig_dims[1]))
                result.new_format = cached_analysis.get('target_format', orig_format)
                result.output_size = 0  # No output file created
                return result
        else:
            orig_dims, orig_format = _get_dds_info(dds_file)
            result.orig_dims = orig_dims
            result.orig_format = orig_format

        if not result.orig_dims:
            result.error_msg = "Could not determine dimensions"
            return result

        success = _process_normal_map(dds_file, output_file, is_nh, settings)

        if success:
            result.success = True
            if output_file.exists():
                result.output_size = output_file.stat().st_size
                result.new_dims = _get_dimensions(output_file)
                result.new_format = _get_format(output_file)
            else:
                # Passthrough case where copy was skipped but processing reported success
                result.new_dims = (cached_analysis.get('new_width', result.orig_dims[0]),
                                   cached_analysis.get('new_height', result.orig_dims[1])) if cached_analysis else result.orig_dims
                result.new_format = cached_analysis.get('target_format', result.orig_format) if cached_analysis else result.orig_format
                result.output_size = 0
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
        # Get dimensions and format using shared parser
        dimensions, format_name = _get_dds_info(dds_file)

        if not dimensions:
            result.error = "Could not determine dimensions"
            return result

        width, height = dimensions
        result.width = width
        result.height = height

        # Normalize format
        current_format = normalize_format(format_name)
        result.format = current_format

        # Check if this is an atlas
        is_atlas = is_texture_atlas(dds_file)

        new_width, new_height = calculate_new_dimensions(width, height, settings, is_atlas=is_atlas)
        result.new_width = new_width
        result.new_height = new_height

        will_resize = (new_width != width) or (new_height != height)

        # Determine target format with smart format handling
        target_format = settings['nh_format'] if is_nh else settings['n_format']

        # Auto-fix: NH-labeled textures with no-alpha formats should be treated as N
        if is_nh and settings.get('auto_fix_nh_to_n', True):
            if current_format in ['BGR', 'BC5/ATI2', 'BC1/DXT1']:
                target_format = settings['n_format']
                is_nh = False

        # Preserve compressed format when not resizing
        should_preserve = False
        if settings.get('preserve_compressed_format', True) and not will_resize:
            compressed_formats = ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']
            if current_format in compressed_formats:
                if is_nh:
                    if current_format == 'BC3/DXT5':
                        should_preserve = True
                else:
                    if current_format in ['BC5/ATI2', 'BC1/DXT1']:
                        should_preserve = True

                if should_preserve:
                    target_format = current_format

        # Auto-optimize: N textures with alpha formats
        if not is_nh and settings.get('auto_optimize_n_alpha', True) and not should_preserve:
            if current_format == 'BGRA':
                target_format = settings['n_format']
            elif current_format == 'BC3/DXT5':
                target_format = 'BC1/DXT1'

        # Small texture override (only for uncompressed sources)
        if settings.get('use_small_texture_override', True):
            is_already_compressed = current_format in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']

            if not is_already_compressed:
                min_dim_output = min(new_width, new_height)
                if is_nh:
                    threshold = settings.get('small_nh_threshold', 256)
                    if threshold > 0 and min_dim_output <= threshold:
                        target_format = "BGRA"
                else:
                    threshold = settings.get('small_n_threshold', 128)
                    if threshold > 0 and min_dim_output <= threshold:
                        target_format = "BGR"

        result.target_format = target_format

        # Detect warnings
        warnings = []
        original_is_nh = dds_file.stem.lower().endswith('_nh')

        # Compressed passthrough info
        if settings.get('allow_compressed_passthrough', False) and not will_resize:
            if current_format in ['BC5/ATI2', 'BC3/DXT5', 'BC1/DXT1']:
                can_passthrough = False
                needs_rename = False

                if original_is_nh and settings.get('auto_fix_nh_to_n', True):
                    if current_format in ['BC5/ATI2', 'BC1/DXT1']:
                        can_passthrough = True
                        needs_rename = True
                    elif current_format == 'BC3/DXT5':
                        can_passthrough = True
                        needs_rename = False
                else:
                    if not original_is_nh and settings.get('auto_optimize_n_alpha', True):
                        if current_format == 'BC3/DXT5':
                            can_passthrough = False
                        else:
                            can_passthrough = True
                    else:
                        can_passthrough = True

                if can_passthrough:
                    result.is_passthrough = True
                    if needs_rename:
                        warnings.append("Compressed passthrough (rename _NH→_N) - already optimized, no reprocessing needed")
                    else:
                        warnings.append("Compressed passthrough - already optimized, no reprocessing needed")

        # Auto-fixed mislabeled NH texture
        if original_is_nh and not is_nh and settings.get('auto_fix_nh_to_n', True):
            warnings.append(f"NH-labeled texture stored as {current_format} (no alpha) - auto-fixed to N texture")

        # Auto-optimized N texture with wasted alpha
        if not original_is_nh and settings.get('auto_optimize_n_alpha', True) and not should_preserve:
            if current_format == 'BGRA' and target_format != 'BGRA':
                warnings.append(f"N texture with unused alpha in BGRA - auto-optimized to {target_format}")
            elif current_format == 'BC3/DXT5' and target_format == 'BC1/DXT1':
                warnings.append("N texture with unused alpha in BC3 - auto-optimized to BC1")

        # Texture atlas detected
        if is_atlas and width > 0 and height > 0:
            max_dim = max(width, height)
            if max_dim > settings.get('max_resolution', 2048) and settings.get('max_resolution', 0) > 0:
                warnings.append(f"Texture atlas detected - resize skipped despite size {width}x{height} exceeding max resolution")

        # N texture saved to format with unused alpha channel
        if not is_nh and not settings.get('auto_optimize_n_alpha', True):
            if target_format in ["BGRA", "BC3/DXT5"]:
                warnings.append(f"N texture will be saved as {target_format} - alpha channel will not be used (auto-optimize disabled)")

        # NH texture saved to format without alpha channel
        if original_is_nh and is_nh:
            if target_format in ["BGR", "BC5/ATI2", "BC1/DXT1"]:
                warnings.append(f"NH texture will be saved as {target_format} - alpha channel not available")

        # Converting compressed to larger format warning
        if not settings.get('preserve_compressed_format', True):
            compressed_source_formats = ["BC3/DXT5", "BC1/DXT1", "BC5/ATI2"]
            if current_format in compressed_source_formats:
                size_increase_targets = []
                if current_format == "BC1/DXT1":
                    if target_format in ["BC3/DXT5", "BC5/ATI2", "BGR", "BGRA"]:
                        size_increase_targets.append(target_format)
                elif current_format in ["BC3/DXT5", "BC5/ATI2"]:
                    if target_format in ["BGR", "BGRA"]:
                        size_increase_targets.append(target_format)

                if size_increase_targets and not will_resize:
                    for target in size_increase_targets:
                        warnings.append(f"Converting {current_format} to {target} will increase file size without quality gain (preserve format disabled)")

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


# =============================================================================
# Main Processor Class
# =============================================================================

class NormalMapProcessor:
    """Core processor for normal map optimization"""

    def __init__(self, settings: NormalSettings):
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

    def find_normal_maps(self, input_dir: Path, track_filtered: bool = False) -> Tuple[List[Path], List[Path]]:
        """
        Find all normal map files in directory. Returns (n_files, nh_files)

        - Includes: .dds files ending in _n or _nh (normal maps)
        - Applies: Path whitelist (Textures) and blacklist (icon, icons, bookart)

        If track_filtered=True, also populates self.filter_stats with counts.
        """
        # Initialize filter stats if tracking
        if track_filtered:
            self.filter_stats = {
                'total_normal_maps_found': 0,
                'included': 0,
                'excluded_whitelist': 0,
                'excluded_blacklist': 0,
                'blacklist_examples': [],
                'whitelist_examples': [],
                # Full lists for export
                'blacklist_files': [],
            }

        is_case_sensitive = platform.system() != 'Windows'

        if is_case_sensitive:
            nh_candidates = list(input_dir.rglob("*_nh.dds")) + list(input_dir.rglob("*_NH.dds")) + \
                           list(input_dir.rglob("*_Nh.dds")) + list(input_dir.rglob("*_nH.dds"))
            n_candidates = list(input_dir.rglob("*_n.dds")) + list(input_dir.rglob("*_N.dds"))
        else:
            nh_candidates = list(input_dir.rglob("*_nh.dds"))
            n_candidates = list(input_dir.rglob("*_n.dds"))

        nh_files_raw = list(set(nh_candidates))
        n_files_raw = [f for f in set(n_candidates) if not f.stem.lower().endswith('_nh')]

        if track_filtered:
            self.filter_stats['total_normal_maps_found'] = len(n_files_raw) + len(nh_files_raw)

        # Apply whitelist/blacklist filtering
        whitelist = self.scanner.path_whitelist
        blacklist = self.scanner.path_blacklist

        def filter_file(f: Path) -> bool:
            """Return True if file should be included"""
            path_parts = [p.lower() for p in f.parts]

            # Check whitelist
            if whitelist:
                if not any(any(w in part for part in path_parts) for w in whitelist):
                    if track_filtered:
                        self.filter_stats['excluded_whitelist'] += 1
                        if len(self.filter_stats['whitelist_examples']) < 5:
                            self.filter_stats['whitelist_examples'].append(str(f.relative_to(input_dir)))
                    return False

            # Check blacklist
            if blacklist:
                for blocked in blacklist:
                    if any(blocked in part for part in path_parts):
                        if track_filtered:
                            self.filter_stats['excluded_blacklist'] += 1
                            self.filter_stats['blacklist_files'].append(str(f.relative_to(input_dir)))
                            if len(self.filter_stats['blacklist_examples']) < 5:
                                self.filter_stats['blacklist_examples'].append(str(f.relative_to(input_dir)))
                        return False

            return True

        n_files = [f for f in n_files_raw if filter_file(f)]
        nh_files = [f for f in nh_files_raw if filter_file(f)]

        if track_filtered:
            self.filter_stats['included'] = len(n_files) + len(nh_files)

        return n_files, nh_files

    def analyze_files(self, input_dir: Path, progress_callback: Optional[Callable[[int, int], None]] = None) -> List[AnalysisResult]:
        """Analyze all normal maps and return analysis results. Results are cached for processing."""
        n_files, nh_files = self.find_normal_maps(input_dir, track_filtered=True)
        all_files = n_files + nh_files

        if not all_files:
            return []

        settings_dict = self.settings.to_dict()
        self._settings_hash = hash(json.dumps(settings_dict, sort_keys=True))

        # Use parallel for large file counts to benefit from I/O parallelism
        # (especially helpful when files are on slow storage)
        use_parallel = self.settings.enable_parallel and len(all_files) > 100

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
        settings_dict = self.settings.to_dict()
        current_hash = hash(json.dumps(settings_dict, sort_keys=True))

        if not self.analysis_cache or self._settings_hash != current_hash:
            raise RuntimeError(
                "Analysis must be run before processing. Please run analyze_files() first, "
                "or re-run it if settings have changed."
            )

        n_files, nh_files = self.find_normal_maps(input_dir)

        # Filter out passthrough files if copy_passthrough_files is disabled
        copy_passthrough = settings_dict.get('copy_passthrough_files', False)
        if not copy_passthrough:
            def should_process(f):
                rel_path = str(f.relative_to(input_dir))
                cached = self._get_cached_analysis(rel_path)
                if cached and cached.get('is_passthrough', False):
                    return False  # Skip passthrough files
                return True

            n_files = [f for f in n_files if should_process(f)]
            nh_files = [f for f in nh_files if should_process(f)]

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

    def _analyze_files_parallel(self, all_files: List[Path], source_dir: Path,
                                settings: dict, progress_callback: Optional[Callable] = None) -> List[AnalysisResult]:
        """Analyze files in parallel for better I/O throughput on slow storage"""
        results = []
        completed = 0
        total_files = len(all_files)
        chunk_size = 100  # Process in chunks for better progress feedback

        with ProcessPoolExecutor(max_workers=self.settings.max_workers) as executor:
            # Process in chunks
            for chunk_start in range(0, total_files, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_files)
                chunk = all_files[chunk_start:chunk_end]

                # Submit chunk
                futures = {}
                for f in chunk:
                    args = (str(f), str(source_dir), settings)
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
                            relative_path=str(file_path.relative_to(source_dir)),
                            file_size=file_path.stat().st_size if file_path.exists() else 0,
                            error=str(e)
                        )
                        results.append(error_result)

                    if progress_callback:
                        progress_callback(completed, total_files)

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
                    if progress_callback:
                        progress_callback(current, total, error_result)

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
                'new_width': result.new_width,
                'new_height': result.new_height,
                'format': result.format,
                'target_format': result.target_format,
                'is_passthrough': result.is_passthrough,
            }
        return None
