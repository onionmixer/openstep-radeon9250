# Q14 판정 — R2b-0 코드·실행 순서 교차검토 재검증

작성 2026-09-16.  입력: `Q14_reply_CODEX.md`(codex `gpt-5.6-sol`), `Q14_reply_A.md`(드라이버·판정기),
`Q14_reply_B.md`(타깃 스크립트·순서).  회신은 검증 대상이지 결론이 아니다 — 아래 "내 검증" 칸은 이
세션에서 실제로 연 원문·실행한 명령만 적는다.  실기에는 아직 아무것도 하지 않았다.

## 0. 내 오류 (코드)

| # | 오류 | 근거(연 원문·실행) | 조치 |
|---|---|---|---|
| 1 | **활성화 부팅을 통째로 날릴 표지 설계.** 실행 스크립트가 `/usr/ucb/logger` 로 시스로그 표지를 쓰고 그것을 하드 게이트로 삼았다.  이 기계는 `logger` 가 `/usr/adm/messages` 에 남지 않는 것을 이미 실측해 두었는데 그 기록을 확인하지 않았다.  런 ID 선점(옛 109 행) 뒤에 실패하므로 재부팅 2 회와 재빌드를 버린다 | `build/r1c/syslog-check.txt` 2 행 `kern.debug;daemon,auth.notice;*.err;mail.crit /usr/adm/messages`(user 없음); `docs/R1C_RESULT.md` 사실 5 "`logger` 표지가 `/usr/adm/messages` 에 남지 않음 … 이번 실행은 표지 없이 진행" | 표지를 **드라이버 자신의 커널 줄**로 바꿨다.  도구에 `state` 모드를 더해 기록 전에 `RDNR2b0State` 를 한 번 읽고, 클래스가 `RDN-R2B0 state boot=… build=… records=… last=… flags=… cmode=… loc=…` 를 IOLog 한다.  스크립트는 그 줄이 10 s 안에 오는지로 시스로그를 증명하고, **그다음에** 런 ID 를 선점한다 |
| 2 | **커널이 이미 해제한 객체를 다시 해제.** `init` 의 `if ([super initFromDeviceDescription:] == nil) return [super free];` | 디컴파일 `001c4dec.c` 14–19 행: `iVar1 = _objc_msgSendSuper(… initFromDeviceDescription_ …); if (iVar1 == 0) { … _objc_msgSendSuper(… free …); }` — 실패 경로에서 슈퍼클래스가 이미 free 한다 | `return nil;` 로 바꿨다.  규칙 `class-init-free` 를 "`[super free]` 는 `-free` 안에서만" 으로 뒤집고 변이를 추가했다(옛 규칙은 오히려 이 형태를 **강제**하고 있었다) |
| 3 | **모드 목록을 막지 않았다.** 슈퍼클래스가 `_displayModeCount` 를 `0xffffffff`, `_displayModes` 를 NULL 로 두는데, 커널의 `IOGetDisplayModeInfo:<n>` 는 부호 없는 비교 뒤 `displayModes + n*0x88` 을 읽는다 → 어떤 인덱스든 NULL 접근 | `001c4dec.c` 21–24 행; `001c3cdc.c` 184–186 행 `(uVar5 = _objc_msgSend(param_1, …displayModeCount…), uVar8 < uVar5)` → `iVar3 = _objc_msgSend(param_1, …displayModes…); piVar2 = (int *)(iVar3 + uVar8 * 0x88);` | `- (unsigned int)displayModeCount { return 0; }` 를 두었다 |
| 4 | **복원이 System 표를 먼저 썼다.** manifest 가 경로순이라 `System.config` → `VGA.config` 순서가 된다.  그 사이 전원이 끊기면 `Active Drivers` 는 VGA 인데 VGA 인스턴스 표가 없다 | `me/restore.sh` 옛 2 단계(경로순 루프); python3 `sorted([...])` → `['EMU10K1.config/…','System.config/…','VGA.config/…']` | 두 벌로 나눠 **System 을 마지막에** 쓰고 그 사이 `sync` |
| 5 | **복원이 낯선 인스턴스 표까지 옮겼다.** manifest 에 없는 표를 전부 주차했다 — `Active Drivers` 에는 telnet 이 타는 `Pro1000` 이 있다 | 옛 `me/restore.sh` 3 단계; S8 의 `Active Drivers` | `OSRDNDisplay.config/*` 만 주차하고, 그 밖의 낯선 표는 **옮기지 않고** 종료 3(재부팅 금지) |
| 6 | **NFS 에 한 줄씩 이어썼다.** `cfgsnap` 의 `LIST` | 옛 `target-cfgsnap-r2b0.sh` 67 행 `>> $DEST/LIST`; 메모리 "OPENSTEP NFS append 함정"(재open 하면 마지막 하나만 남는다) | `/tmp` 에서 만들고 한 번 복사·`cmp` |
| 7 | **`run.done` 을 런 ID 선점 전에 지웠다.** 실수로 다시 돌리면 성공한 실행의 결과가 사라진다 | 옛 `target-run-r2b0.sh` 71–72 행 대 109 행 | 선점에 성공한 뒤에만 `DONE` 을 정하고 지운다.  선점 실패는 `run.done` 을 건드리지 않고 끝낸다 |
| 8 | **위험한 호출 전에 증거가 NFS 에 없었다.** 기록 중 행이 나면 진단이 남지 않는다 | 옛 `target-run-r2b0.sh`(로그는 `/tmp`, 복사는 끝난 뒤) | 기록 직전에 로그·state 출력을 NFS 로 복사·`sync`.  `finish` 는 `check.sh` 출력도 나른다 |
| 9 | **`indexend` 판정이 항등식.** 파서가 게이트 줄의 값으로 그 게이트 줄을 검증했다 | 옛 `parse_r2b0.py` 430–431 행 `w = (1, 'indexend', h(x['val']), p0, …)` | 드라이버가 PLL 뒤 읽은 값을 `idxend val=…` 줄로 따로 남기고, 파서는 그 줄로 판정한다(줄 없음·있으면 안 되는데 있음 모두 FAIL) |
| 10 | **VGA 미해독일 때 스택 쓰레기를 기록으로 찍었다** | 옛 `osrdn_record.m` `vgaSnapshot`(미해독이면 `seq/crtc/gr/attr` 미초기화) | 구조체를 첫 포트 읽기 전에 0 으로 채운다 |
| 11 | **MISC 와 CRTC 기저의 불일치가 기록만이었다** | 옛 `parse_r2b0.py` `vga_facts` 의 `out.append` | FAIL 로 올렸다 |
| 12 | **`dotClockRate` 를 공개하지 않았다** | `grep -n dotClockRate OSRDNDisplay.m` → 없음; Matrox `OpenStepMGAReplacementDisplay.m` 4020 행이 공개한다 | 공개 모드의 공칭값 65250000 을 넣고, R2b-0 은 클럭을 쓰지 않는다는 주석을 달았다 |
| 13 | **`same` 게이트가 표지를 남기지 않았다** — 건너뛰어도 드러나지 않는다 | 옛 `check_cfgdiff.py` 316 행 | PASS 면 `SAME_PASS` 를 쓴다 |

## 1. 검토자별 판정

| 회신·주장 | 내 검증 | 판정 |
|---|---|---|
| **B1(차단)** `logger` 표지는 이 기계에서 오지 않는다 | 0-1 | ✅ 채택 |
| **A1-1(차단)** `[super free]` 이중 해제 | 0-2 | ✅ 채택 |
| A1-8 `displayModeCount` 기본값이 NULL 읽기를 연다 | 0-3 | ✅ 채택 |
| CODEX Q4-6 / B3 복원 순서·주차 범위 | 0-4·0-5 | ✅ 채택 |
| B2 `run.done` 순서, 기록 전 증거 없음, `check.sh` 출력 미수집 | 0-7·0-8 | ✅ 채택 |
| B4 `cfgsnap` 의 NFS 이어쓰기 | 0-6 | ✅ 채택 |
| CODEX Q2-6 `indexend` 항등식 | 0-9 | ✅ 채택 |
| CODEX Q1-3 / A2-3 미해독 VGA 의 초기화되지 않은 값 | 0-10 | ✅ 채택 |
| CODEX Q3-2 MISC/기저 불일치가 기록만 | 0-11 | ✅ 채택 |
| CODEX Q1-7 `dotClockRate` 없음 | 0-12.  단 **인용은 틀렸다**: codex 는 `R2B0_IMPL_PLAN.md:348` 을 근거로 들었는데 그 줄은 "기대값 출처 표" 다.  요구는 상위 계획 `R2_FIRST_LIGHT_PLAN.md` 348 행(R2b 모드셋 단계)과 Matrox 선례에 있다 | ⚖️ 사실 채택, 인용 정정 |
| B4 `same` 게이트에 표지 없음 | 0-13 | ✅ 채택 |
| A3-2 init 줄·`--tool` 없이 `cmode`·`loc` 미검증 | 상태 줄에 `cmode`·`loc` 를 넣고 파서가 begin 줄과 대조하게 했다(새 자체검사 2 건) | ✅ 채택 |
| B3 사전 점검이 "`Active Drivers` 의 모든 드라이버가 인스턴스 표를 갖는가" 를 안 본다 | 사실이다(`check_cfgdiff.py` `mode_precheck`).  다만 위험(Pro1000 표 상실)은 0-5 로 닫혔다 — 복원은 이제 낯선 표를 옮기지 않는다 | ⚖️ 위험은 다른 방법으로 닫음, 규칙 추가는 하지 않음 |
| B5 / CODEX Q5 실행 순서에 `postb`·`restored` 게이트와 `/me/rdn-r2b0/…` 경로가 빠졌다 | 프롬프트에 요약한 순서가 짧았던 것이고, 계획 §9 에는 둘 다 있다(605–609 행) | ⚖️ 코드 결함 아님.  실행은 계획 §9 전문을 따르고, 요약본은 쓰지 않는다 |
| B4 NFS 의 스크립트를 고정 이름으로 실행(R1c 의 낡은 짧은 읽기) | `docs/R1C_RESULT.md` 사실 3 확인 | ✅ 절차로 채택: 각 타깃 스크립트를 돌리기 전에 타깃에서 `sum` 을 재고 호스트 값과 대조한다(§12) |
| CODEX Q5-6 / B5 활성화 직전 새 측정(BAR·브리지·콘솔 모드·여유 공간) | `pcils` 도구가 있고(`docs/R0_5_TOOLS.md` 21 행) 그 캡처를 사전 점검이 이미 쓴다.  `_basicConsoleMode` 는 kmem 읽기로 이미 쟀다(Q13) | ⚖️ 부분 채택: 활성화 스냅샷과 같은 부팅에서 `df`·`ls`·`Active Drivers` 를 찍는다.  `pcils` 재실행은 커널 모듈 적재라 **operator 판단**(§12) |
| CODEX Q1-5 평범한 거절은 걸쇠를 걸지 않는다 | 설계대로다(계획 §9: 줄 손실만 1 회 재실행) | ❌ 기각(문서화된 결정) |
| CODEX Q3-2 시각·프레임 값 무검사, init 줄 없어도 통과 | 시각은 기록 전용이라는 계획 결정이고(Q13 채택), init 줄은 활성화 부팅의 캡처 창 밖이라 필수로 둘 수 없다.  같은 부팅 증명은 이제 상태 줄이 한다 | ❌ 기각(근거 기록) |
| A "시뮬레이터 녹색 세계는 R2a 값을 심은 것" | `sim_r2b0.py` 52–57 행 확인 | ✅ 계획 §12 에 명시 |
| A 미확인: 이 카드에서 `0x3C0` 읽기가 속성 인덱스를 돌려주는지(S14 는 추론) | 계획 S14 그대로 | ✅ operator 고지에 "기록 뒤 화면이 비어도 패닉이 아니다" 를 추가 |

## 2. 고친 뒤 상태

`sh tools/r2b0/hostcheck.sh` 11 단계 PASS — 소스·목적 규칙 63(변이 포함), 파서 자체검사 36,
시뮬레이터 세계 21·변이 33, 역어셈블 게이트 11, 드리프트 6 hunk, 스냅샷 판정 30, 타깃 스크립트 59.
`sh tools/check-all.sh` PASS.

## 3. 남은 미확인 (실기가 가른다)

- 아무 일도 하지 않는 `enterLinearMode` 로 WindowServer 가 사는가, telnet 이 사는가(S10).
- `0x3C0` 읽기가 속성 인덱스인가(S14 추론).
- cc 2.7.2.1 이 낸 reloc 의 명령어 폭·포트 명령 위치(타깃 빌드 뒤 `check_reloc_r2b0.py` 가 본다).
- Configure.app 의 실제 파일 집합 동작(R-1 이 잰다).
