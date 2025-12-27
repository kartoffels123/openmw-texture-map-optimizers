# OpenMW Normal Map Optimizer

A high-performance tool for optimizing, fixing, and compressing normal maps for OpenMW.

## Quick Start

1. **Install Python** from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation
2. **Double-click** `OpenMW Normal Map Optimizer.bat` to launch
3. **Configure** input/output directories in the Settings tab
4. **Run a Dry Run** to preview changes (takes only seconds, even for 10,000+ files)
5. **Process Files** when you're ready

**⚠ DRY RUN IS NOW MANDATORY** - The "Process Files" button is disabled until you run a dry run. This ensures you see what will happen and provides instant processing through analysis caching.

## About

If any of the technical details below don't make sense to you and you just want the game to run better, **use the default settings**. The only thing you might want to adjust is the **Scale Factor** (Settings tab) - set it to 0.5 for extra performance, or leave it at 1.0 to keep original resolution.

## Features

### Version 0.9 (Current)
- **Bugfix for resizing** - Min/max resolution logic now works correctly
- **Default enforce of power-of-2** - Now enabled by default (expected standard)
- **More clear UI on resizing** - Added "Ceiling/Floor" labels and "How Downscaling Works" guide
- **More clear analysis on resizing** - Better messaging about min/max protection

### Version 0.8
- **Analysis caching** - Headers read once during dry run, reused during processing for instant start
- **Mandatory dry run** - Process Files button disabled until dry run completes (don't worry, takes only seconds!)
- **Auto-cache invalidation** - Settings changes automatically invalidate cache and prompt re-analysis
- **Texture atlas protection** - Auto-detects and preserves atlases (filename contains "atlas" or in ATL directory)
- **Smart resolution warnings** - Shows whether current settings will auto-fix oversized/undersized textures
- **Cleaner output** - Consolidated sections, better terminology ("Recalculate" vs "Convert")
- **Performance optimizations** - Stores only 5 file examples instead of full lists (fast on 10k+ files)

### Core Features
- **Batch processing** of normal maps (`_N.dds` and `_NH.dds`)
- **Format conversion** (BC5/ATI2, BC3/DXT5, BC1/DXT1, BGRA, BGR)
- **Texture downscaling** with quality filters and resolution constraints
- **Z-channel reconstruction** for proper normal mapping
- **Y flip conversion** (OpenGL ↔ DirectX normal maps)
- **Smart small texture handling** - Avoids over-compressing tiny textures
- **Smart format preservation** - Keeps compressed formats when not downscaling (v0.5)
- **Auto-fix mislabeled NH→N textures** - Detects BGR/BC5/BC1 formats on NH files (v0.5)
- **Auto-optimize N textures** - Removes wasted alpha channels (BGRA→BC5, BC3→BC1) (v0.5)
- **Comprehensive warning system** - Shows potential issues before processing (v0.5)
- **Dry run analysis** with size projections and detailed conversion breakdown
- **Detailed processing logs** and statistics
- **Export analysis reports** to text files
- **Parallel processing** - Multi-core support for faster batch operations

## GUI Overview

The application has four tabs:

1. **📖 READ THIS FIRST** - Help & documentation with format recommendations
2. **⚙️ Settings** - Configure directories, formats, resize options, and advanced settings
3. **▶️ Process Files** - Run dry runs and process your normal maps
4. **📋 Version Info** - Current version features and known issues

## Important Notes

### 1. Normal Map Orientation
**Your normal maps use DirectX-style (G=Y-)**, not OpenGL-style (G=Y+).
- I cannot auto-detect inverted Y
- Use the "Flip Y (OpenGL→DirectX)" checkbox in Settings if needed

### 2. This Tool is Designed For:
- **Compressing uncompressed textures (BGRA/BGR)** - the primary use case
- **"Smart" file optimization** on already-compressed textures to avoid wasting space
- **Fixing common errors** (mislabeled formats, wasted alpha channels, broken mipmaps)
- **Being minimally invasive** while being highly configurable
- **Running very fast** with parallel processing support

### 3. Compression & Quality
**Compression and downscaling are LOSSY** (you lose information).
- However, 75-95% space savings is nearly always worth it
- BC5 compression is visually lossless for most normal maps
- Dry run shows exact size projections before processing

## Working with Already-Compressed Textures

**Already using BC3/BC1?** The tool intelligently handles compressed textures:

### Smart Optimizations (Automatic)
- **Avoids accidentally converting to larger formats** when NOT resizing
  (BC3 → BGRA would be 4x larger with no benefit)
- **Preserves good compressed formats** when not downscaling (enabled by default)
- **Auto-detects and fixes mislabeled textures** (e.g., _NH files in BC5/BC1)
- **Auto-optimizes wasted space** (e.g., N textures in BC3 → BC1 for half the size)
- **Regenerates mipmap chains** (textures may have bad/missing mipmaps)
- **Reconstructs Z channels** (sometimes missing or incorrect)

### Note on Recompression
Usually pretty harmless! "Double compression" produces nearly identical results (e.g., PSNR ~50 dB, MSE ~0.05) as long as no intermediate operation (e.g., resizing, color changes) is occurring.

**Want to avoid reprocessing entirely?** Enable "Allow well-compressed textures to passthrough" in Settings > Smart Format Handling.

### Valid Reasons to Process Already-Compressed Textures
- **Resizing** (downscaling/upscaling) - the main use case
- **Fixing broken mipmaps or Z channels** - surprisingly common
- **Removing wasted space** (N textures with unused alpha channels)

### Restoring Quality from Heavily Compressed Textures
You can't "upgrade" compressed textures by converting formats. Instead:
1. Use [chaiNNer](https://chainner.app/) with artifact removal models to restore detail
2. Then use this tool to recompress to your preferred format

## For Regular Users

These are edge cases mostly relevant to mod authors. If you just want vastly better performance with very little quality loss, **the default settings will work fine**.

**Still unsure?** Use **Dry Run** to see what will happen before processing. It has a detailed conversion breakdown and statistics.

## Installation

### Requirements
- Python 3.7 or later
- Windows (for DirectXTex tools)

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
Simply double-click **`OpenMW Normal Map Optimizer.bat`**

If Python is not installed or not in PATH, the batch file will show helpful error messages.

## Project Structure

```
openmw-normal-map-optimizer/
├── OpenMW Normal Map Optimizer.bat  # Launch this!
├── optimizer.py                     # Main entry point
├── src/
│   ├── core/
│   │   ├── processor.py            # Core processing logic
│   │   └── dds_parser.py           # Fast DDS header parser
│   └── gui/
│       └── main_window.py          # GUI implementation
├── tools/                           # DirectXTex executables
│   ├── texconv.exe
│   ├── texdiag.exe
│   └── texassemble.exe
└── specs/                           # Reference files
    ├── dds.ksy                      # DDS format specification
    └── dds.py                       # Generated parser (reference)
```

## Version History

### Version 0.9 (Current)
- **Bugfix for resizing** - Min/max resolution logic now works correctly
- **Default enforce of power-of-2** - Now enabled by default (expected standard)
- **More clear UI on resizing** - Added "Ceiling/Floor" labels and "How Downscaling Works" guide
- **More clear analysis on resizing** - Better messaging about min/max protection

### Version 0.8
- Analysis caching - headers read once, reused during processing
- Mandatory dry run - Process Files disabled until dry run completes (takes only seconds!)
- Auto-cache invalidation when settings change
- Texture atlas protection - auto-detects 'atlas' filenames or ATL directories
- Smart resolution warnings show whether current settings will auto-fix
- Cleaner output - consolidated sections, less redundancy
- Better terminology - 'Recalculate' vs 'Convert' for clarity
- Format comparison fixed (BC1_UNORM → BC1/DXT1 normalization)
- Performance - stores only 5 file examples instead of full lists
- Removed misleading 'preserved format' messages

### Version 0.7
- ~100x faster dry run analysis (6,000 files in <1 second vs 1 minute)
- Direct DDS header parsing eliminates subprocess overhead
- Optimized file discovery for large directories
- Grouped conversion summary shows format/resize changes clearly
- Reorganized codebase with cleaner structure
- Support for BC4, BC6H, BC7, and many additional DDS formats

### Version 0.6
- UI/UX improvements and refinements
- Enhanced log output and reporting

### Version 0.5
- Smart format handling preserves compressed formats when not downscaling
- Auto-detection and fixing of mislabeled NH textures
- Auto-optimization of N textures with wasted alpha channels
- Comprehensive warning system shows potential issues before processing

### Earlier Versions
- Parallel processing support
- Dry run analysis
- Z-channel reconstruction
- Format conversion and resolution scaling

## Technical Notes

### Understanding Format Preservation & Passthrough (v0.5+)

There are two distinct options that control how already-compressed textures are handled:

#### "Preserve compressed format when not downsampling" (Enabled by default)
- **What it does:** Keeps the same format (e.g., BC1 → BC1) when NOT resizing. Converting BC1 to BC5 without resizing would double the file size while still retaining BC1's original compression artifacts - no quality gain, just wasted space.
- **Files are still reprocessed** to fix potential issues:
  - Z-channel reconstruction (if missing or incorrect)
  - Mipmap chain regeneration (if broken or missing)
- **If downsampling:** Ignores this setting and uses your configured format (BC5/BC3/BGRA)
- **Result:** Minimal quality loss (recompression artifacts), but technical correctness is ensured

#### "Allow well-compressed textures to passthrough" (Disabled by default - use with caution!)
- **What it does:** TRUE passthrough - files are simply **copied** with NO operations performed
- **When files qualify for passthrough:**
  - BC1 or BC5 for _N textures (well-compressed, no wasted alpha)
  - BC3 for _NH textures (well-compressed, uses alpha)
- **When files DO NOT qualify:**
  - BC3 for _N textures (wasted alpha channel - not well-compressed)
  - BC5/BC1 for _NH textures (missing alpha - not appropriate)
  - Any texture that needs resizing
- **Warning:** Only enable if you're certain your compressed textures already have correct Z-channels and mipmaps
- **Result:** Maximum speed, but skips all corrections

**Summary:**
- **Format Preservation:** Same format, reprocessed for corrections (Z-channel, mipmaps)
- **Passthrough:** No processing at all, just copy (only for well-compressed files by default)
  - With "Smart format handling" disabled, you can get true passthrough for ALL compressed files

**Final Word:** You can override and mix any of these settings. Check the **Dry Run** tab to see exactly what will happen before processing!

### Double Compression
Block compression (BC5/BC3/BC1) is deterministic - recompressing the same format (e.g., BC3 → BC3) produces nearly identical results with minimal quality loss (e.g., PSNR ~50 dB, MSE ~0.05). The tool reprocesses files to ensure proper mipmaps and Z-channel reconstruction, which means compressed inputs get recompressed to the same format. This is generally harmless for quality but doesn't reduce file size. You **CAN** turn off reprocessing with passthrough.

### Performance Optimizations (v0.7)
- **Fast header parsing:** Reads only the first 148 bytes of DDS files instead of spawning subprocesses
- **Sequential analysis:** For dry runs with the fast parser, sequential processing is faster than parallel due to Windows multiprocessing overhead
- **Targeted file discovery:** Only searches for `*_n.dds` and `*_nh.dds` patterns instead of all DDS files

## Resources

- [Normal Map Upscaling Models](https://openmodeldb.info/collections/c-normal-map-upscaling)
- [chaiNNer FAQ](https://openmodeldb.info/docs/faq)
- [DXT Artifact Removal](https://openmodeldb.info/models/1x-DEDXT)
- [DirectXTex](https://github.com/Microsoft/DirectXTex) - Underlying texture conversion tools

## Final Notes

This is all my personal opinion and experience. I have compressed a lot of normal maps for a variety of games and done probably an unhealthy amount of work with the DDS filetype. You can do whatever you want if it makes sense to you. That's why I left in a bunch of options on the settings page.

The defaults are sensible for most users. If you're unsure, just run a dry run and look at the results!
