"""
Core logic for OpenMW Normal Map Optimizer.
Handles file processing, analysis, and conversion independently of UI.
"""

from pathlib import Path
import subprocess
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable
import sys


# Get the directory where the script is located
SCRIPT_DIR = Path(__file__).parent if hasattr(sys, 'frozen') else Path(__file__).parent
TEXDIAG_EXE = str(SCRIPT_DIR / "texdiag.exe")
TEXCONV_EXE = str(SCRIPT_DIR / "texconv.exe")


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
            'resize_method': self.resize_method
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


# Static helper functions for multiprocessing workers
def _get_dimensions_static(input_dds: Path) -> Optional[Tuple[int, int]]:
    """Get dimensions from DDS file. Returns (width, height) or None"""
    try:
        result = subprocess.run(
            [TEXDIAG_EXE, "info", str(input_dds)],
            capture_output=True, text=True, timeout=30
        )

        width_match = re.search(r'width\s*=\s*(\d+)', result.stdout)
        height_match = re.search(r'height\s*=\s*(\d+)', result.stdout)

        if width_match and height_match:
            return int(width_match.group(1)), int(height_match.group(1))
    except Exception:
        pass

    return None


def _get_format_static(input_dds: Path) -> str:
    """Get format from DDS file. Returns format string or 'UNKNOWN'"""
    try:
        result = subprocess.run(
            [TEXDIAG_EXE, "info", str(input_dds)],
            capture_output=True, text=True, timeout=30
        )

        format_match = re.search(r'format\s*=\s*(\S+)', result.stdout)
        if format_match:
            return format_match.group(1)
    except Exception:
        pass

    return "UNKNOWN"


def _calculate_new_dimensions_static(orig_width: int, orig_height: int, settings: dict) -> Tuple[int, int]:
    """Calculate new dimensions based on scale factor and constraints"""
    new_width, new_height = orig_width, orig_height

    scale = settings['scale_factor']
    if scale != 1.0:
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)

    max_res = settings['max_resolution']
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

        dimensions = _get_dimensions_static(input_dds)
        if not dimensions:
            return False

        orig_width, orig_height = dimensions
        new_width, new_height = _calculate_new_dimensions_static(orig_width, orig_height, settings)

        # Determine target format
        target_format = settings['nh_format'] if is_nh else settings['n_format']

        if settings['use_small_texture_override']:
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
    dds_file_path, source_dir_path, output_dir_path, is_nh, settings = args

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
        orig_dims = _get_dimensions_static(dds_file)
        orig_format = _get_format_static(dds_file)
        result.orig_dims = orig_dims
        result.orig_format = orig_format

        if not orig_dims:
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
        dimensions = _get_dimensions_static(dds_file)
        format_name = _get_format_static(dds_file)

        if not dimensions:
            result.error = "Could not determine dimensions"
            return result

        width, height = dimensions
        result.width = width
        result.height = height
        result.format = format_name

        new_width, new_height = _calculate_new_dimensions_static(width, height, settings)
        result.new_width = new_width
        result.new_height = new_height

        # Determine target format
        target_format = settings['nh_format'] if is_nh else settings['n_format']

        if settings['use_small_texture_override']:
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

    def find_normal_maps(self, input_dir: Path) -> Tuple[List[Path], List[Path]]:
        """Find all normal map files in directory. Returns (n_files, nh_files)"""
        all_dds = list(input_dir.rglob("*.dds"))
        nh_files = [f for f in all_dds if f.stem.lower().endswith('_nh')]
        n_files = [f for f in all_dds if f.stem.lower().endswith('_n') and not f.stem.lower().endswith('_nh')]
        return n_files, nh_files

    def analyze_files(self, input_dir: Path, progress_callback: Optional[Callable[[int, int], None]] = None) -> List[AnalysisResult]:
        """Analyze all normal maps and return analysis results"""
        n_files, nh_files = self.find_normal_maps(input_dir)
        all_files = n_files + nh_files

        if not all_files:
            return []

        settings_dict = self.settings.to_dict()

        if self.settings.enable_parallel and len(all_files) > 1:
            results = self._analyze_files_parallel(all_files, input_dir, settings_dict, progress_callback)
        else:
            results = self._analyze_files_sequential(all_files, input_dir, settings_dict, progress_callback)

        return results

    def process_files(self, input_dir: Path, output_dir: Path,
                     progress_callback: Optional[Callable[[int, int, ProcessingResult], None]] = None) -> List[ProcessingResult]:
        """Process all normal maps and return results"""
        n_files, nh_files = self.find_normal_maps(input_dir)
        total_files = len(n_files) + len(nh_files)

        if total_files == 0:
            return []

        settings_dict = self.settings.to_dict()

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
            all_tasks.append((str(f), str(source_dir), str(output_dir), False, settings))
        for f in nh_files:
            all_tasks.append((str(f), str(source_dir), str(output_dir), True, settings))

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
            args = (str(f), str(source_dir), str(output_dir), False, settings)
            result = _process_file_worker(args)
            results.append(result)
            if progress_callback:
                progress_callback(current, total, result)

        for f in nh_files:
            current += 1
            args = (str(f), str(source_dir), str(output_dir), True, settings)
            result = _process_file_worker(args)
            results.append(result)
            if progress_callback:
                progress_callback(current, total, result)

        return results


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
