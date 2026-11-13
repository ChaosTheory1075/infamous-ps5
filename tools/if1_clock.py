# gdb -p <pid> -batch -x if1_clock.py: inFamous 1's frame clock (BCES00220 0x7BC650, from inFAMOUSreborn's
# infamous_clock_probe.h): raw dt, timer0..2 ticks / dt / scale.
import gdb, struct, time
inf = gdb.selected_inferior()
base = int(gdb.parse_and_eval("*(unsigned long*)&vm_base"))
B = 0x7BC650
w = struct.unpack(">36I", bytes(inf.read_memory(base + B, 0x90)))
f = lambda i: struct.unpack(">f", struct.pack(">I", w[i]))[0]
print("t=%d raw_dt=%g | t0 ticks=%u dt=%g scale=%g | t1 ticks=%u dt=%g scale=%g | t2 ticks=%u dt=%g scale=%g" % (
    time.time(), f(0), w[1], f(2), f(4), w[5], f(6), f(8), w[9], f(10), f(12)))
