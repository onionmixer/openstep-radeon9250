# R6 — R200 깊이 지우기 사각형: 창 좌표 3D 의 유일한 선례

작성 2026-09-15.  **사실 추출**이다 — 정점 계약의 확정은 R6 계획서의 몫(PLAN R6 1 항).
codex 검토 없이 쓴 문서라 워드열은 `tools/oracle/r200_clear_oracle.py` 가 낸다.  그 자체검사는
FreeBSD `radeon_state.c` 의 해당 분기에서 **상태 레지스터 순서·`BEGIN_RING` 크기·정점 필드 순서·
W 리터럴·`SE_VAP_CNTL` 상수를 파싱해** 오라클과 대조하고(순서를 바꾼 음성 대조 포함), 부동소수 비트는
`struct` 로 계산한다.

## 1. 선례가 정확히 하는 일

`radeon_cp_dispatch_clear` 의 R200 깊이·스텐실 분기(`radeon_state.c:1106-1229`):

1. 2D 유휴 대기(`WAIT_UNTIL` 2D·HOST idleclean) + 레지스터 12 개를 `PACKET0` 한 쌍씩(합 26 워드).
   `PP_CNTL`=0(텍스처 끔), `RE_CNTL`=0, `RB3D_CNTL`(평면 마스크 사용·색 형식·깊이/스텐실 켬),
   `RB3D_ZSTENCILCNTL`(항상 통과·깊이 쓰기), `RB3D_STENCILREFMASK`, **`RB3D_PLANEMASK`=0**,
   `SE_CNTL`, `SE_VTE_CNTL`=`XY_FMT|Z_FMT`(뷰포트 변환 끔), `SE_VTX_FMT_0`=`Z0|W0`,
   `SE_VTX_FMT_1`=0, `SE_VAP_CNTL`=`9 << 18`(TCL 끔, `FORCE_W_TO_ONE` 는 **주석 처리**),
   `RE_AUX_SCISSOR_CNTL`=0.
2. 상자마다: `RE_TOP_LEFT`=`y1<<16|x1`, `RE_WIDTH_HEIGHT`=`(y2−1)<<16|(x2−1)`(끝 포함) — 소스 주석
   "Funny that this should be required"(`radeon_emit_clip_rect`).
3. 상자마다 `3D_DRAW_IMMD_2`(패킷 3, 13 워드 페이로드): `VF_CNTL` = `RECT_LIST|WALK_RING|3 정점`,
   정점 3 개 × (x, y, z, w) 부동소수, 순서 (x1,y1) (x1,y2) (x2,y2), **w = 1.0f(`0x3f800000`)**.
4. 클라이언트(Mesa 6.5.3 `r200_ioctl.c` 767–771 행): x·y 는 클립 사각형 정수 좌표를 `float` 로,
   z 는 `ctx->Depth.Clear`(0..1).  `SE_CNTL` 의 픽셀 규약은 `VTX_PIX_CENTER_OGL | ROUND_MODE_TRUNC |
   ROUND_PREC_8TH_PIX`(`radeon_cp.c` 초기화의 고정값).

## 2. PLAN R6 정점 계약과 대조

| PLAN R6 1 항 | 선례 | 판정 |
|---|---|---|
| TCL·정점셰이더 끔 | `SE_VAP_CNTL` = 9<<18 만(다른 비트 0) | 선례 있음 |
| `SE_VTE_CNTL` 뷰포트 6 비트 끄고 `XY_FMT|Z_FMT` | 정확히 `0x300` | 선례 있음 |
| `SE_VTX_FMT_0 = Z0|W0|PK_RGBA` | 선례는 `Z0|W0` 만(**색 없음**).  `R200_VTX_PK_RGBA` 는 비트가 아니라 **2 비트 색 필드의 값 1**이고 색 0 필드는 bit 11(`R200_VTX_COLOR_0_SHIFT`, Mesa `r200_reg.h` 388·392 행) → 색 0 을 넣으면 `1 << 11` | **색 있는 정점은 선례 밖** — 계획서의 표기를 `(R200_VTX_PK_RGBA << R200_VTX_COLOR_0_SHIFT)` 로 고칠 것, 정점 워드 순서도 선례에 없음 |
| W 는 1.0 | 세 정점 모두 리터럴 `0x3f800000` | 선례 있음 |
| 목적지 오프셋·피치·플레인 마스크·시저·`SE_CNTL` 을 매 제출 명시 | 선례는 **색 버퍼를 쓰지 않는다**(`PLANEMASK`=0) — 색 목적지 오프셋·피치는 이 분기에 없음 | 색 쓰기는 선례 밖 |
| 좌표 원점 | 선례 x·y 는 DRI 클립 사각형 좌표.  원점 방향은 이 코드로 **미확인** | R6 분수 좌표 커버리지 시험이 정한다(PLAN) |
| 원시 형식 | 선례는 `RECT_LIST`(3 정점) | 삼각형 목록은 `RADEON_PRIM_TYPE_TRI_LIST`(`radeon_drv.h:1203`) — 형식 값만 있고 이 경로의 선례는 없음 |

## 3. 생성표

<!-- BEGIN r200_clear_oracle.py --markdown (generated; do not edit) -->
### 생성표 — 32 bpp·24 비트 깊이, 깊이만 지움, 상자 (10,20)-(110,70), 깊이 0.5

원천: `radeon_state.c` 1124–1247 행(이 도구가 레지스터 순서와 `BEGIN_RING` 크기를 대조).

```
# state (BEGIN_RING 26)
  0x000005c8  PACKET0(RADEON_WAIT_UNTIL)
  0x00050000  
  0x0000070e  PACKET0(RADEON_PP_CNTL)
  0x00000000  
  0x00000714  PACKET0(R200_RE_CNTL)
  0x00000000  
  0x0000070f  PACKET0(RADEON_RB3D_CNTL)
  0x00001902  
  0x0000070b  PACKET0(RADEON_RB3D_ZSTENCILCNTL)
  0x42227072  
  0x0000075f  PACKET0(RADEON_RB3D_STENCILREFMASK)
  0x00000000  
  0x00000761  PACKET0(RADEON_RB3D_PLANEMASK)
  0x00000000  
  0x00000713  PACKET0(RADEON_SE_CNTL)
  0x480055de  
  0x0000082c  PACKET0(R200_SE_VTE_CNTL)
  0x00000300  
  0x00000822  PACKET0(R200_SE_VTX_FMT_0)
  0x00000003  
  0x00000823  PACKET0(R200_SE_VTX_FMT_1)
  0x00000000  
  0x00000820  PACKET0(R200_SE_VAP_CNTL)
  0x00240000  
  0x000009bc  PACKET0(R200_RE_AUX_SCISSOR_CNTL)
  0x00000000  
# clip rect (BEGIN_RING 4)
  0x000009b0  PACKET0(RADEON_RE_TOP_LEFT)
  0x0014000a  
  0x00000711  PACKET0(RADEON_RE_WIDTH_HEIGHT)
  0x0045006d  
# 3D_DRAW_IMMD_2 (BEGIN_RING 14)
  0xc00c3500  
  0x00030038  
  0x41200000  x = 10
  0x41a00000  y = 20
  0x3f000000  z = 0.5
  0x3f800000  w = 1
  0x41200000  x = 10
  0x428c0000  y = 70
  0x3f000000  z = 0.5
  0x3f800000  w = 1
  0x42dc0000  x = 110
  0x428c0000  y = 70
  0x3f000000  z = 0.5
  0x3f800000  w = 1
```
<!-- END r200_clear_oracle.py -->
