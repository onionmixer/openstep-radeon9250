# G4-7 — PP_TRI_PERF: 읽고, 참조처럼 0 으로 (커널, 재부팅 1 회) (계획, 2026-09-27, 코딩 전)

## 0. 범위와 전제

- 출발: `docs/G4_6_GLQUAKE_PLAN.md` §10 — 멈춘 GLQuake 스트림을 r200 DRI 가 내보내는 상태 92 항목과 대조한 결과, 우리 경로(유닛 0·삼선형)에 걸리는 차이는 **`R200_PP_TRI_PERF`(0x2cf8)·`R200_PP_PERF_CNTL`(0x2cfc) 를 우리가 한 번도 쓰지 않는 것** 뿐이다.  참조는 컨텍스트마다 둘 다 0 으로 쓴다.
- 이 계획은 **커널만** 바꾼다(라이브러리·검증기 규칙 불변).  묶는 것은 둘: ① REC3D 가 두 레지스터를 **읽어** 지금 값을 로그에 남긴다(비파괴) ② 제출 앞머리(stage 1)가 참조처럼 둘을 **0 으로 쓰고 되읽어 기록**한다(게이트 아님).  재부팅 1 회에 둘 다 얻는다 — 0 쓰기는 이미 0 이면 무해(멱등)하고, 읽기만 하려 해도 재부팅은 같다.
- 규칙: 하드 행 세 번 뒤라 실기 실험 앞에 오프라인 대조를 두었다(R5 §5 "하드 행 한 번이면 중단·오프라인 분류").  계산은 python, codex 는 계획에(§6), 참조는 연 줄만 인용, 설치 전 `nm -u`, 재부팅은 사용자.

## 1. 참조 (항목마다 연 것)

| # | 사실 | 근거(연 줄) |
|---|---|---|
| P1 | r200 DRI 는 `prf` 상태(`PP_TRI_PERF` 2 워드)를 **always** 로 내보낸다 — 칩 패밀리 조건 없음(앞뒤 `ALLOC_STATE` 줄 740–750 에 `if` 없음) | mesa-amber `r200_state_init_amber.c:748`; Mesa-6.5.3 `r200_state_init.c:492` |
| P2 | 값: `TRI_PERF = 0x1f − 0x1f × texture_blend_quality`, `PERF_CNTL = 0`; 옵션 기본 1.0 → **둘 다 0** | `r200_state_init_amber.c:984-986`; `radeon_screen_amber.c:128-129`(기본 1.0, 범위 0–1, 설명 "“brilinear” texture filtering") |
| P3 | 레지스터: `R200_PP_TRI_PERF 0x2cf8`, `TRI_CUTOFF_MASK` 비트 0–4, `R200_PP_PERF_CNTL 0x2cfc` | `r200_reg_amber.h:1074-1076` |
| P4 | DRM(BSD·Linux)은 이 둘을 **통과 패킷 표**에만 둔다(초기화 안 함): `R200_EMIT_PP_TRI_PERF_CNTL` = 84, `{R200_PP_TRI_PERF, 2}` | freebsd `radeon_drm_bsd.h:157`, `radeon_state.c:245`·`:729` |
| P5 | xorg 는 이름만 안다(`radeon_drm.h:154`), 소스에서 안 쓴다(`src/*.c` grep 0) | xorg `radeon_drm.h:154` |
| P6 | 우리 커널: REC3D 목록 64 개(4 의 배수여야, 로그가 넷씩 찍음), 앞머리 되읽기 9 개, 게이트 마스크 `0x10f`(배치 다섯), 기대값은 `cpR6PreWant` 의 if 사슬로 기본 0 | `osrdn_cp.h:331-333`·`351`; `osrdn_cp.m:2261-2268`·`2200-2204`·`2231-2246`·`3119-3131`·`3143-3158`; `osrdn_modelog.m:17`·`361-367`·`394-396` |
| P7 | 호스트 검사: `check_r6a.py` 가 REC3D 수를 소스·헤더·`REC_WANT` 로 대조, `zclear_oracle.prefix_expect` 가 앞머리 9 쌍(`tri_oracle` 이 재사용), `check_citations.py` 가 `cpR6PreRegs` 줄 2199–2203 을 앵커로 잡음, `check_r5_src.py:229` 은 R3Regs 에 쓰기 금지 | `check_r6a.py:165-168`·`1863-1864`·`1891-1902`·`2503-2508`; `zclear_oracle.py:53`·`188-192`·`310`; `tri_oracle.py:155-156`; `check_citations.py:1340` |

## 2. 설계 (커널)

1. `osrdn_cp.m` 상수: `C_PP_TRI_PERF 0x2cf8`, `C_PP_PERF_CNTL 0x2cfc`(P3).
2. **REC3D**: `osrdnCpR3Regs` 끝에 넷을 더해 68 — `0x2cf8, 0x2cfc, 0x2c00, 0x2c04`.  뒤의 둘(`TXFILTER_0`·`TXFORMAT_0`)은 4 의 배수를 맞추는 자리이자 이미 허용 목록에 있는 레지스터로, 실행 뒤 마지막 텍스처 상태를 남긴다.  `CP_R6_REC_COUNT` 68.  로그는 17 줄(16 → 17, msgbuf 4 KB 안에서 record 단독 실행).
3. **앞머리**: `cpR6PreRegs` **끝에** `C_PP_TRI_PERF, C_PP_PERF_CNTL` 을 붙여 11 개(`CP_R6_PRE_COUNT` 11).  끝에 붙이므로 비트 0–8 과 `CP_R6_PRE_GATE 0x10f` 는 그대로 — 새 둘(비트 9·10)은 **기록만** 하고 게이트하지 않는다(`cpR6PreWant` 기본 0 이 곧 기대값, 코드 변경 없음·주석만).  stage 1 의 워드: **`C_RB3D_COLORPITCH` 뒤·(R7 이면 FMT0/FMT1 뒤)·`C_SCRATCH_REG0` 바로 앞**에 `P0(C_PP_TRI_PERF) 0`, `P0(C_PP_PERF_CNTL) 0` 두 쌍(+4 워드; 배열은 `CP_R6_WORDS` 4080 이라 여유).  끝에 두는 이유: `zclear_oracle.prefix_words()[9]`(SE_VTX_STATE_CNTL 값)를 두 자체시험이 위치로 집는다(codex C7) — `TXMULTI` 뒤에 끼우면 그 색인이 밀린다.  `osrdn_cp.m:3277` 의 "(1 + 9)" 주석 → 11(`osrdn_cp.h:342` 은 이름으로 세므로 불변).
4. 왜 게이트가 아닌가: 되읽기가 0 이 아니어도(레지스터가 쓰기 전용이거나 다른 폭이면) 그리기를 막을 이유가 없다 — 그 사실 자체가 기록으로 남으면 된다.  `prebad=%02x` 는 최소 폭이라 세 자리(0x200·0x400)도 그대로 찍힌다.
5. R7 허용 목록·클라이언트 검증기: **불변**.  클라이언트는 이 레지스터를 못 쓴다(참조도 커널이 아니라 컨텍스트 상태로 쓰지만, 우리 설계에서 상태 초기화는 앞머리 몫이다 — `PP_CNTL_X`·`TXMULTI_CTL_0` 과 같은 자리).

## 3. 호스트 검사 (코딩 전에 정한다; 싼 것부터, check-all 은 마지막 한 번)

- `tools/r6/zclear_oracle.py`: `prefix_expect` 에 `(PP_TRI_PERF, 0), (PP_PERF_CNTL, 0)` 두 쌍 추가(끝에), 자체시험 "prefix gate = the five placement registers" 는 그대로 통과해야 한다(`PRE_GATE` 불변).
- `tools/r6/check_r6a.py`: `REC_WANT` 에 새 절차 키(`g47`: 68) 추가, 자체시험의 `REC_WANT['r6c']` 비교를 **최신 키**로 바꾼다(옛 로그 64 는 옛 키로 계속 판정).
- `tools/oracle/check_citations.py`: `osrdn_cp.m` 앵커 줄 갱신(2199–2203 이 밀린다) — 인용 루프를 돌려 전부 맞춘다.
- **§6 주장을 내가 먼저 깬 자리 셋(codex 회신 전, grep 으로)** — 전부 고쳐야 한다:
  - `osrdn_modelog.m:411-414`: `RDN-R6 zpre` 가 `pre[0]`–`pre[8]` **아홉 개를 손으로 나열**한다 → 열한 개로(한 줄, `%08x` 11 개).
  - `check_r6a.py:1774`: zpre 파서가 `(?:[0-9a-f]{8} ?){9}` 로 **9 를 박아** 앞 아홉만 잡는다 → **`{9,11}`**(옛 9 개 로그도 계속 잡히게, C14); `:1903` 의 위치 비교는 `range(len(pre))` 로, 그리고 g47 절차에서는 `len(pre) == len(want_pre)` 를 따로 요구한다.  `{11}` 로만 바꾸면 옛 로그의 zpre 줄이 안 잡혀 `[None]*11` 이 되고 게이트 실패로 판정된다(codex C14, 재현됨).
  - `check_r6a.py:1774`: `prebad=([0-9a-f]{2})` — 비트 9·10 이 서면 `prebad=200` 세 자리라 **줄 전체가 파싱에서 빠진다**(zclear 줄 실종 = 판정 실패) → `{2,3}`; 커널의 `%02x` 는 그대로(합성 문자열 `prebad=00` 이 2426·2526·2891·2940 행에 박혀 있다).
- **codex 가 더 찾은 자리(§6-1, 전부 원문 확인)**:
  - `zclear_oracle.py:182-191` `prefix_words()` 에 두 쌍 추가(끝, `SCRATCH_REG0` 앞) → `:317` "prefix: 11 PACKET0 pairs" 22 → **13 쌍 26**; `[9]` 색인은 위 배치로 불변(`:370`, `tri_oracle.py:455`).
  - `check_r6a.py:2136` `advance(22)` → 26(R6m 절차 전용; 16 정렬 뒤 둘 다 32 라 결과는 같지만 사실대로).
  - `osrdn_cp.h:265-266` 주석 "26-word state prefix" → 30, `design3.py:16`·`:44` `STATE_PREFIX_WORDS = 26` → 30(부등식 밖이라 결과 불변, 값만 사실대로).
  - `check_r6a.py:57` 의 `ORDERS` 에 `g47` 절차(여섯 단계 + rec3d + zprep/zclear + rec3d + stop + record) 추가 — `REC_WANT` 만 더하면 `check_r6a.py:1831`·`:2184` 에서 KeyError.  `check_r6a.py:2111-2119` 합성 REC3D 목록에 g47 이면 새 넷 추가.
  - `check_r6a.py:2519-2525` 자체시험 `REC_WANT['r6c']` → 최신 키(§3 첫 항목과 같은 것).
- `tools/r5/check_r5_src.py`: 그대로(R3Regs 쓰기 금지 규칙은 읽기 추가와 무관).  `tools/r7/verify_oracle.py` 의 prefix 상수는 표면 넷뿐이라 불변.
- 빌드 → `kext/hostcheck.sh`/symcheck 대역(`nm -u`) → `check-all.sh` 한 번.

## 4. 실기 (재부팅 뒤, 부팅 11)

1. 마운트 → 내 gcdsd → 커널 로그 저장 → 여섯 단계(`record rec3d load map reset start`).  **`rec3d` 가 `load` 앞이라 첫 읽기는 전원/BIOS 값**이다 — 멈춘 세 실행이 돌던 값(어느 경로도 이 레지스터를 안 썼다).
2. `start` 뒤 `rec3d` 한 번 더(읽기 전용 op, `osrdn_mode.m:1487` 이 허용) → 리셋·마이크로코드가 바꾸는지.
3. 오프스크린 첫 제출(ghostprobe 사다리 S1 하나, 내 gcdsd, 시드) → `RDN-R6 zclear … prebad=` 의 비트 9·10 이 0 이면 0 쓰기가 되읽혔다; 그 뒤 `rec3d` 로 0x2cf8 = 0 확인.
4. 값 셋(부팅·start 뒤·앞머리 뒤)을 §7 표에 적는다.

**결정 나무**
- 부팅 값이 **이미 0** → 가설 사망.  추가 재부팅 없이 G4-6 §9 의 가르는 실험(NEAREST_MIPMAP_NEAREST GLQuake, 사용자 gcdsd, 120 초, 정지 위험·승인 뒤)으로 간다.
- 부팅 값이 **0 아님** → (a) 오프스크린 회귀: ghostprobe_v20 사다리 S1–S13 재실행(내 gcdsd, 시드, breadcrumb) — 0 쓰기가 측정된 그림을 바꾸지 않는지; (b) G4-5 의 혼합 가중치 실측(`ghostprobe_v19` MIPE/F, `model.py`)을 다시 — **예측**: 잘림(cutoff)이 켜져 있었다면 f = 2^frac(λ) − 1 로 맞춘 모델이 바뀐다; (c) 그 뒤 GLQuake `RDNMesaMip=all`(추적 켜고, `-nosound`, 110 초, 사용자 gcdsd, **정지 위험 — 승인 뒤**).  안 멈추면 원인 확정·혼합 모드 개방(G4-5 §9 의 마스크)으로; 멈추면 TRI_PERF 무죄, §9 실험으로.

## 5. 위험

| 위험 | 완화 |
|---|---|
| 0x2cf8/0x2cfc 읽기가 안전한가 | REC3D 는 이미 64 개(0x3250 대 포함)를 읽고, DRM 은 이 둘을 CP 로 쓰게 둔다(P4) — MMIO 창 안의 정의된 레지스터 |
| 0 쓰기가 측정된 그림을 바꾼다 | `TRI_CUTOFF` 는 밉 혼합 전용(P2 설명) — NEAREST·LINEAR·레벨 선택 모드는 무관해야 하고, §4-(a) 회귀가 잰다; 참조의 기본값이므로 "참조와 같아지는" 방향 |
| 앞머리가 길어져 stage 1 시간이 는다 | +4 워드·되읽기 +2, M1x 구간 3–4 에 잡힌다 |
| 옛 로그 판정이 깨진다 | `REC_WANT` 를 절차별로 유지 |
| 인용 줄이 밀려 check_citations 실패 | 인용 루프 먼저(싼 검사) |

## 6. codex 교차검토 (코딩 전, 한 호출 = 한 주장·국지적)

주장: "앞머리 목록 **끝에** 둘을 더하고 `SCRATCH_REG0` 앞에서 0 으로 쓰면, `0x10f` 게이트·되읽기 순서·stage-1 크기·판정기(`prefix_expect`·`REC_WANT`)가 전부 맞는다."  codex 에 물을 것: 이 가정을 깨는 자리(9 를 박아 둔 곳, 순서를 가정한 곳)가 `osrdn_cp.m/.h`·`osrdn_modelog.m`·`zclear_oracle.py`·`check_r6a.py` 에 있는가.  판정표는 §6-1 에.

### 6-1. codex 판정표 (2026-09-27, 한 호출, gpt-5.6-sol; 전부 원문을 열어 확인)

codex 는 주장을 "그대로는 성립하지 않는다" 고 했고, 맞다.  내가 먼저 찾은 셋(C1–C3)은 codex 도 잡았다.

| # | codex 주장 | 내 검증(연 것) | 판정 |
|---|---|---|---|
| C1 | `osrdn_modelog.m:411-414` zpre 로그가 9 개 고정 | 열어 확인, `pre[0]`–`pre[8]` | ✅ (내가 먼저 찾음) |
| C2 | `check_r6a.py:1774` prebad 를 정확히 2 자리로 파싱, `200` 은 `20` 으로 잘못 잡힌다 | `([0-9a-f]{2})` 확인.  단 "20 으로 잘못 잡힌다" 는 뒤에 ` pfbad=` 가 선택이라 그렇게 될 수 있다 — 어느 쪽이든 틀린 값 | ✅ |
| C3 | `check_r6a.py:1779` zpre 를 9 개만 파싱 → `:1903` `pre[9]` IndexError | `{9}` 확인, 1896–1897 위치 비교 확인 | ✅ |
| C4 | `check_r6a.py:2499` 형식 자체시험도 `%02x` 를 2 자리로 본다 | 열어 확인.  그러나 그 시험은 합성 줄(`prebad=00`)을 형식과 맞추는 것이라 **바뀔 것 없음** — 커널 `%02x` 를 그대로 두는 §2-4 결정과 일치 | ⚖️ 사실, 조치 없음 |
| C5 | `zclear_oracle.py:182-191` `prefix_words()` 에 새 쌍이 없다; `:317` 22 → 26 | 열어 확인 | ✅ §3 에 추가 |
| C6 | `:370`, `tri_oracle.py:455` 가 `prefix_words()[9]` 를 위치로 집는다 — TXMULTI 뒤에 끼우면 [13] 으로 밀린다 | 열어 확인 | ✅ **설계 변경**: 새 쌍은 끝(`SCRATCH_REG0` 앞)에 — §2-3 수정 |
| C7 | `check_r6a.py:2136` `advance(22)` 고정 | 열어 확인(R6m 절차 분기 안) | ✅ 26 으로 |
| C8 | `osrdn_cp.h:265-266` "26-word state prefix" 주석 고정 | 열어 확인(`:265-266`); `design3.py:16`·`:44` 도 같은 26 을 쓴다(내 grep 추가) | ✅ 30 으로(부등식 밖) |
| C9 | `osrdn_cp.m:3277` "(1 + 9)" | 열어 확인 | ✅ (§2-3 에 이미) |
| C10 | `check_r6a.py:2519-2525` 자체시험이 `REC_WANT['r6c']` 고정 | `:2519-2525` 확인 | ✅ (§3 첫 항목에 이미) |
| C11 | `REC_WANT['g47']` 만 더하면 `ORDERS[procedure]` 에서 KeyError(`:1831`·`:2184`) | 열어 확인 | ✅ §3 에 추가 |
| C12 | `:2111-2119` 합성 REC3D 목록이 64 개까지, 새 넷 없음 | 열어 확인 | ✅ §3 에 추가 |
| C13 | 게이트(`0x10f`)와 커널 배열 크기(`CP_R6_PRE_COUNT`/`REC_COUNT`)는 유지 | `osrdn_cp.h:365`·`:564`·`:569`, `osrdn_cp.m:3271` 확인 | ✅ 주장의 남은 부분은 성립 |

2 차 자기검사: 위 ✅ 의 "내 검증" 은 전부 이 세션에서 `sed -n` 으로 연 줄이다(codex 회신에서 옮긴 줄번호 없음 — C8 의 design3 두 줄은 내 grep).

### 6-2. GPT-6-Astra 재검토 (2026-09-27, 사용자 지시로 모델 교체, 한 호출; 6-1 을 읽히고 "아직 빠진 것" 만 물음)

| # | codex 주장 | 내 검증(연 것) | 판정 |
|---|---|---|---|
| C14 | zpre 파서를 `{11}` 로 바꾸면 옛 9 개 로그가 안 잡혀 `check_r6a.py:1903` 이 `[None]*11` 을 만들고 `:1907` 게이트 실패로 판정 — 옛 `REC_WANT` 키만으로는 옛 로그를 못 지킨다 | `:1898-1909` 열어 확인.  `check-all.sh:142` 은 자체시험만 돌리지만 옛 로그의 수동 재판정은 남는다.  합성 로그는 `check_r6a.py:2424` 이 `prefix_expect` 로 zpre 줄을 만들므로 11 로 따라온다 | ✅ §3 파서 항목 수정(`{9,11}` + 길이별 비교) |
| C15 | `cpR7Verify(c, cpR7Buf, c->subWords, …)`(`osrdn_cp.m:3154`)는 클라이언트 버퍼만 보고, 커널 앞머리는 `:3253-3254` 에서 따로 제출 — 허용 목록 42 불변에 문제 없음 | `:3154`·`:3253-3254` 이 세션에서 이미 열었음(§1 P6, 6-1 C13) | ✅ |
| C16 | 그 외 지정 파일에 추가 파손 없음(`verify_oracle.py` 는 범위 밖) | `verify_oracle.py:80-82`·`:206`·`:257-260` 는 표면 넷과 FMT 상수만 — 내가 §3 에서 이미 확인 | ✅ |

## 7. 구현과 호스트 게이트 (2026-09-27, 코딩; 실기 전)

- 커널: `osrdn_cp.m`(상수 둘·REC3D 68·앞머리 11·prefix 두 쌍·주석)·`osrdn_cp.h`(68·11·30)·`osrdn_modelog.m`(zpre 11 개).  R7 허용 목록 **42 그대로**; `verify_oracle.RESERVED` 에 0x2cf8·0x2cfc 를 더해(클라이언트는 못 쓴다) 생성 블록을 다시 만들어 넣었고(`gen_r7verify --check` PASS, `sim_verify` PASS), `check_r5_src` 의 `R6_RING_OK` 에 둘을 더했다(규칙 약화가 아니라 정밀화: 앞머리가 쓰는 레지스터의 측정 집합).
- 판정기: §3·§6-1·§6-2 항목 전부(`zclear_oracle`·`tri_oracle`·`check_r6a`·`design3`·`check_plan_ops` 의 `# tail nostop`).  자체시험 PASS: zclear_oracle, tri_oracle, check_r6a, verify_oracle, design3, check_plan_ops(g47 = 11 연산 1 케이스).
- 인용: 편집으로 밀린 문서 인용은 편집 전후 사본의 difflib 대응표로 **일괄 재조준**(문서 32 개·234 + 30 + 129 + 15 곳, EXPECT 키 188 + 25); 새 문서 둘의 인용은 PATHS 키 10 개·EXPECT 79 항목을 더해 전부 기계 대조(전 문서 0 failed).  라이브러리 파일(`OSRDNMesaTri.c` 등)의 옛 드리프트(G4-5·G4-6 편집분)는 검사기 힌트로 재조준했다.
- 빌드: `pack_r2b0.py` → 타깃 `target-build-r2b0.sh` — **OSRDNBUILD PASS stamp=f0d603c0 runid=790521010 symbols=21**; 호스트 `check_reloc_r2b0` PASS(`build/r2b0/790521010/R2B0RELOC_PASS`).  hostcheck-r2b0 PASS.
- 실기 러너: `build/g47/run_g47.sh <nonce>`(계획 = `build/g47/plan_ops.txt`, 판정기 `ORDERS['g47']` 와 기계 대조 PASS).  세 번의 TRI_PERF 읽기(부팅 값·START 뒤·첫 앞머리 뒤)를 한 줄씩 찍고, 판정은 `check_r6a.py … --procedure g47`.
- check-all 첫 회: 실패 **하나** — `sim_r6` 기본 실행 "case UC … first difference at 10: ('w', (8328, 3)) vs ('w', (11512, 0))" = R7 클라이언트 경우의 앞머리에서 오라클이 정점 형식 쌍(0x2088)을 표지 바로 앞에 끼워 TRI_PERF 쌍(0x2cf8) 뒤에 두었다; 커널은 형식 쌍 → TRI_PERF 쌍 → 표지 순(§2-3).  §6-1·6-2 가 못 본 자리(`sim_r6.py` 는 검토 범위 밖이었다).  `sim_r6.py` 의 삽입 위치를 `PP_TRI_PERF` 앞으로 고쳐 재실행.
- `sim_r6` 재실행 PASS → **check-all 2 회차 PASS(실패 0)** → 타깃 설치 `target-install-r2b0.sh closed=yes fresh live` **INSTALL DONE runid=790521010**(옛 번들은 `.prev`, 다음 부팅부터).  재부팅은 사용자 몫 — 재부팅 뒤 §4 순서: 마운트 → 내 gcdsd → 커널 로그 저장 → `bash build/g47/run_g47.sh <nonce>` (여섯 단계·rec3d 세 번·zprep/zclear A, STOP 없음) → 판정 → 결정 나무.

## 8. 실측 (2026-09-28, 부팅 11 = 026a93c8, 드라이버 f0d603c0/790521010, `build/g47/run-boot11.log`·`messages-026a93c8.txt`)

| 읽기 | `PP_TRI_PERF`(0x2cf8) | `PP_PERF_CNTL`(0x2cfc) |
|---|---|---|
| 부팅 값(LOAD 전) | 00000000 | 00000000 |
| START 뒤 | 00000000 | 00000000 |
| 첫 앞머리(0 쓰기) 뒤 | 00000000 | 00000000 |

- 11 연산 전부 rc=0, `RDN-R6 zclear case=1 … prebad=00`, `zpre` 11 개(끝 둘 0) — 앞머리 되읽기 정상.  판정 `check_r6a.py … --procedure g47` **PASS**(STOP 없는 절차의 "STOP 뒤 주기" 검사는 `order` 에 stop 이 없을 때 노트로만 남기도록 정밀화).
- **결정 나무의 첫 가지: 부팅 값이 이미 0 → TRI_PERF 가설 사망.**  카드는 참조의 기본값(brilinear 잘림 없음)으로 삼선형을 돌려 왔다.  세 번의 정지는 이 레지스터 때문이 아니다.
- 남는 단서 하나: 0x2cf8 이 읽기 가능한지는 이 실험이 가르지 못한다(0 을 쓰고 0 을 읽었다).  이웃 PP 레지스터들(2c1c·2cc4·2f00·2088)은 부팅 값이 읽히므로 읽기 가능 쪽이 자연스럽지만, 만약 쓰기 전용이라면 부팅 값은 미지이고 지금은 앞머리가 매번 0 을 쓰므로 **어느 쪽이든 참조 상태에서 다음 실험을 한다**.
- 다음(G4-6 §9 의 가르는 실험, 사용자 gcdsd·승인 필요): 기본 라이브러리(혼합 거절)로 `+gl_texturemode GL_NEAREST_MIPMAP_NEAREST` GLQuake 110 초.  멈추면 밉 필터 일반/유닛 0 단독 쪽(T0 우회 후보), 안 멈추면 혼합 모드 고유 → 그다음 `RDNMesaMip=all`(이제 TRI_PERF=0 아래) 로 다시.
