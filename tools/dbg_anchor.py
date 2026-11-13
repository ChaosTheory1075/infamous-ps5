import ast, sys
tag = sys.argv[1]
src = open(__import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + "/tools/if2_patch_toolkit.py").read()
s = open(__import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c").read()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "edit" and len(node.args) >= 4:
        try:
            t = ast.literal_eval(node.args[3])
        except Exception:
            continue
        if t != tag:
            continue
        for name, a in (("old", node.args[1]), ("new", node.args[2])):
            v = ast.literal_eval(a)
            k = 1
            while k <= len(v) and v[:k] in s:
                k += 1
            print(name, "matches whole" if k > len(v) else "diverges at %d: %r" % (k, v[max(0, k - 60):k]))
