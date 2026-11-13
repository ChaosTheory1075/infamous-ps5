"""Which of these function names does the eboot already import?  nid_have.py <eboot.elf> name..."""
import base64, hashlib, re, struct, sys
data = open(sys.argv[1], 'rb').read()
have = set(m.decode() for m in re.findall(rb'([A-Za-z0-9+/-]{11})#[A-Z]{1,3}#[A-Z]{1,3}\x00', data))
for n in sys.argv[2:]:
    h = hashlib.sha1(n.encode() + bytes.fromhex('518D64A635DED8C1E6B039B1C3E55230')).digest()
    nid = base64.b64encode(struct.pack('<Q', struct.unpack('>Q', h[:8])[0])).decode()[:11].replace('/', '-')
    print(f"{n:32s} {nid} {'IMPORTED' if nid in have else 'new'}")
