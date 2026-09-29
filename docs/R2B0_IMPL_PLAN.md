# R2b-0 구현 계획 — 활성화 부팅 기록 (개정 2)

작성 2026-09-15.
- 상위: `docs/R2_FIRST_LIGHT_PLAN.md` 개정 5.2 §3 R2b-0.
- 판정: `docs/review/Q11_verdict.md`, `docs/review/Q12_verdict.md`, **`docs/review/Q13_verdict.md`**.
- 순서(PLAN §4): 계획 → 교차검토 → 재검증 → 코드 → 호스트 검사 → 실기.

**개정 2(Q13, 내 오류 26)**:
- 활성화·원복 절차를 하나로 정리했다.
  - 활성화는 Configure.app 으로 한다.
  - 활성화 부팅의 원복은 **항상** `/me` 집합 복원 스크립트로 한다.
  - R-1 은 재부팅 없는 Configure 왕복이다.
  - 옛 §7-1 경로와 바이트 `cmp` 게이트를 없앴다.
- `check_cfgdiff` 는 키→값 대조와 파일 집합 대조로 바꾸고 정지 목록을 두었다.  `ps` 는 쓰지 않는다.
- 사용자 도구: `IOGetDisplayInfo` 는 `getIntValues` count 5 로 묻는다.  거절 코드는 슈퍼클래스·커널이 쓰지 않는 값으로 바꿨다.
- 드라이버:
  - 기록 사이 종결 걸쇠, 임계 구간 내용 규정.
  - 옵트인 키는 init 에서 한 번 읽어 캐시한다.
  - `getPCIdevice:` 실패를 거절하고 로그로 남긴다.  `+probe:` 버스 스캔은 없앴다.
  - `[self free]`, `_basicConsoleMode` 기록.
- 파서: R1 대비 판정을 기록으로 바꾸고, 기대값마다 사람 출처 표를 두었다.
- 시뮬레이터 표를 줄 단위로 다시 썼다.  역어셈블 게이트는 심볼 범위별로 하고, 읽기 포트 허용 목록을 추가했다.
- 사실 정정:
  - S17 은 **텍스트 부팅일 때만** 커널이 VGA 를 쓴다(이 기계는 실측 텍스트 부팅).
  - VBE 여부는 `"Boot Graphics"` 가 아니라 부트 로더 VBE 필드로 갈린다.
  - 빈 `Location` 은 PCIBus 가 ID 스캔으로 묶는다(역어셈블, 타깃 sum 일치).
- 재부팅 수: 4 회(R-1 은 재부팅 없음).

## 0. 목적과 경계

**묻는 것**:
1. VGA 드라이버가 없는 **활성화 부팅**에서, 우리 드라이버가 기록할 시점에 카드는 어떤 상태인가?
   - **PLL**: refdiv·`PLL_DIV_SEL`·`PPLL_DIV_0..3`.  커널은 쓰지 않으므로 BIOS POST·부트 로더가 남긴 상태다.
   - **VGA 표준 레지스터**: 텍스트 부팅이면 커널 VGA 콘솔이 쓴 상태다(S17, S26).  커널 표로 **예측 가능**하므로 기록은 예측과 실측의 대조가 된다.  아이콘 부팅이면 부트 로더 상태다 — 기록의 `cmode` 가 가른다.
   - **0 단계가 보는 MMIO 레지스터들**.
2. 그 상태에서 R2 계획 §4 0·1 단계 판정(개정 5 기대값)은 각각 무엇을 말하는가?  이 결과로 개정 6 에서 게이트를 확정한다.
3. 우리 번들이 디스플레이 소유자로 적재되고, FB 를 등록하고, WindowServer 가 뜨고, telnet 이 사는가?
4. 복구(Instance 표 집합을 활성화 전 상태로)가 실제로 되는가?

**하지 않는 것**:
- 모드 레지스터(CRTC·PLL 데이터·DAC·팔레트·MC·`SURFACE_CNTL`·`HOST_PATH_CNTL`) 쓰기.
- `enterLinearMode`·`revertToVGAMode` 의 하드웨어 접근.

**우리 코드의 하드웨어 쓰기 전부**:
- (a) PCI 메커니즘 #1 주소 래치 `outl(0xCF8)` — 읽기용
- (b) PLL 인덱스 1 바이트 선택·복원(R2a 규약) — 기록 때만
- (c) VGA 인덱스 포트와 속성 인덱스(PAS 세움) — 기록 때만

커널 내부 쓰기(우리 목록 밖, 기록만 한다):
- `IOGetTimestamp` 의 PIT 래치 0x43/0x40(S21)
- `splhigh`/`splx`/`_splusclock` 의 PIC 마스크 0x21/0xA1(S27)

R2b-0 빌드에는 모드셋 코드가 **소스에 없다**(설정 키가 아님, §6-3 규칙).

## 1. 사실 (이 세션에서 연 원문)

| # | 사실 | 출처 |
|---|---|---|
| S1 | `IO_Framebuffer_Map` 요청에서 커널이 `revertToVGAMode` → `enterLinearMode` → `registerDisplay` 순으로 부른다.  이 분기는 `-[IOFrameBufferDisplay getIntValues:forParameter:count:]`(IMP `0x1c3cdc`) 안에 있고, Unmap 은 `setIntValues:`(IMP `0x1c4188`) 안에 있다 | 30 행; 미러 `mach_kernel` 클래스 구조체 파싱 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S2 | `IOFrameBufferDisplay` 계약(enter/revert 는 하위 클래스, `mapFrameBufferAtPhysicalAddress:length:`) | 헤더 `driverkit/IOFrameBufferDisplay.h` |
| S3 | Matrox 교체 드라이버: init 에서 PCI config(메커니즘 #1)로 BAR 를 읽는다.  MMIO 는 `IOMapPhysicalIntoIOTask`, 그 뒤 `setMemoryRangeList`(FB + 0xA0000/0x20000 + 0xC0000/0x10000) → `mapFrameBufferAtPhysicalAddress`.  raw 매핑으로 FB 를 잡으면 WindowServer 가 멈췄다 | Matrox `.m` 3731–4094 행(MMIO 4038, 범위 4084, FB 4086); `docs/TEST_STATUS.md` 51 행 |
| S4 | Matrox 표: `Title`·`Family=Display`·`Version`·`Location`·`Instance=0`·`Driver Name`·`Class Names`·`Server Name`·`Bus Type=PCI`·`Auto Detect IDs`(device<<16\|vendor)·`FB Address=""`·`Memory Maps=""`·`VGA Memory Maps`·`I/O Ports=""`·`DMA Channels=""`·`IRQ Levels=""`.  `/* */` 주석이 있다.  Load_Commands 는 `WIRE` 만 | Matrox `OSMGADisplay/Default.table`(1·41 행 주석), `Load_Commands.sect` |
| S5 | Matrox `revertToVGAMode` 는 `[super revertToVGAMode]` 를 부른다.  generic VGA(`IOVPCodeDisplay`)는 `runVPCode` 결과가 0 이 아닐 때만 super 를 부른다 | Matrox `.m` 7629 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S6 | 활성화 = `Active Drivers` 에서 `VGA` 를 한 번에 교체 + cold reboot.  겹치면 같은 PCI 를 둘이 주장한다 | Matrox `docs/RECOVERY_REPLACEMENT_DRIVER_EXECUTION_PLAN.md` 33–46 행, `docs/C3_BUNDLE_RENAME_PLAN.md` 130 행 |
| S7 | 설치: 후보 디렉터리 검증 → 원자적 rename, 인스턴스 표 보존, 번들 파일 root.wheel·group/other-writable 금지(driverLoader 거절 규칙, 주석 근거).  인스턴스 표는 기계의 것이고 **기계의 표 집합이 정본**이다 | 작업공간 `tools/install-matrox-driver.sh` 10–20·143–146 행 |
| S8 | 이 기계(2026-09-15 telnet 읽기) `Instance0.table`: `Active Drivers` = `SpaceSaver2Mouse Pro1000 Adaptec2940SCSIDriver MDH10Disk EMU10K1 VGA`.  공장 `Default.table`: `PS2Mouse BusMouse SerialPointingDevice ParallelPort VGA`, `Boot Drivers` 에 `PS2Keyboard` | 타깃 `/private/Drivers/i386/System.config/*.table`(`/private/Devices` 와 같은 디렉터리, `openstep-ac97/README-Instance0.md` 99–100 행) |
| S9 | `config=Default` 는 공장 표로 부팅한다 — 1997 VGA 드라이버 640×480 BW:2, **네트워크 없음**.  여러 프로젝트가 복구 수단으로 안내한다(RV280 에서 실측된 적은 없다) | Matrox `docs/REMAINING_WORK.md` 4366–4371 행, `openstep-matrox-remade/tools/inventory-default-boot-footprint.sh` 6–7 행, `openstep-ac97/README-Instance0.md` 113 행 |
| S10 | "깨진 디스플레이 부팅에서 telnet 생존" 은 미증명 | Matrox `docs/TEST_STATUS.md` 33 행 |
| S11 | 사용자 공간 → 드라이버: `IODeviceMaster lookUpByDeviceName:"Display0"` → `get/setIntValues:…objectNumber:count:`, `cc … -lDriver`.  **get 의 `count` 는 in/out**(커널이 메서드가 남긴 값을 되돌린다), **set 의 `count` 는 값 전달**.  Matrox 는 긴 측정을 파라미터 트리거로 옮겼고, 그 트리거는 설정 키로 거절할 수 있다 | Matrox `test/openstep-mga-stats-probe.m` 5–16; 72–91 행; `.m` 5934–5938; 7354–7370 행; 헤더 `IODevice.h` 161–171 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S12 | PLAN 금지 8: 위험 작업은 nxlogd 켠 부팅에서만, 실패 기록 뒤 영구 비활성화 | `PLAN.md` §2 139–148 행 |
| S13 | 커널 심볼 `.objc_class_name_IOFrameBufferDisplay`·`.objc_class_name_IOConfigTable`·`_IOGetTimestamp`·`_basicConsoleMode` 있음, `___udivdi3`·`___umoddi3`·`___divdi3` 없음 | `kernel_symbols.py --check` |
| S14 | 속성 레지스터 0x10–0x14 는 인덱스에 PAS(0x20)를 세운 채 읽는다(0x00–0x0F 는 불가).  근거는 Matrox 교차검토 문답의 추론이지 실측이 아니다 — R2b-0 기록이 S17 커널 표와 대조해 이 카드에서 실측한다 | Matrox `docs/REMAINING_WORK.md` 3347–3351 행 |
| S15 | R2a 코드(PLL 묶음·헬퍼·파서·시뮬레이터·역어셈블 게이트) 실기 PASS | `docs/R2A_RESULT.md` |
| S16 | `-[IOFrameBufferDisplay revertToVGAMode]` = `0x1c50f4`, `enterLinearMode` = `0x1c50ec`, 둘 다 몸체 `return;` | 미러 `mach_kernel` `__OBJC,__class` 파싱(Python) — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S17 | **커널 VGA 콘솔(조건부)**.  `_kminit` 은 VBE 콘솔이 없으면 기본 콘솔(`_VGAAllocateConsole`, 640×480)을 잡고, 부트 구조체 `graphicsMode == 0`(텍스트 부팅)이면 mode 1·initScreen 1, 아니면 mode 2·initScreen 0 으로 콘솔 Init 함수를 부른다.  **mode ∈ {1,2} 이고 initScreen ≠ 0 일 때만** `_VGASetGraphicsMode` 가 MISC `e3`·SEQ·CRTC·ATTR·GR·DAC 를 쓴다.  커널 표(Python 덤프, `__TEXT,__const`): SEQ `03 21 0f 00 06`, CRTC `5f 4f 50 82 54 80 0b 3e 00 40 00 00 00 00 00 59 ea 8c df 28 00 e7 04 e3 ff`, ATTR `00 01 02 03 … 01 00 03 00 00`, GR `00 0f 00 00 00 00 05 0f ff` — 800×525, 25.175 MHz 에서 59.9405 Hz.  끝 상태: SEQ1 ← `01`, 속성 인덱스 `0x20`, 플립플롭 **데이터 상태**.  Matrox 스냅샷 `misc e3 seq1 01 crtc0 5f crtc9 40 crtc17 e3` 과 같다 | Darwin 0.1 `km.m` 501–509 행(상대 소스, 확인용); 미러 `mach_kernel` VA `0x1d54de`/`0x1d54e3`/`0x1d54fc`/`0x1d5511`; Matrox `REMAINING_WORK.md` 3364 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S18 | 사용자 `setIntValues` 디스패치는 객체 조회만 락으로 감싸고 드라이버 메서드는 락 없이 부른다 — 재진입 가능.  조회 실패는 -704·-727, 커널 진입 실패는 -705 | **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S19 | `registerDisplay` 뒤 커널 알림·패닉은 등록된 디스플레이의 FB 에 그린다(`allocateConsoleInfo` → `_FBAllocateConsole`) — R2b-0 에서는 아무도 스캔아웃하지 않는 곳이다.  FB 콘솔 할당이 0 을 돌려줄 때만 VGA 콘솔로 떨어진다 | **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S20 | 설치된 EMU10K1 인스턴스 `Location` 은 `Dev:11 Func:0 Bus:3`(Radeon 슬롯)이었고 2026-09-15 `Dev:13` 으로 고쳤다.  2026-09-08 syslog 에는 SB Live 가 `03:0b.0` 에서 probe 한 줄이 있다 — 카드 이동으로 낡은 값이다.  이번 부팅들의 probe 위치 줄은 syslog 에 없다(미확인) | 타깃 `EMU10K1.config/Instance0.table`; `logs-pcils-20260915.txt` 37·44 행; 타깃 `/usr/adm/messages.old` 70 행 |
| S21 | `IOGetTimestamp` = `_clock_value(1)`(가동시간, `time_of_boot` 안 더함) = 틱 기준(10 ms) + PIT 보간(`splusclock` 아래 0x43/0x40) — 인터럽트가 대기 중이면 약 10 ms 뒤로 가거나 짧게 읽힐 수 있다 | **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S22 | `get/setIntValues` 의 WindowServer 이름들(`IO_Framebuffer_Map`·`_Unmap`·`_Register`·`IOGetDisplayInfo`·`IOSetTransferTable`)은 슈퍼클래스가 처리한다 — 재정의가 모르는 이름을 삼키면 디스플레이 소유자가 동작하지 않는다.  **`IOGetDisplayInfo` 는 getInt 이고 in-count 가 5 또는 7 일 때만 답한다**(`[width, height, refresh, bpp, colorSpace, (totalWidth, rowBytes)]`).  getChar 로 물으면 -711(Matrox 실측) | 111; Matrox `S3B_PREP_INSTRUMENTATION_PLAN.md` 450; 454–455 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S23 | xf86 은 `PPLL_DIV_0 + PLL_DIV_SEL` 로 살아 있는 분주 슬롯을 읽는다(DIV_1·2 이름 읽기의 선례) | `radeon_driver.c` 1076·1079 행 |
| S24 | `getPCIdevice:` 는 설명 객체가 만들어질 때 PCIBus `configAddress:device:function:bus:` 가 준 위치를 돌려준다.  없으면 **-704 이고 출력 인자는 건드리지 않는다** | 헤더 `driverkit/i386/IOPCIDeviceDescription.h` 25–35 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S25 | **PCIBus 위치 결정**: `Bus Type` ≠ `PCI` 또는 `Auto Detect IDs` 없음 → -704.  `Location` 이 있고 비어 있지 않고 파싱되고 그 위치의 ID 가 맞으면 그 위치.  **없거나 빈 문자열이거나 틀리면** 버스 0..max·장치 0..max·기능 0..7(헤더 다기능 비트 따라)을 스캔해 `Instance` 번째 일치를 쓴다.  타깃 `PCIBus_reloc` sum 이 미러와 같다 | 미러 `PCIBus_reloc` `__text` 0x594–0x843 직접 역어셈블(Python + objdump, 문자열·셀렉터 해석: 63f `Location`, 65b·664 폴백, 6e0 `Instance`, 76b `testIDs:`, 834 -704); 타깃 `sum /private/Drivers/i386/PCIBus.config/PCIBus_reloc` → `09451 40`, 미러 `09451 40`(2026-09-15) |
| S26 | **이 기계의 현 부팅은 텍스트 모드 VGA 콘솔**: `/dev/kmem` 오프셋 = VA(`_hz` `100`, `_tick` `10000`), `_basicConsoleMode` = `1`, `_basicConsole` 연산표 = `_VGAAllocateConsole` 의 표(`0x19b81c 0x19ab88 0x19ae0c …`).  `_basicConsoleMode` 는 `_kminit` 만 쓴다 | 타깃 kmem 읽기(2026-09-15, 사본 `build/r2b0/rdnk1..4`); `_basicConsole 0x1f7b3c`; `_basicConsoleMode 0x1f7b40`; 23 행 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S27 | `_splusclock` 은 소프트 spl 레벨을 **무조건 6** 으로 두고, 이전 레벨이 6 보다 높으면 PIC 마스크를 다시 쓴다 — `splhigh` 안에서 부르면 임계 구간이 깨진다 | **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S28 | **Configure.app 저장**: 손대지 않은 표도 키 순서를 바꿔 다시 쓴다(줄 집합 동일).  인스턴스를 템플릿에서 만들면 `"Default Table" = "<템플릿>"` 키를 넣는다.  드라이버를 **추가**하면 `Default.table` 에서 새 인스턴스를 쓴다(Matrox 실측).  빈 `Location` 을 채운 사례는 없다(캡처한 VGA 표는 `""`) | `build/r2b0/emu10k1/*.after-configure-1456` Python 대조(Q13 판정 0-3); Matrox `R5_INSTALLER_KEEPS_THE_CONFIGURATION_PLAN.md` 22–25·137–138 행 |
| S29 | 모르는 파라미터 이름에 `IODevice` 는 get/set 모두 -711 을 돌려준다 | **근거 미확정**(2026-09-16 출처 규칙, §15-5) |
| S30 | `registerDisplay` 뒤 MISC·CRTC·ATTR 에 상수 포트로 쓰는 커널 코드는 `_VGASetGraphicsMode` 뿐이다.  그 부팅 뒤 호출 경로는 등록 디스플레이가 없거나 종료 때다.  기본 콘솔 연산은 GR 과 SEQ 인덱스 2 만 쓴다(애니메이션 타이머 포함, `ns_timeout`) | 36; 45; 125 행뿐 — 그 밖의 근거는 **근거 미확정**(2026-09-16 출처 규칙, §15-5) |

## 2. 실행 형태 — 두 부분

**A. 활성화 부팅(모드·인덱스 쓰기 0)**
- `+probe:`
  - 출력 인자를 `0xff` 로 초기화하고 `getPCIdevice:` 를 부른다(S24).
  - rc ≠ 0 → 거절.  rc = 0 이면 그 위치의 config 레지스터 0 을 한 번 읽어 `0x59601002` 가 아니면 거절한다.
  - 버스 스캔은 하지 않는다(PCIBus 가 이미 ID 로 골랐다, S25).  "RV280 기능이 하나" 는 기록 B 의 R2a 스캔이 확인한다.
  - IOLog 한 줄(대기 없음): `RDN-R2B0 probe rc=<d> loc=<bb:dd.f> id=<hex8> accept|decline`.
  - 받아들이면 `[super probe:]`.
- `initFromDeviceDescription:`
  - `getPCIdevice:` 위치를 다시 받고, config 읽기로 BAR0·BAR2 와 R2a 사전 검사(mem32·0 아님·hdr 0·cmdmem·wrap·브리지 창·재읽기 일치)를 한다.
  - 이 검사는 **로그를 찍지 않는 변형**이다(R2a 원본은 줄마다 IOSleep).  결과는 RAM 에만 두고, 코드는 `osrdn_record.c` 에 있어 시뮬레이터가 덮는다.
  - 옵트인 키 `"RDN R2B0 Record"` 를 **여기서 한 번** 읽는다.  `configTable` → `valueForStringKey:` → 비교 → `freeString:` → 캐시 `recordEnabled`.
  - `_basicConsoleMode`(커널 변수, S13·S26)를 읽어 캐시한다.  메모리 읽기일 뿐이다.
  - `displayInfo`(1024×768×32) 공개 → MMIO 매핑(0x2000) → `setMemoryRangeList` → `mapFrameBufferAtPhysicalAddress`(0x300000).  순서는 Matrox 와 같다(S3).
  - 로그 한 줄: `RDN-R2B0 init boot=<nonce8> build=<hex8> loc=<bb:dd.f> key=yes|no cmode=<n> ok|abort=<why>`.
  - nonce 는 init 에서 읽은 `IOGetTimestamp` 하위 32 비트다.  가동시간에서 나오므로 부팅 계수가 아니다.  "같은 부팅" 은 nonce 와 이 부팅의 syslog 표지(§7)를 **함께** 봐서 판정한다.
  - 실패하면 로그 한 줄 뒤 `return [self free]`.  `free` 는 자기가 만든 매핑만 푼다.
- `enterLinearMode`: 호출 수 증가, `RDN-R2B0 enter boot=<nonce8> n=<k> refused`.  하드웨어 접근 없음.
- `revertToVGAMode`: 호출 수 증가, `RDN-R2B0 revert boot=<nonce8> n=<k>`, `[super revertToVGAMode]`(S16, 빈 구현).
- 화면은 커널 콘솔의 부팅 그림으로 남는다(S17·S26).  WindowServer 는 스캔아웃되지 않는 VRAM 에 그린다.  이것이 이 프로젝트의 **첫 BAR0 쓰기**다.
- **금지 8 예외(operator 승인 2026-09-15, §11-1)**: A 의 config 입출력과 매핑은 nxlogd 이전이다.  Matrox 교체 드라이버가 같은 일을 하고 여러 번 부팅했다.

**B. 부팅 뒤 기록(nxlogd 켠 뒤)**
1. 호스트: `/ndrv` 마운트 → gcdsd → `nx-logcatch.sh start`.
2. 타깃 `target-run-r2b0.sh`: 시스로그 표지(이 부팅) → 사용자 도구 `rdnr2b0 <runid> <build>`.
3. 도구는 `Display0` 에 `RDNR2b0Record` = `{runid, 0x52324230}` 을 보낸다.
4. 드라이버 `osrdn_record_request()` — 순서가 곧 규칙이다:
   1. 인자: count 2·magic·runid ≠ 0·runid ≠ 마지막 runid.  아니면 `IO_R_INVALID_ARG`(-706).
   2. 캐시 `recordEnabled` 가 아니면 `IO_R_NOT_ATTACHED`(-729).
   3. **임계 구간**(`s = splhigh()` … `splx(s)`): 안에는 비교와 대입만 둔다.
      - `latched` 면 결과 = -728.
      - 그렇지 않고 `inProgress` 이거나 `bootRecords >= 2` 면 결과 = -725.
      - 둘 다 아니면 `inProgress = 1; bootRecords++;`, 결과 = 진행.
      - 호출·IOLog·IOSleep·`IOGetTimestamp` 는 넣지 않는다(S27).
   4. `splx` 뒤에 거절 로그 한 줄(-728 `IO_R_NOT_READY`, -725 `IO_R_BUSY`)을 찍고 그 코드를 돌려준다.
   5. 진행이면 §4 기록.  **모든 출구**(정상 `end`, `stop reason=*`, 사전 검사 실패)에서 `inProgress = 0`.
   6. **종결 걸쇠**: 기록이 `stop reason=vline-static`·`pllbusy`·`pllabort`, BAR2 불일치, 사전 검사 실패로 끝나면 `latched = 1`.  이후 요청은 하드웨어에 닿지 않는다(PLAN 금지 8, S12).
   7. 계수는 test-and-set 때 오르므로 중단된 기록도 부팅당 2 회에 포함된다.
5. 기록 줄은 `boot=<nonce8>` 을 begin 줄에 싣는다.
6. 거절 코드는 커널·슈퍼클래스가 set 경로에서 돌려주는 값(**근거 미확정**(2026-09-16 출처 규칙, §15-5))과 겹치지 않게 골랐다.  단 -706 은 인자 오류로 슈퍼클래스와 같은 뜻으로 쓴다.

**R2b 에 대해 이것이 증명하지 않는 것**:
- `IO_Framebuffer_Map` 문맥에서의 기록·IOSleep
- 부팅 버스트의 syslog 생존
- Map 시점 레지스터 = 기록 시점 레지스터.  둘 사이 상수 포트 쓰기 주체는 없다(S30).  남는 경로는 FB 콘솔 할당 실패와 변수 포트 쓰기다.
- enter/revert 반복과 게이트 평가의 결합
- `enterLinearMode` 안 거절에 대한 WindowServer 반응

A 는 "아무것도 하지 않는 `enterLinearMode` 로 WindowServer 가 산다" 는 것은 증명한다.

## 3. 번들 `OSRDNDisplay`(operator 결정 2026-09-15)

```
OSRDNDisplay/
  Makefile  Makefile.preamble  Makefile.postamble   GLOBAL_RESOURCES = Default.table Instance0.table (인스펙터 없음)
  Default.table  Instance0.table
  English.lproj/Localizable.strings                   첫 키 = Server Name (Matrox C3 판정)
  OSRDNDisplay_reloc.tproj/
    Load_Commands.sect           WIRE 만
    OSRDNDisplay.h / .m          ObjC 클래스 — 포트·MMIO 호출 없음, osrdn_* C 함수만
    osrdn_record.m / .h          기록 로직(C89, 클래스 없음) — 요청 가드·걸쇠, 사전 검사, PCI 스캔, 생존·시간, 레지스터, PLL 묶음, VGA, 판정, 줄
    osrdn_pll.m / .h             R2a pllGroup/pllSnapshot 소스 텍스트(드리프트 검사 대상)
    osrdn_port.m / .h            포트 이음새: osrdn_inb/outb/inl/outl — ioPorts.h 인라인을 감싸는 별도 컴파일 단위
    osrdn_expect.h               판정 기대 표(호스트 gen_expect_r2b0.py 생성)
    RDNR2aMMIO.m / .h            R2a MMIO 헬퍼 그대로
```

- **확장자(코드 착수 때 정정)**: C 코드도 `.m` 이다.  NeXT 헤더는 서로 `#import` 하고 가드가 없어, `.c` 단위에서 `#include` 와 섞으면 형 재정의가 난다(메모리 "NeXT 헤더는 #import 만" 선례).  R2a 도 순수 C 를 `.m`(`CLASSES`)에 두어 타깃 빌드·실기 PASS 했다.  아래의 `osrdn_*.c` 는 모두 `osrdn_*.m` 을 뜻한다.
- **이음새**: `osrdn_record.m`·`osrdn_pll.m` 는 `osrdn_port.h`·`RDNR2aMMIO.h` 로만 하드웨어에 닿는다.
  - 시뮬레이터는 두 단위를 모형으로 바꾼다.
  - 타깃은 별도 단위라 인라인되지 않고 reloc 에 심볼이 남는다(R2a reloc 에서 인라인은 같은 단위 안에서만 펼쳐졌다, Q13 판정 A5-1).
  - 컴파일 플래그는 R2a Makefile 과 같은 `-O` 로 한다.  인라인이 꺼지면 `_outb` 사본이 생겨 §6-4 가 FAIL 한다(안전한 실패, 메시지에 이 가능성을 적는다).
- **`Default.table`/`Instance0.table`(전체)**:

```
"Title" = "OSRDNDisplay R2b-0 record build";
"Family" = "Display";
"Version" = "0.1";
"Instance" = "0";
"Location" = "";            (operator 결정 2026-09-15; PCIBus 가 ID 스캔으로 묶는다, S25)
"Driver Name" = "OSRDNDisplay";
"Class Names" = "OSRDNDisplay";
"Bus Type" = "PCI";
"Auto Detect IDs" = "0x59601002";
"Display Mode" = "Height: 768 Width: 1024 Refresh: 60Hz ColorSpace: RGB:888/32";
"FB Address" = "";
"Memory Maps" = "";
"VGA Memory Maps" = "0xa0000-0xbffff 0xc0000-0xcffff";
"I/O Ports" = "";
"DMA Channels" = "";
"IRQ Levels" = "";
"RDN R2B0 Record" = "Yes";   (두 표 모두 — §11-2 결정 (a), 기록 전용 빌드만)
```

- **`"Server Name"` 은 원본에 쓰지 않는다(2026-09-16 정정).**  driverkit 번들 postamble 이
  `PRODUCT_ROOT/*.table` **전부**에 `"Server Name" = "$(NAME)";` 를 무조건 덧붙인다
  (`ref/openstep/makefiles/NextDeveloper/Makefiles/driverkit/Makefile.bundle_postamble` 1–6 행,
  `OSRDNDisplay/Makefile` `NAME = OSRDNDisplay`).  원본에도 적으면 설치본에 두 줄이 남는다 —
  실제로 2026-09-16 설치본이 그랬고 `check_cfgdiff precheck` 가 `duplicate key 'Server Name'` 로
  멈춰 드러났다.  같은 기계의 다른 설치 표 16 개와 정품 드라이버 표 20 개(`ref/openstep/drivers/
  Drivers/i386/*.config/*.table`)는 전부 중복 키 0, `Server Name` 1 줄이다(python 집계).
  - **왜 위험한가**: 사용자 공간의 설정 표는 `NXStringTable`(`driverkit/IOConfigTable.h` 의 ivar
    주석)이고 `NXStringTable: HashTable`(`objc/NXStringTable.h` 17 행), `HashTable insertKey:value:`
    는 같은 키가 있으면 **갱신**한다(NeXT 문서 `HashTable.rtf` 246 행) — 즉 **마지막 값이 이긴다**.
    커널 쪽이 중복을 어떻게 다루는지는 **확인된 근거가 없다**.  해석이 갈릴 수 있는 표는 출하하지
    않는다: 정품 i386 드라이버 표 20 개와 이 기계 설치 표 16 개 모두 중복 키 0·`Server Name` 1 줄이다.
  - **게이트**: `target-build-r2b0.sh` §3b 가 원본 두 표에 그 줄이 0 개인지, §5 가 빌드 산출 표마다
    정확히 1 개이고 `OSRDNDisplay` 를 가리키는지 본다.  `target-install-r2b0.sh` §3b 는 설치 후보
    표마다 같은 것을 보고, 설치 뒤 §6 이 다시 본다.  `check_cfgdiff.py` 는 `POSTAMBLE`
    (`{'Server Name': 'OSRDNDisplay'}`)을 원본 표 키에 더한 것을 기대값으로 쓰고, 원본이 이미 그
    키를 가지면 거절한다.

- **포트 선언 비교**(상위 §6 요구):
  - Matrox 는 `I/O Ports` 빈 값으로 동작했다.
  - generic VGA 는 `0x3b4-0x3b5 0x3b8-0x3bb 0x3c0-0x3cf 0x3d4-0x3dc 0x46E8-0x46E9` 를 선언한다(`VGA.config/Instance0.table`).
  - 활성화 부팅에는 VGA 드라이버가 없어 충돌 대상이 없다.  빈 값을 택한다 — ring 0 인라인 입출력은 선언 없이 동작한다(R1·R2a 의 0xCF8).
- **출처**:
  - init 줄의 `build`, `RDNR2b0State` 에 build·nonce 를 둔다.
  - 빌드 스탬프 입력에 R2a run 789467668·R1c 이미지 SHA-256 앞 8 자를 넣는다(상위 §6).
  - 줄 접두는 `RDN-R2B0`.  상위 §6 의 `OSRDN init` 은 R2b 용으로 남긴다.

### 3-1. 클래스 메서드

| 메서드 | 동작 | 하드웨어 |
|---|---|---|
| `+probe:` | §2 A | config 읽기 1 쌍 |
| `initFromDeviceDescription:` | §2 A.  실패하면 로그 한 줄, `return [self free]` | config 읽기, 매핑 |
| `enterLinearMode` | 계수·로그 | 없음 |
| `revertToVGAMode` | 계수·로그·super | 없음 |
| `setIntValues:forParameter:count:` | 이름이 `RDNR2b0Record` 가 **아니면 무조건 `return [super setIntValues:…]`**.  맞으면 `osrdn_record_request()` 결과 반환 | §4 |
| `getIntValues:forParameter:count:` | 이름이 `RDNR2b0State` 가 아니면 무조건 super.  맞으면 `*count` 입력이 9 일 때만 9 워드를 채우고 `*count = 9`, 아니면 `IO_R_INVALID_ARG` | 없음 |
| `get/setCharValues:` | 재정의하지 않는다 | — |
| `setBrightness:token:` | self | 없음 |
| `free` | 자기가 만든 MMIO 매핑만 해제, super free.  FB 매핑 해제는 슈퍼클래스 몫이라는 Matrox 주석은 커널에서 확인 안 됨 — 실패 경로에서 3 MiB 매핑이 남을 수 있음, 무해 | 없음 |

- **`RDNR2b0State` 9 워드**: `{nonce, build, enter, revert, bootRecords, lastRunid, lastResult, lastLines, flags}`.
  - `flags`: bit 0 `recordEnabled`, bit 1 `latched`, bit 2 `inProgress`, bit 8–15 `cmode`, bit 16–31 위치(`bus<<8 | dev<<3 | fn`).
  - 예: 03:0b.0 → python3 `hex((3<<8)|(0x0b<<3)|0)` → `0x358`.
- State 읽기는 락이 없다.  도구는 기록 전후에만 읽는다.

## 4. 기록 (`osrdn_record_run`)

- 모든 기록 줄은 `RDN-R2B0 <runid> <kind> ... seq=<k>` 이다.
- **순서 원칙**: 하드웨어 단계마다 그 단계 값을 먼저 모두 읽고 RAM 에 두며, 단계 사이에 줄을 찍는다(IOSleep 20 ms).
  - "모든 값 먼저" 는 **단계 안** 규칙이다.  R2a 도 단계 사이에 줄을 찍었다.
  - PLL 묶음 안·VGA 단계 안에는 줄·대기·시각 읽기가 없다.

### 4-1. 순서

1. `begin version=2 boot=<nonce8> build=<hex8> enter=<n> revert=<n> cmode=<n> loc=<bb:dd.f> key=yes`
2. **PCI**: R2a 스캔·브리지(`ctl3c`)·카드·cfg 덤프.
   - RV280 기능이 정확히 1 개, 그 위치 = init 위치, BAR2 = init 때 RAM 값이어야 한다.
   - 아니면 `stop reason=pci-*` → 걸쇠.
3. **생존·시간**:
   - 생존 8 표본을 읽는다.  각 `IODelay(2000)` 앞뒤로 `IOGetTimestamp` 를 읽는다.
   - `frame60`: `IOSleep(60)` 앞뒤로 시각과 FRAME 을 읽는다.
   - **1 s 창**: `IOSleep(1000)` 앞뒤로 시각과 FRAME 을 읽는다.  59.94 Hz 에서 ±1 프레임은 ±1.7 % 다.
   - 경과 규약(상위 §4):
     - `if (t1 <= t0)` → **미측정**(0 이 아니라 표지)
     - 차이 > 0xFFFFFFFF ns → 포화
     - 32 비트로 자른 뒤 나누기
     - `if` 는 분리한다
   - VLINE 이 정적이면 `stop reason=vline-static` → 걸쇠.  이후 인덱스 쓰기는 없다(PLL·VGA 모두).
   - 줄: `live`×8, `frame60`, `time d0..d6=<us|unm|sat> s60=<us|unm|sat> f60=<n> s1000=<us|unm|sat> f1000=<n>`(코드 착수 때 파서 문법에 맞춰 확정)
4. **레지스터**: R2a 50 개.
5. **PLL**: R2a 묶음 10 개 + `PPLL_DIV_1`·`2`(0x05·0x06, S23) = 12 개.
   - `pllbusy`·`pllabort` 가 나오면 **VGA 단계를 건너뛴다**(`stop reason=pll-*` 뒤 VGA 없음) → 걸쇠.
   - 묶음이 다 끝나면 `CLOCK_CNTL_INDEX` 를 한 번 더 읽어 **`idxend val=<hex8>` 줄**로 남긴다(Q14: 이 값이 없으면
     `indexend` 게이트를 게이트 줄 자신으로 검증하게 된다).
6. **VGA(§4-3)** — 줄 2 개.
7. **판정(§4-4)**.
8. `end lines=<n>`

- 줄 수는 120 줄이다(개정 2 + Q14 의 `idxend` 줄).  120 줄 × 20 ms + 60 ms + 1000 ms + 7×2 ms ≈ 3.47 s(계산은 §4-6).

### 4-2. PLL 묶음

- R2a `pllGroup`/`pllSnapshot` 을 `osrdn_pll.c` 로 옮긴다.
- **소스 드리프트 검사**(`check_drift_src.py`): R2a `RDNR2aProbe.m` 의 두 함수 본문과 대조해 검토한 hunk 만 허용한다(표 크기·접두·줄 함수 이름·포트 이음새).  허용 목록 파일은 코드와 함께 검토 대상이다.
- 역어셈블 게이트는 헬퍼 셋 그대로다.

### 4-3. VGA 표준 레지스터 (`osrdn_port` 이음새)

- **절차**:
  - MISC(0x3CC 읽기) → bit 0 으로 색/단색 기저 결정
  - SEQ 0–4 → CRTC 0–0x18 → GR 0–8.  각 원래 인덱스를 먼저 읽고 끝에 복원한다.
  - ATTR 0x10–0x14: 상태 포트 읽기로 플립플롭 리셋 → 0x3C0 읽기로 원래 인덱스 `ai` → `i|0x20` 쓰기 → 0x3C1 읽기 → … → 리셋 → `ai` 쓰기 → 리셋.  끝 상태는 인덱스 상태다.
- **보호**:
  - 단계 전체를 **한 번의 `splhigh`** 안에 둔다(줄·대기·시각 없음).  커널 콘솔 애니메이션 타이머가 GR·SEQ2 를 락 없이 쓰기 때문이다(S30).
  - `misc == 0xff` 이면 `vga undecoded` 로 기록하고 ATTR 쓰기를 건너뛴다.
  - 플립플롭의 **원래 상태는 복원할 수 없다**(표준 VGA 에서 읽을 수 없다).  모든 쓰기 주체는 **쓰기 전에 리셋**한다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).  우리는 인덱스 상태로 끝낸다.
- **기대값**(파서 독립, S17 커널 표):
  - 비교 대상:
    - MISC `e3`
    - SEQ0 `03`·SEQ1 `01`·SEQ3 `00`·SEQ4 `06`(S30: 모드셋만 씀)
    - CRTC **타이밍**(0x00–0x09, 0x10–0x18)
    - CRTC **커서·시작 주소**(0x0A–0x0F) — 따로 보고
    - ATTR[0x10..0x14] = `01 00 03 00 00`
  - GR 0–8·SEQ2 는 콘솔이 모드셋 전 값을 복원하고 애니메이션이 쓰므로 기록만 한다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
  - 다르면 `vga-state-differs`(`cmode=2` 부트 로더 상태, VBE 콘솔 등)로 기록한다 — FAIL 이 아니다.
  - 같으면 S14(PAS 세운 읽기)가 이 카드에서 실측된다.

### 4-4. 판정 (판정 기계 공유, 기대값은 데이터)

- `osrdn_gate_eval(table, values)` 는 비교·판정·줄 출력만 한다.
- 기대 표는 **개정 5 기대값을 담은 데이터**다(상위 §4 0·1 단계).  R2b 는 같은 기계에 개정 6 표를 넣는다 — 코드 공유이지 판정 공유가 아니다.
- 항목(개정 2 에서 명시 — 개정 0 문서가 덮어써져 "개정 0 과 같다" 는 가리킬 곳이 없었다.  개정 0 목록은 대화 기록에서 되찾았다).  "빌드 스탬프" 는 뺀다(런타임 비교 대상이 없다).
  - **0 단계**(상위 §4 0 단계 행):

    | 이름 | 조건 | 기대 출처 |
    |---|---|---|
    | `aper0` | `CONFIG_APER_0_BASE` = BAR0 & ~0xf | init RAM |
    | `apersize`·`memsize` | `CONFIG_APER_SIZE`·`CONFIG_MEMSIZE` ≥ 0x300000(FB 매핑 길이) | 상수 |
    | `displaybase` | `(MC_FB_LOCATION & 0xffff) << 16` = `DISPLAY_BASE_ADDR` | 같은 기록 |
    | `mcfb`·`mcagp`·`hostpath`·`surface` | `MC_FB_LOCATION`·`MC_AGP_LOCATION`·`HOST_PATH_CNTL`·`SURFACE_CNTL` = R1 | R1 로그 |
    | `divsel` | `CLOCK_CNTL_INDEX` bit 8–9 = 3(`RADEON_PLL_DIV_SEL`, radeon_reg.h 291 행) | 상수 |
    | `crtc2` | `CRTC2_GEN_CNTL` bit 25 = 0(`RADEON_CRTC2_EN`, 414 행) | 상수 |
    | `fpon` | `FP_GEN_CNTL` bit 0 = 0(`RADEON_FP_FPON`, 840 행) | 상수 |
    | `cpmode` | `CP_CSQ_CNTL` bit 28–31 = 0(`RADEON_CSQ_PRIDIS_INDDIS`, 3143 행) | 상수 |
    | `rbbm` | `RBBM_STATUS` bit 31 = 0(`RADEON_RBBM_ACTIVE`, 1487 행) | 상수 |
    | 방해 9 개 | `OVR_CLR`·`OVR_WID_LEFT_RIGHT`·`OVR_WID_TOP_BOTTOM`·`OV0_SCALE_CNTL`·`SUBPIC_CNTL`·`VIPH_CONTROL`·`I2C_CNTL_1`·`CAP0_TRIG_CNTL`·`CAP1_TRIG_CNTL` = R2a | R2a 로그 |
    | 출력 5 개 | `TV_DAC_CNTL`·`DISP_HW_DEBUG`·`DISP_OUTPUT_CNTL`·`DAC_CNTL2`·`CRTC_OFFSET_CNTL` = R2a | R2a 로그 |
    | `bridgevga` | 카드 버스를 포함하는 모든 브리지의 config 0x3c bit 19 = 1(VGA 전달, pcireg.h 1420–1425 행) | 상수 |

  - **1 단계**(상위 §4 1 단계 행, 팔레트는 R2b-0 에서 읽지 않는다):

    | 이름 | 조건 |
    |---|---|
    | `refdiv` | `PPLL_REF_DIV` & 0x3ff ∈ {6, 12}(`RADEON_PPLL_REF_DIV_MASK`, 1466 행) |
    | `ppllcntl` | `PPLL_CNTL` & 0x70003 = 0(bit 0 `RESET`·1 `SLEEP`·16–18 원자 갱신, 1452–1458 행) |
    | `vclksrc` | `VCLK_ECP_CNTL` & 3 = 3(`RADEON_VCLK_SRC_SEL_MASK`, 1656 행; R2a 값) |
    | `indexend` | PLL 단계 끝 `CLOCK_CNTL_INDEX` = 시작 `p0` |

  - 32 항목(python3 `13+9+5+1+4` → `32`).  PLL 단계가 중단되면 1 단계 항목은 `pass=na` 로 찍고 판정은 `refuse` 로 센다.
  - 줄: `gate step=<0|1> name=<이름> val=<hex8> want=<hex8> pass=<1|0|na>`, 이어 `verdict gates=32 refused=<k> result=enter|refuse`.
  - 기대 표는 호스트 `gen_expect_r2b0.py` 가 R1·R2a **원시 로그**에서 만든 `osrdn_expect.h` 다.  생성기는 §6-1 사람 출처 표와 대조해 다르면 실패한다.  R2a 로그 대조(python3): `MC_FB_LOCATION & 0xffff` → `0`, `CP_CSQ_CNTL >> 28` → `0`, `CRTC2_GEN_CNTL` bit 25 → `0`, `RBBM_STATUS` bit 31 → `0`, `PPLL_CNTL & 0x70003` → `0`, `VCLK_ECP_CNTL & 3` → `3`, 브리지 00:1e.0 `ctl3c` bit 19 → `1`.
- **R2b-0 의 권위 있는 출력은 원시값과 파서의 독립 재판정**이다.  드라이버 판정 줄은 C 판정 코드와 파서의 교차 확인이다.

### 4-5. 대기

- 사용하는 대기: 생존 `IODelay(2000)`×7, `IOSleep(60)`, `IOSleep(1000)`, 줄 간격 `IOSleep(20)`.
- 모두 고정 횟수다.  루프 대기는 없다.

### 4-6. 줄 수 (Python)

`begin 1 + pci·bridge·cfg 7 + mmio 1 + live 8 + frame60 1 + time 1 + reg 50 + pllstart 1 + pll 12 + pllend 1 + idxend 1 + vga 2 + gate 32 + verdict 1 + end 1`
- python3 `sum(...)` → `120`
- 페이싱 `120*0.020` → `2.4` s
- 대기 `60+1000+7*2` → `1074` ms
- 합 → `3.474` s

## 5. 사용자 도구 `rdnr2b0.m`

| 단계 | 조건 | 실패 |
|---|---|---|
| `lookUpByDeviceName:"Display0"` | `IO_R_SUCCESS` | 종료 3 — 복구하고 재시도하지 않는다(번들 미적재·init 실패) |
| `getIntValues:"IOGetDisplayInfo"` count 5 | `IO_R_SUCCESS` && 반환 count == 5 && `w[0]`=1024 && `w[1]`=768 | 종료 4 |
| `getIntValues:"RDNR2b0State"` count 9 | `IO_R_SUCCESS` && count == 9 && build == 기대 스탬프(인자) && `flags` bit 0 = 1 && bit 1 = 0 && 위치 = `0x358` | 종료 5 |
| `setIntValues:"RDNR2b0Record"` | 반환값 출력 | -729(키 No)=6, -725(진행 중·한도)=9, -728(걸쇠)=10, -711(재정의 미도달)=11, 그 밖 오류=7 |
| 기록 뒤 `RDNR2b0State` | bootRecords 증가·lastLines 출력 | 8 |

- **`state` 모드**(Q14): `rdnr2b0 <runid> <build> state` 는 위 1–3 단계만 하고 끝난다.  클래스는 State 읽기마다
  `RDN-R2B0 state boot=… build=… records=… last=… flags=… cmode=… loc=…` 를 IOLog 하므로, 이것이 **이 부팅의
  시스로그 증명**이다.  `logger` 표지는 쓰지 않는다 — 이 기계의 `syslog.conf` 는 `user.notice` 를 어디로도
  보내지 않는다(`docs/R1C_RESULT.md` 사실 5, `build/r1c/syslog-check.txt`).

빌드: 타깃 `cc -O -Wall -o /tmp/rdnr2b0 rdnr2b0.m -lDriver`.  이 도구는 호스트에서 흉내 내지 않는다(§10).

## 6. 호스트 도구 (`tools/r2b0/`)

### 6-1. 파서 `parse_r2b0.py`

- R2a 파서의 **문법·사슬·카드·매핑·생존·PLL 묶음 규칙**만 가져온다.
- **가져오지 않는 것**(Q13 B3.1): `parse_r2a._judge` 의 R1 대비 판정(문서화 비트 차이 FAIL, 미정의 비트 REPLAN)과 `PLL_DIV_SEL`-대-R1 FAIL.
  - 활성화 부팅에서는 바로 그 값들이 R1(VESA 800×600 부팅)과 다를 것이다.
  - 이것들은 **기록(facts)** 으로 옮긴다.
- **판정**:
  - (a) 위 R2a 규칙 + PLL 12 묶음
  - (b) VGA 기대값(§4-3, 파서 안에 원시 바이트와 출처 VA)
  - (c) 게이트 독립 재판정
  - (d) boot nonce 일치, 위치 = `03:0b.0`, `cmode` 가 init 줄과 같음
- **기대값 출처 표**:
  - 파서는 드라이버가 컴파일한 생성 헤더를 읽지 않는다.
  - 드라이버용 헤더 생성기에는 매핑 오류 변이를 넣어 파서 대조가 FAIL 하는지 본다.

  | 기대값 | 원시 출처 | 사람 출처 | 쓰임 |
  |---|---|---|---|
  | `OV0_SCALE_CNTL` `807f0000`, `TV_DAC_CNTL` `07660142`, `DISP_HW_DEBUG` `00020000`, `DISP_OUTPUT_CNTL` `10000000`, `DAC_CNTL2` 0, `CRTC_OFFSET_CNTL` `10000000`, 방해 8 개 0 | R2a 로그 | 상위 §4 0 단계 행 | 게이트 재판정 |
  | `MEM_CNTL` `32003200`, `MEM_TIMING_CNTL` `1a395323` | R2a 로그 | 상위 G9 | **FAIL**(불변) |
  | `CONFIG_APER_0_BASE` `e0000000` = BAR0, `DISPLAY_BASE_ADDR` 0 | R2a 로그 | 상위 F4 | **FAIL**(`CONFIG_APER_0_BASE`, 불변) / 재판정 |
  | `CONFIG_MEMSIZE`·`CONFIG_APER_SIZE` 128 MiB | R2a 로그 | 상위 F9 | **FAIL**(불변) |
  | PCI ID `1002:5960`, 위치 `03:0b.0` | R2a 로그 | `logs-pcils-20260915.txt` 37 행 | **FAIL** |
  | `HOST_PATH_CNTL` `70000000`·`MC_FB_LOCATION` `1fff0000`·`MC_AGP_LOCATION` `27ff2000`·`SURFACE_CNTL` `00000100` | R1 로그 | `docs/R1_RESULT.md` 35·36·43 행(코드 착수 때 확인 — 개정 2 초안의 "없음" 은 틀렸다) | 게이트 재판정 |
  | CP 모드·`RBBM_STATUS.ACTIVE`·`CRTC2_EN`·FP 켜짐·`PLL_DIV_SEL`·PLL 1 단계 | 상수 조건(§4-4, radeon_reg.h 행) | 해당 없음 | 게이트 재판정 |
  | VGA 표 | 미러 `mach_kernel` VA 바이트 | S17(Matrox 스냅샷 부분 대조) | 기록(`vga-state-differs`) |

  - 사람 값 10 개가 R2a 원시 로그와 같음은 Q13 판정 B3.3 에서 Python 으로 확인했다.  파서는 실행마다 다시 대조한다.
- **결과 분류**:
  - `FAIL`: 기록 결함, nonce·위치·cmode 불일치, 위 불변 레지스터 차이
  - `PASS-ENTER`: 게이트 전부 pass
  - `PASS-REFUSE`: 거절 게이트 있음 — 값으로 개정 6
- **시각은 기록 전용**이다.  미측정은 개수만 센다.  `iodelay/iosleep` 비율은 내지 않고 따로 보고한다.
- **기록(facts)**:
  - PLL: refdiv·`PLL_DIV_SEL`·`PPLL_DIV_0..3` 과 각 슬롯 VCO(Python, 범위)
  - R1·R2a 대비 차이 전부(문서화·미정의 비트 구분)
  - VGA 대조 결과(타이밍·커서 분리), MISC 클럭 선택, `ATTR[0x10]`, `cmode`
  - 시간: 창 셋의 µs·프레임, VLINE 환산 대비
  - enter·revert 수(enter > 1 이면 WindowServer 재기동 흔적으로 기록)
- **자체검사 합성 로그와 기대 결과**:

  | 경우 | 기대 |
  |---|---|
  | 정상(커널 콘솔 표 그대로) | PASS-ENTER 또는 PASS-REFUSE(게이트 표대로) |
  | 각 kind 누락 | FAIL |
  | 판정 줄 뒤집기 | FAIL |
  | VGA 줄 길이 오류 | FAIL |
  | VGA 커널 표와 다름 | PASS-* + `vga-state-differs` |
  | CRTC 커서 바이트만 다름 | PASS-* + 커서 차이만 보고 |
  | 시각 미측정 | PASS-* |
  | nonce·위치·cmode 불일치 | FAIL |
  | 불변 레지스터 차이 | FAIL |
  | `CRTC_GEN_CNTL`·`PLL_DIV_SEL` 이 R1 과 다름 | **PASS-*** + facts |
  | 12 번째 PLL 없음 | FAIL |
  | pllabort 뒤 VGA 줄 존재 | FAIL |

### 6-2. 시뮬레이터 `sim_r2b0.py`

- 모형:
  - R2a 세계
  - VGA 포트: 인덱스/데이터, 속성 플립플롭·PAS, 상태 포트
  - 가상 `IOGetTimestamp`: 역행 창 주입 가능
  - `splhigh` 깊이
  - 파라미터 호출(재진입·연속 호출 주입)
- 대상: `osrdn_record.c`·`osrdn_pll.c`(바꾸지 않고 32 비트).  포트·MMIO·spl·시각은 모형 단위로 바꾼다.
- **R2a 위반·세계·변이의 처리**(`simworld2a.c`·`sim_r2a.py` 줄 단위):

| R2a 항목 | R2b-0 |
|---|---|
| MMIO base·offset·정렬, write8/32 규칙, data-*, store-while-busy, write32-no-abort, group-after-stop(`stopped`), log/sleep/delay-while-masked, splhigh-nested, splx, left-masked | **유지** |
| `inb`(모든 inb 위반) | **반전**: 허용 목록 포트(§6-3)이고 VGA 단계 안일 때만 허용, 그 밖은 위반 |
| `outb`(모든 outb 위반) | **반전**: 인덱스 포트·속성 인덱스 규칙(§4-3)만 허용.  0x3C0 쓰기가 인덱스인지는 플립플롭 모형이 가른다 |
| `inw`·`outw` | 유지 |
| `outl-port`·`outl-latch`·`inl-port`·`inl-unlatched`·`cfg-offset` | 유지 |
| `second-map`·`map-length`·`map-not-a-bar2`·`host-mmap` | **대체**: 기록 중 map 호출은 모두 위반.  PROT_NONE 기저 매핑은 하니스가 직접 만든다(변이 "direct MMIO read" 의 `sim rc=-11` 유지) |
| `unmap`·`left-mapped` | **대체**: 기록 중 unmap 호출은 모두 위반 |
| `sleep-inside-live-window` | 유지하되 **기록마다** 계수를 초기화한다(프로세스 전역 `delayCalls` 는 두 번째 기록을 못 지킨다) |
| `too-many-functions`·`scenario-*` | 하니스 규칙, 유지 |
| 세계 `map fails`·`unmap fails` | 제외(기록은 매핑하지 않는다) |
| 세계 `…differs from R1`(FAIL/REPLAN) | **반전**: PASS-* + facts |
| R1 회귀 세계(`sim_r2a.py` 193–200 행) | PCI·BAR·브리지 세계는 **유지**하고 기대를 R2b-0 의 `stop reason=pci-*`·걸쇠로 옮긴다.  R1 판정 문구 전용 기대는 제외한다 |
| 세계 카드 0·2, BAR 검사들, 정적 스캔 | 유지 |
| 페이싱 단언(20 ms × 줄 + 60) | **바꿈**: 20 ms × 줄 + 60 + 1000, 생존 7 호출 14000 µs |
| 변이 `no unmap`·`VGA sequencer write` | 제외(뒤집힌 규칙) |
| 변이 `eleventh PLL index` | 제외 — 새 "13 번째 인덱스 추가"·"12 번째 인덱스 오류" 로 대체 |
| 나머지 R2a 변이 17 개 | 유지.  `r2aRegs`·`RDN-R2A` 기준점은 새 이름으로 다시 잡는다(기준점 0 건이면 하니스가 FAIL) |

- **새 위반**:
  - 데이터 포트 쓰기, 허용 목록 밖 포트 읽기
  - `0x3c0` 에 `i|0x20`·`ai` 외 값, PAS 0 인덱스
  - 인덱스 미복원, 플립플롭 데이터 상태로 끝남
  - VGA 단계가 `splhigh` 밖이거나 안에 대기·줄·시각
  - pllabort·pllbusy·vline-static 뒤 인덱스 쓰기
  - `IOGetTimestamp`·IOLog 가 **어느** `splhigh` 안에서든(test-and-set 포함)
  - 재진입 두 번째 호출이 하드웨어에 닿음
  - 부팅당 3 번째 기록이 하드웨어에 닿음
  - **걸쇠 뒤 요청이 하드웨어에 닿음**
  - 어떤 출구 뒤 `inProgress` 가 남음
  - BAR2 ≠ init RAM 인데 기록 계속
- **새 세계**:
  - 커널 콘솔 상태(S17 표 그대로, `PLL_DIV_SEL` 0·refdiv 12 — PLL 은 합성)
  - R2a 부팅 상태
  - 부트 로더 상태(`cmode=2`, VGA 표 다름)
  - 단색(MISC bit 0 = 0), VGA 미해독(`0xff`)
  - 시계 역행
  - pllabort 세계에서 VGA 생략 + 두 번째 요청 -728
  - vline-static 뒤 두 번째 요청 -728
  - 재진입(-725), 세 번째 요청(-725), 키 No(-729)
  - BAR2 변경
- **새 변이**:
  - SEQ 인덱스 미복원, 데이터 포트 쓰기 추가, PAS 없는 속성 인덱스, 플립플롭 리셋 제거, 0x00 속성 읽기, DAC 0x3C9 읽기 추가
  - VGA 단계에서 `splhigh` 제거
  - pllabort 뒤 VGA 계속
  - `t1<=t0` 검사 제거
  - test-and-set 을 평범한 플래그로, 임계 구간 안에 IOLog
  - 걸쇠 설정 제거, `inProgress` 해제를 한 출구에서 제거
  - 13 번째 인덱스 추가, 12 번째 인덱스 오류
  - 판정 표 한 항목 뒤집기
- **64 비트 나눗셈 변이는 여기 두지 않는다**(링크 실패) → §6-3.

### 6-3. 소스·목적 파일 규칙 `check_r2b0_src.py`

- **ObjC 클래스**:
  - `inb|outb|inw|outw|inl|outl|osrdn_in|osrdn_out|rdnMmio|IOReadRegister|IOWriteRegister|IOReadModifyWriteRegister` 호출 0
  - `enterLinearMode`·`revertToVGAMode` 본문 호출은 `IOLog` 와 `[super revertToVGAMode]` 뿐
  - **`get/setIntValues:` 는 자기 이름 비교 실패 경로가 `return [super …]` 한 문장뿐**(구조 검사)
  - `get/setCharValues:` 재정의 0
  - `mapFrameBufferAtPhysicalAddress` 1, `IOMapPhysicalIntoIOTask` 1(이름 상수 0x2000), `setMemoryRangeList` 1
  - `valueForStringKey:` 는 init 에만 있고 뒤에 `freeString:` 이 있다
  - init 실패 경로는 `return [self free]`
- **모드셋 부재**: MMIO 쓰기 호출은 `osrdn_pll.c` 의 `rdnMmioWrite8` 2·`rdnMmioWrite32` 1 뿐, 다른 파일 0.
- **포트**:
  - `osrdn_outb` 의 포트 인자는 `VGA_SEQ_INDEX`·`VGA_GR_INDEX`·crtc 기저 변수·`VGA_ATTR_INDEX` 만
  - `osrdn_inb` 의 포트 인자는 `VGA_MISC_READ`(0x3CC)·`VGA_SEQ_INDEX`/`DATA`(0x3C4/5)·`VGA_GR_INDEX`/`DATA`(0x3CE/F)·crtc 기저·crtc 기저+1·상태(crtc 기저+6)·`VGA_ATTR_INDEX`(0x3C0)·`VGA_ATTR_READ`(0x3C1) 만
  - `osrdn_outl` 은 `PCI_CFG_ADDR` 만, `osrdn_inl` 은 `PCI_CFG_DATA` 만
  - 데이터 포트 이름 상수 쓰기 0
  - "crtc 기저 변수" 의 값은 텍스트로 증명할 수 없다 — 시뮬레이터의 단색·색 세계가 값을 확인한다
  - `osrdn_port.c` 는 네 함수만, 각 한 문장
  - `osrdn_*.c`·`OSRDNDisplay.m`·`RDNR2aMMIO.m` 에 `switch` 0(§6-4 간접 점프)
- **임계 구간**: `splhigh(` 와 짝 `splx(` 사이에 함수 호출은 `osrdn_inb/outb`(VGA 단계)와 PLL 헬퍼(PLL 묶음)뿐이다.  test-and-set 구간은 호출 0.
- **시각**: `IOGetTimestamp` 호출이 `splhigh`…`splx` 사이에 없다(S27).  64 비트 나눗셈·나머지 연산자가 `ns_time_t` 식에 없다(텍스트 규칙).
- **목적 파일**(`-O0 -fno-inline`, 호스트): R2a 규칙 + `__udivdi3`·`__umoddi3`·`__divdi3` 참조 0.  64 비트 나눗셈 변이는 여기서 이 이름으로 FAIL 해야 한다(호스트 `gcc -m32` 로 발동 확인, Q13 판정 E5.6).
- **`nm -u`**(타깃): `___udivdi3`·`___umoddi3`·`___divdi3` 없음, `_basicConsoleMode` 는 커널 심볼표에 있음.
- 각 규칙에 변이를 두고, 같은 실행에서 기준 PASS·변이 FAIL 을 확인한다.

### 6-4. 역어셈블 게이트 `check_reloc.py` 확장

- **스캔 단위는 코드 심볼 범위별**이다(기존 `function_ranges`).  `__text` 전체 선형 스윕은 쓰지 않는다 — PASS 한 R2a reloc 에서 거짓 `in` 이 두 개 나온다(`0xf26`, `0xf5e`, 함수 사이 0 채움에서 어긋남).
- **범위 밖 바이트**: 어떤 범위에도 속하지 않는 `__text` 바이트는 `00` 또는 `90` 만 허용한다.
- **간접 점프**: 범위 안 `jmp *` 는 FAIL(표가 스윕을 어긋나게 할 수 있다).  소스 `switch` 0 규칙과 짝이다.
- **포트 명령어**: 해독된 명령어 `in`·`out`·`ins*`·`outs*` 를 모든 형태(DX·즉치·문자열·`rep`·`66` 접두)로 센다.
  - `_osrdn_inb`: `in (%dx),%al` 정확히 1
  - `_osrdn_inl`: `in (%dx),%eax` 정확히 1
  - `_osrdn_outb`: `out %al,(%dx)` 정확히 1
  - `_osrdn_outl`: `out %eax,(%dx)` 정확히 1
  - 그 밖 모든 범위: 0.  `%ax` 형태(`66` 접두)는 네 함수 안에서도 FAIL.
- 헬퍼 셋(R2a 그대로)의 저장 폭 규칙은 유지한다.
- `lock incl <abs32>`(ioPorts.h 계수기 `_xxx.N`)는 32 비트 비스택 저장으로 분류된다.  현 규칙에는 영향이 없고, 앞으로 "MMIO 헬퍼 밖 저장 금지" 규칙을 만들면 대상이 `_xxx.N` 데이터 심볼인 경우를 면제로 적는다.
- **자체검사 변이**(합성 Mach-O):
  - 다른 함수에 `out %al,$0x80`
  - `outsb`
  - `_osrdn_outl` 에 `66 ef`
  - 함수 사이 0 채움 뒤 스윕이 `EE` 로 읽히는 바이트열 — 범위별 스캔은 PASS 여야
  - 범위 밖 비0 바이트
  - 범위 안 `jmp *%eax`
- 이 게이트는 PIT·PIC 쓰기(커널 이미지 안)를 보지 못하고 볼 필요도 없다.

### 6-5. 드리프트·하니스

- `check_drift_src.py`: §4-2.
- `check_target_r2b0.py`: 스크립트 하니스.  lint 에 다음을 둔다.
  - 기존 `ps` 금지 유지(`tools/r1c/check_target_r1c.py` 50 행 규칙)
  - `set -e`·`grep -c` 종료 코드 사용 금지
  - 복원 스크립트의 `mv`·`cp`·`chmod`·`chown` 대상은 `/private/Drivers/i386/*.config/`·`/me/rdn-r2b0/` 아래만
- `check_cfgdiff.py`: §7-3.  자체검사를 둔다 — 캡처한 `build/r2b0/emu10k1/` 사본으로 "키 순서만 바뀐 표 = 같음", `Default Table` 추가 허용·거절 경우, 값 한 개 변경 = 멈춤.

## 7. 타깃 스크립트와 절차 (`tools/r2b0/`)

| 스크립트 | 하는 일 | 쓰기 |
|---|---|---|
| `target-build-r2b0.sh <tar> <sum> <blocks>` | R2a 빌드 모양 + 빌드 표(키 `Yes`·Server Name) + `nm -u`(`_basicConsoleMode` 포함) + 사용자 도구 `cc` → reloc·도구를 NFS `<runid>/` 로 복사·sum, `BUILD_PASS`(재부팅 뒤에도 남는 표지 — `/tmp` 는 부팅 때 지워진다) | `/tmp`, NFS |
| (호스트) `check_reloc_r2b0.py` | §6-4 → `R2B0RELOC_PASS` | — |
| `target-install-r2b0.sh closed=yes [fresh]` | Matrox 설치 모양(S7), `Active Drivers` 에 `OSRDNDisplay` 가 있으면 거절, 후보·설치본 표마다 `"Server Name"` 1 줄, 설치 reloc sum = `BUILD_PASS`, NFS `INSTALLED`.  **기계의 인스턴스 표를 바이트 그대로 둔다**.  `fresh` 는 그 대신 빌드 산출 표를 설치한다(이 프로젝트가 스스로 넣었다가 정정한 표에만; 옛 표는 `.prev` 에 남는다) | 번들 디렉터리 |
| `target-cfgsnap-r2b0.sh <pre\|postraw\|post\|post2\|post3\|postb> <tag> closed=yes` | §7-1.  `postraw` 는 Configure 가 남긴 그대로의 상태(주차 전) | NFS 만 |
| `target-park-extra-r2b0.sh closed=yes` | §15-2 B.  Configure 가 더 만든 `OSRDNDisplay.config/Instance1..N` 을 `/me/rdn-r2b0/parked-activate.<tag>/` 로 옮겨 `Instance0.table` 하나만 남긴다.  다른 번들은 건드리지 않는다 | 번들 디렉터리·`/me` |
| (호스트) `check_cfgdiff.py precheck\|activate\|same\|restored\|record` | §7-3.  PASS 면 `PRECHECK_PASS`·`ACTIVATE_PASS`·`RESTORED_PASS` 를 뒤 스냅샷 디렉터리에 쓴다 | — |
| (호스트) `pack_restore_r2b0.py <tag>` | `pre` 사본에서 복원 묶음을 만든다(§7-2) | 호스트 |
| `target-stage-restore-r2b0.sh <tag>` | 묶음을 `/me/rdn-r2b0/set.<tag>/` 로 복사, `CURRENT` 에 태그, sum 대조 | `/me` |
| `/me/rdn-r2b0/check.sh` | 읽기 전용: 묶음 sum, 현재 표와의 차이 목록 | 없음 |
| `/me/rdn-r2b0/restore.sh` | §7-2 | Drivers 표 |
| `target-run-r2b0.sh <runid>` | NFS 표지(`BUILD_PASS`·`R2B0RELOC_PASS`·`INSTALLED`)와 설치 reloc sum → `Active Drivers` 에 `OSRDNDisplay`·`VGA` 없음 → `check.sh` 가 묶음 정상 → NFS 도구를 `/tmp` 로 복사·sum → **`rdnr2b0 … state`(하드웨어 접근 없음) 로 드라이버가 낸 상태 줄이 10 s 안에 syslog 에 오는지 확인** → 런 ID 선점 → 여기까지의 증거를 NFS 로 복사·`sync` → `rdnr2b0 <runid> <stamp>` → 끝 줄 대기 60 s → 로그·도구 출력·`check.sh` 출력·`kl_util -s`·`run.done` 을 NFS 로.  Configure.app 확인은 넣지 않는다 — 활성화 부팅에는 GUI 가 없다 | `/tmp`, NFS |

### 7-1. 스냅샷 `target-cfgsnap-r2b0.sh`

- 모든 `/private/Drivers/i386/*.config/Instance*.table` 과 `System.config/Default.table` 을 NFS `build/r2b0/cfg/<tag>/<mode>/` 로 복사한다.
- `ls -lg`·BSD `sum`·`wc -c` 목록을 함께 쓴다.
- 인자 `closed=yes` 는 operator 가 "Configure.app 을 닫았다" 고 말한 것을 기록한다.  `ps` 로 확인하지 않는다(lint).  인자가 없으면 스냅샷을 쓰지 않고 끝낸다.
- 호스트는 NFS 사본의 sum 을 타깃 목록과 대조한다(낡은 크기 읽기 함정).

### 7-2. 집합 복원 `/me/rdn-r2b0/restore.sh`

- **호스트가 발행하는 고정 파일**이다.  인자는 없다.  sum 을 기록한다.
- 묶음 `/me/rdn-r2b0/set.<tag>/`(태그는 `CURRENT` 한 줄):
  - `pre` 스냅샷의 **모든** `*.config/Instance*.table` 사본
  - `manifest`: 줄마다 `<상대 경로> <모드 8진> <소유자> <그룹> <sum> <블록> <바이트>`
- 순서:
  1. 묶음 전 파일의 sum 을 `manifest` 와 대조한다.  하나라도 다르면 **아무것도 쓰지 않고** 종료 2.
  2. manifest 의 각 파일: 현재 파일과 `cmp -s` 가 같으면 건너뛴다.  다르거나 없으면 같은 디렉터리에 `.rdnnew` 로 복사 → `chmod`/`chown`(manifest 값) → `cmp -s` → `mv`(원자적).
  3. manifest 에 없는 `*.config/Instance*.table`(예: Configure 가 만든 `OSRDNDisplay.config/Instance0.table`)은 `/me/rdn-r2b0/parked.<tag>/<디렉터리>/` 로 옮긴다.
  4. 검증: manifest 전 파일 `cmp -s` 같음, `ls -l` 모드·소유자 같음, manifest 밖 인스턴스 표 0 → `sync`.  하나라도 틀리면 종료 3(재부팅하지 않는다).
- 출력은 화면과 `/me/rdn-r2b0/restore.log` 에 남긴다.  NFS 를 쓰지 않는다.
- 활성화 부팅의 원복은 **항상 이 스크립트**다(GUI 없음).  Configure.app 원복은 GUI 가 있는 부팅에서만 쓸 수 있고, 그때도 뒤이어 이 스크립트로 집합을 맞춘다.

### 7-3. Configure.app 활성화와 `check_cfgdiff.py`

**표 파서**(엄격):
- 허용 줄: `"키" = "값";`, `/* … */` 주석(여러 줄 포함), 빈 줄.
- 거절: 그 밖 모양, 중복 키, 비 ASCII.

**모드 `activate`(pre → post)** — 하나라도 어기면 멈춘다:
1. 파일 집합: post = pre + `OSRDNDisplay.config/Instance0.table` 하나.  `VGA.config/Instance*.table` 은 없어지거나 바뀌어도 된다(기록).  그 밖 추가·삭제 0.
2. System·VGA·OSRDNDisplay 밖의 표: 키→값 동일(순서 무시).
3. `System.config/Instance0.table`: `Active Drivers` 밖 키→값 동일.  `Active Drivers` 토큰 다중집합 = pre 에서 `VGA` 하나를 `OSRDNDisplay` 로 바꾼 것(순서는 기록).
4. `System.config/Default.table`: 바이트 동일.
5. `OSRDNDisplay.config/Instance0.table`:
   - 키→값이 설치된 `Default.table` 과 같다.  허용 차이는 `Location`·`Default Table` 뿐이다.
   - **`"RDN R2B0 Record" = "Yes"`**, `"Instance" = "0"`.
   - `Location` 은 `""` 이거나 `Dev:11 Func:0 Bus:3` 이다.
6. 권한: 모든 표 root·wheel, group/other 쓰기 없음.  다시 쓰인 표의 모드는 pre 와 같다.
7. post 와 postb(재부팅 요청 직전 스냅샷)가 바이트 동일.

**모드 `restored`(pre → 복원 뒤)**: 파일 집합 동일, 모든 표 **바이트 동일**, 모드·소유자 동일.

**모드 `record`(a → b)**: 차이만 적는다(판정 없음).

**활성화 전 점검**(모드 `precheck`, pre 하나):
- 드라이버마다 인스턴스 표 1 개(2 개 이상이면 멈춤 — 2026-09-15 VGA 중복 사고).
- 비어 있지 않은 PCI `Location` 은 최신 `pcils` 캡처의 그 위치 ID 가 표 `Auto Detect IDs` 에 있어야 한다.  캡처 날짜를 줄에 적는다.
- `Active Drivers` 에 `VGA` 가 정확히 하나, `OSRDNDisplay` 0.

## 8. 리허설 (활성화 전)

전제: 번들 설치 완료(§9 3).

1. **R-1 — 재부팅 없는 Configure 왕복**
   1. operator: Configure.app 을 닫았다고 알린다.  `cfgsnap pre R1 closed=yes` → 호스트 `precheck`.
   2. 호스트 `pack_restore_r2b0.py R1` → 타깃 `stage-restore R1` → `check.sh`(차이 0).
   3. operator: Configure.app 에서 `VGA` → `OSRDNDisplay`, 저장, 닫기.  `cfgsnap post R1` → `check_cfgdiff activate`.
      - FAIL 이어도 **그대로 4 로 간다**(재부팅 금지).  FAIL 내용이 개정 사유다.
   4. operator: Configure.app 에서 `OSRDNDisplay` → `VGA`, 저장, 닫기.  `cfgsnap post2 R1` → `check_cfgdiff record pre post2`.
   5. telnet `sh /me/rdn-r2b0/restore.sh` → `cfgsnap post3 R1` → `check_cfgdiff restored pre post3`.
   - 이것으로 Configure 의 실제 파일 집합 동작(템플릿·삭제·`Default Table`·키 값)을 보고, 집합 복원의 쓰기 경로를 재부팅 전에 돌린다.
   - **3 과 5 사이에는 디스크에 활성화 구성이 있다.**  이 사이 예기치 않은 재부팅은 nxlogd 없는 활성화 부팅이 된다 → telnet 으로 `restore.sh` → 재부팅 → 중단·분류.
2. **R-2 — `config=Default` 복원** (재부팅 1·2, operator 결정: 진행)
   1. `cfgsnap pre R2 closed=yes`.
   2. operator: 부팅 프롬프트에서 `config=Default` 로 부팅한다(재부팅 1).  화면·키보드를 확인하고 **root 로 로그인**한다.
   3. Terminal 에서 `sh /me/rdn-r2b0/check.sh`, `sh /me/rdn-r2b0/restore.sh`(차이 0 이라 쓰기 없음), 로그 확인.
      - `/me` 가 보이지 않으면 멈추고 복구 수단을 다시 설계한다.
   4. 평소대로 재부팅한다(재부팅 2).  `cfgsnap post R2` → `check_cfgdiff restored pre post`(Default 부팅이 표를 바꾸지 않았는지, VGA·OSRDNDisplay 표 포함).

## 9. 실행 순서·게이트·중단

1. 호스트 `hostcheck-r2b0` PASS → `pack_r2b0.py`.
2. 타깃 build → 호스트 `check_reloc.py` → 사용자 도구 빌드.
3. 타깃 install(번들만).
4. R-1(재부팅 없음) → R-2(재부팅 1·2).
5. **활성화**:
   1. operator: Configure.app 을 닫았다고 알린다.  `cfgsnap pre ACT closed=yes` → `precheck`.
   2. `pack_restore_r2b0.py ACT` → `stage-restore ACT` → `check.sh`(차이 0).
   3. operator: Configure.app 에서 `VGA` → `OSRDNDisplay`, 저장, 닫기.
   4. `cfgsnap post ACT` → `check_cfgdiff activate`.  `check.sh` 가 차이 목록을 낸다(원복 대상 확인).
   5. **operator 고지**(아래) → `cfgsnap postb ACT` → 7 번 규칙 PASS → **operator 재부팅(3)**.
6. 부팅 확인: telnet 300 s, `/ndrv`·gcdsd·nxlogd, `kl_util -s`, `syslog` 의 `RDN-R2B0 probe`·`init` 줄.
7. run → 호스트 parse.
8. telnet `restore.sh` → `cfgsnap post3 ACT` → `check_cfgdiff restored` PASS → **operator 재부팅(4)** → 복귀 확인(VGA Loaded, Workspace).

재부팅은 R-2 의 2 회와 활성화·복귀 2 회를 합쳐 모두 4 회다.  R-2 의 두 번째는 평상 부팅이다.

**operator 고지(재부팅 3 전)**:
- 화면은 커널 콘솔 부팅 그림에 머물고 Workspace 는 **나오지 않는다**.  이것이 정상이며 행이 아니다.
- 패닉도 같은 모습일 수 있다(S19) — 판정은 telnet·nxlogd 로만 한다.
- 이 부팅에서는 Configure.app 을 쓸 수 없다.  원복은 telnet `restore.sh` → 재부팅이다.
- **기록 뒤 화면이 비거나 깨져 보여도 패닉이 아니다**: 속성 인덱스 복원은 `0x3C0` 읽기가 인덱스를 돌려준다는 추론
  (S14)에 기대고 있어, 아니라면 콘솔이 빈 화면이 된다.  판정은 telnet 과 로그로만 한다.
- 300 s 안에 telnet 이 없기 전에는 전원을 끄지 않는다.
- 전원을 재투입하면 fsck 가 콘솔 입력을 요구할 수 있고, 마일스톤이 멈춘다(아래).

**R2b-0 게이트** — 다음이 모두 참이어야 PASS:
- 파서 `PASS-ENTER`/`PASS-REFUSE`
- `RDNR2b0State` 의 nonce·build·위치·cmode 가 기록 begin 줄·init 줄(있으면)과 일치, 이 부팅 syslog 표지 뒤의 줄
- enter ≥ 1(수는 기록), 언로드 없이 부팅 계속
- 기록 1 회 완결
- telnet `restore.sh` 1 회 실제 성공
- `check_cfgdiff restored pre(ACT) post3` PASS(파일 집합·바이트·모드·소유자)
- 복귀 부팅에서 VGA Loaded

**즉시 중단·복구**:
- **`check_cfgdiff activate`·`precheck`·`restored` FAIL**: 재부팅을 요청하지 않는다.  `restore.sh` 로 pre 집합을 맞추고(restored 가 FAIL 이면 그 원인부터) 개정한다.
- **부팅 뒤 300 s 안에 telnet 없음**:
  - operator 에게 알린다: 화면은 고지대로여서 패닉과 구별되지 않는다.
  - `config=Default` → root 로그인 → `sh /me/rdn-r2b0/restore.sh` → 재부팅.
  - 이것은 PLAN 중단 1 이다 — 마일스톤을 멈추고 오프라인 분류한다.
- **telnet 은 되나 NFS 가 안 됨**: telnet 으로 `restore.sh` → operator 재부팅.  기록하지 않는다.
- **도구 종료 3**(Display0 없음): 기록하지 않고 복원한다.  재시도하지 않는다.
- **도구 종료 4·5**(표시 정보·State 불일치): `RDNR2b0State` 를 읽을 수 있으면 기록하고, 기록 없이 복원한다.  재실행하지 않는다.
- **종료 6**(키 No): 복원한다.  이 부팅에서 telnet 으로 키를 고치지 않는다(검토되지 않은 쓰기).  §7-3 5 번 규칙이 왜 통과했는지부터 본다.
- **종료 9·10·11·7·8**: 복원한다.  재실행하지 않는다.
- **pllabort·pllbusy·vline-static**: 드라이버가 걸쇠를 건다 → 복원.  `a ≠ p` 면 복원 뒤 재부팅.
- **기록 중 행·강제 전원 재투입(어떤 이유든)**:
  - operator 전원 재투입 → 활성화 구성으로 부팅 → telnet `restore.sh` → 재부팅.
  - 런 ID 선점으로 재실행이 막혀 있다.
  - PLAN 중단 1·8: **하드웨어 쓰기 마일스톤 전체를 멈추고** 오프라인 분류·저장소 무결성 확인 전에는 다음 실기를 하지 않는다.
- **파서 FAIL 이 줄 손실뿐**(`RDNR2b0State` 는 완결·lastLines 일치, 걸쇠 없음, 시스로그 줄 부족): 새 runid 로 **1 회만** 재실행(부팅당 2 회 한도 안).  그 밖의 FAIL 은 재실행 없이 복원한다.
- **`restore.sh` 종료 2·3**: 재부팅하지 않고 멈춘다.  telnet 으로 원인을 본다.  종료 3 에는 "낯선 인스턴스 표"(옮기지
  않고 멈춤)가 포함된다 — 그 표가 무엇인지 보고 나서 결정한다.
- **`restore.sh` 종료 4**(쓰기 실패, 절반만 복원되었을 수 있는 유일한 경우): **재부팅하지 않고 같은 스크립트를 다시
  돌린다**(같은 바이트를 다시 쓰는 것은 무해하다).  두 번째도 4 면 telnet 으로 원인을 보고, `config=Default` 폴백을
  준비한 뒤에만 다음 조치를 한다.

## 10. 위험·미확인

1. **telnet 생존**(S10) — R-2 와 로컬 복구로 완화한다.
2. **보이지 않는 패닉·알림**(S19): 모니터로는 정상 부팅과 구별되지 않는다.  telnet 과 nxlogd 만 구별한다.
3. **첫 BAR0 쓰기**(WindowServer): aperture 해독·배치(`MC_FB_LOCATION` 0 대 `e0000000`)는 미검증이다.  prefetchable BAR 메모리 쓰기가 행을 부를 근거는 없다(미확인).
4. **init 의 FB 매핑**: Matrox 경로(S3)를 따른다.
5. **0xCF8 래치 경쟁**: 부팅 중 다른 경로가 같은 쌍을 마스크 없이 쓰면 섞일 수 있다.  PCIBus 는 부팅마다 모든 기능의 레지스터 0 을 읽는다(S25).  기록 B 의 config 읽기는 부팅 뒤다.
6. **VGA 상태의 주체**: 텍스트 부팅이면 커널 콘솔(S17·S26 실측), 아이콘 부팅이면 부트 로더다.  `cmode` 가 가른다.  VBE 콘솔은 부트 로더 VBE 필드에 달렸고 이번 부팅은 아니었다.
7. **플립플롭 원래 상태 복원 불가**(§4-3).
8. **FB 매핑 해제**: 슈퍼클래스에 `-free` 가 없다.  init 실패 경로에서 FB 매핑이 남을 수 있으나 무해하다.
9. **Configure.app 동작**(S28): 템플릿 인스턴스화·손대지 않은 표 재기록·인스턴스 삭제.  R-1 이 실측하고 `check_cfgdiff` 가 멈춘다.  "Configure 가 `Location` 을 채운다" 는 미확인이다(채우지 않아도 S25 로 묶인다).
10. **복원 묶음 완전성**: pre 의 모든 인스턴스 표 + manifest 밖 표 주차로 닫는다.  `/me` 가 `config=Default` 부팅에서 보이는지는 R-2 가 확인한다.
11. **R-1 중간 상태**: §8 1 의 3–5 사이에 디스크가 활성화 구성이다.
12. **시험하지 않는 것**: ObjC 클래스(구조 규칙만), 사용자 도구(가짜 없음), driverLoader 의 표 키 매칭(S25 는 PCIBus 까지), `IOGetTimestamp` 실제 동작, 시스로그 손실, 변수 포트 VGA 쓰기 주체(S30).
13. **PIT·PIC 쓰기**: 커널 안(§0) — 우리 쓰기 목록 밖이지만 적어 둔다.
14. **EMU10K1 attach 위치**: 이번 부팅들의 probe 위치 줄은 syslog 에 남지 않았다(S20).  사운드 탭 충돌 해소(operator)·mp3 재생(operator)이 증거이고, 위치 줄은 미확인으로 둔다.

## 11. 결정 (operator)

1. **금지 8 예외** — **승인됨(2026-09-15, operator: Q12 결정 질문에 "네 다른건 상관없는데")**.  개정 1·2 초안이 "결정 필요" 로 남긴 것은 기록 누락이었다(Q13 판정 0-26).  개정 2 는 범위를 줄였다(probe 버스 스캔 제거).
   - 대상: R2b-0 활성화 부팅의 `+probe:`/init 에서 nxlogd 전에 PCI config 입출력(probe 1 쌍, init 사전 검사)과 FB·MMIO 매핑을 한다(§2 A).
   - 근거: Matrox 교체 드라이버가 같은 일을 하고 여러 번 부팅했다.
   - 하드웨어 인덱스 쓰기는 부팅 뒤 nxlogd 켠 상태에서만 한다.
   - R2b 의 모드셋 예외는 개정 6 에서 따로 묻는다.
2. **옵트인 키와 Configure 활성화** — **결정됨(2026-09-16, operator: 권장안 (a))**(Q13 판정 0-4).  Configure 의 "추가" 는 `Default.table` 에서 인스턴스를 만든다(S28).
   - (a) **권장**: 기록 전용 빌드는 `Default.table` 도 `"Yes"`.
     - PLAN §4 "기본 꺼짐" 의 예외다.  D-3("`Active Drivers` 편집 자체가 옵트인")을 R2b-0 기록 파라미터로 넓힌다.
     - 기록은 root 도구가 runid·magic 을 보낼 때만 돈다.
     - R2b 빌드는 규칙대로 `"No"` 로 돌아간다.
   - (b) `Default.table` 은 `"No"` 로 두고, Configure 저장 뒤 검토된 스크립트로 키 한 줄을 고친다.  타깃 표 쓰기가 한 번 늘고, `check_cfgdiff activate` 5 번 규칙이 결과를 확인한다.
   - 어느 쪽이든 §7-3 5 번 규칙이 `"Yes"` 를 요구하고, R-1 이 실제 동작을 먼저 보여 준다.
3. **EMU10K1 `Location`** — 조치함(2026-09-15, operator 허가).
   - operator 보고: Configure.app 사운드 탭이 충돌을 표시했다.
   - 수정: 설치 표 `Location` 을 `Dev:11` → `Dev:13 Func:0 Bus:3` 으로 고쳤다.
     - 한 줄 차이를 호스트가 Python 으로 검증했다.
     - `cmp` 대조, root wheel 644 보존, rename 뒤 되읽기 sum `17199 1`.
   - 백업: `/me/rdn-emu10k1-backup/Instance0.table.20260915`(sum `17135 1`), NFS `build/r2b0/emu10k1/Instance0.table.orig`.
   - **충돌의 실제 원인은 `Location` 이 아니었다**: generic VGA 인스턴스 둘(`Instance0`·`Instance1`)이 같은 VGA 자원을 선언했다.  operator 가 Configure.app 에서 둘째 SVGA 를 지워 해소했다(14:56 저장).
   - 낡은 `Dev:11` 로도 카드가 묶였을 기제는 S25(PCIBus 폴백)다.  "attach 했다" 는 로그 줄로는 확인하지 못했다(S20, 개정 1 의 "실측" 표현 정정).
   - 같은 날 operator 가 보고한 "부우우" 험은 BIOS 화면에서도 났고 **모니터 접지 문제**였다(operator 확인·해결, 15:17 부팅 뒤 mp3 재생 정상).  소프트웨어 원인 아님.
4. **`OSRDNDisplay` `Location`** — 결정됨(2026-09-15): `""`.  다른 시스템에서 Configure.app 으로 수동 전환할 수 있어야 하기 때문이다.  S25 로 동작 기제가 확인됐다.
5. **활성화 수단** — 결정됨(2026-09-15): Configure.app.  활성화 부팅의 원복은 `/me` 집합 복원이다(GUI 없음).
6. **번들 이름** — 결정됨: `OSRDNDisplay`.
7. **R-2** — 결정됨: 진행.
8. **재부팅 수**: 4 회(R-2 의 `config=Default`·평상 복귀, 활성화, 복귀).  R-1 은 재부팅이 없다.

## 12. 코드 착수 때 확정·정정 (2026-09-16)

코드는 `OSRDNDisplay/`, `tools/r2b0/` 에 있다.  `sh tools/r2b0/hostcheck.sh` 11 단계 PASS, `sh tools/check-all.sh` PASS.
- **기대 표**: §4-4 의 32 항목을 명시했다(개정 0 목록 복원).  §6-1 사람 출처 표의 R1 값 네 개는 `docs/R1_RESULT.md` 에 있었다(초안의 "없음" 정정).  `gen_expect_r2b0.py` 가 원시 로그와 사람 값 18 개를 대조해 `osrdn_expect.h` 를 만든다.
- **줄 문법**(파서 기준): `begin ... key=<yes|no>`, `time d0..d6 s60 f60 s1000 f1000`, `vga part=1 misc dec base sqi sq crtci crtc` / `vga part=2 gri gr attri attr`(필드 `seq` 는 줄 순번과 겹쳐 `sq` 로), `gate step name val want pass=<1|0|na>`, `verdict gates=32 refused result`.  줄 밖: `probe rc loc id accept|decline`, `init boot build loc key cmode bar0 bar2 ok|abort=`, `enter`, `revert`, `refused`, syslog 표지 `RDN-R2B0-MARK <runid>`.
- **VGA 미해독**(`misc` 0xff): ATTR 만이 아니라 **모든 인덱스 저장을 건너뛴다**(계획보다 엄격).
- **cc 이름**: `id`·`out` 식별자를 쓰지 않는다(`out` 은 커널 빌드의 매크로) — 초안 코드의 세 곳을 규칙 `cc-names` 가 잡아 고쳤다.
- **`/me` 실측**(2026-09-15 읽기): `/me` 는 루트 파일시스템(`/dev/hd0a`), 권한 `drwxrwxrwx`.  `config=Default` 부팅에서도 보일 것이다(R-2 가 확인).  복원 묶음 디렉터리 `/me/rdn-r2b0` 는 stage 스크립트가 root 소유 755 로 만든다.  `/usr/ucb/logger` 있음.
- **복원 묶음 배치**: `/me/rdn-r2b0/{restore.sh, check.sh, CURRENT, set.<tag>/manifest, set.<tag>/<bundle>.config/InstanceN.table, parked.<tag>/}`.  manifest 줄: `<rel> <8진 모드> <ls 모드> <소유자> <그룹> <sum> <블록> <바이트>`.  `restore.sh` 종료: 0 완료, 2 묶음 불완전(아무것도 안 씀), 3 검증 실패(재부팅 금지), 4 쓰기 실패.  `check.sh` 종료: 0 묶음 정상(`differ=`·`extra=` 보고), 2 묶음 불완전.
- **표지 위치**: `/tmp` 는 재부팅 때 지워지므로 빌드 표지(`BUILD_PASS`)·도구·설치 표지(`INSTALLED`)는 NFS `build/r2b0/<runid>/` 에 둔다.  run 스크립트는 인자로 runid 를 받는다.
- **파서 종료 코드**: 0 PASS-ENTER, 3 PASS-REFUSE, 1 FAIL.
- **검사기 규모**(이번 실행): 소스·목적 규칙·변이 63, 시뮬레이터 세계 21·변이 33, 파서 자체검사 30, 역어셈블 게이트 11, 스냅샷 판정 30, 타깃 스크립트 59(R-1 복원 경로와 run 스크립트를 끝까지 포함), 드리프트 6 hunk.
- **남은 위험(추가)**: `/me` 가 누구나 쓸 수 있어 `rdn-r2b0` 디렉터리 이름 자체는 바뀔 수 있다(단일 사용자 기계, `restore.sh` 는 쓰기 전에 모든 sum 을 다시 본다).  재설치 때 `OSRDNDisplay.config` 에 인스턴스 표가 하나도 없으면(복원이 주차한 뒤) 번들은 인스턴스 표 없이 설치된다 — Configure 의 추가가 `Default.table` 로 만든다(S28), 기록 빌드는 `Default.table` 도 `"Yes"`.

## 13. Q14(코드 교차검토) 뒤 바뀐 것 (2026-09-16)

`docs/review/Q14_verdict.md`.  codex 와 자체 agent 둘이 코드와 실행 순서를 보았고, 내 오류 13 건을 고쳤다.
실기에 아무것도 하지 않은 상태에서 고쳤다.

- **표지**: `logger` 대신 드라이버의 상태 줄(§5 `state` 모드).  이 기계에서 `logger` 는 `/usr/adm/messages` 에
  도달하지 않는다(`docs/R1C_RESULT.md` 사실 5).
- **이중 해제**: `init` 의 슈퍼클래스 실패 경로는 `return nil`.  커널 구현이 이미 free 했다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
  규칙 `class-init-free` 는 이제 `-free` 밖의 `[super free]` 를 막는다.
- **모드 목록**: `- (unsigned int)displayModeCount { return 0; }`.  기본값이면 `IOGetDisplayModeInfo:<n>` 가
  NULL 을 읽는다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
- **복원**: System 표를 마지막에 쓰고 사이에 `sync`.  낯선 인스턴스 표는 **옮기지 않고** 종료 3(`Pro1000` 은
  telnet 이 타는 드라이버다).  주차는 `OSRDNDisplay.config/*` 만.
- **기록**: `idxend` 줄을 따로 남긴다(게이트 항등식 제거).  미해독 VGA 는 구조체를 0 으로 채운 뒤 찍는다.
  MISC 와 CRTC 기저의 불일치는 FAIL 이다.  `dotClockRate` 를 공칭 65250000 으로 공개한다.
- **실행 스크립트**: 런 ID 선점 전에는 `run.done` 을 건드리지 않는다.  기록 직전에 증거를 NFS 로 복사·`sync`.
  `check.sh` 출력도 NFS 로.
- **스냅샷**: `LIST` 를 `/tmp` 에서 만들어 한 번 복사한다(NFS 이어쓰기 함정).
- **`same` 게이트**: PASS 면 `SAME_PASS` 표지를 남긴다 — 건너뛰면 표지가 없어 드러난다.
- **절차**: 타깃 스크립트를 NFS 에서 돌리기 전에 **타깃에서 `sum` 을 재어 호스트 값과 대조**한다(R1c 사실 3 의 낡은
  짧은 읽기).  활성화 스냅샷과 같은 부팅에서 `df`·`ls`·`Active Drivers` 를 함께 남긴다.  `pcils` 재실행(커널 모듈
  적재)은 operator 판단으로 남긴다.
- **시뮬레이터의 한계**(명시): 녹색 세계의 값은 R2a 실측을 심은 것이고 카드의 동작을 예측하지 않는다.
- 줄 수 120, 약 3.47 s(§4-6).


## 14. 설치 뒤 드러난 것 — `"Server Name"` 중복 (2026-09-16, Q15 교차검토 반영)

설치까지 마치고 R-1 의 `pre` 스냅샷을 찍은 다음 `check_cfgdiff precheck` 가 멈췄다:
`REFUSED OSRDNDisplay.config/Instance0.table: duplicate key 'Server Name'`.

- **원인**: 원본 두 표에 그 줄을 직접 써 두었는데, driverkit 번들 postamble 이 빌드 때 모든 표에 같은 줄을
  하나 더 붙인다(§3 의 정정 항목).  R1 때도 같은 것을 보고 "판정이 예상대로 통과" 로 넘긴 기록이 있다
  (`docs/R1_RESULT.md` 18 행) — 그때는 probe 번들이라 설정 표를 아무도 읽지 않았다.
- **고친 것**
  1. `OSRDNDisplay/Default.table`·`Instance0.table` 에서 그 줄을 지웠다(각 18 → 17 줄).
  2. `target-build-r2b0.sh`: 새 단계 3b(원본 표에 0 줄), 5 단계는 산출 표마다 **정확히 1 줄**을 요구한다.
  3. `target-install-r2b0.sh`: 새 단계 3b(후보 표마다 1 줄) + 설치 뒤 재확인.  **설치기는 기존 인스턴스 표를
     보존하므로 재빌드·재설치만으로는 낡은 중복이 안 없어진다** — 두 번째 인자 `fresh` 가 이 한 번을 위해
     빌드 산출 표를 설치한다(옛 표는 `.prev` 에 남는다).
  4. `check_cfgdiff.py`: `POSTAMBLE = {'Server Name': 'OSRDNDisplay'}`.  기대값 = 원본 표 키 ∪ POSTAMBLE
     (`expected_driver_kv`, 원본이 이미 그 키를 가지면 거절).  `precheck` 도 설치본의 그 키를 본다.
     중복 키 거절 규칙은 그대로 두었다(약화 아님, 정밀화).
  5. 자체검사: `installed = 원본 + postamble 줄`, Configure 모사 표도 그 맵에서 만든다.  변이 8 건 추가
     (원본에 키 있음, precheck 키 없음/다른 값/두 번, activate 키 없음/다른 값, 빌드 산출 2 줄/다른 이름,
     원본에 키가 든 tar, 설치 중복 거절, `fresh` 설치).
- **스냅샷 태그**: `build/r2b0/cfg/R1/pre` 는 중복의 **증거**라 지우지 않는다.  다시 설치한 뒤의 R-1 은
  태그 **`R1b`** 로 새로 찍는다(`target-cfgsnap-r2b0.sh` 는 있는 디렉터리를 덮지 않는다).
- **근거(이번에 직접 연 것)**: `Makefile.bundle_postamble` 1–6 행; `driverkit/IOConfigTable.h` 주석과
  `objc/NXStringTable.h` 17 행, `HashTable.rtf` 246 행(사용자 공간은 마지막 값); 이 기계 설치 표 16 개·
  정품 표 20 개 모두 중복 0·`Server Name` 1 줄(python 집계).

### 14-1. 중복이 풀리자 드러난 것 — Adaptec2940 의 낡은 `Location` (2026-09-16)

중복 키 때문에 스냅샷이 통째로 거절돼 그동안 **precheck 의 `Location` 검사 자체가 돈 적이 없었다.**
표가 파싱되자 바로 걸렸다: `Adaptec2940SCSIDriver.config/Instance0.table` 의
`"Location" = "Dev:11 Func:0 Bus:3"` 는 **Radeon 이 있는 03:0b.0** 이다.

- **확인한 사실**
  - 이 기계에 SCSI 컨트롤러가 없다(`logs-pcils-20260915.txt` 장치 11 개, 버스 0·2·3 전부 열거됨).
    **operator 확인(2026-09-16): .18 에 2940 은 꽂혀 있지 않다.**  Radeon 이 그 카드 자리에 들어갔다.
  - PCIBus 는 `Location` 자리의 ID 가 맞을 때만 그 위치를 쓰고 틀리면 스캔한다(S25, 역어셈블).
  - 두 해석 모두 불일치: `0x59601002` vs `0x00789004`(strtol 이 `&` 에서 멈춤), 마스크 해석은
    `0x00601002` vs `0x00789004`(python).
  - 실제 결과가 로그에 있다: 매 부팅 `Adaptec2940: Can't get configSpace; ABORTING`
    (`/usr/adm/messages` 2 줄, 2026-09-09 16:50·17:00).  → 이 드라이버는 Radeon 에 닿을 수 없다.
- **operator 결정(2026-09-16)**: **표는 그대로 둔다.**  `Boot Drivers` 에도 든 드라이버의 표를 위험한
  부팅 직전에 고치는 쪽이 더 큰 위험이고, 고쳐도 부팅 동작은 같다(어차피 스캔).  R2b-0 부팅이 끝난 뒤
  정리 항목으로 남긴다.
- **검사기**: `check_cfgdiff.STALE_PCI_LOCATION_OK` 에 **키 있는 예외** 한 줄.  키는
  (표 이름, `Location` 문자열, 그 자리에서 실제로 읽힌 ID 워드) 세 값이고, 하나라도 달라지면 다시 FAIL 한다.
  통과해도 `NOTE` 줄로 근거를 찍는다.  변이 3 건(다른 `Location`·그 자리 다른 카드·다른 번들의 같은 표)이
  모두 FAIL 하는 것을 자체검사에서 함께 본다.
- **부수 정밀화**: `Auto Detect IDs` 의 `0xIIIIIIII&0xMMMMMMMM` 형식을 파싱한다(그 전에는 토큰을 버려
  "일치 없음" 으로 읽었다 — 결론은 같았지만 이유가 틀렸다).  이해 못 하는 토큰은 그 자체로 FAIL 이다.
- 증거 사본: `build/r2b0/emu10k1/Adaptec2940.Instance0.20260916`(sum `36916 1`, 622 바이트).

## 15. R-1 이 드러낸 것의 조치 계획 (2026-09-16 개정 4 — operator 결정·Q16 내부검토 반영)

R-1 실측은 `docs/R2B0_R1_RESULT.md`.  닫아야 할 것: **Configure 로 디스플레이를 바꾸면 인스턴스가
하나 더 생겨 한 카드에 OSRDNDisplay 인스턴스가 둘이 된다.**

> **출처 규칙(operator 지시 2026-09-16)**: `openstep-kernel-remade` 는 **제작 중인 프로젝트이고
> 분석이 완전하지 않으므로 근거로 쓰지 않는다.**  이 절의 근거는 (a) 실기에서 가져온 바이너리
> (`/usr/etc/driverLoader`), (b) 미러 `ref/openstep`(헤더·정품 드라이버·makefile·NeXT 문서),
> (c) 이 워크스페이스의 정본 문서 `doc/driverkit.md`, (d) Matrox 프로젝트 문서, (e) 이번 실기
> 스냅샷뿐이다.  §15 이전 절들에는 그 프로젝트를 근거로 든 문장이 남아 있다 — 별도 정리 대상
> (§15-5).

### 15-0. 개정 1·2 에서 내가 틀렸던 것

- **"Matrox 는 `Active Drivers` 한 줄 편집으로 활성화했고 되돌림까지 리허설 PASS"** — 틀렸다.
  그 런시트는 스스로 "**display 설정을 바꾸지 않는 같은-설정 reboot** 이므로 display 위험이 0"
  이라 적고(`openstep-matrox-remade/docs/reports/R5_VGA_RECOVERY_REHEARSAL_RUN_SHEET.md` 21–22 행),
  활성화 편집과 역편집은 "**향후**" 로 남겼다(34–35 행).  `R6_H1_TRANSACTION_INPUTS.md:50` 의
  문장이 자기 근거보다 강하다.
- **"Matrox 는 Configure 를 열지 않았다"** — 틀렸다.  공개 설치 안내가 Configure 활성화다
  (`release-packaging/INSTALL.md` 78–79 행), 이름 변경 절차 4 단계도 Configure 다
  (`C3_BUNDLE_RENAME_PLAN.md:99`).
- **"인스턴스 표가 없으면 부팅 후보가 아니다"** — 기제로서 틀렸다.  실기 바이너리에서
  `driverLoader` 는 인스턴스 0 이 없으면 **`Default.table` 로 폴백**한다(F1).  Matrox 의
  "표를 빼니 800x600 4 색 VGA" 는 다른 기제로 설명된다(F3).
- **"번들에서 `Instance0.table` 을 빼자"(개정 0)** 와 **"그대로 두자"(개정 2)** 둘 다 근거가
  부족했다.  정본 문서가 답을 준다(F6): 인스턴스 표는 **발견된 개체의 기록**이고 `Location` 을 담는다.

### 15-1. 확정된 사실

| # | 사실 | 근거(허용 출처) |
|---|---|---|
| F1 | `driverLoader` 는 `Instance0` 부터 번호를 올려 가며 표를 열고 **없는 번호에서 멈춘다**.  **인스턴스 0 이 없으면 오류가 아니라 `Default.table` 로 폴백**해 "Using Default table for %s" 를 찍고 성공한다.  `Default.table` 까지 없을 때만 실패 | 실기 사본 `build/r2b0/driverLoader.bin`(sum `62436 48`) 역어셈블: `0x3bf4 test %ebx,%ebx` → `0x3bf8` 에서 `"Default.table"`(0x949d) 경로를 만들어 다시 열고 `0x3c24` `"Using Default table for %s"`, `0x3c54 xor %eax,%eax`(성공).  실패 문구는 `"No Default table for %s"` |
| F2 | Configure 는 설치된 `Instance0` 을 두고 `Instance1` 을 **추가**하며 `Location` 을 실제 슬롯으로 채운다 | `build/r2b0/cfg/R1b/RECORD-pre-post.txt` |
| F3 | `driverLoader` 는 구성 뒤 `Display0`·`VGADisplay0`·`SVGADisplay0` 이 **하나도 없으면** `"%s: No display driver added, trying VGA"` 를 찍고 **`VGA` 를 적재한다** | 같은 바이너리 `0x3577`–`0x35ee`(세 이름 조회 뒤 `0x9027` 출력, `0x9050`="VGA" 로 호출) |
| F4 | `+probe:` 계약은 "이 서술자에 인스턴스를 만들었으면 YES" — 안 만들 서술자에 `NO` 는 정상 | `ref/openstep/headers/NextDeveloper/Headers/driverkit/IODevice.h` `+ (BOOL)probe:` 주석 |
| F5 | `getPCIdevice:function:bus:` 는 주소를 알 수 있으면 세 인자를 채우고 `IO_R_SUCCESS`, 아니면 코드만 돌려주고 **인자를 건드리지 않는다** | 헤더 `driverkit/i386/IOPCIDeviceDescription.h` 24–36 행 |
| F6 | **`Default.table` 은 지원 장치 카탈로그, `InstanceN.table` 은 이 기계에서 발견된 개체의 기록**이며 **실제 `Location` 을 담는다**.  **`driverLoader` 가 구성에 성공하면 `InstanceN.table` 이 생기고 이후 매 부팅 로드된다** | 이 워크스페이스 정본 `doc/driverkit.md` 155–166·181–184 행(동작 중인 DEC 21041 인스턴스 표 예시 포함) |
| F7 | 빈 `Location` 이어도 PCIBus 는 `Auto Detect IDs` 로 스캔해 `Instance` 번째 일치를 주소로 준다(그 자리 ID 가 맞을 때만 `Location` 을 쓴다) | 미러 정품 `PCIBus.config/PCIBus_reloc` 의 `configAddress:device:function:bus:`(메서드 표에서 IMP `0x594`, 다음 메서드 `0x844`) 역어셈블 — S25 와 같은 함수 |
| F8 | `/me/rdn-r2b0/check.sh` 는 차이가 있어도 **종료값 0**(차이는 `differ=`·`extra=` 출력에만) | `tools/r2b0/me/check.sh` 마지막 두 줄; 실증 `build/r2b0/cfg/R1b/check-after-activate.txt`(`differ=5 extra=1` 인데 "OK") |
| F9 | 이 기계 `System.config/Instance0.table` 은 `root wheel 644`, 우리 드라이버 표는 `444` | `build/r2b0/cfg/R1b/pre/LIST` |
| F11 | `driverLoader` 가 표 경로를 만드는 `/usr/Devices` 는 `../private/Devices` → `Drivers/i386` 심볼릭 링크로, 우리 스크립트가 쓰는 `/private/Drivers/i386` 과 **같은 트리**다.  `/me` 와 그 디렉터리는 같은 파일시스템(`/dev/hd0a`) | 타깃 `ls -ld`·`df`(2026-09-16) |
| F12 | 활성화 직전 `VGA.config` 에는 `Default.table`(505 바이트 444)·`SVGABIOS.table`·`VGA_reloc` 가 있다 — F3 의 VGA 구조가 기댈 파일이 실재한다.  **스냅샷은 이 파일들을 담지 못한다**(`cfgsnap` 은 `Instance*.table` 과 System `Default.table` 만) | 타깃 `ls -l`(2026-09-16) |
| F10 | 인스턴스 둘로도 기계는 **부팅했다** — 2026-09-15 VGA 인스턴스 둘은 하드 행이 아니라 Configure 자원 충돌로 드러났다 | 이 문서 §10 11 항·`build/r2b0/emu10k1/*.after-configure-1456` |

**F3 이 Matrox 의 800x600 사고를 설명한다**: 그 번들 `Default.table` 의 `Auto Detect IDs` 는
**레거시 `0x0519102B`** 이고 카드는 `0x0525102B` 였다(`openstep-matrox-remade/docs/reports/
R1_SOLE_OWNER_CONFIG_REVIEW.md` 70–71 행).  인스턴스 표를 뺀 패키지는 폴백으로 `Default.table` 을
읽었으나 그 카탈로그가 카드와 맞지 않아 디스플레이가 등록되지 않았고, `driverLoader` 가 VGA 를
올린 것으로 설명된다(가설이지만 F1·F3 과 정합).  **우리 `Default.table` 의 `Auto Detect IDs` 는
실제 카드 `0x59601002` 다** — 같은 실패 모양이 아니다.

### 15-2. 조치 (operator 결정 2026-09-16 반영)

**operator 결정**: (A) 인스턴스 표의 `Location` 은 **빈 값 유지**(2026-09-15 결정 그대로).
(B) 활성화는 **Configure.app + 잉여 인스턴스 주차**.  아래는 그 결정에 맞춘 설계다.

- **A. 번들 인스턴스 표**: `Location = ""` 그대로.  PCIBus 가 `Auto Detect IDs` 로 스캔해 `Instance`
  번째 일치를 주소로 준다(F7).  `Default.table` 도 그대로(카탈로그, 옵트인 키 `Yes`).
- **B. 활성화 절차**: operator 가 Configure.app 에서 VGA → OSRDNDisplay 로 바꿔 저장·닫는다.
  R-1 실측대로 `Instance1` 이 생기고 `Instance0` 이 남는다(F2).  이어서 **잉여 인스턴스를 주차**한다.
- **B-1. 주차의 방향이 중요하다 — `Instance0` 을 남긴다.**
  `driverLoader` 는 인스턴스 0 이 없으면 **`Default.table` 로 폴백해 장치를 하나 구성하고**(F1),
  그 다음 `Instance1` 이 있으면 **그것도 구성한다**.  따라서
  - `Instance1`(및 그 이상)을 주차하고 `Instance0` 을 남기면 → **정확히 하나**.
  - `Instance0` 을 주차하고 `Instance1` 을 남기면 → `Default.table` 폴백 + `Instance1` 로 **다시 둘**.
  게이트의 불변식은 "인스턴스 표가 하나" 가 아니라 **"정확히 `Instance0.table` 하나"** 다.
- **B-2. 주차 스크립트** `target-park-extra-r2b0.sh closed=yes`(새로 씀)
  1. 사전: `CURRENT` 의 복원 묶음이 온전하고, `check.sh` 출력이 파싱되며(F8 — 종료값 아님),
     `Active Drivers` 가 `OSRDNDisplay` 를 이름하고 `VGA` 를 이름하지 않는다(= Configure 저장 뒤 상태).
  2. `OSRDNDisplay.config/Instance*.table` 을 열거한다.  `Instance0.table` 이 **없으면 멈춘다**
     (위 폴백 함정 — 이 경우는 사람이 판단할 일이다).
  3. `Instance0.table` 의 키→값이 설치된 `Default.table` 의 키→값과 `Location`·`Default Table` 을
     빼고 같은지, 옵트인 키가 `Yes` 인지 확인한다.  다르면 멈춘다.
  4. `Instance1..N` 을 `/me/rdn-r2b0/parked-activate.<tag>/OSRDNDisplay.config/` 로 **옮긴다**
     (지우지 않는다).  다른 번들의 표는 **절대 건드리지 않는다**.
  5. 옮긴 뒤 다시 열거해 `Instance0.table` 하나만 남았는지 확인하고 `sync`.  결과를 `/tmp` 에서
     만들어 NFS 로 한 번 복사한다(NFS 이어쓰기 함정).
  6. 타깃 셸 규칙(§7 서두)·`check_target_r2b0.py` 의 `SCRIPTS`·`ENV_NAMES` 편입.
  - 되돌림: 주차본은 `/me` 에 남고, `restore.sh` 가 집합 복원으로 `pre` 상태를 되돌린다(주차 경로 포함).
- **C. 게이트 `check_cfgdiff activate` 확장**(새 모드를 만들지 않고 기존 모드를 정밀화)
  - post 의 `OSRDNDisplay.config/Instance*.table` 은 **정확히 하나이고 이름이 `Instance0.table`**.
  - 그 키→값 = 원본 `Default.table` ∪ `POSTAMBLE`, 허용 차이는 `Location`·`Default Table` 뿐(현행).
  - `System.config/Default.table` **바이트 동일**(복구 부팅의 `Active Drivers`; 현행 규칙 유지·명시).
  - `Active Drivers` 는 pre 에서 `VGA` 하나가 `OSRDNDisplay` 로 바뀐 것(현행).
  - **모든 표의 owner·group·mode 비교를 무조건 수행**한다.  현행 규칙은 바이트와 모드가 **둘 다**
    달라졌을 때만 잡아서, 모드만 바뀐 경우(R-1 에서 실제로 우리 표가 `444`→`644`)를 놓친다.
    다만 **Configure 가 바꾼 모드는 기록하고 FAIL 로 삼지 않는다** — B-2 는 Configure 를 쓰는 길이라
    `644` 가 정상이다.  `pre` 의 `444` 와 다르면 `NOTE` 로 남긴다.
  - `VGA.config/Instance*.table` 은 없어져도 된다(현행).  **다만 없어졌으면 `NOTE` 로 남긴다** —
    복구 부팅(`config=Default`)의 디스플레이가 `Default.table` 폴백에 의존하게 되기 때문이다(F1).
  - PASS 면 `ACTIVATE_PASS`(현행).
- **D. 드라이버가 둘째 인스턴스를 거절한다**(이중 안전, B-2 에서는 특히 필요)
  - 걸쇠는 **`osrdn_record.m` 의 파일 정적**으로 둔다.  `OSRDNDisplay.m` 에는 `splhigh` 를 쓸 수 없다
    (`check_r2b0_src.py` 의 `class-no-hw`).  `spl` 규칙의 쌍 개수를 셋으로 넓히고 발동을 증명한다.
    시뮬레이터가 `osrdn_probe_accept` 를 이미 부르므로 거기 두어야 **실기 전에 걸쇠를 돌려 볼 수 있다**.
  - 선점은 `osrdn_probe_accept()` 가 참을 돌려준 **뒤**, `[super probe:]` **앞**.  `[super probe:]` 가
    `NO` 면 되돌린다(걸쇠가 잠긴 채 남으면 **디스플레이 소유자가 아예 없어진다**).
  - 불변식은 **"성공한 인스턴스가 한 부팅에 하나"** 다.  `[super probe:]` 가 `NO` 면(= init 실패,
    그 경로는 `-free` 를 지난다) 걸쇠가 풀려 뒤 인스턴스가 소유자가 될 수 있다.  `-free` 자체는
    걸쇠를 만지지 않는다(만지면 `class-latch` 규칙이 FAIL).  한계: 카드 두 장이면 둘째도 거절한다.
  - **기록 상태**: `osrdnRunId`·`osrdnSeq` 는 파일 정적이라 두 인스턴스가 동시에 기록하면 줄 번호가
    섞여 파서가 재조립하지 못한다 — 걸쇠가 이것도 막는다.

### 15-3. 이번 R-1 에서 정정된 계획 문장

- S28 "빈 `Location` 을 채운 사례는 없다" → **Configure 는 채운다**(F2).
- Configure 는 되돌릴 때 **드라이버 인스턴스 표를 전부 지운다**(설치기가 넣은 것까지).
- Configure 는 손대지 않은 표(`EIDE`·`EMU10K1`)도 키 순서를 바꿔 다시 쓰고, 우리 표 모드를
  `444` → `644` 로 바꿨다.
- `docs/R2B0_R1_RESULT.md` §3 의 "정품 디스플레이 번들은 인스턴스 표를 담지 않는다" 는 **관측으로는
  사실**이지만, 거기서 끌어낸 "그러므로 담지 말아야 한다" 는 기제가 아니다 — F1·F6 이 정본이다.

### 15-4. R-1c (재부팅 없음, 새 태그) — 주차 경로와 게이트 리허설

`cfgsnap pre R1c` → `precheck` → `pack_restore`/`stage-restore R1c` → `check.sh`(차이 0) →
**operator: Configure 에서 VGA → OSRDNDisplay 저장·닫기** → `cfgsnap postraw R1c`(주차 전 상태 보존)
→ `target-park-extra-r2b0.sh closed=yes` → `cfgsnap post R1c` → `check_cfgdiff activate`(확장 규칙) →
`cfgsnap postb R1c` → `check_cfgdiff same post postb`(§7-3 7 번 규칙) →
**operator: Configure 에서 OSRDNDisplay → VGA** → `cfgsnap post2 R1c` → `restore.sh` →
`cfgsnap post3 R1c` → `restored`(pre 바이트 동일) → `restore.sh` 재실행(`wrote=0`).

**실제 활성화 부팅(§9)의 순서도 같다**: Configure → `postraw` → 주차 → `post` → `activate` →
operator 고지 → `postb` → `same post postb` → 재부팅.  §9 5 번을 이 순서로 읽는다.

R-1 과 같은 중간 상태 경고가 그대로다(활성화 구성이 디스크에 있는 동안 예기치 않은 재부팅이 나면
telnet → `restore.sh` → 재부팅 → 중단·분류).

**R-1c 가 증명하지 못하는 것**: `driverLoader` 가 그 구성으로 우리 번들을 실제로 probe 하는지,
빈 `Location` 으로 서술자가 채워지는지(F7 은 정품 드라이버 역어셈블이고 실기 부팅이 아니다),
걸쇠 코드의 실행(시뮬레이터로만), 디스플레이 소유자가 바뀐 부팅에서 telnet·`/ndrv`·nxlogd 가
사는지, 그 부팅의 `basicConsoleMode`.

### 15-5. 별도 정리 대상 — 금지된 출처에 기대는 기존 문장

operator 지시(2026-09-16)로 `openstep-kernel-remade` 는 근거에서 제외한다.  이 계획서에서 그
프로젝트를 근거로 든 곳: **S1·S17·S22·S24·S26(일부)·S27**, §5 의 모드 목록 근거, §13 의 "이중 해제"·
"모드 목록" 두 항목.  각각을 (a) 미러 헤더·NeXT 문서, (b) `doc/driverkit.md`, (c) Matrox 실측,
(d) 실기 측정으로 다시 세우거나, 세우지 못하면 **미확인으로 낮춘다**.  코드에 영향이 있는 것은
`initFromDeviceDescription:` 실패 경로의 `return nil`(§13)과 `displayModeCount` 0 이다 — 둘 다
보수적인 선택이라 지금 동작을 바꾸지는 않지만, 근거는 다시 세워야 한다.
