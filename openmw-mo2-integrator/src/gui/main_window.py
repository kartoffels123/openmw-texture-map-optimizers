"""
GUI for OpenMW MO2 Integrator.
Integrates texture optimizer outputs into Mod Organizer 2 mod lists.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModMatch:
    """Represents a match between optimizer output and original mod."""
    original_name: str
    optimizer_source: Path
    optimizer_type: str  # 'regular' or 'normal'
    target_suffix: str
    enabled_in_modlist: bool
    modlist_index: int  # Position in modlist (0 = top/highest priority)


@dataclass
class IntegrationPlan:
    """Plan for integrating optimizer outputs."""
    matches: list[ModMatch]
    unmatched_optimizer_folders: list[tuple[Path, str]]  # (path, type)
    mods_without_optimizations: list[str]


class MO2IntegratorGUI:
    """GUI for MO2 texture optimizer integration."""

    WINDOW_WIDTH = 900
    WINDOW_HEIGHT = 750

    def __init__(self, root):
        self.root = root
        self.root.title("OpenMW MO2 Integrator")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # State
        self.processing = False
        self.integration_plan: Optional[IntegrationPlan] = None

        # Parsed modlist data
        self.modlist_entries: list[tuple[str, bool]] = []  # (name, enabled)
        self.modlist_path: Optional[Path] = None

        # UI Variables
        self.mo2_mods_dir = tk.StringVar()
        self.modlist_file = tk.StringVar()
        self.regular_maps_dir = tk.StringVar()
        self.normal_maps_dir = tk.StringVar()
        self.integration_mode = tk.StringVar(value="option_a")
        self.regular_suffix = tk.StringVar(value="_regular_map_optimizations")
        self.normal_suffix = tk.StringVar(value="_normal_map_optimizations")

        self.create_widgets()

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_help = ttk.Frame(notebook)
        tab_settings = ttk.Frame(notebook)
        tab_integrate = ttk.Frame(notebook)

        notebook.add(tab_help, text="Help")
        notebook.add(tab_settings, text="Settings")
        notebook.add(tab_integrate, text="Integrate")

        self._create_help_tab(tab_help)
        self._create_settings_tab(tab_settings)
        self._create_integrate_tab(tab_integrate)

    def _create_help_tab(self, parent):
        """Create help tab with instructions."""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # About
        frame_about = ttk.LabelFrame(scrollable, text="About", padding=10)
        frame_about.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_about, text=(
            "OpenMW MO2 Integrator\n\n"
            "This tool integrates the output of the OpenMW texture optimizers\n"
            "(Normal Map Optimizer and Regular Map Optimizer) into your\n"
            "Mod Organizer 2 setup.\n\n"
            "It matches optimizer output folders to your original mods and either:\n"
            "- Creates new mod entries in your load order (Option A)\n"
            "- Merges everything into the Overwrite folder (Option B)"
        ), justify="left", wraplength=700).pack(anchor="w")

        # Option A
        frame_opt_a = ttk.LabelFrame(scrollable, text="Option A: Insert as Separate Mods", padding=10)
        frame_opt_a.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_opt_a, text=(
            "Creates new mod folders with suffixes (e.g., 'MyMod_regular_map_optimizations')\n"
            "and inserts them into your modlist.txt right after the original mod.\n\n"
            "Advantages:\n"
            "- Non-destructive: original mods untouched\n"
            "- Easy to enable/disable optimizations per mod\n"
            "- Maintains granular control over load order\n\n"
            "Disadvantages:\n"
            "- More mod entries in your list\n"
            "- Larger total disk usage"
        ), justify="left", wraplength=700).pack(anchor="w")

        # Option B
        frame_opt_b = ttk.LabelFrame(scrollable, text="Option B: Merge to Overwrite", padding=10)
        frame_opt_b.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_opt_b, text=(
            "Copies all optimized textures into the MO2 Overwrite folder,\n"
            "respecting load order (later mods overwrite earlier ones).\n\n"
            "Advantages:\n"
            "- Smallest disk usage (only winning textures kept)\n"
            "- No modlist changes needed\n\n"
            "Disadvantages:\n"
            "- All-or-nothing: can't disable per mod\n"
            "- Overwrites existing Overwrite content\n"
            "- Harder to undo"
        ), justify="left", wraplength=700).pack(anchor="w")

        # Workflow
        frame_workflow = ttk.LabelFrame(scrollable, text="Workflow", padding=10)
        frame_workflow.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_workflow, text=(
            "1. Run the texture optimizers on your mods folder\n"
            "   - Output to separate folders (e.g., mods_regularmaps, mods_normalmaps)\n"
            "2. Open this tool and configure paths in Settings tab\n"
            "3. Go to Integrate tab and click 'Analyze'\n"
            "4. Review the preview to see what will happen\n"
            "5. Click 'Execute' to perform the integration\n\n"
            "Note: A backup of modlist.txt is created automatically (Option A only)"
        ), justify="left", wraplength=700).pack(anchor="w")

    def _create_settings_tab(self, parent):
        """Create settings tab."""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # MO2 Paths
        frame_mo2 = ttk.LabelFrame(scrollable, text="Mod Organizer 2 Paths", padding=10)
        frame_mo2.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_mo2, text="MO2 Mods Directory:").pack(anchor="w")
        frame_mods = ttk.Frame(frame_mo2)
        frame_mods.pack(fill="x", pady=(0, 10))
        ttk.Entry(frame_mods, textvariable=self.mo2_mods_dir, width=70).pack(side="left", padx=(0, 5))
        ttk.Button(frame_mods, text="Browse...", command=self._browse_mods_dir).pack(side="left")

        ttk.Label(frame_mo2, text="Profile modlist.txt:").pack(anchor="w")
        frame_modlist = ttk.Frame(frame_mo2)
        frame_modlist.pack(fill="x", pady=(0, 5))
        ttk.Entry(frame_modlist, textvariable=self.modlist_file, width=70).pack(side="left", padx=(0, 5))
        ttk.Button(frame_modlist, text="Browse...", command=self._browse_modlist).pack(side="left")

        ttk.Label(frame_mo2, text="Tip: modlist.txt is in profiles/<ProfileName>/",
                 font=("", 8)).pack(anchor="w")

        # Optimizer Output Paths
        frame_opt = ttk.LabelFrame(scrollable, text="Optimizer Output Directories", padding=10)
        frame_opt.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_opt, text="Regular Map Optimizer Output (optional):").pack(anchor="w")
        frame_reg = ttk.Frame(frame_opt)
        frame_reg.pack(fill="x", pady=(0, 10))
        ttk.Entry(frame_reg, textvariable=self.regular_maps_dir, width=70).pack(side="left", padx=(0, 5))
        ttk.Button(frame_reg, text="Browse...", command=self._browse_regular_dir).pack(side="left")

        ttk.Label(frame_opt, text="Normal Map Optimizer Output (optional):").pack(anchor="w")
        frame_norm = ttk.Frame(frame_opt)
        frame_norm.pack(fill="x", pady=(0, 5))
        ttk.Entry(frame_norm, textvariable=self.normal_maps_dir, width=70).pack(side="left", padx=(0, 5))
        ttk.Button(frame_norm, text="Browse...", command=self._browse_normal_dir).pack(side="left")

        ttk.Label(frame_opt, text="At least one optimizer output directory is required",
                 font=("", 8)).pack(anchor="w")

        # Integration Mode
        frame_mode = ttk.LabelFrame(scrollable, text="Integration Mode", padding=10)
        frame_mode.pack(fill="x", padx=10, pady=5)

        ttk.Radiobutton(frame_mode, text="Option A: Insert as separate mods (recommended)",
                       variable=self.integration_mode, value="option_a").pack(anchor="w")
        ttk.Radiobutton(frame_mode, text="Option B: Merge to Overwrite folder",
                       variable=self.integration_mode, value="option_b").pack(anchor="w", pady=(5, 0))

        # Suffixes (Option A only)
        frame_suffix = ttk.LabelFrame(scrollable, text="Mod Suffixes (Option A only)", padding=10)
        frame_suffix.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_suffix, text="Regular Map Suffix:").pack(anchor="w")
        ttk.Entry(frame_suffix, textvariable=self.regular_suffix, width=40).pack(anchor="w", pady=(0, 10))

        ttk.Label(frame_suffix, text="Normal Map Suffix:").pack(anchor="w")
        ttk.Entry(frame_suffix, textvariable=self.normal_suffix, width=40).pack(anchor="w")

    def _create_integrate_tab(self, parent):
        """Create integration tab."""
        # Progress
        frame_progress = ttk.LabelFrame(parent, text="Progress", padding=10)
        frame_progress.pack(fill="x", padx=10, pady=5)

        self.progress_label = ttk.Label(frame_progress, text="Ready - click Analyze to preview")
        self.progress_label.pack(anchor="w", pady=(0, 5))

        self.progress_bar = ttk.Progressbar(frame_progress, mode="determinate", length=400)
        self.progress_bar.pack(fill="x")

        # Log
        frame_log = ttk.LabelFrame(parent, text="Preview / Log", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(frame_log, height=20, width=80, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(frame_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Buttons
        frame_buttons = ttk.Frame(parent)
        frame_buttons.pack(pady=10)

        self.analyze_btn = ttk.Button(frame_buttons, text="Analyze", command=self._start_analysis)
        self.analyze_btn.pack(side="left", padx=5)

        self.execute_btn = ttk.Button(frame_buttons, text="Execute", command=self._start_execution,
                                      state="disabled")
        self.execute_btn.pack(side="left", padx=5)

    # Browse dialogs
    def _browse_mods_dir(self):
        d = filedialog.askdirectory(title="Select MO2 Mods Directory")
        if d:
            self.mo2_mods_dir.set(d)

    def _browse_modlist(self):
        f = filedialog.askopenfilename(title="Select modlist.txt",
                                        filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self.modlist_file.set(f)

    def _browse_regular_dir(self):
        d = filedialog.askdirectory(title="Select Regular Map Optimizer Output")
        if d:
            self.regular_maps_dir.set(d)

    def _browse_normal_dir(self):
        d = filedialog.askdirectory(title="Select Normal Map Optimizer Output")
        if d:
            self.normal_maps_dir.set(d)

    def log(self, message: str):
        """Append message to log."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def clear_log(self):
        """Clear the log."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _validate_inputs(self) -> bool:
        """Validate user inputs."""
        if not self.mo2_mods_dir.get():
            messagebox.showerror("Error", "Please select MO2 Mods directory")
            return False

        if not Path(self.mo2_mods_dir.get()).is_dir():
            messagebox.showerror("Error", "MO2 Mods directory does not exist")
            return False

        if not self.modlist_file.get():
            messagebox.showerror("Error", "Please select modlist.txt")
            return False

        if not Path(self.modlist_file.get()).is_file():
            messagebox.showerror("Error", "modlist.txt does not exist")
            return False

        has_regular = bool(self.regular_maps_dir.get()) and Path(self.regular_maps_dir.get()).is_dir()
        has_normal = bool(self.normal_maps_dir.get()) and Path(self.normal_maps_dir.get()).is_dir()

        if not has_regular and not has_normal:
            messagebox.showerror("Error", "Please select at least one optimizer output directory")
            return False

        return True

    def _parse_modlist(self) -> list[tuple[str, bool]]:
        """
        Parse modlist.txt and return list of (mod_name, enabled).
        Modlist is in reverse order (top = highest priority = loads last).
        """
        entries = []
        modlist_path = Path(self.modlist_file.get())

        with open(modlist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if line.startswith('+'):
                    entries.append((line[1:], True))
                elif line.startswith('-'):
                    entries.append((line[1:], False))
                # Skip lines without +/- prefix (shouldn't happen)

        return entries

    def _get_optimizer_folders(self, optimizer_dir: Path) -> set[str]:
        """Get set of folder names in optimizer output directory."""
        if not optimizer_dir or not optimizer_dir.is_dir():
            return set()

        folders = set()
        for item in optimizer_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Skip analysis report files
                if item.name.endswith('.txt') or item.name.endswith('.json'):
                    continue
                folders.add(item.name)
        return folders

    def _build_integration_plan(self) -> IntegrationPlan:
        """Build plan for integration."""
        regular_dir = Path(self.regular_maps_dir.get()) if self.regular_maps_dir.get() else None
        normal_dir = Path(self.normal_maps_dir.get()) if self.normal_maps_dir.get() else None

        regular_folders = self._get_optimizer_folders(regular_dir) if regular_dir else set()
        normal_folders = self._get_optimizer_folders(normal_dir) if normal_dir else set()

        # Parse modlist (reverse order: index 0 = highest priority)
        self.modlist_entries = self._parse_modlist()
        modlist_names = {entry[0]: (i, entry[1]) for i, entry in enumerate(self.modlist_entries)}

        matches = []
        matched_regular = set()
        matched_normal = set()

        # Match optimizer folders to modlist entries
        for mod_name, (index, enabled) in modlist_names.items():
            # Skip separators
            if mod_name.endswith('_separator'):
                continue

            # Check for regular map optimization
            if mod_name in regular_folders:
                matches.append(ModMatch(
                    original_name=mod_name,
                    optimizer_source=regular_dir / mod_name,
                    optimizer_type='regular',
                    target_suffix=self.regular_suffix.get(),
                    enabled_in_modlist=enabled,
                    modlist_index=index
                ))
                matched_regular.add(mod_name)

            # Check for normal map optimization
            if mod_name in normal_folders:
                matches.append(ModMatch(
                    original_name=mod_name,
                    optimizer_source=normal_dir / mod_name,
                    optimizer_type='normal',
                    target_suffix=self.normal_suffix.get(),
                    enabled_in_modlist=enabled,
                    modlist_index=index
                ))
                matched_normal.add(mod_name)

        # Find unmatched optimizer folders
        unmatched = []
        for folder in regular_folders - matched_regular:
            if not folder.endswith('.txt') and not folder.endswith('.json'):
                unmatched.append((regular_dir / folder, 'regular'))
        for folder in normal_folders - matched_normal:
            if not folder.endswith('.txt') and not folder.endswith('.json'):
                unmatched.append((normal_dir / folder, 'normal'))

        # Find mods without optimizations (informational only)
        all_matched = matched_regular | matched_normal
        mods_without = [name for name, _ in self.modlist_entries
                       if not name.endswith('_separator') and name not in all_matched]

        return IntegrationPlan(
            matches=matches,
            unmatched_optimizer_folders=unmatched,
            mods_without_optimizations=mods_without
        )

    def _start_analysis(self):
        """Start analysis in background thread."""
        if self.processing:
            return

        if not self._validate_inputs():
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.execute_btn.configure(state="disabled")
        self.clear_log()

        threading.Thread(target=self._run_analysis, daemon=True).start()

    def _run_analysis(self):
        """Run analysis and display preview."""
        try:
            self.log("=== Analyzing... ===\n")

            # Build integration plan
            self.integration_plan = self._build_integration_plan()
            plan = self.integration_plan

            # Summary
            regular_count = sum(1 for m in plan.matches if m.optimizer_type == 'regular')
            normal_count = sum(1 for m in plan.matches if m.optimizer_type == 'normal')

            self.log(f"Modlist entries: {len(self.modlist_entries)}")
            self.log(f"Matched optimizations: {len(plan.matches)}")
            self.log(f"  - Regular map: {regular_count}")
            self.log(f"  - Normal map: {normal_count}")

            if plan.unmatched_optimizer_folders:
                self.log(f"\nUnmatched optimizer folders: {len(plan.unmatched_optimizer_folders)}")
                for path, opt_type in plan.unmatched_optimizer_folders[:10]:
                    self.log(f"  - [{opt_type}] {path.name}")
                if len(plan.unmatched_optimizer_folders) > 10:
                    self.log(f"  ... and {len(plan.unmatched_optimizer_folders) - 10} more")

            # Mode-specific preview
            mode = self.integration_mode.get()
            self.log(f"\n=== Integration Mode: {'Option A (Insert Mods)' if mode == 'option_a' else 'Option B (Overwrite)'} ===\n")

            if mode == "option_a":
                self._preview_option_a(plan)
            else:
                self._preview_option_b(plan)

            self.log("\n=== Analysis Complete ===")
            self.log("Review the above and click 'Execute' to proceed.")

            if plan.matches:
                self.execute_btn.configure(state="normal")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))

        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")

    def _preview_option_a(self, plan: IntegrationPlan):
        """Preview Option A: Insert as separate mods."""
        mods_dir = Path(self.mo2_mods_dir.get())

        self.log("Will create new mod folders:")

        # Sort by modlist index to show in load order
        sorted_matches = sorted(plan.matches, key=lambda m: m.modlist_index)

        for match in sorted_matches[:20]:
            new_name = f"{match.original_name}{match.target_suffix}"
            target = mods_dir / new_name
            exists = " (EXISTS - will skip)" if target.exists() else ""
            status = "enabled" if match.enabled_in_modlist else "DISABLED"
            self.log(f"  [{match.optimizer_type}] {new_name}{exists}")
            self.log(f"      After: {match.original_name} ({status})")

        if len(sorted_matches) > 20:
            self.log(f"  ... and {len(sorted_matches) - 20} more")

        self.log(f"\nWill update modlist.txt (backup will be created)")
        self.log(f"New entries will be inserted after their original mods")

    def _preview_option_b(self, plan: IntegrationPlan):
        """Preview Option B: Merge to Overwrite."""
        mods_dir = Path(self.mo2_mods_dir.get())
        overwrite_dir = mods_dir.parent / "overwrite"

        self.log(f"Will copy textures to: {overwrite_dir}")
        self.log(f"\nProcessing order (later overwrites earlier):")

        # Sort by modlist index DESCENDING for Option B
        # (index 0 = highest priority = should be copied LAST to win)
        sorted_matches = sorted(plan.matches, key=lambda m: -m.modlist_index)

        for match in sorted_matches[:20]:
            status = "enabled" if match.enabled_in_modlist else "DISABLED - will skip"
            self.log(f"  [{match.optimizer_type}] {match.original_name} ({status})")

        if len(sorted_matches) > 20:
            self.log(f"  ... and {len(sorted_matches) - 20} more")

        # Count files to copy
        total_files = 0
        for match in plan.matches:
            if match.enabled_in_modlist:
                for _ in match.optimizer_source.rglob('*'):
                    total_files += 1

        self.log(f"\nTotal files to process: ~{total_files}")

    def _start_execution(self):
        """Start execution in background thread."""
        if self.processing:
            return

        if not self.integration_plan or not self.integration_plan.matches:
            messagebox.showerror("Error", "No matches to integrate. Run analysis first.")
            return

        # Confirm
        mode = self.integration_mode.get()
        count = len(self.integration_plan.matches)
        msg = f"This will integrate {count} optimization(s) using {'Option A' if mode == 'option_a' else 'Option B'}.\n\nContinue?"

        if not messagebox.askyesno("Confirm", msg):
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.execute_btn.configure(state="disabled")
        self.clear_log()

        threading.Thread(target=self._run_execution, daemon=True).start()

    def _run_execution(self):
        """Execute the integration."""
        try:
            mode = self.integration_mode.get()
            plan = self.integration_plan

            if mode == "option_a":
                self._execute_option_a(plan)
            else:
                self._execute_option_b(plan)

            self.log("\n=== Integration Complete ===")
            messagebox.showinfo("Success", "Integration completed successfully!")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))

        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.integration_plan = None  # Reset plan

    def _execute_option_a(self, plan: IntegrationPlan):
        """Execute Option A: Insert as separate mods."""
        mods_dir = Path(self.mo2_mods_dir.get())
        modlist_path = Path(self.modlist_file.get())

        self.log("=== Executing Option A: Insert as Separate Mods ===\n")

        # Step 1: Copy optimizer folders to mods directory
        self.log("Step 1: Copying optimizer output folders...\n")
        self.progress_bar["maximum"] = len(plan.matches)
        self.progress_bar["value"] = 0

        copied_mods = []  # Track what we successfully copied
        skipped = 0

        for i, match in enumerate(plan.matches):
            new_name = f"{match.original_name}{match.target_suffix}"
            target_dir = mods_dir / new_name

            if target_dir.exists():
                self.log(f"  SKIP (exists): {new_name}")
                skipped += 1
            else:
                self.log(f"  Copying: {match.optimizer_source.name} -> {new_name}")
                shutil.copytree(match.optimizer_source, target_dir)
                copied_mods.append((match.original_name, new_name, match.modlist_index))

            self.progress_bar["value"] = i + 1
            self.progress_label.config(text=f"Copying {i + 1}/{len(plan.matches)}")
            self.root.update_idletasks()

        self.log(f"\nCopied: {len(copied_mods)}, Skipped: {skipped}")

        if not copied_mods:
            self.log("\nNo new mods to add to modlist.")
            return

        # Step 2: Backup modlist
        self.log("\nStep 2: Backing up modlist.txt...")
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        backup_path = modlist_path.with_suffix(f".txt.{timestamp}")
        shutil.copy2(modlist_path, backup_path)
        self.log(f"  Backup: {backup_path.name}")

        # Step 3: Update modlist
        self.log("\nStep 3: Updating modlist.txt...")

        # Read current modlist
        with open(modlist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Build insertion map: original_mod_name -> list of new entries to insert after
        insertion_map: dict[str, list[str]] = {}
        for original_name, new_name, _ in copied_mods:
            if original_name not in insertion_map:
                insertion_map[original_name] = []
            insertion_map[original_name].append(f"+{new_name}")

        # Build new modlist
        new_lines = []
        for line in lines:
            new_lines.append(line)

            # Check if this line matches a mod we need to insert after
            stripped = line.strip()
            if stripped.startswith('+') or stripped.startswith('-'):
                mod_name = stripped[1:]
                if mod_name in insertion_map:
                    for new_entry in insertion_map[mod_name]:
                        new_lines.append(f"{new_entry}\n")
                        self.log(f"  Inserted: {new_entry} after {mod_name}")

        # Write new modlist
        with open(modlist_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        self.log(f"\nUpdated modlist.txt with {len(copied_mods)} new entries")

    def _execute_option_b(self, plan: IntegrationPlan):
        """Execute Option B: Merge to Overwrite."""
        mods_dir = Path(self.mo2_mods_dir.get())
        overwrite_dir = mods_dir.parent / "overwrite"

        self.log("=== Executing Option B: Merge to Overwrite ===\n")
        self.log(f"Target: {overwrite_dir}\n")

        # Create overwrite directory if it doesn't exist
        overwrite_dir.mkdir(parents=True, exist_ok=True)

        # Sort by modlist index DESCENDING
        # (index 0 = highest priority = loads last = should be copied LAST to win)
        sorted_matches = sorted(plan.matches, key=lambda m: -m.modlist_index)

        # Filter to enabled mods only
        enabled_matches = [m for m in sorted_matches if m.enabled_in_modlist]

        self.log(f"Processing {len(enabled_matches)} enabled mods (disabled mods skipped)\n")

        # Count total files
        total_files = 0
        for match in enabled_matches:
            for f in match.optimizer_source.rglob('*'):
                if f.is_file():
                    total_files += 1

        self.progress_bar["maximum"] = total_files
        self.progress_bar["value"] = 0
        copied_count = 0

        for match in enabled_matches:
            self.log(f"Processing: {match.original_name} [{match.optimizer_type}]")

            source_dir = match.optimizer_source
            for src_file in source_dir.rglob('*'):
                if src_file.is_file():
                    # Compute relative path from optimizer output root
                    rel_path = src_file.relative_to(source_dir)
                    dst_file = overwrite_dir / rel_path

                    # Create parent directories
                    dst_file.parent.mkdir(parents=True, exist_ok=True)

                    # Copy file (overwrites if exists)
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1

                    self.progress_bar["value"] = copied_count
                    if copied_count % 100 == 0:
                        self.progress_label.config(text=f"Copied {copied_count}/{total_files}")
                        self.root.update_idletasks()

        self.progress_label.config(text=f"Copied {copied_count} files")
        self.log(f"\nTotal files copied: {copied_count}")


def main():
    root = tk.Tk()
    app = MO2IntegratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
