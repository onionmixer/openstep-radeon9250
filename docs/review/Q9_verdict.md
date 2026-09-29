# Q9 판정 — R2 계획서 개정 1 교차검토(자체 agent) 재검증

작성 2026-09-15.  codex 사용 불가 기간이라 교차검토는 **자체 agent 둘**(새 general-purpose, 이 세션 추론을
물려받지 않음)이 했다: `docs/review/Q9_reply_A.md`(진입·복귀 시퀀스), `docs/review/Q9_reply_B.md`(R1c·R2a·게이트·
FB 계약).  질문은 `docs/review/Q9_prompt.md`.  **agent 회신도 codex 와 똑같이 검증 대상 입력이다.**  아래 판정은
이 세션에서 원문을 열었거나 Python 으로 다시 계산한 것만 적는다.

## 0. 내가 틀린 것 (먼저)

1. **6 단계 인용**: `(현재 & 세 DIS) | XCRT|LIN|CRT_ON` = `0x8748` 은 NetBSD 식이 아니다 — NetBSD 는
   `DISPLAY_DIS` 하나만 남긴다(`radeonfb.c:2500-2516`, Python `0x8448`).  값은 xf86 마스크
   (`legacy_crtc.c:148-155`) + NetBSD 비트 조합이다.  Q8 판정 D-2 문구도 같은 오독.
2. **2 단계 "xf86 DPMS off 그대로"**: `RADEONBlank` 는 출력 DPMS off(`CRT_ON` 내림·DAC 전원 끔) 도 한다
   (`legacy_output.c` 1070–1076 행, 이 세션에서 열어 확인).  계획은 CRTC 절반만이다.
3. **8m 뒷부분**(`PIXCLK_ALWAYS_ONb|PIXCLK_DAC_ALWAYS_ONb` 세움): NetBSD 는 "ungate" 라 부르지만 xf86 에서는
   **동적 클럭 게이팅 켜기** 경로에만 있고 옵션 기본값은 꺼짐(xf86 `radeon_pm.c` 403–407 행, 끄기 경로 583–586
   행, 옵션 789–793 행).  PLL 창에 참고(xf86)에 없는 쓰기를 넣었다.
4. **PLL 창 동안 CRTC 상태**: xf86 은 `CRTC_EN` 0·요청 차단 해제로 PLL 을 프로그래밍한다
   (`legacy_crtc.c:148-155` 로 시작해 174 행에서 `crtc_gen_cntl` — `EXT_DISP_EN|형식`, `CRTC_EN` 없음 — 을 쓰고
   PLL 로 간다).  계획은 `CRTC_EN` 1·요청 차단 1 이었다.  또 xf86 은 offset·pitch·merge 를 **PLL 앞**에 쓴다.
5. **복귀 순서가 "xf86 순서" 가 아니었다**: xf86 은 CRTC_GEN/EXT 스냅샷을 PLL **앞**에 쓰고, 인덱스 복원 뒤
   100 ms(`radeon_driver.c:5880-5886`, 주석 "console can either hang or the fonts can be corrupted"), CRTC 켜기가
   VGA 복원 **앞**이다.  계획은 GEN/EXT 를 VGA 뒤로 미뤘고 100 ms 가 없었다.
6. **플래그 모순**: 1 단계가 `hardwareTouched`·`snapshotValid` 를 세운 뒤 거절하면 §5 조건이 참 → 종료 때 모드를
   바꾼 적 없는 카드에 전체 복원.
7. **대기 상한 → §5**: 8g/8i 에서 §5 로 가면 리셋 상태 PLL 에 블랭크·FIFO·팔레트 쓰기가 들어간다(금지 2).
8. **0 단계 "방해 클라이언트 9 개 전부 0"**: R2a 가 아직 재지 않은 값을 기대 — 0 이 아니면 매 부팅 거절.
9. **R1c 게이트 6(VCO 범위)·7(BIOS refdiv = 레지스터)**: 6 은 오라클이 BIOS min/max 로 고르면 항진, 고정
   `0x000600ad` 로 읽으면 max < 390 MHz BIOS 에서 거짓 실패(Python: max 350000/389000 → post 4, fb 116).
   7 은 참고가 요구하지 않는다 — NetBSD 는 레지스터 우선(`radeonfb.c:1709-1726`), xf86 은 BIOS 우선.
10. **FB 계약 누락**: Matrox 는 `mapFrameBufferAtPhysicalAddress` 전에 `setMemoryRangeList:num:`(FB + 0xA0000/0x20000
    + 0xC0000/0x10000) 을 부르고 `displayInfo->frameBuffer` 를 채운다(Matrox 드라이버 4078–4093 행).

## 1. 판정표 — A (진입·복귀)

| # | agent 주장 | 내 검증 | 판정 |
|---|---|---|---|
| A1 | VGA 는 표준 I/O 포트, MMIO 미러 금지 — 0x3c4·0x3c8 은 MMIO 에서 32 비트 FP 레지스터 | xf86 `radeon_reg.h` 888·904 행 `FP_H2_SYNC_STRT_WID 0x03c4`·`FP_V2 0x03c8`; NetBSD `radeonfbreg.h` 939·955 행 같은 값, 1652 행 `SEQ8_IDX 0x03c4`·686 행 `DAC_W_INDEX 0x03c8`; xf86 `legacy_crtc.c` 203–204 행 `OUTREG`, 584–585 행 `INREG`; driverkit `i386/ioPorts.h` `inb(port)`·`outb(port, data)`, `displayRegisters.h` `IOReadRegister`; R1 probe `outl`/`inl` | ✅ |
| A1a | CRTC 포트 기준은 MISC bit 0 | xf86 `radeon_reg.h` 531–532·953 행 주석 "VGA, 0x3b5"·"0x03ba"; `radeon_driver.c:3134-3137` `vgaHWGetIOBase` | ✅ |
| A1b | xf86 은 VGA 저장을 블랭크 **전**에 | `radeon_driver.c` 3498 행 `RADEONSave` → 3504 행 `RADEONBlank` | ✅ xf86 순서 채택(CRTC 가 켜진 상태에서 읽음, PAS 깜빡임은 X.Org·Matrox 가 수용) |
| A2 | 미정의 비트 정의 없음, 두 참고 모두 진입 때 버리고 xf86 은 퇴장 때 저장값 복원 | xf86 `radeon_probe.c` 217 행 `xnfcalloc`(ModeReg 0 초기화), `legacy_crtc.c:148-155` OUTREGP(DIS 만 하드웨어 값); 인용 오류는 내 오류 1 | ✅ |
| A3 | 2 단계는 CRTC 절반; xf86 은 POST 된 카드에 ScreenInit 직후 블랭크; NetBSD 는 `CRTC_EN` 안 내림 | 위 3498–3504 행; `radeonfb.c:2699` | ✅ 이름 고침, DAC 전원은 계속 안 씀(F8) |
| A4 | D-5: xf86 방향이 맞다(NetBSD 읽기 대기는 자기 쓰기 대기와 반대) | `radeonfb.c:2150-2166` 은 1 에서 멈춤, 쓰기 대기 `radeonfb.c:2136-2147` 은 1 동안 대기; `legacy_crtc.c:216-228` 주석 | ✅ 8i 상한은 기록 후 8j–8m 계속, 판정은 15 단계; 8g 상한은 8h/8i 건너뛰고 8j–8m 후 걸쇠·복귀; 복귀 중 상한은 기록 후 계속 |
| A5a | 8a–8l 은 xf86 과 순서·마스크 일치 | `legacy_crtc.c:330-400` 을 열어 대조 | ✅ |
| A5b | xf86 은 8k 뒤 `PPLL_CNTL` 읽기 1 회(디버그 메시지 인자) | `legacy_crtc.c` 397–402 행 `INPLL(pScrn, RADEON_PPLL_CNTL)` | ✅ 포함(참고 그대로) |
| A5c | 8m 뒷부분 제거 | 내 오류 3 | ✅ |
| A5d | PLL 창 CRTC 상태 xf86 과 다름 | 내 오류 4 | ✅ xf86 상태로 |
| A5e | R2a 가 `PPLL_CNTL` bit 18(`ATOMIC_UPDATE_VSYNC`)·1·4·5 를 기록 | xf86 `radeon_reg.h` 1452–1458 행 | ✅ |
| A6 | 복귀 순서 4 곳 수정 + `PPLL_CNTL` 복원 방식 명시 | 내 오류 5; xf86 DPMS on `legacy_crtc.c` 687–688 행(GEN 먼저) | ✅ |
| A6b | VGA 평면 메모리가 3 MiB 지우기와 겹치는지 미확인 | `MEM_VGA_WP_SEL`/`RP_SEL` 사용 `.c` 0 건(agent grep, 레지스터 정의만 xf86 `radeon_reg.h` 1116–1117 행 확인) | ⚠️ 잔여 위험(그림 문제, 행 아님) |
| A7 | §4 16 진수 전부 재현 | 내 Q8 Python 출력과 일치 | ✅ |

## 2. 판정표 — B (R1c·R2a·게이트·FB)

| # | agent 주장 | 내 검증 | 판정 |
|---|---|---|---|
| B1 | `/dev/mem` minor 0 은 `mem_size` 미만 모든 물리 페이지를 `pmap_enter` 로 매핑해 읽는다 | `openstep-kernel-remade/04_ghidra/.../00194c24.c` 42–58 행(이 세션에서 열어 확인), `00194bf4.c` `_mmread → _mmrw(dev,uio,0)` | ✅ 오프셋 = 물리 주소.  ⚠️ 셰도 ROM 페이지에 `pmap_enter` 가 안전한지 미확인(패닉 = 디스크 비용) |
| B2 | `dd skip` 이 문자 장치에서 읽어서 건너뛸 수 있다(0x00000–0xBFFFF, VGA 창 포함) | OPENSTEP `dd` 는 미러에 없다 — 확인 불가 | ⚠️ → **`dd` 를 쓰지 않는다**: `lseek`+`read` 전용 사용자 도구로(오프셋이 uio 오프셋으로 직접 감, B1) |
| B3 | 두 번째 캡처의 앞 512 바이트 = 첫 캡처 | 논리 | ✅ |
| B4 | PCIR 길이 게이트는 "크기 바이트 ≤ PCIR 길이" | 참고 트리에 근거 없음(PCI 펌웨어 관례) | ⚖️ 채택(같음을 요구하면 건강한 셰도가 떨어질 수 있다) |
| B5 | `BIOS16(0x48) ≠ 0`, ATOM/MOTA 판별, rev 는 +0x00 8 비트 | `radeon_bios.c` 403–405·413–422·999 행 | ✅ |
| B6 | 게이트 6·7 문제 | 내 오류 9; `radeonfb.c:1709-1726`, xf86 `radeon_driver.c` 1212–1230 행 | ✅ 6 → "BIOS min/max 로 분주 선택 성공", 7 → 불일치는 기록, **권위 = 레지스터 값**(NetBSD 주 참고, 8d 가 쓰는 필드) |
| B7 | xf86 수정 판별은 2950 도 받는다 | `radeon_driver.c` 1108–1113 행 | ✅ refclk 는 `{2700, 1432}` 정확 일치로 — 2950 제외는 의도적 축소로 기록 |
| B8 | 살아 있는 VGA 드라이버는 int10/emu486 으로 비디오 BIOS 를 부를 수 있다 | `strings VGA_reloc`: `emu486 error`, `int10:`, `Set VGA VESA Mode`, `ATIPresent:`; `SVGABIOS.table` `"SVGA VESA BIOS Mode" = "0x6a"` | ✅ R2a 인덱스 경합 위험 실재 — 부팅 직후·로그인/종료 근처 금지 |
| B9 | `OUTREG8` 은 1 바이트 저장, 칩이 바이트 레인을 지키는지는 미확인; R2a 는 끝에 하위 바이트만 복원 | Mesa `radeon/server/radeon_macros.h` 49–50 행 `*(volatile unsigned char *)...`; xf86 `radeon_driver.c` 1076 행 `INREG8(RADEON_CLOCK_CNTL_INDEX + 1)`(바이트 1 을 따로 읽는 의존) | ✅ **저장마다 `CLOCK_CNTL_INDEX` 재읽기 → bit 8–31 이 시작값과 다르면 즉시 32 비트 시작값을 되쓰고 중단**(그 경로에만 있는 쓰기).  타깃 바이너리에서 오프셋 8 저장이 1 바이트인지 역어셈블 게이트 |
| B10 | PLAN 의 등급 E "인덱스 읽기 안 한다 — 필요하면 저장·복원 등급으로 별도 계획" | PLAN 238 행 | ⚖️ R2a 가 그 별도 계획 — R2 계획서에 명시(PLAN 개정 불필요) |
| B11 | xf86 은 BAR0+x = 내부 `fbLocation`+x 를 가정 | xf86 `radeon_accel.c` 840 행 `dstOffs = dst - info->FB + info->fbLocation`, `radeon_driver.c` 494·1530·1408 행 | ✅ F4 근거 보강 |
| B12 | 0 단계 읽기 게이트 추가: `CONFIG_APER_0_BASE` = BAR0 & ~0xf, APER/MEMSIZE ≥ 매핑 길이, `(MC_FB & 0xffff)<<16` = `DISPLAY_BASE_ADDR`, `HOST_PATH_CNTL` = R1, `CRTC_OFFSET_CNTL` = R2a | Python `0xe0000008 & ~0xf` = `0xe0000000` = R1 `CONFIG_APER_0_BASE` | ✅ |
| B13 | 1 단계 거절 후 플래그 모순 | 내 오류 6 | ✅ `indexTouched` / `modeWritten` 분리, 복원 조건 `snapshotValid && modeWritten` |
| B14 | 8c 는 bit 8–9 를 3 으로 **설정**(보존 아님) | `legacy_crtc.c:348-351` | ✅ 0 단계에서 실행 시 `PLL_DIV_SEL` = 3 확인, 호스트 규칙 문구 수정 |
| B15 | 실패할 수 없는 게이트: "start/stop 92 = BIOS", "평가 횟수 ≥ 1" | Python `min(1024*4//16, 0x5c)` = 92 상수 | ✅ 각각 "코드 자기검사", "경로 실행 증명" 으로 이름 바꿈 |
| B16 | FRAME 3–4/60 ms 는 `IOSleep` 초과로 건강해도 실패 | R1 probe `FRAME_GAP_MS 60`·`IOSleep(FRAME_GAP_MS)`; R1 은 56 Hz 에서 +4 | ✅ 경과 시간을 재서 기대 범위를 계산 |
| B17 | FB 계약: `setMemoryRangeList`·`frameBuffer`, 선언 범위 ⊇ 매핑 | Matrox 4078–4093 행, `Default.table` 68–69 행 `"VGA Memory Maps" = "0xa0000-0xbffff 0xc0000-0xcffff"`; driverkit `displayDefs.h` `void *frameBuffer;` | ✅ |
| B18 | 32 bpp 바이트 순서 일치(형식 6 = xRGB, 리틀엔디언 스왑 없음, NetBSD 빨강 bit 16) | xf86 `legacy_crtc.c` 894 행 `/* xRGB */`, 740–757 행(빅엔디안에서만 스왑); NetBSD `radeonfb.c` 2740–2748 행 `ri_rpos = 16` | ✅ 실측은 첫 점등 그림으로 |
| B19 | 13 단계를 균일 지우기 대신 위치 부호 시험 패턴으로(오프셋·바이트 순서가 보이게) | 레지스터 쓰기 추가 없음 | ✅ |
| B20 | `radeonfbreg.h:442` `(f << 8)` 결함 | 이 세션에서 열어 확인; `tools/` 에서 `PIX_WIDTH_MASK` 사용 0 건(grep) | ✅ 호스트 규칙: 쓰지 않고 `0xf << 8` |
| B21 | 재진입 방어: `modeWritten` 이면 재스냅샷 안 함 | driverkit `IOFrameBufferDisplay.h` "revertToVGAMode is called first" 만 있고 두 번 enter 없음 보증 없음 | ✅ 비용 0 |
| B22 | 출처 사슬에 R2a 로그 스탬프·R1c 캡처 해시 | 논리 | ✅ |
| B23 | FIFO 오라클: 모드 클럭 65000(합성값 아님), float32, 저장 레지스터의 다른 비트 유지; 누락 입력 6 개 | xf86 `legacy_crtc.c` 1422 행 `mode1->Clock/1000.0`, 1633 행 `temp = info->SavedReg->grph_buffer_cntl`, 1611 행 `(uint32_t)(... + 0.5)` | ✅ 입력 목록 채택.  ⏭️ agent 의 critical point 민감도 표(9–27) 는 문서에 옮기지 않는다 — 오라클이 실측 입력으로 계산 |
| B24 | R2a 에 `splhigh` | 커널 심볼표에 있다는 주장, 적재 모듈 링크 가능 여부 미확인 | ⚠️ 요구로 넣지 않음, `nm -u` 로 확인 가능하면 검토 |

## 3. 계산 (이 세션 Python 출력)

- xf86 순서 진입(R1 값 기준): 블랭크 `GEN 0x4000200`·`EXT 0x36088740` → 5 단계 `GEN 0x5000600` → 6 단계
  `EXT 0x8748` → PLL 전 `GEN 0x1000600` → DPMS on `GEN 0x3000600`·`EXT 0x8048`.
- 복귀: `GEN|REQ_B 0x6000200` → `EXT` DIS 유지 `0x36088740` → `GEN 0x2000200` → DPMS on(스냅샷 `DISPLAY_DIS` 0
  → crtc_on) `GEN 0x2000200`·`EXT 0x36088040` = 스냅샷과 같다.
- `0xe0000008 & ~0xf` = `0xe0000000`; `0x80*8*4` = 4096.

## 4. 2차 자기검사

- 백틱 인용은 `check_citations.py` 로 기계 대조.  산문 행 번호(xf86 `radeon_pm.c`, `radeon_accel.c`, Mesa,
  커널 Ghidra, driverkit, Matrox) 는 이 세션에서 `sed -n` 으로 열었다.
- 부재 주장: "Radeon VGA MMIO 미러 사용 0 건"(Q8), "`tools/` 에 `PIX_WIDTH_MASK` 0 건" 은 grep 출력 확인.
  "OPENSTEP `dd` 미러에 없음" 은 agent 의 find 결과이고 **내가 다시 돌리지 않았다** — 결론(`dd` 를 쓰지 않음) 은
  그 사실에 의존하지 않는다.
- ⚠️ 남김: A6b(VGA 평면 메모리 위치), B1(셰도 페이지 `pmap_enter`), B9(칩의 바이트 레인 — 재읽기 검사로 탐지),
  B24, `CRTC_EXT_CNTL` 미정의 비트 의미, `PPLL_CNTL` bit 18 값(R2a).
- Q8 판정 D-2 문구 정정은 이 문서 §0-1 이 대신한다(Q8 판정 끝에 정오표 한 줄).
