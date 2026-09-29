# Q8 판정 — R2 첫 점등 계획서 codex 검토 재검증

작성 2026-09-15.  입력: `docs/review/Q8_reply.md`(codex `gpt-5.6-sol`, 검토 대상
`docs/R2_FIRST_LIGHT_PLAN.md` 초안).  **codex 회신은 검증 대상 입력이다.**  아래 모든 행은 이 세션에서
원문을 열거나 Python 으로 다시 계산한 것만 적었다.  인용 줄번호는 `tools/oracle/check_citations.py`
로 기계 대조한다.

## 0. 내가 틀린 것 (먼저)

1. **R2a 를 살아 있는 소유자 밑에서 따로 돌리려 했다** — 내가 근거로 든 Matrox 선례가 정반대였다:
   Matrox 스냅숏은 `enterLinearMode` 안, 모드를 다시 쓰기 직전에 돌았고 "읽기만" 이라는 표현이 거짓이었다고
   스스로 기록했다(`REMAINING_WORK.md:3330-3336`).  그리고 Radeon 의 VGA **MMIO 미러를 쓰는 참고 구현은
   없다**(참고 트리 `.c` 전수 grep: `CRTC8_IDX`·`SEQ8_IDX`·`GRPH8_IDX`·`ATTRX`·`GENFC_WT`·`DAC_W_INDEX`
   0 건).  xf86 은 표준 I/O 함수를 쓴다(`radeon_driver.c:3134-3137`).
2. **§5 팔레트 "8 비트 램프, 스냅샷 없음"** — R2a 가 팔레트를 읽는다고 적어 놓고 복원은 생성 램프로 적은 모순.
   xf86 은 실제 값을 30 비트로 저장한다(`radeon_driver.c:4478-4488`).
3. **FIFO(`GRPH_BUFFER_CNTL`) 를 계산 없이 "쓰지 않는다"** 로 정했다.  xf86 은 모드마다 계산해 쓰고
   (`legacy_crtc.c:1650`) 복귀 때 되돌린다(`radeon_driver.c:5849`).
4. **§7 R1c 게이트가 실패할 수 없다**("통과 또는 기본값 사용 기록").
5. **§7 "대기 루프 진입 수 > 0"** — xf86 주석이 대부분의 칩은 첫 검사에서 통과한다고 적는다
   (`legacy_crtc.c:216-228`).  건강한 카드가 게이트에서 떨어진다.
6. **§4 14 단계에 BAR0 `0xe0000000` 을 박았다** — 같은 문서 §6 과 PLAN 의 "BAR 런타임 읽기" 와 모순.
7. **§6 옵트인 재해석을 PLAN 개정 없이 적었다** — PLAN §4 는 "새 하드웨어 동작은 config 키로 옵트인,
   기본값 꺼짐" 이다.  예외를 두려면 PLAN 을 먼저 고쳐야 한다(아래 D-3).
8. **F2 "radeonfb 처럼 통째로 쓰지 않는다"** — radeonfb 는 `CRTC_EXT_CNTL` 을 **`DISPLAY_DIS` 하나만 남기고**
   새로 짓고(`radeonfb.c:2500-2516`), `DAC_CNTL` 은 범위·블랭킹만 남긴다(`radeonfb.c:760-766`).  "미정의
   비트 전부 보존" 은 두 참고 어디에도 없는 형태였다.

## 1. 판정표

기호: ✅ 채택(검증됨) · ⚖️ 부분 · ❌ 기각(반증) · ⚠️ 미확인으로 남김.

### 1-A. 사실 해석 (codex §1)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| A1 | F1: `CRTC_GEN_CNTL=02000200` → `EXT_DISP_EN`=0, VGA 코어 구동 | Python: bit 9·25 만, pix 2, `EXT_DISP_EN`(bit 24) 0, `CRTC_EN`(bit 25) 1 — `radeonfbreg.h:439`·`:446-447` | ✅ |
| A2 | F2: 미정의 비트 보존이 참고와 다르다 | `radeonfb.c:2500-2516`(`v &= RADEON_CRTC_DISPLAY_DIS`), Python: R1 값에서 NetBSD 식이 버리는 비트 `0x36080000` | ✅ (내 오류 8) |
| A3 | F6: "`CP_CSQ_CNTL=0`, AIC translation 은 bit 7, `DAC_MACRO_CNTL=0`, `CRTC2_GEN_CNTL=0`" | 원시 로그: `CP_CSQ_CNTL=02010080`(모드 bit 28–31 = 0 → 꺼짐), `DAC_MACRO_CNTL=00000607`, `CRTC2_GEN_CNTL=04000000`; `radeonfbreg.h:3248-3249` 의 `PCIGART_TRANSLATE_EN` 은 **bit 0**.  codex 의 원시 로그 줄번호도 어긋남(37 행은 `DAC_CNTL2`, 44 행은 `MEM_SDRAM_MODE_REG`, 55 행은 `GRPH_BUFFER_CNTL`) | ⚖️ 결론(꺼짐·유휴)은 맞고 **값·비트·줄 인용은 틀림** |
| A4 | F6: `GEN_INT_STATUS` 같은 상태 레지스터를 동일성 게이트에 쓰지 말 것 | 원시 로그 `GEN_INT_STATUS=00080007`, R1 `VLINE`/`FRAME` 은 표본마다 변함 | ✅ R2a 재측정 게이트에서 휘발 레지스터 제외 |
| A5 | F7: TV DAC 미측정, `DISP_OUTPUT_CNTL` bit 28 미해석 | `docs/R1_CLOSES.md` 에 `TV_DAC_CNTL` 은 R2 항목; Python: `DISP_OUTPUT_CNTL` DAC 소스 0·TVDAC 소스 0, bit 28 은 `radeonfbreg.h:661-676` 정의 밖 | ✅ 진입 전 게이트로 |
| A6 | F8: FIFO 불필요는 따라 나오지 않는다 | xf86 `legacy_crtc.c:1587-1650`; NetBSD `radeonfb.c` 에 `GRPH_BUFFER_CNTL` 0 건(grep) | ✅ (내 오류 3).  Python: xf86 식의 start/stop 은 RV280(`radeon.h:326` RV100 계열) 상한 `0x5c` = 92 로 **BIOS 값과 같다**; `BUFFER_SIZE`=1·`CRITICAL_CNTL`/`AT_SOF`/`STOP_CNTL`=0 도 같다.  **다른 것은 critical point(BIOS 32) 뿐**이고 이 값은 메모리 타이밍·클럭에서 계산된다 |
| A7 | F9: 브리지 prefetch 창은 256 MiB, 512 MiB 는 MC 범위 | Python: `win24=eff0e000` → `e0000000–efffffff` = 256 MiB; MC_FB `00000000–1fffffff` = 512 MiB | ✅ 수치.  ❌ "계획이 섞었다" — 계획 F9·`R1_RESULT.md` 어디에도 브리지 창을 512 MiB 로 적지 않았다 |
| A8 | F10 명령 `0x0307` | 원시 로그 cfg 00 바이트 `0703` | ✅ |

### 1-B. PLL 인덱스 (codex §2)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| B1 | NetBSD 읽기는 32 비트 인덱스 쓰기로 `PLL_DIV_SEL` 을 지우고 xf86 은 바이트 쓰기 | `radeonfb.c:1572-1585`, `radeon_driver.c:609-621`; Python: `0x303` 에 바이트 쓰기 → DIV_SEL 3 유지, 32 비트 쓰기 → 0 | ✅ |
| B2 | 바이트 쓰기는 소유자와의 동시성 장치가 아니다 | 논리.  generic VGA 드라이버가 `CLOCK_CNTL_INDEX` 를 건드리는지는 바이너리라 확인 불가 | ✅ 잔여 위험으로 기록 (§2 D-1) |
| B3 | VGA 코어 구동 중 `PLL_DIV_SEL` 의 영향 미확인 | 참고에서 결론 줄 근거 없음 | ⚠️ 그대로 미확인 — 모든 경로가 bit 8–9 를 보존·원래 값 복원 |

### 1-C. MC 맵 (codex §3, 차단 1)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| C1 | 두 참고 모두 소유 시 `MC_FB_LOCATION` 을 애퍼처에 맞춘다 | `radeonfb.c:2872-2880`, `radeon_driver.c:1498-1513`; Python: 이 카드에서 둘 다 `0xe7ffe000` | ✅ 사실 |
| C2 | BIOS 맵(FB 내부 주소 0) 에서 BAR0 CPU 접근이 VRAM 시작에 닿는지 증거 없음 → 차단 | xf86 에는 **FB 를 내부 주소 0 에 두는 경로**가 있다: 구 DRI 에서 `mc_fb_location = (mem_size - 1) & 0xffff0000U`(`radeon_driver.c:1485-1488`) — 시작 0, CPU 는 그대로 PCI BAR 로 접근.  FreeBSD DRM 은 칩에 이미 있는 `MC_FB_LOCATION` 을 읽어 쓴다(`radeon_cp.c:1312-1314`).  PLAN R2 는 "MC 맵은 R1 값과 다를 때만 다시 쓴다"(PLAN 270 행) | ⚖️ **기각: "참고가 요구한다"** — 참고 자체가 시작 0 맵을 운용한다.  **채택: 잔여 위험 명시** — BIOS 창 끝이 `1fff`(512 MiB) 로 xf86 구 DRI 식(`07ff`, VRAM 크기) 과 다르다.  첫 점등 스캔아웃은 앞 3 MiB 라 창 끝과 무관, R5 에서 다시 판단.  실패 증상은 행이 아니라 어긋난 그림(맵을 쓰지 않으므로) |

### 1-D. 진입 시퀀스 (codex §4)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| D1 | 블랭크가 `DISPLAY_DIS` 하나뿐 — HSYNC/VSYNC_DIS 와 요청 차단을 함께 | NetBSD `radeonfb_blank` 은 세 비트(`radeonfb.c:2699`); xf86 DPMS off 는 세 비트 + `DISP_REQ_EN_B`, 그리고 **`CRTC_EN` 을 내린다**(`legacy_crtc.c:697-698`); xf86 복원은 먼저 `RADEONBlank`(`radeon_driver.c:5837`).  NetBSD modeswitch 는 시작 블랭크가 주석 처리(`radeonfb.c:2365`) | ✅ xf86 DPMS-off 형식 그대로 |
| D2 | 방해 클라이언트 확인이 12b 로 늦다 | NetBSD 는 CRTC 전에 0 으로 씀(`radeonfb.c:2373-2404`) | ✅ 0 단계(첫 쓰기 전) 로 이동 |
| D3 | PLL 원자 갱신을 쓰기 단위로 적을 것 | xf86 `legacy_crtc.c:330-400`: CPU 클럭 → `PPLL_CNTL`(RESET·ATOMIC·VGA_ATOMIC·PVG) → DIV_SEL=3 → REF_DIV → **DIV_3 FB 필드 → DIV_3 POST 필드(두 번)** → 쓰기 전 대기+W → 읽기 완료 대기 → HTOTAL → 리셋 해제 → 50 ms → PPLL 선택.  NetBSD 는 DIV_0·DIV_SEL 0, 같은 값 두 번(`radeonfb.c:2237-2238`) | ✅ 계획이 "FB·POST 필드" 한 줄로 뭉갰다 |
| D4 | `VCLK_ECP_CNTL` 전후 전환은 맞다 | `radeonfb.c:2168-2337`, `legacy_crtc.c:330-400` | ✅ |
| D5 | `HTOTAL_CNTL=0` | `legacy_crtc.c:1269`(`HTotal & 0x7`); Python 1344 & 7 = 0.  추가 발견: `HTOT_CNTL_VGA_EN` 이 bit 28(`radeonfbreg.h:1048-1049`) → 복귀 때 스냅샷 값 필수 | ✅ |
| D6 | 피치를 하나로; xf86 형은 `0x00800080` | `legacy_crtc.c:954-958`, `radeonfb.c:2438`·`:919-920`; Python: xf86 128·128, NetBSD 4096/32 = 128 | ✅ `0x00800080`(PLL 순서를 따르는 xf86 경로와 일치, 하위 필드는 두 참고 동일) |
| D7 | 30 비트 팔레트는 8 비트 입력을 상위 8 비트로 | `radeonfb.c:2959-3001`; Python `0xff<<22` → R 필드 `0x3fc` | ✅ |
| D8 | `GRPH_BUFFER_CNTL` 계산 또는 증명 | A6 | ✅ xf86 식을 호스트 오라클로, 입력은 R1c·R2a |
| D9 | `DISP_MERGE_CNTL` RGB_OFFSET_EN 내림 | `radeonfb.c:2580-2594` | ✅ |
| D10 | 확장 CRTC 전환 개념은 맞고 마스크는 미정 | A2 | ✅ NetBSD 식 채택 (§2 D-2) |
| D11 | 출력 경로·TV DAC 게이트 | NetBSD 는 `TV_DAC_CNTL` 에 `0x00280203` 을 쓴다(`radeonfb.c:768-775`); xf86 주 DAC 초기화는 `DAC2_DAC_CLK_SEL` 을 내리고 `DAC_CNTL` 을 새로 짓는다(`legacy_output.c:1498-1519`) | ✅ 쓰지 않고 R2a 로 측정·진입 전 동일성 게이트 |
| D12 | FB 지우기는 블랭크 중에 — "NetBSD 는 마지막 언블랭크 전에 지운다" | NetBSD `radeonfb_modeswitch` 끝에서 **이미 언블랭크**(`radeonfb.c:2404`), 지우기(`radeonfb.c:977-978`)는 그 뒤; Matrox 는 언블랭크 뒤 FB clear 로 PASS(Matrox `docs/TEST_STATUS.md` 51 행) | ⚖️ **근거는 틀림**.  권고는 채택(내 판단: 옛 VRAM 노출 방지, 비용 없음) |
| D13 | BAR0 하드코딩 | 계획 97 행 vs 127 행, PLAN 265 행 | ✅ (내 오류 6) |

### 1-E. 복귀 (codex §5)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| E1 | xf86 은 VGA 모드·폰트 저장, 복원 순서 = 블랭크 → FIFO → 맵·공통 → 팔레트 → CRTC → PLL → `CLOCK_CNTL_INDEX` → VGA → DAC 마지막 | `radeon_driver.c:5818-5932`(5837 블랭크, 5849 FIFO, 5852-5870, 5873 인덱스, 5914 vgaHW, 5920-5928 DAC 마지막) | ✅ |
| E2 | 실제 팔레트 복원 | 내 오류 2 | ✅ 30 비트 경로로 저장·복원(DAC 폭과 무관) |
| E3 | SEQ 리셋·화면 끔·CR11 해제·ATTR/PAS·SEQ 재시작 | Matrox `osmgaVgaRestore`(Matrox `OpenStepMGAReplacementDisplay.m` 1985–2050 행, 이 세션에서 열어 확인) | ✅ |
| E4 | 텍스트면 **첫 쓰기 전에 활성화 거절** | Matrox 는 거절하지 않고 복원만 무장 해제(같은 파일 7625–7641 행).  이 기계의 Matrox 실측은 진입 시 그래픽(`attr10 01`, Matrox `docs/REMAINING_WORK.md` 3520 행·3654 행) | ⚖️ 사실은 맞고 **처방 기각**: VGA 드라이버를 뺀 부팅에서 진입 거절은 쓸 수 있는 콘솔을 주지 않는다.  Matrox 형태 유지 + 로그 |
| E5 | 부분 스냅샷 정리 | 계획은 `hardwareTouched` 전에 인덱스 쓰기가 있었다 | ✅ `hardwareTouched` 를 **첫 쓰기 직전**에 세우고 VGA 스냅숏을 블랭크 뒤로 |
| E6 | `CLOCK_CNTL_INDEX` 는 마지막 PLL 인덱스 조작 | `radeon_driver.c:5873` 이 PLL·팔레트 뒤 | ✅ |
| E7 | super revert 와 하드웨어 복원 순서 명시 | Matrox 7630 행 부근 `[super revertToVGAMode]` 먼저 | ✅ (계획 §6 에 이미 있었음, §5 에 명시) |

### 1-F. R2a · R1c · 게이트 · 복구 (codex §6–9)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| F1 | VGA MMIO 미러 동등성 미확인 | 내 오류 1(grep 0 건) | ✅ |
| F2 | 살아 있는 소유자 밑 R2a 제거 | 내 오류 1, PLAN 125 행 | ⚖️ **VGA 표준 레지스터·팔레트 접근은 제거(채택)**.  MMIO 읽기와 PLL 바이트 인덱스 읽기만 남긴다 — R2b 컴파일 입력(refdiv·FIFO 입력·TV DAC)이 필요하고, 데이터 쓰기 없음·bit 8–9 보존.  잔여 위험(B2) 은 D-1 로 운영자 결정 |
| F3 | `/dev/mem` 읽기 안전 미확인 | R1 로그 3 행 `/dev/mem` 존재(codex 는 2 행 `/dev/kmem` 을 인용); R1 계획 §6 C1 미검증 기록 | ✅ 미확인 유지.  완화: 먼저 512 바이트만 읽고 ROM 크기 바이트만큼만 두 번째로 읽는다(POST 가 실행한 이미지 안) |
| F4 | BIOS PLL 오프셋 일치 | `radeonfb.c:1709-1726`, `radeon_bios.c:997`·`:1017`(+0x0e/+0x10/+0x12(32)/+0x16(32), mclk +8·sclk +10) | ✅ |
| F5 | 파서 게이트 보강(경계·그럴듯함·실측 refdiv 대조) | R1 계획 §6 은 크기·체크섬을 경고로만(142–146 행) | ✅ |
| F6 | R1c 게이트 항진 | 내 오류 4 | ✅ |
| F7 | 루프 진입 > 0 게이트 | 내 오류 5 | ✅ 조건 평가 횟수 ≥ 1·상한 도달 0 으로(PLAN 185 행 "양의 계수" 유지) |
| F8 | 종료 중 복귀 실패 위치는 로그로 안 보인다 | `REMAINING_WORK.md:3640-3647`(종료 경로는 revert 를 부른다) 과 이어지는 줄의 `syslogd: going down` | ✅ 판정은 operator 육안 + 진입 경로 로그 |
| F9 | telnet 과 독립인 복구 경로가 없다 — codex 인용 "RECOVERY_REHEARSAL.md 37 행" | 그 파일은 **없다**.  같은 내용은 Matrox `docs/RECOVERY_REPLACEMENT_DRIVER_EXECUTION_PLAN.md` 38 행("별도 physical/serial console 없음"), 깨진 화면 부팅에서 telnet 생존은 미증명(Matrox `docs/TEST_STATUS.md` 33 행) | ⚖️ 사실 채택, 경로 인용은 틀림.  독립 경로는 이 기계에서 **미확인**(부트 로더 선택지 자료 없음) → 운영자 결정 D-4 |
| F10 | PLAN 옵트인 규칙 위반 | PLAN 178 행(codex 는 171 행 인용 — 절 머리) | ✅ 사실(내 오류 7).  처방(키 추가) 은 D-3 |
| F11 | DriverKit 프레임버퍼 계약 명시 | Matrox 4000–4020 행 `displayInfo` 필드, 형식표 1536–1545 행(`RGB:888/32`, `IO_24BitsPerPixel`, `IO_RGBColorSpace`, `--------RRRRRRRRGGGGGGGGBBBBBBBB`) | ✅ |
| F12 | codex 가 인용한 Matrox 경로 `driver/OSMGADisplay/...` | 실제는 `openstep-matrox-remade/OSMGADisplay/...`(find).  줄번호 1819·1863·1925·1988·4004·7630 은 각 블록 안 | ⚖️ 경로 틀림, 내용 맞음 |

## 2. 결정이 필요한 것

- **D-1 (R2a 잔여 위험)**: MMIO 읽기 + PLL 바이트 인덱스 읽기만 하는 R2a 를 살아 있는 generic VGA 밑에서
  돌린다.  데이터 레지스터 쓰기는 없다.  generic VGA 가 `CLOCK_CNTL_INDEX` 를 쓰지 않는다는 증거는 없다.
  → 채택하되 계획서에 잔여 위험으로 적고 **다음 codex 라운드 질문**으로 보낸다.
- **D-2 (`CRTC_EXT_CNTL` 형식)**: 주 참고(BSD) 형식 — 원래 값의 세 DIS 비트만 남기고
  `XCRT_CNT_EN|VGA_ATI_LINEAR|CRT_ON`.  R1 값의 미정의 비트 `0x36080000` 은 진입 동안 내려가고
  복귀에서 스냅샷으로 돌아온다.
- **D-3 (옵트인)**: `Default.table` 키가 기본 꺼짐이면 드라이버는 모드를 안 쓰는데 VGA 가 빠진 부팅이라
  **화면 소유자가 없다** — 키가 안전을 더하지 않는다.  → PLAN §4 에 "디스플레이 소유자 교체
  자체는 `Active Drivers` 편집이 옵트인" 이라는 **명시적 예외를 operator 승인으로** 넣는다.  승인 전에는
  R2b 코드를 쓰지 않는다.
- **D-4 (독립 복구 경로)**: Matrox 는 telnet 단일 채널로 첫 활성화를 통과했다(같은 기계).  이 기계에서 부트
  로더 대안(단일 사용자·다른 설정)은 자료가 없어 미확인.  → operator 가 (a) Matrox 와 같은 telnet 단일 채널을
  수용하거나 (b) 콘솔·부트 선택지를 먼저 확인한다.

## 3. 2차 자기검사

✅ 행을 다시 읽으며 근거 칸을 대조했다:

- 인용 줄번호: 이 문서의 백틱 인용은 `check_citations.py docs/review/Q8_verdict.md` 로 기계 대조(결과는
  아래 실행 기록).  Matrox·PLAN·R1 로그처럼 인용 검사기 경로 밖인 것은 **행 번호를 산문으로** 적었고
  모두 이 세션에서 `sed -n` 으로 열었다.
- 계산: A6·A7·B1·C1·D5·D6·D7 과 §2 D-2 의 값은 이 세션의 Python 출력
  (`blank GEN 0x4000200 EXT 0x36088740`, `GEN program 0x7000600`, `EXT program (blanked) 0x8748`,
  `unblank EXT 0x8048 GEN 0x3000600`, `DAC netbsd 0xff000102`, `pitch 0x800080`,
  `pref window 0xe0000000 0xefffffff 256 MiB`, `netbsd mcfbloc 0xe7ffe000`, `xf86 stop/start 92`).
- 부재 주장: "Radeon VGA MMIO 미러 사용 참고 0 건", "NetBSD `GRPH_BUFFER_CNTL` 0 건", "`RECOVERY_REHEARSAL.md`
  없음" 은 grep·find 출력으로 확인.
- ⚠️ 남김: B3(`PLL_DIV_SEL` 의 VGA 코어 영향), C2 잔여(BAR0 ↔ 내부 0 을 이 카드에서 실측한 적 없음),
  F3(`/dev/mem` 커널 동작), F9(독립 복구), D-1(generic VGA 의 PLL 인덱스 사용).

## 정오표

- 2026-09-15 (Q9): §2 D-2 의 "원래 값의 세 DIS 비트만 남기고" 는 NetBSD 식이 아니라 xf86 마스크 + NetBSD 비트 조합이다(NetBSD 는 `DISPLAY_DIS` 하나만 남긴다) — `docs/review/Q9_verdict.md` §0-1.
