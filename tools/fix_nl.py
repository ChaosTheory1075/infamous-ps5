"""Replace the 'shader stalls' section of if2_patch_toolkit.py with patch_perfdiag.py's, and rejoin
the [spv] miss string that the broken copy split across two lines in the patched toolkit source."""
T = __import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + '/tools/'
mark = '# ---- shader stalls'
src = open(T + 'patch_perfdiag.py').read()
tk = open(T + 'if2_patch_toolkit.py').read()
tk = tk[:tk.index(mark)] + src[src.index(mark):]
open(T + 'if2_patch_toolkit.py', 'w').write(tk)
c = __import__("os").path.expanduser("~") + '/if2/ps3recomp-fork/libs/video/rsx_shader_spirv.cpp'
s = open(c).read()
s = s.replace('ms%s\n", spv_cache_key', 'ms%s\\n", spv_cache_key')
open(c, 'w').write(s)
print('fixed:', 'ms%s\\n", spv_cache_key' in s)
