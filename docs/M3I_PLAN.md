# M3i — 멈춤을 참조처럼 읽는다 (CP 걸쇠 덤프)

사용자 지적(2026-09-25): "참조할 BSD·Linux 가 있는데 왜 누락이 많은가."  M3f 의 결론("링 끝 채우기가 원인")은
다음 부팅의 걸쇠(링 중간, 3024)로 흔들렸다.  **이 문서는 코딩 전에 쓴다.**

## 1. 네 번의 걸쇠, 한 줄로

| 부팅 | 실행 | 제출 | 접두 위치 | 그리기 제출 시작 | 크기 |
|---|---|---|---|---|---|
| e630f871 (M3c) | 컬링 teapot | 148 | 4016→4048 | 채움 48 @4048, 내용 @0 | 108→128 |
| 0238ab06 (M3d) | 컬링 teapot | 148 | 4016→4048 | 채움 48 @4048, 내용 @0 | 108→128 |
| e70f0f3c (M3e) | A(붙잡은 4 삼각형) | 26 | 4016→4048 | 채움 48 @4048, 내용 @0 | 108→128 |
| 02416a57 (M3h) | 640×480 컬링 | 314 | 2992→3024 | 내용 @3024 (경계 3072 는 +48) | 153→176 |

148 의 위치는 로그가 잘려 있어 **멈춘 CP 에 컬링 teapot 을 5 회 돌려 거절 로그에서 제출 크기 60 개를 채취**(비파괴; 한 개는 3,491 삼각형 합으로 결정)하고 일반 실행 96 개(주기 3)와 이어 python 으로 걸었다(`build/m3h/run-790345421/cull-sizes.txt`).  M3c 조각 44 개와 불일치 0.

넷 모두 **접두가 4 KiB 페이지 끝 48 워드 앞에서 끝난 뒤의 그리기 제출**이다.  그러나 같은 기하로 살아남은 제출도 있다(148 앞의 140: @976, 128 워드; 99: 채움 2,096).  직전 바퀴 내용(오래된 선인출 가설)은 살아남은 쪽이 오히려 지저분해 **기각**.  기록의 `post=00000140`(RBBM_STATUS): FIFO 64 비어 있음, `CP_CMDSTRM_BUSY`(bit 16)=0, `GUI_ACTIVE`=0 — CP 는 대기 명령에 갇힌 것이 아니라 **새 제출을 소비하지 않은 채 한가하다**.

## 2. 참조 제출 경로 대조 (이번에 읽은 것)

| 항목 | FreeBSD drm (`radeon_cp.c`·`radeon_state.c`) | Linux 3.10 `r100.c` | 우리 | 판정 |
|---|---|---|---|---|
| 링 크기·rptr 갱신·fetch | size_l2qw=order(16K/8)=11, rptr_update 9, fetch 1 | 같음(+`RB_NO_UPDATE` wb 없을 때) | `0x0804090b` (11·9·1·NO_UPDATE) | 같음 |
| CSQ 모드 | `cp_mode` PRIBM_INDDIS/INDBM | PRIBM_INDBM | `0x40000000` INDBM | 같음 |
| `RB_WPTR_DELAY` | 0 | `pre_write_timer 64` | 0 | FreeBSD 와 같음 |
| 커밋 | tail 16 정렬·PACKET2, `mb()`, WPTR 쓰기, RPTR 읽기 | 같음 | 16 정렬, `osrdn_cpu_serialize()`+RBBM 읽기, WPTR 쓰기, RPTR 읽기 | 같음(M3f 뒤) |
| 그리기 앞 대기 | clear: `WAIT_UNTIL 2D|HOST idleclean` 뒤 상태 12 개 | — | 2단계 첫 워드 같은 값 | 같음 |
| **멈춤 때 읽는 것** | — | `CP_STAT`, `RB_RPTR`, **`RB_WPTR` 되읽기**, `CSQ_STAT`·`CSQ2_STAT`·`CSQ_MODE`, **CSQ FIFO 256 워드**(`CSQ_ADDR`/`CSQ_DATA`), rptr 주변 링 워드 (`r100_debugfs_cp_ring_info`/`_csq_fifo`) | `RBBM_STATUS` 하나 | **우리만 없다** |

## 3. 바꿀 것 (드라이버, 진단만 — 동작 변경 없음)

- D1 `cpLatch`: RBBM_STATUS 에 더해 `CP_STAT`(0x7c0)·`RB_RPTR`·`RB_WPTR`·`CSQ_STAT`·`CSQ2_STAT`·`CSQ_MODE` 를 읽고, CSQ FIFO 의 주 큐 256 워드를 `CSQ_ADDR` 쓰기·`CSQ_DATA` 읽기로 뜬다(Linux 와 같은 순서).  링의 RAM 사본에서 rptr−16..rptr+47 을 복사한다.  전부 `osrdn_cp_state` 에 담아 `kept` 로 다시 찍힌다.
- D2 매 제출: WPTR 을 쓴 뒤 **되읽어** 기록(`wptrRead`).  값이 다르면 그 자리에서 `CP_WHY_WPTR` 로 거절(대기 100 ms 없이).  참조는 되읽지 않지만, "잃어버린 종"은 이 증거 하나로 갈린다.
- 로그 예산: 덤프는 `kept` 재출력에서만(걸쇠 뒤 RECORD), FIFO 256 워드는 8 개씩 32 줄.

## 4. 다음 부팅

`run_m3e.sh`(A 200 → teapot 일반·컬링)로 재현 → `record` 로 덤프 회수.  판정은 덤프의 `CSQ` rptr/wptr 와 FIFO 내용: 우리 워드가 FIFO 에 있으면 "가져왔으나 실행 안 함", 없으면 "가져오지 않음"; `RB_WPTR` 되읽기가 목표와 다르면 "종 분실".

## 5. 설계 세부 (코딩 전, 원문 확인 완료)

- 참조 확인: Linux `r100_debugfs_cp_csq_fifo` 는 보호 없이(디버그 파일이 열릴 때마다, CP 가 살아 있든 아니든) `CSQ_ADDR` 을 쓰고 `CSQ_DATA` 를 읽는다(`r100.c` 2977–2990); `r100_asic_reset` 은 리셋 전에 `RBBM_STATUS` 만 읽는다(2539–).  `CP_STAT`(0x7c0) 의 비트 배치는 미러의 어느 헤더에도 없다 → 원값만 찍는다.  `CSQ_STAT` 필드는 `radeon_reg.h` 3344– 가 8 비트 넷(rptr/wptr 주·간접), `r100.c` 2959– 는 10 비트 셋 — **둘 다 원값을 찍고 해석은 호스트에서**.
- 우리 모형(`world5.c`): 읽기 전용은 `0x0e40`·`0x0710` 뿐(1182 행), `CSQ_ADDR`(0x7f0) 쓰기는 저장만; 걸쇠를 만든 연산의 `ioRd/ioWr` 수를 못 박는 시험 없음(못 박는 것은 걸쇠 **뒤** 연산과 STOP 뿐, 1759·1765·1782 행).  → RECORD 거절 규칙은 그대로 둔다.
- 로그 예산(python): 기록 ~2,500 B + 걸쇠 줄 ~110 B < 4,084 B; FIFO 32 줄 + 링 8 줄 ≈ 3,600 B 는 **따로** — 걸쇠가 거절한 RECORD 를 두 번 부르면 첫 번째는 기록+걸쇠 줄, 두 번째는 FIFO·링 워드(`rdnCpKeptPrints`).
- WPTR 되읽기는 `cpR6Submit` 과 R5 표지 `cpSubmit` 둘 다(같은 모양, 866·2011 행).  불일치 → `CP_WHY_WPTR`(36) 로 `cpLatch`(덤프가 찍히도록; 그 부팅의 CP 는 어차피 어긋난 상태).
- INJECT 의 가짜 걸쇠도 같은 `cpLatch` 를 지나 덤프한다 — 살아 있는 CP 에 `CSQ_ADDR` 을 쓰는 것은 Linux 디버그 파일과 같은 행위.

## 6. codex 계획 검토 (덤프 레지스터의 부작용·보호·필드)

| codex 주장 | 내 검증 (먼저 직접 열었다) | 판정 |
|---|---|---|
| `CSQ_ADDR` 쓰기·`CSQ_DATA`·`CP_STAT`·`RB_RPTR/WPTR`·`CSQ_STAT` 읽기에 문서화된 부작용 없음; 덤프 함수는 잠금·CP 정지 없이 언제든 실행 | `r100.c` 2920–2990: 함수 본문에 잠금·대기·CP 정지 없음; 항목마다 `CSQ_ADDR` 을 다시 쓴다(자동 증가 가정 없음) | ✅ |
| `CSQ_STAT` 은 헤더상 8 비트 필드 넷, 디버그 덤프는 10 비트 여섯으로 해석 — 충돌 | `radeon_reg.h` 3344–3351(`0xff` 마스크 넷), `r100.c` 2959–2964(`0x3ff`); xf86 `radeon_reg.h` 3149–3152 도 8 비트 | ✅ 원값을 찍고 호스트에서 두 해석 다 시도 |
| `CP_STAT`(0x7c0) 비트 배치는 미러 어디에도 없다 | 세 헤더 grep 0 건 | ✅ 원값 |
| `r100_asic_reset` 은 리셋 전 `RBBM_STATUS` 만 읽고 CP 상태를 보존하지 않는다 | `r100.c` 2539–2560 | ✅ (Linux 도 멈춤 원인 분석은 디버그 파일로 한다 — 우리 덤프가 그 역할) |
| `r100_mc_stop` 이 CRTC 등 표시 레지스터를 읽는다 | 열지 않음 — 우리는 리셋을 안 하므로 무관 | ⏭️ |

## 7. 구현

- `osrdn_cp.h`: `CP_WHY_WPTR 36`, `CP_LATCH_FIFO_WORDS 256`·`CP_LATCH_RING_WORDS 64`, 상태에 `latchRead`·`cpStat`·`rbRptr/rbWptr`·`csqMode`·`wptrRead`·`fifo[256]`·`ringNear[64]`·`ringNearAt/Bad`.
- `osrdn_cp.m`: `C_CP_STAT 0x7c0`·`C_CP_CSQ_ADDR 0x7f0`·`C_CP_CSQ_DATA 0x7f4`; `cpLatch` 가 `RBBM_STATUS` 뒤에 여섯 레지스터와 FIFO 256 워드(Linux 와 같은 순서·같은 선택자 쓰기), RAM 링의 `rptr−16` 부터 64 워드와 섀도 불일치 수를 담는다; 두 제출 경로 모두 WPTR 되읽기 → 불일치면 `CP_WHY_WPTR` 로 `cpLatch`.  연산마다 `latchRead`·값들을 0 으로(배열은 남김).
- `osrdn_modelog.m/.h`: 기록에 `RDN-R5 latch …` 한 줄(`latchRead` 일 때), `osrdn_cp_latch_words` 가 `RDN-R5 fifo`/`near` 40 줄.  `OSRDNDisplay.m`: 걸쇠가 거절한 RECORD 가 홀수 번째는 기록, 짝수 번째는 워드를 찍는다(`rdnCpKeptPrints`).
- 검사: `check_r5_src` 규칙 `m3i-latch-dump`(여섯 읽기·FIFO 루프·`latchRead`, 제어 레지스터 접촉 금지, 되읽기 2 곳) + 변이 3(덤프 삭제 / 덤프가 CSQ 제어를 씀 / 종 분실을 안 걸음) 잡힘; `check_cp` 형식 대조에서 `latch`·`fifo`·`near` 는 걸쇠 뒤에만 나오므로 `kept` 처럼 제외; `world5` INJECT 시험은 "가짜 걸쇠 뒤 CSQ 를 안 읽는다" 에서 "걸쇠는 CP 의 계정을 읽는다(`csqRead`·`latchRead`, 쓰기 ≥ 256)" 로 — 설계 변경에 따른 기대값 변경.  `hostcheck-r2b0` PASS(전방 참조 하나를 잡아 고침).
- `run_m3e.sh`: K 단계에서 RECORD 를 두 번(4 초 간격), 덤프 줄 수 보고.
- 역어셈블 게이트(`check_reloc_r2b0`)가 `_cpLatch` 의 `_rdnMmioWrite32` 호출을 잡았다(호출자 표 밖) → 표에 `_cpLatch` 를 이유와 함께 등록하고 필수 호출 쌍에도 넣었다(빠지면 다시 잡힌다).  자체시험 PASS, 게이트 PASS.

## 8. 설치

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** |
| 타깃 빌드 `cfd2cdea` / runid 790349591, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS**(첫 실행은 위 호출자 표로 FAIL, 설치기가 올바르게 거부) |
| 설치 `closed=yes fresh live` | DONE — 그러나 §10 의 D3 를 넣어 **다시 빌드** |

## 9. 다음 부팅

마운트 → gcdsd(teapot — 사용자) → `BOOT=<nonce> BUILD=6a57e203 bash build/m3e/run_m3e.sh` — A 200 → teapot 일반·컬링 → 걸쇠면 RECORD 두 번으로 기록+덤프 회수.
판정(호스트, python): `RB_WPTR` 되읽기 vs 목표(종 분실?), `CSQ_STAT` 의 rptr/wptr(8 비트·10 비트 두 해석), FIFO 256 워드에 우리 제출의 첫 워드들(`WAIT_UNTIL` 0x5c8/0x50000, 프롤로그 0x70e…)이 있는지, `near` 64 워드 = 섀도인지(`nearbad`).

## 10. 사용자 질문(2026-09-26) — "필요한 구현은 다 했나" → 하나 더: 참조의 "찔러 보기"

Linux 의 멈춤 판정은 읽기 뒤에 한 걸음 더 간다: `r100_gpu_is_lockup`(`r100.c` 2499–2511)은 엔진이 바쁘면
`radeon_ring_force_activity` 로 링에 NOP 을 넣고 WPTR 을 다시 써서 rptr 이 움직이는지 본 뒤에야 멈춤이라 한다
(`radeon_ring.c` 는 미러에 없고, 호출과 주석 "force CP activities" 만 `r100.c` 2507–2510 에 있다).

- D3 `cpLatch`: 덤프 뒤 **`kick`** — 현재 wptr 에 PACKET2 16 워드(cpPut), 직렬화+RBBM 읽기, WPTR = wptr+16 쓰기,
  RPTR 읽기, 10 ms(`C_KICK_US`) 동안 rptr 을 폴링.  기록: `kickWptr`(쓴 값), `kickRptr`(뒤 rptr), `kickMoved`(rptr 이 이전과 다른가),
  `kickWptrRead`(WPTR 되읽기).  걸쇠 상태(`latched=1`)는 그대로 — 되살아나도 이 부팅에서 다시 쓰지 않는다(판정은 호스트).
- 판정 갈래: `kickMoved=1` 이면 "종을 다시 울리면 간다"(잃어버린 종/타이밍), 0 이면 "CP 가 링을 못 읽는다"(GART/페치) 쪽.
- D3 구현: `cpLatch` 덤프 뒤 PACKET2 16 워드(링+섀도), `cpFence`(무조건 WBINVD — 걸쇠당 한 번이라 제출 펜스의 손잡이를 안 탄다), WPTR 쓰기·RPTR 읽기·WPTR 되읽기, `cpWait(W_RPTR, 10 ms)`, `kickRptr`·`kickMoved`.  기록 줄에 `kick=쓴값/되읽기 kickrptr= moved= kus=/t`.
- 규칙: `m2a-nowb` 의 `cpFence` 자리 수 6 → **7(M3i kick 을 이름으로 추가)** — 각 자리를 이름으로 세는 규칙이라 정밀화이지 완화가 아니다; `m3i-latch-dump` 에 kick 의 세 문장과 "덤프 뒤에 온다" 순서, 변이 "kick 삭제" 추가(잡힘).  첫 구현은 펜스를 인라인해 `doWb` 3 곳·`cpSubmitFence` 2 곳으로 규칙에 걸렸다 — 규칙이 정확히 제 일을 했다.

## 11. codex 계획 검토 2 (D3 kick — 빌드 전)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| `radeon_ring_force_activity` 등의 정의는 미러에 없다; `r100.c` 2499–2511 은 `GUI_ACTIVE` 가 **꺼져 있으면** 찌르지 않고 "멈춤 아님" | 2499–2511 직접 읽음(앞서 확인) | ✅ — 우리 네 멈춤은 `GUI_ACTIVE=0` 이라 Linux 는 "멈춤 아님" 으로 분류했을 것.  kick 은 참조의 문자 그대로가 아니라 **참조의 방법을 우리 상황에 옮긴 실험**임을 적어 둔다.  16 NOP·10 ms 는 우리 값. |
| WPTR 을 이미 쓴 뒤 다시 쓰는 것을 금하는 문장은 없다; `BEGIN_RING` 은 공간이 있으면 앞 것이 안 끝나도 커밋한다; `WPTR_DELAY` 주석은 반복 쓰기를 전제 | `radeon_drv.h` 2055–2069(앞서 읽음), `r100.c` 1124–1143(앞서 읽음) | ✅ |
| FreeBSD `radeon_wait_ring` 은 시간 초과에 아무것도 안 쓰고 `-EBUSY`, `BEGIN_RING` 은 그 값을 무시(FIXME) | `radeon_cp.c` 1901–1930 열어 확인 | ✅ |
| `radeon_do_cp_idle` 은 PURGE DC·ZC + `WAIT_UNTIL_IDLE` 6 워드를 커밋한 뒤 idle 을 기다린다; 복구는 엔진 소프트 리셋 | `radeon_cp.c` 552–560 열어 확인(리셋 순서는 열지 않음 — 이번엔 안 쓴다) | ✅ / 리셋 부분 ⏭️ |
| "종을 두 번" 같은 우회는 없다; `#if 0` 의 WPTR bit 31 은 죽은 코드 | `radeon_cp.c` 535–546 | ✅ |
| 커밋 패딩은 0–15 워드(16 고정 아님) | `radeon_cp.c` 2100–2108 | ✅ — kick 의 16 워드는 "제출 하나의 최소 단위" 로 택한 우리 값 |

결론: D3 는 참조가 금하는 것을 하지 않는다.  기록에 남길 조건: `kickMoved` 의 해석은 "GUI 가 한가한 CP 에 종을 다시 울렸을 때" 에 한한다.

## 12. 설치 (D3 포함, 최종)

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** |
| 모형 `sim_r5`·`sim_r6` | **PASS** |
| 타깃 빌드 **`6a57e203`** / runid 790352069, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — 다음 부팅부터 |

다음 부팅: `BOOT=<nonce> BUILD=6a57e203 bash build/m3e/run_m3e.sh`.
