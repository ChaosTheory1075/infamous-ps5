"""Map the inFamous 2 port's extra job-module entry points (rebuild.py JOBMOD_EXTRA) onto FoB's modules
by finding the same 32 bytes of code (offsets are module-relative)."""
A = __import__("os").path.expanduser("~") + "/if2/infamous2-lle/spu/jobmods/"
B = __import__("os").path.expanduser("~") + "/fob/infamous2-lle/spu/jobmods/"
pairs = {
    ("jobmod_ab654d30fd90_efe70", "jobmod_db1f4c51136a_efe60"): (0x15280, 0x155EC),
    ("jobmod_cbb4b5c85d75_e59f8", "jobmod_524cae397099_e5a00"): (0x6C44, 0x6C64),
}
for (ia, fb), offs in pairs.items():
    a = open(A + ia + ".bin", "rb").read()
    b = open(B + fb + ".bin", "rb").read()
    out = []
    for o in offs:
        for span in (32, 24, 16):
            pat = a[o:o + span]
            hits = [i for i in range(0, len(b) - span, 4) if b[i:i + span] == pat]
            if len(hits) == 1:
                out.append(hex(hits[0]))
                break
        else:
            out.append("?")
    print(fb, [hex(o) for o in offs], "->", out)
