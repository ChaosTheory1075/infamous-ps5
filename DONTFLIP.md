# DONTFLIP: changes that already broke something. Read before changing any of these.

Every entry also has a `DONTFLIP` comment at the code itself: `grep -rn DONTFLIP ~/inFamous/tools ~/if2/ps3recomp-fork`.

| Setting / change | What it broke | When | Where |
|---|---|---|---|
| inFAMOUS 1 refraction ON (`PS3_IF1_REFRACTION=1`) | Smoke as flat grey cut-outs, blocky explosion patches, start-screen explosion, smeared edges | 2026-11-08 (user video Veyra-2026-11-08-090311) | ps5_app.c, console if1/env.txt |
| Audio tuning as a default for all games (PS3_AUDIO_PRIO 640, QUEUE 20, PACE 8, spu 1001 priority) | inFAMOUS 2 crash (SPURS abort after the karma movie); must stay inFAMOUS 1 only | 2026-11-08 | ps5_app.c, cellAudio.c |
| if2/FoB audio PRIO / PACE / spu 1001 priority (2026-11-10: ONLY QUEUE 36 + HOLD_MIN 1 were given to G_IF2FAM, for the cut-outs) | the full set crashed inFAMOUS 2 (SPURS abort after the karma movie); if QUEUE 36 is ever suspected, revert it with env.txt PS3_AUDIO_QUEUE=8 PS3_AUDIO_HOLD_MIN=2 | 2026-11-10 | ps5_app.c |
| Texture sign extension ON (`PS3_TEX_SEXT=1`) | FoB character heads neon green / magenta | 2026-11-07 | rsx_texture_layout.c |
| GPU-lighting depth copy released when the handle is unchanged | inFAMOUS 2 water/whole-scene flicker + magenta | 2026-11-08 | rsx_draw_engine.c |
| One depth copy per depth buffer (`PS3_VK_DSNAP=0`) | Black/wrong effects, dark Beast | 2026-11-08 | rsx_vulkan_backend.c |
| vperm rewrite of lifted PPU code (tools/ppu_vperm_fast.py) | inFAMOUS 1 hung on the title screen | 2026-11-07 (parked) | ppu_vmx.h |
| Uploads via upload_when_idle.sh / agent polling / auto-deploy watchers | ~5 min uploads, traffic around two console crashes | 2026-11-08 | tools/ps5/upload_when_idle.sh |
| Console access by several sessions at once | PS5 crashed (twice) | 2026-11-08 | (rule: one action at a time, only when the user says) |

## Rules learnt
- Test a visual change in a scene that actually contains the effect (route1 has no smoke/explosions).
- Per-game tuning goes in ps5_app.c behind the game check, never as a runtime default.
- Upload = `curl -T file url -T file url ...` once, when the user says. Nothing else.
| PPU_THREAD_MAX back to 64 (runtime/syscalls/sys_ppu_thread.h) | if1: after 24 autosaves the "Game State Thread" (joinable, never joined) can't get a slot -> "There was an error while saving." loops forever, screen dimmed, pause-menu save/load broken | 2026-11-08 (user's PS5 play, log work/diag/if1_dark_1833) | sys_ppu_thread.h (512) |
| One default line for inFAMOUS 1 AND inFAMOUS 2/FoB in ps5_app.c | if1 tuning in shared defaults crashed if2 (SPURS abort, 11-08); user wants 2+FoB locked together and 1 separate | 2026-11-08 user | ps5_app.c G_IF1 / G_IF2FAM |
| spu coh fence: RELEASE (plain mov) for the PPU reservation store / no seq_cst fence in spu_coh_notify_write* or after RESV_SET in GETLLAR | lost SPURS signal -> EDGE zlib task never runs -> load-screen hang on "_spuEvF" (~1 in 4 boots at 13 threads; console logo/streaming hangs) | 2026-11-10 (BC-250 runs + litmus test) | runtime/spu/spu_coherency.c, spu_channels.c "spu coh fence" |
| PS5 readback buffers back to uncached host memory (PS3_VK_HOST_CACHED=0) | FoB 21.4 -> 10.8 fps (memmove of 2x3.7 MB/frame from uncached memory) | 2026-11-10 | rsx_vulkan_backend.c "vk host cached" |
| SPU_JOB_FLOAT_APPROX on inFAMOUS 1 (any module) | RPCS3: approximate xfloat makes if1 enemies disappear / crashes the giant conduit fight | RPCS3 wiki (memory spu-float-and-direction) | infamous2-lle CMakeLists (if1 has no such option on) |
| Approx float on more than Edge Geometry in if2/FoB without a visual check | Cole vanished with native float on all FoB jobmods (frest(0) NaN); Edge-only L2 is verified | 2026-11-10 | CMakeLists SPU_JOB_FLOAT_APPROX_MODS |
| `PS3RECOMP_ENG_TEXHASH_ASYNC=1` (async texture hash) on inFAMOUS 2 / FoB WITHOUT `PS3RECOMP_ENG_TEXHASH_SAFE=1` | if2 street manhole covers + crossing paint drop out for ~0.5 s at a time (console only; the test box never showed it) | 2026-11-12 (user's console bisect on t35b, env.txt: ASYNC=0 alone = manholes stay) | ps5_app.c G_IF2FAM + console_env.sh: t37 C = ASYNC 1 + SAFE 1, t37 A/B = ASYNC 0; fallback env.txt PS3RECOMP_ENG_TEXHASH_ASYNC=0 |
| `PS3RECOMP_ENG_RMW_DIRECT=2` on inFAMOUS 2 / FoB WITHOUT `PS3RECOMP_VK_RMW_INPASS=1` | if2 trolley rails drop out (barrier macro closed the pass, decal drawn outside any pass); Wolf's rooftop glitch gone with ASYNC=0 + RMW_DIRECT=0 together (not split) | 2026-11-12 (same bisect: + RMW_DIRECT=0 = rails stay) | ps5_app.c G_IF2FAM + console_env.sh, rsx_vulkan_backend.c "vk rmw inpass": t37 C = RMW 2 + INPASS 1, t37 A/B = RMW 0; fallback env.txt PS3RECOMP_ENG_RMW_DIRECT=0 |

## PS3_GCM_REPORT_MEM (occlusion-query lamp glare) - if2/FoB - OFF (2026-11-11)
t31 shipped real occlusion queries (unset = mode 2) without ever being watched in a scene with characters: the lamp glare
sprite draws THROUGH characters (if2 new game, FBI agent scene, ~187 s of work cut.sh). The user stopped a capture over it.
Default is now 0 for G_IF2FAM (ps5_app.c, console_env.sh). Do not enable until that exact scene is clean on the BC-250.

## PS3_FG_GUARD (frame-generation ghost guard) - all games - OFF (2026-11-11)
t31 extended the guard to the default flow+mvwarp frame generation without a console check; the user got pink/purple
blinking in the if2 intro cutscene with frame generation on (launcher default on their console). Default 0 in ps5_app.c.
BC-250 runs use PS3_FRAMEGEN=0 and cannot show this: any frame-generation change needs a console check by the user first.
