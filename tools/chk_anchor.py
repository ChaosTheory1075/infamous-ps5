import re
s = open(__import__("os").path.expanduser("~") + '/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c').read()
t = open(__import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + '/tools/if2_patch_toolkit.py').read()
i = t.index("perfdiag: pipeline build timing")
blk = t[t.rindex('edit("libs/video/rsx_vulkan_backend.c"', 0, i):i]
old = blk.split("'''")[1]
old = old.encode().decode('unicode_escape')
for ln in old.split('\n'):
    print(repr(ln[:90]), ln in s)
