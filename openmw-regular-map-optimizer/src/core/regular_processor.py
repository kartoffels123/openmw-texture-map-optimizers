"""
Core logic for OpenMW Regular Texture Optimizer.
Handles file processing, analysis, and conversion for regular (non-normal map) textures.
"""

from pathlib import Path
import subprocess
import re
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

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# Format mapping for regular textures (no BC5)
REGULAR_FORMAT_MAP = {
    "BC1/DXT1": "BC1_UNORM",
    "BC2/DXT3": "BC2_UNORM",
    "BC3/DXT5": "BC3_UNORM",
    "BGRA": "B8G8R8A8_UNORM",
    "BGR": "B8G8R8X8_UNORM"
}

# Formats that support alpha
ALPHA_FORMATS = ["BC2/DXT3", "BC3/DXT5", "BGRA"]
NO_ALPHA_FORMATS = ["BC1/DXT1", "BGR"]


def _normalize_format(fmt: str) -> str:
    """Normalize format names for comparison"""
    format_map = {
        'BC5_UNORM': 'BC5/ATI2',
        'BC3_UNORM': 'BC3/DXT5',
        'BC2_UNORM': 'BC2/DXT3',
        'BC1_UNORM': 'BC1/DXT1',
        'B8G8R8A8_UNORM': 'BGRA',
        'B8G8R8X8_UNORM': 'BGR',
        'B8G8R8_UNORM': 'BGR'
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
    """Check if a format has an alpha channel"""
    # Handle TGA formats directly
    if format_str == 'TGA_RGBA':
        return True
    if format_str in ('TGA_RGB', 'TGA'):
        return False
    normalized = _normalize_format(format_str)
    return normalized in ['BC3/DXT5', 'BC2/DXT3', 'BGRA']


def _is_texture_atlas(file_path: Path) -> bool:
    """Detect if a file is likely a texture atlas"""
    if 'atlas' in file_path.stem.lower():
        return True
    path_parts = [p.lower() for p in file_path.parts]
    if 'atl' in path_parts:
        return True
    return False


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


def _process_texture_static(input_path: Path, output_path: Path, settings: dict) -> bool:
    """Process a single texture file using texconv."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get dimensions, format, and mipmap count
        dimensions, format_name, mipmap_count = parse_dds_header_extended(input_path)
        if not dimensions:
            # Try TGA or other format
            # For TGA, we can't parse the header directly, so we'll let texconv handle it
            if input_path.suffix.lower() == '.tga':
                # TGA files are always treated as uncompressed, proceed with conversion
                dimensions = (0, 0)  # Will be determined by texconv
                format_name = "TGA"
                mipmap_count = 1
            else:
                return False

        orig_width, orig_height = dimensions

        # For TGA, we need to query texdiag for dimensions
        if format_name == "TGA":
            try:
                result = subprocess.run(
                    [TEXDIAG_EXE, "info", str(input_path)],
                    capture_output=True, text=True, timeout=30
                )
                width_match = re.search(r'width\s*=\s*(\d+)', result.stdout)
                height_match = re.search(r'height\s*=\s*(\d+)', result.stdout)
                if width_match and height_match:
                    orig_width = int(width_match.group(1))
                    orig_height = int(height_match.group(1))
            except Exception:
                pass

        new_width, new_height = _calculate_new_dimensions(orig_width, orig_height, settings, input_path)

        # Check for passthrough (well-compressed textures)
        if settings.get('allow_well_compressed_passthrough', True):
            will_resize = (new_width != orig_width) or (new_height != orig_height)

            if not will_resize and _is_well_compressed(format_name, mipmap_count, orig_width, orig_height):
                # Just copy the file
                shutil.copy2(input_path, output_path)
                return True

        # Determine target format
        target_format = settings.get('target_format', 'BC1/DXT1')

        # Check if source has alpha - if so and target doesn't support alpha, use BC3
        has_alpha = _has_alpha_channel(format_name)
        if has_alpha and target_format in NO_ALPHA_FORMATS:
            # Preserve alpha by using BC3 instead
            target_format = 'BC3/DXT5'

        # Small texture override
        if settings.get('use_small_texture_override', True):
            is_already_compressed = _normalize_format(format_name) in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']

            if not is_already_compressed:
                min_dim = min(new_width, new_height)
                threshold = settings.get('small_texture_threshold', 128)
                if threshold > 0 and min_dim <= threshold:
                    target_format = "BGRA" if has_alpha else "BGR"

        texconv_format = REGULAR_FORMAT_MAP.get(target_format, "BC1_UNORM")

        # Build texconv command
        cmd = [
            TEXCONV_EXE,
            "-f", texconv_format,
            "-m", "0",  # Generate all mipmaps
            "-dx9"
        ]

        # Alpha handling
        if has_alpha:
            cmd.append("-alpha")

        # Compression options
        if target_format in ["BC1/DXT1", "BC2/DXT3", "BC3/DXT5"]:
            bc_options = ""
            if settings.get('uniform_weighting', False):
                bc_options += "u"
            if settings.get('use_dithering', False):
                bc_options += "d"
            if bc_options:
                cmd.extend(["-bc", bc_options])

        # Resize if needed
        if new_width != orig_width or new_height != orig_height:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])

            resize_method = str(settings.get('resize_method', 'CUBIC')).split()[0]
            if resize_method in FILTER_MAP:
                cmd.extend(["-if", FILTER_MAP[resize_method]])

        # Power-of-2 enforcement
        if settings.get('enforce_power_of_2', True):
            cmd.append("-pow2")

        cmd.extend(["-o", str(output_path.parent), "-y", str(input_path)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            return False

        # Rename output file if needed (texconv outputs with original filename)
        generated_file = output_path.parent / (input_path.stem + ".dds")
        if generated_file != output_path:
            if output_path.exists():
                output_path.unlink()
            if generated_file.exists():
                generated_file.rename(output_path)

        return output_path.exists()

    except Exception:
        return False


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

        success = _process_texture_static(input_file, output_file, settings)

        if success and output_file.exists():
            result.success = True
            result.output_size = output_file.stat().st_size
            new_dims, new_fmt = parse_dds_header(output_file)
            result.new_dims = new_dims
            result.new_format = new_fmt
        else:
            result.error_msg = "Processing failed or output missing"

    except Exception as e:
        result.error_msg = str(e)

    return result


def _analyze_file_worker(args):
    """Worker function for parallel analysis."""
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
        # Get dimensions, format, and mipmap count
        if input_file.suffix.lower() == '.tga':
            # TGA files - use fast header parser (no subprocess needed)
            # TGA is always uncompressed with no mipmaps
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

        # Check for alpha
        result.has_alpha = _has_alpha_channel(result.format)

        # Calculate new dimensions
        is_atlas = _is_texture_atlas(input_file)
        new_width, new_height = _calculate_new_dimensions(
            result.width, result.height, settings, is_atlas=is_atlas
        )
        result.new_width = new_width
        result.new_height = new_height

        will_resize = (new_width != result.width) or (new_height != result.height)

        # Check for passthrough
        if settings.get('allow_well_compressed_passthrough', True) and not will_resize:
            if _is_well_compressed(result.format, result.mipmap_count, result.width, result.height):
                result.is_passthrough = True
                result.target_format = result.format
                result.warnings.append("Well-compressed passthrough - file will be copied as-is")
                result.projected_size = file_size
                return result

        # Determine target format
        target_format = settings.get('target_format', 'BC1/DXT1')

        # Handle alpha
        if result.has_alpha and target_format in NO_ALPHA_FORMATS:
            target_format = 'BC3/DXT5'
            result.warnings.append(f"Source has alpha - using {target_format} instead")

        # Small texture override
        if settings.get('use_small_texture_override', True):
            is_already_compressed = result.format in ['BC1/DXT1', 'BC2/DXT3', 'BC3/DXT5']

            if not is_already_compressed:
                min_dim = min(new_width, new_height)
                threshold = settings.get('small_texture_threshold', 128)
                if threshold > 0 and min_dim <= threshold:
                    target_format = "BGRA" if result.has_alpha else "BGR"
                    result.warnings.append(f"Small texture override - using uncompressed {target_format}")

        result.target_format = target_format

        # Check for missing mipmaps warning
        if result.mipmap_count == 1 and max(result.width, result.height) > 4:
            result.warnings.append("Missing mipmaps - will regenerate full mipmap chain")

        # Estimate output size
        num_pixels = new_width * new_height * 1.33  # Mipmap overhead
        bpp_map = {
            "BC1/DXT1": 4,
            "BC2/DXT3": 8,
            "BC3/DXT5": 8,
            "BGRA": 32,
            "BGR": 24
        }
        bpp = bpp_map.get(target_format, 8)
        result.projected_size = int((num_pixels * bpp) / 8) + 128  # 128 for header

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

    def find_textures(self, input_dir: Path) -> List[Path]:
        """
        Find all regular texture files in directory.

        - Includes: .dds, .tga files
        - Excludes: Files ending in _n.dds, _nh.dds (normal maps)
        - Applies: Path whitelist (Textures) and blacklist (icon, icons, bookart)
        """
        # Find DDS files
        dds_files = self.scanner.find_with_suffix_filter(
            input_dir,
            "*.dds",
            exclude_suffixes=["_n", "_nh"]
        )

        # Find TGA files if enabled
        tga_files = []
        if hasattr(self.settings, 'enable_tga_support') and self.settings.enable_tga_support:
            tga_files = self.scanner.find_with_suffix_filter(
                input_dir,
                "*.tga",
                exclude_suffixes=["_n", "_nh"]
            )

        return dds_files + tga_files

    def analyze_files(self, input_dir: Path,
                     progress_callback: Optional[Callable[[int, int], None]] = None) -> List[AnalysisResult]:
        """Analyze all textures and return analysis results."""
        all_files = self.find_textures(input_dir)

        if not all_files:
            return []

        settings_dict = self.settings.to_dict()

        # Store settings hash
        import json
        self._settings_hash = hash(json.dumps(settings_dict, sort_keys=True))

        # Sequential analysis (fast parser makes this efficient)
        results = []
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
