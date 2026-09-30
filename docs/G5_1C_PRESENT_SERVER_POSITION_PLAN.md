# G5-1c — present 의 목적지를 윈도 서버에 직접 묻는다: 드래그 잔상 (라이브러리만, 재부팅 없음) (계획, 2026-09-29, 코딩 전)

## 0. 증상과 원인 (전부 연 것)

- 사용자 보고(G5-1b §6): 창을 끌면 **원래 자리에 마지막 프레임이 스크린샷처럼 남고**, 앱을 종료해도 남는다.  새 자리의 그림은 정상.
- 원인: present 는 윈도 서버가 모르는 화소를 화면에 직접 찍는다(SDL 주석 "A STAMP IS NOT COMPOSITING", `SDL_openstepvideo.m:2594-2638` 앞).  드래그가 시작되면 서버는 **즉시** 창을 옮기지만 앱 쪽 위치는 `windowDidMove`(`SDL_openstepvideo.m:1220-1236`)가 처리된 뒤에야 바뀌고, SDL 의 `StampArm` 은 그 캐시(`SDL_GetWindowPosition`, `SDL_openstepvideo.m:2554`)로 목적지를 잡는다 — 위치가 바뀐 것을 본 프레임 하나만 건너뛴다(`SDL_openstepvideo.m:2562-2565`).  그 사이의 present 는 **비워진 옛 자리**에 찍히고, 서버는 자기가 그리지 않은 화소를 되칠하지 않는다.
- Matrox 의 glwin 데모가 같은 잔상("드래그 잔상", `C8_SDL2_VRAM_PRESENT_PLAN.md:177-179`)을 **서버에 직접 물어** 없앴다: `PScurrentwindowbounds([win windowNumber], …)` 는 서버가 지금 창을 그리는 자리를 동기 왕복으로 돌려주고(`openstep-mga-glwin.m:486-496`), 내용 원점과의 상수 오프셋은 창을 놓은 직후 한 번 잰다(`openstep-mga-glwin.m:462-475`); 이벤트 큐에 무언가 있으면 그 프레임을 건너뛴다(`openstep-mga-glwin.m:539-557`).  SDL 포트는 이것을 안 받았고 C8 이 "캐시가 서버와 얼마나 어긋나는가" 를 남은 전건으로 적었다(`C8_SDL2_VRAM_PRESENT_PLAN.md:248`).
- 라이브러리가 직접 물을 수 있다(실기 확인, `build/g51c/dyt3.c`): `PSfrontwindow(int *)`·`PScurrentwindowbounds(int, float *×4)` 는 `psopsNeXT.h:124`·`psopsNeXT.h:128`(AppKit `Versions/B`), 정의는 AppKit/`libNeXT_s`.  **링크 의존 없이** 런타임에 묶는다: `NSIsSymbolNameDefined("_PSfrontwindow")` 가 AppKit 없는 프로그램에서 0, GLQuake 에서 1; `NSLookupAndBindSymbol`+`NSAddressOfSymbol` 로 주소(`dyld.h:102-108`).  `_dyld_lookup_and_bind` 는 없는 심볼에서 프로세스를 죽이므로(`dyt.c`: "dyld: Undefined symbols") 쓰지 않는다.
- SDL 의 거절 처리(`SDL_openstepvideo.m:2629-2638`): verdict E_BUSY(5)·E_DST(3) 는 그 프레임만, 그 밖은 창을 영구히 막는다(barred).  거절된 프레임은 `StampRelease`(present 끔) → `glFinish`(미러: G5-1b 로 행 반전) → AppKit 경로로 그 프레임을 그린다 — 느리지만 옳다.
- 산술(python 검산): 보정 때 SDL 원점 (192,144)·서버 프레임 (191,143,642,503); 오른쪽 100·아래 50 끌면 서버 (291,93) → 목적지 = (192+100, 144−(93−143)) = (292,194) ✓.  PS 좌표는 y 가 위로 자라므로 y 는 부호 반전; 화면 높이·타이틀바 높이는 필요 없다(차이만 쓴다).

## 1. 설계

1. `OSRDNMesaWindow.c`(새 단위, libc 헤더 없음): 첫 사용 때 `NSIsSymbolNameDefined` 로 `_PSfrontwindow`·`_PScurrentwindowbounds` 를 묻고 있으면 묶는다(`osrdn_window_ready()`).  `osrdn_window_front_bounds(&x,&y,&w,&h)`: `PSfrontwindow` → `PScurrentwindowbounds`.  실패·없음 → 0.
2. `OSRDNMesaPresent.c`, 뒤집힌 모드의 첫 행(§G5-1b 의 "온전" 판정 자리)에서:
   - SDL 이 준 원점 `(dstX, dstY−(H−1))` 이 **보정값과 다르면**(SDL 이 이동을 처리했다) 지금 서버 프레임으로 다시 보정: `cal = {sdlX, sdlTop, bx, by, bw, bh}`.
   - 같으면 서버 프레임을 물어 `(bw,bh)` 가 보정과 다르면 **앞 창이 우리 창이 아니다**(메뉴·패널) → 이 프레임은 verdict E_BUSY 로 거절(SDL 이 AppKit 으로 그린다).  같으면 목적지 `= (sdlX + (bx−bx0), sdlTop − (by−by0))`(정수로 내림; PS 값은 실수).
   - 서버 질의가 없으면(도구·질의 실패) 오늘의 동작.
   - 이동량은 그 프레임의 행 폴백에도 적용한다(온전하지 않은 프레임의 행들이 옛 자리에 찍히지 않도록): 프레임의 첫 행에서 정한 이동량을 그 프레임의 모든 행에 더한다.
3. 옮겨진 목적지가 화면 밖이면 커널이 E_DST 로 거절(`osrdn_cp.m:3926`) → SDL 은 그 프레임만 AppKit — 기존 계약대로.
4. 계기: `OSRDN_TIME_QUERY` 자리(서버 왕복) 추가 — 프레임당 1 회, us 를 본다.
5. 하지 않는 것: SDL·Quake·커널 변경, AppKit 링크, ObjC.

## 2. 검사
- `tools/mesa/sim_present.py` 확장: 가짜 `NSIsSymbolNameDefined`/`NSLookupAndBindSymbol`/`NSAddressOfSymbol` 과 가짜 `PSfrontwindow`/`PScurrentwindowbounds`(시험이 값을 정함).  시나리오: (a) 질의 없음 → 오늘과 같음; (b) 보정 뒤 서버가 (+100, −50) 이동·SDL 원점 그대로 → 블릿 목적지 (292,194)(python 검산값); (c) SDL 원점이 새 값으로 바뀜 → 재보정, 이동량 0; (d) 앞 창 크기 다름 → ioctl 0·verdict 5; (e) 온전하지 않은 프레임의 행에도 이동량 적용.  변이: 이동량 미적용, y 부호, 재보정 누락, 크기 검사 누락.
- judge_m1b B3 허용 목록에 `_NSIsSymbolNameDefined`·`_NSLookupAndBindSymbol`·`_NSAddressOfSymbol`(이유 적음).  check_hook A1 금지 목록 대조(PS 연산자는 그리기 아님 — 확인).
- 실기: R1 월드 프레임(비용), `RDN-C`/present 계수, 그리고 **사용자 드래그 시험**(잔상 없음·메뉴를 열었다 닫아도 정상).

## 3. codex 교차검토 (한 주장·국지적)
주장: "present_rect 의 첫 행에서 (i) SDL 원점 변화로 재보정, (ii) 서버 프레임 이동량을 x 는 더하고 y 는 빼서 목적지에 반영, (iii) 앞 창 크기 불일치면 E_BUSY 거절 — 이 셋이면 드래그 중·후의 stamp 가 서버가 창을 그리는 자리에만 찍히고, SDL 의 거절 처리·kernel 의 E_DST·G5-1b 의 온전 판정·미러 반전과 충돌하지 않는다."  확인할 것: 드래그 중 SDL 이 프레임을 계속 보내는지(이벤트 루프가 막히지 않는지)는 코드로 못 보므로 실기; `PSfrontwindow` 가 우리 창을 돌려주지 않는 경우(메뉴·패널·다른 앱 활성) 와 SDL 의 INPUT_FOCUS 가드(`SDL_openstepvideo.m:2546-2549`)의 관계; PS 실수 좌표의 내림.

## 4. codex 교차검토 판정 (2026-09-29, gpt-6-astra, 한 주장·국지적) — 부분 성립, 설계 보강 (§1-1)

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| 거절 → release → AppKit: `SDL_openstepvideo.m:2636` 조건(E_BUSY 5·E_DST 3 만 예외), `SDL_openstepvideo.m:2688` release+glFinish, `SDL_openstepvideo.m:2702` AppKit present | 열어 확인 | ✅ |
| 재활성화는 `SDL_openstepvideo.m:2581` `if (!data->gl_stamping) { set_present_mode(1)`; 모드 OFF/ON 때 `OSRDNMesaPresent.c:61-74` 는 계수·hold 만 바꾸고 `presentRun`/`presentCover` 는 초기화 안 됨 | 열어 확인 | ✅ 채택 — 모드 ON 에서 보정·run·cover 초기화 |
| SDL 의 위치 변경 skip(`SDL_openstepvideo.m:2562-2565`)은 release 없이 FALSE → armed 아님 → 그 프레임은 present 모드가 켜진 채 AppKit 이 **낡은 배열**을 그린다(`SDL_openstepvideo.m:2662`) | 열어 확인 | ⚖️ SDL 의 기존 동작(이동 뒤 한 프레임 낡은 그림), 이 계획 범위 밖 — 기록 |
| SDL 범위엔 드래그 중 SwapWindow 를 막는 코드가 없다; glwin 은 타이머를 tracking 모드에도 넣고(`openstep-mga-glwin.m:451-458`) 이동 중이면 `return`(`openstep-mga-glwin.m:548-580`) | 열어 확인 | ✅ — 드래그 중 프레임이 오는지는 실기(잔상 자체가 증거) |
| 포커스 ≠ 앞 창(`SDL_openstepvideo.m:2542-2544` "메뉴·패널이 포커스 없이 덮을 수 있다"); glwin 은 **자기 창 번호**로 묻는다(`openstep-mga-glwin.m:496`), `![NSApp isActive]` 검사 `openstep-mga-glwin.m:534-536` | 열어 확인 | ✅ 채택 — `PSfrontwindow` 를 버리고 `PScurrentcontext`+`PSscreenlist` 로 **우리 창 번호**를 얻어 묻는다(§1-1) |
| 라이브러리 자체 거절은 `*outVerdict = 5UL` 을 명시하고 −1(`OSRDNMesaPresent.c:249-250` 기본 E_MODE; `OSRDNMesaPresent.c:396-404` 은 ioctl 결과만 집계), `OSRDNMesaPresent.h:56` 설명 확장 | 열어 확인 | ✅ 채택 |
| SDL 행 공식(`SDL_openstepvideo.m:2625-2627`)엔 예외 없음; 위 클립은 첫 `srcY ≠ 0`, 아래 클립은 `h < H`(`SDL_openstepvideo.m:2576-2577`) → `dstY−(H−1)` 을 늘 원점으로 못 읽는다; 이동량은 프레임 안에서 일관되게 | 열어 확인 | ✅ — G5-1b 의 "직전 프레임 온전" 판정 자리에서만 보정·병합; 이동량은 첫 행에서 정해 프레임 전체에 |
| "SDL 원점이 바뀌었다" 가 곧 "캐시 = 서버" 는 아니다(glwin 은 `openstep-mga-glwin.m:463-465` "캐시가 확실히 맞을 때" 보정) | 열어 확인 | ✅ 채택 — 두 프레임 연속으로 SDL 원점과 서버 프레임이 모두 그대로일 때만 보정(정지 상태) |

codex 줄번호 전부 실제와 일치(python 으로 출력해 대조).

## 1-1. 보강된 설계

- **창 식별**: `PScurrentcontext(&cid)`(`psops.h:89`) → `PScountscreenlist(cid, &n)`·`PSscreenlist(cid, n, list)`(`psopsNeXT.h:146`·`psopsNeXT.h:148`) 로 이 앱의 창 목록을 얻고, 그 가운데 서버 크기가 보정 크기와 맞는 창을 우리 창으로 고른다(GLQuake 는 창 하나).  이후 `PScurrentwindowbounds(ours, …)` 만 묻는다.  앞 창이 무엇이든 무관(메뉴·패널이 우리 창을 덮는 문제는 SDL 의 포커스 가드 몫, 기존과 같음).  탐침 `build/g51c/winprobe.m` 로 의미를 먼저 확인한다.
- **보정 시점**: 첫 행이 오고 직전 프레임이 온전했으며, SDL 원점과 서버 프레임이 **두 프레임 연속 같을 때** `cal` 을 잡는다.  그 뒤 SDL 원점이 바뀌면 보정을 버리고 다시 정지 상태를 기다린다(그 동안은 서버 프레임을 못 쓰므로 SDL 원점 그대로 — 드래그 직후 한두 프레임).
- **모드 ON** 에서 `presentRun`·`presentCover`·보정을 초기화한다.
- 자체 거절(창을 못 찾음·서버 질의 실패·이동한 목적지가 음수)은 `*outVerdict = OSRDN_PRESENT_E_BUSY`, `refused[E_BUSY]++`, −1.

## 0-1. 탐침 결과 (`build/g51c/winprobe.m`, 실기 2026-09-29) — 설계를 바꾼 사실

- 640×480 내용을 (200,200) 에 놓은 창의 서버 경계 = 프레임 = (199,199) 642×504, 지역 창 번호 4.  `PScurrentwindowbounds(4)` 는 이 값을 돌려준다.
- `PSfrontwindow` = 39(다른 앱의 창; 우리 앱은 비활성), `PSscreenlist(cid)` = 180 179 — **서버 전역 번호**이고, 그 번호로 `currentwindowbounds` 를 부르면 `rangecheck` DPS 오류(AppKit 이 NSException 으로 올린다; `DPSSetErrorProc` 로 막히지 않음 — 14 회 예외).  → §1-1 의 "screenlist 로 우리 창" 은 **불가**.  라이브러리에서 DPS 오류는 곧 앱 붕괴이므로, 유효하다고 아는 지역 번호에만 물어야 한다.
- ObjC 런타임을 런타임 바인딩(`_NSApp`·`_objc_msgSend`·`_sel_getUid`)으로 부르면 ObjC 앱 안에서 충돌 없이 동작: `[NSApp windows]` 6 개 → `[2 vis=0 256×128] [3 vis=0 193×208] [4 vis=1 199,199 642×504] [7 vis=1 64×64] [8 vis=0] [10 vis=0]`, 예외 0.  **가시이고 프레임이 내용 크기 + (0..16, 0..48) 인 창 하나** = 우리 창.  (순수 C 프로그램에서 같은 바인딩은 `__objcInit` 중복으로 dyld 가 죽였다 — `dyt5.c`; 라이브러리는 `NSIsSymbolNameDefined("_NSApp")` 가 참일 때만, 즉 AppKit 앱에서만 바인딩한다.)
- §1-1 정정: 창 식별은 `NSApp → windows → windowNumber`(런타임 ObjC) + `PScurrentwindowbounds`; `PScurrentcontext`·`screenlist` 는 쓰지 않는다.

## 5. 구현 (2026-09-29, 라이브러리 **790599970**, 실측 전)

- `mesa/OSRDNMesaWindow.c/.h`: `NSIsSymbolNameDefined` 로 `_NSApp`·`_objc_msgSend`·`_sel_getUid`·`_PScurrentwindowbounds` 를 한 번 묶고(없으면 "질의 없음"), `[NSApp windows]` 를 돌며 **가시이고 프레임이 (W..W+16)×(H..H+48)** 인 창 하나를 우리 창으로(둘이면 거절), 그 지역 번호로 서버 프레임을 묻는다.
- `mesa/OSRDNMesaPresent.c`: 온전한 프레임의 첫 행에서 `presentShiftFor` — 보정은 **두 프레임 연속 SDL 원점·서버 프레임이 같을 때**, 그 뒤 이동량 `(+Δx, −Δy)`; SDL 원점이 바뀌면 보정을 버린다; 창을 못 찾으면 그 프레임을 `E_BUSY` 로 거절; 이동한 목적지가 음수면 `E_DST`.  이동량은 그 프레임의 행 폴백에도 적용.  present 모드 ON 에서 run·cover·보정 초기화.  계수기 `windowFinds`·`windowLost`·`calibrations`·`shifted`, 계측 자리 `OSRDN_TIME_QUERY`.
- 검사: `tools/mesa/sim_present.py` 에 가짜 AppKit/ObjC/DPS 를 두고 시나리오(정지 → 드래그 중 이동량 적용 (110,70) → SDL 이 중간에 따라잡음 → 정착 뒤 재보정 → 창 분실 E_BUSY → 복구 → 위로 벗어남 E_DST) + G5-1c 변이 4 종(y 미적용·y 부호·첫 눈에 보정·크기 검사 누락) PASS; check_compile·check_hook·check_units·sim_time PASS; judge_m1b B3 PASS(런타임 조회 3 심볼 허용).
- 헤더 미러: `ref/openstep/headers/NextDeveloper/Headers/AppKit/psopsNeXT.h`·`dpsclient.h` 를 실기에서 가져옴(인용용).

## 1-2. 첫 실기 뒤 규칙 변경 (2026-09-29): 이동 중에는 찍지 않는다

- 790599970(§5) 으로 사용자 시험: 잔상이 여전했고 **검은 사각형이 Workspace 의 dock 을 덮는** 경우도 보고됐다.  원인 분석: 드래그 중 SDL 원점이 중간중간 갱신되면(`windowDidMove` 가 여러 번) 보정이 버려지고 "정지 2 프레임" 을 기다리는 동안 SDL 원점 그대로 찍혔다 — 즉 드래그 중의 stamp 가 옛 자리(들)에 남는다.  서버 위치를 매 프레임 따라가도, stamp 뒤에 서버가 창을 옮기면 그 한 프레임은 옛 자리에 남는다(경쟁).  glwin 은 `moving` 이면 아예 찍지 않는다(`openstep-mga-glwin.m:548-580`).
- 규칙: 첫 행마다 서버 프레임을 묻고, **직전 질의와 다르면(이동 중) 그 프레임을 E_BUSY 로 거절** — SDL 이 그 프레임을 AppKit 으로 그린다(창 안에만, 잔상 불가).  두 질의 연속 같으면(정지) 찍는다: 보정이 서 있고 SDL 원점이 보정 때와 같으면 서버 이동량을 적용, SDL 이 이동량과 **일치하게** 따라잡았으면 보정을 갱신, 그 밖(미보정·불일치)은 SDL 원점과 서버가 각각 두 번 같아질 때까지 거절(`unsettled`).  보정과 정지 감시는 present 모드 토글(거절마다 SDL 이 끄고 켠다)을 넘어 유지.
- 경쟁(질의와 블릿 사이에 서버가 옮김)은 남는다 — 한 프레임, 드래그 시작 순간에만.  glwin 의 이벤트 큐 peek 는 게임 입력(마우스 이벤트 상시)과 양립하지 않아 쓰지 않는다.
- 검사: `sim_present.py` 를 두 실행(b: AppKit 없음, c: AppKit 앱)으로 나눠 c 에 정지→드래그(거절)→일시정지(이동량 적용)→SDL 따라잡음(일치 재보정)→분실→복구→위로 벗어남 시나리오, 변이 11 종 PASS.  계수 근거는 스크립트 주석에.

## 6. 사용자 확인 (2026-09-29, 라이브러리 **790602422**)

- 사용자: "약간의 잔상이 남지만 충분히 사용 가능한 수준" — 드래그·dock 근처·메뉴 시험 통과.  남는 잔상은 §1-2 의 경쟁(드래그 시작 순간의 한 프레임).
- 그 인스턴스의 계수(`RDN-P`, 53 초·1,664 프레임): rects 5,975 = coalesced **1,655** + rowfallback 2,400(= 5 프레임 × 480: 첫 프레임과 거절 뒤 재개 프레임들) ; finds 1, calibrations 2, **shifted 0**(찍힐 때는 SDL 이 이미 따라잡은 뒤였다), busy 3(이동 중 거절: 드래그 3 회), lost 0, dst 0.  서버 질의 1,658 회, 프레임당 1.
- G5-1c 종결.  월드 프레임 비용: 서버 질의 ~0.5 ms/프레임(G5-1b 17.3 → 20.0 ms 실측은 실행 간 편차 포함; 격프레임 질의는 후속 선택지).
