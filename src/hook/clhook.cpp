// CLHook - d3d8.dll proxy for Disney's Chicken Little (PC, 2005)
//
//  * frame limiter (default 60 FPS) - the game logic is tied to frame rate
//  * optional windowed mode, forced 60 Hz in fullscreen
//  * game-speed control (slow motion), pause and frame advance
//  * time virtualization (QueryPerformanceCounter/timeGetTime/GetTickCount)
//  * in-game text overlay (status + text pushed by external tools)
//  * screenshots of the back buffer (BMP)
//  * shared-memory bridge "Local\CLToolsBridge" for external tools
//  * one-shot dump of the decrypted executable image for static analysis
//
// Build: CLTools\build.bat (MSVC, x86).

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <ctype.h>
#include <math.h>
#include "d3d8min.h"

#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")

// ---------------------------------------------------------------------------
// Shared bridge (must match cltools/bridge.py)
// ---------------------------------------------------------------------------
#pragma pack(push, 4)
struct CLBridge {
    uint32_t magic;            // 0   'CLTB'
    uint32_t version;          // 4
    uint32_t pid;              // 8
    uint32_t hwnd;             // 12
    uint32_t device;           // 16
    uint32_t frame;            // 20  presents since start
    float fps;                 // 24  measured fps
    float frameMs;             // 28  last frame time (ms, real)
    int32_t fpsTarget;         // 32  RW limiter target (0 = off)
    int32_t speedPct;          // 36  RW game speed in percent
    int32_t paused;            // 40  RW
    int32_t stepFrames;        // 44  RW frames to advance while paused
    int32_t overlayOn;         // 48  RW
    int32_t screenshotReq;     // 52  RW 1 = take screenshot on next present
    uint32_t screenshotCount;  // 56
    int32_t fixedStep;         // 60  RW 1 = virtual time advances exactly 1/fpsTarget per frame
    uint32_t overlaySeq;       // 64  RW bumped by tools when overlayText changes
    uint32_t bbWidth;          // 68
    uint32_t bbHeight;         // 72
    uint32_t windowed;         // 76
    uint32_t presentInterval;  // 80  interval actually used
    uint32_t origInterval;     // 84  interval requested by the game
    uint32_t origRefresh;      // 88  refresh requested by the game
    uint32_t vtime_lo;         // 92  virtual time (ms)
    uint32_t videoPlaying;     // 96  number of open Bink videos (FMV / attract demo)
    uint32_t videoCount;       // 100 videos opened since start
    int32_t freecamOn;         // 104 RW free camera active
    float freecam[5];          // 108 RW x, y, z, yaw, pitch (radians)
    char screenshotPath[260];  // 128
    char overlayText[4096];    // 388

    // ---- v2: remote call executed on the game thread (inside Present, between frames) ----
    uint32_t callSeq;          // 4484 RW tool increments to request a call
    uint32_t callDone;         // 4488    set to callSeq when finished
    uint32_t callFn;           // 4492 RW function address
    uint32_t callConv;         // 4496 RW 0 = cdecl/stdcall (this ignored), 1 = thiscall (ecx = callThis)
    uint32_t callThis;         // 4500 RW
    uint32_t callNArgs;        // 4504 RW 0..8
    uint32_t callArgs[8];      // 4508 RW
    uint32_t callResult;       // 4540    eax
    int32_t callStatus;        // 4544    0 ok, 1 exception, 2 bad request
    uint32_t callBufAddr;      // 4548    in-game address of callBuf (for pointer arguments)
    uint8_t callBuf[2048];     // 4552 RW scratch memory visible to the game

    // ---- v2: world-space debug drawing ----
    int32_t worldOn;           // 6600 RW draw lines/labels
    int32_t worldDepth;        // 6604 RW 1 = depth-tested, 0 = always on top
    uint32_t lineCount;        // 6608 RW number of line vertices (pairs)
    uint32_t labelCount;       // 6612 RW
    int32_t viewValid;         // 6616    matrices captured this session
    float view[16];            // 6620    last 3D view matrix set by the game
    float proj[16];            // 6684    last perspective projection set by the game
    char videoName[32];        // 6748 last opened Bink video (file name)
    struct Label {             // 6780
        float x, y, z;
        uint32_t color;
        char text[48];
    } labels[256];             // 64 bytes each -> 16384
    struct LineVert {          // 23164
        float x, y, z;
        uint32_t color;
    } lines[65536];

    // ---- v3: batched script-function calls (handler(ctx, 0) with a fabricated VM stack) ----
    uint32_t scSeq;            // 1071740 RW tool increments to request the batch
    uint32_t scDone;           // 1071744
    uint32_t scCount;          // 1071748 RW entries to execute
    uint32_t scErrors;         // 1071752    entries that raised an exception
    struct ScriptCall {        // 1071756, 36 bytes each
        uint32_t fn;           // native handler address
        uint32_t nargs;        // 0..4, pushed in order (handler pops the last one first)
        uint8_t types[4];      // 1 = int, 2 = float, 4 = bool, other = raw pointer
        uint32_t args[4];
        uint32_t rtype;        // out: type of stack top after the call (0 = nothing, 0xFF = exception)
        uint32_t result;       // out: value of stack top
    } sc[8192];

    // ---- v4: per-frame recorder + exception catcher ----
    int32_t recOn;             // RW sample every presented frame
    uint32_t recHead;          //    records written so far (monotonic, ring index = head % recRing)
    uint32_t recNumAddr;       // RW number of sampled dwords (<= 96)
    uint32_t recRing;          //    ring size in records
    uint32_t recAddr[96];      // RW absolute addresses of the dwords to sample (0 = skip)
    uint32_t crashSeq;         //    unhandled exceptions seen
    uint32_t crashCode, crashEip, crashAccess, crashAccessType, crashFrame;
    uint32_t crashRegs[8];     //    eax ebx ecx edx esi edi ebp esp
    uint32_t crashStack[32];
    uint32_t excHead;          //    first-chance exceptions in game code (ring of 16)
    struct Exc {
        uint32_t frame, code, eip, access, esp, inCall;
    } exc[16];
    struct Rec {
        uint32_t frame;
        uint32_t vtimeMs;
        double realMs;
        uint32_t keys;         // bit mask, see kRecKeys
        uint32_t flags;        // bit0 video playing, bit1 paused, bit2 sample fault, bit3 freecam
        float fps;
        uint32_t gameMs;       // [0x856C24] last value of the game's GetTimeMs()
        uint32_t vals[96];
    } rec[8192];
};
#pragma pack(pop)

static const uint32_t BRIDGE_MAGIC = 0x42544C43;  // "CLTB"
static const uint32_t BRIDGE_VERSION = 4;
static const uint32_t MAX_SCRIPT_CALLS = 8192;
static const uint32_t MAX_LINE_VERTS = 65536;
static const uint32_t MAX_LABELS = 256;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
struct Config {
    int fpsTarget = 60;
    int windowed = 1;
    int windowBorder = 1;
    int forceRefresh = 60;
    int vsync = 0;
    int timeHook = 1;
    int fixedStep = 0;
    int overlay = 1;
    int overlayScale = 1;
    int dumpImage = 0;
    int screenshots = 1;
    int skipDemo = 1;
    int hotkeys = 1;
    int keyPause = VK_F5;
    int keyStep = VK_F6;
    int keySpeed = VK_F7;
    int keyOverlay = VK_F8;
    int keyShot = VK_F9;
    int keyFreecam = VK_F11;
};

static Config g_cfg;
static char g_gameDir[MAX_PATH];
static char g_toolDir[MAX_PATH];
static CRITICAL_SECTION g_logCs;
static CLBridge* g_br;
static volatile LONG g_inRemoteCall;
static HANDLE g_brMap;

static void Log(const char* fmt, ...) {
    char path[MAX_PATH];
    _snprintf(path, sizeof(path), "%s\\clhook.log", g_toolDir);
    EnterCriticalSection(&g_logCs);
    FILE* f = fopen(path, "a");
    if (f) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fprintf(f, "[%02d:%02d:%02d.%03d] ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
        va_list ap;
        va_start(ap, fmt);
        vfprintf(f, fmt, ap);
        va_end(ap);
        fputc('\n', f);
        fclose(f);
    }
    LeaveCriticalSection(&g_logCs);
}

static const char* kDefaultIni =
    "; CLHook settings (d3d8.dll proxy). Changes apply on next game start.\r\n"
    "[Display]\r\n"
    "; 60 = lock the game to 60 FPS (game logic is frame-rate dependent). 0 = no limiter.\r\n"
    "FpsTarget=60\r\n"
    "; 1 = run in a window instead of fullscreen (fullscreen with the proxy is untested)\r\n"
    "Windowed=1\r\n"
    "; 1 = give the window a normal title bar (windowed mode only)\r\n"
    "WindowBorder=1\r\n"
    "; fullscreen refresh rate to request (0 = let the game decide)\r\n"
    "ForceRefresh=60\r\n"
    "; fullscreen only: 1 = vsync at ForceRefresh instead of the limiter\r\n"
    "VSync=0\r\n"
    "\r\n"
    "[Time]\r\n"
    "; hook QueryPerformanceCounter/timeGetTime/GetTickCount (needed for slow motion & pause)\r\n"
    "TimeHook=1\r\n"
    "; 1 = every frame advances game time by exactly 1/FpsTarget (deterministic dt)\r\n"
    "FixedStep=0\r\n"
    "\r\n"
    "[Overlay]\r\n"
    "Enabled=1\r\n"
    "Scale=1\r\n"
    "\r\n"
    "[Hotkeys]\r\n"
    "; virtual-key codes. F5=116 F6=117 F7=118 F8=119 F9=120\r\n"
    "Enabled=1\r\n"
    "Pause=116\r\n"
    "FrameStep=117\r\n"
    "Speed=118\r\n"
    "Overlay=119\r\n"
    "Screenshot=120\r\n"
    "\r\n"
    "[Debug]\r\n"
    "; 1 = write the decrypted game image to CLTools\\dump\\Chick_mem.bin on start\r\n"
    "DumpImage=0\r\n"
    "; 1 = make the back buffer lockable so screenshots work\r\n"
    "Screenshots=1\r\n";

static void LoadConfig() {
    char ini[MAX_PATH];
    _snprintf(ini, sizeof(ini), "%s\\clhook.ini", g_toolDir);
    if (GetFileAttributesA(ini) == INVALID_FILE_ATTRIBUTES) {
        FILE* f = fopen(ini, "wb");
        if (f) {
            fputs(kDefaultIni, f);
            fclose(f);
        }
    }
#define RD(sec, key, field) g_cfg.field = GetPrivateProfileIntA(sec, key, g_cfg.field, ini)
    RD("Display", "FpsTarget", fpsTarget);
    RD("Display", "Windowed", windowed);
    RD("Display", "WindowBorder", windowBorder);
    RD("Display", "ForceRefresh", forceRefresh);
    RD("Display", "VSync", vsync);
    RD("Time", "TimeHook", timeHook);
    RD("Time", "FixedStep", fixedStep);
    RD("Overlay", "Enabled", overlay);
    RD("Overlay", "Scale", overlayScale);
    RD("Hotkeys", "Enabled", hotkeys);
    RD("Hotkeys", "Pause", keyPause);
    RD("Hotkeys", "FrameStep", keyStep);
    RD("Hotkeys", "Speed", keySpeed);
    RD("Hotkeys", "Overlay", keyOverlay);
    RD("Hotkeys", "Screenshot", keyShot);
    RD("Hotkeys", "FreeCamera", keyFreecam);
    RD("Debug", "DumpImage", dumpImage);
    RD("Debug", "Screenshots", screenshots);
    RD("Debug", "SkipAttractDemo", skipDemo);
#undef RD
    if (g_cfg.overlayScale < 1) g_cfg.overlayScale = 1;
    if (g_cfg.overlayScale > 4) g_cfg.overlayScale = 4;
}

static void InitBridge() {
    g_brMap = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, sizeof(CLBridge),
                                 "Local\\CLToolsBridge");
    if (!g_brMap) return;
    g_br = (CLBridge*)MapViewOfFile(g_brMap, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(CLBridge));
    if (!g_br) return;
    memset(g_br, 0, sizeof(CLBridge));
    g_br->version = BRIDGE_VERSION;
    g_br->pid = GetCurrentProcessId();
    g_br->fpsTarget = g_cfg.fpsTarget;
    g_br->speedPct = 100;
    g_br->overlayOn = g_cfg.overlay;
    g_br->fixedStep = g_cfg.fixedStep;
    g_br->callBufAddr = (uint32_t)(uintptr_t)g_br->callBuf;
    g_br->worldOn = 1;
    g_br->worldDepth = 0;
    g_br->magic = BRIDGE_MAGIC;
}

// ---------------------------------------------------------------------------
// Real time + virtual time
// ---------------------------------------------------------------------------
typedef BOOL(WINAPI* QPC_t)(LARGE_INTEGER*);
typedef DWORD(WINAPI* DWFN_t)();
static QPC_t RealQPC;
static DWFN_t RealTimeGetTime, RealGetTickCount;
static int64_t g_qpf;

static inline int64_t RealNow() {
    LARGE_INTEGER li;
    RealQPC(&li);
    return li.QuadPart;
}

static CRITICAL_SECTION g_timeCs;
static int64_t g_vBase, g_rBase;   // scaled clock anchor
static double g_rate = 1.0;        // current rate (0 when paused)
static int g_fixedMode = 0;
static int64_t g_fixedV;           // fixed-step virtual time at last present
static int64_t g_lastPresentReal;
static int64_t g_lastReturned;
static int64_t g_vStart;           // virtual time at init
static DWORD g_msStart, g_tickStart;

static int64_t VirtualNowLocked(int64_t r) {
    int64_t v;
    if (g_fixedMode) {
        int64_t since = r - g_lastPresentReal;
        int64_t grace = g_qpf / 4;  // long frames (loading) let time flow again
        v = g_fixedV + (since > grace ? (int64_t)((since - grace) * g_rate) : 0);
    } else {
        v = g_vBase + (int64_t)((double)(r - g_rBase) * g_rate);
    }
    if (v < g_lastReturned) v = g_lastReturned;
    g_lastReturned = v;
    return v;
}

static int64_t VirtualNow() {
    int64_t r = RealNow();
    EnterCriticalSection(&g_timeCs);
    int64_t v = VirtualNowLocked(r);
    LeaveCriticalSection(&g_timeCs);
    return v;
}

// change rate / mode keeping virtual time continuous
static void SetClock(double rate, int fixedMode) {
    int64_t r = RealNow();
    EnterCriticalSection(&g_timeCs);
    int64_t v = VirtualNowLocked(r);
    g_rate = rate;
    g_fixedMode = fixedMode;
    g_vBase = v;
    g_rBase = r;
    g_fixedV = v;
    g_lastPresentReal = r;
    LeaveCriticalSection(&g_timeCs);
}

// called once per presented frame
static void ClockOnPresent(int fpsTarget) {
    int64_t r = RealNow();
    EnterCriticalSection(&g_timeCs);
    if (g_fixedMode) {
        int64_t step = g_qpf / (fpsTarget > 0 ? fpsTarget : 60);
        int64_t v = g_fixedV + (int64_t)(step * (g_rate > 0 ? 1.0 : 0.0));
        if (v < g_lastReturned) v = g_lastReturned;
        g_fixedV = v;
        g_lastPresentReal = r;
    }
    LeaveCriticalSection(&g_timeCs);
}

static BOOL WINAPI Hook_QPC(LARGE_INTEGER* p) {
    if (!p) return FALSE;
    p->QuadPart = VirtualNow();
    return TRUE;
}
static DWORD WINAPI Hook_timeGetTime() {
    return g_msStart + (DWORD)((VirtualNow() - g_vStart) * 1000 / g_qpf);
}
static DWORD WINAPI Hook_GetTickCount() {
    return g_tickStart + (DWORD)((VirtualNow() - g_vStart) * 1000 / g_qpf);
}

static void InitTime() {
    InitializeCriticalSection(&g_timeCs);
    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    RealQPC = (QPC_t)GetProcAddress(k32, "QueryPerformanceCounter");
    RealGetTickCount = (DWFN_t)GetProcAddress(k32, "GetTickCount");
    HMODULE wmm = LoadLibraryA("winmm.dll");
    RealTimeGetTime = (DWFN_t)GetProcAddress(wmm, "timeGetTime");
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    g_qpf = f.QuadPart;
    int64_t r = RealNow();
    g_vBase = g_rBase = g_vStart = g_lastReturned = g_fixedV = g_lastPresentReal = r;
    g_msStart = RealTimeGetTime();
    g_tickStart = RealGetTickCount();
}

// Patch an import of the main executable. Returns the previous pointer.
static void* PatchIAT(const char* dll, const char* func, void* hook) {
    BYTE* base = (BYTE*)GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return NULL;
    IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress);
    for (; imp->Name; imp++) {
        if (_stricmp((char*)(base + imp->Name), dll) != 0) continue;
        if (!imp->OriginalFirstThunk) continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA* iat = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; names++, iat++) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            IMAGE_IMPORT_BY_NAME* ibn = (IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData);
            if (strcmp((char*)ibn->Name, func) != 0) continue;
            DWORD old;
            VirtualProtect(&iat->u1.Function, sizeof(void*), PAGE_READWRITE, &old);
            void* prev = (void*)iat->u1.Function;
            iat->u1.Function = (DWORD_PTR)hook;
            VirtualProtect(&iat->u1.Function, sizeof(void*), old, &old);
            return prev;
        }
    }
    return NULL;
}

// ----- Bink video tracking -------------------------------------------------------
typedef void*(WINAPI* BinkOpen_t)(const char*, uint32_t);
typedef void(WINAPI* BinkClose_t)(void*);
static BinkOpen_t RealBinkOpen;
static BinkClose_t RealBinkClose;
static volatile LONG g_videoOpen;

static bool ContainsNoCase(const char* s, const char* sub) {
    char a[MAX_PATH];
    size_t n = strlen(s);
    if (n >= sizeof(a)) n = sizeof(a) - 1;
    for (size_t i = 0; i < n; i++) a[i] = (char)tolower((unsigned char)s[i]);
    a[n] = 0;
    return strstr(a, sub) != NULL;
}

static void* WINAPI Hook_BinkOpen(const char* name, uint32_t flags) {
    if (name && g_cfg.skipDemo && ContainsNoCase(name, "chick_demo")) {
        Log("BinkOpen(%s) blocked (SkipAttractDemo=1)", name);
        return NULL;
    }
    void* h = RealBinkOpen(name, flags);
    Log("BinkOpen(%s) -> %p", name ? name : "(null)", h);
    if (h && g_br) {
        InterlockedIncrement(&g_videoOpen);
        g_br->videoPlaying = g_videoOpen;
        g_br->videoCount++;
        const char* base = name ? name : "";
        for (const char* p = base; *p; p++)
            if (*p == 0x5C || *p == '/') base = p + 1;
        strncpy(g_br->videoName, base, sizeof(g_br->videoName) - 1);
        g_br->videoName[sizeof(g_br->videoName) - 1] = 0;
    }
    return h;
}

static void WINAPI Hook_BinkClose(void* h) {
    RealBinkClose(h);
    if (h && g_br) {
        if (InterlockedDecrement(&g_videoOpen) < 0) g_videoOpen = 0;
        g_br->videoPlaying = g_videoOpen;
    }
}

static void InstallBinkHooks() {
    RealBinkOpen = (BinkOpen_t)PatchIAT("binkw32.dll", "_BinkOpen@8", (void*)Hook_BinkOpen);
    RealBinkClose = (BinkClose_t)PatchIAT("binkw32.dll", "_BinkClose@4", (void*)Hook_BinkClose);
    if (!RealBinkOpen || !RealBinkClose) {
        // undo partial patching to keep things consistent
        if (RealBinkOpen) PatchIAT("binkw32.dll", "_BinkOpen@8", (void*)RealBinkOpen);
        if (RealBinkClose) PatchIAT("binkw32.dll", "_BinkClose@4", (void*)RealBinkClose);
        RealBinkOpen = NULL;
        RealBinkClose = NULL;
    }
    Log("bink hooks: open=%p close=%p", RealBinkOpen, RealBinkClose);
}

static void InstallTimeHooks() {
    void* a = PatchIAT("KERNEL32.dll", "QueryPerformanceCounter", (void*)Hook_QPC);
    void* b = PatchIAT("WINMM.dll", "timeGetTime", (void*)Hook_timeGetTime);
    void* c = PatchIAT("KERNEL32.dll", "GetTickCount", (void*)Hook_GetTickCount);
    Log("time hooks: QPC=%p timeGetTime=%p GetTickCount=%p", a, b, c);
}

// ---------------------------------------------------------------------------
// Image dump
// ---------------------------------------------------------------------------
static void DumpImage() {
    BYTE* base = (BYTE*)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    DWORD size = nt->OptionalHeader.SizeOfImage;
    char dir[MAX_PATH], path[MAX_PATH];
    _snprintf(dir, sizeof(dir), "%s\\dump", g_toolDir);
    CreateDirectoryA(dir, NULL);
    _snprintf(path, sizeof(path), "%s\\Chick_mem.bin", dir);
    BYTE* buf = (BYTE*)VirtualAlloc(NULL, size, MEM_COMMIT, PAGE_READWRITE);
    if (!buf) return;
    for (DWORD off = 0; off < size;) {
        MEMORY_BASIC_INFORMATION mbi;
        if (!VirtualQuery(base + off, &mbi, sizeof(mbi))) break;
        DWORD regionEnd = (DWORD)((BYTE*)mbi.BaseAddress + mbi.RegionSize - base);
        if (regionEnd > size) regionEnd = size;
        bool readable = mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
        if (readable) memcpy(buf + off, base + off, regionEnd - off);
        off = regionEnd;
    }
    FILE* f = fopen(path, "wb");
    if (f) {
        fwrite(buf, 1, size, f);
        fclose(f);
    }
    VirtualFree(buf, 0, MEM_RELEASE);
    Log("dumped image base=%p size=0x%X -> %s", base, size, path);
}

// ---------------------------------------------------------------------------
// D3D8 hooks
// ---------------------------------------------------------------------------
typedef void*(WINAPI* Direct3DCreate8_t)(UINT);
typedef HRESULT(WINAPI* CreateDevice_t)(void*, UINT, DWORD, HWND, DWORD, D3DPRESENT_PARAMETERS8*, void**);
typedef HRESULT(WINAPI* Reset_t)(void*, D3DPRESENT_PARAMETERS8*);
typedef HRESULT(WINAPI* Present_t)(void*, const RECT*, const RECT*, HWND, const void*);

static HMODULE g_realD3D8;
static Direct3DCreate8_t RealDirect3DCreate8;
static CreateDevice_t RealCreateDevice;
static Reset_t RealReset;
static Present_t RealPresent;
static void* g_d3d;
static void* g_dev;
static HWND g_hwnd;
static D3DPRESENT_PARAMETERS8 g_pp;

static void PatchVTable(void** vt, int idx, void* hook, void** orig) {
    if (vt[idx] == hook) return;
    DWORD old;
    VirtualProtect(&vt[idx], sizeof(void*), PAGE_EXECUTE_READWRITE, &old);
    *orig = vt[idx];
    vt[idx] = hook;
    VirtualProtect(&vt[idx], sizeof(void*), old, &old);
}

static void ApplyPresentOverrides(D3DPRESENT_PARAMETERS8* pp) {
    if (g_br) {
        g_br->origInterval = pp->FullScreen_PresentationInterval;
        g_br->origRefresh = pp->FullScreen_RefreshRateInHz;
    }
    if (g_cfg.windowed) {
        D3DDISPLAYMODE8 mode = {};
        typedef HRESULT(WINAPI * GADM_t)(void*, UINT, D3DDISPLAYMODE8*);
        if (g_d3d && SUCCEEDED(((GADM_t)VT(g_d3d)[IDX_D3D_GetAdapterDisplayMode])(g_d3d, 0, &mode)))
            pp->BackBufferFormat = mode.Format;
        pp->Windowed = TRUE;
        pp->FullScreen_RefreshRateInHz = 0;
        pp->FullScreen_PresentationInterval = D3DPRESENT_INTERVAL_DEFAULT;
        pp->SwapEffect = D3DSWAPEFFECT_DISCARD;
        pp->BackBufferCount = 1;
    } else if (!pp->Windowed) {
        if (g_cfg.forceRefresh > 0) pp->FullScreen_RefreshRateInHz = g_cfg.forceRefresh;
        pp->FullScreen_PresentationInterval =
            g_cfg.vsync ? D3DPRESENT_INTERVAL_ONE : D3DPRESENT_INTERVAL_IMMEDIATE;
    }
    if (g_cfg.screenshots && pp->MultiSampleType == 0) pp->Flags |= D3DPRESENTFLAG_LOCKABLE_BACKBUFFER;
}

static void StorePresentParams(const D3DPRESENT_PARAMETERS8* pp) {
    g_pp = *pp;
    if (g_br) {
        g_br->bbWidth = pp->BackBufferWidth;
        g_br->bbHeight = pp->BackBufferHeight;
        g_br->windowed = pp->Windowed;
        g_br->presentInterval = pp->FullScreen_PresentationInterval;
    }
}

static void FixWindow() {
    if (!g_cfg.windowed || !g_cfg.windowBorder || !g_hwnd) return;
    UINT w = g_pp.BackBufferWidth, h = g_pp.BackBufferHeight;
    if (!w || !h) return;
    LONG style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE;
    SetWindowLongA(g_hwnd, GWL_STYLE, style);
    SetWindowLongA(g_hwnd, GWL_EXSTYLE, GetWindowLongA(g_hwnd, GWL_EXSTYLE) & ~WS_EX_TOPMOST);
    RECT rc = {0, 0, (LONG)w, (LONG)h};
    AdjustWindowRect(&rc, style, FALSE);
    SetWindowPos(g_hwnd, HWND_NOTOPMOST, 40, 40, rc.right - rc.left, rc.bottom - rc.top,
                 SWP_FRAMECHANGED | SWP_SHOWWINDOW);
}

// ----- overlay --------------------------------------------------------------
static void* g_fontTex;
static int g_cellW = 8, g_cellH = 16;
static const int ATLAS_W = 256, ATLAS_H = 128;
static const float SOLID_U = 252.5f / ATLAS_W, SOLID_V = 124.5f / ATLAS_H;

struct OVert {
    float x, y, z, rhw;
    DWORD c;
    float u, v;
};
static OVert g_verts[6 * 1500];
static int g_nverts;

static void ReleaseFont() {
    if (g_fontTex) {
        typedef ULONG(WINAPI * Rel_t)(void*);
        ((Rel_t)VT(g_fontTex)[IDX_TEX_Release])(g_fontTex);
        g_fontTex = NULL;
    }
}

static bool CreateFontTexture(void* dev) {
    HDC dc = CreateCompatibleDC(NULL);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = ATLAS_W;
    bi.bmiHeader.biHeight = -ATLAS_H;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    void* bits = NULL;
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, NULL, 0);
    HGDIOBJ oldBmp = SelectObject(dc, bmp);
    HFONT font = CreateFontA(-14, 0, 0, 0, FW_BOLD, 0, 0, 0, ANSI_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                             ANTIALIASED_QUALITY, FIXED_PITCH | FF_MODERN, "Consolas");
    HGDIOBJ oldFont = SelectObject(dc, font);
    TEXTMETRICA tm;
    GetTextMetricsA(dc, &tm);
    g_cellW = tm.tmAveCharWidth;
    g_cellH = tm.tmHeight;
    if (g_cellW > 16) g_cellW = 16;
    if (g_cellH > 20) g_cellH = 20;
    memset(bits, 0, ATLAS_W * ATLAS_H * 4);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(255, 255, 255));
    for (int c = 32; c < 127; c++) {
        char ch = (char)c;
        int i = c - 32;
        TextOutA(dc, (i % 16) * g_cellW, (i / 16) * g_cellH, &ch, 1);
    }
    GdiFlush();
    DWORD* px = (DWORD*)bits;
    for (int y = ATLAS_H - 6; y < ATLAS_H; y++)
        for (int x = ATLAS_W - 6; x < ATLAS_W; x++) px[y * ATLAS_W + x] = 0xFFFFFFFF;

    typedef HRESULT(WINAPI * CT_t)(void*, UINT, UINT, UINT, DWORD, D3DFORMAT, DWORD, void**);
    void* tex = NULL;
    HRESULT hr = ((CT_t)VT(dev)[IDX_DEV_CreateTexture])(dev, ATLAS_W, ATLAS_H, 1, 0, D3DFMT_A8R8G8B8,
                                                        D3DPOOL_MANAGED, &tex);
    bool ok = false;
    if (SUCCEEDED(hr) && tex) {
        typedef HRESULT(WINAPI * TL_t)(void*, UINT, D3DLOCKED_RECT8*, const RECT*, DWORD);
        typedef HRESULT(WINAPI * TU_t)(void*, UINT);
        D3DLOCKED_RECT8 lr;
        if (SUCCEEDED(((TL_t)VT(tex)[IDX_TEX_LockRect])(tex, 0, &lr, NULL, 0))) {
            for (int y = 0; y < ATLAS_H; y++) {
                DWORD* dst = (DWORD*)((BYTE*)lr.pBits + y * lr.Pitch);
                for (int x = 0; x < ATLAS_W; x++) {
                    DWORD s = px[y * ATLAS_W + x];
                    BYTE r = (BYTE)(s >> 16), g = (BYTE)(s >> 8), b = (BYTE)s;
                    BYTE a = r > g ? (r > b ? r : b) : (g > b ? g : b);
                    dst[x] = ((DWORD)a << 24) | 0x00FFFFFF;
                }
            }
            ((TU_t)VT(tex)[IDX_TEX_UnlockRect])(tex, 0);
            g_fontTex = tex;
            ok = true;
        }
    }
    SelectObject(dc, oldFont);
    SelectObject(dc, oldBmp);
    DeleteObject(font);
    DeleteObject(bmp);
    DeleteDC(dc);
    Log("font texture: hr=0x%08X cell=%dx%d ok=%d", hr, g_cellW, g_cellH, ok);
    return ok;
}

static void AddQuad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, DWORD c) {
    if (g_nverts + 6 > (int)(sizeof(g_verts) / sizeof(g_verts[0]))) return;
    x0 -= 0.5f;
    y0 -= 0.5f;
    x1 -= 0.5f;
    y1 -= 0.5f;
    OVert a = {x0, y0, 0, 1, c, u0, v0}, b = {x1, y0, 0, 1, c, u1, v0};
    OVert d = {x0, y1, 0, 1, c, u0, v1}, e = {x1, y1, 0, 1, c, u1, v1};
    OVert* o = &g_verts[g_nverts];
    o[0] = a;
    o[1] = b;
    o[2] = d;
    o[3] = b;
    o[4] = e;
    o[5] = d;
    g_nverts += 6;
}

// Text: lines separated by '\n'. "\x01RRGGBB" sets colour for the rest of the line.
static void BuildText(const char* text, float x, float y, int scale) {
    float cw = (float)g_cellW * scale, ch = (float)g_cellH * scale;
    // measure
    int maxCols = 0, lines = 0, cols = 0;
    for (const char* p = text;; p++) {
        if (*p == '\x01') {
            for (int k = 0; k < 6 && p[1]; k++) p++;
            continue;
        }
        if (*p == '\n' || !*p) {
            if (cols > maxCols) maxCols = cols;
            lines++;
            cols = 0;
            if (!*p) break;
            continue;
        }
        cols++;
    }
    AddQuad(x - 4, y - 3, x + maxCols * cw + 4, y + lines * ch + 3, SOLID_U, SOLID_V, SOLID_U, SOLID_V, 0xA0000000);
    float cx = x, cy = y;
    DWORD color = 0xFFFFFFFF;
    for (const char* p = text; *p; p++) {
        unsigned char c = (unsigned char)*p;
        if (c == '\x01') {
            char hex[7] = {0};
            for (int k = 0; k < 6 && p[1]; k++) hex[k] = *++p;
            color = 0xFF000000 | strtoul(hex, NULL, 16);
            continue;
        }
        if (c == '\n') {
            cx = x;
            cy += ch;
            color = 0xFFFFFFFF;
            continue;
        }
        if (c < 32 || c > 126) c = '?';
        int i = c - 32;
        float u0 = (float)((i % 16) * g_cellW) / ATLAS_W, v0 = (float)((i / 16) * g_cellH) / ATLAS_H;
        float u1 = u0 + (float)g_cellW / ATLAS_W, v1 = v0 + (float)g_cellH / ATLAS_H;
        if (c != ' ') AddQuad(cx, cy, cx + cw, cy + ch, u0, v0, u1, v1, color);
        cx += cw;
    }
}

static void FlushQuads(void* dev);
static void DrawOverlay(void* dev, const char* text) {
    if (!g_fontTex && !CreateFontTexture(dev)) return;
    g_nverts = 0;
    BuildText(text, 8, 8, g_cfg.overlayScale);
    FlushQuads(dev);
}

static void FlushQuads(void* dev) {
    if (!g_nverts || !g_fontTex) return;

    typedef HRESULT(WINAPI * CSB_t)(void*, DWORD, DWORD*);
    typedef HRESULT(WINAPI * TOK_t)(void*, DWORD);
    typedef HRESULT(WINAPI * SRS_t)(void*, DWORD, DWORD);
    typedef HRESULT(WINAPI * STEX_t)(void*, DWORD, void*);
    typedef HRESULT(WINAPI * STSS_t)(void*, DWORD, DWORD, DWORD);
    typedef HRESULT(WINAPI * DPUP_t)(void*, DWORD, UINT, const void*, UINT);
    typedef HRESULT(WINAPI * H_t)(void*, DWORD);
    typedef HRESULT(WINAPI * V_t)(void*);
    void** vt = VT(dev);
    DWORD token = 0;
    if (FAILED(((CSB_t)vt[IDX_DEV_CreateStateBlock])(dev, D3DSBT_ALL, &token))) return;
    SRS_t srs = (SRS_t)vt[IDX_DEV_SetRenderState];
    STSS_t tss = (STSS_t)vt[IDX_DEV_SetTextureStageState];
    ((V_t)vt[IDX_DEV_BeginScene])(dev);
    ((H_t)vt[IDX_DEV_SetVertexShader])(dev, D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1);
    ((H_t)vt[IDX_DEV_SetPixelShader])(dev, 0);
    srs(dev, D3DRS_ZENABLE, 0);
    srs(dev, D3DRS_ZWRITEENABLE, 0);
    srs(dev, D3DRS_ALPHATESTENABLE, 0);
    srs(dev, D3DRS_ALPHABLENDENABLE, 1);
    srs(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    srs(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    srs(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    srs(dev, D3DRS_FOGENABLE, 0);
    srs(dev, D3DRS_LIGHTING, 0);
    srs(dev, D3DRS_FILLMODE, D3DFILL_SOLID);
    srs(dev, D3DRS_STENCILENABLE, 0);
    srs(dev, D3DRS_SPECULARENABLE, 0);
    srs(dev, D3DRS_VERTEXBLEND, 0);
    srs(dev, D3DRS_COLORWRITEENABLE, 0xF);
    ((STEX_t)vt[IDX_DEV_SetTexture])(dev, 0, g_fontTex);
    ((STEX_t)vt[IDX_DEV_SetTexture])(dev, 1, NULL);
    tss(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    tss(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    tss(dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    tss(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    tss(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    tss(dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    tss(dev, 0, D3DTSS_TEXCOORDINDEX, 0);
    tss(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, 0);
    tss(dev, 0, D3DTSS_ADDRESSU, D3DTADDRESS_CLAMP);
    tss(dev, 0, D3DTSS_ADDRESSV, D3DTADDRESS_CLAMP);
    tss(dev, 0, D3DTSS_MAGFILTER, D3DTEXF_POINT);
    tss(dev, 0, D3DTSS_MINFILTER, D3DTEXF_POINT);
    tss(dev, 0, D3DTSS_MIPFILTER, D3DTEXF_NONE);
    tss(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    tss(dev, 1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    DPUP_t dp = (DPUP_t)vt[IDX_DEV_DrawPrimitiveUP];
    for (int i = 0; i < g_nverts; i += 600) {
        int n = g_nverts - i < 600 ? g_nverts - i : 600;
        dp(dev, D3DPT_TRIANGLELIST, n / 3, &g_verts[i], sizeof(OVert));
    }
    ((V_t)vt[IDX_DEV_EndScene])(dev);
    ((TOK_t)vt[IDX_DEV_ApplyStateBlock])(dev, token);
    ((TOK_t)vt[IDX_DEV_DeleteStateBlock])(dev, token);
}

// ----- screenshot -----------------------------------------------------------
static void TakeScreenshot(void* dev) {
    typedef HRESULT(WINAPI * GBB_t)(void*, UINT, DWORD, void**);
    typedef HRESULT(WINAPI * SD_t)(void*, D3DSURFACE_DESC8*);
    typedef HRESULT(WINAPI * SL_t)(void*, D3DLOCKED_RECT8*, const RECT*, DWORD);
    typedef HRESULT(WINAPI * SU_t)(void*);
    typedef ULONG(WINAPI * Rel_t)(void*);
    void* surf = NULL;
    if (FAILED(((GBB_t)VT(dev)[IDX_DEV_GetBackBuffer])(dev, 0, 0, &surf)) || !surf) return;
    D3DSURFACE_DESC8 d;
    ((SD_t)VT(surf)[IDX_SURF_GetDesc])(surf, &d);
    D3DLOCKED_RECT8 lr;
    HRESULT hr = ((SL_t)VT(surf)[IDX_SURF_LockRect])(surf, &lr, NULL, D3DLOCK_READONLY);
    if (SUCCEEDED(hr)) {
        char dir[MAX_PATH], path[MAX_PATH];
        _snprintf(dir, sizeof(dir), "%s\\screens", g_toolDir);
        CreateDirectoryA(dir, NULL);
        SYSTEMTIME st;
        GetLocalTime(&st);
        _snprintf(path, sizeof(path), "%s\\shot_%04d%02d%02d_%02d%02d%02d_%03d.bmp", dir, st.wYear, st.wMonth, st.wDay,
                  st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
        UINT w = d.Width, h = d.Height;
        UINT rowBytes = (w * 3 + 3) & ~3u;
        BYTE* img = (BYTE*)malloc(rowBytes * h);
        for (UINT y = 0; y < h; y++) {
            BYTE* src = (BYTE*)lr.pBits + y * lr.Pitch;
            BYTE* dst = img + (h - 1 - y) * rowBytes;
            for (UINT x = 0; x < w; x++) {
                BYTE r, g, b;
                if (d.Format == D3DFMT_X8R8G8B8 || d.Format == D3DFMT_A8R8G8B8) {
                    DWORD p = ((DWORD*)src)[x];
                    r = (BYTE)(p >> 16);
                    g = (BYTE)(p >> 8);
                    b = (BYTE)p;
                } else if (d.Format == D3DFMT_R5G6B5) {
                    WORD p = ((WORD*)src)[x];
                    r = (BYTE)(((p >> 11) & 31) * 255 / 31);
                    g = (BYTE)(((p >> 5) & 63) * 255 / 63);
                    b = (BYTE)((p & 31) * 255 / 31);
                } else {
                    WORD p = ((WORD*)src)[x];
                    r = (BYTE)(((p >> 10) & 31) * 255 / 31);
                    g = (BYTE)(((p >> 5) & 31) * 255 / 31);
                    b = (BYTE)((p & 31) * 255 / 31);
                }
                dst[x * 3 + 0] = b;
                dst[x * 3 + 1] = g;
                dst[x * 3 + 2] = r;
            }
        }
        ((SU_t)VT(surf)[IDX_SURF_UnlockRect])(surf);
        FILE* f = fopen(path, "wb");
        if (f) {
            BITMAPFILEHEADER fh = {};
            BITMAPINFOHEADER ih = {};
            fh.bfType = 0x4D42;
            fh.bfOffBits = sizeof(fh) + sizeof(ih);
            fh.bfSize = fh.bfOffBits + rowBytes * h;
            ih.biSize = sizeof(ih);
            ih.biWidth = w;
            ih.biHeight = h;
            ih.biPlanes = 1;
            ih.biBitCount = 24;
            fwrite(&fh, sizeof(fh), 1, f);
            fwrite(&ih, sizeof(ih), 1, f);
            fwrite(img, rowBytes, h, f);
            fclose(f);
            if (g_br) {
                strncpy(g_br->screenshotPath, path, sizeof(g_br->screenshotPath) - 1);
                g_br->screenshotCount++;
            }
        }
        free(img);
    } else {
        Log("screenshot: LockRect failed hr=0x%08X (set Screenshots=1)", hr);
        if (g_br) g_br->screenshotCount++;
    }
    ((Rel_t)VT(surf)[IDX_SURF_Release])(surf);
}

// ----- limiter --------------------------------------------------------------
static HANDLE g_waitTimer;
static int64_t g_nextFrame;

static void PreciseWaitUntil(int64_t target) {
    for (;;) {
        int64_t now = RealNow();
        int64_t remain = target - now;
        if (remain <= 0) return;
        double ms = remain * 1000.0 / g_qpf;
        if (ms > 2.0) {
            if (g_waitTimer) {
                LARGE_INTEGER due;
                due.QuadPart = -(LONGLONG)((ms - 1.5) * 10000.0);
                SetWaitableTimer(g_waitTimer, &due, 0, NULL, NULL, FALSE);
                WaitForSingleObject(g_waitTimer, INFINITE);
            } else {
                Sleep((DWORD)(ms - 1.5));
            }
        } else {
            YieldProcessor();
        }
    }
}

static void LimitFrame(double fps) {
    if (fps <= 0) {
        g_nextFrame = 0;
        return;
    }
    int64_t period = (int64_t)(g_qpf / fps);
    int64_t now = RealNow();
    if (g_nextFrame == 0 || now - g_nextFrame > period * 2) g_nextFrame = now;  // too far behind: resync
    if (now < g_nextFrame) PreciseWaitUntil(g_nextFrame);
    g_nextFrame += period;
}

// ----- hotkeys ---------------------------------------------------------------
static bool g_keyDown[256];
static bool KeyPressed(int vk) {
    if (vk <= 0 || vk > 255) return false;
    bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
    bool pressed = down && !g_keyDown[vk];
    g_keyDown[vk] = down;
    return pressed;
}

static bool GameFocused() {
    HWND fg = GetForegroundWindow();
    if (!fg) return false;
    DWORD pid = 0;
    GetWindowThreadProcessId(fg, &pid);
    return pid == GetCurrentProcessId();
}

static const int kSpeeds[] = {100, 50, 25, 10};

static void PollHotkeys() {
    if (!g_cfg.hotkeys || !g_br) return;
    bool focused = GameFocused();
    bool pPause = KeyPressed(g_cfg.keyPause), pStep = KeyPressed(g_cfg.keyStep);
    bool pSpeed = KeyPressed(g_cfg.keySpeed), pOv = KeyPressed(g_cfg.keyOverlay), pShot = KeyPressed(g_cfg.keyShot);
    if (!focused) return;
    if (pPause) g_br->paused = !g_br->paused;
    if (pStep) {
        if (g_br->paused)
            g_br->stepFrames++;
        else
            g_br->paused = 1;
    }
    if (pSpeed) {
        int cur = 0;
        for (int i = 0; i < 4; i++)
            if (kSpeeds[i] == g_br->speedPct) cur = i;
        g_br->speedPct = kSpeeds[(cur + 1) % 4];
    }
    if (pOv) g_br->overlayOn = !g_br->overlayOn;
    if (pShot) g_br->screenshotReq = 1;
    if (KeyPressed(g_cfg.keyFreecam) && focused) g_br->freecamOn = !g_br->freecamOn;
}

// ----- clock state sync ------------------------------------------------------
static int g_appliedSpeed = 100, g_appliedFixed = -1, g_appliedPaused = 0;
static bool g_stepFrame;  // the frame now running was released by frame-advance

static void SyncClock() {
    if (!g_cfg.timeHook || !g_br) return;
    int speed = g_br->speedPct;
    if (speed < 1) speed = 1;
    if (speed > 1000) speed = 1000;
    // while paused / frame-stepping every released frame gets exactly 1/fpsTarget of game time
    int fixed = (g_br->fixedStep || g_br->paused) ? 1 : 0;
    int paused = g_br->paused && !g_stepFrame;
    if (speed != g_appliedSpeed || fixed != g_appliedFixed || paused != g_appliedPaused) {
        SetClock(paused ? 0.0 : speed / 100.0, fixed);
        g_appliedSpeed = speed;
        g_appliedFixed = fixed;
        g_appliedPaused = paused;
    }
}

// ----- camera capture ----------------------------------------------------------
static bool g_fcInit;
static void BuildLookView(float* m, const float* eye, float yaw, float pitch);
typedef HRESULT(WINAPI* SetTransform_t)(void*, DWORD, const float*);
static SetTransform_t RealSetTransform;
static float g_view[16], g_proj[16];
static bool g_haveView, g_haveProj;

static HRESULT WINAPI Hook_SetTransform(void* dev, DWORD state, const float* m) {
    if (m) {
        if (state == 2) {  // D3DTS_VIEW, skip identity (2D passes)
            bool ident = m[0] == 1.f && m[5] == 1.f && m[10] == 1.f && m[12] == 0.f && m[13] == 0.f && m[14] == 0.f &&
                         m[1] == 0.f && m[2] == 0.f && m[4] == 0.f;
            if (!ident) {
                if (g_br && g_br->freecamOn && g_fcInit) {
                    static float fv[16];
                    BuildLookView(fv, g_br->freecam, g_br->freecam[3], g_br->freecam[4]);
                    memcpy(g_view, fv, 64);
                    g_haveView = true;
                    return RealSetTransform(dev, state, fv);
                }
                memcpy(g_view, m, 64);
                g_haveView = true;
            }
        } else if (state == 3) {  // D3DTS_PROJECTION, keep perspective ones only
            if (m[11] != 0.f && m[15] == 0.f) {
                memcpy(g_proj, m, 64);
                g_haveProj = true;
            }
        }
    }
    return RealSetTransform(dev, state, m);
}

// ----- world-space lines and labels ----------------------------------------------
static bool ProjectToScreen(float x, float y, float z, float* sx, float* sy) {
    float v[4], c[4];
    for (int i = 0; i < 4; i++) v[i] = x * g_view[0 * 4 + i] + y * g_view[1 * 4 + i] + z * g_view[2 * 4 + i] + g_view[3 * 4 + i];
    for (int i = 0; i < 4; i++) c[i] = v[0] * g_proj[0 * 4 + i] + v[1] * g_proj[1 * 4 + i] + v[2] * g_proj[2 * 4 + i] + v[3] * g_proj[3 * 4 + i];
    if (c[3] <= 0.01f) return false;
    float nx = c[0] / c[3], ny = c[1] / c[3];
    if (nx < -1.2f || nx > 1.2f || ny < -1.2f || ny > 1.2f) return false;
    float w = (float)(g_pp.BackBufferWidth ? g_pp.BackBufferWidth : 800);
    float h = (float)(g_pp.BackBufferHeight ? g_pp.BackBufferHeight : 600);
    *sx = (nx + 1.f) * 0.5f * w;
    *sy = (1.f - ny) * 0.5f * h;
    return true;
}

static void DrawWorldLines(void* dev) {
    if (!g_br || !g_br->worldOn || !g_haveView || !g_haveProj) return;
    uint32_t n = g_br->lineCount & ~1u;
    if (n > MAX_LINE_VERTS) n = MAX_LINE_VERTS;
    if (!n) return;
    typedef HRESULT(WINAPI * CSB_t)(void*, DWORD, DWORD*);
    typedef HRESULT(WINAPI * TOK_t)(void*, DWORD);
    typedef HRESULT(WINAPI * SRS_t)(void*, DWORD, DWORD);
    typedef HRESULT(WINAPI * STEX_t)(void*, DWORD, void*);
    typedef HRESULT(WINAPI * STSS_t)(void*, DWORD, DWORD, DWORD);
    typedef HRESULT(WINAPI * DPUP_t)(void*, DWORD, UINT, const void*, UINT);
    typedef HRESULT(WINAPI * H_t)(void*, DWORD);
    typedef HRESULT(WINAPI * V_t)(void*);
    void** vt = VT(dev);
    DWORD token = 0;
    if (FAILED(((CSB_t)vt[IDX_DEV_CreateStateBlock])(dev, D3DSBT_ALL, &token))) return;
    SRS_t srs = (SRS_t)vt[IDX_DEV_SetRenderState];
    STSS_t tss = (STSS_t)vt[IDX_DEV_SetTextureStageState];
    static const float ident[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    ((V_t)vt[IDX_DEV_BeginScene])(dev);
    RealSetTransform(dev, 256 /*D3DTS_WORLD*/, ident);
    RealSetTransform(dev, 2, g_view);
    RealSetTransform(dev, 3, g_proj);
    ((H_t)vt[IDX_DEV_SetVertexShader])(dev, 0x002 /*XYZ*/ | D3DFVF_DIFFUSE);
    ((H_t)vt[IDX_DEV_SetPixelShader])(dev, 0);
    srs(dev, D3DRS_ZENABLE, g_br->worldDepth ? 1 : 0);
    srs(dev, D3DRS_ZWRITEENABLE, 0);
    srs(dev, D3DRS_ALPHATESTENABLE, 0);
    srs(dev, D3DRS_ALPHABLENDENABLE, 1);
    srs(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    srs(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    srs(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    srs(dev, D3DRS_FOGENABLE, 0);
    srs(dev, D3DRS_LIGHTING, 0);
    srs(dev, D3DRS_FILLMODE, D3DFILL_SOLID);
    srs(dev, D3DRS_STENCILENABLE, 0);
    srs(dev, D3DRS_VERTEXBLEND, 0);
    srs(dev, D3DRS_COLORWRITEENABLE, 0xF);
    srs(dev, D3DRS_CLIPPING, 1);
    ((STEX_t)vt[IDX_DEV_SetTexture])(dev, 0, NULL);
    tss(dev, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    tss(dev, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    tss(dev, 0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    tss(dev, 0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    tss(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, 0);
    tss(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    tss(dev, 1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    DPUP_t dp = (DPUP_t)vt[IDX_DEV_DrawPrimitiveUP];
    for (uint32_t i = 0; i < n; i += 30000) {
        uint32_t k = n - i < 30000 ? n - i : 30000;
        dp(dev, 2 /*D3DPT_LINELIST*/, k / 2, &g_br->lines[i], sizeof(CLBridge::LineVert));
    }
    ((V_t)vt[IDX_DEV_EndScene])(dev);
    ((TOK_t)vt[IDX_DEV_ApplyStateBlock])(dev, token);
    ((TOK_t)vt[IDX_DEV_DeleteStateBlock])(dev, token);
}

static void BuildWorldLabels() {
    if (!g_br || !g_br->worldOn || !g_haveView || !g_haveProj) return;
    uint32_t n = g_br->labelCount;
    if (n > MAX_LABELS) n = MAX_LABELS;
    char buf[64];
    for (uint32_t i = 0; i < n; i++) {
        CLBridge::Label& l = g_br->labels[i];
        float sx, sy;
        if (!ProjectToScreen(l.x, l.y, l.z, &sx, &sy)) continue;
        _snprintf(buf, sizeof(buf), "\x01%06X%.47s", l.color & 0xFFFFFF, l.text);
        buf[sizeof(buf) - 1] = 0;
        BuildText(buf, sx, sy, 1);
    }
}

// ----- remote calls -------------------------------------------------------------
static __declspec(noinline) uint32_t DoCall(uint32_t fn, uint32_t thisp, const uint32_t* args, uint32_t n) {
    uint32_t result = 0;
    __asm {
        mov esi, esp
        mov ecx, n
        mov edx, args
    push_loop:
        test ecx, ecx
        jz do_call
        dec ecx
        push dword ptr [edx + ecx * 4]
        jmp push_loop
    do_call:
        mov ecx, thisp
        call fn
        mov result, eax
        mov esp, esi
    }
    return result;
}

static void ExecRemoteCall() {
    if (!g_br) return;
    uint32_t seq = g_br->callSeq;
    if (seq == g_br->callDone) return;
    uint32_t args[8];
    uint32_t n = g_br->callNArgs;
    uint32_t fn = g_br->callFn;
    if (n > 8 || fn < 0x401000 || fn >= 0x7FFF0000) {
        g_br->callStatus = 2;
        g_br->callDone = seq;
        return;
    }
    memcpy(args, g_br->callArgs, sizeof(args));
    uint32_t thisp = g_br->callConv == 1 ? g_br->callThis : 0;
    g_inRemoteCall = 1;
    __try {
        g_br->callResult = DoCall(fn, thisp, args, n);
        g_br->callStatus = 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_br->callStatus = 1;
        Log("remote call 0x%08X raised exception 0x%08X", fn, GetExceptionCode());
    }
    g_inRemoteCall = 0;
    g_br->callDone = seq;
}

// ----- v4: per-frame recorder and exception catcher ------------------------------------
static const uint32_t REC_RING = 8192;
static const int kRecKeys[32] = {'W', 'A', 'S', 'D', VK_SPACE, 'R', 'E', VK_LSHIFT, 'V', VK_LBUTTON, VK_RBUTTON,
                                 VK_NUMPAD8, VK_NUMPAD2, VK_NUMPAD4, VK_NUMPAD6, VK_ESCAPE, VK_RETURN, VK_UP, VK_DOWN,
                                 VK_LEFT, VK_RIGHT, VK_CONTROL, VK_TAB, 'Q', 'F', 'C', 'X', 'Z', VK_F5, VK_F6, VK_F7,
                                 VK_F8};
static void RecordFrame() {
    if (!g_br || !g_br->recOn) return;
    g_br->recRing = REC_RING;
    uint32_t h = g_br->recHead;
    CLBridge::Rec& r = g_br->rec[h % REC_RING];
    r.frame = g_br->frame;
    r.vtimeMs = g_br->vtime_lo;
    r.realMs = (double)RealNow() * 1000.0 / (double)g_qpf;
    uint32_t keys = 0;
    for (int i = 0; i < 32; i++)
        if (GetAsyncKeyState(kRecKeys[i]) & 0x8000) keys |= 1u << i;
    r.keys = keys;
    r.flags = (g_br->videoPlaying ? 1u : 0u) | (g_br->paused ? 2u : 0u) | (g_br->freecamOn ? 8u : 0u);
    r.fps = g_br->fps;
    uint32_t n = g_br->recNumAddr > 96 ? 96 : g_br->recNumAddr;
    __try {
        r.gameMs = *(volatile uint32_t*)0x856C24;
        for (uint32_t i = 0; i < n; i++) {
            uint32_t a = g_br->recAddr[i];
            r.vals[i] = a ? *(volatile uint32_t*)(uintptr_t)a : 0;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        r.flags |= 4;
    }
    MemoryBarrier();
    g_br->recHead = h + 1;
}

static LONG CALLBACK FirstChanceHandler(EXCEPTION_POINTERS* ep) {
    if (!g_br || !ep || !ep->ExceptionRecord || !ep->ContextRecord) return EXCEPTION_CONTINUE_SEARCH;
    DWORD code = ep->ExceptionRecord->ExceptionCode;
    if (code == 0x406D1388 || code == 0x40010006 || code == 0xE06D7363 || code < 0x80000000)
        return EXCEPTION_CONTINUE_SEARCH;  // thread naming, debug strings, C++ throws, non-errors
    uint32_t eip = ep->ContextRecord->Eip;
    if (eip < 0x401000 || eip >= 0x800000) return EXCEPTION_CONTINUE_SEARCH;  // only game code
    uint32_t i = g_br->excHead % 16;
    CLBridge::Exc& e = g_br->exc[i];
    e.frame = g_br->frame;
    e.code = code;
    e.eip = eip;
    e.access = ep->ExceptionRecord->NumberParameters >= 2 ? (uint32_t)ep->ExceptionRecord->ExceptionInformation[1] : 0;
    e.esp = ep->ContextRecord->Esp;
    e.inCall = g_inRemoteCall ? 1 : 0;
    g_br->excHead++;
    return EXCEPTION_CONTINUE_SEARCH;
}

static LPTOP_LEVEL_EXCEPTION_FILTER g_prevFilter;
static LONG WINAPI CrashFilter(EXCEPTION_POINTERS* ep) {
    if (g_br && ep && ep->ExceptionRecord && ep->ContextRecord) {
        CONTEXT* c = ep->ContextRecord;
        g_br->crashCode = ep->ExceptionRecord->ExceptionCode;
        g_br->crashEip = c->Eip;
        g_br->crashAccessType =
            ep->ExceptionRecord->NumberParameters >= 1 ? (uint32_t)ep->ExceptionRecord->ExceptionInformation[0] : 0;
        g_br->crashAccess =
            ep->ExceptionRecord->NumberParameters >= 2 ? (uint32_t)ep->ExceptionRecord->ExceptionInformation[1] : 0;
        g_br->crashFrame = g_br->frame;
        uint32_t regs[8] = {c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp};
        memcpy(g_br->crashRegs, regs, sizeof(regs));
        __try {
            memcpy(g_br->crashStack, (void*)(uintptr_t)c->Esp, sizeof(g_br->crashStack));
        } __except (EXCEPTION_EXECUTE_HANDLER) {
        }
        MemoryBarrier();
        g_br->crashSeq++;
        Log("CRASH code=0x%08X eip=0x%08X %s 0x%08X frame=%u eax=%08X ebx=%08X ecx=%08X edx=%08X esi=%08X edi=%08X "
            "ebp=%08X esp=%08X",
            g_br->crashCode, c->Eip, g_br->crashAccessType ? "write" : "read", g_br->crashAccess, g_br->frame, c->Eax,
            c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp);
    }
    return g_prevFilter ? g_prevFilter(ep) : EXCEPTION_CONTINUE_SEARCH;
}

static void InstallCrashCatcher() {
    AddVectoredExceptionHandler(1, FirstChanceHandler);
    g_prevFilter = SetUnhandledExceptionFilter(CrashFilter);
    Log("exception catcher installed (prev filter %p)", g_prevFilter);
}

// ----- batched script calls --------------------------------------------------------
static uint8_t g_scCtx[0x200];
static uint8_t g_scStack[0x80];
static uint32_t g_scVals[32];
static uint8_t g_scTypes[32];

static void ExecScriptCalls() {
    if (!g_br) return;
    uint32_t seq = g_br->scSeq;
    if (seq == g_br->scDone) return;
    uint32_t n = g_br->scCount;
    if (n > MAX_SCRIPT_CALLS) n = MAX_SCRIPT_CALLS;
    uint32_t errors = 0;
    for (uint32_t i = 0; i < n; i++) {
        CLBridge::ScriptCall& c = g_br->sc[i];
        memset(g_scCtx, 0, sizeof(g_scCtx));
        memset(g_scStack, 0, sizeof(g_scStack));
        memset(g_scVals, 0, sizeof(g_scVals));
        memset(g_scTypes, 0, sizeof(g_scTypes));
        *(uint32_t*)(g_scCtx + 0xF0) = (uint32_t)(uintptr_t)g_scStack;
        *(uint32_t*)(g_scStack + 0x30) = (uint32_t)(uintptr_t)g_scVals;
        *(uint32_t*)(g_scStack + 0x34) = (uint32_t)(uintptr_t)g_scTypes;
        uint32_t na = c.nargs > 4 ? 4 : c.nargs;
        for (uint32_t k = 0; k < na; k++) {
            g_scVals[k] = c.args[k];
            g_scTypes[k] = c.types[k];
        }
        g_scStack[8] = (uint8_t)(int8_t)((int)na - 1);
        if (c.fn < 0x401000 || c.fn >= 0x800000) {
            c.rtype = 0xFF;
            errors++;
            continue;
        }
        uint32_t args[2] = {(uint32_t)(uintptr_t)g_scCtx, 0};
        __try {
            DoCall(c.fn, 0, args, 2);
            int sp = (int8_t)g_scStack[8];
            if (sp >= 0 && sp < 32) {
                c.rtype = g_scTypes[sp];
                c.result = g_scVals[sp];
            } else {
                c.rtype = 0;
                c.result = 0;
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            c.rtype = 0xFF;
            errors++;
        }
    }
    g_br->scErrors = errors;
    g_br->scDone = seq;
}

// ----- free camera -----------------------------------------------------------------
static int64_t g_fcLast;

static void BuildLookView(float* m, const float* eye, float yaw, float pitch) {
    // right-handed view (the game's projection is right-handed): camera looks along -Z
    float fx = sinf(yaw) * cosf(pitch), fy = sinf(pitch), fz = cosf(yaw) * cosf(pitch);  // forward
    float zx = -fx, zy = -fy, zz = -fz;                                                     // zaxis = eye - at
    float xx = 1.f * zz - 0.f * zy, xy = 0.f * zx - 0.f * zz, xz = 0.f * zy - 1.f * zx;    // cross(up, z)
    float xl = sqrtf(xx * xx + xy * xy + xz * xz);
    if (xl < 1e-6f) xl = 1e-6f;
    xx /= xl; xy /= xl; xz /= xl;
    float yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;            // cross(z, x)
    m[0] = xx; m[1] = yx; m[2] = zx; m[3] = 0;
    m[4] = xy; m[5] = yy; m[6] = zy; m[7] = 0;
    m[8] = xz; m[9] = yz; m[10] = zz; m[11] = 0;
    m[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
    m[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
    m[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]);
    m[15] = 1;
}

static void FreecamFromView(const float* v) {
    // invert the game's view: rows of the 3x3 part are the camera axes (columns of the inverse)
    float zx = v[2], zy = v[6], zz = v[10];
    float tx = v[12], ty = v[13], tz = v[14];
    float ex = -(tx * v[0] + ty * v[1] + tz * v[2]);
    float ey = -(tx * v[4] + ty * v[5] + tz * v[6]);
    float ez = -(tx * v[8] + ty * v[9] + tz * v[10]);
    g_br->freecam[0] = ex; g_br->freecam[1] = ey; g_br->freecam[2] = ez;
    g_br->freecam[3] = atan2f(-zx, -zz);
    float fy = -zy;
    if (fy > 1.f) fy = 1.f;
    if (fy < -1.f) fy = -1.f;
    g_br->freecam[4] = asinf(fy);
}

static void FreecamUpdate() {
    if (!g_br) return;
    if (!g_br->freecamOn) {
        g_fcInit = false;
        return;
    }
    if (!g_fcInit) {
        if (g_haveView) FreecamFromView(g_view);
        g_fcInit = true;
        g_fcLast = RealNow();
    }
    int64_t now = RealNow();
    float dt = (float)((now - g_fcLast) / (double)g_qpf);
    g_fcLast = now;
    if (dt > 0.1f) dt = 0.1f;
    if (!GameFocused()) return;
    auto down = [](int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; };
    float speed = (down(VK_CONTROL) ? 25.f : 6.f) * dt, turn = 1.6f * dt;
    float& yaw = g_br->freecam[3];
    float& pitch = g_br->freecam[4];
    if (down(VK_LEFT)) yaw += turn;
    if (down(VK_RIGHT)) yaw -= turn;
    if (down(VK_UP)) pitch += turn;
    if (down(VK_DOWN)) pitch -= turn;
    if (pitch > 1.55f) pitch = 1.55f;
    if (pitch < -1.55f) pitch = -1.55f;
    float fx = sinf(yaw) * cosf(pitch), fy = sinf(pitch), fz = cosf(yaw) * cosf(pitch);
    float rx = -cosf(yaw), rz = sinf(yaw);
    float* p = g_br->freecam;
    if (down('I')) { p[0] += fx * speed; p[1] += fy * speed; p[2] += fz * speed; }
    if (down('K')) { p[0] -= fx * speed; p[1] -= fy * speed; p[2] -= fz * speed; }
    if (down('L')) { p[0] -= rx * speed; p[2] -= rz * speed; }
    if (down('J')) { p[0] += rx * speed; p[2] += rz * speed; }
    if (down('O')) p[1] += speed;
    if (down('U')) p[1] -= speed;
}

// ----- Present --------------------------------------------------------------
static int64_t g_lastPresent, g_fpsWindowStart;
static uint32_t g_fpsFrames;
static char g_ovText[4096 + 256];

static HRESULT WINAPI Hook_Present(void* dev, const RECT* src, const RECT* dst, HWND wnd, const void* dirty) {
    RecordFrame();
    PollHotkeys();
    FreecamUpdate();
    SyncClock();
    ExecRemoteCall();
    ExecScriptCalls();
    if (g_br) {
        g_br->viewValid = g_haveView && g_haveProj;
        if (g_haveView) memcpy(g_br->view, g_view, 64);
        if (g_haveProj) memcpy(g_br->proj, g_proj, 64);
    }
    DrawWorldLines(dev);
    if (g_br && g_br->worldOn && g_br->labelCount && (g_fontTex || CreateFontTexture(dev))) {
        g_nverts = 0;
        BuildWorldLabels();
        FlushQuads(dev);
    }

    if (g_br && g_br->overlayOn && g_cfg.overlay) {
        double speed = g_br->speedPct / 100.0;
        int n = _snprintf(g_ovText, sizeof(g_ovText) - 1,
                          "\x01" "FFD040CLTools\x01" "FFFFFF %5.1f fps  frame %u  target %d  speed x%.2f%s%s",
                          g_br->fps, g_br->frame, g_br->fpsTarget, speed, g_br->fixedStep ? (g_br->freecamOn ? "  FIXED  FREECAM" : "  FIXED") : (g_br->freecamOn ? "  FREECAM" : ""),
                          g_br->paused ? "  \x01" "FF5050PAUSED (F5 resume, F6 step)" : "");
        if (n > 0 && g_br->overlayText[0]) {
            g_ovText[n++] = '\n';
            strncpy(g_ovText + n, g_br->overlayText, sizeof(g_ovText) - n - 1);
        }
        g_ovText[sizeof(g_ovText) - 1] = 0;
        DrawOverlay(dev, g_ovText);
    }
    if (g_br && g_br->screenshotReq) {
        g_br->screenshotReq = 0;
        TakeScreenshot(dev);
    }

    double target = g_br ? g_br->fpsTarget : g_cfg.fpsTarget;
    if (g_br && g_br->speedPct != 100 && target > 0) target = target * g_br->speedPct / 100.0;
    bool vsyncDoesIt = !g_pp.Windowed && g_cfg.vsync;
    if (!vsyncDoesIt) LimitFrame(target);

    HRESULT hr = RealPresent(dev, src, dst, wnd, dirty);

    int64_t now = RealNow();
    if (g_br) {
        g_br->frame++;
        if (g_lastPresent) g_br->frameMs = (float)((now - g_lastPresent) * 1000.0 / g_qpf);
        g_fpsFrames++;
        if (!g_fpsWindowStart) g_fpsWindowStart = now;
        if (now - g_fpsWindowStart >= g_qpf / 2) {
            g_br->fps = (float)(g_fpsFrames * (double)g_qpf / (now - g_fpsWindowStart));
            g_fpsFrames = 0;
            g_fpsWindowStart = now;
        }
        g_br->vtime_lo = (DWORD)((VirtualNow() - g_vStart) * 1000 / g_qpf);
    }
    g_lastPresent = now;
    if (g_cfg.timeHook) ClockOnPresent(g_br ? g_br->fpsTarget : g_cfg.fpsTarget);

    // pause / frame advance: block here after the frame is shown
    g_stepFrame = false;
    if (g_br && g_br->paused) {
        if (g_br->stepFrames <= 0) {
            SyncClock();  // freeze game time
            while (g_br->paused && g_br->stepFrames <= 0) {
                PollHotkeys();
                if (g_br->screenshotReq) {
                    g_br->screenshotReq = 0;
                    TakeScreenshot(dev);
                }
                // Keep the thread's input hooks alive: DirectInput's keyboard/mouse use low-level hooks that
                // are serviced on this thread. PM_NOREMOVE only processes sent messages / hook callbacks,
                // posted messages stay queued for the game's own loop.
                MSG msg;
                PeekMessageA(&msg, NULL, 0, 0, PM_NOREMOVE);
                MsgWaitForMultipleObjects(0, NULL, FALSE, 5, QS_ALLINPUT);
                ExecRemoteCall();
                ExecScriptCalls();
            }
            g_nextFrame = 0;
            g_lastPresent = 0;
        }
        if (g_br->paused && g_br->stepFrames > 0) {
            g_br->stepFrames--;
            g_stepFrame = true;  // release exactly one frame
        }
    }
    SyncClock();
    return hr;
}

static HRESULT WINAPI Hook_Reset(void* dev, D3DPRESENT_PARAMETERS8* pp) {
    Log("Reset: %ux%u fmt=%u windowed=%d refresh=%u interval=0x%X", pp->BackBufferWidth, pp->BackBufferHeight,
        pp->BackBufferFormat, pp->Windowed, pp->FullScreen_RefreshRateInHz, pp->FullScreen_PresentationInterval);
    ApplyPresentOverrides(pp);
    HRESULT hr = RealReset(dev, pp);
    Log("Reset -> 0x%08X", hr);
    if (SUCCEEDED(hr)) {
        StorePresentParams(pp);
        FixWindow();
    }
    return hr;
}

static HRESULT WINAPI Hook_CreateDevice(void* d3d, UINT adapter, DWORD type, HWND focus, DWORD behavior,
                                        D3DPRESENT_PARAMETERS8* pp, void** ppDev) {
    Log("CreateDevice: adapter=%u type=%u behavior=0x%X %ux%u fmt=%u bbcount=%u ms=%u swap=%u windowed=%d "
        "depth=%d/%u flags=0x%X refresh=%u interval=0x%X",
        adapter, type, behavior, pp->BackBufferWidth, pp->BackBufferHeight, pp->BackBufferFormat,
        pp->BackBufferCount, pp->MultiSampleType, pp->SwapEffect, pp->Windowed, pp->EnableAutoDepthStencil,
        pp->AutoDepthStencilFormat, pp->Flags, pp->FullScreen_RefreshRateInHz, pp->FullScreen_PresentationInterval);
    D3DPRESENT_PARAMETERS8 orig = *pp;
    ApplyPresentOverrides(pp);
    behavior &= ~D3DCREATE_PUREDEVICE;  // state blocks need a non-pure device
    HRESULT hr = RealCreateDevice(d3d, adapter, type, focus, behavior, pp, ppDev);
    if (FAILED(hr)) {
        Log("CreateDevice with overrides failed 0x%08X, retrying with game parameters", hr);
        *pp = orig;
        hr = RealCreateDevice(d3d, adapter, type, focus, behavior, pp, ppDev);
    }
    Log("CreateDevice -> 0x%08X dev=%p", hr, ppDev ? *ppDev : NULL);
    if (SUCCEEDED(hr) && ppDev && *ppDev) {
        g_dev = *ppDev;
        g_hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus;
        StorePresentParams(pp);
        if (g_br) {
            g_br->device = (uint32_t)(uintptr_t)g_dev;
            g_br->hwnd = (uint32_t)(uintptr_t)g_hwnd;
        }
        void** vt = VT(g_dev);
        PatchVTable(vt, IDX_DEV_Present, (void*)Hook_Present, (void**)&RealPresent);
        PatchVTable(vt, IDX_DEV_Reset, (void*)Hook_Reset, (void**)&RealReset);
        PatchVTable(vt, IDX_DEV_SetTransform, (void*)Hook_SetTransform, (void**)&RealSetTransform);
        FixWindow();
    }
    return hr;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------
static bool LoadReal() {
    if (g_realD3D8) return true;
    char path[MAX_PATH];
    GetSystemDirectoryA(path, MAX_PATH);
    strcat(path, "\\d3d8.dll");
    g_realD3D8 = LoadLibraryA(path);
    if (!g_realD3D8) {
        Log("cannot load %s", path);
        return false;
    }
    RealDirect3DCreate8 = (Direct3DCreate8_t)GetProcAddress(g_realD3D8, "Direct3DCreate8");
    return RealDirect3DCreate8 != NULL;
}

static bool g_firstCreate = true;

extern "C" void* WINAPI Proxy_Direct3DCreate8(UINT sdk) {
    if (!LoadReal()) return NULL;
    if (g_firstCreate) {
        g_firstCreate = false;
        if (g_cfg.dumpImage) DumpImage();
        if (g_cfg.timeHook) InstallTimeHooks();
        InstallBinkHooks();
        InstallCrashCatcher();
    }
    void* d3d = RealDirect3DCreate8(sdk);
    Log("Direct3DCreate8(%u) -> %p", sdk, d3d);
    if (d3d) {
        g_d3d = d3d;
        PatchVTable(VT(d3d), IDX_D3D_CreateDevice, (void*)Hook_CreateDevice, (void**)&RealCreateDevice);
    }
    return d3d;
}

extern "C" void WINAPI Proxy_DebugSetMute() {
    if (!LoadReal()) return;
    typedef void(WINAPI * F)();
    F f = (F)GetProcAddress(g_realD3D8, "DebugSetMute");
    if (f) f();
}

extern "C" HRESULT WINAPI Proxy_ValidatePixelShader(const DWORD* a, const void* b, BOOL c, char** d) {
    if (!LoadReal()) return E_FAIL;
    typedef HRESULT(WINAPI * F)(const DWORD*, const void*, BOOL, char**);
    F f = (F)GetProcAddress(g_realD3D8, "ValidatePixelShader");
    return f ? f(a, b, c, d) : E_FAIL;
}

extern "C" HRESULT WINAPI Proxy_ValidateVertexShader(const DWORD* a, const DWORD* b, const void* c, BOOL d,
                                                     char** e) {
    if (!LoadReal()) return E_FAIL;
    typedef HRESULT(WINAPI * F)(const DWORD*, const DWORD*, const void*, BOOL, char**);
    F f = (F)GetProcAddress(g_realD3D8, "ValidateVertexShader");
    return f ? f(a, b, c, d, e) : E_FAIL;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_logCs);
        GetModuleFileNameA(NULL, g_gameDir, MAX_PATH);
        char* slash = strrchr(g_gameDir, '\\');
        if (slash) *slash = 0;
        _snprintf(g_toolDir, sizeof(g_toolDir), "%s\\CLTools", g_gameDir);
        CreateDirectoryA(g_toolDir, NULL);
        LoadConfig();
        InitTime();
        InitBridge();
        timeBeginPeriod(1);
        g_waitTimer = CreateWaitableTimerExW(NULL, NULL, 0x00000002 /*HIGH_RESOLUTION*/, TIMER_ALL_ACCESS);
        if (!g_waitTimer) g_waitTimer = CreateWaitableTimerW(NULL, FALSE, NULL);
        DisableProcessWindowsGhosting();
        Log("CLHook loaded into pid %u (fps=%d windowed=%d timehook=%d fixed=%d dump=%d)", GetCurrentProcessId(),
            g_cfg.fpsTarget, g_cfg.windowed, g_cfg.timeHook, g_cfg.fixedStep, g_cfg.dumpImage);
    }
    return TRUE;
}
