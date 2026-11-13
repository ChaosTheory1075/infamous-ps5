# eng caster log (DIAGNOSTIC): PS3RECOMP_ENG_CASTER_LOG=<zeta hex> -- for every draw into that depth
# target that hits the index memo, the caster's size in map texels: the bounding box of its position
# attribute (float/half x3/x4) over the memo's vertex range, through the program's position rows
# c[256..259] (inFAMOUS 1's sun-shadow caster program: o0 = x*c256 + y*c257 + z*c258 + c259). A
# histogram per cascade (the n-th run of draws into the target in a frame) every 300 frames: how many
# shadow draws a small-caster skip could drop (2026-11-05, the L1 frame-rate lead).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng caster log" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''    const u32* draw_idx = g.indices;   /* idx memo: the remembered indices on a hit */''',
'''    { static int on = -1; static u32 zt;   /* eng caster log */
      if (__builtin_expect(on < 0, 0)) { const char* e = getenv("PS3RECOMP_ENG_CASTER_LOG"); zt = e && *e ? (u32)strtoul(e, NULL, 16) : 0; on = zt != 0; }
      if (on) {
          static u32 frame = ~0u, cascade, last_zeta, hist[6][8], other[6], since;
          if (frame != g.frames) { frame = g.frames; cascade = 0; last_zeta = 0;
              if (++since >= 300) { since = 0;
                  for (u32 k = 0; k < 6; k++) { u32 t = other[k]; for (u32 b = 0; b < 8; b++) t += hist[k][b];
                      if (t) fprintf(stderr, "[caster] cascade %u: %u draws/300f  <0.25:%u <0.5:%u <1:%u <2:%u <4:%u <8:%u <32:%u >=32:%u texels, no-range %u\\n",
                                     k, t, hist[k][0], hist[k][1], hist[k][2], hist[k][3], hist[k][4], hist[k][5], hist[k][6], hist[k][7], other[k]); }
                  memset(hist, 0, sizeof hist); memset(other, 0, sizeof other); } }
          if (sf.zeta_offset == zt) {
              if (last_zeta != zt && cascade < 5) cascade++;
              const u32 k = cascade;
              rsx_dsp_vertex_attr a; rsx_dsp_get_vertex_attr(&g.rsx, 0, &a);
              const eng_im_entry* e = dc.im_hit;
              const u8* base = NULL;
              const u32 esz = a.type == RSX_VTX_TYPE_FLOAT ? 4u : a.type == RSX_VTX_TYPE_HALF ? 2u : 0u;
              if (e && esz && a.size >= 3 && a.stride && !a.frequency)
                  base = eng_guest_ptr(NULL, a.location, a.offset, 1);
              if (!base) other[k]++;
              else {
                  float mn[3] = { 1e30f, 1e30f, 1e30f }, mx[3] = { -1e30f, -1e30f, -1e30f };
                  int ok = 1;
                  for (u32 i = 0; i < e->span && ok; i++) {
                      const u32 vi = (e->lo + i + e->base) & 0x000FFFFFu;
                      const u8* p = eng_guest_ptr(NULL, a.location, a.offset + vi * a.stride, esz * 3u);
                      if (!p) { ok = 0; break; }
                      for (u32 j = 0; j < 3; j++) {
                          float f;
                          if (esz == 4) { u32 w = ((u32)p[j*4] << 24) | ((u32)p[j*4+1] << 16) | ((u32)p[j*4+2] << 8) | p[j*4+3]; memcpy(&f, &w, 4); }
                          else { const u32 hb = ((u32)p[j*2] << 8) | p[j*2+1];
                                 const u32 s = (hb >> 15) << 31, ex = (hb >> 10) & 31u, m = hb & 1023u;
                                 const u32 w = ex == 0 ? s : ex == 31 ? (s | 0x7F800000u | (m << 13)) : (s | ((ex + 112u) << 23) | (m << 13));
                                 memcpy(&f, &w, 4); }
                          if (f < mn[j]) mn[j] = f; if (f > mx[j]) mx[j] = f;
                      }
                  }
                  if (!ok || !e->span) other[k]++;
                  else {
                      float m4[4][4]; memcpy(m4, g.rsx.constants[256], sizeof m4);
                      float lo[2] = { 1e30f, 1e30f }, hi[2] = { -1e30f, -1e30f };
                      for (u32 q = 0; q < 8; q++) {
                          const float x = (q & 1) ? mx[0] : mn[0], y = (q & 2) ? mx[1] : mn[1], z = (q & 4) ? mx[2] : mn[2];
                          float o[4]; for (u32 r = 0; r < 4; r++) o[r] = x * m4[0][r] + y * m4[1][r] + z * m4[2][r] + m4[3][r];
                          const float w = o[3] != 0.0f ? o[3] : 1.0f;
                          for (u32 r = 0; r < 2; r++) { const float v = o[r] / w; if (v < lo[r]) lo[r] = v; if (v > hi[r]) hi[r] = v; }
                      }
                      const float sx = (hi[0] - lo[0]) * 0.5f * (float)(sf.clip_w ? sf.clip_w : 1024u);
                      const float sy = (hi[1] - lo[1]) * 0.5f * (float)(sf.clip_h ? sf.clip_h : 1024u);
                      const float s = sx > sy ? sx : sy;
                      const u32 b = s < 0.25f ? 0 : s < 0.5f ? 1 : s < 1 ? 2 : s < 2 ? 3 : s < 4 ? 4 : s < 8 ? 5 : s < 32 ? 6 : 7;
                      hist[k][b]++;
                  }
              }
          }
          last_zeta = sf.zeta_offset;
      } }

    const u32* draw_idx = g.indices;   /* idx memo: the remembered indices on a hit */''')
open(C, "w").write(c); print("patched")
