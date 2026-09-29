# Q12 판정 — R2b-0 구현 계획 개정 0 교차검토(자체 agent 둘) 재검증

- 요청: `docs/review/Q12_prompt.md`.  회신: `Q12_reply_A.md`(드라이버·안전), `Q12_reply_B.md`(절차·복구·도구).
- 원칙: 회신은 검증 대상이다.  "내 검증" 칸은 이 세션에서 직접 연 파일:줄, 실행한 명령과 출력이다.
- 반영: `docs/R2B0_IMPL_PLAN.md` 개정 1, `docs/R2_FIRST_LIGHT_PLAN.md` 개정 5.1.

## 0. 내가 틀린 것 (먼저)

1. **"기록값 = 부트 로더 상태" 는 틀렸다.**
   - 커널이 부팅 때 자체 VGA 콘솔로 모드를 건다: `_kminit` → `_VGAAllocateConsole`(640×480) → 콘솔 연산표의
     `FUN_0019ab88` → `_VGASetGraphicsMode`.
   - 커널 표 값은 Matrox 가 "부트 로더 스냅샷" 으로 기록한 바이트와 같다.
   - PLL 은 커널이 쓰지 않으므로 BIOS POST·부트 로더 상태로 남는다.
2. **상위 계획을 개정 없이 바꿨다.**  상위 §3 R2b-0 은 기록을 `enterLinearMode` 에서 하도록 정의했다.
3. **금지 8 예외를 R2b 로 미뤘다.**  R2b-0 의 부팅 경로에도 PCI config 포트 입출력과 FB 매핑이 있으므로 지금 필요하다.
4. **`get/setIntValues:` 재정의가 super 로 넘겨야 한다는 규칙을 빠뜨렸다.**  WindowServer 기동(`IO_Framebuffer_Map` 등)이
   슈퍼클래스의 두 메서드 안에 있다.
5. **재진입을 막지 않았다.**  커널은 `setIntValues` 호출을 직렬화하지 않는데, "진행 중·부팅당 2 회" 를 평범한 플래그로 적었다.
6. **PLL 중단 뒤 VGA 인덱스 쓰기를 금지하지 않았다.**
7. **"모든 값 먼저" 와 "R2a 그대로" 가 모순이었다.**  R2a 는 config 읽기 사이에 줄을 찍고 잔다.
8. **포트 입출력의 시뮬레이터 이음새가 없었다.**  `inb/outb` 는 NeXT 인라인 어셈블리라 호스트에서 컴파일되지 않는다.
9. **64 비트 나눗셈 변이를 시뮬레이터에 두었다.**  링크가 실패해서 하니스가 "빌드 실패" 로 센다.
10. **"R2a 위반·세계 전부" 라고 적었다.**  `left-mapped`·`outb` 는 R2b-0 에서 뒤집힌다.
11. **"게이트 코드를 R2b 와 그대로 공유" 는 과장이다.**  개정 6 에서 게이트가 바뀐다.
12. **복구 스크립트 설계 결함**
    - 대상에서 생성하므로 R-2 는 옛 사본을 확인한다.
    - "인자 없이" 와 `--check` 가 모순이다.
    - 쓰기 경로를 한 번도 돌리지 않는다.
    - 표 교체 뒤 권한·소유자를 확인하지 않는다.
    - `diff` 출력 해석은 조용히 통과할 수 있다.
    - 시스로그 표지를 재부팅 전에 잡는다.
13. **낡은 로그 방지가 없다.**  init·enter·revert 줄에 부팅 식별자가 없고, `RDNR2b0State` 에 빌드 스탬프가 없다(개정 0 의 "같은 내용을 준다" 는 거짓).
14. **사용자 도구가 `IO_R_SUCCESS` 를 보지 않는다.**  `count` 만 확인하는데 `count` 는 입출력 겸용이다.
15. **표 키가 불완전하고 `Location` 결정이 빠졌다.**  `Family`·`Title`·`Version`·`Instance`·`Location` 이 없다.
16. **S5 "super 를 항상 부른다" 는 틀렸다.**  generic VGA 는 `runVPCode` 결과가 0 이 아닐 때만 super 를 부른다.
17. **줄 수 추정이 적었다**: 110 → 약 120 줄, 약 2.4 s.

## 1. 판정표 — 검토자 A

| # | 주장 | 내 검증 | 판정 |
|---|---|---|---|
| A1.5/1.6 | 커널이 VGA 를 직접 프로그램, 표 값 = Matrox 스냅샷 | 디컴파일 `00197514.c` 13–26 행 `_basicConsole = _FBAllocateVBEConsole(); if (_basicConsole == 0) { _basicConsole = _BasicAllocateConsole(); }`; `00197c58.c` `local_8c = 0x280; local_88 = 0x1e0; _VGAAllocateConsole(&local_8c);`; `0019b760.c` 25 행 `puVar1[1] = FUN_0019ab88;`; `0019ab88.c` 53–54 행 `if ((param_2 - 1 < 2) && (param_3 != 0)) { _VGASetGraphicsMode(); }`; Python 덤프 CRTC `5f 4f 50 82 54 80 0b 3e 00 40 … e3 ff`, ATTR `… 01 00 03 00 00`, 800×525, 59.9405 Hz; Matrox `REMAINING_WORK.md` 3364 행 `misc e3 seq1 01 crtc0 5f crtc9 40 crtc17 e3` | ✅ 채택 — 전제 정정, 파서 VGA 기대값을 커널 표에서 독립 도출 |
| A1.1 | `IOFrameBufferDisplay` revert·enter 는 빈 구현 | 내 Python 클래스 구조체 파싱: `IOFrameBufferDisplay super IODisplay [('revertToVGAMode', '0x1c50f4'), ('enterLinearMode', '0x1c50ec')]`, `001c50f4.c` `return;` | ✅ (§10-1 닫음) |
| A1.3 | WindowServer 기동이 슈퍼클래스 get/set 안 → super 전달 규칙 필요 | `001c3cdc.c` 25–37 행(Map), `001c4188.c` 21·30 행(Unmap); 내 클래스 구조체 파싱: `IOFrameBufferDisplay` `setIntValues:forParameter:count: 0x1c4188`, `getIntValues:forParameter:count: 0x1c3cdc` | ✅ 채택 — super 전달 규칙 |
| A1.4 | 등록 뒤 알림·패닉이 우리 FB 에 그려져 보이지 않는 행처럼 보임 | `00195ec0.c` 48 행 `_objc_msgSend(DAT_001e7768,PTR_s_allocateConsoleInfo_001f949c)`, 54 행 콘솔 호출; `001c4eac.c` `_FBAllocateConsole(uVar1);` | ✅ 채택 — §10·operator 안내 |
| A1.4 | WindowServer 쓰기가 이 프로젝트 최초의 BAR0 쓰기 | R1·R2a 는 BAR2 읽기뿐(계획·결과 문서) | ✅ 채택 — §10 |
| A1.7 | init 은 R2a 검사를 "그대로" 쓸 수 없음(줄·IOSleep) | `RDNR2aProbe.m` 197–203 행 `IOLog(...); r2aSeq++; IOSleep(LINE_PACE_MS);` | ✅ 채택 |
| A2 | VGA 절차 타당, 플립플롭 원래 상태는 복원 불가, 0xFF(미해독) 기록 | 논리·계획 대조; X.Org `vgaHW.c` 경로는 이 작업공간에서 찾지 못함(`find … -name vgaHW.c` 출력 없음) | ⚖️ 채택(플립플롭 한계 명시, `vga-undecoded`); vgaHW 인용은 ⚠️ 미확인 — 대신 커널 ATTR 기대값으로 기록이 PAS 세운 읽기를 자체 검증 |
| A2.5 | 포트 입출력 이음새 필요 | `ioPorts.h` `static __inline__` + `asm volatile` (계획 작성 때 확인한 헤더) | ✅ 채택 — `osrdn_port.c` 별도 단위 |
| A3.2 | 커널이 `setIntValues` 를 직렬화하지 않음 | `001a4d70.c` 11–16 행 `lock … FUN_001a3d58 … unlock; if (iVar1 == 0) { … setIntValues…` | ✅ 채택 — `splhigh` test-and-set |
| A3.4 | `PPLL_DIV_1/2` 읽기 선례 있음 | `radeon_driver.c` 1076 행 `ppll_div_sel = INREG8(RADEON_CLOCK_CNTL_INDEX + 1) & 0x3;`, 1079 행 `n = (INPLL(pScrn, RADEON_PPLL_DIV_0 + ppll_div_sel) & 0x7ff);`(이 세션 열람) | ✅ 채택 |
| A3.5 | pllbusy/pllabort 뒤 VGA 쓰기 금지 | 계획 순서(PLL → VGA) | ✅ 채택 |
| A3.7 | 게이트 코드 공유는 과장 — 판정 기계만 공유, 기대값은 데이터 | 상위 §3 R2b-0 "결과로 개정 6: … 게이트를 의미 조건으로" | ✅ 채택 |
| A3.8 | 기록 트리거에 옵트인 키 | `PLAN.md` §4 "새 하드웨어 동작은 config 키로 옵트인"; Matrox `.m` 5935–5938 행 키 거절 | ✅ 채택 — `"RDN R2B0 Record" = "Yes"` |
| A4 | 시각 0 = 미측정, 1 s 창 추가, 포화·분리 `if` 규칙 명시 | Q11 판정 B3b(비단조) 와 같은 근거; Python `0.060*59.94` → 3.5964 | ✅ 채택 |
| A5.2/5.3 | 표 키 전체 명시, `Location` 결정 | Matrox `Default.table` 키(계획 작성 때 읽음); Matrox `R5_INSTALLER_KEEPS_THE_CONFIGURATION_PLAN.md` 27–33 행 "What is NOT established … controlled experiment varying `Location` alone"; 타깃 설치본 `OSMGADisplay.config/Instance*.table` 에 `Location` 줄 없음(grep, 이 세션) | ✅ 채택 — operator 결정 항목 |
| A5.4 | EMU10K1 인스턴스 `Location` 이 Radeon 슬롯 | 저장소 `openstep-emu10k1/EMU10K1/Instance0.table` 14 행 `"Location" = "Dev:11 Func:0 Bus:3"`; **타깃 설치본도 같음**(telnet grep, 이 세션); pcils `03:0b.0 … [1002:5960]`, `03:0d.0 … [1102:0002]` | ✅ 채택 — 활성화 전 operator 결정 |
| A5.7 | `+probe:` 가 드라이버로더가 준 장치 위치와 대조 | 헤더 `driverkit/i386/IOPCIDeviceDescription.h` 33 행 `- (IOReturn) getPCIdevice: (unsigned char *) devNum`(이 세션 grep) | ✅ 채택 |

## 2. 판정표 — 검토자 B

| # | 주장 | 내 검증 | 판정 |
|---|---|---|---|
| B1.1 | R-2 가 `/me` 쓰기 경로를 검증하지 않음, 인자 모순, 로그인 사용자 미명시 | 계획 개정 0 §7·§8 문구 대조 | ✅ 채택 |
| B1.1c | 표 교체 뒤 권한·소유자 확인 필요 | 작업공간 `tools/install-matrox-driver.sh` 143–149 행(번들 규칙) — System.config 에 같은 규칙이 적용되는지는 미확인 | ⚖️ 채택(확인 추가), 적용 여부는 미확인으로 기록 |
| B1.4 | `diff` 해석 대신 호스트가 만든 기대 파일과 `cmp` | 논리; `cmp -s` 는 R2a 타깃 빌드에서 동작 | ✅ 채택 |
| B1.5 | 표지를 기록 부팅 안에서 | R2a `target-run.sh` 의 MARK 방식 | ✅ 채택 |
| B2.1 | `IO_R_SUCCESS` 확인 | 헤더 `IODeviceMaster.h` "count … // in/out"(B 인용) | ✅ 채택 |
| B2.2/2.3 | 금지 8 예외가 지금 필요, 상위 계획 개정 필요 | 계획 개정 0 §2 A 부분 | ✅ 채택 — operator 결정 |
| B2.4c | 커널 VGA 콘솔이 데이터 레지스터를 씀 | A1.5 와 같은 근거(내가 연 파일) | ✅ |
| B3.1 | 64 비트 나눗셈 변이는 시뮬레이터에서 링크 실패 | 내 빌드: `undefined reference to '__udivdi3'` | ✅ 채택 — 목적 파일 규칙으로 이동 |
| B3.2 | R2a `left-mapped`·`outb` 뒤집힘 | `sim_r2a.py` MUTATIONS(내가 작성) | ✅ 채택 — 유지·반전·제외 목록 명시 |
| B3.3 | PLL 소스 재사용에 드리프트 검사 없음 | `check_drift.py` `SCRIPTS = ['target-build.sh', 'target-run.sh']`(내가 작성) | ✅ 채택 |
| B3.4 | 기대값 생성기 항등식 위험, 부팅이 못 바꾸는 레지스터 차이는 FAIL | 논리 | ✅ 채택 |
| B3.5 | 타깃 reloc 의 `out` 명령어 검사 없음 | `check_reloc.py` 는 세 헬퍼만(내가 작성) | ✅ 채택 — 포트 단위를 별도 컴파일 단위로 두고 역어셈블 게이트 확장 |
| B3.7 | 시간 사실은 기록 전용 | A4 와 같음 | ✅ |
| B4.5 | 부팅 식별자·빌드 스탬프 | 논리 | ✅ 채택 |
| B4 기타 | init 실패 시 Display0 없음(exit 3 = 복구), WindowServer 반복 기동(enter 수), 재실행 1 회 허용, 기록 중 행·fsck, NFS 없는 telnet 복구 | 논리 | ✅ 채택 |
| B4.11 | `IOFrameBufferDisplay` revert = `0x1c50f4` | 내 파싱 | ✅ |
| B5 행 C3 130 | 128 행이어야 한다 | `grep -n "Active Drivers 는 한 번에 바꿔라"` → **130** | ❌ 기각 — 내 인용이 맞다 |
| B5 기타 | S5 부분, S14 부분(측정 아님), 줄 수 120, 인자 모순, init 접두 불일치(상위 `OSRDN init`) | `001c8050.c` 16–21 행 `if (iVar2 != 0)`; 상위 계획 366 행 `OSRDN init build=` | ✅ 채택 |

## 3. operator 결정이 필요한 것 (계획 개정 1 §11)

1. **금지 8 예외**: R2b-0(와 R2b)의 부팅 경로에서 nxlogd 전에 PCI config 포트 입출력(메커니즘 #1)과 FB·MMIO 매핑을 한다.
   - Matrox 교체 드라이버가 같은 일을 하고 여러 번 부팅했다.
   - 기록(PLL·VGA 인덱스)은 부팅 뒤 nxlogd 켠 상태로 둔다.
2. **EMU10K1 `Location` 충돌**: 설치된 EMU10K1 인스턴스가 `Dev:11 Func:0 Bus:3`(Radeon 자리)를 가리킨다.  선택지 셋:
   - (a) 활성화 전에 `Dev:13` 으로 고치고 재부팅해 오디오를 확인한다(별도 변경·재부팅 1 회).
   - (b) 그대로 두고, R2b-0 부팅에서 driverLoader 로그로 두 드라이버의 주장을 기록한다.
   - (c) R-1 리허설 부팅에서 driverLoader·EMU10K1 로그를 먼저 확인한다.
   - 권장은 (a) 다.  같은 PCI 위치를 두 드라이버가 가리키는 구성은 C3 판정 "겹치면 소유가 순서에 달린다" 의 경우다.
3. **`OSRDNDisplay` `Instance0.table` 의 `Location`**:
   - (a) `Dev:11 Func:0 Bus:3`(R2a 실측 03:0b.0).  Matrox 가 동작한 상태와 같은 형태다.
   - (b) 빈 값.  동작 여부 미확정.
   - 권장은 (a) 다.

## 4. 환경

- 검토자·재검증 모두 읽기 전용이다.
- 실기 접근은 telnet 읽기 둘뿐이다: EMU10K1·Pro1000·OSMGADisplay 인스턴스 표의 `Location` 줄, 앞서 System.config 표.
