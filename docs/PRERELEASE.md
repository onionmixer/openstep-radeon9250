# 공개 전 목록

공개는 **모든 작업이 끝난 뒤**다(2026-09-24, 사용자 결정).  이 문서는 그때 막힐 것을 미리
적어 둔다.  이미 고친 것은 고친 날과 함께 남긴다.

| # | 항목 | 상태 |
|---|---|---|
| 1 | 제출 로그가 기본으로 켜져 있다(1,082 us/제출) | **고침** — M2g(`docs/M2G_PLAN.md`), 출고 기본값 209 us |
| 2 | `.gitignore` 가 `build/` 전체를 뺐다 — 거기 사는 소스 183 개 중 **80 개**가 밖에서 쓰인다(`check-all.sh` 가 여섯을 직접 실행, 나머지는 문서 인용).  깨끗한 클론은 자기 스위트에서 실패했을 것이다 | **고침**(2026-09-24) — `build/**` 에서 `*.py`·`*.sh` 만 되살림.  `git check-ignore` 로 필요한 80 개 포함·산출물 7,632 개 제외를 양방향 확인 |
| 3 | 라이선스 — matrox 와 같게, Mesa 모듈도 matrox Mesa 모듈과 같게 | **고침**(2026-09-24) — `LICENSE` 동일 확인, `NOTICE` 에 R200 CP 마이크로코드(MIT, AMD) 전문과 Mesa 절, `docs/R0_4_LICENSES.md` 3 |
| 4 | **인용 대상 45 개가 프로젝트 밖이다** — 형제 프로젝트(`openstep-matrox-remade`·`openstep-intel1000`·`openstep-mesa342`), `ref/openstep`, `pcils/scan-nextonion.txt`.  떼어낸 저장소에선 `check_citations.py` 가 `open()` 에서 예외로 **판정 없이 죽고**, 스위트는 그것을 FAIL 로 센다 | **열림** — 고치는 방식이 분리 방법에 달려 있다.  "대상 없음" 을 조용히 건너뛰게 만들면 안 된다([[checker-discipline]]): 건너뛴 수를 이름과 함께 말하고, **프로젝트 안** 대상이 없을 때는 FAIL |
| 5 | `ref/upstream/`(인용 대상 53 개)은 커밋하지 않고 `tools/fetch-ref.sh` 가 다시 받는다 | **고침**(2026-09-24) — README 에 둘 다 있었으나 **순서**가 없었다.  "새로 받은 트리에서는 먼저 fetch-ref" 를 스위트 줄에 붙였다 |
| 6 | Mesa 패키지가 Mesa 의 `COPYRIGHT`·`COPYING` 을 바이트 그대로 실어야 한다 | **고침**(2026-09-29) — `OSRDNMesaAccel` 이 `COPYRIGHT`·`COPYING`·`README.Mesa` 를 자기 문서 디렉터리 아래 싣고 빌더·검증기가 `cmp` 한다(`docs/REL1_PACKAGING_PLAN.md` 11, 13) |
| 7 | `NOTICE` 의 "앞으로 재현해야 할 것" — NetBSD radeonfb(BSD 3-clause, Itronix)·xf86-video-ati 등에서 **코드를 옮긴 곳이 실제로 있는지** | **대조함(2026-09-24), 옮긴 코드 없음.**  우리 소스 51 개(`OSRDNDisplay/**`·`mesa/*`, 마이크로코드 헤더 제외)를 `ref/upstream` 의 C 소스 6,913 개(의미 있는 줄 1,249,251 개)와 python 으로 대조: 공백을 정규화한 줄이 **세 줄 이상 연속으로** 한 참고 파일과 같은 구간 = **2 건**, 둘 다 `typedef struct { const char *name; unsigned int offset; }` 보일러플레이트(`osrdn_pll.h` 23-27, `osrdn_record.m` 111-113)이고 참고 쪽에선 연속도 아니다.  **한계**: 정확한 줄 일치만 본다 — 이름을 바꿔 옮긴 코드는 못 잡는다.  레지스터 주소·값은 `docs/R0_4_LICENSES.md` 2 의 방침대로 **사실**로 쓴 것이다 |
| 8 | 공개될 트리의 실 IP | **0 건** 확인(2026-09-24).  `nextonion` 은 호스트 이름이고 이미 공개된 matrox 에도 있다 |
| 9 | `.pyc` 60 개가 추적되고 있었다 | **고침**(2026-09-29) — 추적 해제, `.gitignore` 에 `*.pyc`(이력에는 남는다) |
| 10 | codex 원문 로그 58 개(`docs/review/*_log*.txt`) 공개 여부 | **열림** — `docs/REL1_PACKAGING_PLAN.md` D9 |
