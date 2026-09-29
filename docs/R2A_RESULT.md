# R2a 결과 — 2026-09-15 실기

**게이트 PASS**
- `parse_r2a.py build/r2a/789467668/rdn-r2a-789467668.log 789467668 a917b913 build/r1/rdn-r1-789453017.log 789453017 --out build/r2a/789467668` 가 `R2A: PASS` 로 끝났다.
- 타깃 빌드 `R2ABUILD PASS`: `nm -u` 10 개가 모두 커널에 있다(`_splhigh`·`_splx` 포함).
- 역어셈블 게이트 `check_reloc.py` PASS: reloc sum `08016 90`.
- 실행 `R2ARUN DONE`: `kl_util -a/-l/-u/-d` 가 모두 exit 0 이다.

`CLOCK_CNTL_INDEX` 바이트 저장 20 번(묶음 10 × 인덱스·복원)이 행 없이 끝났다.  32 비트 되쓰기는 한 번도 일어나지 않았다(중단 없음).  실행 뒤 타깃은 정상이다: 적재 잔여 없음, WindowServer·gcdsd·nxlogd 살아 있음.

**실행 기록**(`build/r2a/`)
- 패키지: `RDNR2aProbe-a917b913-789467668.tar`(sum `44553 50`)
- 타깃 빌드 출력: `build-789467668.log`
- `789467668/` 안: `RDNR2aProbe_reloc`, `reloc.sum`, `R2ARELOC_PASS`, `run.out`, `run.done`, `rdn-r2a-789467668.log`, `r2a-facts-789467668.txt`
- 호스트 nxlogd 사본 `logs/kernel-20260915-191924.log` 에도 같은 81 줄이 있다.

## 0. 실행 전후

- **실행 전 재부팅**(operator): 실행 전 재부팅이 종료 후반에 멈췄다.
  - 타깃 `/usr/adm/messages` 에서 `reboot: rebooted by root` → `syslogd: going down on signal 15` 뒤 기록이 없다.
  - 원인은 미확인이다.  R2a 코드는 그때 실기에 닿지 않았다.  후보는 R1c 때 멈춘 채 남았을 수 있는 백그라운드 `ps ax` 다(미확인).
- **operator 재부팅 뒤 기반 복구**: `/ndrv` 마운트 → gcdsd(cwd `/ndrv` 확인) → nxlogd.
- **호스트 결함 1 건 — `pack_probe.py`**
  - hostcheck PASS 문자열을 R1 의 `hostcheck: PASS` 로 찾았다.  R2a hostcheck 는 `hostcheck-r2a: PASS` 를 찍으므로 패킹을 거절했다.
  - 거절 쪽 결함이라 안전했다.  하니스는 `--skip-hostcheck` 로만 패키저를 돌려 이 경로를 못 봤다.
  - 문자열을 고치고, 두 파일의 문자열이 같음을 확인했다.
- **발행 확인**: 타깃에서 `target-build.sh`(7542 바이트, sum `35450 8`), `target-run.sh`(6307, `31431 7`), tar(51200, `44553 50`) 의 `wc -c`·sum 이 호스트와 같다.
- **`uname`**: 타깃 sh 경로에 `uname` 이 없다(`uname: not found`).  사실 줄 하나가 빠졌을 뿐 판정과는 무관하다.

## 1. PLL 인덱스 동작 (이번 실행의 주 목적)

| 항목 | 관측 | 뜻 |
|---|---|---|
| `p0` | `00000303` | WR_EN 0, `PLL_DIV_SEL` 3.  R1 과 같다 |
| 바이트 레인 | 10 묶음 모두 `c = (p & ~0xff) \| idx` | 8 비트 저장이 bit 8–31 을 보존한다.  NetBSD 식 32 비트 저장이었으면 `PLL_DIV_SEL` 이 0 이 됐을 것 |
| DATA 읽기 부작용 | 모두 `d = c` | DATA 읽기가 인덱스를 바꾸지 않는다 |
| 복원 | 모두 `e = p` | 복원 바이트 저장 뒤 인덱스가 원래 값이다 |
| 묶음 사이 | 모든 `p = p0` | 실행 동안 인덱스를 바꾼 다른 쓰기가 없다 |
| 예약 bit 6 | 되읽기 0 | 남는 위험 4 는 이 카드에서 해당 없음 |
| WR_EN 래치 | 관측 불가 | WR_EN 이 한 번도 서지 않았다.  미확인으로 남는다 |

## 2. PLL 값 (Python 으로 풀이, 정의는 xf86 `radeon_reg.h`)

| 인덱스 | 이름 | 값 | 풀이 |
|---|---|---|---|
| 0x02 | `PPLL_CNTL` | `0000a700` | 설정된 비트 8·9·10·13·15.  `RESET`(0)·`SLEEP`(1)·`ATOMIC_UPDATE_EN`(16)·`VGA_ATOMIC_UPDATE_EN`(17)·`ATOMIC_UPDATE_VSYNC`(18) 모두 0 |
| 0x03 | `PPLL_REF_DIV` | `00000006` | refdiv **6**(`REF_DIV_MASK` 0x3ff), bit 15 0 |
| 0x04 | `PPLL_DIV_0` | `00070086` | fb 134, post 코드 7(/12) |
| 0x07 | `PPLL_DIV_3` | `00030047` | fb **71**, post 코드 **3**(/8, xf86 `post_divs` 표) |
| 0x08 | `VCLK_ECP_CNTL` | `000000c3` | 소스 3 = `PPLLCLK`, `PIXCLK_ALWAYS_ONb`·`PIXCLK_DAC_ALWAYS_ONb` 1 |
| 0x09 | `HTOTAL_CNTL` | `00000000` | `HTOT_CNTL_VGA_EN` 0 |
| 0x0a | `X_MPLL_REF_FB_DIV` | `006a510c` | 기록만 |
| 0x0d | `SCLK_CNTL` | `00007ffa` | 기록만 |
| 0x12 | `MCLK_CNTL` | `aa3f1212` | 기록만 |
| 0x2d | `PIXCLKS_CNTL` | `0000f8c0` | 기록만 |

**콘솔 픽셀 클럭**(Python): 27000 kHz × 71 / 6 = VCO **319500 kHz**(BIOS PLL 범위 200–400 MHz 안), / 8 = **39937.5 kHz**.
- VESA 800×600@60(40.000 MHz) 에 맞는다.  부팅 로그의 `VGADisplay: Mode Selected: 800 x 600 @ 60 Hz`·`VESA mode selected: 0x6a` 와도 맞는다.
- CRTC 워드는 800×600, 총 1024×626 이다.  이 총합이면 62.30 Hz, 60 ms 에 3.74 프레임이고 실측 `frame60` 은 +4 다.
- 콘솔이 `EXT_DISP_EN` 0 인 VGA 코어 구동이라 CRTC 워드가 실제 스캔아웃 값인지는 여전히 미확인이다.

**R1c BIOS 표와 다른 점**: BIOS PLL 정보의 refdiv 는 12 인데, 레지스터(VESA BIOS 모드셋 결과)는 6 이다.
- ~~R2b 는 `PPLL_REF_DIV` 를 자기 계산값으로 쓴다(xf86 방식).~~ **정정(2026-09-15, Q11)**: R2 계획 개정 4·5 는 레지스터 refdiv 를 그대로 쓴다(NetBSD 방식, 계획 G3).  xf86 의 CRT 경로는 refdiv 를 직접 탐색한다.
- 복귀 스냅샷은 이 레지스터 값 6 을 복원해야 한다.  BIOS 표 값 12 가 아니다.

## 3. 추가 레지스터 15 개

| 레지스터 | 값 | 비고 |
|---|---|---|
| `CRTC_OFFSET_CNTL` | `10000000` | |
| `DISP_MERGE_CNTL` | `ffff0000` | |
| `TV_DAC_CNTL` | `07660142` | |
| `DISP_HW_DEBUG` | `00020000` | |
| `OVR_CLR`·`OVR_WID_LEFT_RIGHT`·`OVR_WID_TOP_BOTTOM` | 0·0·0 | |
| `OV0_SCALE_CNTL` | `807f0000` | 방해 클라이언트 중 유일하게 0 이 아님.  설정 비트 16–22·31, `SCALER_ENABLE`(bit 30) 은 0 — 오버레이 스케일러는 꺼져 있다 |
| `SUBPIC_CNTL`·`VIPH_CONTROL`·`I2C_CNTL_1` | 0·0·0 | |
| `CAP0_TRIG_CNTL`·`CAP1_TRIG_CNTL` | 0·0 | |
| `MEM_CNTL` | `32003200` | bit 0(`MEM_NUM_CHANNELS_MASK` 0x01) = 0 → xf86 RV280 분기에서 RamWidth 64 |
| `MEM_TIMING_CNTL` | `1a395323` | |

R1 레지스터 33 개(휘발 2 개 제외)는 R1 과 모두 같다.  `CLOCK_CNTL_INDEX` 는 bit 8–31 만 비교했고, 그 값도 `00000303` 로 같다.

## 4. 브리지·기타

- **`00:1e.0`**(카드 경로, 버스 3): 브리지 제어 `000c`, **VGA 전달 1**.
- **`00:03.0`**(버스 2, 카드 경로 아님): 제어 `0004`, VGA 전달 0.
- **생존 표본 간격**(기록, 게이트 아님): VLINE 증분을 콘솔 줄 속도(39937.5 kHz / 1024)로 환산했다(Python).
  - 이번 실행에서 `IODelay(2000)` 한 번이 **약 4.1 ms** 였다(증분 159–160 줄).
  - 같은 방법으로 R1 로그를 계산하면 약 2.05–2.10 ms(80–82 줄) 다.  R1 은 PLL 을 읽지 않았으므로, R1 CRTC 워드가 같다는 점에 기대어 같은 콘솔 클럭이라고 가정한 값이다.
  - 부팅마다 지연 보정이 두 배 차이 날 수 있다는 뜻으로 읽힌다.  원인은 미확인이다.
  - R2 의 대기 시간은 `IODelay` 인자를 믿지 말고 VLINE·프레임 계수로 확인할 것.
- **R1 판정 재확인**: `MC_FB_LOCATION` 시작 0 과 RV280 정렬 애퍼처 기준 `e0000000` 은 다르다(R1 과 같음).  CP 꺼짐, GART 꺼짐, PCI 버스마스터 켜짐도 R1 과 같다.

## 5. R2 계획에 넘기는 것

1. `CLOCK_CNTL_INDEX` 바이트 저장은 상위 비트를 보존한다(실측).  R2b 의 PLL 접근 규칙(xf86 `OUTREG8`)을 이 카드에서 확인했다.
2. 복귀 스냅샷의 PLL 값은 위 표다.
   - 콘솔 모드는 `PLL_DIV_SEL` 3, `PPLL_DIV_3` = `00030047`, `PPLL_REF_DIV` = 6, `VCLK_ECP_CNTL` = `c3`, `PPLL_CNTL` = `a700`.
3. `OV0_SCALE_CNTL` 이 0 이 아니다(`807f0000`, `SCALER_ENABLE` 0).
   - xf86 `RADEONInitCommonRegisters` 는 이 값을 0 으로 두고, 공통 레지스터 복원에서 그대로 쓴다.
   - R2b 가 xf86 을 따라 이 레지스터를 쓸지, 복귀 목록에 원래 값을 넣을지는 R2 계획에서 정한다.
4. `IODelay` 실제 길이가 부팅마다 달라질 수 있다(2.05 ms 대 4.1 ms).  PLL 안정 대기 등은 하한만 믿고, 필요하면 VLINE 으로 잰다.
5. 미확인으로 남는 것: WR_EN 래치 방식, 콘솔 CRTC 워드와 실제 스캔아웃의 관계, 멈춘 재부팅의 원인.
