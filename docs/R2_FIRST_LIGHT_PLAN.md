# R2 — 첫 점등 계획서 (개정 6)

작성 2026-09-15.  **개정 5.2 — Q13(R2b-0 구현 계획 개정 1 검토) 반영(`docs/review/Q13_verdict.md`): §3 R2b-0 게이트를 구현 계획 개정 2 에 맞춤(바이트 `cmp` 대신 집합 복원 대조), VGA 레지스터 주체는 **텍스트 부팅일 때** 커널 VGA 콘솔(이 기계 실측 `_basicConsoleMode` 1), §3 표·§7 게이트의 낡은 문구 정정.  이 문서의 "부트 로더 상태" 는 PLL 에 대해서는 BIOS POST·부트 로더, VGA 코어에 대해서는 텍스트 부팅이면 커널 콘솔 상태를 뜻한다.**  개정 5.1 — Q12(R2b-0 구현 계획 검토) 반영(`docs/review/Q12_verdict.md`): §3 R2b-0 을 구현 계획 개정 1 에
맞춤(기록은 부팅 뒤 파라미터 트리거, 부팅 경로는 config 읽기·매핑만, 금지 8 예외는 operator 결정), VGA 레지스터의 주체는
커널 VGA 콘솔(부트 로더 아님).**  개정 5 — Q11(자체 agent 둘) 재검증 반영(`docs/review/Q11_verdict.md`, 내 오류 7): 새 단계 R2b-0(활성화
부팅 첫 실행은 모드 레지스터 쓰기 없이 기록·거절), `PLL_DIV_SEL` 규칙 재정의, `IOGetTimestamp` 사용 규약, 호스트 규칙 구멍,
G3·G4·G10 문구와 인용 줄.  refdiv 표·0 단계 게이트 형태는 R2b-0 결과로 개정 6 에서 확정.**  개정 4 — R2a 실측(`docs/R2A_RESULT.md`, run 789467668) 반영: §1b 새 실측 표, "R2a 값 대기" 항목을
채움, refdiv 6(레지스터)으로 분주 재계산, 방해 클라이언트 `OV0_SCALE_CNTL` 은 쓰지 않음, 복귀 PVG 는 스냅샷 값(D-6 제안),
경과 시간은 `IOGetTimestamp`, §9 정리.  개정 4 는 코드 전 검토 대상이다.**  개정 3 — Q10(R1c·R2a 구현 계획 검토) 에서 이 문서와 어긋난 곳을 고침(`docs/review/Q10_verdict.md`): R2a PLL
읽기 규약·역어셈블 게이트 문구·PCIR device 게이트.**  개정 2 는 Q9(자체 agent 둘) 반영(`docs/review/Q9_verdict.md`), 코드 없음.
개정 1 은 Q8(codex) 반영(`docs/review/Q8_verdict.md`).  순서는 PLAN §4: 이 계획 → 교차검토 → 재검증 → 코드 →
호스트 검사 → 실기.  입력은 `docs/R1_RESULT.md`(실측), `docs/R0_2_MODESET_DECODE.md`, `docs/R0_3_VGA_RETURN_DECODE.md`,
`docs/R1_CLOSES.md`.

**operator 결정(2026-09-15)**:
- D-3: PLAN §4 옵트인 예외 승인 — 디스플레이 소유자 교체는 `Active Drivers` 편집이 옵트인.
- D-4: 복구 채널은 telnet 단일 채널.

**진행 조건**:
- R1c·R2a 는 각자 구현 계획(호스트 도구·probe 코드 모양) 을 적고 검토한 뒤 코드.
- R2b 코드는 R1c·R2a 실측 PASS 와 그 값으로 이 문서의 "R2a 값 대기" 항목을 채운 개정 뒤.
  - R1c PASS(`docs/R1C_RESULT.md`), R2a PASS(`docs/R2A_RESULT.md`) — 값은 개정 4 에서 채웠다.  남은 조건은 개정 4 검토·재검증.

## 1. 이 계획을 바꾼 R1 실측

| # | 실측 | 계획에 주는 결론 |
|---|---|---|
| F1 | `CRTC_GEN_CNTL` `02000200`: `EXT_DISP_EN` 0, `CRTC_EN` 1, 형식 8 bpp — **VGA 코어가 화면을 구동**.  소유자는 generic `IOVGADisplay`(VESA 0x6a, 800×600) 이고 BIOS 호출(int10/emu486) 경로를 가진다(`VGA_reloc` strings) | 첫 점등은 "VGA 코어 → 확장 CRTC" 전환, 복귀는 확장 CRTC 를 끄고 **표준 VGA 레지스터 전체**를 되돌린다.  활성화 부팅에는 VGA 드라이버가 없으므로 진입 때 스냅샷은 부팅 콘솔이 남긴 상태다(Matrox 실측: 그래픽; 개정 5.2: 텍스트 부팅이면 커널 VGA 콘솔) |
| F2 | `CRTC_EXT_CNTL` `36088040` 의 bit 19·25·26·28·29, `DAC_CNTL` bit 14·21·22, `DISP_OUTPUT_CNTL` bit 28, `HOST_PATH_CNTL` bit 28–30 은 어느 헤더에도 정의 없음 | 진입 쓰기는 참고의 구성식: `CRTC_EXT_CNTL` = xf86 마스크(`legacy_crtc.c:148-155`, 세 DIS 비트만 하드웨어 값) + NetBSD 비트(`radeonfb.c:2500-2516`, `XCRT_CNT_EN|VGA_ATI_LINEAR|CRT_ON`).  두 참고 모두 진입 때 미정의 비트를 버리고 xf86 은 퇴장 때 저장값을 되쓴다 — 우리도 복귀가 스냅샷 전체를 되돌린다.  `DAC_CNTL` 은 NetBSD 식(`radeonfb.c:758-764`) |
| F3 | `CLOCK_CNTL_INDEX` `00000303` — `PLL_DIV_SEL` 3 | NetBSD PLL 접근은 32 비트 인덱스 쓰기로 bit 8–9 를 지운다(`radeonfb.c:1565-1578`), xf86 은 바이트 쓰기(`radeon_driver.c:603-615`).  → 인덱스 선택은 **1 바이트 저장**, R2a 는 저장마다 재읽기로 bit 8–31 불변을 확인.  VGA 코어 중 `PLL_DIV_SEL` 의 영향 미확인 |
| F4 | BIOS MC 맵: FB 내부 `00000000–1fffffff`, `DISPLAY_BASE_ADDR` 0, `CONFIG_APER_0_BASE` `e0000000` = BAR0 & ~0xf | **MC 맵을 쓰지 않는다**(PLAN R2 "R1 값과 다를 때만").  세 참고 모두 "BAR0 + x = 내부 MC_FB 시작 + x" 를 가정하고(xf86 `radeon_accel.c` 840 행), xf86 은 시작 0 맵을 운용한 경로가 있다(`radeon_driver.c:1485-1488`).  잔여 위험: 이 카드 실측 없음 → 0 단계 읽기 게이트 + 10 단계 시험 패턴으로 첫 그림에서 판정 |
| F5 | `SURFACE_CNTL` = `SURF_TRANSLATION_DIS` 만 | 쓰지 않는다.  32 bpp 바이트 순서는 스왑 없음이 참고와 같다(xf86 은 빅엔디안에서만 스왑) |
| F6 | CP 모드 0, `RBBM_STATUS.ACTIVE` 0, `AIC_CNTL` 0, `GEN_INT_CNTL` 0 | 진입 전 재확인.  `GEN_INT_STATUS`·VLINE·FRAME 은 휘발 — 동일성 판정 제외 |
| F7 | `CRTC2_EN` 0, `FP_GEN_CNTL` 0, `DISP_OUTPUT_CNTL` 소스 0(bit 28 미해석), TV DAC 는 R2a 에서 `TV_DAC_CNTL` `07660142` | 0 단계에서 R2a 값과 같지 않으면 거절.  쓰지 않는다 |
| F8 | `DAC_PDWN` 0, `DAC_MACRO_CNTL` 전원 끔 0, `GRPH_BUFFER_CNTL` `20205c5c` | DAC 전원은 쓰지 않는다(그래서 블랭크는 xf86 `RADEONBlank` 의 **CRTC 절반만**).  FIFO 는 xf86 식으로 계산(§8) |
| F9 | 128 MiB, 브리지 prefetch 창 256 MiB, BAR0 은 런타임에 PCI config 에서 하위 4 비트 마스크 | 스캔아웃 3 MiB |
| F10 | PCI 명령 `0x0307` | 건드리지 않는다 |

## 1b. 이 계획을 바꾼 R2a 실측 (개정 4)

값은 `docs/R2A_RESULT.md`(run 789467668, 스탬프 `a917b913`), 계산은 Python(`tools/oracle/radeon_modeset.py` 함수).

| # | 실측 | 계획에 주는 결론 |
|---|---|---|
| G1 | 10 묶음 모두 1 바이트 인덱스 저장 뒤 bit 8–31 불변, DATA 읽기 뒤 인덱스 불변, 복원 = `P` | §3 PLL 읽기 규약과 F3 의 1 바이트 저장이 이 카드에서 성립.  1 단계 스냅샷은 R2a 코드 그대로 |
| G2 | `PPLL_REF_DIV` refdiv **6**, `PPLL_DIV_3` `00030047`(fb 71, post 코드 3 = /8), `VCLK_ECP_CNTL` `000000c3`(소스 3 = PPLLCLK), `PPLL_CNTL` `0000a700`, `HTOTAL_CNTL` 0 | 콘솔 클럭 27000 × 71 / 6 / 8 = 39937.5 kHz(VESA 800×600@60).  **NetBSD 분주 선택에 refdiv 6·40000 kHz 를 넣으면 `00030047` 이 정확히 나오고 refdiv 12 로는 `0003008e`** — 레지스터 refdiv 6 과 일관된다(개정 5: 이것은 클럭 측정이 아니라 일관성 확인 — post /8 이 정해지면 fb 는 refdiv 에 비례한다).  더 강한 근거: refdiv 12 가 살아 있다면 fb 71 로 VCO 가 27000 × 71 / 12 = 159750 kHz 로 BIOS 최소 200000 kHz 아래다(Python).  §3 R1c "권위는 레지스터 값" 에 따라 **분주 계산은 레지스터 refdiv**(§4 6 단계 아래 표) |
| G3 | BIOS PLL 표 refdiv 12(R1c) ≠ 레지스터 6 | NetBSD 레거시 BIOS 경로(RV280 은 R300 아님)는 attach 때 읽은 레지스터 refdiv 를 쓰고 BIOS 값은 0 일 때만(`radeonfb.c:1706-1721`).  xf86 은 `pll->reference_div` 에 BIOS 값을 두지만(`radeon_driver.c:1213-1227`) **CRT 모드셋은 refdiv 를 직접 탐색**하고 그 값은 LCD 에만 쓴다(`radeon_crtc.c:167-178`, `legacy_crtc.c:1771-1794`) — 개정 4 의 "xf86 은 BIOS 값을 먼저" 대조는 틀렸다(Q11).  주 참고 NetBSD 를 따른다.  결과: 6d 가 쓰는 refdiv 는 현재 값과 같다 |
| G4 | `PPLL_DIV_0` `00070086`(fb 134, /12) | refdiv 12 로 풀면 25125 kHz, 지금 refdiv 6 으로는 VCO 603000 kHz — **범위 밖**(Python).  "VGA 클럭 슬롯" 이라는 해석은 근거 문헌이 없어 미확인(개정 5).  refdiv 6 인 동안 `PLL_DIV_SEL` 0 선택은 금지(NetBSD 는 클럭 0 을 고른다, `radeonfb.c:2228-2230`).  xf86 식 3 고정 유지(§7 규칙) |
| G5 | `PPLL_CNTL` PVG 필드(bit 11–13, `radeon_reg.h:1453-1454`) = **4**, VCO 319500 kHz | xf86 이득식(`legacy_crtc.c:251-280`, 복원 때 재계산 `legacy_crtc.c:312-314`)은 이 VCO 에서 7.  진입은 xf86 식(391500 kHz → 7 — BIOS 가 그 VCO 에 무엇을 고를지 모르는 잔여 위험), 복귀는 **스냅샷 PVG**(§5 4.5, D-6 제안) |
| G6 | `OV0_SCALE_CNTL` `807f0000` = `SCALER_SOFT_RESET`(bit 31) + `BURST_PER_PLANE` 0x7f, `SCALER_ENABLE` 0(`radeon_reg.h:1237-1265`); 나머지 방해 클라이언트 8 개 0 | 오버레이는 소프트 리셋 중.  NetBSD(`radeonfb.c:2373-2383`, `GEN_INT_CNTL` 포함 10 개)·xf86 은 0 을 쓰는데, 0 은 리셋을 푼다 → **쓰지 않는다**(§2 오버레이 쓰기 없음 유지).  xf86 도 모드셋 뒤 `SCALER_SOFT_RESET` 을 쓴다(`radeon_video.c:1320`, `RADEONEnterVT` 경로) — 소프트 리셋 상태 운용의 선례.  0 단계 게이트 형태는 R2b-0 뒤 확정(`SCALER_ENABLE` = 0 후보) |
| G7 | `CRTC_OFFSET_CNTL` `10000000`(bit 28, xf86 헤더 미정의), `DISP_MERGE_CNTL` `ffff0000`(`RGB_OFFSET_EN` bit 8 = 0), `TV_DAC_CNTL` `07660142`, `DISP_HW_DEBUG` `00020000`, `DAC_CNTL2` 0, `DISP_OUTPUT_CNTL` `10000000` | 5 단계 `CRTC_OFFSET_CNTL`=0(xf86 비DRI·타일 없음, `legacy_crtc.c:776-779`) 은 미정의 bit 28 을 내린다 — F2 와 같은 처리(복귀가 스냅샷을 되쓴다).  `DISP_MERGE_CNTL` RMW 는 값을 바꾸지 않는다 |
| G8 | 카드 경로 브리지 `00:1e.0` VGA 전달 1 | 2 단계·§5 4.9 의 표준 VGA I/O 가 카드에 닿는다.  0 단계에 브리지 VGA 전달 = 1 게이트 추가 |
| G9 | `MEM_CNTL` `32003200`(bit 0 = 0 → RamWidth 64, `radeon_driver.c:1629-1634`), `MEM_TIMING_CNTL` `1a395323`, `PIXCLKS_CNTL` `0000f8c0`(ALWAYS_ONb 비트 6·7·11–15 세움) | FIFO 오라클 입력 확보(§8).  클럭 게이팅 레지스터는 쓰지 않는다(§2) |
| G10 | `IODelay(2000)` 이 이번 부팅 4.08–4.10 ms, R1 로그 환산 2.05–2.10 ms(같은 콘솔 클럭 가정).  `IODelay` 가 부팅마다 보정된 상수를 쓴다는 것은 **근거 미확정**(2026-09-16 출처 규칙, R2b-0 계획 §15-5) — 원인 후보로만 둔다.  **실측은 부팅마다 다르다는 것뿐이다**(R1 2.05 ms, R2a 4.1 ms, R2b-0 1.87 ms).  어느 부팅이 벗어난 쪽인지 모른다.  4.1 ms 는 39937.5 kHz 로 환산한 값이라 refdiv 근거로 쓰지 않는다 | 지연 루프 길이를 믿지 않는다: 하한 대기와 13 단계 경과 시간은 `IOGetTimestamp`(driverkit `generalFuncs.h` 88 행, 미러 커널 심볼 있음) 로 잰다(§4 원칙) — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |

## 1c. 이 계획을 바꾼 R2b-0 실측 (개정 6, 2026-09-16)

원자료 `docs/R2B0_RESULT.md`, run `789526262`(활성화 부팅, 판정 `PASS-REFUSE`).
**R2b 가 실제로 출발할 상태를 처음으로 잰 것이다** — R1·R2a 는 VGA 가 화면을 쥔 부팅이었다.

| # | 실측 | 계획에서 바뀌는 것 |
|---|---|---|
| H1 | **`CLOCK_CNTL_INDEX` 의 `PLL_DIV_SEL` 이 `1`** 이다(`idxend=00000103`).  R2a 콘솔은 `3` 이었다.  R2b-0 의 `divsel` 게이트가 바로 이것 때문에 거절했다(32 중 1) | §4 0 단계의 "`CLOCK_CNTL_INDEX` bit 8–9 = 3" 을 **상수 조건에서 빼고**, 읽은 값을 기록·보존해 §5 마지막에 **읽은 그대로** 되돌린다.  받아들이는 집합은 실측된 `{1, 3}`.  그 밖의 값은 거절(미지의 부트 상태) |
| H2 | 콘솔이 쓰는 PLL 슬롯이 부팅마다 다르다: 이번은 `PPLL_DIV_1`(fb 151, post 7, VCO 339.75 MHz), R2a 는 `PPLL_DIV_3` | xf86 처럼 **`PPLL_DIV_3` 만 쓰는** 설계가 오히려 유리하다 — 이번 부팅에서는 콘솔 슬롯(1)을 건드리지 않는다.  다만 `DIV_3` 도 스냅샷·복원 대상이다(콘솔이 3 을 쓰는 부팅이 있으므로) |
| H3 | `PPLL_REF_DIV` refdiv = **12**(R2a 는 6) | 컴파일 표 `{6, 12}` 가 맞았다 — 그대로 둔다 |
| H4 | `PPLL_CNTL = 0000a700`(bit 0–1 `RESET`·`SLEEP` = 0, bit 16–18 = 0), `VCLK_ECP_CNTL = 000000c3`(소스 3), `HTOTAL_CNTL = 0` | §4 1 단계의 거절 조건이 활성화 부팅에서도 성립한다 — 그대로 둔다 |
| H5 | 콘솔 모드가 **640×480**(totals 768×524), R2a 는 800×600.  `CRTC_*` 7 개 워드가 R2a 와 다르다 | §4 0 단계에서 **"= R2a 값" 인 조건은 전부 의미 조건으로 바꾼다**(예: 방해 클라이언트는 "꺼져 있음", CRTC 는 "`CRTC_EN`=1·`EXT_DISP_EN`=0" 처럼).  **부팅 상태 상수를 코드에 굳히지 않는다** |
| H6 | 방해 클라이언트·출력 경로: `CRTC2_GEN_CNTL 04000000`(CRTC2 꺼짐), `FP_GEN_CNTL 0`, `DISP_OUTPUT_CNTL 10000000`, `DAC_CNTL2 0`, `SURFACE_CNTL 00000100`, CP 모드 0, GART 번역 0, `RBBM_ACTIVE 0` | 0 단계 조건을 **두 부팅(R2a·R2b-0)에서 모두 성립한 값**으로만 쓴다.  한 부팅에서만 본 값은 기록으로 내린다 |
| H7 | **VGA 레지스터가 커널 콘솔 표와 완전히 일치**(`vga=kernel-table`, MISC `e3`, ATTR10 `01`, 커서·시작 바이트 차이 없음) — 두 부팅 연속 | §4 2 단계(표준 VGA 스냅샷)·§5 VGA 복원 설계를 그대로 간다.  기대값의 근거가 미러 커널 표 + **두 번의 실측**이 됐다 |
| H8 | **MC 맵은 R1 이후 그대로**: `MC_FB_LOCATION 1fff0000`(카드 주소 시작 0), `DISPLAY_BASE_ADDR 0`, `displaybase` 게이트 통과 | §4 3 단계(MC 맵 손대지 않음, F4) 유지.  "애퍼처 기준과 다르니 다시 써야 한다" 는 **서로 다른 주소 공간 비교**다(`docs/R2B0_RESULT.md` 2 절 정정) |
| H9 | `IODelay(2000)` 이 이번 부팅 **1.87 ms**(R1 2.05, R2a 4.1) | `IOGetTimestamp` 로만 대기를 재는 개정 4·5 설계가 맞았다.  `IODelay` 인자는 단위로 신뢰하지 않는다 |
| H10 | 활성화 절차가 확립됐다: Configure 전환 → 잉여 인스턴스 주차 → `activate`·`same` 게이트 → 재부팅, 복구는 `/me` 집합 복원 | R2b 도 **같은 절차**로 올린다.  드라이버의 한-소유자 걸쇠(`+probe:`)와 주차 스크립트를 그대로 쓴다 |

### 1c-1. 첫 모드 — **800×600@60 결정(operator, 2026-09-16)**

호스트 오라클(`tools/oracle/radeon_modeset.py`)을 이번 부팅 실측으로 돌린 값:

| 입력 | refclk 27 MHz(R1c), **refdiv 12**(이번 부팅 실측), PLL 200–400 MHz(R1c) |
|---|---|
| fb 분주 / post 분주 | **142 / 8** → `PPLL_DIV` 워드 `0003008e`(post 코드 3 = 분주 8) |
| VCO | 320000 kHz (범위 안) |
| 실제 도트클럭 | **39937.5 kHz** |
| 새로고침 | 60.222 Hz |
| CRTC 4 워드 | `00630083` `00100340` `02570273` `00040258` — **radeonfb 와 xf86 이 같은 값** |

**이 모드는 이 카드·이 모니터가 이미 구동한 것이다**: R2a 콘솔이 800×600@60·39.94 MHz 였다
(`docs/R2A_RESULT.md`).  그때는 refdiv 6·fb 71, 이번은 refdiv 12·fb 142 — **도트클럭이 같다.**

여기서 나오는 규칙: **fb 는 상수가 아니라 그 부팅에서 읽은 `PPLL_REF_DIV` 로 계산한다.**
`PPLL_REF_DIV` 는 쓰지 않는다(스냅샷 대상).  호스트 오라클이 refdiv {6, 12} 두 경우의 값을
컴파일 표로 내고, 드라이버는 읽은 refdiv 로 그중 하나를 고른다 — 나눗셈을 드라이버에서 하지 않는다.

**남은 결정**(구현 계획에서 교차검토 대상):
1. **첫 실행이 모드를 쓸 것인가.**  더 조심스러운 쪼개기: (a) 블랭크 → 즉시 복귀만 하는 실행으로
   블랭크·복원 경로를 먼저 증명하고, (b) 그다음 부팅에서 전체 모드셋.  대가는 재부팅 한 번 더.
2. **`PLL_DIV_SEL` 을 3 으로 옮겼다가 되돌리는 것**이 이번 부팅(콘솔 슬롯 1)에서 안전한지 —
   xf86 은 그렇게 한다.  근거를 참고 구현에서 다시 확인할 것.

## 2. 범위

**한다**: **800×600@60**(operator 결정 2026-09-16, §1c-1; 개정 5 까지는 1024×768@60), 32 bpp(`RGB:888/32`), CRTC1 → 주 DAC 하나.  Workspace 가 이 드라이버의 프레임버퍼로
그린다.  종료 때 VGA 콘솔 복귀.

**하지 않는다**: MC 맵·`HOST_PATH_CNTL`·`SURFACE_CNTL`·`BUS_CNTL`·버스 마스터·CP·2D 엔진·인터럽트·CRTC2·
FP/TMDS·TV DAC 쓰기·DAC 전원·동적 클럭 게이팅·오버레이·하드웨어 커서·다중 모드(R3).

## 3. 단계 분할

| 단계 | 하드웨어 접근 | 목적 | 실행 형태 |
|---|---|---|---|
| **R1c** BIOS 셰도 읽기 | 사용자 공간 `/dev/mem` 읽기(`lseek`+`read`) | PLL 기준값·mclk·sclk | 작은 사용자 도구 + 호스트 파서 |
| **R2a** MMIO·PLL 스냅샷 probe | MMIO 읽기 + **PLL 인덱스 1 바이트 선택**(데이터 쓰기 없음) | R2b 입력(refdiv·FIFO·출력 경로·`PPLL_CNTL`) 과 PLL 읽기 규약의 실기 증명 | R1 과 같은 bare loadable |
| **R2b-0** 활성화 부팅 기록 | §4 0–2 단계 읽기와 그 인덱스·플립플롭 쓰기만, **모드 레지스터 쓰기 없음** | 활성화 부팅 상태 실측(PLL·VGA·MMIO), 게이트 판정 기록, telnet 복구 실제 수행 | `OSRDNDisplay` 기록 전용 빌드, 활성화 부팅 |
| **R2b** 모드셋 드라이버 | 모드 레지스터(§4) | 첫 점등 | `OSRDNDisplay` 활성화 부팅 |

표준 VGA 레지스터·팔레트는 살아 있는 소유자 밑에서 읽지 않는다 — R2b 가 소유한 부팅에서만(Matrox 도
`enterLinearMode` 안에서 읽었다, `REMAINING_WORK.md:3327-3333`).  R2a 는 PLAN 의 R1 등급 E("인덱스 읽기 — 필요하면
저장·복원 등급으로 별도 계획") 의 **그 별도 계획**이다.

### R1c — BIOS 셰도에서 PLL 블록

- 커널 `/dev/mem` minor 0 은 오프셋을 **물리 주소**로 받아 해당 페이지를 `pmap_enter` 로 매핑해 읽는다
  (**근거 미확정**(2026-09-16 출처 규칙, §15-5)).  **`dd skip=` 은 쓰지 않는다** — OPENSTEP `dd` 가 문자
  장치에서 건너뛰기를 읽기로 하는지 확인할 수 없고, 그러면 0x00000–0xBFFFF(살아 있는 VGA 창 포함)를 읽는다.
- 새 사용자 도구(구현 계획 별도): `open("/dev/mem", O_RDONLY)` → `lseek(0xC0000)` → 512 바이트 → 호스트가
  크기 바이트 확인 → 두 번째 실행에서 `lseek(0xC0000)` → 크기 바이트 × 512 바이트(상한 64 KiB).
- 잔여 위험: 셰도 페이지에 대한 `pmap_enter` 가 이 커널에서 안전한지 미확인 — 패닉이면 루트 fsck 비용.
  nxlogd 켜고, 부팅 직후·로그인/종료 근처를 피해서.
- 호스트 파서(`tools/r1c/parse_bios.py`) **하드 게이트**:
  1. `55 AA`, 크기 바이트 × 512 ≤ 캡처 길이.
  2. 두 번째 캡처 앞 512 바이트 = 첫 캡처(셰도 안정성·장치 일관성).
  3. PCIR 포인터·구조가 캡처와 선언 이미지 **둘 다**의 경계 안, 서명 `PCIR`, **vendor = 0x1002**, code type 0,
     **크기 바이트 ≤ PCIR image length**(초기화된 ROM 은 줄 수 있다).  device 는 기록만(개정 3: xf86 은 PCIR ID 를 보지
     않는다, Q10 B6).
  4. `BIOS16(0x48)` ≠ 0, `+4` 가 `ATOM`/`MOTA` 가 아님(레거시, `radeon_bios.c:380-427`).
  5. `+0x30` → PLL 블록, 블록 `0x1a` 바이트가 경계 안.
  6. 필드(`radeonfb.c:1697-1714`, `radeon_bios.c:997`·`:1017`):
     - `+0x00` rev(8 비트)
     - `+0x08` mclk(16)
     - `+0x0a` sclk(16)
     - `+0x0e` refclk(16, 10 kHz)
     - `+0x10` refdiv(16)
     - `+0x12` min(32)
     - `+0x16` max(32)
  7. 그럴듯함:
     - refclk ∈ {2700, 1432} 정확 일치 — xf86 이 받는 2950 은 **의도적으로 제외**
     - 0 < min < max
     - mclk·sclk ≠ 0 — xf86 은 0 을 200 으로 바꾸지만 여기서는 실패
     - **NetBSD 분주 선택(`radeon_modeset.py`) 이 BIOS min/max 로 성공**
  - 기록만:
    - ROM 체크섬
    - BIOS refdiv 와 R2a 레지스터 refdiv 의 일치 여부 — **권위는 레지스터 값**(NetBSD 주 참고, 6d 가 쓰는 필드).
      불일치면 R2b 전에 이 문서에 결정을 적는다.
- 판정: 1–7 전부 PASS = "BIOS 값 확보".  실패면 R2b 진행 불가(기본값 정책은 별도 문서·별도 게이트).  파서 자체검사
  변이(서명·경계·PCIR·앞 512 불일치·필드 0·ATOM) 각각 FAIL.

### R2a — MMIO·PLL 스냅샷 probe

읽는 것:

| 무리 | 레지스터 |
|---|---|
| PLL | `PPLL_CNTL`(bit 1·4·5·16·17·18 해석), `PPLL_REF_DIV`, `PPLL_DIV_0`, `PPLL_DIV_3`, `VCLK_ECP_CNTL`(소스·`PIXCLK_*ALWAYS_ONb`), `HTOTAL_CNTL`, `PIXCLKS_CNTL`, `MCLK_CNTL`, `SCLK_CNTL`, `M_SPLL_REF_FB_DIV`(= xf86 `X_MPLL_REF_FB_DIV`, 인덱스 0x0a) — `PPLL_DIV_1`·`2` 는 구현 계획에서 뺐다 |
| CRTC1·출력 | R1 목록 + `CRTC_OFFSET_CNTL`, `DISP_MERGE_CNTL`, `TV_DAC_CNTL`, `DISP_HW_DEBUG`, `DAC_CNTL2` |
| 방해 클라이언트 | `OVR_CLR`, `OVR_WID_LEFT_RIGHT`, `OVR_WID_TOP_BOTTOM`, `OV0_SCALE_CNTL`, `SUBPIC_CNTL`, `VIPH_CONTROL`, `I2C_CNTL_1`, `CAP0_TRIG_CNTL`, `CAP1_TRIG_CNTL`(`radeonfb.c:2352-2383`) |
| FIFO 입력 | `MEM_CNTL`, `MEM_TIMING_CNTL`, `MEM_SDRAM_MODE_REG` |
| 브리지 | `00:1e.0` config 0x3e(브리지 제어, VGA 전달 비트) — config 0x3c 워드의 상위 16 비트, bit 19(`pcireg.h:1420-1425`) — config 읽기 |

PLL 읽기 규약(개정 3, Q10 반영 — 상세는 `docs/R1C_R2A_IMPL_PLAN.md` §2-4): 레지스터마다 `splhigh()` 로 인터럽트를
막은 한 묶음 안에서
1. `P` = `CLOCK_CNTL_INDEX` 32 비트 읽기(WR_EN 이 서 있으면 쓰지 않고 끝)
2. **하위 1 바이트 저장** `idx & 0x3f`
3. 재읽기 `C` — bit 8–31 이 `P` 와 다르거나 하위 바이트 ≠ idx 면 중단
4. `CLOCK_CNTL_DATA` 읽기
5. 재읽기 `D` = `C` 아니면 중단
6. 하위 바이트 `P & 0xff` 복원 → 재읽기 = `P` 아니면 중단
→ `splx()`.  중단은 **같은 묶음에서 읽은 `P`** 를 32 비트로 되쓰고 끝(낡은 시작값이 소유자 변경을 덮지 않게).
묶음 사이 소유자 활동은 다음 묶음의 `P` 변화로 기록.

데이터 레지스터에는 쓰지 않는다.

게이트:
- 순번·스탬프 사슬.
- 모든 묶음에서 `C`·`D`·복원 재읽기 조건 성립, 모든 `P` = 첫 `P`.
- 안정 레지스터 R1 값 일치(휘발 제외, `CLOCK_CNTL_INDEX` 는 bit 8–31 만, 미정의 비트만 다르면 "기록+재계획").
- PLL 읽기 수 = 목록 수.
- **타깃 바이너리 역어셈블에서 헬퍼 `rdnMmioWrite8` 의 저장이 1 바이트, `rdnMmioWrite32` 는 32 비트**(target-build 게이트)
  — 32 비트 쓰기는 소스 규칙상 중단 경로 한 곳에서만 불린다(개정 3: 이전 문구 "오프셋 8 저장이 전부 1 바이트" 는 중단
  경로의 32 비트 쓰기와 모순, Q10 B7).
- 시뮬레이터 변이·세계는 구현 계획 §2-7.

잔여 위험(D-1):
- 소유자 VGA 드라이버는 비디오 BIOS 를 부를 수 있다(int10/emu486).
- 묶음 원자화(`splhigh`, 단일 CPU) 로 묶음 안 끼어들기는 막는다.
- 소유자가 자기 `idx|WR_EN` 저장과 DATA 쓰기 사이에서 선점된 경우는 WR_EN 검사가 쓰지 않고 끝낸다.
- RV280 의 WR_EN 래치 방식은 미확인.
- 바이트 레인이 무시되고 32 비트 되쓰기도 안 먹으면 `PLL_DIV_SEL` 이 바뀐 채 끝난다 — 추가 실행 전 재부팅.
- `_splhigh`/`_splx` 적재 링크는 타깃 `nm -u` 로 판정(안 되면 개정).

결과(개정 4): **PASS**, `docs/R2A_RESULT.md`.  중단·32 비트 되쓰기 0, `_splhigh`/`_splx` 링크됨, WR_EN 은 한 번도 서지 않아
래치 방식은 여전히 미확인.

### R2b-0 — 활성화 부팅 기록 (개정 5, Q11 B1)

R1·R2a 값은 generic VGA 드라이버가 VESA 0x6a 를 건 부팅에서 쟀다.  활성화 부팅에는 VGA 드라이버가 없다(F1).  Matrox 선례의
활성화 부팅 스냅샷은 순수 VGA 640×480, 클럭 선택 0 이었다(`REMAINING_WORK.md:3360-3369`) — 개정 5.1: 이 값은 **커널 VGA
콘솔**(`_VGASetGraphicsMode`)의 표와 바이트 단위로 같다(Q12 A1.5).  개정 5.2: 커널이 이 표를 쓰는 것은 텍스트 부팅(`_basicConsoleMode` 1)일 때뿐이고, 이 기계의 현 부팅은 텍스트 부팅이다(Q13 판정, kmem 실측).  이 카드에서 활성화 부팅의 `PLL_DIV_SEL`·refdiv·방해
클라이언트 값은 **모른다**.  그래서 R2b 첫 부팅은(개정 5.2, 상세는 `docs/R2B0_IMPL_PLAN.md` 개정 2):

- 부팅 경로(`+probe:`·init)는 PCI config 읽기와 FB·MMIO 매핑만 한다.  `enterLinearMode`·`revertToVGAMode` 는 하드웨어에 닿지
  않는다.  이 부분의 nxlogd 이전 config 입출력·매핑은 **금지 8 예외로 operator 승인**을 받았다(2026-09-15).
- 0–2 단계 기록은 **부팅 뒤 nxlogd 를 켠 상태에서** 사용자 도구가 파라미터로 트리거한다(Matrox 선례, 금지 8 준수).  기록은
  판정을 평가만 하고 모드 레지스터를 쓰지 않는다.
- "읽기 전용" 이 아니다: PLL 인덱스 1 바이트 선택·복원(R2a 규약), VGA 인덱스·ATTR 플립플롭·`PALETTE_INDEX` 는 쓰기다
  (Matrox 정정 `REMAINING_WORK.md:3327-3333`).  정확한 주장은 "모드 레지스터 쓰기 없음".
- 기록: 0 단계 전 항목 원시값, PLL 블록 전체(`PPLL_DIV_0..3`, `PPLL_REF_DIV`, `PPLL_CNTL`, `VCLK_ECP_CNTL`, `HTOTAL_CNTL`,
  `CLOCK_CNTL_INDEX`), MISC 클럭 선택, `ATTR[0x10]`, 게이트별 판정, 대기마다 `IOGetTimestamp` 경과와 FRAME 증가.
- WindowServer 는 아무도 스캔아웃하지 않는 FB 에 그린다 — 복귀 그림은 깨질 수 있으나 행은 아니다(§5 7).
- 같은 부팅에서 telnet 복구(D-4)를 실제 수행한다(Matrox `TEST_STATUS.md` 33 행 미증명 항목).
- 결과로 개정 6: refdiv 표(행 추가·삭제), `PLL_DIV_SEL` ≠ 3 처리, 0 단계 게이트를 "= R2a 값" 에서 의미 조건(예:
  `SCALER_ENABLE` 0, `CRTC2_EN` 0)으로.
- 게이트(개정 5.2): 기록 사슬 완전·boot nonce·위치·cmode 일치, 모드 레지스터 쓰기 0(소스 규칙), 언로드 없이 부팅 계속, telnet 집합 복원 1 회
  성공, 복원 뒤 인스턴스 표 집합이 활성화 전 스냅샷과 파일 집합·바이트·모드 동일(Configure 는 키 순서를 바꾸므로 기대값은 호스트가 만든 표가 아니라 스냅샷).  줄 접두는 `RDN-R2B0`(§6 의 `OSRDN init` 은 R2b 용).

### R2b — 모드셋 드라이버

§4 진입, §5 복귀, §6 드라이버 계약·활성화·복구.

## 4. R2b 진입 시퀀스 (`enterLinearMode`)

원칙:
- **플래그 셋**:
  - `indexTouched`: 인덱스 선택만 한 상태(1 단계 안에서 제자리 복원).
  - `snapshotValid`: 1·2 단계 스냅샷 완료.
  - `modeWritten`: **4 단계 첫 모드 레지스터 쓰기 직전**에 세움.
  - §5 하드웨어 복원 조건은 `snapshotValid && modeWritten`.
- 모든 거절 판정은 `modeWritten` 전에 끝낸다.  거절은 인덱스를 되돌리고 반환 — 복원 없음.
- **재진입 방어**: `modeWritten` 이 이미 서 있으면 재스냅샷하지 않는다(VGA 스냅샷을 드라이버 모드로 덮지 않게).
- 모드 쓰기 뒤 실패는 RAM 기록 → 영구 걸쇠(다음 **진입**을 막음) → §5.  대기 상한 처리는 6 단계 표.
- 대기는 절대 시간 상한 + 평가 횟수(평가 횟수 ≥ 1 은 "경로 실행 증명" 이지 하드웨어 증명이 아니다).
- **시간은 `IOGetTimestamp` 로 잰다**(개정 4, G10): `IODelay`/`IOSleep` 인자는 요청일 뿐이다.
  - 하한 대기(6l 50 ms, §5 4.7 100 ms, 12 단계 2 s) 는 잰 경과가 하한에 닿을 때까지 잠을 이어 간다.
  - 상한 대기는 잰 경과로 끊는다.  13 단계 FRAME 판정의 경과 시간도 같은 시계다.
  - `ns_time_t` 는 `unsigned long long` 이다.  cc 2.7.2.1 의 `long long` 비교 결합 결함 때문에 차이를 한 번 계산해
    32 비트 ms 로 줄인 뒤 비교한다(구현 계획에서 규칙·변이).
  - **경과 계산 규약**(개정 5, Q11 B3 — AC97 드라이버 `ich_elapsedUs` 와 같은 모양):
    - `if (t1 <= t0)` → 경과 0.  커널 시계는 클럭 인터럽트가 처리되기 전 두 번 읽으면 약 10 ms 뒤로 갈 수 있다(디컴파일
(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).  부호 없는 뺄셈이 큰 값이 되어 하한
      대기가 즉시 끝나는 것을 막는다.
    - 차이가 `0xFFFFFFFF` ns 를 넘으면 상한 값으로 두고, 32 비트로 자른 뒤 나눈다.  64 비트 나눗셈은 커널에 없는
      `___udivdi3` 를 부른다(`kernel_symbols.py --check` → MISSING) — 빌드는 되고 적재가 실패한다.
    - `if` 는 따로, `&&`/`||` 로 묶지 않는다.  `splhigh` 등 올린 spl 안에서는 시각을 읽지 않는다.
    - 상한 대기는 "평가 횟수 또는 시간" 이라 시계가 0 으로 눌려도 끝난다.
  - `IOGetTimestamp` 자체의 정확도는 미확인이다.  첫 R2b 로그에 대기마다 잰 ms 와 FRAME 증가를 함께 남겨 서로 대조한다.
- 레지스터 값은 호스트 오라클(Python) 이 R1·R2a·R1c 로 계산해 컴파일한다.  아래 16 진수는 R1 값(= R2a 값, `docs/R2A_RESULT.md` §3) 기준 Python 출력
  이고, 코드는 실행 시 읽은 값에 같은 식을 적용한다.
- 레지스터 구성과 순서는 **xf86 `legacy_crtc` 모드셋 경로**(DPMS off → `RADEONRestoreCrtcRegisters` →
  `RADEONRestorePLLRegisters` → DPMS on) 를 따르고, 값의 비트 구성만 F2 대로.

| # | 단계 | 조건·세부 | 근거 |
|---|---|---|---|
| 0 | 읽기 전용 확인 | 빌드 스탬프 로그.  BAR0·BAR2 를 PCI config 에서, 하위 4 비트 마스크.  **`CONFIG_APER_0_BASE` = BAR0**, `CONFIG_APER_SIZE`·`CONFIG_MEMSIZE` ≥ 매핑 길이.  `(MC_FB_LOCATION & 0xffff)<<16` = `DISPLAY_BASE_ADDR`, MC 맵 = R1.  `HOST_PATH_CNTL` = R1.  `SURFACE_CNTL` = R1.  `CLOCK_CNTL_INDEX` bit 8–9 = 3(MMIO 읽기; 부트 로더 상태에서 3 이 아닐 수 있다 — R2b-0 이 기록, 처리는 개정 6).  `CRTC2_EN`·FP 켜짐 0.  CP 모드 0.  `RBBM_STATUS.ACTIVE` 0.  방해 클라이언트 9 개·`TV_DAC_CNTL`·`DISP_HW_DEBUG`·`DISP_OUTPUT_CNTL`·`DAC_CNTL2`·`CRTC_OFFSET_CNTL` = **R2a 값**(개정 4: `OV0_SCALE_CNTL` `807f0000`, 나머지 방해 클라이언트 0(개정 5: "= R2a 값" 은 R2b-0 뒤 의미 조건으로 바꾼다), `TV_DAC_CNTL` `07660142`, `DISP_HW_DEBUG` `00020000`, `DISP_OUTPUT_CNTL` `10000000`, `DAC_CNTL2` 0, `CRTC_OFFSET_CNTL` `10000000`; 방해 클라이언트는 쓰지 않는다, G6).  브리지 `00:1e.0` VGA 전달 = 1(G8, config 읽기).  하나라도 다르면 거절 | F4·F6·F7·G6–G8, `radeonfb.c:2352-2383` |
| 1 | MMIO·PLL·팔레트 스냅샷 | `indexTouched` → R2a 와 같은 코드·목록(1 바이트 인덱스, 묶음 재읽기·복원 검사) → 팔레트 30 비트 256 개(`PALETTE_INDEX` 에 `0 << 16`, `PALETTE_30_DATA` 연속 읽기) → 거절 판정: `PPLL_REF_DIV` refdiv ∈ 컴파일 표 {6, 12}(개정 4: 활성화 부팅의 스냅샷은 부트 로더 상태라 R2a 의 6 과 다를 수 있다 — 표에 없으면 거절), `PPLL_CNTL` bit 0–1(`RESET`·`SLEEP`)·16–18 = 0(개정 5: 0–1 추가, §5 4.5 의 "복귀 = 스냅샷" 전제), `VCLK_ECP_CNTL` 소스 = R2a 값(3), `CLOCK_CNTL_INDEX` 끝 = 시작.  `PPLL_DIV_3`·PVG 필드는 거절 조건이 아니라 RAM·로그(§5 4.5).  refdiv 표 {6, 12} 는 부트 로더 상태에 대한 추측이다 — R2b-0 이 실제 값을 기록 | `radeon_driver.c:4478-4488`, `radeon_macros.h:115-122` |
| 2 | 표준 VGA 스냅샷 | **블랭크 전**(xf86 순서, `radeon_driver.c:3498-3504`).  I/O 포트(`inb`/`outb`): MISC(0x3cc) → bit 0 으로 CRTC 0x3d4/0x3b4·상태 0x3da/0x3ba 결정 → SEQ 0–4, CRTC 0–0x18, GR 0–8, ATTR 0–0x14(플립플롭 리셋 → 읽기 → PAS 원래대로; 읽는 동안 깜빡임은 X.Org·Matrox 가 수용).  인덱스는 원래 값 복원.  실패는 거절(아직 `modeWritten` 아님).  → `snapshotValid` | xf86 `radeon_driver.c:3132-3135`, `radeon_reg.h` 531–532·953 행, Q9 A1 |
| 3 | ~~MC 맵~~ | 하지 않는다(F4) | F4 |
| 4 | 블랭크 | `modeWritten` → xf86 DPMS off 의 CRTC 절반: `CRTC_GEN_CNTL` `CRTC_EN` 내림·`DISP_REQ_EN_B` 세움(`04000200`) → `CRTC_EXT_CNTL` 세 DIS 비트 세움(`36088740`).  출력 절반(`CRT_ON`·DAC 전원) 은 쓰지 않는다(F8) | `legacy_crtc.c:696-697` |
| 5 | CRTC 레지스터 | xf86 `RADEONRestoreCrtcRegisters` 순서: `CRTC_GEN_CNTL` = `EXT_DISP_EN|(6<<8)|DISP_REQ_EN_B`(`05000600`) → `CRTC_EXT_CNTL` = 세 DIS 하드웨어 값 + `XCRT_CNT_EN|VGA_ATI_LINEAR|CRT_ON`(`00008748`) → 타이밍 4 워드 **`0x00630083`·`0x00100340`·`0x02570273`·`0x00040258`**(800×600@60, 개정 6 — radeonfb 와 xf86 이 같은 값, `tools/oracle/radeon_modeset.py`) → `CRTC_OFFSET_CNTL`=0 → `CRTC_OFFSET`=0 → `CRTC_PITCH`=**`0x00640064`**(800 px / 8 = 100, 개정 6) → `DISP_MERGE_CNTL` RMW `RGB_OFFSET_EN` 내림 → `CRTC_GEN_CNTL` = `EXT_DISP_EN|(6<<8)`(`01000600`, `CRTC_EN` 0·요청 차단 해제 — xf86 이 PLL 을 이 상태에서 한다) | `legacy_crtc.c:148-155`, `legacy_crtc.c:174`, `legacy_crtc.c:954-958`, `radeonfb.c:2528-2576` |
| 6 | PPLL | 아래 **6a–6m**, xf86 `RADEONRestorePLLRegisters` 그대로 | `legacy_crtc.c:330-400` |
| 7 | FIFO | `GRPH_BUFFER_CNTL` = xf86 식(시작값은 **이번 진입에서 읽은** 레지스터, start·stop 을 0x5c 로, `BUFFER_SIZE` 1, `CRITICAL_CNTL`/`AT_SOF`/`STOP_CNTL` 0, critical point = 오라클) | `legacy_crtc.c:1526-1589` |
| 8 | DAC | NetBSD 식 `(현재 & (RANGE|BLANKING)) | MASK_ALL | 8BIT_EN`(`ff000102`).  `DAC_CNTL2` 는 0 확인(0 단계) 으로 쓰지 않음 | `radeonfb.c:758-764` |
| 9 | 팔레트 | 선형 램프 256: `VCLK_ECP_CNTL` 저장 → `PIXCLK_DAC_ALWAYS_ONb` 내림 → `PALETTE_INDEX` → `PALETTE_30_DATA`(`i<<22|i<<12|i<<2`) → `VCLK_ECP_CNTL` 복원(1 바이트 인덱스) | `radeonfb.c:2953-2995` |
| 10 | 시험 패턴 | 블랭크 중, init 에서 매핑한 FB 에(런타임 BAR0): 네 모서리 표식·위에서 아래로 R·G·B·흰색 띠·가로 기울기.  오프셋 어긋남·바이트 순서·피치 오류가 첫 그림에 보이게 | Q9 B19 |
| 11 | 언블랭크 | xf86 DPMS on: `CRTC_GEN_CNTL` `CRTC_EN` 세움·`DISP_REQ_EN_B` 내림(`03000600`) → `CRTC_EXT_CNTL` 세 DIS 내림(`00008048`) | `legacy_crtc.c:686-687` |
| 12 | 보여 주기 | 2 s 기다린 뒤 반환(operator 가 패턴을 본다).  WindowServer 가 덮어 그린다 | — |
| 13 | 되읽기 판정 | 타이밍 4 워드, `CRTC_GEN_CNTL` 형식·`EXT_DISP_EN`·`CRTC_EN`, `PPLL_DIV_3` FB·POST, `PPLL_REF_DIV` refdiv, `CLOCK_CNTL_INDEX` bit 8–9 = 3, `CRTC_PITCH` 하위 × 8 × 4 = `rowBytes`, `GRPH_BUFFER_CNTL`, `CRTC_EXT_CNTL`(미정의 비트 되읽기는 기록만), VLINE 움직임, FRAME 증가 = **잰 경과 시간**(`IOGetTimestamp`) × 오라클 리프레시 ± 1 — 리프레시는 1 단계 refdiv 로 고른 표 행(6 → 60.2346 Hz, 12 → 59.8884 Hz).  두 행은 2 s 에 0.69 프레임 차이라 FRAME 판정으로 구별되지 않는다(Python) — 행은 `PPLL_REF_DIV` 되읽기가 판정.  기록만: `CRTC_OFFSET_CNTL`, `PPLL_CNTL` PVG 필드 | PLAN R2 게이트 |

**6 단계 PPLL**(xf86 `RADEONRestorePLLRegisters`, PLAN 금지 2 — 창 안에 참고에 없는 읽기·쓰기 없음).  "RMW" 는 1 바이트
인덱스 PLL 읽고-바꾸고-쓰기:

- 6a. `VCLK_ECP_CNTL` RMW: `VCLK_SRC_SEL` = CPUCLK
- 6b. `PPLL_CNTL` RMW: `RESET|ATOMIC_UPDATE_EN|VGA_ATOMIC_UPDATE_EN` 세움, PVG = 오라클 이득
  (쓰기 `legacy_crtc.c:338-347`, 이득식 `legacy_crtc.c:251-280`: VCO ≥ 300 MHz → 7, ≥ 180 → 4 — R1c refclk 와 1 단계
  refdiv 로 계산, 표 두 행 모두 7)
- 6c. `CLOCK_CNTL_INDEX` MMIO RMW: `PLL_DIV_SEL` = 3(`legacy_crtc.c:348-351` — 설정이지 보존이 아니다).
  **개정 6**: 0 단계는 더 이상 3 을 요구하지 않는다(H1, 이번 부팅은 1).  여기서 슬롯을 3 으로 옮기는 것은
  1·2 단계(`VCLK_ECP_CNTL` → CPUCLK, `PPLL_CNTL` RESET) 뒤이므로 CRTC 에 보이지 않는다.  **콘솔이 쓰던
  슬롯의 워드(`PPLL_DIV_0..2`)는 진입·복귀 어디서도 쓰지 않는다** — 참고 구현도 `PPLL_DIV_3` 만 쓴다
- 6d. `PPLL_REF_DIV` RMW: refdiv 필드
- 6e. `PPLL_DIV_3` RMW: FB 필드만(`legacy_crtc.c:376-383` 첫 번째)
- 6f. `PPLL_DIV_3` RMW: POST 필드만(두 번째)
- 6g. 쓰기 전 대기: `PPLL_REF_DIV` bit 15 = 0 까지(`legacy_crtc.c:230-238`, xf86 은 상한 없음)
- 6h. `PPLL_REF_DIV` RMW: bit 15 세움
- 6i. 읽기 완료 대기: bit 15 = 0 까지, 상한 10000 평가 + 시간 상한(`legacy_crtc.c:214-226`)
- 6j. `HTOTAL_CNTL` = 0(전체 쓰기, `HTotal & 7`)
- 6k. `PPLL_CNTL` RMW: `RESET|SLEEP|ATOMIC_UPDATE_EN|VGA_ATOMIC_UPDATE_EN` 내림
- 6k'. `PPLL_CNTL` 읽기 1 회(xf86 디버그 메시지 인자, `legacy_crtc.c:397-402`) — 값은 RAM 기록, PVG 필드를 로그(개정 5: 진입 PVG 7 잔여 위험 기록)
- 6l. 50 ms(`legacy_crtc.c:409`)
- 6m. `VCLK_ECP_CNTL` RMW: `VCLK_SRC_SEL` = PPLLCLK.  **`PIXCLK_*ALWAYS_ONb` 는 쓰지 않는다**(xf86 에서는 옵트인 동적
  클럭 게이팅)

대기 상한 처리(D-5, Q9 A4·B):

| 상한 도달 | 다음 하드웨어 조작 |
|---|---|
| 6g | 6h·6i 건너뜀 → 6j–6m 수행 → 걸쇠 → §5 |
| 6i | 기록(횟수·마지막 값) → 6j–6m 계속 → 13 단계 되읽기가 판정(xf86 과 같은 동작, 상한 도달은 시험 판정 FAIL) |

NetBSD 의 같은 창은 `PPLL_DIV_0`·`PLL_DIV_SEL` 0 이고(`radeonfb.c:2237-2238`) 읽기 대기 방향이 반대다
(`radeonfb.c:2150-2166` — 자기 쓰기 대기 `radeonfb.c:2128-2139` 와 모순).  xf86 을 따른다.

**분주 표**(개정 4, G2·G3): R1c refclk 27000 kHz·min 200000·max 400000 kHz 와 **1 단계에서 읽은 레지스터 refdiv** 로
오라클(NetBSD 분주 선택)이 컴파일 시 계산한다.  표에 없는 refdiv 는 1 단계 거절.  **40000 kHz 목표(800×600@60, operator 결정 §1c-1)**, Python 출력:

| refdiv | `PPLL_DIV_3` 워드 | fb | post | **실현** VCO | 픽셀 클럭 | 리프레시(1056×628) | xf86 PVG |
|---|---|---|---|---|---|---|---|
| 6(R2a 부팅 실측) | `0x00030047` | 71 | /8 | 319500 kHz | 39937.5 kHz | 60.2223 Hz | 7 |
| 12(R2b-0 부팅 실측) | `0x0003008e` | 142 | /8 | 319500 kHz | 39937.5 kHz | 60.2223 Hz | 7 |

- **개정 6: 두 행 모두 실측된 부팅 상태다** — refdiv 6 은 R2a 부팅, refdiv 12 는 R2b-0 활성화 부팅
  (`docs/R2B0_RESULT.md`).  추측이 아니고, 둘 다 도달 가능하다.  `PLL_DIV_SEL` 은 더 이상 거절 조건이
  아니므로(H1) refdiv 12 행에 실제로 도달한다.
- **두 행의 픽셀 클럭이 같다**(39937.5 kHz): `PPLL_REF_DIV` 를 쓰지 않고 읽은 refdiv 로 fb 만 고르기 때문이다.
  그래서 13 단계 리프레시·§6 `dotClockRate` 는 행에 무관하게 하나다 — 달라지는 것은 `PPLL_DIV_3` 되읽기
  기대값뿐.  시뮬레이터는 두 행과 거절 세계를 모두 돈다.
- **강한 교차 확인**: refdiv 6 행의 워드 `0x00030047` 은 **R2a 콘솔에서 실제로 측정된 `PPLL_DIV_3` 과 비트
  단위로 같다**(`docs/R2A_RESULT.md` 49 행).  즉 이 계산 사슬 전체가 실기 값으로 확인됐다.
- **미해결(개정 6 이 새로 만든 질문): 진입 PVG.**  이번 모드의 실현 VCO(319500 kHz)는 **콘솔이 잠겨 돌던
  VCO 와 같다**.  그 상태의 `PPLL_CNTL` PVG 필드는 두 부팅 모두 **4** 였는데(`0000a700`), xf86 식은 같은
  VCO 에 **7** 을 준다.  진입에 7 을 쓰면 "이 카드에서 이 VCO 로 잠기는 것이 실측된 값" 과 다른 이득으로
  잠그게 된다.  §5 4.5 는 복귀에 스냅샷 PVG(4)를 쓰기로 이미 정했으므로, 그대로 두면 **같은 VCO 를 진입 7 /
  복귀 4 로 잠그는** 모양이 된다.  구현 계획에서 교차검토로 한쪽으로 고정한다.

## 5. 복귀 (`revertToVGAMode`)

xf86 `RADEONRestore`(`radeon_driver.c:5814-5928`) 의 순서를 첫 점등 범위로 줄인다.

1. **생명주기**:
   - 플래그 정리와 `[super revertToVGAMode]` 는 항상 먼저(Matrox 선례).
   - 하드웨어는 `snapshotValid && modeWritten` 일 때만.  부팅 때의 첫 revert(enter 보다 먼저) 는 하드웨어를 건드리지 않는다.
2. **복원 중 대기 상한은 기록하고 계속한다** — 걸쇠는 다음 진입을 막을 뿐 이 복원을 끊지 않는다(끊으면 콘솔을 잃는다).
3. **텍스트 콘솔**:
   - `ATTR[0x10]` bit 0 = 0 이면 폰트 평면이 없으니 표준 VGA 복원(4.9) 만 건너뛰고 로그를 남긴다
     (`REMAINING_WORK.md:3384-3399`).
   - 진입은 거절하지 않는다(VGA 드라이버 없는 부팅).
   - 진입이 VGA 레지스터를 쓰지 않으므로 건너뛰어도 VGA 코어 레지스터는 스냅샷 그대로다.
4. 순서:
   1. 블랭크(§4 4 단계와 같은 CRTC 절반).
   2. `GRPH_BUFFER_CNTL` 스냅샷(`radeon_driver.c:5849`).
   3. 팔레트 30 비트 스냅샷 256 개(xf86 복원은 클럭 처리 없이 쓴다, `radeon_driver.c` 4506–4510 행; 진입 9 단계와
      같은 클럭 처리를 쓸지는 구현 계획에서 한쪽으로 고정).
   4. CRTC(xf86 `RADEONRestoreCrtcRegisters` 에 스냅샷): `GEN = 스냅샷|DISP_REQ_EN_B`(`06000200`) → `EXT` = 스냅샷
      비DIS 비트 + 하드웨어 DIS(`36088740`) → 타이밍 4 워드 → `CRTC_OFFSET_CNTL` → `CRTC_OFFSET` → `CRTC_PITCH` →
      `DISP_MERGE_CNTL` → `GEN = 스냅샷`(`02000200`).
   5. PLL: §4 6a–6m 틀에 스냅샷 값(refdiv·`PPLL_DIV_3`·`HTOTAL_CNTL` — bit 28 `HTOT_CNTL_VGA_EN` 포함,
      `radeonfbreg.h:1048-1049`):
      - PVG = **스냅샷의 PVG 필드**(개정 4, D-6 제안; 개정 5 Q11 에서 유지).  xf86 은 스냅샷 분주로 이득을 다시 계산한다(`legacy_crtc.c:312-314`) —
        R2a 콘솔은 VCO 319500 kHz 에 PVG 4 인데 xf86 식은 7 이다(G5).  이 카드에서 잠기는 것이 실측된 값(4)을 되쓴다.
        같은 RMW 의 필드 값만 다르고 쓰기 자체는 참고에 있다(PLAN 금지 2 안).  검토에서 xf86 그대로(7)가 낫다는
        근거가 나오면 되돌린다.
      - 개정 5 근거 추가: 어느 참고도 `PPLL_CNTL`/PVG 를 저장·복원하지 않는다.  NetBSD 는 `PPLL_CNTL` 을 `SETPLL`/`CLRPLL`
        로만 건드려(`radeonfb.c:2220-2250`, 매크로 `radeonfbvar.h:334-335`) PVG 를 펌웨어 값 그대로 둔다 — D-6 복귀 뒤
        상태가 NetBSD 가 남기는 상태와 같다.  시뮬레이터 기대값은 "스냅샷 PVG" 로 명시한다(xf86 식으로 "고치는" 변경이
        조용히 통과하지 않게).
      - `PPLL_CNTL` 전체 스냅샷 쓰기는 하지 않는다(참고에 없음).
      - 6m 소스는 PPLLCLK — R2a 소스 3 = PPLLCLK(G2), 진입 1 단계가 같은 값을 확인한다.
      - 6k 가 내리는 `RESET`·`SLEEP`·`ATOMIC_UPDATE_EN`·`VGA_ATOMIC_UPDATE_EN` 은 R2a 에서 모두 0 이다(`PPLL_CNTL`
        `0000a700`) — 복귀 뒤 이 비트들은 스냅샷과 같다.  bit 8·9·10·15(두 헤더 미정의)는 RMW 가 보존한다.
   6. **`CLOCK_CNTL_INDEX` 32 비트 스냅샷 — 마지막 PLL 인덱스 조작**(`radeon_driver.c:5873`).  **개정 6: 읽은 32 비트
      워드를 그대로 되쓴다 — 상수 3 이 아니다.**  이번 부팅의 스냅샷은 `00000103`(`PLL_DIV_SEL` = 1)이고, 이
      쓰기가 콘솔 슬롯을 되돌린다.  **이 쓰기는 4.7 의 100 ms 와 4.8 의 DPMS on 보다 반드시 앞**이어야 한다:
      6m 뒤 4.6 까지는 PLL 이 슬롯 3 으로 CRTC 를 몰고 있고(xf86 도 같은 창), CRTC 가 아직 블랭크라서만 무해하다.
   7. **100 ms**(`radeon_driver.c:5880-5886`).
   8. CRTC 켜기: 스냅샷 `DISPLAY_DIS` 가 0 이면 xf86 DPMS on(`GEN` 먼저, `EXT` 다음) — R1 값으로 결과는 스냅샷과 같다
      (`02000200`, `36088040`, Python).
   9. 표준 VGA(Matrox 순서, I/O 포트):
      - SEQ 리셋·화면 끔
      - MISC → SEQ 2–4
      - CR11 보호 해제 → CRTC 0–0x18
      - GR 0–8
      - 플립플롭 → PAS 끔 → ATTR 0–0x14
      - SEQ 1 원래 → 리셋 해제 → PAS 켬
      - VGA DAC 경로 팔레트 쓰기는 하지 않는다(3. 에서 끝남)
   10. **`DAC_CNTL` 스냅샷 마지막**(`8BIT_EN` 0 복귀, `radeon_driver.c:5912-5920`).
5. 반복 호출 멱등(`modeWritten` 을 복원 끝에 내린다).
6. 종료 중에는 syslogd 가 먼저 내려가 로그가 없다(`REMAINING_WORK.md:3639-3646` 이어지는 기록) — 판정은 operator 육안.
   기대 그림은 **활성화 부팅의 콘솔 화면**(개정 5.2: 이 기계는 텍스트 부팅 — 커널 VGA 콘솔의 640×480 그래픽 모드 화면).
7. 잔여 위험:
   - VGA 코어 평면 메모리가 VRAM 어디인지 미확인 — 진입 10 단계·Workspace 그림이 덮으면 복귀 그림이 깨질 수 있다
     (그림 문제, 행 아님).
   - 폰트는 저장하지 않는다.

## 6. 드라이버 계약·활성화·복구·출처

Matrox 선례(원문 확인):

- **프레임버퍼 계약**(Matrox 드라이버 4000–4093 행, 형식표 1536–1545 행, driverkit `displayDefs.h`):
  - `displayInfo`:
    - `width`·`totalWidth`·`screenWidth` **800**, `height`·`screenHeight` **600**(개정 6)
    - `rowBytes` **3200**, `memorySize` **3200×600 = 1920000**
    - `bitsPerPixel` `IO_24BitsPerPixel`, `colorSpace` `IO_RGBColorSpace`
    - `pixelEncoding` `--------RRRRRRRRGGGGGGGGBBBBBBBB`(형식 6 = xRGB, 리틀엔디언 스왑 없음, NetBSD 빨강 bit 16)
    - `refreshRate`·`scanRate` 60, `dotClockRate` = 오라클 실제 클럭 **39937500 Hz**(두 행 동일, 개정 6) — 옛 값 65250000 또는 64875000(개정 5)
    - 플래그는 공개하는 자리에서(`IO_DISPLAY_HAS_TRANSFER_TABLE` 은 `setTransferTable:count:` 구현 시만)
  - init 순서:
    1. `[deviceDescription setMemoryRangeList:num:]` — FB(런타임 BAR0, 크기 ≥ 매핑 길이) + 0xA0000/0x20000 +
       0xC0000/0x10000
    2. `mapFrameBufferAtPhysicalAddress:length:`
    3. `displayInfo->frameBuffer` = 반환 주소
  - raw `IOMapPhysicalIntoIOTask` 로 FB 를 매핑하면 부팅 WindowServer 가 멈췄다(Matrox 4050–4056 행).
  - `Default.table`: `"Memory Maps" = ""`, `"VGA Memory Maps" = "0xa0000-0xbffff 0xc0000-0xcffff"`, 포트 사용 선언은
    구현 계획에서 Matrox 표와 VGA 표를 대조해 정한다.
  - 미해결 심볼이면 적재가 조용히 실패 — `nm -u` 게이트.
- **init**: 하드웨어 모드 쓰기 없음, BAR 는 PCI config 에서.
- **활성화**:
  - `Active Drivers` 에서 `VGA` 를 한 번에 교체 + cold reboot(Matrox `docs/RECOVERY_REPLACEMENT_DRIVER_EXECUTION_PLAN.md`
    36–44 행).
  - 기준선: `"SpaceSaver2Mouse Pro1000 Adaptec2940SCSIDriver MDH10Disk EMU10K1 VGA"`.
- **복구(D-4)**:
  - telnet 으로 `Active Drivers` 를 `VGA` 로 되돌림 + cold reboot.
  - 깨진 화면 부팅에서 telnet 생존은 미증명(Matrox `docs/TEST_STATUS.md` 33 행).
  - R2b 전 generic VGA → generic VGA 편집·재부팅 리허설 한 번.  재부팅은 operator.
- **설치**: 설치 스크립트는 `Active Drivers` 를 건드리지 않는다(작업공간 `tools/install-matrox-driver.sh` 7 행).
- **실패 시**: `enterLinearMode` 실패는 로그 한 줄에 복구 절차를 적고 반환(Matrox 7334–7338 행).
- **옵트인(D-3)**: PLAN §4 예외 반영됨.  R3 이후 추가 기능은 키.
- **출처 사슬**:
  - init 첫 줄에 `OSRDN init build=<hex8>`(`%08x`, 커널 `sprintf` 폭 함정).
  - 설치 reloc `sum`.
  - **R2a 로그 run id·스탬프와 R1c 캡처 SHA-256 을 빌드 스탬프 입력에 포함** — 다른 카드·BIOS 의 값과 짝지어지지
    않게.
    - 개정 4 입력: R2a run 789467668·스탬프 `a917b913`·로그 SHA-256 `e97c433f28e14a5ef6c4c88256a455affa01e98c15cff35a61eb066a5d1e9f12`,
      R1c 이미지 SHA-256 `7124ae93f71ea1497b4bc01b8623ae41a4916f4033aa4cf108f466a5ce7ada8c`.

## 7. 게이트

- **R1c**: §3 하드 게이트 1–7.  파서 자체검사 변이.
- **R2a**: §3 R2a 게이트(묶음 재읽기·복원·`P` 불변·헬퍼 폭 역어셈블).  실행 한 번, 행이면 중단·오프라인 분류(PLAN §7).
- **R2b-0**(개정 5.2): §3 R2b-0 게이트 — 기록 사슬·nonce·위치·cmode 일치, 모드 레지스터 쓰기 0(소스 규칙), 언로드 없이 부팅 계속, telnet 집합 복원 1 회, 복원 대조 PASS.
- **R2b**:
  - R2b-0 PASS 와 그 값으로 만든 개정 6 이 전제.
  - 빌드 스탬프 = 설치 sum = 묶은 트리 스탬프(R2a·R1c 입력 포함).
  - 거절 0, 진입 완료 계수 1.
  - §4 13 단계 되읽기 값.
  - 대기: 평가 횟수 ≥ 1(경로 실행 증명)·상한 도달 0.
  - **시험 패턴이 제자리·제 색**(operator, F4·바이트 순서 판정).
  - Workspace 가 뜸.
  - 종료 시 콘솔 화면 복귀(operator, 개정 5.2 문구).
  - 복구 절차 1 회 실제 수행.
- **호스트 검사**(C89·`#import`·심볼·금지 조작·시뮬레이터).  새 규칙, 각 규칙에 변이:
  - `CLOCK_CNTL_INDEX` 32 비트 쓰기는 6c(bit 8–9 를 3 으로)·§5 4.6(스냅샷)·R2a 중단 경로 3 곳뿐.
  - MMIO 오프셋 8 의 그 밖 저장은 `& 0x3f` 1 바이트.
  - 개정 5: 바이트 범위가 0x08–0x0b 와 겹치는 MMIO 쓰기는 위 목록뿐(오프셋 9 쓰기·오프셋 8 의 16 비트 쓰기 변이).
  - MC·`HOST_PATH_CNTL`·`SURFACE_CNTL`·`BUS_CNTL`·CP·`TV_DAC_CNTL`·`DAC_MACRO_CNTL` 쓰기 0 건.
  - `PIXCLK_ALWAYS_ONb` 새로 세우기 0 건(개정 4 정밀화: R2a 에서 `VCLK_ECP_CNTL` 의 두 ALWAYS_ONb 는 이미 1 이다 — RMW 가
    읽은 비트를 보존하는 것과 9 단계의 저장값 복원은 허용, 상수로 세우는 식은 금지).  개정 5: 판정은 구조 검사 — 모든
    `VCLK_ECP_CNTL` 쓰기의 ALWAYS_ONb 비트는 같은 레지스터 읽기 또는 저장값에서 온다.
  - 개정 5: 9 단계의 `PIXCLK_DAC_ALWAYS_ONb` 내림은 **모든 출구 경로**(대기 상한·조기 반환 포함)에서 복원과 짝(변이: 사이에서 반환).
  - `PLL_DIV_SEL`(bit 8–9)을 **바꾸는** 쓰기는 6c 뿐(개정 5 재정의, Q11 A4·B4: §5 4.6 과 R2a 중단 경로는 읽은 값을 그대로
    되쓴다 — 그 경로의 bit 8–9 가 3 이라는 것은 0 단계 게이트 뒤에서만 도달한다는 구조로 검사).
  - 방해 클라이언트 9 개와 `GEN_INT_CNTL` 쓰기 0 건(개정 4, G6; 개정 5: NetBSD 목록 10 개에 맞춤).
  - 개정 5: `PIXCLKS_CNTL`·`MCLK_CNTL`·`SCLK_CNTL`·`PPLL_DIV_0`·`1`·`2`·`X_MPLL_REF_FB_DIV` 쓰기 0 건.
  - 개정 5: `nm -u` 에 `___udivdi3`·`___umoddi3`·`___divdi3` 없음(64 비트 나눗셈 금지).  올린 spl 안 `IOGetTimestamp` 호출 0 건.
  - `modeWritten` 이 첫 모드 레지스터 쓰기 직전에 서고 모든 거절이 그 앞(코드 구조 검사).
  - 모든 대기에 상한.
  - `radeonfbreg.h` 의 `RADEON_CRTC_PIX_WIDTH_MASK`(`(f << 8)` 결함) 사용 금지.
  - 시뮬레이터가 §4·§5 의 레지스터 쓰기와 6k' 읽기 순서를 기록해 이 문서의 표와 비교.

## 8. 호스트 오라클 (코드 전에 만들 것)

- `radeon_modeset.py` 확장: BIOS min/max 로 분주 선택, PVG 이득, 실제 클럭, 리프레시.
- **FIFO 오라클** — xf86 `RADEONInitDispBandwidthLegacy` 를 Python 으로:
  - 입력:
    - `MEM_TIMING_CNTL`
    - `MEM_SDRAM_MODE_REG`: R1 `75320032` → DDR 1, Tcas 색인 3
    - `MEM_CNTL`: RamWidth, `radeon_driver.c:1629-1634`
    - 개정 4 실측 입력(R2a): `MEM_TIMING_CNTL` `1a395323`, `MEM_CNTL` `32003200`(RamWidth 64), `MEM_SDRAM_MODE_REG`
      `75320032`, `GRPH_BUFFER_CNTL` `20205c5c`(R2b 는 진입 때 다시 읽는다), mclk 182250 kHz·sclk 238500 kHz(R1c)
    - R1c mclk·sclk
    - 진입 때 읽은 `GRPH_BUFFER_CNTL`
    - **모드 클럭 65000 kHz**(합성 클럭 아님, `legacy_crtc.c` 1422 행)
  - 계산 규약:
    - float32 연산과 `(uint32_t)(x + 0.5)` 절삭을 흉내 낸다.
    - `DispPriority` 1(`radeon_driver.c:3144`).
    - RV280 은 `<= RV380` 분기로 rv3x0 타이밍 해독(`legacy_crtc.c:1443-1448`) — 참고가 하는 대로 계산하고 적는다.
  - "start/stop 92" 는 코드 자기검사.
- `parse_bios.py`·R1c 도구 + 변이, R2a 파서 + 휘발 제외 목록.

## 9. 남은 결정·확인

- **R2a 결과로 개정한 것**(개정 4):
  - 방해 클라이언트 0 이 아님 → `OV0_SCALE_CNTL` 만(소프트 리셋), 쓰지 않음·게이트(G6).
  - `PPLL_CNTL` bit 16–18 → 모두 0, 개정 불필요.  PVG 4 → 복귀는 스냅샷 PVG(D-6 제안, G5).
  - `VCLK_ECP_CNTL` 소스 → PPLLCLK(3), 개정 불필요.
  - BIOS/레지스터 refdiv 불일치 → 레지스터 우선, refdiv {6, 12} 분주 표(G2·G3, §4 분주 표).
  - 브리지 VGA 전달 → 1, 0 단계 게이트(G8).
- **Q11 로 정한 것**(개정 5, `docs/review/Q11_verdict.md`):
  - D-6: 복귀 PVG 는 스냅샷 값 — 두 검토자 모두 더 안전하다고 판정, NetBSD 근거 추가.
  - 활성화 부팅 거절 가능성 → R2b-0 단계 신설(기록 전용 첫 부팅, telnet 복구 겸함).
- **R2b-0 결과로 정할 것**(개정 6): 부트 로더 상태의 refdiv·`PLL_DIV_SEL` 과 그 처리(12 행 유지·삭제, 3 이 아닌 스냅샷의
  복귀), 0 단계 게이트의 의미 조건화, `OV0_SCALE_CNTL` 게이트 형태.
- **실측으로 닫힌 것**(개정 4): 칩의 바이트 레인(G1), `splhigh` 링크 가능성(R2a 타깃 `nm -u`).
- 미확인으로 남김(판정 문서 참조):
  - `PLL_DIV_SEL` 의 VGA 코어 영향
  - `CRTC_EXT_CNTL` 미정의 비트 의미, `CRTC_OFFSET_CNTL` bit 28·`PPLL_CNTL` bit 8–10·15 의미
  - 셰도 페이지 `pmap_enter` 안전성
  - VGA 평면 메모리 위치
  - RV280 WR_EN 래치 방식(R2a 에서 한 번도 서지 않음)
  - `IOGetTimestamp` 정확도, `IODelay` 길이가 부팅마다 달라지는 원인(G10 — `us_spin_calibrate` 1 회 보정이 후보)
  - `PPLL_DIV_0` 의 용도(VGA 클럭 슬롯이라는 해석은 미확인), 진입 PVG 7 이 이 카드에서 잠기는지
  - xf86 CRT 경로가 이 카드에 고를 refdiv(Q11 A 의 에뮬레이션 값은 미확인이라 옮기지 않음)
  - 콘솔 CRTC 워드(800×600, 총 1024×626)가 실제 스캔아웃 값인지
  - R2a 실행 전 재부팅이 종료 후반에 멈춘 원인(`docs/R2A_RESULT.md` §0)
