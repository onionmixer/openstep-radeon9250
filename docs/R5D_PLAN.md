# R5d — CP 실패·해제 경로 (계획, 코딩 전, 교차검토 대상, 2026-09-18)

입력: `PLAN.md` R5 의 R5d 항과 Gate, `docs/R5_PLAN.md`(특히 7-1 E1, 7-2 B1·B3·B10·B14, 8, 12, 13), R5 실기 PASS(부팅 fdca7cd1,
build 65b66543).  R5 가 정상 경로(START→SUBMIT→STOP)를 닫았다.  R5d 는 **실패 경로**를 실기에서 한 번 실제로 지나가게 한다.

## 0. 한 줄 요약

실제 제출이 끝난 **뒤** 드라이버가 스스로 "대기가 넘쳤다" 고 판정하게 하는 **주입 연산 하나**(INJECT)를 옵트인 키 뒤에 두고,
그 걸쇠 이후 모든 경로(제출·모드 순환·엔진·걸쇠 STOP·종료 복귀·다음 부팅)가 계획대로 거절·정지·회복하는지 한 부팅에서 본다.
하드웨어를 망가뜨리는 주입(잘못된 PTE, 멈춘 CP)은 하지 않는다.

## 1. 확인한 사실

| # | 사실 | 근거 |
|---|---|---|
| F1 | 걸쇠는 RAM 먼저(`c->latched = 1`), 그다음 `RBBM_STATUS` 읽기 하나 | `osrdn_cp.m` `cpLatch` |
| F2 | 걸쇠 뒤 STOP 은 `CSQ_CNTL = 0` 쓰기 하나 + `RBBM_STATUS` 읽기 하나, **GART·MC 는 그대로**, 블록은 해제하지 않음 | `cpStopLatched`, `docs/R5_PLAN.md` 7-1 E1·7-2 B1 |
| F3 | 걸쇠면 RECORD 외 모든 CP 연산은 `CP_WHY_LATCHED` 로 거절; RECORD 는 PLL 을 읽지 않는다 | `osrdn_cp_run`, `cpRecord` |
| F4 | 걸쇠면 모드 순환은 **클레임 뒤·복귀 전**에 `MODE_WHY_CP` 로 거절, 엔진 연산은 `ENG_RC_CP` | `osrdn_mode.m` 순환·엔진 래퍼 |
| F5 | 커널 복귀(`revertToVGAMode`)는 CP 정지(걸쇠면 CSQ 쓰기 하나) 뒤 모드 복귀를 **계속** 한다(CRTC·PLL·DAC — GART 와 무관) | `OSRDNDisplay.m` `revertToVGAMode`, `modeRevertBody` |
| F6 | MAP 게이트 실패 → unmap → POST(걸쇠 아님)는 **이미 실기에서 한 번 지나갔다**(부팅 eab8c318, 되돌린 뒤 RECORD 로 GART 꺼짐·AGP 복원 확인) | `docs/R5_PLAN.md` 12-1 |
| F7 | writeback 둘 다 꺼져 있어 GPU 가 시스템 메모리에 쓰는 경로가 없다 — "늦은 쓰기" 는 블록 대조(예비·카나리·가드·링=사본)로 본다 | `docs/R5_PLAN.md` 8, 13 |
| F8 | `AIC_STAT` 이 R5 실행 중 4→6(비트 1) — 정의 미상, 미해결 | `docs/R5_PLAN.md` 13 |

**PLAN.md 와 다른 점(검토 받을 것)**: PLAN R5d 문구는 "유휴 실패여도 CSQ 끔 → writeback 끔 → CP 정지/리셋 → GART 해제 → 링 해제 →
`BUS_MASTER_DIS` 스냅샷" 이다.  R5 교차검토 E1 이 이것을 뒤집었다 — 멈춘 CP 가 페치 중이면 GART 를 끄는 순간 번역 없는 주소로 나가고,
AGP 창을 되돌리면 응답 없는 구간(master-abort)이 된다.  그래서 **걸쇠 뒤에는 CSQ 만 끄고 GART·블록은 부팅 끝까지 둔다**, 회복은 재부팅.
R5d 는 이 E1 규칙을 시험한다(PLAN 문구는 이 계획 확정 뒤 고친다).

## 2. 결정

### D1. 주입 = INJECT 연산 하나 (op 9), 키 `"RDN CP Inject" = "Yes"` 뒤
- 동작: SUBMIT 과 **같은 준비·표지·센티넬·WPTR 쓰기**, RPTR 따라잡기와 유휴 대기도 **그대로 성공까지** 기다린다(= 실제 제출이 끝났다는 증명),
  그다음 되읽기 **대신** `cpLatch` + `why = CP_WHY_INJECTED`, `injectCount++`, 반환 `CP_RC_LATCHED`.
- 이유: 걸쇠 기계를 시험하되 GPU 는 건강하고 유휴인 상태에서 — 페치 중 걸쇠(진짜 행)는 안전하게 만들 수 없어 **시험하지 않는다**(한계로 기록).
- 키 둘: `"RDN CP Test"`(R5, 있음) **와** 새 `"RDN CP Inject"` 가 모두 Yes 일 때만.  이 빌드의 표에만 넣고 R5d 끝나면 뺀다.
- 한 부팅에 한 번(`injectCount` 가 1 이면 거절 — 어차피 걸쇠라 두 번째는 `LATCHED` 로 거절된다; 규칙은 명시만).

### D2. 기록 추가 (판정 아님)
- 연산 끝 기록(R5-fix1 G3)에 `AIC_STAT` 을 더한다 — CSQ 읽기와 같은 조건(걸쇠·엔진 걸쇠 아님, idle 먼저).  F8 을 연산 단위로 좁힌다.
- state 줄에 `inject=` 계수.

### D3. 실기 절차 (한 부팅, 연산마다 새 runid·`sync`, 첫 **예상 밖** 결과에서 멈춤)
1. RECORD → LOAD → MAP → RECORD → RESET → RECORD → START → SUBMIT 1024 (R5 와 같음: 건강함 증명)
2. **INJECT 1024** → 기대 rc 3(LATCHED), why INJECTED, state RUNNING·latched 1, 표지는 CP 가 실행했으므로 SCRATCH_REG0–2 = 표지
3. 거절 확인(각각 기대값): SUBMIT → REFUSED/LATCHED, MAP·RESET·START·LOAD → REFUSED/LATCHED, INJECT → REFUSED/LATCHED,
   `rdnr2b0 cycle` → 순환 거절(`MODE_WHY_CP`, 모드 레지스터 쓰기 0), `rdnr2b0 engine record` → `ENG_RC_CP`
4. STOP → rc 3(LATCHED), 이후 RECORD: `csq` 모드 0, **`aic` 비트 0 = 1 그대로**(E1), `agploc = ffffffc0` 그대로, s0–s2 = 주입 제출의 표지,
   블록 불일치 0, 링 = 사본
5. 60 초 뒤 RECORD 한 번 더: 4 와 같음(늦은 쓰기 없음), `rbbm` 유휴
6. operator 재부팅 — **종료 화면에서 콘솔 복귀 관찰**(걸쇠 상태의 커널 복귀, F5)
7. 다음 부팅(키 그대로): RECORD 한 번 — 부팅 기준값(`agploc=27ff2000`, `aic=0`, `csqstat=02000603`)으로 돌아왔는지, WindowServer·커서 정상,
   그리고 R5 정상 절차를 **한 번 더**(RECORD→…→STOP→RECORD→cycle) — 걸쇠 부팅 뒤 회귀 없음
8. R5d 뒤 빌드: `"RDN CP Inject"` 키를 뺀 표로 재설치(기본 꺼짐 원칙)

### D4. 판정기 `tools/r5/check_r5d.py`
- 부팅 A(주입): D3-1~5 의 연산 목록·rc·why 정확 일치, `inject=1`, 주입 제출의 표지 되읽기(RECORD 의 s0–s2)·독 불변, 걸쇠 뒤 RECORD 의 aic 비트 0·agploc,
  두 RECORD 동일(블록·링·레지스터), 순환 거절 줄(`RDN-R2B cycle ... why=` MODE_WHY_CP, 쓰기 계수 0), 엔진 거절 rc.
- 부팅 B(회복): 기준값, R5 `check_cp.py` 가 PASS.
- 자체 시험: 합성 로그 + 변이(주입 없이 걸쇠, 걸쇠 뒤 제출 수락, 걸쇠 STOP 이 GART 를 끔, 늦은 쓰기, 순환이 복귀함, 부팅 B 기준값 불일치 …).

### D5. 호스트 검사
- `sim_r5.py`: INJECT 경우 — 준비·제출·따라잡기 뒤 걸쇠, 걸쇠 뒤 쓰기 1(STOP 의 CSQ)·읽기 규칙, 키 둘 중 하나 없으면 거절;
  변이: 따라잡기 전에 걸쇠(제출 증명 없음), 키 하나만 검사, 걸쇠 없이 반환, `injectCount` 없음, 걸쇠 STOP 이 unmap.
- `sim_r2b.py`: 걸쇠 뒤 순환 거절이 모드 레지스터를 쓰지 않음(있으면 재사용), 걸쇠 상태 커널 복귀가 모드 복귀를 계속함.
- `check_r5_src.py`: INJECT 가 키 둘을 모두 보는지, `cpInject` 가 `cpSubmit` 과 같은 준비 함수를 쓰는지(복제 금지).
- reloc 게이트: 새 함수의 호출자 표.

## 3. 위험

| 위험 | 대응 |
|---|---|
| 걸쇠 상태로 종료·재부팅 — GART 켜진 채 PCI 리셋 | 블록은 해제되지 않아 모든 항목이 응답하는 메모리, CP 는 유휴·CSQ 꺼짐.  재부팅의 PCI 리셋이 카드를 초기화한다고 **가정** — D3-7 이 확인 |
| 걸쇠 뒤 RECORD 가 레지스터를 많이 읽는다(F3) | 유휴 확인 뒤에만(RBBM 먼저).  주입은 건강한 CP 에서 하므로 읽기가 안 돌아올 이유가 없다 |
| 주입 키가 다음 빌드에 남음 | D3-8, `check_r5_src` 가 표의 키를 빌드 종류와 대조 |
| WindowServer 가 걸쇠 뒤 모드 변경 시도(Configure 등) | 순환·진입 거절 경로(F4) — 시험 중엔 Configure 를 열지 않는다 |

## 4. 교차검토에 물을 것
1. E1 규칙(걸쇠 뒤 GART·블록 유지, 재부팅 회복)을 R5d 가 시험하는 것이 맞는가, PLAN 원문(GART 해제)으로 가야 하는가.
2. 건강한 CP 에서의 주입이 "실제 제출 뒤 실패 주입" 게이트를 충족하는가; 빠진 실패 종류(PRE_TIMEOUT·POST 는 R5 에서 실기로 지나갔는가).
3. 걸쇠 뒤 RECORD 의 넓은 읽기가 규칙 "진단 읽기 하나" 와 충돌하는가.
4. 재부팅 전 60 초 관찰로 "늦은 쓰기 없음" 을 말할 수 있는가.
5. 판정기가 속을 수 있는 곳(낡은 로그, 다른 부팅의 줄).

## 5. operator 결정 (2026-09-18 22:1x)
codex 는 2026-09-19 19:23 까지 사용량 한도(이 계획으로 실행해 확인 — "You've hit your usage limit").  **operator: "내부 agent 로 진행"**
— 계획 교차검토는 내부 agent, 판정은 전 건 원문 재확인.

## 6. 계획 검토 판정 (내부 agent 1 건; 인용한 행 전부 열어 확인)

### 6-1. 내가 틀린 것
- **F3**: "걸쇠면 RECORD 외 모든 연산 거절" — STOP 은 걸쇠여도 실행된다(`osrdn_cp.m` `osrdn_cp_run` 의 STOP 분기가 걸쇠 검사보다 앞), RECORD 는 걸쇠 뒤에도
  `CSQ_CNTL/MODE/STAT` 을 읽는다(`cpRecord` 첫 부분) — R5-fix1 12-6 #1(걸쇠 뒤 CSQ 읽기 금지)과 모순.
- **F7**: "GPU 가 시스템 메모리에 쓰는 경로가 없다" 는 과장.  정확히는: GPU 의 시스템 메모리 접근은 전부 GART 를 거치고(`DIS_OUT_OF_PCI_GART_ACCESS`, AGP 창 치움)
  모든 PTE 가 블록 안을 가리키므로, 어떤 쓰기도 블록 안에 떨어지고 `cpCheckBlock` 이 본다.
- **D3 가 R5 규칙과 충돌(B1)**: `docs/R5_PLAN.md` 9-2 "걸쇠면 더 부르지 않고 순환도 하지 않음", 7-2 B1(걸쇠 = CSQ 쓰기 하나 + RBBM 읽기 하나),
  도구 `tools/r5/rdnr5cp.m` 22–23 행이 이를 말한다 — D3-3~5 는 걸쇠 뒤에 SUBMIT·MAP·cycle·engine·RECORD 를 부른다.  PLAN 중단 조건 6(자동 대조)의 사례.

### 6-2. 판정

| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| B1 | 걸쇠 뒤 호출은 **주입 걸쇠에만** 허용, 진짜 걸쇠 뒤 RECORD 는 거절(또는 RBBM 만) | ✅ | 위 6-1 |
| M1 | 재부팅 회복 증거가 약하다 — 이 드라이버만 쓰는 값(s0–s2, s5, rbbase, ptbase, rbcntl, rptraddr, isync, saddr, aic, lo, hi, agploc)으로 판정, meaddr 는 제외(1c/0 로 부팅마다 다름) | ✅ | eab8c318 로그 130–134 행(되돌린 뒤: rbbase 20000000·s5 5a5a0005·ptbase 40000·isync 33) → fdca7cd1 첫 RECORD 89–94 행(부팅값) — 이 세션에서 둘 다 읽음; meaddr 는 eab8c318 99 행 1c, fdca7cd1 94 행 0 |
| M1b | 재부팅은 **warm `reboot`** 으로, 방법을 기록(전원 재시작이면 증명 안 됨) | ✅ | eab8c318 로그 2 행 "rebooted by root" |
| M1c | 카드가 리셋되지 않았다면: MAP 이 `ffffffc0` 을 원래 값으로 저장한다 → MAP 게이트에 "`MC_AGP_LOCATION` 이 이미 `ffffffc0` 이거나 `TRANSLATE_EN` 이 이미 켜져 있으면 거절" | ✅ | `cpMap` 의 저장 순서 확인 |
| M2 | INJECT 가 되읽기를 건너뛰면 제출 증명이 사라진다(`got[]` 은 연산마다 0) → **SUBMIT 전체(되읽기·독·블록)를 한 뒤** 걸쇠; 판정기는 `wRptr`·`wIdle` 한도 0 을 요구; 별도 함수 말고 `cpSubmit` 꼬리에 | ✅ | `osrdn_cp_run` 초기화 확인 |
| M3a | "해제 순서 로그" 가 없다 → CP 단위의 연산별 MMIO 쓰기·읽기 계수 | ✅ | CP 단위의 모든 MMIO 가 `rdnMmio*` 직접 호출 — 계수 래퍼로 |
| M3b | PLAN R5d **Gate 문구 자체**도 고쳐야(유휴 시도·`BUS_MASTER_DIS` 복원은 이 설계에 없음 — `BUS_CNTL` 은 읽기만) | ✅ | `cpMap` 의 `BUS_CNTL` 은 읽기만 |
| M3c | 출처 사슬: 판정기가 빌드 id 와 키를 봐야 | ✅ | 부팅 때 키 두 개를 한 줄로 로그, 도구 출력의 `build=` 대조 |
| M4 | 판정기가 속는 곳: 부팅은 마지막 select 줄로, cycle 줄엔 boot= 없음 → 부팅 A·B nonce 명시, A≠B, 연산마다 begin 줄 | ✅ | `check_cp.py` parse 확인 |
| m1 | 연산 범위 검사(`op > CP_OP_STOP`)에 op 9 | ✅ | 두 곳 |
| m2 | `injectCount` 거절은 도달 불가(걸쇠 검사가 먼저) | ✅ | 규칙 삭제 |
| m3 | 걸쇠 뒤 RECORD 는 `aic==3` 정확·ptbase/lo/hi 불변 | ✅ | — |
| m4 | 순환 거절의 증거는 `cycle n=0 why=15`(쓰기 계수 없음) | ✅ | `osrdn_mode.m` 순환 경로 |
| m5 | `"RDN CP Test"="Yes"` 가 커밋된 두 표에 있음 — PLAN §4 기본 꺼짐과 어긋남 | ⚖️ | 두 표 22 행 확인.  시험 빌드 관행(R4 키도 같음) — **배포(P) 전 전부 끄기**를 할 일 목록에 |
| F5 | 클레임이 잡힌 동안 종료가 오면 `osrdn_mode_cp_stop` 은 그냥 돌아간다 | 기록만 | 잡은 쪽의 `modeFinish` 가 복귀 작업을 하지만 `modeWritten` 일 때만 — CP 연산은 라이브 모드에서만 가능하므로 사실상 닫힘 |
| Q2 | 실기에서 한 번도 안 지나간 실패: PRE_TIMEOUT, 대기로 인한 POST, CHECK_FAILED, 진짜 대기 걸쇠 | 기록 | R5 두 부팅 로그에서 rc≠0 은 eab8c318 의 MAP(게이트) 하나 — 이 세션에서 판정기 출력으로 확인 |
| Q4 | 60 초 관찰은 증거가 아니라 일관성 확인(유휴 대기가 성공했으므로 구조상 비행 중인 것 없음) | ✅ | 문구 고침 |
| (d) | 주입 직후(CSQ 켜진 채) RECORD 하나; 걸쇠 뒤 WindowServer·커서 육안; **주입 키 없는 표를 재부팅 전에 설치**해 부팅 B 가 D3-8 도 겸함(`closed=yes fresh live` 는 "this boot keeps the driver already in memory; the next boot gets the new one" — R5 설치 출력) | ✅ | 설치 출력 문구는 이 세션의 R5 설치 때 읽음 |

## 7. 개정 명세 (6 반영 — 2 절과 충돌하면 이 절이 이긴다)

- **INJECT(op 9)** = SUBMIT 전체(준비·표지·센티넬·WPTR·따라잡기·유휴·되읽기·독·블록 대조) → 그 판정이 깨끗할 때만 `cpLatch`, `latchInjected = 1`, `why = CP_WHY_INJECTED`,
  `injectCount++`, rc `LATCHED`.  판정이 틀리면 SUBMIT 과 같이 CHECK_FAILED(걸쇠 없음).  구현은 `cpSubmit` 꼬리의 분기 하나.  키 두 개.
- **걸쇠 뒤 규칙**: `latchInjected` 가 아니면(진짜 걸쇠) RECORD 도 거절(읽기 0); 주입 걸쇠면 RECORD 허용.  다른 연산은 둘 다 `LATCHED` 거절(하드웨어 접근 0).
  STOP 은 둘 다 `cpStopLatched`.  연산 끝 CSQ·AIC 기록은 걸쇠면 안 함(그대로).
- **MMIO 계수**: CP 단위의 모든 MMIO 를 계수 래퍼(`cpRd32`/`cpWr32`/`cpWr8`)로 — 연산마다 `wr=`·`rd=` 를 state 줄에.  걸쇠 STOP 은 `wr=1 rd=1` 이어야 한다.
- **MAP 게이트 추가**: `MC_AGP_LOCATION == ffffffc0` 이거나 `AIC_CNTL` 비트 0 이 이미 켜져 있으면 거절(아무것도 안 씀).
- **부팅 줄**: `RDN-R5 keys boot= test= inject= build=`.
- **절차**: 부팅 A = R5 앞부분(…SUBMIT 1024) → INJECT → RECORD(CSQ 켜진 채) → 거절 확인(SUBMIT·MAP·RESET·START·LOAD·INJECT, cycle, engine record) → STOP(`wr=1 rd=1`) →
  RECORD → 60 초 → RECORD → WindowServer·커서 육안 → **주입 키 없는 표로 설치** → operator warm `reboot`(종료 화면 콘솔 관찰, 방법 기록).
  부팅 B = 키 줄 `inject=0`, 첫 RECORD 가 부팅값(M1 목록), INJECT → REFUSED/KEY, R5 정상 절차 전체 + cycle.
- **판정기** `check_r5d.py <A 로그> <B 로그> --boot-a N --boot-b N`: nonce·빌드·키 줄, 연산마다 begin, A≠B, 위 기대값 전부, 변이.
- **PLAN.md R5d 문구·Gate** 를 E1 에 맞게 고친다(이 개정과 함께).

## 8. 구현과 실기 전 코드 검토 (2026-09-18)

### 8-1. 만든 것
- `osrdn_cp.h/.m`: `CP_OP_INJECT`, `CP_WHY_INJECTED`·`CP_WHY_NOT_FRESH`, `cpSubmit(..., inject)` 꼬리(깨끗한 되읽기 뒤에만 걸쇠), 진짜 걸쇠 뒤 RECORD 거절,
  MAP 신선도 게이트, 연산 끝 `AIC_STAT` 기록, **MMIO 계수**(접근자 이름을 가리는 함수형 매크로 셋 — 소스 문구·reloc 호출 그래프는 그대로).
- `osrdn_modelog.m`: `inject` 이름, `RDN-R5 io wr= rd= aicstat= inject= injected=` 줄, INJECT 에도 marks/got 줄.
- `OSRDNDisplay.m`: `"RDN CP Inject"`(CP 키와 함께만), 부팅마다 `RDN-R5 keys boot= test= inject= build=`.
- 표: A 빌드는 두 표에 `"RDN CP Inject" = "Yes"`; B 빌드는 없음.
- 도구 `rdnr5cp inject <len>`; 판정기 `tools/r5/check_r5d.py`(부팅을 nonce 로 자름, 자체 시험 변이 26).
- 검사: `sim_r5.py` R5d 묶음 + 변이 10, `check_r5_src.py` 규칙 `r5d-count`·`r5d-key` + 변이 4, `check_cp.py` 가 inject·io·keys 를 앎.

### 8-2. 구현 중 잡은 것 (내 결함)
- 판정기 `cut()` 이 select 줄부터 잘랐다 — 실기에서는 **block·keys 줄이 select 줄보다 먼저** 찍힌다(fdca7cd1 로그 17–18 행).  합성 로그가 순서를 거꾸로
  만들어 가렸다 → nonce 로 자르고 합성 로그를 실기 순서로.
- `r5d-key` 규칙이 문자열을 지운 본문에서 `"Yes"` 를 찾아 기준에서 실패했다(그 결과 모든 변이가 그 규칙으로 "잡힌" 것처럼 보였다) → 원문에서.

### 8-3. 코드 검토 판정 (내부 agent; 인용한 행 전부 열어 확인)
| # | 지적 | 판정 | 조치 |
|---|---|---|---|
| B1 | INJECT 는 marks/got 줄을 찍지 않는데(`osrdn_modelog.m` 조건이 SUBMIT·NEGCTL 만) 판정기는 요구 — 실기의 올바른 실행이 FAIL | ✅ | 로그 조건에 INJECT 추가(계획 M2 의 제출 증명이 로그에 남음) |
| B2 | 엔진 거절은 `osrdn_engine_run` 을 안 거쳐 로그 줄의 연산 이름이 낡은 값(`bad`) — 판정기의 `RDN-R4 record` 정규식이 못 봄 | ✅ | 판정기가 이름 무관하게 rc 만; 합성 로그도 `bad` 이름으로 |
| m2 | 순환·엔진 거절이 INJECT **뒤**인지 판정하지 않음(MAPPED 에서도 같은 값) | ✅ | INJECT 결과 줄 뒤에서만 세고, 부팅 전체에서 한 번씩만 |
| m3 | 부팅 A 앞 여덟 연산은 rc 만 봄 | ✅ | MAP/RESET/START 게이트 마스크·HI, SUBMIT 표지 |
| m4 | "rebooted by" 가 마지막 RDN 줄 뒤여야 한다는 가정 | ✅ | INJECT 뒤 어디든 |
| m5 | 두 RECORD 비교에 aicstat 포함 | ✅ | 제외(미해결 기록값) |
| m6 | CSQ 켜진 채 `CSQ_CNTL` 모드 비트가 되읽히는지 실측 없음 | ✅ | 판정 아닌 기록(notes) |
| m1 | 걸쇠 없는 STOP 안에서 진짜 걸쇠가 서면 읽기 2(`cpLatch`+`cpStopLatched`) | 기록만 | R5 부터; 판정기의 wr=1 rd=1 은 이미 걸쇠인 STOP 에만 |
| m7 | RECORD 의 SCLK(`osrdn_pll_peek`)는 계수 밖 | 기록만 | 걸쇠면 RECORD 가 PLL 을 안 읽는다 |
| — | 매크로·C89·reloc 호출 그래프 | 결함 없음 | 검토자가 사용처 전부 확인 |

### 8-4. 빌드 (2026-09-18)
- 전체 검사 `tools/check-all.sh` PASS(최종 코드).
- **A**(두 키): stamp `9ec1688b`, runid 789739652 → 빌드 트리가 뒤의 B 로 덮여 **같은 소스를 runid 789739821 로 다시 묶어** 빌드(빌드 스크립트가 runid 재사용을 거절 — 설계대로).
  reloc 게이트 PASS, 두 A reloc 바이트 동일, `nm -u` 는 65b66543 과 동일(20).  **설치됨**(`closed=yes fresh live`), 설치된 두 표에 `"RDN CP Inject" = "Yes"`.
- **B**(주입 키 없음, 저장소의 최종 상태): stamp `ce029e90`, runid 789739722, reloc 게이트 PASS; A 와 reloc 차이는 8 바이트 — 전부 두 곳의 빌드 스탬프 워드(python 대조).
  부팅 A 절차 뒤 설치할 때는 빌드 트리를 B 로 되돌려야 하므로 **새 runid 로 다시 묶어** 빌드한다.

## 9. 부팅 A (2026-09-18, eae3072b, build 9ec1688b) — 재부팅 전 판정: "rebooted by" 줄 하나만 미충족(예상대로)

로그 `build/r5/boot-eae3072b.pre.log`.  키 줄 `test=1 inject=1 build=9ec1688b`, 블록 `phys=00040000 ok`.
- R5 앞부분 8 연산 rc 0.  계수: LOAD `wr=513`(인덱스 1 + 마이크로코드 512), MAP `wr=16`.
- **INJECT**(n=9): rc 3, why 22, latched·injected, `inject=1`, 표지 3 개 되읽힘(`d8a3d848 7afa5283 9c32ccda`), REG5 독, 대기 한도 0, 블록 불일치 0, `wr=4`.
- **operator 절차 이탈(내 실수)**: 출력만 버리려고 붙인 `… | head -0` 이 INJECT 를 **한 번 더 실행**했다(n=10).  걸쇠 뒤라 `rc=1 why=3 wr=0 rd=0` — 카드 무접촉,
  계획의 거절 여섯 중 INJECT 거절이 순서만 앞당겨졌다.  판정기는 거절 여섯을 **순서 무관·정확히 한 번씩**으로 고쳤다(자체 시험: 다른 순서 통과, 누락·중복 실패).
- RECORD(n=11, CSQ 켜진 채): **`CSQ_CNTL = 42010080` — 켜진 CSQ 의 모드 비트 4 가 되읽힌다(처음 실측)**, s0–s2 = 주입 표지, `wr=0`(걸쇠라 PLL 안 읽음).
- 거절 SUBMIT·MAP·RESET·START·LOAD: 전부 `rc=1 why=3 wr=0 rd=0`.  순환: `cycled live=0` → `cycle n=0 why=15`.  엔진: `RDN-R4 bad … rc=6`(이름은 낡은 값, 8-3 B2 예측대로).
- **걸쇠 STOP: `rc=3 wr=1 rd=1`** — 해제 순서 증거.
- RECORD 두 번(60 초 간격): 동일, `csq` 모드 0, **`aic=3`·ptbase·lo·hi·`agploc=ffffffc0` 그대로(E1)**, s0–s2 주입 표지, s5 독, 블록 불일치 0.
- **AIC_STAT(미해결 R5 §13)**: RESET 뒤까지 4, **START 직후 7**(비트 0·1) — CP 의 첫 GART 페치와 겹친다; 걸쇠 뒤 RECORD 도 7.
- **새 사실 — CSQ 를 끄면 `RB_RPTR` 이 0 으로 읽힌다**(걸쇠 STOP 은 CSQ_CNTL 쓰기 하나뿐인데 rptr 0, wptr 0x810).  이것은 **깨끗한 STOP 의 잠복 결함**을 뜻한다:
  `cpStop` 은 CSQ 를 끈 **뒤** rptr==wptr 를 다시 본다 — R5 PASS(fdca7cd1)는 두 바퀴 뒤 wptr 가 우연히 0 이라 통과했다.  wptr≠0 이면 거짓 걸쇠(안전 쪽 실패).
  부팅 B 의 R5 절차도 같은 일정(wptr 0 으로 끝남)이라 이번엔 영향 없음.  **수정은 다음 작업(계획→검토→코드)**.
- 이후 B 빌드(stamp ce029e90) 를 새 runid 789740875 로 빌드·게이트·설치(A 와 reloc 차이는 스탬프뿐, 앞의 B 와 바이트 동일).

## 10. R5d 실기 PASS (2026-09-18) — `tools/r5/check_r5d.py` PASS

`check_r5d.py build/r5/boot-eae3072b.full.log build/r5/boot-e457149e.full.log --boot-a eae3072b --boot-b e457149e --build-a 9ec1688b --build-b ce029e90` → PASS.
- 재부팅: `15:56:27 reboot: rebooted by root`(warm).  operator 관찰: 종료 때 **정상 재부팅의 그래픽 종료 화면**(2026-09-19 보고; OPENSTEP 은 종료 때 텍스트 모드가 나오지 않는다 — `docs/R5_STOPFIX_PLAN.md` 11).  걸쇠 상태의 WindowServer·커서 육안은 보고 대기.
- 부팅 B(e457149e, build ce029e90): 키 줄 `test=1 inject=0`.  첫 RECORD — 이 드라이버만 쓰는 값 전부 부팅값: `aic=0`, ptbase·lo·hi 0, `agploc=27ff2000`,
  s0–s2 `cdcdcdcd`(주입 표지 아님), s5 독 아님, `rbbase=cdcdcdcc`, rbcntl·rptraddr·isync 0, `csqstat=02000603`, `aicstat=4` — **warm reboot 가 GART·CP·스크래치를 되돌린다**.
- INJECT → `rc=1 why=1`(키), `wr=0`.  이어 R5 정상 절차 전체 rc 0, cycle `n=1 verdict=0` — 걸쇠 부팅 뒤 회귀 없음.
- 남은 것: (1) **깨끗한 STOP 의 잠복 결함**(9 절 — CSQ 끈 뒤 rptr 비교) 수정, (2) AIC_STAT 비트 0·1 의 뜻(START 직후 켜짐), (3) PLAN R5 게이트의 한계 기록 — 페치 중 걸쇠는 시험하지 않았다.
