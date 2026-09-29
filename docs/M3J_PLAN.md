# M3J — 참조의 복구: 걸쇠 대신 kick → 엔진 리셋 → 재시작 → 계속

`docs/G1_REMAINING.md` 부팅 1 의 드라이버.  **이 문서는 코딩 전에 쓴다.**

## 1. 참조 대조 (FreeBSD `radeon_cp.c`, 원문 확인)

| 단계 | FreeBSD | 우리 | 판정 |
|---|---|---|---|
| 시간 초과 | `radeon_wait_ring` 은 `-EBUSY` 만(1901–1930); Xorg 가 idle 재시도 뒤 `cp_stop idle=0` → `radeon_do_engine_reset` | 100 ms 뒤 **부팅 내내 걸쇠** | **우리만 다름** — 바꾼다 |
| 정지 | `radeon_do_cp_stop`: `CSQ_CNTL = PRIDIS_INDDIS`(617) | `cpStopLatched` 같은 쓰기 | 같음 |
| 엔진 리셋 | pixcache flush, MCLK forceon, `RBBM_SOFT_RESET` 펄스(CP|HI|SE|RE|PP|E2|RB), 복원(628–680) | `cpReset` 본문이 그대로(816–) — 다만 `state==MAPPED && !resetDone` 게이트 | 본문 같음; 게이트만 우회 |
| CP 리셋 | `radeon_do_cp_reset`: `WPTR := RPTR`(602–612) | `cpReset` 끝·`cpMap` 에 같은 줄 | 같음 (CSQ 꺼진 뒤 이 카드의 RPTR 은 0 — 실측 eae3072b) |
| 시작 | `radeon_do_cp_start`: idle 대기, `CSQ_CNTL = cp_mode`, 8 워드(ISYNC·PURGE DC·PURGE ZC·WAIT_UNTIL_IDLE) 커밋(571–598) | `cpStart` 가 같은 8 워드 + PACKET2 8, 뒤에 우리 대기·독·블록 검사 | 같음 |
| 마이크로코드·GART | 소프트 리셋은 `AIC` 를 안 건드리고 ME 를 다시 싣지 않는다 | — | 재적재 없음 |

## 2. 설계 (드라이버)

`cpFail(c, base)` 가 지금의 `cpLatch` 자리를 대신한다:
1. `cpLatch` 의 덤프 + kick(M3i 그대로; `latched` 는 아직 세우지 않는다).
2. kick 으로 rptr 이 움직였으면 kick 목표까지 `C_KICK_US` 더 기다리고 idle 대기 → 되면 `recoverKind=1`.
3. 아니면 참조 순서: `CSQ_CNTL=0` → `cpResetPulse`(cpReset 본문을 함수로 뽑음: pixcache flush·MCLK·펄스·복원) → `WPTR := RPTR`, `c->wptr` 맞춤 → `cpStartCore`(cpStart 의 스트림·CSQ on·대기·독·블록 검사) → 되면 `recoverKind=2`.
4. 둘 다 안 되면 지금처럼 `latched=1`, `CP_RC_LATCHED`.
5. 복구되면 `c->recovers++`, 그 제출은 **`CP_RC_RECOVERED`(8)** 로 돌려준다 — 라이브러리는 거절로 보고 소프트웨어로 대체, 다음 제출부터 정상.  첫 실패의 기록·덤프는 `rdnCpKept` 에 남는다(M3e 규칙: RAN·REFUSED 가 아닌 첫 rc).
- `resetDone`·`state` 는 복구 뒤 `RUNNING` 으로; STOP 은 평소대로.  `osrdn_cp_run` 의 `latched` 게이트는 그대로(복구 실패 때만 걸쇠).
- 회수: 매 실패 기록에 `recover=kind kicks= resets=` 를 찍는다.  덤프는 `kept` 재출력.

## 3. 호스트
- `world5.c`: `simResetHeals` — `RBBM_SOFT_RESET` 의 CP 비트 쓰기가 `simNeverAdvance` 를 지운다.  시험: (a) 안 움직이는 CP → 복구 kind 2 → 다음 SUBMIT 이 RAN; (b) 리셋으로도 안 나으면 걸쇠; (c) 복구 뒤 STOP 은 깨끗; (d) 복구의 리셋 펄스가 참조 모양(기존 추적 검사 재사용).
- `check_r5_src`: `cpFail` 의 순서(덤프 → kick → CSQ off → 펄스 → 포인터 → 시작), `CP_RC_RECOVERED` 가 RAN 으로 오인되지 않음(`OSRDNDisplay.m` 의 `live != CP_RC_RAN` 판정들), 변이 3.
- 판정기: `run_g1.sh` 가 `recover=` 를 집계.

## 4. codex 계획 검토 (복구 순서·리셋이 지우는 것·포인터)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| FreeBSD 리셋 ioctl 은 `radeon_do_engine_reset` 뿐 — 링 재초기화·마이크로코드 재적재·AIC 재기록 없음; `CP_START` 도 마찬가지 | `radeon_cp.c` 1798–1810, 571–598 열어 확인 | ✅ |
| 초기화·재개는 마이크로코드 적재·링 초기화 **뒤에** 엔진 리셋을 부른다 → 펄스가 ME RAM·링·GART 를 지운다면 자기모순 | `radeon_cp.c` 1481–1486(적재→링→리셋) 확인 | ✅ 행동 증거(하드웨어 보증은 아님 — 문서 없음) |
| Xorg 의 FIFO 시간 초과 복구도 `RBBM_SOFT_RESET` 직접 펄스 + 2D 상태 복원, CP 재시작; 링·GART 는 안 건드림 | `radeon_accel.c` 225–240 확인 | ✅ |
| Linux `r100_asic_reset` 은 CSQ=0 뒤 `RB_CNTL|RPTR_WR_ENA`, `RPTR_WR=0`, `WPTR=0`, `RB_CNTL` 복원으로 **포인터를 0 으로 강제** | `r100.c` 2552–2558(앞서 읽음), `radeon_reg.h` 3305·3309 | ✅ → **채택**(FreeBSD 의 `WPTR := RPTR` 대신): 이 카드는 CSQ 가 꺼지면 RPTR 이 0 으로 읽혀 읽은 값이 CP 의 내부 위치라는 보장이 없고, 0 강제는 MAP 게이트의 기대(rptr=wptr=0)와 맞는다 |
| CSQ=0 을 리셋 앞에 두는 것은 Linux 순서(보수적), FreeBSD·Xorg 는 바로 펄스 | `radeon_cp.c` 626 주석 "will stop the CP if it is running", `r100.c` 2552 | ✅ Linux 순서 채택 |

## 5. 확정 순서 (cpFail)
덤프+kick(M3i) → kick 이 움직였으면 kick 목표까지 대기·idle → kind 1.  아니면: `CSQ_CNTL=0` → `cpResetPulse`(cpReset 본문 그대로) →
`RB_CNTL|=RPTR_WR_ENA`, `RPTR_WR=0`, `WPTR=0`, `RB_CNTL=값` → `c->wptr=0` → `cpStartCore`(스트림·CSQ on·대기·독·블록) → RAN 이면 kind 2.
그 외 → 걸쇠.  복구된 제출은 `CP_RC_RECOVERED`(8).

## 6. 구현

- `osrdn_cp.m`: `cpLatchDump`(M3i 덤프+kick, `latched` 는 안 세움) / `cpLatch`(덤프 뒤 걸쇠) / **`cpFail`**(§5 순서); `cpReset` 의 리셋 펄스를 `cpResetPulse` 로 뽑아 둘이 공유; `cpStart` 를 게이트 + `cpStartCore` 로.  `cpSubmit`(R5 표지 — M3i 때 되읽기가 `cpStart` 에 잘못 들어갔던 것을 발견, 여기에도 넣음)과 `cpR6Submit` 의 여섯 실패 자리 → `cpFail`; `cpStart`·`cpStop` 의 실패는 걸쇠 그대로(되살릴 CP 가 없다).  `C_CP_RB_RPTR_WR`·`C_RB_RPTR_WR_ENA`(Linux 헤더).  연산마다 `recoverKind=0`, `recovers` 는 부팅 누적.
- `osrdn_cp.h`: `CP_RC_RECOVERED 8`, `recoverKind`·`recovers`.  `osrdn_modelog.m`: 걸쇠 줄에 `recover= recovers=`.
- `OSRDNDisplay.m`: 보관 재출력 조건을 "걸쇠가 거절한 RECORD **또는** 보관이 있는 채 RAN 한 RECORD"(`keptNow`)로 — 복구된 부팅에서도 덤프가 나온다; 그때 RECORD 자신의 기록은 찍지 않는다(4 KB).  `r7bSubmit` 은 변경 없음: RECOVERED 는 RAN·REFUSED 가 아니라 이미 "카드 실패" 로 기록·보관·`EIO` 처리된다.
- 규칙(정밀화, 완화 아님): SOFT_RESET·`cpMclkPut` 은 `cpResetPulse` 에서만; 펜스 순서는 `cpStartCore`; m3i 는 `cpLatchDump`, 되읽기 2(복구)+1(START); 새 `m3j-recover`(순서 12 단계·GART/마이크로코드/링 베이스 불가침·`cpFail` 6 곳) + 변이 4; m3e 는 `keptNow` 형태 + 변이 2.  모두 잡힘.
- 모형: `simResetHeals`(SOFT_RESET_CP 쓰기가 never-advance 를 푼다) + 시험: 안 낫는 걸쇠(kind 0), 낫는 복구(rc 8, kind 2, recovers 1, RUNNING, wptr 16, CSQ on, 덤프 있음) → 다음 SUBMIT RAN → STOP 깨끗 → RECORD 블록 이상 0.
- 모형 시험 배치 실수 하나: "낫는 복구" 블록을 "진짜 걸쇠 SUBMIT" 과 그 뒤 "RECORD 거절" 검사 사이에 끼워 넣어 RECORD 가 되살아난 CP 에서 실행됐다(드라이버 결함 아님).  순서를 바로잡음.  `sim_r5`·`sim_r6` PASS, 변이 전부 잡힘.

## 7. 부팅 A 가 준 것과 부팅 2 의 판정 (docs/G1_REMAINING.md 진행 기록 참조)

부팅 A 덤프: CP 는 페이지 경계(2048)에서 다음 페이지를 못 가져오고, 큐 비어 있음, 종 받음, kick 무효 → **kick 만으로는 안 낫는다**(`recoverKind` 1 은 기대하지 않는다).  부팅 2 에서 볼 것은 `recoverKind=2`(엔진 리셋+재시작으로 되살아남) 여부와 그 뒤 제출들이 정상인지.  `run_g1.sh` 가 `rc=8`(RECOVERED) 제출 수를 집계하고, RECORD 두 번으로 첫 실패의 기록(홀수)·FIFO(짝수)를 회수한다.

## 8. 설치 (부팅 2 용)

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** |
| 타깃 빌드 **`4a5edb03`** / runid 790386901, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | 첫 실행 FAIL(새 MMIO 호출자 넷: `_cpLatchDump`·`_cpFail`·`_cpResetPulse`·`_cpStartCore`) → 표에 이름으로 등록, 필수 호출 쌍 셋 추가 → **PASS**; 설치기는 그 사이 올바르게 거부 |
| 설치 `closed=yes fresh live` | **DONE** — 설치된 `Instance0.table`·`Default.table` 의 Display Mode = **1024×768 RGB:888/32** 확인 |

부팅 2: `RUNID=1790272700 BOOT=<nonce> BUILD=4a5edb03 R=2 bash build/g1/run_g1.sh` → `judge_teapot` r1·r2.  화면은 1024×768 로 뜨고, 창 시작은 0x400000 이 된다(python: 1024×768×4 + 가드 256 행).

## 9. 결과 (부팅 2) — **복구 동작 확인**
같은 제출(컬링 26 번째)이 같은 덤프로 멈췄고, kick 은 무효, **엔진 리셋+재시작(`recover=2`)으로 되살아났다**.  이후 ≈9 만 삼각형 정상, 두 바퀴 그림 PASS.  세부는 `docs/G1_REMAINING.md` 진행 기록.
멈춤의 **근본 원인은 여전히 모른다**(위치·내용 어느 하나로 안 갈림; CP 가 페이지 경계에서 다음 페치를 못 함).  참조도 이런 멈춤을 원인 추적 없이 리셋으로 다룬다 — 이 프로젝트도 그 선에서 G1 을 닫는다.
