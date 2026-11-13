"""if1_interp_continue.py <stubs.cpp>...: the SPU_INTERP_CONTINUE default of if1_patch_port.py, applied
to already-patched inFamous 1 trees."""
import sys
from pathlib import Path

for f in sys.argv[1:]:
    p = Path(f)
    s = p.read_text()
    if "SPU_INTERP_CONTINUE" in s:
        print(f"{f}: already set")
        continue
    if "    if1_english();\n" not in s:
        sys.exit(f"{f}: if1_english() call not found")
    s = s.replace("    if1_english();\n", "    if1_english();\n    setenv(\"SPU_INTERP_CONTINUE\", \"1\", 0);\n", 1)
    p.write_text(s)
    print(f"{f}: SPU_INTERP_CONTINUE=1 by default")
