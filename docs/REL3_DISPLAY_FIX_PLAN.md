# REL3 — 부팅 시험 패턴 잔상과 수평 위치 (v1.2 계획)

작성 2026-09-30, 1.1 공개 직후 사용자 보고 두 건.

1. OPENSTEP 로그인 화면으로 넘어갈 때 색 시험 패턴의 흔적이 남는다.
2. 화면 왼쪽에 검은 띠가 생기고 그림 전체가 오른쪽으로 밀린다. 1024x768 RGB32, 800x600 RGB32 둘 다 같다.
   **같은 캡처 경로에서 G450 은 정상이었다**(사용자, 2026-09-30).

## 1. 관측

### 1-1 캡처 측정 (사용자 캡처 `mpv-shot0001.jpg`, 800x600 RGB32, python/PIL)

| 항목 | 캡처 픽셀 | 원본 800x600 환산 |
|---|---|---|
| 캡처 크기 | 1436x1080 | 축척 가로 1436/800 = 1.795, 세로 1080/600 = 1.8 |
| 왼쪽 검은 띠 (y=50·540·1000 세 줄 모두) | x 0–23, 24 부터 배경 | 약 13 픽셀 |
| 로그인 패널 가로 | 328–1159, 중심 743.5 | 중심 414.2 (가운데 400 보다 +14) |
| 로그인 패널 세로 | 304–770 부근, 중심 약 537 | 중심 약 298 (가운데 300 과 −2) |

- 세로는 맞고, 가로만 약 13–14 픽셀 오른쪽으로 밀렸다.
- 가로 축척이 세로 축척과 같다(1.795 ≈ 1.8). 캡처는 800 픽셀 폭을 그대로 담는다.
- 그러므로 왼쪽 13 픽셀은 검정(블랭킹)이고, **그림의 오른쪽 13 픽셀은 잘린다.**

### 1-2 드라이버가 쓴 값 (실기 `/usr/adm/messages`, 1.1 이전 부팅의 R2B 되읽기)

`CRTC_H_TOTAL_DISP got=00630083`, `CRTC_H_SYNC_STRT_WID got=00100340`, `CRTC_OFFSET 0`, `CRTC_OFFSET_CNTL 0`,
`CRTC_PITCH 00640064`, `CRTC_MORE_CNTL` 은 R1 에서 0(`docs/R1_RESULT.md`).

- 모두 생성표(`osrdn_mode_expect.h`, `tools/oracle/radeon_modeset.py`)와 같다.
- 프레임버퍼 쪽도 맞다. `OSRDNDisplay.m` 은 `info->frameBuffer` 를 BAR0 매핑 그대로 주고, rowBytes 는 width×bytes 다.
- CRTC_OFFSET 은 0, 피치는 800/8 = 100 이다.
- 따라서 **데이터가 밀린 것이 아니라 동기 위치 문제**다.

## 2. 원인

### 2-1 시험 패턴 (보고 1)

`osrdn_mode.m` 진입 본문의 순서:

- step 10(1034–1035행): `skipShow` 가 0 인 진입, 곧 부팅에서 `osrdn_mode_pattern` 이 프레임버퍼 전체에 색 띠를 그린다.
- step 13(1053–1054행): `MODE_SHOW_US`(2 초, `osrdn_mode.h` 111행)를 기다린다.
- 그 뒤 **패턴을 지우지 않는다.** WindowServer 가 화면을 다 덮기 전까지 패턴이 드러난다.

이 패턴은 R2b/R3 첫 점등 때 운용자가 눈으로 확인하려고 넣은 것이다. 공개판에는 필요 없다.

### 2-2 수평 위치 (보고 2)

우리 hsync 시작값은 `hsync_start − 8` 이다. 참고 넷이 모두 같은 식이다:

- NetBSD radeonfb.c 2542행 (`/* match xf86-video-radeon */`)
- xf86-video-ati 6.14.6 legacy_crtc.c 934행
- Linux KMS radeon_legacy_crtc.c 628행
- 우리 오라클 radeon_modeset.py 58·73행

예외는 구 Linux fbdev radeonfb(`drivers/video/fbdev/aty/radeon_base.c`)다.

- CRT 에 `hsync_adj_tab[] = {0, 0x12, 9, 9, 6, 5}` 를 더한다(1645·1729·1731행).
- 32bpp 는 `radeon_get_dstbpp` → DST_32BPP 6 → 표[5] = **+5**, 15bpp +9, 8bpp +18 이다.
- 픽셀 파이프라인 지연을 bpp 별로 보정하는 것이다.
- 측정된 13 픽셀은 +5 로는 설명되지 않는다.

결론:

- 이 RV280 보드의 DAC 출력은 동기에 비해 약 13 픽셀(32bpp) 늦다.
- 참고 식 어느 것도 그 양을 주지 않는다. **실측으로 정해야 한다.**
- 같은 캡처 경로에서 G450 이 가운데였으므로 기준은 캡처 장비다. hsync 를 늦추면(시작값 +) 그림이 왼쪽으로 온다.
- 모드마다, bpp 마다 같은지는 모른다. 파이프라인 지연이면 픽셀 수가 일정하겠지만 **추정**이다. 재서 정한다.

## 3. 설계

### 3-1 패턴 → 검게 지우기

- `osrdn_mode_pattern` 을 `osrdn_mode_clear` 로 바꾼다. 같은 모양으로, 32비트 워드마다 한 번 `rdnMmioWrite32` 로 **0** 을 쓴다.
  - 0 이 검정인 근거는 네 포맷 모두에서 확인했다.
  - 부팅 진입의 팔레트는 `modeLutMake`(678행)가 만든다. 표가 아직 없으면 항등 램프라 0 번이 검정이고, BW:8 도 256 레벨이면 항등이다.
  - 16·32bpp 는 직접색이라 0 이 검정이다.
- step 10 조건(`fb != 0 && !mode->skipShow`)은 그대로 둔다. 사이클(`skipShow` 1)은 지우지 않는다. 2026-09-16 에 사이클이 데스크톱 위에 패턴을 다시 그린 사고의 규칙을 그대로 지킨다.
- step 13 의 2 초 대기를 없애고 `MODE_SHOW_US`·`wShow` 도 지운다.
  - 이 대기는 운용자가 패턴을 보라고 있던 것이다.
  - 진입 중 커널 되돌림 처리는 `modeFinish` 가 대기 유무와 관계없이 한다.
  - `wShow` 는 로그(`osrdn_modelog.m` 147행)와 시뮬레이터가 읽으므로 함께 고친다.
- `skipShow` 의 뜻은 '지우지 않음'으로 주석을 고친다.

### 3-2 hsync 위치 보정

1. **상태**: `osrdn_mode_state` 에 `long hsyncAdj`(픽셀, 부호 있음)를 둔다.
2. **값 계산**: `osrdn_mode_hsync(row, adj)` 가 쓸 워드를 만든다. `modeCrtc` 와 `modeVerify` 가 **같은 함수**를 부른다.
   - 시작 필드는 `(r->hSync & 0x1fff) + adj` 다.
   - 폭·극성 비트는 표 그대로 둔다.
   - 허용 범위는 행마다 계산한다. `start + adj ≥ hdisp − 8` 이고 `start + adj + wid×8 ≤ htotal − 8` 이어야 한다.
   - 범위 밖이면 adj 0 으로 쓰고 거절을 기록한다.
   - 1-2 의 다섯 모드에서 python 으로 계산한 공통 허용 범위는 −16 ~ +48 이고, 640x480 의 앞 포치 16 이 하한을 정한다.
3. **기본값**: 포맷별 상수표 `osrdnHsyncAdj[fmt]` 를 둔다.
   - 1차 빌드는 32bpp 에 **13**(1-1 측정)을 넣는다.
   - 16bpp·8bpp·BW:8 은 측정 전까지 13 으로 두고, 4 절 실측으로 확정한다.
4. **표 키**: `"RDN HSync Adjust"`(10진, 부호 허용)를 둔다. 있으면 기본값 대신 쓰고, 파싱 실패나 범위 밖이면 기본값을 쓰고 로그에 남긴다. 다른 모니터나 캡처 장비를 쓰는 사람을 위한 탈출구이고, 3-4 의 Configure 인스펙터가 이 키를 쓴다(사용자 요청 2026-09-30).
   - 파싱과 범위 규칙은 새 C89 헤더 `osrdn_hsyncpanel.h` 하나에 둔다. `osrdn_graypanel.h` 처럼 AppKit·driverkit·libc 를 쓰지 않는다.
   - 드라이버와 인스펙터가 같은 헤더를 import 하고, 호스트 시험이 그 헤더를 컴파일해 python 오라클과 대조한다.
5. **실시간 파라미터**: `OSRDN_HSYNC_PARAM` 은 재부팅 없이 캘리브레이션하기 위한 것이다. `{MAGIC, adj}` 를 받는다.
   - 조건: `recordEnabled` 이고 MMIO 가 매핑돼 있어야 한다.
   - 순서: `modeClaim` → 기존 래퍼(`osrdn_mode_cp`)와 같이 `kernelRevertSeen=0`·**`noSleep=1`**·`skipShow=1`·`wantRevertCheck=0` → `modeWritten` 이고 커널 되돌림이 없으며 범위 안이면 `hsyncAdj` 를 갱신하고 `CRTC_H_SYNC_STRT_WID` **한 레지스터만** 쓴다 → 되읽기 → `modeFinish`.
   - IOLog 로 `RDN-REL3 hsync adj=.. word=.. got=..` 를 남긴다.
   - CP 가 켜져 있어도 허용한다. CP 는 CRTC 타이밍 레지스터를 쓰지 않는다. 사이클과 달리 되돌림·재진입을 하지 않는다.
   - 스캔 중에 쓰면 한 프레임 동기가 흔들릴 수 있다. 되돌릴 수 있고 비파괴다.
   - 되돌림 뒤 재진입(사이클)은 `hsyncAdj` 를 그대로 쓴다.
6. **도구**: `tools/rel3/rdnhsync.m`(`tools/r2b0/rdnr2b0.m` 의 IODeviceMaster 호출 모양을 따른다). `rdnhsync <adj>` 다.

### 3-4 Configure.app 인스펙터

- "Gray Levels" 행 아래에 "Horizontal position:" 라벨, 슬라이더, 현재값 라벨을 이식한다.
  - 슬라이더는 −16 ~ +48 정수다. 다섯 모드 공통 허용 범위이고, 드라이버는 행별 범위로 다시 검사한다.
  - 템플릿은 실기에서 쓰인 `openstep-spacesaver2ps2/ref/nibtemplates/PS2MouseInspector.xml` 의 Slider(oid 21)와 라벨(23)이다.
- `tools/r3/build-inspector-nib.py` 에 행을 더한다. 26-4 규칙대로 GROW 를 다시 계산하고, `check_nib_r3d.py` 도 새 행에 맞춘다.
- `setTable:` 은 키를 읽어 슬라이더와 라벨을 맞춘다. 없거나 잘못된 값이면 기본값을 보인다.
- 슬라이더 동작은 라벨을 갱신하고 키를 `NXCopyStringBuffer` 10진 문자열로 쓴다.
- 캡션은 "takes effect after the next reboot" 를 유지한다.
- 이 칸은 **다음 부팅부터** 적용된다. 이번 캘리브레이션의 실시간 조정은 3-2 의 5–6(`rdnhsync`)이 맡는다.

### 3-3 호스트 검사

- `tools/r2b/check_r2b_src.py`: 순서 목록의 `osrdn_mode_pattern` → `osrdn_mode_clear`. '한 가지 방법으로만 쓴다' 규칙을 유지하고, **쓰는 값이 0** 이라는 규칙을 새로 둔다. 둘 다 변이로 확인한다.
- `tools/r2b/sim_r2b.py`: 패턴 합 표(`pattern_sum`)를 0 표 또는 '전부 0' 검사로 바꾼다. 변이 문자열 162–164·220–226행을 새 이름과 새 동작으로 바꾼다.
- `tools/r2b/sim/simworld2b.c`:
  - 프레임버퍼 쓰기 검사를 '정확히 한 번 덮고 값은 모두 0' 으로 바꾼다.
  - `wShow` 조건(993·999·1018행)을 제거한다.
  - hsync 기대값을 `osrdn_mode_hsync` 로 받는다. 기본 adj, 표 키 adj, 범위 밖 adj, 이렇게 세 경우를 넣는다.
- `tools/r2b0/check_reloc_r2b0.py` 106행: `_rdnMmioWrite32` 허용 호출자 `_osrdn_mode_pattern` → `_osrdn_mode_clear`.
- 새 python 규칙: `osrdn_mode_hsync` 의 범위 식이 3-2 의 식과 같은지, 다섯 모드 × adj −64..+320 전 조합을 python 오라클과 대조한다(호스트 컴파일한 C 와 비교).
- `tools/check-all.sh` 는 마지막에 한 번만 돌린다.

## 4. 실기 절차

1. 빌드(`target-build-r2b0.sh`) → `check_reloc_r2b0.py` → `host_release_gates.py --driver` → `nm -u` 대조.
2. 설치하고, 사용자가 재부팅한다. 부팅 모드는 현재 Instance0.table 그대로다.
3. **캡처 1**: 사용자가 로그인 화면을 캡처한다. 판정 두 가지:
   - 로그인 전환에 패턴이 없는가(눈으로).
   - 1-1 과 같은 python 측정으로 띠 폭과 패널 중심을 잰다. 목표는 띠 0, 중심 오차 ±1 픽셀이다.
4. 어긋나면 `rdnhsync <adj>` 로 바꿔 가며 다시 캡처한다. 재부팅은 필요 없다.
5. 다른 해상도(800x600 ↔ 1024x768)는 Display Mode 를 바꾸고 재부팅해서 3–4 를 반복한다.
6. 16bpp·8bpp 는 사용자가 원하면 같은 방식으로 잰다. 재지 않으면 32bpp 값을 쓰고 **미측정**으로 적는다.
7. 측정값으로 기본값 표를 확정한다. 1차와 다르면 재빌드 → 설치 → 재부팅 → 캡처로 최종 확인한다.

## 5. 공개

- Version 1.2(Default/Instance0.table, `pkg/OSRDNDisplay.info`), `RELEASE_NOTES_v1.2.md`, README.
- 패키지는 `/me/packages/drivers/OSRDNDisplay/` 에 두고, 1.1 은 `/me/packages/old/OSRDNDisplay-1.1/` 로 옮긴다.
- 커밋과 공개는 설치 시험이 통과한 뒤에 한다. HANDOFF 3 절의 commit-tree 방식을 따르고, 판정표만 싣는다.
- 검사 패턴 이름은 글자 그대로 쓰지 않는다.

## 6. 교차검토 판정표

| # | codex 주장 | 내 검증 방법 | 판정 |
|---|---|---|---|
| X1 | step 13 대기를 빼도 정확성은 같다: `wShow` 를 읽는 곳은 로그뿐이고, 진입 중 되돌림은 `modeFinish` 가 처리한다 | `osrdn_mode.h` 105–118행(PLL 은 별도 50 ms), `osrdn_mode.m` 133–150행(대기는 계수만), 1300–1325행(바쁠 때 `kernelRevertSeen`) 을 열어 봄. `grep -rn wShow` 결과: `osrdn_modelog.m` 147행(편집 전)과 `simworld2b.c` 993·996·999·1018 뿐. 로그의 `sh=` 를 읽는 판정 스크립트 grep 0 건 | ✅ 채택. 로그의 `sh=` 필드도 뺀다 |
| X2 | 실시간 파라미터에 `noSleep=1` 이 빠졌다 | `osrdn_mode_cp` 1450–1454행: claim 직후 `noSleep = 1 /* setIntValues must not sleep */` | ✅ 채택(3-2 의 5 수정) |
| X3 | `kernelRevertSeen` 을 리셋하지 말라 | 같은 래퍼 1452행이 claim 직후 0 으로 리셋한다. claim 이 비었을 때 온 되돌림은 `osrdn_mode_revert`(1300–1325행)가 스스로 claim 을 잡고 끝낸다 | ❌ 기각. 기존 래퍼와 같이 리셋한다 |
| X4 | 되돌림은 스냅샷 값을 쓴다 | `osrdn_mode.m` 1240행 `mode->snap.mmio[SNAP_CRTC_H_SYNC]` | ✅ 사실 |
| X5 | 재진입이 보정을 유지하려면 `modeCrtc`·`modeVerify` 둘 다 공유 계산을 써야 한다 | 544·775행이 `r->hSync` 를 그대로 쓴다 | ✅ 이미 3-2 의 2 에 있음 |
| X6 | CP 내부가 H_SYNC 를 건드리는지 모른다 | `grep -n "H_SYNC\|0x0204\|0x204" osrdn_cp.m osrdn_engine.m osrdn_cpu.m osrdn_window.m osrdn_vmap.m` 결과 0 건 | ✅ 건드리지 않음 |
| X7 | 슬라이더 이식은 라디오 매트릭스와 같은 graft→attach→reindex·커넥터 절차로 된다. 다만 outlet·action 은 새로 선언해야 한다 | `build-inspector-nib.py` 144–194행(add_label·add_matrix 의 절차, `add_connector` 두 개), `OSRDNDisplayInspector.h` 에 `grayMatrix` 만 있음 | ✅ 채택 |
| X8 | PS2 인스펙터는 `setMinValue:`/`setMaxValue:` 를 부르지 않는다. 범위는 nib(50–400)에 있다 | `SS2MouseInspector.m` 116–117·219–231행, `PS2MouseInspector.xml` 슬라이더 셀 값 400·50·350 | ✅ 사실. 범위는 nib 셀에 −16/+48 로 넣고, 동작에서 `intValue` 로 정수로 맞춰 다시 `setIntValue:` 한다 |
| X9 | 라벨 23 은 Helvetica-Oblique(글꼴 25)이고 스크립트는 글꼴 10 만 사상한다 | XML 553행대 `oid 25 Font Helvetica-Oblique`, 스크립트 140행 `LABEL_MAP` | ⚖️ 사실이지만 기존 Gray Levels 라벨·캡션도 같다(1.0 부터 실기에 나감). 이번엔 바꾸지 않는다 |
| X10 | GROW 57 assert 를 새 행 높이로 다시 계산해야 한다 | 스크립트 67–71행 `GROW = GAP_ABOVE + TOP - STOCK_CHILD_Y; assert GROW == 57` | ✅ 채택 |

## 7. 실기 결과 (2026-09-30)

첫 빌드: stamp 97d449e6, runid 790769823, 기본값 13.
- 실기 빌드 OSRDNBUILD PASS(reloc sum `35544 535`), `check_reloc_r2b0.py` PASS, `host_release_gates.py --driver` PASS.
- `nm -u` 는 1.1(790754867)과 바이트로 같다(21 개, 실기 `cmp`).
- pkg 는 `build/rel3-pkg.sh` 로 만들었다. build·verify·BOM 겹침 모두 PASS.

**부팅 02e5e8cb (800x600 RGB:888/32)**
- 로그: `RDN-REL3 hsync adj=13 kbad=0`, 되읽기 `CRTC_H_SYNC_STRT_WID got=0010034d`(= 표 `00100340` + 13, python 확인).
- 사용자 관찰: 처음엔 "왼쪽 띠·오른쪽 잘림 없음". 이어서 **"오른쪽에 검은색이 생겼다"**.
- `rdnhsync 0` → 되읽기 `00100340`. 사용자: "왼쪽에 검은띠가 생겼다".
- `rdnhsync 7`(0 과 13 의 가운데, python 6.5 → 7) → 되읽기 `00100347`. 사용자: **"지금이 딱 맞다"**.

**부팅 043eb660**
- 설치된 `Instance0.table` 에 `"RDN HSync Adjust" = "7";` 을 넣었다(677 → 703 바이트, 원본 백업 `/usr/local/rel1/Instance0.table.pre-hsync7`).
- 로그: `adj=7 kbad=0`, 되읽기 `00100347`.
- 사용자: 재부팅 화면·부팅 화면·로그인 화면 이상 없음.

**종료·부팅 화면의 띠**
- 사용자: 종료 화면은 보이지만 왼쪽·아래쪽에 검은 영역이 있고, **드라이버 적재 전의 부팅 화면도 같다**.
- 종료 때 드라이버는 부팅 스냅샷을 그대로 되돌린다. 스냅샷 `CRTC_GEN_CNTL 02000200` 은 확장 표시(bit 24)가 꺼진 VGA 타이밍이고, `CRTC_H_SYNC_STRT_WID` 스냅샷 `000002a0` 은 되돌림 뒤 그대로다.
- 그러므로 BIOS·커널 VGA 출력의 성질이다. 고치지 않는다(콘솔 복원 원칙).

**결정**: 기본값을 7 로 바꾼다(사용자, 2026-09-30).
- 바꾼 곳: `osrdn_modesel.h`, `osrdn_hsyncpanel.h`, nib 슬라이더 초기값, 오라클 `modesel_oracle.py`, `sim_r2b.py`, `test_modesel.py` 손 사례, 변이 앵커, `rdnhsync.m` 주석.
- 1024x768 은 7 로 보지 않았다(노트에 적는다).

**최종 빌드 (기본값 7)**
- `pack_r2b0.py` stamp **ddbbfa6c**, runid **790772415**.
- 실기 OSRDNBUILD PASS(reloc sum `00799 535`), `check_reloc_r2b0.py` PASS, `host_release_gates.py --driver` PASS.
- `nm -u` 는 1.1 과 같다(21 개, `cmp`).
- pkg 는 `build/rel3-pkg.sh` CHAIN PASS. 기본값 13 빌드는 `/me/packages/old/OSRDNDisplay-1.2-default13/` 로 옮겼다.
- 설치 전에 설치된 표를 키 없는 원본으로 되돌렸다.
- 부팅 e94e38ae:
  - `RDN-R2B0 init build=ddbbfa6c`, 표에 HSync 키 0 줄
  - `RDN-REL3 hsync adj=7 kbad=0`, 되읽기 `00100347`
  - 사용자 확인: 슬라이더 7
- 호스트 검사:
  - hostcheck-r2b0(pack), sim_r2b 97 PASS, check_r2b_src, test_modesel, test_inspector_gray, test_inspector_hsync, check_nib_r3d, hostcheck_inspector
  - check-all 의 관련 11 항목(check_sources, sync_docs, 인용 자가 시험, mutate_gen_r3, check_bundle_modes, check_target_r3, check_select, check_reloc_cclines, check_notice_nib, check_tool_mode, radeon_modeset)
  - 전 문서 인용 검사(재조준 112 개, bare 인용 1 개 교정)
  - **전체 check-all 은 사용자 결정으로 생략**(2026-09-30): 바뀌지 않은 CP·3D·Mesa 검사가 대부분이다.
