// Minimal Direct3D 8 definitions needed by CLHook (no DirectX SDK required).
// Interfaces are used through raw vtables; indices follow d3d8.h.
#pragma once
#include <windows.h>

typedef DWORD D3DFORMAT;

enum {
    D3DFMT_UNKNOWN = 0,
    D3DFMT_R8G8B8 = 20,
    D3DFMT_A8R8G8B8 = 21,
    D3DFMT_X8R8G8B8 = 22,
    D3DFMT_R5G6B5 = 23,
    D3DFMT_X1R5G5B5 = 24,
    D3DFMT_A1R5G5B5 = 25,
    D3DFMT_A4R4G4B4 = 26,
};

struct D3DPRESENT_PARAMETERS8 {
    UINT BackBufferWidth;
    UINT BackBufferHeight;
    D3DFORMAT BackBufferFormat;
    UINT BackBufferCount;
    DWORD MultiSampleType;
    DWORD SwapEffect;
    HWND hDeviceWindow;
    BOOL Windowed;
    BOOL EnableAutoDepthStencil;
    D3DFORMAT AutoDepthStencilFormat;
    DWORD Flags;
    UINT FullScreen_RefreshRateInHz;
    UINT FullScreen_PresentationInterval;
};

struct D3DDISPLAYMODE8 {
    UINT Width;
    UINT Height;
    UINT RefreshRate;
    D3DFORMAT Format;
};

struct D3DSURFACE_DESC8 {
    D3DFORMAT Format;
    DWORD Type;
    DWORD Usage;
    DWORD Pool;
    UINT Size;
    DWORD MultiSampleType;
    UINT Width;
    UINT Height;
};

struct D3DLOCKED_RECT8 {
    INT Pitch;
    void* pBits;
};

struct D3DVIEWPORT8 {
    DWORD X, Y, Width, Height;
    float MinZ, MaxZ;
};

#define D3DPRESENT_INTERVAL_DEFAULT 0x00000000
#define D3DPRESENT_INTERVAL_ONE 0x00000001
#define D3DPRESENT_INTERVAL_IMMEDIATE 0x80000000
#define D3DPRESENTFLAG_LOCKABLE_BACKBUFFER 0x00000001
#define D3DSWAPEFFECT_DISCARD 1
#define D3DCREATE_PUREDEVICE 0x00000010
#define D3DPOOL_DEFAULT 0
#define D3DPOOL_MANAGED 1
#define D3DLOCK_READONLY 0x00000010
#define D3DSBT_ALL 1
#define D3DPT_TRIANGLELIST 4
#define D3DFVF_XYZRHW 0x004
#define D3DFVF_DIFFUSE 0x040
#define D3DFVF_TEX1 0x100

// render states (D3D8 numbering)
#define D3DRS_ZENABLE 7
#define D3DRS_FILLMODE 8
#define D3DRS_ZWRITEENABLE 14
#define D3DRS_ALPHATESTENABLE 15
#define D3DRS_SRCBLEND 19
#define D3DRS_DESTBLEND 20
#define D3DRS_CULLMODE 22
#define D3DRS_ALPHABLENDENABLE 27
#define D3DRS_FOGENABLE 28
#define D3DRS_SPECULARENABLE 29
#define D3DRS_STENCILENABLE 52
#define D3DRS_CLIPPING 136
#define D3DRS_LIGHTING 137
#define D3DRS_VERTEXBLEND 151
#define D3DRS_COLORWRITEENABLE 168
#define D3DBLEND_SRCALPHA 5
#define D3DBLEND_INVSRCALPHA 6
#define D3DCULL_NONE 1
#define D3DFILL_SOLID 3

// texture stage states (D3D8 numbering, includes sampler states)
#define D3DTSS_COLOROP 1
#define D3DTSS_COLORARG1 2
#define D3DTSS_COLORARG2 3
#define D3DTSS_ALPHAOP 4
#define D3DTSS_ALPHAARG1 5
#define D3DTSS_ALPHAARG2 6
#define D3DTSS_TEXCOORDINDEX 11
#define D3DTSS_ADDRESSU 13
#define D3DTSS_ADDRESSV 14
#define D3DTSS_MAGFILTER 16
#define D3DTSS_MINFILTER 17
#define D3DTSS_MIPFILTER 18
#define D3DTSS_TEXTURETRANSFORMFLAGS 24
#define D3DTOP_DISABLE 1
#define D3DTOP_SELECTARG1 2
#define D3DTOP_MODULATE 4
#define D3DTA_DIFFUSE 0
#define D3DTA_TEXTURE 2
#define D3DTADDRESS_CLAMP 3
#define D3DTEXF_NONE 0
#define D3DTEXF_POINT 1

// vtable indices
enum D3D8Index {
    IDX_D3D_GetAdapterDisplayMode = 8,
    IDX_D3D_CreateDevice = 15,

    IDX_DEV_Release = 2,
    IDX_DEV_Reset = 14,
    IDX_DEV_Present = 15,
    IDX_DEV_GetBackBuffer = 16,
    IDX_DEV_CreateTexture = 20,
    IDX_DEV_BeginScene = 34,
    IDX_DEV_EndScene = 35,
    IDX_DEV_SetTransform = 37,
    IDX_DEV_SetViewport = 40,
    IDX_DEV_GetViewport = 41,
    IDX_DEV_SetRenderState = 50,
    IDX_DEV_ApplyStateBlock = 54,
    IDX_DEV_DeleteStateBlock = 56,
    IDX_DEV_CreateStateBlock = 57,
    IDX_DEV_SetTexture = 61,
    IDX_DEV_SetTextureStageState = 63,
    IDX_DEV_DrawPrimitiveUP = 72,
    IDX_DEV_SetVertexShader = 76,
    IDX_DEV_SetPixelShader = 88,

    IDX_SURF_Release = 2,
    IDX_SURF_GetDesc = 8,
    IDX_SURF_LockRect = 9,
    IDX_SURF_UnlockRect = 10,

    IDX_TEX_Release = 2,
    IDX_TEX_LockRect = 16,
    IDX_TEX_UnlockRect = 17,
};

inline void** VT(void* obj) { return *(void***)obj; }
