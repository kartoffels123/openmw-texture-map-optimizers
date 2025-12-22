# OpenMW Normal Map Optimizer

This tool optimizes, fixes, and compresses normal maps for OpenMW.

## About

If any of the text below doesn't make sense to you and you just want the game to run better, just use the default settings. On the Settings tab, the only thing I'd vary is setting Scale Factor from 1.0 to 0.5 if you want extra performance.

**⚠ ALWAYS DO A DRY RUN.**

### Important Assumptions

1. **Your normal maps use DirectX-style (G=Y-)**, not OpenGL-style (G=Y+).
   I cannot auto-detect inverted Y - use the checkbox if needed.

2. **You have UNCOMPRESSED normal maps.** This tool is designed to compress uncompressed textures.

   **Already using BC3/BC1?** The main thing to avoid is accidentally converting to larger formats when NOT resizing:
   - BC3 → BGRA: 4x larger files with no quality improvement
   - BC3 → BC5: Same file size, but artifacts remain (no benefit)
   - BC3 → BC3: Surprisingly pretty harmless! "double compression" produces nearly identical results (e.g. PSNR ~64 dB, MSE ~0.03)

   **Why does the tool reprocess BC3/BC1 files?** It fixes technical issues:
   - Regenerates mipmap chains (textures may have bad/missing mipmaps)
   - Reconstructs Z channels (this is sometimes missing)

   **Valid reasons to process already-compressed textures:**
   - **Resizing** (downscaling/upscaling) - the main use case
   - **Fixing broken mipmaps or Z channels** - surprisingly common

   **Want to restore quality from heavily compressed BC3/BC1?** You can't "upgrade" compressed textures by converting formats. Instead:
   1. Use chaiNNer with artifact removal models to restore detail
   2. Then use this tool to recompress to your preferred format

   **Note for regular users:** These are edge cases mostly relevant to mod authors. If you just want vastly better performance with very little quality loss, the default settings will work fine.

   Still unsure? Use "Dry Run" to see what will happen before processing. It has a file by file breakdown and statistics at the bottom.

3. **Compression and downsampling are LOSSY** (you lose information). However, 75-95% space savings is nearly always worth it.

4. **Z-channel reconstruction:** Many normal map generators output 2-channel (RG only) maps, expecting BC5/ATI2 or R8G8 formats. OpenMW will ONLY compute Z on-the-fly for BC5/ATI2 and R8G8 formats. For all other formats (BC3/DXT5, BC1/DXT1, BGRA, BGR), you MUST have Z pre-computed in the file. This tool can reconstruct Z = sqrt(1 - X² - Y²) for those formats that need RGB stored explicitly (enabled by default, toggle in settings if you already have Z computed).

### Final Caveat

This is all my personal opinion and experience. I have compressed a lot of normal maps for a variety of games and done probably an unhealthy amount of work with the DDS filetype. You can do whatever you want if it makes sense to you. That's why I left in a bunch of options on the settings page.

### Resources

- [Normal Map Upscaling Models](https://openmodeldb.info/collections/c-normal-map-upscaling)
- [chaiNNer FAQ](https://openmodeldb.info/docs/faq)
- [DXT Artifact Removal](https://openmodeldb.info/models/1x-DEDXT)

## Requirements

- Python 3.x installed on your system

## Setup

1. Install Python from [python.org](https://www.python.org/downloads/)
2. Ensure the following files are in the same folder:
   - `texconv.exe`
   - `texdiag.exe`
   - `openmw_normalmap_optimizer.py`
   - `run_openmw_normalmap_optimizer.bat`

## Usage

Run `run_openmw_normalmap_optimizer.bat` to start the application.

The GUI has four tabs:
- **📖 READ THIS FIRST - Help & Documentation** - Essential information about formats, recommendations, and technical details
- **⚙️ Settings** - Configure input/output directories, formats, resize options, and processing parameters
- **▶️ Process Files** - Run dry runs and process your normal maps
- **📋 Version Info** - See current version features and known issues

## Features (Version 0.3)

- Batch processing of normal maps (`_N.dds` and `_NH.dds`)
- Preserves nested directory structures
- Format conversion (BC5, BC3/DXT5, BC1/DXT1, BGRA, BGR)
- Resolution scaling and constraints
- Z-channel reconstruction for proper normal mapping
- Y flip normal map conversion (OpenGL to DirectX)
- Configurable small and large texture handling
- Dry run analysis with size projections
- Detailed processing logs and statistics
- Export analysis reports
- Parallel processing (multi-core support for faster batch operations)

## Technical Notes

- **Double compression concerns:** Block compression (BC5/BC3/BC1) is deterministic - recompressing the same format (e.g., BC3 → BC3) produces nearly identical results with minimal quality loss (PSNR >60 dB, MSE <0.1). The tool currently reprocesses all files to ensure proper mipmaps and Z-channel reconstruction, which means compressed inputs get recompressed to the same format. This is generally harmless for quality but doesn't reduce file size.

- **Why reprocess everything?** Z-channel validity and mipmap quality cannot be verified without additional dependencies (numpy/PIL), so the tool always regenerates proper mipmaps and reconstructs Z when needed. This ensures technical correctness at the cost of some processing time.

- **Future improvements:** Optional format validation to skip reprocessing when compressed inputs don't need fixes (no resizing, valid mipmaps, correct Z-channel).
