# R6b — R200 가위: `RE_TOP_LEFT` 는 언제 자르는가 (계획, 코딩 전, 교차검토 대상, 2026-09-19)

입력: `docs/R6_PLAN.md` 9(부팅 e3ec4d0c 실측), 참고 조사(내부 agent, 아래 인용은 이 세션에서 연 것만).

## 0. 한 줄 요약

R6a 경우 C 에서 가위의 끝(`RE_WIDTH_HEIGHT`)만 적용되고 왼쪽 위(`RE_TOP_LEFT`)는 적용되지 않았다.  참고는 `RE_TOP_LEFT` 를 0 아닌 값으로 쓸 때 **언제나**
`R200_RE_CNTL.SCISSOR_ENABLE`(비트 1)을 켠다.  가설 H: **`RE_WIDTH_HEIGHT` 는 늘, `RE_TOP_LEFT` 는 `SCISSOR_ENABLE` 이 켜져 있을 때만 자른다.**
경우 C 와 **`RE_CNTL` 한 값만** 다른 경우 D 로 한 부팅에서 가린다.

## 1. 사실 (이 세션에서 연 것)

| # | 사실 | 근거 |
|---|---|---|
| S1 | 실측: 경우 C(기하 (0,0)–(64,32), `RE_TOP_LEFT=(3<<16)\|5`, `RE_WIDTH_HEIGHT=(20<<16)\|36`, `RE_CNTL=0`) → [0,37)×[0,21) 777 워드 | `docs/R6_PLAN.md` 9 |
| S2 | Mesa 6.5.3 R200 의 `RE_CNTL` 초기값 = `PERSPECTIVE_ENABLE \| SCISSOR_ENABLE`(항상 켬); GL 가위는 DRM 클립 사각형(`RE_TOP_LEFT`/`RE_WIDTH_HEIGHT`)으로 | `r200_state_init.c` 669–670 행 |
| S3 | mesa-amber: 가위 갱신 때 `RE_CNTL \|= SCISSOR_ENABLE` 을 **강제**하고 `SCI_XY_1`=`RE_TOP_LEFT`, `SCI_XY_2`=`RE_WIDTH_HEIGHT`(둘 다 끝 포함) | amber `r200_state.c` 1578–1600 행, `r200_state_init.c` 821–822 행 |
| S4 | FreeBSD R200 깊이 지우기(우리 선례)는 `RE_CNTL=0` 이지만 기하 = 클립 사각형이라 `RE_TOP_LEFT` 가 무시돼도 드러나지 않는다; 주석 "Funny that this should be required -- sets top-left?" | FreeBSD `radeon_state.c` 1223–1226 행 |
| S5 | xf86 R200 합성은 `RE_WIDTH_HEIGHT` 만 쓴다(너비·높이 그대로, −1 없음) | xf86 `radeon_exa_render.c` 1124–1127 행 |
| S6 | Linux KMS 의 명령 검사기는 `RE_WIDTH_HEIGHT` 의 Y(11 비트)만으로 버퍼 크기를 제한하고 `RE_TOP_LEFT` 는 보지 않는다 | Linux `r100.c` 1671–1675 행 |
| S7 | 명시적 규칙("TOP_LEFT 는 SCISSOR_ENABLE 일 때만")은 어느 참고에도 없다 — H 는 추론 | 조사 결과(NOT FOUND) |

## 2. 설계

- ZCLEAR 에 **경우 D(4)** 를 더한다: 경우 C 와 전부 같고, 선례 상태 블록의 `R200_RE_CNTL` 값만 `0 → 2`(`SCISSOR_ENABLE`, `r200_reg.h` 269 행).  다른 비트(`PERSPECTIVE_ENABLE` 등)는 켜지 않는다(변수 하나).
- 기대(오라클·판정기):
  - C: [0,37)×[0,21) — 이제 **실측된 사실**(재현 확인용).
  - D: H 가 맞으면 [5,37)×[3,21)(576 워드).  판정기는 D 의 결과를 가설 표(H / C 와 같음 / 기하 전체 / 기타)로 분류해 보고하고, H 일 때만 PASS.
- 안전: `RE_WIDTH_HEIGHT` 가 쓰기를 원점~끝으로 제한함은 S1 로 실측 — D 가 어느 가설이든 쓰기는 [0,37)×[0,21) 안(깊이 버퍼 안).
- 시뮬레이터 모형: H 를 따르게 고친다(`RE_TOP_LEFT` 는 `RE_CNTL` 비트 1 일 때만).  R6a 의 C 기대도 실측값으로 고친다.
- 실기 절차(한 부팅): RECORD → LOAD → MAP → RESET → START → ZPREP → ZCLEAR C → ZPREP → ZCLEAR D → STOP → RECORD → cycle.  판정 `check_r6a.py --procedure r6b`.

## 3. 교차검토에 물을 것
1. H 외에 S1 을 설명하는 다른 가설(예: `RE_TOP_LEFT` 가 R200 에서 다른 뜻, 레지스터 쓰기 순서, 원점 기준 좌표)이 있는가, D 가 그것들과 H 를 가르는가.
2. `RE_CNTL` 비트 1 만 켜는 것이 다른 동작(원근·스티플 등)에 영향을 줄 수 있는가.
3. 경우 D 에서 가위 좌표가 끝 포함/미포함 어느 쪽으로 해석될지(Mesa·amber 는 둘 다 끝 포함).

## 4. 계획 검토 판정 (내부 agent; 인용·수치 전부 재확인)

### 4-1. 내가 틀린 것
- §0 "참고는 **언제나** SCISSOR_ENABLE 을 켠다" — 우리가 따른 FreeBSD 깊이 지우기가 바로 `RE_CNTL=0` 에 0 아닌 TL 을 쓴다(S4 와 모순).  바른 문구: 0 아닌 TL 이 **자르기를 기대받는** 경로는 모두 켠다.
- §2 안전 근거: "S1 이 쓰기를 [0,37)×[0,21) 로 제한" — S1 은 `RE_CNTL=0` 의 동작이고 D 는 그것을 바꾼다(예: WH 가 TL 기준 상대값이면 [5,42)×[3,24)).  바른 근거: **기하 (0..64, 0..32) 자체가 깊이 버퍼 안** — 가장자리 한 픽셀 넘쳐도 최대 타일 주소 12300 < 16384(python), 가위는 덮는 영역을 줄일 뿐 늘리지 않는다.
- r6b 절차가 REC3D 를 모두 빼 D1 판정과 "RE_CNTL=2 가 실제로 들어갔다" 는 증거를 잃었다.

### 4-2. 판정
| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| E1 | C 뒤 REC3D 에 `26c0=00030005`·`1c44=00140024`·`1c50=0` — TL 쓰기는 들어갔다 | ✅ | 로그 282·279·280 행 |
| E2 | C 의 요약값과 맞는 777 칸 사각형은 [0,37)×[0,21) 하나(타일) | ✅ | python: 64×64 안 모든 777 칸 사각형 전수 |
| E3 | "TL 을 빼는 오프셋" 가설은 A 가 반박 | ✅ | python: A 에서 [0,32)×[0,18) 불일치 |
| E4 | 요약값은 일반적으로 충돌할 수 있다 → 분류기는 "사각형 적합" 으로, 모호·비사각형도 보고 | ✅ | 검토자의 전수 결과(7657 공유) — 분류기가 면적 같은 사각형 전수로 모호성을 스스로 보고 |
| M1 | REC3D 를 START 뒤·D 직후·끝에 | ✅ | — |
| M2 | 안전 근거를 기하로 | ✅ | 4-1 |
| M3 | D 판정은 사각형 적합(면적=변경 수인 모든 사각형) + 명명 표 | ✅ | — |
| M4 | 반박된 예측을 세탁하지 않기: 규칙 H 하나에서 A·B·C·D·E 를 모두 도출, 옛 규칙과 반박은 R6_PLAN 9 에 남김, C 가 [5,37)×[3,21) 로 오면 FAIL, 모형의 `1c50≠0` 문 대신 스트림 대조, RE_CNTL 변이 둘("C 가 2", "D 가 0"), 오라클 자체 시험을 "A==C" 에서 "A==D, C==E" 로 | ✅ | 아래 5 |
| m5 | 한 부팅에 A(같은 부팅의 D 비교 기준)·C′(D 뒤 C 재실행: 원인이 RE_CNTL 이고 늦은 효과가 없음, 다음 부팅을 위해 0 복귀)·E(`RE_CNTL=0`, TL=(20,12): D==C 일 때 "무시" 와 "서브픽셀 단위" 를 가름) | ✅ | E 는 기하가 버퍼 안이라 안전 |
| m6–m8 | 문구·R100 검사기 인용의 한계·코드 모양(경우별 `recntl` 필드, 상태 블록 복사 뒤 덮어쓰기) | ✅ | — |

## 5. 개정 명세 (4 반영 — 2 절과 충돌하면 이 절이 이긴다)
- **규칙 H**(오라클·모형 공통): 덮는 영역 = 기하 ∩ [x0, WHx]×[y0, WHy], x0,y0 = `RE_CNTL` 비트 1 이면 TL, 아니면 0.
  - A: TL (5,3)·기하=가위·`RE_CNTL` 0 → [5,37)×[3,21)(기하가 자름)  · B: 같은 사각형 z 0.5
  - C: 기하 (0,0)–(64,32), TL (5,3), `RE_CNTL` 0 → [0,37)×[0,21)(S1 실측과 일치)
  - **D**: C 와 같고 `RE_CNTL` 2 → [5,37)×[3,21)(A 와 같은 깊이 영역)
  - **E**: 기하 (0,0)–(64,32), TL (20,12), `RE_CNTL` 0 → [0,37)×[0,21)(C 와 같음)
- 드라이버: 경우 표에 `recntl` 필드, 상태 블록을 복사한 뒤 `RE_CNTL` 값만 덮어씀, 경우 1–5.
- 판정기 `check_r6a.py --procedure r6b`: RECORD → REC3D → LOAD → MAP → RESET → START → REC3D → (ZPREP→ZCLEAR) A → C → D → **REC3D**(1c50=2) → C′ → E → **REC3D**(1c50=0, 1c3c=0) → STOP → RECORD → cycle.
  경우마다 H 기대 대조 + **사각형 적합 분류**(면적=변경 수인 64×64 안 모든 사각형, 이름 붙은 후보: H·C 그대로·끝 미포함·TL 기준 상대·기하 전체·그리지 않음) 보고,
  D 는 같은 부팅의 A 요약값과도 직접 대조(타일 모형 무관).
- 시뮬레이터: 모형을 H 로, `1c50` 문 제거(스트림 대조가 경우별 값을 검사), 경우 1–5, 변이 "C 가 RE_CNTL 2 를 씀"·"D 가 0 을 씀" 둘 다 잡혀야.
- 안전: 기하가 버퍼 안(4-1).

## 6. 구현과 실기 전 코드 검토 (2026-09-19)
- 드라이버: `cpR6Case.recntl`, 경우 D·E, 상태 블록 복사 뒤 `w[5]`(=`R200_RE_CNTL` 값, `cpR6State[4]`=0x714=0x1c50>>2)만 덮어씀, 경우 게이트 1..`CP_R6_CASES`(5).
- 오라클: `covered()` = 규칙 H, 모든 경우를 여기서 도출; 자체 시험이 "A==D, C==E, C≠D" 와 "C = 실측 [0,37)×[0,21)".
- 시뮬레이터: 모형을 H 로(`RE_TOP_LEFT` 는 `RE_CNTL` 비트 1 일 때만), 모형의 `1c50` 문 제거 — 경우별 값은 스트림 대조; 변이 추가 "C 가 2", "D 가 0", "경우별 값을 안 씀", "E 의 TL 이 C 것"(모형이 못 보는 곳을 스트림이 봄) — 전부 잡힘.
- 판정기 `--procedure r6b`: 규칙 H 대조 + 사각형 적합(이름은 경우별로, 한 사각형에 두 해석이면 둘 다), D↔A·C↔C′ 같은 부팅 직접 대조, REC3D 로 `RE_TOP_LEFT`(D 뒤 00030005, 끝 000c0014)·`RE_CNTL`·`RB3D_CNTL`.
  R6a 실기 로그를 H 로 다시 판정 → PASS(H 가 첫 부팅을 모두 설명; 옛 규칙의 반박은 `docs/R6_PLAN.md` 9 에 그대로).
- 코드 검토(내부 agent): blocker·major 없음.  minor 5 모두 반영 — (1) `RE_CNTL` 되읽기는 실측된 적 없음: D 가 H 대로면 되읽기 0 은 FAIL 이 아니라 "되읽히지 않음" 기록,
  (2) REC3D 에서 `RE_TOP_LEFT` 판정, (3) 이름표를 경우별로(E 의 "TL 적용"·"1/16 단위"), (4) C↔C′ 비교, (5) TL 변이 고정; 도구의 상한 5 에 주석.
- 안전(검토 확인): `recntl` 은 0 또는 2 뿐, 기하 (0,0)–(64,32) 는 버퍼 안, 보조 가위 0.
- 빌드: 전체 검사 PASS(최종), stamp `168b2195`, runid 789791671, reloc 게이트 PASS, `nm -u` 동일(20), 스택 프레임 최대 572 B(R6a 와 같음).  **설치됨**, 재부팅 대기.

## 7. 실기 PASS (2026-09-19, 부팅 feca1cba, build 168b2195) — 가설 H 확인

`check_r6a.py build/r6/boot-feca1cba.full.log --boot feca1cba --build 168b2195 --procedure r6b` → **PASS**.  모든 연산 rc 0, 걸쇠 없음, STOP 깨끗, 순환 verdict 0.
- A: 576 워드 `a5ffffff`(wsum `726dc460`) — R6a 와 같은 값.
- C: 777 워드(wsum `9ec5efc1`) — **R6a 부팅과 같은 값, 재현**.
- **D(C + `RE_CNTL`=2)**: 576 워드, 요약값이 **같은 부팅의 A 와 완전히 같다** — `RE_TOP_LEFT` 가 `SCISSOR_ENABLE` 에서 자른다.
- C′(D 뒤 C): C 와 같다 — 늦은/달라붙는 효과 없음.  E(TL (20,12), `RE_CNTL` 0): C 와 같다 — TL 은 **무시**(서브픽셀 단위 해석 기각).
- D 직후 REC3D: `RE_CNTL=00000002`(**되읽힌다** — 처음 실측), `RE_TOP_LEFT=00030005`; 마지막 REC3D: `RE_CNTL=0`, `RE_TOP_LEFT=000c0014`, `RB3D_CNTL=0`.

**확정된 사실(R200/RV280 3D 가위)**: `RE_WIDTH_HEIGHT` 는 늘(끝 포함) 자르고, `RE_TOP_LEFT` 는 `R200_RE_CNTL` 비트 1(`SCISSOR_ENABLE`)일 때만 자른다(둘 다 끝 포함, 절대 좌표).
이후 3D 경로(R6 사다리·검증기)는 가위가 필요하면 **`SCISSOR_ENABLE` 을 켜고** TL·WH 를 함께 쓴다 — FreeBSD 깊이 지우기 선례의 `RE_CNTL=0` 은 기하 = 클립일 때만 안전하다.

---

**각주 (2026-09-21, R6k 계획 중에 찾음)**: 위 S7 의 "명시적 규칙은 어느 참고에도 없다 — H 는 추론" 은
**소스만 grep 한 결과**였다.  같은 트리의 커밋 기록에 규칙 H 가 글로 적혀 있다:

> `ChangeLog:6797-6800`, 커밋 9243791("r200: fixup scissors for DDX"):
> "a) turn of R200_RE_CNTL - SCISSOR_ENABLE - this save us emitting R200_RE_TOP_LEFT, **note scissor is
> still enabled**.  b) disable aux scissors."

즉 비트 1 을 끄면 `RE_TOP_LEFT` 를 안 내도 되고(= TL 이 안 문다) 가위(= `RE_WIDTH_HEIGHT`)는 계속 문다 —
**우리 실측(88·92 행)과 같다**.  교훈: 부재 주장을 적기 전에 `ChangeLog`·커밋 기록도 grep 할 것.
