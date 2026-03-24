"""Conftest — fixes all import paths for the test suite.
pytest loads this before any test file. No more sys.path hacks in individual tests.
"""
import os
import sys

# Add scripts/ and web/ to path so tests can import directly
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
WEB = os.path.join(ROOT, "web")

for p in [ROOT, SCRIPTS, WEB]:
    if p not in sys.path:
        sys.path.insert(0, p)
