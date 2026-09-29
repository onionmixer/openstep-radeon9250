# G3 — 화면 제시(present) 경로: 카드가 그린 것을 VRAM→화면 블릿으로 내보낸다 (계획, 2026-09-26)

사용자: "완성된게 아닌데 릴리즈 준비는 아무런 의미가 없습니다."  완성 = **화면에서 가속된 teapot**.
실측(`docs/G1_REMAINING.md` 2026-09-26): SDL2 teapot 800×600, 가속 링크 render+finish **1124.6 ms**(0.63 fps), 소프트웨어 11.1 ms(12.1 fps).  카드는 그렸다(커널 로그 `RDN-R7B submit … drawn=1`); 느린 것은 `glFinish` 의 VRAM 되읽기(1.9 MiB, Matrox 실측 746 ns/화소)와 AppKit 전달이다.

## 1. 참고가 이미 답하는 것 (원문 확인)

| 물음 | 답 | 근거 |
|---|---|---|
| 제시를 어떻게 하나 | **CP 로 보내는 2D 블릿**: `PACKET0(WAIT_UNTIL,0) 3D_IDLECLEAN|HOST_IDLECLEAN(0x00060000)` → `PACKET0(DP_GUI_MASTER_CNTL,0)` GMC → `PACKET0(SRC_PITCH_OFFSET,1)` src,dst → `PACKET0(SRC_X_Y,2)` `x<<16|y`, `x<<16|y`, `w<<16|h` → `PACKET0(WAIT_UNTIL,0) 2D_IDLECLEAN|HOST_IDLECLEAN(0x00050000)` = 13 워드.  `CP_PACKET0(reg,n)` 의 n 은 **레지스터 수 − 1** | FreeBSD `radeon_state.c:1343-1400` `radeon_cp_dispatch_swap`; WAIT 값 `radeon_drv.h:1906-1922`; 매크로 `radeon_drv.h:1891-1892` |
| GMC 워드 | `SRC_PITCH_OFFSET_CNTL(1<<0) | DST_PITCH_OFFSET_CNTL(1<<1) | BRUSH_NONE(15<<4) | (6<<8 ARGB8888) | SRC_DATATYPE_COLOR(3<<12) | ROP3_S(0xcc0000) | DP_SRC_SOURCE_MEMORY(2<<24) | CLR_CMP_CNTL_DIS(1<<28) | WR_MSK_DIS(1<<30)` | 같은 함수; 비트는 `radeon_reg.h:683-737` |
| 레지스터 | `DP_GUI_MASTER_CNTL 0x146c`, `SRC_PITCH_OFFSET 0x1428`, `DST_PITCH_OFFSET 0x142c`, `SRC_X_Y 0x1590`(x<<16|y), `DST_X_Y 0x1594`, `DST_WIDTH_HEIGHT 0x1598`(w<<16|h), `WAIT_UNTIL 0x1720` | `radeon_reg.h:683`, `:784`, `:792`, `:797`, `:1580`, `:1585`, `:1705`; **주의** R4 의 MMIO 경로가 쓴 `SRC_Y_X 0x1434`·`DST_Y_X 0x1438` 와 다른 CP 용 레지스터다(`R4_ENGINE_PLAN.md` 1-1) |
| 피치·오프셋 인코딩 | `(pitch_bytes/64)<<22 | (카드주소>>10)`; 우리 카드주소 = VRAM 오프셋(MC_FB_LOCATION) | `R4_ENGINE_PLAN.md` 1-2, `radeon_cp.c:1315-1317` |
| 화면과 창 | 화면(스캔아웃)은 **카드 주소 0**(`CRTC_OFFSET` 0, `osrdn_mode.m:547-548`), 1024×768 RGB:888/32, rowBytes 4096.  클라이언트 창(오프스크린 표면들)은 `[winStart, winEnd)` = `[0x400000, …)`(`OSRDNDisplay.m:488-497`, caps.winStart) — 색 표면은 창 오프셋 0 = 카드 주소 `winStart` | 부팅 3 `osrdncaps`, `osrdn_r7b.h` caps.winStart |
| 응용과의 계약 | `SDL_OpenStepGLPresent{abi,size, surface_origin(), set_present_mode(on), present_rect(srcX,srcY,w,h,dstX,dstY,&verdict)}` 를 `SDL_SetWindowData(win, "OpenStep.GL.VRAMPresent", &hooks)` 로 등록.  **SDL2 는 바꾸지 않는다** — 계약의 목적이 "라이브러리만 바꿔 링크" 이다(사용자 지적 2026-09-26).  SDL 은 `dstX/dstY` 를 화면 **좌상단 원점**으로 주고 화면 밖을 잘라 비음수 rect 를 만들며(`SDL_openstepvideo.m:2523-2534`), 표면이 아래→위 순서라 **행마다 역순으로 `present_rect(…, h=1, …)` 를 부른다**(`:2560-2598`; Matrox 실측 행당 7.21 us, 800×600 8.01 ms/프레임).  이동·가림(focus)·expose 는 SDL 이 처리하고 거절 시 되읽기 경로로 내려간다 | `SDL_openstepglpresent.h`, `SDL_openstepvideo.m:2599-2650` |
| 커널 게이트·판정 | magic → 모드/등록 → 걸쇠 → busy → 32bpp → 기하(0·0xffff 초과·stride 0x8000 초과) → dst 가 화면 안 → src 원점이 창 안·64 B 정렬 → src 사각형이 창 안 → 엔진 idle → 블릿 → 판정 `OK/E_MAGIC/E_SRC/E_DST/E_GEOM/E_BUSY/E_LATCH/E_MODE` | Matrox `OpenStepMGAReplacementDisplay.m:6360-6500` `runHW3DPresent`, `OpenStepMGAHW3D.h:1414-1421` |
| 라이브러리 쪽 | `PresentMode(on)` 은 미러를 세우고(되읽기 0 회), `PresentRect` 는 ioctl 하나(VRAM→VRAM, 버스 안 넘음) | Matrox `OpenStepMGAMesaBuffer.c:746-818` |
| 방향 | blit 은 행을 못 뒤집는다 — 데모가 절두체 top/bottom 을 바꾸고 컬링을 뒤집는다(Matrox glwin·SDL teapot 의 PRESENT 모드); **시험으로 고정** | Matrox `C8_SDL2_VRAM_PRESENT_PLAN.md` §6 |
| expose | SDL 뷰의 `drawRect:` 가 낡은 비트맵을 도장 위에 그린다 → SDL 포트가 expose 뒤 재제시·가드로 처리(이미 포트에 있음) | C8 §5.5, `SDL_openstepvideo.m` StampArm |
| 커널이 직접 조립한 CP 작업의 선례 | `cpZclear` 가 `cpR6Words` 를 **WAIT 부터 꼬리까지 직접** 채워 `cpR6Submit` 으로 낸다; `cpR6Submit` 은 접두·꼬리를 붙이지 않고 16 워드 경계까지 PACKET2 로 채운 뒤 WPTR 되읽기 → rptr 도달 → idle 두 대기만 한다(seed 꼬리 불필요); 검증기 `cpR7Verify` 는 클라이언트 워드(`CP_R7_CASE`)에만 | `osrdn_cp.m:3031-3200`, `osrdn_cp.m:2357-2381`, `osrdn_cp.m:3142-3157`, `osrdn_cp.m:3348-3358` |
| ioctl 블록 한계 | 128 B 미만(IOCPARM_MASK 0x7f), 크기 128 은 0 으로 감겨 조용히 깨짐 → `_fits` typedef | `osrdn_r7b.h:102-177` |

## 2. 설계

### 2-1. 드라이버 — 새 ioctl `OSRDN_R7B_IOC_PRESENT`(그룹 'R', 번호 4)
블록(10 워드 = 40 B): `magic, version, srcOrg, srcStride(px), srcX, srcY, w, h, dstX, dstY` in / `status, verdict` out → 12 워드 48 B.  `_fits` typedef 추가.
핸들러 `r7bPresent:` 는 `r7bSubmit2:` 와 같은 자리(`OSRDNDisplay.m:263`)에서 분기, **Matrox 게이트를 같은 순서로**:
1. magic/version → `E_MAGIC`.
2. 모드 선택·32bpp·CP `RUNNING`·`failed/latched` 아님 → `E_MODE`/`E_LATCH` (cp 상태는 `osrdn_mode_cp` 의 새 op `CP_OP_PRESENT` 안에서 본다 — ZCLEAR 와 같은 통로, 클레임 아래).
3. 기하: `w,h ∈ [1,0xffff]`, `srcStride ∈ [1,0x8000]`, **`srcStride*4 % 64 == 0`**(피치 필드가 64 B 단위; 폭 16 화소 배수) → `E_GEOM`.
4. dst: `w ≤ modeW, dstX ≤ modeW−w, h ≤ modeH, dstY ≤ modeH−h` → `E_DST`.  화면 밖은 응용이 미리 자른다(SDL 의 rect 형).  화면은 카드 주소 0 부터 rowBytes 피치.
5. src: `srcOrg` 는 **창 오프셋**(카드 주소 = `winStart + srcOrg`); `srcOrg < winEnd − winStart`, `srcOrg % 64 == 0`, `srcX + w ≤ srcStride`, 마지막 행·꼬리가 `winEnd − winStart` 안(Matrox 의 avail/lastRow/tail 산술 그대로, 넘침 없는 형태) → `E_SRC`.
6. 워드 조립(`cpPresent`, 커널 정적 배열 13 워드, 참조와 같은 순서): `[P0(WAIT_UNTIL,0), 0x00060000]`, `[P0(GMC,0), gmc]`, `[P0(SRC_PITCH_OFFSET,1), srcPO, dstPO]`, `[P0(SRC_X_Y,2), srcX<<16|srcY, dstX<<16|dstY, w<<16|h]`, `[P0(WAIT_UNTIL,0), 0x00050000]`; `srcPO = (srcStride*4/64)<<22 | (winStart + srcOrg)>>10`, `dstPO = (rowBytes/64)<<22 | 0`(화면은 카드 주소 0); `gmc` 의 32bpp 는 `GMC_DST_32BPP (6<<8)`.  다중 레지스터 PACKET0 매크로 `C_P0N(reg,n)`(`n<<16 | reg>>2`) 을 추가.  `cpR6Submit` 은 접두·꼬리를 **붙이지 않으므로** 두 WAIT 는 여기서 조립한다.  걸쇠·복구는 기존 경로 그대로.
   **행 단위 비용이 관건**: SDL 이 800×600 을 600 번 부른다.  한 호출 = ioctl + 16 워드 링 쓰기(비캐시 ~69 ns/워드) + WPTR 되읽기 + rptr 대기(16 워드 소비) + idle 대기(800 화소 블릿 ~1 us) ≈ **15–20 us 추정** → 프레임당 ~10 ms(Matrox 8 ms 와 같은 급).  실기 2 단계가 실측한다; 20 fps 를 못 넘으면 다음 칸은 "마지막 행까지 대기 생략" 같은 제출 경량화이지 SDL 변경이 아니다.
7. 판정: `OK` / `E_BUSY`(클레임 BUSY) / `E_LATCH`(LATCHED·RECOVERED 는 이번 프레임 거절, 다음 프레임 재시도).  카운터 `presentOk/presentRefused[verdict]`, 로그는 첫 1 회 + 거절 종류별 첫 1 회(msgbuf 4 KB) — **행마다 로그 금지**(`RDN-R7B submit` 줄은 제출마다 찍히므로 present 는 그 경로를 타지 않는다).
8. 통로: `osrdn_mode_cp` 는 `arg,len` 만 받으므로 **`osrdn_mode_present(mode, base, cp, latched, blk)`** 를 둔다 — 클레임을 잡은 뒤 `cp->presentReq = blk` 를 놓고 `osrdn_cp_run(CP_OP_PRESENT)` → `cpPresent` 가 클레임 안에서 로컬 13 워드를 조립(공유 staging 없음, codex 지적).
9. 대기 정책: `cpWait` 는 첫 폴링 뒤 `IODelay(10)` 단위(`osrdn_cp.m:224-287`; M2b 는 스핀이 3 % 밖에 못 얻어 끄기로 함 `M2B_PLAN.md:188-203`).  1 행 블릿은 10 us 안에 끝나므로 행당 두 대기 ≈ 20 us + 제출 고정비(fence 직렬화·16 워드 쓰기·WPTR 되읽기) + ioctl ≈ **30–40 us 추정** → 800×600 18–24 ms.  실기 2 단계가 잰다; 스핀 손잡이는 M2b 의 음성 결과대로 건드리지 않는다.
- 울타리(M3h `RDNTeapotFence`)와의 관계: 제시는 화면(창 밖)에 쓰는 것이 목적이라 울타리와 양립 못 한다 → 울타리 켜진 부팅에서는 `E_MODE` 로 거절(표로 명시).

### 2-2. 라이브러리 (`mesa/OSRDNMesaSurface.c`, 새 `mesa/OSRDNMesaPresent.c`) — SDL2 는 그대로, 링크만 바꾼다
- **소유 검사**: 세 함수 모두 `osrdn_surf_bound_to(OSMesaGetCurrentContext())` 로 **현재 컨텍스트가 표면의 주인일 때만** 동작한다(`osmesa.c:1994` `osmesa == ctx->DriverCtx`, 소유 키와 같다).  소프트웨어로 간 두 번째 컨텍스트가 첫 표면을 찍지 못한다(codex 지적).
- `unsigned long OSRDNMesaBufferOrigin(void)`: 현재 컨텍스트가 주인이면 **1**(카드 주소는 0 이라 "0 = 없음" 계약과 충돌; SDL 은 예/아니오로만 쓴다 — 헤더 주석에 명시), 아니면 0.
- `void OSRDNMesaBufferPresentMode(int on)`: `surfPresent` 플래그.  **미러 억제는 `glFinish` 경로(`osrdnHookFinish`)에서만** — 명시적 읽기(`osrdnHookRenderFinish`, `OSMesaGetColorBuffer`)와 해제(leave/release) 는 그대로 복사한다(M3g 계약 유지, codex 지적).  Finish 의 억제는 `finishStoodDown++` 로 센다.  on 이면 장치 fd 를 **붙잡는다**(아래).
- `int OSRDNMesaBufferPresentRect(...)`: 주인이 아니면 −1(verdict E_MODE); 블록을 채워(`srcOrg = 0`, `srcStride = surfRowPixels`) 보낸다; 판정 카운터.
- **fd 관리자 하나**: 드라이버는 open 마다 `RDN-R4 open/close` 를 로그하고 open 은 단일 걸쇠다(`OSRDNDisplay.m:184-236`).  행마다 열면 로그 600 줄·걸쇠 충돌.  기존 `triHeldFd`(환경변수 `OSRDN_TRI_HOLD`)를 **프로그램적 hold** 로 확장: `osrdn_tri_hold_set(1)` 이면 `triOpen` 이 fd 를 붙잡고 `triClose` 가 안 닫는다; present 는 `triOpen()/triClose()` 를 그대로 쓴다.  PresentMode(0)·표면 해제에서 hold 해제(`osrdn_tri_hold_set(0)` → 닫는다).  삼각형 경로와 present 가 같은 fd 를 쓴다.
- 카운터 노출 `OSRDNMesaPresentCounts(...)`(ok/refused[8]/stoodDown).

### 2-3. 데모 `test/osrdn-sdl-teapot.c`
Matrox `openstep-mga-sdl-teapot.c` 를 복사해 심볼만 radeon 것으로(카운터: drawn/batches/refused/mirrors/present).  `OSRDN_SDLTEAPOT_PRESENT=1` 이면 hooks 등록 + 절두체 뒤집기(Matrox 와 동일 로직).  빌드 줄은 지난 실측과 같고 PLAIN 만 뺀다.

### 2-4. 호스트 검사 (코딩 단계)
- `tools/r5/sim/world5.c`: **원시 링 캡처** — `wptrWritten` 이 실행 전 old-rptr→wptr 의 워드를 배열에 복사(codex 지적: `R6W` 는 해석된 레지스터만 찍어 헤더·묶음을 못 본다).  `CP_OP_PRESENT` 시험: 게이트 8 종 각각의 거절(판정값, `ioWr == 0`), 통과 시 캡처된 **앞 13 워드가 python 오라클(`tools/r7/present_oracle.py`, 참조 함수를 그대로 옮긴 것)과 일치**하고 뒤 3 워드는 PACKET2, 레지스터 모델 `R(0x146c)…R(0x1598)` 값 일치, 피치·오프셋 인코딩(python 으로 800×600·1024×768·srcOrg 0·winStart 0x400000 표), 걸쇠 뒤 거절.  `tools/r7/sim_present.py` 가 `sim_r6.py` 처럼 출력을 파싱해 오라클과 대조.  변이: GMC 비트 하나 빠짐, DST_X_Y 순서 바뀜, 폭 16 배수 검사 제거, dst 경계 `<` 오류, src 꼬리 검사 제거, WAIT 에서 HOST 비트 빠짐 — 각각 FAIL.
- `check_r5_src.py` 규칙: `cpPresent` 는 `cpR7Verify` 를 부르지 않고 `cpR6Submit` 만; 상수는 이 파일이 명명한 값과 XOR 게이트.
- `check_reloc_r2b0.py` 호출자 표에 `_cpPresent`.  인용 검사·`check-all` PASS.
- 라이브러리: `hostcheck` 의 링크·심볼 검사에 새 파일 추가; 데모는 타깃에서만 빌드.

### 2-5. 실기 (재부팅 1 회 — **사용자 승인 필요**, 예산 3 회는 소진됨)
1. 마운트 → gcdsd(**사용자**: 화면 창) → caps 로 stamp 확인.
2. 데모 소프트웨어 링크 1 회(기준 그림·fps), 가속 링크 되읽기 경로 1 회(카운터: drawn/mirrors — **1124 ms 의 내역**이 여기서 나온다: mirrors 가 프레임당 1 회인지 여러 회인지).
3. `OSRDN_SDLTEAPOT_PRESENT=1` 가속 링크: 판정 카운터(refused 0), **되읽기 0 회**, fps, 사용자가 그림·방향을 본다(뒤집히면 절두체 스위치 반대 — 데모 코드만 바꾸면 되고 재부팅 불필요).
4. 커널 로그: `RDN-R7B present` 첫 줄, 걸쇠 0.
5. 되돌림: 제시가 거절되면 SDL 이 되읽기 경로로 내려간다(화면은 여전히 그려짐, 느릴 뿐).
성공 기준: 800×600 에서 제시 경로 fps 가 소프트웨어 12 fps 를 넘고 되읽기 0, 그림이 소프트웨어와 같다(방향 포함).

## 3. 위험·모르는 것
- **프레임당 나머지 비용**(클리어·zclear·표면 준비): Matrox 는 14 ms 였다; 우리는 미측정 — 실기 2 단계가 답한다.  되읽기를 없애도 12 fps 를 못 넘으면 다음 칸은 그 비용이다.
- CP 블릿이 3D 상태를 건드리는지: 참조는 매 swap 마다 같은 링에서 한다 — 같은 순서(3D idle 앞, 2D idle 뒤)를 지키면 참조와 같다.
- 화면 쓰기는 WindowServer 모르게 일어난다(Matrox 와 같은 절충; SDL 의 가드는 focus 기반이라 메뉴·패널 가림은 못 본다 — `SDL_openstepvideo.m:2489-2505`, 코드 자체가 명시).
- SDL 의 세로 부분 잘림: 위가 잘리면 `srcY=-dstY` 로 올리지만 아래가 잘릴 때는 `srcY` 를 안 옮긴다(`:2530-2533`) — 역순 행 복사에서는 잘못된 세로 구간이 보일 수 있다(codex 지적, 원문 확인).  SDL 포트의 결함으로 별건 기록(`openstep-sdl20`), 이 칸에서는 창을 화면 안에 두고 잰다.
- 폭 16 배수 제약(피치 64 B): 데모 800·1024 는 통과; 일반 응용은 거절 판정으로 알 수 있다.

## 4. 하지 않는 것
15/16bpp 화면 제시(RGB:555 모드는 별도), 부분 갱신 최적화, WindowServer 합성과의 동기(수직귀선 대기), 되읽기 경로 자체의 가속.

## 5. codex 교차검토 판정표 (계획 단계, 2026-09-26)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 13 워드의 레지스터·좌표 패킹은 참조와 같다 | `radeon_state.c:1377-1401` 원문 | ✅ |
| GMC 32bpp 상수명은 `GMC_DST_32BPP (6<<8)` | `radeon_reg.h:705` 원문 | ✅ 채택(값은 같았다, 이름만) |
| 두 WAIT 는 HOST 비트 포함(0x60000/0x50000) | `radeon_drv.h:1906-1922` 원문 | ✅ 채택 — 계획 수정 |
| `CP_PACKET0(reg,n)` 의 n 은 레지스터 수 − 1 | `radeon_drv.h:1891`, `radeon_state.c:1389` | ✅ 채택 — 표기 수정 |
| `cpR6Submit` 은 접두·꼬리를 안 붙이고 16 워드 패딩만 | `osrdn_cp.m:2370-2381` 원문 | ✅ 채택 — **내가 틀렸다**(요약 기억이 잘못돼 있었다), cpPresent 가 WAIT 둘을 직접 조립 |
| `cpR7Verify` 생략 근거는 cpZclear 와 같다 | `osrdn_cp.m:3142-3157`, `osrdn_cp.m:3348-3358` | ✅ |
| SDL 의 dst 는 좌상단 원점, 화면 밖은 StampArm 이 자른다 | `SDL_openstepvideo.m:2523-2534` 원문 | ✅ |
| SDL 은 행마다 역순으로 부른다 | `:2560-2598` 원문("ROW BY ROW, IN REVERSE") | ✅ — 설계의 핵심 제약으로 반영(행 단위 비용) |
| 아래쪽 잘림 때 `srcY` 미조정 결함 | `:2530-2533` 원문 | ✅ 별건 기록 |
| 메뉴·패널 가림은 못 본다 | `:2489-2505` 원문 | ✅ 사실, Matrox 와 같은 절충 |

내 추가 실수(사용자 지적): 위 결과를 보고 "SDL2 에 `present_flip` 을 더해 재빌드" 를 제안했다 — 계약의 목적이 "라이브러리만 바꿔 링크" 인데 그것을 깼을 것이다.  철회.  대신 커널 제시 ioctl 을 행 단위 호출에 싸게 만든다(2-1 6).

## 6. codex 교차검토 판정표 2 (수정 계획, 2026-09-26)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 행당 15–20 us 는 과소: 첫 폴링 실패 시 `IODelay(10)`, 대기 둘 | `osrdn_cp.m:224-287` 원문(폴링 → 스핀 → `IODelay(C_TICK_US)`), `M2B_PLAN.md:188-203`(ZCLEAR 대기 58 us, 스핀 −3 %) | ✅ 채택 — 30–40 us 로 고침, 스핀 손잡이는 M2b 대로 안 켠다 |
| `cpSubmitFence` 직렬화·MMIO read 고정비, WBINVD 는 기본 꺼짐 | `osrdn_cp.m:741-760` | ✅ 사실(추정에 포함) |
| 클레임은 splhigh 플래그 교환, BUSY 즉시 반환 | `osrdn_mode.m:911-924` | ✅ |
| `osrdn_mode_cp` 는 `arg,len` 뿐 → 전용 진입·클레임 안 조립 | `osrdn_mode.m:1442-1444` 원문 | ✅ 채택 — `osrdn_mode_present` + `presentReq` |
| 미러 전체 억제는 M3g·명시적 읽기·해제·거절 fallback 을 깬다 | `OSRDNMesaHook.c:1408-1425`, `OSRDNMesaHook.c:1978-1987`, `OSRDNMesaSurface.c:341-353` 원문 | ✅ 채택 — Finish 에서만 억제 |
| 두 번째 컨텍스트가 첫 표면을 present 할 수 있다 | `OSRDNMesaSurface.c:176-179`(단일 owner) | ✅ 채택 — 현재 컨텍스트 = owner 검사(`osmesa.c:1994`) |
| `OSRDNMesaProbeDeviceFd` 없음, open 마다 로그, 단일 걸쇠 → 공유 fd 관리자 | `OSRDNDisplay.m:213-236` 로그, `OSRDNMesaTri.c:373-411` `triHeldFd` | ✅ 채택 — hold 를 프로그램적으로 |
| world5 에 원시 링 기록기가 없다(R6W 는 해석된 쓰기) | `world5.c:222-223`, `world5.c:1214-1215` | ✅ 채택 — `wptrWritten` 캡처 + `sim_present.py` |

## 7. 구현 기록 (2026-09-26, 코딩 — 계획 검토 2 회 뒤)

| 자리 | 변경 |
|---|---|
| `osrdn_r7b.h` | `osrdn_r7b_present`(12 워드 48 B) + `OSRDN_R7B_IOC_PRESENT`(그룹 'R' 4) + `_fits`; 판정 `OSRDN_PRESENT_*`(Matrox 번호: DST 3, BUSY 5); 커널 내부 `osrdn_cp_present_req`(blk·modeW/H·rowBytes·bytesPerPixel·verdict out) |
| `osrdn_cp.h` | `CP_OP_PRESENT 20`(`CP_OP_LAST 20`), `CP_WHY_PRESENT 37`, 상태에 `presentReq`·`presentVerdict`·`presentOk`·`presentRefused[8]` |
| `osrdn_cp.m` | 2D 레지스터·`C_P0N(reg,n)`·`C_PRESENT_GMC 0x52cc36f3`·WAIT PRE/POST(HOST 비트 포함); `cpPresentRefuse`/`cpPresent`(게이트 → 13 워드 로컬 조립 → `cpR6Submit`); 디스패치 |
| `osrdn_mode.h/.m` | `osrdn_mode_present(mode, base, cp, latched, req)`: 클레임 → `presentReq` 놓고 `osrdn_cp_run(CP_OP_PRESENT)` 조용히 → 판정을 `req->verdict` 로(공통 게이트 거절은 latched 면 LATCH, 아니면 MODE) |
| `OSRDNDisplay.m/.h` | ioctl 디스패치 + `r7bPresent:`(화면 = `osrdn_res(rdnMode.res)`·`displayInfo->rowBytes`·`fmt->bytes`; rc→status/verdict; **판정별 1 회만 로그** `RDN-G3 present`) |
| `osrdn_modelog.m`, `tools/r5/rdnr5cp.m` | op 이름표에 "present" |
| `mesa/OSRDNMesaPresent.h/.c` | `OSRDNMesaBufferOrigin/PresentMode/PresentRect`(현재 컨텍스트 = 표면 주인일 때만), `OSRDNMesaPresentCounts/VerdictName`, `osrdn_present_active` |
| `mesa/OSRDNMesaTri.c/.h` | `osrdn_tri_hold_set`(프로그램적 fd 보유), `osrdn_tri_device_open/close` |
| `mesa/OSRDNMesaHook.c/.h` | `osrdnHookFinish`: flush → present 중이면 `finishStoodDown++` 후 복사 없이 반환 → 아니면 미러 |
| `tools/mesa/target-build-mesa.sh` | 단위 목록·`ld -r` 에 `OSRDNMesaPresent` |
| `test/osrdn-sdl-teapot.c` | Matrox SDL teapot 을 python 으로 변환(심볼 매핑 shim + 보고부); `OSRDN_SDLTEAPOT_PRESENT=3` 이 SDL 훅 등록 |
| 검사 | `tools/r7/present_oracle.py`(참조식 13 워드, 자체검사); `world5.c`: 원시 링 캡처 + PRESENT 시험(거절 16 종·13 워드·PACKET2 패딩·2D 레지스터·두 번째 행·failed·걸쇠 뒤); `sim_r5.py`: `present_expect.h` 생성 + 변이 8; `check_r5_src.py`: `g3-present` 규칙(검증기 미사용·`cpR6Submit` 1 회·게이트 문자열·상수 XOR 게이트·SDL 판정 번호·클래스 로그 1 회) + 자체 변이 3; `check_hook.py`: M3g 규칙을 present 게이트까지 정밀화 + 변이 2; `check_units.py` 앵커 |

결과: `hostcheck-r2b0` PASS, `sim_r5` PASS(변이 79), `check_r5_src` PASS, `check_compile/check_units/check_hook` PASS.  `check-all` 은 아래 8 절.

## 8. 호스트 게이트·설치 (2026-09-26)

| 게이트 | 결과 |
|---|---|
| `bash tools/check-all.sh` | **PASS** (인용 재조준 뒤 — 편집 전 사본을 역패치로 복원하다 빈 줄 하나가 어긋나 스위트를 두 번 더 돌렸다; 기억 `gate-cheap-checks-before-the-suite`) |
| 타깃 드라이버 빌드 **`481d68ae`** / runid 790399831, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — reloc sum 10959 509, `Instance0.table` 1024×768 RGB:888/32 |
| 라이브러리 `target-build-mesa.sh` runid **790399871**(`OSRDNMesaPresent` 포함) | **RDNMESA PASS** |

부팅 절차: `build/g3/run_g3.sh` — `LIBRUN=790399871 BOOT=<nonce> BUILD=481d68ae bash build/g3/run_g3.sh`(사용자 gcdsd; CP 기동 → 데모 3 종 빌드 → sw / 되읽기 / PRESENT=3 각 40 프레임 → `RDN-G3` 줄).  사용자는 세 창의 그림·방향을 본다.

## 9. 부팅 4 (드라이버 481d68ae, 부팅 07328757, 2026-09-26) — 제시는 동작, 병목은 둘

`run_g3.sh`(`build/g3/run-790402030`), 800×600·40 프레임: 소프트웨어 10.8+7.0 ms(11.8 fps) / 되읽기 962+434 ms(0.68 fps) / **PRESENT=3: render 335 ms + 도장 18.9 ms(2.8 fps), 행 34,800 개 전부 OK, 되읽기 0, `RDN-G3 present … verdict=0`**.  행당 31 us 는 추정대로.  화면·방향은 사용자가 확인(정상).

**"왜 느린가" 는 참조·Matrox 대조로 답했다**(사용자 지적 뒤).  분해(데모 타이머 + 커널 `tstage`, 1분 안쪽 시험 둘):

| 자리 | 우리 | 참조 / Matrox | 실측 |
|---|---|---|---|
| 깊이 클리어 | **CPU 가 VRAM 창에 243k 워드 직접 쓰기** `OSRDNMesaDepth.c`(G3b 전, CPU 루프)(+ Mesa 소프트웨어 색·깊이 클리어) | `radeon_cp_dispatch_clear`: 색은 `CNTL_PAINT_MULTI` 2D 채우기, 깊이는 **우리 `cpR6State` 와 같은 상태 블록**으로 3D 사각형(`radeon_state.c:1076-1200`); Matrox 는 엔진 | glClear ≈ 250 ms/프레임 |
| 제출당 로그 | `r7bSubmit` 끝 `IOLog("RDN-R7B submit…")` **무조건**(`OSRDNDisplay.m:1342`) | 참조·Matrox: 제출당 로그 없음 | **ioctl 4,525 us/제출**(커널 CP 연산은 338 us); **syslogd 를 SIGSTOP 하니 290 us** → 그리기 143 → 21 ms/프레임.  IOLog 는 syslogd 가 배달 중이면 그 줄을 기다린다 |
| 제출 뒤 대기 | rptr·idle 두 대기 | 참조는 그냥 돌아옴 | 73 us/제출(tstage `wait`) — 지금은 작다 |
| 프레임당 제출 수 | RenderFinish 마다(32) | Matrox 도 같음; 참조는 16 KB 버퍼 | 로그만 빼면 32×0.29 = 9 ms |

**G3b(다음 부팅) 변경**: ① 제출당 `IOLog` 를 `loud` 리스 안으로(기본 무음) ② 클리어를 카드로 — 새 ioctl `CLEAR`: 색은 참조의 2D 채우기, 깊이는 `cpR6State` 블록 + 사각형(참조 그대로) ③ 라이브러리 `osrdn_depth_clear` 는 CPU 쓰기 대신 `CLEAR` 호출, 색 클리어는 `osrdnHookClear` 가 `DD_FRONT_LEFT_BIT` 를 잡아 카드로(Mesa 의 소프트웨어 클리어는 present 모드에선 앱 배열만 지운다).  기대: render 335 → ~25 ms, 프레임 ≈ 45 ms(~20 fps); 그 다음 칸이 참조식 큰 배치.
