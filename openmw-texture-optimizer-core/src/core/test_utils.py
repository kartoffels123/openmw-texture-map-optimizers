"""Shared pipeline verification utilities"""

from pathlib import Path
from typing import Type, Dict, Any, Tuple, List, Callable
import json

# Import normalize_format from utils to avoid duplication
from .utils import normalize_format


def verify_analysis_vs_output(
    processor,
    input_dir: Path,
    output_dir: Path,
    dds_parser_func: Callable,
    interactive: bool = True
) -> Tuple[bool, List[Dict], int]:
    """
    Generic pipeline verification: Compare analysis predictions to actual outputs.

    This is the core test - works for both normal maps and regular textures.

    Args:
        processor: Configured processor instance (NormalMapProcessor or RegularTextureProcessor)
        input_dir: Path to input directory with test data
        output_dir: Path to output directory (will be created)
        dds_parser_func: Function to parse DDS headers (parse_dds_header)
        interactive: If True, pause before processing to review dry run

    Returns:
        (success, mismatches, total_checked)
    """
    settings_dict = processor.settings.to_dict()

    print("=" * 80)
    print("PIPELINE VERIFICATION TEST")
    print("=" * 80)

    # Show key settings
    print("\n=== Settings ===")
    for key, value in settings_dict.items():
        print(f"  {key}: {value}")

    # STEP 1: Analysis (Dry Run)
    print("\n" + "=" * 80)
    print("STEP 1: Running Analysis (Dry Run)")
    print("=" * 80)

    def progress_callback(current, total):
        if current % 1000 == 0 or current == total:
            print(f"  Analyzing... {current}/{total} files")

    analysis_results = processor.analyze_files(input_dir, progress_callback=progress_callback)

    # Store predictions
    predictions = {}
    passthrough_count = 0

    for result in analysis_results:
        if not result.error:
            is_passthrough = any('Compressed passthrough' in w or 'passthrough' in w.lower()
                                for w in (result.warnings or []))
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

    # STEP 2: Processing
    print("\n" + "=" * 80)
    print("STEP 2: Running Processing")
    print("=" * 80)

    def process_progress_callback(current, total, result):
        if current % 100 == 0 or current == total:
            print(f"  Processing... {current}/{total} files")

    processor.process_files(input_dir, output_dir, progress_callback=process_progress_callback)

    # STEP 3: Verification
    print("\n" + "=" * 80)
    print("STEP 3: Verifying Outputs Match Predictions")
    print("=" * 80)

    mismatches = []
    verified_count = 0

    for rel_path, prediction in predictions.items():
        output_file = output_dir / rel_path

        # TGA files are converted to DDS, so check for .dds output
        if not output_file.exists() and rel_path.lower().endswith('.tga'):
            dds_path = Path(rel_path).with_suffix('.dds')
            output_file = output_dir / dds_path

        if not output_file.exists():
            mismatches.append({
                'file': rel_path,
                'type': 'MISSING',
                'message': 'Output file not created'
            })
            continue

        # Read actual output
        dimensions, format_str = dds_parser_func(output_file)
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

    # Generate report
    _generate_report(output_dir, settings_dict, predictions, verified_count, mismatches)

    return (len(mismatches) == 0, mismatches, len(predictions))


def _generate_report(output_dir: Path, settings_dict: dict, predictions: dict,
                     verified_count: int, mismatches: List[Dict]):
    """Generate verification report"""
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total files checked: {len(predictions)}")
    print(f"Verified (match):    {verified_count}")
    print(f"Mismatches:          {len(mismatches)}")

    report_lines = [
        "=" * 80,
        "PIPELINE VERIFICATION REPORT",
        "=" * 80,
        "",
        "=== Settings ===",
    ]

    for key, value in settings_dict.items():
        report_lines.append(f"  {key}: {value}")

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

            for item in items[:5]:  # Show first 5
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

            # Add all mismatches to report
            report_lines.append(f"\nAll {mtype} files:")
            for item in items:
                report_lines.append(f"  {item['file']}")

        # Save report
        report_path = output_dir / "verification_report_FAILED.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"\n📄 Full report saved to: {report_path}")
    else:
        print("\n✅ SUCCESS: All files matched dry run predictions!")
        print("\nThe analysis → processing pipeline is working correctly.")

        report_lines.append("✅ SUCCESS: All files matched dry run predictions!")
        report_lines.append("")
        report_lines.append("The analysis → processing pipeline is working correctly.")

        # Save success report
        report_path = output_dir / "verification_report_SUCCESS.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))

        print(f"\n📄 Report saved to: {report_path}")
