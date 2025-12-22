# OpenMW Normal Map Optimizer

This tool optimizes, fixes, and compresses normal maps for OpenMW.

## About

If any of the text below doesn't make sense to you and you just want the game to run better, just use the default settings. On the Settings tab, the only thing I'd vary is setting Scale Factor from 1.0 to 0.5 if you want extra performance.

**⚠ ALWAYS DO A DRY RUN.**

### Important Assumptions

1. **Your normal maps use DirectX-style (G=Y-)**, not OpenGL-style (G=Y+).
   I cannot auto-detect inverted Y - use the checkbox if needed.

2. **You have UNCOMPRESSED normal maps.** If already compressed, then you should ONLY be using this for resizing. You cannot magically uncompress. Use chaiNNer with artifact removal (recommended) and/or upscaling models to restore compressed maps first.

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
- **📋 Version History** - See current version features and known issues

## Features (Version 0.2)

- Batch processing of normal maps (`_N.dds` and `_NH.dds`)
- Format conversion (BC5, BC3/DXT5, BC1/DXT1, BGRA, BGR)
- Resolution scaling and constraints
- Z-channel reconstruction for proper normal mapping
- Y flip normal map conversion (OpenGL to DirectX)
- Configurable small and large texture handling
- Dry run analysis with size projections
- Detailed processing logs and statistics
- Export analysis reports

## Known Issues

- The tool allows converting compressed formats to uncompressed formats if selected. Ideally, compressed inputs without resizing would be copied as-is, but since Z-channel validity cannot be verified without some dependencies (numpy/PIL) + overhead, the tool reprocesses all files. This may cause unnecessary decompression where the output will still look compressed but have a large file size (Very Bad) or introduce double compression artifacts (Varies from Fine to Very Bad). The user HAS been warned about this on the document page. Further the dry run does tell them what conversions are occurring.
- Future versions will add (optional) format validation to preserve compressed inputs when no resizing occurs IF Z-channel reconstruction is not needed or selected. Should also keep in mind the user may have not generated mipmaps or have created invalid ones.
- Future versions should make some functions more clear.
