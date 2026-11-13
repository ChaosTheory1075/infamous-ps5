// vk smaa: SMAA 1x (Jimenez et al., SMAA.hlsl: MIT, see LICENSE.txt; the copy here returns "no edge" instead
// of discard, as compute shaders have no discard; from the MP3 PS5 port's tools/smaa) as three compute
// passes on the guest-size frame before EASU (vk_fsr.inc). One invocation per pixel; SMAA's vertex shader
// offsets are computed here. One layout for all passes: bindings 0..2 sampled, 3 the storage output.
layout(local_size_x = 8, local_size_y = 8) in;
layout(push_constant) uniform SmaaPC { vec4 metrics; } pc;   // 1 / width, 1 / height, width, height

#define SMAA_GLSL_4
#define SMAA_PRESET_HIGH
#define SMAA_RT_METRICS pc.metrics
#include "SMAA.hlsl"

bool SmaaPixel(out ivec2 pixel, out vec2 texcoord) {
  pixel = ivec2(gl_GlobalInvocationID.xy);
  texcoord = (vec2(pixel) + 0.5) * pc.metrics.xy;
  return all(lessThan(vec2(pixel), pc.metrics.zw));
}
