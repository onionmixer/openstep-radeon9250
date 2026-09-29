# Q11 판정 — R2 계획 개정 4 교차검토(자체 agent 둘) 재검증

- 요청: `docs/review/Q11_prompt.md`.  회신: `Q11_reply_A.md`(PLL·복귀), `Q11_reply_B.md`(게이트·시간·방법).
- 원칙: 회신은 검증 대상 입력이다.  아래 "내 검증" 칸은 이 세션에서 직접 연 파일:줄, 실행한 명령과 출력이다.
- 반영: `docs/R2_FIRST_LIGHT_PLAN.md` 개정 5.

## 0. 내가 틀린 것 (먼저)

1. **G3 의 xf86 대조가 틀렸다.**  G3 은 "xf86 은 BIOS refdiv 를 먼저 쓴다" 고 적었다.  그러나 xf86 의 CRT 모드셋은 refdiv 를
   직접 탐색한다(`radeon_crtc.c:175-186`).  BIOS 값을 쓰게 하는 플래그는 LCD 에서만 붙는다(`legacy_crtc.c:1771-1794`).
2. **인용 줄이 틀렸다.**
   - `legacy_crtc.c:334-346` 은 이득 재계산이 아니다.  334 행은 `VCLK_ECP_CNTL` RMW 이고, 재계산은 `:312-314`, `PPLL_CNTL`
     RMW 는 `:338-347` 이다.
   - `radeonfb.c:2373-2404` 은 방해 레지스터 쓰기(`:2373-2383`)보다 넓다.  NetBSD 목록은 `GEN_INT_CNTL`(`:2381`) 을 포함해 10 개다.
3. **G4 "VGA 슬롯" 은 추론을 사실처럼 적은 것이다.**  근거 문헌이 없다.  말할 수 있는 것은 "refdiv 12 로 풀면 25125 kHz,
   지금 refdiv 6 으로는 범위 밖 VCO" 까지다.
4. **활성화 부팅과의 모순을 만들었다.**
   - refdiv 12 행은 "부트 로더 상태" 를 위한 것이라 적었다.
   - 그런데 0 단계 `PLL_DIV_SEL` = 3 게이트와 §7 규칙은 VESA 상태를 전제한다.  부트 로더가 슬롯 0 을 쓰면 12 행에는 도달할 수 없다.
5. **`IOGetTimestamp` 사용법이 불완전했다.**  64 비트 나눗셈이 커널에 없는 `___udivdi3` 를 부른다는 점과 비단조 창을 빠뜨렸다.
6. **호스트 규칙에 구멍을 남겼다.**
   - 오프셋 0x09–0x0b 저장, 클럭·인터럽트 레지스터 쓰기 금지 목록이 없다.
   - 9 단계 `PIXCLK_DAC_ALWAYS_ONb` 복원을 모든 경로에서 요구하지 않았다.
   - `PLL_DIV_SEL` 규칙 문구가 R2a 중단 경로·§5 4.6 과 충돌한다.
7. **개정 4 가 놓친 문서 불일치.**
   - `docs/R2A_RESULT.md:63` "xf86 방식" 이 개정 4 와 어긋난다.
   - §6 `dotClockRate` 가 행에 따라 달라진다는 말이 없다.
   - 1 단계가 `PPLL_CNTL` bit 0–1 을 보지 않는다.
   - "R1 값 기준" 문구가 남아 있다.

## 1. 판정표 — 검토자 A

| # | 주장 | 내 검증 | 판정 |
|---|---|---|---|
| A1a | G2–G5·분주 표 수치 모두 맞음 | 개정 4 작성 때 Python 출력(콘솔 40000 → `00030047`/`0003008e`, 65000 행 둘), 이번에 `27000*71/12` → 159750.0 재실행 | ✅ |
| A1b | 더 강한 근거: refdiv 12 면 fb 71 로 VCO 159750 kHz < BIOS 최소 200000 | `python3 -c "print(27000*71/12)"` → 159750.0; bios-facts `minpll_10khz=20000` | ✅ 채택 — G2 에 추가 |
| A1c | "재현" 은 일관성 확인이지 클럭 측정이 아님 | 논리 확인: post /8 이 정해지면 fb = round(refdiv×320000/27000) | ✅ 문구 조정 |
| A1d | G10 의 4.1 ms 는 39937.5 kHz 를 써서 refdiv 근거로 순환 | `R2A_RESULT.md:87` "콘솔 줄 속도(39937.5 kHz / 1024)로 환산" | ✅ |
| A2a | NetBSD RV280 은 R300 아님 → 레지스터 refdiv 우선 | `radeonfb.c:505-509` `case RADEON_RV280: sc->sc_flags \|= RFB_RV100;`, `:515-522` R300 목록에 RV280 없음; `:1720-1724` | ✅ |
| A2b | xf86 CRT 경로는 refdiv 를 탐색, `pll->reference_div` 는 `USE_REF_DIV` 때만 | `radeon_crtc.c:175` `if (flags & RADEON_PLL_USE_REF_DIV)`, `:178` `while (min_ref_div < max_ref_div-1)`; `legacy_crtc.c:1771` `pll_flags = RADEON_PLL_LEGACY`, `:1793-1794` LCD 만 `USE_REF_DIV`; `legacy_crtc.c:1229-1231` 기본 `RADEON_PLL_OLD` | ✅ 채택 — G3 고침 |
| A2c | xf86 에뮬레이션이면 refdiv 9·fb 130 | 재실행하지 않음 | ⚠️ 미확인 — 계획에 옮기지 않음 |
| A2d | {6, 12} 표는 부트 로더 상태에 대한 추측, 정상 카드 거절 가능; 두 기대값 집합; `dotClockRate` 행 의존 | 계획 `:305` `dotClockRate = 오라클 실제 클럭(Hz)` 확인; B1 과 합쳐 판단 | ✅ 채택 — R2b-0 결과로 재결정(§3 R2b-0) |
| A3a | 어느 참고도 `PPLL_CNTL`/PVG 를 저장·복원하지 않음, NetBSD 는 PVG 를 쓰지 않음 | `radeonfb.c:2223` `SETPLL(sc, RADEON_PPLL_CNTL,`, `:2250` `CLRPLL(sc, RADEON_PPLL_CNTL,`; `radeonfbvar.h:334-335` SETPLL/CLRPLL 정의; `legacy_crtc.c:312` 재계산 | ✅ — D-6 근거로 추가 |
| A3b | 진입 PVG 7 은 BIOS 선택과 다를 수 있는 잔여 위험, 되읽기 PVG 기록 | 논리 | ✅ 채택 |
| A3c | 1 단계가 `PPLL_CNTL` bit 0–1 을 보지 않아 "복귀 = 스냅샷" 미보장 | 계획 1 단계 문구 `bit 16–18` 만 | ✅ 채택 |
| A3d | 인용 `legacy_crtc.c:334-346` 오류 | `grep -n` → `:312` `pllGain = RADEONComputePLLGain`, `:334` `OUTPLLP(pScrn, RADEON_VCLK_ECP_CNTL,`, `:338` `OUTPLLP(pScrn,` | ✅ |
| A4a | "VGA 슬롯" 미확인 | `grep -rn -i "vga clock\|vga_clock\|25175\|25\.175" radeonfb.c radeonfbreg.h legacy_crtc.c radeon_reg.h radeon_driver.c` → 출력 없음; NetBSD 는 슬롯 0 에 자기 모드를 씀 `radeonfb.c:2230-2232` | ✅ 문구 축소 |
| A4b | `PLL_DIV_SEL` 규칙 문구가 R2a 중단 경로·§5 4.6 과 충돌 | 계획 `:355` 문구 확인 | ✅ 채택 — 규칙 재정의 |
| A5a | xf86 은 모드셋 뒤 `SCALER_SOFT_RESET` 을 씀 | `radeon_video.c:1320` `OUTREG(RADEON_OV0_SCALE_CNTL, RADEON_SCALER_SOFT_RESET);`; 호출 `radeon_driver.c:6302` `RADEONResetVideo(pScrn);` (`RADEONEnterVT` `:6227`) | ✅ |
| A5b | 0 단계 게이트는 `SCALER_ENABLE` = 0 으로, `GEN_INT_CNTL` 명시 | `radeonfb.c:2381` | ✅ 채택(게이트 형태는 R2b-0 뒤 확정) |
| A6 | `R2A_RESULT.md:63`, `dotClockRate`, "R1 값 기준", 시뮬레이터가 스냅샷 PVG 기대 | `R2A_RESULT.md` 63 행 `R2b 는 PPLL_REF_DIV 를 자기 계산값으로 쓴다(xf86 방식).` 확인; 계획 177 행 확인 | ✅ 채택 |

## 2. 판정표 — 검토자 B

| # | 주장 | 내 검증 | 판정 |
|---|---|---|---|
| B1a | Matrox 활성화 부팅 스냅샷은 순수 VGA 640×480, 클럭 선택 0 | `openstep-matrox-remade/docs/REMAINING_WORK.md` 3364 행 `misc e3 seq1 01 crtc0 5f`, 3369 행 `클럭 선택 0 = 25.175 MHz VGA 클럭`, 3373 행 `MGA 확장 모드 꺼짐 — 순수 VGA` | ✅ (다른 카드라는 한계는 남음) |
| B1b | 활성화 부팅에서 `PLL_DIV_SEL` = 3 게이트가 거절할 가능성이 높음 | B1a + `PPLL_DIV_0` 이 refdiv 12 에 맞는 값(Python 25125) — ATI BIOS 가 표준 VGA 모드에서 `PLL_DIV_SEL` 을 무엇으로 두는지는 파일로 확인 불가 | ⚖️ 부분채택 — "가능성 높음" 은 미확인, "모른다" 는 사실 |
| B1c | 계획 내부 모순(0 단계 게이트 ↔ 12 행 ↔ §5 4.6 ↔ §7) | 계획 문구 대조 | ✅ (내 오류 4) |
| B1d | R2b 첫 부팅을 "모드 레지스터 쓰기 없는 기록·거절" 실행으로 의무화, telnet 복구 시험 겸함 | Matrox `D1_REPLACEMENT_DISPLAY_OWNERSHIP.md` 36 행 `S3 replacement init ... documented init validation만`; `TEST_STATUS.md` 33 행 telnet 미증명(계획 §6 인용) | ✅ 채택 — 새 단계 R2b-0 |
| B1e | "읽기 전용" 이 아니라 "모드 레지스터 쓰기 없음"(인덱스·ATTR 플립플롭·팔레트 인덱스는 쓰기) | `REMAINING_WORK.md` 3330 행 `"읽기만 하고 쓰지 않는다"는 거짓이었다` | ✅ 채택 |
| B2a | 4.08–4.10 / 2.05–2.10 ms 재현, 방법 구조 타당 | 개정 4 작성 때 Python(`[159,160,...]`, `[80,81,...]`); 이번 `(0x2e-0x201)%626` → 159 | ✅ |
| B2b | 픽셀 클럭과 무관한 구간이 두 부팅을 분리 | 재실행: 증분 전체 범위(80–82, 159–160)로 R1 [1.534, 3.056], R2a [3.048, 5.964] ms — **0.008 ms 겹친다**.  B 는 81·159 한 값으로 계산 | ⚖️ 부분채택 — "거의 분리", 단정 불가 |
| B2c | 원인 후보: 부팅 때 한 번 하는 `us_spin_calibrate` | `0018aafc.c:14` `_us_spin_calibrate();`, `001a54a8.c` `_IODelay` → `_us_spin(param_1);`; 보정식의 거친 계단은 `00187980.asm` 을 읽지 않았다 | ⚖️ — 호출 구조 ✅, 계단 해석은 미확인으로 기록 |
| B3a | `IOGetTimestamp` 는 export·선언, ns, PIT 기반(지연 보정과 무관) | `kernel_symbols.py --check` → `_IOGetTimestamp in kernel`; `001a54f8.c` `_clock_value(1)`; `00187d48.asm` PIT 래치 `OUT 0x43` | ✅ |
| B3b | 비단조 창(ISR 전 두 번 읽으면 약 10 ms 뒤로) | `00187d48.asm` `MOV word ptr [0x001e75d8],SI` 뒤 `CMP SI,BX; JBE`·`ADD [EBP-0x10],0x989680`; ISR `00187844.asm` `ADD [0x001e75d0],0x989680`·`MOV [0x001e75d8],SI` — 마지막 읽은 값과 비교하므로 창이 존재 | ✅ 채택 — `t1 <= t0` → 0, 올린 spl 안에서 읽지 않음 |
| B3c | 64 비트 나눗셈 → `___udivdi3` 미존재 | `kernel_symbols.py --check ___udivdi3` → MISSING; AC97 `IntelAC97Driver.m` 1767–1792 행 주석과 `if (t1 <= t0) return 0;` | ✅ 채택 |
| B4a | 오프셋 0x09–0x0b 저장 미검사 | 계획 351 행 `MMIO 오프셋 8 의 그 밖 저장은 & 0x3f 1 바이트` 뿐 | ✅ 채택 |
| B4b | `PIXCLKS_CNTL`·`MCLK_CNTL`·`SCLK_CNTL`·`PPLL_DIV_0..2`·`X_MPLL_REF_FB_DIV`·`GEN_INT_CNTL` 쓰기 금지 규칙 없음 | `awk '/^## 7\./,/^## 8\./' 계획 \| grep -n "PIXCLKS_CNTL\|MCLK_CNTL\|SCLK_CNTL\|GEN_INT_CNTL\|PPLL_DIV_0\|X_MPLL"` → 출력 없음(rc 1) | ✅ 채택 |
| B4c | 9 단계 DAC 클럭 비트 내림의 복원이 모든 경로에서 필요 | 계획 193 행 문구 | ✅ 채택 |
| B4d | `CRTC_OFFSET_CNTL` 13 단계 기록 | 논리 | ✅ 채택 |
| B5 | 39 항목 중 실패·부분 4 | 행 27·32 는 A3d 와 같음, 행 14 는 내 오류 2, 행 22 는 문구 | ✅ |
| B6c | 2 s 창에서 FRAME 판정은 두 행을 구별 못 함(0.69 프레임) | 재실행 `2*(60.2346-59.8884)` → 0.6924 | ✅ 채택 — refdiv 되읽기가 행을 판정 |

## 3. 계획에 반영한 결정(개정 5)

1. **새 단계 R2b-0**
   - 활성화 부팅의 첫 실행은 모드 레지스터 쓰기가 없다.
   - 0–2 단계 값·PLL 블록 전체(`PPLL_DIV_0..3`)·MISC 클럭 선택·`ATTR[0x10]`·게이트 판정을 기록하고 거절한다.
   - telnet 복구를 1 회 실제 수행한다.
   - R2b 진입 게이트·refdiv 표·`PLL_DIV_SEL` 처리는 이 결과로 개정 6 에서 확정한다.
2. **`PLL_DIV_SEL` 규칙 재정의**: "bit 8–9 를 바꾸는 쓰기는 6c 뿐.  스냅샷 되쓰기(§5 4.6, R2a 중단)는 읽은 값을 그대로
   쓴다".  §5 4.6 은 스냅샷 `PLL_DIV_SEL` 이 3 이 아니면 R2b-0 뒤 개정할 때까지 도달 불가(0 단계 거절)임을 명시한다.
3. **시간**: `t1 <= t0` → 0, 차이를 32 비트로 자른 뒤 나누기, `___udivdi3`·`___umoddi3` 를 `nm -u` 금지 목록에, 올린 spl 안
   읽기 금지.
4. **호스트 규칙 추가**: 0x08–0x0b 바이트 범위 쓰기, 클럭·인터럽트 레지스터 쓰기 0, 9 단계 복원 전 경로, 각 변이.
5. **D-6 유지**, 근거에 NetBSD 추가.  진입 PVG 7 잔여 위험, 6k' 와 13 단계에 PVG 되읽기 기록, 1 단계 `PPLL_CNTL` bit 0–1.
6. **문서 수정**: G3·G4·G10 문구, 인용 줄, `dotClockRate` 행 의존, "R1 = R2a", `R2A_RESULT.md` 정정 줄.

## 4. 환경

- 검토자·재검증 모두 읽기 전용이다.  실기·네트워크 접근은 없다.
