# Q13 판정 — R2B0_IMPL_PLAN 개정 1 교차검토 재검증

작성 2026-09-15.  입력: `Q13_reply_A.md`, `Q13_reply_B.md`.  검토자 회신은 검증 대상이지 결론이 아니다.
검증은 이 세션에서 원문을 열고 python3 로 다시 계산한 것만 적는다.

## 0. 내 오류 (개정 1)

| # | 오류 | 근거(연 원문·실행) |
|---|---|---|
| 1 | §7-3 로 활성화 수단을 바꾸고도 §7(표 365·367 행), §7-2(389–390 행 "§7-1 의 5–6", `baseline`), §8 R-1(418 행 `--rehearse`), §9 게이트(443 행 `cmp`)에 없어진 §7-1 경로를 남겼다.  413 행과 417–420 행이 R-1 을 서로 다르게 정의한다 | `R2B0_IMPL_PLAN.md` 365·367·389·390·413·418·443 행 열람 |
| 2 | 상위 계획 §7 게이트(383 행 "거절 반환, `modeWritten` 0")와 §3 표(70 행 "부트 로더 상태 실측")를 5.1 에서 고치지 않았다.  §3 게이트(180 행)의 "복귀 표 `cmp` 일치" 는 Configure 가 키 순서를 바꾸는 사실과 모순이다 | `R2_FIRST_LIGHT_PLAN.md` 70·180·383 행 열람 |
| 3 | `check_cfgdiff` 를 **키 집합** 비교로 설계했다.  값 변화(`Location`·옵트인 키·`Display Mode`)를 못 잡고, Configure 가 템플릿에서 만들 때 넣는 `Default Table` 키에는 헛멈춤한다 | python3: VGA 저장본 vs `SVGABIOS.table` → only-after `['Default Table']`, 값 차이 0; vs `Default.table` → `Default Table`·`SVGA Mode`·`SVGA VESA BIOS Mode` 추가, `Display Mode` 640×480→800×600 |
| 4 | 옵트인 키를 `Instance0.table` 만 `"Yes"` 로 두고 활성화는 Configure 로 정했다.  Configure 가 드라이버를 **추가**하면 `Default.table` 에서 새 인스턴스를 만든다는 Matrox 실측이 있다 → 키가 `"No"` → 활성화 부팅이 종료 6 으로 끝난다 | Matrox `R5_INSTALLER_KEEPS_THE_CONFIGURATION_PLAN.md` 22–25 행 "adding it made Configure write a fresh instance from `Default.table`, where every development switch is `No`", 137–138 행 |
| 5 | 활성화 부팅은 스캔아웃이 없는데(78 행) §7-3 원복을 "반대 방향(Configure)" 으로 적었다(404 행).  그 부팅의 원복은 **항상** telnet 스크립트다 | 78·404·412 행 |
| 6 | `/me` 복구 스크립트가 `System.config/Instance0.table` 한 파일만 되돌린다.  Configure 활성화는 VGA 인스턴스 표를 지우거나 새로 만들 수 있다(현 VGA 표는 SVGABIOS 800×600, 공장 Default 는 640×480) | 369·389 행; VGA 저장본 3 행 `"Default Table" = "SVGABIOS"` |
| 7 | 파서가 R2a 판정 `_judge` 를 그대로 쓰면 R1 대비 문서화된 비트 차이·`PLL_DIV_SEL` 차이를 FAIL 로 낸다 — 활성화 부팅에서 바로 그 값들이 R1(VESA 800×600 부팅)과 다를 것이다 | `tools/r2a/parse_r2a.py` 254–255·264–266 행; R2a 로그 python3: `CRTC_H_TOTAL_DISP 0x63007f`, `CLOCK_CNTL_INDEX 0x303` |
| 8 | §6-2 표가 `inb`(311 행, VGA 읽기에 필요 → 반전), `inw`/`outw`, `outl-*`/`inl-*`/`cfg-offset`, map 계열(358–377), `unmap`(389), 세계 `'unmap fails'`·`'…differs from R1'`, 페이싱 단언(243 행, +1000 ms 없음)을 빠뜨렸다.  "나머지 18" 안의 `'eleventh PLL index'` 는 새 "12 번째 인덱스 오류" 와 중복 | `simworld2a.c` 262–263·287–288·311–314·319–342·389 행; `sim_r2a.py` 181·188·190·243·285 행; python3 MUTATIONS 항목 20 |
| 9 | `sleep-inside-live-window` 는 프로세스 전역 `delayCalls` 라 두 번째 기록(재진입·부팅당 2 회 세계)을 지키지 못한다 | `simworld2a.c` 262 행 `if (delayCalls > 0 && delayCalls < LIVE_GAPS)` |
| 10 | 기록 사이 **종결 걸쇠**가 없다.  pllabort·pllbusy·vline-static 로 끝난 뒤에도 "부팅당 < 2" 가 두 번째 기록을 허락한다.  PLAN 금지 8 "로그 한 번 뒤 영구 비활성화" 위반 | `PLAN.md` 139–146 행; 계획 86–88·453·457 행 |
| 11 | §9 중단에 종료 4–8, 강제 전원 재투입(PLAN 중단 1·8 은 마일스톤 정지), `check_cfgdiff` FAIL 시 행동이 없다 | 계획 447–458 행; `PLAN.md` 489–499 행 |
| 12 | `target-cfgsnap` 에 `ps` 를 넣었다 — 실기 행 뒤 만든 lint 가 금지한다 | 401 행; `tools/r1c/check_target_r1c.py` 50 행; `tools/r2a/check_target_r2a.py` 175 행(실패하는 가짜 `ps`) |
| 13 | §11-2 "틀린 `Location` 으로도 attach 했다" 는 **추론**이었다.  캡처한 로그에 `probe: location` 줄이 없다.  실기 `/usr/adm/messages` 에도 없고, `messages.old` 에는 `Sep 8 03:28:10 … probe: location 03:0b.0` 뿐(그때 SB Live 가 0b 에 있었다 — 카드 이동으로 낡은 값) | `grep -n "probe: location" build/r2b0/boot-1517.txt` → 없음(rc 1); 실기 읽기(telnet, 2026-09-15): `grep -n "probe: location" /usr/adm/messages` 0 줄, `messages.old` 70 행 |
| 14 | 4-6 "대기 1.06 s" — 실제 `60+1000+7*2` = 1074 ms(195 행 3.47 s 는 맞다) | python3 `60+1000+7*2` → `1074`, `120*0.020+1.074` → `3.474` |
| 15 | §11 번호 순서 1,2,3,7,4,5,6.  §10-9·10 이 이미 결정된 항목을 "결정 필요" 로 가리킨다 | 470–471·477–504 행 |

## 1. 검토자 B

| 주장 | 내 검증 | 판정 |
|---|---|---|
| E1.1 sum·줄 집합·순서 | python3 BSD sum: EMU after `(2880)`, expected `(17199)`, orig `(17135)`, System `(11206)`, VGA `(16469)`; 차이 1 줄(17 행 `Location`); 집합 같음, 순서 `[17, 18, 2, …, 16, 1, 0]` | ✅ (VGA 블록 수는 블록 크기 가정 차이, 계획에 안 들어감) |
| E1.3 템플릿 인스턴스화·`Default Table` 추가 | python3 키→값 대조(위 0-3) | ✅ |
| E1.4 Matrox R5 22–25·137–138 | 원문 열람(20–27·135–139 행) | ✅ |
| E1.9 인스턴스 표는 기계의 것 | `tools/install-matrox-driver.sh` 10–20 행 | ✅ |
| E1.10 설치 EMU10K1 표 ≠ 저장소 표 | `openstep-emu10k1/EMU10K1/Instance0.table` 4 행 `"Version" = "001"`, 19 행 `Timer Samples` | ✅ |
| E1.12 `ps` lint | 위 0-12 | ✅ |
| E1.14/E1.15 `cmp` 게이트·R-1 이중 정의 | 위 0-1·0-2 | ✅ |
| E1.16/E1.17 경로 동일·목록이 적재 결정 | `openstep-ac97/README-Instance0.md` 99–105 행 | ✅ |
| B1.1(c) "Configure 가 `Location` 을 채운다" 미확인 | 캡처한 VGA 저장본은 `"Location" = ""`(17 행) — 채운 사례 없음 | ✅ 미확인으로 기록 |
| B1.2 `check_cfgdiff` 키→값·파일 집합·정지 목록 | 0-3 | ✅ 채택(목록은 개정 2 에서 재작성, (vi) "Configure 실행 중" 은 `ps` 없이 operator 진술로) |
| B1.3 옵트인 키 대 Configure | 0-4 | ✅ 채택 → operator 결정 필요(§3) |
| B1.4(a)(b)(c)(d) 원복 경로·집합 복원·출처 단일화·무재부팅 왕복 리허설 | 0-5·0-6; 413·389·412 행 | ✅ 채택 |
| B1.4(e) R-2 에 VGA·OSRDNDisplay 표 sum 추가 | 425 행 열람 — `System.config/*.table` 만 | ✅ |
| B2 표 | 각 행 원문 대조(365·367·381·384·388·389·409·443 행, 상위 70·179–180·383 행) | ✅ (0.12e "made worse" 동의) |
| B3.1 `_judge` R1 대비 FAIL | 0-7 | ✅ |
| B3.3 사람 값 10 개 = R2a 원시 로그 | python3 로그 재파싱: `OV0_SCALE_CNTL 0x807f0000`, `TV_DAC_CNTL 0x7660142`, `DISP_HW_DEBUG 0x20000`, `DISP_OUTPUT_CNTL 0x10000000`, `DAC_CNTL2 0x0`, `CRTC_OFFSET_CNTL 0x10000000`, `MEM_CNTL 0x32003200`, `MEM_TIMING_CNTL 0x1a395323`, `CONFIG_APER_0_BASE 0xe0000000`, `DISPLAY_BASE_ADDR 0x0`; 상위 219 행 열람 — `HOST_PATH_CNTL`·`SURFACE_CNTL`·MC 맵은 "= R1" 로만, 16 진 없음 | ✅ |
| B3.4 자체검사 결과값 누락 | 273–277 행 | ✅ |
| B3.5 §6-2 표 | 0-8 | ✅ |
| B3.6 종결 걸쇠 | 0-10 | ✅ |
| B4.1 중단 누락 | 0-11 | ✅ |
| B4.2 operator 사전 고지 | 78·448·450 행 | ✅ 채택 |
| B4.5 "`Location` 이 실제 슬롯과 맞음" 점검이 §7-3 에 없음 | 402 행("둘 이상인지"만), 496 행 | ✅ |
| B4.6 attach 증거 없음 | 0-13 (실기 syslog 추가 확인) | ✅.  **단 "다음 캡처 로그로 닫는다" 는 불가**: 현재 syslog 에 probe 줄이 남지 않는다 → 부팅 버퍼(`boot-1517.txt` 식)에서 확인하거나 미확인으로 둔다 |
| B5 사실 표(S1–S24) | 표본 재확인: S17 수치 python3 `25175000/(800*525)` → `59.94047619047619`; 나머지는 A 회신 검증과 함께 | ⚖️ B 가 PASS 라 한 줄번호는 A 판정 뒤 대조 스크립트로 일괄 확인 |
| B5 "S7 install 143–149" | 계획 46 행 인용, B 는 143–146 확인 | ⏭️ 행동 불변 |
| 개정 1 R2a 줄 종류 합 81 | python3 Counter → reg 50, pll 10, live 8, cfg 4, bridge 2, begin·pci·mmio·frame60·pllstart·pllend·end 각 1, 합 81 | ✅ |

## 0-A. 내 오류 (검토자 A 로 드러난 것)

| # | 오류 | 근거 |
|---|---|---|
| 16 | **§5 도구가 `IOGetDisplayInfo` 를 `getCharValues` 로 묻는다 → 매 실행 -711 → 종료 4**, 활성화 재부팅 한 번이 버려진다.  커널은 이 이름을 `getIntValues` 에서 in-count 5 또는 7 로만 받는다.  Matrox 가 같은 실수를 실측했다.  Q12 B 주장을 원문 대조 없이 채택한 것이 원인 | `KD/001c3cdc.c` 21 행 `iVar3 = *param_5;`, 111 행 `"IOGetDisplayInfo"`, 120 행 `if ((iVar3 == 5) \|\| (iVar3 == 7))`; `grep -l IOGetDisplayInfo KD/*.c` → `001c3cdc.c` 만; `KD/001a48f0.c` 62–63 행 `return 0xfffffd39;`; python3 `0xfffffd39-2**32` → `-711`; Matrox `S3B_PREP_INSTRUMENTATION_PLAN.md` 450·454–455 행 |
| 17 | 거절 코드 `IO_R_UNSUPPORTED`(종료 6)는 슈퍼클래스가 **모르는 이름 전부**에 돌려주는 값이라 "키 없음" 과 "재정의에 도달 못함" 을 못 가른다 | `KD/001a49d0.c` `return 0xfffffd39;` |
| 18 | S17 "커널 VGA 콘솔이 VGA 레지스터를 쓴다" 에 **조건**을 빠뜨렸다: `_kminit` 은 부트 구조체 `graphicsMode == 0`(텍스트 부팅)일 때만 initScreen=1 을 넘기고, 그때만 `_VGASetGraphicsMode` 가 불린다.  아이콘 부팅이면 부트 로더 상태다.  또 VBE 콘솔 여부는 `"Boot Graphics"` 키가 아니라 부트 로더가 채운 VBE 필드로 갈린다(§11-2(iv) 틀림) | `KD/00197514.c` 17–26 행 `bVar1 = _DAT_0001114c == 0; … (_basicConsole,uVar2,bVar1,bVar1,…)`; `KD/0019ab88.c` 53 행 `if ((param_2 - 1 < 2) && (param_3 != 0))`; Darwin01 `km.m` 501–509 행; `KD/0019ecb8.c` 16 행 `if ((_DAT_0001285c == 0) \|\| (_DAT_00012854 == 0))`; `strings -a mach_kernel \| grep -ic "boot graphics"` → `0` |
| 19 | §4-3 "플립플롭을 인덱스 상태로 두는 것이 참조 쓰기 주체의 관례" — 커널은 **데이터 상태로 두고 끝낸다**.  관례는 "쓰기 전에 리셋" 이다 | `KD/001979e4.c` 121–122 행 `in(0x3da); out(0x3c0,0x20);` |
| 20 | §6-4 "reloc 전체에서 `out` 0 개" 를 선형 스윕으로 하면 **이미 PASS 한 R2a reloc 에서 거짓 `in` 이 나온다**.  opcode 목록도 `E4–E7`·`6C–6F`·`66` 접두를 빠뜨렸다 | python3(`check_reloc.parse_macho`/`function_ranges`/`disassemble`) R2a reloc: 전체 스윕 → `0xf26 in $0x8b,%eax`(`_rdnMmioRead32`), `0xf5e in $0xb8,%eax`; 범위별 → `_pciRead` 의 `out %eax,(%dx)`·`in (%dx),%eax` 둘뿐 |
| 21 | 읽기 포트 허용 목록이 없다(`0x3C7`–`0x3C9` DAC 읽기가 규칙을 통과) | 계획 337–340 행: 쓰기 인자만 제한 |
| 22 | `splhigh` test-and-set 구간 내용(IOLog 는 `splx` 뒤, "진행 중" 해제는 모든 출구, 계수는 test-and-set 시점)을 정하지 않았다.  `IOGetTimestamp` 금지의 커널 근거(`_splusclock` 이 무조건 레벨 6 으로 내림)도 안 적었다 | `KD/0018bd98.c` 끝 `DAT_001e7714 = 6;`(조건 밖), 레벨 >6 이면 PIC 마스크 재기록 |
| 23 | 옵트인 키를 **언제** 읽는지 안 정했다(Matrox 는 init 에서 한 번 읽어 캐시) | `OpenStepMGAReplacementDisplay.m` 3896–3900 행 |
| 24 | `+probe:` 의 `getPCIdevice:` 실패(rc -704, 출력 인자 **미기록**) 처리·로그가 없고, nxlogd 전 버스 스캔이 "로그 없는 변형" 으로 선언되지 않았다 | `KD/001c1c70.c` 11–12 행 `if (*pcVar1 == '\0') { uVar2 = 0xfffffd40;`; python3 → `-704`; 헤더 `IOPCIDeviceDescription.h` 29–30 행 "parameters are left untouched" |
| 25 | init 실패 경로 `[super free]` 는 자기 `free` 를 건너뛰어 MMIO 매핑이 샌다.  revert 줄에 `boot=` 없음.  S11 "count 는 in/out" 은 get 만 맞다(set 은 값 전달) | 계획 77·157·164 행; `IODevice.h` 161–171 행 |
| 26 | 금지 8 예외는 Q12 결정 질문에 operator 가 "네 다른건 상관없는데" 로 이미 승인했는데, 개정 1 에 "결정 필요" 로 남겨 검토자 B 가 "여전히 열림" 으로 읽었다 | 대화 기록(Q12 보고의 결정 질문 1 과 그 답) |

## 2. 검토자 A

| 주장 | 내 검증 | 판정 |
|---|---|---|
| E1.2 `IOGetDisplayInfo` 는 getInt 5/7 | 0-16 | ✅ 채택(차단) |
| E1.4 -711 은 모르는 이름의 기본값 | 0-17 | ✅ 채택: 키 거절은 `IO_R_PRIVILEGE`(-705, `return.h` 20 행) |
| A2-1 커널 표 바이트 | Q12 에서 확인한 VA 바이트 + 이번 python3 섹션 파싱: `0x1d54dc __TEXT,__const e3 00 03 21 0f 00 06 5f 4f 50 82 …` | ✅ |
| A2-2 작성 주체는 조건부, "이 기계의 평상 부팅은 아이콘 부팅이라 아마 거짓" | **실기 측정(읽기만, telnet, 2026-09-15)**: `/dev/kmem` 오프셋=VA 를 `_hz`(0x1dee30)=`100`·`_tick`=`10000` 으로 확인한 뒤, `_basicConsoleMode`(0x1f7b40) = **`1`**(TEXT), `_basicConsole`(0x1f7b3c) = `0x376000`, 그 연산표 = `0x19b81c 0x19ab88 0x19ae0c 0x19b340 0x19b860 0x19b9c8 0x19b9e0` = `_VGAAllocateConsole` 이 넣는 표(`KD/0019b760.c` 24–30 행).  사본 `build/r2b0/rdnk1..4` | ⚖️ **조건은 채택, 결론은 기각**: 이 기계의 현 부팅은 텍스트 모드·VGA 콘솔이라 `_VGASetGraphicsMode` 가 **실행됐다**.  S17 에 조건을 적고 기록에 `_basicConsoleMode` 를 싣는다 |
| A2-3 VBE 는 부트 로더 VBE 필드 | 0-18 | ✅ (위 실측으로 이번 부팅은 VBE 아님) |
| A2-4 `registerDisplay` 뒤 MISC/CRTC/ATTR 상수 포트 쓰기 주체 없음 | `grep -l "out(0x3c0,"`·`0x3c2`·`0x3d4`·`0x3d5` → 각각 `001979e4.c` 만; `out(0x3c4,` 의 2 가 아닌 인덱스는 `001979e4.c` 16·36·45·125 행뿐; `KD/00195c68.c` 61–66 행 | ✅ (변수 포트는 못 봄 — A 한계 그대로 기록) |
| A2-5 SEQ0/1/3/4 예측 가능, GR·SEQ2 기록만 | 위 grep | ✅ 채택(비-FAIL 대조) |
| A2-6 CRTC 타이밍/커서 분리 | 행동: `vga-state-differs` 의 헛발생 방지 | ✅ 채택 |
| A2-7 플립플롭 문구 | 0-19 | ✅ |
| A3-1 `getPCIdevice:` rc·위치 로그, 거절, probe 스캔 삭제 | 0-24; `KD/001c1b88.c` 25–32 행(설명 생성 시 `configAddress:`) | ✅ 채택: probe 스캔을 빼고 "RV280 기능 1 개" 는 기록 B 로 |
| A3-3 nonce 는 가동시간, 부팅 계수 아님 | `KD/00187b98.c` `param_1 == 1` 이면 `time_of_boot` 안 더함 | ✅ 문구 |
| A3-4 get 성공 시 `*count = 8` | `KD/00181dd4.c` `local_8 = param_4; … *param_6 = local_8;` | ✅ |
| A3-5 임계 구간 내용 | 0-22 | ✅ 채택(차단) |
| A3-6 splhigh/splx 가 PIC 0x21/0xA1 을 쓴다 | `KD/0018bd98.c` `out(0x21,…)`·`out(0xa1,…)` | ✅ §0 에 PIT 래치와 함께 기록 |
| A3-8 키는 init 에서 한 번, `freeString:`, State 에 노출 | 0-23; `KD/00195c68.c` 24–41 행 `freeString:` | ✅ 채택 |
| A3-9 `return [self free]` | 0-25 | ✅ |
| A4 빈 `Location` → PCIBus 가 ID 스캔으로 `Instance` 번째 일치를 묶음 | **직접 역어셈블**(`PCIBus_reloc` `__text` 파일 오프셋 0x918, 0x594–0x843, 문자열·셀렉터는 `__cstring`/`__message_refs` 로 해석): `63f push 'Location'` → `659 test; 65b je 6d6`(없음→스캔), `661 cmpb $0x0,(%ebx); 664 je 6c2`(빈 문자열→해제 후 스캔), `6b2 testIDs:` 일치 시 `6be movb $0x1`, `6e0 'Instance'`→`strtoul`, `76b testIDs:` / `777 cmpl $0x0,-0x18(%ebp); 77b jle 784`(찾음), `7ec testb $0x80,-0xe(%ebp)`(다기능 비트), `834 mov $0xfffffd40` | ✅ |
| A4-3 타깃 PCIBus 가 미러와 같은지 미확인 | **실기 읽기**: `sum /private/Drivers/i386/PCIBus.config/PCIBus_reloc` → `09451 40`; 호스트 미러 `sum` → `09451 40` | ✅ 이제 확인됨 |
| A4 EMU10K1 attach 설명(Dev:11 은 ID 불일치 → 스캔이 Dev:13) | 위 역어셈블 경로 | ⚖️ 기제는 확인, 이번 부팅들의 attach 위치 줄은 여전히 없음(0-13) |
| A5-1 별도 포트 단위는 심볼로 남는다 | R2a reloc 범위별 결과(인라인 확장, `_inl`/`_outl` 심볼 없음) | ✅ |
| A5-2 선형 스윕 불가, 범위별+범위 밖 바이트+간접 점프 | 0-20 | ✅ 채택(차단) |
| A5-3 opcode 목록 | 명령어 표기(`in`·`out`·`ins*`·`outs*`)로 판정 | ✅ 채택 |
| A5-4 `lock incl` 은 32 비트 저장으로 분류 | 행동 불변(현 규칙 영향 없음) | ⏭️ 미래 규칙 면제로만 기록 |
| A5-6 읽기 허용 목록, `IOReadRegister` 계열 이름 | 0-21 | ✅ (`displayRegisters.h` 11 행 `#import <driverkit/i386/ioPorts.h>`, 13·23·33 행 세 이름 확인) |
| E5.6 64 비트 나눗셈 변이가 실패할 수 있다 | 호스트 `gcc -m32 -O0 -fno-inline` → `nm d.o`: `U __udivdi3`(f 만) | ✅ |
| A1 표의 나머지 fixed 판정 | 개정 1 해당 행 열람(55·58·189·485 등) | ✅ |

## 3. 채택 요약 → 개정 2

- 활성화·복원: 단일 절차(Configure 활성화, 원복은 **항상** `/me` 집합 복원), R-1 = 무재부팅 Configure 왕복 + 집합 복원, `cmp` 게이트 교체.
- `check_cfgdiff`: 키→값·파일 집합·정지 목록, `ps` 제거(operator 진술).
- 파서: R1 대비 판정 제거·기록화, 사람 값 출처 표, 자체검사 결과값.
- 드라이버: 종결 걸쇠, 임계 구간 내용, 키 init 캐시·`IO_R_PRIVILEGE`, `getPCIdevice:` 거절·로그, probe 스캔 제거, `[self free]`, `_basicConsoleMode` 기록.
- 도구: `getIntValues:"IOGetDisplayInfo"` count 5.
- 게이트: §6-4 범위별 역어셈블, 읽기 허용 목록.
- 중단: 종료 4–8, 전원 재투입 = 마일스톤 정지, cfgdiff FAIL.
- 문구: S17 조건, VBE 근거, 플립플롭, S11, 1074 ms, §11 번호.

## 4. operator 결정 필요

1. **옵트인 키와 Configure 활성화**(0-4).  선택지:
   - (a) 기록 전용 빌드는 `Default.table` 도 `"Yes"` — PLAN §4 기본 꺼짐의 예외(D-3 "`Active Drivers` 편집 자체가 옵트인" 을 R2b-0 기록 파라미터로 넓힘).  파라미터는 root 도구의 runid·magic 이 있어야만 돈다.  **권장**.
   - (b) Configure 저장 뒤 검토된 스크립트로 키 한 줄을 고친다(타깃 쓰기 1 회 추가, cfgdiff 가 확인).
   - (c) 키를 없애고 다른 옵트인.
2. ~~금지 8 예외~~ — 이미 승인됨(0-26).  개정 2 §11-1 에 기록.
