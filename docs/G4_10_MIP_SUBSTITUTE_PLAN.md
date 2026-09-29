# G4-10 — 혼합 밉 모드를 레벨 선택 모드로 대체해 카드에 보낸다 (라이브러리만, 재부팅 없음) (계획, 2026-09-29, 코딩 전)

## 0. 범위와 전제

- 출발: `docs/G4_8_REPLAY_PLAN.md` §15 — 이 카드에서 레벨 사이 혼합 경로(hw MIN 6·7)는 몇 제출 만에 머신을 굳힌다(여섯 부팅, 재생 8 회로 확정); 레벨 선택 모드는 무해.  사용자 결정(2026-09-29): 가장 안전하고 확실한 길 = **A**.
- 하는 것: 라이브러리가 GL_NEAREST_MIPMAP_LINEAR 를 NEAREST_MIPMAP_NEAREST 로, GL_LINEAR_MIPMAP_LINEAR 를 LINEAR_MIPMAP_NEAREST 로 **대체해** 카드에 보낸다(텍셀 필터는 앱이 청한 대로, 레벨 사이 혼합만 선택으로).  Matrox M12 §10-1 판정 2 의 "문서화된 근사" 와 같은 성격이되, 여기서는 정확도가 아니라 **정지 회피**가 이유다.  커널·검증기·포트 **불변**.
- 하지 않는 것: 혼합 값을 카드에 보내는 어떤 경로도 기본에서는 열지 않는다.  `RDNMesaMip=all` 은 진짜 혼합 값을 보내는 실험 경로로 **남기되** "이 카드를 굳힌다" 고 헤더·문서에 적는다(재현기가 필요할 때를 위해; G4-5 의 scene D 판정이 그 경로의 기록).
- 규칙: 계산은 python, codex 는 계획에(§6), 참조는 연 줄만, 실기는 정지 위험 없는 것만(대체된 모드는 실측으로 무해).

## 1. 참조 (항목마다 연 것)

| # | 사실 | 근거 |
|---|---|---|
| R1 | GL 코드 → 하드웨어 MIN 필드는 `triMinField` 한 곳에서 정해진다(6 코드; 알 수 없으면 ~0 으로 프롤로그가 거절); 프롤로그는 `tex && (triMinField(...) == ~0 || levels < 1 || levels > MAX || (밉 코드 && levels < 2))` 이면 0 워드 | `OSRDNMesaTri.c:223-234`·`:649-656` |
| R2 | 클래스 허용: `classMinOk` — 비밉 두 코드는 항상, 밉 코드는 `texComplete`·`texLodOk` 가 서고 knob 이 ALL 이거나 MEASURED 마스크에 들 때; 마스크는 지금 NMN·LMN 둘(G4-6 보류) | `OSRDNMesaClass.c:210-233` |
| R3 | `minCode` 의 다른 소비처: 상주 레벨 수 `levels = M + 1`(밉 코드면), `osrdn_tri_texture_set` 저장, 배치 이음 판정(`triB.texMin == triTex.minCode`), 추적(세그먼트 minCode) — 어느 것도 "코드 4·5 = 카드가 혼합한다" 를 전제하지 않는다(레벨 수·이음·기록은 GL 코드 기준) | `OSRDNMesaHook.c:834-843`, `OSRDNMesaTri.c:217-223`·`:1264`·`:1287` |
| R4 | knob 문서: OFF / MEASURED(측정된 모드) / ALL(넷 다, 측정 탐침용) | `OSRDNMesaTri.h:45-55` |
| R5 | G4-5 판정기의 scene D(혼합 두 행)는 `RDNMesaMip=all` 로 돌린 그림을 카드 법칙 `G = 32·2^(k/8)` 로 판정한다; 기본 knob 에서는 두 행이 소프트웨어였다 | `judge_g45.py:87-104`, `run_g45.sh:45` |
| R6 | 검사기: `sim_class.py` 의 밉 행(4·5 는 기본 knob 에서 DECLINE 'TEXTURE'), 변이 "the default knob ignores the measured mask"; `check_hook.py` 의 같은 변이(`g45-mip`) | `sim_class.py:170-183`·`:433`, `check_hook.py:1463-1465` |
| R7 | Matrox 선례: 혼합쌍을 문서화된 근사로 개방, 편차 표가 정본 | `M12_WARP_MIPMAP_PLAN.md:385-390` |
| R8 | 실측 근거: 레벨 선택(NMN) 436 회·NMN + MAG LINEAR 436 회 무해; 혼합 6·7 은 2~7 회에 정지 | `docs/G4_8_REPLAY_PLAN.md` §15 |

## 2. 설계 (라이브러리)

1. **대체는 한 곳에서**: `OSRDNMesaTri.c` 에 `triMinSent(code)` — knob 이 `OSRDN_TRI_MIP_ALL` 이 아니면 코드 4 → 2, 5 → 3 로 바꾼 뒤 `triMinField` 에 넘긴다; 프롤로그의 두 호출(`OSRDNMesaTri.c:650`·`:656`)이 이것을 쓴다.  `triTex.minCode`(GL 코드)는 그대로 둔다 — 레벨 수·이음·추적은 GL 코드 기준이 맞고(R3), 추적을 읽는 쪽은 "코드 4·5 는 기본 knob 에서 2·3 으로 보내진다" 를 안다(§4 의 디코더 표기).
2. **허용**: `classMinOk` 의 MEASURED 마스크를 네 모드로(2·3 은 측정된 모드, 4·5 는 대체돼 2·3 으로 보내지므로 같은 조건).  완결·λ 조건(`texComplete`, `texLodOk`, `levels ≥ 2`, `M ≤ 11`)은 그대로 — 대체된 모드도 레벨 선택이라 같은 상주·λ 규칙을 쓴다.
3. **knob**: OFF(전부 소프트웨어) / MEASURED(기본; 넷 다 카드로, 4·5 는 대체) / ALL(넷 다 **진짜 값**으로 — 정지 재현 경로, 문서에 명시).  `OSRDNMesaTri.h` 의 설명과 `OSRDNMesaClass.c` 의 HELD BACK 주석을 이 결정으로 바꾼다.
4. 포트(`gl_vidsdl.c`)·커널·검증기·아레나·업로드: 불변.

## 3. 호스트 검사 (코딩 전에 정한다)

- `sim_class.py`: 행 "NEAREST_MIPMAP_LINEAR, measured knob" 과 "LINEAR_MIPMAP_LINEAR, measured knob" 을 DECLINE → **TAKE**(완결·λ OK 일 때); knob OFF 행은 DECLINE 유지; ALL 행 TAKE 유지; 변이 "the default knob ignores the measured mask" 는 "마스크를 0 으로" 로 여전히 모든 밉 행을 DECLINE 시켜야 한다.
- `check_hook.py` 새 규칙 `g410-substitute`(텍스트 규칙 + 변이): (a) 프롤로그의 TXFILTER 슬롯은 `triMinSent` 를 거친다(직접 `triMinField(triTex.minCode)` 를 쓰는 변이는 잡힘), (b) `triMinSent` 는 ALL 이 아닐 때만 4→2·5→3 (ALL 에서도 바꾸는 변이, 기본에서 안 바꾸는 변이 둘 다 잡힘), (c) 마스크가 네 모드.
- **단위 시뮬레이터**: 프롤로그를 실제로 돌려 워드를 보는 `sim_pack.py`/`sim_texrun.py` 중 TXFILTER 워드를 검사하는 것이 있으면 코드 4·5 의 기대 워드를 (MIN 2·3 필드 | MAX) 로 고친다; 없으면 `sim_trifunc.py` 에 한 경우를 더한다(코딩 때 확인해 §7 에 적는다).
- `judge_g45.py`: scene D 의 card 행 판정은 knob=all 기록에 대한 것이므로 그대로(역사); **새 판정 `judge_g410.py`**: 기본 knob 으로 scene D 를 돌린 그림(ghostprobe_v19 `GHOST_MIPD=1`, `RDNMesaMip` 없음)은 두 행이 카드에서 **레벨 선택** 으로 나와야 한다 — 기대 G 값은 `model.py` 의 레벨 색(scene C 와 같은 계단), 행 0 은 NMN, 행 1 은 LMN.  카운터: delegated 0, drawn = 격자 수.
- 인용 루프·싼 검사 먼저, `check-all` 마지막 한 번.

## 4. 실기 (재부팅 없음; 정지 위험 없음 — 카드로 가는 값은 실측 무해한 2·3 뿐)

1. 타깃 라이브러리 빌드(`target-build-mesa.sh`), `glquake_radeon` 재링크.
2. **내 gcdsd**: ghostprobe_v19 scene D 를 기본 knob 으로 → `judge_g410.py` 로 그림·카운터 판정(대체가 설계대로인지 **그림으로** 증명, [[counters-say-yes-the-picture-knows]]).
3. **사용자 gcdsd**: GLQuake 자가 실행 300 프레임/110 초, 기본 knob, 추적 켬(`RDNMesaTrace`) — 판정: 세그먼트 MIN 코드 분포에 4 가 있고(GL 코드로 기록), 소프트웨어 위임 0, 프레임 시간; 그다음 `timedemo demo1`(가속이 온전해진 뒤에만, [[timedemo-only-when-accel-is-complete]]).
4. 남은 것: 추적 디코더(`cpdec.py`)와 문서에 "기본 knob 에서 코드 4·5 → 필드 2·3" 표기.  **(G5-4 정정: `cpdec.py` 는 커밋된 적이 없다 — 표기는 추적 줄을 만드는 `triTrace` 의 머리 주석(`mesa/OSRDNMesaTri.c`)에 두었다.)**

## 5. 위험

| 위험 | 완화 |
|---|---|
| 대체가 프롤로그 밖으로 새어(예: 배치 키가 GL 코드로 이음을 판정) 같은 텍스처의 4 와 2 를 한 세그먼트로 이어 버린다 | 이음 판정은 GL 코드 기준이라 4 와 2 는 다른 세그먼트(보낼 값은 같지만 무해); 반대로 4 를 2 로 보내는데 세그먼트가 갈리는 것도 무해 |
| 화질: 레벨 전환이 계단으로 보인다 | Matrox 와 같은 문서화된 근사; 체인이 8×8 에서 잘려 있어 전환 수가 적다; 사용자가 화면으로 판단 |
| `all` 을 누가 켠다 | 헤더·문서에 "이 카드를 굳힌다" 명시, 러너 어디에서도 기본으로 쓰지 않는다 |
| 기존 G4-5 판정이 깨진다 | scene D 판정은 knob=all 로그에 대한 것이라 로그가 있는 한 그대로; 새 판정은 별도 파일 |

## 6. codex 교차검토 (코딩 전, 한 호출 = 한 주장·국지적)

주장: "`triMinSent` 를 프롤로그의 TXFILTER 슬롯 두 호출에만 끼우고 `classMinOk` 의 마스크를 네 모드로 넓히면, 그 밖의 `minCode` 소비처(상주 레벨 수·`osrdn_tri_texture_set`·배치 이음·추적·`texWhy`)와 λ/완결 조건은 손대지 않아도 대체된 모드가 측정된 모드(2·3)와 정확히 같은 규칙으로 카드에 간다."  codex 에 물을 것: `OSRDNMesaTri.c`(프롤로그 540-580, 이음 1080-1110, texture_set 205-215)·`OSRDNMesaHook.c`(775-790, 1595-1615)·`OSRDNMesaClass.c`(177-230) 에서 코드 4·5 가 2·3 과 다르게 다뤄지는 자리, 또는 hw 필드 값을 `triMinField` 밖에서 다시 만드는 자리가 있는가.

### 6-1. codex 판정표 (2026-09-29, GPT-6-Astra 한 호출; 전부 원문 확인)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| F1 | 하드웨어 MIN 매핑은 `triMinField` 하나, 호출은 프롤로그 두 곳 | `OSRDNMesaTri.c:223-231`·`:650`·`:656` | ✅ |
| F2 | 레벨 수 계산은 네 밉 코드에 같다 | `OSRDNMesaHook.c:827` | ✅ |
| F3 | 범위 검사·배치 이음·저장은 GL 코드 기준, 4↔2 는 여전히 다른 세그먼트 | `OSRDNMesaTri.c:217`·`:1264`·`:1287` | ✅ (§5 첫 행) |
| F4 | MAG 결합에 MIN 코드 분기 없음 | `:655` | ✅ |
| F5 | knob 소비처는 `classMinOk` 외 `OSRDNMesaHook.c:1844`(값 전달뿐) | 확인 | ✅ |
| F6 | 허용의 코드별 차이는 마스크뿐 | `OSRDNMesaClass.c:226`·`:231` | ✅ |
| F7 | 생성 표에 대체 필드를 막는 제약 없음 | `OSRDNMesaTriTable.h:503-507` | ✅ |
| F8 | texWhy 본문·추적은 범위 밖 | 내가 열어 확인: `osrdn_class_tex_why`(`OSRDNMesaClass.c:236-306`)에 코드 4·5 분기 없음, 추적은 `minCode` 를 수로만 기록 | ✅ 보완 |
| — | 단위 시뮬레이터 중 TXFILTER 워드를 보는 것 | `sim_pack/sim_texrun/sim_trifunc` grep 0 | §3: check_hook 텍스트 규칙 + 변이로 고정, judge_g410 그림이 실측 |

## 7. 구현과 실측 (2026-09-29, 부팅 17 = 드라이버 2d3234bf, 라이브러리 **790580725**)

- 라이브러리: `OSRDNMesaTri.c` `triMinSent`(knob ALL 이 아니면 4→2·5→3) 를 프롤로그의 TXFILTER 두 호출에; `OSRDNMesaClass.c` 마스크 네 모드 + HELD BACK 주석을 결론으로 교체; `OSRDNMesaTri.h` knob 설명(ALL = 정지 재현기).  `sim_class.py` 혼합 두 행 TAKE(+ 불완결 행 DECLINE), `check_hook.py` 규칙 `g410-substitute`(변이 4: 프롤로그 우회·ALL 도 대체·LML 을 그대로·마스크 축소 — 전부 잡힘).  자체시험 PASS: sim_class, check_hook, check_compile.  타깃 빌드 `RDNMESA PASS runid=790580725`, `judge_m1b` PASS.
- **그림 증명**(`build/g410/run_g410.sh`, 내 gcdsd, CP 기동 포함): scene D 를 **기본 knob** 으로 — 카운터 drawn 36 · delegated 0 · verifyRefused 0; 그림(`build/g410/qd.mipd.ppm`, GL 원점이라 세로 뒤집어 읽음 — 첫 판정기가 이를 빠뜨려 배경을 읽었고 `judge_g45.block` 의 규약으로 고쳤다) 은 두 행 모두 k 0–4 → 레벨 1(G 32), k 5–8 → 레벨 2(G 64) 로 **평평**하다; 같은 장면의 G4-5 knob=all 그림은 32·35·38·41… 로 혼합.  `judge_g410` PASS(자체시험 3: 선택 통과·혼합 잡힘·엉뚱한 레벨 잡힘).  → 대체는 설계대로: 혼합 요청이 레벨 선택으로 카드에 간다.
- GLQuake: `glquake_radeon` 을 790580725 에 재링크(`GLQUAKE_BUILD=pass`).  다음: 사용자 gcdsd 아래 자가 실행 300 프레임/110 초(기본 knob, 추적 켬) → 세그먼트 코드 분포·위임 0·프레임 시간, 그다음 timedemo.
- **GLQuake 자가 실행**(부팅 17, 사용자 gcdsd, 기본 knob, `-nosound`, 300 프레임, 16:40): **정지 없음**, 300 프레임 42.2 초, `to Mesa 0`, `drawn 1,278,674`, `gate refused Hook.c:5 x4`(전과 같은 넷), `kernel declined 4`, 필터 감사 207/0.  추적 7,221 제출: GL 코드 4(NML) 세그먼트 **20,392**·삼각형 **915,866**(첫 제출 730 번째부터), 코드 1/0 은 라이트맵·UI; 레벨 2/3/4/5 = 8×8 캡 체인 그대로.  즉 월드 전부가 대체된 모드로 카드에서 그려졌다(`build/g410/trace-glq.txt`, `glq-self.log`).
- timedemo(`run-glquake-timedemo.sh glquake_radeon 640 480 120`, 16:42): 데모는 재생됐지만(`Playing demo from demo1.dem`, pak0) 120 초 안에 끝나지 않아 `frames` 줄이 없다 — 이전 세션의 timedemo 로그(`build/g46/td-*.log`)도 같은 모양(한 번도 완주 기록 없음).  fps 는 자가 실행의 tick 으로 잰다(아래).
- **fps(자가 실행 tick, python)**: 프레임 0–100 8.2, 100–200 7.2, 200–300 7.0 fps(640×480, 월드 전부 카드, Mesa 위임 0).  NMN 강제 실행(부팅 11, 41.9 초/300 프레임)과 같은 수준 — 즉 대체 뒤 남는 병목은 필터가 아니라 **제출 경로**(제출마다 CP idle 까지 동기 대기, 검증기·copyin 비용: M1x/M2 실측)다.  성능은 별도 과제(G5)로.
- 남은 것: `all` knob 을 문서에 "정지 재현기" 로 적었고(헤더·§0), 추적 디코더 표기(코드 4·5 → 필드 2·3)는 `cpdec.py` 주석에.  **(G5-4 정정: 그 파일은 저장소에 없다; 표기는 `triTrace` 머리 주석에.)**
