#!/usr/bin/env python3
"""
Test to verify that processing output matches dry run analysis predictions.

Usage:
    python tests/test_verify_pipeline.py <input_dir> <output_dir> [--settings settings.json]

Or run from GUI:
    1. Configure settings in GUI
    2. Click "Export Settings" button
    3. Run: python tests/test_verify_pipeline.py <input_dir> <output_dir> --settings optimizer_settings.json
"""

import sys
import json
import importlib.util
from pathlib import Path

# Add path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import shared core modules using same pattern as processor.py
_shared_core_path = Path(__file__).parent.parent.parent / "openmw-texture-optimizer-core" / "src" / "core"

def _import_shared_module(module_name):
    """Import a module from the shared core package."""
    import types
    full_name = f"shared_core.{module_name}"

    if full_name in sys.modules:
        return sys.modules[full_name]

    if "shared_core" not in sys.modules:
        shared_core_pkg = types.ModuleType("shared_core")
        shared_core_pkg.__path__ = [str(_shared_core_path)]
        sys.modules["shared_core"] = shared_core_pkg

    spec = importlib.util.spec_from_file_location(
        full_name,
        _shared_core_path / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    setattr(sys.modules["shared_core"], module_name, module)

    return module

# Import shared test framework and DDS parser from shared core
_test_utils = _import_shared_module("test_utils")
_dds_parser = _import_shared_module("dds_parser")

verify_analysis_vs_output = _test_utils.verify_analysis_vs_output
parse_dds_header = _dds_parser.parse_dds_header

# Import tool-specific components
from src.core.processor import NormalMapProcessor
from src.core.normal_settings import NormalSettings as ProcessingSettings


def load_settings_from_dict(settings_dict: dict) -> ProcessingSettings:
    """Load ProcessingSettings from dictionary"""
    return ProcessingSettings(
        n_format=settings_dict.get('n_format', 'BC5/ATI2'),
        nh_format=settings_dict.get('nh_format', 'BC3/DXT5'),
        scale_factor=settings_dict.get('scale_factor', 1.0),
        max_resolution=settings_dict.get('max_resolution', 2048),
        min_resolution=settings_dict.get('min_resolution', 256),
        invert_y=settings_dict.get('invert_y', False),
        reconstruct_z=settings_dict.get('reconstruct_z', True),
        uniform_weighting=settings_dict.get('uniform_weighting', True),
        use_dithering=settings_dict.get('use_dithering', False),
        use_small_texture_override=settings_dict.get('use_small_texture_override', True),
        small_nh_threshold=settings_dict.get('small_nh_threshold', 256),
        small_n_threshold=settings_dict.get('small_n_threshold', 128),
        resize_method=settings_dict.get('resize_method', 'CUBIC'),
        enable_parallel=settings_dict.get('enable_parallel', True),
        max_workers=settings_dict.get('max_workers', 4),
        chunk_size_mb=settings_dict.get('chunk_size_mb', 75),
        preserve_compressed_format=settings_dict.get('preserve_compressed_format', True),
        auto_fix_nh_to_n=settings_dict.get('auto_fix_nh_to_n', True),
        auto_optimize_n_alpha=settings_dict.get('auto_optimize_n_alpha', True),
        allow_compressed_passthrough=settings_dict.get('allow_compressed_passthrough', False),
        copy_passthrough_files=settings_dict.get('copy_passthrough_files', False),
        enable_atlas_downscaling=settings_dict.get('enable_atlas_downscaling', False),
        atlas_min_resolution=settings_dict.get('atlas_min_resolution', 2048),
        atlas_max_resolution=settings_dict.get('atlas_max_resolution', 8192),
        enforce_power_of_2=settings_dict.get('enforce_power_of_2', True)
    )


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nQuick test with default settings:")
        print("  python test_verify_pipeline.py <input_dir> <output_dir>")
        print("\nTest with custom settings:")
        print("  python test_verify_pipeline.py <input_dir> <output_dir> --settings my_settings.json")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        sys.exit(1)

    # Load settings
    if '--settings' in sys.argv:
        settings_path = Path(sys.argv[sys.argv.index('--settings') + 1])
        with open(settings_path, 'r') as f:
            settings_dict = json.load(f)
        settings = load_settings_from_dict(settings_dict)
        print(f"Loaded settings from: {settings_path}")
    else:
        settings = ProcessingSettings()  # Use defaults
        print("Using default settings")

    # Create processor
    processor = NormalMapProcessor(settings)

    # Run verification using shared framework
    success, mismatches, total = verify_analysis_vs_output(
        processor=processor,
        input_dir=input_dir,
        output_dir=output_dir,
        dds_parser_func=parse_dds_header,
        interactive=True
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
