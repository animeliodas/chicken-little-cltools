# The high-FPS zipline glitch — why it ends levels

**English** · [Русский](ru/ZIPLINE_GLITCH.md)

Everything below was verified in game (Steam build, `Chick.exe` PE timestamp 1130358323) with CLTools: reproduced,
measured, and the key step tested in isolation.

## Summary

1. A zipline is a physical rope whose bounce is integrated by a **numerically unstable scheme**. At 60 FPS it damps
   the bounce; at high FPS (from ~150–200 FPS here, >300 for most runners) it **amplifies it exponentially**.
2. If you jump off before the end, the rope stays "active" without a rider and keeps being simulated. Its vertical
   displacement `y` grows roughly ×10 per second (at ~1000 FPS): 2 → 25 → 8·10³ → 10⁸ (10 s) → 10¹⁴ (16 s)
   → **6·10¹⁹ (22 s)** → 10²⁵ (28 s) → 2·10²⁷ (30 s) → … → float overflow (~40 s).
3. The rope's touch box (OBB) is `max(zipline_obb_width, |y|)`, so the rope turns into a **giant box** you can touch
   from almost anywhere nearby.
4. Touching it attaches the player and places him on the rope at a coordinate of the order of `y`. Once
   `|y| > √FLT_MAX ≈ 1.8·10¹⁹`, squared distances overflow to `inf`, and `inf − inf` gives a **NaN player position**.
5. **A NaN position ends the level.** Tested directly: writing NaN into the player position at the spawn point, with
   no rope at all, instantly finishes SchoolYard (Save Game prompt, then `school.bik` and dodgeball). The game compares
   with `fcomp` + `test ah,1`, so with NaN every "less than" is *true*; the trigger test passes and `Level_EXIT`
   (a *Level Switch* to `dodgeball`) fires. In townsquare the level switch goes to the `theatre` sub-level instead.

That also explains the **23–30 s window**:
* **too early** — `y` is still finite and "normal": the player is just flung far away, the camera flies into the sky;
* **inside the window** — touching produces NaN → the level ends;
* **much later** — the rope's own fields overflow (velocity, then `y`) → the rope becomes inf/NaN → crash or random
  behaviour.

## Details (for reverse engineers)

| What | Address |
|---|---|
| zipline class vtable | `0x7BD778` (object ~0x23E0 bytes, rope sub-object at `+0x3DC`) |
| init from attributes (`zipline_tautness`, `_damping`, `nextZiplineName`, …) | `0x54F860` |
| rope physics step (runs while `zip+0x498` = active) | `0x54D770` via `0x54E040` |
| rope shape over 22 nodes (displacement `y` × profile `1 − 4(t − 0.5)²`) | `0x54E590` |
| touch OBB = `max(obb_width, |r|)`, `r = √(x² + y²)` | `0x54EEC0` |
| avatar touch test → attach (`0x4DACE0`) | `0x54DDC0` |
| rider advance along the rope (the 0..1 clamp lets NaN through) | `0x550380` |
| rope fields: `+0x60` rider position 0..1, `+0x64` rider weight (0 = nobody), `+0x68/+0x6C` displacement x/y, `+0x70/+0x74` velocities, `+0xAC` length | |

In `0x54D770` the spring has a negative damping term (`−0.2·k`, `k = 2π·4`). At a large dt it is outweighed by the
numerical damping of the implicit scheme, at a small dt it is not. The game's dt is **integer milliseconds**
(`GetTimeMs` @ `0x65FC10`), so with a fluctuating frame rate dt jumps between 0, 1 and 2 ms and the growth rate
changes from attempt to attempt.

## Why some spots only work 1 time in 100

* **Unstable frame rate.** The growth of `y` depends on dt, so the moment the NaN window opens moves by seconds.
  At ~1000 FPS the 10²⁰ threshold is reached at ~22–23 s, at 250 FPS at ~40 s, at 120 FPS there is no growth at all.
  A 23–30 s timer only works at the frame rate it was found with.
* **Any short FPS drop** (loading, Alt+Tab, lag) lets the rope settle and **deactivate** (`active = 0`) — the glitch
  silently disappears.
* **Not every rope allows jumping off:** `zipwire7/10/11/12/13` have `ziplineAllowSlideJump = False`. In SchoolYard
  `zipwire4` worked (jump at ~85–88 % of the length).
* Touching where the shape has almost no displacement (right at the ends, where `1 − 4(t − 0.5)²` ≈ 0) may not
  overflow.

## How to make it reliable

1. **Keep the frame rate constant and high** from the jump to the touch: an external limiter (e.g. RTSS) at a fixed
   value, ideally one where 1000/FPS is an integer (1000, 500, 250, 200) — then dt is identical every frame and the
   time to the window is reproducible.
2. Measure the window for your frame rate once in CLTools → Inspector → **Zipline** (or the in-game overlay): time
   since the glitch, `log10|y|` and a status: *growing* (touch = fly into the sky) → **NaN WINDOW**
   (touch = level ends) → *near overflow*. The window starts at about `|y| ≈ 10²⁰`.
3. Then, at that frame rate, wait that long and touch the rope away from its very ends.

Practice: **Calm all ropes** resets ropes, F5/F6 pause and frame-step, the **Levels** tab gets you back quickly.

## cornmaze: where the crashes come from (confirmed)

* There is one rope, `zipwire11` (13.9, 0.5, −11.0). The level switch is `Phase_Trigger5` (Level Switch → `cannon`).
* Every crash (in the runner's recordings and in my tests) is the same instruction `0x5D5066`: a read of
  `NULL+0xBC` in the light sorter `0x5D4DE0`. The object being lit is the player; its centre is NaN.
* Why NaN crashes it: `dist < d` is compiled as `fcomp` + `test ah,1`. With NaN, x87 sets C0 and the comparison counts
  as true, so the insertion loop walks into the empty slot of the **dynamic** light list (a NULL pointer).
* cornmaze's dynamic lights are the 38 lamps of **19 "trash-can" ground drones** (`TrashCan*`, type
  *Platforming Drone - Ground*, code `0x583F30–0x5874A0`: `grnd_spinup`, `grnd_Weapon_charge`, `grnd_shoot_loop`
  switch the lamps on). While no lamp is lit the sorter skips them. Switching any light on also resets the lighting
  timer (`[0x83A46C]`), so the player's lighting is recomputed immediately.
* Verified:
  * in the 5 recorded crashes the game died 1–3 frames after the touch → a lamp was already lit;
  * in my test with all lamps off it crashed after ~1 s: the NaN player "wakes" the drones (their distance checks pass
    with NaN as well);
  * with all drones killed (`Enemy__KillAllGroundDrones`) there is no crash and the level ends (Save Game prompt).
* `LevelSwitch.adb`: when the trigger fires, the save prompt appears immediately (the game pauses), then a 0.75 s fade
  and the level change. Success = the trigger fires before any lamp lights up.

**What this means for a run**
1. Touch the rope only while **no trash-can lamp is lit**. The Zipline tab and the overlay show "Dynamic lights ON":
   green 0 = fine, red = guaranteed crash. Don't wake the drones on the way, or wait until they calm down.
   Inspector → World 3D → "Highlight drones" shows all 19 trash cans in game (through the corn) with their state and
   distance — handy for killing them on the way.
   **Reliable (verified): 0 drones alive = no crash.** A NaN player wakes **every** drone of the level regardless of
   distance, so while any drone is alive there is a chance it lights its lamp before the switch fires.
2. Even with the lamps off there is a race "trigger vs. drones waking up" (~1 s). What makes the trigger fire faster is
   still open — recordings that include the lamp state will tell.

## Recording attempts (black box)

1. You need the `d3d8.dll` from this release (CLHook v4).
2. Run `CLTools/Record.bat`: it waits for the game and writes every frame to
   `CLTools/recordings/<world>_<time>.csv.gz` (+ a `.json` with events). Recorded: position / velocity, which rope the
   player hangs on, the state of every rope (`active`, weight, rider position, `y`, `vy`), dynamic lights, pressed keys,
   real frame time, the game's dt, FPS. If the game crashes, the recording is kept up to the last frame and the `.json`
   gets the crashing instruction, registers and stack.
3. Make attempts as usual, as many as you like. `Ctrl+C` stops the recorder.
4. Analysis: `py -3 CLTools/scripts/analyze_zip.py` → attempt table and `recordings/analysis.txt`.

## Where else NaN works (code and level survey)

**Source of NaN.** The negatively damped spring (`−0.2·k`) only exists in live code for ziplines (`0x54D770`). Its copy
(`0x54AFB0`, class `0x7BD510`) is never instantiated in the retail game. Wires (wire walk, class `0x7BD300`) use
different code. Divisions by dt in the movement code are guarded (`|dt| < 1e-7`), so the zipline glitch is the only
NaN source found so far.

**What NaN does.** Comparisons are `fcomp` + `test ah,1`, so with NaN every "less than" is true. Therefore:
1. level switch / warp triggers fire;
2. drones and other "player within distance" checks think the player is next to them;
3. the light sorter crashes if any **dynamic light** in the level is lit (crash at `0x5D5066`).

| Level | Ziplines | What NaN fires | Dynamic lights |
|---|---|---|---|
| SchoolYard | 14 | `Level_EXIT` → dodgeball (verified: success) | none → no crash |
| cornmaze | 1 (`zipwire11`) | `Phase_Trigger5` → cannon (verified) | 19 trash-can drones → crash if a lamp is lit |
| townsquare | 10 | `LevelSwitch` → **theatre** (the "glitch loads theatre" case) | not tested |
| theatre | 1 | `exit_trigger` / `trigger_level_end` → townSquare | not tested |
| Final_Boss | 1 | warp `rocketwarp` → `rocketwarp_target` | **3 of 4 lit → verified: crash** |
| beamChase | 5 | no switch or warp triggers — probably the "no proven effect" spot | not tested |

**Tools (Inspector → Zipline):**
* "Dynamic lights ON" — whether any dynamic light is lit right now (red = NaN will crash the game);
* **"Simulate: player position = NaN"** — does what the glitch does, instantly; a quick way to see what NaN does at any
  spot without growing a rope;
* **anomaly detector** — every actor whose position became NaN / inf / > 10⁵ (class, address, time).
