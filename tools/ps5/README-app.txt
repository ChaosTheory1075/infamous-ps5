@TITLE@ for PS5 -- private test build
=====================================================================

A static recompilation of the PS3 game, not an emulator: the game's PowerPC and SPU code was
translated to native code, the firmware it needs (liblv2, libsre) too, and the graphics go
through Vulkan (Mesa's RADV driver, built into eboot.bin). Built from your own copy of the game.

What is in this folder
  eboot.bin, sce_sys/, sce_module/   the app
  game/                              the game data from your copy (@SOURCE@)
  cache/shaders/                     translated shaders (shipped pre-filled where possible; the app
                                     adds the rest while you play, so later sessions stutter less)
  logs/@LOG@.log@LOGPAD@written every run; the run before is kept as
                                     logs/@LOG@.prev.log. It has a
                                     status line every 15 s, the frame rate every 10 s, the
                                     controller once a second, and a crash report if it crashes.
  env.txt                            optional settings, one VAR=value per line (see below)

Install
  Copy the whole folder to the console's homebrew folder like the other recomp apps
  (for example /data/homebrew/@TITLEID@), then start it from the home screen.

First start
@FIRSTRUN@
  - The first time each effect appears its shader is translated, which can cause a short
    hitch; it is kept in cache/shaders/ afterwards.

Controls (DualSense)
  Buttons as on the PS3 controller. OPTIONS = START, touchpad click = SELECT,
  L2/R2 analog.

env.txt (optional, one per line, e.g.  PS3_LANG=fr)
  PS3_LANG=en|fr|es|de|it|nl|pt|...   game language (default en)
  PS5_STACK_CAP_MB=64                 stack per game thread, MB (raise if the log ends in a crash
                                      deep in game code)
  PS3RECOMP_VK_BATCH=0                one GPU submission per draw (slower; a test if the picture
                                      breaks)
  PAD_TRACE=0                         no controller line in the log
  PS3RECOMP_ENG_FPSLOG=0              no frame-rate line in the log
  PS3_FTRACE=                         no frame timeline (logs/ftrace.txt, 120-180 s into a run:
                                      play at least 3 minutes, in the open world)
  PS3RECOMP_VK_DUMP=                  no screenshots (default: a half-size one every 10 s to
                                      logs/shot.NNN.ppm, PS3RECOMP_VK_DUMP_EVERY=<seconds>)
  PS5_LOG_LINEBUF=1                 write the log line by line (default: buffered, flushed every
                                      second; the last second is lost if the app crashes)
  PS3_USLEEP_KICK_US=0                the game's short polling sleeps use the system timer again
                                      (default: they wake as soon as an SPU writes memory)
  PS3RECOMP_ENG_GPU_LIGHT=            inFAMOUS 2 and Festival of Blood: light the frame on the SPUs,
                                      not the GPU (if the lighting ever looks wrong)
  PS3RECOMP_ENG_GPU_SSAO=             inFAMOUS 2 and FoB: ambient occlusion on the SPUs, not the GPU
  PS3RECOMP_ENG_GPU_SSAO_WB=0         with GPU ambient occlusion, skip copying depth and normals
                                      back each frame (faster; the night sky may lose its clouds)
  PS3_VK_DEPTH_RGBA8_GPU=0            depth-as-colour copies on the CPU, as before

Known gaps in this build
  - inFAMOUS 2 and Festival of Blood light their frame and compute their ambient occlusion on
    the GPU (as the Mac port does); inFAMOUS 1 uses the SPU jobs for both.
@GAPS@
  - First console run of this port: if it does not reach the menu, send its log (logs/@LOG@.log).
