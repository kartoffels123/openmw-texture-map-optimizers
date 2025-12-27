# OpenMW Texture Optimizers - Architecture

This document describes the shared architecture for the OpenMW texture optimization tools.

## Overview

The project consists of three main components:

1. **openmw-texture-optimizer-core** - Shared functionality
2. **openmw-normal-map-optimizer** - Normal map specific tool
3. **openmw-regular-map-optimizer** - Regular texture specific tool

## Directory Structure

```
openmw-texture-map-optimizers/
├── .github/
│   └── workflows/
│       ├── release.yml           # Normal map releases (tag: normal-v*)
│       └── release-regular.yml   # Regular texture releases (tag: regular-v*)
│
├── openmw-texture-optimizer-core/
│   ├── src/
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── dds_parser.py          # Fast DDS header parser
│   │   │   ├── base_settings.py       # Base settings class
│   │   │   ├── file_scanner.py        # Path filtering
│   │   │   └── utils.py               # format_size, format_time, etc.
│   │   └── gui/
│   │       └── __init__.py
│   └── tests/
│       ├── __init__.py
│       └── test_utils.py              # Shared verification logic
│
├── openmw-normal-map-optimizer/
│   ├── src/
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── normal_settings.py     # Extends base_settings
│   │   │   ├── processor.py           # Normal map processor
│   │   │   └── dds_parser.py          # (will be removed/aliased)
│   │   └── gui/
│   │       └── main_window.py
│   ├── tests/
│   │   ├── test_verify_pipeline.py    # Current test (kept for compatibility)
│   │   └── test_verify_pipeline_new.py # Uses shared test utilities
│   ├── tools/                         # texconv.exe, texdiag.exe
│   ├── optimizer.py
│   ├── OpenMW Normal Map Optimizer.bat
│   └── README.md
│
└── openmw-regular-map-optimizer/
    ├── src/
    │   ├── core/
    │   │   ├── __init__.py
    │   │   ├── regular_settings.py    # Extends base_settings
    │   │   └── regular_processor.py   # Regular texture processor (TODO)
    │   └── gui/
    │       └── main_window.py         # (TODO)
    ├── tests/
    │   └── test_verify_pipeline.py    # Uses shared test utilities (TODO)
    ├── tools/                         # texconv.exe, texdiag.exe (TODO: copy)
    ├── optimizer.py                   # Entry point (placeholder)
    ├── OpenMW Regular Map Optimizer.bat
    └── README.md
```

## Code Sharing

### Shared Core (~70% reuse)

- **DDS Parser** - Fast header-only parsing for both tools
- **Utils** - format_size(), format_time(), FORMAT_MAP, FILTER_MAP
- **FileScanner** - Path whitelist/blacklist filtering
- **BaseSettings** - Common settings (scale, resolution, parallel, etc.)
- **Test Framework** - verify_analysis_vs_output() for pipeline testing

### Tool-Specific

**Normal Map Optimizer:**
- Separate N_format and NH_format settings
- Z reconstruction, Y inversion
- Auto-fix mislabeled _NH files
- No path filtering (processes all normal maps)

**Regular Texture Optimizer:**
- Single target_format setting
- Path filtering (Textures whitelist, icon/bookart blacklist)
- Mipmap validation
- Passthrough for well-compressed textures
- Excludes _N and _NH files
- TGA support

## Testing Strategy

Both tools use the same test methodology:

1. Run analysis (dry run) to get predictions
2. Run processing to generate actual outputs
3. Compare predictions vs actual outputs
4. Generate report (SUCCESS or FAILED)

The verification logic is shared in `openmw-texture-optimizer-core/tests/test_utils.py`.

Each tool has its own test script that:
- Imports the shared verification function
- Loads tool-specific settings
- Creates tool-specific processor
- Calls shared verification

## Deployment

### Versioning

- Core: `core-v1.0.0` (internal, not released separately)
- Normal maps: `normal-v1.0.0` (triggers normal map workflow)
- Regular textures: `regular-v1.0.0` (triggers regular texture workflow)

### Release Process

1. Tag format determines which workflow runs
2. Each workflow bundles its tool + core package
3. Releases are independent (different repos conceptually)

### GitHub Actions Workflows

**release.yml** (Normal Maps)
- Triggers on `normal-v*` tags
- Bundles openmw-normal-map-optimizer + core
- Creates openmw-normal-map-optimizer.zip

**release-regular.yml** (Regular Textures)
- Triggers on `regular-v*` tags
- Bundles openmw-regular-map-optimizer + core
- Creates openmw-regular-map-optimizer.zip

## Implementation Status

### ✅ Completed

- [x] Core package structure
- [x] DDS parser extraction
- [x] Utility functions extraction
- [x] FileScanner for path filtering
- [x] BaseSettings and data classes
- [x] Shared test utilities (verify_analysis_vs_output)
- [x] NormalSettings (extends BaseSettings)
- [x] RegularSettings (extends BaseSettings)
- [x] Normal map optimizer integration
- [x] Regular texture optimizer structure
- [x] GitHub Actions workflows
- [x] Documentation

### ⏳ In Progress / TODO

- [ ] Test normal map optimizer with shared utilities
- [ ] Implement RegularTextureProcessor
- [ ] Implement regular texture GUI
- [ ] Copy tools/ to regular texture optimizer
- [ ] Full integration testing

## Next Steps

1. **Implement RegularTextureProcessor**
   - Similar to NormalMapProcessor but with:
     - Single format instead of N/NH split
     - Path filtering using FileScanner
     - Mipmap validation
     - Passthrough logic for well-compressed textures
     - Exclusion of _N and _NH files

2. **Implement Regular Texture GUI**
   - Simpler than normal map GUI
   - Single format dropdown
   - Blacklist/whitelist configuration
   - Passthrough toggle

3. **Testing**
   - Verify normal map optimizer still works
   - Test regular texture optimizer on dataset
   - Validate pipeline verification tests

4. **Documentation**
   - Update READMEs for both tools
   - Create migration guide for normal map users
   - Document differences between tools
