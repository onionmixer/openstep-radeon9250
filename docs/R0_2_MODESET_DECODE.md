# R0-2 — RV280 레거시 모드셋 해독과 첫 점등 시퀀스 초안

작성 2026-09-15.  **하드웨어 무접촉 문서**다.  1–3 절은 참고 소스에서 읽은
사실(인용은 `tools/oracle/check_citations.py docs/R0_2_MODESET_DECODE.md` 로 대조),
4 절은 **설계 초안**이라 R2 계획서와 교차검토를 거쳐야 코드가 된다.  실기로
확인한 것은 없다.

사실 전반은 `ANALYSIS.md`, 레지스터 오프셋은 그 문서 12 절 표가 정본이다.

## 1. radeonfb 가 POST 된 카드에서 하는 일 (attach 순서)

| 순서 | 동작 | 쓰는 레지스터 | 출처 |
|---|---|---|---|
| 1 | 스크래치 레지스터 쓰기·읽기·복원 시험 | `BIOS_0_SCRATCH` | `radeonfb.c:570-574` |
| 2 | ROM 매핑, 필요하면 ROM 을 켜서 읽고 되돌림 | `SEPROM_CNTL1`, `VIPH_CONTROL`, `BUS_CNTL`, CRTC 요청·표시 비트 | `radeonfb.c:1395-1438` |
| 3 | 클럭 기준값(BIOS 또는 기본값) | `PPLL_REF_DIV` 읽기(인덱스 쓰기) | `radeonfb.c:1697-1714` |
| 4 | 연결기·TMDS 표 | 없음(BIOS 파싱) | `radeonfb.c:640-657` |
| 5 | MC 맵 설정 | CRTC 표시·요청 차단, `MC_FB/AGP_LOCATION`, `HOST_PATH_CNTL`=0, `DISPLAY_BASE_ADDR`, `OV0_BASE_ADDR`, 100 ms 전후 | `radeonfb.c:2843-2921` |
| 6 | 버스·RBBM·인터럽트 기본값 | `BUS_CNTL`(BUS_MASTER_DIS), `BUS_CNTL1`, `FCP_CNTL`, `RBBM_CNTL`, `AGP_CNTL`, `HOST_PATH_CNTL`=0, `GEN_INT_CNTL`=0, `GEN_INT_STATUS` ack | `radeonfb.c:2922-2955` |
| 7 | DAC 배선: 포트별 `DAC_CNTL2.DAC_CLK_SEL`, TV DAC 이면 `DISP_HW_DEBUG`·`DISP_OUTPUT_CNTL` | `DAC_CNTL2` 외 | `radeonfb.c:669-695` |
| 8 | FP/TMDS 소스 선택 | `FP_GEN_CNTL`, `FP2_GEN_CNTL` | `radeonfb.c:717-756` |
| 9 | `DAC_CNTL` = 기존의 범위·블랭킹 비트 + `MASK_ALL` + `8BIT_EN` | `DAC_CNTL` | `radeonfb.c:758-764` |
| 10 | `TV_DAC_CNTL` = 매직값("may need more investigation"), TMDS 켬 | `TV_DAC_CNTL`, `FP_GEN_CNTL` | `radeonfb.c:762-769` |
| 11 | 모드 전환: 오버레이·캡처·I²C·인터럽트 끔 → CRTC 별 `setcrtc` → 언블랭크 | 아래 2 절 | `radeonfb.c:2352-2383` |
| 12 | 2D 엔진 초기화 | `ANALYSIS.md` 8 절 | `radeonfb.c:946-947` |
| 13 | 화면 지우기(엔진 채우기) | 엔진 | `radeonfb.c:977-978` |
| 14 | 언블랭크, 팔레트 | `CRTC_EXT_CNTL`, `FP_GEN_CNTL`, 팔레트 | `radeonfb.c:1048`, `:1063-1064` |

## 2. `radeonfb_setcrtc` (CRTC1) 레지스터 단위

1. `CRTC_GEN_CNTL` = 형식 코드<<8 | `EXT_DISP_EN` | `CRTC_EN` (+ 이중주사·인터레이스·
   복합 sync 플래그) — **통째로 쓴다**(`radeonfb.c:2462-2482`).
2. `CRTC_EXT_CNTL`: 기존 값에서 `DISPLAY_DIS` 만 남기고 `XCRT_CNT_EN | VGA_ATI_LINEAR`,
   `CRT_ON` 을 세운다(`radeonfb.c:2501-2510`).
3. 현재 해상도가 다르면 타이밍 4 워드 + FP 섀도 워드(`radeonfb.c:2465-2523`).
4. `radeonfb_program_vclk`(`ANALYSIS.md` 5 절).
5. `CRTC_OFFSET`=0, `CRTC_OFFSET_CNTL`=0, `CRTC_PITCH`, `DISP_MERGE_CNTL` 의
   `RGB_OFFSET_EN` 해제, `CRTC_EXT_CNTL` 의 sync·표시 비활성 해제,
   `CRTC_GEN_CNTL.DISP_REQ_EN_B` 해제(`radeonfb.c:2580-2594`).
6. 내부 TMDS 포트면 TMDS PLL(`radeonfb.c:2609-2633`).

피치: radeonfb 는 `rd_stride / rd_bpp`(`radeonfb.c:2438`), stride 는 64 바이트 정렬
(`radeonfb.c:919-920`).  1024×768×32 → stride 4096 → 피치 128.

## 3. xf86-video-ati 와의 차이 (설계 결정 대상)

| 항목 | radeonfb | xf86 | 비고 |
|---|---|---|---|
| 분주 슬롯 | `PPLL_DIV_0`, `PLL_DIV_SEL`=0 | `PPLL_DIV_3`, `PLL_DIV_SEL`=3 | `radeonfb.c:2237-2238`, `legacy_crtc.c:348-380` |
| 원자 갱신 대기 | 비트가 설 때까지(사실상 무대기) | 비트가 내려갈 때까지, 상한 10000 | `radeonfb.c:2150-2166`, `legacy_crtc.c:214-226` |
| PLL 이득(PVG) | 안 씀 | `RADEONComputePLLGain` 값을 `PPLL_CNTL` 에 | `legacy_crtc.c:331-343` |
| `HTOTAL_CNTL` | 0 | `HTotal & 7` | `radeonfb.c:2101-2270`, `legacy_crtc.c:1269` |
| `HOST_PATH_CNTL` | 0 으로 씀 | RV280 에서 `HDP_APER_CNTL` 세움 | `radeonfb.c:2889`, `radeon_driver.c:1694-1704` |
| MC 맵 | 항상 씀 | 값이 바뀔 때만 | `radeon_driver.c:4076-4081` |
| 피치 레지스터 | 하위 워드만 | `pitch | pitch<<16` | `legacy_crtc.c:954-958` |
| TV DAC | 매직값 | 저장된 값 보존/출력별 계산 | `radeonfb.c:762-769` |

1024×768 은 `HTotal = 1344`, `1344 & 7 = 0` 이라 `HTOTAL_CNTL` 차이는 이 모드에서
값으로 드러나지 않는다(오라클 `MODES` 의 htotal 800·1056·1344·1688·2160 모두 8 의
배수 — `python3 -c "print([h%8 for h in (800,1056,1344,1688,2160)])"` → 전부 0).

## 4. 첫 점등 시퀀스 초안 — **검토 전 설계**

원칙: **BIOS 가 둔 상태에서 바꿔야 하는 것만 바꾼다.**  주 VGA 로 POST 된 카드는
이미 CRTC1 → 주 DAC → VGA 커넥터 경로가 살아 있고(VGA 텍스트가 화면에 나오고 있으니),
첫 판에 필요한 변경은 형식·타이밍·클럭·스캔아웃 주소다.  배선은 R1 스냅샷과 같게
두되, **비활성 출력(CRTC2·FP/TMDS·TV DAC)은 "안 건드림" 이 아니라 "비활성임을 확인하고
아니면 진입 중단"** 이다(Q5 4c).  이 원칙은 xf86 의 "MC 맵은 바뀔 때만" 과 같은
방향이지만 **참고 구현이 이렇게 최소 변경만 한 선례는 없다** `[미검증 설계]`.

| # | 단계 | 쓰기 조건 | 대기(상한) | 되읽기 판정 |
|---|---|---|---|---|
| 0 | 스냅샷(R0-3 목록) — 인덱스 레지스터 읽기 포함, 이 시점부터 드라이버 소유 | 항상 | — | 스냅샷 유효 플래그 |
| 1 | 블랭크: `CRTC_EXT_CNTL |= DISPLAY_DIS` | 항상 | — | 가능 |
| 2 | 메모리 요청 차단: `CRTC_GEN_CNTL |= DISP_REQ_EN_B`, CRTC2 도 켜져 있으면 | 항상 | 100 ms 고정 | 가능 |
| 3 | 엔진 유휴 확인(`RBBM_STATUS` ACTIVE 0) — CP 는 R1 스냅샷에서 꺼져 있어야 함 | CP 켜져 있으면 **중단**(R5 전까지 CP 를 다룰 코드 없음) | 절대 기한.  초과 시 순서: **실패를 RAM 에 기록(추가 GPU 읽기 없이) → 영구 걸쇠 → 복원** | — |
| 4 | MC 맵: 목표값 = RV280 정렬 적용 계산값 | **스냅샷과 다를 때만**, AGP 먼저 치움 | 전후 100 ms | 가능 |
| 5 | `CRTC_GEN_CNTL` 형식 6(32bpp)·`EXT_DISP_EN`·`CRTC_EN` (+`DISP_REQ_EN_B` 유지) | 항상 | — | 가능 |
| 6 | `CRTC_EXT_CNTL`: 읽고 `XCRT_CNT_EN | VGA_ATI_LINEAR | CRTC_CRT_ON` 을 **더한다**(`DISPLAY_DIS` 유지).  새 값으로 덮어 `CRT_ON` 을 잃으면 주 CRT 가 꺼진다 — 두 참고 모두 세운다(`radeonfb.c:2500-2516`) | 항상 | — | 가능 |
| 7 | 타이밍 4 워드 = 오라클 값 | 항상 | — | 가능 |
| 8 | PPLL 전이(xf86 의미의 대기) — **`PPLL_DIV_3` 에 쓰고 `PLL_DIV_SEL`=3**, `DIV_0..2` 불가침(5 절 1 결정안) | 목표 분주가 현재와 다를 때 | 요청 전·후 대기 절대 기한, 50 ms | 분주 레지스터만 |
| 8b | 픽셀 클럭 게이트 해제(`VCLK_ECP_CNTL` 의 `PIXCLK_ALWAYS_ONb`·`PIXCLK_DAC_ALWAYS_ONb`) — radeonfb 가 PLL 전이 뒤에 한다(`radeonfb.c:2101-2270`) | 항상 | — | 가능 |
| 9 | `CRTC_OFFSET`=0, `CRTC_OFFSET_CNTL`=0, `CRTC_PITCH`=128, `DISP_MERGE_CNTL.RGB_OFFSET_EN` 해제 | 항상 | — | 가능 |
| 10 | `SURFACE_CNTL` 에 타일링·변환이 켜져 있으면 해제 | 스냅샷이 0 이 아닐 때 | — | 가능 |
| 11 | `DAC_CNTL |= MASK_ALL | 8BIT_EN`(범위·블랭킹 비트 보존) | 스냅샷과 다를 때 | — | 가능 |
| 11b | DAC 전원·FIFO·센터링: `DAC_CNTL.DAC_PDWN`/`DAC_MACRO_CNTL` RGB 전원, `GRPH_BUFFER_CNTL`, `CRTC_MORE_CNTL` — **xf86 만** 다루고 radeonfb 는 쓰지 않는다(`CRTC_MORE_CNTL` 은 출력만).  R1 값으로 R2 계획에서 결정 | R1 결과 뒤 | — | — |
| 12 | 팔레트 선형 램프(`VCLK_ECP_CNTL` 게이트·`DAC2_PALETTE_ACC_CTL` 프로토콜) | 항상 | — | 표본 몇 개 |
| 12b | 방해 가능 클라이언트 0: `OVR_CLR`, `OVR_WID_*`, `OV0_SCALE_CNTL`, `SUBPIC_CNTL`, `VIPH_CONTROL`, `I2C_CNTL_1`, `GEN_INT_CNTL`, `CAP0/1_TRIG_CNTL` — radeonfb 가 모드 전환 전에 한다(`radeonfb.c:2352-2383`), 스냅샷에 넣어 복원 | 항상 | — | 가능 |
| 13 | 요청 차단 해제, sync·표시 해제 = 언블랭크 | 항상 | — | 가능 |
| 14 | FB clear: `mapFrameBufferAtPhysicalAddress:` 매핑으로 1024×768×4 바이트 | 매핑 길이 ≤ 보고 VRAM·애퍼처 | — | 표본 |

오라클 값(1024×768@60, 기본 클럭 가정 — **실제 refdiv 는 R1 스냅샷의 `PPLL_REF_DIV`**):
`H_TOTAL_DISP=0x007f00a7`, `H_SYNC_STRT_WID=0x00910410`, `V_TOTAL_DISP=0x02ff0325`,
`V_SYNC_STRT_WID=0x00860302`, PPLL 분주 워드 `0x000600ad`.
(`python3 tools/oracle/radeon_modeset.py` 출력 그대로.)

## 5. 열린 질문 (R1 결과 또는 검토로 닫는다)

1. **분주 슬롯 — 결정안: `DIV_3`**(Q5 5).  VGA `MISC` 클럭 선택과 `PPLL_DIV_n` 의 대응은
   소스로 미확인이지만, xf86 방식(DIV3 사용·DIV0–2 보존·복귀 시 PPLL 공통 상태·DIV3·
   `VCLK_ECP_CNTL` 복원 후 `CLOCK_CNTL_INDEX` 복원)은 VGA 가 고정 클럭을 쓰든 PPLL 슬롯을
   쓰든 안전하다.  `radeon_reg.h` 는 r128 에서 변환해 틀린 정의가 섞였다고 스스로 경고하므로
   비트 정의는 radeonfb 헤더와 대조해 쓴다.  R1 은 콘솔의 `PLL_DIV_SEL` 을 기록한다.
2. **PLL 이득(PVG)**: xf86 은 쓰고 radeonfb 는 안 쓴다.  닫는 조건: 두 구현의 RV280
   동작 기록, 또는 BIOS 가 둔 `PPLL_CNTL` 값을 보존하는 방식 채택.
3. **`HOST_PATH_CNTL`**: 두 참고가 반대로 쓴다.  첫 판은 **스냅샷 값 보존**을 제안.
4. **최소 변경 원칙 자체**(4 절): 선례 없음.  교차검토 질문으로 보낸다.
5. 3 단계의 CP 상태: BIOS 가 CP 를 켜 두는 경우가 있는가 — R1 의 `CP_CSQ_CNTL` 로 닫는다.
6. 부분 실패 시 복원 경계: 어느 단계 이후 실패부터 전체 복원이 필요한가 — R0-3 과 함께.
