# CLTools — research & speedrun toolkit for Disney's Chicken Little (PC, 2005)

**English** · [Русский](README.ru.md)

A toolkit for speedrunners and researchers of the PC (Steam) version of *Disney's Chicken Little*:
FPS lock, slow motion / pause / frame advance, player coordinates and teleport, **hidden triggers and real collision
drawn inside the game**, the surviving parts of the **developers' debug menu**, a free camera, a map viewer,
a per-frame "black box" recorder, archive tools and reverse-engineering notes — including a full explanation of the
high-FPS **zipline glitch** ([docs/ZIPLINE_GLITCH.md](docs/ZIPLINE_GLITCH.md)).

> Not affiliated with Disney or Avalanche Software. You need your own copy of the game. This repository contains no
> game files, no decompiled game code and no game data.

## Install (2 minutes)

1. Download **`CLTools-vX.Y.zip`** from [Releases](../../releases).
2. Extract it **into the game folder** (Steam → Chicken Little → Manage → Browse local files), so that `d3d8.dll`
   ends up next to `Chick.exe` and the `CLTools` folder is created.
3. Run **`CLTools\Setup.bat`** once. It installs the Python packages the tools need (and offers to install Python
   through `winget` if you don't have it).
4. Start the game from Steam as usual.

That's it. The FPS lock, hotkeys, overlay and free camera work as soon as `d3d8.dll` is in place, even without Python.
To uninstall, delete `d3d8.dll` and the `CLTools` folder.

## In-game hotkeys

| Key | Action |
|---|---|
| F5 | pause / resume |
| F6 | advance one frame (pauses if running) |
| F7 | game speed 100 % → 50 % → 25 % → 10 % |
| F8 | overlay on/off |
| F9 | screenshot → `CLTools/screens/` |
| F11 | **free camera**: I/J/K/L move, U/O down/up, arrow keys look, Ctrl = fast |

Settings live in `CLTools/clhook.ini` (created on first start): `FpsTarget=60`, `Windowed=1`, `FixedStep`,
`SkipAttractDemo=1` (no demo video on the title screen), hotkeys, …

## Tools

| Tool | Start | What it does |
|---|---|---|
| **Inspector** | `Inspector.bat` | the main panel (tabs below) |
| **Map Viewer** | `MapView.bat` | top-down level map: geometry boxes, every object, editable player starts, live player + trail, live enemy drones |
| **Recorder** | `Record.bat` | per-frame black box (state, keys, ropes, lights, crash address) → `CLTools/recordings/` |
| HOG archives | `py -3 -m cltools.hog list/extract/pack` | the game's `.hog` archives |
| DB containers | `py -3 -m cltools.dbl file.DBL` | chunk listing of `.DBL/.env/.adb/...` |

### Inspector tabs

* **Main** — FPS target, game speed, pause / frame step, fixed time step; player position / velocity / yaw,
  teleport (the camera jumps along), position slots; memory watch list (addresses and pointer chains) shown in the
  in-game overlay.
* **Debug menu** — what survived of the developers' debug menu: wire-frame (see through walls), lighting, fog, vertex
  colours, textures, bones, distortion, visibility/render/occlusion modes, the engine's own frame limiter; the game's
  cheats (God mode, Big head, …); player actions (eggs, coins, difficulty, cards); free camera controls.
* **World 3D** — drawn inside the game with the game's camera:
  * level object volumes: death boxes, checkpoints, level / volume triggers, cameras, sound/particle triggers,
    pickups — with names;
  * **live enemy drones** through walls (green asleep, yellow awake, red lamp on, grey killed);
  * **collision scan**: thousands of the engine's own ground rays around the player → the real walkable surface
    (invisible floors and ledges included).
* **Zipline** — monitor for the high-FPS zipline glitch (rope state, NaN window), dynamic-light warning, anomaly
  detector (actors with NaN / inf / huge coordinates), "simulate NaN position".
* **Levels** — the game's level table; load any world (e.g. sub-levels such as `theatre` that *Select Level* doesn't
  list).
* **Script** — call any of the engine's 1222 native script functions.

## How the timing works

The game simulates with the real frame time in **integer milliseconds** (`GetTimeMs` @ `0x65FC10`), so everything
depends on the frame rate (at 60 FPS dt alternates 16/17 ms). The engine's own 30 FPS limiter is disabled in the retail
build. CLTools locks the game to exactly `FpsTarget`; slow motion scales frame rate and game time together; pause and
frame advance give exactly 1/60 s per frame, and input keeps working while paused.

## Documentation

* [docs/ZIPLINE_GLITCH.md](docs/ZIPLINE_GLITCH.md) — why the high-FPS zipline glitch ends levels, why it crashes in
  cornmaze, how to make it reliable, where else NaN works.
* [docs/RE_NOTES.md](docs/RE_NOTES.md) — addresses, structures, file formats, timing, debug menu, script VM, cameras.
* [docs/script_functions.txt](docs/script_functions.txt) — all 1222 script functions with their native addresses.
* Russian versions: [README.ru.md](README.ru.md), [docs/ru/](docs/ru/).

## For developers

* Build the proxy DLL: `build.bat` (Visual Studio Build Tools, x86). Output: `build/d3d8.dll`.
* Unpacked executable for static analysis: set `DumpImage=1` in `clhook.ini`, start the game once, then
  `py -3 scripts/rebuild_dump.py` → `dump/Chick_unpacked.exe` (load at 0x400000 in Ghidra/IDA/REA).
  `scripts/re_helper.py` offers quick capstone-based xrefs/disassembly.
* Research scripts used for the zipline analysis live in `scripts/` (`zip_*.py`, `analyze_zip.py`, `crash_report.py`).

## Known limitations

* Fullscreen mode with the proxy has not been tested (the default is windowed).
* The collision scan shows floors (downward rays); walls appear as height steps, ceilings are not shown.
* Object volumes are axis-aligned boxes.
* The map viewer draws boxes, not meshes (the model / texture formats are not decoded yet).
* The free camera only replaces the view; the game still culls objects using its own camera near the player.
* Addresses are for the current Steam build of `Chick.exe` (PE timestamp 1130358323).
* The `.hog` archives are locked while the game runs.

## License

MIT — see [LICENSE](LICENSE).
