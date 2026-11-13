# Third-party code and assets in inFAMOUS: ReCharged

The project's own code is GPL-3.0 (see `LICENSE`). This repository and the release built from it contain, or are built
from, the components below. "Where" says where each is used: **repo** = files in this repository (path given),
**games** = linked into `if1.bin`, `if2.bin`, `fob.bin`, **launcher** = linked into `eboot.bin`, **payload** =
`payloads/inst-payload.elf`, **zip** = other files of the release download. Licence texts are in this folder.

## In this repository

| Component | Licence | Source | Where |
|---|---|---|---|
| ps3recomp (sp00nznet and contributors), via the fork NoahBPeterson/ps3recomp, base commit in `toolkit/BASE_COMMIT.txt` | MIT, `ps3recomp-MIT.txt` | https://github.com/sp00nznet/ps3recomp, https://github.com/NoahBPeterson/ps3recomp | repo: `toolkit/` is a patch to it plus added files (our changes, MIT); games |
| infamous2-recomp (erikomis), commit a69a052 | MIT, `infamous2-recomp-MIT.txt` | https://github.com/erikomis/infamous2-recomp | repo: `tools/` edit its port templates (`tools/main_guard_counts.patch` holds context lines of its `main.cpp`); games |
| MihawkGen / PS5_MihawkGen (mihawk-99), commit c57232a9 | GPL-3.0-or-later, `MihawkGen-LICENSE.md`, `MihawkGen-THIRD_PARTY_NOTICES.txt` (also next to the code) | https://github.com/mihawk-99/PS5_MihawkGen | repo: `toolkit/added/libs/video/framegen/` (its sources and `fg_network_blob.inc`, the network weights); our wrappers `vk_framegen*.cpp` and `fgflow/` (based on its mvwarp method) are GPL-3.0-or-later as derived work; games |
| ps5-native-app-boilerplate runtime (BlackBearReloaded), via Nazky/ps5-plume-triangle | GPL-3.0-or-later, `GPL-3.0.txt` | https://github.com/Nazky/ps5-plume-triangle | repo: `tools/ps5/ps5-pie-tls.ld` and `ps5-pie-unwind-tls.ld` are copies of its linker scripts with a PT_TLS (GPL-3.0-or-later); games, launcher (`app_crt`, `app_cpp_runtime`); zip: `sce_module/libc.prx` (made by its `libc_builder`, `libc.prx-README.md`) |
| Dear ImGui (Omar Cornut) 1.92.9b | MIT, `DearImGui-MIT.txt` | https://github.com/ocornut/imgui | repo: `toolkit/added/third_party/imgui/` (macOS overlay only; not in the PS5 programs) |
| SMAA (Jimenez, Echevarria, Masia, Navarro, Gutierrez) | MIT, `SMAA-MIT.txt` | https://github.com/iryoku/smaa | repo: `toolkit/added/third_party/smaa/`, `toolkit/added/libs/video/smaa/` (ported passes); games |
| AMD FidelityFX Super Resolution 1 (EASU, RCAS) | MIT, `AMD-FSR1-MIT-header.txt` | https://github.com/GPUOpen-Effects/FidelityFX-FSR | repo: `toolkit/added/libs/video/fsr1/easu.comp`, `rcas.comp` (written after FsrEasuF / FsrRcasF) and their SPIR-V headers; games |
| FXAA 3.11 (Timothy Lottes) | none applies (written from the algorithm; no NVIDIA file used) | - | repo: `toolkit/added/libs/video/fsr1/fxaa.comp`; games |
| DejaVu Sans (glyph bitmaps rendered from it by `tools/ps5/gen_overlay_font.py`) | Bitstream Vera / Arev licence, DejaVu changes public domain, `DejaVu-LICENSE.txt` | https://dejavu-fonts.github.io | repo: `toolkit/added/libs/video/vk_overlay_font.h` (FPS counter); games |
| RPCS3 (decryption port; elsewhere a behaviour reference) | GPL-2.0, see "Licence findings" | https://github.com/RPCS3/rpcs3 | repo: `tools/ps5/launcher/installer.c` (SELF / NPDRM / RAP decryption "the way RPCS3 does it": its `unself.cpp` / `key_vault.cpp`, `rap_to_rif`, and the key values from its `key_vault`); launcher, payload. Comments citing RPCS3 behaviour in the toolkit patch (`rsx_fp_decompiler.c`, `rsx_draw_engine.c`, `rsx_texture_layout.c/.h`, `rsx_vp_decompiler.c/.h`, `cellSysutilNpEula.c/.h`, `spu_helpers.h`, `ppu_vmx.h`, `cellMsgDialog.h`, `cellGame.c`, `sceNp.c`, `cellAvconfExt.c`, `cellGem.c`, `rsx_metal_backend.m`, two tests, `docs/ONLINE.md`) and in `tools/` (16 files); upstream ps3recomp states RPCS3 was used only as a reference |
| RPCS3 game patches by Hasster ("Disable refraction/shifting effect", "Disable speed limit", canary "(Experimental) Unstable audio") | no licence text found | https://github.com/RPCS3/rpcs3 (patch database) | repo: `tools/if1_patch_port.py` (two data patches, `PS3_IF1_RPCS3_DATA=0` = off), `tools/patch_if1_unstable_audio.py` (off by default); games (inFAMOUS) |
| Metal Gear Rising PS5 port's quick menu (`mgr_quick_menu.cpp`) | GPL-3.0 (that repository) | - | repo: `toolkit/added/libs/video/vk_quickmenu.inc` is drawn "as the other PS5 recomps draw it", modelled on that menu; whether code was copied is not established |

## Built from, not in this repository

| Component | Licence | Source | Where |
|---|---|---|---|
| PS5 Payload SDK (John Törnblom and contributors) v0.42 + mihawk-99/PS5_PayloadSDK (`libps5platform.a`) | GPL-3.0-or-later (headers in `include/freebsd`: BSD), `GPL-3.0.txt` | https://github.com/ps5-payload-dev/sdk, https://github.com/mihawk-99/PS5_PayloadSDK | games, launcher, payload |
| musl regex (TRE) and dlmalloc, inside `libps5platform.a` | MIT / BSD-2-Clause, `musl-COPYRIGHT.txt`; MIT-0, `dlmalloc-MIT0-header.txt` | https://musl.libc.org | games, launcher |
| GTA IV for PS5 helpers (elripalda): `ps5/tools/ps5_stat.c`, `ps5_emutls.c` (from LLVM compiler-rt emutls), `ps5_relro_pad.c` | GPL-3.0 (that repository); emutls: Apache-2.0 WITH LLVM-exception | https://github.com/elripalda/gta4-ps5 | games, launcher (compiled by `tools/ps5/ps5link.sh`, `tools/ps5/launcher/build_launcher.sh`) |
| Mesa RADV for the PS5 (PS5_Mesa, mihawk-99 and the Mesa contributors) | MIT (some files Apache-2.0 OR MIT, BSL-1.0), `Mesa-license.rst`, `Mesa-licenses-*.txt` | https://github.com/mihawk-99/PS5_Mesa | games, launcher |
| zlib 1.3.1 (Jean-loup Gailly, Mark Adler), inside Mesa | zlib, `zlib-LICENSE.txt` | https://zlib.net | games, launcher |
| LLVM libc++, libc++abi, libunwind, compiler-rt builtins (clang 18) | Apache-2.0 WITH LLVM-exception, `LLVM-18-debian-copyright.txt` | https://llvm.org | games, launcher |
| glslang 15.4.0 | BSD-3-Clause / MIT / Apache-2.0; `glslang_tab.cpp` GPL-3 with the Bison exception; `glslang-LICENSE.txt` | https://github.com/KhronosGroup/glslang | games (built by `tools/ps5/build_glslang*.sh`) |
| SPIRV-Tools v2025.3, SPIRV-Headers | Apache-2.0, `SPIRV-Tools-Apache-2.0.txt`; MIT-style, `SPIRV-Headers-LICENSE.txt` | https://github.com/KhronosGroup/SPIRV-Tools, https://github.com/KhronosGroup/SPIRV-Headers | games |
| Vulkan headers | Apache-2.0 OR MIT, `Vulkan-Headers-LICENSE.md` | https://github.com/KhronosGroup/Vulkan-Headers | games, launcher (headers) |
| SDL2 2.30.12 (pacbrew-repo v0.40.2) | zlib, `SDL2-zlib.txt` | https://github.com/libsdl-org/SDL, https://github.com/ps5-payload-dev/pacbrew-repo | games |
| GNU libiconv 1.17 (pacbrew-repo v0.40.2) | LGPL-2.1-or-later, `LGPL-2.1.txt`, `libiconv-header-notice.txt` | https://www.gnu.org/software/libiconv/ | games |
| libsamplerate 0.2.2 (pacbrew-repo) | BSD-2-Clause, `libsamplerate-BSD-2.md` | https://github.com/libsndfile/libsamplerate | games link line (probably not pulled in) |
| ATRAC3 / ATRAC3+ decoder from FFmpeg, via PPSSPP `ext/at3_standalone` (in the upstream ps3recomp tree) | LGPL-2.1-or-later, `LGPL-2.1.txt`, `at3_standalone-README.txt` | https://github.com/hrydgard/ppsspp | games |
| stb_image, stb_image_write, stb_truetype (Sean Barrett) | MIT or public domain, `stb-MIT-or-PublicDomain.txt` | https://github.com/nothings/stb | games (ps3recomp `libs/codec`, `libs/font`), launcher |
| dr_mp3 0.7.4 (David Reid), with minimp3 (lieff) | public domain (Unlicense) or MIT-0, `dr_mp3-PublicDomain-or-MIT0.txt` | https://github.com/mackron/dr_libs | launcher (the copy in GTA IV for PS5's `src/ps5/hub`) |
| ps5-native-tool (BlackBearReloaded) | GPL-3.0-or-later | https://github.com/Nazky/ps5-plume-triangle | used to sign the programs; not shipped |
| PS5 AT9 Converter (BlackBearReloaded) | see its repository | - | made the home screen music; not shipped as code |

## Fonts in the release download (zip)

| Font | Licence |
|---|---|
| Oswald (`launcher/font_title.ttf`, `font_item.ttf`) | SIL OFL 1.1, `OFL-Oswald.txt` |
| Inter (`launcher/font_body.ttf`) | SIL OFL 1.1, `OFL-Inter.txt` |
| Noto Sans CJK (`launcher/font_cjk.ttc`) | SIL OFL 1.1, `NotoSansCJK-LICENSE.txt` |
| DejaVu Sans (`launcher/font_fallback.ttf`) | Bitstream Vera / Arev, `DejaVu-LICENSE.txt` |

## Licence findings (not legal advice)

1. **GPL-3.0 parts in every PS5 program.** The games and the launcher statically link GPL-3.0-or-later code
   (PS5 Payload SDK platform layer, the ps5-native-app-boilerplate runtime, GTA IV for PS5's helpers, and in the
   games MihawkGen). GPL-3.0 asks for the whole program's Corresponding Source. The games also contain code
   recompiled from Sony's PS3 programs (the game executables and firmware modules), which cannot be published or
   put under the GPL; this repository therefore cannot be a complete Corresponding Source for the game programs.
2. **RPCS3-derived code.** The SELF / NPDRM / RAP decryption in `tools/ps5/launcher/installer.c` is ported from
   RPCS3, which is licensed under GPL-2.0.
3. **LGPL-2.1 (libiconv, ATRAC3 decoder)** is linked statically; relinking a modified library needs the other
   object files, which runs into point 1.
4. **No licence found** for the RPCS3 game patch values (Hasster) and the PS5 AT9 Converter.
5. **Keys:** `installer.c` holds publicly known PS3 package, SELF/NPDRM, NP klicensee and RAP keys (as RPCS3's
   `key_vault` does).

No game files are included. inFAMOUS, PlayStation and PS5 are trademarks of their owners.
