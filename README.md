# inFAMOUS: ReCharged

inFAMOUS (2009), inFAMOUS 2 (2011) and inFAMOUS: Festival of Blood (2011), the PS3 games, recompiled to run
natively on the PS5, in one app with a launcher, by ChaosTheory1075.

> Built on [ps3recomp](https://github.com/sp00nznet/ps3recomp) and erikomis'
> [infamous2-recomp](https://github.com/erikomis/infamous2-recomp), with frame generation from
> [MihawkGen](https://github.com/mihawk-99/PS5_MihawkGen). All the credit goes to them.

An unofficial fan project, not affiliated with or endorsed by Sony Interactive Entertainment or Sucker Punch
Productions. **No game files are included:** you need your own copies of the games for the PS3.

**Download:** the newest `inFAMOUS-ReCharged-*.zip` from
[Releases](https://github.com/ChaosTheory1075/infamous-ps5/releases).

## What's in it
- inFAMOUS, inFAMOUS 2 and Festival of Blood, recompiled to run natively on the PS5 (not emulated), in one app
  (PPSA95463): the launcher's HOME page picks the game
- About 30 FPS, as on the PS3: in play sessions on a PS5 the median was 29.9-30.0 FPS in all three games
- FSR 1 upscaling to 4K, SMAA anti-aliasing and 16x texture filtering, on by default
- FRAME GENERATION (on by default): an extra frame between each two for smoother motion (it does not make the
  game itself run faster)
- Installs each game from your own PS3 dumps: the launcher checks the edition, decrypts the game's program from
  your dump and copies the game files. Uninstalling keeps your saves
- inFAMOUS 2's four updates downloaded by the launcher from Sony's update server, or copied by hand
- Trophies: unlocked in the games, listed on the launcher's TROPHIES page
- An animated menu: lightning, sparks and arcs in each game's colours (bats for Festival of Blood); turn it off
  with SETTINGS > MENU EFFECTS
- A launcher with HOME, CONTENT, SAVES (back up your saves), TROPHIES, SETTINGS and CREDITS pages

## What you need
- A jailbroken PS5 that runs homebrew apps, with a payload loader on port 9021 (etaHEN or elfldr)
- Your **own** dumps of exactly these editions (other regions and editions are not accepted by the installer):

| Game | Edition | Files |
|---|---|---|
| inFAMOUS | USA disc **BCUS98119** (v1.00 or v2.00) or Europe disc **BCES00220** | the disc itself in the PS5's drive, an `.iso` (encrypted or decrypted) or the disc's folder |
| inFAMOUS 2 | USA disc **BCUS98125** (v1.00 or v2.00) + its four updates **1.01, 1.02, 1.03, 1.04** | the disc itself in the PS5's drive, an `.iso` (encrypted or decrypted) or the disc's folder, plus the four update `.pkg` files |
| Festival of Blood | USA PSN **NPUA80657** | the `.pkg` and its `.rap` licence file |

- inFAMOUS 2's updates: the launcher downloads the four official update packages (258 MB) from Sony's PS3
  update server for you (CONTENT page: X shows a notice, X again starts it; the PS5 needs internet; each file is
  checked against Sony's checksum). You can also copy them into `install/` by hand. All four are needed.
- **Straight from the disc:** put the PS3 disc in the PS5's drive (the PS5 says "unsupported disc"; that is fine)
  and press INSTALL: the installer reads and decrypts the disc itself (Redump's published disc keys). It reads at
  the drive's speed, about 26 MB/s (inFAMOUS 2: ~12 minutes). This needs the payload loader on port 9021.
- An encrypted ISO (as dumped, Redump) works too, for the editions above; no PS3Dec step. No PS3 firmware file is needed.
- Free space: about 7.5 GB (inFAMOUS), 18 GB (inFAMOUS 2), 4.4 GB (Festival of Blood), plus the dumps until
  you delete them.

## Install
1. FTP the `PPSA95463` folder from the zip to `/data/homebrew/` on the PS5 (upgrading: copy it over the old
   one; installed games, saves and settings are kept).
2. Put your dumps (and the inFAMOUS 2 updates, if you have them) in `PPSA95463/install/`.
3. Open **inFAMOUS: ReCharged**. Pick a game and press X to install it; keep the app open until it is done.
4. When the game says PLAY, press X. You can then delete the dumps in `install/`.

Leave a game from the PS menu. `README.txt` in the download has the launcher's controls and folders.

## Known issues
- Festival of Blood: the light near green road flares flickers (a bug in the port; the PS3 shows it steady).
- A minor shadow glitch remains.
- inFAMOUS: painted road markings can sometimes show through walls.
- A short stutter the first time each effect appears (its shader is built once, then cached).
- No glare around lamps in inFAMOUS 2 and Festival of Blood; inFAMOUS: heat distortion is off.
- FRAME GENERATION: ghosting and uneven pacing when a game drops into the low 20s.
- Some Festival of Blood cutscenes play faster than on the PS3.
- DLC COSTUMES is on by default; turn it off in SETTINGS if you do not own them.

Report bugs in this repository's [Issues](https://github.com/ChaosTheory1075/infamous-ps5/issues): turn DIAGNOSTICS on for that game (SETTINGS), reproduce it once, and attach the game's log from
`PPSA95463/<if1|if2|fob>/logs/` (launcher and install problems: `PPSA95463/logs/launcher.log`).

## How it's put together
Each game is its own recompiled program: `eboot.bin` is the launcher, `if1.bin`, `if2.bin` and `fob.bin` are the
games, which the launcher starts in its place (`sceSystemServiceLoadExec`). The games are built with a fork of
ps3recomp (`toolkit/`: its base commit, our patch and our added files: the Vulkan RSX backend work, FSR 1, SMAA,
frame generation, SPU/PPU runtime changes) and erikomis' infamous2-recomp port templates, which our tools in
`tools/` edit.

| Path | What it is |
|---|---|
| `tools/ps5/launcher/` | The launcher (`launcher.c`, texts in `launcher_text.inc`) and the installer (`installer.c`: the disc in the PS5's drive, ISO (decrypted or encrypted), disc folder, PSN package, update download) |
| `tools/ps5/` | PS5 glue: `ps5_app.c` (per-game defaults, settings, trophies), `ps5_shims.c`, the linker scripts, `ps5link.sh`, `build_if2.sh` (all three games), `ps5.cmake`, `ps5cc` |
| `tools/` | The edits to the port sources and the recompiled code (each an exact-text insertion that stops if its anchor is not found once), build and measurement scripts |
| `toolkit/` | Our changes to ps3recomp: `BASE_COMMIT.txt`, `ps3recomp-fork.patch`, `added/` |
| `work/` | Test-box measurement scripts (console environment, A/B runs, soak and boot tests) |
| `DONTFLIP.md` | Changes that broke something before: read before changing a default |

No recompiled game code is in this repository: it is generated from your own copy of each game's executable.

## Build from source
The build runs on Linux (Ubuntu 24.04), as root, with clang 18 and your own game files. The scripts read
`IF_ROOT` (this repository's folder, default `$HOME/inFamous`) and the other paths in `tools/local.env.example`.

1. The toolkit fork:
   ```bash
   git clone https://github.com/NoahBPeterson/ps3recomp.git ps3recomp-fork
   cd ps3recomp-fork
   git checkout $(cat ../toolkit/BASE_COMMIT.txt)
   git apply ../toolkit/ps3recomp-fork.patch
   cp -r ../toolkit/added/. .
   ```
2. The port sources, from [infamous2-recomp](https://github.com/erikomis/infamous2-recomp) at `a69a052`, edited by
   `tools/if2_patch_rebuild.py` (all three games), then `tools/if1_patch_port.py` (inFAMOUS) or the edits in
   `tools/fob_build.sh` (Festival of Blood); `tools/if1_build.sh`, `tools/if2_build.sh` and `tools/fob_build.sh`
   run these steps and the lift from your own decrypted EBOOT.
3. After the lift: `tools/postlift.sh <if1|if2|fob>` (prints the commands; `GO=1` runs them).
4. The PS5 programs: `tools/ps5/build_if2.sh` (`GAME=if1|if2|fob`) and `tools/ps5/launcher/build_launcher.sh`,
   with the PS5 Payload SDK, Mesa RADV for the PS5 and the ps5-plume-triangle tooling (see
   [LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md) for each one's source).

## Credits
- **ChaosTheory1075**: inFAMOUS: ReCharged
- **sp00nznet** and contributors: [ps3recomp](https://github.com/sp00nznet/ps3recomp), the PS3 recompilation
  toolkit and runtime; **NoahBPeterson**: the [ps3recomp fork](https://github.com/NoahBPeterson/ps3recomp) this
  one starts from
- **erikomis**: [infamous2-recomp](https://github.com/erikomis/infamous2-recomp), the inFAMOUS 2 port templates
  used for all three games
- **mihawk-99**: [MihawkGen](https://github.com/mihawk-99/PS5_MihawkGen) frame generation,
  [PS5_Mesa](https://github.com/mihawk-99/PS5_Mesa) (Mesa RADV for the PS5) and the PS5 platform layer
- **BlackBearReloaded**: the PS5 native app runtime and `libc.prx`, and the PS5 AT9 Converter (the home screen
  music); **Nazky**: [ps5-plume-triangle](https://github.com/Nazky/ps5-plume-triangle)
- **John Törnblom** and contributors: the [PS5 Payload SDK](https://github.com/ps5-payload-dev/sdk)
- **elripalda**: [GTA IV for PS5](https://github.com/elripalda/gta4-ps5), whose PS5 helpers (`ps5_stat.c`,
  `ps5_emutls.c`, `ps5_relro_pad.c`) the games and the launcher link
- The **RPCS3** team and the PS3 Developer Wiki: how the PS3 behaves, and the SELF / NPDRM / RAP decryption the
  installer follows; **Hasster**: the RPCS3 game patches used in inFAMOUS
- Built with Mesa RADV, glslang, SPIRV-Tools, SDL2, GNU libiconv, the ATRAC3 decoder from FFmpeg (via PPSSPP),
  AMD FidelityFX FSR 1, SMAA, stb, dr_mp3, zlib, LLVM libc++, and the Oswald, Inter, Noto Sans CJK and DejaVu
  fonts
- Special thanks to **Sucker Punch Productions**, for inFAMOUS

## License
GNU General Public License v3.0 (see [LICENSE](LICENSE)) for the project's own code. Files that come from or are
derived from other projects keep their own licences, listed with their sources in
[LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md). No game files are included. inFAMOUS and all related names belong to their
owners.
