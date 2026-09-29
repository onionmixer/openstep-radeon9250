# G4 — glquake 를 위한 Mesa 추가 작성 (계획, 코딩 전, codex 교차검토 대상, 2026-09-26)

G3c(깊이 clear 형식) 뒤의 다음 목표.  Matrox 때 teapot 뒤에 glquake 가 요구한 것을 Mesa 훅에 더한 선례(`../openstep-quake/docs/Q2_GLQUAKE_PLAN.md`·`Q3_PIPELINE_REASSESSMENT.md`·`Q5_GL_COVERAGE_AUDIT.md`, `../openstep-matrox-remade/docs/M1_4E2…E9`)를 읽고, radeon 에서 같은 일을 **무엇을·어떤 순서로·어느 쪽(라이브러리/커널/실기)에서** 해야 하는지 정한다.  숫자는 전부 `build/g4/model.py` 가 계산한다(§4).

## 0. 범위와 전제

- 대상: `../openstep-quake`(sdl2quake-openstep, LibreQuake pak)를 `libGL_radeon.a` 로 링크해 **전 삼각형이 카드에서, 그림이 stock 과 같고, 속도가 쓸 만한** 상태.  Matrox 는 174 ms/프레임(5.7 fps)에서 시작해 WARP 전가속으로 갔다(HANDOFF_SDL2QUAKE.md 21 행).
- 전제(G3 까지 확정): 삼각형·구로·블렌드(SRC_ALPHA/1−SRC_ALPHA)·깊이(LESS·쓰기)·텍스처(ARGB8888 8×8 하나, NEAREST, REPEAT/CLAMP_LAST 실측)·present·카드 clear·**뒷면 컬링은 이미 훅이 한다**(`OSRDNMesaHook.c:897`; Mesa 3.4.2 는 `RenderVBCulledTab` 로 컬링된 삼각형을 우리에게 주지 않는 경로도 있으나 M3b 가 그 반대 경로를 확인했다 `vbrender.c:680`).
- SDL2 는 건드리지 않는다(사용자 지시).  포트(`openstep-quake`)는 최소 변경(§5 G4-0 b).

## 1. glquake 가 실제로 요구하는 것 — 원본 전수 (python, `gl_*.c` 14 파일 + 포트 2 파일)

`upstream/sdlquake/gl_*.c` 의 `gl*(` 호출 전수(총 64 진입점)를 python 으로 세고 인자 상수를 모았다.  실행 표면에 드는 것만 적는다(`gl_test.c` 는 `#ifdef GLTEST`, 안개는 주석 처리 — Q5 가 확인).

| 상태 | quake 의 사용 | 자리 | 지금 우리 | 필요 |
|---|---|---|---|---|
| glDepthFunc | **LEQUAL**(기본), **GEQUAL**(`gl_ztrick 1` 기본: 홀수 프레임 LEQUAL+범위 (0, 0.49999), 짝수 GEQUAL+(1, 0.5), 깊이 clear 생략 `gl_rmain.c:1006`) | `gl_rmain.c:1013` | LESS 만 `OSRDNMesaClass.c:342` | LEQUAL·GEQUAL(+ALWAYS) |
| glDepthMask | 0/1 (라이트맵·물·불꽃) | gl_rsurf.c 679·746, gl_rlight.c 123 | 쓰기 ON 만 | 쓰기 OFF |
| glDepthRange | 총 모델 0..0.3, ztrick 1..0.5 | `gl_rmain.c:707` | Mesa 가 창 z 에 반영(우리는 창 z 를 보냄) | 없음(확인만) |
| glBlendFunc | (SRC_ALPHA, 1−SRC_ALPHA) 9 곳, **(ZERO, 1−SRC_COLOR)** 라이트맵 2 곳, **(ONE, ONE)** 플래시블렌드 | `gl_rsurf.c:382`, `gl_rlight.c:127` | 첫 쌍만 `OSRDNMesaClass.c:362` | 두 쌍 더 |
| glAlphaFunc | GREATER 0.666 — 초기화 때 켜지만 **매 프레임 R_SetupGL 이 끄고**(`gl_rmain.c:938`) 월드·모델은 꺼진 채 그린다; 켜는 곳은 **스프라이트**(`gl_rmain.c:228`)와 **2D**(gl_draw.c 595·850: 콘솔·HUD 글자의 알파 구멍) | `gl_vidsdl.c:449` | 켜진 상태 = RasterMask 밖 → 스프라이트·2D 만 소프트웨어(월드는 무관) | 하드웨어 알파 테스트(G4-3); 그 전엔 그대로 소프트웨어 |
| glTexEnv | MODULATE 12, REPLACE 11, BLEND 2 (**BLEND 는 multitexture 분기 안**) | `gl_rsurf.c:452` | REPLACE 만 | MODULATE |
| glCullFace | FRONT(기본), BACK(거울) | gl_rmain.c 912-915 | 훅이 컬링 `OSRDNMesaHook.c:897` | 없음 |
| glShadeModel | FLAT/SMOOTH | gl_rmain.c 563·573 | 둘 다 | 없음 |
| glTexImage2D | GL_RGBA 14 곳(내부 `gl_solid_format 3`/`gl_alpha_format 4`), **크기 8×8 ~ 512×512**(lq_e0m1 에 512×512), REPEAT 만 | gl_draw.c GL_Upload8/32 | G4-0 당시 8×8 하나 → G4-1b: POT 8..512 `OSRDNMesaClass.c:306` | POT 임의 크기·다중 텍스처·아레나 |
| glTexSubImage2D | 라이트맵 블록 갱신(동적 광원) 3 곳 | gl_rsurf.c | 없음 | 부분 갱신 |
| 필터 | 엔진 기본은 min `GL_LINEAR_MIPMAP_NEAREST` 이나 **포트가 VID_Init 에서 무조건 LINEAR/LINEAR 로 덮어쓴다**(`gl_vidsdl.c:476`; 그 위 주석 "역사적" 은 낡았다 — 코드가 살아 있다) | gl_draw.c·포트 | NEAREST/LINEAR | **지금 포트엔 없음**(밉은 G4-3 선택) |
| 라이트맵 형식 | `-lm_4` 로 RGBA(Matrox 포트가 그렇게 돌린다) | Q5 §3 | RGBA 텍스처 | 없음(포트 인자) |
| multitexture | `gl_mtexable = false` — Mesa 3.4.2 는 ARB 만 광고 | `gl_vidsdl.c:224` | — | 없음 |
| 팔레트 텍스처 | `is8bit = false` | `gl_vidsdl.c:84` | — | 없음 |
| glClear | 색·깊이(ztrick 이면 깊이 생략) | gl_rmain.c | G3b/G3c | 없음 |
| Fog·Lines·Scissor·Stipple·PolygonOffset·Stencil·정점배열 | 미사용/주석/`#ifdef` | Q5 §2 | — | 없음 |

**결론**: 새로 받아야 할 상태는 **깊이 비교 2(+쓰기 OFF)·블렌드 쌍 2·MODULATE·텍스처(크기·개수·부분 갱신)** 네 묶음이 월드·모델을 가속하고, **알파 테스트**(스프라이트·2D)와 **밉 필터**(포트가 안 씀)는 뒤로 미룰 수 있다, Matrox 의 E2/E3/E4 + 4C5/4C6/4CA/4D9 와 같은 묶음이다.


### 1-1. G4-0 계측 결과 (2026-09-26, 부팅 7, 라이브러리 790413900, 내 gcdsd)

Matrox 의 `q2-state-matrix.c` 를 **한 줄도 고치지 않고** radeon 으로 돌렸다: `test/mgashim/`(Matrox 헤더 이름 여섯 개가 전부 `osrdn-mga-shim.h` 로 들어오고, `OSMGA*` 이름을 `OSRDN*` 계수기·함수로 잇는다; 소프트웨어 강제는 Matrox 시험들이 자기 방식이라 적은 **전면 시저**로 `osrdn-mga-shim.h:202`).  `-I test/mgashim` 만 다르다.

| 팔(GLQuake 의 상태 조합) | 기대(Matrox 1.3) | radeon 지금 |
|---|---|---|
| world / mipmap | software | software |
| world / GL_LINEAR, lightmap / RGBA, alias SMOOTH·FLAT, world 128·256·512, pass 1/2, MODULATE | HARDWARE | **전부 software**(hard 0 soft 1: 선택기가 상태를 거절, 삼각형은 우리 훅에 오지도 않음) |
| lightmap / LUMINANCE | software | software |
| uv 0..4 … uv 64 on 0.2 % | HARDWARE | mixed/none(상태 변경 없음, 그려진 삼각형 0 — 위와 같은 거절) |

즉 **GLQuake 가 쓰는 상태 조합 21 개 중 0 개가 가속**된다 — §3 의 T1(64×64 이상 텍스처)이 모든 팔을 막고, 그 뒤에 M(MODULATE)·B(블렌드 쌍)·D(깊이) 가 줄지어 있다.  "texture residency 195 fitted" 줄은 Matrox 아레나 질의를 흉내낸 스텁이 0 을 돌려준 결과라 **의미 없음**(G4-1 의 아레나가 생기면 실제 값).

## 2. 지금 있는 것 (읽은 것)

- 분류기 `OSRDNMesaClass.c`: 위 표의 "지금 우리" 열.  거절 사유 11 개, `sim_class.py` 가 변이로 잠근다.
- 커널 검증기(R7a): 허용 레지스터 **41 개**(G4-3 K2 뒤 42: PP_MISC; `osrdn_cp.m:2561`; R6 사다리가 잰 것에서 자동 생성 — "타이핑으로 합법이 되지 않는다"), 값 규칙은 `tools/r7/verify_oracle.py` 의 `value_ok` 뿐: PP_CNTL 의 TEX_1..5 금지(`verify_oracle.py:111`), TCL 금지, 큐브맵 금지, **TXFILTER 의 밉 필드 금지**(G4-4 K5 뒤엔 미실측 필드 금지, `verify_oracle.py:114`), 피치 워드의 타일·HyperZ 비트 금지.  **ZSTENCILCNTL 의 비교 함수·쓰기 비트, BLENDCNTL 의 인자 쌍, TXCBLEND 의 연산은 값 규칙이 없다** → 라이브러리만 바꾸면 된다.  `PP_MISC`(0x1c14, 알파 테스트의 참조값·연산)는 **허용 목록 밖**이다.
- 실측 규칙(기억 `r200-measured-rules`): 래스터·구로·블렌드 F+1(인자 일반)·깊이 floor(z·2ⁿ)·16 비트 배치·텍스처 픽셀 중심·이중선형·REPEAT/CLAMP_LAST·보조 시저.  **안 잰 것**: 알파 테스트, MODULATE 의 8 비트 곱 반올림, 밉 레벨 배치와 밉 필터, 텍스처 캐시 무효화, 16 비트 텍스처 형식.
- 창: 커널 창 [0x400000, 0x7c00000) = **120 MiB**(카드 128 MiB, `RDN-R4 vmap` 실측 mem=08000000); 라이브러리는 7,872,512 B 만 매핑하고 텍셀은 `OSRDNMesaTriTable.h:479` 뒤 **8 KiB** 다 — 아레나는 **라이브러리 쪽 결정**이지 커널 변경이 아니다.
- 제출: 배치 최대 `osrdn_cp.h:285` 2016 워드(G4-3 K4 뒤 4068) — 근거는 **링 4096 워드에 10 워드 꼬리를 더해 어느 wptr 에서도 들어가는 한계**(`osrdn_cp.h:285-290`)이고, 8 KiB 스테이징 페이지(2048 워드)도 같은 크기다; 링 4096 워드, 제출마다 fence(WBINVD)+rptr+idle 대기(동기), 링 고정 113.32 µs + 47.3 ns/워드(M1z 실측), ioctl 왕복 290 µs(13 워드, 이 세션 실측).  프롤로그를 정하는 상태가 다른 삼각형이 오면 열린 배치를 제출하고 새로 연다(`OSRDNMesaTri.c:1417`; 빈 배치는 무조건 합류).

## 3. 간극표 — 항목·근거·어디서·실측

| # | 항목 | 하드웨어 인코딩(참조) | 실측 | 커널 | 라이브러리 | 단 |
|---|---|---|---|---|---|---|
| D | 깊이 LEQUAL/GEQUAL/ALWAYS, 쓰기 OFF | ZSTENCILCNTL [6:4] 비교, bit30 쓰기 — `r200_state.c:344`; R6G E1 표 | 비교값 자체는 미실측, 필드는 R6g 가 LESS/ALWAYS 로 확인 | 없음 | 분류기·프롤로그 슬롯 9 | G4-1 |
| B | 블렌드 (ZERO,1−SRC_COLOR), (ONE,ONE) | RB3D_BLENDCNTL(0x1c20) 원본<<16·목적지<<24, ZERO 32·ONE 33·1−SRC_COLOR 35·SRC_ALPHA 38·1−SRC_ALPHA 39(r200_reg.h 73–80 행); 참조는 DRM 이 blendColor 를 지원하면 CBLENDCNTL/ABLENDCNTL 경로를 쓰고 아니면 0x1c20(`r200_state.c:282`) — 우리는 R6j 가 잰 0x1c20 | 산술 F+1 은 인자 일반(R6j) | 없음 | 분류기·프롤로그 슬롯 7 | G4-1 |
| M | TexEnv MODULATE | TXCBLEND 단계 0 = MADD, A=R0(텍셀), B=DIFFUSE — `r200_texstate.c:558` | 곱의 반올림 미실측 | 없음 | 텍스처 프롤로그 | G4-1(그림 게이트) |
| A | 알파 테스트 GREATER 0.666(스프라이트·2D 만) | PP_CNTL bit 23 `ALPHA_TEST_ENABLE`(`r200_reg.h:180`) + **PP_MISC 0x1c14** REF_ALPHA [7:0]·ALPHA_TEST_OP [10:8] | **미실측, PP_MISC 는 허용 밖** | **R6n 측정 경우 + 허용 목록 재생성** | 그때까지 스프라이트·2D 는 소프트웨어(월드 무관) | G4-3 |
| T1 | 텍스처 임의 POT 크기(≤512)·개수 | TXFORMAT log2 폭·높이, TXOFFSET 32 B 눈금(실측), POT 는 TXSIZE/TXPITCH 무시(R6h X9) | 8×8 만 실측; 큰 크기는 같은 필드 | 없음(창 안이면 통과) | 아레나(first-fit, 32 B, DeleteTexture 로 반환), 업로드 변환 RGB/RGBA→ARGB8888 | G4-1 |
| T2 | TexSubImage2D | CPU 가 텍셀을 다시 쓴다 | **텍스처 캐시가 옛 텍셀을 들고 있는가 미실측** | 없음(캐시 무효 방법이 레지스터면 허용 여부 확인) | 부분 행 쓰기 | G4-1 + G4-3 탐침 |
| F | 밉 필터 | TXFILTER MIN 필드(`r200_tex.c:206`), `MAX_MIP_LEVEL`(`r200_texstate.c:339`), 레벨은 32 B 정렬로 연속(`r200_texstate.c:278`) | 미실측 | **검증기 밉 필드 금지 해제 = 체인 전체가 창 안인지 계산** | 포트가 LINEAR 를 강제하므로 지금은 불필요; 진짜 밉은 선택 | G4-3(선택) |
| W | 랩 | REPEAT 만 필요 — `r200_tex.c:66` | REPEAT 실측(R6h XC) | 없음 | 없음 | — |
| S | 상태 변경을 배치 안에 | 검증기는 P0 와 P3 를 섞어 받는다(R6g X8: 같은 제출 안 상태 변경 실측) | 실측 있음 | 없음(검증기 원문으로 확인) | 배치가 상태 변경으로 안 닫히게 | G4-2 |
| P | 스테이징 창 확대 | 2016 워드 = 페이지 하나 | — | **R7c: 다중 페이지 스테이징·링 분할 또는 링 확대** | 배치 상한 상수 | G4-3(수치 뒤 결정) |

## 4. 숫자 (`build/g4/model.py`, 출력 `build/g4/model.out`)

```
texture budget (pak pak0.pak)
  worst map maps/lq_e0m1.bsp: world texels 735488, x4/3 for mips, ARGB8888 -> 3.74 MiB
  all mdl skins (upper bound, every model of the pak): 2565568 texels -> 13.05 MiB with mips
  lightmaps: 64 blocks x 128 x 128 x 4 = 4.00 MiB (upper bound, gl_rsurf.c MAX_LIGHTMAPS)
  upper bound in all: 21.30 MiB
  arena today: 8192 bytes (8.0 KiB); the kernel window allows up to 112.5 MiB after 0x780000
submission model
  textured triangles a batch: 93 (2016 - 54 - 2) / 21
  ioctl entry+exit outside the ring: 176 us (290 - ring 113.9)
  a full batch: 385 us
   5000 tris/frame,   0 extra state-change batches:   54 batches ->   20.7 ms submit ->  48.2 fps ceiling
   5000 tris/frame, 150 extra state-change batches:  204 batches ->   64.5 ms submit ->  15.5 fps ceiling
  10000 tris/frame,   0 extra state-change batches:  108 batches ->   41.5 ms submit ->  24.1 fps ceiling
  10000 tris/frame, 150 extra state-change batches:  258 batches ->   85.3 ms submit ->  11.7 fps ceiling
  20000 tris/frame,   0 extra state-change batches:  216 batches ->   82.9 ms submit ->  12.1 fps ceiling
  20000 tris/frame, 150 extra state-change batches:  366 batches ->  126.8 ms submit ->   7.9 fps ceiling
  10000 tris + 150 splits at  2016-word batches:  258 batches ->  85.3 ms (11.7 fps ceiling)
  10000 tris +   0 splits at  2016-word batches:  108 batches ->  41.5 ms (24.1 fps ceiling)
  10000 tris + 150 splits at 16384-word batches:  163 batches ->  57.5 ms (17.4 fps ceiling)
  10000 tris +   0 splits at 16384-word batches:   13 batches ->  13.7 ms (72.8 fps ceiling)
  10000 tris + 150 splits at 65536-word batches:  154 batches ->  54.9 ms (18.2 fps ceiling)
  10000 tris +   0 splits at 65536-word batches:    4 batches ->  11.1 ms (90.1 fps ceiling)
  the words alone, 10000 textured triangles: 9.9 ms at 47.3 ns a word (ring put only; the staging copy is on top)
```

읽기:
1. **텍스처는 전부 들어간다** — 최악 상한 21.3 MiB(모든 스킨·라이트맵 64 블록 포함) < 112.5 MiB.  축출(eviction)·16 비트 형식은 **필요 없다**; 아레나는 first-fit + 반환이면 된다.
2. **속도의 벽은 제출 횟수다.** 삼각형 1 만 개면 배치 108 개 = 41.5 ms(24 fps 상한, 그리기 시간 제외).  상태 변경마다 배치를 닫으면(프레임당 150 회 가정) 11.7 fps 로 떨어진다 — 이것이 Matrox 의 5.7 fps 와 같은 모양이다.  **상태 변경을 배치 안에 넣는 것(S)이 1 순위**, 스테이징 창을 16 K 워드로 키우면(P) 13 배치·13.7 ms(73 fps 상한).
3. 프레임당 삼각형·상태 변경 수는 **가정**이다(5 천·1 만·2 만).  G4-0 이 실측으로 바꾼다.

### 4-1. 아레나·상태 변경 예산 (`model.py` 두 번째 절)

```
texture arena (library side)
  ARGB8888 bytes, 32 B aligned rows: 8x8=256, 16x16=1024, 32x32=4096, 64x64=16384, 128x128=65536, 256x256=262144, 512x512=1048576
  TXFORMAT words (ARGB8888 | ALPHA_IN_MAP | log2 w << 8 | log2 h << 12): 8:0x3346, 64:0x6646, 128:0x7746, 512:0x9946
  arena 16 MiB: map 24641536 bytes = 3008 pages (kernel allows 15360), lightmaps 64 x 65536 = 4.00 MiB
  arena 32 MiB: map 41418752 bytes = 5056 pages (kernel allows 15360), lightmaps 64 x 65536 = 4.00 MiB
  arena 64 MiB: map 74973184 bytes = 9152 pages (kernel allows 15360), lightmaps 64 x 65536 = 4.00 MiB
state changes inside a batch (G4-2): PACKET0 pairs a change costs, against a new batch
  texture bind (TXOFFSET, TXFORMAT, TXFILTER, TXSIZE, TXPITCH) 10 words vs a new batch: 54 prologue + 289 us fixed
  tex env REPLACE<->MODULATE (TXCBLEND_0, TXABLEND_0)         4 words vs a new batch: 54 prologue + 289 us fixed
  depth func / mask (ZSTENCILCNTL)                            2 words vs a new batch: 54 prologue + 289 us fixed
  blend on/off + pair (RB3D_CNTL, RB3D_BLENDCNTL)             4 words vs a new batch: 54 prologue + 289 us fixed
  shade model (SE_CNTL)                                       2 words vs a new batch: 54 prologue + 289 us fixed
```
- 32 MiB 아레나면 pak 상한 21.3 MiB 가 들어가고 매핑은 5,056 페이지(커널 허용 15,360).  `mmap` 길이만 바뀐다(`OSRDNMesaSurface.c:126`).
- 상태 변경 한 번은 배치 안에서 **2–10 워드**, 새 배치는 54 워드 + 289 µs.  G4-2 의 근거.

## 5. 사다리 — 구체 명세 (참조: Mesa-6.5.3 r200 DRI = 인코딩, Matrox M1_4C5/C6/CA/E2/E3/E8 = 설계 선례, Mesa 3.4.2 = 훅 계약)

원칙: 커널은 G4-3 까지 건드리지 않는다(허용 레지스터·값 규칙이 이미 열려 있다, §2).  각 항목은 **분류기 조항 → 프롤로그 슬롯/레지스터 값(참조 인코딩) → 검사 규칙·변이 → 시험(Matrox 시험을 shim 으로) → 게이트** 로 적는다.  Matrox 가 이미 결정한 것은 그 결정을 쓰고, 하드웨어가 달라 다른 것만 새로 정한다.

### G4-0 — 계측·시험대 (끝, §1-1)
남은 것 하나: 포트 빌드의 radeon 변형 — `build-glquake.sh` 에 `ACCEL=radeon` 모드(`-I$RDN/test/mgashim -I$RDN/mesa -I$RDN/OSRDNDisplay/OSRDNDisplay_reloc.tproj`, `libGL_radeon.a`, 산출 `glquake_radeon`).  `gl_vidsdl.c` 는 **안 고친다**(헤더 이름이 같다).  라이트맵 RGBA 는 실행 인자 `-lm_4`(Matrox 와 같다).

### G4-1 — 상태 확장 (라이브러리만, 재부팅 없음)

| # | 분류기(`OSRDNMesaClass.c`) | 프롤로그/레지스터 | 인코딩 근거 | Matrox 선례의 결정 | 시험(shim) |
|---|---|---|---|---|---|
| D | `OSRDNMesaClass.c:342`: `depthFunc ∈ {LESS, LEQUAL, GEQUAL, ALWAYS}`(GL_NEVER 거절), `depthMask` 0/1 허용 | 슬롯 9 ZSTENCILCNTL(`OSRDNMesaTriTable.h:433`): 형식 0 · Z_TEST 필드 [6:4] = LESS 1/LEQUAL 2/GEQUAL 4/ALWAYS 7 · bit 30 = 쓰기(마스크 0 이면 0) · 스텐실 ALWAYS · ops 0x0222 — 값은 `(0x42227010 & ~0x70) \| func<<4` 에서 bit 30 만 마스크로 | `r200_state.c:344`·`r200_state.c:395`; R6G E1 표 | M1_4E2: Mesa 만, 커널 무변경; **`depthOn` 을 비교값과 분리**(우리는 RB3D_CNTL Z_ENABLE bit 8 이 그 분리다); NEVER 거절(E8: 원본이 이름을 안 붙임); 시험은 "평평한 깊이 코드 같은/한 코드 가까이/멀리 × 가속/강제소프트" | `openstep-mga-mesa-depth-anchor-test.c`·`depth-agree.c` 를 shim 으로; python 이 통과/거절 화소를 지정 |
| B | `OSRDNMesaClass.c:362`: 쌍 ∈ {(SRC_ALPHA,1−SRC_ALPHA), (ZERO,1−SRC_COLOR), (ONE,ONE)}, **RGB 쌍 == A 쌍** 계속 요구(E3 §4) | 슬롯 7 BLENDCNTL: `src<<16 \| dst<<24 \| ADD_CLAMP<<12`; 부호값 ZERO 32·ONE 33·1−SRC_COLOR 35·SRC_ALPHA 38·1−SRC_ALPHA 39; RB3D_CNTL bit 0 ALPHA_BLEND_ENABLE | `r200_state.c:332`, `r200_reg.h:73`, `r200_reg.h:186`; R6J J1/J2 | M1_4E3: Mesa 만; 오라클은 인자 함수를 표로(우리 산술은 F+1 실측 규칙) | `openstep-mga-mesa-blendfactor-test.c`(shim): 세 쌍 + 기존 쌍 불변 |
| M | `texEnvMode ∈ {REPLACE, MODULATE}` (`OSRDNMesaClass.c:314` 의 env 코드 조항(G4-1a 에서 REPLACE 또는 MODULATE 로 완화됨)) | 텍스처 프롤로그(`OSRDNMesaTriTable.h:542`)의 TXCBLEND_0/TXABLEND_0(0x2f00/0x2f08): REPLACE = 측정값 `0x0010000a`(MADD, A=R0, B=~0); MODULATE = `TXC_OP_MADD \| ARG_A_R0_COLOR \| ARG_B_DIFFUSE_COLOR \| ARG_C_ZERO`, 알파도 R0_ALPHA×DIFFUSE_ALPHA — 상수는 `gen_tri_prologue.py` 가 r200_reg.h 에서 읽어 생성 | `r200_texstate.c:558`, `r200_texstate.c:797` | M1_4CA: 엔진 곱 ≠ Mesa 곱(28.6 %) 이지만 **기본 env 라 예외로 열었다**, 정점색 흰색이면 정확히 같다.  우리는 곱의 8 비트 규칙을 **한 번 잰다**(G4-3 실기에 경우 추가) — 그 전엔 시험 허용치로 | `q2-state-matrix` MODULATE 팔 + 시험기 장면(흰 정점색 → 정확 일치, 회색 → 허용치) |
| T1 | 텍스처: 유닛 0 `TEXTURE0_2D`, 레벨 0(BaseLevel 0), 테두리 0, **POT 8..512**(`texWidth/Height` 고정값 비교를 `is_pot && ≤ 512` 로), 형식 `GL_RGB`·`GL_RGBA`(Mesa 3.4.2 저장: 3·4 바이트/텍셀), min/mag `NEAREST`·`LINEAR`, wrap `REPEAT`(측정 XC)·`CLAMP`(측정 XA 의 CLAMP_LAST 로 — GL_CLAMP 의 경계 규칙 차이는 시험이 본다), 비상주면 거절 | TXFORMAT = `ARGB8888 \| ALPHA_IN_MAP \| log2w<<8 \| log2h<<12`(`tex_oracle.py:53`; 8→0x3346 은 측정 프롤로그와 일치, 512→0x9946), TXSIZE/TXPITCH 는 POT 에서 안 읽힘(R6h X9) 이지만 Mesa 처럼 채움, TXFILTER = 필터·랩 비트(`r200_reg.h:853`), TXOFFSET = winStart + 아레나 오프셋(32 B 눈금, `r200_reg.h:1070`) | `r200_reg.h:882`, `r200_reg.h:900`, `r200_reg.h:903`, `r200_texstate.c:278` | M1_4C5 §8: 아레나 **최초적합 + 세대(epoch)**, 상주 기록은 `gl_texture_image->DriverData`(`types.h:216`), **첫 그리기 때 올림**, 무효화는 TexImage/TexSubImage/DeleteTexture 셋, 바이트는 숫자로 조립(엔디안 무관); M1_4C6 §6-2: 유닛 0 객체·BaseLevel 0 | `openstep-mga-mesa-arena-test.c`(아레나 질의 → shim 의 `BufferTextureArena` 를 실제 함수로), `test-mesa-texarena.c`; `q2-state-matrix` 128/256/512 팔 |
| T2 | TexSubImage2D 갱신 | 상주 기록 `valid=0` → 다음 그리기 전 재업로드(전체 레벨; 행 범위 최적화는 뒤) | Mesa 3.4.2 훅 **구식 알림 훅** `Driver.TexImage`·`Driver.TexSubImage`(`teximage.c:1557`, `teximage.c:2238`: 신형 `TexImage2D` 의 성공 여부와 무관하게 **항상** 뒤에 불린다 — Mesa 의 저장을 그대로 두는 가장 안전한 자리; codex 검토로 정정)와 `Driver.DeleteTexture`(`texobj.c:506`: 이미지 해제 **전**)를 **체인**으로 잡는다(Matrox `prevTexImage` 방식).  `BindTexture` 는 같은 객체 재바인드에 안 불린다(`texobj.c:562`) → 상주는 Bind 에 기대지 않는다 | M1_4C5 §3-4 | 시험기: 갱신 뒤 재표본 = stock; 텍스처 캐시 무효화 여부는 G4-3 탐침 |
| L | 라이트맵 = RGBA 128×128 텍스처 + SubImage | T1·T2 로 덮임 | — | Q5 §3 | `q2-state-matrix` "lightmap / RGBA", "pass 2" |

**검증기가 이미 허용하는 것(codex 검토 B, 원문 확인)**: TXOFFSET 은 창 안 + **끝 경계 1 KiB 고정**(`osrdn_cp.m:2768`, `osrdn_cp.h:258`: 텍스처 크기로 재지 않았다 — K3 이 재고 K7 이 draw 마다 재게 했다), 정렬 검사 없음, TXFORMAT 은 큐브맵 비트만 금지(`osrdn_cp.m:2628`), TXFILTER 는 밉 마스크만 → G4-1 은 커널 없이 되고, **라이브러리가 32 B 정렬과 "아레나 끝 + 텍스처 바이트 ≤ winEnd" 를 스스로 지킨다**; 검증기 경계를 TXFORMAT 크기로 정밀화하는 것은 G4-3 항목(§6-7).

**구현 단위(파일)**: `OSRDNMesaClass.c`(조항 D·B·M·T1) · `OSRDNMesaTri.c` `triPrologue`(슬롯 값: ZSTENCIL/BLENDCNTL/RB3D_CNTL/TXCBLEND/TXFORMAT/TXFILTER/TXOFFSET) · **새 단위 `OSRDNMesaTexArena.c`**(Matrox `OpenStepMGAMesaTexArena` 의 API 모양: `Set/Drop/Epoch/Alloc/Free/Stat`) · `OSRDNMesaTex.c`(임의 크기·형식 변환 업로드; 지금의 8×8 고정 제거) · `OSRDNMesaHook.c`(텍스처 훅 체인·상주 조회 `OSRDNMesaHook.c:308`; M1g 의 8×8 일회 업로드는 제거) · `OSRDNMesaSurface.c`(매핑 길이 = 0x780000 + 32 MiB, `OSRDNMesaSurface.c:126`).  `gen_tri_prologue.py` 가 새 상수(MODULATE 워드, 랩·필터 조합)를 r200_reg.h 에서 생성하고 `check_units.py`·`check_hook.py`·`sim_class.py`·`sim_pack.py` 에 규칙·변이.

**게이트(순서)**: 단위 시뮬레이터·규칙 → hostcheck(링크·심볼) → 타깃 빌드 → shim 시험 3 종(depth-anchor/agree, blendfactor, arena) + 시험기 장면 PASS → `q2-state-matrix` 21 팔 중 21 HARDWARE(밉·LUMINANCE 팔 제외) → `check-all`.

### G4-2 — 상태 변경을 배치 안에 (라이브러리)
- 지금: `OSRDNMesaTri.c:1417` 가 프롤로그를 정하는 여덟 값 중 하나라도 다르면 합류 거절 → 제출.  바꿈: 열린 배치에 **차이 나는 슬롯의 P0 쌍만** 덧붙이고(§4-1: 2–10 워드), 뒤이어 새 IMMD 패킷을 연다.  검증기(`osrdn_cp.m:2774`)는 P0/P3 교대를 받고 VTX_FMT_0 은 첫 DRAW 전 한 번이면 된다(§7 판정 2-4) — 텍스처 켜짐/꺼짐이 바뀌면 VTX_FMT_0/1 도 쌍으로 다시 쓴다.
- 배치 상한 2016 워드 안에서 "남은 공간 < 상태 쌍 + 삼각형 한 개" 면 제출.  `world5`·`sim_r5` 에 "한 배치 안 상태 변경 뒤 그리기" 시험(R6g X8 실측이 근거), `check_hook` 규칙.
- 측정: G4-0 c 의 timedemo 로 프레임당 배치 수 전후 비교.

### G4-3 — 실기 부팅 1 회 (커널 + 측정)
- **R6n 알파 테스트**: PP_MISC(0x1c14) 측정 경우 2(GREATER 0.666 = 참조값 170, LEQUAL) × 알파 텍스처 → 허용 목록 재생성(`verify_oracle.py --c-tables`), world5 모델; 그다음 분류기에 A(스프라이트·2D).
- **MODULATE 곱 규칙**: R6 방식 경우 1(텍셀×정점색 격자) → `tools/r6` 오라클에 규칙, 시험 허용치를 규칙으로 교체.
- **밉**(선택): 레벨 배치·MIN 필터 측정, 검증기 밉 규칙 정밀화(§6-5).
- **텍스처 캐시 탐침**, **스테이징 확대(R7c)** 는 G4-0 c 수치 뒤 결정.
- **검증기 정밀화**: TXOFFSET 끝 경계를 TXFORMAT(log2 폭·높이·형식 바이트)로, 밉 마스크를 MIN_FILTER bit 2 + MAX_MIP_LEVEL [19:16] 로(§6-5) — 변이와 함께.

### G4-4 — glquake 화면 (사용자 gcdsd)
`build-glquake.sh ACCEL=radeon` → `run-glquake-timedemo.sh glquake_radeon` + `glquake_sw` 대조(스크린샷·fps).

## 6. 위험·미결

1. **텍스처 캐시**(T2): 참조 DRM 은 텍스처를 2D 블릿으로 올리고 앞뒤에 `RADEON_FLUSH_CACHE`(색 캐시)만 낸다; 텍스처 캐시 무효화가 필요한지, TXOFFSET 재기록으로 충분한지 **모른다** → G4-3 탐침.  그 전 G4-1 에서 SubImage 는 "재표본 전에 프롤로그(TXOFFSET 포함)를 다시 쓴다" 로 두고 시험기가 잡는다.
2. **MODULATE 반올림**: 8 비트 곱의 규칙 미실측 → stock 과 ±1 차이를 판정기 허용치로 두고, 어긋나면 R6 방식 측정.
3. **ztrick**: GEQUAL 프레임은 깊이 clear 없이 범위만 뒤집는다 — 우리 카드 clear 는 색만 하게 되고(깊이 비트 없음) 깊이 버퍼는 이전 프레임 값 그대로여야 한다(clear 가 안 건드리는지 시험기가 본다).
4. **성능 모형의 가정**: 프레임당 삼각형·상태 변경 수, 47.3 ns/워드는 링 put 만(스테이징 복사 별도).  G4-0 c 가 바꾼다; 그 전에 P 를 결정하지 않는다.
5. **검증기의 밉 마스크가 부정확하다**: `TXFILTER_MIP_MASK 0x0001c000` 은 비트 14–16 인데, 밉 모드는 MIN_FILTER 필드([4:1], `r200_reg.h:839`)의 bit 2 이고 레벨 수는 MAX_MIP_LEVEL [19:16](`r200_reg.h:846`) 이다 — python: `LINEAR_MIP_NEAREST | MAX_MIP_LEVEL 2` = 0x2000c 가 마스크를 **통과**한다(MAX_MIP_LEVEL 3 은 bit 16 으로 걸린다).  G4-3 에서 규칙을 "bit 2 와 [19:16] 은 체인이 창 안일 때만" 으로 정밀화하고 변이를 둔다(기억 `checker-discipline`: 규칙은 약화 말고 정밀화).
6. 큰 텍스처(512×512)의 TXFORMAT log2 필드는 실측 8×8 과 같은 필드지만 값이 다르다 — G4-0 a 의 256×256 장면이 그림으로 확인한다.

## 7. codex 교차검토 판정표 (계획, 2026-09-26, gpt-5.6-sol 4 회 국지 호출 — 회신은 전부 원문으로 재확인)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| D: Z_TEST [6:4], LEQUAL 2·GEQUAL 4·ALWAYS 7, 쓰기 bit 30 | r200_reg.h 98·107–115·155 원문, R6G E1 표 | ✅ |
| B: 참조는 blendColor 지원 시 CBLENDCNTL/ABLENDCNTL, 아니면 RB3D_BLENDCNTL; 부호값 32/33/34/35/38/39 | `r200_state.c:282` 원문, r200_reg.h 73–80 원문 | ✅ 채택(§3 B 에 경로 주석) |
| A: PP_MISC REF [7:0]·OP [10:8], PP_CNTL 0x00800000 = bit 23 | `r200_reg.h:180` 원문; python `0x00800000 == 1<<23` | ✅ |
| M: MODULATE = MADD, A=R0, B=DIFFUSE, C=ZERO; 알파 같은 모양 | r200_texstate.c 797–802 원문 | ✅ |
| F: 레벨 32 B 정렬 연속, MAX_MIP_LEVEL 시프트 16·마스크 0xf<<16 | r200_texstate.c `Align to 32-byte offset`, `r200_reg.h:846` 원문 | ✅ (그리고 이 원문이 §6-5 의 검증기 마스크 결함을 드러냈다) |
| 검증기: 네 레지스터 값 규칙 없음, PP_MISC 허용 밖, 밉 마스크 거절, P0/P3 교대 가능(VTX_FMT_0 은 첫 DRAW 전 한 번) | `value_ok`(verify_oracle.py 107–124)·cpR7Allow 원문 | ✅ |
| 배치 2016 의 근거는 8 KiB 페이지가 아니라 링(10 워드 꼬리 포함, 어느 wptr 에서든) | `osrdn_cp.h:285-290` 원문; 8 KiB 정적 단언은 별도(osrdn_r7b.h 122) | ✅ 채택 — §2 정정(내가 틀렸다) |
| 라이브러리: 상태 불일치 시 다음 삼각형 직전 제출, 빈 배치는 합류 | `OSRDNMesaTri.c:1417` 원문 | ⚖️ 사실; 모형의 "상태 변경 = 배치" 는 삼각형이 뒤따르는 변경에 대해 성립 — §2 표현 정정 |
| 텍스처 삼각형 93/배치, 제출은 동기 | python 재계산, cpR6Submit 원문(이 세션에서 읽음) | ✅ |
| **알파 테스트는 전역이 아니다**: R_SetupGL 이 매 프레임 끄고 월드·모델은 꺼진 채; 켜는 곳은 스프라이트·2D | `gl_rmain.c:938`·`gl_rmain.c:228`·gl_draw.c 595/850 원문 | ✅ 채택 — §1·§3·§5 정정(내가 틀렸다; A′ 삭제) |
| GL_BLEND env 두 곳은 mtexable 분기 안 | gl_rsurf.c 428–452·532–554 | ✅ |
| ztrick: 홀수 LEQUAL+(0, 0.49999), 짝수 GEQUAL+(1, 0.5), 깊이 clear 없음, gl_clear 0 이면 색도 없음 | `gl_rmain.c:1006` 원문 | ✅ 채택 — §1 값 정정 |
| 블렌드 쌍은 정확히 셋 | python 전수(§1) 와 일치 | ✅ |
| **포트가 필터를 LINEAR/LINEAR 로 덮어쓰고 랩도 명시** | `gl_vidsdl.c:476` 원문(무조건 블록) | ✅ 채택 — 밉 필터를 G4-1 에서 뺐다(내가 낡은 주석을 믿었다) |
| 라이트맵 128×128·64 블록·`-lm_4`·행 범위 SubImage | gl_rsurf.c 37–40·701–713 | ✅ |

### 7-1. 계획 개정본 검토 (2026-09-26, 2 회 국지 호출, 전부 원문 재확인)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 신형 `TexImage2D` 성공 여부와 무관하게 구식 `Driver.TexImage` 가 **항상** 뒤에 불린다 | `teximage.c:1557` 가 분기 밖 | ✅ 채택 — 내가 틀렸다(§5 T2: 구식 알림 훅을 잡는다) |
| `TexSubImage2D`: 실패 시 Mesa 갱신 → 신형 `TexImage2D` 전체 업로드 → 구식 `TexSubImage` | teximage.c 2224-2247 원문 | ✅ (우리는 신형을 안 잡으므로 구식만) |
| `DeleteTexture` 는 이미지 해제 전 | `texobj.c:506` | ✅ |
| 같은 객체 재바인드는 `BindTexture` 훅 없이 조기 반환; `DriverData` 는 Mesa 가 초기화에서도 제외 | `texobj.c:562`, teximage.c 736-759 | ✅ 채택 — 상주는 Bind 이벤트에 기대지 않음 |
| RGB 3·RGBA 4 바이트, R,G,B 순, `Format` 은 기본 형식 | teximage.c 256-275·620-635 | ✅ |
| TXOFFSET 끝 경계는 고정 1 KiB(`CP_R6_TEX_BYTES`), 정렬 검사 없음 | `osrdn_cp.m:2768`, `osrdn_cp.h:258` | ✅ 채택 — 라이브러리가 정렬·경계를 지키고 G4-3 에서 검증기 정밀화 |
| TXFORMAT 은 큐브맵 비트만, TXFILTER 는 밉 마스크만 금지 | `osrdn_cp.m:2628`, 그 아래 줄 | ✅ |
| 검증기의 winEnd 는 `c->winEnd`(실기 0x07c00000) | osrdn_cp.m 2887-2891 | ✅ |

## 8. G4-1a 결과 (2026-09-26, 라이브러리 790422901, 부팅 7, 내 gcdsd)

- 구현: 분류기가 상태를 **코드**로 내린다(`osrdn_class_depth_code` = 1 | Z_TEST<<1 | write<<4, `osrdn_class_blend_code` 1..3, `osrdn_class_env_code` 1..2); 훅은 그 코드를 기존 `smooth/blend/tex/depth` 인자에 실어 Tri 로 보내고(시그니처 불변), 코드 0 인데 기능이 켜져 있으면 보내지 않는다(`codeGap`, 0 이어야). Tri 는 슬롯에서 코드→워드(ZSTENCILCNTL = 측정 LESS 워드의 비교 필드·쓰기 비트만 치환; BLENDCNTL 3 쌍; TXCBLEND/TXABLEND 슬롯 12·13 = REPLACE 측정값 또는 MODULATE 파생값 0x8a). 생성기가 r200_reg.h 에서 전부 파생하고 자체검사(python 재계산)한다. sim_class 행 +8·변이 +3, check_hook 규칙·변이 +3, 전부 PASS.
- **텍스처 프롤로그에 DEPTHOFFSET/DEPTHPITCH 슬롯이 없었다**(M1g 는 64×64 만): 커널 검증기가 프리픽스의 깊이 피치 64 로 800×600 클립을 검사해 **모든 큰 텍스처 삼각형을 거절**(why 11)하고 있었다. 생성기 `tex_template()` 에 두 쌍을 더해 58 워드.
- 실기(탐침 `GHOST_STATES`, 가속 vs stock 화소 대조, 38 삼각형 전부 카드):

| 장면 | 다른 화소 | >32 | 판정 |
|---|---|---|---|
| LESS / 마스크 off | 19 | 19 | 모서리 |
| GEQUAL, ALWAYS (마스크 둘 다) | 166 | 166 | 모서리 |
| LEQUAL, 다른 삼각형이 같은 평면 | 1,135 | 1,135 | **동률이 행 띠로 갈림**(아래) |
| tie0: **같은 삼각형** LESS→LEQUAL | 15 | 15 | 동률 전부 통과 — quake 라이트맵 패스의 모양 |
| tie1: 다른 코플래너 삼각형 | 1,353 | 1,353 | 하드웨어의 z 가 삼각형마다 행 단위로 ±1 코드 — Mesa 소프트웨어는 통과시킴 |
| REPLACE / MODULATE (8×8) | 2,208 / 2,208 | 15 / 15 | 표본·곱 반올림 차 ≤32, 최악 209/165 — Matrox 4CA 와 같은 급의 예외로 연다 |
| blendfactor-test(shim): (ONE,ONE)·(ZERO,1−SRC_C)·(SRC_A,1−SRC_A) | 0 | 0 | 엔진 = 소프트웨어 정확히 |

- 미결 §6-8: **코플래너 다른 삼각형의 동률**(tie1). quake 는 같은 폴리곤을 다시 그리므로 당장 문제는 아니나, 데칼·물 표면 등은 영향 가능; 원인(하드웨어 z 평면 설정의 행 단위 반올림)은 R6 방식 측정 후보.

## 8-1. G4-1b 결과 (2026-09-26, 라이브러리 790425520, 부팅 7, 내 gcdsd) — 텍스처 아레나·상주·원근

**구현**

- `mesa/OSRDNMesaTexArena.c/.h`(새 단위, Matrox `OpenStepMGAMesaTexArena` 의 모양): 정렬된 블록 512 개·최초적합·32 B 정렬·세대(epoch).  libc·Mesa 없음, 호스트에서 `tools/mesa/sim_arena.py` 가 독립 모형과 548 단계 대조 + 변이 10 개 (전부 잡힘).
- 상주 기록은 `gl_texture_image->DriverData`(`osrdnTexRes`: epoch·origin·bytes·w·h·valid).  **첫 그리기 때 올린다**(`osrdnTexResident`, 3 바이트 RGB 도 `osrdn_tex_upload_at` 가 ARGB 워드로 조립).  구식 `Driver.TexImage`(레벨 0 → 기록 폐기) / `TexSubImage`(valid=0) / `DeleteTexture`(전 레벨 폐기) 를 **체인**으로 건다(`osrdnPrev*`).  표면을 (재)잡을 때마다 epoch 이 오르고 아레나는 `OSRDN_TEX_BYTE_OFF` 부터 매핑이 닿는 만큼(최대 32 MiB) 으로 다시 놓인다; 예약은 `OSRDN_TEX_BYTE_OFF + OSRDN_TEX_ARENA_BYTES`.
- 분류기 T1 확장: POT 8..512(`osrdn_class_tex_dim_ok`), 테두리 0, `GL_RGB`/`GL_RGBA`, min·mag `NEAREST`/`LINEAR`, wrap REPEAT.  sim_class 행 +9(16×16·512×512·256×64·4×4·1024·24×8·LUMINANCE·밉 필터), 변이 +2.
- Tri: 현재 텍스처(`osrdn_tri_texture_set`) → 슬롯 TXOFFSET/TXFORMAT(log2)/TXFILTER/TXSIZE/TXPITCH, 배치 키에 포함(텍스처가 바뀌면 배치 닫힘).  생성기 슬롯 14–17, 자체검사 PASS.
- shim: `OSMGAMesaBufferTextureArena` 를 실제 질의로(`osrdn_texarena_stat`), `OSMGA_HW3D_CAP_VRAMLEN` = 창 크기, `HookHardState` = installs + opens(상태 변화 없는 팔도 판정되도록; Matrox 는 그리기마다 재판정).

**실기에서 드러나 고친 것 셋**(전부 실측이 먼저, 원인은 원문으로)

| 증상(탐침 `GHOST_TEXBIG`, `build/g3c/ghostprobe_v7..v14.c`, 판정 `build/g4/judge_texbig.py`) | 원인 | 고침 |
|---|---|---|
| 첫 텍스처 장면(t64)이 소프트웨어(`why TEXTURE`)인데 같은 상태의 다음 장면은 카드 | `ghostprobe_v9` 가 컨텍스트를 읽음: `ReallyEnabled=2` 인데 **`RasterMask=0`**.  Mesa 3.4.2 는 RasterMask 를 `NEW_RASTER_OPS`/`NEW_TEXTURE_ENABLE` 에서만 다시 계산하고(`state.c:991`, `update_rasterflags` `state.c:997`, 비트는 `state.c:817`) ReallyEnabled 는 `NEW_TEXTURING` 만으로 움직인다(`state.c:957`) — enable 뒤 `glTexParameter` 로 완성된 텍스처의 첫 그리기는 비트가 낡다.  Mesa 자신의 삼각형 선택은 ReallyEnabled 를 읽는다(`triangle.c:1563`) | 훅이 분류기에 주는 rasterMask 의 TEXTURE_BIT 를 **ReallyEnabled 에서** 만든다(`OSRDNMesaHook.c` UpdateState); check_hook 규칙·변이 |
| NEAREST 텍스처가 사각형 가운데서 **2 텍셀 앞서고 양 끝은 맞음**(sub 장면: 파란 상자가 5 px 왼쪽; 텍셀/px 기울기 0.84 % 낮음) | 정점 W 가 1.0 이라 카드가 s·t 를 **화면 선형(아핀)** 으로 보간; Mesa 소프트웨어는 원근 보정(`triangle.c:1612`, 기본 힌트 `context.c:939`).  탐침의 모델뷰는 −20° 회전이라 w 가 위아래 9 % 다르다 | ① 텍스처 정점에 Mesa 의 `Win[3]` = 1/w(`xform.c:170`; `feedback.c:172` 가 역수를 취함) ② **그것만으로는 그림이 비트 단위로 그대로였다** — R6i 실측(`docs/R6I_PLAN.md` 8): `RE_CNTL.PERSPECTIVE_ENABLE` 없이는 W 가 무시된다(PD = PA).  텍스처 템플릿의 RE_CNTL 을 0x2 → **0xa** 로(생성기 `tex_template`, 자체검사: 평면 템플릿은 0x2 유지).  커널 검증기는 RE_CNTL 값을 제한하지 않는다(`cpR7ValueAllowed`), world5 는 {0,2,0xa} 를 이미 허용 |
| Matrox 아레나 시험이 `OSMGA_HW3D_CAP_VRAMLEN` 미정의로 컴파일 실패 | shim 의 caps 가 비어 있었다 | caps[0] = 창 바이트 |

**실기 대조**(가속 vs stock, 800×600, 판정기 PASS; "이웃 밖" = 32 초과 차이인데 stock 의 8 이웃 어느 것과도 32 이내가 아닌 화소)

| 장면 | 다른 화소 | >32 | 이웃 밖 | 비고 |
|---|---|---|---|---|
| t64 (64² RGBA NEAREST REPLACE) | 1,031 | 283 | 0 | 텍셀/px 기울기 stock 과 0.06 % 이내(redef) |
| t256rgb (256² **RGB 3 바이트** LINEAR MODULATE·흰색) | 43,776 | 281 | 0 | 평균 텍셀 오프셋 ≤ 2(이중선형 규약 차, R6i a = −½) |
| t512 (512² NEAREST, s 0..2 반복) | 5,087 | 286 | 0 | 이음매 열이 1 px 이내 |
| multi (128²·32² 번갈아 세 삼각형) | 1,057 | 60 | 0 | 두 텍스처 동시 상주 |
| sub (128² 에 32² `glTexSubImage2D` 뒤 다시) | 1,702 | 293 | 0 | 상자가 제자리 |
| lm (t64 REPLACE + 128² 블렌드 ZERO/1−SRC_C) | 29,421 | 148 | 0 | quake 라이트맵 패스 모양 |
| redef (같은 이름을 64² 로 재정의) / del (삭제 뒤 같은 이름 32²) | 1,031 / 527 | 283 / 286 | 0 / 0 | 기록 폐기·재할당 |
| big (1024×8) / lum (LUMINANCE) | 0 / 0 | — | — | 분류기 거절 → 소프트웨어, stock 과 동일 |
| 계수기 | drawn 19 = 하드웨어 장면 삼각형 전부, delegated 0, codeGap 0, texAbsent 0, texUploads 8, texUploadBad 0 | | | |

- `q2-state-matrix`(Matrox 시험 무수정, shim): **21 팔 중 18 HARDWARE**; 밉·LUMINANCE 2 팔은 예정된 소프트웨어; **"uv 0..64" 1 팔은 §6-9**.  상주 시험 "distinct 64×64 until no room": 195 전부 맞음.
- `openstep-mga-mesa-arena-test`(Matrox 시험 무수정): 다섯 크기 전부 아레나 32.00 MiB, `0 failed`.
- `GHOST_UV`(q2 의 uv 팔을 훅 계수기와 그림으로): uv 1·4·16 은 32 삼각형 전부 카드, stock 과 이웃 밖 0(LINEAR 라 전 화소가 ≤32 로 다름).

- G4-0 의 남은 하나: `openstep-quake/build/build-glquake.sh` 에 `ACCEL=radeon RDN_LIB=<libGL_radeon.a>` 모드(가산적; shim 디렉터리를 SDL 의 Headers 보다 **앞에** — 거기에 같은 이름의 Matrox 헤더가 설치돼 있어 첫 빌드가 'conflicting types' 로 섰다).  실기 빌드 `GLQUAKE_BUILD=pass /usr/local/nxbuild/bin/glquake_radeon`(라이브러리 790425520).  timedemo 대조(G4-0c)는 화면 그리기라 사용자 gcdsd 에서.

**남은 것은 §6-9~6-11 로.**

### 6-9. 큰 배치의 카드 대기 100 ms 가 정지로 읽힌다 (커널, G4-3) — **닫힘(부팅 8, docs/G4_3_KERNEL_PLAN.md 12)**

`GHOST_UV` uv 64·256(32 개의 큰 삼각형, 64 텍셀 텍스처를 64~256 번 반복, LINEAR): 훅은 32 개를 다 넘겼는데 `submitted` 0, `refused[REFUSED]` 1, `lastStatus` 5(EIO), `lastAt` = 끝.  커널 로그 `RDN-R7B submit … rc=8 drawn=0`, `RDN-R5 wait … idle=…/1/100000` — **`C_IDLE_US` 100 ms 의 idle 대기가 끝났다**.  그런데 VRAM 그림은 stock 과 **비트 단위로 같다**(ub.uv64 = uk.uv64): 카드는 다 그렸고, 커널이 정지로 판정한 것이다.  q2 에선 uv 0..64 만 걸리고 0..256 은 통과 — 시간 경계 근처의 요동.  훅은 배치 닫힘 뒤라 되돌릴 정점이 없다(**삼각형 유실**).  고침은 커널 쪽: 대기를 시간이 아니라 **진행(rptr 전진) 기준**으로(BSD 참조가 하는 것), 그 전까지 라이브러리는 유실을 센다.  glquake 의 벽은 이런 반복·최소화 삼각형이다 — G4-3 첫 항목.

### 6-10. 텍스처 삼각형의 정점색이 원근 보정된다

`PERSPECTIVE_ENABLE` 은 색도 나눈다(R6i PE).  Mesa 3.4.2 의 원근 삼각형은 색을 화면 선형으로 보간한다 — MODULATE 에 기울어진 폴리곤이면 stock 과 갈릴 수 있다(GL 규약은 어느 쪽도 허용).  판정기 허용치(≤32·이웃) 안에 있었고, 평면 템플릿(텍스처 없음)은 비트를 끈 채라 M1d–M1f 그림은 그대로다.

### 6-11. Mesa 3.4.2 RasterMask 의 TEXTURE_BIT 는 한 그리기 낡다

§8-1 표 첫 줄.  **같은 Mesa 위의 Matrox 훅도** RasterMask 를 읽는다면 같은 첫 그리기가 소프트웨어로 간다 — Matrox 쪽 점검 항목(이 프로젝트 밖).

