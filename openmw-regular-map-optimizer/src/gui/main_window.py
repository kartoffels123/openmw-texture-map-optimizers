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

        # UI Variables
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.target_format = tk.StringVar(value="BC1/DXT1")
        self.resize_method = tk.StringVar(value="CUBIC (Recommended)")
        self.scale_factor = tk.DoubleVar(value=1.0)
        self.max_resolution = tk.IntVar(value=2048)
        self.min_resolution = tk.IntVar(value=256)
        self.uniform_weighting = tk.BooleanVar(value=False)
        self.use_dithering = tk.BooleanVar(value=False)
        self.use_small_texture_override = tk.BooleanVar(value=True)
        self.small_texture_threshold = tk.IntVar(value=128)
        self.enable_parallel = tk.BooleanVar(value=True)
        self.max_workers = tk.IntVar(value=max(1, cpu_count() - 1))
        self.enforce_power_of_2 = tk.BooleanVar(value=True)
        self.allow_well_compressed_passthrough = tk.BooleanVar(value=True)
        self.enable_tga_support = tk.BooleanVar(value=True)
        self.use_path_whitelist = tk.BooleanVar(value=True)
        self.use_path_blacklist = tk.BooleanVar(value=True)
        self.custom_blacklist = tk.StringVar(value="")
        self.enable_atlas_downscaling = tk.BooleanVar(value=False)
        self.atlas_max_resolution = tk.IntVar(value=4096)

        self.create_widgets()

        # Attach change callbacks
        for var in [self.target_format, self.resize_method, self.scale_factor,
                    self.max_resolution, self.min_resolution, self.uniform_weighting,
                    self.use_dithering, self.use_small_texture_override,
                    self.small_texture_threshold, self.allow_well_compressed_passthrough,
                    self.enable_atlas_downscaling, self.atlas_max_resolution,
                    self.enforce_power_of_2, self.use_path_whitelist, self.use_path_blacklist,
                    self.custom_blacklist, self.enable_tga_support]:
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
            "- Passthrough for well-compressed textures (BC1/BC2/BC3 with mipmaps)\n"
            "- TGA to DDS conversion\n"
            "- Mipmap regeneration for textures missing mipmaps\n\n"
            "RUN DRY RUN FIRST to see what will happen before processing."
        )
        ttk.Label(frame, text=info, justify="left", wraplength=self.WRAPLENGTH).pack(anchor="w")

    def _create_settings_tab(self, parent):
        """Create settings tab"""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_basic = ttk.Frame(notebook)
        tab_filtering = ttk.Frame(notebook)
        notebook.add(tab_basic, text="Basic")
        notebook.add(tab_filtering, text="Filtering")

        self._create_basic_settings(tab_basic)
        self._create_filtering_settings(tab_filtering)

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

        # Format
        frame_format = ttk.LabelFrame(scrollable, text="Format Options", padding=10)
        frame_format.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_format, text="Target format:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_format, textvariable=self.target_format,
                    values=["BC1/DXT1", "BC2/DXT3", "BC3/DXT5", "BGRA", "BGR"],
                    state="readonly", width=20).grid(row=0, column=1, padx=10)
        ttk.Label(frame_format, text="(BC1 for no alpha, BC3 for alpha)",
                 font=("", 8)).grid(row=0, column=2, sticky="w")

        # Resize
        frame_resize = ttk.LabelFrame(scrollable, text="Downscale Options", padding=10)
        frame_resize.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_resize, text="Downscale Factor:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.scale_factor,
                    values=[0.125, 0.25, 0.5, 1.0], state="readonly", width=20).grid(row=0, column=1, padx=10)

        ttk.Label(frame_resize, text="Max Resolution:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.max_resolution,
                    values=[0, 256, 512, 1024, 2048, 4096], state="readonly", width=20).grid(row=1, column=1, padx=10)

        ttk.Label(frame_resize, text="Min Resolution:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(frame_resize, textvariable=self.min_resolution,
                    values=[0, 128, 256, 512], state="readonly", width=20).grid(row=2, column=1, padx=10)

        # Passthrough
        frame_pass = ttk.LabelFrame(scrollable, text="Passthrough", padding=10)
        frame_pass.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_pass, text="Allow well-compressed textures to passthrough",
                       variable=self.allow_well_compressed_passthrough).pack(anchor="w")
        ttk.Label(frame_pass, text="BC1/BC2/BC3 with proper mipmaps are copied as-is",
                 font=("", 8)).pack(anchor="w")

        # TGA
        frame_tga = ttk.LabelFrame(scrollable, text="TGA Support", padding=10)
        frame_tga.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_tga, text="Enable TGA file support",
                       variable=self.enable_tga_support).pack(anchor="w")

        # Parallel
        frame_parallel = ttk.LabelFrame(scrollable, text="Parallel Processing", padding=10)
        frame_parallel.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_parallel, text="Enable parallel processing",
                       variable=self.enable_parallel).pack(anchor="w")
        ttk.Label(frame_parallel, text="Max workers:").pack(side="left", padx=(20, 5))
        ttk.Combobox(frame_parallel, textvariable=self.max_workers,
                    values=list(range(1, cpu_count() + 1)), state="readonly", width=10).pack(side="left")

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

        # Whitelist
        frame_white = ttk.LabelFrame(scrollable, text="Path Whitelist", padding=10)
        frame_white.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_white, text="Only process paths containing 'Textures'",
                       variable=self.use_path_whitelist).pack(anchor="w")

        # Blacklist
        frame_black = ttk.LabelFrame(scrollable, text="Path Blacklist", padding=10)
        frame_black.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(frame_black, text="Skip paths containing 'icon', 'icons', 'bookart'",
                       variable=self.use_path_blacklist).pack(anchor="w")
        ttk.Label(frame_black, text="Custom blacklist (comma-separated):").pack(anchor="w", pady=(10, 0))
        ttk.Entry(frame_black, textvariable=self.custom_blacklist, width=50).pack(anchor="w", pady=5)

        # Excluded
        frame_excluded = ttk.LabelFrame(scrollable, text="Always Excluded", padding=10)
        frame_excluded.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_excluded, text="Files ending in _n.dds, _N.dds, _nh.dds, _NH.dds\n"
                 "(Use Normal Map Optimizer for these)").pack(anchor="w")

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
        content = self.log_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showwarning("Warning", "No log content")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="analysis_report.txt")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            messagebox.showinfo("Success", f"Saved to {path}")

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
        blacklist = ["icon", "icons", "bookart"] if self.use_path_blacklist.get() else []
        custom = [x.strip() for x in self.custom_blacklist.get().split(",") if x.strip()]

        settings = RegularSettings(
            target_format=self.target_format.get(),
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
            enable_tga_support=self.enable_tga_support.get(),
        )
        settings.path_whitelist = whitelist
        settings.path_blacklist = blacklist
        settings.custom_blacklist = custom
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
                return

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
                'tga_conversion': [], 'alpha_preserved': []
            }
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
                if r.has_alpha and r.target_format in ('BC3/DXT5', 'BGRA'):
                    action_groups['alpha_preserved'].append(r)
                if r.width and r.height and max(r.width, r.height) > 2048:
                    oversized_textures.append((r.relative_path, r.width, r.height))

                # Track conversions (non-passthrough)
                if not r.is_passthrough:
                    key = (r.format, r.target_format, will_resize)
                    if key not in conversion_stats:
                        conversion_stats[key] = {'count': 0, 'files': []}
                    conversion_stats[key]['count'] += 1
                    conversion_stats[key]['files'].append(r.relative_path)

            # Current State
            self.log("\n=== Current State ===")
            self.log(f"Total size: {format_size(total_current)}")
            if len(results) > 0:
                self.log(f"Average size per file: {format_size(total_current // len(results))}")

            # Format Breakdown
            self.log("\n=== Format Breakdown (Current) ===")
            for fmt, stats in sorted(format_stats.items(), key=lambda x: -x[1]['count']):
                self.log(f"  {fmt}: {stats['count']} files, {format_size(stats['size'])} total")

            # Format Conversions
            if conversion_stats:
                self.log("\n=== Format Conversions ===")
                for (src_fmt, dst_fmt, has_resize), data in sorted(conversion_stats.items(), key=lambda x: -x[1]['count']):
                    resize_label = " + resize" if has_resize else ""
                    self.log(f"  {src_fmt} -> {dst_fmt}{resize_label}: {data['count']} files")

            # Conversion Examples
            if conversion_stats:
                self.log("\n=== Conversion Examples ===")
                for (src_fmt, dst_fmt, has_resize), data in sorted(conversion_stats.items(), key=lambda x: -x[1]['count'])[:5]:
                    resize_label = " + resize" if has_resize else ""
                    count = data['count']
                    self.log(f"{src_fmt} -> {dst_fmt}{resize_label}: {count} files")
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
                self.log(f"Files to pass through: {len(action_groups['passthrough'])} (copied as-is)")

            files_to_process = total_modify + len(action_groups['no_change'])
            self.log(f"\n{files_to_process} files will be processed with texconv.")
            self.log(f"{len(action_groups['passthrough'])} files will be copied as-is (well-compressed passthrough).")

            # Projection
            savings = total_current - total_projected
            savings_pct = (savings / total_current * 100) if total_current > 0 else 0

            self.log("\n=== Projected Output ===")
            self.log(f"Current: {format_size(total_current)}")
            self.log(f"Projected: {format_size(total_projected)}")
            self.log(f"Savings: {format_size(savings)} ({savings_pct:.1f}%)")

            # Issues & Auto-Fixes
            has_issues = (action_groups['missing_mipmaps'] or action_groups['tga_conversion'] or
                         action_groups['alpha_preserved'] or oversized_textures)

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

                if action_groups['alpha_preserved']:
                    self.log(f"\n[i] Auto-fix: {len(action_groups['alpha_preserved'])} file(s) with alpha channel preserved (using BC3/BGRA)")

                if oversized_textures:
                    max_res = settings.max_resolution
                    will_fix = [t for t in oversized_textures if max(t[1], t[2]) > max_res and max_res > 0]
                    if will_fix and max_res > 0:
                        self.log(f"\n[i] Auto-fix: {len(will_fix)} texture(s) larger than {max_res}px will be downscaled")
                        for path, w, h in will_fix[:3]:
                            self.log(f"      - {path} ({w}x{h})")
                        if len(will_fix) > 3:
                            self.log(f"      ... and {len(will_fix) - 3} more")
                    else:
                        self.log(f"\n[!] Resolution: {len(oversized_textures)} texture(s) larger than 2048px")
                        for path, w, h in oversized_textures[:5]:
                            self.log(f"      - {path} ({w}x{h})")
                        if len(oversized_textures) > 5:
                            self.log(f"      ... and {len(oversized_textures) - 5} more")
                        self.log("    Set 'Max Resolution' to auto-downscale if needed")

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

            self.log(f"Processing {len(all_files)} files...\n")
            self.progress_bar["maximum"] = len(all_files)
            self.progress_bar["value"] = 0

            def progress_cb(current, total, result):
                self.progress_bar["value"] = current
                self.progress_label.config(text=f"Processing {current}/{total}")
                if result.success:
                    self.processed_count += 1
                    self.total_input_size += result.input_size
                    self.total_output_size += result.output_size
                else:
                    self.failed_count += 1
                    self.log(f"Failed: {result.relative_path}")
                self.root.update_idletasks()

            self.processor.process_files(input_dir, output_dir, progress_cb)

            elapsed = time.time() - start_time
            savings = self.total_input_size - self.total_output_size
            savings_pct = (savings / self.total_input_size * 100) if self.total_input_size > 0 else 0

            self.log(f"\n=== Complete ({format_time(elapsed)}) ===")
            self.log(f"Processed: {self.processed_count}, Failed: {self.failed_count}")
            self.log(f"Savings: {format_size(savings)} ({savings_pct:.1f}%)")

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
