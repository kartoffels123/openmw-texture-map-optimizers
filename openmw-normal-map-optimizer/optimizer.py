#!/usr/bin/env python3
"""
OpenMW Normal Map Optimizer - Main Entry Point
Launches the GUI application for optimizing normal map textures.
"""

import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.gui.main_window import main

if __name__ == "__main__":
    main()
