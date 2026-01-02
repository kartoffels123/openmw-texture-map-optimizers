# General User Guide

> Advanced users or mod authors should see subpage readmes.

## Prerequisites

- **Mod Organizer 2** modlist setup
- Running the optimizer on your **WHOLE Mods folder** (not individual mods)

### Understanding the Scope

| Input | Output | Covered in this guide? |
|-------|--------|------------------------|
| `MyMO2Install/Mods/` | `MyMO2Install/Mods_regular_maps_optimized/` | ✅ Yes |
| `MyMO2Install/Mods/MyCoolMod/` | `MyMO2Install/Mods/MyCoolMod_regular_maps_optimized/` | ❌ No |

---

## Running Regular Map Optimizer

1. **Input**: Your MO2 Mods folder
2. **Output**: Something like `Mods_regular_maps_optimized`
   - ⚠️ **DO NOT** put this inside your MO2 Mods folder
   - Recommended: Place it next to your Mods folder
   ```
   MyMO2Install/
   ├── Mods/
   └── Mods_regular_maps_optimized/   <-- Output goes here
   ```
3. **Change settings** as needed
   - Most users only need: **Max Resolution Ceiling** and **Downscale Factor**
4. **Dry Run and Analysis**
   - This may take a moment
   - Read the output — if you like the results, proceed; if not, go back to step 3
5. **Export Report** to your output folder
   - Name: `analysis_report.txt`
6. **Export Settings** to your output folder
   - Name: `settings.json`
7. **Process Files**
8. **Export Report** again to your output folder
   - Name: `analysis_report_results.txt`
   - ⚠️ Do not overwrite your `analysis_report.txt`

> **Note**: Exporting the Report and Settings is not required but highly recommended to keep track of what happened. It costs no time.

---

## Running Normal Map Optimizer

1. **Input**: Your MO2 Mods folder
2. **Output**: Something like `Mods_normal_maps_optimized`
   - ⚠️ **DO NOT** put this inside your MO2 Mods folder
   - Recommended: Place it next to your Mods folder
   ```
   MyMO2Install/
   ├── Mods/
   └── Mods_normal_maps_optimized/   <-- Output goes here
   ```
3. **Change settings** as needed
   - Most users only need: **Max Resolution Ceiling**, **Downscale Factor**, and **"Allow well-compressed textures to passthrough"**
4. **Dry Run and Analysis**
   - This may take a moment
   - Read the output — if you like the results, proceed; if not, go back to step 3
5. **Export Report** to your output folder
   - Name: `analysis_report.txt`
6. **Export Settings** to your output folder
   - Name: `settings.json`
7. **Process Files**
8. **Export Report** again to your output folder
   - Name: `analysis_report_results.txt`
   - ⚠️ Do not overwrite your `analysis_report.txt`

> **Note**: Exporting the Report and Settings is not required but highly recommended to keep track of what happened. It costs no time.

---

## Integration

Congratulations! You now have "optimized" copies of your modlist. Proceed to integration.

> ⚠️ **Important**: Integration ONLY works if you ran the optimizers on the MO2 Mods directory — not any subdirectory. For subdirectories, you probably already have the setup you want and can organize it manually.

### Remember

| Input | Output | Supported? |
|-------|--------|------------|
| `MyMO2Install/Mods/` | `MyMO2Install/Mods_regular_maps_optimized/` | ✅ Yes |
| `MyMO2Install/Mods/MyCoolMod/` | `MyMO2Install/Mods/MyCoolMod_regular_maps_optimized/` | ❌ No (already in the directory) |

### Integration Steps

1. **MO2 Mods Directory**: Your MO2 Mods Directory
   - Example: `MyMO2Install/Mods/`
2. **Profile modlist.txt**: Set to your profile's modlist
   - Example: `MyMO2Install/profiles/<ProfileName>/modlist.txt`
3. **Regular Map Optimizer Output** *(Optional)*: Your regular mods output folder
   - Example: `MyMO2Install/Mods_regular_maps_optimized`
4. **Normal Map Optimizer Output** *(Optional)*: Your normal mods output folder
   - Example: `MyMO2Install/Mods_normal_maps_optimized`
5. **Integration Mode**: For general users, **Option B** is recommended
   - Option A requires purging every time you re-run and takes up more disk space
6. **Purge old directories** *(Optional but recommended if you've run the program before)*
   - Removes directories ending in `_regular_map_optimizations` and `_normal_map_optimizations`
   - This cleans up the Mods directory
7. **Analyze**
8. **Execute**
9. **Follow the instructions** in the window after execution — it will tell you what to do

---

## Congratulations!

You've made it through the guide.

---

## Optional Cleanup

- **Keep the reports** from `Mods_normal_maps_optimized` and `Mods_regular_maps_optimized`
- Remove the rest of the contents of those folders to save space

---

## Troubleshooting

### "I don't like the results on a specific object"

If you have an issue with a specific object:

1. Open the console in-game (usually tilde `~`)
2. Click on the object
3. Type `ori` and press Enter
4. This will tell you the specific texture it's calling

If that texture is in one of your optimized folders, you can delete it to fall back to the original texture. This is why I recommend general users use **Option B**. Much easier to track down the texture in there.

### "It looks bad"

Delete `Mods_normal_maps_optimized` and `Mods_regular_maps_optimized`, then:

| Integration Mode | Cleanup Steps |
|------------------|---------------|
| **Option A** | Run the purge function in the MO2 integrator to clean up the loose files. Restart MO2 and open the OpenMW launcher to ensure complete purge. |
| **Option B** | Delete or disable `integrated_optimized_textures_YYYY_MM_DD_HH_MM_SS` in MO2. |

This will clean up everything. This is why I recommend casual users use **Option B**.

### "I still want optimizations but these are too aggressive or touched something I didn't want to touch"
1. Follow the advice for "It looks bad"
2. Try less aggressive settings
3. Read the analysis reports
4. You can exclude mods you don't want optimizations for by deleting them from `Mods_regular_maps_optimized` and `Mods_normal_maps_optimized`. Or you can target specific mods directly.

### "I think there is an error."

Open a bug report. Please include your COMPLETE LOGS.