# R6 — 참고 구현의 명령 검증기가 실제로 검사하는 것

작성 2026-09-15.  **사실 추출**이다 — 우리 검증기의 설계는 R6 계획서의 몫(PLAN R6 3 항).
codex 검토 없이 쓴 문서라 표는 `tools/oracle/r200_verifier.py` 가 FreeBSD `radeon_state.c` 에서
**파싱해 계산**한다: 상태 패킷 표 95 행, `radeon_drm.h` 의 emit id, 두 검사 switch 의 case 묶음,
검사하는 데이터 워드의 인덱스 식(`cmacro.py` 로 평가), 레지스터 값.  자체검사는 구조 불일치 0 과
음성 대조 3 종(표 행 삭제·case 삭제·검사 워드를 틀리게 바꾼 사본이 각각 잡힘)을 요구한다.

## 1. 구조

- 명령 버퍼는 최대 64 KiB, **먼저 커널로 통째로 복사한 뒤** 검사·방출한다
  (`radeon_state.c:2856-2875`) — 검사와 사용 사이 경합 방지.  PLAN R6 의 "입력 전체 스냅샷" 과 같다.
- 명령 종류 9 가지: 상태 패킷(id → 레지스터 묶음), 스칼라·벡터(TCL 색인 레지스터), 버퍼 폐기,
  패킷 3, 클립 사각형을 씌운 패킷 3, 스칼라 2, 대기, 선형 벡터(`radeon_state.c:2890` 이하 루프의 switch).
- 상태 패킷은 표의 첫 레지스터부터 `count` 워드를 `PACKET0` 하나로 내보낸다
  (`radeon_state.c:2590-2624`).

## 2. 계산으로 확인한 사실

1. **주소 레지스터를 범위에 포함하는 상태 패킷은 20 개이고, 그 주소 워드는 전부 검사된다**
   (생성표 A, 미검사 0).  주소 레지스터는 이름으로 57 개(두 계열은 검증기 자신의 인덱스 산술로 유도).
   `RB3D_ZMASKOFFSET` 을 범위에 넣는 상태 패킷은 없다.
2. **검사의 내용은 "FB 창 또는 GART 창 안인가" 하나뿐이다**(`radeon_drv.h:415-428`).  소유(다른
   클라이언트의 버퍼·앞 버퍼)도, 대상 크기(텍스처 크기×형식이 창을 넘는가)도 보지 않는다 — 시작 주소
   한 점.
3. 검사에 실패한 주소를 **고쳐서 받아들인다**: 0 기준 오프셋이면 클라이언트별 `radeon_fb_delta` 를
   더하고, FB 끝을 넘으면 GART 오프셋으로 간주해 옮긴 뒤 다시 검사한다(`radeon_state.c:42-91`).
4. **서로 다른 id 가 같은 레지스터를 쓴다**: 26 쌍(생성표 B).  예: `R200_EMIT_PP_TXCTLALL_n` 은
   `R200_EMIT_PP_TXFILTER_n`(6 워드) 과 `R200_EMIT_PP_CUBIC_FACES_n` 의 레지스터를 함께 쓴다.
   id 단위 허용 목록은 **레지스터 단위 정책과 같지 않다** — PLAN R6 이 "좁은 레지스터 및 비트 허용"
   을 요구하는 근거.
5. **패킷 3**(생성표 C): RV280(R200 microcode) 에서 받아들이는 opcode 중 `3D_DRAW_IMMD_2`·
   `3D_DRAW_VBUF_2`·`3D_DRAW_INDX_2`·`3D_CLEAR_HIZ` 는 **내용을 전혀 검사하지 않는다**.  R100 시절
   opcode `3D_DRAW_IMMD`/`VBUF`/`INDX`·`WAIT_FOR_IDLE`·`NOP`·`3D_CLEAR_ZMASK` 도 무검사로 통과한다.
   `3D_RNDR_GEN_INDX_PRIM` 은 R200 에서 거절(`radeon_state.c:152-305`).  PLAN R6 의 첫 판
   패킷 `3D_DRAW_IMMD_2` 는 참고 검증기에서 **길이 외에는 아무것도 검사받지 않는 패킷**이다.
6. 스칼라·스칼라 2·벡터 방출 함수는 **남은 버퍼 길이와 개수를 비교하지 않는다**
   (`radeon_state.c:2581-2643`).  선형 벡터만 비교한다(`radeon_state.c:2683-2707`).  Linux 3.10 의
   `radeon_emit_scalars` 도 같다(`radeon_state.c` Linux 판 2670–2686 행).  — 우리 검증기는 이 명령
   종류를 받지 않거나(첫 판은 TCL 우회) 모든 종류에 길이 대조를 둔다.

## 3. R6 계획서가 정할 것

| # | 사실 | 결정할 것 |
|---|---|---|
| 1 | 주소 검사가 창 한 점 | 소유 할당 전체 범위(시작+크기) 검사 — PLAN R6 3 항 그대로, 선례 없음을 명시 |
| 2 | 주소를 고쳐서 받는다 | 고치지 않고 거절 |
| 3 | id 끼리 레지스터가 겹친다 | id 가 아니라 레지스터·비트 단위 허용 표 |
| 4 | `3D_DRAW_IMMD_2` 무검사 | 정점 형식·정점 수·길이 교차 검사(PLAN) — 이 문서의 사실 5 가 근거 |
| 5 | 스칼라·벡터 길이 무검사 | 첫 판은 스칼라·벡터·선형 벡터 명령을 받지 않는다(TCL 우회) |

## 4. 생성표

<!-- BEGIN r200_verifier.py --markdown (generated; do not edit) -->
### 생성표 A — 상태 패킷 (RV280 이 받는 R200 microcode 경로)

범위 = 첫 레지스터부터 `count` 워드.  **검사** = `radeon_check_and_fixup_offset` 을 거치는 워드, **미검사 주소** = 범위 안에 주소 레지스터가 있는데 검사하지 않는 것.

| id | case | 범위 | 분류 | 검사하는 주소 | 미검사 주소 |
|---|---|---|---|---|---|
| 0 | `RADEON_EMIT_PP_MISC` | `1c14`–`1c2c` (7) | checked | `1c24` RADEON_RB3D_DEPTHOFFSET | — |
| 1 | `RADEON_EMIT_PP_CNTL` | `1c38`–`1c40` (3) | checked | `1c40` RADEON_RB3D_COLOROFFSET | — |
| 2 | `RADEON_EMIT_RB3D_COLORPITCH` | `1c48`–`1c48` (1) | no-offsets | — | — |
| 3 | `RADEON_EMIT_RE_LINE_PATTERN` | `1cd0`–`1cd4` (2) | no-offsets | — | — |
| 4 | `RADEON_EMIT_SE_LINE_WIDTH` | `1db8`–`1db8` (1) | no-offsets | — | — |
| 5 | `RADEON_EMIT_PP_LUM_MATRIX` | `1d00`–`1d00` (1) | no-offsets | — | — |
| 6 | `RADEON_EMIT_PP_ROT_MATRIX_0` | `1d58`–`1d5c` (2) | no-offsets | — | — |
| 7 | `RADEON_EMIT_RB3D_STENCILREFMASK` | `1d7c`–`1d84` (3) | no-offsets | — | — |
| 8 | `RADEON_EMIT_SE_VPORT_XSCALE` | `1d98`–`1dac` (6) | no-offsets | — | — |
| 9 | `RADEON_EMIT_SE_CNTL` | `1c4c`–`1c50` (2) | no-offsets | — | — |
| 10 | `RADEON_EMIT_SE_CNTL_STATUS` | `2140`–`2140` (1) | no-offsets | — | — |
| 11 | `RADEON_EMIT_RE_MISC` | `26c4`–`26c4` (1) | no-offsets | — | — |
| 12 | `RADEON_EMIT_PP_TXFILTER_0` | `1c54`–`1c68` (6) | checked | `1c5c` RADEON_PP_TXOFFSET_0 | — |
| 13 | `RADEON_EMIT_PP_BORDER_COLOR_0` | `1d40`–`1d40` (1) | no-offsets | — | — |
| 14 | `RADEON_EMIT_PP_TXFILTER_1` | `1c6c`–`1c80` (6) | checked | `1c74` RADEON_PP_TXOFFSET_1 (derived) | — |
| 15 | `RADEON_EMIT_PP_BORDER_COLOR_1` | `1d44`–`1d44` (1) | no-offsets | — | — |
| 16 | `RADEON_EMIT_PP_TXFILTER_2` | `1c84`–`1c98` (6) | checked | `1c8c` RADEON_PP_TXOFFSET_2 (derived) | — |
| 17 | `RADEON_EMIT_PP_BORDER_COLOR_2` | `1d48`–`1d48` (1) | no-offsets | — | — |
| 18 | `RADEON_EMIT_SE_ZBIAS_FACTOR` | `1db0`–`1db4` (2) | no-offsets | — | — |
| 19 | `RADEON_EMIT_SE_TCL_OUTPUT_VTX_FMT` | `2254`–`227c` (11) | no-offsets | — | — |
| 20 | `RADEON_EMIT_SE_TCL_MATERIAL_EMMISSIVE_RED` | `2210`–`2250` (17) | no-offsets | — | — |
| 21 | `R200_EMIT_PP_TXCBLEND_0` | `2f00`–`2f0c` (4) | no-offsets | — | — |
| 22 | `R200_EMIT_PP_TXCBLEND_1` | `2f10`–`2f1c` (4) | no-offsets | — | — |
| 23 | `R200_EMIT_PP_TXCBLEND_2` | `2f20`–`2f2c` (4) | no-offsets | — | — |
| 24 | `R200_EMIT_PP_TXCBLEND_3` | `2f30`–`2f3c` (4) | no-offsets | — | — |
| 25 | `R200_EMIT_PP_TXCBLEND_4` | `2f40`–`2f4c` (4) | no-offsets | — | — |
| 26 | `R200_EMIT_PP_TXCBLEND_5` | `2f50`–`2f5c` (4) | no-offsets | — | — |
| 27 | `R200_EMIT_PP_TXCBLEND_6` | `2f60`–`2f6c` (4) | no-offsets | — | — |
| 28 | `R200_EMIT_PP_TXCBLEND_7` | `2f70`–`2f7c` (4) | no-offsets | — | — |
| 29 | `R200_EMIT_TCL_LIGHT_MODEL_CTL_0` | `2268`–`227c` (6) | no-offsets | — | — |
| 30 | `R200_EMIT_TFACTOR_0` | `2ee0`–`2ef4` (6) | no-offsets | — | — |
| 31 | `R200_EMIT_VTX_FMT_0` | `2088`–`2094` (4) | no-offsets | — | — |
| 32 | `R200_EMIT_VAP_CTL` | `2080`–`2080` (1) | flush-then-emit | — | — |
| 33 | `R200_EMIT_MATRIX_SELECT_0` | `2230`–`2240` (5) | no-offsets | — | — |
| 34 | `R200_EMIT_TEX_PROC_CTL_2` | `22a8`–`22b8` (5) | no-offsets | — | — |
| 35 | `R200_EMIT_TCL_UCP_VERT_BLEND_CTL` | `22c0`–`22c0` (1) | no-offsets | — | — |
| 36 | `R200_EMIT_PP_TXFILTER_0` | `2c00`–`2c14` (6) | no-offsets | — | — |
| 37 | `R200_EMIT_PP_TXFILTER_1` | `2c20`–`2c34` (6) | no-offsets | — | — |
| 38 | `R200_EMIT_PP_TXFILTER_2` | `2c40`–`2c54` (6) | no-offsets | — | — |
| 39 | `R200_EMIT_PP_TXFILTER_3` | `2c60`–`2c74` (6) | no-offsets | — | — |
| 40 | `R200_EMIT_PP_TXFILTER_4` | `2c80`–`2c94` (6) | no-offsets | — | — |
| 41 | `R200_EMIT_PP_TXFILTER_5` | `2ca0`–`2cb4` (6) | no-offsets | — | — |
| 42 | `R200_EMIT_PP_TXOFFSET_0` | `2d00`–`2d00` (1) | checked | `2d00` R200_PP_TXOFFSET_0 | — |
| 43 | `R200_EMIT_PP_TXOFFSET_1` | `2d18`–`2d18` (1) | checked | `2d18` R200_PP_TXOFFSET_1 | — |
| 44 | `R200_EMIT_PP_TXOFFSET_2` | `2d30`–`2d30` (1) | checked | `2d30` R200_PP_TXOFFSET_2 | — |
| 45 | `R200_EMIT_PP_TXOFFSET_3` | `2d48`–`2d48` (1) | checked | `2d48` R200_PP_TXOFFSET_3 | — |
| 46 | `R200_EMIT_PP_TXOFFSET_4` | `2d60`–`2d60` (1) | checked | `2d60` R200_PP_TXOFFSET_4 | — |
| 47 | `R200_EMIT_PP_TXOFFSET_5` | `2d78`–`2d78` (1) | checked | `2d78` R200_PP_TXOFFSET_5 | — |
| 48 | `R200_EMIT_VTE_CNTL` | `20b0`–`20b0` (1) | no-offsets | — | — |
| 49 | `R200_EMIT_OUTPUT_VTX_COMP_SEL` | `2250`–`2250` (1) | no-offsets | — | — |
| 50 | `R200_EMIT_PP_TAM_DEBUG3` | `2d9c`–`2d9c` (1) | no-offsets | — | — |
| 51 | `R200_EMIT_PP_CNTL_X` | `2cc4`–`2cc4` (1) | no-offsets | — | — |
| 52 | `R200_EMIT_RB3D_DEPTHXY_OFFSET` | `1d60`–`1d60` (1) | no-offsets | — | — |
| 53 | `R200_EMIT_RE_AUX_SCISSOR_CNTL` | `26f0`–`26f0` (1) | no-offsets | — | — |
| 54 | `R200_EMIT_RE_SCISSOR_TL_0` | `1cd8`–`1cdc` (2) | no-offsets | — | — |
| 55 | `R200_EMIT_RE_SCISSOR_TL_1` | `1ce0`–`1ce4` (2) | no-offsets | — | — |
| 56 | `R200_EMIT_RE_SCISSOR_TL_2` | `1ce8`–`1cec` (2) | no-offsets | — | — |
| 57 | `R200_EMIT_SE_VAP_CNTL_STATUS` | `2140`–`2140` (1) | no-offsets | — | — |
| 58 | `R200_EMIT_SE_VTX_STATE_CNTL` | `2180`–`2180` (1) | no-offsets | — | — |
| 59 | `R200_EMIT_RE_POINTSIZE` | `2648`–`2648` (1) | no-offsets | — | — |
| 60 | `R200_EMIT_TCL_INPUT_VTX_VECTOR_ADDR_0` | `2254`–`2260` (4) | no-offsets | — | — |
| 61 | `R200_EMIT_PP_CUBIC_FACES_0` | `2c18`–`2c18` (1) | no-offsets | — | — |
| 62 | `R200_EMIT_PP_CUBIC_OFFSETS_0` | `2d04`–`2d14` (5) | checked | `2d04` R200_PP_CUBIC_OFFSET_F1_0, `2d08` R200_PP_CUBIC_OFFSET_F2_0, `2d0c` R200_PP_CUBIC_OFFSET_F3_0, `2d10` R200_PP_CUBIC_OFFSET_F4_0, `2d14` R200_PP_CUBIC_OFFSET_F5_0 | — |
| 63 | `R200_EMIT_PP_CUBIC_FACES_1` | `2c38`–`2c38` (1) | no-offsets | — | — |
| 64 | `R200_EMIT_PP_CUBIC_OFFSETS_1` | `2d1c`–`2d2c` (5) | checked | `2d1c` R200_PP_CUBIC_OFFSET_F1_1, `2d20` R200_PP_CUBIC_OFFSET_F2_1, `2d24` R200_PP_CUBIC_OFFSET_F3_1, `2d28` R200_PP_CUBIC_OFFSET_F4_1, `2d2c` R200_PP_CUBIC_OFFSET_F5_1 | — |
| 65 | `R200_EMIT_PP_CUBIC_FACES_2` | `2c58`–`2c58` (1) | no-offsets | — | — |
| 66 | `R200_EMIT_PP_CUBIC_OFFSETS_2` | `2d34`–`2d44` (5) | checked | `2d34` R200_PP_CUBIC_OFFSET_F1_2, `2d38` R200_PP_CUBIC_OFFSET_F2_2, `2d3c` R200_PP_CUBIC_OFFSET_F3_2, `2d40` R200_PP_CUBIC_OFFSET_F4_2, `2d44` R200_PP_CUBIC_OFFSET_F5_2 | — |
| 67 | `R200_EMIT_PP_CUBIC_FACES_3` | `2c78`–`2c78` (1) | no-offsets | — | — |
| 68 | `R200_EMIT_PP_CUBIC_OFFSETS_3` | `2d4c`–`2d5c` (5) | checked | `2d4c` R200_PP_CUBIC_OFFSET_F1_3, `2d50` R200_PP_CUBIC_OFFSET_F2_3, `2d54` R200_PP_CUBIC_OFFSET_F3_3, `2d58` R200_PP_CUBIC_OFFSET_F4_3, `2d5c` R200_PP_CUBIC_OFFSET_F5_3 | — |
| 69 | `R200_EMIT_PP_CUBIC_FACES_4` | `2c98`–`2c98` (1) | no-offsets | — | — |
| 70 | `R200_EMIT_PP_CUBIC_OFFSETS_4` | `2d64`–`2d74` (5) | checked | `2d64` R200_PP_CUBIC_OFFSET_F1_4, `2d68` R200_PP_CUBIC_OFFSET_F2_4, `2d6c` R200_PP_CUBIC_OFFSET_F3_4, `2d70` R200_PP_CUBIC_OFFSET_F4_4, `2d74` R200_PP_CUBIC_OFFSET_F5_4 | — |
| 71 | `R200_EMIT_PP_CUBIC_FACES_5` | `2cb8`–`2cb8` (1) | no-offsets | — | — |
| 72 | `R200_EMIT_PP_CUBIC_OFFSETS_5` | `2d7c`–`2d8c` (5) | checked | `2d7c` R200_PP_CUBIC_OFFSET_F1_5, `2d80` R200_PP_CUBIC_OFFSET_F2_5, `2d84` R200_PP_CUBIC_OFFSET_F3_5, `2d88` R200_PP_CUBIC_OFFSET_F4_5, `2d8c` R200_PP_CUBIC_OFFSET_F5_5 | — |
| 73 | `RADEON_EMIT_PP_TEX_SIZE_0` | `1d04`–`1d08` (2) | no-offsets | — | — |
| 74 | `RADEON_EMIT_PP_TEX_SIZE_1` | `1d0c`–`1d10` (2) | no-offsets | — | — |
| 75 | `RADEON_EMIT_PP_TEX_SIZE_2` | `1d14`–`1d18` (2) | no-offsets | — | — |
| 76 | `R200_EMIT_RB3D_BLENDCOLOR` | `3218`–`3220` (3) | no-offsets | — | — |
| 77 | `R200_EMIT_TCL_POINT_SPRITE_CNTL` | `22c4`–`22c4` (1) | no-offsets | — | — |
| 78 | `RADEON_EMIT_PP_CUBIC_FACES_0` | `1d24`–`1d24` (1) | no-offsets | — | — |
| 79 | `RADEON_EMIT_PP_CUBIC_OFFSETS_T0` | `1dd0`–`1de0` (5) | checked | `1dd0` RADEON_PP_CUBIC_OFFSET_T0_0, `1dd4` RADEON_PP_CUBIC_OFFSET_T0_1 (derived), `1dd8` RADEON_PP_CUBIC_OFFSET_T0_2 (derived), `1ddc` RADEON_PP_CUBIC_OFFSET_T0_3 (derived), `1de0` RADEON_PP_CUBIC_OFFSET_T0_4 (derived) | — |
| 80 | `RADEON_EMIT_PP_CUBIC_FACES_1` | `1d28`–`1d28` (1) | no-offsets | — | — |
| 81 | `RADEON_EMIT_PP_CUBIC_OFFSETS_T1` | `1e00`–`1e10` (5) | checked | `1e00` RADEON_PP_CUBIC_OFFSET_T1_0, `1e04` RADEON_PP_CUBIC_OFFSET_T1_1 (derived), `1e08` RADEON_PP_CUBIC_OFFSET_T1_2 (derived), `1e0c` RADEON_PP_CUBIC_OFFSET_T1_3 (derived), `1e10` RADEON_PP_CUBIC_OFFSET_T1_4 (derived) | — |
| 82 | `RADEON_EMIT_PP_CUBIC_FACES_2` | `1d2c`–`1d2c` (1) | no-offsets | — | — |
| 83 | `RADEON_EMIT_PP_CUBIC_OFFSETS_T2` | `1e14`–`1e24` (5) | checked | `1e14` RADEON_PP_CUBIC_OFFSET_T2_0, `1e18` RADEON_PP_CUBIC_OFFSET_T2_1 (derived), `1e1c` RADEON_PP_CUBIC_OFFSET_T2_2 (derived), `1e20` RADEON_PP_CUBIC_OFFSET_T2_3 (derived), `1e24` RADEON_PP_CUBIC_OFFSET_T2_4 (derived) | — |
| 84 | `R200_EMIT_PP_TRI_PERF_CNTL` | `2cf8`–`2cfc` (2) | no-offsets | — | — |
| 85 | `R200_EMIT_PP_AFS_0` | `2f80`–`2ffc` (32) | no-offsets | — | — |
| 86 | `R200_EMIT_PP_AFS_1` | `2f00`–`2f7c` (32) | no-offsets | — | — |
| 87 | `R200_EMIT_ATF_TFACTOR` | `2ee0`–`2efc` (8) | no-offsets | — | — |
| 88 | `R200_EMIT_PP_TXCTLALL_0` | `2c00`–`2c1c` (8) | no-offsets | — | — |
| 89 | `R200_EMIT_PP_TXCTLALL_1` | `2c20`–`2c3c` (8) | no-offsets | — | — |
| 90 | `R200_EMIT_PP_TXCTLALL_2` | `2c40`–`2c5c` (8) | no-offsets | — | — |
| 91 | `R200_EMIT_PP_TXCTLALL_3` | `2c60`–`2c7c` (8) | no-offsets | — | — |
| 92 | `R200_EMIT_PP_TXCTLALL_4` | `2c80`–`2c9c` (8) | no-offsets | — | — |
| 93 | `R200_EMIT_PP_TXCTLALL_5` | `2ca0`–`2cbc` (8) | no-offsets | — | — |
| 94 | `R200_EMIT_VAP_PVS_CNTL` | `22d0`–`22d4` (2) | no-offsets | — | — |

### 생성표 B — 같은 레지스터를 쓰는 패킷 쌍

| 패킷 | 패킷 | 겹치는 레지스터 |
|---|---|---|
| `RADEON_EMIT_SE_CNTL_STATUS` | `R200_EMIT_SE_VAP_CNTL_STATUS` | `2140` |
| `RADEON_EMIT_SE_TCL_OUTPUT_VTX_FMT` | `R200_EMIT_TCL_LIGHT_MODEL_CTL_0` | `2268` `226c` `2270` `2274` `2278` `227c` |
| `RADEON_EMIT_SE_TCL_OUTPUT_VTX_FMT` | `R200_EMIT_TCL_INPUT_VTX_VECTOR_ADDR_0` | `2254` `2258` `225c` `2260` |
| `RADEON_EMIT_SE_TCL_MATERIAL_EMMISSIVE_RED` | `R200_EMIT_MATRIX_SELECT_0` | `2230` `2234` `2238` `223c` `2240` |
| `RADEON_EMIT_SE_TCL_MATERIAL_EMMISSIVE_RED` | `R200_EMIT_OUTPUT_VTX_COMP_SEL` | `2250` |
| `R200_EMIT_PP_TXCBLEND_0` | `R200_EMIT_PP_AFS_1` | `2f00` `2f04` `2f08` `2f0c` |
| `R200_EMIT_PP_TXCBLEND_1` | `R200_EMIT_PP_AFS_1` | `2f10` `2f14` `2f18` `2f1c` |
| `R200_EMIT_PP_TXCBLEND_2` | `R200_EMIT_PP_AFS_1` | `2f20` `2f24` `2f28` `2f2c` |
| `R200_EMIT_PP_TXCBLEND_3` | `R200_EMIT_PP_AFS_1` | `2f30` `2f34` `2f38` `2f3c` |
| `R200_EMIT_PP_TXCBLEND_4` | `R200_EMIT_PP_AFS_1` | `2f40` `2f44` `2f48` `2f4c` |
| `R200_EMIT_PP_TXCBLEND_5` | `R200_EMIT_PP_AFS_1` | `2f50` `2f54` `2f58` `2f5c` |
| `R200_EMIT_PP_TXCBLEND_6` | `R200_EMIT_PP_AFS_1` | `2f60` `2f64` `2f68` `2f6c` |
| `R200_EMIT_PP_TXCBLEND_7` | `R200_EMIT_PP_AFS_1` | `2f70` `2f74` `2f78` `2f7c` |
| `R200_EMIT_TFACTOR_0` | `R200_EMIT_ATF_TFACTOR` | `2ee0` `2ee4` `2ee8` `2eec` `2ef0` `2ef4` |
| `R200_EMIT_PP_TXFILTER_0` | `R200_EMIT_PP_TXCTLALL_0` | `2c00` `2c04` `2c08` `2c0c` `2c10` `2c14` |
| `R200_EMIT_PP_TXFILTER_1` | `R200_EMIT_PP_TXCTLALL_1` | `2c20` `2c24` `2c28` `2c2c` `2c30` `2c34` |
| `R200_EMIT_PP_TXFILTER_2` | `R200_EMIT_PP_TXCTLALL_2` | `2c40` `2c44` `2c48` `2c4c` `2c50` `2c54` |
| `R200_EMIT_PP_TXFILTER_3` | `R200_EMIT_PP_TXCTLALL_3` | `2c60` `2c64` `2c68` `2c6c` `2c70` `2c74` |
| `R200_EMIT_PP_TXFILTER_4` | `R200_EMIT_PP_TXCTLALL_4` | `2c80` `2c84` `2c88` `2c8c` `2c90` `2c94` |
| `R200_EMIT_PP_TXFILTER_5` | `R200_EMIT_PP_TXCTLALL_5` | `2ca0` `2ca4` `2ca8` `2cac` `2cb0` `2cb4` |
| `R200_EMIT_PP_CUBIC_FACES_0` | `R200_EMIT_PP_TXCTLALL_0` | `2c18` |
| `R200_EMIT_PP_CUBIC_FACES_1` | `R200_EMIT_PP_TXCTLALL_1` | `2c38` |
| `R200_EMIT_PP_CUBIC_FACES_2` | `R200_EMIT_PP_TXCTLALL_2` | `2c58` |
| `R200_EMIT_PP_CUBIC_FACES_3` | `R200_EMIT_PP_TXCTLALL_3` | `2c78` |
| `R200_EMIT_PP_CUBIC_FACES_4` | `R200_EMIT_PP_TXCTLALL_4` | `2c98` |
| `R200_EMIT_PP_CUBIC_FACES_5` | `R200_EMIT_PP_TXCTLALL_5` | `2cb8` |

### 생성표 C — 패킷 3 허용 목록 (`radeon_check_and_fixup_packet3`)

| opcode | 값 | 처리 |
|---|---|---|
| `RADEON_3D_DRAW_IMMD` | `0x00002900` | accepted |
| `RADEON_3D_DRAW_VBUF` | `0x00002800` | accepted |
| `RADEON_3D_DRAW_INDX` | `0x00002a00` | accepted |
| `RADEON_WAIT_FOR_IDLE` | `0x00002600` | accepted |
| `RADEON_CP_NOP` | `0x00001000` | accepted |
| `RADEON_3D_CLEAR_ZMASK` | `0x00003200` | accepted |
| `RADEON_CP_3D_DRAW_IMMD_2` | `0x00003500` | R200 microcode only |
| `RADEON_CP_3D_DRAW_VBUF_2` | `0x00003400` | R200 microcode only |
| `RADEON_CP_3D_DRAW_INDX_2` | `0x00003600` | R200 microcode only |
| `RADEON_3D_CLEAR_HIZ` | `0x00003700` | R200 microcode only |
| `RADEON_3D_LOAD_VBPNTR` | `0x00002f00` | accepted; address words checked; count <= 18 |
| `RADEON_3D_RNDR_GEN_INDX_PRIM` | `0x00002300` | R100 microcode only (refused on RV280); address words checked |
| `RADEON_CP_INDX_BUFFER` | `0x00003300` | R200 microcode only; address words checked; register word must be 0x80000810 |
| `RADEON_CNTL_HOSTDATA_BLT` | `0x00009400` | accepted; address words checked |
| `RADEON_CNTL_PAINT_MULTI` | `0x00009a00` | accepted; address words checked |
| `RADEON_CNTL_BITBLT_MULTI` | `0x00009b00` | accepted; address words checked |
<!-- END r200_verifier.py -->
