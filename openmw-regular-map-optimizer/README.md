# OpenMW Regular Texture Optimizer v0.5

A high-performance tool for optimizing and compressing regular (non-normal map) textures for OpenMW.

## Quick Start

1. **Install Python** from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation
2. **Double-click** `OpenMW Regular Map Optimizer.bat` to launch
3. **Configure** input/output directories in the Settings tab
4. **Run a Dry Run** to preview changes
5. **Process Files** when you're ready

**⚠ DRY RUN IS MANDATORY** - The "Process Files" button is disabled until you run a dry run. This ensures you see what will happen and provides fast processing through analysis caching.

## About

If any of the technical details below don't make sense to you and you just want the game to run better, **use the default settings**. The only thing you might want to adjust is the **Scale Factor** (Settings tab) - set it to 0.5 for extra performance, or leave it at 1.0 to keep original resolution.

## Features

### Core Features
- **Batch processing** of regular textures (DDS and TGA files)
- **Automatic format selection** based on alpha channel presence:
  - No alpha → BC1/DXT1 (4 bits/pixel)
  - Has alpha → BC3/DXT5 (8 bits/pixel)
  - Small textures → BGR/BGRA uncompressed
- **Alpha channel optimization** - detects unused alpha and DXT1a textures
- **Smart passthrough** - skips well-compressed textures that don't need processing
- **Path filtering** - whitelist/blacklist system for selective processing
- **TGA support** - converts TGA files to optimized DDS
- **Texture downscaling** with quality filters and resolution constraints
- **Mipmap validation** - regenerates broken or missing mipmaps
- **Texture atlas protection** - auto-detects and preserves atlas textures
- **Dry run analysis** with size projections and detailed breakdown
- **Parallel processing** - multi-core support with configurable chunk sizes
- **Export analysis reports** to JSON for external tools

### Smart Features
- **Intelligent format handling** - automatically selects BC1 or BC3 based on actual alpha usage
- **Unused alpha detection** - textures with format-declared alpha but all-opaque pixels get BC1
- **DXT1a detection** - BC1 textures using 1-bit transparency are preserved correctly
- **Passthrough for well-compressed** - skip already-optimal textures entirely
- **No-mipmap paths** - UI elements (birthsigns, levelup, splash) skip mipmap generation

## GUI Overview

The application has three tabs:

1. **📖 READ THIS FIRST** - Help & documentation with format recommendations
2. **⚙️ Settings** - Configure directories, formats, path filters, and advanced settings
3. **▶️ Process Files** - Run dry runs and process your textures

## Important Notes

### 1. This Tool is Designed For:
- **Compressing uncompressed textures (TGA, BGRA/BGR DDS)** - the primary use case
- **Optimizing already-compressed textures** to remove wasted alpha channels
- **Fixing common issues** (missing mipmaps, oversized textures)
- **Being minimally invasive** with smart passthrough
- **Running fast** with parallel processing and cuttlefish compression

### 2. Compression & Quality
**Compression is LOSSY** (you lose information).
- However, 75-95% space savings is nearly always worth it
- BC1/BC3 compression is visually fine for most textures*.
- Dry run shows exact size projections before processing


  note: I could go on about this, but tl;dr Atlas preservation and small file preservation make this a non-issue for you.

### 3. Alpha Channel Handling

The tool has alpha channel analysis:

**Alpha Optimization (Enabled by default - RECOMMENDED)**
- Detects textures with format-declared alpha that's actually unused (all pixels = 255)
- These get compressed to BC1 instead of BC3 (50% smaller!)
- Also detects DXT1a (BC1 with 1-bit alpha transparency)

**DXT1a Handling:**
- DXT1a textures that pass through unchanged are preserved correctly
- DXT1a textures that need reprocessing (resize, mipmap regen) are upgraded to BC2.
- BC2 preserves the "sharpness" of DXT1a. I've found recompressing directly to DXT1a can cause unexpected issues, so BC2/DXT3 is the logical fallback.

**⚠ Warning:** Disabling Alpha Optimization means:
- Unused alpha won't be detected → larger files (BC3 instead of BC1)
- DXT1a won't be detected → 1-bit alpha lost when reprocessing

## Path Filtering

### Whitelist (Default: "Textures")
Only processes textures in folders containing "Textures" in the path.
This prevents accidentally processing UI icons, bookart, etc.

### Blacklist (Default: icon, icons, bookart, menu_, tx_menu_, cursor, compass, target)
Skips textures in these folders or with these prefixes.
These UI elements shouldn't be compressed - they're viewed at 1:1 pixel scale.

### No-Mipmap Paths (Default: birthsigns, levelup, splash, scroll.*)
Textures in these locations are processed but skip mipmap generation.
These UI elements can be compressed but are displayed at 1:1 scale and don't benefit from mipmaps. Also apparently OpenMW dislikes mipmaps on these, so no mipmaps here.

## Settings Reference

### Format Settings
- **Preserve compressed format**: Keeps BC1→BC1, BC2→BC2, BC3→BC3 when not resizing
- **Allow passthrough**: Skip well-compressed files entirely (just copy)
- **Copy passthrough files**: Whether to copy passthrough files to output or skip them

### Alpha Settings
- **Alpha Optimization**: Analyze alpha channels for unused alpha and DXT1a detection

### Size Settings
- **Scale factor**: Downsize texture dimensions (0.5 = half size)
- **Max resolution**: Cap texture size (default: 2048)
- **Min resolution**: Floor for texture size downsizing (default: 256)
- **Enforce power-of-2**: Round dimensions to power-of-2 (recommended)

### Performance Settings
- **Parallel processing**: Enable multi-core processing
- **Max workers**: Number of parallel processes
- **Chunk size (MB)**: Memory limit per processing batch

## Installation

### Requirements
- Python 3.7 or later
- Windows (for DirectXTex and cuttlefish tools)
- numpy (`pip install numpy`) - for DDS alpha analysis

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
Simply double-click **`OpenMW Regular Map Optimizer.bat`**

## Project Structure

```
openmw-regular-map-optimizer/
├── OpenMW Regular Map Optimizer.bat  # Launch this!
├── optimizer.py                      # Main entry point
├── src/
│   ├── core/
│   │   ├── regular_processor.py     # Core processing logic
│   │   └── regular_settings.py      # Regular texture settings
│   └── gui/
│       └── main_window.py           # GUI implementation
├── tools/                            # Compression tools
│   ├── texconv.exe                   # DirectXTex converter
│   ├── texdiag.exe                   # DirectXTex diagnostics
│   └── cuttlefish/                   # Fast BC1/BC2/BC3 compressor
│       └── cuttlefish.exe
└── tests/
    └── test_verify_pipeline.py      # Pipeline verification tests

# Shared core (../openmw-texture-optimizer-core/src/core/)
├── dds_parser.py                     # Fast DDS/TGA header parser
├── base_settings.py                  # Shared data classes
├── utils.py                          # Shared utilities
└── file_scanner.py                   # Path filtering
```

## Compression Tools

### Cuttlefish (Primary)
Used for BC1, BC2, and BC3 compression. Higher quality than texconv (2-5 dB PSNR improvement).

### texconv (Fallback)
DirectXTex command-line tool. Used when cuttlefish doesn't support the format or fails.

## Differences from Normal Map Optimizer

| Feature | Normal Map Optimizer | Regular Texture Optimizer |
|---------|---------------------|---------------------------|
| Target files | `_N.dds`, `_NH.dds` | All non-normal textures |
| Formats | BC5, BC3, BC1, BGRA, BGR | BC1, BC2, BC3, BGRA, BGR |
| Alpha handling | Height maps in `_NH` | Unused alpha detection, DXT1a |
| Path filtering | None (explicit patterns) | Whitelist/blacklist system |
| TGA support | No | Yes |
| Compression tool | texconv only | cuttlefish + texconv |

## Testing

Run pipeline verification test:

```bash
python tests/test_verify_pipeline.py <input_dir> <output_dir> [--settings settings.json]
```

This compares dry run analysis predictions against actual processing outputs.

## Technical Notes

### Understanding Passthrough

**"Allow well-compressed textures to passthrough"** means files that are already optimal are skipped:
- Correct format for their alpha usage (BC1 for opaque, BC2/BC3 for transparent)
- Valid mipmap chain
- Within resolution limits (BGR/BGRA are kept for small textures)
- Not needing resize

Passthrough files can optionally be copied to output or skipped entirely.

### Cuttlefish vs texconv Quality

Cuttlefish produces higher quality BC1/BC2/BC3 compression:
- ~2-5 dB higher PSNR
- Better color preservation
- Similar compression speed

texconv is used for formats cuttlefish doesn't support. In this case it's only BGR as it's a very old format.

### Alpha Analysis Performance

Alpha Optimization adds analysis time during dry run:
- Reads texture data to check actual alpha values
- Detects BC1 blocks using DXT1a mode
- Worth it for accurate format selection and smaller output

## Version History

### Version 0.5 (Current)
- **Land texture protection** - New filtering option to protect terrain/landscape textures from resizing while still applying compression and mipmap fixes
- **Land texture scanner** - New CLI tool (`land_texture_scanner.py`) to extract LTEX records from ESP/ESM files and generate exclusion lists
- **Sample exclusion lists** - Includes `POTI_2-1_land_textures.txt` (590 entries) covering vanilla + most popular mods
- **Texture atlas min resolution** - Added configurable min resolution for atlas textures (default: 2048) alongside max resolution (default: 8192)

### Version 0.4
- **More filtering options** - Enhanced path filtering with additional configuration options

### Version 0.2
- **DX10 header stripping** - Cuttlefish outputs DX10 extended headers which OpenMW doesn't support; these are now automatically stripped and converted to legacy DDS format
- **BGRA moved to texconv** - Uncompressed BGRA textures now use texconv instead of cuttlefish for proper legacy DDS output
- **Proper alpha handling** - Added `-alpha -sepalpha` flags for straight alpha and proper mipmap generation without color bleeding

### Version 0.1
- Initial release with cuttlefish compression for BC1/BC2/BC3 and texconv for BGR
- Alpha channel optimization and DXT1a detection
- Smart passthrough for well-compressed textures
- Path filtering with whitelist/blacklist system

## Resources

- [DirectXTex](https://github.com/Microsoft/DirectXTex) - Underlying texture tools
- [cuttlefish](https://github.com/akb825/Cuttlefish) - High-quality texture compression
- [OpenMW](https://openmw.org/) - Open source Morrowind engine

## Final Notes

This is all my personal opinion and experience. I have compressed a lot of different maps for a variety of games and done probably an unhealthy amount of work with the DDS filetype. You can do whatever you want if it makes sense to you. That's why I left in a bunch of options on the settings page.

The defaults are sensible for most users. If you're unsure, just run a dry run and look at the results!

