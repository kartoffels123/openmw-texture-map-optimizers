"""
GUI layer for OpenMW Normal Map Optimizer.
Handles all tkinter UI logic, delegates processing to optimizer_core.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import webbrowser
import time
import json
from pathlib import Path
from multiprocessing import cpu_count

from src.core import (
    NormalMapProcessor,
    ProcessingSettings,
    ProcessingResult,
    AnalysisResult,
    format_size,
    format_time,
    get_parser_stats,
    reset_parser_stats
)


class NormalMapProcessorGUI:
    """GUI for Normal Map Processor"""

    WINDOW_WIDTH = 850
    WINDOW_HEIGHT = 1200
    WRAPLENGTH = 700

    def __init__(self, root):
        self.root = root
        self.root.title("Normal Map Processor")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # State
        self.processing = False
        self.total_input_size = 0
        self.total_output_size = 0
        self.processed_count = 0
        self.failed_count = 0
        self.processor = None  # Store processor instance to maintain cache

        # UI Variables
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
        self.use_small_texture_override = tk.BooleanVar(value=True)
        self.small_nh_threshold = tk.IntVar(value=256)
        self.small_n_threshold = tk.IntVar(value=128)
        self.enable_parallel = tk.BooleanVar(value=True)
        self.max_workers = tk.IntVar(value=max(1, cpu_count() - 1))
        self.chunk_size_mb = tk.IntVar(value=75)
        self.preserve_compressed_format = tk.BooleanVar(value=True)
        self.auto_fix_nh_to_n = tk.BooleanVar(value=True)
        self.auto_optimize_n_alpha = tk.BooleanVar(value=True)
        self.allow_compressed_passthrough = tk.BooleanVar(value=False)
        self.copy_passthrough_files = tk.BooleanVar(value=False)

        # Atlas settings
        self.enable_atlas_downscaling = tk.BooleanVar(value=False)
        self.atlas_max_resolution = tk.IntVar(value=4096)

        # Power-of-2 enforcement
        self.enforce_power_of_2 = tk.BooleanVar(value=True)

        self.create_widgets()

        # Attach change callbacks AFTER widgets are created to avoid triggering during init
        for var in [self.n_format, self.nh_format, self.resize_method, self.scale_factor,
                    self.max_resolution, self.min_resolution, self.invert_y, self.reconstruct_z,
                    self.uniform_weighting, self.use_dithering, self.use_small_texture_override,
                    self.small_nh_threshold, self.small_n_threshold, self.preserve_compressed_format,
                    self.auto_fix_nh_to_n, self.auto_optimize_n_alpha, self.allow_compressed_passthrough,
                    self.copy_passthrough_files, self.enable_atlas_downscaling, self.atlas_max_resolution,
                    self.enforce_power_of_2]:
            var.trace_add('write', self.invalidate_analysis_cache)

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_help = ttk.Frame(notebook)
        tab_settings = ttk.Frame(notebook)
        tab_process = ttk.Frame(notebook)

        notebook.add(tab_help, text="📖 READ THIS FIRST - Help & Documentation")
        notebook.add(tab_settings, text="⚙️ Settings")
        notebook.add(tab_process, text="▶️ Process Files")

        self._create_help_tab(tab_help)
        self._create_settings_tab(tab_settings)
        self._create_process_tab(tab_process)

    def _create_help_tab(self, tab_help):
        """Create the help/documentation tab with nested sub-tabs"""
        help_notebook = ttk.Notebook(tab_help)
        help_notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_about = ttk.Frame(help_notebook)
        tab_smart_format = ttk.Frame(help_notebook)
        tab_formats = ttk.Frame(help_notebook)

        help_notebook.add(tab_about, text="About & Guide")
        help_notebook.add(tab_smart_format, text="Smart Format Decision Flow")
        help_notebook.add(tab_formats, text="Format Reference")

        self._create_about_doc(tab_about)
        self._create_smart_format_doc(tab_smart_format)
        self._create_formats_doc(tab_formats)

    def _create_about_doc(self, parent):
        """Create the about/guide documentation sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # About section
        frame_info = ttk.LabelFrame(scrollable, text="About", padding=10)
        frame_info.pack(fill="x", padx=10, pady=5)

        info_text = (
            "OpenMW Normal Map Optimizer\n\n"
            "This tool optimizes, fixes, and compresses normal maps for OpenMW.\n\n"
            "If any of the text below doesn't make sense to you and you just want the game to run\n"
            "better, just use my default settings. On the Settings tab, the only thing\n"
            "I'd vary is setting Scale Factor from 1.0 to 0.5 if you want extra performance.\n\n"
            "⚠ DRY RUN IS NOW MANDATORY\n"
            "The 'Process Files' button is disabled until you run a dry run.\n"
            "Don't worry - it takes only seconds, even for 10,000+ files!\n"
            "This ensures you see what will happen and provides instant processing via caching.\n\n"
            "IMPORTANT NOTES:\n"
            "1. Your normal maps use DirectX-style (G=Y-), Not OpenGL-style (G=Y+).\n"
            "   I cannot auto-detect inverted Y - use the checkbox if needed.\n\n"
            "2. This tool is designed for:\n"
            "   • Compressing uncompressed textures (BGRA/BGR) - the primary use case\n"
            "   • \"Smart\" file optimization on already-compressed textures to avoid wasting space\n"
            "   • Fixing common errors (mislabeled formats, wasted alpha channels, broken mipmaps)\n"
            "   • Being minimally invasive while being highly configurable\n"
            "   • Running very fast with parallel processing support\n\n"
            "3. Compression and downscaling are LOSSY (you lose information). However,\n"
            "   75-95% space savings is nearly always worth it.\n\n"
            "WORKING WITH ALREADY-COMPRESSED TEXTURES:\n"
            "Already using BC3/BC1? The tool intelligently handles compressed textures:\n"
            "• Avoids accidentally converting to larger formats when NOT resizing\n"
            "  (BC3 → BGRA would be 4x larger with no benefit)\n"
            "• Preserves good compressed formats when not downscaling (enabled by default)\n"
            "• Auto-detects and fixes mislabeled textures (e.g., _NH files in BC5/BC1)\n"
            "• Auto-optimizes wasted space (e.g., N textures in BC3 → BC1 for half the size)\n"
            "• Regenerates mipmap chains (textures may have bad/missing mipmaps)\n"
            "• Reconstructs Z channels (sometimes missing or incorrect)\n\n"
            "Note on Recompression: Usually pretty harmless! \"Double compression\"\n"
            "produces nearly identical results (e.g., PSNR ~50 dB, MSE ~0.05) as long as\n"
            "no intermediate operation (e.g., resizing, color changes) is occurring.\n\n"
            "Want to avoid reprocessing entirely? Enable \"Allow well-compressed textures\n"
            "to passthrough\" in Settings > Smart Format Handling.\n\n"
            "Valid reasons to process already-compressed textures:\n"
            "• Resizing (downscaling/upscaling) - the main use case\n"
            "• Fixing broken mipmaps or Z channels - surprisingly common\n"
            "• Removing wasted space (N textures with unused alpha channels)\n\n"
            "Want to restore quality from heavily compressed BC3/BC1? You can't \"upgrade\"\n"
            "compressed textures by converting formats. Instead:\n"
            "1. Use chaiNNer with artifact removal models to restore detail\n"
            "2. Then use this tool to recompress to your preferred format\n\n"
            "FOR REGULAR USERS:\n"
            "These are edge cases mostly relevant to mod authors. If you just want vastly\n"
            "better performance with very little quality loss, the default settings will\n"
            "work fine.\n\n"
            "Still unsure? Use \"Dry Run\" to see what will happen before processing.\n"
            "It has a file-by-file breakdown and statistics at the bottom.\n\n"
            "FINAL CAVEAT:\n"
            "This is all my personal opinion and experience. I have compressed a lot of\n"
            "normal maps for a variety of games and done probably an unhealthy amount of\n"
            "work with the DDS filetype. You can do whatever you want if it makes sense\n"
            "to you. That's why I left in a bunch of options on the settings page.\n\n"
        )

        info_label = ttk.Label(frame_info, text=info_text, justify="left",
                              font=("", 9), wraplength=self.WRAPLENGTH)
        info_label.pack(anchor="w")

        links_frame = ttk.Frame(frame_info)
        links_frame.pack(anchor="w", pady=(5, 0))

        ttk.Label(links_frame, text="Resources:", font=("", 9, "bold")).pack(side="left")

        self._create_link(links_frame, "Normal Map Upscaling Models",
                         "https://openmodeldb.info/collections/c-normal-map-upscaling")
        ttk.Label(links_frame, text="|").pack(side="left", padx=5)
        self._create_link(links_frame, "chaiNNer FAQ", "https://openmodeldb.info/docs/faq")
        ttk.Label(links_frame, text="|").pack(side="left", padx=5)
        self._create_link(links_frame, "DXT Artifact Removal", "https://openmodeldb.info/models/1x-DEDXT")

    def _create_smart_format_doc(self, parent):
        """Create the smart format decision flow documentation sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Smart Format Handling Decision Flow
        frame_decision_flow = ttk.LabelFrame(scrollable, text="Smart Format Handling - Decision Flow", padding=10)
        frame_decision_flow.pack(fill="x", padx=10, pady=5)

        decision_flow_text = (
            "The tool applies format decisions in this priority order:\n\n"
            "Priority 0: Compressed Passthrough (if enabled - NOT RECOMMENDED)\n"
            "  ⚠ Well-compressed textures → Skip reprocessing entirely\n"
            "  ⚠ NH in BC3 → passthrough ✓ | N in BC5/BC1 → passthrough ✓\n"
            "  ⚠ NH in BC5/BC1 → passthrough + rename to _N ✓ (mislabeled)\n"
            "  ⚠ N in BC3 → reprocess (wasted alpha, not well-compressed)\n"
            "  ⚠ Skips Z-channel reconstruction and mipmap regeneration\n"
            "  ⚠ Use 'Copy passthrough files' to control output behavior\n\n"
            "Priority 1: Format Options (_N and _NH)\n"
            "  • NH textures → User's NH format (default: BC3/DXT5)\n"
            "  • N textures → User's N format (default: BC5/ATI2)\n\n"
            "Priority 2: Mislabeled NH→N textures (auto-fix)\n"
            "  • texture_NH.dds in BC5/BC1/BGR → Treated as N texture, uses N format\n"
            "  • Reason: These formats have no alpha channel\n\n"
            "Priority 3: Preserve compressed formats when not resizing\n"
            "  • Prevents converting BC1→BC5 (doubles file size, no quality gain)\n"
            "  • NH textures: Only BC3 preserved (has alpha)\n"
            "  • N textures: Only BC5 or BC1 preserved (no wasted alpha)\n"
            "  • BC3 N textures are NOT preserved (wasted alpha)\n"
            "  • Files still REPROCESSED for Z-reconstruction + mipmaps\n\n"
            "Priority 4: Auto-optimize formats with wasted alpha\n"
            "  • N textures in BGRA → User's N format (compress & remove alpha)\n"
            "  • N textures in BC3 → BC1 (half file size, same compression quality)\n\n"
            "Priority 5: Small texture override (only for uncompressed sources)\n"
            "  • NH ≤256px → BGRA (only if source is uncompressed)\n"
            "  • N ≤128px → BGR (only if source is uncompressed)\n"
            "  • Already-compressed small textures kept compressed\n"
            "  • Prevents decompressing small BC1/BC3/BC5 textures\n\n"
            "Example: N texture in BC3, not downscaling, small override disabled\n"
            "  → Step 1: BC5 (user N format)\n"
            "  → Step 2: No change (not NH)\n"
            "  → Step 3: NOT preserved (BC3 has wasted alpha for N)\n"
            "  → Step 4: BC1 (optimize BC3→BC1) ✓ FINAL\n"
            "  → Step 5: No change (not small)\n\n"
            "Example: NH texture in BC5, not downscaling\n"
            "  → Step 1: BC3 (user NH format)\n"
            "  → Step 2: BC5 → treated as N texture, format becomes BC5 ✓ FINAL\n"
            "  → Step 3: Preserved (BC5 is good for N)\n"
            "  → Step 4: No change (preserved)\n"
            "  → Step 5: No change (already compressed, kept compressed)\n\n"
            "Example: N texture in BC1, 64x64, not downscaling\n"
            "  → Step 1: BC5 (user N format)\n"
            "  → Step 2: No change (not NH)\n"
            "  → Step 3: Preserved (BC1 is good for N) ✓ FINAL\n"
            "  → Step 4: No change (preserved)\n"
            "  → Step 5: No change (already compressed, kept compressed even though small)"
        )

        decision_flow_label = ttk.Label(frame_decision_flow, text=decision_flow_text, justify="left",
                                        font=("Courier New", 8), wraplength=self.WRAPLENGTH)
        decision_flow_label.pack(anchor="w")

    def _create_formats_doc(self, parent):
        """Create the format reference documentation sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Format Reference
        frame_format_ref = ttk.LabelFrame(scrollable, text="Format Reference", padding=10)
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
        frame_size_comp = ttk.LabelFrame(scrollable, text="File Size Comparison (with mipmaps)", padding=10)
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
        """Create the settings tab with nested sub-tabs"""
        settings_notebook = ttk.Notebook(tab_settings)
        settings_notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_basic = ttk.Frame(settings_notebook)
        tab_advanced = ttk.Frame(settings_notebook)
        tab_smart_format = ttk.Frame(settings_notebook)

        settings_notebook.add(tab_basic, text="Basic Settings")
        settings_notebook.add(tab_advanced, text="Advanced")
        settings_notebook.add(tab_smart_format, text="Smart Format Handling")

        self._create_basic_settings(tab_basic)
        self._create_advanced_settings(tab_advanced)
        self._create_smart_format_settings(tab_smart_format)

    def _create_basic_settings(self, parent):
        """Create basic settings sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Directory Info
        frame_dir_info = ttk.LabelFrame(scrollable, text="⚠ Important: Directory Structure", padding=10)
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
        frame_input = ttk.LabelFrame(scrollable, text="Input Directory", padding=10)
        frame_input.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_input, textvariable=self.input_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_input, text="Browse...", command=self.browse_input).pack(side="left")

        # Output Directory
        frame_output = ttk.LabelFrame(scrollable, text="Output Directory", padding=10)
        frame_output.pack(fill="x", padx=10, pady=5)
        ttk.Entry(frame_output, textvariable=self.output_dir, width=50).pack(side="left", padx=5)
        ttk.Button(frame_output, text="Browse...", command=self.browse_output).pack(side="left")

        # Format Options
        frame_formats = ttk.LabelFrame(scrollable, text="Format Options", padding=10)
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

        # Downscale Options
        frame_resize = ttk.LabelFrame(scrollable, text="Downscale Options", padding=10)
        frame_resize.pack(fill="x", padx=10, pady=5)

        # Explanation section
        ttk.Label(frame_resize,
                 text="How Downscaling Works:",
                 font=("", 9, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))
        ttk.Label(frame_resize,
                 text="• Downscale Factor: Applies to ALL textures (e.g., 0.5 = half size, 1.0 = no resize)\n"
                      "• Max Resolution (Ceiling): Downscales textures LARGER than this - applies EVEN at 1.0 scale factor\n"
                      "• Min Resolution (Floor): Protects textures SMALLER than this - only applies when scale < 1.0 (e.g., 0.5, 0.25)\n\n"
                      "Example 1 (with downscaling): Factor 0.5, max 2048, min 256\n"
                      "  → 4096x4096 becomes 2048x2048 (capped by max), 512x512 becomes 256x256, 256x256 stays as-is (protected by min)\n"
                      "Example 2 (no downscaling): Factor 1.0, max 2048, min 256\n"
                      "  → 4096x4096 becomes 2048x2048 (capped by max), 512x512 stays as-is, min does nothing at 1.0",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Label(frame_resize, text="Downscale Method:").grid(row=2, column=0, sticky="w", pady=5)
        resize_combo = ttk.Combobox(frame_resize, textvariable=self.resize_method,
                                    values=[
                                        "CUBIC (Recommended - smooth surfaces + detail)",
                                        "FANT (Detail preservation - similar to Lanczos)",
                                        "BOX (Blurry, good for gradients)",
                                        "LINEAR (Fast, general purpose)"
                                    ], state="readonly", width=45)
        resize_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(frame_resize, text="Downscale Factor:").grid(row=3, column=0, sticky="w", pady=5)
        scale_combo = ttk.Combobox(frame_resize, textvariable=self.scale_factor,
                                   values=[0.125, 0.25, 0.5, 1.0], state="readonly", width=20)
        scale_combo.grid(row=3, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(1.0 = no downscaling unless max resolution set)",
                 font=("", 8, "italic")).grid(row=3, column=2, sticky="w")

        ttk.Label(frame_resize, text="Max Resolution (Ceiling):").grid(row=4, column=0, sticky="w", pady=5)
        max_res_combo = ttk.Combobox(frame_resize, textvariable=self.max_resolution,
                                     values=[0, 128, 256, 512, 1024, 2048, 4096, 8192],
                                     state="readonly", width=20)
        max_res_combo.grid(row=4, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(0 = disabled)",
                 font=("", 8, "italic")).grid(row=4, column=2, sticky="w", columnspan=2)

        ttk.Label(frame_resize, text="Min Resolution (Floor):").grid(row=5, column=0, sticky="w", pady=5)
        min_res_combo = ttk.Combobox(frame_resize, textvariable=self.min_resolution,
                                     values=[0, 128, 256, 512, 1024, 2048, 4096, 8192],
                                     state="readonly", width=20)
        min_res_combo.grid(row=5, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(frame_resize, text="(0 = disabled)",
                 font=("", 8, "italic")).grid(row=5, column=2, sticky="w", columnspan=2)

    def _create_advanced_settings(self, parent):
        """Create advanced settings sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Normal Map Options
        frame_normal_opts = ttk.LabelFrame(scrollable, text="Normal Map Options", padding=10)
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
        frame_small_tex = ttk.LabelFrame(scrollable, text="Small Texture Handling", padding=10)
        frame_small_tex.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_small_tex, text="Override format for small textures (recommended)",
                       variable=self.use_small_texture_override).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_small_tex,
                 text="Small textures benefit from uncompressed formats. This overrides your format settings for tiny UNCOMPRESSED textures. Already-compressed small textures (BC1/BC3/BC5) are kept compressed to avoid wasting disk space.",
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
        frame_parallel = ttk.LabelFrame(scrollable, text="Parallel Processing", padding=10)
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

        # Power-of-2 Enforcement
        frame_pow2 = ttk.LabelFrame(scrollable, text="Power-of-2 Enforcement", padding=10)
        frame_pow2.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_pow2, text="Enforce power-of-2 dimensions (recommended)",
                       variable=self.enforce_power_of_2).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_pow2,
                 text="Forces textures to power-of-2 dimensions (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, etc.).\n"
                      "This is the expected standard and prevents unwanted behavior with texture rendering.\n"
                      "⚠ Disabling this is NOT RECOMMENDED - while OpenMW supports NPOT (non-power-of-two) textures,\n"
                      "POT dimensions are the expected standard. Only disable if you have a specific reason.",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

    def _create_smart_format_settings(self, parent):
        """Create smart format handling sub-tab"""
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Smart Format Handling
        frame_smart_format = ttk.LabelFrame(scrollable, text="Smart Format Handling", padding=10)
        frame_smart_format.pack(fill="x", padx=10, pady=5)

        ttk.Checkbutton(frame_smart_format, text="Preserve compressed format when not downscaling (recommended)",
                       variable=self.preserve_compressed_format).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_smart_format,
                 text="When enabled, BC1/BC3/BC5 textures will keep their format if not being downscaled. Prevents unnecessary quality loss or file size increase.",
                 font=("", 8), wraplength=600, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(frame_smart_format, text="Auto-fix NH→N mislabeled textures (recommended)",
                       variable=self.auto_fix_nh_to_n).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_smart_format,
                 text="Textures labeled _NH but stored in BGR/BC5/BC1 (no alpha) will be treated as _N textures and use N format settings.",
                 font=("", 8), wraplength=600, justify="left").grid(row=3, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(frame_smart_format, text="Auto-optimize N textures with unused alpha (recommended)",
                       variable=self.auto_optimize_n_alpha).grid(row=4, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_smart_format,
                 text="N textures stored in BGRA→your N format setting (BC5/BC1/BGR) or BC3→BC1 to remove wasted alpha channel. Reduces file size without quality loss.",
                 font=("", 8), wraplength=600, justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(frame_smart_format, text="Allow well-compressed textures to passthrough (NOT recommended)",
                       variable=self.allow_compressed_passthrough).grid(row=6, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_smart_format,
                 text="⚠ When enabled, correctly-compressed textures skip reprocessing. NH in BC3 and N in BC5/BC1 pass through. Mislabeled NH in BC5/BC1 are renamed to _N. Only N in BC3 (wasted alpha) are reprocessed. Skips Z-channel reconstruction and mipmap regeneration. Use 'Copy passthrough files' below to control whether skipped files are copied to output or left in place.",
                 font=("", 8), wraplength=600, justify="left", foreground="red").grid(row=7, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(frame_smart_format, text="Copy passthrough files to output",
                       variable=self.copy_passthrough_files).grid(row=8, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_smart_format,
                 text="When enabled, passthrough files are copied to output directory. When disabled, they are skipped entirely (saves disk space, output only contains modified textures).",
                 font=("", 8), wraplength=600, justify="left").grid(row=9, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_smart_format, text="", font=("", 2)).grid(row=10, column=0, columnspan=3, sticky="w")

        ttk.Label(frame_smart_format,
                 text="Decision Priority Order:\n"
                      "0. Compressed passthrough (if enabled - copies well-compressed only)\n"
                      "   • NH in BC3 → passthrough ✓\n"
                      "   • N in BC5/BC1 → passthrough ✓\n"
                      "   • NH in BC5/BC1 → passthrough + rename to _N ✓\n"
                      "   • N in BC3 → reprocess (wasted alpha)\n"
                      "1. Format Options (_N and _NH)\n"
                      "2. Mislabeled NH→N textures\n"
                      "3. Preserve compressed formats when not downscaling\n"
                      "4. Auto-optimize formats with wasted alpha\n"
                      "5. Small texture override (only for uncompressed sources)",
                 font=("", 8), wraplength=600, justify="left").grid(row=11, column=0, columnspan=3, sticky="w", pady=(5, 2))

        # Texture Atlas Settings (Collapsible)
        frame_atlas = ttk.LabelFrame(scrollable, text="Texture Atlas Settings (Advanced)", padding=10)
        frame_atlas.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_atlas,
                 text="By default, texture atlases are automatically detected and protected from resizing.\n"
                      "Detection: Filename contains 'atlas' or path contains 'ATL' directory.\n"
                      "Atlases still receive format conversion, Z-reconstruction, and mipmap regeneration.",
                 font=("", 8), wraplength=600, justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(frame_atlas, text="Enable downscaling for texture atlases (NOT recommended)",
                       variable=self.enable_atlas_downscaling).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame_atlas,
                 text="⚠ Atlases are large for a reason - they pack many smaller textures into one file. Downscaling reduces detail for all packed textures.",
                 font=("", 8), wraplength=600, justify="left", foreground="red").grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_atlas, text="Max resolution for atlases:", font=("", 9)).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=5)
        atlas_max_combo = ttk.Combobox(frame_atlas, textvariable=self.atlas_max_resolution,
                                       values=[1024, 2048, 4096, 8192, 16384],
                                       state="readonly", width=15)
        atlas_max_combo.grid(row=3, column=1, sticky="w", pady=5)
        ttk.Label(frame_atlas,
                 text="Only applies if 'Enable downscaling for texture atlases' is checked. Default: 4096",
                 font=("", 8), wraplength=600, justify="left").grid(row=4, column=0, columnspan=3, sticky="w", pady=2)

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
        self.export_settings_btn = ttk.Button(button_frame, text="Export Settings", command=self.export_settings)
        self.export_settings_btn.pack(side="left", padx=5)
        self.process_btn = ttk.Button(button_frame, text="Process Files", command=self.start_processing, state="disabled")
        self.process_btn.pack(side="left", padx=5)

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

    def export_settings(self):
        """Export current settings to a JSON file for test verification"""
        file_path = filedialog.asksaveasfilename(
            title="Export Settings for Testing",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="optimizer_settings.json"
        )

        if file_path:
            try:
                settings = self.get_settings()
                settings_dict = settings.to_dict()

                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(settings_dict, f, indent=2)

                messagebox.showinfo("Success",
                    f"Settings exported to:\n{file_path}\n\n"
                    f"Use with test_verify_pipeline.py:\n"
                    f"python test_verify_pipeline.py <input> <output> --settings {Path(file_path).name}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export settings:\n{str(e)}")

    def invalidate_analysis_cache(self, *args):
        """Invalidate analysis cache when settings change"""
        if self.processor:
            self.processor = None
            self.process_btn.configure(state="disabled")

    def get_settings(self) -> ProcessingSettings:
        """Convert GUI variables to ProcessingSettings object"""
        return ProcessingSettings(
            n_format=self.n_format.get(),
            nh_format=self.nh_format.get(),
            scale_factor=self.scale_factor.get(),
            max_resolution=self.max_resolution.get(),
            min_resolution=self.min_resolution.get(),
            invert_y=self.invert_y.get(),
            reconstruct_z=self.reconstruct_z.get(),
            uniform_weighting=self.uniform_weighting.get(),
            use_dithering=self.use_dithering.get(),
            use_small_texture_override=self.use_small_texture_override.get(),
            small_nh_threshold=self.small_nh_threshold.get(),
            small_n_threshold=self.small_n_threshold.get(),
            resize_method=self.resize_method.get(),
            enable_parallel=self.enable_parallel.get(),
            max_workers=self.max_workers.get(),
            chunk_size_mb=self.chunk_size_mb.get(),
            preserve_compressed_format=self.preserve_compressed_format.get(),
            auto_fix_nh_to_n=self.auto_fix_nh_to_n.get(),
            auto_optimize_n_alpha=self.auto_optimize_n_alpha.get(),
            allow_compressed_passthrough=self.allow_compressed_passthrough.get(),
            copy_passthrough_files=self.copy_passthrough_files.get(),
            enable_atlas_downscaling=self.enable_atlas_downscaling.get(),
            atlas_max_resolution=self.atlas_max_resolution.get(),
            enforce_power_of_2=self.enforce_power_of_2.get()
        )

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
        self.processed_count = 0
        self.failed_count = 0
        self.stats_label.config(text="Processing...")

        threading.Thread(target=self.process_files, daemon=True).start()

    def analyze_files(self):
        """Run analysis using core processor"""
        start_time = time.time()
        try:
            reset_parser_stats()  # Reset statistics at start of dry run
            settings = self.get_settings()

            # Create new processor instance (invalidates old cache)
            self.processor = NormalMapProcessor(settings)

            input_dir = Path(self.input_dir.get())
            self.log("=== Dry Run (Preview) ===\n")

            # Log analysis mode info
            self.log("Note: First dry run reads all file headers (may take a minute for large datasets).")
            self.log("Subsequent runs use cached data and are nearly instant.\n")

            # Define progress callback
            def progress_callback(current, total):
                pass  # Analysis results are logged in batch below

            results = self.processor.analyze_files(input_dir, progress_callback)

            if not results:
                self.log("No normal map files found!")
                messagebox.showinfo("Dry Run Complete", "No normal map files found")
                return

            # Count files
            n_count = sum(1 for r in results if not r.is_nh)
            nh_count = sum(1 for r in results if r.is_nh)
            self.log(f"Found {len(results)} normal map files ({n_count} _n.dds, {nh_count} _nh.dds)\n")

            # Analyze results
            total_current_size = sum(r.file_size for r in results)
            total_projected_size = sum(r.projected_size for r in results if not r.error)
            format_stats = {}
            oversized_textures = []
            oversized_will_fix = []
            undersized_textures = []
            undersized_will_fix = []
            all_warnings = []
            all_info_messages = []

            action_groups = {
                'resize_and_reformat': [],
                'resize_only': [],
                'reformat_only': [],
                'no_change': [],
                'passthrough': []
            }

            for i, result in enumerate(results, 1):
                if result.error:
                    self.log(f"[{i}/{len(results)}] Error analyzing {result.relative_path}: {result.error}")
                    continue

                # Update format stats
                if result.format not in format_stats:
                    format_stats[result.format] = {'count': 0, 'size': 0}
                format_stats[result.format]['count'] += 1
                format_stats[result.format]['size'] += result.file_size

                # Check size warnings and whether they'll be auto-fixed
                if result.width and result.height:
                    max_dim = max(result.width, result.height)
                    min_dim = min(result.width, result.height)
                    will_resize = (result.new_width != result.width) or (result.new_height != result.height)

                    if max_dim > 2048:
                        oversized_textures.append((result.relative_path, result.width, result.height))
                        if will_resize and max(result.new_width, result.new_height) <= 2048:
                            oversized_will_fix.append((result.relative_path, result.width, result.height))

                    if min_dim < 256:
                        undersized_textures.append((result.relative_path, result.width, result.height))
                        if will_resize and min(result.new_width, result.new_height) >= 256:
                            undersized_will_fix.append((result.relative_path, result.width, result.height))

                    # Categorize action
                    will_resize = (result.new_width != result.width) or (result.new_height != result.height)
                    will_reformat = result.format != result.target_format

                    # Check if this is a passthrough file (will be copied as-is)
                    is_passthrough = any('Compressed passthrough' in w for w in (result.warnings or []))

                    if is_passthrough:
                        action_groups['passthrough'].append(
                            (result.relative_path, result.width, result.height, result.format)
                        )
                    elif will_resize and will_reformat:
                        action_groups['resize_and_reformat'].append(
                            (result.relative_path, result.width, result.height, result.format,
                             result.new_width, result.new_height, result.target_format)
                        )
                    elif will_resize:
                        action_groups['resize_only'].append(
                            (result.relative_path, result.width, result.height, result.format,
                             result.new_width, result.new_height)
                        )
                    elif will_reformat:
                        action_groups['reformat_only'].append(
                            (result.relative_path, result.width, result.height, result.format, result.target_format)
                        )
                    else:
                        action_groups['no_change'].append(
                            (result.relative_path, result.width, result.height, result.format)
                        )

                # Collect warnings/info for this file (log summary later, not per-file)
                if result.warnings:
                    for warning in result.warnings:
                        # Categorize as info or warning
                        if any(keyword in warning for keyword in ['auto-fixed', 'auto-optimized', 'preserved']):
                            all_info_messages.append((result.relative_path, warning))
                        else:
                            all_warnings.append((result.relative_path, warning))

            # Build detailed conversion summary
            format_conversions = {}  # (source_format, target_format) -> count (actual format changes only)
            resize_conversions = {}  # (original_size, new_size) -> count
            reprocessing_only = {}  # (format) -> count (same format, reprocessed for Z/mipmaps)
            combined_conversions = {}  # (source_fmt, target_fmt, resize_type) -> [file_list]

            for result in results:
                if result.error:
                    continue

                will_resize = (result.new_width != result.width) or (result.new_height != result.height)
                will_reformat = result.format != result.target_format
                is_passthrough = any('Compressed passthrough' in w for w in (result.warnings or []))

                # Track actual format conversions only
                if will_reformat:
                    key = (result.format, result.target_format)
                    format_conversions[key] = format_conversions.get(key, 0) + 1

                # Track same-format reprocessing (Z-reconstruction, mipmaps)
                # Exclude passthrough files (they are copied as-is, not reprocessed)
                if not will_reformat and not will_resize and not is_passthrough:
                    if result.format not in reprocessing_only:
                        reprocessing_only[result.format] = 0
                    reprocessing_only[result.format] += 1

                # Track resize conversions
                if result.width and result.new_width:
                    if will_resize:
                        resize_key = (f"{result.width}x{result.height}", f"{result.new_width}x{result.new_height}")
                        resize_conversions[resize_key] = resize_conversions.get(resize_key, 0) + 1

                # Track combined conversions for detailed breakdown
                # Only store first 5 examples to avoid memory/performance issues with large datasets
                resize_type = "resize" if will_resize else "no_resize"
                combo_key = (result.format, result.target_format, resize_type)
                if combo_key not in combined_conversions:
                    combined_conversions[combo_key] = {'count': 0, 'examples': []}
                combined_conversions[combo_key]['count'] += 1
                if len(combined_conversions[combo_key]['examples']) < 5:
                    combined_conversions[combo_key]['examples'].append(result.relative_path)

            # Display stats
            self.log("\n=== Current State ===")
            self.log(f"Total size: {format_size(total_current_size)}")
            if len(results) > 0:
                self.log(f"Average size per file: {format_size(total_current_size // len(results))}")

            self.log("\n=== Format Breakdown (Current) ===")
            for fmt, stats in sorted(format_stats.items()):
                self.log(f"{fmt}: {stats['count']} files, {format_size(stats['size'])} total")

            # Show format conversion summary (actual conversions only)
            if format_conversions:
                self.log("\n=== Format Conversions ===")
                # Use combined_conversions to show resize info
                for (src_fmt, dst_fmt, resize_type), data in sorted(combined_conversions.items(),
                                                                      key=lambda x: -x[1]['count']):
                    # Only show actual format conversions (not same-format reprocessing)
                    if src_fmt != dst_fmt:
                        resize_label = " + resize" if resize_type == "resize" else ""
                        self.log(f"{src_fmt} → {dst_fmt}{resize_label}: {data['count']} files")

            # Show reprocessing summary (same format, Z-reconstruction + mipmaps)
            if reprocessing_only:
                total_reprocessed = sum(reprocessing_only.values())
                self.log(f"\n=== Reprocessing ({total_reprocessed} files, same format) ===")
                for fmt, count in sorted(reprocessing_only.items(), key=lambda x: -x[1]):
                    self.log(f"  {fmt}: {count} files")
                self.log("\nNote: Files will be reprocessed for Z-reconstruction + mipmap regeneration.")

            # Show resize summary
            if resize_conversions:
                self.log("\n=== Resolution Changes ===")
                # Group by scale factor
                scale_groups = {}
                for (src_res, dst_res), count in resize_conversions.items():
                    src_w, src_h = map(int, src_res.split('x'))
                    dst_w, dst_h = map(int, dst_res.split('x'))
                    scale = dst_w / src_w
                    scale_str = f"{scale:.2f}x" if scale != 1.0 else "unchanged"
                    if scale_str not in scale_groups:
                        scale_groups[scale_str] = []
                    scale_groups[scale_str].append((src_res, dst_res, count))

                for scale_str, conversions in sorted(scale_groups.items()):
                    total_in_group = sum(c[2] for c in conversions)
                    self.log(f"\n{scale_str} scaling ({total_in_group} files):")
                    for src_res, dst_res, count in sorted(conversions, key=lambda x: -x[2]):
                        self.log(f"  {src_res} → {dst_res}: {count} files")

            # Show detailed conversion breakdown with examples (exclude same-format no-resize reprocessing)
            actual_conversions = {k: v for k, v in combined_conversions.items()
                                 if k[0] != k[1] or k[2] == "resize"}  # Include if format changes OR resizing

            if actual_conversions and len(actual_conversions) <= 15:  # Only show if not too many categories
                self.log("\n=== Conversion Examples ===")
                for (src_fmt, dst_fmt, resize_type), data in sorted(actual_conversions.items(), key=lambda x: -x[1]['count']):
                    count = data['count']
                    examples = data['examples']
                    resize_label = " + resize" if resize_type == "resize" else ""
                    self.log(f"{src_fmt} → {dst_fmt}{resize_label}: {count} files")
                    # Show examples (we stored max 5)
                    for f in examples[:3]:
                        self.log(f"    • {f}")
                    if count > 3:
                        self.log(f"    ... and {count - 3} more")

            # Show actions summary
            self.log("\n=== Summary ===")
            total_with_changes = len(action_groups['resize_and_reformat']) + len(action_groups['resize_only']) + len(action_groups['reformat_only'])
            if total_with_changes > 0:
                self.log(f"Files to modify: {total_with_changes}")
                if len(action_groups['resize_and_reformat']) > 0:
                    self.log(f"  • Resize + Convert: {len(action_groups['resize_and_reformat'])}")
                if len(action_groups['resize_only']) > 0:
                    self.log(f"  • Resize only: {len(action_groups['resize_only'])}")
                if len(action_groups['reformat_only']) > 0:
                    self.log(f"  • Convert only: {len(action_groups['reformat_only'])}")

            if len(action_groups['no_change']) > 0:
                self.log(f"Files to recalculate: {len(action_groups['no_change'])} (same format/size, Z-fix + mipmaps)")

            if len(action_groups['passthrough']) > 0:
                copy_passthrough = self.copy_passthrough_files.get()
                if copy_passthrough:
                    self.log(f"Files to pass through: {len(action_groups['passthrough'])} (will be copied)")
                else:
                    self.log(f"Files to pass through: {len(action_groups['passthrough'])} (will be skipped)")

            # Update the final message to exclude passthrough files
            files_to_process = len(results) - len(action_groups['passthrough'])
            if files_to_process > 0:
                self.log(f"\n{files_to_process} files will receive Z-reconstruction + mipmap regeneration.")
            if len(action_groups['passthrough']) > 0:
                copy_passthrough = self.copy_passthrough_files.get()
                if copy_passthrough:
                    self.log(f"{len(action_groups['passthrough'])} files already optimized (will be copied to output).")
                else:
                    self.log(f"{len(action_groups['passthrough'])} files already optimized (will be skipped, not in output).")

            # Projection
            savings = total_current_size - total_projected_size
            savings_percent = (savings / total_current_size * 100) if total_current_size > 0 else 0

            self.log("\n=== Projected Output (with current settings) ===")
            self.log(f"Projected total size: {format_size(total_projected_size)}")
            self.log(f"Estimated savings: {format_size(savings)} ({savings_percent:.1f}%)")

            # Combine info and warnings into single issues section
            has_issues = all_info_messages or oversized_textures or undersized_textures or all_warnings

            if has_issues:
                self.log("\n=== Issues & Auto-Fixes ===")

            # Show automatic optimizations first (these are good things)
            if all_info_messages:
                info_groups = {}
                for path, info in all_info_messages:
                    if info not in info_groups:
                        info_groups[info] = []
                    info_groups[info].append(path)

                for info, paths in info_groups.items():
                    self.log(f"\nℹ Auto-fix: {info}")
                    self.log(f"   Affects {len(paths)} file(s)")
                    if len(paths) <= 3:
                        for path in paths:
                            self.log(f"     • {path}")
                    else:
                        for path in paths[:3]:
                            self.log(f"     • {path}")
                        self.log(f"     ... and {len(paths) - 3} more")

                self.log("\n   (Disable in Settings > Smart Format Handling if needed)")

            # Show warnings (things user might want to address)
            if oversized_textures or undersized_textures or all_warnings:
                if all_info_messages:
                    self.log("")  # Blank line separator

            # Display conversion/format warnings
            if all_warnings:
                self.log(f"\n⚠ Found {len(all_warnings)} format/conversion warning(s):")
                warning_groups = {}
                for path, warning in all_warnings:
                    if warning not in warning_groups:
                        warning_groups[warning] = []
                    warning_groups[warning].append(path)

                for warning, paths in warning_groups.items():
                    self.log(f"\n  {warning}:")
                    for path in paths[:3]:
                        self.log(f"    • {path}")
                    if len(paths) > 3:
                        self.log(f"    ... and {len(paths) - 3} more files")

            if oversized_textures:
                if len(oversized_will_fix) == len(oversized_textures):
                    # All will be fixed
                    self.log(f"\nℹ Auto-fix: {len(oversized_textures)} texture(s) larger than 2048px will be downscaled")
                    for path, w, h in oversized_textures[:3]:
                        self.log(f"     • {path} ({w}x{h})")
                    if len(oversized_textures) > 3:
                        self.log(f"     ... and {len(oversized_textures) - 3} more")
                elif len(oversized_will_fix) > 0:
                    # Some will be fixed
                    unfixed = len(oversized_textures) - len(oversized_will_fix)
                    self.log(f"\nℹ Auto-fix: {len(oversized_will_fix)} of {len(oversized_textures)} oversized textures will be downscaled")
                    self.log(f"⚠  {unfixed} will remain larger than 2048px - adjust 'Max Resolution' if needed")
                else:
                    # None will be fixed
                    self.log(f"\n⚠ Resolution: {len(oversized_textures)} texture(s) larger than 2048px")
                    for path, w, h in oversized_textures[:5]:
                        self.log(f"     • {path} ({w}x{h})")
                    if len(oversized_textures) > 5:
                        self.log(f"     ... and {len(oversized_textures) - 5} more")
                    self.log("   → Enable 'Max Resolution: 2048' to auto-downscale (except texture atlases)")

            if undersized_textures:
                if len(undersized_will_fix) > 0:
                    # Some will be upscaled (unusual but possible)
                    self.log(f"\nℹ Auto-fix: {len(undersized_will_fix)} of {len(undersized_textures)} undersized textures will be upscaled")
                    unfixed = len(undersized_textures) - len(undersized_will_fix)
                    if unfixed > 0:
                        self.log(f"⚠  {unfixed} will remain smaller than 256px")
                else:
                    # Show as info only if user is downscaling
                    settings = self.get_settings()
                    if settings.scale_factor < 1.0:
                        if settings.min_resolution > 0:
                            self.log(f"\nℹ Protection: {len(undersized_textures)} texture(s) smaller than {settings.min_resolution}px will not be downscaled")
                            for path, w, h in undersized_textures[:5]:
                                self.log(f"     • {path} ({w}x{h})")
                            if len(undersized_textures) > 5:
                                self.log(f"     ... and {len(undersized_textures) - 5} more")
                            self.log(f"   → Protected by 'Min Resolution: {settings.min_resolution}' setting (prevents over-compression)")
                        else:
                            self.log(f"\n⚠ Resolution: {len(undersized_textures)} texture(s) smaller than 256px")
                            for path, w, h in undersized_textures[:5]:
                                self.log(f"     • {path} ({w}x{h})")
                            if len(undersized_textures) > 5:
                                self.log(f"     ... and {len(undersized_textures) - 5} more")
                            self.log("   → Set 'Min Resolution: 256' to prevent over-compression when downscaling")

            self.stats_label.config(
                text=f"Current: {format_size(total_current_size)} → Projected: {format_size(total_projected_size)} ({savings_percent:.1f}% savings)"
            )

            elapsed_time = time.time() - start_time
            self.log(f"\n=== Analysis Complete ({format_time(elapsed_time)}) ===")

            # Show parser statistics (only if there were fallbacks)
            fast_hits, texdiag_fallbacks = get_parser_stats()
            if texdiag_fallbacks > 0:
                self.log(f"Note: {texdiag_fallbacks} file(s) used texdiag fallback")

            messagebox.showinfo("Dry Run Complete",
                f"Current: {format_size(total_current_size)}\n"
                f"Projected: {format_size(total_projected_size)}\n"
                f"Estimated savings: {savings_percent:.1f}%")

        except Exception as e:
            self.log(f"\nError: {str(e)}")
            messagebox.showerror("Error", f"Dry run failed: {str(e)}")
            # Don't enable process button on error
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.export_btn.configure(state="normal")
        else:
            # Only enable process button on successful analysis
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.process_btn.configure(state="normal")
            self.export_btn.configure(state="normal")

    def process_files(self):
        """Run processing using core processor"""
        start_time = time.time()
        try:
            # Check if analysis has been run
            if not self.processor:
                messagebox.showerror("Error",
                    "You must run 'Dry Run (Analysis)' before processing.\n\n"
                    "This ensures optimal performance by caching file metadata.")
                return

            input_dir = Path(self.input_dir.get())
            output_dir = Path(self.output_dir.get())

            n_files, nh_files = self.processor.find_normal_maps(input_dir)
            total_files = len(n_files) + len(nh_files)

            self.log(f"Found {len(nh_files)} _nh.dds file(s)")
            self.log(f"Found {len(n_files)} _n.dds file(s)")
            self.log(f"Total: {total_files} normal map file(s)\n")

            if total_files == 0:
                messagebox.showinfo("No Files", "No normal map files found")
                return

            # Initialize progress
            self.progress_bar["maximum"] = total_files
            self.progress_bar["value"] = 0

            # Batch GUI updates for performance
            last_update_time = time.time()
            last_update_count = 0
            pending_logs = []

            # Define progress callback
            def progress_callback(current, total, result: ProcessingResult):
                nonlocal last_update_time, last_update_count, pending_logs

                self.total_input_size += result.input_size

                if result.success:
                    self.total_output_size += result.output_size
                    self.processed_count += 1

                    if result.orig_dims and result.new_dims:
                        orig_w, orig_h = result.orig_dims
                        new_w, new_h = result.new_dims
                        size_change = result.output_size - result.input_size
                        size_change_str = f"+{format_size(size_change)}" if size_change > 0 else format_size(size_change)

                        pending_logs.append(f"✓ {result.relative_path}")
                        pending_logs.append(f"  {orig_w}×{orig_h} {result.orig_format} → {new_w}×{new_h} {result.new_format} | "
                                f"{format_size(result.input_size)} → {format_size(result.output_size)} ({size_change_str})")
                    else:
                        pending_logs.append(f"✓ Completed: {result.relative_path}")
                else:
                    self.failed_count += 1
                    error_msg = result.error_msg or 'Unknown error'
                    pending_logs.append(f"✗ Failed: {result.relative_path} - {error_msg}")

                # Update GUI periodically (every 2 seconds)
                current_time = time.time()
                should_update = (
                    current_time - last_update_time >= 2.0 or  # Every 2 seconds
                    current == total  # Always update on last file
                )

                if should_update:
                    # Flush pending logs
                    if pending_logs:
                        self.log('\n'.join(pending_logs))
                        pending_logs.clear()

                    # Update progress
                    self.progress_bar["value"] = current
                    self.progress_label.config(text=f"Processed {current}/{total} files")

                    # Update UI
                    self.root.update_idletasks()

                    last_update_time = current_time
                    last_update_count = current

            # Process files
            if self.processor.settings.enable_parallel and total_files > 1:
                self.log(f"Using parallel processing: {self.processor.settings.max_workers} workers, {self.processor.settings.chunk_size_mb}MB chunks\n")
            else:
                self.log("Using sequential processing\n")

            # This will use cached analysis data automatically
            self.processor.process_files(input_dir, output_dir, progress_callback)

            self.progress_label.config(text="Processing complete!")

            # Display final stats
            elapsed_time = time.time() - start_time
            total = self.processed_count + self.failed_count
            savings = self.total_input_size - self.total_output_size
            savings_percent = (savings / self.total_input_size * 100) if self.total_input_size > 0 else 0

            stats_msg = f"Files: {self.processed_count}/{total} successful | {format_size(self.total_input_size)} → {format_size(self.total_output_size)} | Saved: {format_size(savings)} ({savings_percent:.1f}%)"
            self.stats_label.config(text=stats_msg)

            self.log("\n=== Processing Complete ===")
            self.log(f"Found {len(nh_files)} _nh.dds file(s)")
            self.log(f"Found {len(n_files)} _n.dds file(s)")
            self.log(f"Total: {total_files} normal map file(s)")
            self.log(f"Successful: {self.processed_count}")
            self.log(f"Failed: {self.failed_count}")
            self.log(f"Space savings: {format_size(savings)} ({savings_percent:.1f}%)")
            self.log(f"Time taken: {format_time(elapsed_time)}")
            if total > 0:
                avg_time = elapsed_time / total
                self.log(f"Average per file: {format_time(avg_time)}")

            if self.failed_count > 0:
                messagebox.showwarning("Completed with errors", f"Processing completed with {self.failed_count} failed file(s)\n\n{stats_msg}")
            else:
                messagebox.showinfo("Success", f"Processing completed!\n\n{stats_msg}")

        except Exception as e:
            self.log(f"\nError: {str(e)}")
            messagebox.showerror("Error", f"Processing failed: {str(e)}")
        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.process_btn.configure(state="normal")


def main():
    """Entry point for GUI application"""
    root = tk.Tk()
    app = NormalMapProcessorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
