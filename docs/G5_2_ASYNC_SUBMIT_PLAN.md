# G5-2 — 제출을 수락으로: 카드 시간을 CPU 와 겹친다 (커널 + 라이브러리, 재부팅 1회)

G5-0 §8-2 가 남긴 마지막 큰 덩어리다: 제출마다 CPU 가 **카드가 스트림을 소비·그리는 동안 동기로 돈다**(R1 976 us × 8.6 = 8.4 ms/프레임, R2 450 us × 25 = 11.2 ms) — 그리고 그 앞뒤에 R6 시절의 검증 장치가 제출당 290 us(2.5 / 7.7 ms) 붙어 있다.  이 칸은 **제출 ioctl 의 계약을 "완료"에서 "수락"으로** 바꾸고, 완료 대기를 **다음 링 접촉**으로 미룬다.

같은 주제의 이전 계획이 둘 있다.  둘 다 열어 읽었다:

- `docs/M1W_PLAN.md` — 이 드라이버에서 같은 시도.  **§7 에서 보류**: codex 가 센 실패 모드 8 건(전초의 idle 대기, RPTR==WPTR 의 모호성, 픽스캐시 플러시의 성격, 성공 후 실패, 마지막 제출의 hang, 예약 비트, 펜스 순서, RPTR 전진 ≠ 엔진 idle).  **§2 는 이 칸이 답해야 할 목록이다.**  당시 배치 상한은 2,016 워드였고 카드 대기는 삼각형당 0.69 us 였다; 지금은 4,068 워드·제출당 ~1 ms 다.
- `../openstep-matrox-remade/docs/W5_ASYNC_SUBMIT_DESIGN.md` — Matrox 에서 **짓지 않기로** 한 설계.  §8 "완료를 알아차릴 주체가 없다" 가 핵심이었고, 답은 셋 중 "다른 엔진 사용자가 진입할 때 대신 폴링한다" 였다.  이 드라이버는 그 답을 **이미 구조로 갖고 있다**(§1-3).

**넣지 않는 것**: 인터럽트, 타이머, 링 구조·크기 변경(4,096 워드 그대로), 2차 큐(CSQ 간접), 프리픽스·꼬리의 레지스터 프로그래밍 변경(스트림은 오늘과 워드 단위로 같다), 참고에 없는 대기 조건.

## 0. 금지 목록 대조 — 설계 전에

| 어디 | 규칙 | 이 설계 |
|---|---|---|
| `docs/R7_PLAN.md` 4 규칙 5 | WAIT_UNTIL 은 클라이언트가 못 보낸다(예약 4 레지스터) | 그대로.  프리픽스 앞 WAIT_UNTIL 은 여전히 드라이버 것 |
| `docs/M3F_PLAN.md` | 링 끝 채우기 금지, FreeBSD 처럼 감는다 | `cpPut` 의 마스크 그대로(`osrdn_cp.m:2348-2356`) |
| `docs/G4_3_*` K1 | W_RPTR 대기는 진행이 있으면 시계를 다시 시작(참조 `radeon_wait_ring`) | **자리 대기도 같은 규칙**(§2-2) |
| [[failure-latch-must-be-terminal]] | 실패 걸쇠는 종결적 | 자리 대기·retire 의 타임아웃은 `cpFail`(M3j 복구, 실패 시 걸쇠) — 새 걸쇠 없음 |
| [[runner-plan-must-equal-judge-procedure]] | 러너 = 판정 절차, CP 는 부팅당 한 주기 | §6 |
| [[driver-change-review-order]] | 검토 → 빌드 → **설치 전 `nm -u`** → 재부팅 요청 | §5 |
| `docs/M1L_PLAN.md` 4, `docs/M1M_PLAN.md` 4 "제출을 비동기로 바꾸지 않는다" | 그때는 병목이 측정되지 않았다 / 카드 대기가 0 이었다 | G5-0 §8-2 가 숫자로 만들었다: **8.4 / 11.2 ms** |

## 1. 확인된 사실 (전부 열어서)

### 1-1. 한 제출이 지금 하는 일 (`cpZclear` 의 `CP_R7_CASE`)

| 순서 | 무엇 | 어디 | 제출당 us (R1 / R2, G5-0 tstage) |
|---|---|---|---|
| 게이트 | `cpIdleGate`(FIFO 빔·RBBM 비활성), **`rptr == wptr`**, poison, SURFACE_CNTL | `osrdn_cp.m:3199-3208` | gates 7 |
| 전초 | `cpWait(W_FIFO)` → 스크래치 센티넬 둘 → **`cpWait(W_IDLE)`** → 되읽기 | `osrdn_cp.m:3217-3226` | pre 20 |
| 1 단계 | 프리픽스 32 워드 → `cpR6Submit`(패딩·펜스·도어벨·**W_RPTR·W_IDLE**) | `osrdn_cp.m:3231-3255` | s1ring 37 |
| 1 단계 검증 | SCRATCH_REG0 + 13 레지스터 되읽기 | `osrdn_cp.m:3259-3277` | s1read 13 |
| 2 단계 | WAIT_UNTIL(2) + 클라이언트 워드 + 꼬리 10 → `cpR6Submit` | `osrdn_cp.m:3355-3358`, `:3494-3498`, `:3506` | s2asm 10, **s2ring 1121 / 612** |
| 2 단계 검증 | 픽스캐시 플러시(DC_FLUSH_ALL + `cpWait(W_DC)`) + 스크래치 되읽기 | `osrdn_cp.m:3511-3515` | flush 12 |
| 3 단계·꼬리 | quiet 면 2 읽기, poison, **`cpCheckBlock`(링 4,096 워드를 그림자와 대조)** | `osrdn_cp.m:3539`, `:3679` | tail 45 |
| (두 `cpR6Submit` 의 합) | put / fence(WBINVD) / wait | `osrdn_cp.m:2380`, `:2398`, `:2417-2419` | put 59, fence 8, wait 79 / 93 |

- **s2ring 1121 − (put+fence+wait) ≈ 976 us 가 카드 시간**이다.  `wait` 가 그것을 안 담는 이유: W_RPTR 대기는 rptr 이 움직일 때마다 시계를 **다시 시작**한다(`osrdn_cp.m:245-250`, 참조 `radeon_cp.c:1918` `head != last_head → i = 0`).
- 검증 장치 중 **생산 경로에서 없어질 수 있는 것**: pre 20 + s1ring 37 + s1read 13 + flush 12 + tail 45 = **127 us/제출**(python).  gates·s2asm·put·fence 는 남는다.
- 클라이언트의 `drawn` 은 **도어벨 전에** 정해진다: `cpR7Verify` 가 스테이징된 워드를 판정하고(`osrdn_cp.m:3154-3157`), `r7bRun` 은 `live == RAN && r7Why == OK` 를 `drawn` 으로 돌려준다(`OSRDNDisplay.m:1329`).  즉 "그렸다" 가 아니라 이미 "검증되어 링에 들어갔다" 의 뜻이고, 이 칸은 그 뜻을 **바꾸지 않는다** — 뒤의 대기만 뺀다.

### 1-2. 다음 접촉이 어디서 기다리나 — 링은 FIFO 고, 모든 접촉이 같은 링을 쓴다

| 접촉 | 어떻게 링에 닿나 | 앞 제출과의 순서 |
|---|---|---|
| 다음 SUBMIT | `cpR6Submit` → `cpPut` 이 `wptr` 부터 쓴다 | 링의 뒤 |
| PRESENT | `cpPresent` 가 13 워드를 **같은 `cpR6Submit`** 으로(`osrdn_cp.m:3932-3943`), 첫 워드가 `WAIT_UNTIL 3D_IDLECLEAN|HOST_IDLECLEAN`(`osrdn_cp.m:1450`) | 카드가 **자기 안에서** 앞 그리기 완료·캐시 정리를 기다린 뒤 블릿한다.  참조의 블릿 앞 WAIT 와 같다(`radeon_drv.h` 1914-1922) |
| CLEAR | 같은 `cpR6Submit`, 첫 워드 같은 WAIT | 같음 |
| STOP·모드 복귀 | `osrdn_cp_quiesce` → `cpStop` 이 **W_RPTR(wptr) → W_IDLE → CSQ off** 를 기다린다(`osrdn_cp.m:4089-4097`) | 복귀 전에 링이 빈다 — **이미 retire 다** |
| 문자 장치 마지막 close | `rdnDevClose`(`OSRDNDisplay.m:220-236`): 걸쇠만 푼다, 대기 없음 | §2-5 에서 retire 를 붙인다 |

`cpR6Submit` 은 오늘 **자리 검사가 없다**(진입 게이트 `rptr == wptr` 이 "링이 비었다" 를 보증하므로).  §2-2 가 그 자리에 자리 대기를 넣는다 — 그러면 present/clear/다른 op 는 **코드 변경 없이** 앞 제출 뒤에 줄을 선다.

### 1-3. Matrox W5 §8 의 "완료 주체" 문제가 여기서는 어떻게 다른가

- W5 는 `stormBusy` 가 **ioctl 사이에도 잡혀 있어** present·2D·모드 변경이 다음 3D 제출까지 막히는 것이 문제였다.  이 드라이버의 클레임(`modeClaim`/`modeFinish`, `osrdn_mode.m:1449-1476`)은 **한 ioctl 안에서만** 잡힌다.  카드가 그리는 동안 클레임은 풀려 있고, 다음 사용자가 클레임을 잡고 **링에 줄을 선다**(§1-2).  "완료 주체" 는 **다음 링 접촉의 자리 대기**다 — present 는 프레임마다 오고, 게임이 끝나면 close·모드 복귀가 온다.
- W5 §5 의 "유저랜드가 VRAM 을 직접 매핑해 막을 수 없는 drain" — 이 라이브러리도 창을 매핑한다(`OSRDNMesaSurface.c:126`).  CPU 가 그 창을 **읽거나 쓰는 자리는 셋뿐**이고 전부 라이브러리 안이다(§1-4).  게임은 창에 닿지 않는다.

### 1-4. 유저랜드가 카드의 목적지·소스에 닿는 자리 (전수 — **codex Q2 로 정정**, §9)

**표면 창 자체가 OSMesa 의 그리기 버퍼다**: `osrdn_surf_take` 가 `surfBase` 를 Mesa 에 돌려준다(`OSRDNMesaSurface.c:228`).  그래서 Mesa 의 **소프트웨어 래스터 전부**(위임 삼각형·점·선·소프트웨어 clear·ReadPixels·CopyPixels·DrawPixels·Bitmap)가 CPU 로 창을 읽고 쓴다.  훅은 그 앞마다 `osrdnFlushFor(이유)` 를 부른다 — 그러나 `osrdnFlushFor` 는 **배치가 비었으면 아무것도 안 한다**(`OSRDNMesaHook.c:539-545`).  비동기 뒤에는 배치가 비어도 앞 제출이 카드에서 돌고 있을 수 있다.  `grep osrdn_surf_window` 만으로는 이것이 안 보인다([[absence-enumeration-must-follow-calls]]).

| 자리 | 읽기/쓰기 | 왜 retire 가 필요한가 |
|---|---|---|
| 텍스처 업로드 `OSRDNMesaTex.c:141`(`osrdn_tex_upload_level`), `:225`(`osrdn_tex_upload`, 별도 진입점 `:190`) | **쓰기** | 훅이 업로드 전에 flush 한다(`OSRDNMesaHook.c:361`, F8 "열린 배치가 이 블록을 읽을 수 있다") — 비동기 뒤 flush 는 "제출" 이지 "완료" 가 아니다.  카드가 아직 읽고 있는 텍셀을 덮을 수 있다 |
| 표면 미러 `OSRDNMesaSurface.c:283` | **읽기** | glFinish(present 아닐 때)·`OpenStepMesaAccelMirror`·leave 가 부른다(`OSRDNMesaHook.c:1424`, `:1987`).  그리기 끝나기 전에 읽으면 반쪽 그림 |
| 깊이 되읽기 `OSRDNMesaDepth.c:49-61` | 읽기 | 시험 도구만(`osrdn_depth_get`) |
| **Mesa 소프트웨어 경로** — flush 이유 DELEGATE `OSRDNMesaHook.c:1110`, POINTS `:1465`, LINES `:1479`, CLEAR `:665`(카드 clear 가 거절되면 저장된 소프트웨어 clear), READPIX `:1575`, COPYPIX `:1592`, DRAWPIX `:1603`, BITMAP `:1613`, LEAVE `:1659` | 읽기·쓰기 | flush 뒤 곧바로 소프트웨어가 창에 닿는다.  배치가 비어도 retire 가 필요하다 |

그 밖에 `osrdn_surf_release`(`OSRDNMesaSurface.c:341`) 는 창을 잊을 뿐 읽지 않는다 — 그러나 그 뒤 프로세스가 끝나면 마지막 제출이 링에 남으므로 §2-5 의 종료 retire 가 맡는다.

### 1-5. 참조의 자리 규칙 (FreeBSD `radeon_cp.c:1901-1926`, `radeon_drv.h:2055-2066`)

    space = head - tail;  if (space <= 0) space += size;   -- 워드 단위로 (rptr - wptr) mod 4096
    if (space > n) 자리 있음                                 -- 같음(==) 은 자리 아님: 빈 링과 꽉 찬 링을 가른다
    BEGIN_RING: n 을 16 정렬까지 늘려 묻는다(_align_nr)      -- 우리 cpR6Submit 의 패딩과 같은 뜻
    head 가 움직이면 i = 0                                   -- 진행이 있으면 시계 재시작

`rptr == wptr` 은 빈 링이다(`space = size`).  꽉 찬 링은 `wptr = rptr - 1` 까지만 허용된다.  M1w §7 두 번째 항목의 답이다.

### 1-6. 링 예산 (python)

| | 워드 |
|---|---|
| 프리픽스(`osrdn_cp.m:3231-3253`, R7 케이스) | 32 |
| WAIT_UNTIL | 2 |
| 꼬리(`osrdn_cp.m:3494-3498`) | 10 |
| 클라이언트 최대 N | 4,036 → 합 4,080 = 16 의 배수.  `free ≥ 4080` 은 앞 제출의 미인출 워드가 **15 개 이하**일 때 참(codex: `wptr=0, rptr=4081` 이면 free 4,080 — 빈 링만이 아니다, python 확인) |
| 오늘의 상한 4,068 | 합 4,112 > 4,095 — **한 링 쓰기로는 못 넣는다** |

한 제출을 **한 번의 링 쓰기**로 합치면 클라이언트 상한이 4,036 으로 내려간다.  **구현은 합치지 않았다**(§10-1): 프리픽스와 본문을 오늘처럼 두 번 쓰되 사이의 대기만 뺀다 — 카드가 보는 워드가 오늘과 패딩까지 같고, 클라이언트 상한 4,068 과 라이브러리 배치 상한이 그대로다.  값은 제출당 펜스·도어벨 한 번(수 us).  4,096 링에 4,080 짜리 본문은 **한 개만** 들어간다 — 그래서 겹침은 **다음 제출의 자리 대기가 이번 제출의 도어벨보다 늦게 오는 만큼**이다(M1w §5-1 의 "곱게 퇴화" 와 같은 산수).

## 2. 설계

### 2-1. 생산 제출 op `CP_OP_ASUBMIT`(22) 과 ioctl `SUBMIT3`(verb 6)

**구현(§10)**: `cpZclear` 는 건드리지 않고 별도 함수 `cpAsubmit` 을 두었다.  프리픽스·드라이버 WAIT_UNTIL·스트림·꼬리는 `cpZclear` 의 클라이언트 경우와 **문장 단위로 같고**, `check_r5_src` 의 `g52-async` 규칙이 두 함수의 `w[n++] = ...;` 열을 대조한다(한 줄 빠뜨리는 변이가 잡힌다).  `cpZclear` 를 쪼개 공유하는 길은 버렸다: 그 텍스트에 기대는 규칙·인용·오라클이 여섯 곳 넘게 있어 쪼개는 쪽의 위험이 더 컸다.

`cpAsubmit` 의 순서:

    게이트: state RUNNING, failed 아님, 3D 키, seed 규칙(같음); 공통 게이트(latched 등)는 osrdn_cp_run 이 그대로
           cpIdleGate 와 rptr == wptr 는 묻지 않는다 — 카드가 그리는 중인 것이 정상이다
           poison 카나리아·SURFACE_CNTL 은 그대로(MMIO 읽기 둘, 엔진 상태 무관 — M1w §3)
    검증:  cpR7Verify (cpZclear 와 같은 호출, 같은 허용목록)
    쓰기1: 프리픽스 32 워드 → noWait = 1 → cpR6Submit → noWait = 0 → inflight = 1
    쓰기2: WAIT_UNTIL + 클라이언트 N(≤ 4,068) + 꼬리 10 → 같은 괄호 → asubmits++
           대기 없음, 되읽기 없음, 센티넬 없음, 픽스캐시 플러시 없음, cpCheckBlock 없음

`cpR6Submit` 은 두 가지만 달라졌다: 첫머리에 자리 대기(§2-2), 그리고 WPTR 되읽기 확인 **뒤·대기 앞**에 `if (c->noWait) return CP_RC_RAN;`.  동기 경로가 대기를 끝내면 `inflight = 0`.  `noWait` 는 `osrdn_cp_run` 진입마다 0 으로 돌아간다.

`drawn` = "검증되어 링에 들어갔고 도어벨이 먹었다"(WPTR 되읽기 일치).  오늘의 뜻과 같다(§1-1).

ioctl: `OSRDN_R7B_IOC_SUBMIT3` 은 `osrdn_r7b_submit2` 와 **같은 블록**, verb 번호만 6.  `r7bSubmit2:op:` 가 스테이징을 그대로 타고 `r7bRun` 에 op 를 넘긴다(SUBMIT2 → `CP_OP_ZCLEAR`, SUBMIT3 → `CP_OP_ASUBMIT`).  로그 규칙(M2g·M3c: quiet 성공은 침묵, 실패는 말한다)은 op 와 무관하게 같다.  **버전(`OSRDN_R7B_VERSION` 2)과 CAPS 는 그대로** — 올리면 v2 로 빌드된 모든 바이너리가 거절된다.  옛 커널은 새 verb 에 ENOTTY 를 돌려주므로 라이브러리는 시작할 때 RETIRE 를 한 번 물어 지원 여부를 안다.

### 2-2. 자리 대기 `cpWaitSpace(c, base, len, w)`

    free = (rptr - c->wptr - 1) & C_RPTR_MASK      -- 빈 링: 4,095.  wptr == rptr - 1: 0
    조건  free >= len                                -- 참조의 space > n 과 동치(python 으로 대조, §4)
    시계  W_RPTR 과 같은 규칙: rptr 이 움직이면 t0 재시작, C_RPTR_US 로 타임아웃
    실패  cpFail (M3j: 재도어벨 → 리셋·재시작 → 그래도 안 되면 걸쇠).  이 제출은 거절, 라이브러리가 소프트웨어로 그린다
    kick  cpLatchDump 의 M3i kick 은 wptr 에 PACKET2 16 개를 **자리 확인 없이** 쓴다(`osrdn_cp.m:430-458`, cpLatch·cpFail 둘 다 부른다).
          free < 16 이면 미인출 워드를 덮거나 WPTR 이 RPTR 에 닿아 꽉 찬 링이 빈 링으로 보인다(codex, §9).
          → kick 앞에 같은 free 식을 두고 free < 16 이면 kick 을 건너뛴다(kickMoved = 0 → cpFail 은 리셋 경로로).
          오늘도 4,080 워드 제출 직후 free = 15 라 같은 구멍이 있다 — 이 칸에서 함께 막는다

`cpWait` 에 종류를 더하지 않고 **별도 함수**로 둔다: `cpWait` 는 `c` 를 모르고, `need` 하나로는 `wptr` 과 `len` 을 같이 못 나른다.  진행-재시작 루프는 `cpWait` 의 W_RPTR 가지와 같은 모양이며 `check_r5_src` 규칙으로 두 루프의 재시작 문장이 같음을 박는다.

### 2-3. `CP_OP_RETIRE`(23) 과 ioctl `RETIRE`(verb 7)

    RUNNING 이면: cpWait(W_RPTR, c->wptr) → cpWaitRetry(W_IDLE) → 픽스캐시 플러시(DC_FLUSH_ALL + W_DC)
    → c->inflight = 0, CP_RC_RAN.   타임아웃은 cpFail.
    RUNNING 아니면 거절(CP_WHY_STATE 류의 기존 사유).

픽스캐시 플러시는 참조에서 **idle 로 가는 길의 일부**다(`radeon_do_wait_for_idle` → `radeon_do_pixcache_flush`, `radeon_cp.c:378-392`).  M1w §7 세 번째 항목(진단인가 coherency 인가)의 답: **CPU 가 창을 읽기 전의 idle 경로에 속한다** → retire 에 둔다, 제출마다 하지 않는다.  present 는 카드 안 `3D_IDLECLEAN` 이 같은 일을 한다(§1-2).

블록(`osrdn_r7b_retire`, 32 B): `{magic "RTR0", version 1, status, waited(커널에 비행 중이 있었나), us, asubmits, lost, rc}`.  `lost` 는 수락된 작업을 버린 **사건** 수다(표지가 하나라 둘을 함께 잃어도 1, §10-2 codex).

### 2-4. 라이브러리

| 어디 | 무엇 |
|---|---|
| `OSRDNMesaTri.c` | `osrdn_tri_async()`: knob `RDNMesaSync=1` 이 없고 copyin 경로이며 RETIRE 가 성공하면 1(한 번만 묻는다).  `triSubmit`: async 면 `SUBMIT3`, 아니면 `SUBMIT2`.  배치 상한 그대로 |
| `OSRDNMesaTri.c` 비행 표지 | `triInflight`: SUBMIT3 이 `drawn` 으로 돌아오면 1, retire 성공 시 0.  **`osrdn_tri_retire_if_inflight()`** 는 0 이면 ioctl 없이 돌아간다 — CPU 가 창에 닿는 자리가 많아도(§1-4) 비용은 "카드 → CPU 전환 한 번에 ioctl 한 번" |
| `OSRDNMesaHook.c` `osrdnFlushFor` | 배치 flush **뒤, 배치가 비었어도** 이유가 CPU 접촉(DELEGATE·POINTS·LINES·CLEAR·READPIX·COPYPIX·DRAWPIX·BITMAP·LEAVE·TEXUPLOAD·SURFACE·RELEASE)이면 `retire_if_inflight`.  BRACKET·STATE·CTX·REFUSED·ALONE·GLFLUSH·OUTSIDE·TEXDROP 은 안 부른다(창에 안 닿는다; TEXDROP 은 할당 메타데이터만 — codex 도 반증 못 함).  이유 목록은 표 하나로 두고 `check_hook` 규칙이 전 이유의 분류를 요구한다 |
| `OSRDNMesaTex.c` `osrdn_tex_upload_level` **과 `osrdn_tex_upload`** | 창에 쓰기 **직전** `retire_if_inflight`(훅 경로 밖 호출자도 덮도록 두 함수 안에) |
| `OSRDNMesaSurface.c` `osrdn_surf_mirror` | 복사 **직전** retire (한 자리: glFinish·Mirror·leave 셋을 다 덮는다) |
| `OSRDNMesaDepth.c` `osrdn_depth_get` | 읽기 전 retire |
| `PresentMode(0)`·`osrdn_surf_release` | 따로 두지 않았다: PresentMode(0) 뒤에 창을 읽는 것은 미러뿐이고 미러가 retire 한다; release 는 훅의 RELEASE flush 이유가 retire 한다 |
| 계수 | `async`, `asubmits`, `retires`, `retiresSkipped`(비행 표지 0 — ioctl 없음), `retireFailed`, `retireUs`, **`lateLatch`**(수락된 제출이 있을 때 다음 제출이 실패), `lost`(커널 값) — 종료 보고의 **RDN-A** 줄 |

비행 표지가 0 이면 ioctl 이 없다(`retiresSkipped`); 1 이면 ioctl 한 번이고 카드가 이미 놀고 있으면 커널은 MMIO 읽기 몇 번으로 끝난다.  R1 에서 업로드 124/300 프레임 = 프레임당 0.4 회, 미러는 present 모드에서 0 회.

### 2-5. 커널의 종료 backstop

`rdnDevClose`(마지막 close) 가 커널의 비행 표지가 1 일 때만 `r7bCloseRetire` → `r7bRetire` 를 부른다(close 는 C 함수라 인스턴스 변수 `rdnCp` 를 메서드로 읽는다); `RDN-R4 close` 줄에 `retires=` 가 붙었다 — 라이브러리가 retire 없이 죽어도(시그널) 링에 남은 제출을 커널이 기다린다.  M1w §7 다섯 번째 항목의 답.  모드 복귀는 이미 `cpStop` 으로 기다린다(§1-2).

### 2-6. 오류 귀속 — 성공 뒤의 실패 (M1w §7 네 번째)

| 실패가 드러나는 자리 | 누가 무엇을 받나 | 그 사이 제출된 삼각형 |
|---|---|---|
| 다음 SUBMIT3 의 자리 대기 타임아웃 → `cpFail` | 그 제출이 `REFUSED`/`RECOVERED` → 라이브러리가 **그 제출을** 소프트웨어로 그린다(오늘의 재생 경로 `OSRDNMesaHook.c:447-499`) | 앞 제출은 **잃는다**(색인이 죽었다, `lostAtFlush` 와 같은 이유).  `lateLatch++` |
| PRESENT 의 W_IDLE 타임아웃 | E_LATCH → SDL 이 다음 프레임 재시도(오늘과 같음) | 같음 |
| RETIRE 타임아웃 | `retireFailed++`, 호출자는 되읽기를 건너뛴다(미러: 복사 안 함, 업로드: 쓰지 않고 실패 반환 → 훅이 텍스처를 소프트웨어로) | 같음 |

카드가 멈추면 어차피 그 부팅의 가속은 끝이다(`cpFail` 이 복구를 시도하고, 못 하면 걸쇠 → 전부 소프트웨어).  잃는 것은 **한 배치**이고 계수된다.

### 2-7. M1w §7 판정표에 대한 답 (한 줄씩)

| M1w 의 실패 모드 | 이 설계 |
|---|---|
| 전초 idle 대기가 겹침을 0 으로 | 생산 op 에 전초(센티넬·W_FIFO·W_IDLE)가 **없다** |
| RPTR == WPTR 모호 | `free = (rptr − wptr − 1) & mask`, 참조의 `space > n` (§1-5, python 대조) |
| 픽스캐시 플러시의 성격 | idle 경로 → retire 에만 (§2-3) |
| 성공 후 실패의 소급 불가 | 계약을 "수락" 으로 명시, `lateLatch` 계수, 한 배치 손실 (§2-6) |
| 마지막 제출의 hang | close backstop + 모드 복귀의 `cpStop` + 라이브러리 release/atexit retire (§2-4, §2-5) |
| 예약 비트를 구형 클라이언트가 켤 위험 | 비트가 아니라 **새 verb + caps version 3 정확 일치** |
| 펜스 → 도어벨 순서 | `cpR6Push` 가 `cpR6Submit` 의 순서를 그대로 잘라 낸 것(`osrdn_cp.m:2380-2411`) |
| RPTR 전진 ≠ 엔진 idle | 자리 대기는 링만 본다; 엔진 hang 은 **프레임마다 오는 present 의 W_IDLE(retry)** 과 retire 가 잡는다 |

## 3. 0 단계 — 카드 시간의 정체: fetch 인가 draw 인가 (재부팅 없음, 오프스크린)

`build/g52/run_g52_0.sh`: 같은 길이(4,057 워드) 두 스트림을 rdnreplay 로 20 회씩, 커널 계기 켜고 tdump.

- `real` — 기록된 월드 스트림 `build/g410/trace-g411-last.bin[:4057]`(`trace-g411.txt` seq 9af: 187 삼각형, 7 draw, 레지스터 패킷 58)
- `synth` — 같은 프롤로그(60 워드) × 67 + 레지스터 쌍 7 + **삼각형 1 개**(검증기의 EMPTY 거절을 피하는 최소 draw).  CP 는 같은 16 KB 를 가져오고 엔진은 거의 안 그린다

    card(synth) ≈ fetch,   card(real) − card(synth) ≈ 187 삼각형의 그리기

읽는 법: 이 값은 설계를 바꾸지 않는다 — 어느 쪽이든 겹침은 §1-6 의 산수다.  바꾸는 것은 **기대치**다: fetch 가 크면 rptr 이 그리기보다 앞서 가고 present 의 W_IDLE 잔여가 크다; draw 가 크면 자리 대기가 곧 완료 대기라 잔여가 작다.  §6 의 PRESENT 상한을 이 값으로 정한다.  두 스트림은 python 이 만들고 걸었다(`build/g52/mkstreams.py`).

### 3-1. 결과 (2026-09-29, 부팅 12f30d88, 드라이버 2d3234bf, `build/g52/run0.log`)

| 스트림 | 제출 | s2ring | put | fence | wait | **카드** (us/제출) |
|---|---:|---:|---:|---:|---:|---:|
| real (187 삼각형) | 20 | 1,674 | 63 | 8 | 44 | **1,560** |
| synth (레지스터 쓰기 + 삼각형 1) | 20 | 265 | 63 | 8 | 36 | **158** |

    fetch ≈ 158 us,  그리기 ≈ 1,560 − 158 = 1,401 us  (90 %)

- 카드 시간은 **거의 전부 그리기**다.  그런데 그 시간이 W_RPTR 대기(진행하면 시계 재시작)에 숨어 있었다 — 즉 **rptr 은 그리기 속도로 전진한다**: CP 가 엔진 FIFO 가 빌 때만 더 가져온다.
- 그래서 §1-6 의 산수가 그대로다: 4,080 워드 제출은 앞 제출의 미인출이 15 워드 이하가 될 때까지(= 앞 그리기가 거의 끝날 때까지) 자리를 못 얻는다.  **겹침 = 제출 사이의 CPU 시간**, §4 의 모형과 같다.
- present 의 카드 안 WAIT 는 마지막 제출의 남은 그리기(최대 ~1 ms)를 기다린다 — §4 가 이미 1 ms 로 셌다.
- 이 스트림(1,560 us)은 게임 평균(976 us, G5-0 §8-2)보다 무겁다: 기록된 마지막 스트림이 큰 월드 삼각형 묶음이었다.
- 배치를 반으로 줄이면 링에 둘이 들어가 "자리 대기 = 앞의 앞 제출 완료" 가 된다 — 그리기 90 % 라는 이 결과가 그 후속 측정(§4 끝)을 값있게 만든다.

## 4. 이득 상한 (python, G5-1c 월드 프레임 18.5 ms 기준)

| | R1 월드 | R2 데모 |
|---|---|---|
| 지금 제출 ioctl | 10.9 ms (8.6 × 1,266 us) | 18.9 ms (25 × 757) |
| 제출 사이의 CPU 시간 | 769 us | 835 us |
| 가려지는 카드 시간 / 잔여 | 769 / 207 us | 450 / 0 |
| 검증 장치 제거 | −127 us/제출 | −127 |
| **새 제출 ioctl** | **3.2 ms** | **4.5 ms** |
| **프레임(present 가 마지막 제출을 기다리는 ~1 ms 포함)** | **~11.8 ms (85 fps)** | **~27 ms (37 fps)** |

가정: 제출 사이 CPU 시간이 균등(실제는 콘솔 프레임·업로드 프레임이 들쭉날쭉) — 그래서 이것은 상한이고 판정선은 §6 에서 보수적으로 잡는다.  링에 한 제출만 들어가므로(§1-6) **배치를 반으로 줄이면 둘이 떠서** 더 가려질 수 있다 — 그것은 이 칸 뒤의 측정(`RDNMesaBatch` knob 이 이미 있다).

## 5. 단계

| | 무엇 | 재부팅 |
|---|---|---|
| 0 | §3 측정 | 없음 |
| 1 | 커널: `cpR7Prefix`/`cpR7Tail`/`cpR6Push` 추출(동작 무변경) → `cpWaitSpace` → `cpAsubmit` → `cpRetire` → verb 6·7, caps v3 → `rdnr5cp.m` 이름표 `asubmit`·`retire` → `rdnDevClose` backstop.  `check_r5_src` 규칙: (a) `cpR6Submit` 은 `cpR6Push` 를 부른다 (b) 자리 대기의 재시작 문장이 W_RPTR 것과 같다 (c) `cpAsubmit` 에 `cpWait(` 호출이 없다 (d) `CP_OP_LAST` 23 (e) retire 에 픽스캐시 플러시가 있다.  `tools/r5/sim_space.py`: 자리 산술을 참조 식과 4,096×4,096 전수 대조 + 변이 3 | 없음 |
| 2 | 라이브러리 §2-4 + `sim_present.py`/`check_hook.py` 류에 retire 자리 규칙(업로드·미러·depth_get 앞에 retire 가 있다, 변이로) + `judge_m1b` 심볼 허용 | 없음 |
| 3 | 호스트 검사(싼 것 먼저: check_r5_src, sim_space, check_hook, check_citations) → 타깃 빌드 → **`nm -u`** → 설치 → rdnreplay·rdnr5cp 재빌드(헤더 버전) → **재부팅 요청** | **1** |
| 4 | §6 게이트 | 없음 |
| 5 | check-all → 커밋 → timedemo(위임 0 일 때만) | 없음 |

**코드 전에 codex 교차검토**(§7), 한 호출 = 한 주장.

## 6. 게이트 — 러너가 곧 판정 절차 (`build/g52/run_g52_off.sh`·`run_g52_on.sh`, 판정 `build/g52/judge_g52.py`)

구현에서 G1·G2 를 강하게 했다: 같은 스트림을 두 번 그리면 당연히 같으므로, **각 팔 앞에 창을 한 색(00204060)과 먼 깊이로 채운다**(`rdndump fill`).  그래서 G2 의 "G1 과 바이트 동일" 이 뜻을 갖고, 판정기는 채움 위에 그려진 화소가 0 이 아닌지도 본다.  `rdnreplay async=1` 은 SUBMIT3 로 보내고 마지막에 RETIRE 를 한 번 부른다.  G1–G3 는 오프스크린(내 gcdsd), G4–G7 은 GLQuake 라 사용자 gcdsd.

CP 는 부팅당 한 주기이므로 순서가 곧 절차다:

| # | 실행 | 판정 (전부 python) |
|---|---|---|
| G1 | 오프스크린: `rdnreplay real ×1` 을 **SUBMIT2** 로 → `rdndump` 색·깊이 | 기준 그림 |
| G2 | `rdnreplay real ×1` 을 **SUBMIT3** 로 → `RETIRE` → `rdndump` | **G1 과 바이트 동일**(그림이 안다) |
| G3 | `rdnreplay real ×20` SUBMIT3 (retire 없이 연속) → tdump | `asubmits = 20`, `latched = 0`, 자리 대기 타임아웃 0; 계기: 제출당 ioctl 시간 |
| G4 | GLQuake `+map start`, `RDNMesaSync=1`(같은 부팅의 대조군) | RDN-T SUBMIT ≈ G5-1c 값(±20 %) — 드라이버 설치가 동기 경로를 안 바꿨다 |
| G5 | GLQuake `+map start`, 비동기 기본 | RDN-C: delegated 0, lost 0, `lateLatch` 0, replayed 0, `retireFailed` 0; RDN-T: **SUBMIT ≤ 5 ms/월드프레임**(11 →), PRESENT ≤ 1 + §3 의 잔여 예측 ms, **월드 프레임 ≤ 14 ms**; 텍스처가 정상(사용자 눈, 스크린샷 1 장) |
| G6 | 데모 | RDN-C 같은 조건, 프레임 ≤ 32 ms |
| G7 | 창 이동·종료 | 종료 뒤 `RDN-R4 close` 줄 다음에 retire 기록, 커널 걸쇠 0, 다음 실행이 다시 가속 |

G2 가 실패하면(그림이 다르면) 자리·순서 가정이 틀린 것이고 **여기서 멈춘다**.  G5 의 숫자만 모자라면 설계는 맞고 산수가 틀린 것 — §4 의 가정을 실측으로 바꾼다.

## 7. codex 에 묻는 것 (계획 단계, 코딩 전, 한 호출 = 한 주장)

- **Q1 (순서·안전)**: "`cpR6Submit` 에 자리 대기 하나를 넣고 생산 제출은 도어벨 뒤에 안 기다리면, present/clear/STOP 은 코드 변경 없이 앞 제출 뒤에 안전하게 줄을 선다" — `osrdn_cp.m` 의 `cpR6Submit`·`cpPresent`·`cpStop` 과 참조 `radeon_wait_ring` 만 보고 반증할 것.
- **Q2 (drain 전수)**: "§1-4 의 세 자리 + close/모드복귀 밖에 CPU 가 카드의 소스·목적지에 닿는 곳이 없다" — `mesa/` 와 `OSRDNDisplay.m` 의 매핑·창 접근을 grep 해 누락을 찾을 것.

회신은 [[codex-review-verify]] 절차로 전부 다시 연다.

## 8. 자체 확인 (codex 전)

- `cpR6Submit` 호출자 전수: `grep -n "cpR6Submit(" osrdn_cp.m` — cpZclear(1·2 단계), cpPresent, cpClear, R6 케이스들.  전부 빈 링에서 부르므로 자리 대기는 no-op.
- `rdnDevClose` 는 caller 문맥에서 돈다(`OSRDNDisplay.m:135-137`) — ioctl 과 같은 조건으로 기다려도 된다.
- 프리픽스 32 + 2 + 10 + 4,036 = 4,080 (python).  `CP_R6_WORDS` 4,080 이라 `w[]` 배열도 그대로 맞는다.
- 스트림 동일성: 생산 op 가 카드에 보이는 워드 = 오늘의 1 단계 + 2 단계 워드를 **한 줄로 이은 것**(센티넬은 MMIO 였으므로 링에 없다).  `tools/r6/sim_r6.py` 의 스트림 모형은 바뀌지 않는다.
- 섞어 쓰기: 비행 중에 ZCLEAR(SUBMIT2·R6 케이스·ZPREP) 가 오면 `cpIdleGate` 가 `CP_WHY_ACTIVE` 로 거절한다(`osrdn_cp.m:3199`, codex 확인).  **경합이 아니라 거절**이고 거절은 소프트웨어로 간다 — 안전하다.  라이브러리는 한 프로세스 안에서 SUBMIT2 와 SUBMIT3 을 섞지 않는다(knob 은 프로세스 단위); 진단 도구는 앞 프로세스의 close backstop 뒤에 온다.

## 9. codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전, 두 호출)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| Q1-1 `free=(rptr−wptr−1)&mask`, `free≥len` ⇔ 참조 `space>len` | python 으로 (rptr, wptr) 4,096² 전수: `free == space−1` 불일치 0 | ✅ 사실 (설계 유지) |
| Q1-1 "4,080 은 빈 링에서만" 은 틀렸다 (`wptr=0, rptr=4081` → free 4,080) | python: free 4,080 | ✅ 채택 — §1-6 문구 정정 |
| Q1-1 참조 `BEGIN_RING` 은 정렬된 4,080 에 4,096 을 예약한다 | `radeon_drv.h:2059` 를 열고 python: `16 − ((0+4080)&15) + 4080 = 4096` — 이미 정렬돼도 16 을 더 붙이는 참조의 과잉 예약 | ⚖️ 사실, 행동 불변 — 우리는 패딩한 길이(4,080)로 묻고 `space > len` 의 1 워드 여유는 유지된다 |
| Q1-2 cpLatch·cpFail 의 kick 이 자리 확인 없이 16 워드를 쓴다 | `osrdn_cp.m:430-458`(kick), `:466`·`:493`(cpLatchDump 호출) 열었다.  free<16 이면 덮어쓰기 또는 WPTR==RPTR | ✅ 채택 — §2-2 kick 가드.  오늘의 4,080 제출에도 있는 구멍 |
| Q1-2 cpZclear 의 `cpIdleGate` 가 비행 중 SUBMIT2 를 거절한다 | `osrdn_cp.m:3199`, `:771` 열었다 | ⚖️ 사실, 결론은 "경합 아님·안전한 거절" — §8 에 기록 |
| Q1-3 RPTR 은 인출 진행이고 엔진 완료가 아니다; present 의 카드 안 WAIT 가 순서를 잡는다 | §1-2 와 같은 결론(`osrdn_cp.m:3932`, 꼬리 `:3496` 의 WAIT_IDLE) | ✅ 반증 안 됨 |
| Q1-4 도어벨 순서 | `:2398-2411` | ✅ 반증 안 됨 |
| Q2 표면 창이 Mesa 의 그리기 버퍼라 소프트웨어 경로가 전부 창에 닿는다 | `OSRDNMesaSurface.c:228` `return (void *)surfBase;`, 위임 `OSRDNMesaHook.c:1110-1112` 열었다 | ✅ 채택 — **§1-4 가 틀렸다**.  §2-4 에 비행 표지와 flush 이유별 retire |
| Q2 `osrdnFlushFor` 는 빈 배치면 아무것도 안 한다 | `OSRDNMesaHook.c:539-545` 열었다 | ✅ 채택 — retire 는 flush 와 별개로 |
| Q2 `osrdn_tex_upload` 가 별도 진입점 | `OSRDNMesaTex.c:190`, 쓰기 `:225`; 호출자 grep: 헤더 선언만(현재 호출자 없음) | ✅ 채택 — 두 함수 모두에 |
| Q2 present 모드 glFinish 가 retire 없이 돌아간다 | `OSRDNMesaHook.c:1414-1420` 열었다 — 그러나 거기서 CPU 는 창을 안 읽는다(계약상 배열은 낡음); 블릿은 링에서 카드 안 WAIT 로 순서가 잡힌다 | ❌ 위험으로는 기각 — 읽기가 없다 |
| Q2 TEXDROP·아레나 재사용·triDest·rdnR7bVirt·커널 창 코드 | codex 가 반증 못 함; triDest 는 ioctl 안 copyin(`OSRDNDisplay.m` `r7bSubmit2`) 으로 이미 확인 | ✅ 반증 안 됨 |

**내가 틀린 것**: §1-4 를 `grep osrdn_surf_window` 로 셌다 — 창 포인터가 Mesa 에게 넘어간다는 것(`surf_take`)을 호출을 따라가지 않아 놓쳤다.  그리고 §1-6 의 "빈 링에서만" 은 틀린 산수였다.

## 10. 구현 (2026-09-29, 설치 전)

### 10-1. 무엇이 바뀌었나

| 자리 | 변경 |
|---|---|
| 커널 `osrdn_cp.m` | `cpWaitSpace`(참조식 자리, 진행하면 시계 재시작) · `cpR6Submit` 첫머리 자리 대기와 WPTR 되읽기 뒤 `noWait` 반환 · 동기 대기가 끝나면 `inflight = 0` · `cpLatchDump` kick 에 16 워드 가드 · `cpLatch`/`cpFail` 이 비행 중 작업을 `lostInflight` 로 셈 · `cpStop` 이 드레인 뒤 `inflight = 0` · `cpAsubmit`·`cpRetire` · `osrdn_cp_run` 진입마다 `noWait = 0` |
| 커널 `osrdn_cp.h` | `CP_OP_ASUBMIT` 22, `CP_OP_RETIRE` 23, `CP_OP_LAST` 23, 상태 필드 |
| 커널 `osrdn_modelog.m` | op 이름표 두 개, `RDN-R5 async` 줄(ASUBMIT·RETIRE·TDUMP·걸쇠 때만) |
| 커널 `OSRDNDisplay.m` | SUBMIT3·RETIRE 디스패치, `r7bSubmit2:op:`·`r7bRun:…op:`, `r7bRetire`, `r7bCloseRetire`, close 줄에 `retires=` |
| ioctl `osrdn_r7b.h` | SUBMIT3(verb 6, submit2 블록), RETIRE(verb 7, `osrdn_r7b_retire`) — 버전·CAPS 불변 |
| 도구 | `rdnr5cp.m` op 이름표, `rdnreplay async=1`, `rdndump fill` |
| 라이브러리 | §2-4 표 그대로 + 종료 보고 RDN-A 줄 |

### 10-2. 코드에 대한 codex 교차검토 (`gpt-6-astra`, 한 주장, 커널 함수만)

주장: "(1) noWait 가 남지 않는다 (2) inflight 는 수락된 미실행 작업이 있을 때만 1 이고 버려지면 lostInflight 가 센다 (3) 모든 링 쓰기 앞에 자리 대기가 있다(kick 은 16 워드 가드) (4) 자리 대기 타임아웃은 링에 쓰지 않는다".

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| (1) 두 쓰기 모두 반환 검사 전에 noWait 를 지운다, 진입에서도 지운다 | `cpAsubmit` 두 괄호와 `osrdn_cp_run` 진입을 열었다 | ✅ 반증 안 됨 |
| (2) lostInflight 는 제출 수가 아니라 사건 수다(표지가 하나) | 사실 — `inflight` 는 불리언이고 둘이 떠 있다 함께 잃어도 1 | ⚖️ 동작은 설계대로, **이름의 뜻을 주석·블록 설명에 바로 적었다** |
| (3) `cpStartCore` 는 자리 대기 없이 16 워드를 쓴다 | 열었다: 부르는 곳은 `cpStart`(맵 직후, 빈 링)와 `cpFail`(포인터를 0/0 으로 되돌린 직후) 둘뿐 | ⚖️ 문구로는 사실, 위험 없음 — 두 곳 다 링이 비었음을 코드가 보장 |
| (4) 타임아웃 뒤 cpFail 의 kick 이 쓸 수 있다 | 가드가 16 워드 빈 때만 허용 — 설계 그대로 | ✅ 설계대로 |

### 10-3. 검사기

| 검사기 | 추가 |
|---|---|
| `tools/r5/check_r5_src.py` | `g52-async`(두 함수의 워드 열 대조, cpAsubmit 이 카드에 묻지 않음, 쓰기 두 번·괄호, 자리 식·재시작, kick 가드, 진입 초기화, RETIRE 순서) + 변이 10; `r6-ring` 허용에 cpAsubmit; `r7-verify` 를 함수별로 정밀화(파일 전체 검색이 한쪽의 거절 누락을 못 봤다); `m3j` cpFail 반환 9 곳을 함수별로 |
| `tools/r5/sim_space.py` (새) | 소스의 자리 식을 읽어 4,096² 전 쌍을 참조 식과 대조, kick 가드, 패딩 길이; 변이 3 |
| `tools/r7/check_r7b.py` | `g52-ioctl`(verb·블록·디스패치·close 가 걸쇠 전에 retire) + 변이 3 |
| `tools/mesa/check_hook.py` | `g52-retire`(flush 이유 표 길이·순서·필수 1, 빈 배치에도 retire, 미러 retire 순서) + 변이 4; m1d 규칙은 **제출** ioctl 만 세도록(RETIRE 는 한 집 `triRetireIoctl`) |
| `tools/mesa/sim_texupload.py` | 업로드 두 함수가 **쓰기 전에** retire 를 한 번 부르는지 창의 합으로 잰다 + 변이 3(없음·없음·쓴 뒤로 이동) |
| `tools/mesa/sim_batch.py` | 가짜 카드가 RETIRE 를 옛 커널처럼 거절(ENOTTY), SUBMIT3 는 SUBMIT2 처럼 받음 |
| `tools/r2b0/check_reloc_r2b0.py` | MMIO 호출자 목록에 cpWaitSpace·cpAsubmit·cpRetire(쓰기는 cpRetire 만) |
| `build/g52/judge_g52.py` (새) | 게이트 판정 + 자체검사(그림이 다름·아무것도 안 그림·제출 수 누락) |

### 10-4. 빌드

- 드라이버: `pack_r2b0.py`(hostcheck-r2b0 PASS 포함) → 타깃 **OSRDNBUILD PASS stamp=81450f91 runid=790606948 symbols=21**(미정의 심볼 전부 커널 export) → 호스트 `check_reloc_r2b0` PASS.
- 라이브러리: 타깃 **RDNMESA PASS runid=790607015**, `judge_m1b` PASS(미정의 22 개 전부 허용 목록).
- 도구: 타깃에서 `rdnreplay`·`rdndump` 재빌드(새 문자열 확인).
- 새 라이브러리는 옛 커널에서 RETIRE 가 ENOTTY 라 **동기로 돈다** — 설치 순서가 어긋나도 안전하다.

## 11. 실기 결과 (2026-09-29, 부팅 ee4b61a6, 드라이버 81450f91, 라이브러리 790613340)

**게이트 전부 PASS** (`build/g52/off.log`, `build/g52/on.log`).

| 게이트 | 결과 |
|---|---|
| G1 | 채움(색 00204060, 깊이 0) 위에 동기 재생 1 회: 177,773 화소 그려짐 |
| G2 | 같은 채움 위에 SUBMIT3 + RETIRE: 색·깊이 **G1 과 바이트 동일** |
| G3 | SUBMIT3 20 회(fd 하나), RETIRE 1 회: 자리 대기 18 회, RETIRE 3,541 us, lost 0, markbad 0, 걸쇠 0 |
| G4–G6 | GLQuake 동기/수락/데모: 위임·재생·소프트웨어 0, `latelatch` 0, `lost` 0, `failed` 0 |
| G7 | 부팅 합계: 수락 10,533, 자리 대기 2,437 회(23 %, 평균 1,353 us), RETIRE 346(기다림 331, 평균 1,224 us), 걸쇠·skip·복구 0 |
| G8 | GLQuake 직후 첫 카드 clear: rc 0, ok — **G4-6 의 대기 초과는 재현되지 않았다** |

| 월드 구간(150–300, python) | 동기 | 수락 |
|---|---|---|
| 프레임 | 17.2 ms (58.1 fps) | **15.1 ms (66.2 fps), −12 %** |
| 제출 | 11.78 | 6.95 |
| present(카드 꼬리가 여기로) | 0.61 | 2.14 |
| 제출 + present | 12.39 | 9.09 |
| 콘솔·적재 구간(1–150) | 38.6 | **23.3 (−40 %)** |

- §4 의 상한(~11.8 ms)에 못 미친 이유: 수락 제출의 23 % 가 **링 자리를 기다렸다**(평균 1.35 ms) — 4,080 워드 본문이 링에 하나만 들어가므로, 제출 사이 CPU 시간이 카드의 그리기보다 짧으면 다음 제출이 앞 그리기를 기다린다(§1-6).  카드가 병목에 가까워졌다는 뜻이다.  다음 지렛대: 배치를 줄여 둘이 떠 있게(`RDNMesaBatch`, 남은 작업 10) — 카드 일이 같으면 이득은 겹침이 늘어나는 만큼뿐이다.
- 곁에서 고친 것(시험 도구): 깊이 GEQUAL 스트림에 먼 깊이로 채우면 아무것도 안 그려진다(판정기가 "그려진 화소 0" 으로 잡았다) → 깊이 0 으로 채움.  `rdnreplay` 가 반복마다 열고 닫으면 마지막 close 의 retire 가 매번 기다려 수락을 못 잰다 → fd 하나를 쥔다.  `/usr/ucb/logger` 는 `/usr/adm/messages` 에 안 남는다(실측) → 구간 표지는 줄 수로.
