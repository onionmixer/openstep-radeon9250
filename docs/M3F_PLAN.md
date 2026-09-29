# M3f — 링 끝까지 채우지 말고 BSD 처럼 감는다

선행: `docs/M3E_PLAN.md` 8.  **이 문서는 코딩 전에 쓴다.**

## 1. 사실

- M3e A: 붙잡은 108 워드 제출만 새 CP 에 보냈더니 **첫 되감기**에서 걸쇠.  그리기 제출이 링 끝의 48 워드를
  PACKET2 로 채우고 0 부터 쓴 순간, CP 가 패딩 첫 워드(4048)에서 한 워드도 나아가지 않았다.
- 같은 패딩 가지가 752·800(teapot 일반)·1248(R6M) 워드에서는 성공했다.  왜 48 만 실패하는지는 모른다.
- **참고 구현은 링 끝까지 채우지 않는다**: FreeBSD `radeon_commit_ring` 은 tail 을 16 워드 정렬까지만 PACKET2 로 채우고
  `OUT_RING` 이 `write &= mask` 로 패킷을 끝 너머로 잇는다.  Linux r100 도 같다(`align_mask = 16 - 1`).
- **이 기계의 CP 는 자연 감김을 이미 처리했다**: R5 실기 PASS(부팅 fdca7cd1, `docs/R5_PLAN.md` 13)의 SUBMIT 이
  1024 워드를 3088 에서 16 으로 **패딩 없이** 감았고(PACKET0 가 끝을 가로지름), 표지가 전부 되읽혔다.
- "3D 패킷은 링 끝을 넘지 않는다"는 규칙의 근거는 측정이 아니라 조심이었다(`osrdn_cp.m` `cpR6Submit` 주석
  "no 3D packet has crossed it on the machine").  모형(`world5.c`)이 그것을 실패로 정해 두었을 뿐이다.

## 2. 바꿀 것 (드라이버 한 곳)

`cpR6Submit`: `pad` 를 없앤다.  길이는 지금처럼 16 워드로 올리고 남는 칸은 PACKET2(= BSD 의 16 정렬 패딩),
쓰기는 `cpPut` 이 이미 `& C_RPTR_MASK` 로 감싼다.  새 wptr = `(p + len) & mask`.  나머지(펜스, WPTR 쓰기, 대기)는 그대로.

## 3. 호스트

- `tools/r5/sim/world5.c`: "a 3D packet across the ring end" 실패 규칙을 뺀다(읽기는 이미 `& mask`).  "near the end" 시험은
  **끝을 가로지르는** 제출로 기대값을 바꾼다(기대 wptr 는 python 으로).
- `tools/r6/sim_r6.py` 의 변이 "a 3D packet may cross the ring end"(= 새 동작) 를 없애고, 반대 변이
  "the draw is padded to the ring end again" 을 `check_r5_src` 규칙이 잡게 한다.

## 4. 다음 부팅 시험

`run_m3e.sh` 그대로(드라이버 빌드 번호만 새 것): A 200 회 — 제출 160 워드 주기로 약 8 바퀴, **M3e 가 걸린 4048 자리를
포함한** 여러 위치에서 끝을 가로지른다(python 으로 목록) → 통과하면 teapot 일반·컬링 → `judge_teapot.py` 로 그림 판정.
걸리면 보관 기록이 어디서 멈췄는지 말한다.

## 5. codex 계획 검토 (한 질문: 패딩을 없애면 "끝을 안 넘는다"에 기댄 다른 곳이 있는가)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 링·섀도 접근은 `cpPut`(가림), 전체 대조, 채우기뿐 | `grep "cpShadow\[\|cpRing(c)"` 전수: 145·372·422·434·442·830·831 — 셋 외 없음 | ✅ |
| `W_RPTR` 은 가린 rptr 와 가린 목표의 **같음** 비교 | `osrdn_cp.m` 185–186 열어 확인 | ✅ |
| STOP 은 가린 `c->wptr` 까지 대기 | `osrdn_cp.m` 1039–1044 | ✅ |
| 제출 전 따라잡기 검사는 가린 위치끼리 | `osrdn_cp.m` 2681–2684 | ✅ |
| `rptrAfter` 는 기록일 뿐 | `osrdn_cp.m` 2031 | ✅ |
| 주석 둘이 낡는다(`cpR6Submit` 머리, `osrdn_cp.h` `CP_R6_WORDS`) | 둘 다 열어 확인 | ✅ 함께 고친다 |

곁에서 본 것: MAP 은 링을 `PACKET2` 전부가 아니라 `CP_GUARD_HEAD`/`PACKET2` 쌍으로 채운다(`cpFillBlock`) — R5 계획 표의 "전부 PACKET2" 와 다르다.  이번 변경과는 무관(첫 바퀴의 낡은 내용을 CP 가 읽었다면 REG5 가 바뀌었을 텐데 걸쇠 기록의 `reg5=5a5a0005` 는 그대로).

## 6. 구현·호스트

- `osrdn_cp.m` `cpR6Submit`: `pad` 삭제, `target = (p + len) & C_RPTR_MASK`, 머리 주석에 근거(M3e·R5 13·FreeBSD).  `osrdn_cp.h` `CP_R6_WORDS` 주석 갱신.
- `world5.c`: "a 3D packet across the ring end" 실패 규칙 삭제(읽기는 이미 가림).  링 끝 시험 기대값(python): 깊이 case 1 은 접두 4032→4064, 그리기 64 워드 4064→**32**; 색 case 6 은 80 워드 4064→**48**.  **그림은 그대로**(깊이 576·색 576).  `sim_r5` PASS.
- `sim_r6.py`: 옛 변이 "a 3D packet may cross the ring end" 삭제(이제 정상 동작).  `check_r5_src` 규칙 `m3f-wrap-like-bsd` + 변이 2 종(끝까지 채우기 복귀 / 가림 없이 쓰기) 잡힘.  `sim_r6` PASS.
- 다음 부팅 A 200 회의 끝 넘김(python): 7 회 — `(26 그리기 4048) (52 접두 4080) (77 그리기 4016) (103 그리기 4080) (128 그리기 3984) (154 그리기 4048) (180 접두 4080)`.  **M3e 가 걸린 자리(그리기 4048)를 두 번** 지난다.

## 7. 설치

| 게이트 | 결과 |
|---|---|
| 인용 이동 | `osrdn_cp.m` 편집 전 파일을 되살려 `reaim_diff` 100 키 + 끝 줄이 바뀐 범위 3 개(1980-2041→1987-2046, 1981-2000→1988-2005 — 기대 문자열도 새 `cpPut(c, p + k, …)` 로, 2005-2031→2010-2036) 손으로, 맨 `:N` 2 개(M3C), `world5.c` 5 키.  모든 문서 인용 0 실패 |
| `bash tools/check-all.sh` | **PASS** |
| 타깃 빌드 `0b22f49d` / runid 790284600, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — 다음 부팅부터 |

## 8. 다음 부팅

`BOOT=<nonce> BUILD=0b22f49d bash build/m3e/run_m3e.sh` — A 200 회(끝 넘김 7 회, M3e 의 4048 자리 2 회) → 통과하면 teapot 일반·컬링(화면 권한: 사용자 gcdsd) → `python3 tools/mesa/judge_teapot.py` 로 그림 판정.

## 9. 결과 (부팅 00d2c737, 드라이버 0b22f49d, 실행 790334398) — **PASS**

`build/m3e/run-790334398/`.

- **A**: 붙잡은 108 워드 제출 200 회 **전부 그려짐**(`RDNREPLAY step=end rounds=200 all-drawn=1`).  링 끝 넘김 7 회, M3e 가 걸린 자리(그리기 4048)를 두 번 지났다.
- **teapot 일반**: submitted 6,400, REFUSED 0.  **컬링**: culled 2,909, submitted 3,491(= 6,400 − 2,909, python), REFUSED 0 — 두 부팅 연속 걸리던 자리를 지나 끝까지.
- 마지막 RECORD `r=0` — CP 는 걸쇠 없이 살아 있다(`kept` 줄 0).
- **그림**(`judge_teapot.py`, 스톡 기준은 같은 소스의 스톡 링크 `build/m3a/1790272100`): `judge_teapot: PASS` —
  64×64 CARD 6,400 전부 카드, 다른 화소 549(1 차이 456, 2 차이 53, 그 이상 40, 최대 75), 2×2 덩어리 0;
  CULL 3,491 + 2,909 = 6,400, 다른 화소 20, 덩어리 0.  판정 입력은 `judge/`.

**결론**: 컬링 teapot 의 CP 걸쇠는 `cpR6Submit` 의 "링 끝까지 PACKET2 로 채우기" 가 원인이었다(적어도 48 워드 채움에서 CP 가 채움 첫 워드에서 멈춤).  FreeBSD 와 같은 자연 감김으로 바꾸자 같은 자리·같은 스트림이 통과했다.  왜 작은 채움만 멈췄는지는 재지 않았다 — 그 경로가 없어졌으므로 잴 이유도 없다.
