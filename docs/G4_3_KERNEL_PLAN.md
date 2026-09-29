# G4-3 — 커널 한 부팅: 대기·알파 테스트·검증기 텍스처 경계·스테이징 (계획, 코딩 전, codex 교차검토 대상, 2026-09-26)

G4-1b 가 닫히면서 라이브러리만으로 갈 수 있는 곳은 끝났다(`docs/G4_GLQUAKE_PLAN.md` 8-1).  남은 것은 전부 커널 쪽이고, 커널은 부팅을 태운다.  그래서 한 부팅에 넣을 것을 **참조가 하는 일**(BSD/Linux DRM, xorg, Mesa r200, Matrox 커널·훅)에서 항목마다 읽어 정하고, 각 항목을 **현재 코드 → 참조 → 설계 → 호스트 검사 → 실기 판정** 으로 적는다.  사용자 규칙: 혼자 판단하지 않는다, timedemo 는 가속이 온전한 뒤에만.

## 0. 범위와 전제

- 한 부팅.  CP 는 부팅당 한 주기(`runner-plan-must-equal-judge-procedure`), 러너 = 판정 절차.  드라이버 빌드 → `nm -u` → 설치 → 재부팅(사용자) → 러너 → 판정 → check-all.
- 항목: **K1** 큰 배치의 대기(§6-9 유실), **K2** 알파 테스트(PP_MISC), **K3** 검증기 텍스처 경계(크기·정렬·밉 체인), **K4** 스테이징 확대.  **K5** 밉맵과 **K6** 텍스처 캐시는 §6·§7 에서 "이 부팅 밖" 으로 근거와 함께 둔다.
- 라이브러리 쪽 짝(분류기 조항·프롤로그 슬롯·shim)은 커널 항목과 같은 번호로 같이 간다; 재부팅 없이 되는 부분은 커널보다 먼저 호스트 검사까지 끝낸다.

## 1. 참조 (항목마다 연 것)

| 항목 | BSD/Linux DRM | xorg | Mesa r200 / 3.4.2 | Matrox |
|---|---|---|---|---|
| K1 대기 | `radeon_cp.c:1901-1925` `radeon_wait_ring`: **head 가 움직이면 i = 0** — 예산은 "진행 없음" 구간에 대한 것; `radeon_cp.c:378-396` `radeon_do_wait_for_idle`: RBBM_ACTIVE 를 `usec_timeout` 번(1 µs 간격) 만 본다; 그 상한 `radeon_drv.h:1805` 100 ms; `radeon_cp.c:552-566` `radeon_do_cp_idle` = PURGE + WAIT_UNTIL_IDLE 패킷 뒤 그 대기.  제출 자체는 대기하지 않는다 | `radeon.h:237-238` `RADEON_IDLE_RETRY 16`·`RADEON_TIMEOUT 2000000`; `radeon_accel.c:640-652` idle ioctl 이 EBUSY 면 `RADEON_IDLE_RETRY` 만큼 다시(`i++ < 16` 이라 루프 17 회 + 첫 호출 = 18 회 — codex 지적, 원문 확인); `radeon_accel.c:135-146` MMIO 대기는 2 M 회 폴링 뒤에야 리셋 | — | `OpenStepMGAReplacementDisplay.m:2577-2583` 완료 폴링은 지연 × 루프 한도로 **벽시계 상한을 고정** |
| K2 알파 테스트 | — | — | `r200_state.c:66-92` `r200AlphaFunc`: PP_MISC = REF 바이트 ∣ OP; `r200_reg.h:33-43` 필드; 켜기는 PP_CNTL `R200_ALPHA_TEST_ENABLE`(`r200_reg.h:180`, `r200_state.c:1965`); Mesa 3.4.2 `types.h:356-357` AlphaRef 는 **GLubyte** | `OpenStepMGAMesaHook.c:2818-2835` GL 함수 → 모드, **ALWAYS 는 끔**, NEVER 는 선택기가 거절 |
| K3 텍스처 경계 | `radeon_state.c:116-135` TXOFFSET 은 오프셋만 고친다(크기 검사 없음) | — | `r200_texstate.c:278` 레벨은 32 B 정렬로 연속, `r200_texstate.c:315-316` 총 크기 정렬, `r200_texstate.c:338-339` MAX_MIP_LEVEL = 레벨 수 − 1; `r200_texmem.c:382` 블릿 오프셋은 1 KiB 단위 | 아레나 32 B(M12 계획 1-2) |
| K4 스테이징 | 링은 DRM 이 크게 잡는다(우리 링 `osrdn_cp.h:51` 4096 워드) | — | — | 사다리꼴 40 dword 리스트를 DMA 블록으로(`OpenStepMGAReplacementDisplay.m:2584-2592`) |
| K5 밉 | — | — | 위 K3 의 배치 규칙 | `M12_WARP_MIPMAP_PLAN.md:1-40`: 마지막 품질 항목으로, 자격 프로브가 1 단계 |
| K6 텍스처 캐시 | `radeon_state.c` 텍스처 업로드 = FLUSH_CACHE + WAIT_UNTIL_IDLE 뒤 블릿(§7) | — | — | — |

## 2. K1 — 큰 배치가 정지로 읽히지 않게

**구현 전**: 제출 뒤 W_RPTR 100 ms → W_IDLE 100 ms, 둘 다 **벽시계 고정**(`osrdn_cp.m:217` `cpWait`, `C_IDLE_US`/`C_RPTR_US` 100 000).  **구현(2026-09-26)**: `osrdn_cp.m:2417-2420` — W_RPTR 는 진행 되돌림, W_IDLE 은 `cpWaitRetry` 로 `CP_IDLE_RETRY`(16, `osrdn_cp.h:52`) 회; world5 의 두 경우(느린 그리기 = 재시도로 통과, 진짜 정지 = 16 회 뒤 정지)와 `check_r5_src` 규칙 `g43-k1-wait`·변이 3 개 PASS.  넘기면 `cpFail`(`osrdn_cp.m:489`) 이 복구(도어벨 재타·리셋)하고 클라이언트는 EIO 를 받는다.  §6-9 의 uv 64·256: 카드는 다 그렸는데(VRAM = stock) 대기가 먼저 끝났다.

**참조가 하는 것**: DRM 은 링 공간 대기에서 **진행이 있으면 시계를 되돌린다**(`radeon_cp.c:1911-1919`), idle 은 100 ms 를 보되 xorg 가 EBUSY 를 **`RADEON_IDLE_RETRY`(16) 번 더** 시도한다(`radeon_accel.c:640-652`; 실제 호출은 18 회) — 실효 예산 1.6–1.8 s.  MMIO 대기는 2 M 폴 뒤에야 리셋.  그리고 DRM 은 **일반 제출 뒤 idle 을 기다리지 않는다**: vertex 는 `COMMIT_RING(); return 0;`(`radeon_state.c:2282-2290`), indirect 도 같고 앞에 `WAIT_UNTIL_3D_IDLE` 패킷만 넣는다(`radeon_state.c:2484-2500`).  우리 제출이 동기인 것은 M2e 의 결정(클라이언트가 glFinish 뒤 VRAM 을 읽는다)이라 이 부팅에선 예산만 참조의 것으로 맞춘다.

**설계**
- W_RPTR: `cpWait` 에 "진행 되돌림" 을 넣는다 — rptr 이 마지막 값과 다르면 t0 를 다시 찍는다(`radeon_wait_ring` 그대로).  상한은 그대로 100 ms **무진행**.
- W_IDLE: rptr 이 wptr 에 닿은 뒤의 idle 은 진행 신호가 없다.  참조처럼 **재시도 수**를 둔다: `C_IDLE_RETRY 16`(xorg `RADEON_IDLE_RETRY` 와 같은 상수; xorg 의 실제 호출 수 18 회는 오프바이원이라 따라 하지 않고 16 × 100 ms = 1.6 s 로 적는다), 한 번에 `C_IDLE_US`.  몇 번째에 끝났는지 `w->retries` 로 남긴다(측정: 실제 최악을 안다).
- 실패 판정·복구·EIO 는 지금 그대로, 예산만 참조의 것으로.  다른 대기(FIFO·KICK·DC)는 손대지 않는다.
- 계수기: `wIdle.retriesMax`, `wRptr.progressResets` — `RDN-R5 wait` 줄에 추가.

**호스트**: world5 에 "느린 그리기"(idle 이 N 폴 뒤에 서는 모형)를 넣고 uv64 급 배치가 EIO 없이 끝나는 것을 단언, 변이(재시도 1) 가 잡히는지; check_r5_src 규칙: 상수 16 은 `radeon.h:237` 에서 읽은 값과 같아야.  **실기**: `GHOST_UV` uv 64·256 → drawn 32, EIO 0, 대기 µs 기록; q2-state-matrix 19/21 (밉·LUMINANCE 제외 전부).

## 3. K2 — 알파 테스트 (스프라이트·2D 매 프레임)

**필요**: GLQuake 는 월드는 끄고 그리지만 스프라이트와 **2D(콘솔·HUD 글자)** 는 `GL_GREATER 0.666` 을 켠다(`docs/G4_GLQUAKE_PLAN.md` 1 표) — 지금은 켜진 상태 = RasterMask 밖 → 매 프레임 소프트웨어.

**인코딩(참조)**: `r200AlphaFunc`(`r200_state.c:66-92`): `PP_MISC`(0x1c14) 의 `REF_ALPHA[7:0]` = ref 바이트, `ALPHA_TEST_OP[10:8]` = NEVER 0(FAIL)…GREATER 5, ALWAYS 7(PASS)(`r200_reg.h:33-43`); 켜기 = `PP_CNTL` bit 23(`r200_reg.h:180`).  Mesa 3.4.2 는 `glAlphaFunc` 진입점에서 0..1 을 바이트로 바꿔 둔다(`alpha.c:57-62`: 끝점 0/255, 중간은 `FloatToInt(f*255)` — 일반 경로는 내림, `mmath.h:284-285`); 훅은 **그 바이트를 그대로** 쓴다 = Mesa 소프트웨어가 비교하는 값과 같다.  r200 은 자기 float ref 를 반올림한다(`imports.h:495-496` IROUND)라 우리 식과 다를 수 있으나 우리 대조 기준은 stock Mesa 다(codex 지적으로 정정).  Matrox 는 ALWAYS 를 "끔" 으로 보내고 NEVER 를 거절한다(`OpenStepMGAMesaHook.c:2818-2835`) — 같은 규칙.

**커널**: `PP_MISC` 는 허용 41 개 밖(`verify_oracle.py:108` — 허용은 **측정된** 레지스터에서 생성).  그러므로 순서는 **측정 → 허용**: 이 부팅의 R6 경우 **R6n**: 알파가 열마다 0..255 로 오르는 8×8 텍스처(R6h 무늬 방식), REPLACE, `PP_CNTL|bit23`, `PP_MISC = GREATER | 0xaa` 와 대조군(비트 끔·PASS·FAIL·LEQUAL 0xaa) — 판정은 열별 "그려짐/안 그려짐" 이 `alpha > 170` 과 맞는지(경계 값 170 자체가 열에 있게 무늬를 짠다: 비교가 > 인지 ≥ 인지 갈린다).  통과 뒤 `cpR7Allow` 에 0x1c14 추가(생성기 `--c-tables`), 값 규칙: REF·OP 밖 비트 0; `PP_CNTL` 값 규칙에 bit 23 허용.

**라이브러리(구현 2026-09-26)**: 분류기 조항 A — `RM_ALPHA`(ALPHATEST_BIT) 를 아는 비트에 넣고, 비트와 `Color.AlphaEnabled` 가 어긋나면 RASTER, 코드가 0 이면 `OSRDN_WHY_ALPHA_MODE`; 코드 = `osrdn_class_alpha_code(func, ref)` = 1 | op<<1 | ref<<4, op 는 r200AlphaFunc 의 필드 값(NEVER→FAIL 0 … ALWAYS→PASS 7: 여덟 함수 전부, Matrox 의 "ALWAYS 는 끔" 대신 참조의 PASS 를 따랐다).  훅은 `osrdn_tri_alpha_set(code)`(텍스처 설정과 같은 모양, 배치 키에 포함), Tri 는 슬롯 `PP_CNTL`(템플릿 워드 | ALPHA_TEST_ENABLE)·`PP_MISC`(ref | op<<8) — 두 템플릿 모두, 생성기가 r200_reg.h 에서 파생하고 자체검사.  sim_class 행 6·변이 2, check_hook 규칙 `g43-k2-alpha`·변이 2, 전부 PASS.  **커널**: `PP_MISC` 를 허용 42 번째로 — 원칙은 "R6 사다리가 잰 레지스터" 였는데 이것은 **클라이언트 경로에서 stock Mesa 를 오라클로 재는** 레지스터라 오라클에 그 뜻을 적어 넣었다(`verify_oracle.py:108` 위 주석); 값 규칙은 REF·OP 두 필드뿐(경우 U31·U32), world5 도 같은 마스크.  R6n 커널 경우는 **만들지 않았다**: 측정은 ghostprobe 의 알파 장면(§8)이 한다.  **실기**: `GHOST_ALPHA` 7 장면(GREATER 0.666·LEQUAL·NEVER·ALWAYS·NOTEQUAL·EQUAL·끔) 가속 vs stock, 판정 `judge_g43.py`(이웃 밖 0, 그려진 화소 수 차 ≤ 600); q2 의 2D 팔.

## 4. K3 — 검증기 텍스처 경계

**구현 전**: TXOFFSET 은 창 안 + **끝까지 1 KiB**(`osrdn_cp.h:258`) 만 봤다; 정렬 검사 없음; 밉 필드는 거절(`osrdn_cp.m:2630`; G4-4 K5 가 미실측 필드 마스크로 바꿨다).  **구현(2026-09-26)**: `osrdn_cp.m:2768` `cpR7TextureFits`/`cpR7TextureBytes`(G4-4 K7 뒤엔 `cpR7SurfacesOk` 안) + 오라클 `texture_bytes`, 경우 U25–U30, TXFORMAT 값 규칙(ARGB8888 만); sim_r5·check_r7b PASS.  G4-1b 가 512² 를 보내는 지금, 검증기는 텍스처가 창 밖 1 MiB 를 읽어도 모른다.

**설계**: 텍스처 바이트를 **카드가 읽는 레지스터에서** 계산한다 — `TXFORMAT` 의 log2 폭·높이(비트 8·12, `r200_reg.h` WIDTH/HEIGHT_SHIFT), 텍셀 4 바이트(ARGB8888 만 허용, 형식 필드 값 규칙), `MAX_MIP_LEVEL` n 이면 레벨 i 의 바이트 = ((w>>i)·4 를 32 로 올림)·(h>>i)(비타일 2D 의 식, `r200_texstate.c:271-275`; 마이크로타일·사각형 텍스처는 다른 식이라 형식 값 규칙으로 막는다), 레벨 시작은 32 B 정렬(`r200_texstate.c:278`), **총합은 1 KiB 로 올림**(`r200_texstate.c:315-316`, `RADEON_OFFSET_MASK` = 0x3ff `radeon_drm.h:327-332` — 처음 32 B 라 적은 것은 내 오류, codex 가 잡음).  레벨별 오프셋 레지스터는 R200 에 없다(`r200_reg.h` 의 `PP_TXOFFSET_0..5` 는 유닛별) — 체인은 TXOFFSET 하나에서 유도된다.  규칙: `toff` 32 B 정렬(R6 실측 눈금), [toff, toff+bytes) ⊂ [winStart, winEnd), 색·깊이 표면과 서로소(`cpR7SurfaceFits` 와 같은 틀).  밉 필드는 K5 전엔 계속 거절하되 **크기 계산은 지금 넣어** K5 가 검증기를 다시 열지 않게.  호스트: `verify_oracle.py` 거울 + `check_r7_src` + world5 경우(창 끝 걸침·정렬 어긋남·표면 겹침 = 거절).  **실기**: TEXBIG 10 장면 그대로 PASS(회귀), 검증기 거절 0.

## 5. K4 — 스테이징 확대

**수치**(`model.out:8-18`, K4 뒤 재계산): 4068 워드 배치 = 텍스처 삼각형 190 개(2016 이면 93); 10 000 tri/프레임이면 53 배치(2016: 108) → 제출 25.4 ms(41.5) → 상한 39 fps(24).

**제약**(codex 가 코드에서 끌어낸 것을 내가 열어 확인): 커널이 클라이언트 워드 앞에 붙이는 것은 **WAIT_UNTIL 한 쌍(2 워드)**, 뒤는 purge 2 쌍 + wait + RB3D_CNTL + scratch = **10 워드**(`osrdn_cp.m:3350-3358`, `osrdn_cp.m:3494-3498`); 26 워드 상태 프리픽스는 **별도 제출**(`osrdn_cp.m:3229-3234`).  `model.out` 의 "54" 는 라이브러리의 텍스처 프롤로그(배치 안)이지 커널 프리픽스가 아니다 — 처음 적은 "프리픽스 54" 는 내 혼동.  제출 길이 L = roundup16(B + 2 + 10) 이 `cpPut` 마스킹으로 되감기며(`osrdn_cp.m:2370-2381`, `osrdn_cp.m:2403-2406`), 조건은 **0 < L < CP_RING_WORDS**(등호는 target == start).  2016 은 design3 의 옛 모형(끝 패딩·프리픽스 22 가정)에서 나왔다; 지금 `design3.py:42-44` 는 현행 되감기 모형이고 4068/4080 을 도출해 헤더·오라클 다섯 곳과 대조한다(PASS).  안 A: `CP_R7_BATCH_MAX` 2016 → **4068**: L = roundup16(4080) = 4080 < 4096(design3 가 도출; 여유가 아니라 팽팽함).  동반: `CP_R6_WORDS` 2064 → **4080**(`osrdn_cp.m:3171-3174` 가 need > CP_R6_WORDS 로 먼저 거절, `osrdn_cp.h:260-266`), `cpR7Buf`·`OSRDN_R7B_MAX_WORDS`, `design3.py` 를 현행 되감기 모형으로 고쳐 **4068**(팽팽한 최대: 4072 면 4096) 을 도출·다섯 상수 대조, 라이브러리 `OSRDN_BATCH_MAX_TRIS` 268 파생(sim_batch).  **창은 한 페이지 그대로**: 매핑 경로는 `OSRDN_R7B_WINDOW_WORDS`(2048) 로 묶이고(`OSRDNDisplay.m` SUBMIT 의 count 검사), 라이브러리는 `caps->maxWords > caps->bytes/4` 면 copyin 경로(SUBMIT2, 508 워드씩 스테이지)를 기본으로 고른다 — vmap 의 한 페이지 전제를 건드리지 않는 길(환경변수로 되돌릴 수 있음).  **구현(2026-09-26)** 전부 호스트 PASS.  안 B: 링 확대(R5 열 재실행, DRM 은 MB 급) — 한 부팅에 새 위험을 더 얹는다.  **안 A 로**, 링 확대는 K4 의 측정(배치/프레임·제출 ms)이 근거를 만든 뒤.  **실기**: 같은 장면의 배치 수가 절반, 정점 손실 0(sim_batch 의 경계 변이).

## 6. K5 — 밉맵은 이 부팅 밖 (결정 요청)

포트는 `VID_Init` 에서 필터를 **무조건 LINEAR/LINEAR 로** 덮는다(`docs/G4_GLQUAKE_PLAN.md` 1 표, `gl_vidsdl.c:476`): 이 포트의 GLQuake 는 밉을 샘플하지 않는다.  Matrox 도 밉을 **마지막 품질 항목**(M12) 으로, 자격 프로브부터 했다.  K3 가 체인 크기 계산을 먼저 넣으므로 K5 는 검증기 한 줄(밉 필드 허용) + 라이브러리(레벨 상주·업로드·TXFILTER MIN 필드) 로 다음 부팅에 간다.  **이 부팅에 넣기를 원하시면** R6n 옆에 밉 경우(R6h 무늬 4 레벨) 를 추가한다 — 판단은 사용자.

## 7. K6 — 텍스처 캐시는 설계로 닫힘

DRM 의 텍스처 업로드는 FLUSH_CACHE(색 캐시) + WAIT_UNTIL_IDLE 뒤 블릿이고 텍스처 캐시 명령은 없다(`radeon_state.c` `radeon_cp_dispatch_texture`).  우리 배치는 **매 배치 텍스처 레지스터를 다시 쓴다**(프롤로그), 텍셀이 바뀌면 상주 기록이 배치를 닫는다.  G4-1b sub 장면(같은 TXOFFSET 에 재업로드 → 다음 배치)이 stock 과 이웃 밖 0 으로 맞았다 — 낡은 텍셀은 관측되지 않았다.  탐침 없이 닫는다; 재발 조건(배치 중간의 텍셀 변경)은 설계상 없다.

## 8. 부팅 계획 (러너 = 판정)

1. 호스트(끝, 2026-09-26): K1 `cpWait`/`cpWaitRetry` + world5 두 경우 + `g43-k1-wait`; K2 라이브러리 짝 + 허용·값 규칙 + U31/U32; K3 `cpR7TextureFits` + 오라클 거울 + U25–U30; K4 상수 4068/4080 + design3 재작성 + copyin 기본; `hostcheck-r2b0`(C89·심볼) PASS; `check-all` 은 마지막에 한 번.  라이브러리는 재부팅 전에 빌드해 둔다(소스가 최종이므로): `target-build-mesa.sh <runid>`.
2. 드라이버: `pack_r2b0.py` → 타깃 `target-build-r2b0.sh <tar> <sum> <blocks>` → `target-install-r2b0.sh closed=yes fresh live` → **재부팅 요청**(사용자).
3. 러너(`build/g43/run_g43.sh`, 내 gcdsd; `LIBRUN=<runid> BUILD=<stamp>`): 드라이버 스탬프 확인 → CP 기동(run_g3c 와 같은 여섯 op) → 탐침 `ghostprobe_v16` 빌드(가속·stock) → `GHOST_UV`(K1) → `GHOST_MANY`(K4: 300 삼각형 = 2 배치) → `GHOST_TEXBIG`(K3 회귀, `judge_texbig.py`) → `GHOST_ALPHA`(K2) → q2-state-matrix → `judge_g43.py`(K1·K2·K4·q2 한 판정씩).
4. 러너 = 판정 절차: 판정기가 읽는 로그 이름(uv.log·many.log·alpha.log·q2.log·texbig.log)은 러너가 쓴 것 그대로다.

## 9. 위험

- R6n 이 실패하면(비교 방향·REF 해석) K2 는 이 부팅에서 **측정만** 남기고 허용은 다음 부팅 — 허용을 미리 열지 않는다.
- K1 의 재시도 1.6 s 는 진짜 정지에서 복구를 1.5 s 늦춘다 — 참조와 같은 값이라 받아들인다; 정지 빈도는 계수기로 본다.
- K4 는 링 되감기 경계(R6l·M3J)를 다시 지난다: sim_batch·world5 의 되감기 경우를 새 상수로 다시 돌린다.

## 10. codex 교차검토 판정표

4 회 국지 호출(gpt-5.6-sol), 회신의 모든 줄번호·수치를 내가 열어 확인했다.

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| K1 (a) `radeon_wait_ring` 은 head 가 움직이면 i = 0 (`radeon_cp.c:1911-1919`) | 열어 확인 (`if (head != last_head) i = 0;`) | ✅ 사실 |
| K1 (b) `radeon_do_wait_for_idle` 은 진행 되돌림 없이 usec_timeout 만, 앞에 FIFO 64 대기 (`radeon_cp.c:378-396`) | 열어 확인 | ✅ 사실 |
| K1 (c) xorg 재시도는 16 이 아니라 루프 17 + 첫 호출 = 18 회 (`radeon_accel.c:640-652`, `i++ < RADEON_IDLE_RETRY`) | 열어 확인: do-while 에 `i++ <` | ✅ 채택 — 문서 정정, 설계 상수는 16 유지(참조 상수) |
| K1 (d) DRM 은 제출 뒤 idle 을 기다리지 않는다 (`radeon_state.c:2282-2290`, `radeon_state.c:2484-2500`) | 열어 확인 (`COMMIT_RING(); return 0;`, indirect 는 앞에 WAIT_UNTIL_3D_IDLE) | ✅ 사실 — §2 에 적음(동기 제출은 M2e 의 결정) |
| K2 (c) Mesa 3.4.2 는 glAlphaFunc 에서 바이트로 변환(`alpha.c:57-62`, 일반 경로 내림 `mmath.h:284-285`), r200 은 IROUND(`imports.h:495-496`) — "변환 없음" 은 부정확 | 열어 확인 | ⚖️ 부분채택 — 훅은 Mesa 의 바이트를 그대로 쓴다(= 소프트웨어 기준); 문구 정정 |
| K3 총 크기 정렬은 32 B 가 아니라 1 KiB (`RADEON_OFFSET_MASK` 0x3ff, `radeon_drm.h:327-332`, `r200_texstate.c:315-316`) | 열어 확인 | ✅ 채택 — 내 오류 정정 |
| K3 행 크기 식은 비타일 2D 만 (`r200_texstate.c:271-275`), 레벨 오프셋 레지스터 없음 | 열어 확인, r200_reg.h 에 MIP/LEVEL OFFSET 0 건 | ✅ 사실 — 형식 값 규칙으로 타일·사각형 차단 |
| K4 커널 프리픽스는 2 워드 + 꼬리 10, 26 워드 프리픽스는 별도 제출; 조건 L = roundup16(B+12) < 4096; 2016 은 design3 옛 모형; CP_R6_WORDS 도 키워야 (`osrdn_cp.m:3350-3358`, `osrdn_cp.m:3494-3498`, `osrdn_cp.m:3171-3174`, `osrdn_cp.h:260-266`, `design3.py:42-44`) | 전부 열어 확인 | ✅ 채택 — §5 다시 씀(내 "프리픽스 54" 혼동 정정) |

## 11. 게이트·설치 (2026-09-27)

| 게이트 | 결과 |
|---|---|
| 호스트: gen self-test/--check · sim_class · check_hook · sim_pack · sim_batch · check_units · sim_arena · sim_texrun · verify_oracle self-test · check_r7b · check_r5_src · sim_r5(world5, K1 두 경우·U25–U32) · design3 · design2 · sim_r6 · check_cp · hostcheck-r2b0 · 인용 루프(전 문서) | **PASS** |
| `check-all.sh` | **PASS**(첫 실행에서 검사기 셋이 새 코드에 낡아 있었다 — design2 의 RM_KNOWN 목록, check_cp 의 합성 wait 줄, sim_r6 의 CP_R6_WORDS 앵커; 정밀화 뒤 재실행 PASS) |
| 라이브러리 | **790433817**(RDNMESA PASS; 알파 슬롯·배치 4068·copyin 기본) |
| 타깃 드라이버 **`1beb2ed9`** / runid 790438700, 미정의 심볼 21, reloc 37502 517; `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — runid 790438700 |

부팅 8 절차: 사용자 재부팅 → NFS 마운트 → 내 gcdsd → `LIBRUN=790433817 BUILD=1beb2ed9 bash build/g43/run_g43.sh` → `judge_texbig.py`·`judge_g43.py` PASS → 사용자 gcdsd 는 이 부팅에서 필요 없다(전부 오프스크린).

## 12. 부팅 8 결과 (2026-09-27, 드라이버 `1beb2ed9`·라이브러리 790433817, 내 gcdsd)

러너 `build/g43/run_g43.sh` → `judge_texbig.py` **PASS**, `judge_g43.py` **PASS**(K4 판정을 §5-1 로 정밀화한 뒤).

| 항목 | 실측 | 판정 |
|---|---|---|
| K1 대기 | `GHOST_UV` uv 1·4·16·**64·256** 전부 hooked 32 / drawn 32 / delegated 0, 거절 0; 이 부팅의 `RDN-R7B submit` 에 rc≠0 없음(부팅 7 은 uv 64·256 이 rc=8·EIO) | **PASS** — §6-9 유실 닫힘 |
| K2 알파 테스트 | `GHOST_ALPHA` 7 장면(GREATER 0.666·LEQUAL 0.5·NEVER·ALWAYS·NOTEQUAL·EQUAL·끔): 이웃 밖 0, 그려진 화소 수 stock 과 ≤ 0.5 % 차(18 717 vs 18 809 등); 14 삼각형 전부 카드, codeGap 0 | **PASS** |
| K3 검증기 | `GHOST_TEXBIG` 10 장면 회귀 PASS(G4-1b 와 같은 수치), 검증기 거절 0 | **PASS** |
| K4 배치 4068 | `GHOST_MANY` 300 삼각형 한 상태 = **5 배치**(예상 2) | ⚠ 아래 §5-1 |
| q2-state-matrix | **21 팔 중 19 HARDWARE**(밉·LUMINANCE 예정 소프트웨어), **uv 0..64 도 HARDWARE**(부팅 7 은 mixed/none) | **PASS** |

### 5-1. K4 의 실측: 배치는 워드가 아니라 Mesa 의 VB 가 자른다

300 삼각형이 5 배치였다.  Mesa 3.4.2 의 정점 버퍼는 216 정점(`config.h:181` `VB_MAX`) = 72 삼각형이고, 훅은 `RenderFinish` 마다 배치를 닫는다(`osrdnHookRenderFinish` → `osrdn_tri_batch_flush`).  그래서 배치 하나는 최대 72 삼각형 — 2016 워드(93 개) 도 4068 워드(190 개) 도 닿지 않는다.  ceil(300/72) = 5.  **K4 의 상수는 맞지만 효과는 아직 없다**: 효과를 내려면 배치가 `RenderFinish` 를 넘어 상태 변화·`glFinish`·워드 한계까지 살아 있어야 하며, 그것은 소프트웨어 원시(점·선)와의 순서 문제를 같이 풀어야 하는 **G4-2(배치 안의 상태 변화)** 의 항목이다.  모델(`build/g4/model.py`)의 "93/190 삼각형 배치" 전제는 이 실측으로 틀렸다 — 프레임당 배치 수는 tris/72 + 상태 변화 수다.  판정기 `judge_g43.py` 의 K4 기대를 5(= VB 경계)로 정밀화했다.

### 남은 것
- 대기 재시도 횟수(`wIdle.retries`)는 `RDN-R5 wait` 줄이 op 끝에서만 찍혀 이 부팅에선 회수하지 못했다(uv 64·256 이 EIO 없이 그려진 것으로 K1 은 닫힘).  다음 부팅의 러너에 "제출 직후 quiet op" 을 넣어 최악 재시도 수를 남긴다.
- K5 밉맵: 결정 대기.  G4-2: 배치가 VB 를 넘도록(§5-1).
- **K7(다음 부팅, K5 와 함께)**: 검증기의 표면 판정을 draw 마다 — G4-2 계획의 codex 검토가 찾은 구멍(`docs/G4_2_BATCH_PLAN.md` 4).
- **K8(다음 부팅, K5·K7 과 함께) — K4 의 불일치, G4-2 실기가 찾음(2026-09-27)**: K4 는 `CP_R7_BATCH_MAX`/CAPS `maxWords` 를 4068 로 올렸지만 **copyin 제출(SUBMIT2)은 여전히 8 KB 스테이징 페이지 하나로 복사**해 `n > OSRDN_R7B_WINDOW_WORDS`(2048)를 "count" 로 거절한다(`OSRDNDisplay.m` 의 reject2 가지; 커널 로그 `RDN-R7B reject2 words=4052 count`, `words=2372 count`).  부팅 8 의 K4 는 배치가 VB(72 삼각형 = 1572 워드)에 묶여 2048 을 넘은 적이 없어 못 봤다.  임시 조치(라이브러리, 재부팅 없음): 상한 = min(maxWords, bytes/4) = 2048.  커널 고침: SUBMIT2 가 페이지 단위로 `copyin` → `APPEND` 를 반복해 4068 까지 받거나, 그럴 수 없으면 CAPS 가 2048 을 광고해야 한다(광고와 수락이 갈리면 안 된다 — 검사기: `osrdn_r7b.h` 의 두 상한이 갈리는 곳을 `design3.py` 가 잡도록).  오라클 경우: 2049 워드 copyin 제출 수락.

