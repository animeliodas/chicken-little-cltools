"""Game-specific knowledge: addresses and structures of Chick.exe (Steam build, PE timestamp 1130358323).

All addresses are absolute (image base 0x400000, no ASLR). See docs/RE_NOTES.md for how they were found.
"""
import math
import struct

EXE_TIMESTAMP = 1130358323

# --- globals -------------------------------------------------------------------
GAME_PTR = 0x831A38            # CGame* singleton
GAME_AVATARS = 0x658           # CAvatar* players[8]
GAME_AVATAR_COUNT = 0x678
GAME_LEVEL_STATE = 0x60C       # -> struct, +4 = level progression id
WORLD_PATH_BUF = 0x85783C      # "worlds\<World>\<World>" of the loaded world
LEVEL_TABLE = 0x7F6EDC         # 33 entries * 0x2C: +0 ?, +4 dir, +8 name key, +0xC music, +0x10 flags (bit0 = listed)
LEVEL_TABLE_STRIDE = 0x2C
LEVEL_COUNT = 33

GAME_LIMITER_ON = 0x83ED86     # byte: engine frame limiter (Sleep based) on/off
GAME_FRAME_INTERVAL = 0x83ED90 # byte: frame interval in 1/60 s units (2 = 30 fps)
TIME_FREEZE_FLAG = 0x856C1C    # byte: GetTimeMs() returns TIME_FREEZE_VALUE when set
TIME_FREEZE_VALUE = 0x856C20
DEBUG_MENU_PTR = 0x857DC4      # DebugMenu* singleton (menu items are never added in retail)

# --- CAvatar ---------------------------------------------------------------------
AV_POS = 0x44                  # vec3 render/actor position
AV_ROT = 0x50                  # 3x3 rotation matrix (rows, 12-byte stride)
AV_VEL = 0x74                  # vec3 velocity (units/s), used by Avatar__GetSpeed
AV_PHYS_POS = 0x12AC           # vec3 authoritative mover position (write this to teleport)
AV_PHYS_POS_PREV = 0x12C8      # vec3 mover position copy (previous/centre)
AV_POS_COPIES = (-0x1A0, 0x44, 0x378, 0x11FC, AV_PHYS_POS, AV_PHYS_POS_PREV)

# --- cameras -----------------------------------------------------------------------
CAM_MANAGER_PTR = 0x82A2D8     # camera manager; FindSet("player1") 0x41B370, FindCam("follow") 0x41A980 (thiscall)
CAM_FIND_SET, CAM_FIND = 0x41B370, 0x41A980
CAM_FOLLOW_SNAP = 0x421550     # thiscall(cam, float* out, 0, 1): snap the follow camera onto its target
STR_PLAYER1, STR_FOLLOW = 0x7947FC, 0x79B460

# --- script API (native handlers, see docs/script_functions.txt) ----------------------
SCRIPT_REGISTER = 0x5DAAA0     # RegisterScriptFunc(handler, name, flags)


class Game:
    def __init__(self, proc):
        self.p = proc

    # ---- objects --------------------------------------------------------------
    def game(self):
        return self.p.u32(GAME_PTR)

    def avatar(self, index=0):
        g = self.game()
        if not g:
            return 0
        n = self.p.u32(g + GAME_AVATAR_COUNT)
        if index >= n or n > 8:
            return 0
        return self.p.u32(g + GAME_AVATARS + 4 * index)

    # ---- player ---------------------------------------------------------------
    def player_pos(self):
        a = self.avatar()
        return self.p.vec3(a + AV_PHYS_POS) if a else None

    def player_vel(self):
        a = self.avatar()
        return self.p.vec3(a + AV_VEL) if a else None

    def player_rot(self):
        a = self.avatar()
        if not a:
            return None
        m = struct.unpack("<9f", self.p.read(a + AV_ROT, 36))
        return [m[0:3], m[3:6], m[6:9]]

    def player_yaw_deg(self):
        r = self.player_rot()
        if not r:
            return None
        return math.degrees(math.atan2(r[2][0], r[2][2]))

    def teleport(self, pos, zero_velocity=True):
        a = self.avatar()
        if not a:
            raise RuntimeError("no player avatar (not in a level?)")
        for off in AV_POS_COPIES:
            self.p.w_vec3(a + off, pos)
        if zero_velocity:
            self.p.w_vec3(a + AV_VEL, (0.0, 0.0, 0.0))

    def snap_camera(self, br):
        """Make the follow camera jump to the player immediately (after a teleport). Needs CLHook v3."""
        mgr = self.p.u32(CAM_MANAGER_PTR)
        if not mgr:
            return False
        cset = br.call(CAM_FIND_SET, STR_PLAYER1, this=mgr)
        cam = br.call(CAM_FIND, STR_FOLLOW, this=cset) if cset else 0
        if not cam:
            return False
        buf = br.buf_write(bytes(16), 0x700)
        br.call(CAM_FOLLOW_SNAP, buf, 0, 1, this=cam)
        return True

    def teleport_snap(self, pos, br=None):
        self.teleport(pos)
        if br is not None and br.b.version >= 3:
            import time
            time.sleep(0.05)
            try:
                self.snap_camera(br)
            except Exception:
                pass

    # ---- world ----------------------------------------------------------------
    def world_name(self):
        try:
            s = self.p.read(WORLD_PATH_BUF, 0x40).split(b"\0", 1)[0].decode("latin-1")
        except OSError:
            return None
        parts = s.replace("/", "\\").split("\\")
        if len(parts) >= 2 and parts[0].lower() == "worlds":
            return parts[1]
        return None

    def level_table(self):
        out = []
        for i in range(LEVEL_COUNT):
            a = LEVEL_TABLE + i * LEVEL_TABLE_STRIDE
            try:
                out.append((i, self.p.cstr(self.p.u32(a + 4), 40), self.p.cstr(self.p.u32(a + 8), 40)))
            except OSError:
                pass
        return out

    # ---- engine timing ----------------------------------------------------------
    def engine_limiter(self):
        return self.p.u8(GAME_LIMITER_ON), self.p.u8(GAME_FRAME_INTERVAL)

    def set_engine_limiter(self, on=None, interval=None):
        if on is not None:
            self.p.write(GAME_LIMITER_ON, bytes([1 if on else 0]))
        if interval is not None:
            self.p.write(GAME_FRAME_INTERVAL, bytes([int(interval)]))

    # ---- summary ----------------------------------------------------------------
    def snapshot(self):
        a = self.avatar()
        info = {"world": self.world_name()}
        if a:
            info["pos"] = self.p.vec3(a + AV_PHYS_POS)
            info["vel"] = self.p.vec3(a + AV_VEL)
            yaw = self.player_yaw_deg()
            lim, iv = self.engine_limiter()
            info["extra"] = f"yaw {yaw:7.2f} deg   avatar 0x{a:08x}   engine limiter {'on' if lim else 'off'} (interval {iv})"
        return info
