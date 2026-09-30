# M3d — 처음 실패한 전송의 스트림을 붙잡아 둔다 (라이브러리만)

선행: `docs/M3C_PLAN.md` 8.  컬링 실행이 결정적으로 CP 를 멈추고(읽기 포인터 대기 100 ms),
멈춘 제출은 **삼각형 2 개(108 워드)** 다.  그 워드가 어디에도 남지 않는다 — 보낸-삼각형 링은
성공한 뒤에만 기록한다.  **이 문서는 코딩 전에 쓴다.**

## 1. 무엇을

`OSRDNMesaTri.c` 의 두 실패 지점 — 단발 `osrdn_tri_send` 의 `triSubmit` 실패와 묶음
`osrdn_tri_batch_flush` 의 `triSubmit` 실패 — 에서, **이 프로세스에서 처음 실패한** 전송의
스트림 전체(`triDest[0..n)`, 최대 `OSRDN_BATCH_MAX_WORDS` = 2,016)를 정적 배열에 복사한다.
실패 사유·삼각형 수·정점 너비와 함께.  두 번째 실패부터는 덮지 않는다 — 걸쇠 뒤 거절이
첫 증거를 지우지 않게.

- 게터 `OSRDNMesaTriFailed()`, 스톡 링크용 `test/osrdn-mesa-nocount.c` 에 0 을 주는 짝.
- 주전자가 끝날 때 `RDNTEAPOT step=failed n= why= tris= vw=` 와 워드 8 개씩 출력.

## 2. 왜 그 순간 스트림이 아직 있나

`triDest` 는 복사 모드면 라이브러리 버퍼(`triCached`), 아니면 8 KB 묶음 창(`triWindow`)이다
(`OSRDNMesaTri.c:543-558`).  커널은 그것을 **읽어** 링에 올리고, 그리기는 다른 영역(색 0,
깊이 0x10000)에 한다.  실패 경로는 곧바로 `triBatchReset()` 으로 **계수만** 지운다.

## 3. 시험 (호스트)

`sim_batch.py` 의 거절 경우(가짜 카드가 flush 를 거절)에서: 붙잡은 `n` 이 스트림 길이와 같고,
워드가 그 스트림(`S`/`w` 줄)과 **워드 단위로** 같고, 두 번째 실패가 첫 것을 덮지 않는다.
변이: 붙잡기 삭제 / 두 번째가 덮음.

## 4. codex 계획 검토 (한 질문: 붙잡는 순간 `triDest` 가 커널이 받은 것과 같은가)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 독 모드는 `triSubmit` 첫머리에서 `triDest[0]` 을 덮는다 | `OSRDNMesaTri.c:871-872` 열어 확인 (codex 는 474 라 적음) | ⚖️ 사실, 줄번호 틀림. 붙잡은 것은 커널이 **받은** 것이므로 목적에 맞다 |
| 복사 모드에서 커널은 `copyin` 으로 자기 페이지에 복사할 뿐 사용자 버퍼에 쓰지 않는다 | `OSRDNDisplay.m:1206-1207` copyin(src=sb->words + k*4, dst=rdnR7bVirt; G4-4 K8 뒤 조각 단위), `OSRDNDisplay.m:1275` `const unsigned *w`; `bzero/memset/bcopy` grep 0 건 | ✅ |
| `copyin` 이 중간에 실패하면 커널 페이지와 우리 사본이 다르다 | `OSRDNDisplay.m:1206-1210` — 그 경우 검증·제출 없이 "copyin" 으로 거절 | ⚖️ 사실이나, 그때 카드는 아무것도 안 받았으므로 사본은 "보내려던 것" 으로 충분 |
| 창 모드 ioctl 은 메타데이터만 넘기고 `triDest` 를 건드리지 않는다 | `OSRDNMesaTri.c:992-994` | ✅ |
| `triBatchReset` 은 붙잡는 자리 뒤다 | 구현에서 `triKeepFailed` 를 `triBatchReset()` 앞에 둠 | ✅ |

추가: 붙잡을 때 `triCounts.lastWhy/lastAt/lastWord/lastStatus` 와 시드도 함께 남긴다 — 커널이 어느 워드에서 멈췄는지(`at`)가 곧 분석의 출발점이다.

## 5. 구현·게이트

- `OSRDNMesaTri.h` `osrdn_tri_failed`, `OSRDN_TRI_FAIL_WORDS 2016`(.c 에서 `OSRDN_BATCH_MAX_WORDS` 와 같지 않으면 빌드 중단).
- `OSRDNMesaTri.c` `triKeepFailed` — 단발·묶음 두 실패 자리, 첫 실패만.
- `test/osrdn-mesa-nocount.c` 짝, `test/osrdn-mesa-teapot.c` `sayFailed` (`%lx`, 폭 없음 — 타깃 cc 가 무시).
- `sim_batch.py` 경우 D: 두 번 거절, 붙잡은 기록 `(n failures reason tris vw batch)` = `(첫 스트림 길이, 2, 6, 2, 5, 1)`, 워드는 첫 스트림과 워드 단위로 같다.  변이 3 종(안 붙잡음 / 두 번째가 덮음 / 한 워드 짧음) 모두 잡힘.
- 인용 이동: 이 칸의 삽입으로 `OSRDNMesaTri.c` 가 40 줄, `.h` 가 29 줄 밀렸다.  편집 전 파일을 삽입 블록 제거로 되살려 `reaim_diff.py` 로 16 키를 옮겼고, 맨 `:N` 인용 4 개와 헤더 키 하나는 손으로 옮겼다(각 줄 열어 확인).

## 6. 타깃 빌드와 재현

- 라이브러리 `build/m1b/1790272200` (RDNMESA PASS), 주전자 `build/m3a/1790272300` (BUILD PASS).  `nm`: accel 에 `_OSRDNMesaTriFailed`·`_triKeepFailed`, stock 에 `_OSRDNMesaTriFailed`·`_noneFailed`.  드라이버는 그대로(5b8ff9c5 / 790267856).
- 이 부팅(e630f871)은 CP 가 걸쇠에 걸려 있으므로 재현은 **재부팅 뒤**:
  `RUNID=1790272300 BOOT=<새 nonce> bash build/m3a/run_m3c.sh` — 걸쇠가 재현되면 그 실행의 `.out` 에 `RDNTEAPOT step=failed` 와 `failed-w` 줄이 남는다.  해석(워드 분해)은 호스트에서 python 으로.

## 7. 재현 결과 (부팅 0238ab06, 실행 790275431)

`build/m3a/1790272300/m3c-790275431/`.  일반 실행 6,400 삼각형 이상 없음.  컬링 실행에서 **지난 부팅과 같은 자리**: submitted 2,993, culled 2,909, replayed 498, REFUSED 9.
커널 기록의 첫 실패는 `subs=148 words=108 rc=3`(LATCHED) — 지난 부팅(e630f871)과 **같은 제출 번호, 같은 크기**.  결정적이다.

붙잡은 첫 실패 스트림(`r1-cull.out` 의 `step=failed`, python 분해):

- `n=108 tris=4 vw=5 batch=1 why=0 at=108 status=5` — 검증기는 108 워드 전부를 받았다(`why=0 at=108`).  거절은 검증이 아니라 실행(CP 걸쇠)에서 났다.
- 워드 46 `c03c3500`: 그리기 패킷, 개수 필드 + 1 = 61 = 1 + 12 × 5 ✓, 워드 47 `000c0074`: vf 0x74, 정점 12.
- 삼각형 4 개, 모두 64 × 64 안(x 23.4–25.1, y 30.8–31.9), z 0.450–0.454, w 1.0, 색 ff0a0a0a, 부호 면적 +0.18 / +0.18 / +0.27 / +0.27(감김이 모두 같고 퇴화 없음).
- **같은 크기·같은 머리(`c03c3500`)의 108 워드 제출은 이 부팅에서 여러 번 성공했다**(subs 3, 6, 9, 12, … 114, 137).  스트림의 **모양**은 원인이 아니다.

잃은 것: 제출 138–147 과 148 의 전체 기록 앞부분이 다시 msgbuf(4 KB) 넘침으로 사라졌다.  남은 것은 대기 줄 꼬리 `…/1/100014/t6697` — 읽기 포인터 대기가 100 ms 제한에서 끊겼다(지난 부팅 100,008 us 와 같은 모양).

**아직 모르는 것:** 원인이 이 네 삼각형의 **내용**인가, 그때까지 쌓인 **상태**(링 위치 등)인가.  둘을 가르는 실험은 CP 가 새로 떠 있어야 하므로 다음 부팅에서 한다.
