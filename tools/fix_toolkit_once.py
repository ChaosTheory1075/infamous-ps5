p = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c"
s = open(p).read()
s = s.replace('register(t0);\n";', 'register(t0);\\n";')
s = s.replace('register(t%u);\n", u, u);', 'register(t%u);\\n", u, u);')
open(p, "w").write(s)
print("toolkit literals repaired")
