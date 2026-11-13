"""Our edits of a port's CMakeLists.txt (~/<game>/infamous2-lle/CMakeLists.txt), on top of the
upstream one (infamous2-recomp @ a69a052, ~/<game>/src/infamous2-lle/CMakeLists.txt). Idempotent:
every block is skipped when its text is already there, and stops with an error when its anchor is
missing (a silently skipped edit cost two broken builds, see tools/if2_patch_toolkit.py).

  all games  SPU_LIFTED_CONST_GATES + SPU_LIFTED_LSB on the lifted SPU sources (2026-11-08)
  if1        hardware float (SPU_FLOAT_NATIVE) for the three audio images only (2026-11-07)
  if1        PPU_VM_BASE_CONST / PPU_VM_BASE_CONST_FOLD options, empty/OFF by default (2026-11-11)
  if2, fob   native867e5.c compiled in when it is present (work/native867e5; runs only with
             PS3_NATIVE_867E5=1) and kept on the float mode of the lifted job it replaces (2026-11-11)
  if2, fob   SPU_JOB_FLOAT_APPROX (ON) with SPU_JOB_FLOAT_APPROX_MODS (2026-11-10):
               if2 default  jobmod_d0d15ec83992_ea2a0   (Edge Geometry only, +3.6%)
               fob default  empty = every jobmod        (+7%; RPCS3's default for FoB)
             DONTFLIP: if1 gets no approx float; if2 beyond Edge Geometry is not verified.
  fob        SPU_JOB_FLOAT_NATIVE option block (OFF; measurement only)

usage: patch_port_cmake.py <if1|if2|fob> <port dir (.../infamous2-lle)>
A changed cache default (SPU_JOB_FLOAT_APPROX_MODS) reaches an existing build dir only with
-DSPU_JOB_FLOAT_APPROX_MODS=... or a fresh configure.
"""
import sys
from pathlib import Path

game = sys.argv[1]
if game not in ("if1", "if2", "fob"):
    sys.exit("usage: patch_port_cmake.py <if1|if2|fob> <port dir>")
p = Path(sys.argv[2]) / "CMakeLists.txt"
s = p.read_text()


def edit(tag, marker, old, new):
    """Replace old by new once; skip when marker (unique text of new) is already in the file."""
    global s
    if marker in s:
        print(f"{tag}: already there")
        return
    if s.count(old) != 1:
        sys.exit(f"CMakeLists.txt: {tag}: anchor found {s.count(old)} times, expected 1")
    s = s.replace(old, new, 1)
    if marker not in s:
        sys.exit(f"CMakeLists.txt: {tag}: marker missing after the edit")
    print(f"{tag}: applied")


J867 = "jobmod_867e5d2348b3_e2898"

# const gates + lsb (all games)
edit("const gates",
     'COMPILE_DEFINITIONS "SPU_USE_DISPATCH_MT;SPU_LIFTED_CONST_GATES;SPU_LIFTED_LSB")',
     "        COMPILE_DEFINITIONS SPU_USE_DISPATCH_MT)\n",
     '        COMPILE_DEFINITIONS "SPU_USE_DISPATCH_MT;SPU_LIFTED_CONST_GATES;SPU_LIFTED_LSB")\n')

# Everything below goes after the block that sets the SPU sources' properties.
TAIL_ANCHOR = ('        set_source_files_properties(${SPU_SOURCES} PROPERTIES COMPILE_OPTIONS "-O2")\n'
               "    endif()\n"
               "endif()\n")

if game == "if1":
    IF1_AUDIO = (
        "# spu float native: inFAMOUS 1's audio images (Boomrang DSP plugins 0002-0004) use the hardware float\n"
        "# result without the SPU range checks (runtime/spu/spu_helpers.h). Gameplay code keeps the checks.\n"
        "foreach(_au spu_0002_at_0068FE00 spu_0003_at_006A3800 spu_0004_at_006BF480)\n"
        '    if(EXISTS "${SPU_DIR}/${_au}/spu_recomp.c")\n'
        '        set_property(SOURCE "${SPU_DIR}/${_au}/spu_recomp.c" APPEND PROPERTY COMPILE_DEFINITIONS SPU_FLOAT_NATIVE)\n'
        "    endif()\n"
        "endforeach()\n")
    edit("if1 audio float native", "foreach(_au spu_0002_at_0068FE00", TAIL_ANCHOR, TAIL_ANCHOR + IF1_AUDIO)
    # if1 guest base const (2026-11-11): the PPU_VM_BASE_CONST / PPU_VM_BASE_CONST_FOLD options, ahead of Install.
    # Empty (the default) = off and nothing compiles differently; main.cpp's side is tools/if1_patch_port.py,
    # the lifted headers' side tools/patch_ppu_vmb_header.py.
    INSTALL = ("# ---------------------------------------------------------------------------\n"
               "# Install\n")
    VMB = (
        "# B1 constant guest base. -DPPU_VM_BASE_CONST=0x1000000000ull compiles the guest window's host address into the\n"
        "# lifted PPU code (recompiled/ppu_recomp.h and lle/*/*_recomp.h: PPU_VMB) instead of loading the vm_base global\n"
        "# on every access, and makes main.cpp put the window exactly there (Linux: mmap MAP_FIXED_NOREPLACE; PS5:\n"
        "# ps5_guest_vm_require_base) and stop at startup if it is anywhere else. The value must be a multiple of 4 GB;\n"
        "# 0x1000000000 is where the PS5 maps it. Empty (the default) = off, and nothing is compiled differently.\n"
        "# Only the lifted TUs and main.cpp get the definition, so the runtime and the SPU sources are not rebuilt.\n"
        "# PPU_VM_BASE_CONST_FOLD=ON also lets clang fold the vector accesses' alignment test against the constant. That\n"
        "# changes those functions' control flow, so a -fprofile-use profile from a build without it stops matching them\n"
        "# (they are then compiled without profile, with no warning): turn it on only for the instrumented build AND the\n"
        "# build that uses its profile. OFF keeps every existing profile valid.\n"
        'set(PPU_VM_BASE_CONST "" CACHE STRING\n'
        '    "Host address of the guest window compiled into the lifted PPU code (e.g. 0x1000000000ull); empty = off")\n'
        'option(PPU_VM_BASE_CONST_FOLD "With PPU_VM_BASE_CONST: fold alignment tests too (needs a profile from such a build)" OFF)\n'
        'if(NOT "${PPU_VM_BASE_CONST}" STREQUAL "")\n'
        '    message(STATUS "Guest base:      constant ${PPU_VM_BASE_CONST} (PPU_VM_BASE_CONST), fold ${PPU_VM_BASE_CONST_FOLD}")\n'
        "    set_property(SOURCE main.cpp ${RECOMP_SOURCES} ${LLE_SOURCES} APPEND PROPERTY\n"
        '        COMPILE_DEFINITIONS "PPU_VM_BASE_CONST=${PPU_VM_BASE_CONST}")\n'
        "    if(PPU_VM_BASE_CONST_FOLD)\n"
        "        set_property(SOURCE ${RECOMP_SOURCES} ${LLE_SOURCES} APPEND PROPERTY\n"
        '            COMPILE_DEFINITIONS "PPU_VM_BASE_CONST_FOLD")\n'
        "    endif()\n"
        "endif()\n"
        "\n")
    edit("if1 guest base const", 'set(PPU_VM_BASE_CONST "" CACHE STRING', INSTALL, VMB + INSTALL)
else:
    # native867e5 source (if2, fob)
    old = ('        list(APPEND SPU_SOURCES ${SPU_LIFTED}\n'
           '             "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")\n')
    new = (old +
           "        # native867e5: native C version of the culling/gather job (work/native867e5; PS3_NATIVE_867E5=1, default off)\n"
           '        if(EXISTS "${SPU_DIR}/' + J867 + '/native867e5.c")\n'
           '            list(APPEND SPU_SOURCES "${SPU_DIR}/' + J867 + '/native867e5.c")\n'
           "        endif()\n")
    edit("native867e5 source", '        if(EXISTS "${SPU_DIR}/' + J867 + '/native867e5.c")\n', old, new)

    # spu float approx (if2, fob): per-game default list
    mods = {"if2": "jobmod_d0d15ec83992_ea2a0", "fob": ""}[game]
    SRC = "${CMAKE_CURRENT_SOURCE_DIR}/spu/"
    APPROX = (
        "# spu float approx (2026-11-10): RPCS3-\"approximate\"-like float for the gameplay job modules\n"
        "# (runtime/spu/spu_helpers.h SPU_FLOAT_APPROX=2; FoB/if2 run fine with approximate xfloat in RPCS3).\n"
        'option(SPU_JOB_FLOAT_APPROX "approximate SPU float in the jobmods" ON)   # 2026-11-10: Edge Geometry only (FoB +9.5%, if2 +3.6%)\n'
        "if(SPU_JOB_FLOAT_APPROX)\n"
        '    set(SPU_JOB_FLOAT_APPROX_MODS "' + mods + '" CACHE STRING "jobmods (;-list) that get approx float; empty = all")\n'
        "    if(SPU_JOB_FLOAT_APPROX_MODS)\n"
        '        set(_jma "")\n'
        "        foreach(_m ${SPU_JOB_FLOAT_APPROX_MODS})\n"
        '            list(APPEND _jma "' + SRC + '${_m}/spu_recomp.c")\n'
        "        endforeach()\n"
        "    else()\n"
        '        file(GLOB _jma "' + SRC + 'jobmod_*/spu_recomp.c")\n'
        "    endif()\n"
        "    foreach(_f ${_jma})\n"
        '        set_property(SOURCE "${_f}" APPEND PROPERTY COMPILE_DEFINITIONS "SPU_FLOAT_APPROX=2")\n'
        "    endforeach()\n"
        "    # native867e5 must use the same float mode as the lifted job it replaces\n"
        '    if("' + SRC + J867 + '/spu_recomp.c" IN_LIST _jma AND EXISTS "' + SRC + J867 + '/native867e5.c")\n'
        '        set_property(SOURCE "' + SRC + J867 + '/native867e5.c" APPEND PROPERTY COMPILE_DEFINITIONS "SPU_FLOAT_APPROX=2")\n'
        "    endif()\n"
        "endif()\n")
    NATIVE = (
        "# spu float native for the gameplay job modules (RPCS3: FoB runs fine with approximate xfloat).\n"
        "# SPU_JOB_FLOAT_NATIVE=ON (default OFF while measured).\n"
        'option(SPU_JOB_FLOAT_NATIVE "native SPU float in the jobmods" OFF)\n'
        "if(SPU_JOB_FLOAT_NATIVE)\n"
        '    set(SPU_JOB_FLOAT_NATIVE_GLOB "jobmod_*" CACHE STRING "which jobmods")\n'
        '    file(GLOB _jm "' + SRC + '${SPU_JOB_FLOAT_NATIVE_GLOB}/spu_recomp.c")\n'
        "    foreach(_f ${_jm})\n"
        '        set_property(SOURCE "${_f}" APPEND PROPERTY COMPILE_DEFINITIONS SPU_FLOAT_NATIVE)\n'
        "    endforeach()\n"
        "endif()\n")
    edit("spu float approx", "option(SPU_JOB_FLOAT_APPROX ", TAIL_ANCHOR,
         TAIL_ANCHOR + APPROX + (NATIVE if game == "fob" else ""))
    # An older tree may carry the approx block with another game's default list.
    want = '    set(SPU_JOB_FLOAT_APPROX_MODS "' + mods + '" CACHE STRING'
    if want not in s:
        sys.exit(f"CMakeLists.txt: SPU_JOB_FLOAT_APPROX_MODS default is not the {game} one ({mods or 'empty'})")

p.write_text(s)
print(f"{game}: CMakeLists.txt ok")
