"""
GUI layer for OpenMW Regular Texture Optimizer.
Handles all tkinter UI logic, delegates processing to core.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import json
from pathlib import Path
from multiprocessing import cpu_count

from src.core import (
    RegularTextureProcessor,
    RegularSettings,
    ProcessingResult,
    AnalysisResult,
    format_size,
    format_time,
)
from src.core.regular_settings import (
    DEFAULT_BLACKLIST,
    AGGRESSIVE_BLACKLIST,
    DEFAULT_NO_MIPMAPS,
)


class RegularTextureProcessorGUI:
    """GUI for Regular Texture Processor"""

    WINDOW_WIDTH = 850
    WINDOW_HEIGHT = 1000
    WRAPLENGTH = 700

    def __init__(self, root):
        self.root = root
        self.root.title("OpenMW Regular Texture Optimizer")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # State
        self.processing = False
        self.total_input_size = 0
        self.total_output_size = 0
        self.processed_count = 0
        self.failed_count = 0
        self.processor = None

        # Analysis results storage for detailed export
        self.last_analysis_results = None
        self.last_conversion_stats = None
        self.last_alpha_stats = None
        self.last_filter_stats = None
        self.last_action_groups = None

        # UI Variables
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.resize_method = tk.StringVar(value="FANT (Recommended - sharp details)")
        self.scale_factor = tk.DoubleVar(value=1.0)
        self.max_resolution = tk.IntVar(value=4096)
        self.min_resolution = tk.IntVar(value=256)
        self.uniform_weighting = tk.BooleanVar(value=False)
        self.use_dithering = tk.BooleanVar(value=False)
        self.use_small_texture_override = tk.BooleanVar(value=True)
        self.small_texture_threshold = tk.IntVar(value=256)
        self.enable_parallel = tk.BooleanVar(value=True)
        self.max_workers = tk.IntVar(value=max(1, cpu_count() - 1))
        self.enforce_power_of_2 = tk.BooleanVar(value=True)
        self.allow_well_compressed_passthrough = tk.BooleanVar(value=True)
        self.preserve_compressed_format = tk.BooleanVar(value=True)
        self.enable_tga_support = tk.BooleanVar(value=True)
        self.use_path_whitelist = tk.BooleanVar(value=True)
        self.use_path_blacklist = tk.BooleanVar(value=True)
        self.use_aggressive_blacklist = tk.BooleanVar(value=False)
        self.custom_blacklist = tk.StringVar(value="")
        self.copy_passthrough_files = tk.BooleanVar(value=False)
        self.use_no_mipmap_paths = tk.BooleanVar(value=True)
        self.exclude_normal_maps = tk.BooleanVar(value=True)
        self.enable_atlas_downscaling = tk.BooleanVar(value=False)
        self.atlas_max_resolution = tk.IntVar(value=8192)
        self.optimize_unused_alpha = tk.BooleanVar(value=True)  # Default ON - recommended
        self.alpha_threshold = tk.IntVar(value=255)
        self.analysis_chunk_size = tk.IntVar(value=100)  # Chunk size for parallel alpha analysis

        self.create_widgets()

        # Attach change callbacks
        for var in [self.resize_method, self.scale_factor,
                    self.max_resolution, self.min_resolution, self.uniform_weighting,
                    self.use_dithering, self.use_small_texture_override,
                    self.small_texture_threshold, self.allow_well_compressed_passthrough,
                    self.preserve_compressed_format, self.enable_atlas_downscaling,
                    self.atlas_max_resolution, self.enforce_power_of_2, self.use_path_whitelist,
                    self.use_path_blacklist, self.use_aggressive_blacklist, self.custom_blacklist,
                    self.enable_tga_support, self.copy_passthrough_files, self.use_no_mipmap_paths,
                    self.exclude_normal_maps, self.optimize_unused_alpha]:
            var.trace_add('write', self.invalidate_analysis_cache)

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_help = ttk.Frame(notebook)
        tab_settings = ttk.Frame(notebook)
        tab_process = ttk.Frame(notebook)

        notebook.add(tab_help, text="Help")
        notebook.add(tab_settings, text="Settings")
        notebook.add(tab_process, text="Process Files")

        self._create_help_tab(tab_help)
        self._create_settings_tab(tab_settings)
        self._create_process_tab(tab_process)

    def _create_help_tab(self, parent):
        """Create the help tab"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        frame = ttk.LabelFrame(scrollable, text="About", padding=10)
        frame.pack(fill="x", padx=10, pady=5)

        info = (
            "OpenMW Regular Texture Optimizer\n\n"
            "Optimizes and compresses regular (non-normal map) textures.\n\n"
            "KEY FEATURES:\n"
            "- Excludes _N and _NH files (use Normal Map Optimizer for those)\n"
            "- Path filtering: Only 'Textures' folders, skips icon/bookart\n"
            "- Smart passthrough for well-compressed textures\n"
            "- TGA to DDS conversion\n"
            "- Mipmap regeneration for textures missing mipmaps\n\n"
            "RUN DRY RUN FIRST to see what will happen before processing."
        )
        ttk.Label(frame, text=info, justify="left", wraplength=self.WRAPLENGTH).pack(anchor="w")

        # File Categories
        frame_categories = ttk.LabelFrame(scrollable, text="File Categories", padding=10)
        frame_categories.pack(fill="x", padx=10, pady=5)

        categories_text = (
            "Files are handled in three ways:\n\n"
            "SKIP - Filtered out entirely, never processed, not in output\n"
            "   • Blacklisted paths (icon, bookart, menu_, etc.)\n"
            "   • Not in whitelist ('Textures' folder)\n"
            "   • Normal map suffixes (_n, _nh)\n\n"
            "PASSTHROUGH - Well-compressed, copied as-is to output\n"
            "   • BC1/BC2/BC3 with valid mipmaps, no resize needed\n"
            "   • Can optionally skip copy to save disk space\n\n"
            "MODIFIED - Needs processing, always outputs\n"
            "   • Format conversion (TGA→DDS, uncompressed→BC1/BC3)\n"
            "   • Resizing (scale factor or max resolution)\n"
            "   • Mipmap regeneration"
        )
        ttk.Label(frame_categories, text=categories_text, justify="left", wraplength=self.WRAPLENGTH).pack(anchor="w")

        # Decision Priority Order
        frame_order = ttk.LabelFrame(scrollable, text="Processing Decision Order", padding=10)
        frame_order.pack(fill="x", padx=10, pady=5)

        order_text = (
            "For files that pass filtering (not skipped):\n\n"
            "1. COMPRESSED TEXTURES (BC1, BC2, BC3):\n"
            "   • If NOT resizing AND has valid mipmaps:\n"
            "     → Passthrough (copy as-is or skip)\n"
            "   • If resizing OR missing mipmaps:\n"
            "     → Reprocess, keep same format (BC1→BC1, BC2→BC2, BC3→BC3)\n\n"
            "2. UNCOMPRESSED TEXTURES (TGA, BGR, BGRA):\n"
            "   • Small textures (below threshold):\n"
            "     → Keep uncompressed (BGR/BGRA) - compression wastes space on small files\n"
            "   • Normal size, NO alpha:\n"
            "     → Compress to BC1\n"
            "   • Normal size, HAS alpha:\n"
            "     → Compress to BC3"
        )
        ttk.Label(frame_order, text=order_text, justify="left", wraplength=self.WRAPLENGTH).pack(anchor="w")

    def _create_settings_tab(self, parent):
        """Create settings tab"""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_basic = ttk.Frame(notebook)
        tab_filtering = ttk.Frame(notebook)
        tab_advanced = ttk.Frame(notebook)
        notebook.add(tab_basic, text="Basic")
        notebook.add(tab_filtering, text="Filtering")
        notebook.add(tab_advanced, text="Advanced")

        self._create_basic_settings(tab_basic)
        self._create_filtering_settings(tab_filtering)
        self._create_advanced_settings(tab_advanced)

    def _create_basic_settings(self, parent):
        """Create basic settings"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Directories
        frame_input = ttk.LabelFrame(scrollable, text="Input Directory", padding=10)
        frame_input.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_input, textvariable=self.input_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_input, text="Browse...", command=self.browse_input).pack(side="left")

        frame_output = ttk.LabelFrame(scrollable, text="Output Directory", padding=10)
        frame_output.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_output, textvariable=self.output_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_output, text="Browse...", command=self.browse_output).pack(side="left")

        # Format info (no dropdown - auto-selected based on alpha)
        frame_format = ttk.LabelFrame(scrollable, text="Format Selection (Automatic)", padding=10)
        frame_format.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_format,
                 text="Format is automatically selected based on alpha channel:\n"
                      "• No alpha → BC1/DXT1 (4 bpp, best compression)\n"
                      "• Has alpha → BC3/DXT5 (8 bpp, preserves transparency)\n"
                      "• Small textures → BGR/BGRA uncompressed (see threshold under advanced)",
                 font=("", 8), justify="left").pack(anchor="w")

        # Resize
        frame_resize = ttk.LabelFrame(scrollable, text="Downscale Options", padding=10)
        frame_resize.pack(fill="x", padx=10, pady=5)

        # Explanation section (from normal map optimizer)
        ttk.Label(frame_resize,
                 text="How Downscaling Works:",
                 font=("", 9, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 5))
        ttk.Label(frame_resize,
                 text="• Downscale Factor: Applies to ALL textures (e.g., 0.5 = half size, 1.0 = no resize)\n"
                      "• Max Resolution (Ceiling): Downscales textures LARGER than this - applies EVEN at 1.0 scale factor\n"
                      "• Min Resolution (Floor): Protects textures SMALLER than this - only applies when scale < 1.0\n\n"
                      "Example 1 (with downscaling): Factor 0.5, max 2048, min 256\n"
                      "  -> 4096x4096 becomes 2048x2048 (capped by max), 512x512 becomes 256x256, 256x256 stays (protected by min)\n"
                      "Example 2 (no downscaling): Factor 1.0, max 2048, min 256\n"
                      "  -> 4096x4096 becomes 2048x2048 (capped by max), 512x512 stays as-is, min does nothing at 1.0",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(frame_resize, text="Downscale Method:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.resize_method,
                    values=[
                        "FANT (Recommended - sharp details)",
                        "CUBIC (Smooth surfaces + detail)",
                        "LINEAR (Fast, general purpose)",
                        "BOX (Blurry, good for gradients)"
                    ], state="readonly", width=45).grid(row=2, column=1, sticky="w", padx=10)

        ttk.Label(frame_resize, text="Downscale Factor:").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.scale_factor,
                    values=[0.125, 0.25, 0.5, 1.0], state="readonly", width=20).grid(row=3, column=1, sticky="w", padx=10)
        ttk.Label(frame_resize, text="(1.0 = no downscaling unless max resolution set)",
                 font=("", 8, "italic")).grid(row=3, column=2, sticky="w")

        ttk.Label(frame_resize, text="Max Resolution (Ceiling):").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.max_resolution,
                    values=[0, 128, 256, 512, 1024, 2048, 4096, 8192], state="readonly", width=20).grid(row=4, column=1, sticky="w", padx=10)
        ttk.Label(frame_resize, text="(0 = disabled)",
                 font=("", 8, "italic")).grid(row=4, column=2, sticky="w")

        ttk.Label(frame_resize, text="Min Resolution (Floor):").grid(row=5, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.min_resolution,
                    values=[0, 128, 256, 512, 1024, 2048, 4096, 8192], state="readonly", width=20).grid(row=5, column=1, sticky="w", padx=10)
        ttk.Label(frame_resize, text="(0 = disabled)",
                 font=("", 8, "italic")).grid(row=5, column=2, sticky="w")

        # Alpha Optimization
        frame_alpha = ttk.LabelFrame(scrollable, text="Alpha Optimization (RECOMMENDED)", padding=10)
        frame_alpha.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_alpha,
                 text="Alpha optimization performs two critical functions:\n"
                      "1. Detects 'fake' alpha (all opaque pixels) -> compress to BC1/BGR, saving space/\n"
                      "2. Detects DXT1a (BC1 with 1-bit alpha) -> preserves alpha by upgrading to BC2 when resizing or if recalculating mipmaps.",
                 font=("", 8), wraplength=600, justify="left").pack(anchor="w", pady=(0, 5))

        ttk.Checkbutton(frame_alpha, text="Enable alpha optimization (STRONGLY RECOMMENDED)",
                       variable=self.optimize_unused_alpha).pack(anchor="w")
        ttk.Label(frame_alpha, text="Scans all textures to detect unused alpha AND DXT1a transparency",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        ttk.Label(frame_alpha,
                 text="Note: Adds analysis time (reads full texture data, not just headers).\n"
                      "However, this is ESSENTIAL for accurate processing, especially when resizing.",
                 font=("", 8), foreground="orange").pack(anchor="w", pady=(5, 0))

        ttk.Label(frame_alpha,
                 text="WARNING: Disabling this may cause loss of transparency in DXT1a textures.\n"
                      "Only disable if you are certain your textures don't use DXT1a.",
                 font=("", 8), foreground="red").pack(anchor="w", pady=(2, 0))

    def _create_advanced_settings(self, parent):
        """Create advanced settings tab"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Passthrough / Format Preservation
        frame_pass = ttk.LabelFrame(scrollable, text="Passthrough & Format Preservation", padding=10)
        frame_pass.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_pass, text="Allow well-compressed textures to passthrough",
                       variable=self.allow_well_compressed_passthrough).pack(anchor="w")
        ttk.Label(frame_pass, text="BC1/BC2/BC3 with proper mipmaps skip processing (no changes needed)",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        ttk.Checkbutton(frame_pass, text="Copy passthrough files to output",
                       variable=self.copy_passthrough_files).pack(anchor="w", pady=(10, 0))
        ttk.Label(frame_pass, text="When enabled, passthrough files are copied to output directory.\n"
                                   "When disabled, they are skipped (output only contains modified textures).",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        ttk.Checkbutton(frame_pass, text="Preserve compressed format (BC1->BC1, BC2->BC2, BC3->BC3)",
                       variable=self.preserve_compressed_format).pack(anchor="w", pady=(10, 0))
        ttk.Label(frame_pass, text="When processing compressed textures (not passthrough), keep their original format\n"
                                   "instead of converting to target format.",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        # Small Texture Override
        frame_small_tex = ttk.LabelFrame(scrollable, text="Small Texture Override", padding=10)
        frame_small_tex.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_small_tex, text="Enable small texture override",
                       variable=self.use_small_texture_override).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_small_tex,
                 text="Small textures benefit from uncompressed formats. This overrides compression for tiny\n"
                      "UNCOMPRESSED textures. Already-compressed small textures (BC1/BC2/BC3) are kept\n"
                      "compressed to avoid wasting disk space by decompressing them.",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_small_tex, text="Threshold:").grid(row=2, column=0, sticky="w", pady=5, padx=(20, 0))
        ttk.Combobox(frame_small_tex, textvariable=self.small_texture_threshold,
                    values=[0, 64, 128, 256, 512], state="readonly", width=15).grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_small_tex, text="(Textures ≤ this on any side stay uncompressed, 0 = disabled)",
                 font=("", 8, "italic")).grid(row=2, column=2, sticky="w")

        ttk.Label(frame_small_tex,
                 text="Uses BGRA for textures with alpha, BGR for textures without alpha.\n"
                      "⚠ Threshold is checked AFTER resizing. Recommended: 128",
                 font=("", 8), wraplength=600, justify="left").grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 2))

        # Texture Atlas Settings
        frame_atlas = ttk.LabelFrame(scrollable, text="Texture Atlas Settings", padding=10)
        frame_atlas.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_atlas,
                 text="Texture atlases are automatically detected and protected from resizing.\n"
                      "Detection: Filename contains 'atlas' or path contains 'ATL' directory.\n"
                      "Atlases still receive format conversion and mipmap regeneration.",
                 font=("", 8), wraplength=600, justify="left").pack(anchor="w", pady=(0, 5))

        ttk.Checkbutton(frame_atlas, text="Enable downscaling for texture atlases (NOT recommended)",
                       variable=self.enable_atlas_downscaling).pack(anchor="w")
        ttk.Label(frame_atlas,
                 text="Atlases are large for a reason - they pack many smaller textures into one file.\n"
                      "Downscaling reduces detail for all packed textures.",
                 font=("", 8), wraplength=600, justify="left", foreground="red").pack(anchor="w", padx=(20, 0))

        frame_atlas_max = ttk.Frame(frame_atlas)
        frame_atlas_max.pack(anchor="w", pady=(5, 0))
        ttk.Label(frame_atlas_max, text="Max resolution for atlases:").pack(side="left")
        ttk.Combobox(frame_atlas_max, textvariable=self.atlas_max_resolution,
                    values=[1024, 2048, 4096, 8192, 16384], state="readonly", width=10).pack(side="left", padx=(10, 0))
        ttk.Label(frame_atlas,
                 text="Only applies if 'Enable downscaling for texture atlases' is checked. Default: 4096",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        # TGA
        frame_tga = ttk.LabelFrame(scrollable, text="TGA Support", padding=10)
        frame_tga.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_tga, text="Enable TGA file support",
                       variable=self.enable_tga_support).pack(anchor="w")
        ttk.Label(frame_tga, text="Process .tga files in addition to .dds files",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        # Parallel
        frame_parallel = ttk.LabelFrame(scrollable, text="Parallel Processing", padding=10)
        frame_parallel.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_parallel, text="Enable parallel processing",
                       variable=self.enable_parallel).pack(anchor="w")
        frame_workers = ttk.Frame(frame_parallel)
        frame_workers.pack(anchor="w", pady=(5, 0))
        ttk.Label(frame_workers, text="Max workers:").pack(side="left", padx=(20, 5))
        ttk.Combobox(frame_workers, textvariable=self.max_workers,
                    values=list(range(1, cpu_count() + 1)), state="readonly", width=10).pack(side="left")
        ttk.Label(frame_parallel, text="Number of parallel texture processing threads",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        frame_chunk = ttk.Frame(frame_parallel)
        frame_chunk.pack(anchor="w", pady=(5, 0))
        ttk.Label(frame_chunk, text="Analysis chunk size:").pack(side="left", padx=(20, 5))
        ttk.Combobox(frame_chunk, textvariable=self.analysis_chunk_size,
                    values=[25, 50, 100, 200, 500], state="readonly", width=10).pack(side="left")
        ttk.Label(frame_parallel, text="Batch size for parallel alpha analysis (higher = more memory, faster)",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

    def _create_filtering_settings(self, parent):
        """Create filtering settings"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Normal Map Exclusion
        frame_normal = ttk.LabelFrame(scrollable, text="Normal Map Exclusion", padding=10)
        frame_normal.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_normal, text="Exclude normal maps (_n, _nh suffixes)",
                       variable=self.exclude_normal_maps).pack(anchor="w")
        ttk.Label(frame_normal, text="Use the Normal Map Optimizer for these files instead",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        # Whitelist
        frame_white = ttk.LabelFrame(scrollable, text="Path Whitelist", padding=10)
        frame_white.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_white, text="Only process paths containing a 'Textures' directory",
                       variable=self.use_path_whitelist).pack(anchor="w")

        # Blacklist
        frame_black = ttk.LabelFrame(scrollable, text="Path Blacklist (Skip Entirely)", padding=10)
        frame_black.pack(fill="x", padx=10, pady=5)
        blacklist_str = ", ".join(DEFAULT_BLACKLIST)
        ttk.Checkbutton(frame_black, text=f"Skip paths containing: {blacklist_str}",
                       variable=self.use_path_blacklist).pack(anchor="w")

        # Aggressive blacklist option
        ttk.Checkbutton(frame_black, text="Aggressive UI filtering (OpenMW Lua mods, levelup, scroll, etc.)",
                       variable=self.use_aggressive_blacklist).pack(anchor="w", pady=(10, 0))
        aggressive_str = ", ".join(AGGRESSIVE_BLACKLIST)
        ttk.Label(frame_black,
                 text=f"Also skips: {aggressive_str}\nMay exclude some legitimate textures.",
                 font=("", 8)).pack(anchor="w", padx=(20, 0))

        ttk.Label(frame_black, text="Custom blacklist (comma-separated):").pack(anchor="w", pady=(10, 0))
        ttk.Entry(frame_black, textvariable=self.custom_blacklist, width=50).pack(anchor="w", pady=5)

        # No-mipmap paths
        frame_nomip = ttk.LabelFrame(scrollable, text="No-Mipmap Paths", padding=10)
        frame_nomip.pack(fill="x", padx=10, pady=5)
        nomip_str = ", ".join(DEFAULT_NO_MIPMAPS)
        ttk.Checkbutton(frame_nomip, text="Skip mipmap generation for UI paths",
                       variable=self.use_no_mipmap_paths).pack(anchor="w")
        ttk.Label(frame_nomip, text=f"Paths: {nomip_str}",
                 font=("", 8), wraplength=400).pack(anchor="w", pady=(5, 0))
        ttk.Label(frame_nomip, text="These files are displayed at 1:1 scale (no mipmaps needed)",
                 font=("", 8)).pack(anchor="w")

    def _create_process_tab(self, parent):
        """Create processing tab"""
        frame_progress = ttk.LabelFrame(parent, text="Progress", padding=10)
        frame_progress.pack(fill="x", padx=10, pady=5)
        self.progress_label = ttk.Label(frame_progress, text="Ready to process")
        self.progress_label.pack(anchor="w", pady=(0, 5))
        self.progress_bar = ttk.Progressbar(frame_progress, mode="determinate", length=400)
        self.progress_bar.pack(fill="x")

        frame_log = ttk.LabelFrame(parent, text="Log", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = tk.Text(frame_log, height=15, width=70, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(frame_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        frame_stats = ttk.LabelFrame(parent, text="Summary", padding=10)
        frame_stats.pack(fill="x", padx=10, pady=5)
        self.stats_label = ttk.Label(frame_stats, text="No files processed yet")
        self.stats_label.pack()

        button_frame = ttk.Frame(parent)
        button_frame.pack(pady=10)
        self.analyze_btn = ttk.Button(button_frame, text="Dry Run (Analysis)", command=self.start_analysis)
        self.analyze_btn.pack(side="left", padx=5)
        self.export_btn = ttk.Button(button_frame, text="Export Report", command=self.export_log, state="disabled")
        self.export_btn.pack(side="left", padx=5)
        self.export_settings_btn = ttk.Button(button_frame, text="Export Settings", command=self.export_settings)
        self.export_settings_btn.pack(side="left", padx=5)
        self.process_btn = ttk.Button(button_frame, text="Process Files", command=self.start_processing, state="disabled")
        self.process_btn.pack(side="left", padx=5)

    def browse_input(self):
        d = filedialog.askdirectory(title="Select Input Directory")
        if d:
            self.input_dir.set(d)

    def browse_output(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d:
            self.output_dir.set(d)

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def export_log(self):
        """Export detailed analysis report with complete file listings."""
        content = self.log_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showwarning("Warning", "No log content")
            return

        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="analysis_report.txt")
        if not path:
            return

        # Build detailed report
        lines = [content, "\n"]

        # Excluded files section
        if self.last_filter_stats:
            lines.append("\n" + "=" * 60)
            lines.append("EXCLUDED FILES")
            lines.append("=" * 60 + "\n")

            # Normal maps
            normal_files = self.last_filter_stats.get('normal_map_files', [])
            if normal_files:
                lines.append(f"\n--- Normal Maps (_n, _nh): {len(normal_files)} files ---")
                for f in sorted(normal_files):
                    lines.append(f"  {f}")

            # Blacklisted paths
            blacklist_files = self.last_filter_stats.get('blacklist_files', [])
            if blacklist_files:
                lines.append(f"\n--- Blacklisted Paths: {len(blacklist_files)} files ---")
                for f in sorted(blacklist_files):
                    lines.append(f"  {f}")

        # Mipmap regeneration section (no_change = same format/size, just mipmap regen)
        if self.last_action_groups and self.last_action_groups.get('no_change'):
            lines.append("\n" + "=" * 60)
            lines.append("MIPMAP REGENERATION (same format/size)")
            lines.append("=" * 60 + "\n")

            mipmap_files = self.last_action_groups['no_change']
            # Group by format
            by_format = {}
            for r in mipmap_files:
                fmt = r.format
                if fmt not in by_format:
                    by_format[fmt] = []
                by_format[fmt].append(r)

            for fmt, files in sorted(by_format.items(), key=lambda x: -len(x[1])):
                lines.append(f"\n--- {fmt}: {len(files)} files ---")
                for r in sorted(files, key=lambda x: x.relative_path):
                    lines.append(f"  {r.relative_path}")

        # Resize section (with dimensions)
        if self.last_analysis_results:
            resized = [r for r in self.last_analysis_results
                      if r.new_width != r.width or r.new_height != r.height]
            if resized:
                lines.append("\n" + "=" * 60)
                lines.append("RESIZED TEXTURES")
                lines.append("=" * 60 + "\n")

                lines.append(f"\n--- {len(resized)} files will be resized ---")
                for r in sorted(resized, key=lambda x: x.relative_path):
                    lines.append(f"  {r.relative_path}: {r.width}x{r.height} → {r.new_width}x{r.new_height}")

        # Conversion details section
        if self.last_conversion_stats:
            lines.append("\n" + "=" * 60)
            lines.append("DETAILED FILE LISTINGS BY CONVERSION TYPE")
            lines.append("=" * 60 + "\n")

            # Group by conversion type
            for (src_fmt, dst_fmt, has_resize), data in sorted(
                self.last_conversion_stats.items(),
                key=lambda x: (-x[1]['count'], x[0][0], x[0][1])
            ):
                resize_note = " (with resize)" if has_resize else ""
                lines.append(f"\n--- {src_fmt} → {dst_fmt}{resize_note}: {data['count']} files ---")
                # Include dimensions for each file if available
                if self.last_analysis_results:
                    result_map = {r.relative_path: r for r in self.last_analysis_results}
                    for f in sorted(data['files']):
                        r = result_map.get(f)
                        if r and (r.new_width != r.width or r.new_height != r.height):
                            lines.append(f"  {f} ({r.width}x{r.height} → {r.new_width}x{r.new_height})")
                        else:
                            lines.append(f"  {f}")
                else:
                    for f in sorted(data['files']):
                        lines.append(f"  {f}")

        if self.last_alpha_stats:
            lines.append("\n" + "=" * 60)
            lines.append("ALPHA OPTIMIZATION DETAILS")
            lines.append("=" * 60 + "\n")

            for conversion, data in sorted(
                self.last_alpha_stats.items(),
                key=lambda x: -x[1]['count']
            ):
                lines.append(f"\n--- {conversion}: {data['count']} files ---")
                for f in sorted(data['files']):
                    lines.append(f"  {f}")

        with open(path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Success", f"Detailed report saved to {path}")

    def export_settings(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="settings.json")
        if path:
            settings = self.get_settings()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings.to_dict(), f, indent=2)
            messagebox.showinfo("Success", f"Saved to {path}")

    def invalidate_analysis_cache(self, *args):
        if self.processor:
            self.processor = None
            self.process_btn.configure(state="disabled")

    def get_settings(self) -> RegularSettings:
        whitelist = ["Textures"] if self.use_path_whitelist.get() else []
        blacklist = DEFAULT_BLACKLIST.copy() if self.use_path_blacklist.get() else []
        if self.use_aggressive_blacklist.get():
            blacklist.extend(AGGRESSIVE_BLACKLIST)
        custom = [x.strip() for x in self.custom_blacklist.get().split(",") if x.strip()]
        no_mipmap_paths = DEFAULT_NO_MIPMAPS.copy() if self.use_no_mipmap_paths.get() else []

        settings = RegularSettings(
            scale_factor=self.scale_factor.get(),
            max_resolution=self.max_resolution.get(),
            min_resolution=self.min_resolution.get(),
            resize_method=self.resize_method.get(),
            enable_parallel=self.enable_parallel.get(),
            max_workers=self.max_workers.get(),
            uniform_weighting=self.uniform_weighting.get(),
            use_dithering=self.use_dithering.get(),
            use_small_texture_override=self.use_small_texture_override.get(),
            enforce_power_of_2=self.enforce_power_of_2.get(),
            enable_atlas_downscaling=self.enable_atlas_downscaling.get(),
            atlas_max_resolution=self.atlas_max_resolution.get(),
            allow_well_compressed_passthrough=self.allow_well_compressed_passthrough.get(),
            preserve_compressed_format=self.preserve_compressed_format.get(),
            copy_passthrough_files=self.copy_passthrough_files.get(),
            exclude_normal_maps=self.exclude_normal_maps.get(),
            enable_tga_support=self.enable_tga_support.get(),
            optimize_unused_alpha=self.optimize_unused_alpha.get(),
            alpha_threshold=self.alpha_threshold.get(),
            analysis_chunk_size=self.analysis_chunk_size.get(),
        )
        settings.path_whitelist = whitelist
        settings.path_blacklist = blacklist
        settings.custom_blacklist = custom
        settings.no_mipmap_paths = no_mipmap_paths
        settings.small_texture_threshold = self.small_texture_threshold.get()
        return settings

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
            messagebox.showerror("Error", "Please select both directories")
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.process_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.total_input_size = 0
        self.total_output_size = 0
        self.processed_count = 0
        self.failed_count = 0
        self.stats_label.config(text="Processing...")

        threading.Thread(target=self.process_files, daemon=True).start()

    def analyze_files(self):
        start_time = time.time()
        try:
            settings = self.get_settings()
            self.processor = RegularTextureProcessor(settings)
            input_dir = Path(self.input_dir.get())

            self.log("=== Dry Run (Preview) ===\n")
            self.log("Note: First dry run reads all file headers (may take a minute for large datasets).")
            self.log("Subsequent runs use cached data and are nearly instant.\n")
            if settings.path_whitelist:
                self.log(f"Whitelist: {settings.path_whitelist}")
            if settings.path_blacklist:
                self.log(f"Blacklist: {settings.path_blacklist}")
            if settings.custom_blacklist:
                self.log(f"Custom blacklist: {settings.custom_blacklist}")
            self.log("")

            # No progress callback - just run analysis
            results = self.processor.analyze_files(input_dir, lambda c, t: None)

            if not results:
                self.log("No texture files found!")
                self.log("\nMake sure your input directory contains:")
                self.log("  - .dds or .tga files")
                self.log("  - A 'Textures' folder in the path (if whitelist enabled)")
                self.log("  - No 'icon', 'icons', 'bookart' in path (if blacklist enabled)")
                messagebox.showinfo("Done", "No texture files found")
                self.processing = False
                self.analyze_btn.configure(state="normal")
                return

            # Display filter statistics
            if hasattr(self.processor, 'filter_stats'):
                stats = self.processor.filter_stats
                total_found = stats.get('total_textures_found', 0)
                excluded_normal = stats.get('excluded_normal_maps', 0)
                excluded_whitelist = stats.get('excluded_whitelist', 0)
                excluded_blacklist = stats.get('excluded_blacklist', 0)
                total_excluded = excluded_normal + excluded_whitelist + excluded_blacklist

                if total_excluded > 0:
                    self.log(f"=== Filter Results ===")
                    self.log(f"Total texture files scanned: {total_found}")
                    self.log(f"Included for processing: {stats.get('included', len(results))}")
                    self.log(f"Excluded: {total_excluded}")

                    if excluded_normal > 0:
                        self.log(f"  - Normal maps (_n, _nh): {excluded_normal}")

                    if excluded_whitelist > 0:
                        self.log(f"  - Not in 'Textures' folder: {excluded_whitelist}")
                        examples = stats.get('whitelist_examples', [])
                        for ex in examples[:3]:
                            self.log(f"      {ex}")
                        if len(examples) > 3:
                            self.log(f"      ... and {excluded_whitelist - 3} more")

                    if excluded_blacklist > 0:
                        self.log(f"  - Blacklisted paths (icon, bookart, etc.): {excluded_blacklist}")
                        examples = stats.get('blacklist_examples', [])
                        for ex in examples[:3]:
                            self.log(f"      {ex}")
                        if len(examples) > 3:
                            self.log(f"      ... and {excluded_blacklist - 3} more")
                    self.log("")

            # Count files by type
            dds_count = sum(1 for r in results if not r.relative_path.lower().endswith('.tga'))
            tga_count = sum(1 for r in results if r.relative_path.lower().endswith('.tga'))
            passthrough_count = sum(1 for r in results if r.is_passthrough)

            self.log(f"Found {len(results)} texture files ({passthrough_count} passthrough)")
            if dds_count > 0:
                self.log(f"  - {dds_count} DDS files")
            if tga_count > 0:
                self.log(f"  - {tga_count} TGA files")

            # Calculate totals
            total_current = sum(r.file_size for r in results)
            total_projected = sum(r.projected_size for r in results if not r.error)

            # Collect stats
            format_stats = {}
            conversion_stats = {}
            action_groups = {
                'resize_and_reformat': [], 'resize_only': [], 'reformat_only': [],
                'no_change': [], 'passthrough': [], 'missing_mipmaps': [],
                'tga_conversion': [], 'no_mipmaps': [], 'dxt1a': [], 'alpha_optimized': []
            }
            # Track alpha optimization by original format
            alpha_optimization_stats = {}  # e.g., {'BC3/DXT5': 5, 'TGA_RGBA': 3}
            oversized_textures = []

            for r in results:
                if r.error:
                    continue

                # Format stats
                if r.format not in format_stats:
                    format_stats[r.format] = {'count': 0, 'size': 0}
                format_stats[r.format]['count'] += 1
                format_stats[r.format]['size'] += r.file_size

                # Categorize action
                will_resize = (r.new_width != r.width) or (r.new_height != r.height)
                will_reformat = r.format != r.target_format

                if r.is_passthrough:
                    action_groups['passthrough'].append(r)
                elif will_resize and will_reformat:
                    action_groups['resize_and_reformat'].append(r)
                elif will_resize:
                    action_groups['resize_only'].append(r)
                elif will_reformat:
                    action_groups['reformat_only'].append(r)
                else:
                    action_groups['no_change'].append(r)

                # Track issues
                if r.mipmap_count == 1 and max(r.width or 0, r.height or 0) > 4:
                    action_groups['missing_mipmaps'].append(r)
                if r.format in ('TGA', 'TGA_RGB', 'TGA_RGBA'):
                    action_groups['tga_conversion'].append(r)
                if r.width and r.height and max(r.width, r.height) > self.max_resolution.get():
                    # Track if it will actually be resized (accounts for atlas protection)
                    will_be_resized = (r.new_width != r.width) or (r.new_height != r.height)
                    oversized_textures.append((r.relative_path, r.width, r.height, will_be_resized))

                # Track no-mipmap files from warnings
                for warning in (r.warnings or []):
                    if "No-mipmap path" in warning:
                        action_groups['no_mipmaps'].append(r)

                # Track DXT1a textures (BC1 using 1-bit alpha)
                if hasattr(r, 'has_dxt1a') and r.has_dxt1a:
                    action_groups['dxt1a'].append(r)

                # Track alpha optimization
                if hasattr(r, 'alpha_optimized') and r.alpha_optimized:
                    action_groups['alpha_optimized'].append(r)
                    orig_fmt = getattr(r, 'original_format', 'UNKNOWN')
                    target_fmt = r.target_format or 'UNKNOWN'
                    key = f"{orig_fmt} → {target_fmt}"
                    if key not in alpha_optimization_stats:
                        alpha_optimization_stats[key] = {'count': 0, 'files': []}
                    alpha_optimization_stats[key]['count'] += 1
                    alpha_optimization_stats[key]['files'].append(r.relative_path)

                # Track conversions (non-passthrough)
                if not r.is_passthrough:
                    key = (r.format, r.target_format, will_resize)
                    if key not in conversion_stats:
                        conversion_stats[key] = {'count': 0, 'files': []}
                    conversion_stats[key]['count'] += 1
                    conversion_stats[key]['files'].append(r.relative_path)

            # Store for detailed export
            self.last_analysis_results = results
            self.last_conversion_stats = conversion_stats
            self.last_alpha_stats = alpha_optimization_stats
            self.last_action_groups = action_groups
            if hasattr(self.processor, 'filter_stats'):
                self.last_filter_stats = self.processor.filter_stats

            # Current State
            self.log("\n=== Current State ===")
            self.log(f"Total size: {format_size(total_current)}")
            if len(results) > 0:
                self.log(f"Average size per file: {format_size(total_current // len(results))}")

            # Format Breakdown
            self.log("\n=== Format Breakdown (Current) ===")
            for fmt, stats in sorted(format_stats.items(), key=lambda x: -x[1]['count']):
                self.log(f"  {fmt}: {stats['count']} files, {format_size(stats['size'])} total")

            # Separate actual format conversions from same-format reprocessing
            actual_conversions = {}  # format changes
            reprocessing_resize = {}  # same format, needs resize
            reprocessing_mipmaps = {}  # same format, needs mipmap regen

            for (src_fmt, dst_fmt, has_resize), data in conversion_stats.items():
                if src_fmt != dst_fmt:
                    # Actual format conversion
                    key = (src_fmt, dst_fmt, has_resize)
                    actual_conversions[key] = data
                elif has_resize:
                    # Same format, but resizing
                    if src_fmt not in reprocessing_resize:
                        reprocessing_resize[src_fmt] = {'count': 0, 'files': []}
                    reprocessing_resize[src_fmt]['count'] += data['count']
                    reprocessing_resize[src_fmt]['files'].extend(data['files'][:5])
                else:
                    # Same format, no resize - must be mipmap regeneration
                    if src_fmt not in reprocessing_mipmaps:
                        reprocessing_mipmaps[src_fmt] = {'count': 0, 'files': []}
                    reprocessing_mipmaps[src_fmt]['count'] += data['count']
                    reprocessing_mipmaps[src_fmt]['files'].extend(data['files'][:5])

            # Show actual format conversions
            if actual_conversions:
                self.log("\n=== Format Conversions ===")
                for (src_fmt, dst_fmt, has_resize), data in sorted(actual_conversions.items(), key=lambda x: -x[1]['count']):
                    resize_label = " + resize" if has_resize else ""
                    self.log(f"  {src_fmt} → {dst_fmt}{resize_label}: {data['count']} files")

            # Show same-format reprocessing for resize
            if reprocessing_resize:
                total_resize = sum(d['count'] for d in reprocessing_resize.values())
                self.log(f"\n=== Resize Only ({total_resize} files, keeping format) ===")
                for fmt, data in sorted(reprocessing_resize.items(), key=lambda x: -x[1]['count']):
                    self.log(f"  {fmt}: {data['count']} files")

            # Show same-format reprocessing for mipmaps
            if reprocessing_mipmaps:
                total_mipmap = sum(d['count'] for d in reprocessing_mipmaps.values())
                self.log(f"\n=== Mipmap Regeneration ({total_mipmap} files, same format/size) ===")
                for fmt, data in sorted(reprocessing_mipmaps.items(), key=lambda x: -x[1]['count']):
                    self.log(f"  {fmt}: {data['count']} files")
                self.log("Note: These files have missing/incomplete mipmaps that will be regenerated.")

            # Conversion Examples (only for actual format changes)
            if actual_conversions:
                self.log("\n=== Conversion Examples ===")
                for (src_fmt, dst_fmt, has_resize), data in sorted(actual_conversions.items(), key=lambda x: -x[1]['count'])[:5]:
                    resize_label = " + resize" if has_resize else ""
                    count = data['count']
                    self.log(f"{src_fmt} → {dst_fmt}{resize_label}: {count} files")
                    for f in data['files'][:3]:
                        self.log(f"    - {f}")
                    if count > 3:
                        self.log(f"    ... and {count - 3} more")

            # Summary
            self.log("\n=== Summary ===")
            total_modify = len(action_groups['resize_and_reformat']) + len(action_groups['resize_only']) + len(action_groups['reformat_only'])

            if total_modify > 0:
                self.log(f"Files to modify: {total_modify}")
                if action_groups['resize_and_reformat']:
                    self.log(f"  - Resize + Convert: {len(action_groups['resize_and_reformat'])}")
                if action_groups['resize_only']:
                    self.log(f"  - Resize only: {len(action_groups['resize_only'])}")
                if action_groups['reformat_only']:
                    self.log(f"  - Convert only: {len(action_groups['reformat_only'])}")

            if action_groups['no_change']:
                self.log(f"Files to reprocess: {len(action_groups['no_change'])} (same format/size, mipmap regeneration)")
            if action_groups['passthrough']:
                copy_passthrough = self.copy_passthrough_files.get()
                if copy_passthrough:
                    self.log(f"Files to pass through: {len(action_groups['passthrough'])} (will be copied)")
                else:
                    self.log(f"Files to pass through: {len(action_groups['passthrough'])} (will be skipped)")

            files_to_process = total_modify + len(action_groups['no_change'])
            self.log(f"\n{files_to_process} files will be processed (cuttlefish for BC/BGRA, texconv for BGR).")
            if action_groups['passthrough']:
                copy_passthrough = self.copy_passthrough_files.get()
                if copy_passthrough:
                    self.log(f"{len(action_groups['passthrough'])} files already optimized (will be copied to output).")
                else:
                    self.log(f"{len(action_groups['passthrough'])} files already optimized (will be skipped, not in output).")

            # Projection
            savings = total_current - total_projected
            savings_pct = (savings / total_current * 100) if total_current > 0 else 0

            self.log("\n=== Projected Output ===")
            self.log(f"Current: {format_size(total_current)}")
            self.log(f"Projected: {format_size(total_projected)}")
            self.log(f"Savings: {format_size(savings)} ({savings_pct:.1f}%)")

            # Issues & Auto-Fixes
            has_issues = (action_groups['missing_mipmaps'] or action_groups['tga_conversion'] or
                         action_groups['no_mipmaps'] or oversized_textures)

            if has_issues:
                self.log("\n=== Issues & Auto-Fixes ===")

                if action_groups['missing_mipmaps']:
                    self.log(f"\n[i] Auto-fix: {len(action_groups['missing_mipmaps'])} file(s) have missing mipmaps")
                    self.log("    Full mipmap chain will be regenerated")
                    for r in action_groups['missing_mipmaps'][:3]:
                        self.log(f"      - {r.relative_path}")
                    if len(action_groups['missing_mipmaps']) > 3:
                        self.log(f"      ... and {len(action_groups['missing_mipmaps']) - 3} more")

                if action_groups['tga_conversion']:
                    self.log(f"\n[i] Auto-fix: {len(action_groups['tga_conversion'])} TGA file(s) will be converted to DDS")
                    for r in action_groups['tga_conversion'][:3]:
                        self.log(f"      - {r.relative_path}")
                    if len(action_groups['tga_conversion']) > 3:
                        self.log(f"      ... and {len(action_groups['tga_conversion']) - 3} more")

                if action_groups['no_mipmaps']:
                    self.log(f"\n[i] No-mipmaps: {len(action_groups['no_mipmaps'])} file(s) will be processed without mipmaps")
                    self.log("    (UI elements like splash screens, birthsigns, levelup)")
                    for r in action_groups['no_mipmaps'][:3]:
                        self.log(f"      - {r.relative_path}")
                    if len(action_groups['no_mipmaps']) > 3:
                        self.log(f"      ... and {len(action_groups['no_mipmaps']) - 3} more")

                if oversized_textures:
                    # Use actual analysis results (accounts for atlas protection, etc.)
                    will_fix = [t for t in oversized_textures if t[3]]  # t[3] = will_be_resized
                    wont_fix = [t for t in oversized_textures if not t[3]]

                    if will_fix:
                        self.log(f"\n[i] Auto-fix: {len(will_fix)} texture(s) larger than {self.max_resolution.get()}px will be downscaled")
                        for path, w, h, _ in will_fix[:3]:
                            self.log(f"      - {path} ({w}x{h})")
                        if len(will_fix) > 3:
                            self.log(f"      ... and {len(will_fix) - 3} more")

                    if wont_fix:
                        self.log(f"\n[i] Skipped: {len(wont_fix)} large texture(s) not resized (atlas protection or settings)")
                        for path, w, h, _ in wont_fix[:3]:
                            self.log(f"      - {path} ({w}x{h})")
                        if len(wont_fix) > 3:
                            self.log(f"      ... and {len(wont_fix) - 3} more")

            # Alpha Analysis Section (always show if DXT1a found or alpha optimization enabled)
            has_alpha_info = action_groups['dxt1a'] or action_groups['alpha_optimized']

            if has_alpha_info:
                self.log("\n=== Alpha Channel Analysis ===")

                # DXT1a detection (BC1 with 1-bit transparency)
                if action_groups['dxt1a']:
                    self.log(f"\n[i] DXT1a detected: {len(action_groups['dxt1a'])} BC1/DXT1 file(s) use 1-bit alpha")
                    self.log("    These textures use punch-through transparency (fully opaque or fully transparent)")
                    for r in action_groups['dxt1a'][:3]:
                        self.log(f"      - {r.relative_path}")
                    if len(action_groups['dxt1a']) > 3:
                        self.log(f"      ... and {len(action_groups['dxt1a']) - 3} more")

                # Alpha optimization (unused alpha detected)
                if action_groups['alpha_optimized']:
                    total_optimized = len(action_groups['alpha_optimized'])
                    self.log(f"\n[i] Alpha optimization: {total_optimized} file(s) with unused alpha channel")
                    self.log("    Alpha-capable formats converted to non-alpha formats")

                    # Show breakdown by conversion type (e.g., "BGRA → BC1", "BGRA → BGR")
                    for conversion, data in sorted(alpha_optimization_stats.items(), key=lambda x: -x[1]['count']):
                        self.log(f"      {conversion}: {data['count']} files")
                        for f in data['files'][:2]:
                            self.log(f"        - {f}")
                        if data['count'] > 2:
                            self.log(f"        ... and {data['count'] - 2} more")

            elapsed = time.time() - start_time
            self.log(f"\n=== Analysis Complete ({format_time(elapsed)}) ===")

            self.stats_label.config(text=f"Current: {format_size(total_current)} -> Projected: {format_size(total_projected)} ({savings_pct:.1f}% savings)")
            messagebox.showinfo("Done", f"Found {len(results)} files\nCurrent: {format_size(total_current)}\nProjected: {format_size(total_projected)}\nSavings: {savings_pct:.1f}%")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))
            self.processing = False
            self.analyze_btn.configure(state="normal")
            return

        self.processing = False
        self.analyze_btn.configure(state="normal")
        self.process_btn.configure(state="normal")
        self.export_btn.configure(state="normal")

    def process_files(self):
        start_time = time.time()
        try:
            if not self.processor:
                messagebox.showerror("Error", "Run Dry Run first")
                return

            input_dir = Path(self.input_dir.get())
            output_dir = Path(self.output_dir.get())
            all_files = self.processor.find_textures(input_dir)

            # Filter out passthrough files if copy_passthrough_files is disabled
            # to show accurate count of files that will actually be processed
            copy_passthrough = self.copy_passthrough_files.get()
            if not copy_passthrough and self.processor.analysis_cache:
                files_to_process = []
                for f in all_files:
                    rel_path = str(f.relative_to(input_dir))
                    cached = self.processor.analysis_cache.get(rel_path)
                    if cached and cached.is_passthrough:
                        continue  # Skip passthrough files
                    files_to_process.append(f)
                process_count = len(files_to_process)
            else:
                process_count = len(all_files)

            self.log(f"Processing {process_count} files...\n")
            self.progress_bar["maximum"] = process_count
            self.progress_bar["value"] = 0

            last_ui_update = time.time()
            pending_logs = []

            def progress_cb(current, total, result):
                nonlocal last_ui_update, pending_logs

                # Track stats
                self.total_input_size += result.input_size

                if result.success:
                    self.processed_count += 1
                    self.total_output_size += result.output_size

                    if result.orig_dims and result.new_dims:
                        orig_w, orig_h = result.orig_dims
                        new_w, new_h = result.new_dims
                        size_change = result.output_size - result.input_size
                        size_change_str = f"+{format_size(size_change)}" if size_change > 0 else format_size(size_change)

                        pending_logs.append(f"✓ {result.relative_path}")
                        pending_logs.append(f"  {orig_w}x{orig_h} {result.orig_format} → {new_w}x{new_h} {result.new_format} | "
                                f"{format_size(result.input_size)} → {format_size(result.output_size)} ({size_change_str})")
                    else:
                        pending_logs.append(f"✓ {result.relative_path}")
                else:
                    self.failed_count += 1
                    error_msg = result.error_msg or 'Unknown error'
                    pending_logs.append(f"✗ Failed: {result.relative_path} - {error_msg}")

                # Only update UI every 2 seconds (or on last file)
                now = time.time()
                if now - last_ui_update >= 2.0 or current == total:
                    # Flush pending logs
                    if pending_logs:
                        self.log('\n'.join(pending_logs))
                        pending_logs.clear()

                    self.progress_bar["value"] = current
                    self.progress_label.config(text=f"Processing {current}/{total}")
                    self.root.update_idletasks()
                    last_ui_update = now

            self.processor.process_files(input_dir, output_dir, progress_cb)

            elapsed = time.time() - start_time
            savings = self.total_input_size - self.total_output_size
            savings_pct = (savings / self.total_input_size * 100) if self.total_input_size > 0 else 0

            self.log(f"\n=== Complete ({format_time(elapsed)}) ===")
            self.log(f"Processed: {self.processed_count}, Failed: {self.failed_count}")
            self.log(f"Savings: {format_size(savings)} ({savings_pct:.1f}%)")

            # Post-processing stats
            dx10_stripped = getattr(self.processor, 'dx10_headers_stripped', 0)
            bgrx_converted = getattr(self.processor, 'bgrx_to_bgr24_converted', 0)
            if dx10_stripped > 0 or bgrx_converted > 0:
                self.log("\n=== Post-Processing ===")
                if dx10_stripped > 0:
                    self.log(f"DX10 headers stripped: {dx10_stripped} (cuttlefish BC output → legacy DDS)")
                if bgrx_converted > 0:
                    self.log(f"BGRX→BGR24 converted: {bgrx_converted} (32-bit padded → true 24-bit)")

            self.stats_label.config(text=f"Processed: {self.processed_count} | Savings: {savings_pct:.1f}%")
            self.progress_label.config(text="Complete!")
            messagebox.showinfo("Done", f"Processed {self.processed_count} files\nSavings: {savings_pct:.1f}%")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))
        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.process_btn.configure(state="normal")
            self.export_btn.configure(state="normal")


def main():
    root = tk.Tk()
    app = RegularTextureProcessorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
