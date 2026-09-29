# R5 STOP 수정 — CSQ 를 끈 뒤의 rptr 비교 (계획, 코딩 전, 교차검토 대상, 2026-09-19)

입력: `docs/R5D_PLAN.md` 9·10(부팅 eae3072b 의 실측), `docs/R5_PLAN.md` 8·13, 드라이버 `osrdn_cp.m` `cpStop`.

## 0. 한 줄 요약

깨끗한 STOP 은 CSQ 를 끈 **뒤에** `RB_RPTR == wptr` 를 요구한다.  그런데 CSQ 를 끄면 `RB_RPTR` 이 0 으로 읽힌다(실측).  wptr 가 0 이 아니면
**거짓 걸쇠**(안전 쪽 실패) — R5 PASS 는 두 바퀴 뒤 wptr 가 우연히 0 이라 통과했다.  비교를 CSQ 를 끄기 **전**으로 옮기고, 끈 뒤의 값은 기록만 한다.

## 1. 사실

| # | 사실 | 근거 |
|---|---|---|
| S1 | `cpStop`(RUNNING): RPTR 따라잡기 대기 → 유휴 대기 → `CSQ_CNTL = 0` → 유휴 대기 → **RPTR 을 읽어 wptr 와 비교, 다르면 걸쇠** | `osrdn_cp.m` `cpStop` |
| S2 | 부팅 eae3072b: CSQ 켜진 채 RECORD `rptr=00000810 wptr=00000810`(n=11) → 걸쇠 STOP(CSQ_CNTL 쓰기 **하나**, `wr=1 rd=1`) → RECORD `rptr=00000000 wptr=00000810`(n=18, n=19 도 같음) | `build/r5/boot-eae3072b.full.log` |
| S3 | S2 사이의 다른 호출은 모두 카드 무접촉: CP 거절 5 개 `wr=0 rd=0`, 순환·엔진 거절은 `modeFinish` 만(할 수 있는 일은 복귀·LUT — 복귀는 `kernelRevertSeen` 이 없어 안 함, LUT 는 팔레트) | `osrdn_mode.m` `modeFinish`/`modeReleaseOrWork`, 같은 로그 |
| S4 | R5 PASS(fdca7cd1)의 STOP 은 `wptr=0` 에서 — 일정 16 + 1024×7 + 1008 = 8192 ≡ 0 (mod 4096) | `docs/R5_PLAN.md` 13, python |
| S5 | 참고 드라이버는 CP 를 끈 뒤 RPTR 을 보지 않는다: FreeBSD `radeon_do_cp_stop` 은 `CSQ_CNTL` 쓰기 하나, KMS `r100_cp_disable` 은 `CSQ_MODE`·`CSQ_CNTL` 0 뒤 유휴 대기뿐 | `radeon_cp.c:617-624`, `r100.c:1219-1231` |
| S6 | 호스트 시뮬레이터는 "CSQ 끄면 RPTR 0" 을 모형에 두지 않아 이 결함을 못 봤다 — 모든 STOP 경우가 wptr 0 이거나 걸쇠 | `tools/r5/sim/world5.c` |

S2 의 한계: 관측 한 번, CSQ 쓰기와 RPTR 0 사이의 인과는 S3 의 배제로만.  **두 번째 관측을 이 수정의 실기 시험이 만든다**(3 절).

## 2. 수정

- `cpStop`(RUNNING): 따라잡기 대기(그대로) → 유휴 대기(그대로) → **CSQ 가 켜진 채 RPTR 을 읽어 `rptrAfter` 에 두고 wptr 와 비교, 다르면 걸쇠**
  → `CSQ_CNTL = 0` → 유휴 대기(그대로) → RPTR 을 한 번 더 읽어 **`rptrOff` 에 기록만**(판정 아님) → unmap.
- 새 필드 `rptrOff`, `ptrs` 줄 끝에 `roff=`.
- MMIO 계수: STOP 읽기가 하나 는다(`rd` +1) — 판정기의 걸쇠 STOP `wr=1 rd=1` 은 걸쇠 경로라 무관.
- 다른 곳: RPTR 을 CSQ 가 꺼진 상태에서 읽어 판정하는 곳이 없는지 전수 확인(MAP 은 CSQ 꺼진 채 읽은 값을 **그대로 WPTR 에** 써서 둘을 맞춘다 — 판정이 아니라 정렬;
  MAP 게이트는 rptr==wptr==`c->wptr` — 그 값 자체가 같은 읽기에서 옴).

## 3. 검사

- 시뮬레이터: 모형에 "CSQ_CNTL 에 모드 0 을 쓰면 RPTR 0"(S2).  경우: START 뒤 바로 STOP(wptr 16), SUBMIT 1024 뒤 STOP(wptr 1040) → 깨끗(rc 0, state STOPPED,
  `rptrAfter == wptr`, `rptrOff == 0`).  변이: 옛 비교(끈 뒤) 복원 → 위 경우가 걸쇠로 실패; 끄기 전 비교 제거 → "끄기 전 따라잡지 못함" 경우(모형 손잡이)가 통과해 실패.
- 판정기 `check_cp.py`: `--submits N`(기본 8) — 절차의 SUBMIT 개수를 바꿀 수 있게; STOP 의 `rafter == 마지막 wptr` 판정, `roff` 기록.
- 소스 규칙: `cpStop` 에서 `C_CP_CSQ_CNTL` 쓰기 **뒤에** `c->wptr` 와의 비교가 없어야(r5-stop).

## 4. 실기 (한 부팅)

RECORD → LOAD → MAP → RECORD → RESET → RECORD → START → **SUBMIT 1024** → STOP(**wptr 1040**) → RECORD → cycle.
기대: STOP rc 0·state 4·`rafter=1040`·`roff=0`(S2 의 두 번째 관측), 마지막 RECORD `rptr=0 wptr=1040`, cycle verdict 0.  판정 `check_cp.py <log> --submits 1`.

## 5. 교차검토에 물을 것
1. S2·S3 이 "CSQ 끄기 → RPTR 0" 을 세우기에 충분한가, 다른 설명(예: 유휴 뒤 RPTR 이 스스로 0, 읽기 부작용)은 배제되는가.
2. CSQ 가 켜진 채 한 비교가 끈 뒤 비교가 막으려던 것(끄는 순간 남은 페치)을 잃는가 — 잃는다면 무엇으로 대신하나.
3. RPTR 이 CSQ 꺼짐에서 0 이면 다른 곳(MAP·게이트·NEGCTL·판정기)에 같은 가정이 숨어 있는가.
4. 실기 한 부팅(wptr 1040)이 수정의 증거로 충분한가.

## 6. operator 결정 (2026-09-19 00:2x)
codex 는 2026-09-19 19:23 까지 한도.  **operator: "내부 agent 로 진행"** — 계획 교차검토는 내부 agent, 판정은 전 건 원문 재확인.

## 7. 계획 검토 판정 (내부 agent 1 건; 인용 전부 열어 확인)

### 7-1. 내가 틀린 것
- **S3**: "순환·엔진 거절은 카드 무접촉" — `modeFinish` 는 복귀 작업을 할 수 있고 그 맨 앞이 `osrdn_cp_quiesce`(걸쇠면 `CSQ_CNTL=0`)다.
  바른 문구: **n=11 과 n=18 사이에 CP 에 닿을 수 있는 쓰기는 `CSQ_CNTL=0` 뿐**(`RBBM_SOFT_RESET` 은 `cpReset` 에서만).  결론은 같다.
- **S6**: 시뮬레이터에 wptr 16 에서의 깨끗한 STOP 경우가 **있었다**(`world5.c` 694–696 행: `upToStart()` 뒤 STOP) — 모형이 CSQ 쓰기에 RPTR 을 안 바꿔 통과했을 뿐.
- **4 절 절차와 판정기 불일치**: 계획한 부팅엔 NEGCTL 이 없는데 `check_cp.py` 152 행 절차는 NEGCTL 을 요구한다.

### 7-2. 판정
| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| E1 | CSQ 켜진 채로는 시간·읽기로 RPTR 이 0 이 되지 않는다(n=11 이 주입 36 초 뒤에도 810) | ✅ | eae3072b 로그 n=11 줄(이 세션에서 읽음) |
| E5 | 어느 참고도 CSQ 끄기가 RPTR 에 하는 일을 말하지 않는다; KMS 는 재시작 때 `RB_CNTL|RB_RPTR_WR_ENA` + `RB_RPTR_WR=0` 으로 **강제** | ✅ | `r100.c` 1155–1158·2553–2557 행, Linux `radeon_reg.h` 3305·3309 행 열어 확인 |
| Q1 | "0 으로 읽힘" 과 "0 으로 리셋됨" 은 로그로 구별 불가 — 수정엔 무관, **재시작 경로엔 유관** | ✅ | 기록: 지금은 재시작 경로 없음(LOAD 는 NONE, MAP 은 LOADED 에서만); 생기면 KMS 식 강제 필수 |
| M1 | 실기 절차 = **G4 전체 + NEGCTL 뒤 SUBMIT 16** → STOP 을 wptr 16 에서(회귀 범위 유지, 변수 하나) | ✅ | python: (8192+16) mod 4096 = 16 |
| M2 | "끄기 전 비교 제거" 변이는 죽일 수 없다 — RPTR 따라잡기 대기(`osrdn_cp.m` 878 행)가 같은 것을 이미 요구 | ✅ | 878–881 행 열어 확인.  **끄기 전 비교를 새로 넣지 않는다**(참고와 같이 대기에 맡김), 끈 뒤 비교만 제거 |
| (2) | 끈 뒤 의미 있는 기록: WPTR 은 유지됨(n=18 `wptr=810`), REG5 | ✅ | 끈 뒤 `RPTR`·`WPTR` 둘 다 기록(판정 아님) |
| m3 | 판정기: STOP `rafter`, 마지막 RECORD 의 rptr/wptr 를 기록 | ✅ | — |
| m5 | 거짓 걸쇠는 "안전 쪽" 만이 아니다 — GART 켜짐·AGP 옮겨짐이 남고 모드 변경이 막힌다; 복귀 경로(`modeRevertBody`·`revertToVGAMode`)도 `cpStop` 을 부른다 | ✅ | `osrdn_mode.m` 1201–1202 행 확인.  수정 우선순위 근거 |

## 8. 개정 명세 (7 반영 — 2·3·4 절과 충돌하면 이 절이 이긴다)
- `cpStop`(RUNNING): 따라잡기 대기 → 유휴 대기 → **`rptrAfter` = RPTR 읽기(기록)** → `CSQ_CNTL=0` → 유휴 대기 → **`rptrOff`·`wptrOff` = RPTR·WPTR 읽기(기록만)** → unmap.
  끈 뒤의 rptr 비교는 **없앤다**.  새 비교는 넣지 않는다.
- `ptrs` 줄 끝에 `roff= woff=`.
- 시뮬레이터: 모형 "CSQ_CNTL 모드 0 쓰기 → RPTR 0"; 경우: wptr 16·1040 의 깨끗한 STOP(`rptrAfter==wptr`, `rptrOff==0`, `wptrOff==wptr`).  변이: 옛 끈 뒤 비교 복원.
- 판정기 `check_cp.py`: 절차를 연산 순서대로 걷는다; `--tail-submit N`(NEGCTL 뒤 SUBMIT 하나, 길이 N); STOP `rafter == 그때의 wptr` 판정; `roff`·`woff`·마지막 RECORD 의 rptr/wptr 는 기록.
- 소스 규칙 `r5-stop`: `cpStop` 에서 `C_CP_CSQ_CNTL` 쓰기 뒤에 `c->wptr` 와의 비교가 없다.
- 실기: G4 전체(…NEGCTL) → **SUBMIT 16** → STOP(wptr 16) → RECORD → cycle.  판정 `check_cp.py <log> --tail-submit 16`.
- 재시작 경로가 생기면 KMS 식 RPTR 강제(Q1) — 지금은 없음.

## 9. 구현과 실기 전 코드 검토 (2026-09-19)
- 코드: `cpStop` 끈 뒤 비교 제거, `rptrAfter`(끄기 전, 기록)·`rptrOff`/`wptrOff`(끈 뒤, 기록), `ptrs` 줄 `roff= woff=`.  시뮬레이터 모형(CSQ 끄기 → RPTR 0, 가짜 CP 페치 중단),
  경우 wptr 16·1040 깨끗한 STOP·"엔진 유휴인데 RPTR 뒤처짐"(→ 걸쇠) — 7-2 M2 가 "죽일 수 없다" 던 변이도 이 경우로 죽는다.  변이 2, 소스 규칙 `r5-stop`(+변이), 판정기 `--tail-submit`.
- 코드 검토(내부 agent): 결함 없음.  검토자가 실기 형식으로 만든 로그(NEGCTL `len=0`, 꼬리 SUBMIT 16, STOP `rafter=16 roff=0 woff=10`)로 `--tail-submit 16` PASS, rafter 0 이면 FAIL 확인.
  minor: (1) CSQ 끄기에 가짜 CP 의 남은 워드를 안 비움 → 고침; (2) fdca7cd1 회귀는 wp 0 이라 새 STOP 판정에 대해 공허 — 실기가 닫는다; (3) 합성 로그의 옛 ptrs 형식 → 고침;
  (4) `r5-stop` 규칙은 `==`/`!=` 만 본다 — 시뮬레이터 경우가 덮음(기록).
- 실기 주의: 꼬리 SUBMIT 은 NEGCTL 과 다른 runid(씨앗 재사용 거절).
- 빌드: 전체 검사 PASS(최종 코드), stamp `02aa9a90`, runid 789746849, reloc 게이트 PASS, `nm -u` 는 R5d 빌드와 동일(20), **설치됨**(주입 키 없음).  재부팅 대기.

## 10. 실기 PASS (2026-09-19, 부팅 e4582e2b, build 02aa9a90)
`check_cp.py build/r5/boot-e4582e2b.full.log --tail-submit 16` → PASS.  R5 전체 + NEGCTL 뒤 SUBMIT 16 → **STOP 이 wptr 16 에서 깨끗이**:
`ptrs rafter=16 roff=00000000 woff=00000010` — CSQ 를 끈 뒤 RPTR 0·WPTR 유지(**"CSQ 끄기 → RPTR 0" 두 번째 관측**, 첫째는 eae3072b), 마지막 RECORD `rptr 0 wptr 16`,
순환 `n=1 verdict=0`.  옛 코드였다면 이 STOP 은 거짓 걸쇠였다.

## 11. 종료 화면 — 정상 (operator 보고 2026-09-19, 내 착각 정정)
operator: "종료화면에 콘솔은 안보였습니다 … **종료 화면과 콘솔화면은 다른겁니다.  정상적인 재부팅 시 보이는 종료화면이었어요.  openstep 은 종료시
그래픽 화면이 보이지 일반적인 text mode 가 나오지 않습니다.**"
- 내가 틀린 것: OPENSTEP 의 종료 화면을 텍스트 콘솔로 여겨 "콘솔이 안 보였다 = 기준 미달" 로 읽고 미해결로 적었다.  OPENSTEP 은 종료 때 **그래픽 종료 화면**을
  보이고 텍스트 모드가 나오지 않는다(operator).  관찰은 **정상 재부팅의 종료 화면** — 정상.
- 이 관찰이 말하는 것: 종료 경로에서 화면이 정상 종료 화면을 보였다.  말하지 않는 것: 우리 복귀(`revertToVGAMode`)가 VGA 텍스트 레지스터를 되돌렸는지 — 그 뒤에
  보이는 텍스트가 없으므로 화면으로는 볼 수 없다(복원 논리는 R2c 순환이 바이트 단위로 증명, `docs/R2_CLOSEOUT.md` 1 행 16).
