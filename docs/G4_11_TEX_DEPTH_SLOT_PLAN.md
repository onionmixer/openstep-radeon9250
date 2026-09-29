# G4-11 — 텍스처 프롤로그의 깊이 슬롯 누락 (라이브러리 생성기 결함) (계획, 2026-09-29, 코딩 전)

## 0. 증상과 확정된 원인

- 사용자 실측(2026-09-29, GLQuake 시작 맵): 앞의 엘리베이터 아랫부분이 바닥 뒤에 가려져야 하는데 보인다 — 깊이 검사가 빠진 그림.
- 추적(라이브러리, `RDNMesaTraceLastDepth`) 으로 잡은 월드 제출(seq 2474, 배치 깊이 코드 9 = GEQUAL·쓰기 없음)의 스트림에서 `RB3D_ZSTENCILCNTL` = **0x02227072**(검사 ALWAYS·쓰기 없음 = 깊이 OFF 리터럴).  코드 9 라면 0x02227040 이어야 한다(python, `OSRDNMesaTriTable.h` 상수로 계산).
- 카드의 깊이 표면 덤프(`tools/g48/rdndump`, 창 + 0x500000, 640×480×2): 0 이 49 %, 0xffff 가 49 %, 나머지 2 % — 장면의 깊이가 **써지지 않았다**.  정점 z 는 0.486–0.499 로 정상(훅이 DepthMax 로 나눔, `OSRDNMesaHook.c:957-984`).
- 호스트 재현: `triPrologueTo(…, tex=1, depth=9)` 를 Tri.c 를 그대로 컴파일해 부르면 ZSTENCIL 워드가 늘 0x02227072.  **원인**: 생성된 표 `osrdnTexSlot`(텍스처 프롤로그 60 워드)의 워드 7(ZSTENCILCNTL)이 슬롯 **0(리터럴)** 이고, 평면 표 `osrdnTriSlot` 은 같은 자리가 슬롯 **9** 다.  생성기의 텍스처 루프(`gen_tri_prologue.py:356-362`)가 `r == zsten` 에서 WRITE 비트만 지우고 `slot = SLOT_ZSTENCILCNTL` 을 빠뜨렸다(평면 루프 `gen_tri_prologue.py:186-190` 에는 있다).  M1g 가 텍스처 표를 만들 때 M1i 의 깊이 슬롯이 평면 표에만 들어갔고, 이후 깊이 실측(R6f·G4-1a)은 평면 프롤로그로만 이뤄져 잡히지 않았다.
- 영향: 텍스처가 있는 모든 카드 그리기가 깊이 없이(검사 ALWAYS·쓰기 없음) 그려졌다 — GLQuake 월드 전부.  RB3D_CNTL 의 Z 비트(슬롯 6)는 켜지지만 ZSTENCILCNTL 이 꺼져 있어 효과가 없다.

## 1. 설계 (생성기 한 줄, 표 재생성)

- `gen_tri_prologue.py` 텍스처 루프의 `if r == zsten:` 가지에 `slot = SLOT_ZSTENCILCNTL` 추가(평면 루프와 같은 형태) → `OSRDNMesaTriTable.h` 재생성 → `osrdnTexSlot` 워드 7 = 9.  C 쪽(`triPrologueTo` 의 ZSTENCIL 분기)은 이미 맞다.
- 회귀 규칙: 생성기 자체시험(또는 `check_hook`)에 "두 표 모두 ZSTENCILCNTL 워드의 슬롯이 9" + 변이(텍스처 루프에서 슬롯 줄 제거 → 잡힘).  호스트 프롤로그 하네스(위 재현)를 `tools/mesa/sim_prologue.py` 로 남겨 depth 코드 0·5·9·21·25 × tex 0/1 의 ZSTENCIL 워드를 기대값과 대조.

## 2. 검증 (재부팅 없음)

1. 호스트: 재생성 표의 슬롯 확인(python), sim_prologue, check_hook, check_compile, sim_pack, gen `--check`, check-all 마지막.
2. 타깃: 라이브러리 빌드·재링크 → 시작 맵 300 프레임 + `rdndump` — 깊이 표면의 비-클리어 화소 비율이 2 % → 대부분(장면이 화면을 덮으므로 90 % 이상)으로; 월드 스트림의 ZSTENCIL 이 코드대로(0x42227020/0x42227040 등).
3. 사용자 화면 확인(엘리베이터 가림).

## 3. codex 교차검토 (한 주장·국지적)

주장: "텍스처 루프에 `slot = SLOT_ZSTENCILCNTL` 을 더하는 것만으로 표가 평면 표와 같은 규약이 되고, 생성기의 다른 출력(리터럴 값·검사기 표·`OSRDN_TEX_PROLOGUE_WORDS`)과 C 의 ZSTENCIL 분기·검사기(check_hook·sim_pack·gen --check)는 손댈 것이 없다."

## 4. codex 교차검토 판정 (2026-09-29, gpt-6-astra, 한 주장·국지적)

줄번호는 편집 뒤의 현재 줄로 재조준했다(편집 전 사본을 역구성해 difflib 로 대응).

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| `gen_tri_prologue.py:185-190` 은 슬롯을 설정하고 텍스처 루프 `:355-363` 은 `SLOT_LITERAL` 로 시작해 비트만 지운다 | 두 자리를 열어 읽음 | ✅ |
| 텍스처 루프 뒤에 슬롯 후처리·두 번째 ZSTENCILCNTL 쓰기가 없다(`:407-408` 은 `words/slots +=` 뿐, `OSRDNMesaTriTable.h:544` 에 한 번) | `gen_tri_prologue.py:405-409` 와 표를 열어 확인 | ✅ |
| `OSRDN_TEX_PROLOGUE_WORDS` 는 `len(tw)`(`:625`) 라 바뀌지 않는다 | 연 뒤 재생성 결과 60 그대로 | ✅ |
| 자체시험 `:890-893` 은 평면 표만, `:990-995` 텍스처 슬롯 개수 검사엔 ZSTENCIL 이 없고, `:1040-1041` 은 이미 ZSTENCIL 분기 | 세 자리를 열어 확인 | ✅ — 규칙을 더했다(§5) |
| `--check` 는 헤더 전체를 비교하므로(`:1123-1137`) 재생성이 필수 | 열어 확인; 수정 뒤 `--check` 가 561 행 한 곳(`0 → 9`)만 달랐다 | ✅ |
| `triPrologueTo` 는 tex 로 배열만 고르고(`OSRDNMesaTri.c:558-561`) 같은 switch(`:600-601`), 깊이 분기(`:681-689`)에 tex 전용 가지가 없다 | 열어 확인 | ✅ |

codex 가 낸 줄번호 9 곳 모두 실제와 일치.  주장에 모순 없음 → 채택.

## 5. 구현 (2026-09-29, 라이브러리 **790586567**, 드라이버 2d3234bf, 재부팅 없음)

- `gen_tri_prologue.py:356-362`: 텍스처 루프의 `r == zsten` 가지에 `slot = SLOT_ZSTENCILCNTL`(평면 루프 `gen_tri_prologue.py:185-190` 과 같은 형태).  재생성: `mesa/OSRDNMesaTriTable.h` 는 `osrdnTexSlot` 워드 7 이 `0 → 9` 한 곳만 달라졌다(`--check` 의 첫 차이 561 행, 그 뒤 PASS).
- 회귀 규칙 2 개(`gen_tri_prologue.py:991-1004`): 텍스처 표에 ZSTENCILCNTL 슬롯이 정확히 1 개; **평면 표의 비-리터럴 슬롯은 같은 레지스터를 쓰는 텍스처 표에도 같은 슬롯으로 있어야 한다**(두 표는 한 규약).  변이 시험: 슬롯 줄 제거 → 두 규칙 모두 FAIL, 텍스처 슬롯을 SE_CNTL 로 바꿈 → 세 규칙 FAIL(자체시험 rc 1).
- 호스트 하네스(Tri.c 를 그대로 include, Verify.c 링크): `triPrologueTo(tex=1)` 의 ZSTENCIL 워드 = 깊이 코드 0/5/9/21/25 에 `02227072/02227020/02227040/42227020/42227040` — 헤더 상수(`OSRDN_TRI_ZSTENCIL_LESS 0x42227010`, TEST_MASK 0x70, WRITE 0x40000000, shift 4)로 python 이 계산한 값과 5/5 일치.  (첫 python 계산은 WRITE 를 bit 0 으로 잘못 두어 21·25 가 어긋났다 — 헤더 상수로 다시 계산해 바로잡음.)
- 검사기: gen self-test·`--check`·check_hook·sim_pack·sim_class·check_compile PASS.

## 6. 실측 (시작 맵 300 프레임, `+map start`, 오프스크린, 추적 + `rdndump`)

| 항목 | 수정 전(§0, 라이브러리 790585730) | 수정 후(790586567) |
|---|---|---|
| 깊이 표면(640×480×16 비트) 0 / 0xffff / 그 밖 | 49.0 % / 49.0 % / **2.0 %** | 5.2 % / 4.6 % / **90.2 %**(80 행 위로는 100 %, 값 0x80b7–0xeabf = ztrick 범위) |
| 마지막 깊이 제출의 스트림 `RB3D_ZSTENCILCNTL` | 0x02227072(ALWAYS·쓰기 없음) | 0x02227040(코드 9)·0x42227040(코드 25) — 코드대로 |
| 제출 2480 개의 깊이 코드 | — | 0:1904, 21:134, 5:160, 25:138, 9:144 |
| 카드 그림 432,752 / Mesa 위임 0 / 정지 없음 | 동일 | 동일 |
| 그림(`build/g410/g411-before-after.png`) | 무기가 검은 상자 위, 표지판이 잘림 | 가림 정상(표지판 전체·무기 정상), 92,071 화소 차이 |

- 사용자 화면 확인: §7.

## 7. 사용자 확인

- 2026-09-29, 사용자 화면 확인(라이브러리 790586567, 드라이버 2d3234bf, 사용자 gcdsd): "실행된 quake 에서는 아까같은 에러는 보이지 않는거 같습니다" — §0 의 엘리베이터 가림 증상 해소.  G4-11 종결.
