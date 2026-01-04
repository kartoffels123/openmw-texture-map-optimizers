# OpenMW MO2 Integrator v0.1

Integrates the output of the OpenMW texture optimizers (Normal Map Optimizer and Regular Map Optimizer) into your Mod Organizer 2 setup.

## Quick Start

1. **Install Python** from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation
2. **Double-click** `OpenMW MO2 Integrator.bat` to launch
3. **Configure** your MO2 Mods directory and modlist.txt paths
4. **Select** your optimizer output directories
5. **Choose** an integration mode (Merged recommended)
6. **Run Integration**

## Overview

After running the texture optimizers on your MO2 Mods folder, you'll have separate output directories containing optimized textures. This tool:

1. Matches optimizer output folders to your original mods
2. Respects your load order
3. Integrates the optimized textures into MO2

---

## Requirements

- MO2 Mods directory path
- Profile `modlist.txt` path (found in `profiles/<ProfileName>/modlist.txt`)
- At least one optimizer output directory (regular maps and/or normal maps)

---

## Integration Modes

### Option A: Insert as Separate Mods (Power Users)

Creates new mod folders with suffixes and inserts them into your modlist:
- `MyMod` → `MyMod_regular_map_optimizations`
- `MyMod` → `MyMod_normal_map_optimizations`

**Advantages:**
- Easy to enable/disable optimizations per mod
- Useful for debugging texture issues
- Maintains granular control over load order

**Disadvantages:**
- More mod entries in your list
- Larger total disk usage
- Modifies your `modlist.txt` (backup created automatically)
- Requires purging old optimization folders before re-running

---

### Option B: Merged Optimizations (Recommended)

Creates a single mod folder with all optimized textures merged:
`integrated_optimized_textures_YYYY_MM_DD_HH_MM_SS`

**Advantages:**
- Smallest disk usage (only winning textures kept)
- Single mod to manage in MO2
- Easy to enable/disable all optimizations at once
- Multiple runs create separate timestamped folders
- Does not modify `modlist.txt`

**Disadvantages:**
- All-or-nothing: can't disable per original mod
- See [Troubleshooting](#troubleshooting) for fixing individual textures

---

## Collision Detection (Option B)

Option B includes automatic collision detection. If an optimized texture would incorrectly override a higher-priority mod's texture, it is **skipped**.

Example:
- `ModA` (high priority) has `textures/rock.dds`
- `ModB` (low priority) also has `textures/rock.dds` and was optimized

Without collision detection, the optimized `ModB` texture would override `ModA`, breaking your intended load order. The integrator detects this and skips the conflicting file.

---

## Purge Function

The **Purge** button removes all previously created optimization folders and their modlist entries:
- Folders ending in `_regular_map_optimizations`
- Folders ending in `_normal_map_optimizations`

**When to use:**
- Before re-running Option A
- To clean up after switching from Option A to Option B
- To completely remove all optimizations

---

## Post-Integration Steps

After integration completes, you must:

1. **Refresh MO2**: `View > Refresh`, press `F5`, or click the Refresh icon
2. **Enable the mod** (Option B): Toggle the new mod ON in the left panel
3. **Remind OpenMW**: Open the OpenMW Launcher from MO2 once so it picks up new texture folders
4. **Verify**: Check your `openmw.cfg` for entries like:
   ```
   data="C:/YourMO2Install/mods/integrated_optimized_textures_2024_01_01_12_00_00"
   ```
   Config location: `YourMO2Install/profiles/YourProfile/openmw.cfg`

---

## Troubleshooting

### Fixing a single bad texture (Option B)

1. Open the console in-game (usually tilde `~`)
2. Click on the problematic object
3. Type `ori` and press Enter
4. This shows the texture path being used
5. Navigate to `integrated_optimized_textures_*` folder
6. Delete the specific texture file
7. The game will fall back to the original

### Complete removal

**Option A:**
1. Use the Purge function
2. Restart MO2
3. Open the OpenMW Launcher to ensure complete purge

**Option B:**
1. Delete or disable `integrated_optimized_textures_*` in MO2
2. Optionally delete the folder from disk

---

## Technical Details

### Load Order Processing

- MO2's `modlist.txt` lists mods in priority order (top = highest priority = loads last)
- Option A inserts optimization mods **before** the original in the file (higher priority)
- Option B copies files in reverse priority order (highest priority copied last = wins)

---

## Installation

### Requirements
- Python 3.7 or later
- Windows

### Setup
1. **Download/Clone** this repository
2. **Install Python** from [python.org](https://www.python.org/downloads/)
   - During installation, check "Add Python to PATH"
3. **Verify installation** by opening Command Prompt and typing:
   ```
   python --version
   ```
   You should see something like `Python 3.13.x`

### Running the Application
Simply double-click **`OpenMW MO2 Integrator.bat`**

If Python is not installed or not in PATH, the batch file will show helpful error messages.

---

## Project Structure

```
openmw-mo2-integrator/
├── OpenMW MO2 Integrator.bat    # Launch this!
├── integrator.py                 # Main entry point
├── src/
│   └── gui.py                    # GUI implementation
└── example_mo2_structure/        # Reference MO2 structure
```

---

## Version History

### Version 0.1 (Current)
- Initial release
- Two integration modes: Separate Mods and Merged Optimizations
- Automatic collision detection for merged mode
- Load order respect from MO2's modlist.txt
- Purge function for cleanup
- Automatic modlist.txt backup

---

## Resources

- [Mod Organizer 2](https://www.modorganizer.org/) - Mod management tool
- [OpenMW](https://openmw.org/) - Open source Morrowind engine