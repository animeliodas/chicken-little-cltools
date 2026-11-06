# Chicken Little (PC, Steam) — reverse-engineering notes

Build: `Chick.exe`, PE timestamp `1130358323` (2005-10-26), x86, image base `0x400000`, no ASLR.
Engine: Avalanche Software in-house engine (same family as *Tak and the Power of Juju*), Direct3D 8, DirectInput 7, Bink.

## Protection / unpacking

* `Chick.exe` and `Launcher.exe` are wrapped with **SteamStub** (`.bind` section, entry point inside it, `.text` encrypted).
* Steam always starts `Launcher.exe` (settings dialog); "Play!" runs
  `Chick.exe -dxdiskdriveletter=X -dxfullscreen -dxadapter=0 -dxresolution=N`.
  Starting `Chick.exe` directly makes SteamStub relaunch through Steam.
* Other switches parsed by the game: `-dxshaderdebugging`, `-dxadapterres`. Hidden launcher checkboxes:
  "Run Windowed (test only)", "Run Debug executable (test only)" (`ChickDebug.exe`, not shipped).
* Unpacked image for static analysis: set `DumpImage=1` in `CLTools/clhook.ini`, start the game once, then
  `py -3 CLTools/scripts/rebuild_dump.py` → `CLTools/dump/Chick_unpacked.exe` (load in Ghidra/IDA/REA, base 0x400000).
  The proxy DLL dumps from `Direct3DCreate8`, i.e. after the stub has decrypted `.text`.
* Incremental linking: most functions are reached through `jmp` thunks at `0x401000–0x40b000`.

## Settings

* Registry `HKCU\SOFTWARE\Disney\Chicken Little\Settings`: `resolution`, `anti-aliasing`, `mouse look`, `invert mouse`, `mouse sensitivity`.
* `%APPDATA%\Buena Vista Games\Chicken Little\`: `Chick1a/b/c.sav` (92180 bytes each), `keymap.ini`, controller ini files.

## Timing (why the game is frame-rate dependent)

| Address | Meaning |
|---|---|
| `0x65FC10` | `GetTimeMs()` – integer milliseconds from `QueryPerformanceCounter`. If byte `[0x856C1C]` is set it returns `[0x856C20]` (frozen time). |
| `0x441B30` | per-frame timer update: `dt = now - last` (ms, integer), clamped to `[timer+0x48]`; mode `[timer+0x3C]`: 0 = fixed `[0x83ED90]*16.667 ms`, 1 = `dt >> shift` (slow), 2 = `dt << shift` (fast), else real dt |
| `0x640170` | EndScene + Present |
| `0x6402A0` | end of frame: optional **engine frame limiter**: if byte `[0x83ED86]` ≠ 0 it `Sleep`s until `[0x83ED90] * 16.668 ms` passed (only `Sleep`, ±1–4 ms jitter) |
| `0x83ED86` | byte, engine limiter on/off (toggled by `0x5E5CF0`, the debug-menu "Tgl V-Sync"). Retail default: **off** |
| `0x83ED90` | byte, frame interval in 1/60 s units. Retail default **2** (= designed for 30 fps). Setter `0x5E5680` |
| `0x856BC0` / `0x856BC8` | QPC base / QPC frequency of the timer module |

Consequences: the game simulates with the *real* integer-ms frame time, so physics/animation depend on the frame rate
(and at 60 fps dt alternates 16/17 ms). With the CLHook limiter the game runs at a steady 60 fps
(Bink videos and the attract-mode demo run at 30).

## Objects

| Address / offset | Meaning |
|---|---|
| `[0x831A38]` | `CGame*` singleton |
| `game+0x658` | `CAvatar* players[8]`, `game+0x678` = player count |
| `game+0x60C` | level-progress state (`+4` = progression id) |
| `avatar+0x44` | vec3 position (render copy) |
| `avatar+0x50` | 3×3 rotation matrix (12-byte rows); yaw = `atan2(m[2][0], m[2][2])` |
| `avatar+0x74` | vec3 velocity, units/s (used by `Avatar__GetSpeed`) |
| `avatar+0x12AC` | vec3 **authoritative mover position** — write here to teleport |
| `avatar-0x1A0, +0x378, +0x11FC, +0x12C8` | other position copies (teleport writes all of them) |
| `0x85783C` | string `worlds\<World>\<World>` of the loaded world |
| `0x7F6EDC` | level table, 33 × 0x2C: `+4` world dir, `+8` name string id, `+0xC` music, `+0x10` flags (bit 0 = listed) |
| `[game+0x60C]+4` | current level index into that table |

Level table (index: world): 0 intro (title-screen backdrop, flags 0x100), 1 SchoolYard, 2 dodgeball, 3 gooseychase,
4 townSquare, 5 BballPractice, 6 BigGame, 7 RT_ToCLsHouse, 8 beamchase, 9 flight1, 10 aliensu1, 11 antigrav, 12 space1,
13 flight2, 14 transtube, 15 cornmaze, 16 cannon, 17 RT_FireTruck, 18 bosstube, 19 aliensu2, 20 space2, 21 flight3,
22 Final_Boss, 23 RT_FinalEscape, 24 flight4, 25 baseball, 26 holoplay, 27 townArt, 28 theatre, 29 showcase,
30 holoJon, 31 holoChris, 32 garage. `theatre` is a normal sub-level reached in-game (not in Select Level).
Entries 25-27 and 29-32 are dev leftovers without world data, so no unused playable world ships with the PC version.
Any world can be loaded directly by pointing entry 1's dir pointer (`0x7F6F0C`) at another entry's string and choosing
*Select Level -> Late for School* (Inspector -> Levels) - handy for practising sub-levels.

## Script API

The game script VM registers 1222 native functions with `RegisterScriptFunc(handler, name, flags)` at `0x5DAAA0`
(called from `0x48A000–0x48F000`). Full list: `docs/script_functions.txt` (name, thunk, handler).
Handlers have the signature `handler(ScriptCtx*, int argc)`; `0x5DA530` pops an argument, `0x5DA450` pushes the result.
Interesting ones: `Game__SwitchToLevel 0x474C70`, `Game__WarpToEntryPoint 0x474F80`, `SetGameTimerSpeed 0x4756C0`,
`GetFrameSec 0x477530`, `Avatar__SetInvincible 0x477460`, `Avatar__SetJumpVars 0x47B7E0`, `Avatar__SetGravity 0x478620`,
`Game__GetAvatar 0x473270`.

## Developer debug menu

* `0x463250` builds the whole developer menu, but nothing calls it; its owner class (debug HUD layer, vtable `0x798078`,
  ctor `0x443D30`, draws "FPS" and "Avatar1 Pos/Vel" in `0x451500`) is never constructed, and the central command
  handlers `0x4567A0` (SimLoop/Statistics/Collision/Cut Scenes/Powerups/...) and `0x4567B0` (Camera) are **stubbed to
  `ret`**. Show Collision, Show Coords, Quick Level Reset, Slow Motion, Free Camera etc. cannot be revived from the menu.
* Surviving handlers (Inspector -> Debug menu):
  * renderer flags `0x83ED74` Lighting, `0x83ED75` Fog, `0x83ED76` Vertex colours, `0x83ED77` **Wire-frame**,
    `0x83ED80` Diffuse maps, `0x83ED8B` View back buffer, `0x83ED8D` Bone render (0-3), `0x83EB3C` Distortion;
    toggles `0x5E5AF0 0x5E5B30 0x5E5B10 0x5E5B50 0x5E5BF0 0x5E5D40 0x5E5B60 0x5DDFE0`.
    `0x83ED84` "Draw Boxes" is written but never read (dead).
  * modes: visibility `[0x839C34]` (cycle `0x5C30A0`), render `[0x839C3C]` (`0x5C2FF0`), occlusion `[0x839C58]` (`0x5C3170`).
  * cheats: `0x459B00(id, key)` toggles a flag in the persistent-data table `[0x82A6D0]+0x148` (getter: thiscall
    `0x4033EB(key)`); keys `godMode bigHead bigComb bigFeet sunGlasses underwear paperPants featherCloud cannonBalls`.
  * player: `0x460D50(id, 0)`: -4 add egg, -3 remove egg, -2 add coin, -1/0/1 difficulty, 2 add 20 card sets.
* The menu calls command callbacks as `cb(id, ctx)` (cdecl).
* Dead "Show Surface" code `0x462C50`: ray from the camera (`[0x857740]`) through the collision world (`[0x83F528]`,
  raycast `0x418130`) printing `ColXYZ`, `Actor:` / `Static collision data`, `Material:`.

## Script VM

* Native handler signature: `handler(ScriptCtx* ctx, int idx)` (cdecl). Argument stack `S = [ctx + idx*4 + 0xF0]`:
  `S+8` int8 top index, `S+0x30` dword values, `S+0x34` byte types (1 int, 2 float, 4 bool, others pointers).
  Pop = `0x5DA530` / `0x5DA580` (float), push float = `0x5DA480`. Arguments are popped last-first.
* CLHook fabricates a context and runs batches of handlers on the game thread (`bridge.script_batch`), e.g.
  `FindGroundXYZ` (`0x61C690`: x, y, z -> ground height below or -FLT_MAX) used by the collision scanner.

## Camera / rendering

* The game sets `D3DTS_VIEW` / `D3DTS_PROJECTION` through `IDirect3DDevice8::SetTransform`; projection is right-handed
  (`_34 = -1`). CLHook keeps the last non-identity view and perspective projection to draw world-space lines/labels.
* Units are roughly metres; Chicken Little is ~0.35 tall, the follow camera sits ~1.4 behind him.

## Cameras

* Camera manager `[0x82A2D8]`; `FindSet("player1")` = thiscall `0x41B370`, `FindCam("follow")` = thiscall `0x41A980`
  (strings `0x7947FC`, `0x79B460`). Follow camera: `+0x64..+0x6C` requested position, `+0x70` current position.
* Snap the follow camera onto its target (used after teleports): thiscall `0x421550(cam, float* out, 0, 1)`
  (what `Camera__SetFollowCamPos` does).
* Free camera (CLHook): the 3D `D3DTS_VIEW` set by the game is replaced with a right-handed look-at matrix;
  culling still uses the game camera.

## Zipline glitch

See `docs/ZIPLINE_GLITCH.md` (vtable `0x7BD778`, rope at `+0x3DC`, unstable integrator `0x54D770`, NaN player position
fires the SchoolYard `Level_EXIT` level switch).

## Videos

* `binkw32 _BinkOpen@8 / _BinkClose@4` are hooked. Startup: `fmv/b/bvg.bik`, `fmv/a/avlogo.bik`; level intros such as
  `fmv/I/Intro.bik`; title attract demo `fmv/3/30sec_chick_demo.bik`, `fmv/1/1min_chick_demo.bik`
  (blocked by `SkipAttractDemo=1`, the title then just idles).

## File formats

* **HOG** archive: `u16 ver=2, u16 1, u32 count, u32 names_size, u32 table_off(0x10)`, entries `u32 name_off, u32 data_off, u32 size`.
  Tool: `py -3 -m cltools.hog list|extract|pack`.
* **DB container** (`.DBL .env .adb .sdb .mdb .dbu`): 0x20-byte header (`"DB"`/`"DX"` at +8, chunk count at +0x18),
  then chunks with a 0x40-byte header (`u16 type, u16 flags, u32 size, u16 version, "1000"`).
  World `.DBL` chunks: `0x82` textures, `0x22` models, `0x60` placed instances (0xB0-byte records with matrix,
  position, bounding sphere, world-space AABB), `0x600` sound emitters, `0x283` world bounds. Tool: `cltools/dbl.py`.
* **.OA** (`data_dx/worlds/<w>/<w>.OA`): text export of every object instance with `#Pos` and editor attributes.
  The game loads the compiled `.env` (same attributes, binary; supports `x/y/z_pos_override`).
* **.VAR**: text `context <name> … end` scripts. Loose `data/worlds/<w>/player.var` (start points) **is read by the game
  on every level load / restart** (verified by changing `startPos0` and finding the new value in memory).
  Most other `.VAR` files live in `data_dx/vars.hog`.
