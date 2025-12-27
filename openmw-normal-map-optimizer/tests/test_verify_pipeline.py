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
from pathlib import Path

# Add parent directory to path so we can import src module
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.processor import NormalMapProcessor, ProcessingSettings
from src.core.dds_parser import parse_dds_header


def normalize_format(fmt):
    """Normalize format names for comparison"""
    format_map = {
        'BC5_UNORM': 'BC5/ATI2',
        'BC3_UNORM': 'BC3/DXT5',
        'BC1_UNORM': 'BC1/DXT1',
        'B8G8R8A8_UNORM': 'BGRA',
        'B8G8R8X8_UNORM': 'BGR',
        'BC2_UNORM': 'BC2/DXT3',
        'B5G6R5_UNORM': 'B5G6R5'
    }
    return format_map.get(fmt, fmt)


def load_settings_from_dict(settings_dict):
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
        enable_atlas_downscaling=settings_dict.get('enable_atlas_downscaling', False),
        atlas_max_resolution=settings_dict.get('atlas_max_resolution', 4096)
    )


def verify_processing_matches_analysis(input_dir, output_dir, settings, interactive=True):
    """
    Verify that actual processing output matches what the dry run predicted.

    Args:
        input_dir: Path to input directory
        output_dir: Path to output directory
        settings: ProcessingSettings object
        interactive: If True, pause before processing to review dry run

    Returns:
        (success, mismatches, total_checked)
    """
    print("=" * 80)
    print("PIPELINE VERIFICATION TEST")
    print("=" * 80)

    # Show settings being tested
    print("\n=== Settings ===")
    settings_dict = settings.to_dict()
    key_settings = [
        'n_format', 'nh_format', 'scale_factor', 'max_resolution', 'min_resolution',
        'preserve_compressed_format', 'auto_fix_nh_to_n', 'auto_optimize_n_alpha',
        'allow_compressed_passthrough', 'use_small_texture_override',
        'small_n_threshold', 'small_nh_threshold', 'enable_atlas_downscaling'
    ]
    for key in key_settings:
        print(f"  {key}: {settings_dict[key]}")

    print("\n" + "=" * 80)
    print("STEP 1: Running Analysis (Dry Run)")
    print("=" * 80)

    processor = NormalMapProcessor(settings)

    # Progress callback for analysis
    def progress_callback(current, total):
        if current % 1000 == 0 or current == total:
            print(f"  Analyzing... {current}/{total} files")

    analysis_results = processor.analyze_files(input_dir, progress_callback=progress_callback)

    # Store predictions
    predictions = {}
    passthrough_count = 0
    for result in analysis_results:
        if not result.error:
            is_passthrough = any('Compressed passthrough' in w for w in (result.warnings or []))
            predictions[result.relative_path] = {
                'target_format': result.target_format,
                'target_width': result.new_width,
                'target_height': result.new_height,
                'is_passthrough': is_passthrough
            }
            if is_passthrough:
                passthrough_count += 1

    print(f"\n✓ Analysis complete: {len(predictions)} files")
    print(f"  - Passthrough: {passthrough_count} files")
    print(f"  - To process: {len(predictions) - passthrough_count} files")

    if interactive:
        print("\n" + "=" * 80)
        input("Press Enter to run processing and verify outputs...")

    print("\n" + "=" * 80)
    print("STEP 2: Running Processing")
    print("=" * 80)

    # Progress callback for processing
    def process_progress_callback(current, total, result):
        if current % 100 == 0 or current == total:
            print(f"  Processing... {current}/{total} files")

    processor.process_files(input_dir, output_dir, progress_callback=process_progress_callback)

    print("\n" + "=" * 80)
    print("STEP 3: Verifying Outputs Match Predictions")
    print("=" * 80)

    mismatches = []
    verified_count = 0

    for rel_path, prediction in predictions.items():
        output_file = output_dir / rel_path

        if not output_file.exists():
            mismatches.append({
                'file': rel_path,
                'type': 'MISSING',
                'message': 'Output file not created'
            })
            continue

        # Read actual output
        dimensions, format_str = parse_dds_header(output_file)
        if not dimensions:
            mismatches.append({
                'file': rel_path,
                'type': 'READ_ERROR',
                'message': 'Could not read output DDS header'
            })
            continue

        actual_width, actual_height = dimensions
        actual_format = normalize_format(format_str)

        # Check format
        if actual_format != prediction['target_format']:
            mismatches.append({
                'file': rel_path,
                'type': 'FORMAT_MISMATCH',
                'predicted_format': prediction['target_format'],
                'actual_format': actual_format,
                'predicted_size': f"{prediction['target_width']}x{prediction['target_height']}",
                'actual_size': f"{actual_width}x{actual_height}"
            })
            continue

        # Check dimensions
        if actual_width != prediction['target_width'] or actual_height != prediction['target_height']:
            mismatches.append({
                'file': rel_path,
                'type': 'SIZE_MISMATCH',
                'format': actual_format,
                'predicted_size': f"{prediction['target_width']}x{prediction['target_height']}",
                'actual_size': f"{actual_width}x{actual_height}"
            })
            continue

        verified_count += 1
        if verified_count % 1000 == 0:
            print(f"  Verified {verified_count}/{len(predictions)} files...")

    # Report results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total files checked: {len(predictions)}")
    print(f"Verified (match):    {verified_count}")
    print(f"Mismatches:          {len(mismatches)}")

    # Build report text
    report_lines = [
        "=" * 80,
        "PIPELINE VERIFICATION REPORT",
        "=" * 80,
        "",
        "=== Settings ===",
    ]
    for key in key_settings:
        report_lines.append(f"  {key}: {settings_dict[key]}")

    report_lines.extend([
        "",
        "=== Results ===",
        f"Total files checked: {len(predictions)}",
        f"Verified (match):    {verified_count}",
        f"Mismatches:          {len(mismatches)}",
        ""
    ])

    if mismatches:
        print("\n❌ FAILURES DETECTED\n")
        report_lines.append("❌ FAILURES DETECTED")
        report_lines.append("")

        # Group by type
        by_type = {}
        for m in mismatches:
            by_type.setdefault(m['type'], []).append(m)

        for mtype, items in by_type.items():
            print(f"\n{mtype}: {len(items)} files")
            report_lines.append(f"\n{mtype}: {len(items)} files")

            for item in items[:5]:  # Show first 5 of each type
                print(f"\n  File: {item['file']}")
                report_lines.append(f"\n  File: {item['file']}")

                if 'predicted_format' in item:
                    line1 = f"    Predicted: {item['predicted_format']} @ {item['predicted_size']}"
                    line2 = f"    Actual:    {item['actual_format']} @ {item['actual_size']}"
                    print(line1)
                    print(line2)
                    report_lines.append(line1)
                    report_lines.append(line2)
                elif 'predicted_size' in item:
                    line1 = f"    Format:    {item['format']}"
                    line2 = f"    Predicted: {item['predicted_size']}"
                    line3 = f"    Actual:    {item['actual_size']}"
                    print(line1)
                    print(line2)
                    print(line3)
                    report_lines.append(line1)
                    report_lines.append(line2)
                    report_lines.append(line3)
                else:
                    line = f"    {item['message']}"
                    print(line)
                    report_lines.append(line)

            if len(items) > 5:
                msg = f"\n  ... and {len(items) - 5} more {mtype} errors"
                print(msg)
                report_lines.append(msg)

            # Add all mismatches to report (not just first 5)
            report_lines.append(f"\nAll {mtype} files:")
            for item in items:
                report_lines.append(f"  {item['file']}")

        # Save report
        report_path = output_dir / "verification_report_FAILED.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"\n📄 Full report saved to: {report_path}")
        return False, mismatches, len(predictions)
    else:
        print("\n✅ SUCCESS: All files matched dry run predictions!")
        print("\nThe analysis → processing pipeline is working correctly with these settings.")

        report_lines.append("✅ SUCCESS: All files matched dry run predictions!")
        report_lines.append("")
        report_lines.append("The analysis → processing pipeline is working correctly with these settings.")

        # Save success report
        report_path = output_dir / "verification_report_SUCCESS.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"\n📄 Report saved to: {report_path}")
        return True, [], len(predictions)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nQuick test with default settings:")
        print("  python test_verify_pipeline.py <input_dir> <output_dir>")
        print("\nTest with custom settings:")
        print("  python test_verify_pipeline.py <input_dir> <output_dir> --settings my_settings.json")
        print("\nSettings JSON format example:")
        print("""  {
      "n_format": "BC5/ATI2",
      "nh_format": "BC3/DXT5",
      "preserve_compressed_format": true,
      "allow_compressed_passthrough": false,
      "auto_optimize_n_alpha": true,
      ...
  }""")
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
        # Use defaults
        settings = ProcessingSettings()
        print("Using default settings")

    # Run verification
    success, mismatches, total = verify_processing_matches_analysis(
        input_dir, output_dir, settings, interactive=True
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
