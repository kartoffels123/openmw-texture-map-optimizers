# OpenMW Regular Texture Optimizer

Optimize and compress regular (non-normal map) textures for OpenMW.

## Features

- Compresses uncompressed textures (TGA, uncompressed DDS)
- Validates and fixes mipmap chains
- Intelligently passes through well-compressed textures
- Filters out UI textures (icons, bookart)
- Whitelist: Only processes textures in "Textures" folders
- Blacklist: Skips icon/icons/bookart folders (customizable)
- Excludes normal maps (_N and _NH files)

## Requirements

- Python 3.7+
- Windows (for texconv/texdiag tools)
- numpy (`pip install numpy`) - for DDS alpha analysis

## Usage

1. Double-click `OpenMW Regular Map Optimizer.bat` to launch the GUI
2. Or run: `python optimizer.py`

## Settings

- **Target Format**: BC1/DXT1 (default), BC2/DXT3, BC3/DXT5, BGRA, BGR
- **Passthrough Mode**: Skip textures that are already well-compressed
- **Path Filters**: Customize which folders to include/exclude

## Differences from Normal Map Optimizer

- Works on regular textures only (excludes _N and _NH files)
- Single target format (not separate N/NH formats)
- Validates mipmap count (passthrough logic)
- Path filtering (Textures whitelist, icon blacklist)
- Supports TGA files
- No Z reconstruction or Y-axis inversion

## Testing

Run pipeline verification test:

```bash
python tests/test_verify_pipeline.py <input_dir> <output_dir> [--settings settings.json]
```

This compares dry run analysis predictions against actual processing outputs.
