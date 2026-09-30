# G5-1b — present 를 프레임당 한 블릿으로: 라이브러리가 y 를 뒤집어 그린다 (라이브러리만, 재부팅 없음) (계획, 2026-09-29, 코딩 전)

## 0. 사실 (전부 연 것)

- G5-0 §8-1·G5-1a §5: present 행 480 회 = **15 ms/프레임**(행당 31–33 us), 월드 프레임 30.7 ms 의 절반.
- 왜 행 단위인가: 카드는 **창 y 를 그대로 행으로** 그린다(Y_UP; `OSRDNMesaHook.c:1906-1915` 은 Y_UP 이 아닌 컨텍스트를 카드에서 뺀다) → 표면은 아래→위, 화면은 위→아래.  SDL 은 그래서 행을 역순으로 한 번씩 찍는다(`SDL_openstepvideo.m:2594-2638`: 행 k 의 원본 `srcY+k` → 목적지 `dstY+(h−1−k)`), 그리고 Y_UP 을 바인드마다 1 로 고정한다(`SDL_openstepvideo.m:2250`·`SDL_openstepvideo.m:2264`).  주석 `SDL_openstepvideo.m:2609-2612` 가 "드라이버 present 가 원본을 위로 걷는 법을 배우면 한 블릿" 이라 적었다.
- 커널 present 는 h 행짜리 사각 블릿을 **같은 방향**으로 복사한다(`osrdn_cp.m:3923-3959`: `DP_CNTL` = `L2R_T2B`, `SRC_X_Y`/`DST_Y_X`/`DST_HEIGHT_WIDTH`).  R200 2D 의 방향 비트는 목적지 X/Y 두 개뿐이고 원본은 따라간다(`radeon_reg.h:670-672`) — **수직 뒤집기 블릿은 없다**.  높이 제한은 `C_PRESENT_MAX_DIM` 과 화면 안(`osrdn_cp.m:3926`).
- 훅은 컬링을 **Mesa 창 좌표로 직접** 한다(`OSRDNMesaHook.c:918-929`, 카드는 컬링 안 함), 정점은 `Win[1]` 을 그대로 y 로 싣는다(`OSRDNMesaHook.c:1002-1004`); 표면 높이는 `osrdnTriState.height`(`OSRDNMesaHook.c:763`)로 손에 있다.  커널 검증기에 정점 좌표 범위 규칙은 없다(`osrdn_cp.h:298-306`: TYPE·TRUNC·P0·P3·VF·VTX_FMT 뿐).
- present 모드 질의 `osrdn_present_active()` 가 있다(`OSRDNMesaPresent.h:64`, 훅이 `OSRDNMesaHook.c:1420` 에서 쓴다).

## 1. 설계 — 뒤집어 그리고, 첫 행에서 통째로 찍는다

1. **정점 y 뒤집기**: present 모드가 켜진 컨텍스트에서만, 정점 패킹 때 `wy = H − y`(`H = st->height`).  픽셀 중심 `y = r + 0.5` → `H − y = (H−1−r) + 0.5`: 행 r 이 행 `H−1−r` 로 정확히 옮겨진다(반올림 변화 없음).  컬링은 뒤집기 **전** 좌표로 이미 판정되므로 손대지 않는다(`OSRDNMesaHook.c:918-929` 은 `Win` 을 읽는다).  깊이·텍스처 좌표·w·색·프롤로그(TOP_LEFT, WIDTH_HEIGHT, 깊이 오프셋)는 y 와 무관.  결과: 표면 행 s = 화면 행 s(위→아래).
2. **present 병합**: SDL 의 행 호출은 그대로 온다.  present 모드에서 `OSRDNMesaBufferPresentRect(srcX, srcY, w, 1, dstX, dstY)` 는
   - `srcY == 0`(한 프레임의 첫 행; SDL 은 k=0 부터)이면 **한 번의 블릿**으로 원본 행 0..H−1 → 목적지 행 `dstY−(H−1)` .. `dstY` 를 보낸다(뒤집힌 표면에서는 원본 행 s 가 화면 행 `dstY0 + s`; SDL 의 첫 호출 `dstY = dstY0 + H − 1`).  커널이 거절하면(창이 화면 밖: E_DST) 행 단위로 물러난다(아래).
   - 그 뒤의 행(k ≥ 1)은 "이미 찍힌 영역"(같은 srcX·w·dstX, 목적지 행이 마지막 전체 블릿의 범위 안)이면 ioctl 없이 OK.
   - 그 밖의 호출(부분 사각형, 첫 행 거절 뒤)은 행마다 원본 행 `H−1−srcY` → `dstY` 로 한 행 블릿(뒤집힌 표면의 올바른 행).  그림은 어느 경로든 같다.
3. **present 모드가 아닌 컨텍스트**(teapot 되읽기 데모, OSMesa 미러)는 뒤집지 않는다 — 되읽기 경로가 Y_UP 을 전제한다.  뒤집기 판정은 삼각형마다 `osrdn_present_active()` 한 번(정적 int 읽기 수준).
4. 소프트웨어 폴백(위임 삼각형·점·선·비트맵)이 present 모드에서 표면에 그리면 **거꾸로** 그려진다 — GLQuake 정상 경로에서 전부 0 이고(G5-0/1a 통계), 0 이 아닌 실행은 판정기가 표시한다.  이것이 이 설계의 알려진 한계이며, 정본 답(Mesa 에 Y_UP=0 을 요구하고 SDL 이 한 블릿)은 SDL 변경이라 이번 범위 밖.
5. `rdndump` 는 그대로(원시 행) — 판정 python 이 present 모드 덤프를 뒤집어 비교한다.

## 2. 검사
- `check_hook.py` 규칙 + 변이: 뒤집기가 present 모드에 묶여 있다(뒤집기 상수화 → 잡힘), `H − y` 형태(`H − 1 − y` 로 바꾸면 잡힘), 컬링이 뒤집기 앞에 있다.
- 호스트 시뮬레이터 `tools/mesa/sim_present.py`: Present.c 를 가짜 ioctl(호출 기록)로 링크해 SDL 의 행 순서(k=0..H−1, 역순 dst)를 흉내 → ioctl 1 회·전체 사각형; 부분 사각형·첫 행 거절 → 행마다 `H−1−srcY`; 변이: 병합 없음(480 회), 원본 행 매핑 누락.
- 실기: R1 월드 프레임·R2 데모(`RDNMesaTime=1`): present 호출 300/프레임 → **1/프레임**, −15 ms; 그림 게이트: R1 뒤 `rdndump` 를 **뒤집어** G5-1a 의 `r1b` 와 비교(조명 띠 허용 규칙 그대로); **사용자 화면 확인**(방향·HUD·무기).

## 1-1. codex 판정 뒤 설계 보강 (§4)

- **미러 되복사가 방향을 안다**: `osrdn_surf_mirror`(`OSRDNMesaSurface.c:323-327`, 평면 복사)는 명시적 미러(`OSRDNMesaHook.c:1987-1990`)와 present 를 끄는 길에서 여전히 돈다.  훅이 뒤집어 그릴 때 표면에 `flipped` 표시를 두고(`osrdn_surf_set_flipped`), 미러는 표시가 서 있으면 **행을 뒤집어** 복사한다 — 앱 배열의 Y_UP 계약이 유지된다.  present 모드가 꺼진 뒤 첫 그리기까지도 표시가 마지막 그림의 방향을 말한다.
- **높이는 표면 것**: 뒤집기의 H 와 병합 블릿의 행 수는 둘 다 `surfCounts.height`(`OSRDNMesaSurface.c:224`)에서 온다(`st->height` 는 `ctx->DrawBuffer->Height` `OSRDNMesaHook.c:861` 로 같은 창이지만, 한 곳에서 읽는다).  병합의 조건: `h == 1`, `srcY == 0`, `dstY ≥ H−1`, `w == 표면 폭`.
- **한계(문서화, 판정기가 0 을 요구)**: present 모드에서 소프트웨어가 표면에 그리는 경로 — 위임 삼각형(`OSRDNMesaHook.c:1112`), 묶음 실패·검증 거절 재생(`OSRDNMesaHook.c:492-493`·`OSRDNMesaHook.c:614-615`), 점·선(`OSRDNMesaHook.c:1467`·`OSRDNMesaHook.c:1481`), 픽셀 명령(ReadPixels·CopyPixels·DrawPixels·Bitmap `OSRDNMesaHook.c:1509`·`OSRDNMesaHook.c:1511`·`OSRDNMesaHook.c:1604`·`OSRDNMesaHook.c:1614`) — 은 Y_UP 좌표로 그리므로 뒤집힌 표면에서 **거꾸로** 다.  GLQuake 정상 경로에서 전부 0(G5-0/1a 통계).  라이브러리가 종료 때 `RDN-C` 줄로 그 계수를 찍고 판정기가 0 을 요구한다.  ReadPixels 의 좌표 보정은 후속 항목.
- 뒤집기 판정은 `osrdn_present_active()`(표면 소유자 컨텍스트가 present 를 켰는가 `OSRDNMesaPresent.c:48`; 표면은 하나라 훅이 패킹하는 컨텍스트가 곧 소유자).

## 4. codex 교차검토 판정 (2026-09-29, gpt-6-astra, 한 주장·국지적) — (a) 성립, (c)·(d) 정정, (b)·(e) 한정

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| (a) 두 패킹 팔이 같은 `wy` 를 쓴다(`OSRDNMesaHook.c:1003`·`OSRDNMesaHook.c:1034`·`OSRDNMesaHook.c:1037`, `OSRDNMesaTri.c:766`), 컬링(`OSRDNMesaHook.c:916-921`)은 `Win` 원본 | 줄을 열어 확인 | ✅ — float 에서 `H − y` 를 만든 뒤 `osrdnBits` |
| 픽셀 명령(`OSRDNMesaHook.c:1509`·`OSRDNMesaHook.c:1511`·`OSRDNMesaHook.c:1604`·`OSRDNMesaHook.c:1614`)은 present 검사 없이 원래 y 로 표면을 읽고 쓴다(`OSRDNMesaHook.c:1505`) | 열어 확인 | ✅ 채택 — 한계로 문서화, 계수 0 요구 |
| 소프트웨어 폴백이 살아 있다: 위임 `OSRDNMesaHook.c:1112`, 재생 `OSRDNMesaHook.c:492-493`·`OSRDNMesaHook.c:614-615`, 거절 상태 `OSRDNMesaHook.c:1655`·`OSRDNMesaHook.c:1661`, 점·선 `OSRDNMesaHook.c:1467`·`OSRDNMesaHook.c:1481`(`OSRDNMesaHook.c:1448-1450`), `OSRDNMesaHook.c:1632-1634` | 열어 확인 | ✅ 채택 — 같은 한계·계수 0 |
| (c) 미러는 present 에서 전부 꺼지지 않는다: `OSRDNMesaHook.c:1421-1423` 은 glFinish 의 되복사만 생략(`OSRDNMesaHook.c:1414`·`OSRDNMesaHook.c:1417-1418`), 명시적 미러 `OSRDNMesaHook.c:1984`·`OSRDNMesaHook.c:1987` 은 검사 없음, `OSRDNMesaSurface.c:323-327` 은 행 반전 없는 평면 복사, `OSRDNMesaPresent.h:51-53` | 열어 확인 | ✅ 채택 — §1-1 `flipped` 표시 + 행 반전 미러 |
| (d) `st->height`(`OSRDNMesaHook.c:861` DrawBuffer) 와 표면 높이(`OSRDNMesaHook.c:1938`→`OSRDNMesaSurface.c:224`)·SDL 사각형(`OSRDNMesaPresent.c:358-360`, 계약 `OSRDNMesaPresent.h:55`)의 동일성은 이 파일들로 증명 안 됨 | 열어 확인 | ✅ 채택 — H 는 `surfCounts.height` 한 곳에서, 병합 조건에 폭·`srcY==0`·`dstY ≥ H−1` |
| clear 는 전체 표면(`OSRDNMesaHook.c:713-714`, `OSRDNMesaDepth.c:113-114`) — 방향 무관; 부분 clear 미반영은 기존 문제(`OSRDNMesaHook.c:654-655`·`OSRDNMesaHook.c:732`·`OSRDNMesaHook.c:728`) | 열어 확인 | ⏭️ 기존 한계, 이 계획과 무관 |
| 텍스처는 별도 아레나(`OSRDNMesaHook.c:340`·`OSRDNMesaHook.c:351`·`OSRDNMesaHook.c:361-362`·`OSRDNMesaHook.c:1949`) | 열어 확인 | ✅ |
| `osrdn_present_active()` 는 현재 컨텍스트를 안 본다(`OSRDNMesaPresent.c:48`), PresentRect 는 `presentOn` 을 안 본다(`OSRDNMesaPresent.c:250`), 모드 전환(`OSRDNMesaPresent.c:61-73`)은 행 순서를 안 바꾼다 | 열어 확인 | ⚖️ 표면이 하나라 소유자 = 패킹 컨텍스트; 모드 전환은 `flipped` 표시가 해결 |

codex 줄번호 60 여 곳 전부 실제와 일치(python 으로 출력해 대조).

## 3. codex 교차검토 (한 주장·국지적)
주장: "정점 패킹의 `wy = H − y`(present 모드에서만)와 present_rect 의 첫 행 통째 블릿·나머지 행 무시·부분 사각형 행 매핑만으로 그림이 같다: 컬링(`OSRDNMesaHook.c:918-929`)은 뒤집기 전 좌표라 불변, 깊이·텍스처·프롤로그·검증기는 y 와 무관, 표면을 읽는 다른 경로(clear, 업로드, 되읽기)는 present 모드에서 y 방향에 의존하지 않는다."  확인할 것: 훅의 `osrdn_present_active()` 사용처(`OSRDNMesaHook.c:1420`)가 무엇을 하는지, 정점 패킹 두 팔(inl / `osrdn_tri_vertex`)이 같은 `wy` 를 쓰는지, present 모드에서 표면을 CPU 로 읽는 경로(Mirror/ReadPixels)가 살아 있는지, `st->height` 가 표면 높이(창 높이)와 같은지.

## 5. 구현·실측 (2026-09-29, 라이브러리 **790596985**, 드라이버 2d3234bf, 사용자 gcdsd, 재부팅 없음; `build/g51b/run_g51b.sh` → `run.log`)

- 구현: 훅 `osrdnTriangleWith` 의 `flipY = osrdn_present_active()`, `flipH = 표면 높이`, 정점 `wy = osrdnBits(flipY ? flipH − y : y)`, `osrdn_surf_set_flipped(flipY)`; `osrdn_surf_mirror` 는 표시가 서 있으면 행을 뒤집어 복사; `OSRDNMesaBufferPresentRect` 는 뒤집힌 표면에서 첫 행(`srcY == 0`, 전폭, `dstY ≥ H−1`)에 전체 블릿 → `coalesced`, 그 블릿이 덮은 행은 ioctl 없이 `covered`, 그 밖은 `H−1−srcY` 행 블릿 `rowFallback`.  종료 때 `RDN-C` 줄(위임·재생·점·선·픽셀 명령·미러 계수).  검사: `check_hook` 규칙 `g51b-flip` + 변이 4, `tools/mesa/sim_present.py`(행 순서·병합·부분·거절 폴백·변이 4) PASS, `sim_time`(병합 프레임 경계) PASS, judge_m1b PASS(첫 빌드는 `fprintf` 로 B3 에 걸려 Time 의 write 포매터로 바꿈).

| | G5-1a(790595436) | G5-1b | 차 |
|---|---|---|---|
| 시작 맵 **월드 프레임 150–300** | 30.7 ms (32.6 fps) | **17.3 ms (57.7 fps)** | −13.4 ms |
| 데모 300 프레임 | 60.2 ms (16.6 fps) | **40.8 ms (24.5 fps)** | −19.4 ms |
| present | 15.0 ms, 480 ioctl/프레임 | **1.3 ms, 1 ioctl/프레임**(판정기의 2.6 은 창 생성 직후 표시 전의 첫 프레임 480 행이 섞인 평균: 777 = 297 + 480) | |

- `RDN-C`: delegated·replayed·points·lines·outside·nosoftware·readpix·copypix·drawpix·bitmap 전부 **0**, mirrors 2(종료 경로, 표시 0 — present 를 끄고 나서 복사되므로 `mirrors_flipped` 0 은 정상: 그 시점엔 표면이 이미 해제·재그리기 대상이 아님).
- **그림**(`build/g51b/r1-vs-g51a.png`): 새 덤프는 위→아래이고 방향·HUD·표지판·무기 모두 정상.  뒤집어 G5-1a 의 `r1b` 와 비교하면 31 % 화소·|Δ|≥16 6.7 %: 대부분 바닥 조명 띠(행 320–400, 게임 시간 차)이고 나머지는 폴리곤 경계의 **1 화소 선**(y 를 뒤집으면 래스터의 경계 소유 규칙이 다른 쪽 삼각형에 붙는다) — 구조적 차이 없음.  뒤집지 않고 비교하면 99.9 % 가 다르다(방향 증명).  이후 그림 게이트의 기준은 G5-1b 자신.
- 사용자 화면 확인: §6.

## 6. 사용자 확인

- 2026-09-29 사용자 보고 1: "glquake 창을 이동하면 원래 위치에 스크린샷처럼 잔상이 남는다" — 그리고 **앱을 종료한 뒤에도 윈도 서버 화면에 남아 있다**.  present 는 윈도 서버가 모르는 화소를 화면에 직접 찍는 것이라(SDL 주석 "A STAMP IS NOT COMPOSITING", `SDL_openstepvideo.m:2594-2638` 앞), 창이 옮겨진 뒤 옛 자리를 다시 칠하는 것은 윈도 서버의 몫인데 서버는 그 자리가 바뀐 줄 모른다(자기 백킹에는 우리 화소가 없다) — 행 단위 도장이던 G3 부터 같은 성질이고 라이브러리가 고칠 수 없다.  고칠 자리는 SDL: 창 위치가 바뀐 프레임(`StampArm` 이 한 프레임 도장을 쉬는 자리)에서 **옛 사각형을 AppKit 으로 한 번 다시 그려** 서버가 그 영역을 되칠하게 하는 것.  → 후속 항목(SDL 쪽).
- 같은 확인 중 발견한 라이브러리 버그(사용자 보고 전 코드 읽기에서): 창이 화면 **아래로 걸치면** SDL 이 행을 `ph < H` 개만 보내는데, 첫 행의 `dstY` 만으로는 `ph` 를 알 수 없어 전체 블릿이 창 꼭대기보다 `H − ph` 행 위에 놓였다.  수정: **직전 프레임이 온전(H 행 연속·같은 첫 목적지·같은 x·폭)했을 때만** 통째 블릿, 이동·크기·클립이 바뀐 첫 프레임은 행 단위(그 한 프레임만 옛 비용).  `sim_present.py` 에 클립·이동·평평한 행 시나리오와 변이 6 종.  라이브러리 **790597856**.
- 실행 중이던 사용자 인스턴스 위로 재링크해 그 프로세스가 깜빡이고 뒤집혔다 — 제 실수(메모리 `relink-kills-the-running-instance`).  종료 뒤 790597856 으로 다시 띄움.
