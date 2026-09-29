# R1 — 카드 설치 뒤 조사 계획 (하드웨어 쓰기 없음)

작성 2026-09-15.  **계획**이다 — 교차검토 → 재검증 → 코드 순서.  상위 계획은
`PLAN.md` R1, 사실은 `ANALYSIS.md`.  실기로 확인한 것은 없다.

**구현 상태(2026-09-15)**: A·B 는 `probe/RDNR1Probe` 로 구현, 호스트 게이트
`tools/r1/hostcheck.sh` 9 단계 PASS(§7).  구현하면서 계획과 달라진 곳은 본문에
**[구현]** 으로 표시했다.  C 는 probe 에 없다(§6), D 는 `target-run.sh` 가 적재 전에 기록한다.

## 1. 목적 — 무엇에 답하나

| 질문 | 쓰이는 곳 | 답하는 항목 |
|---|---|---|
| 이 카드의 ID·rev·subsystem, BAR 값, 브리지 창 | 매칭, 매핑 | A |
| 스캔아웃이 살아 있고 MMIO 매핑이 캐시 없이 디코드되는가 | 모든 뒤 단계 | B-live |
| 보고 VRAM(`CONFIG_MEMSIZE`), 애퍼처(`CONFIG_APER_SIZE`), `HDP_APER_CNTL` | 매핑 길이, 오프스크린 창 | B |
| BIOS 가 둔 MC 맵(`MC_FB/AGP_LOCATION`, `DISPLAY_BASE_ADDR`) 과 RV280 정렬 규칙 만족 여부 | R2 "바뀔 때만 MC 쓰기" | B |
| 콘솔이 쓰는 PLL 분주 슬롯(`CLOCK_CNTL_INDEX` bits 8-9) | R0-2 §5-1, R0-3 §3 | B |
| 출력 경로(CRTC1/2 켜짐, `DAC_CNTL2`, `DISP_OUTPUT_CNTL`, `FP_GEN_CNTL`) | R2 "배선을 건드리지 않는다" 의 전제 | B |
| CP·버스 마스터·GART 가 BIOS 에서 꺼져 있는가 | R2 단계 3, R5 | B |
| 콘솔의 현재 CRTC 타이밍(해상도 추정) | R0-3 복귀 판정 참고 | B |
| BIOS PLL 블록(refclk/minpll/maxpll, BIOS refdiv) | PLL 계산 입력 | C |
| `/dev/mem` 이 있는가 | C 의 방식 선택 | D (셸 한 줄) |

## 2. 전제와 복구

1. operator 가 G450 을 빼고 Radeon 을 꽂고, **Active Drivers 를 generic VGA 로** 둔
   부팅(`OSMGADisplay` 가 남아 있으면 먼저 되돌림).  이 부팅의 화면·telnet 이 복구
   기준선이다(Matrox H1 방식 — RV280 에서 증명된 것은 아님).
2. 이 부팅에서 `/ndrv` 마운트 → gcdsd 기동 → **`tools/nx-logcatch.sh start`** 를 먼저
   켠다.  PCI 읽기가 안 돌아오는 행은 루프 상한으로 못 막고, 로컬 로그는 행과 함께
   사라진다(Matrox `REMAINING_WORK.md` 3-61 끝).
3. probe 는 **bare loadable**: IODevice 아님, 매칭 없음, `CALL/WIRE/START`,
   `ADVERTISE` 없음(재적재가 kern_loader 를 태운다).  한 번 적재·실행·언로드.
4. 행이 나면: operator 전원 재시작 → 같은 VGA 기준선 → nxlogd 에 남은 마지막 줄로
   멈춘 조작을 특정 → 그 조작을 빼고 재계획.  **같은 조작 재시도 금지.**

## 3. 조작 등급 — probe 에 **컴파일되는** 것

| 등급 | 조작 | 포함 |
|---|---|---|
| A | PCI config 읽기(메커니즘 #1: `0xCF8` 에 주소 쓰기 → `0xCFC` 읽기) | 예 — **"대상 장치 쓰기 없음"** 이지 "읽기 전용" 은 아니다: 호스트 브리지의 전역 주소 래치 `0xCF8` 에 쓴다(Q5).  다른 config 사용자와의 경합 가능성은 미확인 |
| B | MMIO 한 페이지(BAR2 기준 0x2000) 매핑 → 명명 레지스터 **읽기** → 언매핑 | 예 |
| C | 레거시 BIOS 셰도 `0xC0000` 고정 64 KiB 매핑 → **읽기** → 언매핑 | 방식은 §6 의 선택지 |
| — | config 쓰기(BAR sizing 포함), MMIO 쓰기, 인덱스 쓰기(PLL/VGA/ATTR), VRAM 매핑·쓰기, ROM enable | **소스에 코드가 없다.**  빌드 게이트가 기계적으로 확인(§7) |

MMIO 매핑 길이 0x2000 의 근거(Python 계산, 2026-09-15): 읽을 레지스터의 최대 오프셋은
`RBBM_STATUS` 0x0e40 → 필요 길이 0x0e44 ≤ 0x2000(커널 페이지 8 KiB).  radeonfb 가
레거시 칩에서 접근하는 MMIO 최대 오프셋은 `RB2D_DSTCACHE_CTLSTAT` 0x342c 이므로 MMIO
BAR 는 그보다 크다 → 0x2000 매핑은 BAR 안이다.

## 4. 항목

### A. PCI config (읽기)

- 버스 0–7 × 장치 0–31 × 기능(헤더 타입 멀티펑션이면 0–7) 을 훑어 vendor 0x1002 이고
  device 가 RV280 합집합(5960 5961 5962 5963 5964 5965 5c61 5c63) 인 기능을 찾는다.
  못 찾으면 `1002:` 인 모든 기능을 적고 **B·C 를 하지 않는다**.
- 카드: 0x00–0x3f 전 64 바이트 덤프(한 줄 16 바이트, 4 줄).  **[구현] 캡 목록은 뺐다** —
  §1 의 어느 질문도 쓰지 않고, 0x40 이상 config 읽기만 늘린다.  필요해지면 재계획.
  (시뮬레이터가 0x40 이상 읽기를 위반으로 거절한다.)
- 경로: **[구현]** 버스 0–7 의 PCI-PCI 브리지(class 0604) 를 **모두** 0x18(버스 번호),
  0x1c–0x2c(창) 로 기록하고(경로의 상위집합), 경로 판정은 probe 와 호스트 파서가 **각자**
  계산해 대조한다.  브리지 표는 16 개 — 넘치면 `stop reason=too-many-bridges` 이고 경로
  판정이 불완전하므로 **매핑하지 않는다**(시뮬레이터에서 드러난 결함을 고침).
- 여러 개면 **B·C 를 하지 않는다**(한 장 전제가 깨짐).

### B. MMIO (읽기)

사전 검사(Q5): BAR2(config 0x18) 가 메모리 BAR(bit0=0)이고 **32 비트 타입**(bits 2-1 = 00)이며
주소가 0 이 아니고, 명령 레지스터 Memory Space Enable(bit1)=1, 주소가 상위 브리지의 memory
또는 prefetch 창 안 — 하나라도 아니면 매핑하지 않고 `map=skipped` 로 기록.
**[구현, Q7]** 네 가지를 더한다: (a) 선택 기능의 헤더 형이 0(`pcireg.h:430` — 형 0 에서만 0x18 이
BAR2), (b) 매핑 끝이 4 GiB 를 넘지 않음(버스 0 카드도), (c) prefetch 창은 형 0 이거나 형 1 이고
상위 절반(0x28/0x2c) 이 둘 다 0 일 때만 사용(`pcireg.h:1409-1412`), (d) 판정에 쓴 config 값
(BAR2·명령·헤더·경로 브리지 0x18/0x20/0x24/0x28/0x2c)을 **다시 읽어 같을 때만** 매핑 — 잠금 없는
0xCF8/0xCFC 쌍에 다른 사용자가 끼어든 것을 탐지(막지는 못함).  `mmio` 줄에 `hdr= wrap= stable=` 가
붙고, 호스트 파서가 로그된 config 바이트만으로 모든 판정 필드를 따로 계산해 대조한다.  BAR2 길이는
측정하지 않는다(sizing 은 쓰기) — 0x2000 이 BAR 안이라는 근거는 §3 의 0x342c 논거뿐이다.
`IOMapPhysicalIntoIOTask(base, 0x2000)` — 실패하면 중단.  읽는 순서:

1. `CRTC_CRNT_FRAME`(0x0214)·`CRTC_VLINE_CRNT_VLINE`(0x0210) 표본 8 쌍, 표본 사이
   `IODelay(2000)` µs.  **판정은 VLINE(bits 16-26)이 두 가지 이상 값**인 것만.  8 표본 창은
   14 ms 로 640×480@59.94 Hz 에서 0.839 프레임이라 프레임 경계를 볼 보장이 없다(Python,
   Q5).  VLINE 이 정적이면 "캐시·무디코드 의심" 으로 적고 나머지 읽기 중단.
   **[구현]** 8 표본을 **먼저 모두 읽고 나서** 줄을 찍는다 — 줄마다 `IOSleep(20)` 이
   붙어 있어 읽으면서 찍으면 간격이 22 ms, 창이 154 ms 가 되어 위 계산의 전제가 깨진다
   (시뮬레이터가 발견; 이제 창 안의 sleep 을 위반으로 거절).  정적이면
   `stop reason=vline-static` → 언매핑 → 반환(`frame60`·레지스터 줄 없음), 파서는 정적
   VLINE 뒤에 읽은 줄이 있으면 따로 실패시킨다.
2. `CRTC_CRNT_FRAME` 을 60 ms 간격 두 번 — **기록만**(59.94 Hz 면 3.6, 70.09 Hz 면 4.2 증가
   예상).  VGA 모드에서 이 계수기가 도는지는 미확인이라 게이트가 아니다.
3. 나머지 35 개 레지스터(표본 둘 포함 총 37 개 — Q5 로 `MEM_SDRAM_MODE_REG`,
   `CRTC_MORE_CNTL`, `GRPH_BUFFER_CNTL`, `DAC_MACRO_CNTL` 추가) — 오프셋은 `ANALYSIS.md`
   12 절 표(생성)와 `tools/r1/parse_r1.py` 의 `REGS`(자체검사가 헤더와 대조).  공간은 전부
   MMIO.  최대 오프셋은 여전히 `RBBM_STATUS` 0x0e40.

읽기 부작용: 참고 트리에서 이 목록의 **읽기**가 상태를 바꾼다는 근거를 찾지 못했다.
`GEN_INT_STATUS` 는 쓰기로 ack 한다(`radeonfb.c:2955`).  `[미검증: RV280 에서 읽기 부작용
없음]`.

### C. BIOS 셰도 — §6 에서 선택

### D. 셸

`ls -l /dev/mem /dev/kmem`, `uname -a`, `/usr/etc/kl_util -s` 로 적재 모듈 목록.

## 5. 출력 형식과 호스트 판정

- 모든 줄 앞에 `RDN-R1 <runid>` — runid 는 적재 인자(`CALL radeonR1Entry <runid>`)로
  주고 실행마다 바꾼다(낡은 로그 grep 사고 방지).
- **[구현] 출처**: 첫 줄 `begin version=1 build=<hex8>`.  `build` 는 `pack_probe.py` 가 묶은
  트리의 SHA-256 앞 32 비트이고 `target-build.sh` 가 `-DR1_BUILD=0x<hex8>` 로 넘긴다(정수 —
  타깃 make 에서 따옴표 중첩이 없다).  0 은 "스탬프 없음" 이고 파서가 거절한다.  파서
  호출은 `parse_r1.py <log> <runid> <build>` — 셋이 모두 맞아야 판정한다.
- 한 줄에 한 사실, `key=value`.  줄 사이 `IOSleep(20)` 으로 버스트를 늦춘다(syslog 가
  버스트를 버린 기록).  **모든 줄에 0 부터 연속 순번 `seq`**, 끝 줄에 총 줄 수 → 호스트가
  누락·반복을 위치까지 센다(브리지 수가 기계마다 달라 줄 수를 미리 알 수 없어 순번 방식).
- 줄 문법의 정본은 `tools/r1/parse_r1.py` 머리말(probe 는 그 문법으로 쓴다).  파서는
  합성 로그 5 종(정상, 줄 누락, 낡은 runid 섞임, 정적 스캔아웃, 다른 runid)으로
  `--self-test` 한다.
- 호스트 도구 `tools/r1/parse_r1.py`: 로그에서 runid 줄만 모아 (1) 누락 검사,
  (2) 필드 해독(MC 맵 → 주소 범위, CRTC 워드 → 해상도·총계·sync, `CLOCK_CNTL_INDEX`
  → DIV_SEL, `CONFIG_*` → MiB, `HDP_APER_CNTL` 비트), (3) 규칙 판정(RV280 정렬,
  `MC_FB_LOCATION` 이 BAR0 과 일치, CP·GART·버스 마스터 꺼짐) — **R2 입력으로 기록하는 판정이고
  R1 게이트가 아니다**(§8: 이 상태들을 알아내는 것이 R1 의 목적, Q7 3d), (4) R2 입력 파일
  (`docs/R1_RESULT.md` 초안) 생성.  해독 공식은 `radeon_modeset.py` 의 역함수이고,
  **왕복 시험**(오라클 값 → 해독 → 원래 모드)으로 파서를 검증한다 — 실기 전에 할 수 있다.

## 6. BIOS 셰도를 읽는 방식 — 선택지

| | 방식 | 장점 | 미검증·위험 |
|---|---|---|---|
| C1 | 사용자 공간 `dd if=/dev/mem bs=1 skip=786432 count=65536` 류 | 커널 코드 없음, 64 KiB 를 파일로 호스트에 | 근거: i386 커널이 BSD 메모리 장치 함수 `_mmread`·`_mmrw`·`_mmwrite` 를 export 한다(`tools/host/kernel_symbols.py` 로 `ref/openstep/ps2/mach_kernel` 파싱, 2026-09-15).  미검증: 장치 노드 존재·권한, 오프셋이 물리 주소인지(D 에서 확인) |
| C2 | probe 가 64 KiB 를 매핑해 **16 진 줄로 IOLog**(32 바이트/줄, 2048 줄, 줄마다 순번, 끝에 전체 체크섬) | 도구 추가 없음 | 로그 2048 줄 × `IOSleep(20)` = 약 41 초, syslog·nxlogd 부하.  **불완전하면 재시도하지 않고 C 항목 실패로 기록**(§2 의 재시도 금지와 충돌 방지, Q5) |
| C3 | probe 가 매핑 후 **경계 검사된 고정 오프셋만** 로그(0x00–0x7f, BIOS16(0x48) 가 가리키는 64 바이트, 그 +0x30 이 가리키는 32 바이트) | 줄 수 적음 | 커널 안에서 포인터를 따라간다(Q2 에서 지적된 위험 — 경계 검사로 제한) |

제안: **D 로 `/dev/mem` 확인 → 있으면 C1, 없으면 C2**.  C3 은 커널 파싱이라 쓰지 않는다.
**[구현]** 첫 probe 에는 C 가 없다.  D(`ls -l /dev/mem /dev/kmem`)는 `target-run.sh` 가 적재
전에 로그 머리에 적는다 — 그 결과를 보고 C1(셸) 또는 C2(probe 개정) 를 따로 계획한다.

**호스트 판정(규범, Q5)**: 게이트 — (1) `55 AA` 서명(xf86 `radeon_bios.c:77-87`),
(4) PCIR 포인터·구조가 이미지 안이고 서명 `PCIR`, vendor/device 가 A 의 카드와 같음, (5) ATOM 이
아닌 레거시 BIOS(xf86 `radeon_bios.c:380-427` 의 판별), (6) PLL 블록까지 따라가는 **모든 포인터와
읽는 오프셋이 이미지 경계 안**.  기록·경고만 — (2) ROM 크기 바이트(×512)가 64 KiB 안, (3) 그
크기의 8 비트 체크섬 0: PC 옵션 ROM 의 일반 규약이지만 **참고 트리의 어느 구현도 검사하지
않는다**(2026-09-15 grep 0 건 — 셰도 사본은 POST 가 고친 뒤일 수도 있다).  게이트가 하나라도
실패하면 BIOS PLL 값은 쓰지 않고 radeonfb 기본값(27 MHz/12/125–400 MHz)을 R2 입력으로 한다.

## 7. 빌드 게이트 (코드 작성 뒤, 실기 전)

0. **probe 는 Matrox 뼈대를 복사하지 않고 새로 쓴다** — Matrox 의 `Load_Commands.sect` 는
   `CALL openStepMGAProbeEntry 4`(모드 재프로그래밍 단계)로 무장돼 있다(Q5).
1. 호스트 검사: C89·`#import` 규칙·타깃 헤더로 문법 검사(emu10k1 hostcheck 방식,
   부품은 `tools/host/`), 커널 심볼표 대조.
2. **금지 조작 부재 검사**(스크립트): probe 소스에 MMIO 쓰기(`*(... *)(base + off) =`),
   `outb/outw/outl` 중 `0xCF8` 외의 포트, `pciWriteConfig`, `IOMapPhysicalIntoIOTask` 의
   길이가 0x2000·0x10000 이외, VGA 포트 상수(0x3c0–0x3df) 가 **0 건**.  같은 실행에서
   변이(쓰기 한 줄을 넣은 사본) 가 **실패**해야 게이트가 유효하다.
3. **목적 파일 검사**: 호스트 gcc `-m32` 목적 파일을 `objdump -d` 해서 `out` 명령어가
   `0xCF8` 로의 `outl` 뿐인지, `Load_Commands.sect` 의 `CALL` 대상·인자가 R1 진입점과 runid
   하나뿐이고 `ADVERTISE` 가 없는지 검사(소스 패턴 검사만으로는 컴파일된 경로를 보장 못 함).
4. 타깃 빌드 후 `nm -u` 미해결 심볼 0.

**[구현] 도구와 순서** (전부 `tools/r1/`):

| 단계 | 어디서 | 도구 | 무엇을 막나 |
|---|---|---|---|
| 1 | 호스트 | `hostcheck.sh` 1–7 | 위 1–3 + 변이(검사기가 실패할 수 있음을 같은 실행에서) |
| 2 | 호스트 | `hostcheck.sh` 8 = `sim_r1.py` | **바꾸지 않은 probe 소스**를 32 비트로 컴파일해 가짜 PCI·MMIO 와 링크, 23 개 세계(정상·카드 없음/둘·창 밖·64 비트 BAR·io·0·디코드 꺼짐·브리지 없음·창 끝 걸침·매핑 실패·정적 스캔·브리지 넘침·버스 0 wrap·64 비트 prefetch 창 위/아래·헤더 형 1·config 값이 두 번째 읽기에서 바뀜(`cfgflip`)·언매핑 실패 등)의 로그를 `parse_r1.py` 로 판정.  가짜 세계는 `outb/outw/inb/inw`, `0xCF8` 외 `outl`, 0x40 이상 config 읽기, 두 번째·다른 길이 매핑, MMIO 쓰기(읽기 전용 매핑), 생존 창 안 sleep, 언매핑 누락을 위반으로 거절.  변이 13 개(매핑 거절 조건 하나씩을 지운 변이는 그 조건이 지키는 세계에서 매핑해야 잡힘)가 모두 걸려야 PASS.  shim 원형은 타깃 헤더와 기계 대조 |
| 3 | 호스트 | `hostcheck.sh` 9 = `check_target_scripts.py` | 타깃 스크립트 두 개를 `/bin/sh` 와 가짜 make/nm/sum/kl_util 로 실행: 정상 1 + 고장 15(빌드: sum·스탬프·runid·적재 명령·템플릿·UNCHECKED·make 실패·제품 없음·ADVERTISE·서버 이름·심볼), 정상 1 + 고장 10(실행: runid 재사용·표지 없음/다른 트리·**빌드 뒤 reloc 변경**·nxlogd 없음·Matrox 활성·설정 표 없음·`-a` 실패·끝 줄 없음·언로드 실패) + SIGTERM 중 언로드.  정상 실행은 **묶은 소스·스탬프로 만든 시뮬레이터**를 가짜 `kl_util -l` 이 돌려 pack→build→load→log→parse 전 사슬을 판정.  타깃에 없는 셸 구성($(), printf, cut, grep -q, `\|`, mkdir -p, test -e, dirname) 린트 |
| 4 | 호스트 | `pack_probe.py` | hostcheck PASS 여야 묶는다.  runid 치환, 스탬프, MANIFEST, BSD `sum`(타깃 `/usr/bin/sum` 과 같은 알고리즘 — Matrox 기록값 `45628 103` 으로 검증) |
| 5 | 타깃 | `target-build.sh <tar> <sum> <blocks>` | sum 대조, 스탬프·runid 형식, `MANIFEST` 가 UNCHECKED 가 아님, 적재 명령 원문 = 정확히 세 줄, make **자신의 종료 코드**, 제품의 적재 명령에 ADVERTISE/SMAP/DETACH/PORT_DEATH 없음·CALL 한 줄, `Server Name`, `nm -u` ⊆ `/mach_kernel`(0 개면 실패) → `R1BUILD_PASS`(스탬프·runid·**reloc sum**) |
| 6 | 타깃 | `target-run.sh` | `R1BUILD_PASS` 가 이 트리와 **지금의 reloc sum** 을 가리킬 것, nxlogd 실행 중·`Active Drivers` 에 Matrox 없음, runid 를 `mkdir /me/rdn-r1-ran.d/<runid>` 로 원자적으로 선점(적재 **전** — 행 뒤 재부팅해도 같은 묶음 재시도 불가), D 사실 기록, `kl_util -a/-l`, 끝 줄 최대 60 s, `-u/-d`(HUP/INT/TERM 트랩 포함, 실패는 FAIL), `/tmp/rdn-r1-<runid>.log` |
| 7 | 호스트 | `parse_r1.py <log> <runid> <build>` | §5·§8 |

시뮬레이터가 보여 줄 수 없는 것: cc 2.7.2.1 의 코드 생성, 실제 커널의 `IOLog` 손실, 실제
카드.  타깃 도구(sh·make·nm·strings·kl_util)의 실제 동작도 첫 실기 실행에서 처음 확인된다.

## 8. 판정(Gate)과 결과 기록

- A·B·C·D 결과를 `docs/R1_RESULT.md` 에 기록(파서 출력 + 사람 해석).
- 통과: 카드 1 장 식별, B-live 판정 LIVE, 보고 크기 대조표, MC 맵·출력 경로 스냅샷,
  CP/GART/버스마스터 상태, 콘솔 분주 슬롯, BIOS PLL 블록(또는 "없음" 과 기본값 사용 결정).
- 실패 처리: 어느 항목이든 "정적/중단" 이면 그 원인을 R1 재계획에서 다룬다.
  R2 계획은 R1 통과 뒤에만 쓴다.

## 9. 이 계획이 닫는 열린 질문

- R0-2 §5-1(분주 슬롯) — 콘솔 쪽 값만.  VGA `MISC` 클럭 대응은 여전히 소스 과제.
- R0-2 §5-5(BIOS 가 CP 를 켜 두는가).
- R0-3 §5-3 은 **닫지 않는다**(`ATTR[0x10]` 읽기는 인덱스 쓰기 — R2 스냅샷에서).
