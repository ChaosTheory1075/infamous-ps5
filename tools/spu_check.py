"""Which of the EU port's SPU programs exist byte-for-byte in another inFamous EBOOT.elf.

Job modules: the installer's extract_jobmods() (C0DEC0DE layout), named jobmod_<sha1[:12]>_e<entry>.
SPU ELF images: the port names them spu_<n>_at_<file offset>; here we list the US build's embedded
SPU ELFs (\x7fELF with e_machine SPU = 0x17) so their offsets can be compared.

usage: spu_check.py <EBOOT.elf> <port spu patch dir>
"""
import hashlib
import struct
import sys
from pathlib import Path

d = open(sys.argv[1], "rb").read()
port = {p.name for p in Path(sys.argv[2]).iterdir() if p.is_dir()}


def be32(o):
    return struct.unpack_from(">I", d, o)[0]


mods = []
i = 0x20
while i + 4 <= len(d):
    if d[i:i + 4] == b"\xC0\xDE\xC0\xDE" and (i - 0x20) % 4 == 0:
        s = i - 0x20
        entry, size = be32(s + 0x10), be32(s + 0x14)
        if all(be32(s + 4 * k) >> 25 == 0x21 for k in range(4)) and 0x24 <= size <= 0x40000 \
                and s + size <= len(d) and entry < size:
            name = f"jobmod_{hashlib.sha1(d[s:s + size]).hexdigest()[:12]}_e{entry:04X}"
            if name not in mods:
                mods.append(name)
            i = s + max(size, 0x24)
            continue
    i += 4

eu_mods = sorted(n for n in port if n.startswith("jobmod_"))
same = [n for n in mods if n in port]
print(f"job modules: US {len(mods)}, EU port patches {len(eu_mods)}, identical {len(same)}")
print("  EU-only:", [n for n in eu_mods if n not in mods])

elfs = []
o = d.find(b"\x7fELF", 1)
while o != -1:
    if o + 0x14 <= len(d) and struct.unpack_from(">H", d, o + 0x12)[0] == 0x17:
        elfs.append(o)
    o = d.find(b"\x7fELF", o + 1)
print("US SPU ELF offsets:", [f"{x:08X}" for x in elfs])
print("EU port SPU images:", sorted(n for n in port if n.startswith("spu_")))
