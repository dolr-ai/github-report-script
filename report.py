#!/usr/bin/env python3
"""
Wrapper script to run GitHub Report Script as a module
"""
from src.main import main
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run main

if __name__ == '__main__':
    main()
