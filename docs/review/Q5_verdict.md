# Q5 판정 — R1 조사 계획, R0-2·R0-3 설계 초안

질문 `Q5_prompt.md`, 회신 `Q5_reply.md` (gpt-5.6-sol, read-only, 2026-09-15).
인용 72곳을 Python 으로 범위·기대 문자열 대조 → 72 일치.  계산(생존 판정 창)은 Python 으로
재계산해 일치.  계획을 바꾸는 주장은 본문을 직접 읽었다.  `N/` = NetBSD `radeonfb.c`,
`X/` = xf86-video-ati 6.14.6 `src/`.

## 내가 틀렸던 것 (먼저)

| 내 문서 | 사실 | 근거 |
|---|---|---|
| R0-2 §4 단계 6 "`CRTC_EXT_CNTL`: `XCRT_CNT_EN | VGA_ATI_LINEAR`" — `CRT_ON` 누락 | 두 참고 모두 `CRTC_CRT_ON` 을 세운다("unconditional turn on CRT").  새 값으로 쓰면 주 CRT 가 꺼질 수 있다 | `N/:2500-2516`, `X/legacy_output.c:960-967` 열람 |
| R1 §4-B 생존 판정 "FRAME ≥1 증가 **그리고** VLINE ≥2 값" (8 표본 × 2 ms) | 창이 14 ms 뿐이라 640×480@59.94 에서 0.839 프레임 → 경계를 못 볼 확률 16.1 %, 720×400@70.09 에서 1.9 % | Python: `(8-1)*2 = 14 ms`, `25.175e6/800/525 = 59.940 Hz`, `14e-3*59.94 = 0.839` |
| R1 §3 등급 A 를 "읽기" 로 부름 | 메커니즘 #1 은 호스트 브리지의 **전역 `0xCF8` 주소 래치**에 쓴다 | Matrox probe `OpenStepMGAProbe.m:68-75` 열람 — "대상 장치 쓰기 없음" 으로 표기 |
| R1 §6 C2 "누락 시 재실행" | R1 §2 의 "같은 조작 재시도 금지" 와 충돌 | 두 줄 모두 내 문서(`R1_INTERROGATION_PLAN.md:31-32, 103`) |
| R1 §6 에 호스트 판정 목록 없음 | 셰도 판정(55 AA·ROM 크기·체크섬·PCIR 경계·vendor/device·포인터 경계)이 상위 PLAN 에만 있었다 | `PLAN.md:235-238` vs R1 §6 |
| R0-2 §4 단계 3 "초과 시 중단·복원" | PLAN 금지 8 은 실패를 **추가 GPU 읽기 전에 RAM 에 기록**하고 영구 걸쇠를 요구 — 순서가 초안에 없었다 | `PLAN.md` 금지 8 |

## 판정표

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| 1a | 명명 31 레지스터 읽기에 문서화된 부작용은 없다(`GEN_INT_STATUS` 는 쓰기로 ack) | `F/radeon_irq.c:137,165`, `N/:2954-2955` 인용 통과; 앞서 내 조사와 같음 | ✅ |
| 1b | `IOMapPhysicalIntoIOTask` 의 캐시 속성은 헤더로 미확인, `IODirectDevice` 매핑만 캐시 인자가 있다 | `kernelDriver.h:85-93`, `IODirectDevice.h:75-85`, `driverTypes.h:53-59` 인용 통과 | ✅ 사실. 단 Matrox H1 S2 에서 이 API 가 **실측으로 uncached** 였다(프로젝트 기록) — RV280 에서도 VLINE 변화로 재확인 |
| 1c | 0x342c 근거는 RV280 경로에 대해 유효(radeonfb 는 RV280 을 R300 으로 분류하지 않고 비-R300 flush 가 0x342c 접근) | `N/:313-320, 504-522, 3796-3807` 인용 통과 | ✅ |
| 1d | 그래도 BAR2 크기는 측정 안 됨 → BAR 0 거절, 64 비트 메모리 BAR 처리, Command Memory Enable 확인, 타입 비트 마스크, 브리지 창 포함 확인 | 사실 | ✅ **채택** — R1 §4-B 사전 검사로 |
| 2 | 생존 판정은 AND 로는 부당; VLINE 만 짧게, FRAME 은 두 프레임 넘는 별도 관찰, VGA 모드에서 FRAME 이 도는지 미확인 | Python 재계산(위), `radeon_irq.c:294-318` 은 VGA 모드 의미를 말하지 않음 | ✅ **채택** — 게이트는 VLINE(8 표본 서로 다른 값 ≥2), FRAME 은 60 ms 두 표본을 **기록만**(Python: 2 프레임 = 33.4 ms) |
| 3 | C1 이 가장 깨끗하나 헤더로 미확인, C2 는 순번·체크섬 없으면 불가, C3 기각, R1 문서에 판정 목록 필요 | `conf.h:64-79`(장치 틀만), `IOFrameBufferDisplay.h:63-69`(인스턴스 메서드) 인용 통과 | ✅ 채택 — C2 는 순번·체크섬 + 한 번에 완전해야 판정, 불완전이면 **재시도 없이 C 항목 실패로 기록** |
| 4a | `CRT_ON` 누락 | 위 "틀렸던 것" | ✅ 채택 |
| 4b | DAC 전원(`DAC_CNTL.DAC_PDWN`, `DAC_MACRO_CNTL` RGB 전원), `GRPH_BUFFER_CNTL`(FIFO 임계), `CRTC_MORE_CNTL`(센터링·컷오프), 픽셀 클럭 게이트, 공용 클라이언트, 비활성 출력 정책이 빠졌다 | `X/legacy_output.c:808-842`, `X/legacy_crtc.c:1590-1655`, `X/radeon_reg.h:419-423` 본문.  **그러나 주 참고 radeonfb 는 `GRPH_BUFFER_CNTL`·`DAC_MACRO_CNTL`·DAC 전원 비트를 쓰지 않고 `CRTC_MORE_CNTL` 은 출력만 한다**(`N/` 에서 grep: `CRTC_MORE_CNTL` 한 곳 `:2336` PRINTREG, 나머지 0 건) | ⚖️ **부분 채택** — "필수" 가 아니라 xf86 만의 조치다.  R1 에서 네 레지스터를 읽고(`GRPH_BUFFER_CNTL`, `CRTC_MORE_CNTL`, `DAC_MACRO_CNTL`, `MEM_SDRAM_MODE_REG`), R2 계획에서 값을 보고 정한다.  픽셀 클럭 게이트 해제·공용 클라이언트 0 쓰기는 radeonfb 도 하므로 채택(`N/:2266-2271, 2373-2383`) |
| 4c | 비활성 출력은 "안 건드림" 이 아니라 "비활성임을 확인하고 아니면 중단" 또는 명시적 끔·복원 | 사실(정책 문제) | ✅ 채택 — 확인 후 중단안 |
| 4d | `DAC_VGA_ADR_EN` 은 xf86 만 세움 | `X/legacy_output.c:1515-1517`, radeonfb `:762-765` 는 안 세움 | ✅ 미확인으로 기록 |
| 5 | VGA MISC ↔ `PPLL_DIV_n` 대응은 미확인; 가장 안전한 설계는 xf86 방식(DIV3 사용, DIV0–2 보존, 복귀 시 PPLL 공통·DIV3·`VCLK_ECP_CNTL` 복원 후 `CLOCK_CNTL_INDEX` 복원, VGA MISC 도 복원).  `radeon_reg.h` 는 "r128 에서 변환, Radeon 에서 틀린 정의가 있다" 고 경고 | `X/radeon_reg.h:44-52` 경고문 본문, 나머지 인용 통과 | ✅ 채택 — R0-2 §5-1 을 "DIV3" 로 결정 제안 |
| 6 | 확장 비트 해제만으로 VGA 타이밍이 돌아온다는 근거 없음; xf86 은 표준 VGA 레지스터·폰트까지 복원 | `X/radeon_driver.c:5763-5779, 5904-5917` 인용 통과 | ✅ 채택 — 표준 VGA 레지스터 스냅샷·복원(Matrox 3-52~3-54 와 같은 방식) |
| 7a | 텍스트 콘솔이면 **`enterLinearMode` 를 거절**해야 한다 | Matrox `REMAINING_WORK.md:3350-3358`(폰트 저장·복원 후 기본값 승격), `:3505-3513`("TEXT 라면 여기서 멈춘다 — 폰트 평면 저장·복원이 먼저") 본문.  둘 다 **복원 기능을 켜는 일**을 멈춘 것이지 모드 진입을 막은 것이 아니다.  실패 결과는 종료 중 검은 콘솔이고 다음 부팅 BIOS 가 복구한다 | ⚖️ 부분 — 진입은 막지 않는다.  텍스트 콘솔이면 복원을 **무장하지 않고** 기록, 폰트 평면 저장·복원은 텍스트일 때 복원 기능의 선행 조건 |
| 7b | R0-2 가 Q2 판정 항목을 아직 다 반영하지 않았다 | 사실(4b 와 같은 목록) | ✅ 채택 |
| 7c | 타임아웃 처리 순서(RAM 기록 → 걸쇠 → 복원) 누락 | 위 "틀렸던 것" | ✅ 채택 |
| 7d | C2 재시도 충돌 | 위 | ✅ 채택 |
| 7e | Matrox probe 뼈대의 `Load_Commands.sect` 는 stage 4(쓰기) 로 무장돼 있다; 소스 패턴 검사만으로는 컴파일된 경로를 보장 못 한다 | `Load_Commands.sect:19` `CALL openStepMGAProbeEntry 4`, `OpenStepMGAProbe.m:284-430` 인용 통과 | ✅ **채택** — R1 probe 는 뼈대를 복사하지 않고 새로 쓰며, 빌드 게이트가 `Load_Commands.sect` 와 **목적 파일**(`objdump` 로 `out` 명령·포트 상수)도 검사 |

## 2차 자기검사

✅ 행 재확인: 1c·1d·5·6·7e 는 인용 대조 + 본문(4b·5·7a 는 위 범위를 직접 열었다).  4b 는 codex
결론을 그대로 받지 않고 radeonfb 전수 grep 으로 "xf86 만의 조치" 임을 확인해 부분 채택으로
바꿨다.  7a 는 Matrox 기록 두 곳을 열어 codex 결론이 기록보다 강함을 확인했다.  수치(0.839,
16.1 %, 1.9 %, 33.4 ms, stop_req 256→0x7c)는 Python 출력이다.
