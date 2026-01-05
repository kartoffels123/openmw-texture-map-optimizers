"""
Land Texture Scanner - Extract LTEX (landscape texture) references from ESP/ESM files.

Uses tes3conv to convert ESP/ESM to JSON, then parses LTEX records to identify
textures used for terrain/landscape. These textures typically need to stay high
resolution since they tile across large world areas.
"""

import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LandTextureRecord:
    """Represents an LTEX record from an ESP/ESM file."""
    id: str
    texture_path: str
    index: Optional[int] = None
    source_plugin: Optional[str] = None


class LandTextureScanner:
    """Scans ESP/ESM files for LTEX (landscape texture) records."""

    def __init__(self, tes3conv_path: Optional[Path] = None):
        """
        Initialize the scanner.

        Args:
            tes3conv_path: Path to tes3conv.exe. If None, assumes it's in PATH
                          or uses default location.
        """
        if tes3conv_path is None:
            # Try default location relative to this file
            default_path = Path(__file__).parent.parent.parent.parent / \
                          "supporting-docs" / "nif-and-esp-parsing" / "tes3conv.exe"
            if default_path.exists():
                tes3conv_path = default_path
            else:
                tes3conv_path = Path("tes3conv.exe")  # Assume in PATH

        self.tes3conv_path = tes3conv_path
        self._validate_tes3conv()

    def _validate_tes3conv(self):
        """Verify tes3conv is accessible."""
        try:
            result = subprocess.run(
                [str(self.tes3conv_path), "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0 and "Usage:" not in result.stdout:
                raise FileNotFoundError(f"tes3conv not working: {result.stderr}")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"tes3conv not found at {self.tes3conv_path}. "
                "Please provide the correct path or add it to PATH."
            )

    def _convert_esp_to_json(self, esp_path: Path) -> list[dict]:
        """
        Convert an ESP/ESM file to JSON using tes3conv.

        Args:
            esp_path: Path to the ESP/ESM file

        Returns:
            List of record objects from the plugin
        """
        # tes3conv outputs to stdout when no output file is specified
        # Use encoding='utf-8' to handle non-ASCII characters in the JSON
        result = subprocess.run(
            [str(self.tes3conv_path), str(esp_path), "--compact"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace undecodable bytes
            timeout=300  # 5 minute timeout for large files
        )

        if result.returncode != 0:
            raise RuntimeError(f"tes3conv failed for {esp_path}: {result.stderr}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse tes3conv output for {esp_path}: {e}")

    def _extract_ltex_records(self, records: list[dict], source_plugin: str) -> list[LandTextureRecord]:
        """
        Extract LTEX records from parsed plugin data.

        Args:
            records: List of record dictionaries from tes3conv
            source_plugin: Name of the source plugin file

        Returns:
            List of LandTextureRecord objects
        """
        ltex_records = []

        for record in records:
            # tes3conv uses "type": "LandscapeTexture" for LTEX records
            record_type = record.get("type", "")

            if record_type == "LandscapeTexture":
                ltex = self._parse_ltex_record(record, source_plugin)
                if ltex:
                    ltex_records.append(ltex)

        return ltex_records

    def _parse_ltex_record(self, record: dict, source_plugin: str) -> Optional[LandTextureRecord]:
        """
        Parse a single LTEX record.

        tes3conv format:
        {
            "type": "LandscapeTexture",
            "flags": "",
            "id": "AC_darkstone01",
            "index": 8,
            "file_name": "Tx_land_darkstone01.tga"
        }
        """
        record_id = record.get("id", "")
        texture_path = record.get("file_name", "")

        if not texture_path:
            return None

        # Normalize path: lowercase, forward slashes, ensure textures/ prefix
        texture_path = texture_path.lower().replace("\\", "/")

        # Add textures/ prefix if not present (LTEX paths are relative to textures/)
        if not texture_path.startswith("textures/"):
            texture_path = "textures/" + texture_path

        # Get index
        index = record.get("index")

        return LandTextureRecord(
            id=record_id,
            texture_path=texture_path,
            index=index,
            source_plugin=source_plugin
        )

    def scan_plugin(self, esp_path: Path) -> list[LandTextureRecord]:
        """
        Scan a single ESP/ESM file for LTEX records.

        Args:
            esp_path: Path to the ESP/ESM file

        Returns:
            List of LandTextureRecord objects found
        """
        if not esp_path.exists():
            raise FileNotFoundError(f"Plugin not found: {esp_path}")

        records = self._convert_esp_to_json(esp_path)
        return self._extract_ltex_records(records, esp_path.name)

    def scan_plugins(self, esp_paths: list[Path]) -> dict[str, LandTextureRecord]:
        """
        Scan multiple ESP/ESM files and merge results.

        Later plugins override earlier ones (like load order).

        Args:
            esp_paths: List of paths to ESP/ESM files, in load order

        Returns:
            Dict mapping texture_path -> LandTextureRecord (last one wins)
        """
        all_textures: dict[str, LandTextureRecord] = {}

        for esp_path in esp_paths:
            try:
                records = self.scan_plugin(esp_path)
                for record in records:
                    # Later plugins override earlier ones
                    all_textures[record.texture_path] = record
            except Exception as e:
                print(f"Warning: Failed to scan {esp_path}: {e}")

        return all_textures

    def get_land_texture_paths(self, esp_paths: list[Path]) -> set[str]:
        """
        Get just the texture paths from multiple plugins.

        Args:
            esp_paths: List of paths to ESP/ESM files

        Returns:
            Set of normalized texture paths (lowercase, forward slashes)
        """
        records = self.scan_plugins(esp_paths)
        return set(records.keys())


def find_plugins_in_directory(directory: Path,
                               extensions: tuple[str, ...] = (".esm", ".esp", ".omwaddon")
                               ) -> list[Path]:
    """
    Find all plugin files in a directory (non-recursive).

    Args:
        directory: Directory to search
        extensions: File extensions to include

    Returns:
        List of plugin paths found
    """
    plugins = []
    for ext in extensions:
        plugins.extend(directory.glob(f"*{ext}"))
        plugins.extend(directory.glob(f"*{ext.upper()}"))
    return sorted(set(plugins))


# =============================================================================
# Integration helpers for use with texture optimizers
# =============================================================================

def scan_mods_directory_for_land_textures(
    mods_dir: Path,
    tes3conv_path: Optional[Path] = None,
    verbose: bool = False
) -> set[str]:
    """
    Scan a mods directory (containing subfolders) for land texture references.

    Expected structure:
        mods_dir/
            ModA/
                ModA.esp
                Textures/...
            ModB/
                ModB.esm
                Textures/...

    Args:
        mods_dir: Path to mods directory containing mod subfolders
        tes3conv_path: Path to tes3conv.exe (optional, auto-detected if None)
        verbose: Print progress messages

    Returns:
        Set of texture stems (filename without extension, lowercase) that are
        land textures and should be excluded from optimization.
    """
    scanner = LandTextureScanner(tes3conv_path)
    all_land_texture_stems: set[str] = set()

    if not mods_dir.is_dir():
        return all_land_texture_stems

    # Scan each mod subfolder
    for mod_folder in mods_dir.iterdir():
        if not mod_folder.is_dir():
            continue

        # Find ESPs/ESMs in this mod folder
        plugins = find_plugins_in_directory(mod_folder)

        if not plugins:
            continue

        for plugin_path in plugins:
            try:
                records = scanner.scan_plugin(plugin_path)
                for record in records:
                    # Extract stem from texture path (e.g., "textures/tx_sand_01.tga" -> "tx_sand_01")
                    tex_stem = Path(record.texture_path).stem.lower()
                    all_land_texture_stems.add(tex_stem)

                if verbose and records:
                    print(f"  {plugin_path.name}: {len(records)} LTEX records")

            except Exception as e:
                if verbose:
                    print(f"  Warning: Failed to scan {plugin_path.name}: {e}")

    return all_land_texture_stems


def is_land_texture(file_path: Path, land_texture_stems: set[str]) -> bool:
    """
    Check if a file is a land texture.

    Args:
        file_path: Path to texture file
        land_texture_stems: Set of land texture stems from scan_mods_directory_for_land_textures

    Returns:
        True if this is a land texture that should be excluded
    """
    stem = file_path.stem.lower()
    return stem in land_texture_stems


def get_land_texture_exclusion_filter(land_texture_stems: set[str]):
    """
    Create a filter function for use with file scanning.

    Args:
        land_texture_stems: Set of texture stems (lowercase, no extension)

    Returns:
        Function that takes a Path and returns True if it should be EXCLUDED
    """
    def should_exclude(file_path: Path) -> bool:
        """Returns True if this file is a land texture and should be excluded."""
        return is_land_texture(file_path, land_texture_stems)

    return should_exclude


def save_exclusion_list(stems: set[str], output_path: Path) -> None:
    """
    Save land texture stems to a text file for use with texture optimizers.

    Format: One stem per line, sorted alphabetically.
    Lines starting with # are comments.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Land Texture Exclusion List\n")
        f.write("# Generated by land_texture_scanner.py\n")
        f.write("#\n")
        f.write("# These texture stems are used for terrain/landscape tiling.\n")
        f.write("# Land textures will still be processed (compression, mipmaps) but NOT resized by default.\n")
        f.write("#\n")
        f.write("# Usage: In the Regular Map Optimizer GUI, go to Filtering tab -> Land Texture Settings\n")
        f.write("#        and browse to this file.\n")
        f.write("#\n")
        f.write("# Format: One texture stem per line (filename without extension, case-insensitive)\n")
        f.write(f"# Total entries: {len(stems)}\n")
        f.write("\n")
        for stem in sorted(stems):
            f.write(f"{stem}\n")


def load_exclusion_list(input_path: Path) -> set[str]:
    """
    Load land texture stems from a text file.

    Ignores empty lines and lines starting with #.
    """
    stems = set()
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                stems.add(line.lower())
    return stems


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Scan ESP/ESM files for land texture (LTEX) records.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan a MO2-style mods folder and save exclusion list:
  python land_texture_scanner.py --mods D:/MO2/mods --output land_textures.txt

  # Scan a single plugin:
  python land_texture_scanner.py path/to/plugin.esp

  # Scan all plugins in a directory:
  python land_texture_scanner.py --dir path/to/Data Files
"""
    )

    parser.add_argument('input', nargs='?', help='Plugin file or directory to scan')
    parser.add_argument('--mods', metavar='DIR', help='Scan MO2-style mods directory (subfolders with ESPs)')
    parser.add_argument('--dir', metavar='DIR', help='Scan all plugins in a single directory')
    parser.add_argument('--output', '-o', metavar='FILE', help='Save stems to text file for use as exclusion list')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed progress')

    args = parser.parse_args()

    # Determine mode
    if args.mods:
        # Scan MO2-style mods directory
        mods_dir = Path(args.mods)
        print(f"Scanning mods directory: {mods_dir}")
        print("Looking for ESP/ESM files in mod subfolders...\n")

        land_textures = scan_mods_directory_for_land_textures(mods_dir, verbose=args.verbose)

        print(f"\n=== Summary ===")
        print(f"Total unique land texture stems: {len(land_textures)}")

        if args.output:
            output_path = Path(args.output)
            save_exclusion_list(land_textures, output_path)
            print(f"\nSaved exclusion list to: {output_path}")
        else:
            print(f"\nFirst 20 stems:")
            for stem in sorted(land_textures)[:20]:
                print(f"  {stem}")
            if len(land_textures) > 20:
                print(f"  ... and {len(land_textures) - 20} more")
            print("\nTip: Use --output to save the full list to a file")

    elif args.dir:
        # Scan all plugins in a single directory
        directory = Path(args.dir)
        plugins = find_plugins_in_directory(directory)
        print(f"Found {len(plugins)} plugins in {directory}")

        scanner = LandTextureScanner()
        print(f"\nScanning {len(plugins)} plugin(s)...")

        all_stems: set[str] = set()
        for plugin_path in plugins:
            if args.verbose:
                print(f"\n=== {plugin_path.name} ===")
            try:
                records = scanner.scan_plugin(plugin_path)
                for record in records:
                    all_stems.add(Path(record.texture_path).stem.lower())
                if args.verbose:
                    print(f"Found {len(records)} LTEX records")
            except Exception as e:
                if args.verbose:
                    print(f"  Error: {e}")

        print(f"\n=== Summary ===")
        print(f"Total unique land texture stems: {len(all_stems)}")

        if args.output:
            output_path = Path(args.output)
            save_exclusion_list(all_stems, output_path)
            print(f"\nSaved exclusion list to: {output_path}")

    elif args.input:
        # Scan specific plugin file(s)
        plugin_path = Path(args.input)
        scanner = LandTextureScanner()

        print(f"Scanning: {plugin_path.name}")
        try:
            records = scanner.scan_plugin(plugin_path)
            print(f"Found {len(records)} LTEX records:")

            all_stems: set[str] = set()
            for record in records[:10]:
                print(f"  {record.id}: {record.texture_path}")
                all_stems.add(Path(record.texture_path).stem.lower())
            for record in records[10:]:
                all_stems.add(Path(record.texture_path).stem.lower())

            if len(records) > 10:
                print(f"  ... and {len(records) - 10} more")

            if args.output:
                output_path = Path(args.output)
                save_exclusion_list(all_stems, output_path)
                print(f"\nSaved exclusion list to: {output_path}")

        except Exception as e:
            print(f"Error: {e}")

    else:
        parser.print_help()
