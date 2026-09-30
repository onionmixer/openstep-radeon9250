# M3e — 내용인가, 쌓인 상태인가 (다음 부팅 한 번)

선행: `docs/M3D_PLAN.md` 7.  컬링 주전자가 두 부팅 연속 **같은 제출(148번째, 108 워드)**에서 CP 를 걸쇠에
걸었다.  붙잡은 스트림은 멀쩡하다 — 삼각형 4 개, 상태는 다른 제출과 같다(smooth 1, blend 0, tex 0,
depth 1, 64 × 64, 고정 워드 46 개가 표와 일치 — python 대조).  같은 크기·같은 머리의 제출이 같은 부팅에서
여러 번 성공했다.  **이 문서는 코딩 전에 쓴다.**

두 가설:
- **H-내용**: 이 네 삼각형 자체가 카드를 멈춘다(예: 특정 좌표·깊이 조합).
- **H-상태**: 그때까지 쌓인 무엇(링 위치·되감기·깊이 버퍼 내용·카드 내부 상태)이 원인이고 이 제출은 우연히 그 자리에 섰다.

## 1. 실험 A — 붙잡은 네 삼각형만, 새 CP 에서

새 도구 `test/osrdn-mesa-replay.c`(라이브러리 `libGL_radeon.a` 링크, GL 문맥 없음 — `osrdn-mesa-probe-test.c`
처럼 탐침만):

- 입력: 붙잡은 스트림의 워드 48–107(정점 60 워드)을 호스트 python 이 `r1-cull.out` 에서 뽑아 만든
  16진 파일.  상태 인자는 위에서 python 으로 판독한 값을 **도구 인자로 고정**한다.
- `osrdn_tri_batch_add` × 4 → `osrdn_tri_batch_flush`, 이것을 R 번.  첫 실패에서 멈추고
  `OSRDNMesaTriFailed()` 를 출력한다.
- 호스트 게이트: `sim_batch` 식 가짜 ioctl 로 도구를 돌려, 첫 제출이 붙잡은 108 워드와 **winStart
  자리를 빼고 워드 단위로 같음**을 python 으로 확인(winStart 자리 = 슬롯 COLOROFFSET·DEPTHOFFSET).

판정: A 가 R 번 안에 걸쇠 → H-내용.  R 번 모두 통과 → H-내용 기각(적어도 "이 워드만으로는 아니다").
**한계**: 깊이 버퍼 내용은 주전자 때와 다르다(ZPREP 패턴 뒤 한 번).  A 가 통과해도 "깊이 내용"은 남는다.

## 2. 실험 B — 걸쇠 기록을 잃지 않게 (드라이버)

두 부팅 모두 걸쇠의 전체 기록이 msgbuf(4 KB) 넘침으로 사라졌다(대기 줄 꼬리만 남음).  고침:

- `OSRDNDisplay.m` r7bSubmit: 카드 위 실패(`live` 가 RAN·REFUSED·BUSY·NOT_LIVE 가 아닌 것)가
  **처음** 났을 때 `rdnCpCopy` 를 정적 사본에 복사하고 제출 번호를 적어 둔다.  이후 덮지 않는다.
- CP op 경로: RECORD 가 걸쇠 때문에 거절된 뒤(하드웨어는 읽지 않는다 — `osrdn_cp.m:4196`, R5d 7 그대로),
  사본이 있으면 머리줄 하나(`RDN-R5 kept boot= subs=`)와 함께 사본을 `osrdn_cp_lines` 로 **다시 출력**.
  메모리만 읽는다.
- 실행이 끝나 조용해진 뒤 `r5op.sh record` 한 번 → 기록이 온전히 남는다.

## 3. 다음 부팅 순서

1. 드라이버(B) 설치는 이번 부팅에 해 두고 재부팅(설치 전 `nm -u` 검사).
2. 부팅 후 CP 올림 → ZPREP → **A**(R 번).
3. A 가 통과하면 `run_m3c.sh` 로 걸쇠 재현 → `r5op.sh record` 로 보관 기록 회수.
4. A 가 걸쇠면 3 은 하지 않는다(이미 걸렸다) → `r5op.sh record` 로 A 의 기록 회수.

## 4. codex 계획 검토 (B 한 질문: 보관 사본을 나중에 출력할 때 카드나 바뀐 메모리를 읽는가)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| `osrdn_cp_state` 에 `T *` 멤버가 없고, 주소 필드는 `block`·`alias`(`vm_address_t`) 둘 | 구조체 본문(`osrdn_cp.h` 422–574)에서 `*`·`vm_address_t`·`volatile` grep: `*` 는 주석뿐, `vm_address_t` 두 줄(425, 430) | ✅ |
| `osrdn_cp_lines` 는 `block`·`alias` 를 참조하지 않는다 | `osrdn_modelog.m` 에서 `->block`·`->alias` grep 0 건 | ✅ |
| `cpDigestLine` 이 따르는 포인터는 구조체 안(`&c->dDepth[k]`) | `osrdn_modelog.m` 272·369 열어 확인 | ✅ |

사본 크기: `plane` 4 × 256 워드 등으로 약 4.6 KB 이상(python) — 이미 있는 정적 `rdnCpCopy` 와 같은 크기, 스택이 아니라 정적.

거절된 RECORD 의 모양: `osrdn_cp_run` 은 `c->rc = CP_RC_REFUSED`(`osrdn_cp.m:4127`)로 시작하고 걸쇠면 `why = CP_WHY_LATCHED` 로 끝난다.  `osrdn_mode_cp` 는 RECORD 를 NOT_LIVE 검사에서 뺀다(`osrdn_mode.m:1487`).  그래서 조건 `live == CP_RC_REFUSED && rdnCpCopy.why == CP_WHY_LATCHED` 가 성립한다.

## 5. 구현·검증 (이 부팅, CP 걸쇠 상태에서)

- **A 도구** `test/osrdn-mesa-replay.c` → 타깃 `build/m3e/rdnreplay`(라이브러리 1790272200 링크).  입력 `build/m3e/latch148.words`(python 이 `r1-cull.out` 워드 48–107 을 뽑음; 워드 46·47 이 `c03c3500`·`000c0074` 임을 단언).
- **A 입력 증명**: 걸쇠 상태에서 한 번 실행 → 커널이 `rc=1 why=3`(LATCHED)로 거절, 카드는 안 읽음 → 라이브러리가 붙잡은 스트림을 주전자의 108 워드와 python 으로 대조: **108/108 같음, 차이 0**(winStart 포함, 같은 부팅이므로).  `build/m3e/verify-latched.out`.
- **B 드라이버**: `OSRDNDisplay.m` 에 `rdnCpKept`·`rdnCpKeptRc`·`rdnCpKeptSub`, 첫 카드 실패에서 복사, 걸쇠가 거절한 RECORD 에서 `RDN-R5 kept` 머리줄 + 사본 출력.  `check_r5_src` 규칙 `m3e-kept-latch` + 변이 4 종 모두 잡힘.
- 인용 이동: `OSRDNDisplay.m` 19 줄 증가, 편집 전 파일을 되살려 `reaim_diff.py` 로 34 키, 맨 `:N` 하나(M2F) 손으로.

## 6. 설치

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** (`check_cp` 자체시험: `kept` 줄은 걸쇠 뒤에만 나오므로 "좋은 로그" 형식 대조에서 뺐다 — 이유를 코드에 적음) |
| 타깃 빌드 `2d45136c` / runid 790280527, 미정의 심볼 21(전부 `/mach_kernel` 이 내보냄) | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — 이 부팅은 메모리의 옛 드라이버(5b8ff9c5) 그대로, 다음 부팅부터 새 것 |

## 7. 다음 부팅

`BOOT=<새 nonce> bash build/m3e/run_m3e.sh` (`R=200` 기본).  스크립트는 CAPS 가 `build=2d45136c` 이고
`cprunning=0` 일 때만 진행한다.  시드는 A `S+100000`, 컬링 `S+400000`, 일반 `S+450000` 에서 시작 — 서로 5 만 이상 떨어지고 2³² 미만(python).

## 8. 결과 (부팅 e70f0f3c, 실행 790281220)

`build/m3e/run-790281220/`.  드라이버 2d45136c, CP 새로 올림(START 뒤 wptr 16), ZPREP, 그리고 A.

- **A 는 26 번째 제출(round 25)에서 CP 를 걸쇠에 걸었다.**  앞의 25 번은 그려졌다.  T 는 돌지 않았다(설계대로).
- **보관 기록이 처음으로 온전히 남았다**(`RDN-R5 kept boot=e70f0f3c subs=26 rc=3` + 전체 기록):
  `stage=2`(그리기 제출), `ptrs rbefore=4016 rafter=4048 wafter=128`, `wait rptr=7350/1/100007/t7349`(100 ms 제한), 검증기는 108 워드 통과.
- **링 위치 재구성(python)**: case 171 한 번 = 접두 32(13 쌍 26 워드 → 16 올림) + 그리기 `round16(n + 12)` = 128.  START 뒤 16 + 25 × 160 = 4016 ✓.  26 번째: 접두 4016→4048(끝을 안 넘음) 성공, 그리기 128 워드는 남은 48 워드보다 커서 **4048–4095 를 PACKET2 48 개로 채우고 0 부터** 썼다(`osrdn_cp.m` `cpR6Submit`), 새 wptr 128 ✓.  **CP 는 4048 에서 한 워드도 나아가지 않았다** — 패딩의 첫 워드.
- **A 에서 링 끝을 넘은 것은 이것이 처음**(python: 26 번째 이전의 되감기 0 회).  즉 **첫 되감기가 걸쇠**.
- 대조: teapot 일반 실행의 복원 가능한 구간에서 패딩 752·800 워드의 되감기 5 회는 성공(두 부팅 로그를 합침, 공통 94 제출의 워드 수 일치; 잃은 구간은 두 부팅이 같아 148 번째의 위치는 복원 불가).  R6M(부팅 e5d55a94)에서 패딩 1248 성공.
- 우리 쪽 쓰기 검사: `cpPut` 은 인덱스를 링으로 감싼다, `CP_PACKET2` = `0x80000000`.  드라이버 쓰기 버그는 안 보인다.

**참고 구현(사용자 지시로 BSD 도 확인)**: FreeBSD drm `radeon_commit_ring`(`radeon_cp.c` 2094–)은 tail 을 **16 워드 정렬까지만** PACKET2 로 채우고, `OUT_RING` 은 `write &= mask` 로 **패킷을 링 끝 너머로 그대로 잇는다**.  Linux r100 도 같다(`align_mask = 16 - 1`, nop = PACKET2).  **링 끝까지 채우는 패딩은 우리 드라이버만의 방식**이고, 그것이 멈춘 자리와 겹친다.  링 설정값(`RB_CNTL` 의 크기·rptr 갱신·fetch 크기·NO_UPDATE)은 FreeBSD 와 같다.

**아직 모르는 것**: 왜 48 은 실패하고 752·800·1248 은 성공했는가.  한 부팅에 걸쇠 하나라 패딩 크기를 하나씩 재는 것은 비싸다.
