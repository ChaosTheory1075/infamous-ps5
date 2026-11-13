#!/bin/bash
# vk smaa: rebuilds smaa_<pass>_spv.h from smaa_<pass>.comp (glslangValidator, vulkan1.0). Run after changing a shader.
set -euo pipefail
cd "$(dirname "$0")"
for p in edges weights blend; do
  glslangValidator -V --target-env vulkan1.0 -I. -o smaa_$p.spv smaa_$p.comp
  python3 - smaa_$p.spv s_smaa_${p}_spv > smaa_${p}_spv.h <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read(); w = struct.unpack('<%dI' % (len(d) // 4), d)
print('static const uint32_t %s[] = {' % sys.argv[2])
for i in range(0, len(w), 8): print('    ' + ', '.join('0x%08x' % x for x in w[i:i + 8]) + ',')
print('};')
PY
  rm smaa_$p.spv
done
