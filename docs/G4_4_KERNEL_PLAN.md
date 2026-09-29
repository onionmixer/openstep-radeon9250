# G4-4 — 부팅 9 커널 계획: K8 청크 copyin · K7 draw 마다 표면 판정 · K5 밉맵 (계획, 2026-09-27, 코딩 전)

## 0. 범위와 전제

- 한 부팅(부팅 9).  드라이버 빌드 → `nm -u` → 설치 → 재부팅(사용자) → 러너 → 판정 → check-all.  재부팅은 사용자 몫; 라이브러리는 재부팅 없이 몇 번이든 다시 빌드할 수 있으므로 **커널 항목을 먼저, 라이브러리 항목은 그 뒤에 반복**하는 순서로 짠다.
- 세 항목은 전부 G4-2·G4-3 이 남긴 것이다: K8 은 G4-2 실기가 잡은 K4 의 불일치(`docs/G4_2_BATCH_PLAN.md` 12-1), K7 은 G4-2 계획의 codex 검토가 찾은 검증기 구멍(같은 문서 4), K5 는 G4-3 §6 에서 사용자가 "다음 부팅으로" 미룬 밉맵.
- 규칙: 계산은 python(`build/g44/model.py`), codex 검토는 코딩 전(§8), 참조는 항목마다 열어 인용(§1).

## 1. 참조 (항목마다 연 것)

| 항목 | 연 곳 | 무엇을 |
|---|---|---|
| K8 | `OSRDNDisplay.m:1141` · `OSRDNDisplay.m:1171-1172` · `OSRDNDisplay.m:1247` · `OSRDNDisplay.m:927` · `osrdn_cp.m:2883` · `osrdn_cp.h:291` | SUBMIT2 는 (구현 전) `n > OSRDN_R7B_WINDOW_WORDS` 를 "count" 로 거절하고 한 페이지에 `n*4` 바이트를 한 번에 copyin 했다 — 인용 줄은 K8 구현 뒤의 count 검사와 조각 copyin; r7bSubmit 은 페이지에서 508 워드씩 APPEND; copyin 은 클레임 전이어야 한다; `cpR7Stage` 는 조각마다 `cpR7Buf` 로 옮기고 4068 을 넘으면 떨어뜨린다 |
| K8 참조 | `radeon_state.c:2856` · `radeon_state.c:2866-2869` · `radeon_state_linux.c:2883-2898` | BSD·Linux 의 cmdbuf 는 **64 KiB 상한**, 커널 버퍼를 할당해 전체를 한 번에 복사(BSD `drm_alloc`+`DRM_COPY_FROM_USER`; Linux 3.10 은 `drm_buffer_alloc`+`drm_buffer_copy_from_user`, 페이지 단위 버퍼) — 둘 다 "복사한 뒤 검증·제출" 이지 페이지 하나에 묶이지 않는다 |
| K7 | `osrdn_cp.m:2774` · `osrdn_cp.m:2722` · `verify_oracle.py:209-243` | 검증기는 루프 안에서 표면 레지스터를 마지막 값으로 덮고 **루프 뒤 한 번** 판정한다(커널·오라클 같은 모양) |
| K5 필드 | `r200_reg.h:826-839` · `r200_reg.h:846-847` · `r200_tex.c:206-231` | MIN_FILTER 는 비트 [4:1], 밉 모드 2·3·6·7(<<1) 는 전부 **비트 2** 를 켠다, 이방성 8–11 은 비트 4; MAX_MIP_LEVEL 은 [19:16]; GL 네 밉 필터 ↔ 네 모드 1:1(r200SetTexFilter) |
| K5 배치 | `r200_texstate.c:272` · `r200_texstate.c:282-285` · `r200_texstate.c:338-339` | 레벨 i 의 행 = (폭×4 + 31)&~31, 레벨 시작은 32 B 정렬로 **연속**, MAX_MIP_LEVEL = 레벨 수 − 1 — K3 의 `cpR7TextureBytes`(`osrdn_cp.m:2647`)·오라클 `texture_bytes` 가 이미 이 배치로 체인 바이트를 센다 |
| K5 구현 전 규칙 | `osrdn_cp.m:1404` · `osrdn_cp.m:2630` · `verify_oracle.py:114` · `verify_oracle.py:154` · `OSRDNMesaClass.c:309-310` | 커널·오라클의 "밉 마스크" 0x1c000 은 **비트 14·15·16** 이라 MIN_FILTER 필드도 MAX_MIP_LEVEL 전체도 아니었다(python 확인 §2-3) — 인용 줄은 K5 구현 뒤 `CP_R7_TXFILTER_UNMEASURED`/`TXFILTER_UNMEASURED_MASK` 가 선 자리; 분류기는 MIN/MAG 를 NEAREST·LINEAR 로만 받았다(K5 뒤 `classMinOk` 가 손잡이·완전성으로 밉 넷을 더 받는다) |
| K5 실측 | `R6H_PLAN.md:136` · `R6I_PLAN.md:29` | 4 폭 텍스처의 행은 **32 바이트 간격**으로 읽힌다(XF) — r200 배치의 행 반올림과 같다; MAX_MIP_LEVEL 이 PP_TXFILTER 비트 16–19 라는 것은 R6i 가 실측 |
| K5 Mesa | `texobj.c:186-200` · `types.h:802-811` · `types.h:828` · `texture.c:378-397` | 완전성 검사가 `P`(최고 레벨)·`Complete` 를 채운다; 객체는 `Image[level]`·`MinFilter` 를 가진다; 소프트웨어 샘플러의 레벨 선택(NEAREST: λ+0.5 내림, LINEAR: 두 레벨 보간, `M` 으로 클램프) |
| K5 Matrox | `M12_WARP_MIPMAP_PLAN.md:1-40` | 밉은 **자격검증 프로브가 1 단계**(4D9 의 아틀라스 기법: 레벨 서명·대조군·모드×배율), 훅 게이트 개방은 그 뒤; 체인은 한 블록, 레벨 원점은 블록 안 오프셋; GLQuake 는 1×1 까지 전 레벨 업로드하고 포트는 LINEAR 로 강제 복구 |

## 2. K8 — SUBMIT2 청크 copyin (K4 의 불일치를 닫는다)

### 2-1 사실
- CAPS 는 `maxWords = OSRDN_R7B_MAX_WORDS`(4068, `OSRDNDisplay.m:906`)를 광고하지만 SUBMIT2 는 (구현 전) `n > OSRDN_R7B_WINDOW_WORDS`(2048)를 "count" 로 거절했다(지금 `OSRDNDisplay.m:1141` 는 MAX_WORDS 만 본다) — 스테이징 페이지 `rdnR7bVirt` 가 한 장(8 KB)이고 copyin 이 `n*4` 바이트를 **한 번에** 그 페이지로 옮겼기 때문(지금은 조각 copyin, `OSRDNDisplay.m:1171-1172`).  `osrdn_r7b.h:29-33` 의 주석(구현 전 "copyin 경로의 상한 4068")은 코드와 어긋나 있었고(K8 이 고쳐 썼다), 어떤 검사기도 광고와 수락을 대조하지 않았다.
- 실기 증거: `RDN-R7B reject2 words=4052 count`, `words=2372 count`(G4-2 §12-1).  임시 조치로 라이브러리가 min(maxWords, bytes/4) 로 자기 상한을 낮췄다(`mesa/OSRDNMesaTri.c` `triRoomWords`).
- 스테이징은 이미 조각 단위다: r7bSubmit 이 페이지에서 `CP_R7_APPEND_MAX`(508) 워드씩 `APPEND` 하고(`OSRDNDisplay.m:1247`), `cpR7Stage` 가 `cpR7Buf[4068]` 에 쌓는다(`osrdn_cp.m:2883`).  즉 **copyin 만 조각으로 바꾸면** 페이지 한 장으로 4068 까지 받는다.

### 2-2 설계
- `r7bSubmit2`: 거절 조건에서 `n > OSRDN_R7B_WINDOW_WORDS` 를 뺀다(`n > OSRDN_R7B_MAX_WORDS` 만); magic·seed·`words == 0`("words", `OSRDNDisplay.m:1145`)·nodev 검사는 **그대로**(codex 가 잡음: 빼면 널 포인터가 copyin 까지 간다).  RESET 뒤 루프: `take = min(n − k, CP_R7_APPEND_MAX)`; `copyin(words + k*4, rdnR7bVirt, take*4)` → 실패면 status EFAULT·why "copyin"·`rdnR7bDenied++`·return(스테이징에 남은 조각은 다음 제출의 RESET 이 버린다 — `cpR7Stage` 의 RESET 이 `subWords = 0`); 성공이면 `APPEND(take, rdnR7bVirt)`.  루프 뒤는 r7bSubmit 의 꼬리(quiet 결정·stage 로그·제출)와 **같은 코드**여야 하므로 그 꼬리를 `- (void)r7bRun:(osrdn_r7b_submit *)sb staged:(int)staged` 로 떼어 두 경로가 부른다(복사본 둘은 갈린다).
- **copyin 은 여전히 클레임 전**이다: 클레임은 `osrdn_mode_cp` 안(`OSRDNDisplay.m:927` 의 조건)이고 루프는 그 앞에서 끝난다.  페이지 폴트로 자는 것은 조각마다 일어날 수 있지만 클레임 없이 잔다.
- 중간 EFAULT 뒤 상태(codex 지적을 원문으로 확인): `subWords` 는 성공한 조각 수, `subDropped` 0, `cpR7Buf` 는 유효한 접두부 — 두 ioctl 경로 모두 RESET 으로 시작하므로(`osrdn_cp.m:2883` 의 RESET 이 `subWords = 0`) 다음 제출이 읽을 수 없다.  **페이지 잔여물**은 RESET 이 지우지 않지만 그 페이지는 클라이언트의 매핑 자체(창 경로 `OSRDNDisplay.m:1240` 이 같은 `rdnR7bVirt` 에서 스테이지)라 클라이언트가 어차피 자기 것으로 덮어 쓴다 — 오늘의 한 번 copyin 도 부분 실패 때 같다.  `rdnR7bSubmits` 는 꼬리에서만 증가하므로 거절은 `rdnR7bDenied` 에만 센다(오늘과 같음).  cpR7Stage 의 APPEND 상한(`osrdn_cp.m:2902`: 조각 ≤ 508, 합 ≤ 4068)이 `cpR7Buf` 넘침을 이미 막는다.
- CAPS 에 `copyinWords` 필드를 더한다(= `OSRDN_R7B_MAX_WORDS`): **광고와 수락이 한 상수**가 되고, 옛 커널은 0 을 돌려주므로 라이브러리가 "페이지 상한" 으로 읽는다(라이브러리는 커널보다 자주 바뀐다).  `osrdn_r7b_caps` 는 8 워드 → 9 워드(128 B 한계 안, `check_r7b` 가 크기를 재계산).
- 라이브러리: `triRoomWords` = copyin 경로면 min(maxWords, copyinWords ? copyinWords : bytes/4), 창 경로면 min(maxWords, bytes/4, 창 워드).  `OSRDNMesaProbeCaps` 에 `copyinWords`.
- 로그 형식(`RDN-R7B reject2 boot=%08x words=%u %s denied=%u`)은 그대로(`check_r7b` 의 형식 규칙).

### 2-3 수치 (python, `build/g44/model.py`)
4068 워드 = 508 조각 9 개(마지막 4), copyin 한 번 ≤ 2032 B; 2049 워드면 5 조각.  K8 뒤 텍스처 삼각형 190 개/배치(4068 − 60 − 2)/21 → GHOST_MANY 300 = **2 배치**(오늘 4, 부팅 8 은 5); G4-2 §5 모델의 B1+B2 수치(10k 삼각형 + 150 변화 = 53–54 배치)가 그제서야 현실이 된다.

### 2-4 검사
- `check_r7b`: 새 규칙 `r7b-submit2-chunked` — SUBMIT2 본문의 count 조건이 정확히 `n == 0UL || n > OSRDN_R7B_MAX_WORDS` 이고, `copyin(` 이 APPEND 루프 **안**에 `take * 4UL` 로 있으며, `take` 가 `CP_R7_APPEND_MAX` 로 잘리고, 두 경로가 같은 꼬리(`r7bRun:`)를 부른다; CAPS 의 `copyinWords` 가 `OSRDN_R7B_MAX_WORDS` 와 같은 상수; 변이 — 옛 페이지 조건 복귀·copyin 이 루프 밖·꼬리 복사본.
- `sim_batch`: `caps.copyinWords` 0 → 경우 I(페이지 상한), 4068 → 새 경우 J(4068 까지: 267 삼각형 = 4055 워드); 변이 — copyinWords 를 무시.
- `osrdn_r7b.h` 주석 정정, `design3`(K4 의 4068/4080 도출) 은 불변.

## 3. K7 — 검증기가 draw 마다 표면을 판정한다

### 3-1 사실
`cpR7Verify` 는 P0 가 표면 레지스터를 쓰면 지역 변수(coff·cpitch·zoff·zpitch·wh·toff·tfmt·tfil)를 덮고, P3 는 `drew = 1` 만 남기며, 판정은 `c->r7At = n` 뒤 한 번이다(`osrdn_cp.m:2774`, 판정 함수 `osrdn_cp.m:2722`).  오라클도 같다(`verify_oracle.py:209-243`).  그래서 "창 밖 COLOROFFSET → draw → 정상 값 → draw" 는 통과한다(M3h 부터).  라이브러리는 배치 안에서 표면을 바꾸지 않으니 우리 스트림엔 무관하지만, 신뢰 경계는 **클라이언트가 무엇을 보내든** 닫혀야 한다.

### 3-2 설계
- 루프 안 P3 가지에서 `drew = 1` 앞에 `cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, haveT, tfmt, haveTF, tfil)` 를 부른다 — 오늘 루프 뒤에 있는 네 검사(haveWH·색·깊이·텍스처)를 함수로 뽑은 것.  루프 뒤 판정은 **그대로 둔다**(같은 함수 호출): 마지막 draw 뒤에 바뀐 값은 아무것도 읽지 않으므로 뒤 판정은 잉여지만, 뺀 뒤 판정과 draw 판정이 갈릴 길이 없어진다.  `EMPTY`(draw 없음)는 그대로.
- 생성 검증기(`gen_r7verify.py`)는 텍스트를 잘라 오므로 라이브러리 사전검증이 **자동으로** 같은 규칙을 갖는다(`--check` 가 재생성을 요구).  `FIELDS`/`FORBIDDEN` 불변(새 함수는 `c->r7WinStart/End` 만 읽는다).
- 오라클: 같은 자리에 같은 함수.  새 경우 **U34**(색 오프셋 창 밖 → draw → 복원 → draw: SURFACE, 오늘 OK) · **U35**(TXOFFSET 창 밖 → draw → 창 안 → draw: SURFACE).  `check_r6a` 의 R7a 열이 U-경우 전부를 커널 텍스트에 돌리므로 둘이 자동으로 들어간다; `sim_verify` 도 같은 오라클 경우를 라이브러리 사본에 돌린다.
- **정확한 문장(codex 가 고침, 원문 `osrdn_cp.m:2768` 로 확인 — K7 뒤엔 `cpR7SurfacesOk` 안)**: "오늘 통과하는 스트림 중 verdict 가 바뀌는 것은 **어떤 draw 시점에 네 검사 중 하나가 실패하는 스트림뿐**" — 창 밖 표면·RE_WIDTH_HEIGHT 없음뿐 아니라 **TXOFFSET 은 썼는데 TXFORMAT 을 아직 안 쓴 채 그리는 스트림**(`haveT && !haveTF`)도 포함된다(오늘은 뒤에 오는 TXFORMAT 이 끝 판정을 살린다).  라이브러리 프롤로그는 TXOFFSET·TXFORMAT·TXFILTER 를 항상 함께 쓰고(텍스처 템플릿) flat 템플릿은 셋 다 안 쓰므로 해당 없음 — `sim_batch` 스트림이 증거.  TXFILTER 엔 존재 플래그가 없어 초기값 0 또는 마지막 값이 쓰인다(`osrdn_cp.m:2793-2795`).  **PP_CNTL 은 값 규칙(`osrdn_cp.m:2624`)으로만 판정되고 텍스처 판정을 켜고 끄지 않는다**: TXOFFSET 을 썼으면 PP_CNTL 이 텍스처를 꺼도 footprint 를 판정하고, 안 썼으면 PP_CNTL 이 켜도 판정하지 않는다 — 이 계획은 그 이상을 가정하지 않는다.
- B2 세그먼트는 draw 사이에 TXOFFSET/TXFORMAT/TXFILTER 를 바꾼다 → draw 마다 그 텍스처로 판정된다.  `sim_batch` 의 스트림 20 개가 전부 오라클을 통과해야 한다(회귀).
- `check_r5_src`: 판정 함수 호출이 P3 가지와 루프 뒤에 **각 한 번**; 변이 — P3 가지의 호출 제거(U34 가 OK 로 바뀜).

## 4. K5 — 밉맵

### 4-1 커널(이 부팅)
- 값 규칙 정밀화: `CP_R7_TXFILTER_MIP`(0x1c000, 비트 14·15·16 — 어느 필드도 아니다) 을 버리고 **미실측 필드 마스크** `CP_R7_TXFILTER_UNMEASURED` = 이방성(비트 4, `r200_reg.h:835-838` 의 8–11 모드) | 헤더가 이름 짓지 않은 비트 8–15(`r200_reg.h` 의 TXFILTER 블록 `r200_reg.h:825-874` 엔 비트 8–15 정의가 없다) | YUV(비트 20–21, `r200_reg.h:848-851`) 로 바꾼다 — 오늘보다 비트 8–13 은 엄격해지고(우리는 0 만 쓴다) 비트 2·16–19 는 열린다.  밉 모드(비트 2)는 **허용**; `MAX_MIP_LEVEL`[19:16] 은 K3 의 `cpR7TextureBytes` 가 이미 "기본 레벨이 반으로 줄어 닿을 수 있는 수" 로 묶고 창 안 판정도 한다(`osrdn_cp.m:2647`).  **LOD_BIAS 는 TXFILTER 가 아니라 PP_TXFORMAT_X 의 필드다**(`r200_reg.h:950-951` 은 TXFORMAT_X 블록 `r200_reg.h:922` 아래에 있고, `r200_tex.c:1001-1005` 가 `TEX_PP_TXFORMAT_X` 에 쓴다 — 첫 초안이 TXFILTER 로 잘못 놓았고 codex 가 잡았다); 우리 텍스처 템플릿은 TXFORMAT_X 에 0 을 쓰므로 bias 0, 이방성 0(1:1).
- 오라클 거울: `TXFILTER_MIP_MASK` → `TXFILTER_ANISO_MASK` + YUV/LOD 마스크, U14(밉 필터 = 거절)를 **U14(이방성 = 거절)** 로 바꾸고 **U36**(밉 모드 NEAREST_MIP_NEAREST + MAX_MIP_LEVEL 3, 64×64 → OK)·**U37**(MAX_MIP_LEVEL 7 인 64×64 = 7 > 6 → SURFACE: 이미 K3 규칙)·**U38**(LOD_BIAS 비트 → P0_VALUE).
- python 으로 확인한 것(§1 K5 필드): 네 밉 모드 0x4·0x6·0xc·0xe 는 전부 비트 2, 이방성 넷은 비트 4, 옛 마스크는 비트 14·15·16.

### 4-2 라이브러리(재부팅 없이 반복 가능, 커널 뒤)
- **자격검증 프로브 먼저**(Matrox M12 의 1 단계): `ghostprobe_v18` `GHOST_MIP` — 128×128 RGBA 텍스처, 레벨 i 를 **단색 i** 로(8 레벨, 1×1 까지) r200 배치대로 아레나에 올리고(레벨 행 (폭×4+31)&~31, 시작 32 B 정렬 — K3 의 계산과 같은 python 함수), TXFILTER = NEAREST | MIN NEAREST_MIP_NEAREST | MAX_MIP_LEVEL 7, 사각형 8 개: 레벨 0–4 는 128·64·32·16·8 px 에 텍스처 좌표 0..1, 레벨 5–7 은 **8×8 px 에 좌표 0..2·0..4·0..8**(λ 는 그대로 5·6·7 이면서 표본이 64 개 — 1·2·4 px 사각형은 표본 1–16 개라 약하다는 codex 지적 채택).  λ = log2(텍셀/픽셀) 이 정수라 Mesa 의 NEAREST 규칙(`texture.c:391-397`: (int)(λ + 0.5)) 과 하드웨어 모두 경계(i ± 0.5)에서 0.5 떨어져 있다.  판정: 사각형 i 의 지배색(≥ 95 %)이 레벨 i 의 색 — 하드웨어가 r200 배치의 오프셋에서 레벨을 읽는지, 8 미만 폭의 행 반올림(R6h XF)이 맞는지, 클램프(MAX_MIP_LEVEL 4 인 두 번째 장면에서 5·6·7 px 사각형이 레벨 4 색)가 맞는지를 그림이 말한다.  stock 도 같은 장면(Mesa 의 λ+0.5 내림)이라 대조군이 된다.  프로브가 실패하면 그 뒤는 하지 않는다(어느 레벨이 어디서 읽혔는지가 다음 계획의 입력).
- 프로브 통과 뒤: 상주 기록이 **체인 전체를 한 블록**으로(`osrdn_texarena_alloc(chain bytes)`, 바이트는 `cpR7TextureBytes` 와 같은 python 생성 함수 — 32 MiB 아레나에 pak 상한 21.3 MiB + 4/3 은 이미 들어 있다, 여유 10.7 MiB), 레벨마다 `osrdn_tex_upload_at` 로 오프셋에 업로드(행 반올림을 업로드가 맡는다: 폭 < 8 인 레벨은 32 B 행), TexSubImage 는 그 레벨만 무효화; 분류기가 네 밉 MIN 필터를 받되 `to->Complete` 이고 모든 레벨이 `osrdnTexUsable` 일 때만; 프롤로그 TXFILTER 슬롯에 MIN 모드 + MAX_MIP_LEVEL = 레벨 수 − 1(`gen_tri_prologue.py` 가 r200_reg.h 에서 상수를 끌어온다); `osrdn_tri_texture_set` 에 레벨 수.  손잡이 `RDNMesaMip=0` 이면 밉 필터를 소프트웨어로(오늘 모양).
- 수혜자는 오늘 포트가 아니다(VID_Init 이 LINEAR 강제, G4 계획 §1 표) — q2-state-matrix 의 mipmap 팔(21 중 1)과 Matrox 동등성.  timedemo 는 이것과 무관하게 K8 뒤 가능해진다(`timedemo-only-when-accel-is-complete` 의 "온전함" 은 유실·폴백 0 이지 밉이 아니다 — 사용자 확인 필요).

## 5. 호스트 검사 (코딩 전에 정한다)

| 검사 | 무엇을 |
|---|---|
| `check_r7b` | K8 규칙 + 변이 3, CAPS 9 워드 크기 재계산, `copyinWords` == MAX_WORDS |
| `check_r5_src` | K7 판정 함수 호출 두 자리, K5 값 규칙 앵커 정밀화(ANISO/YUV/LOD), 변이 각각 |
| `verify_oracle --self-test` + `check_r6a` R7a 열 | U34·U35·U36·U37·U38, U14 재정의; 커널 텍스트 = 오라클 |
| `gen_r7verify --check`, `sim_verify` | 라이브러리 사본 재생성·같은 판정 |
| `sim_batch` | 경우 J(copyinWords 4068), 20+ 스트림 전부 오라클(K7 회귀) |
| `build/g44/model.py` | §2-3·§4 수치(조각 수, 190/배치, 체인 바이트, 프로브 사각형 크기와 λ) |
| `hostcheck-r2b0`, `check-all` | 마지막 한 번 |

## 6. 부팅 계획 (러너 = 판정)

1. 호스트: §5 전부 PASS → `pack_r2b0.py` → 타깃 `target-build-r2b0.sh` → `nm -u` → `target-install-r2b0.sh closed=yes fresh live` → 라이브러리 `target-build-mesa.sh <runid>`(copyinWords 읽는 판) → **재부팅 요청**.
2. 러너 `build/g44/run_g44.sh`(내 gcdsd; `LIBRUN`·`BUILD`): 스탬프 확인 → CP 기동 → `ghostprobe_v18` 빌드(가속·stock) → `GHOST_MANY`(K8: **2 배치**, drawn 300, lost 0) → `GHOST_SEG`·`GHOST_ORDER`(G4-2 회귀) → `GHOST_MIP` 두 장면(K5 프로브) → UV·TEXBIG·ALPHA·q2 회귀 → `judge_texbig`·`judge_g43`·`judge_g42`(MANY 기대치는 `copyinWords` 로 계산)·`judge_g44`(MIP).
3. K7 은 실기 장면이 없다(우리 스트림은 원래 통과): 커널 로그에 `refused` 0 과 회귀 PASS 가 증거, 규칙 자체는 호스트(U34/U35)가 증명.
4. 러너 = 판정 절차: 로그 이름은 러너가 쓴 그대로.

## 7. 위험

- K8: 조각 copyin 중간 EFAULT 는 스테이징을 반쯤 채운 채 돌아온다 — RESET 이 다음 제출 첫 줄이라 안전하지만, `subWords` 가 남아 있는 상태에서 다른 경로(SUBMIT 창 경로)가 APPEND 만 부르는 일은 없는지 `check_r7b` 로 못 박는다(두 경로 모두 RESET 으로 시작).
- K7: 오늘 통과하던 클라이언트 스트림이 거절되는 경우는 "중간 draw 때 표면이 창 밖" 뿐 — 그런 스트림을 만드는 코드는 이 프로젝트에 없다(`sim_batch` 20 스트림이 증거).
- K5: 하드웨어가 r200 배치와 다르게 레벨을 읽으면 프로브가 잡는다 — 그때 **라이브러리 밉은 안 켜고**(손잡이 기본 0 으로) 다음 계획의 입력으로 남긴다.  커널 값 규칙 완화는 라이브러리가 안 쓰면 아무 스트림도 안 바뀐다.
- 셋을 한 부팅에: 커널 diff 는 K8(핸들러 루프 + CAPS 한 워드)·K7(함수 하나 + 호출 두 곳)·K5(마스크 셋) — 각각 호스트 규칙·변이가 있고 서로 다른 파일 영역이라 갈라 볼 수 있다.

## 8. codex 교차검토 판정표 (2026-09-27, 주장 하나에 호출 하나, 전부 원문으로 재확인)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| K8: 거절 조건에서 `words == 0` 검사를 빼면 널 포인터가 copyin 까지 간다 | `OSRDNDisplay.m:1145` 을 열어 `else if (sb->words == 0UL)` 확인 | ✅채택 — §2-2 에 "그대로" 명시 |
| K8: 조각 copyin 이 페이지 앞을 덮어 성공 뒤 페이지엔 마지막 조각만 남는다 | 설계상 사실; 페이지는 클라이언트 매핑(창 경로 `OSRDNDisplay.m:1240` 도 `rdnR7bVirt`) — 커널 스트림은 `cpR7Buf` | ⚖️부분채택 — 무해, §2-2 에 기록 |
| K8: EFAULT 뒤 `subWords` 는 접두부, `subDropped` 0, 두 경로 모두 RESET 으로 시작하므로 재해석 없음; `rdnR7bSubmits` 는 꼬리에서만 증가 | `osrdn_cp.m:2883-2911` RESET/APPEND, `OSRDNDisplay.m:1288` | ✅사실 — §2-2 |
| K8: cpR7Stage 의 상한(조각 ≤ 508, 합 ≤ 4068)이 `cpR7Buf` 넘침을 막는다 | `osrdn_cp.m:2902`·`osrdn_cp.m:2907` | ✅사실 |
| K7: (b) 의 문장이 틀렸다 — `haveT && !haveTF`(TXOFFSET 뒤 TXFORMAT 전에 draw) 도 새로 거절된다 | `osrdn_cp.m:2835-2840`·`osrdn_cp.m:2768` | ✅채택 — §3-2 문장 교체, 라이브러리 무관 확인 |
| K7: TXFILTER 엔 존재 플래그가 없다; PP_CNTL 은 값 규칙뿐이고 텍스처 판정을 켜고 끄지 않는다 | `osrdn_cp.m:2793-2795`, `osrdn_cp.m:2624`, 대입 사슬에 PP_CNTL 없음 | ✅사실 — §3-2 에 기록 |
| K5-A: MIN 필드 [4:1]·밉 모드 = 비트 2·이방성 = 비트 4·MAX_MIP [19:16]·YUV 20–21 은 맞고, **LOD_BIAS 는 TXFILTER 가 아니라 TXFORMAT_X** | `r200_reg.h:825-874` 블록 경계(다음 레지스터 `r200_reg.h:875`), `r200_reg.h:922` TXFORMAT_X 블록 안의 950-951, `r200_tex.c:1001-1005` | ✅채택 — 내 오류, §4-1 교체 |
| K5-B: 크기 식은 `w * Height * Depth`; 2D 면 Depth 1 이라 계획과 같다 | `r200_texstate.c:272-274` | ⚖️사실이나 행동 불변(2D 만) |
| K5-C: λ 산술과 Mesa 규칙은 맞다; 1 px 사각형은 표본 1 개라 약하다 — 8×8 에 좌표 0..8 로 | `texture.c:391-397`; 표본 수 1·4·16 vs 64 | ✅채택 — §4-2 프로브 교체 |
| K5-C: MAX_ANISO 0 = 1:1, bias 0 은 0; 프로브가 둘을 명시적으로 초기화해야 | 텍스처 템플릿이 TXFORMAT_X 0·TXFILTER 이방성 0 을 쓴다(`OSRDNMesaTriTable.h` 텍스처 프롤로그 0xb02 = 0) | ✅사실 — 템플릿이 이미 한다 |

## 9. 구현 기록 (2026-09-27, 호스트 검사까지; 드라이버 스탬프 `4d2ee38a`/runid 790467758)

**K8**: `OSRDNDisplay.m` — `r7bSubmit2` 가 RESET 뒤 508 워드 조각마다 `copyin` → `APPEND`(중간 EFAULT 는 "copyin" 거절), 두 경로의 꼬리를 `r7bRun:words:staged:` 하나로(`OSRDNDisplay.h` 에 선언); `osrdn_r7b.h` **버전 2**(SUBMIT2 가 maxWords 를 통째로 받는 계약; 프로브는 버전을 정확히 요구하므로 옛 커널에선 소프트웨어로 물러선다), MAX_WORDS 주석 정정.  CAPS 필드는 더하지 않았다(구조체 크기 = ioctl 번호라 파급이 크고, 버전이 같은 말을 한다).  라이브러리 `triRoomWords`: copyin 경로 = maxWords, 창 경로 = 매핑.  검사: `check_r7b` 규칙 `r7b-submit2-chunked`(count 조건·루프 안 copyin·조각 상한·페이지에서 APPEND·EFAULT break·공용 꼬리 하나) + 변이 3, `check_r5_src` g3b 규칙을 `r7bRun:` 으로, `sim_batch` 경우 I 반전(copyin 은 페이지에 안 묶임) + 변이 2, `judge_g42` 기대치는 헤더 버전으로 계산(2 면 4068 → MANY 2 배치).

**K7**: `osrdn_cp.m` — `cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF)` 를 뽑아 P3 가지(`drew = 1` 앞)와 루프 뒤에서 호출; 오라클 `surfaces_ok` 거울 + U34/U35 + 자기시험 변이; 생성 검증기 재생성(`--check`), `check_r5_src` 규칙 `g44-k7-per-draw`(호출 2 회·순서·헬퍼 내용) + 변이 2, `sim_verify` 변이 갱신(클립 검사는 헬퍼 안) + K7 변이.

**K5 커널**: `CP_R7_TXFILTER_MIP`(0x1c000) → `CP_R7_TXFILTER_UNMEASURED`(0x0030ff10 = 이방성 비트 4 | 미정의 비트 8–15 | YUV 20–21); 오라클 `TXFILTER_UNMEASURED_MASK`, U14 를 이방성으로, U36(64² 4 레벨 OK)·U37(8 레벨 = 하나 더 → SURFACE)·U38(YUV → P0_VALUE).

**K5 라이브러리(프로브 모드, `RDNMesaMip=1` 일 때만)**: 생성 표에 밉 MIN 모드 넷·MAX_MIP 필드·`OSRDN_TRI_MIN_*` 코드(GL 이름; `triMinField` 가 r200SetTexFilter 의 대응으로 필드에 놓는다 — NEAREST_MIPMAP_LINEAR ↔ LINEAR_MIP_NEAREST 교차 포함); `osrdn_tri_texture_set(off, w, h, mag, minCode, levels)`, TXFILTER 슬롯 = MIN 필드 | (levels − 1) << 16, 밉 코드에 레벨 1 은 프롤로그 거절; 배치 키에 minCode·levels; `osrdn_texarena_chain`(r200 배치의 레벨 오프셋·바이트 = 커널 `cpR7TextureBytes` = 오라클 `texture_bytes`; `sim_arena` 경우 14 + 변이 3 — 레벨 정렬 변이는 관측 불가라 뺐다: 행이 이미 32 의 배수); `osrdn_tex_upload_level`(행 간격 인자, 폭 1 부터; `upload_at` 은 그 특수형); 분류기 `classMinOk`(밉 넷은 손잡이 + `to->Complete`), `osrdn_class_min_code`; 훅 `osrdnTexResident(to, org, w, h, levels)` 가 체인을 한 블록으로 상주(각 레벨 크기·형식 검사, 레벨마다 업로드), `levels = M + 1`, 계수 `texChains`.  `check_hook` 앵커·UpdateState 대입 목록 갱신.  `check_compile`(훅 단위 Mesa src 포함)·`check_hook`·`sim_batch`·`sim_pack`·`check_units`·`sim_arena`·생성기 자기시험·`hostcheck-r2b0` PASS.

**설치**: 드라이버 `4d2ee38a`/runid 790467758(OSRDNBUILD PASS 심볼 21·`check_reloc_r2b0` PASS·INSTALL DONE, 다음 부팅부터), 라이브러리 **790467902**(RDNMESA PASS·`judge_m1b` PASS; 버전 2 헤더).  부팅 9 절차: 사용자 재부팅 → NFS 마운트 → 내 gcdsd → `LIBRUN=790467902 BUILD=4d2ee38a CAPSRUN=790467758 bash build/g44/run_g44.sh` → 판정 넷 PASS.

**실기 도구**: `build/g44/ghostprobe_v18.c`(`GHOST_MIP` 두 장면: 픽셀 단위 직교 투영, 레벨별 단색 8 레벨, 사각형 128·64·32·16·8 px 좌표 0..1 + 8 px 좌표 0..2/0..4/0..8, 장면 B 는 `GL_TEXTURE_MAX_LEVEL` 4), `build/g44/judge_g44.py`(사각형마다 지배색 ≥ 95 % = 기대 레벨 색, 카드·stock 둘 다; 어긋나면 어느 레벨 색인지 이름 짓는다), `build/g44/run_g44.sh`(`CAPSRUN` 으로 버전 2 osrdncaps; MANY·SEG·ORDER·MIP + 회귀 + 판정 넷).

## 10. 부팅 9 결과 (2026-09-27, 드라이버 `4d2ee38a`·라이브러리 790467902·osrdncaps 790467758, 내 gcdsd; `build/g44/run.log`, MIP 재실행 `mip.log`)

| 항목 | 실측 | 판정 |
|---|---|---|
| K8 | GHOST_MANY 300 삼각형 = **2 배치**, drawn 300, 거절 0(부팅 8: 5, G4-2: 4); SEG 3 배치·ORDER 4 배치 | judge_g42 PASS |
| K7 | 회귀 전부 통과(우리 스트림은 원래 통과; 규칙은 U34/U35·sim_verify 가 호스트에서 증명) | — |
| K5 프로브 장면 A | 카드: 사각형 0–7 이 **레벨 0–7 의 색 100 %**(λ = 0…7) — r200 배치의 오프셋에서 레벨을 읽고, 폭 4·2·1 의 32 B 행도 맞다 | judge_g44 PASS |
| K5 프로브 장면 B(`GL_TEXTURE_MAX_LEVEL` 4) | 카드: 사각형 5–7 이 레벨 4 의 색(클램프) | PASS |
| stock(대조군) | 사각형 0–4·7 은 카드와 같고 **5·6 은 한 레벨 높다**(0..2/0..4 좌표) — Mesa 3.4.2 `compute_lambda` 가 ρ² = r1 + r2(두 축 제곱합, `triangle.c:1061-1076` "used to be MAX2")를 쓰는 것이 후보 원인이지만 0–4 가 안 밀리는 이유는 **미해결**로 남긴다; stock 은 배치의 대조군이지 LOD 의 판정자가 아니므로 judge 가 한 레벨 위를 허용 | 기록 |
| 회귀 | UV·TEXBIG·ALPHA·q2 19/21·SEG·ORDER 그대로 | judge_texbig·judge_g43 PASS |

**첫 실행의 프로브 결함**: 사각형을 90 px 간격 한 줄에 놓아 128 px 사각형 위에 64 px 사각형이 겹쳤다(카드·stock 똑같이 85 %) → 두 줄 150 px 간격으로 고쳐 재실행.

**결론**: 커널 K8·K7·K5 는 닫혔다.  밉 라이브러리 경로는 프로브가 통과했으므로 다음 단계(`RDNMesaMip` 기본을 켜고 q2 의 mipmap 팔·회귀 장면으로 확인)는 **재부팅 없이** 진행할 수 있다.

**부팅 뒤에 드러난 검사기 낡음(2026-09-27)**: 재부팅을 check-all 결과 전에 요청했다.  이후 check-all 이 `sim_class`(변이 앵커), `check_r7b`(생성 표 — 오라클 U14 재정의·U34–U38), `sim_r6`(클립 앵커)를 잡았고 전부 고쳤다.  드라이버 본체(`osrdn_cp.m`·`OSRDNDisplay.m`)는 영향 없음; 다만 설치된 tar 의 시험 도구 `rdnr7sub` 는 U34–U38 을 모른다(R7a 경우를 실기에서 돌릴 일이 생기면 다음 pack 에서 갱신).
