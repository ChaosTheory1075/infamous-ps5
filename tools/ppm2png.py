#!/usr/bin/env python3
"""Binary PPM (P6) to PNG with only the standard library: ppm2png.py <in.ppm> <out.png> [scale]"""
import struct
import sys
import zlib


def read_ppm(path):
    d = open(path, 'rb').read()
    tok, i = [], 0
    while len(tok) < 4:
        while d[i:i + 1].isspace():
            i += 1
        if d[i:i + 1] == b'#':
            while d[i:i + 1] != b'\n':
                i += 1
            continue
        j = i
        while not d[j:j + 1].isspace():
            j += 1
        tok.append(d[i:j]); i = j
    w, h = int(tok[1]), int(tok[2])
    return w, h, d[i + 1:i + 1 + w * h * 3]


def write_png(path, w, h, rgb):
    raw = b''.join(b'\x00' + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(t, b):
        c = struct.pack('>I', len(b)) + t + b
        return c + struct.pack('>I', zlib.crc32(t + b) & 0xFFFFFFFF)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


w, h, px = read_ppm(sys.argv[1])
s = int(sys.argv[3]) if len(sys.argv) > 3 else 1
if s > 1:
    out = bytearray()
    for y in range(0, h, s):
        row = px[y * w * 3:(y + 1) * w * 3]
        for x in range(0, w, s):
            out += row[x * 3:x * 3 + 3]
    px, w, h = bytes(out), (w + s - 1) // s, (h + s - 1) // s
write_png(sys.argv[2], w, h, px)
print(sys.argv[2], w, h)
