# gdb -p <pid> -batch -x if1_framectr.py: the counter inFamous 1's main loop waits on in func_001167C8
# (loc_00116860: usleep(5) while *(*(*(r30 - 0x7FB0)) + 8) < obj+0x7C, r30 = *(toc - 0x7E04)).
import gdb, struct
inf = gdb.selected_inferior()
base = int(gdb.parse_and_eval("*(unsigned long*)&vm_base"))
def be32(a):
    return struct.unpack(">I", bytes(inf.read_memory(base + a, 4)))[0]
toc = be32(0x771B50 + 4)
r30 = be32((toc - 0x7E04) & 0xFFFFFFFF)
r28 = be32((r30 - 0x7FB0) & 0xFFFFFFFF)
obj = be32(r28)
print("toc=0x%08X r30=0x%08X r28=0x%08X obj=0x%08X counter(+8)=0x%08X" % (toc, r30, r28, obj, be32(obj + 8)))
print("obj words:", " ".join("%08X" % be32(obj + 4 * i) for i in range(16)))
