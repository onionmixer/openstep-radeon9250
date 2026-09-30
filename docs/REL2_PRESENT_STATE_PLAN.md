# REL2 — present 블릿이 2D 상태를 스스로 싣는다 (radeon 1.1)

작성 2026-09-30.  코딩 전 계획이다.  codex 판정표는 끝 절.  발견 경위는
`openstep-sdl20/docs/PLAN_RELEASE_OPENSTEP5.md` 21–22 절.

## 1. 증상과 확인된 사실

| # | 사실 | 근거 |
|---|---|---|
| F1 | 부팅 뒤 **카드에서 clear 를 한 번도 하지 않은** 클라이언트(GLQuake)가 radeon present 로 그리면 창이 로딩 콘솔에서 멈춘다(소리·입력·게임은 돈다) | 사용자 관찰, 실행 A–E(설치 1.4·1.3·G5 개발판, 재부팅 직후 포함) |
| F2 | 같은 부팅에서 radeon teapot(clear 1 회)을 먼저 돌리면 그 뒤 GLQuake 는 화면이 나온다 | 실행 G2, 사용자 관찰 |
| F3 | 증상은 SDL2 판과 무관 — openstep.4 를 정적으로 담은 1.3·G5 개발판도 같다 | python 판별 문자열(PLAN_RELEASE_OPENSTEP5.md 21) |
| F4 | 블릿은 매번 "성공": `RDN-P rects=2212 covered=139868 busy=1`, 커널 `RDN-G3 present ok=425349 refused=1` | 로그 |
| F5 | `cpPresent`(`osrdn_cp.m` 3891–) 의 13 워드: WAIT(3D) · GMC · SRC/DST_PITCH_OFFSET · SRC_X_Y/DST_X_Y/DST_WIDTH_HEIGHT · WAIT(2D).  **`DEFAULT_SC_BOTTOM_RIGHT`(0x16e8)·`DP_CNTL`(0x16c0) 없음** | 원문 |
| F6 | 두 레지스터를 쓰는 곳은 부팅 R4 엔진 시험(MMIO, `osrdn_engine.m` 486·516·558)과 **clear**(`cpClear`, `osrdn_cp.m` 4048·4055) 뿐 | 전수 grep |
| F7 | CP 기동 6 단계에 `reset`(엔진 리셋)이 있다 — 부팅 엔진 시험이 써 둔 값을 리셋이 지운다고 본다(부팅 순서: 엔진 시험 → 첫 open 의 자동 기동) | B7 `r7bAutoStart`, 커널 로그 순서 |
| F8 | 참조: DRM `radeon_cp_dispatch_swap`(linux-3.10 `radeon_state.c` 1373–) 도 우리 present 와 같은 워드만 보낸다 — 잘라내기·방향은 **X 서버의 `RADEONEngineRestore`**(xf86-video-ati `radeon_accel.c` 389–420: `DEFAULT_SC_BOTTOM_RIGHT` = RIGHT_MAX\|BOTTOM_MAX 등)가 써 둔 값에 기댄다.  이 스택엔 X 서버가 없다 | 참조 원문 |
| F9 | present 의 GMC 에는 `WR_MSK_DIS`(bit 30)가 있어 `DP_WRITE_MASK` 는 쓰이지 않는다; `DST_CLIPPING` 은 없어 기본 잘라내기(`DEFAULT_SC_BOTTOM_RIGHT`)를 쓴다 | `C_PRESENT_GMC` 0x52cc36f3, `present_oracle.py` 비트 |

**원인(가설, 수정 후 실기로 증명)**: 엔진 리셋 뒤 `DEFAULT_SC_BOTTOM_RIGHT`(와/또는 `DP_CNTL`)가 리셋 값이라 present 블릿이 잘려 나가거나 엉뚱한 방향으로 간다.  clear 가 한 번 돌면 둘 다 제 값이 되어 가려진다.  둘 중 어느 하나인지는 가르지 않는다 — X 서버가 **둘 다** 쓰므로 둘 다 싣는다.

## 2. 수정

`cpPresent` 의 워드에 clear 와 같은 **세** 쌍을 넣는다(13 → 19) — X 의 EXA 복사 `Emit2DState`(`radeon_exa_funcs.c` 107–114)가 복사마다 쓰는 것 중 복사에 닿는 셋, clear(`osrdn_cp.m` 4048·4054·4055)와 같은 값:

```
WAIT_UNTIL        3D_IDLECLEAN|HOST_IDLECLEAN
DEFAULT_SC_BOTTOM_RIGHT  C_SC_MAX (0x1fff1fff)          <- 새로
DP_WRITE_MASK     0xffffffff                            <- 새로 (GMC 의 WR_MSK_DIS 로 쓰이지 않을 것이나, EXA·clear 와 같게)
DP_CNTL           C_DP_CNTL_L2R_T2B (3)                 <- 새로
DP_GUI_MASTER_CNTL  C_PRESENT_GMC
SRC_PITCH_OFFSET, DST_PITCH_OFFSET
SRC_X_Y, DST_X_Y, DST_WIDTH_HEIGHT
WAIT_UNTIL        2D_IDLECLEAN|HOST_IDLECLEAN
```

- L2R_T2B 가 맞는 이유: 원본(3D 창의 표면)과 목적지(화면, 카드 주소 0)는 서로 다른 메모리라 겹침이 없고, 좌표는 지금처럼 왼쪽 위에서 시작한다.
- 매 present 에 싣는다 — 부팅 기동의 `reset` 뿐 아니라 CP 복구(`recover=2`, 엔진 리셋)도 같은 상태를 지우므로 "한 번 복원" 은 복구 경로마다 따로 챙겨야 한다.  워드 4 개 = 16 B/블릿, 프레임당 present 행 7.5 회(judge_g50) — 무시할 비용.
- present 워드는 커널이 만든다(클라이언트 검증기 대상 아님, `check_r5_src` g3-present: `cpR7Verify` 를 쓰지 않음).

## 3. 호스트 쪽 고정물 갱신

- `tools/r7/present_oracle.py` `words()`: 세 쌍 추가(레지스터 주소·값은 이름에서, 참조 줄 인용).  자체 검사 기대 수 13 → 19.
- **링 채움**: 제출은 PACKET2 로 16 의 배수까지 채운다(`osrdn_cp.m` 2345 행 부근) — 19 워드는 32 워드가 된다.  `world5.c` 2066–2080 은 `capCount == 16`, 위치 번호 [3]·[5]·[6]·[8]·[9]·[10], 두 번째 행 [8]·[9] 를 **숫자로** 박아 두었다 → 오라클이 `present_expect.h` 에 워드 수·채움 수·레지스터 위치를 **이름 붙은 상수로** 생성하고 world5 는 그것만 쓴다(숫자 재박기 금지).
- `tools/r5/sim_r5.py` 가 `tools/r5/sim/present_expect.h` 를 다시 생성 → `world5.c` 의 G3 비교가 커널 워드와 새 오라클을 대조.
- `tools/r5/check_r5_src.py` g3-present: 두 `#define` 값(0x16e8·0x16c0·0x1fff1fff·3)과 `cpPresent` 안의 두 `C_P0N(...)` 쌍을 요구, **변이 2 개**(각 쌍을 뺀 소스는 실패해야).
- 인용 재조준: `osrdn_cp.m` 에 줄이 늘어 뒤쪽 인용이 밀린다 → 편집 전 사본 + `tools/oracle/reaim_diff.py`(메모리 규칙).
- 스위트: 싼 검사(인용·소스 규칙·sim_r5) 먼저, `tools/check-all.sh` 는 마지막 한 번.

## 4. 빌드·패키징·실기 판정

1. 드라이버 빌드: REL1 과 같은 사슬(`pack_r2b0.py` → `target-build-r2b0.sh` → `check_reloc_r2b0.py` → `host_release_gates.py --driver`), 설치 전 `nm -u` 심볼 검사(메모리 규칙 "드라이버 변경 순서").
2. 버전 1.1(Matrox 명명 규칙): `Default.table`·`Instance0.table` Version, `pkg/OSRDNDisplay.info`, README·릴리스 노트.  **Display 패키지만 새로** — MesaAccel(790662776)·Demos(rdn.1)은 바뀌지 않는다(자산은 1.0 판을 그대로 다시 싣는다, 이름 규칙은 공개 단계에서 확정).
3. `/me/packages/drivers/OSRDNDisplay/` 교체(옛 것은 old), 사용자 설치 → 재부팅.
4. **판정(그림)**: 재부팅 직후 **teapot 없이** 첫 클라이언트로 GLQuake(radeon) — 사용자가 화면 진행을 본다.  이어서 teapot 뒤 GLQuake 도 정상(회귀 없음).  계수: present ok, CP 복구 발생 시에도 화면 유지(관찰되면).
5. 그 뒤 SDL2 openstep.5·sdl2quake 1.4·radeon 1.1 을 함께 커밋·공개(사용자 결정 2 번).

## 5. 위험

- R1 가설이 틀릴 수 있다(다른 상태 레지스터) — 판정은 그림으로만.  틀리면 X 의 `RADEONEngineRestore` 목록(`DP_DATATYPE`·`SURFACE_CNTL`·`DEFAULT_OFFSET` 등)으로 넓힌다.
- R2 드라이버 재설치·재부팅은 사용자 몫, 부팅마다 CP 는 한 번(메모리 규칙).
- R3 Matrox 는 무관(다른 드라이버, 자체 WARP 경로).

## 6. codex 교차검토 (gpt-6-astra, 한 호출 한 주장)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| Q1 | (PARTLY) X 드라이버는 엔진 리셋이 2D 상태를 지운다고 보고 `RADEONEngineRestore`(`radeon_accel.c` 370–422: `DEFAULT_SC_BOTTOM_RIGHT` 405–406 등, **`DP_CNTL` 은 안 씀**)를 리셋·초기화 뒤에 부른다 — 단 "모든 리셋 뒤" 는 과장(`RADEONRestoreMemMapRegisters` 의 리셋 4077·4164 뒤엔 없음).  EXA 복사는 복사 준비마다 `Emit2DState` 로 `DEFAULT_SC_BOTTOM_RIGHT`(107)·`DP_WRITE_MASK`·`DP_CNTL`(114)를 쓰고, GMC 에 `DST_CLIPPING` 없음(기본 잘라내기 사용) | 원문 열어 확인: `radeon_dri.c` 1219–1221 주석 "**DRM_RADEON_CP_INIT does an engine reset, which resets some engine registers back to their default values, so we need to restore those engine register here**", `radeon_exa_funcs.c` 102–116·263–276, `radeon_reg.h` 643–645, `radeon_accel.c` 140–148 | ✅ 채택(과장 부분은 우리 설계와 무관) — 세 쌍을 **present 마다** 싣는 설계를 EXA 복사에 맞춤 |
| Q2 | 의존성 목록: `osrdn_cp.m` 1452(13)·3873–3874 주석; `present_oracle.py` 5–14·53–60·169–170(len 13, [8]·[10]); `present_expect.h`(생성물); `sim_r5.py` 272·**284(`g3PresentWant[13]` 을 오라클과 따로 박음)**; `world5.c` 2066·2071(`capCount == 16`)·2072–2076(13 경계)·2077–2081(위치 3,5,6,8,9,10)·2086–2087(두 번째 행 [8]·[9]); `check_r5_src` g3-present 는 새 쌍을 검사하지 않으나 기존 규칙·변이는 살아남음(clear 의 DP_CNTL 변이 앵커는 8 칸 들여쓰기 — present 를 4 칸으로 쓰면 충돌 없음); Mesa 쪽 `sim_present.py`·`judge_m1b.py` 무관; 인용 19 개가 +3 줄 밀려 깨짐(목록), 문서 인용 다수; `build/g4/model.py` 는 13 워드로 계산한 **역사적** 모델; 링·배치 한도 영향 없음(16 의 배수로 32 워드, 링 4096) | 연 줄: `present_oracle.py` 160–172, `sim_r5.py` 278–288, `check_r5_src.py` 1600–1606, `world5.c` 2055–2112, `osrdn_cp.m` 2345 부근 채움; PACKET0 헤더 python 계산 `0x5ba`·`0x5b3`·`0x5b0`, SC_MAX `0x1fff1fff` — codex 값과 일치; `cpPresent` 를 참조하는 도구는 `check_r5_src.py`·`sim_r5.py` 둘 뿐(grep) | ✅ 채택 — 3 절 목록을 이것으로 확정.  인용은 편집 전 사본 + `reaim_diff.py` 로 일괄, `build/g4/model.py`·역사 문서는 측정 당시의 기록이라 고치지 않는다 |

## 7. 구현·빌드 (2026-09-30)

- `osrdn_cp.m`: `C_PRESENT_WORDS` 19, `cpPresent` 첫 WAIT 뒤 세 쌍(`/* REL2 */`), 머리 주석에 이유와 참조 줄.  `present_oracle.py`: 세 쌍·`DEFAULT_SC_RIGHT_MAX|BOTTOM_MAX`(radeon_reg.h 643–645)·자체검사(길이 19, 위치 14·16, 새 여섯 워드 `0x5ba 0x1fff1fff 0x5b3 0xffffffff 0x5b0 3`).  `sim_r5.py`: 워드 수·링 길이(32)·위치를 오라클 워드에서 찾아 `present_expect.h` 에 이름 상수로(`G3_IX_GMC` 9 … `G3_IX_WH` 16 — codex 예측과 같음).  `world5.c`: 숫자 대신 그 상수, 실행 뒤 `R(0x16e8)=0x1fff1fff·R(0x16cc)=0xffffffff·R(0x16c0)=3` 확인.  `check_r5_src.py` g3-present: 세 쌍이 GMC 앞에 있어야, `C_PRESENT_WORDS` 19, 변이 3(각 쌍 삭제) — 전부 잡힘.
- 싼 검사: `sim_r5` PASS, `check_r5_src` PASS, 인용 — 편집 전 사본으로 `reaim_diff.py` 28 개(osrdn_cp.m·world5.c·check_r5_src.py) + openstep-sdl20 HEAD 판 `SDL_openstepvideo.m` 으로 22 개(다른 세션의 부분 갱신 변경이 밀어낸 것) 이동, 사람 몫 0, 전 문서 0 failed, 자체검사 PASS.
- 버전 1.1: `Default.table`·`Instance0.table`·`pkg/OSRDNDisplay.info`.
- 드라이버: `pack_r2b0.py` stamp **fb454446** runid **790754867** → 실기 `target-build-r2b0.sh` OSRDNBUILD PASS(reloc sum `14642 525`, 도구 `37957 52` 1.0 과 같음) → `check_reloc_r2b0.py` PASS → `host_release_gates.py --driver` PASS.  `nm -u` 21 개, 1.0(790662775)과 동일.
- 패키지(`build/rel2-pkg.sh`): build·verify(reloc == 판정 바이트)·BOM 겹침 PASS.  1.0 대비 18 파일 중 BOM·`.info`·두 표(Version)·reloc 만 다름(python).  배치 `/me/packages/drivers/OSRDNDisplay/`(1.1), 1.0 은 `/me/packages/old/OSRDNDisplay-1.0/`.  빌드 트리 사본 `/usr/local/rel1/build-rel2`.

## 8. 실기 판정 (2026-09-30, 부팅 08b0babd, 드라이버 build=fb454446)

- 설치 확인: 영수증 Version 1.1, 설치된 reloc sum `14642 525` == 빌드, 커널 `RDN-R2B0 init boot=08b0babd build=fb454446`.
- **부팅 뒤 카드의 첫 클라이언트 = GLQuake**(자동 기동 09:46:21 을 GLQuake 가 일으킴), 이 부팅에서 teapot·clear 0 회.  두 번째 실행(09:47:28–36)에서 **사용자 확인: 게임 화면까지 진행**.  (첫 실행 09:46:19–34 는 사용자가 다시 보자고 해 판정에 쓰지 않는다.)  수정 전 같은 조건(A–E, 재부팅 직후 D 포함)은 전부 로딩 콘솔에서 멈췄다 → **수정 확인**.
- 계수: 300 tick, `RDN-C delegated=0`, `RDN-P rects=2212 covered=139868`.
- 회귀: 같은 부팅에서 teapot(clear 1) 뒤 GLQuake — 두 번째 실행(09:49:18–26)에서 **사용자 확인: 게임 화면까지 진행**.  (첫 번째 09:48:24–32 는 사용자가 다시 보자고 함.)

## 9. 공개 (2026-09-30)

- 워크스페이스 `check-all` PASS(두 번째 실행; 첫 실행에서 잡힌 두 건 — 옛 작업 일지의 금지 출처 파일명, `G3_PRESENT_PLAN.md` 의 bare `:N` 인용 5 개 — 을 고친 뒤).
- 공개 커밋은 HANDOFF 3 절대로: 원격 main `7a4d489` 를 부모로, `docs/review` 판정표 외 44 개를 뺀 트리 → `ed2c065`(blob 710 개 0 건).  첫 시도 `36dc86d` 는 blob 검사가 REL1 계획 23 절에 글자 그대로 적힌 검사 패턴 이름을 잡아 버렸다(비밀 아님) — 문구를 바꾸고 다시.
- main·`v1.1` = `ed2c065`, 자산: Display 1.1(`73a0be53…`) + MesaAccel 1.0·Demos rdn.1(v1.0 자산과 SHA-256 동일).  재다운로드 `sha256sum -c` 전부 성공.
- 함께: SDL2 `v2.32.10-openstep.5`(`903a4ff`), sdl2quake `v1.4`(split `aeaae2b`, libre 1.0 은 기존 자산).
