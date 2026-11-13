a = open(__import__("os").path.expanduser("~") + "/if2/infamous2-lle/spu/jobmods/jobmod_cbb4b5c85d75_e59f8.bin", "rb").read()
b = open(__import__("os").path.expanduser("~") + "/fob/infamous2-lle/spu/jobmods/jobmod_524cae397099_e5a00.bin", "rb").read()
for o in (0x6C44, 0x6C64):
    wa = [a[o + 4 * k:o + 4 * k + 4] for k in range(-4, 8)]
    best = []
    for d in range(-0x40, 0x44, 4):
        wb = [b[o + d + 4 * k:o + d + 4 * k + 4] for k in range(-4, 8)]
        best.append((sum(x == y for x, y in zip(wa, wb)), d))
    best.sort(reverse=True)
    print(hex(o), "best shifts (matching words of 12, delta):", [(n, hex(d)) for n, d in best[:4]])
