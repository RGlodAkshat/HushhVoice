import os
import sys

# Ensure api/ is on sys.path so imports like "services.*" work in tests.
API_DIR = os.path.dirname(os.path.dirname(__file__))
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)
