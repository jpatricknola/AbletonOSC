#--------------------------------------------------------------------------------
# Live-free unit tests for the OSC dispatcher.
#
# This package is deliberately separate from tests/, whose __init__.py sends
# /live/api/reload at import time and therefore mutates a running Live
# instance during collection. Nothing here may import tests/, bind a fixed
# port, or require Ableton. The test-suite item in issues.md owns folding this
# into a restructured tests/ tree.
#
# Run with:  python3 -m pytest tests_unit/
# pytest is the only dependency beyond the standard library. Last verified
# with CPython 3.12.7 (/opt/anaconda3/bin/python3) and pytest 7.4.4.
#--------------------------------------------------------------------------------
