# G2 — 1024×768 RGB:888/32 인데 색이 16비트처럼 보인다 (2026-09-26)

사용자 관찰: "1024x768 에 RGB 32 인데 화면에 보이는 컬러는 RGB 16 처럼 보입니다. matrox 때랑은 다르게 보이네요."

## 1. 하드웨어 쪽은 로그로 배제 (부팅 e70f08b0, 드라이버 4a5edb03, `build/g1/run-790387796/boot.drv`)

| 항목 | 값 | 근거 |
|---|---|---|
| CRTC 픽셀 형식 | `want=6 got=6` (32bpp ARGB) | `RDN-R3 verify` 줄 |
| DAC_CNTL | `ff000102` = MASK_ALL·**DAC_8BIT_EN**(bit 8)·range 2 | 같은 줄 `dac=`; `osrdn_mode.m:596-598` `modeDac` |
| LUT 워드 배치 | `(r<<22)|(g<<12)|(b<<2)` 를 `PALETTE_30_DATA` 에 | `osrdn_mode.m:740`, `osrdn_snap.m:315`; NetBSD `radeonfb.c:2995-2996` 과 같다 |
| LUT 되읽기 | `verifylut bad=0`, `xfer … lutbad=0`, `bright … lutbad=0` | 상위 8비트 전부 일치 |
| 출력 경로 | FP_GEN_CNTL = 0 (R2a 탐침 `rdn-r2a-789467668.log:52`), 모드셋 게이트 `GATE_FPON` 이 FPON=0 을 요구 | 아날로그 DAC 출력, TMDS 18비트 패널 형식 문제 아님 |
| WindowServer 에 알린 형식 | `IO_24BitsPerPixel`, `"--------RRRRRRRRGGGGGGGGBBBBBBBB"` | `osrdn_mode_expect.h:274`; Matrox `OpenStepMGAReplacementDisplay.m:1538` 과 같은 문자열 |

## 2. 남은 차이 하나 — LUT 에 실리는 **전송표**

- WindowServer 는 `IO_DISPLAY_HAS_TRANSFER_TABLE`(`OSRDNDisplay.m:451`) 을 보고 256 항목 표를 보낸다(Matrox `TEST_STATUS.md:84` 실측).  이번 부팅: `RDN-R3 xfer n=1 count=256 … xferdata sum=4a4a9a00 first=000000ff last=ffffffff ident=0`.
- python 역산: 그 합에서 Σv = **44699**(항등이면 32640).  감마 2.2 리프트 `255·(k/255)^(1/2.2)` 의 합 44824 와 거의 같다 — **어두운 쪽을 크게 올리는 곡선**이다(S3 예제의 내장 `gamma8`(`S3ProgramDAC.m:162`) 도 같은 모양: 0,15,22,27,31… 합 43334).
- 우리 드라이버는 이 표를 **32bpp 에서도 LUT 에 그대로 싣는다**(`osrdn_mode.m:709`, `osrdn_mode.m:720-732` `modeLutMake`).  NeXT 의 S3·QVision 예제도 그렇게 한다(`S3.m:59-87` `setTransferTable:` 이 24bpp 에서도 표를 받아 `S3ProgramDAC.m:195` `setGammaTable` 로 DAC 에 싣는다).
- **Matrox 재작 드라이버는 다르다**: RGB 직접색에서는 표를 **캐시만 하고 LUT 는 선형 램프**(모드셋 `OpenStepMGAReplacementDisplay.m:4751` 의 `f->isPseudo` 조건, `OpenStepMGAReplacementDisplay.m:4775-4789` "8bpp/32bpp RGB … 256-entry ramp" `v = i`).  8bpp 의사색에서만 표를 싣는다.
- 8비트 입력→8비트 출력 LUT 에 2.2 리프트를 걸면: k=1→15, k=2→22 … 어두운 16 단계가 출력 0–72 로 벌어지고(계단이 보인다), 밝은 56 단계(200–255)가 출력 25 단계로 눌린다.  **화면이 밝고 계조가 뭉개져 "16비트처럼" 보이는 것과 부합한다.**  Matrox 에서는 이 곡선이 걸린 적이 없다.

## 3. 재부팅 없이 확인 — 유저랜드에서 전송표를 바꿔 본다

- 경로: `IODeviceMaster lookUpByDeviceName:"Display0"` → `setIntValues:… forParameter:"IOSetTransferTable" count:256` (`displayDefs.h:176` "packed RGBM", `IO_SET_TRANSFER_TABLE`).  우리 `setIntValues:` 는 CYCLE·ENGINE·RECORD 이름만 잡고 나머지는 superclass 로 넘긴다(`OSRDNDisplay.m:597`, `OSRDNDisplay.m:734-735`).  superclass 가 개수(24bpp = 256)를 검사하고 `setTransferTable:count:` 를 부른다(24-1 커널 사실).  드라이버는 곧바로 LUT 에 적용한다(이번 부팅 `xfer … applied=1`, `lutBase` 는 `mmioMapped && recordEnabled`).
- 도구 `tools/r3/rdnxfer.m`: 텍스트 파일의 256 워드(16진)를 읽어 보낸다.  표는 호스트 python 이 만든다: `ident`(0xkkkkkkff), `g22`(감마 2.2 리프트, 되돌리기용 근사).  결과는 `RDN-R3 xfer n=2 …`/`xferdata sum=` 줄로 확인(항등이면 `ident=1`).
- 안전: 쓰는 것은 LUT 256 항목뿐(모드·CRTC·PLL 무관).  되돌리기는 `g22` 를 다시 보내거나 재부팅.  CP·teapot 에는 영향 없음(LUT 는 스캔아웃 뒤 단계).
- 판정: 사용자가 항등표 뒤의 화면을 보고 "Matrox 때와 같다" 면 원인 확정.

## 4. 그 뒤의 결정(사용자 몫)

- A. Matrox 재작과 같게: RGB 직접색(888/32·555/16)은 선형 램프, 표는 8bpp·BW 에서만.  사용자가 이미 눈으로 받아들인 형제 드라이버의 규칙.  드라이버 변경 → 마지막 재부팅에 릴리스 검증과 함께.
- B. NeXT 예제(S3·QVision) 그대로 두기(지금).
- 어느 쪽이든 `docs/R3_MULTIMODE_PLAN.md` 24 의 설계 결정을 갱신한다.

## 5. 실기 판정과 드라이버 변경 계획 (2026-09-26)

**판정**: 항등표를 보내자(`RDN-R3 xfer n=2 result=1 applied=4 lutbad=0`, `xferdata sum=00007f00 ident=1`) 사용자: "matrox 처럼 보입니다."  → 원인은 LUT 에 실린 WindowServer 감마 곡선.  결정 A(Matrox 규칙) 채택.

**변경 (드라이버, `osrdn_mode.m` `modeLutMake` 한 곳)**
- `direct = (f != 0 && f->ioColorSpace == RGB(2) && !f->pseudo)` — 888/32·555/16.
- direct 이면 표 분기를 타지 않는다(표는 그대로 저장·계수·로그; LUT 만 선형).  RGB:256/8(`pseudo`)·BW:8 은 지금처럼 표를 싣는다(8bpp 의사색에서 표는 컬러맵이다 — Matrox `OpenStepMGAReplacementDisplay.m:4751`).
- 선형 램프: 888/32 는 `k`; **555/16 은 `((k>>3)*255)/31`** — 카드가 5비트 성분으로 LUT 를 `v*8..v*8+7` 로 찾으므로(Xorg depth 15 `OUTPAL(idx*8+j)`, 우리 표 분기의 `rep=8` 과 같은 사실) `k` 그대로면 최대 248 로 3 % 어둡다(Matrox `OpenStepMGAReplacementDisplay.m:4758-4773` 15bpp 주석과 같은 이유; Xorg `drmmode_display.c:1643-1651`·`radeon_driver.c:3326-3334`).
- 밝기 배율·Gray Levels·되읽기·kick/defer 는 그대로.  `IO_DISPLAY_HAS_TRANSFER_TABLE` 광고도 그대로(Matrox 도 전 형식 광고; 표는 8bpp 에 필요).

**오라클·시험 (`tools/r2b/sim_r2b.py` `lut_rule`, `tools/r2b/sim/simworld2b.c`)**
- `lut_rule(mono, gray, entries, level, direct, bpp15)`: direct 면 entries 무시, bpp15 면 확장 램프.
- 세계 시험: 표 배관 시험(즉시 적용·밝기·257/255 항목·저장 뒤 진입·순환 재진입)은 **RGB:256/8(fmt 2)** 로 옮겨 표가 보이게 유지; 새 시험 3: (a) 888/32 에 T1 → 결과 APPLIED 이고 LUT 는 램프, (b) 555/16 에 T3 → 확장 램프(`simxLutRamp15`), (c) 밝기 32 를 888/32 에 → 램프 절반.  Gray Levels 는 BW:8 그대로.
- 변이 2: "direct 도 표를 싣는다"(`&& !direct` 제거), "555 램프를 확장하지 않는다".

**뒤처리**: `docs/R3_MULTIMODE_PLAN.md` 24 에 결정 갱신 한 줄, 인용 등록, `check-all.sh` PASS, 빌드·`nm -u` 검사 → **마지막 재부팅(3/3)** 에 릴리스 검증(`run_g1.sh` 한 바퀴 + 화면 확인)과 함께.

## 6. codex 교차검토 판정표 (계획 단계, 2 회)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 항등표 실험: 되돌리기가 근사(`g22`)라 정확하지 않다 | python 으로 합 `4a4a9a00` 을 재현하는 식을 탐색 → `floor(255·(k/255)^(1/2.2))` 유일 해, 묶음 합 일치 (`tools/r3/gen_xfer.py`) | ✅ 채택 — 정확한 원표를 재전송할 수 있게 함 |
| 적용은 LUT 외에 픽셀클록 게이트·PLL 인덱스도 잠시 바꾼다 (`osrdn_mode.m:607-617`, `osrdn_mode.m:770-783`) | 원문 확인: `modePalette` 가 `VCLK_ECP_CNTL` 을 껐다 켜고 `modeLutApply` 가 인덱스를 되돌린다 — WindowServer 의 표가 부팅 때 지난 것과 같은 경로 | ⚖️ 사실, 새 위험 아님 |
| 클레임 충돌 시 실패 대신 지연 적용 (`osrdn_mode.m:1609-1611`) | 원문 확인(`lutDeferred++`, `MODE_LUT_DEFERRED`); 이번 실행 로그 `result=1 applied=4` 로 즉시 적용 증명 | ⚖️ 사실, 이번엔 해당 없음 |
| 항등표로도 같게 보이면 LUT 는 원인이 아니다 | 판정 기준에 넣음 (3절) | ✅ 채택 |
| `direct = cspace 2 && !pseudo` 가 888/32·555/16 만 고른다 (`osrdn_mode_expect.h:274`-277) | 표 행 확인: 256/8 은 `pseudo=1`, BW:8 은 색공간 1 | ✅ |
| Xorg depth 15 는 `index*8+j` 에 같은 값 복제 (`radeon_driver.c:3326-3334`), `break` 없이 16 으로 떨어짐(`:3336`) | 원문 확인 (`drmmode_display.c:1643-1651` 도 같다) | ✅ — 555 램프 `((k>>3)*255)/31` |
| fmt 2 는 시뮬레이터에서 진입 가능, `modeInit` 이 fmt 를 0 으로 되돌리니 시험마다 다시 지정 | `simworld2b.c:1036`(전 형식 행렬)·`simworld2b.c:387` 확인 | ✅ 채택 — 배관 시험마다 `mode.fmt = 2` |
| `verifyLut` 는 진입이 만든 `modeLut` 과 비교하므로 어긋남 없음 (`osrdn_mode.m:1020-1021`, `osrdn_mode.m:837`) | 원문 확인 | ✅ |
| 전 형식 행렬이 모든 형식에 `k` 램프를 강제 (`simworld2b.c:1093`, 편집 뒤 줄) | 원문 확인 → fmt 1 은 `simxLutRamp15` | ✅ 채택 |
| stuck-LUT 시험이 색인 7 을 쓰는데 555 램프의 0–7 은 0 이라 못 잡는다 (`simworld2b.c:1526`, `simworld2b.c:1535`, 편집 뒤 줄) | 원문 확인(`palette[7] = 0`, 시뮬레이터 훅 `simworld2b.c:207`) → 색인 15 로 | ✅ 채택 |

결과: `tools/r2b/sim_r2b.py` PASS — 베이스라인 25 검사, 변이 90 개 전부 잡힘(새 변이 2: "direct 도 표를 싣는다", "555 램프를 펴지 않는다"; 빠진 555 표 시험 대신 BW:8 에 32 항목 표를 펴는 시험으로 기존 변이 유지).

## 7. 설치 (부팅 3 용, 2026-09-26)

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** (sim_r2b 변이 90 포함) |
| 타깃 빌드 **`38fd8446`** / runid 790393645, 미정의 심볼 21(지난 4a5edb03 과 같음) | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — `/private/Devices/OSRDNDisplay.config/OSRDNDisplay_reloc` sum 62877 495 = BUILD_PASS, `Instance0.table` = 1024×768 RGB:888/32 |

부팅 3(마지막) 절차: 마운트 → gcdsd(telnet) → `osrdncaps` 로 `build=38fd8446` 확인 → **사용자가 화면 색을 본다**(항등 LUT 상태여야: Matrox 와 같게) → `/usr/adm/messages` 의 `RDN-R3 xfer n=1 … result=1 lutbad=0` 과 `verifylut bad=0` → `RUNID=1790272700 BOOT=<nonce> BUILD=38fd8446 R=1 bash build/g1/run_g1.sh` → `judge_teapot`.  옵션(화면 확인용): `rdnxfer ws22.txt` 로 감마표를 다시 보내 LUT 가 **바뀌지 않음**을 로그(`xfer n=2 result=1`)와 화면으로 확인 — 직접색은 표를 무시하므로 화면이 그대로여야 한다.

## 8. 부팅 3 (드라이버 38fd8446, 부팅 e67d7442, 2026-09-26)

- 사용자: "화면 색은 matrox 처럼 잘 보이는군요."  — 드라이버가 스스로 램프를 실은 상태(항등표 도구 없이).
- 로그: `select 1024x768 RGB:888/32`, `verify want=6 got=6 dac=ff000102`, `verifylut bad=0`, `xfer n=1 count=256 result=1 applied=1 lutbad=0`, `xferdata sum=4a4a9a00 ident=0`(WindowServer 는 같은 감마표를 보냈고 드라이버는 받아 저장만 했다), `bright level=64 lutbad=0`.
- 릴리스 검증 `run_g1.sh R=1` → 아래 9 절.

## 9. 부팅 3 릴리스 검증 결과 — PASS (`build/g1/run-790394588`)

- 8 조합(64·256·640×480·1024×768 × 일반·컬링) 완주, `judge_teapot --recovered 1` **PASS**, 울타리 밖 변화 0, glFinish 동기 전부 1, 걸쇠 0.
- 멈춤 1 회: **세 부팅 연속 같은 제출**(sub 410, 컬링 64×64 의 26 번째, 153 워드, `rptr=0x800` 페이지 경계, 큐 비어 있음, kick 무효) → `recover=2 recovers=1`, 7 삼각형 소프트웨어 대체.  결정적이므로 원인은 페이지 경계 + 그 스트림 내용의 조합이다 — 원인 추적은 G1 밖(참조도 리셋으로 다룬다).
- G1 통과 기준 전부 충족 + G2 화면 색 정상.  **재부팅 예산 3/3 소진, 실기 검증 종료.**
