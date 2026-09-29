# G4-2 — 배치가 VB 브래킷을 넘고, 상태 변화가 배치 안에 들어간다 (계획, 코딩 전, codex 교차검토 대상, 2026-09-27)

부팅 8 이 잰 것(`docs/G4_3_KERNEL_PLAN.md` 5-1): 배치를 자르는 것은 4068 워드 상한이 아니라 **Mesa 의 정점 버퍼**다 — 216 정점(`config.h:181` `VB_MAX`) = 72 삼각형마다 `RenderFinish` 가 오고 훅이 거기서 배치를 닫는다(`OSRDNMesaHook.c:1429` → `osrdnFlushBatch`).  300 삼각형 = 5 배치.  제출 한 번은 ≈ 480 µs(`model.out:16`), 10 000 tri/프레임이면 139 배치 ≈ 67 ms → 15 fps 상한 — 상태 변화를 세지 않고도 그렇다.  G4-2 는 그 둘을 푼다: **(B1)** 배치가 브래킷을 넘어 워드 상한까지 산다, **(B2)** 상태 변화가 배치를 닫지 않고 세그먼트로 들어간다.  둘 다 커널 변경이 없다(재부팅 없음).

## 0. 왜 지금 그렇게 돼 있는가 (읽은 것)

- 훅은 `RenderFinish` 에서 반드시 비운다(`OSRDNMesaHook.c:1429-1441`).  이유는 **재생 약속**: 제출이 거절되면 훅이 들고 있던 **VB 인덱스**(`osrdnPend.v[i]`, `OSRDNMesaHook.c:444-608`)로 Mesa 의 소프트웨어 삼각형 함수를 다시 부른다 — 인덱스는 브래킷 안에서만 살아 있다(`vbrender.c:699-729`: RenderStart → 원시 루프 → RenderFinish; `vbindirect.c:313-336` 도 같은 모양).  Matrox 도 같은 이유로 "배치는 브래킷을 넘지 않는다" 고 못 박았다(`OpenStepMGAMesaHook.c:775-812`: 인덱스·클립 임시 정점·멀티패스 세 가지).
- Tri 의 배치는 프롤로그 하나 + **draw 패킷 하나**(헤더 두 워드의 정점 수를 flush 때 다시 씀, `OSRDNMesaTri.c:719-724`): 상태가 다르면 `osrdn_tri_batch_joins` 가 0 을 돌려주고 배치가 닫힌다(`OSRDNMesaTri.c:1394-1420`).
- 상태 변화가 잦은 것은 GLQuake 의 본성이다: 월드 표면마다 `glBindTexture`, 라이트맵 패스마다 블렌드 on/off(`docs/G4_GLQUAKE_PLAN.md` 1 표).  모델은 상태 변화 150/프레임에서 상한 14.4 fps(`model.out:20`).

## 1. 참조 (항목마다 연 것)

| 물음 | 참조 | 무엇을 가져오는가 |
|---|---|---|
| 명령 버퍼 안의 상태 변화 | r200 DRI: `r200_cmdbuf.c:146` `r200EmitState` — 더러워진 상태 원자를 **DRM `RADEON_CMD_PACKET` 레코드**(커널이 레지스터 그룹으로 해석, `r200_state_init.c:75-81`)로 같은 명령 버퍼에 복사하고(`r200_cmdbuf.c:185-195`), draw 패킷은 그 직후(`r200_cmdbuf.c:216-230`: `r200EmitVbufPrim` 안에서 EmitState → PACKET3); 사이에 대기 없음; 텍스처 원자도 같은 경로이고 **텍스처 캐시 무효화 명령은 없다** — 대신 항상 dirty 로 다시 보낸다(`r200_texstate.c:1180-1183`); 정점은 `R200_FIREVERTICES`(`r200_ioctl.h:162-167`) 때 나간다; 버퍼가 차면 `r200FlushCmdBuf`(`r200_ioctl.c:174`) | 세그먼트 = "바뀐 레지스터 쌍 + 새 draw 패킷", 레지스터 쓰기와 패킷 사이에 WAIT 없음(codex 가 "raw PACKET0" 표현을 바로잡음: DRM 레코드지만 하드웨어가 받는 것은 레지스터 쓰기다) |
| 소프트웨어가 표면을 만지기 전 | r200: `r200_span.c:239-246` `r200SpanRenderStart` = FIREVERTICES + idle 대기; swrast 의 span 접근 앞뒤 훅 | **소프트웨어 원시·읽기 앞에서 flush** 가 참조의 규칙 |
| 브래킷 | Mesa 3.4.2 `vbrender.c:699-729`(VB 렌더), `vbindirect.c:313-336`(indirect); 멀티패스는 `MultipassFunc`(`dd.h:874`) | 브래킷은 VB 하나; 멀티패스 컨텍스트는 배치하지 않는다(Matrox 와 같이) |
| 원시 종류 | `vbrender.c:706-707` `VB->Primitive[i]`(GL enum: `gl.h:140` POINTS 0 … `gl.h:149` POLYGON 9) — 그러나 **indirect 경로는 RenderStart 앞에 `ctx->VB` 를 CVA 의 VB 로 바꾸고 원시는 인자 VB 에서 읽는다**(`vbindirect.c:350-376`), 그리고 `RENDER_START`(`types.h:2156-2160`)는 readpix·drawpix·bitmap·copypix·clear 의 소프트웨어 구간에서도 불린다(`readpix.c:771-776`, `copypix.c:644-649`, `drawpix.c:821-828`, `bitmap.c:65`, `buffers.c:279-280`) — RenderStart 에서 `ctx->VB` 를 훑는 첫 설계는 **틀렸다**(codex 지적, 원문 확인).  사각형은 `basic_quad`(`quads.c:48-54`) → 우리 TriangleFunc 두 번 | 점·선은 **함수 래핑**으로(§3 F3), 픽셀 명령은 훅으로(F7) |
| 점·선·픽셀 경로 | OSMesa: `osmesa.c:2009-2011` PointsFunc NULL(Mesa 가 자기 점 함수를 고름, PB → `WriteRGBAPixels`), LineFunc = OSMesa 직접 쓰기(`osmesa.c:1601-1610`), TriangleFunc; **Mesa 는 드라이버가 둔 PointsFunc/LineFunc 를 그대로 둔다**(`points.c:1333-1346`, `lines.c:1071-1084`: "Device driver will draw") 그리고 선택은 `Driver.UpdateState` 뒤에 한다(`state.c:1111`, `state.c:1122-1124`) — 삼각형과 같은 가드; `dd.h:462` DrawPixels·`dd.h:473` ReadPixels·`dd.h:483` CopyPixels·`dd.h:492` Bitmap 훅(GL_FALSE 면 Mesa 가 소프트웨어로: 훅이 먼저 불린다 `readpix.c:771-776`, `drawpix.c:821-828`; CopyPixels 는 RENDER_START 뒤에 훅 `copypix.c:644-649` 이지만 복사 자체보다는 앞이다), `dd.h:334` Flush | 픽셀 명령은 훅으로 flush 뒤 GL_FALSE; 점·선은 UpdateState 에서 삼각형처럼 "NULL → Mesa 의 선택 → 저장 → 래퍼" |
| 사전검증 | Matrox `OpenStepMGAMesaHook.h:313` `Prevalidated` — ioctl 전에 프로세스 안에서 검증기를 돌려 거절될 배치를 소프트웨어로 | 재생 약속을 브래킷 밖에서도 지키는 길 |
| 검증기의 다중 패킷 | `verify_oracle.py:286-310`: draw 마다 `SE_VTX_FMT` 로 정점 폭을 다시 세고 `drew` 만 기록 — 한 스트림에 draw 여럿·형식 변경 허용; R6l 이 "한 제출의 패킷 여럿" 을 실측 | 세그먼트는 검증기 변경 없이 통과 |

## 2. B0 — 사전검증: 재생 약속을 옮겨 놓는다

**문제**: 브래킷을 넘긴 배치가 flush 에서 거절되면 인덱스가 죽어 재생할 수 없다.  **답**: 거절될 스트림은 **브래킷이 끝나기 전에** 안다 — 검증기를 프로세스 안에서 돌린다.

- 커널의 `cpR7Verify`·`cpR7ValueAllowed`·`cpR7TextureFits`·`cpR7SurfaceFits`·`cpR7VertexWords` 를 **공유 단위** `OSRDNDisplay/OSRDNDisplay_reloc.tproj/osrdn_r7verify.c/.h` 로 뽑는다: `osrdn_cp_state` 대신 `(winStart, winEnd, defC, defZ, defPitch)` 와 결과 `(why, at, word)` 를 인자로.  커널은 그것을 부르고(동작 불변: `sim_r5` 32 경우·`check_r5_src` 규칙 그대로), 라이브러리는 같은 파일을 컴파일한다(`check_units`: 새 단위·`hostcheck-r2b0` 에 포함).  **소스가 하나**라 등가성은 정의로 성립하고, `sim_verify.py` 가 라이브러리 쪽 빌드로 오라클 경우 32 개를 돌려 커널과 같은 판정을 내는지 본다.
- 훅의 `RenderFinish`: 배치가 열려 있으면 `osrdn_tri_batch_verify()`(공유 검증기, 현재 스트림 + 임시 꼬리) → **거절이면 지금 flush**(인덱스가 살아 있으므로 재생 가능, 계수 `prevalidateRefused`), 통과면 열어 둔다.  flush 때도 한 번 더 돈다(싸다: 워드 수에 선형).
- 약속의 새 문장: **검증기가 이름 붙일 수 있는 거절은 삼각형을 하나도 잃지 않는다; 정지(EIO)는 배치를 잃고 `lostAtFlush` 에 세인다**(K1 뒤 정지는 16 라운드 뒤에만 온다).  Matrox 의 `Prevalidated` 와 같은 자리.

**구현 결정(2026-09-27, 계획과 다른 점)**: 커널 소스를 옮기지 **않았다**.  라이브러리 쪽 검증기 `mesa/OSRDNMesaVerify.c/.h` 는 `tools/mesa/gen_r7verify.py` 가 **커널 텍스트에서 생성**한다 — `osrdn_cp.m` 의 R7a 절(`cpR7Verify` 와 그 보조 함수)·`cpR7Allow` 표·`CP_R7`/`C_*` 마스크 블록을 잘라 `osrdn_cp_state` 를 `osrdn_r7v` 로 바꿔 쓰고, 입구는 `osrdn_r7_verify(winStart, winEnd, defC, defZ, defPitch, w, n, &at, &word)` 하나.  이유: 설치된 커널(1beb2ed9)을 건드리지 않는 것이 가장 안전하고, 등가성은 `gen_r7verify.py --check`(생성물이 현재 커널 텍스트와 같은지) + `sim_verify.py`(오라클 32 경우 + 긴 스트림, 변이 6 개 전부 검출) 로 매 check-all 마다 다시 증명된다.  커널 쪽 `sim_r5`·`check_r5_src` 는 손대지 않았다.  검증 인자는 커널 호출 자리(`osrdn_cp.m` 의 `cpR7Verify(c, cpR7Buf, c->subWords, c->winStart + cpR6ColorOff(cs), c->winStart + cpR6DepthOff(cs), CP_R6_PITCH)`)를 그대로 따른다: `defC = winStart + 0x3c000`, `defZ = winStart + 0`, `defPitch = 64`, `winEnd` 는 라이브러리가 매핑한 바이트 수로 보수적으로.

## 3. B1 — 배치가 브래킷을 넘는다: flush 지점의 완전한 목록

배치는 다음 중 하나가 올 때까지 산다.  각 줄은 훅 하나·규칙 하나(`check_hook`)·시뮬 경우 하나다.

| # | 사건 | 왜 flush 인가 | 어디서 |
|---|---|---|---|
| F1 | 워드 상한(`caps->maxWords` − 12 − 다음 세그먼트 비용) | 스트림이 더 못 큰다 | Tri `osrdn_tri_batch_reserve` |
| F2 | RenderFinish 에서 사전검증 거절 | 재생 가능한 마지막 순간 | 훅 RenderFinish |
| F3 | 소프트웨어 점·선 함수가 불리기 직전 | OSMesa 의 선은 콜백 없이(`osmesa.c:1601-1610`), 점은 PB 로 표면을 직접 쓴다 — 카드 삼각형이 그 아래 깔려야 한다.  RenderStart 에서 VB 를 훑는 방법은 indirect 경로·픽셀 명령의 RENDER_START 에서 엉뚱한 VB 를 읽으므로 쓰지 않는다(§1) | 훅 UpdateState: `PointsFunc`/`LineFunc` 를 NULL → `gl_set_point_function`/`gl_set_line_function` → 저장 → 래퍼(flush 뒤 저장된 함수 호출), 삼각형의 M1d 설치와 같은 네 걸음; Mesa 는 non-NULL 을 그대로 둔다(`points.c:1333-1346`, `lines.c:1071-1084`) |
| F4 | 위임 삼각형(분류기는 받았으나 Tri 가 거절: texProjective·notBound·refused) | 지금은 브래킷 안에서도 순서가 뒤집힌다(`OSRDNMesaHook.c:1106-1112` 위임 앞에 flush 없음) — 함께 고친다 | 훅 `osrdnHookTriangle` 위임 가지 |
| F5 | 분류기가 거절한 상태로의 UpdateState(leave) | 다음 원시는 전부 소프트웨어 | 훅 UpdateState |
| F6 | Clear · Finish(M3g 되복사) · **Flush(새 훅)** | 표면을 읽거나 덮는다 | 훅 |
| F7 | ReadPixels · CopyPixels · DrawPixels · Bitmap(새 훅: flush 뒤 GL_FALSE) | Mesa 가 span 으로 표면을 읽고 쓴다 | 훅 |
| F8 | 텍셀 업로드(`osrdnTexResident` 의 `osrdn_tex_upload_at` 앞) · 상주 기록 폐기(`osrdnTexDrop` 의 `osrdn_texarena_free` 앞) | 열린 배치가 그 텍셀·그 블록을 읽는다; 다음 alloc 이 블록을 재사용할 수 있다 | 훅 |
| F9 | 표면 해제·재잡기(`OpenStepMesaAccelBuffer`/`ReleaseBuffer`), MakeCurrent | 표면이 바뀐다 | 훅 |
| F10 | `MultipassFunc != 0` 인 컨텍스트 | 브래킷 안에서 루프가 반복된다 | 배치 자체를 끈다(Matrox 규칙) |

브래킷 밖의 소프트웨어 쓰기로 남는 것: 없음 — OSMesa 의 직접 쓰기(선·깊이 삼각형)는 원시 경로에만 있고(Matrox 주석 `OpenStepMGAMesaHook.c:3775-3790`, 우리 `osmesa.c:2010-2011`), 원시 경로는 F3(점·선 래퍼)·F4(위임 삼각형)·사각형→삼각형(`quads.c:48-54`)이 막는다; 픽셀 명령은 F7, 지우기는 F6.

## 4. B2 — 세그먼트: 상태 변화를 배치 안에

- 배치 키를 둘로 나눈다: **표면**(colourByteOff·pitch·width·height: 바뀌면 배치를 닫는다 — 검증기가 표면을 마지막 값으로 판정하므로 스트림 안에서 바꾸지 않는다) 과 **상태**(smooth·blend·tex·depth·alpha·현재 텍스처: 바뀌면 **세그먼트**).
- Tri 의 배치는 `triSeg[k] = { hdrAt, tris, vw }` 목록(상한 `OSRDN_TRI_SEGS` 256; 넘치면 F1 처럼 flush) 과 `triLast[reg]` = 이 스트림이 그 레지스터에 마지막으로 쓴 값(프롤로그 등록 순서의 작은 배열, 레지스터 ≤ 48 개).  새 상태의 프롤로그를 `triPrologue` 로 **스크래치에** 만든 뒤 쌍마다 `triLast` 와 비교해 **다른 쌍만** 덧붙이고, 새 헤더 두 워드를 놓는다(정점 폭이 바뀌면 `SE_VTX_FMT_0/1` 쌍이 그 차이 안에 들어온다).  flush 는 세그먼트마다 헤더를 다시 쓴다.  비용: 상태 변화 하나 = 바뀐 쌍 × 2 + 2 워드(최악 = 프롤로그 전부 58 + 2; 텍스처만 바뀌면 TXOFFSET·TXFORMAT·TXFILTER·TXSIZE·TXPITCH 10 + 2 = 12 워드), 제출 하나(480 µs) 대신.
- 참조가 그렇게 한다: r200 은 상태 원자를 정점 앞에 raw 레지스터 쓰기로 넣고 사이에 대기가 없다(`r200_cmdbuf.c:146`).  검증기는 패킷마다 형식을 다시 센다(§1).  하드웨어는 R6l 이 한 제출의 패킷 여럿을 쟀다.
- 재생: B0 뒤 flush 실패는 정지뿐이라 세그먼트별 상태 복원 재생(Matrox 의 `pendSrc`)은 **만들지 않는다** — 정지는 잃고 센다.
- **K7(커널, 다음 부팅 — codex 가 찾고 원문으로 확인한 구멍)**: 검증기는 표면 레지스터를 루프 안에서 마지막 값으로 덮고 **루프 뒤에 한 번** 판정한다(`osrdn_cp.m:2758-2770`, 오라클 `verify_oracle.py:209-243`).  그래서 "창 밖 COLOROFFSET → draw → 정상 값으로 복원" 스트림은 통과한다(M3h 부터 있던 구멍; 라이브러리는 배치 안에서 표면을 바꾸지 않으므로 우리 스트림은 무관하지만 신뢰 경계가 닫히지 않는다).  고침: 각 PACKET3 에서 그 시점의 coff·cpitch·zoff·zpitch·wh·toff/tfmt/tfil 로 판정(커널 + 오라클 + 경우 U34 = 중간에 창 밖 오프셋으로 그리고 복원 → SURFACE).  K5 밉맵과 같은 부팅.

## 5. 수치 (python: `build/g4/model.py` `g42_model`, 출력 `model.out:7-12`)

배치 하나 482 µs, VB 72 삼각형, 4068 워드 = 텍스처 삼각형 190 개.  세 체제를 같은 비용으로 계산했다(상태 변화 하나의 세그먼트 비용은 12 워드(텍스처 교체: 쌍 5 + 헤더 2)에서 60 워드(프롤로그 전부 + 헤더) 사이):

| 프레임 | 오늘(VB 마다 + 변화마다 배치) | B1 만(워드 상한, 변화마다 배치) | B1+B2(변화는 워드로) |
|---|---|---|---|
| 5 000 tri, 변화 0 | 70 배치 33.7 ms (30 fps 상한) | 27 배치 13.0 ms (77) | 26 배치 12.5 ms (80) |
| 10 000 tri, 변화 0 | 139 · 67.0 ms (15) | 53 · 25.5 ms (39) | 52 · 25.1 ms (40) |
| 10 000 tri, 변화 150 | 289 · 139 ms (7) | 203 · 98 ms (10) | 53–54 · 25.5–26.0 ms (38) |
| 10 000 tri, 변화 600 | 739 · 356 ms (3) | 653 · 315 ms (3) | 54–61 · 26–29 ms (34) |

**B1 만으로는 부족하다**(변화가 곧 배치): B2 가 있어야 상태 변화 수가 fps 에서 사라진다.  실제 fps 는 제출이 동기라 CPU 몫이 더해진다 — 비동기 제출은 다음 단계(G4-4 후보).

## 6. 호스트 검사 (전부 코딩 전에 정한다)

- `sim_verify.py`(새): 공유 검증기를 라이브러리 쪽으로 컴파일해 오라클 32 경우 + 세그먼트 경우 U33(패킷 둘, 사이에 TX·BLEND 쌍)을 판정; 커널 판정과 같아야.
- `sim_batch.py`: 경우 추가 — 두 상태 한 배치(헤더 둘, 사이 쌍은 **차이만**), 폭 변화(5→7 워드) 세그먼트, 세그먼트 상한, F1 경계, 표면 변화는 닫힘; 변이 — 차이 대신 전체를 넣음(워드 수), 헤더 하나만 다시 씀, 세그먼트 표 넘침.
- `check_hook.py`: 규칙 `g42-flush-points`(F2–F9 훅마다 `osrdnFlushBatch` 호출이 있고, RenderFinish 는 사전검증 뒤에만 flush), `g42-no-multipass`, 변이 각각.
- `check_units.py`·`hostcheck-r2b0`·`check_r5_src`(커널이 공유 단위를 부르는지, 함수 본문이 옮겨진 뒤 규칙 앵커), `sim_r5`(불변), `verify_oracle --c-cases`(U33) → 표 재생성.
- `audit_hooks`(새 훅 Flush·ReadPixels·CopyPixels·DrawPixels·Bitmap 선언 대조).

## 7. 실기 (재부팅 없음, 내 gcdsd)

| 장면(`ghostprobe_v17`) | 기대 | 판정 |
|---|---|---|
| `GHOST_MANY` 300 삼각형 한 상태 | **2 배치**(190/배치), 그림 = stock | judge_g43 K4 를 2 로 되돌림 |
| `GHOST_SEG` 300 삼각형, 2 개마다 텍스처 A/B·블렌드 on/off 교대(150 변화) | 배치 ≤ ceil(워드/4068) ≈ 3, 그림 = stock | 새 judge |
| `GHOST_ORDER` 카드 삼각형 → 소프트웨어 선(GL_LINES) → 카드 삼각형; `glReadPixels` 중간 읽기; `glTexSubImage2D` 중간 | 그림 = stock(선이 앞 삼각형 위·뒤 삼각형 아래), 읽은 화소 = stock | 새 judge |
| TEXBIG·ALPHA·STATES 회귀 | 그대로 | judge_texbig·judge_g43 |
| q2-state-matrix | 19/21 그대로 | |
| 티팟 PRESENT(오프스크린, G3: 32.07 fps) | 상승(수치는 기록) | run_g3 의 오프스크린 팔 |
| 계수기 | `prevalidateRefused` 0, `lostAtFlush` 0, `delegated` 전과 같음 | |

## 8. 위험

- 공유 검증기로 커널 소스를 옮기면 `check_r5_src` 의 앵커 여럿이 움직인다 — 규칙은 옮긴 자리를 가리키게 고친다(약화 없음).
- F3 의 VB 훑기는 RenderStart 마다 O(원시 수) — 원시는 VB 당 수십 개, 무시할 만하다; `CopyStart` 이전의 복사 정점은 이전 원시의 꼬리라 건너뛴다.
- 세그먼트 사이 레지스터 쓰기의 파이프라인 위험: r200 이 같은 방식이라 받아들이되, `GHOST_SEG` 의 그림 대조가 게이트다.
- 배치가 프레임 끝(glFinish)까지 살면 카드가 논다 — 다음 단계(비동기 제출)의 문제이지 이 단계의 회귀는 아니다: 오늘도 VB 끝까지 논다.

## 9. codex 교차검토 판정표

4 회 국지 호출(gpt-5.6-sol); 회신의 줄번호·수치는 전부 열어 확인했다.

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| B0: 검증기 함수군은 `r7WinStart/End` 읽기·`r7At/Word` 쓰기만 하고 커널 심볼 참조가 없다; 상수(`CP_R7_*` 마스크, `C_*` 레지스터)와 `cpR7Allow[]` 는 `.m` 안이라 공유 단위로 함께 옮겨야 | `osrdn_cp.m:72`·`osrdn_cp.m:106`·`osrdn_cp.m:1391` 등 define 위치 확인, 2449-2457 표 확인 | ✅ 채택 — 공유 단위에 상수·표를 같이 둔다 |
| F3: `gl_render_vb_indirect` 는 RenderStart 전에 `ctx->VB = cvaVB`, 원시는 인자 VB (`vbindirect.c:350-376`); `RENDER_START` 는 픽셀 명령·clear 에서도 불린다; 점은 PB→WritePixels, 사각형은 `basic_quad`→TriangleFunc | 전부 열어 확인 (`vbindirect.c:360` `ctx->VB = cvaVB;`, `types.h:2156-2160`, `readpix.c:771-776`, `copypix.c:644-649`, `buffers.c:279-280`, `quads.c:48-54`) | ✅ 채택 — F3 를 VB 훑기에서 점·선 함수 래퍼로 바꿈(가드 `points.c:1333-1346`, `lines.c:1071-1084` 도 확인) |
| §4: 두 검증기 모두 draw 수 제한 없음, draw 마다 정점 폭 재계산; **표면은 루프 뒤 마지막 값으로만 판정 → 중간 창 밖 오프셋 스트림이 통과(보안 구멍)**; Tri 는 헤더를 `pn` 한 곳만 | `osrdn_cp.m:2758-2770`, `verify_oracle.py:209-243` 확인; 오라클로 그 스트림을 만들어 `WHY_OK` 인지는 **K7 작업 때 U34 로 실제 확인** | ✅ 채택 — K7 로 등록(다음 커널 부팅) |
| r200: 상태는 DRM `RADEON_CMD_PACKET` 레코드로 draw 직전에, 대기 없음; tex 원자도 같고 캐시 무효화 명령 없음(항상 dirty) | `r200_cmdbuf.c:216-230`, `r200_state_init.c:75-81`, `r200_texstate.c:1180-1183` 확인 | ⚖️ 부분채택 — "raw PACKET0" 표현을 고침; 설계(세그먼트 = 레지스터 쓰기 + 패킷, 대기 없음)는 그대로 |

## 10. 구현 기록 — B1 (2026-09-27, 호스트 검사까지)

**변경 파일**: `mesa/OSRDNMesaTri.h`/`.c`(`osrdn_tri_batch_verify`·`osrdn_tri_batch_truncate`·`osrdn_tri_span_enabled`, 계수 `verifies`/`verifyRefused`/`truncated`), `mesa/OSRDNMesaHook.h`/`.c`(flush 사유 표 `OSRDN_FLUSH_*` 20 개, `osrdnFlushFor`, `osrdnBracketEnd`, 점·선 래퍼, Flush·ReadPixels·CopyPixels·DrawPixels·Bitmap 훅, `osrdnPend.stale`), `tools/mesa/gen_r7verify.py`(커널 호출 자리의 세 기본값을 `OSRDN_R7V_DEF_*` 로 방출), `tools/mesa/check_hook.py`(규칙 `g42-flush-points`, 설치 쓰기 7 줄·설치자 `osrdnInstallPrims` 등록, 변이 17), `tools/mesa/sim_batch.py`(검증기 링크, 경우 V, 변이 3), `tools/mesa/check_compile.py`(훅 단위를 Mesa `src/` 헤더로 호스트 컴파일 — 시그니처가 `dd.h` 에서 어긋나면 호스트에서 잡힌다, 변이 2).

**§3 의 표와 코드의 대응** (`osrdnFlushFor(사유)` 한 줄 = 한 함수, `check_hook` 이 함수 이름과 "보호 대상보다 앞" 을 강제):

| 계획 | 사유 코드 | 함수 | 앞서야 하는 것 |
|---|---|---|---|
| F1 | `STATE` | `osrdnTriangleWith` | `osrdn_tri_batch_add(` |
| (ctx) | `CTX` | `osrdnTriangleWith` | 같음 |
| F2 | `REFUSED` | `osrdnBracketEnd` | — |
| F3 | `POINTS`/`LINES` | `osrdnHookPoints`/`osrdnHookLine` | 저장된 함수 호출 |
| F4 | `DELEGATE` | `osrdnTriangleWith` | `(*sw)(ctx, v0, v1, v2, pv);` |
| F5 | `LEAVE` | `osrdnHookInstall` | `return;` |
| F6 | `CLEAR`/`GLFLUSH` | `osrdnHookClear`/`osrdnHookFlush` | `osrdn_card_clear(` / 이전 훅 |
| F7 | `READPIX`/`COPYPIX`/`DRAWPIX`/`BITMAP` | 각 훅 | 이전 훅(없으면 GL_FALSE) |
| F8 | `TEXUPLOAD`/`TEXDROP` | `osrdnTexResident`/`osrdnTexDrop` | `osrdn_tex_upload_at(` / `osrdn_texarena_free(` |
| F9 | `SURFACE`/`RELEASE` | `OpenStepMesaAccelBuffer`/`ReleaseBuffer` | `osrdn_surf_take(` / `osrdn_surf_release(` |
| F10 | (배치 안 함) | `osrdnHookInstall` 이 `MultipassFunc` 를 읽어 `osrdnMultipass` | 삼각형 경로가 단독 전송 |
| (M1k) | `OUTSIDE`/`BRACKET`/`ALONE` | 손잡이 off 의 옛 모양 · 브래킷 밖 삼각형 | — |

**계획에 없던 결정 — 검증된 접두부와 거절된 꼬리**: 브래킷 2 의 RenderFinish 에서 검증기가 거절하면 배치엔 두 부류가 섞여 있다: 브래킷 1 이 끝날 때 **검증을 통과해 열어 둔** 삼각형 k 개(인덱스 죽음)와 이번 브래킷의 신선한 꼬리.  계획 §2 의 "거절이면 지금 flush(재생 가능)" 는 꼬리에만 참이다.  구현: `osrdn_tri_batch_truncate(k)` 로 스트림을 접두부만 남기고(그 워드들은 브래킷 1 때 검증한 스트림과 **한 워드도 다르지 않다** — 프롤로그·정점 워드는 그대로, 헤더는 flush 가 같은 개수로 다시 쓴다) 그것만 제출(`prefixFlushed`), 꼬리는 그 자리에서 소프트웨어로 그린다(`replayed`).  k = 0 이면 ioctl 을 쓰지 않는다(같은 규칙이 커널에서도 거절한다).  거절이 없으면 통과 배치는 열어 두고 `osrdnPend.stale = n` 으로 표시한다.

**약속의 새 문장(코드)**: `osrdnFlushBatch` 의 재생 루프는 `i < stale` 인 항목을 **절대 그리지 않고** `lostAtFlush` 에 센다 — 죽은 인덱스로 `ctx->VB` 를 읽는 일은 없다.  검증기가 통과시킨 스트림이 커널에서 실패하는 길은 정지(EIO)뿐이므로 `lostAtFlush` 는 "카드가 답하지 않았다" 의 계수다(실기 게이트: 0).  RenderFinish 없이 RenderStart 가 오면(`unfinished`, Mesa 는 짝을 맞추므로 0 이어야) 그 항목도 stale 로 표시만 한다.

**손잡이**: `RDNMesaSpan=0` 이면 M1k 모양(RenderStart 의 `osrdnFlushOutside`, RenderFinish 의 무조건 flush) 으로 돌아간다 — 같은 부팅에서 두 모양을 잴 수 있다.

**검증기 인자**: `winEnd = winStart + osrdn_surf_window(&winBytes)` 의 winBytes(라이브러리 매핑이 닿는 곳, 커널의 `winCeiling` 을 넘지 않는다 — 그 너머는 mmap 이 실패했을 것), `defC/defZ/defPitch` 는 생성 헤더의 `OSRDN_R7V_DEF_*`(커널 `osrdn_cp.h` 의 `CP_R6_COLOR_OFF`/`CP_R6_DEPTH_OFF`/`CP_R6_PITCH`, 생성기가 커널 호출 자리 문자열까지 대조).

**호스트 검사 결과**: `gen_r7verify --check/--self-test` PASS, `sim_verify` PASS, `check_hook` PASS(규칙 111 개·변이 전부 검출), `sim_batch` PASS(경우 V: 빈 배치 EMPTY 13 · 셋 OK · 경계 0 이면 SURFACE 11 · 절단 후 헤더 정점 3 · 스트림이 경우 A 와 워드 동일; 변이 3 검출), `check_compile` PASS(훅 단위 Mesa src 컴파일 포함), `check_units` PASS, `hostcheck-r2b0` PASS.  실기는 B2 뒤 §7 대로.

## 11. 구현 기록 — B2 (2026-09-27, 호스트 검사까지)

**변경 파일**: `mesa/OSRDNMesaTri.c`(배치 구간 재작성: `triRoomWords`·`triSameState`/`triSameSurface`·`triKeepState`·`triSegOpen`·`triSegRestore`·`triSegTrim`·`triStreamLast`·`triSegDiff`·`triSegHeaders`, `triPrologueTo(dst, …)`), `mesa/OSRDNMesaTri.h`(`OSRDN_TRI_SEGS` 256, 계수 `segments`/`segWords`), `tools/mesa/sim_batch.py`(경우 B 재정의·경우 S·스트림 파서 `segments()`·변이 8, 옮겨간 앵커 7).  훅은 손대지 않았다 — 세그먼트는 `osrdn_tri_batch_joins`/`reserve` 안의 일이다.

**§4 와 같은 점**: 배치 키를 표면(colourByteOff·pitch·width·height: 다르면 닫힘)과 상태(smooth·blend·tex·depth·alpha·텍스처 5 항: 다르면 세그먼트)로 나눴다; 세그먼트 = 새 상태의 프롤로그를 스크래치에 만들어 **스트림이 마지막으로 그 레지스터에 쓴 값과 다른 쌍만** 덧붙이고 헤더 두 워드; flush 는 세그먼트마다 헤더를 다시 쓴다; 재생은 만들지 않았다(B1 의 stale 규칙이 대신한다).

**§4 와 다른 점**: (1) `triLast[reg]` 표를 두지 않고 `triStreamLast` 가 **스트림 자체**(프롤로그 쌍 + 각 세그먼트의 쌍)를 걸어 "마지막 값" 을 읽는다 — 정본이 하나.  (2) 배치의 상한은 삼각형 수(`maxTris`)가 아니라 **워드**(`triB.room` = min(caps->maxWords, 창 워드) — 정점 폭이 다른 세그먼트가 섞이면 삼각형 수로는 못 센다; 경우 C·G 의 수치는 그대로다(48+2+267×15 = 4055 ≤ 4068, 268 은 4070).  (3) reserve 뒤 commit 을 안 한 세그먼트(두 단계 API)가 헤더에 정점 0 을 남기면 검증기가 VF 로 거절하므로 `triSegTrim` 이 flush·verify·절단·새 세그먼트 열기 전에 **빈 꼬리 세그먼트를 쌍까지 통째로** 지운다(훅은 add 만 쓰지만 API 가 허용하는 길이다 — 하네스에서 잡혔다).  (4) `OSRDN_TRI_SEGS` 256 은 닿을 수 없는 상한이다: 세그먼트 하나가 최소 17 워드(헤더 2 + 삼각형 15)라 256 개는 4352 워드 > 4068 — `sim_batch` 가 이 부등식을 검사한다.

**python 으로 확인한 수치**(표 `OSRDNMesaTriTable.h` 에서): flat→tex 프롤로그 차이 11 쌍(`0x70e 0x714 0x823 0xbc0 0xbc2` + 텍스처 전용 `0xb00–0xb04 0xb40`), tex→flat 5 쌍; 하네스 경우 S 의 스트림은 48 + 2 + 30 + 22 + 2 + 42 + 10 + 2 + 15 = 173 워드(세 세그먼트), 계수 `segWords` 32; 깊이 on/off 를 삼각형마다 바꾸면 세그먼트 하나 = 2×2 + 2 + 15 = 21 워드라 4068 에 **191** 개(1 + ⌊(4068 − 65)/21⌋), 스트림 4055 워드, 하나 더는 4076 > 4068.

**호스트 검사 결과**: `sim_batch` PASS(20 스트림 전부 오라클 통과; 경우 B = 상태 다름은 세그먼트·표면 다름은 BATCH_OPEN; 경우 S = 세그먼트가 **정확히** 스트림이 안 쓴 쌍만 나른다(경우 A/E 의 프롤로그를 정본으로 대조), 절단 뒤 빈 세그먼트 제거, 미커밋 reserve 두 번 뒤 스트림에 그 흔적 없음, 191 상한; 변이 24 개 전부 검출), `check_hook` PASS, `check_compile` PASS, `check_units` PASS, `hostcheck-r2b0` PASS, 인용 재조준 20 건(사람 몫 0).

**실기 도구**: `build/g42/ghostprobe_v17.c`(v16 + `GHOST_SEG`·`GHOST_ORDER`·계수기 줄 `b1:`/`b2:`/`why:`), `build/g42/run_g42.sh`(LIBRUN·BUILD; 재부팅 없음; MANY·SEG·ORDER + UV·TEXBIG·ALPHA·q2 회귀 + 세 판정), `build/g42/judge_g42.py`(MANY 2 배치·SEG ≤ 3 배치·세그먼트 ≥ 149 − (배치 − 1)·ORDER 의 flush 표에 lines/points/readpix/texupload·그림 넷 이웃 규칙·모든 장면에서 refused = lost = unfinished = primNoSw = desync = noSw = 0).

## 12. 실기 (2026-09-27, 드라이버 `1beb2ed9` 그대로·내 gcdsd·재부팅 없음)

### 12-1. 첫 실행 — 라이브러리 790444279 (`build/g42/run.log`)

| 장면 | 결과 | 뜻 |
|---|---|---|
| MANY | batches=2 **drawn=0** flushFailed=2 lost=254 replayed=46 prevalidated=5 | 브래킷을 넘긴 두 배치(4052·2372 워드)를 **커널이 거절** — 클라이언트 검증기는 통과(verifyRefused=0)시켰으니 검증기 밖의 한계 |
| SEG | batches=150 **segments=0** why: outside=150 | 상태 변화마다 `OpenStepMesaAccelUpdateState` 의 M1k 무조건 flush(`osrdnFlushOutside`)가 먼저 닫아 세그먼트가 한 번도 안 열림 — §3 의 flush 지점 열거가 이 호출 자리(훅 함수가 아닌 UpdateState 진입부)를 빠뜨렸다 |
| ORDER | drawn=6 prevalidated=3 points=1 lines=8 why: outside=2 readpix=1 | 그림은 맞지만 선·점 앞의 flush 는 UpdateState 가 대신 해 버려 F3 이 시험되지 않음 |
| UV·TEXBIG·ALPHA·q2 | 부팅 8 과 같음 | 회귀 없음 |

**거절의 원인(커널 로그, 원문)**: `RDN-R7B reject2 boot=1a97434b words=4052 count denied=1`, `… words=2372 count denied=2`.  SUBMIT2(copyin) 가지는 `n > OSRDN_R7B_MAX_WORDS || n > OSRDN_R7B_WINDOW_WORDS` 를 "count" 로 거절한다 — 스테이징이 8 KB 페이지 하나(`rdnR7bVirt`)라 **2048 워드가 실제 상한**인데 CAPS 는 `maxWords` 4068 을 광고한다(K4 의 불일치, `docs/G4_3_KERNEL_PLAN.md` 12 의 K8 로 등록).  부팅 8 은 배치가 VB 에 묶여 1572 워드를 넘은 적이 없어 못 봤다.  약속은 지켜졌다: 잃은 254 개는 `lostAtFlush` 에 세어졌고 죽은 인덱스로 그린 것은 없다(`replayed` 46 = 마지막 브래킷의 신선한 항목).

**고침(둘 다 라이브러리, 호스트 검사 뒤 재빌드 790444668)**: (1) `triRoomWords` = min(`caps->maxWords`, `caps->bytes/4`[, 창 워드]) — 커널이 어느 경로로든 받는 만큼만; `sim_batch` 경우 I(copyin + 작은 페이지 → 경우 G 와 같은 상한) + 변이 2.  (2) UpdateState 의 flush 를 `RDNMesaSpan` 손잡이 뒤로 — 상태 변화는 세그먼트; `check_hook` 이 `osrdnFlushOutside` 호출 지점 네 곳(RenderStart·Finish·UpdateState·Mirror)을 열거하고 RenderStart·UpdateState 는 손잡이 가드를 요구, 변이 1.  기대치 갱신: 2048 워드면 텍스처 삼각형 94 개/배치, MANY 300 = **4** 배치(부팅 8 의 5 에서 하나 줄 뿐 — 4068 이 되려면 K8), SEG ≤ 5, `judge_g42` 가 `osrdn_r7b.h`·표에서 계산.

### 12-2. 두 번째 실행 — 라이브러리 790444668 (`build/g42/run2.log`, ORDER 는 장면 수정 뒤 재실행·`run3.log` 가 최종)

| 장면 | 실측 | 판정 |
|---|---|---|
| MANY (300 텍스처 삼각형, 한 상태) | **batches=4** drawn=300 lost=0 refused=0 prevalidated=5 flushes: state=3(F1 워드 상한)·outside=1(glFinish); 그림 stock 과 이웃 규칙 0 | PASS — 부팅 8 의 5 → 4 (2048 워드 = 94 삼각형/배치; 4068 이면 2, K8 뒤) |
| SEG (같은 300, 2 개마다 텍스처 A/B·블렌드 on/off, 149 변화) | **batches=5 segments=147** segWords=882(세그먼트당 3 쌍 = 6 워드) verifies=150 lost=0; flush: state=3·outside=1·texupload=1(텍스처 B 첫 사용 때 F8); 그림 stock 과 0 | PASS — 149 변화 중 147 이 스트림 안(나머지 2 는 배치 경계) |
| ORDER (카드 → 소프트웨어 선 → 카드 → glReadPixels → 카드 → glTexSubImage2D → 카드 → 소프트웨어 점) | drawn=8 prevalidated=4 flush: **points=1 lines=1 readpix=1 texupload=1**; 그림 100,923 화소 stock 과 **0 차**, 읽은 64×64 블록 stock 과 **0 차**; lost=refused=primNoSw=0 | PASS — F3·F7·F8 이 실제로 발화하고 순서가 맞다 |
| UV·TEXBIG·ALPHA·q2 회귀 | uv 1..256 전부 카드; texbig 10 장면·alpha 7 장면 이웃 규칙 0; q2 19/21 HARDWARE | judge_texbig PASS·judge_g43 PASS |

**첫 실행에서 배운 것(§12-1)과 그 고침이 실기로 닫혔다**: 커널이 받는 상한(2048)을 라이브러리가 따르니 거절 0; UpdateState 의 flush 를 손잡이 뒤로 보내니 세그먼트가 열린다.  ORDER 장면은 처음에 모델뷰(translate/rotate)를 잊어 읽기 블록이 빈 곳을 읽었다(두 쪽 다 단색 — `judge_g42` 의 "stock 이 아무것도 안 그렸으면 같음은 증명이 아니다" 가 잡음) → `glLoadIdentity` 로 고침.

**수치의 뜻**: 브래킷을 넘는 것 자체(B1)는 됐고, 세그먼트(B2)도 됐다.  그러나 제출 워드 상한이 2048 이라 §5 모델의 "B1+B2 = 53 배치/10k 삼각형" 은 오늘 절반 크기 배치로 ~110 이다; 4068 은 커널 K8(SUBMIT2 청크 copyin) 뒤에 온다.  다음 부팅 묶음: K5(밉맵)·K7(draw 마다 표면 판정)·K8.

**티팟 PRESENT fps(§7 마지막 행)는 재지 못했다**: `test/osrdn-sdl-teapot.c` 는 SDL 창을 만들어 DPS 연결이 필요하고(`DPS Error: Can't connect to server`, `build/g42/teapot/pr.out`), 내 telnet gcdsd 엔 WindowServer 세션이 없다.  §7 의 "오프스크린 팔" 은 오기 — `run_g3.sh` 의 pr 팔은 화면 창이다.  사용자 gcdsd 로 `LIBRUN=790444668 BOOT=1a97434b BUILD=1beb2ed9 bash build/g3/run_g3.sh` 를 돌리면 G3 의 32.07 fps 와 비교된다(라이브러리만 바뀌었으므로 재부팅 불필요).  최종 기록은 `build/g42/run3.log`(세 판정 PASS).
