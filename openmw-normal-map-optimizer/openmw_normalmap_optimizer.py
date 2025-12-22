from pathlib import Path
import subprocess
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import webbrowser
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import os
import sys
import time


# Get the directory where the script is located
SCRIPT_DIR = Path(__file__).parent if hasattr(sys, 'frozen') else Path(__file__).parent
TEXDIAG_EXE = str(SCRIPT_DIR / "texdiag.exe")
TEXCONV_EXE = str(SCRIPT_DIR / "texconv.exe")


# Top-level worker function for ProcessPoolExecutor (must be picklable)
def _process_file_worker(args):
    """
    Worker function for parallel processing. Must be at module level for pickling.

    Args:
        args: Tuple of (dds_file_path, source_dir_path, output_dir_path, is_nh, settings_dict)

    Returns:
        dict: Processing result with keys: success, relative_path, input_size, output_size,
              orig_dims, new_dims, orig_format, new_format, error_msg
    """
    dds_file_path, source_dir_path, output_dir_path, is_nh, settings = args

    dds_file = Path(dds_file_path)
    source_dir = Path(source_dir_path)
    output_dir = Path(output_dir_path)

    relative_path = dds_file.relative_to(source_dir)
    output_file = output_dir / relative_path

    result = {
        'success': False,
        'relative_path': str(relative_path),
        'input_size': dds_file.stat().st_size,
        'output_size': 0,
        'orig_dims': None,
        'new_dims': None,
        'orig_format': 'UNKNOWN',
        'new_format': 'UNKNOWN',
        'error_msg': None
    }

    try:
        # Get original dimensions and format
        orig_dims = _get_dimensions_static(dds_file)
        orig_format = _get_format_static(dds_file)
        result['orig_dims'] = orig_dims
        result['orig_format'] = orig_format

        if not orig_dims:
            result['error_msg'] = "Could not determine dimensions"
            return result

        # Process the file
        success = _process_normal_map_static(dds_file, output_file, is_nh, settings)

        if success and output_file.exists():
            result['success'] = True
            result['output_size'] = output_file.stat().st_size
            result['new_dims'] = _get_dimensions_static(output_file)
            result['new_format'] = _get_format_static(output_file)
        else:
            result['error_msg'] = "Processing failed or output missing"

    except Exception as e:
        result['error_msg'] = str(e)

    return result


def _get_dimensions_static(input_dds: Path):
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


def _get_format_static(input_dds: Path):
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


def _process_normal_map_static(input_dds: Path, output_dds: Path, is_nh: bool, settings: dict) -> bool:
    """
    Process a single normal map file using texconv's built-in features.
    Static version for multiprocessing.
    """
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

    try:
        output_dds.parent.mkdir(parents=True, exist_ok=True)

        # Get dimensions and calculate resize
        dimensions = _get_dimensions_static(input_dds)
        if not dimensions:
            return False

        orig_width, orig_height = dimensions

        # Calculate new dimensions (from settings)
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

        # Determine target format (with small texture override)
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
            "-m", "0",  # Generate mipmaps
            "-alpha",   # Linear alpha
            "-dx9"      # DX9 compatibility
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

        # Execute texconv
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


def _create_file_chunks(files_with_sizes, chunk_size_bytes):
    """
    Create chunks of files based on total size.

    Args:
        files_with_sizes: List of tuples (file_path, file_size)
        chunk_size_bytes: Target chunk size in bytes

    Returns:
        List of chunks, where each chunk is a list of file paths
    """
    chunks = []
    current_chunk = []
    current_size = 0

    for file_path, file_size in files_with_sizes:
        # If adding this file would exceed chunk size and we have files, start new chunk
        if current_size + file_size > chunk_size_bytes and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(file_path)
        current_size += file_size

    # Add remaining files
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _analyze_file_worker(args):
    """
    Worker function for parallel analysis. Must be at module level for pickling.

    Args:
        args: Tuple of (dds_file_path, source_dir_path, settings_dict)

    Returns:
        dict: Analysis result with file info
    """
    dds_file_path, source_dir_path, settings = args

    dds_file = Path(dds_file_path)
    source_dir = Path(source_dir_path)
    relative_path = dds_file.relative_to(source_dir)
    file_size = dds_file.stat().st_size
    is_nh = dds_file.stem.lower().endswith('_nh')

    result = {
        'relative_path': str(relative_path),
        'file_size': file_size,
        'is_nh': is_nh,
        'width': None,
        'height': None,
        'format': 'UNKNOWN',
        'new_width': None,
        'new_height': None,
        'target_format': None,
        'projected_size': 0,
        'error': None
    }

    try:
        # Get file info
        dimensions = _get_dimensions_static(dds_file)
        format_name = _get_format_static(dds_file)

        if not dimensions:
            result['error'] = "Could not determine dimensions"
            return result

        width, height = dimensions
        result['width'] = width
        result['height'] = height
        result['format'] = format_name

        # Calculate new dimensions
        new_width, new_height = width, height

        scale = settings['scale_factor']
        if scale != 1.0:
            new_width = int(width * scale)
            new_height = int(height * scale)

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

        result['new_width'] = new_width
        result['new_height'] = new_height

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

        result['target_format'] = target_format

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
        result['projected_size'] = total_bytes + 128

    except Exception as e:
        result['error'] = str(e)

    return result


class NormalMapProcessorGUI:
    # Constants
    WINDOW_WIDTH = 850
    WINDOW_HEIGHT = 1200
    WRAPLENGTH = 700

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

    def __init__(self, root):
        self.root = root
        self.root.title("Normal Map Processor")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # Variables
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.n_format = tk.StringVar(value="BC5/ATI2")
        self.nh_format = tk.StringVar(value="BC3/DXT5")
        self.resize_method = tk.StringVar(value="CUBIC (Recommended - smooth surfaces + detail)")
        self.scale_factor = tk.DoubleVar(value=1.0)
        self.max_resolution = tk.IntVar(value=2048)
        self.min_resolution = tk.IntVar(value=256)
        self.invert_y = tk.BooleanVar(value=False)
        self.reconstruct_z = tk.BooleanVar(value=True)
        self.uniform_weighting = tk.BooleanVar(value=True)
        self.use_dithering = tk.BooleanVar(value=False)

        # Small texture handling
        self.use_small_texture_override = tk.BooleanVar(value=True)
        self.small_nh_threshold = tk.IntVar(value=256)  # _NH textures <= this use BGRA
        self.small_n_threshold = tk.IntVar(value=128)   # _N textures <= this use BGR

        # Parallel processing settings
        self.enable_parallel = tk.BooleanVar(value=True)
        self.max_workers = tk.IntVar(value=max(1, cpu_count() - 1))
        self.chunk_size_mb = tk.IntVar(value=75)  # MB total per chunk

        self.processing = False
        self.total_input_size = 0
        self.total_output_size = 0

        self.create_widgets()

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_help = ttk.Frame(notebook)
        tab_settings = ttk.Frame(notebook)
        tab_process = ttk.Frame(notebook)
        tab_version = ttk.Frame(notebook)

        notebook.add(tab_help, text="📖 READ THIS FIRST - Help & Documentation")
        notebook.add(tab_settings, text="⚙️ Settings")
        notebook.add(tab_process, text="▶️ Process Files")
        notebook.add(tab_version, text="📋 Version Info")

        self._create_help_tab(tab_help)
        self._create_settings_tab(tab_settings)
        self._create_process_tab(tab_process)
        self._create_version_tab(tab_version)

    def _create_help_tab(self, tab_help):
        """Create the help/documentation tab with scrollable content"""
        # Create main container
        main_container = ttk.Frame(tab_help)
        main_container.pack(fill="both", expand=True)

        canvas_help = tk.Canvas(main_container, highlightthickness=0)
        scrollbar_help = ttk.Scrollbar(main_container, orient="vertical", command=canvas_help.yview)
        scrollable_help = ttk.Frame(canvas_help)

        scrollable_help.bind(
            "<Configure>",
            lambda e: canvas_help.configure(scrollregion=canvas_help.bbox("all"))
        )

        canvas_help.create_window((0, 0), window=scrollable_help, anchor="nw")
        canvas_help.configure(yscrollcommand=scrollbar_help.set)

        canvas_help.pack(side="left", fill="both", expand=True)
        scrollbar_help.pack(side="right", fill="y")

        # Add scroll indicator at bottom
        scroll_hint = ttk.Label(tab_help, text="⬇ Scroll down for more options ⬇",
                               font=("", 9, "bold"), foreground="blue",
                               background="#f0f0f0", anchor="center")
        scroll_hint.pack(side="bottom", fill="x", pady=2)

        # Bind mousewheel scrolling
        def _on_mousewheel(event):
            canvas_help.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas_help.bind_all("<MouseWheel>", _on_mousewheel)

        # About section
        frame_info = ttk.LabelFrame(scrollable_help, text="About", padding=10)
        frame_info.pack(fill="x", padx=10, pady=5)

        info_text = (
            "OpenMW Normal Map Optimizer\n\n"
            "This tool optimizes, fixes, and compresses normal maps for OpenMW.\n\n"
            "If any of the text below doesn't make sense to you and you just want the game to run\n"
            "better, just use my default settings. On the Settings tab, the only thing\n"
            "I'd vary is setting Scale Factor from 1.0 to 0.5 if you want extra performance.\n\n"
            "⚠ ALWAYS DO A DRY RUN.\n\n"
            "IMPORTANT ASSUMPTIONS:\n"
            "1. Your normal maps use DirectX-style (G=Y-), Not OpenGL-style (G=Y+).\n"
            "   I cannot auto-detect inverted Y - use the checkbox if needed.\n\n"
            "2. You have UNCOMPRESSED normal maps. This tool is designed to compress\n"
            "   uncompressed textures.\n\n"
            "   Already using BC3/BC1? The main thing to avoid is accidentally converting\n"
            "   to larger formats when NOT resizing:\n"
            "   • BC3 → BGRA: 4x larger files with no quality improvement\n"
            "   • BC3 → BC5: Same file size, but artifacts remain (no benefit)\n"
            "   • BC3 → BC3: Surprisingly pretty harmless! \"double compression\" produces\n"
            "     nearly identical results (e.g. PSNR ~64 dB, MSE ~0.03)\n\n"
            "   Why does the tool reprocess BC3/BC1 files? It fixes technical issues:\n"
            "   • Regenerates mipmap chains (textures may have bad/missing mipmaps)\n"
            "   • Reconstructs Z channels (this is sometimes missing)\n\n"
            "   Valid reasons to process already-compressed textures:\n"
            "   • Resizing (downscaling/upscaling) - the main use case\n"
            "   • Fixing broken mipmaps or Z channels - surprisingly common\n\n"
            "   Want to restore quality from heavily compressed BC3/BC1? You can't \"upgrade\"\n"
            "   compressed textures by converting formats. Instead:\n"
            "   1. Use chaiNNer with artifact removal models to restore detail\n"
            "   2. Then use this tool to recompress to your preferred format\n\n"
            "   Note for regular users: These are edge cases mostly relevant to mod authors.\n"
            "   If you just want vastly better performance with very little quality loss,\n"
            "   the default settings will work fine.\n\n"
            "   Still unsure? Use \"Dry Run\" to see what will happen before processing.\n"
            "   It has a file by file breakdown and statistics at the bottom.\n\n"
            "3. Compression and downsampling are LOSSY (you lose information). However,\n"
            "   75-95% space savings is nearly always worth it.\n\n"
            "4. Z-channel reconstruction: Many normal map generators output 2-channel\n"
            "   (RG only) maps, expecting BC5/ATI2 or R8G8 formats. OpenMW will ONLY\n"
            "   compute Z on-the-fly for BC5/ATI2 and R8G8 formats. For all other\n"
            "   formats (BC3/DXT5, BC1/DXT1, BGRA, BGR), you MUST have Z pre-computed\n"
            "   in the file. This tool can reconstruct Z = sqrt(1 - X² - Y²) for those\n"
            "   formats that need RGB stored explicitly (enabled by default, toggle in\n"
            "   settings if you already have Z computed).\n\n"
            "FINAL CAVEAT:\n"
            "This is all my personal opinion and experience. I have compressed a lot of\n"
            "normal maps for a variety of games and done probably an unhealthy amount of\n"
            "work with the DDS filetype. You can do whatever you want if it makes sense\n"
            "to you. That's why I left in a bunch of options on the settings page.\n\n"
        )

        info_label = ttk.Label(frame_info, text=info_text, justify="left",
                              font=("", 9), wraplength=self.WRAPLENGTH)
        info_label.pack(anchor="w")

        # Links
        links_frame = ttk.Frame(frame_info)
        links_frame.pack(anchor="w", pady=(5, 0))

        ttk.Label(links_frame, text="Resources:", font=("", 9, "bold")).pack(side="left")

        self._create_link(links_frame, "Normal Map Upscaling Models",
                         "https://openmodeldb.info/collections/c-normal-map-upscaling")
        ttk.Label(links_frame, text="|").pack(side="left", padx=5)
        self._create_link(links_frame, "chaiNNer FAQ", "https://openmodeldb.info/docs/faq")
        ttk.Label(links_frame, text="|").pack(side="left", padx=5)
        self._create_link(links_frame, "DXT Artifact Removal", "https://openmodeldb.info/models/1x-DEDXT")

        # Format Reference
        frame_format_ref = ttk.LabelFrame(scrollable_help, text="Format Reference", padding=10)
        frame_format_ref.pack(fill="x", padx=10, pady=5)

        format_ref_text = (
            "RECOMMENDED:\n"
            "  BC5/ATI2: 8 bpp (16 bytes/block), 2-channel 8-bit each, 2:1 ratio, best for normals\n"
            "  BC3/DXT5: 8 bpp (16 bytes/block), RGB shares 4 bpp (5:6:5), A gets 4 bpp, for normals+height\n\n"
            "IT DEPENDS:\n"
            "  BGRA (8:8:8:8): 32 bpp, uncompressed, for normals+height ≤512x512 or smooth gradients critical\n\n"
            "NOT RECOMMENDED:\n"
            "  BC1/DXT1: 4 bpp (8 bytes/block), RGB shares 4 bpp (5:6:5), 1-bit alpha, visible artifacts\n"
            "  BGR (8:8:8): 24 bpp, uncompressed, no alpha, very large files\n\n"
            "Note: BC3 and BC1 use the same RGB compression (5:6:5 sharing 4 bpp). BC5\n"
            "gives each channel full 4 bpp, making it far superior for normals. This tool\n"
            "can force uniform weighting (enabled by default) for BC3/BC1 instead of the\n"
            "default perceptual weighting (which favors green channel in the 5:6:5 split).\n\n"
            "Why BC3 over BC1? For pure normal maps we only need RG. BC5 vs BGR (3x\n"
            "larger) vs BC1 (0.5x smaller). BGR is much larger without benefit. BC1 is\n"
            "smaller but damages quality significantly. BC5 is the clear winner.\n\n"
            "For RGBA (normals+height), choose BC3 or BGRA. BGRA is 4x larger than BC3.\n"
            "Outside of specific use cases (≤512x512 or critical gradients), take the\n"
            "compression hit and reduce file size. See comparisons below.\n\n"
            "bpp = bits per pixel"
        )

        format_ref_label = ttk.Label(frame_format_ref, text=format_ref_text, justify="left",
                                     font=("Courier New", 8), wraplength=self.WRAPLENGTH)
        format_ref_label.pack(anchor="w")

        bc_link_frame = ttk.Frame(frame_format_ref)
        bc_link_frame.pack(anchor="w", pady=(2, 0))
        self._create_link(bc_link_frame, "Block Compression Technical Details",
                         "https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression",
                         font_size=8)

        # File Size Comparison
        frame_size_comp = ttk.LabelFrame(scrollable_help, text="File Size Comparison (with mipmaps)", padding=10)
        frame_size_comp.pack(fill="x", padx=10, pady=5)

        size_comp_text = (
            "2048x2048:  BGRA=22.4MB  BGR=16.8MB  BC5=5.6MB  BC3=5.6MB  BC1=2.8MB\n"
            "1024x1024:  BGRA=5.6MB   BGR=4.2MB   BC5=1.4MB  BC3=1.4MB  BC1=0.7MB\n\n"
            "⚠ IMPORTANT: Unless you REALLY know what you're doing, your normal maps should NEVER exceed 5.6MB.\n"
            "   Stick to BC5 (2048x2048 max) or BC3 (2048x2048 max) formats. In most cases, go smaller!\n\n"
            "For normal+height (_NH): Choose between:\n"
            "  • 1.0x scale BC3: More fine detail, compressed\n"
            "  • 0.5x scale BGRA: Smoother gradients, uncompressed, same file size as 1.0x BC3"
        )

        size_comp_label = ttk.Label(frame_size_comp, text=size_comp_text, justify="left",
                                    font=("Courier New", 8), wraplength=self.WRAPLENGTH)
        size_comp_label.pack(anchor="w")

    def _create_settings_tab(self, tab_settings):
        """Create the settings tab with all configuration options"""
        # Create main container
        main_container = ttk.Frame(tab_settings)
        main_container.pack(fill="both", expand=True)

        # Create scrollable frame for settings
        canvas_settings = tk.Canvas(main_container, highlightthickness=0)
        scrollbar_settings = ttk.Scrollbar(main_container, orient="vertical", command=canvas_settings.yview)
        scrollable_settings = ttk.Frame(canvas_settings)

        scrollable_settings.bind(
            "<Configure>",
            lambda e: canvas_settings.configure(scrollregion=canvas_settings.bbox("all"))
        )

        canvas_settings.create_window((0, 0), window=scrollable_settings, anchor="nw")
        canvas_settings.configure(yscrollcommand=scrollbar_settings.set)

        canvas_settings.pack(side="left", fill="both", expand=True)
        scrollbar_settings.pack(side="right", fill="y")

        # Add scroll indicator at bottom
        scroll_hint = ttk.Label(tab_settings, text="⬇ Scroll down for more options ⬇",
                               font=("", 9, "bold"), foreground="blue",
                               background="#f0f0f0", anchor="center")
        scroll_hint.pack(side="bottom", fill="x", pady=2)

        # Bind mousewheel scrolling
        def _on_mousewheel(event):
            canvas_settings.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas_settings.bind_all("<MouseWheel>", _on_mousewheel)

        # Directory Info
        frame_dir_info = ttk.LabelFrame(scrollable_settings, text="⚠ Important: Directory Structure", padding=10)
        frame_dir_info.pack(fill="x", padx=10, pady=5)

        dir_info_text = (
            "• Input and Output directories MUST be different folders\n"
            "• Nested directory structures are preserved in the output\n"
            "  Example:\n"
            "    Input:  mymod_input/\n"
            "    Output: mymod_output/\n"
            "    mymod_input/textures/weapons/sword_n.dds → mymod_output/textures/weapons/sword_n.dds"
        )
        ttk.Label(frame_dir_info, text=dir_info_text, justify="left",
                 font=("", 8), wraplength=self.WRAPLENGTH).pack(anchor="w")

        # Input Directory
        frame_input = ttk.LabelFrame(scrollable_settings, text="Input Directory", padding=10)
        frame_input.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_input, textvariable=self.input_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_input, text="Browse...", command=self.browse_input).pack(side="left")

        # Output Directory
        frame_output = ttk.LabelFrame(scrollable_settings, text="Output Directory", padding=10)
        frame_output.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_output, textvariable=self.output_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_output, text="Browse...", command=self.browse_output).pack(side="left")

        # Format Options
        frame_formats = ttk.LabelFrame(scrollable_settings, text="Format Options", padding=10)
        frame_formats.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_formats, text="_N.dds format:").grid(row=0, column=0, sticky="w", pady=5)
        n_combo = ttk.Combobox(frame_formats, textvariable=self.n_format,
                               values=["BC5/ATI2", "BC1/DXT1", "BGRA", "BGR"], state="readonly", width=20)
        n_combo.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_formats, text="(Recommended: BC5/ATI2 - RG only)",
                 font=("", 8, "italic")).grid(row=0, column=2, sticky="w")

        ttk.Label(frame_formats, text="_NH.dds format (RGBA):").grid(row=2, column=0, sticky="w", pady=5)
        nh_combo = ttk.Combobox(frame_formats, textvariable=self.nh_format,
                                values=["BC3/DXT5", "BGRA"], state="readonly", width=20)
        nh_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_formats, text="(Recommended: BC3/DXT5 (mostly) Read the Documentation Section.)",
                 font=("", 8, "italic")).grid(row=2, column=2, sticky="w")

        # Resize Options
        frame_resize = ttk.LabelFrame(scrollable_settings, text="Resize Options", padding=10)
        frame_resize.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_resize, text="Resize Method:").grid(row=0, column=0, sticky="w", pady=5)
        resize_combo = ttk.Combobox(frame_resize, textvariable=self.resize_method,
                                    values=[
                                        "CUBIC (Recommended - smooth surfaces + detail)",
                                        "FANT (Detail preservation - similar to Lanczos)",
                                        "BOX (Blurry, good for gradients)",
                                        "LINEAR (Fast, general purpose)"
                                    ], state="readonly", width=45)
        resize_combo.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(frame_resize, text="Scale Factor:").grid(row=1, column=0, sticky="w", pady=5)
        scale_combo = ttk.Combobox(frame_resize, textvariable=self.scale_factor,
                                   values=[0.125, 0.25, 0.5, 1.0], state="readonly", width=20)
        scale_combo.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(1.0 = no resizing unless max set)",
                 font=("", 8, "italic")).grid(row=1, column=2, sticky="w")

        ttk.Label(frame_resize, text="Max Resolution:").grid(row=2, column=0, sticky="w", pady=5)
        max_res_combo = ttk.Combobox(frame_resize, textvariable=self.max_resolution,
                                     values=[0, 128, 256, 512, 1024, 2048, 4096, 8192],
                                     state="readonly", width=20)
        max_res_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(0 = no limit; Downsamples textures above threshold EVEN at 1.0 scale)",
                 font=("", 8, "italic")).grid(row=2, column=2, sticky="w", columnspan=2)
        ttk.Label(frame_resize, text="Recommended: 2048 unless you know what you're doing",
                 font=("", 8, "italic")).grid(row=3, column=2, sticky="w", padx=(0, 0), columnspan=2)

        ttk.Label(frame_resize, text="Min Resolution:").grid(row=4, column=0, sticky="w", pady=5)
        min_res_combo = ttk.Combobox(frame_resize, textvariable=self.min_resolution,
                                     values=[0, 128, 256, 512, 1024, 2048, 4096, 8192],
                                     state="readonly", width=20)
        min_res_combo.grid(row=4, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(0 = no limit; Only applies when scale < 1.0, prevents downsampling below this)",
                 font=("", 8, "italic")).grid(row=4, column=2, sticky="w", columnspan=2)
        ttk.Label(frame_resize, text="Recommended: 256 for downsampling",
                 font=("", 8, "italic")).grid(row=5, column=2, sticky="w", padx=(0, 0), columnspan=2)

        # Normal Map Options
        frame_normal_opts = ttk.LabelFrame(scrollable_settings, text="Normal Map Options", padding=10)
        frame_normal_opts.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_normal_opts, text="Convert OpenGL to DirectX (Invert Y channel)",
                       variable=self.invert_y).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(frame_normal_opts,
                 text="Note: OpenMW expects DirectX-style normal maps (Y-). Use this if your source uses OpenGL convention (Y+).",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Checkbutton(frame_normal_opts, text="Reconstruct Z channel from X/Y (recommended)",
                       variable=self.reconstruct_z).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(frame_normal_opts,
                 text="⚠ Only disable if you KNOW your maps have correct Z data, and you don't want to recalculate it based on\npotentially lossy input R and G (e.g. converting BC3 to half-sized BC3). BC5 always skips Z.",
                 font=("", 8), wraplength=600, justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Checkbutton(frame_normal_opts, text="Use uniform weighting for BC1/BC3 (recommended)",
                       variable=self.uniform_weighting).grid(row=4, column=0, sticky="w", pady=2)
        ttk.Label(frame_normal_opts,
                 text="Normal maps store geometric data, not perceptual color. Uniform weighting gives equal precision to RGB.\nOnly applies to BC1/DXT1 and BC3/DXT5 formats.",
                 font=("", 8), wraplength=600, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Checkbutton(frame_normal_opts, text="Use dithering for BC1/BC3 (NOT recommended)",
                       variable=self.use_dithering).grid(row=6, column=0, sticky="w", pady=2)
        ttk.Label(frame_normal_opts,
                 text="⚠ Dithering adds noise which corrupts normal vectors and causes lighting artifacts.\nOnly applies to BC1/DXT1 and BC3/DXT5 formats.",
                 font=("", 8), wraplength=600, justify="left").grid(row=7, column=0, columnspan=2, sticky="w", pady=2)

        # Small Texture Handling
        frame_small_tex = ttk.LabelFrame(scrollable_settings, text="Small Texture Handling", padding=10)
        frame_small_tex.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_small_tex, text="Override format for small textures (recommended)",
                       variable=self.use_small_texture_override).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_small_tex,
                 text="Small textures benefit from uncompressed formats. This overrides your format settings for tiny textures.",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_small_tex, text="_NH threshold (BGRA):").grid(row=2, column=0, sticky="w", pady=5, padx=(20, 0))
        nh_threshold_combo = ttk.Combobox(frame_small_tex, textvariable=self.small_nh_threshold,
                                         values=[0, 64, 128, 256, 512], state="readonly", width=15)
        nh_threshold_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_small_tex, text="(Textures ≤ this on any side use BGRA, recommended: 256)",
                 font=("", 8, "italic")).grid(row=2, column=2, sticky="w")

        ttk.Label(frame_small_tex, text="_N threshold (BGR):").grid(row=3, column=0, sticky="w", pady=5, padx=(20, 0))
        n_threshold_combo = ttk.Combobox(frame_small_tex, textvariable=self.small_n_threshold,
                                        values=[0, 64, 128, 256, 512], state="readonly", width=15)
        n_threshold_combo.grid(row=3, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_small_tex, text="(Textures ≤ this on any side use BGR, recommended: 128)",
                 font=("", 8, "italic")).grid(row=3, column=2, sticky="w")

        ttk.Label(frame_small_tex,
                 text="⚠ Note: Thresholds are checked AFTER resizing. Set to 0 to disable override for that type.",
                 font=("", 8), wraplength=600, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", pady=(5, 2))

        # Parallel Processing Settings
        frame_parallel = ttk.LabelFrame(scrollable_settings, text="Parallel Processing", padding=10)
        frame_parallel.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_parallel, text="Enable parallel processing (recommended for speedy processing.)",
                       variable=self.enable_parallel).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_parallel,
                 text=f"Parallel processing uses multiple CPU cores to process files simultaneously. Detected: {cpu_count()} cores",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_parallel, text="Max workers:").grid(row=2, column=0, sticky="w", pady=5, padx=(20, 0))
        workers_combo = ttk.Combobox(frame_parallel, textvariable=self.max_workers,
                                     values=list(range(1, cpu_count() + 1)), state="readonly", width=15)
        workers_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_parallel, text=f"(CPU cores to use, recommended: {max(1, cpu_count() - 1)})",
                 font=("", 8, "italic")).grid(row=2, column=2, sticky="w")

        ttk.Label(frame_parallel, text="Chunk size (MB):").grid(row=3, column=0, sticky="w", pady=5, padx=(20, 0))
        chunk_combo = ttk.Combobox(frame_parallel, textvariable=self.chunk_size_mb,
                                   values=[25, 50, 75, 100, 150, 200], state="readonly", width=15)
        chunk_combo.grid(row=3, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_parallel, text="(Total filesize per batch, recommended: 50-100MB)",
                 font=("", 8, "italic")).grid(row=3, column=2, sticky="w")

        ttk.Label(frame_parallel,
                 text="⚠ Chunking groups files by total size to balance I/O and CPU usage across workers.\n"
                      "Larger chunks = fewer context switches, but less granular progress.\n"
                      "Smaller chunks = more responsive progress, but more overhead.\n\n"
                      "If your computer becomes unresponsive, lower the CPU cores used or make the chunks smaller.\n"
                      "This is pretty unlikely though. It's worth making 15 minutes of processing take only 15 seconds.",
                 font=("", 8), wraplength=600, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", pady=(5, 2))

    def _create_process_tab(self, tab_process):
        """Create the processing tab with progress log and controls"""
        # Progress Bar
        frame_progress = ttk.LabelFrame(tab_process, text="Progress", padding=10)
        frame_progress.pack(fill="x", padx=10, pady=5)

        self.progress_label = ttk.Label(frame_progress, text="Ready to process", font=("", 9))
        self.progress_label.pack(anchor="w", pady=(0, 5))

        self.progress_bar = ttk.Progressbar(frame_progress, mode="determinate", length=400)
        self.progress_bar.pack(fill="x", pady=(0, 5))

        # Progress/Log
        frame_log = ttk.LabelFrame(tab_process, text="Log", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(frame_log, height=10, width=70, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(frame_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Space Savings Display
        frame_stats = ttk.LabelFrame(tab_process, text="Summary", padding=10)
        frame_stats.pack(fill="x", padx=10, pady=5)
        self.stats_label = ttk.Label(frame_stats, text="No files processed yet", font=("", 10))
        self.stats_label.pack()

        # Buttons
        button_frame = ttk.Frame(tab_process)
        button_frame.pack(pady=10)
        self.analyze_btn = ttk.Button(button_frame, text="Dry Run (Analysis - Run me first!)", command=self.start_analysis)
        self.analyze_btn.pack(side="left", padx=5)
        self.export_btn = ttk.Button(button_frame, text="Export Analysis Report", command=self.export_log, state="disabled")
        self.export_btn.pack(side="left", padx=5)
        self.process_btn = ttk.Button(button_frame, text="Process Files", command=self.start_processing)
        self.process_btn.pack(side="left", padx=5)

    def _create_version_tab(self, tab_version):
        """Create the version history tab"""
        # Create main container
        main_container = ttk.Frame(tab_version)
        main_container.pack(fill="both", expand=True)

        canvas_version = tk.Canvas(main_container, highlightthickness=0)
        scrollbar_version = ttk.Scrollbar(main_container, orient="vertical", command=canvas_version.yview)
        scrollable_version = ttk.Frame(canvas_version)

        scrollable_version.bind(
            "<Configure>",
            lambda e: canvas_version.configure(scrollregion=canvas_version.bbox("all"))
        )

        canvas_version.create_window((0, 0), window=scrollable_version, anchor="nw")
        canvas_version.configure(yscrollcommand=scrollbar_version.set)

        canvas_version.pack(side="left", fill="both", expand=True)
        scrollbar_version.pack(side="right", fill="y")

        # Add scroll indicator at bottom
        scroll_hint = ttk.Label(tab_version, text="⬇ Scroll down for more ⬇",
                               font=("", 9, "bold"), foreground="blue",
                               background="#f0f0f0", anchor="center")
        scroll_hint.pack(side="bottom", fill="x", pady=2)

        # Bind mousewheel scrolling
        def _on_mousewheel(event):
            canvas_version.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas_version.bind_all("<MouseWheel>", _on_mousewheel)

        # Version Info
        frame_version = ttk.LabelFrame(scrollable_version, text="Version Features", padding=10)
        frame_version.pack(fill="x", padx=10, pady=5)

        version_text = (
            "Version 0.3\n"
            "Features:\n"
            "  • Batch processing of normal maps (_N.dds and _NH.dds)\n"
            "  • Format conversion (BC5, BC3/DXT5, BC1/DXT1, BGRA, BGR)\n"
            "  • Resolution scaling and constraints\n"
            "  • Z-channel reconstruction for proper normal mapping\n"
            "  • Y flip normal map conversion\n"
            "  • Smart small texture handling\n"
            "  • Dry run analysis with size projections\n"
            "  • Detailed processing logs and statistics\n"
            "  • Export analysis reports\n"
            "  • Parallel processing (multi-core support for faster batch operations)\n\n"
            "Known Issues:\n"
            "  • The tool allows converting compressed formats to uncompressed formats if\n"
            "    selected. Ideally, compressed inputs without resizing would be copied as-is,\n"
            "    but since Z-channel validity cannot be verified without some dependencies\n"
            "    (numpy/PIL) + overhead, the tool reprocesses all files. This may cause unnecessary\n"
            "    decompression where the output will still look compressed but have a large file size (Very Bad)\n"
            "    or introduce double compression artifacts (Varies from Fine to Very Bad).\n"
            "    The user HAS been warned about this on the document page. Further the dry run does tell them what conversions are occurring.\n"
            "  • Future versions will add (optional) format validation to preserve compressed inputs\n"
            "    when no resizing occurs IF Z-channel reconstruction is not needed or selected.\n"
            "    Should also keep in mind the user may have not generated mipmaps or have created invalid ones.\n"
            "  • Future versions should make some functions more clear.\n"
        )

        version_label = ttk.Label(frame_version, text=version_text, justify="left",
                                  font=("Courier New", 9), wraplength=self.WRAPLENGTH)
        version_label.pack(anchor="w")

    def _create_link(self, parent, text, url, font_size=9):
        """Helper to create clickable hyperlinks"""
        link = ttk.Label(parent, text=text, foreground="blue", cursor="hand2",
                        font=("", font_size, "underline"))
        link.pack(side="left", padx=(5, 0) if font_size == 9 else 0)
        link.bind("<Button-1>", lambda e: webbrowser.open(url))

    def browse_input(self):
        directory = filedialog.askdirectory(title="Select Input Directory")
        if directory:
            self.input_dir.set(directory)

    def browse_output(self):
        directory = filedialog.askdirectory(title="Select Output Directory")
        if directory:
            self.output_dir.set(directory)

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def export_log(self):
        """Export current log content to a text file"""
        log_content = self.log_text.get("1.0", "end-1c")
        if not log_content.strip():
            messagebox.showwarning("Warning", "No log content to export")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save Analysis Report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="normal_map_analysis_report.txt"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                messagebox.showinfo("Success", f"Report exported to:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export report:\n{str(e)}")

    def start_analysis(self):
        if self.processing:
            return

        if not self.input_dir.get():
            messagebox.showerror("Error", "Please select input directory")
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.process_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        threading.Thread(target=self.analyze_files, daemon=True).start()

    def start_processing(self):
        if self.processing:
            return

        if not self.input_dir.get() or not self.output_dir.get():
            messagebox.showerror("Error", "Please select both input and output directories")
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.process_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        self.total_input_size = 0
        self.total_output_size = 0
        self.stats_label.config(text="Processing...")

        threading.Thread(target=self.process_files, daemon=True).start()

    def process_files(self):
        start_time = time.time()
        try:
            source_dir = Path(self.input_dir.get())
            output_dir = Path(self.output_dir.get())

            all_dds = list(source_dir.rglob("*.dds"))
            nh_files = [f for f in all_dds if f.stem.lower().endswith('_nh')]
            n_files = [f for f in all_dds if f.stem.lower().endswith('_n') and not f.stem.lower().endswith('_nh')]

            total_files = len(nh_files) + len(n_files)
            self.log(f"Found {len(nh_files)} _nh.dds file(s)")
            self.log(f"Found {len(n_files)} _n.dds file(s)")
            self.log(f"Total: {total_files} normal map file(s)\n")

            # Initialize progress bar
            self.progress_bar["maximum"] = total_files
            self.progress_bar["value"] = 0

            # Track processing results
            self.processed_count = 0
            self.failed_count = 0

            # Prepare settings dict for worker processes
            settings = {
                'n_format': self.n_format.get(),
                'nh_format': self.nh_format.get(),
                'scale_factor': self.scale_factor.get(),
                'max_resolution': self.max_resolution.get(),
                'min_resolution': self.min_resolution.get(),
                'invert_y': self.invert_y.get(),
                'reconstruct_z': self.reconstruct_z.get(),
                'uniform_weighting': self.uniform_weighting.get(),
                'use_dithering': self.use_dithering.get(),
                'use_small_texture_override': self.use_small_texture_override.get(),
                'small_nh_threshold': self.small_nh_threshold.get(),
                'small_n_threshold': self.small_n_threshold.get(),
                'resize_method': self.resize_method.get()
            }

            # Check if parallel processing is enabled
            if self.enable_parallel.get() and total_files > 1:
                self._process_files_parallel(n_files, nh_files, source_dir, output_dir, settings, total_files)
            else:
                self._process_files_sequential(n_files, nh_files, source_dir, output_dir, total_files)

            self.progress_label.config(text="Processing complete!")

            elapsed_time = time.time() - start_time
            self._display_final_stats(elapsed_time)

        except Exception as e:
            self.log(f"\nError: {str(e)}")
            messagebox.showerror("Error", f"Processing failed: {str(e)}")
        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.process_btn.configure(state="normal")

    def _process_files_parallel(self, n_files, nh_files, source_dir, output_dir, settings, total_files):
        """Process files in parallel using ProcessPoolExecutor"""
        max_workers = self.max_workers.get()
        chunk_size_bytes = self.chunk_size_mb.get() * 1024 * 1024  # Convert MB to bytes

        self.log(f"Using parallel processing: {max_workers} workers, {self.chunk_size_mb.get()}MB chunks\n")

        # Prepare all files with their sizes and metadata
        all_tasks = []
        for f in n_files:
            all_tasks.append((str(f), str(source_dir), str(output_dir), False, settings, f.stat().st_size))
        for f in nh_files:
            all_tasks.append((str(f), str(source_dir), str(output_dir), True, settings, f.stat().st_size))

        # Create chunks based on file size
        files_with_sizes = [(task[0], task[5]) for task in all_tasks]
        chunks = _create_file_chunks(files_with_sizes, chunk_size_bytes)

        self.log(f"Created {len(chunks)} chunks from {total_files} files\n")

        current_file = 0

        # Process chunks in parallel
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {}
            for task in all_tasks:
                # task format: (file_path, source_dir, output_dir, is_nh, settings, file_size)
                # worker needs: (file_path, source_dir, output_dir, is_nh, settings)
                worker_args = task[:5]
                future = executor.submit(_process_file_worker, worker_args)
                future_to_file[future] = task[0]  # Store file path for logging

            # Process results as they complete
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                current_file += 1

                try:
                    result = future.result()
                    self._handle_processing_result(result)

                    # Update progress
                    self.progress_bar["value"] = current_file
                    self.progress_label.config(text=f"Processed {current_file}/{total_files} files")
                    self.root.update_idletasks()

                except Exception as e:
                    self.log(f"✗ Exception processing {Path(file_path).name}: {str(e)}")
                    self.failed_count += 1

    def _process_files_sequential(self, n_files, nh_files, source_dir, output_dir, total_files):
        """Process files sequentially (fallback or single file)"""
        self.log("Using sequential processing\n")
        current_file = 0

        for dds_file in n_files:
            current_file += 1
            self.progress_label.config(text=f"Processing file {current_file} of {total_files}: {dds_file.name}")
            self.progress_bar["value"] = current_file
            self._process_single_file(dds_file, source_dir, output_dir, is_nh=False)

        for dds_file in nh_files:
            current_file += 1
            self.progress_label.config(text=f"Processing file {current_file} of {total_files}: {dds_file.name}")
            self.progress_bar["value"] = current_file
            self._process_single_file(dds_file, source_dir, output_dir, is_nh=True)

    def _handle_processing_result(self, result):
        """Handle a processing result from the worker"""
        self.total_input_size += result['input_size']

        if result['success']:
            self.total_output_size += result['output_size']
            self.processed_count += 1

            # Log detailed info
            if result['orig_dims'] and result['new_dims']:
                orig_w, orig_h = result['orig_dims']
                new_w, new_h = result['new_dims']
                size_change = result['output_size'] - result['input_size']
                size_change_str = f"+{self.format_size(size_change)}" if size_change > 0 else self.format_size(size_change)

                self.log(f"✓ {result['relative_path']}")
                self.log(f"  {orig_w}×{orig_h} {result['orig_format']} → {new_w}×{new_h} {result['new_format']} | "
                        f"{self.format_size(result['input_size'])} → {self.format_size(result['output_size'])} ({size_change_str})")
            else:
                self.log(f"✓ Completed: {result['relative_path']}")
        else:
            self.failed_count += 1
            error_msg = result.get('error_msg', 'Unknown error')
            self.log(f"✗ Failed: {result['relative_path']} - {error_msg}")

    def _process_single_file(self, dds_file, source_dir, output_dir, is_nh):
        """Process a single DDS file"""
        relative_path = dds_file.relative_to(source_dir)
        output_file = output_dir / relative_path
        file_type = "_NH" if is_nh else "_N"

        # Get original dimensions and format info
        dimensions = self._get_dimensions(dds_file)
        orig_format = self._get_format(dds_file)

        input_size = dds_file.stat().st_size
        self.total_input_size += input_size

        if self.process_normal_map(dds_file, output_file, is_nh):
            if output_file.exists():
                output_size = output_file.stat().st_size
                self.total_output_size += output_size

                # Get new dimensions and format
                new_dimensions = self._get_dimensions(output_file)
                new_format = self._get_format(output_file)

                # Log detailed info
                if dimensions and new_dimensions:
                    orig_w, orig_h = dimensions
                    new_w, new_h = new_dimensions
                    size_change = output_size - input_size
                    size_change_str = f"+{self.format_size(size_change)}" if size_change > 0 else self.format_size(size_change)

                    self.log(f"✓ {relative_path}")
                    self.log(f"  {orig_w}×{orig_h} {orig_format} → {new_w}×{new_h} {new_format} | {self.format_size(input_size)} → {self.format_size(output_size)} ({size_change_str})")
                else:
                    self.log(f"✓ Completed: {relative_path}")

                self.processed_count += 1
            else:
                self.log(f"✗ Failed (output missing): {relative_path}")
                self.failed_count += 1
        else:
            self.log(f"✗ Failed: {relative_path}")
            self.failed_count += 1

    def _display_final_stats(self, elapsed_time=None):
        """Calculate and display final processing statistics"""
        total_files = self.processed_count + self.failed_count
        savings = self.total_input_size - self.total_output_size
        savings_percent = (savings / self.total_input_size * 100) if self.total_input_size > 0 else 0

        input_str = self.format_size(self.total_input_size)
        output_str = self.format_size(self.total_output_size)
        savings_str = self.format_size(savings)

        stats_msg = f"Files: {self.processed_count}/{total_files} successful | {input_str} → {output_str} | Saved: {savings_str} ({savings_percent:.1f}%)"
        self.stats_label.config(text=stats_msg)

        self.log("\n=== Processing Complete ===")
        self.log(f"Total files: {total_files}")
        self.log(f"Successful: {self.processed_count}")
        self.log(f"Failed: {self.failed_count}")
        self.log(f"Space savings: {savings_str} ({savings_percent:.1f}%)")

        if elapsed_time is not None:
            time_str = self._format_time(elapsed_time)
            self.log(f"Time taken: {time_str}")
            if total_files > 0:
                avg_time = elapsed_time / total_files
                self.log(f"Average per file: {self._format_time(avg_time)}")

        if self.failed_count > 0:
            messagebox.showwarning("Completed with errors", f"Processing completed with {self.failed_count} failed file(s)\n\n{stats_msg}")
        else:
            messagebox.showinfo("Success", f"Processing completed!\n\n{stats_msg}")

    def analyze_files(self):
        """Analyze normal map files and report statistics with size projection"""
        start_time = time.time()
        try:
            source_dir = Path(self.input_dir.get())

            all_dds = list(source_dir.rglob("*.dds"))
            nh_files = [f for f in all_dds if f.stem.lower().endswith('_nh')]
            n_files = [f for f in all_dds if f.stem.lower().endswith('_n') and not f.stem.lower().endswith('_nh')]

            self.log("=== Dry Run (Preview) ===\n")
            self.log(f"Found {len(nh_files)} _nh.dds file(s)")
            self.log(f"Found {len(n_files)} _n.dds file(s)")
            self.log(f"Total: {len(nh_files) + len(n_files)} normal map file(s)\n")

            if not nh_files and not n_files:
                self.log("No normal map files found!")
                messagebox.showinfo("Dry Run Complete", "No normal map files found")
                return

            total_current_size = 0
            total_projected_size = 0
            format_stats = {}
            all_files = n_files + nh_files

            # Track size warnings
            oversized_textures = []  # > 2048 on any side
            undersized_textures = []  # < 256 on any side

            # Track action categories
            action_groups = {
                'resize_and_reformat': [],
                'resize_only': [],
                'reformat_only': [],
                'no_change': []
            }

            # Prepare settings for workers
            settings = {
                'n_format': self.n_format.get(),
                'nh_format': self.nh_format.get(),
                'scale_factor': self.scale_factor.get(),
                'max_resolution': self.max_resolution.get(),
                'min_resolution': self.min_resolution.get(),
                'use_small_texture_override': self.use_small_texture_override.get(),
                'small_nh_threshold': self.small_nh_threshold.get(),
                'small_n_threshold': self.small_n_threshold.get()
            }

            # Use parallel processing for analysis if enabled
            if self.enable_parallel.get() and len(all_files) > 1:
                self.log(f"Using parallel analysis: {self.max_workers.get()} workers\n")
                results = self._analyze_files_parallel(all_files, source_dir, settings)
            else:
                self.log("Using sequential analysis\n")
                results = self._analyze_files_sequential(all_files, source_dir, settings)

            # Process results
            for i, result in enumerate(results, 1):
                if result['error']:
                    self.log(f"[{i}/{len(all_files)}] Error analyzing {result['relative_path']}: {result['error']}")
                    continue

                relative_path = result['relative_path']
                file_size = result['file_size']
                total_current_size += file_size

                self.log(f"[{i}/{len(all_files)}] Analyzing: {relative_path}")

                width = result['width']
                height = result['height']
                format_name = result['format']
                new_width = result['new_width']
                new_height = result['new_height']
                target_format = result['target_format']
                projected_size = result['projected_size']
                total_projected_size += projected_size

                # Update format stats
                if format_name not in format_stats:
                    format_stats[format_name] = {'count': 0, 'size': 0, 'files': []}
                format_stats[format_name]['count'] += 1
                format_stats[format_name]['size'] += file_size
                format_stats[format_name]['files'].append(str(relative_path))

                # Check for size warnings
                max_dim = max(width, height)
                min_dim = min(width, height)

                if max_dim > 2048:
                    oversized_textures.append((relative_path, width, height))
                if min_dim < 256:
                    undersized_textures.append((relative_path, width, height))

                # Categorize action
                will_resize = (new_width != width) or (new_height != height)
                will_reformat = format_name != target_format

                if will_resize and will_reformat:
                    action_groups['resize_and_reformat'].append((relative_path, width, height, format_name, new_width, new_height, target_format))
                elif will_resize:
                    action_groups['resize_only'].append((relative_path, width, height, format_name, new_width, new_height))
                elif will_reformat:
                    action_groups['reformat_only'].append((relative_path, width, height, format_name, target_format))
                else:
                    action_groups['no_change'].append((relative_path, width, height, format_name))

                self.log(f"  Current: {format_name}, {width}x{height}, {self.format_size(file_size)}")
                self.log(f"  Projected: {target_format}, {new_width}x{new_height}, {self.format_size(projected_size)}")

            self.log("\n=== Current State ===")
            self.log(f"Total size: {self.format_size(total_current_size)}")
            self.log(f"Average size per file: {self.format_size(total_current_size // len(all_files))}")

            self.log("\n=== Format Breakdown ===")
            for format_name, stats in sorted(format_stats.items()):
                self.log(f"{format_name}: {stats['count']} files, {self.format_size(stats['size'])} total")

            # Show action breakdown
            self.log("\n=== Actions to be Taken ===")
            self.log(f"Resize + Reformat: {len(action_groups['resize_and_reformat'])} files")
            if action_groups['resize_and_reformat'] and len(action_groups['resize_and_reformat']) <= 3:
                for path, w, h, fmt, new_w, new_h, new_fmt in action_groups['resize_and_reformat']:
                    self.log(f"  • {path}: {w}×{h} {fmt} → {new_w}×{new_h} {new_fmt}")

            self.log(f"Resize only: {len(action_groups['resize_only'])} files")
            if action_groups['resize_only'] and len(action_groups['resize_only']) <= 3:
                for path, w, h, fmt, new_w, new_h in action_groups['resize_only']:
                    self.log(f"  • {path}: {w}×{h} → {new_w}×{new_h} (keeping {fmt})")

            self.log(f"Reformat only: {len(action_groups['reformat_only'])} files")
            if action_groups['reformat_only'] and len(action_groups['reformat_only']) <= 3:
                for path, w, h, fmt, new_fmt in action_groups['reformat_only']:
                    self.log(f"  • {path}: {fmt} → {new_fmt} (keeping {w}×{h})")

            self.log(f"No change: {len(action_groups['no_change'])} files")
            if action_groups['no_change'] and len(action_groups['no_change']) <= 3:
                for path, w, h, fmt in action_groups['no_change']:
                    self.log(f"  • {path}: {w}×{h} {fmt} (unchanged)")

            # Show projection
            savings = total_current_size - total_projected_size
            savings_percent = (savings / total_current_size * 100) if total_current_size > 0 else 0

            self.log("\n=== Projected Output (with current settings) ===")
            self.log(f"Projected total size: {self.format_size(total_projected_size)}")
            self.log(f"Estimated savings: {self.format_size(savings)} ({savings_percent:.1f}%)")

            # Display warnings
            if oversized_textures or undersized_textures:
                self.log("\n=== ⚠ WARNINGS ===")

            if oversized_textures:
                self.log(f"\n⚠ Found {len(oversized_textures)} texture(s) larger than 2048 on any side:")
                for path, w, h in oversized_textures[:5]:  # Show first 5
                    self.log(f"  • {path} ({w}x{h})")
                if len(oversized_textures) > 5:
                    self.log(f"  ... and {len(oversized_textures) - 5} more")
                self.log("\nRECOMMENDATION: Use the 'Max Resolution' setting to limit texture size to 2048,")
                self.log("unless these are texture atlases (which should be kept at their original size).")

            if undersized_textures:
                self.log(f"\n⚠ Found {len(undersized_textures)} texture(s) smaller than 256 on any side:")
                for path, w, h in undersized_textures[:5]:  # Show first 5
                    self.log(f"  • {path} ({w}x{h})")
                if len(undersized_textures) > 5:
                    self.log(f"  ... and {len(undersized_textures) - 5} more")
                self.log("\nRECOMMENDATION: Set 'Min Resolution' to 256 if you plan to resize.")
                self.log("It is NOT recommended to resize textures smaller than 256x256.")
                self.log("")
                self.log("However, don't worry about accidentally compressing small textures!")
                self.log("By default, this tool automatically saves:")
                self.log("  • _NH textures ≤256 on any side → BGRA (uncompressed)")
                self.log("  • _N textures ≤128 on any side → BGR (uncompressed)")
                self.log("This can be adjusted in Settings → Small Texture Handling.")

            self.stats_label.config(
                text=f"Current: {self.format_size(total_current_size)} → Projected: {self.format_size(total_projected_size)} ({savings_percent:.1f}% savings)"
            )

            elapsed_time = time.time() - start_time
            self.log("\n=== Dry Run Complete ===")
            self.log(f"Time taken: {self._format_time(elapsed_time)}")
            if len(all_files) > 0:
                avg_time = elapsed_time / len(all_files)
                self.log(f"Average per file: {self._format_time(avg_time)}")

            messagebox.showinfo("Dry Run Complete",
                f"Current: {self.format_size(total_current_size)}\n"
                f"Projected: {self.format_size(total_projected_size)}\n"
                f"Estimated savings: {savings_percent:.1f}%")

        except Exception as e:
            self.log(f"\nError: {str(e)}")
            messagebox.showerror("Error", f"Dry run failed: {str(e)}")
        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.process_btn.configure(state="normal")
            self.export_btn.configure(state="normal")

    def _analyze_files_parallel(self, all_files, source_dir, settings):
        """Analyze files in parallel using ProcessPoolExecutor"""
        max_workers = self.max_workers.get()
        results = []

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {}
            for f in all_files:
                future = executor.submit(_analyze_file_worker, (str(f), str(source_dir), settings))
                future_to_file[future] = f

            # Collect results as they complete
            for future in as_completed(future_to_file):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    file_path = future_to_file[future]
                    results.append({
                        'relative_path': str(file_path.relative_to(source_dir)),
                        'file_size': 0,
                        'error': str(e)
                    })

        return results

    def _analyze_files_sequential(self, all_files, source_dir, settings):
        """Analyze files sequentially (fallback)"""
        results = []
        for f in all_files:
            result = _analyze_file_worker((str(f), str(source_dir), settings))
            results.append(result)
        return results

    def format_size(self, bytes_size):
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} TB"

    def _format_time(self, seconds):
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

    def _get_dimensions(self, input_dds: Path):
        """Get dimensions from DDS file. Returns (width, height) or None"""
        result = subprocess.run(
            [TEXDIAG_EXE, "info", str(input_dds)],
            capture_output=True, text=True
        )

        # Parse output: width = 2048, height = 2048
        width_match = re.search(r'width\s*=\s*(\d+)', result.stdout)
        height_match = re.search(r'height\s*=\s*(\d+)', result.stdout)

        if width_match and height_match:
            return int(width_match.group(1)), int(height_match.group(1))

        self.log(f"Warning: Could not determine dimensions for {input_dds.name}")
        return None

    def _get_format(self, input_dds: Path):
        """Get format from DDS file. Returns format string or 'UNKNOWN'"""
        result = subprocess.run(
            [TEXDIAG_EXE, "info", str(input_dds)],
            capture_output=True, text=True
        )

        # Parse output: format = BC5_UNORM
        format_match = re.search(r'format\s*=\s*(\S+)', result.stdout)
        if format_match:
            return format_match.group(1)

        return "UNKNOWN"

    def _estimate_output_size(self, width, height, format_name):
        """Estimate output file size based on dimensions and format (includes mipmaps)"""
        # Calculate total pixels including mipmaps (roughly 1.33x base size with full mip chain)
        num_pixels = width * height * 1.33

        # Bits per pixel for each format
        bpp_map = {
            "BC5/ATI2": 8,
            "BC3/DXT5": 8,
            "BC1/DXT1": 4,
            "BGRA": 32,
            "BGR": 24
        }

        bpp = bpp_map.get(format_name, 32)  # Default to 32 if unknown
        total_bytes = int((num_pixels * bpp) / 8)

        # Add overhead for DDS header (~128 bytes)
        return total_bytes + 128

    def _calculate_new_dimensions(self, orig_width, orig_height):
        """Calculate new dimensions based on scale factor and constraints"""
        new_width, new_height = orig_width, orig_height

        # Apply scale factor
        scale = self.scale_factor.get()
        if scale != 1.0:
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)

        # Apply max resolution constraint (largest dimension)
        max_res = self.max_resolution.get()
        if max_res > 0:
            max_dim = max(new_width, new_height)
            if max_dim > max_res:
                scale_factor = max_res / max_dim
                new_width = int(new_width * scale_factor)
                new_height = int(new_height * scale_factor)

        # Apply min resolution constraint (smallest dimension)
        # Only applies if we're downsampling - prevents going too small
        min_res = self.min_resolution.get()
        if min_res > 0 and scale < 1.0:
            min_dim = min(new_width, new_height)
            if min_dim < min_res:
                scale_factor = min_res / min_dim
                new_width = int(new_width * scale_factor)
                new_height = int(new_height * scale_factor)

        return new_width, new_height

    def process_normal_map(self, input_dds: Path, output_dds: Path, is_nh: bool) -> bool:
        """Process a single normal map file using texconv's built-in features"""
        output_dds.parent.mkdir(parents=True, exist_ok=True)

        # Get dimensions and calculate resize first
        dimensions = self._get_dimensions(input_dds)
        if not dimensions:
            return False

        orig_width, orig_height = dimensions
        new_width, new_height = self._calculate_new_dimensions(orig_width, orig_height)

        # Determine target format (with small texture override)
        target_format = self.nh_format.get() if is_nh else self.n_format.get()

        # Check small texture override (based on OUTPUT dimensions)
        if self.use_small_texture_override.get():
            min_dim = min(new_width, new_height)
            if is_nh:
                threshold = self.small_nh_threshold.get()
                if threshold > 0 and min_dim <= threshold:
                    target_format = "BGRA"
            else:
                threshold = self.small_n_threshold.get()
                if threshold > 0 and min_dim <= threshold:
                    target_format = "BGR"

        texconv_format = self.FORMAT_MAP[target_format]

        # Build texconv command
        cmd = [
            TEXCONV_EXE,
            "-f", texconv_format,
            "-m", "0",  # Generate mipmaps
            "-alpha",   # Linear alpha
            "-dx9"      # DX9 compatibility
        ]

        # Invert Y if needed
        if self.invert_y.get():
            cmd.append("-inverty")

        # Reconstruct Z for non-BC5/ATI2 formats (BC5/ATI2 is 2-channel only)
        if target_format != "BC5/ATI2" and self.reconstruct_z.get():
            cmd.append("-reconstructz")

        # BC compression options
        if target_format in ["BC1/DXT1", "BC3/DXT5"]:
            bc_options = ""
            if self.uniform_weighting.get():
                bc_options += "u"
            if self.use_dithering.get():
                bc_options += "d"
            if bc_options:
                cmd.extend(["-bc", bc_options])

        # Apply resize if needed
        if new_width != orig_width or new_height != orig_height:
            cmd.extend(["-w", str(new_width), "-h", str(new_height)])

            resize_method = self.resize_method.get().split()[0]
            if resize_method in self.FILTER_MAP:
                cmd.extend(["-if", self.FILTER_MAP[resize_method]])

        # Output and input
        cmd.extend(["-o", str(output_dds.parent), "-y", str(input_dds)])

        # Execute texconv
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            self.log(f"Error: texconv failed with return code {result.returncode}")
            if result.stderr:
                self.log(f"  stderr: {result.stderr.strip()}")
            if result.stdout:
                self.log(f"  stdout: {result.stdout.strip()}")
            self.log(f"  Command: {' '.join(cmd)}")
            return False

        # Rename output file if needed
        generated_dds = output_dds.parent / input_dds.name
        if generated_dds != output_dds:
            if output_dds.exists():
                output_dds.unlink()
            generated_dds.rename(output_dds)

        return True


if __name__ == "__main__":
    root = tk.Tk()
    app = NormalMapProcessorGUI(root)
    root.mainloop()
