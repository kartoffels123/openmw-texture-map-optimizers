"""File discovery and path filtering for texture optimizers"""

from pathlib import Path
from typing import List, Set
import platform


class FileScanner:
    """Handles file discovery with whitelist/blacklist path filtering"""

    def __init__(self, path_whitelist: List[str] = None, path_blacklist: List[str] = None):
        """
        Initialize file scanner with optional path filters.

        Args:
            path_whitelist: List of path components that MUST be present (e.g., ["Textures"])
            path_blacklist: List of path components to exclude (e.g., ["icon", "icons", "bookart"])
        """
        self.path_whitelist = [p.lower() for p in (path_whitelist or [])]
        self.path_blacklist = [p.lower() for p in (path_blacklist or [])]
        self.is_case_sensitive = platform.system() != 'Windows'

    def should_process_path(self, path: Path) -> bool:
        """
        Check if a file path passes whitelist and blacklist filters.

        Args:
            path: Path to check

        Returns:
            True if path should be processed, False otherwise
        """
        path_str = str(path).lower()
        path_parts = [p.lower() for p in path.parts]

        # Check whitelist (must contain ALL whitelisted components)
        for required in self.path_whitelist:
            # Check if any part of the path contains the required string
            if not any(required in part for part in path_parts):
                return False

        # Check blacklist (must not contain ANY blacklisted components)
        for blocked in self.path_blacklist:
            if any(blocked in part for part in path_parts):
                return False

        return True

    def find_files(self, input_dir: Path, patterns: List[str],
                   exclude_patterns: List[str] = None) -> List[Path]:
        """
        Find files matching patterns, respecting whitelist/blacklist filters.

        Args:
            input_dir: Root directory to search
            patterns: Glob patterns to match (e.g., ["*.dds", "*.tga"])
            exclude_patterns: Patterns to exclude (e.g., ["*_n.dds", "*_nh.dds"])

        Returns:
            List of Path objects matching criteria
        """
        exclude_patterns = exclude_patterns or []
        all_files = []

        # Find files matching patterns
        for pattern in patterns:
            if self.is_case_sensitive:
                # On case-sensitive systems, we need to try multiple case variations
                # For simplicity, just use the pattern as-is
                candidates = list(input_dir.rglob(pattern))
            else:
                # On case-insensitive systems (Windows), single pattern matches all cases
                candidates = list(input_dir.rglob(pattern))

            all_files.extend(candidates)

        # Deduplicate
        all_files = list(set(all_files))

        # Apply path filters
        filtered_files = [f for f in all_files if self.should_process_path(f)]

        # Apply exclude patterns
        if exclude_patterns:
            final_files = []
            for f in filtered_files:
                should_exclude = False
                for exclude_pattern in exclude_patterns:
                    # Check if stem matches exclude pattern
                    if exclude_pattern.startswith('*'):
                        # Pattern like "*_n.dds"
                        suffix = exclude_pattern[1:]  # Remove leading *
                        if f.name.lower().endswith(suffix.lower()):
                            should_exclude = True
                            break

                if not should_exclude:
                    final_files.append(f)

            return final_files

        return filtered_files

    def find_with_suffix_filter(self, input_dir: Path, base_pattern: str,
                                include_suffixes: List[str] = None,
                                exclude_suffixes: List[str] = None) -> List[Path]:
        """
        Find files with specific filename suffixes (e.g., _n, _nh).

        Args:
            input_dir: Root directory to search
            base_pattern: Base glob pattern (e.g., "*.dds")
            include_suffixes: Only include files with these suffixes (e.g., ["_n", "_nh"])
            exclude_suffixes: Exclude files with these suffixes (e.g., ["_n", "_nh"])

        Returns:
            List of Path objects matching criteria
        """
        # Get all files matching base pattern
        all_files = self.find_files(input_dir, [base_pattern])

        filtered_files = []
        for f in all_files:
            stem_lower = f.stem.lower()

            # Check include suffixes
            if include_suffixes:
                matches = any(stem_lower.endswith(suffix.lower()) for suffix in include_suffixes)
                if not matches:
                    continue

            # Check exclude suffixes
            if exclude_suffixes:
                matches = any(stem_lower.endswith(suffix.lower()) for suffix in exclude_suffixes)
                if matches:
                    continue

            filtered_files.append(f)

        return filtered_files
