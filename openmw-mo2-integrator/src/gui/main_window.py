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
class TextureCollision:
    """Represents a texture that would be incorrectly overwritten in Option B."""
    texture_rel_path: str  # e.g., "textures/rock.dds"
    optimized_mod: str  # Mod that was optimized (lower priority)
    winning_mod: str  # Mod that should win (higher priority, not optimized)
    optimized_mod_index: int
    winning_mod_index: int


@dataclass
class IntegrationPlan:
    """Plan for integrating optimizer outputs."""
    matches: list[ModMatch]
    unmatched_optimizer_folders: list[tuple[Path, str]]  # (path, type)
    mods_without_optimizations: list[str]
    # Option B collision detection
    collisions: list[TextureCollision] = None  # Populated for Option B
    files_to_skip: set[tuple[str, str]] = None  # (mod_name, rel_path) pairs to skip


class MO2IntegratorGUI:
    """GUI for MO2 texture optimizer integration."""

    WINDOW_WIDTH = 900
    WINDOW_HEIGHT = 1100

    # Fixed suffixes - do not change (needed for reliable purge/regeneration)
    REGULAR_SUFFIX = "_regular_map_optimizations"
    NORMAL_SUFFIX = "_normal_map_optimizations"

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
        self.integration_mode = tk.StringVar(value="option_b")

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
            "- Merges into a single timestamped mod folder (Option B)\n"
            "Option A is recommended for debugging, while Option B is recommended for users." 
        ), justify="left", wraplength=700).pack(anchor="w")

        # Option B (Recommended)
        frame_opt_b = ttk.LabelFrame(scrollable, text="Option B: Merged Optimizations (Recommended)", padding=10)
        frame_opt_b.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_opt_b, text=(
            "Creates a single mod folder with all optimized textures merged,\n"
            "named 'integrated_optimized_textures_YYYY_MM_DD_HH_MM_SS'.\n\n"
            "Respects load order (later mods overwrite earlier ones).\n"
            "Collision detection automatically skips textures that would\n"
            "incorrectly override higher-priority mods.\n\n"
            "Advantages:\n"
            "- Smallest disk usage (only winning textures kept)\n"
            "- Single mod to manage in MO2\n"
            "- Easy to enable/disable all optimizations at once\n"
            "- Multiple runs create separate timestamped folders\n\n"
            "Disadvantages:\n"
            "- All-or-nothing: can't disable per original mod.\n"
            " Note: If something DOES look bad, open the console, click the object in game,\n"
            " and then type ori to see what the texture is. You can then remove it from the override mod if it was in there."
        ), justify="left", wraplength=700).pack(anchor="w")

        # Option A
        frame_opt_a = ttk.LabelFrame(scrollable, text="Option A: Insert as Separate Mods (Power Users)", padding=10)
        frame_opt_a.pack(fill="x", padx=10, pady=5)
        ttk.Label(frame_opt_a, text=(
            "Creates new mod folders with suffixes (e.g., 'MyMod_regular_map_optimizations')\n"
            "and loads them after the original mod.\n\n"
            "This ensures optimized textures override the originals.\n\n"
            "Advantages:\n"
            "- Easy to enable/disable optimizations per mod\n"
            "- Useful for debugging texture issues\n"
            "- Maintains granular control over load order\n\n"
            "Disadvantages:\n"
            "- More mod entries in your list\n"
            "- Larger total disk usage\n"
            "- Writes to your modlist.txt (however a backup is created automatically)\n"
            "- Requires purging old optimization folders before re-running to avoid duplicates"
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

        ttk.Radiobutton(frame_mode, text="Option A: Insert as separate mods (for debugging/power users)",
                       variable=self.integration_mode, value="option_a").pack(anchor="w")
        ttk.Radiobutton(frame_mode, text="Option B: Merged optimizations folder (recommended)",
                       variable=self.integration_mode, value="option_b").pack(anchor="w", pady=(5, 0))

        # Option A Cleanup
        frame_cleanup = ttk.LabelFrame(scrollable, text="Option A Cleanup", padding=10)
        frame_cleanup.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_cleanup, text=(
            "If you've used Option A before and want to clean up, or are re-running Option A:\n"
            "Use the 'Purge' button in the Integrate tab BEFORE clicking Analyze.\n\n"
            "This removes folders and modlist entries matching these suffixes:"
        ), font=("", 8)).pack(anchor="w")

        ttk.Label(frame_cleanup, text=f"  Regular maps: {self.REGULAR_SUFFIX}\n"
                                      f"  Normal maps: {self.NORMAL_SUFFIX}",
                 font=("", 8)).pack(anchor="w", pady=(5, 0))

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

        self.purge_btn = ttk.Button(frame_buttons, text="Purge Only", command=self._start_purge)
        self.purge_btn.pack(side="left", padx=5)

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

    def _start_purge(self):
        """Start purge operation."""
        if self.processing:
            return

        # Validate minimal inputs for purge
        if not self.mo2_mods_dir.get():
            messagebox.showerror("Error", "Please select MO2 Mods directory")
            return

        if not Path(self.mo2_mods_dir.get()).is_dir():
            messagebox.showerror("Error", "MO2 Mods directory does not exist")
            return

        if not self.modlist_file.get():
            messagebox.showerror("Error", "Please select modlist.txt")
            return

        if not Path(self.modlist_file.get()).is_file():
            messagebox.showerror("Error", "modlist.txt does not exist")
            return

        # Confirm
        if not messagebox.askyesno("Confirm Purge",
            "This will DELETE all folders ending with:\n"
            f"  {self.REGULAR_SUFFIX}\n"
            f"  {self.NORMAL_SUFFIX}\n\n"
            "And remove their entries from modlist.txt.\n\n"
            "Continue?"):
            return

        self.processing = True
        self.analyze_btn.configure(state="disabled")
        self.execute_btn.configure(state="disabled")
        self.purge_btn.configure(state="disabled")
        self.clear_log()

        threading.Thread(target=self._run_purge, daemon=True).start()

    def _run_purge(self):
        """Execute purge operation."""
        try:
            mods_dir = Path(self.mo2_mods_dir.get())
            modlist_path = Path(self.modlist_file.get())

            self.log("=== Purging Optimization Folders ===\n")

            purged_count = 0
            purged_from_modlist = []

            for item in mods_dir.iterdir():
                if item.is_dir():
                    if item.name.endswith(self.REGULAR_SUFFIX) or item.name.endswith(self.NORMAL_SUFFIX):
                        self.log(f"  Removing: {item.name}")
                        shutil.rmtree(item)
                        purged_count += 1
                        purged_from_modlist.append(item.name)

            self.log(f"\nPurged {purged_count} folder(s)")

            # Also remove purged entries from modlist
            if purged_from_modlist:
                self.log("\nCleaning modlist.txt entries...")

                # Backup first
                timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
                backup_path = modlist_path.with_suffix(f".txt.{timestamp}")
                shutil.copy2(modlist_path, backup_path)
                self.log(f"  Backup: {backup_path.name}")

                with open(modlist_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                new_lines = []
                removed_entries = 0
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('+') or stripped.startswith('-'):
                        mod_name = stripped[1:]
                        if mod_name in purged_from_modlist:
                            removed_entries += 1
                            continue  # Skip this line
                    new_lines.append(line)

                with open(modlist_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                self.log(f"  Removed {removed_entries} modlist entries")

            self.log("\n=== Purge Complete ===")
            messagebox.showinfo("Success", f"Purged {purged_count} folder(s)")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            self.log(traceback.format_exc())
            messagebox.showerror("Error", str(e))

        finally:
            self.processing = False
            self.analyze_btn.configure(state="normal")
            self.purge_btn.configure(state="normal")

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
                    target_suffix=self.REGULAR_SUFFIX,
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
                    target_suffix=self.NORMAL_SUFFIX,
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
            mods_without_optimizations=mods_without,
            collisions=None,
            files_to_skip=None
        )

    def _detect_option_b_collisions(self, plan: IntegrationPlan) -> tuple[list[TextureCollision], set[tuple[str, str]]]:
        """
        Detect collisions for Option B where an optimized texture would incorrectly
        overwrite a higher-priority mod's texture.

        Returns:
            (collisions, files_to_skip) where files_to_skip is set of (mod_name, rel_path)
        """
        mods_dir = Path(self.mo2_mods_dir.get())

        self.log("Scanning for texture collisions...")
        self.progress_label.config(text="Building texture index...")
        self.root.update_idletasks()

        # Build index of which mods have which textures (from original mods folder)
        # mod_name -> set of relative texture paths (lowercase for comparison)
        mod_textures: dict[str, set[str]] = {}

        # Only scan enabled mods that are NOT in our optimization set
        optimized_mod_names = {m.original_name for m in plan.matches}

        # Get list of all enabled mods from modlist with their priority
        enabled_mods_with_priority = [
            (name, idx) for idx, (name, enabled) in enumerate(self.modlist_entries)
            if enabled and not name.endswith('_separator')
        ]

        # Scan original mods for texture files
        scanned = 0
        for mod_name, _ in enabled_mods_with_priority:
            mod_path = mods_dir / mod_name
            if not mod_path.is_dir():
                continue

            textures = set()
            # Look for texture files in the mod
            for tex_file in mod_path.rglob('*'):
                if tex_file.is_file() and tex_file.suffix.lower() in ('.dds', '.tga'):
                    rel_path = tex_file.relative_to(mod_path)
                    textures.add(str(rel_path).lower())

            if textures:
                mod_textures[mod_name] = textures

            scanned += 1
            if scanned % 50 == 0:
                self.progress_label.config(text=f"Scanning mods: {scanned}/{len(enabled_mods_with_priority)}")
                self.root.update_idletasks()

        self.log(f"  Scanned {scanned} mods, {sum(len(t) for t in mod_textures.values())} texture files indexed")

        # Now check each optimized texture against higher-priority mods
        collisions = []
        files_to_skip: set[tuple[str, str]] = set()

        # Build priority lookup: mod_name -> index (lower index = higher priority)
        mod_priority = {name: idx for idx, (name, _) in enumerate(self.modlist_entries)}

        for match in plan.matches:
            if not match.enabled_in_modlist:
                continue

            opt_mod_name = match.original_name
            opt_mod_priority = mod_priority.get(opt_mod_name, 9999)

            # Get all textures in this optimizer output
            for tex_file in match.optimizer_source.rglob('*'):
                if not tex_file.is_file():
                    continue
                if tex_file.suffix.lower() not in ('.dds', '.tga'):
                    continue

                rel_path = str(tex_file.relative_to(match.optimizer_source)).lower()

                # Check if any HIGHER priority mod (lower index) has this texture
                for other_mod_name, other_textures in mod_textures.items():
                    if other_mod_name == opt_mod_name:
                        continue  # Skip self

                    other_priority = mod_priority.get(other_mod_name, 9999)

                    # Only care if other mod is HIGHER priority (lower index)
                    if other_priority < opt_mod_priority:
                        if rel_path in other_textures:
                            # Collision detected!
                            collisions.append(TextureCollision(
                                texture_rel_path=rel_path,
                                optimized_mod=opt_mod_name,
                                winning_mod=other_mod_name,
                                optimized_mod_index=opt_mod_priority,
                                winning_mod_index=other_priority
                            ))
                            files_to_skip.add((opt_mod_name, rel_path))

        self.log(f"  Found {len(collisions)} collision(s)")
        return collisions, files_to_skip

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
                # For Option B, detect collisions first
                collisions, files_to_skip = self._detect_option_b_collisions(plan)
                plan.collisions = collisions
                plan.files_to_skip = files_to_skip
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
            self.log(f"      Overrides: {match.original_name} ({status})")

        if len(sorted_matches) > 20:
            self.log(f"  ... and {len(sorted_matches) - 20} more")

        self.log(f"\nWill update modlist.txt (backup will be created)")

    def _preview_option_b(self, plan: IntegrationPlan):
        """Preview Option B: Create merged optimizations folder."""
        mods_dir = Path(self.mo2_mods_dir.get())

        self.log(f"Will create new mod folder in: {mods_dir}")
        self.log(f"Folder name: integrated_optimized_textures_<timestamp>")

        # Show collision warnings FIRST if any
        if plan.collisions:
            self.log(f"\n=== COLLISION DETECTION ===")
            self.log(f"Found {len(plan.collisions)} texture(s) that would incorrectly override higher-priority mods.")
            self.log(f"These files will be SKIPPED to preserve correct load order:\n")

            # Group collisions by optimized mod for cleaner display
            by_mod: dict[str, list[TextureCollision]] = {}
            for c in plan.collisions:
                if c.optimized_mod not in by_mod:
                    by_mod[c.optimized_mod] = []
                by_mod[c.optimized_mod].append(c)

            for mod_name, mod_collisions in sorted(by_mod.items()):
                self.log(f"  {mod_name}: {len(mod_collisions)} file(s) skipped")
                for c in mod_collisions[:5]:
                    self.log(f"    - {c.texture_rel_path}")
                    self.log(f"      (would override '{c.winning_mod}' which has higher priority)")
                if len(mod_collisions) > 5:
                    self.log(f"    ... and {len(mod_collisions) - 5} more")

            self.log("")

        self.log(f"Processing order (later overwrites earlier):")

        # Sort by modlist index DESCENDING for Option B
        # (index 0 = highest priority = should be copied LAST to win)
        sorted_matches = sorted(plan.matches, key=lambda m: -m.modlist_index)

        for match in sorted_matches[:20]:
            status = "enabled" if match.enabled_in_modlist else "DISABLED - will skip"
            self.log(f"  [{match.optimizer_type}] {match.original_name} ({status})")

        if len(sorted_matches) > 20:
            self.log(f"  ... and {len(sorted_matches) - 20} more")

        # Count files to copy (excluding skipped)
        total_files = 0
        skipped_files = 0
        for match in plan.matches:
            if match.enabled_in_modlist:
                for f in match.optimizer_source.rglob('*'):
                    if f.is_file() and f.suffix.lower() in ('.dds', '.tga'):
                        rel_path = str(f.relative_to(match.optimizer_source)).lower()
                        if plan.files_to_skip and (match.original_name, rel_path) in plan.files_to_skip:
                            skipped_files += 1
                        else:
                            total_files += 1
                    elif f.is_file():
                        total_files += 1  # Non-texture files always copied

        self.log(f"\nFiles to copy: {total_files}")
        if skipped_files > 0:
            self.log(f"Files to skip (collision protection): {skipped_files}")

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

        # Build insertion map: original_mod_name -> list of new entries to insert BEFORE
        # (BEFORE = higher in file = higher priority = loads after = overrides original)
        insertion_map: dict[str, list[str]] = {}
        for original_name, new_name, _ in copied_mods:
            if original_name not in insertion_map:
                insertion_map[original_name] = []
            insertion_map[original_name].append(f"+{new_name}")

        # Build new modlist
        new_lines = []
        for line in lines:
            # Check if this line matches a mod we need to insert BEFORE
            stripped = line.strip()
            if stripped.startswith('+') or stripped.startswith('-'):
                mod_name = stripped[1:]
                if mod_name in insertion_map:
                    for new_entry in insertion_map[mod_name]:
                        new_lines.append(f"{new_entry}\n")
                        self.log(f"  Inserted: {new_entry} before {mod_name}")

            new_lines.append(line)

        # Write new modlist
        with open(modlist_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        self.log(f"\nUpdated modlist.txt with {len(copied_mods)} new entries")
        self.log("\n[!] Refresh MO2: View > Refresh, press F5, or click the Refresh icon.")
        self.log("[!] Remind OpenMW: Sometimes you need to open the OpenMW Launcher from MO2 so it")
        self.log("    picks up new texture folders. Once opened, it should be fine. Then close and")
        self.log("    launch the executable as usual.")
        self.log("[!] Verify: Check your openmw.cfg for entries like:")
        self.log('    data="C:/YourMO2Install/mods/YourMod_regular_map_optimizations"')
        self.log("    Config location (MO2/OpenMW Plugin): YourMO2Install/profiles/YourProfile/openmw.cfg")

    def _execute_option_b(self, plan: IntegrationPlan):
        """Execute Option B: Create merged optimizations folder."""
        mods_dir = Path(self.mo2_mods_dir.get())
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        output_folder_name = f"integrated_optimized_textures_{timestamp}"
        output_dir = mods_dir / output_folder_name

        self.log("=== Executing Option B: Merged Optimizations ===\n")
        self.log(f"Creating merged folder: {output_folder_name}\n")

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Sort by modlist index DESCENDING
        # (index 0 = highest priority = loads last = should be copied LAST to win)
        sorted_matches = sorted(plan.matches, key=lambda m: -m.modlist_index)

        # Filter to enabled mods only
        enabled_matches = [m for m in sorted_matches if m.enabled_in_modlist]

        self.log(f"Processing {len(enabled_matches)} enabled mods (disabled mods skipped)")

        if plan.files_to_skip:
            self.log(f"Collision protection: {len(plan.files_to_skip)} file(s) will be skipped\n")
        else:
            self.log("")

        # Count total files (excluding skipped)
        total_files = 0
        skipped_count = 0
        for match in enabled_matches:
            for f in match.optimizer_source.rglob('*'):
                if f.is_file():
                    # Check if this file should be skipped
                    if f.suffix.lower() in ('.dds', '.tga') and plan.files_to_skip:
                        rel_path_lower = str(f.relative_to(match.optimizer_source)).lower()
                        if (match.original_name, rel_path_lower) in plan.files_to_skip:
                            skipped_count += 1
                            continue
                    total_files += 1

        self.progress_bar["maximum"] = total_files
        self.progress_bar["value"] = 0
        copied_count = 0
        actual_skipped = 0

        for match in enabled_matches:
            self.log(f"Processing: {match.original_name} [{match.optimizer_type}]")

            source_dir = match.optimizer_source
            for src_file in source_dir.rglob('*'):
                if src_file.is_file():
                    # Check if this file should be skipped (collision protection)
                    if src_file.suffix.lower() in ('.dds', '.tga') and plan.files_to_skip:
                        rel_path_lower = str(src_file.relative_to(source_dir)).lower()
                        if (match.original_name, rel_path_lower) in plan.files_to_skip:
                            actual_skipped += 1
                            continue

                    # Compute relative path from optimizer output root
                    rel_path = src_file.relative_to(source_dir)
                    dst_file = output_dir / rel_path

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
        if actual_skipped > 0:
            self.log(f"Files skipped (collision protection): {actual_skipped}")

        self.log(f"\nCreated mod folder: {output_folder_name}")
        self.log("\n[!] Refresh MO2: View > Refresh, press F5, or click the Refresh icon.")
        self.log("[!] Toggle the mod ON in the left panel. It will be at the bottom (highest priority).")
        self.log("[!] Remind OpenMW: Sometimes you need to open the OpenMW Launcher from MO2 so it")
        self.log("    picks up new texture folders. Once opened, it should be fine. Then close and")
        self.log("    launch the executable as usual.")
        self.log("[!] Verify: Check your openmw.cfg for entries like:")
        self.log('    data="C:/YourMO2Install/mods/YourMod_regular_map_optimizations"')
        self.log("    Config location (MO2/OpenMW Plugin): YourMO2Install/profiles/YourProfile/openmw.cfg")


def main():
    root = tk.Tk()
    app = MO2IntegratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
