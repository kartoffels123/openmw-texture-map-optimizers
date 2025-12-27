#!/usr/bin/env python3
"""
OpenMW Regular Texture Optimizer - Main Entry Point
Launches the GUI application for optimizing regular texture maps.
"""

import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Add core package to path
core_path = Path(__file__).parent.parent / "openmw-texture-optimizer-core" / "src"
sys.path.insert(0, str(core_path))

from src.gui.main_window import main

if __name__ == "__main__":
    main()
