"""Pytest bootstrap: put the fiscal-core root on sys.path so ``import app``
works without setting PYTHONPATH manually.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
