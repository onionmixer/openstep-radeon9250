# M3h — 깊이 버퍼를 표면 크기로 (64×64 해제)

G1 열린 항목 2(`docs/M3A_PLAN.md` 14).  사용자 결정(2026-09-25): 진행.  **이 문서는 코딩 전에 쓴다.**

## 1. 사실 (열어 확인)

| | 사실 | 확인한 곳 |
|---|---|---|
| F1 | 라이브러리 창 배치: 색 0, 깊이 `0x10000`, 텍스처 `0x20000`; 깊이 피치 64·8 KiB 고정 | `mesa/OSRDNMesaTriTable.h` 43–46·449 |
| F2 | 검증기의 클라이언트 창은 `[winStart, winStart + 256 KiB)` | `osrdn_cp.m` case 171 의 `r7WinStart/End` |
| F3 | 커널 별칭(되읽기·다이제스트)은 256 KiB 시험 블록.  case 171 이 별칭에서 읽는 것은 표의 **고정 오프셋 64 워드**(색·깊이 다이제스트, 측정용) 뿐 | `osrdn_cp.m` 다이제스트 자리, M1h 설명 |
| F4 | 사용자 mmap 창(`osrdn_vmap_window`)은 `[winStart, winCeiling)` — VRAM 거의 전부.  **클라이언트는 이 범위를 이미 CPU 로 쓸 수 있다** | `OSRDNDisplay.m` 창 설정·`osrdn_vmap_fix` |
| F5 | 발자국 검사는 `피치 × 4 × CP_R7_ROWS`, **`CP_R7_ROWS = 64` 고정** — R7 계획 규칙 7 은 "× 높이" | `osrdn_cp.m` `cpR7SurfaceFits`·`CP_R7_ROWS`; `docs/R7_PLAN.md` 167–170 |
| F6 | 주 시저 `RE_WIDTH_HEIGHT`(0x1c44)는 허용 목록에 있고 **값 검사가 없다** — 64 행 가정을 강제하는 것이 없다 | `cpR7Allow`, `cpR7ValueAllowed` |
| F7 | 참고 구현의 깊이 버퍼: 피치 = 폭을 32 로 올림, 크기 = 높이를 16 으로 올림 × 피치 × cpp, GPU 페이지(4 KiB) 정렬 | xf86 `radeon_accel.c` 1187–1189, `radeon_exa.c` 807–808 |
| F8 | 색 피치 마스크 `0x1ff8` — 피치는 8 픽셀 단위 | `CP_R7_PITCH_MASK` |
| F9 | 16 비트 깊이는 타일, Mesa `r200_mba_z16` 배치(피치 64 에서만 실측) | 메모리 `r200-measured-rules` 깊이 절 |

**F5+F6 은 지금도 있는 틈이다**: 클라이언트가 주 시저를 크게 쓰면 64 행 발자국 밖(창 뒤 VRAM)에 그릴 수 있다.  F4 때문에 새 권한은 아니지만(그 VRAM 은 이미 CPU 로 쓸 수 있다), 검증기가 말하는 규칙과 하는 일이 다르다.

## 2. 설계

**드라이버(재부팅 1 회)**
- D1 클라이언트 창 = `[winStart, winCeiling)`(F4 와 같은 범위).  커널 별칭·시험 블록은 그대로.
- D2 발자국의 행 수를 **그 스트림의 주 시저에서**: 그리기가 있는 스트림은 `RE_WIDTH_HEIGHT` 를 **반드시** 써야 하고(카드 레지스터는 앞 제출의 값을 기억하므로), 행 = 높이 필드 + 1, 열 = 폭 필드 + 1 ≤ 피치.  색 발자국 = `off + 피치 × 4 × 행`, 깊이 발자국 = `off + 피치 × 4 × 올림16(행)`(16·24 비트 모두 덮는 상한), 깊이 피치는 32 의 배수.
- D3 CAPS 가 클라이언트 창 크기를 알린다(라이브러리가 맞출 수 있게).

**라이브러리(같은 설치로)**
- L1 배치: 색 0(폭 × 높이 × 4), 깊이는 그 뒤 4 KiB 정렬(`올림16(높이) × 올림32(폭) × 2`), 텍스처는 그 뒤 — 전부 창 크기 안이어야 받는다.
- L2 프롤로그: `DEPTHPITCH = 올림32(폭)`, `DEPTHOFFSET = winStart + 깊이 자리`; 64×64 가드는 "창에 맞는가" 가드로.
- L3 폭은 8 의 배수만(F8; 표면 피치 = 폭 = 응용 행 길이, M3g).  아니면 소프트웨어.

**실기(같은 부팅)**
- H1 창 안 발자국 검사: 사용자 매핑으로 창을 무늬로 채우고 큰 표면(예 640×480, 깊이 켬) 전면 그리기 → **발자국 밖 워드가 하나도 안 변했는지**(CPU 로 읽음, 호스트 판정).
- H2 teapot 256×256·640×480 가속 vs 스톡, CARD 판정 + glFinish.
- H3 주 시저가 없는 그리기 스트림·주 시저가 피치보다 넓은 스트림이 거절되는지.

## 3. codex 계획 검토 (한 질문: 허용된 41 레지스터 중 쓰기 범위를 옮기거나 늘리는 것)

41 개 이름은 내가 먼저 참고 헤더에서 python 으로 뽑았다(mesa-amber·Mesa-6.5.3·xf86 `r200_reg.h`/`radeon_reg.h`).

| codex 주장 | 내 검증 (Mesa-6.5.3 `r200_reg.h`) | 판정 |
|---|---|---|
| `RB3D_CNTL` 비트 9 `DEPTH_XZ_OFFEST_ENABLE` 가 `DEPTHXY_OFFSET` 을 켜 깊이 쓰기를 옮긴다 | 195 행 `(1 << 9)`, 299–301 행 `DEPTHXY_OFFSET`·X/Y 시프트 | ✅ → 두 값 제약 |
| `COLORPITCH` 의 타일·마이크로타일(비트 16·17)은 `4×피치×행` 을 넘을 수 있다 | 213–216 행 | ✅ → 피치 마스크 밖 비트 금지 |
| `COLOROFFSET` 은 하위 4 비트를 버린다 | 209 행 `0xfffffff0` | ⚖️ winStart 는 페이지 정렬이라 실해는 없음, 마스크한 값으로 계산 |
| 색 형식은 최대 4 바이트 | 190–200 행 형식 목록(ARGB8888 이 최대) | ✅ |
| `DEPTHPITCH` 의 HyperZ(비트 16–17)·엔디언은 `4×피치×올림16(행)` 에 덮인다 | mesa-amber `r200_reg.h` 91–97 | ⚖️ 덮인다는 주장은 재지 않았다 → **안전 쪽으로 마스크 밖 비트 금지** |
| 시저·TOP_LEFT·SE_VTE_CNTL 은 줄이기만 | 메모리의 시저 실측(넓히지 못한다) | ✅ |

## 4. 확정 설계

**드라이버** — `osrdn_cp.h/.m`, `OSRDNDisplay.m`
1. `rdnCp.winEnd = winCeiling`(사용자 매핑 창의 끝, F4).  case 171 의 `r7WinEnd = winEnd`(없으면 지금처럼 +256 KiB).
2. 그리기가 있는 스트림은 `RE_WIDTH_HEIGHT` 를 **써야** 한다.  행 = 높이 반워드 + 1, 열 = 폭 반워드 + 1(반워드 전체 16 비트 — 11 비트라고 가정하지 않는다, 안전 쪽).
3. 표면이 스트림에 없으면 **드라이버 접두의 표면**(case 표의 색·깊이 자리, 피치 `CP_R6_PITCH`)으로 검사한다 — 카드는 그 값으로 그리므로.
4. 색: `열 ≤ 피치`, `(off & ~0xf) + 피치×4×행 ≤ 창 끝`.  깊이: `열 ≤ 피치`, 피치는 32 의 배수, `off + 피치×4×올림16(행) ≤ 창 끝`.
5. 값 규칙: `COLORPITCH`·`DEPTHPITCH` 는 마스크 `0x1ff8` 밖 비트 0; `RB3D_CNTL` 비트 9 는 0; `DEPTHXY_OFFSET` 은 0.
6. 호스트 오라클 `tools/r7/verify_oracle.py` 를 같은 규칙으로(커널과 대조하는 `sim_r6` 이 쓴다) + 변이.

**라이브러리** — 최대 크기 고정 배치(CAPS 변경 없음: 창이 모자라면 mmap·검증기가 거절 → 소프트웨어)
7. 색 0, 깊이 `0x500000`, 텍스처 `0x780000`; 최대 1280×1024(색 5 MiB, 깊이 `올림16(1024)×올림32(1280)×2` = 2.5 MiB — python 으로 확인).
8. 프롤로그 `DEPTHPITCH = 올림32(폭)`; 가드는 "폭 ≤ 1280, 높이 ≤ 1024, 폭 % 8 == 0".
9. `osrdn_depth_clear(value, 폭, 높이)`: 할당 영역 전체를 16 비트 값으로 **선형** 채우기 + 되읽기(타일과 무관 — 영역의 모든 반워드가 어떤 픽셀이거나 여백).  64×64 깊이 읽기 도구(`osrdn_depth_get`)는 표 그대로(오프셋만 따라감).

## 5. 구현·호스트

**드라이버**: `osrdn_cp.h` `winEnd`; `OSRDNDisplay.m` `rdnCp.winEnd = winCeiling`; `osrdn_cp.m` — `CP_R7_ROWS` 삭제,
`cpR7SurfaceFits(off, pitch, rows, cols, depth)`(오프셋 하위 4 비트 버림·열 ≤ 피치·깊이 피치 32 배수·깊이 행 16 올림),
`cpR7Verify(..., defC, defZ, defPitch)`(접두 표면을 기본값으로 늘 검사, `RE_WIDTH_HEIGHT` 필수, 반워드 전체),
값 규칙 셋(`cpR7ValueAllowed`), case 171 의 창 끝 = `winEnd`(없으면 +256 KiB).
**오라클** `tools/r7/verify_oracle.py`: 같은 규칙(접두 값은 `osrdn_cp.h` 에서 읽음), `WIN_BYTES` = 16 MiB(1280×1024 깊이의 4 바이트 상한 끝 `0xa00000`, python), 사례 U17–U24 추가·U6/U13 은 창 끝 기준으로, 자체시험의 좋은 스트림에 주 시저.  24 사례 모두 의도한 규칙 하나로 판정(사유 문구로 확인).  생성 표 세 사본(`world5.c`·`rdnr7dev.c`·`rdnr7sub.m`) 교체, `world5` 는 사례 실행 때 `C.winEnd = WIN0 + CP_R7_SIM_WIN_BYTES`.  `check_r7b` PASS, `sim_r6`(변이 M3h 10 종 포함) PASS, `sim_r5` PASS.
**라이브러리**: 생성기 `SURF_MAX 1280×1024`, `DEPTH_OFF 0x500000`, `TEX_OFF 0x780000`(자체 단언: 색 5 MiB ≤ 깊이 자리, 깊이 끝 ≤ 텍스처 자리); `triPrologue` 가드(최대 크기·피치 8 배수·폭 ≤ 피치·색 영역이 깊이 자리 앞), `DEPTHPITCH = 올림32(폭)`; `osrdn_depth_clear(value, 폭, 높이)` 전체 할당 선형 채우기 + 되읽기.  `sim_batch` 경우 Z 를 새 가드로(7 단발 + 묶음), 변이 3 종 잡힘.
**teapot**: `RDNTeapotFence=1` 이면 창 전체를 무늬로 채우고 glFinish 뒤 색·깊이 영역 밖 변화 수를 `step=fence` 로.  `judge_teapot`: CARD 기준 = 헤더의 최대 크기 & 폭 8 배수, 울타리 규칙(자체시험 2 종), 파일 이름 `폭x높이`.
**인용**: 편집 전 판 여덟으로 `reaim_diff` 130 키, 끝 줄이 바뀐 2 개와 맨 `:N` 8 개는 손으로(각 줄 열어 확인; M3D 의 맨 인용 955 는 M3e 때부터 옮겨지지 않은 채 남아 있던 것).

**한계(적어 둠)**: `osrdn_depth_get/at`(M1i 깊이 읽기 도구)는 64×64 타일 표 그대로라 깊이 피치가 64 인 표면(폭 33–64)에서만 맞다 — 시험 도구이고 teapot 은 쓰지 않는다.  `rdnr7dev` 의 U6·U13·U21 은 16 MiB 모의 창 끝 기준이라, 실기(창 끝 = winCeiling)에서는 통과로 나올 것이다 — 실기 R7 게이트를 다시 돌릴 때 고칠 것.
- `check_plan_ops`: `build/r7/plan_ops.txt`(끝난 R7a 실기의 16 사례 계획)는 판정 절차가 24 사례로 늘어 맞지 않게 됐다 → 머리에 **HISTORY** 를 적고 `procedure` 줄을 떼어 대조 대상에서 뺐다(검사기가 정한 "역사" 표시 방식).  R7 게이트를 다시 돌리려면 새 계획과 U6·U13·U21 의 재조준이 필요하다.

## 6. 설치

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** |
| 타깃 빌드 `a5dd4d1d` / runid 790345066, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — 다음 부팅부터 |
| 라이브러리 1790272600, teapot 1790272700 | **PASS** |

## 7. 다음 부팅

마운트 → gcdsd(teapot — 사용자) → `RUNID=1790272700 BOOT=<nonce> BUILD=a5dd4d1d bash build/m3h/run_m3h.sh` →
`python3 tools/mesa/judge_teapot.py build/m3h/run-<R>`.  64(회귀)·256·640×480·640×480 컬링, 가속은 울타리 켬.
