# G4-5 — 밉맵 경로 완성 (라이브러리만, 재부팅 없음) (계획, 2026-09-27, 코딩 전)

## 0. 범위와 전제

- 부팅 9 가 커널 쪽을 닫았다: 검증기는 밉 모드와 MAX_MIP_LEVEL 을 받고 체인 바이트로 판정하며(K5), 카드는 NEAREST_MIPMAP_NEAREST 에서 8 레벨 전부를 r200 배치의 오프셋에서 읽었다(`docs/G4_4_KERNEL_PLAN.md` 10).  이 계획의 모든 것은 **라이브러리와 탐침**이다 — 재부팅 없이 몇 번이든 빌드·실기 확인한다.
- 오늘 라이브러리의 밉 경로는 **프로브 모드**(`RDNMesaMip=1` 일 때만 밉 필터 넷을 받는다)이고, 원문을 다시 읽다가 결함 둘을 찾았다(§1): 하위 레벨을 바꿔도 카드 체인이 낡은 채 남고, 레벨 수가 MinLod/MaxLod/LodBias 를 무시한다.
- Matrox M12 Phase B 가 같은 질문에 이미 답해 두었다(§1 마지막 두 줄) — 그 결정을 그대로 따르고, 다른 점만 적는다.
- 규칙: 계산은 python, codex 검토는 코딩 전(§6), 참조는 연 줄을 인용.

## 1. 참조 (항목마다 연 것)

| 항목 | 연 곳 | 무엇을 |
|---|---|---|
| 레벨 무효화 | `r200_tex.c:701` · `r200_tex.c:749` | r200 은 TexImage2D·TexSubImage2D 마다 **그 레벨**을 dirty 로 표시(`t->dirty_images[face] |= (1 << level)`) — 다음 사용 때 그 레벨을 다시 올린다 |
| 레벨 범위 | `texmem.c:1251` · `texmem.c:1279-1284` | `driCalculateTextureFirstLastLevel`: 밉 필터면 first = Base + (int)(MinLod + 0.5), last = min(Base + (int)(MaxLod + 0.5), Base + MaxLog2, MaxLevel) — MinLod/MaxLod 를 레벨 범위로 옮긴다 |
| Mesa 3.4.2 | `texobj.c:76-80` · `types.h:878` · `texture.c:2746-2750` · `texture.c:378-397` | MinLod/MaxLod 기본 −1000/1000·MaxLevel 1000·MinMagThresh 0; 유닛의 `LodBias` 는 λ 에 더해진다; 레벨 선택(NEAREST: (int)(λ + 0.5), LINEAR: floor(λ) 와 frac 혼합, M 으로 클램프) |
| 우리 훅 | `OSRDNMesaHook.c:308` 와 TexImage/TexSubImage 훅 | 레코드는 base image 하나(체인 한 블록); TexImage 는 level 0 일 때만 drop, TexSubImage 는 level 0 일 때만 invalid — **level ≥ 1 의 변경이 카드에 안 간다** |
| Matrox 결정 | `M12_WARP_MIPMAP_PLAN.md:205` · `M12_WARP_MIPMAP_PLAN.md:249` · `M12_WARP_MIPMAP_PLAN.md:251` | 어느 레벨을 만져도 base 레코드 invalid(체인 전체 lazy 재복사); admission 은 레벨 수 = P − BaseLevel 일 때만, MinLod/MaxLod/LodBias 비기본 → 소프트웨어; 1 차 개방은 레벨 선택 두 모드(MM1S/MM2S = GL `*_MIPMAP_NEAREST`), 혼합 두 모드는 가중을 오라클과 대조한 뒤(M12-C) |
| 수혜자 | `q2-state-matrix.c:190` · `q2-state-matrix.c:193` | q2 의 "world / mipmap" 팔은 GLQuake 기본 `GL_LINEAR_MIPMAP_NEAREST`(64², RGB)로 지금은 소프트웨어를 기대 |

## 2. 설계 (라이브러리)

1. **무효화(결함 1)**: TexImage 훅 — level 0 은 지금처럼 drop, **level ≥ 1 은 base 레코드를 `valid = 0`**(체인 전체를 다음 그리기에 다시 올린다; 레벨 크기·형식은 `osrdnTexResident` 가 매번 검사하므로 모양이 바뀌면 거기서 소프트웨어로 물러선다).  TexSubImage 훅 — **어느 레벨이든** base 레코드 `valid = 0`.  r200 의 레벨 단위 dirty 대신 Matrox 의 체인 단위: 레벨 하나만 다시 올리는 최적화는 측정이 요구할 때.  라이트맵 등 비밉 객체는 레벨 0 만 있으므로 오늘과 같다.
2. **수락(결함 2)**: 밉 MIN 필터는 `to->Complete`, `BaseLevel == 0`, **MinLod ≤ 0 이고 MaxLod ≥ M**(GL 기본에서 벗어나 λ 를 자르지 않을 때 — r200 처럼 레벨 범위로 흉내내지 않는다; Matrox 규칙), **유닛 LodBias == 0** 일 때만.  레벨 수 = M + 1(M = P − Base, P 는 이미 MaxLevel 로 캡); 12 이하(log2 ≤ 11).  아니면 소프트웨어.
3. **모드 개방**: 손잡이 `RDNMesaMip` — 미설정이면 **측정된 모드만**(NEAREST_MIPMAP_NEAREST 는 부팅 9, LINEAR_MIPMAP_NEAREST 는 §3 장면 C 가 통과하면), "0" 이면 밉 전부 소프트웨어, "all" 이면 혼합 두 모드도(장면 D 측정용).  혼합 두 모드의 기본 개방은 장면 D 가 오라클 한계 안일 때 별도 결정.
4. **분류기**: `classMinOk` 가 코드별 허용(표 한 줄)과 위 수락 조건을 본다 — 훅이 상태를 채운다(`texMinLod`, `texMaxLod`, `texM`, `texLodBias`).
5. **q2 기대치**: 장면 C 통과 뒤 "world / mipmap" 을 hardware 로(q2-state-matrix 는 Matrox 원본 그대로라 기대 문자열은 judge 쪽 허용 목록에서 뺀다).

## 3. 탐침 (`ghostprobe_v19`, 재부팅 없음)

- **장면 A·B**: 부팅 9 그대로(회귀).
- **장면 C — LINEAR_MIPMAP_NEAREST / MAG LINEAR 의 레벨 선택**: A 와 같은 단색 레벨·같은 사각형; 단색이라 레벨 안 필터는 결과를 안 바꾸고, 사각형 i 가 레벨 i 색이어야 한다(r200 은 이 GL 모드를 `R200_MIN_FILTER_NEAREST_MIP_LINEAR` 필드로 보낸다 — `r200_tex.c:206-231`).
- **장면 D — 혼합 가중(NEAREST_MIPMAP_LINEAR·LINEAR_MIPMAP_LINEAR, `RDNMesaMip=all`)**: 레벨 i 의 G = 32·i(단색), 16 px 사각형에 텍스처 좌표 범위 s = 2^λ / 8 로 λ = 1 + k/8(k = 0…8).  GL/Mesa 의 혼합은 floor(λ)·frac(λ) 이므로 기대 G = 32 + 4k(k < 8), k = 8 은 64(`build/g45/model.py` 가 표를 만든다).  판정: |G − 기대| ≤ 2(f 오차 ≤ 1/16, M12-C 와 같은 한계), 사각형 안 G 폭 ≤ 4.  이것으로 카드의 λ 산식(두 축 max 인지)과 혼합 가중이 함께 드러난다.  stock 은 대조군으로만 기록(Mesa 3.4.2 는 ρ² 를 두 축의 합으로 계산해 λ 가 +0.5 밀린다 — `triangle.c:1061-1076`; 부팅 9 의 stock 편차는 이것으로 일부만 설명되며 미해결로 남아 있다).
- **장면 E — 무효화**: λ = 2 사각형을 그린 뒤 (E1) `glTexSubImage2D(level 2)` 로 전부 다른 색, (E2) `glTexImage2D(level 2)` 로 또 다른 색, 각 뒤에 다시 그려 새 색이어야 한다; level 0 은 안 바뀌었으니 λ = 0 사각형은 그대로.  결함 1 의 회귀 시험.
- **장면 F — 수락 규칙**: MinLod = 1, MaxLod = 2, LodBias = 1(EXT 가 켜져 있으면) 각각에서 `delegated` 가 늘어야(소프트웨어) 하고 그림은 stock 과 같다.
- 판정기 `judge_g45.py`: A·B·C 사각형 색, D 의 G 표, E 의 색 변화, F 의 delegated 증가와 stock 일치; 모든 장면 lost = refused = 0.

## 4. 호스트 검사 (코딩 전에 정한다)

| 검사 | 무엇을 |
|---|---|
| `check_hook` | 규칙 `g45-mip-invalidate`(TexImage level ≥ 1 과 TexSubImage 모든 레벨이 base 레코드를 invalid) · `g45-mip-admit`(수락 조건 넷); 변이 각각 |
| `sim_class` 또는 분류기 단위 시험 | `classMinOk` 의 표: 코드 × 손잡이 × 조건 |
| `sim_arena` | 체인 경우(부팅 9 그대로) |
| `build/g45/model.py` | §3 장면 D 의 좌표·기대 G, 장면 C/E 의 사각형 |
| `check_compile`·`hostcheck-r2b0`·`check_units`·`sim_batch` | 회귀 |

## 5. 실기 (재부팅 없음, 내 gcdsd)

러너 `build/g45/run_g45.sh`(LIBRUN; 드라이버 4d2ee38a 그대로): 프로브 v19(가속 두 번: 기본 손잡이·`RDNMesaMip=all`, 그리고 stock) → 장면 A–F → q2-state-matrix → 회귀(MANY·SEG·ORDER·UV·TEXBIG·ALPHA) → 판정 넷(texbig·g43·g42·g45).

## 6. codex 교차검토 판정표 (2026-09-27, 두 호출, 전부 원문으로 재확인)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 결함 1 은 사실: 레코드는 `Image[0]->DriverData` 하나, TexImage 는 level 0 만 drop, TexSubImage 는 level 0 만 invalid, 업로드는 `!r->valid` 일 때만 | `OSRDNMesaHook.c:308` 이하 원문 | ✅사실 |
| `Driver.TexImage` 가 불릴 때 새 이미지는 이미 설치돼 있다; 기존 레벨은 **같은 구조체를 재초기화**(옛 `Data` 만 free)하고 `init_texture_image` 는 `DriverData` 를 안 건드린다; 새 구조체는 `CALLOC_STRUCT`(0) | `teximage.c:1493-1512`·`teximage.c:1555-1566`·`teximage.c:341-347` | ✅사실 — level 0 drop 은 옛 카드 사본의 레코드를 푼다(의도대로), level ≥ 1 의 `valid = 0` 은 살아 있는 base 레코드에 닿는다 |
| TexImage 뒤 dirty 목록 → `gl_update_dirty_texobjs` 가 완전성·P·M 을 다시 계산 | `teximage.c:1563-1565`·`texstate.c:1727-1737` | ✅사실 — 다음 그리기의 `Complete`/`M` 은 새 값 |
| `valid = 0` 은 아무것도 free 하지 않고 `osrdnTexDrop` 은 0 을 확인·지우므로 이중 해제 없음 | 원문 | ✅사실 |
| **TexSubImage2D(새 방식 훅)가 성공하면 구식 `Driver.TexSubImage` 를 건너뛴다** — 무효화가 보장 안 된다 | `teximage.c:2156-2174`·`teximage.c:2234-2244` 원문은 맞다; 그러나 `Driver.TexSubImage2D`·`Driver.TexImage2D` 를 설정하는 곳은 Mesa core·OSMesa·`mesa/` 어디에도 없다(grep 0 건) | ⚖️부분채택 — 이 빌드에선 도달 불가; `check_hook` 규칙으로 "아무도 설정하지 않는다" 를 못 박는다 |
| 장면 D 의 기대 G 표(32 + 4k, k = 8 은 64) 맞음; 8 비트 반올림은 ≤ 0.5 라 ±2 안 | python(§3) 과 같은 값 | ✅사실 |
| stock Mesa 는 이 사각형에서 λ = L + 0.5(ρ² = r1 + r2 = 2·(2^L)²): k = 0 → G 48, k = 4 → 64 | `triangle.c:1061-1076` 산술 재계산 | ✅사실 — 장면 D 에서 stock 은 대조군이 아니라 **다른 답**이다; 판정은 GL 표로 |
| 단색 레벨이면 레벨 안 필터·REPEAT 이음매가 결과를 안 바꾼다 | 논리 | ✅채택 |
| r200: GL_NEAREST_MIPMAP_LINEAR → `LINEAR_MIP_NEAREST`, GL_LINEAR_MIPMAP_LINEAR → `LINEAR_MIP_LINEAR` | `r200_tex.c:224-230` | ✅사실 — `triMinField` 가 이미 이 대응 |

**stock 편차(부팅 9)와의 관계**: 위 산식대로면 stock 의 장면 A 사각형 1–4 도 한 레벨 높아야 하는데 실측은 맞았다 — 아직 설명 안 됨(미해결 유지).  카드 경로는 GL 정의대로이므로 영향 없음.

## 7. 첫 실행 (2026-09-27, 라이브러리 790469684, 드라이버 4d2ee38a, 내 gcdsd; `build/g45/run.log`)

- **세 제출이 CP_WHY_SEED(13)로 거절**(장면 D 822 워드·E 146 워드·UV 734 워드; 커널 로그 `RDN-R5 zclear ... rc=1 why=13 gv=00000001`).  CP 정지가 아니었다(rc 1 = REFUSED, 아무것도 안 씀).  원인은 **러너**: 탐침이 `RDNMesaSeed` 없이 뜨면 시드가 1 에서 시작하고(`OSRDNMesaTri.h` 의 WHERE THE SEED COMES FROM), 직전 프로세스가 제출을 딱 한 번 했으면 다음 프로세스의 첫 제출이 같은 시드다.  g1·m3a·m3e·m3h 러너는 실행마다 시드를 주었는데 g3c 에서 파생된 g43·g44·g45 러너가 그것을 잃었다(부팅 8·9 는 우연히 안 걸림).  `run_g45.sh` 는 가속 프로세스 13 개 모두에 `RDNMesaSeed=$((SEEDBASE + n000))` 를 준다.
- 그 거절을 빼면: 장면 C(`RDNMesaMip=all`)는 16 삼각형 전부 카드, 기본 손잡이에서는 카드 0(분류기가 거절하면 삼각형 함수가 설치되지 않으므로 소프트웨어는 `delegated` 가 아니라 `drawn = 0` 으로 보인다 — 판정기 정정); **장면 E 의 행 1·2 는 TexSubImage·TexImage(level 2) 뒤 새 색으로 그려졌다 = 결함 1 의 고침이 실기에서 동작**; 장면 F 의 MinLod·MaxLod·LodBias 세 경우 모두 소프트웨어, 그림은 stock 과 동일.
- **stock 편차 해명**: 장면 D 의 stock 값(k = 0 → G 48, k = 4 → 63)은 Mesa 3.4.2 의 λ + 0.5(ρ² = r1 + r2) 그대로다.  축 정렬 정사각형에서 그 λ 는 NEAREST 반올림 경계(i + 0.5)에 **정확히** 놓이므로 부동소수 오차로 i 와 i + 1 을 오간다 — 부팅 9 장면 A 의 "0–4 는 맞고 5·6 은 한 레벨 위" 가 이것으로 설명된다(장면 E 의 stock 도 같은 128 px 사각형이 행마다 레벨 0 과 1 로 갈렸다).  카드는 GL 정의(λ = log2 ρ, max 축)대로다.

## 8. 결과 (2026-09-27, 라이브러리 **790470099**, 드라이버 4d2ee38a, 재부팅 없음; `build/g45/run3.log`)

| 장면 | 실측 | 판정 |
|---|---|---|
| A·B(부팅 9 회귀, 기본 손잡이) | 8 사각형 레벨 0–7, MAX_LEVEL 4 클램프 | judge_g44 PASS |
| C LINEAR_MIPMAP_NEAREST | `RDNMesaMip=all` 과 기본 손잡이 모두 16 삼각형 카드, 사각형 i = 레벨 i 색 100 % | PASS — **측정 마스크에 추가** |
| D *_MIPMAP_LINEAR 혼합 | 카드 G = 32, 35, 38, 41, 45, 49, 54, 59, 64 = **32·2^(k/8)** (9 점 모두 ±0.5): 카드는 두 레벨을 **ρ 에 선형**(f = 2^frac(λ) − 1)으로 섞는다; GL 의 f = frac(λ) 와 최대 0.086(λ 소수 0.53) 차이 — M12-C 의 1/16 을 넘는다 | 법칙은 확정, 두 모드는 **기본 소프트웨어**(`RDNMesaMip=all` 에서만 카드) |
| E 레벨 교체 | 행 0 레벨 2, 행 1 TexSubImage 색, 행 2 TexImage 색 — 무효화 고침이 실기에서 동작 | PASS |
| F MinLod·MaxLod·LodBias | 기본은 카드 2 삼각형, 세 경우는 소프트웨어(drawn 0), 그림 stock 과 동일 | PASS |
| q2-state-matrix | "world / mipmap"(GLQuake 기본 필터) **HARDWARE**(32 카드, 소프트웨어 0) — 부팅 8 까지 소프트웨어였던 팔 | judge_g43 PASS(mipmap 팔은 허용 목록) |
| 회귀 | MANY 2 배치·SEG·ORDER·UV·TEXBIG·ALPHA | judge_texbig·g42·g43 PASS |

**남은 소프트웨어 상태(의도)**: *_MIPMAP_LINEAR 두 모드(혼합 법칙 차이), LUMINANCE 텍스처, MinLod/MaxLod/LodBias 비기본.  GLQuake 경로(LINEAR_MIPMAP_NEAREST, 포트가 강제하는 LINEAR)는 전부 카드다.

## 9. 다음 (2026-09-27)

- **GLQuake 빌드**: `ACCEL=radeon RDN_LIB=.../790470099/libGL_radeon.a sh build-glquake.sh` 가 오류 0 으로 `/usr/local/nxbuild/bin/glquake_radeon` 을 만들었다(세션 초의 `OSMGAMesaRefusal` 선언 충돌은 include 순서 고침으로 닫힘).
- **가속이 온전한가**: GLQuake 가 실제로 쓰는 상태 — 월드 LINEAR RGBA, 라이트맵 RGBA(포트가 `-lm_4` 경로로 강제, `gl_vidsdl.c:99`), 알리아스, 2 패스, 그리고 이번에 밉맵(GLQuake 기본 필터) — 가 q2-state-matrix 에서 전부 HARDWARE.  남은 소프트웨어 팔(LUMINANCE)은 이 포트가 쓰지 않는다.  그래서 timedemo 가 의미 있는 시점이다(`timedemo-only-when-accel-is-complete`).
- **timedemo 는 사용자 gcdsd**: 게임이 SDL 창을 연다(내 telnet gcdsd 엔 WindowServer 가 없다).  러너 `build/g46/run_timedemo.sh [w] [h]` — radeon 과 대조군 `glquake_sw` 를 같은 해상도로, 가속 프로세스마다 고유 `RDNMesaSeed`.
- **그 뒤**: timedemo 수치가 제출 비용에 막히면 R7c(링·스테이징 확대)가 다음 커널 부팅 후보; 아니면 커널 부팅 없이 끝난다.  포트의 LINEAR 강제(`gl_vidsdl.c:476`)를 풀어 GLQuake 기본 밉 필터로 돌리는 것은 Matrox 빌드와 공유하는 포트 변경이라 사용자 결정 사항.
