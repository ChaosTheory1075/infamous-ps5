"""Turn a copy of the inFamous 2 port (infamous2-recomp/infamous2-lle) into an inFamous 1 (EU disc
BCES00220) one: the executable-specific numbers in rebuild.py and stubs.cpp, and inFamous 1's own edits of
main.cpp (constant guest base, off unless built with PPU_VM_BASE_CONST) and game_patches.cpp (RPCS3 data patches,
the g_if1_unst_audio switch). Run after tools/if2_patch_rebuild.py. Idempotent.

Numbers for the EU EBOOT.elf (sha256 095d8514...):
  code end       0x55dc4c   (last of 194 import stubs 0x55dc2c + 0x20; tools/if1_map.sh)
  policy module  file 0x68CD80, 0x2D80 bytes, guest 0x69CD80, LS base 0xA00, entry 0x2BF0
                 (inFAMOUSreborn's installer/infamous.toml, pm-carve / pm-wrap)
inFamous 2's extra SPU entry points (policy module 0xA2C, spu_0000 0x9C84/0x9DB8, two job modules,
data modules 0x6C44/0x6C64) name inFamous 2's code; the SPU interpreter covers missing ones.

usage: if1_patch_port.py <port src dir (…/infamous2-lle)>
"""
import re
import sys
from pathlib import Path

port = Path(sys.argv[1])
r = port / "tools" / "rebuild.py"
s = r.read_text()
reps = [
    ("TITLE_ID = 'NPUA80638'", "TITLE_ID = 'BCES00220'"),
    ("'--code-end', '0x742e18'", "'--code-end', '0x55dc4c'"),
    ("f.seek(0x8D5B00)", "f.seek(0x68CD80)"),
    ("blob = f.read(11904)", "blob = f.read(0x2D80)"),
    ("'--entry', '0xA00', '--out', 'spu/images/wwsjob_pm_at_008E5B00.elf'",
     "'--entry', '0x2BF0', '--out', 'spu/images/wwsjob_pm_at_0069CD80.elf'"),
    ("                         '--extra-funcs', 'wwsjob_pm_at_008E5B00=0xA2C',\n"
     "                         '--extra-funcs', 'spu_0000_at_007FA100=' + ','.join(SPU_IMAGE_EXTRA)],",
     "                         ],"),
    ("'--title', 'infamous2', '--eboot', self.elf,", "'--title', 'infamous1', '--eboot', self.elf,"),
    ("JOBMOD_EXTRA = (('jobmod_ab654d30fd90_efe70', ('0x15280', '0x155EC')),\n"
     "                ('jobmod_cbb4b5c85d75_e59f8', ('0x6C44', '0x6C64')))",
     "JOBMOD_EXTRA = ()"),
    # inFamous 1 has no DA7ABA5E data modules (and may have no relocatable jobs): optional steps.
    ("        self.run('jobs', [self.py, os.path.join(tools, 'lift_datamods.py'), self.elf,\n"
     "                          '--out', 'spu', '--extra', '0x6C44,0x6C64'], cwd=self.port)\n",
     "        try:\n"
     "            self.run('jobs', [self.py, os.path.join(tools, 'lift_datamods.py'), self.elf,\n"
     "                              '--out', 'spu'], cwd=self.port)\n"
     "        except StepError:\n"
     "            emit('WARN', 'jobs', 'no data modules in this executable')\n"),
    ("        self.run('jobs', [self.py, os.path.join(tools, 'lift_relocmods.py'), self.elf, '--out', 'spu'],\n"
     "                 cwd=self.port)\n",
     "        try:\n"
     "            self.run('jobs', [self.py, os.path.join(tools, 'lift_relocmods.py'), self.elf, '--out', 'spu'],\n"
     "                     cwd=self.port)\n"
     "        except StepError:\n"
     "            emit('WARN', 'jobs', 'no relocatable jobs in this executable')\n"),
]
for a, b in reps:
    if b in s:
        continue
    if a not in s:
        sys.exit(f"rebuild.py: anchor not found: {a[:60]!r}")
    s = s.replace(a, b, 1)
r.write_text(s)

st = port / "stubs.cpp"
s = st.read_text()
s = s.replace("#define WWSJOB_PM_EA    0x008E5B00u", "#define WWSJOB_PM_EA    0x0069CD80u")
s = s.replace("#define WWSJOB_PM_SIZE  11904u", "#define WWSJOB_PM_SIZE  0x2D80u")
# spu_workloads.c registers inFamous 1's 8 embedded SPU images first: the policy module is image 9.
s = s.replace("#define WWSJOB_PM_IMAGE 3", "#define WWSJOB_PM_IMAGE 9")
# English on the EU disc. The game (func_00089F80) keeps, at 0x00720868, 7 x { u32 count, u32 list } of
# the languages each release ships (game numbers: 1 English, 2 French, ... 17 English UK); BCES00220's
# list is Fr/De/Es/It/Nl, and a system language not in it gets the first, French. The disc has every
# language's data, so for an English PS3_LANG (the default) point BCES00220's entry at a one-language
# list holding English (taken from the US release's list), before the game runs. (Same idea as
# inFAMOUSreborn's infamous_lang.h, which does it from the system-language read.)
LANG_FN = r'''
/* inFamous 1 EU: English (see tools/if1_patch_port.py). */
#include <cstdlib>
#include <cstring>
extern "C" uint8_t* vm_base;
static uint32_t if1_be32(uint32_t ea)
{
    const uint8_t* p = vm_base + ea;
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static void if1_put_be32(uint32_t ea, uint32_t v)
{
    uint8_t* p = vm_base + ea;
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}
static void if1_english(void)
{
    const char* l = getenv("PS3_LANG");
    if (l && *l && strncmp(l, "en", 2) != 0) return;
    const uint32_t LISTS = 0x00720868u;
    const uint32_t us_n = if1_be32(LISTS), us_list = if1_be32(LISTS + 4u);
    const uint32_t eu_n = if1_be32(LISTS + 8u);
    if (us_n != 3u || eu_n != 5u) {
        fprintf(stderr, "[if1 lang] language lists not where expected (%u/%u): left alone\n", us_n, eu_n);
        return;
    }
    for (uint32_t i = 0; i < us_n; i++)
        if (if1_be32(us_list + 4u * i) == 1u) {
            if1_put_be32(LISTS + 8u + 4u, us_list + 4u * i);
            if1_put_be32(LISTS + 8u, 1u);
            fprintf(stderr, "[if1 lang] BCES00220 language list -> English\n");
            return;
        }
}
'''
if "if1_english" not in s:
    s = s.replace("extern \"C\" void ps3_load_prx_modules(void)\n{\n",
                  LANG_FN + "\nextern \"C\" void ps3_load_prx_modules(void)\n{\n    if1_english();\n", 1)
    if "if1_english();" not in s:
        sys.exit("stubs.cpp: ps3_load_prx_modules not found")
# Job module image 4 (EA 0x6B3880) enters at LS 0x18BB0, which its lift lacks: the interpreter runs
# it to the next lifted entry, and without SPU_INTERP_CONTINUE that hand-back ended the SPU thread
# (SPURS aborted, the RSX then waited on that job's command buffer every frame). Set before any SPU
# runs; an explicit SPU_INTERP_CONTINUE=0 still wins.
if "SPU_INTERP_CONTINUE" not in s:
    s = s.replace("    if1_english();\n",
                  "    if1_english();\n    setenv(\"SPU_INTERP_CONTINUE\", \"1\", 0);\n", 1)
st.write_text(s)

(port / "gpu_light.c").write_text(
    "/* inFamous 1: no GPU light offload (inFamous 2's hooks name its own light job module). */\n"
    "void infamous2_gpu_light_install(void) {}\n")
(port / "gpu_ssao.c").write_text(
    "/* inFamous 1: no GPU SSAO offload (inFamous 2's hooks name its own SSAO job module). */\n"
    "void infamous2_gpu_ssao_install(void) {}\n")


def edit_once(path, tag, marker, pairs):
    """Apply (old, new) replacements to path unless marker is already there. Each old must occur exactly
    once (else stop: a silently skipped edit cost two broken builds), and marker must be there afterwards."""
    t = path.read_text()
    if marker in t:
        print(f"{path.name}: {tag}: already there")
        return
    for old, new in pairs:
        if t.count(old) != 1:
            sys.exit(f"{path.name}: {tag}: anchor found {t.count(old)} times, expected 1: {old[:70]!r}")
        t = t.replace(old, new, 1)
    if marker not in t:
        sys.exit(f"{path.name}: {tag}: marker missing after the edit")
    path.write_text(t)
    print(f"{path.name}: {tag}: applied")


# main.cpp, B1 constant guest base (2026-11-11, OFF unless the port is configured with -DPPU_VM_BASE_CONST=<addr>,
# tools/patch_port_cmake.py): the guest window at the compiled-in base or a stop at startup. Needs
# tools/if2_patch_rebuild.py first (it anchors on the "ps5 decl" / "vm" blocks) and, on the PS5,
# ps5_guest_vm_require_base in tools/ps5/ps5_app.c when the switch is on. The lifted headers' side is
# tools/patch_ppu_vmb_header.py (postlift.sh).
VMB_FUNCS = r'''/* B1 constant guest base: built with -DPPU_VM_BASE_CONST=<address>, the lifted code's inline guest accesses
 * (recompiled/ppu_recomp.h, PPU_VMB) use that address instead of loading vm_base, so the guest window has to be
 * exactly there. Linux maps it there (MAP_FIXED_NOREPLACE: never over something else, never moved); the PS5 app
 * is told to accept no other address (ps5_guest_vm_require_base, tools/ps5/ps5_app.c). vm_base_const_check stops
 * the process before any guest code runs if the two differ (Windows and macOS do not place the window, so a
 * build with the switch stops there). Without the switch nothing here changes. */
#if defined(PPU_VM_BASE_CONST)
#include <errno.h>
extern "C" { const uint64_t ppu_vm_base_const_value = (uint64_t)(PPU_VM_BASE_CONST); }   /* the header's link guard */
static_assert((uint64_t)(PPU_VM_BASE_CONST) != 0 && ((uint64_t)(PPU_VM_BASE_CONST) & 0xFFFFFFFFull) == 0,
              "PPU_VM_BASE_CONST must be a non-zero multiple of 4 GB (host pointers are truncated to guest addresses)");
#  if defined(__PROSPERO__)
extern "C" void ps5_guest_vm_require_base(uint64_t base);
#  elif defined(__linux__)
#    ifndef MAP_FIXED_NOREPLACE
#      define MAP_FIXED_NOREPLACE 0x100000   /* Linux 4.17+; older headers lack the name */
#    endif
static uint8_t* vm_map_const_base(void)
{
    void* const want = (void*)(uintptr_t)ppu_vm_base_const_value;
    void* const got = mmap(want, VM_SIZE, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    if (got == MAP_FAILED) {
        fprintf(stderr, "FATAL: could not map the guest window at its compiled-in base %p (%s): the range up to %p "
                        "is taken or unavailable (see /proc/self/maps; sanitizer builds use it). Stopping.\n",
                want, strerror(errno), (void*)((uintptr_t)want + VM_SIZE));
        fflush(stderr);
        abort();
    }
    if (got != want) {            /* a kernel older than 4.17 takes the address as a hint only */
        fprintf(stderr, "FATAL: the guest window was mapped at %p instead of its compiled-in base %p "
                        "(kernel without MAP_FIXED_NOREPLACE?). Stopping.\n", got, want);
        fflush(stderr);
        abort();
    }
    return (uint8_t*)got;
}
#  endif
static void vm_base_const_check(void)
{
    if ((uint64_t)(uintptr_t)vm_base == ppu_vm_base_const_value) return;
    fprintf(stderr, "FATAL: guest memory is at %p, but this build has the guest base compiled in as 0x%llx "
                    "(PPU_VM_BASE_CONST): the lifted code would read and write the wrong memory. Stopping.\n",
            (void*)vm_base, (unsigned long long)ppu_vm_base_const_value);
    fflush(stderr);
    abort();
}
#endif
'''
VMB_DECL = "#if defined(__PROSPERO__)\nextern \"C\" uint8_t* ps5_map_guest_vm(uint64_t size);\n#endif\n"
VMB_PS5 = "#  if defined(__PROSPERO__)\n    vm_base = ps5_map_guest_vm(VM_SIZE);\n"
VMB_ELSE = "    ppu_vm_size = 0xE0000000u;\n#  else\n"
VMB_END = "#  endif\n#endif\n    return vm_base != nullptr;\n"
edit_once(port / "main.cpp", "guest base const", "static void vm_base_const_check(void)", [
    (VMB_DECL, VMB_FUNCS + VMB_DECL),
    (VMB_PS5, "#  if defined(__PROSPERO__)\n"
              "#    if defined(PPU_VM_BASE_CONST)\n"
              "    ps5_guest_vm_require_base(ppu_vm_base_const_value);   /* no other address is accepted */\n"
              "#    endif\n"
              "    vm_base = ps5_map_guest_vm(VM_SIZE);\n"),
    (VMB_ELSE, "    ppu_vm_size = 0xE0000000u;\n"
               "#  elif defined(PPU_VM_BASE_CONST) && defined(__linux__)\n"
               "    vm_base = vm_map_const_base();   /* at the compiled-in base, or the process stops with a message */\n"
               "    ppu_vm_size = 0;\n"
               "#  else\n"),
    (VMB_END, "#  endif\n#endif\n"
              "#if defined(PPU_VM_BASE_CONST)\n"
              "    if (vm_base) vm_base_const_check();\n"
              "#endif\n"
              "    return vm_base != nullptr;\n"),
])

# game_patches.cpp (rebuild.py's port step copies it into the port; it used to be edited in the port only):
#   if1 rpcs3 data     two of RPCS3's inFamous data patches (game patch database, EU BCES00220 01.00, by Hasster),
#                      written at startup only where the EBOOT holds the original value; PS3_IF1_RPCS3_DATA=0 = off,
#                      PS3_IF1_REFRACTION=1 keeps the refraction one off (2026-11-07)
#   if1 unstable audio the g_if1_unst_audio switch that tools/patch_if1_unstable_audio.py's edits of the lifted code
#                      read (PS3_IF1_AUDIO_PATCH=0 = off; tools/ps5/ps5_app.c sets 0 for if1)
GP_DATA = r'''/* if1 rpcs3 data: two of RPCS3's inFamous patches (EU disc BCES00220 01.00, PPU-d0c3e2a1...) that the player
 * used in the emulator, built in -- written only where the EBOOT still holds the original value:
 *   "Disable refraction/shifting effect" (Hasster): 0x00786910 0.1 -> 0 ("disables broken shifting/refracting")
 *   "Disable speed limit" (Hasster): 0x007615D8 1/15 s -> 0.15 s, the largest frame step the game takes before it
 *   runs in slow motion (below 15 fps the world slowed down).
 * PS3_IF1_RPCS3_DATA=0: neither. */
static void if1_rpcs3_data(void)
{
    const char* e = getenv("PS3_IF1_RPCS3_DATA");
    if ((e && *e == '0') || !vm_base) return;
    struct { uint32_t ea, was, now; const char* name; } w[] = {
        { 0x00786910u, 0x3DCCCCCDu, 0x00000000u, "Disable refraction/shifting effect" },
        { 0x007615D8u, 0x3D888889u, 0x3E19999Au, "Disable speed limit" } };
    const char* rf = getenv("PS3_IF1_REFRACTION");   /* 1: keep the refraction (signed blend emulated by the renderer) */
    for (auto& x : w) {
        if (x.ea == 0x00786910u && rf && *rf == '1') { fprintf(stderr, "[patch] \"%s\": off (PS3_IF1_REFRACTION=1)\n", x.name); continue; }
        uint8_t* p = vm_base + x.ea;
        const uint32_t v = (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
        if (v != x.was) { fprintf(stderr, "[patch] \"%s\": 0x%08X holds 0x%08X, not this EBOOT's: skipped\n", x.name, x.ea, v); continue; }
        p[0] = (uint8_t)(x.now >> 24); p[1] = (uint8_t)(x.now >> 16); p[2] = (uint8_t)(x.now >> 8); p[3] = (uint8_t)x.now;
        fprintf(stderr, "[patch] \"%s\" (Hasster, RPCS3): on\n", x.name);
    }
}

'''
GP_AUDIO = r'''
/* if1 unstable audio (tools/patch_if1_unstable_audio.py): RPCS3's canary patch "(Experimental) Unstable audio"
 * (Hasster) in the lifted code, on unless PS3_IF1_AUDIO_PATCH=0. */
extern "C" int g_if1_unst_audio = 1;
__attribute__((constructor)) static void if1_unst_audio_init(void)
{
    const char* e = getenv("PS3_IF1_AUDIO_PATCH");
    g_if1_unst_audio = !(e && *e == '0');
    fprintf(stderr, "[patch] if1 unstable audio (RPCS3 canary, Hasster): %s\n", g_if1_unst_audio ? "on" : "off");
}
'''
GP_APPLY = "extern \"C\" void infamous2_apply_patches(const char* elf_path)\n{\n"
GP_TAIL = "            (double)width / (double)height);\n}\n"
gp = port / "game_patches.cpp"
if not gp.read_text().endswith(GP_TAIL):
    if "g_if1_unst_audio" not in gp.read_text():
        sys.exit("game_patches.cpp: if1 unstable audio: the file no longer ends with the PS3_ASPECT function")
edit_once(gp, "if1 rpcs3 data", "if1_rpcs3_data();   /* if1 rpcs3 data */", [
    (GP_APPLY, GP_DATA + GP_APPLY + "    if1_rpcs3_data();   /* if1 rpcs3 data */\n")])
edit_once(gp, "if1 unstable audio", "extern \"C\" int g_if1_unst_audio = 1;", [
    (GP_TAIL, GP_TAIL + GP_AUDIO)])

print("inFamous 1 port numbers applied")
