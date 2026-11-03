"""FORK glue rules (run: python3 -I test_block_glue.py). Taps and wipes never enter; a deliberate press/hold does."""
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("glue", os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-to-cube.py"))
glue = importlib.util.module_from_spec(spec); spec.loader.exec_module(glue)
d = glue.decide
cases = [
    ("tap never enters",                d({"gesture": "tap"}, False),                                        (None, False)),
    ("wipe spins, stays outside",       d({"gesture": "stroke", "direction": "left to right", "distance": 1}, False), (("spin", 1.0, 0.0), False)),
    ("vertical wipe only spins",        d({"gesture": "stroke", "direction": "top to bottom", "distance": 1}, False), (("spin", 0.0, -1.0), False)),
    ("light press never enters",        d({"gesture": "press", "pressure": 0.3, "duration": 1.0}, False),     (None, False)),
    ("quick firm press never enters",   d({"gesture": "press", "pressure": 0.9, "duration": 0.1}, False),     (None, False)),
    ("firm held press enters",          d({"gesture": "press", "pressure": 0.9, "duration": 0.5}, False),     ("enter", True)),
    ("the same again comes back out",   d({"gesture": "press", "pressure": 0.9, "duration": 0.5}, True),      ("back", False)),
    ("iPad: one still finger enters",   d({"gesture": "rest", "fingers": 1, "duration": 1.1}, False),         ("enter", True)),
    ("iPad: a resting palm doesn't",    d({"gesture": "rest", "fingers": 4, "duration": 3.0}, False),         (None, False)),
]
bad = [name for name, got, want in cases if got != want]
for name, got, want in cases:
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else f"got {got} want {want}")
sys.exit(1 if bad else 0)
