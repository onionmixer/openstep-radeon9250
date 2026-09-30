# G3b — 클리어를 카드로, 제출 로그를 리스 안으로 (계획, 2026-09-26)

부팅 4 실측(`docs/G3_PRESENT_PLAN.md` 9): 800×600 PRESENT 프레임 = glClear ≈ 250 ms + 그리기 143 ms + 도장 19 ms.
- glClear: `osrdn_depth_clear` 가 **CPU 로 VRAM 창에 243k 워드**를 쓴다(`OSRDNMesaDepth.c`(G3b 전의 `osrdn_depth_clear`, CPU 루프)).  참조·Matrox 는 카드가 지운다.
- 그리기: 제출 ioctl 4,525 us 중 CP 연산 338 us; **syslogd 를 멈추면 290 us** → 제출마다 무조건 찍는 `IOLog("RDN-R7B submit")`(`OSRDNDisplay.m:1342`) 가 syslogd 배달을 기다린다.  참조·Matrox 는 제출당 로그 0.

## 1. 참고가 답하는 것 (원문 확인)

| 물음 | 답 | 근거 |
|---|---|---|
| 색 클리어 | `PACKET3(CNTL_PAINT_MULTI, 4)`: GMC = `DST_PITCH_OFFSET_CNTL | BRUSH_SOLID_COLOR | (fmt<<8) | SRC_DATATYPE_COLOR | ROP3_P | CLR_CMP_CNTL_DIS`, `pitch_offset`, `colour`, `x<<16|y`, `w<<16|h`; 앞서 `PACKET0 DP_WRITE_MASK` = color_mask | `radeon_state.c:892-912` (`CNTL_PAINT_MULTI 0x9A00` `radeon_drv.h:1178`, `CP_PACKET3 0xC0000000` `:1155`) |
| 깊이 클리어(R200, hierz 없음) | 상태 12 개 = **우리 `cpR6State` 와 같은 블록**(PP_CNTL 0, RE_CNTL 0, RB3D_CNTL Z on, ZSTENCILCNTL, STENCILREFMASK 0, PLANEMASK 0, SE_CNTL, VTE `XY_FMT|Z_FMT`, VTX_FMT_0 `Z0|W0`, VTX_FMT_1 0, VAP_CNTL, AUX_SCISSOR 0) → 상자마다 클립 사각형 → `PACKET3(3D_DRAW_IMMD_2, 12)`: `RECT_LIST | WALK_RING | 3<<16` (= `0x00030038`, 우리 case 표의 값) + 정점 3 개 `(x1,y1,z,1.0) (x1,y2,z,1.0) (x2,y2,z,1.0)` float | `radeon_state.c:1076-1262`; `osrdn_cp.m:1494-1508` `cpR6State`; `RECT_LIST 8`·`WALK_RING 3<<4`·`NUM_VERTICES_SHIFT 16` `radeon_drv.h:1207-1219` |
| ZSTENCILCNTL 비트 | `Z_TEST_ALWAYS 7<<4`, `Z_WRITE_ENABLE 1<<30`, 16비트 형식 `0<<0` | `radeon_reg.h:2185-2234` |
| 깊이 z 값 | 정점 z 는 [0,1] float(`VTX_Z_FMT`), 카드는 `floor(z·2^16)` 로 쓴다 — 지금 `osrdnHookClear` 가 쓰는 변환과 같다 | R6f 실측(`OSRDNMesaHook.c` `osrdnHookClear` 주석) |
| 우리 깊이 버퍼 배치 | 창 오프셋 `OSRDN_TRI_DEPTH_BYTE_OFF 0x500000`, 피치 `(w+31)&~31` px, 행 `(h+15)&~15`; 프롤로그의 `DEPTHOFFSET = winStart + off`, `DEPTHPITCH` px | `OSRDNMesaDepth.c:110-111`, `gen_tri_prologue.py:91-92` |
| 색 표면 | 창 오프셋 0, 피치 `surfRowPixels`(= 폭) | `OSRDNMesaSurface.c` `surfRowPixels` |
| 가짜 CP | `r6Draw` 가 `RECT_LIST|WALK_RING|3` 를 요구하고 `R(0x1c24)`·`R(0x1c28)` 로 깊이에 그린다; **PACKET3 `PAINT_MULTI` 모델은 없다**(`cpStep` 은 DRAW_IMMD_2 와 PACKET0 만) | `world5.c:561-658`, `world5.c:1117-1219` |
| 제출 로그 | `RDN-R7B submit` 은 M2g 가 일부러 남겨 둔 줄(C8) — "같이 바꾸면 두 변경이 섞인다" | `M2G_PLAN.md` C8 |

## 2. 설계

### 2-1. 커널 — 새 ioctl `OSRDN_R7B_IOC_CLEAR`(그룹 'R' 5), `CP_OP_CLEAR 21`
블록(52 B): `magic, version, flags(1 색|2 깊이), colourOff, colourPitch(px), colourValue(ARGB8888), depthOff, depthPitch(px), depthZ(float bits, [0,1]), w, h` in / `status, verdict` out.  통로는 present 와 같다: `osrdn_mode_clear(...)` → 클레임 → `cp->clearReq` → `osrdn_cp_run(CP_OP_CLEAR)` → `cpClear` 가 로컬 배열에 조립 → `cpR6Submit`.
게이트(판정은 present 의 것을 재사용: OK/E_MAGIC/E_GEOM/E_SRC/E_LATCH/E_MODE/E_BUSY): magic → latched/failed → RUNNING·창·32bpp → `flags ∈ {1,2,3}`, `w,h ∈ [1,0xffff]` → 색: `colourOff` 1 KiB 정렬·창 안, `colourPitch*4 % 64 == 0`, `w ≤ colourPitch`, 마지막 행 꼬리가 창 안(present 의 산술) → 깊이: `depthOff % 32 == 0`(DEPTHOFFSET)·창 안, `depthPitch % 32 == 0`, `(h+15)&~15` 행 × `depthPitch*2` B 가 창 안, `depthZ` 는 float 비트로 `0 ≤ z ≤ 1.0`(`0x00000000..0x3f800000`, 부호 비트 0).
워드(참조 순서; 색 10 + 깊이 47 = **57**, 색만 10, 깊이만 47; `tools/r7/present_oracle.py` `clear_words` 가 정본):
```
[색] P0(WAIT_UNTIL,0) 3D|HOST                  -- "3D 가 끝난 뒤 2D 채우기" radeon_state.c:880-884
     P0(DP_WRITE_MASK,0) 0xffffffff
     P3(PAINT_MULTI,4) GMC_CLEAR, PO(colourPitch*4, winStart+colourOff), colourValue, 0<<16|0, w<<16|h
[깊이] P0(WAIT_UNTIL,0) 2D|HOST
     cpR6State 의 12 쌍, **단 ZSTENCILCNTL 은 0x42227070**(7 절 G3c 정정: 클라이언트가 그리는 형식은 0x42227010 의 16 비트(nibble 0)이고, 0x02227072 는 깊이 OFF 값이다 — 부팅 5 는 선례의 24 비트 0x42227072 를 보냈다)
     P0(RB3D_DEPTHOFFSET,1) winStart+depthOff, depthPitch      -- 0x1c24, 0x1c28 인접
     P0(RE_TOP_LEFT,0) 0 ; P0(RE_WIDTH_HEIGHT,0) (h-1)<<16|(w-1)   -- 클립 = 표면
     P3(DRAW_IMMD_2,12) 0x00030038, 0,0,z,1.0, 0,h,z,1.0, w,h,z,1.0   (x,y 는 float 픽셀; 헤더+제어+12 = 14 워드)
     (꼬리 없음 — 참조는 사각형에서 끝난다; 캐시 일관성은 IDLECLEAN 대기가 맡는다)
```
`GMC_CLEAR = DST_PITCH_OFFSET_CNTL | BRUSH_SOLID_COLOR(13<<4) | DST_32BPP | SRC_DATATYPE_COLOR | ROP3_P(0xf00000) | CLR_CMP_CNTL_DIS` (python 으로 값 고정, XOR 게이트).  깊이 클리어 뒤 다음 클라이언트 제출의 프롤로그가 자기 상태를 다시 쓴다(R7 프롤로그가 ZSTENCILCNTL·PLANEMASK·VTX_FMT 를 매번 쓰는지 **확인 항목** — 안 쓰면 `cpClear` 가 끝에 프롤로그 기본값을 되돌린다).
계수기 `clearOk/clearRefused[8]`, 로그는 판정별 1 회(`RDN-G3 clear`).

### 2-2. 제출 로그
`r7bSubmit` 끝 `IOLog("RDN-R7B submit …")` → `if (!quiet || live != CP_RC_RAN)`: loud 리스가 있거나 실패했을 때만.  M2g 규칙(`check_r5_src.py` m2g)은 quiet_take 의 모양만 보므로 새 규칙 하나: "제출 성공 경로에 무조건 IOLog 가 없다"(변이: 가드 제거).  판정기 `judge_m1l.py` 등이 이 줄을 세는 곳이 있으면(grep) loud 팔에서만 기대하게.

### 2-3. 라이브러리
- `osrdn_depth_clear(value16, w, h, why)` → ioctl `CLEAR{flags=2, depthOff=OSRDN_TRI_DEPTH_BYTE_OFF, depthPitch=(w+31)&~31, depthZ=float(value16/65536)}`; CPU 루프·되읽기 제거(계수기 `readBad` 는 0 유지, 이름은 둔다).  z 변환: 훅이 `far = floor(Depth.Clear·65536)` 을 만들던 것을 **float 그대로** 넘기게 바꾼다(`osrdn_depth_clear_f(z)` 추가, 옛 진입은 z = value/65536.0).
- 색: `osrdnHookClear` 가 `DD_FRONT_LEFT_BIT` 에 대해 표면이 묶였고 `osrdn_colour_clear(packed, w, h)` 가 OK 면 **그 비트를 `left` 에서 뺀다**(카드가 지웠으니 Mesa 는 앱 배열을 안 지운다; 되읽기 모드에선 Finish 미러가 앱 배열을 채운다 — M3g 계약 유지).  `packed` 는 `ctx->Color.ClearColor` 를 `osrdn_surf_shifts` 로 묶는다(정점 색과 같은 규칙).  깊이 비트는 지금처럼 **넘긴다**(Mesa 도 자기 버퍼를 지움 — M1j 의 절충 그대로).
- 두 비트가 같이 오면 ioctl 한 번(flags 3).
- fd 는 `osrdn_tri_device_open/close`.

### 2-4. 호스트 검사
- `present_oracle.py` 에 `clear_words(...)` 추가(참조 함수를 그대로 옮김); `sim_r5.py` 가 `clear_expect.h` 생성.
- `world5.c`: `cpStep` 에 PACKET3 `PAINT_MULTI` 모델(5 워드 → 가짜 VRAM 사각형 채우기, pitch_offset 해석) 추가; CLEAR 시험: 게이트 12 종 거절, 색만·깊이만·둘 다의 워드가 오라클과 일치, 가짜 VRAM 의 색 사각형이 값으로 채워짐, 가짜 깊이가 `floor(z·2^16)` 로 채워짐(r6Draw 가 RECT_LIST 로 그린다), 그 뒤 클라이언트 제출이 정상.  변이 6(GMC 비트, ROP, 정점 순서, ZSTENCIL 비트, 게이트 2).
- `check_r5_src.py`: `g3b-clear` 규칙(검증기 미사용·상수 XOR·`cpR6Submit` 1 회·로그 없음) + 제출 로그 가드 규칙; `check_hook.py`: Clear 훅 규칙 정밀화(색 비트는 성공 시에만 뺀다, 깊이 비트는 넘긴다) + 변이.
- 인용 검사, `check-all` 마지막 한 번(기억 `gate-cheap-checks-before-the-suite`).

### 2-5. 실기 (재부팅 1 회)
`run_g3.sh` 그대로(PRESENT 팔 + 분해 타이머): 기대 glClear ≈ 1 ms, 그리기 ≈ 21 ms, 도장 19 ms → ~40 ms/프레임.  화면·방향·배경색(클리어 색이 카드에서 보여야 함) 사용자 확인.  커널 로그 `RDN-G3 clear` 1 줄, `RDN-R7B submit` 0 줄.

## 3. 위험
- 깊이 클리어 뒤 3D 상태 잔류(PLANEMASK 0 등) → 다음 제출의 프롤로그가 덮는지 2-1 확인 항목.
- 색 2D 채우기와 3D 그리기의 캐시: 참조는 2D 앞·뒤에 WAIT 2D idle 만 둔다; 우리는 꼬리에 DSTCACHE purge 까지.
- 창 안 검사 산술은 present 의 것을 재사용(넘침 없는 형태).

## 4. codex 교차검토 판정표 (계획, 2026-09-26)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 색 블록은 WAIT 빼고 8 워드, `PAINT_MULTI,4` 는 6 워드 | `radeon_state.c:888-910` | ✅ (오라클과 같음) |
| `DRAW_IMMD_2,12` 는 14 워드, 총 63 | 오라클 `clear_words` 로 셈 | ✅ 채택(꼬리를 뺀 뒤 57) |
| `C_CLEAR_ZSTENCIL 0x40007070` 은 cpR6State 와 다르다 | `osrdn_cp.m:1499` 0x42227072 | ❌ **7 절에서 뒤집힘** — codex 의 값도 내 채택도 틀렸다: 형식 nibble 은 클라이언트의 0(16 비트)이어야 하고 답은 0x42227070 |
| 첫 WAIT 는 `3D_IDLECLEAN|HOST`(0x60000) | `radeon_state.c:883-886` 원문 | ✅ 채택 |
| 색 2D 뒤 깊이 3D 앞 `2D|HOST` | `radeon_state.c:1199-1201` | ✅ |
| purge 꼬리는 참조에 없고 cpZclear 꼬리엔 `RB3D_CNTL=0` 도 있다 | `radeon_state.c` 1262 까지 purge 없음; `osrdn_cp.m` 꼬리 | ✅ 채택 — 꼬리 제거(참조 모양) |
| 다음 프롤로그가 상태를 전부 다시 쓴다 | `OSRDNMesaTriTable.h:445-457` 46 워드 확인(PLANEMASK 0x761, ZSTENCIL 0x70b, VTX_FMT 0x822/823, VTE 0x82c, VAP 0x820, WIDTH_HEIGHT 0x711, DEPTHOFFSET/PITCH 0x709/70a) | ✅ |
| `DP_WRITE_MASK 0xffffffff` 는 참조의 `color_mask` 와 다름(전 채널로 제한하면 의도) | 사실; 이 API 는 전 채널 클리어만 | ⚖️ 의도된 차이 |

## 5. 구현 기록 (2026-09-26)

| 자리 | 변경 |
|---|---|
| `osrdn_r7b.h` | `osrdn_r7b_clear`(13 워드 52 B) + `OSRDN_R7B_IOC_CLEAR`(그룹 'R' 5) + `_fits`; `OSRDN_CLEAR_COLOUR/DEPTH`; `osrdn_cp_clear_req` |
| `osrdn_cp.h/.m` | `CP_OP_CLEAR 21`; `cpFloatBits`(FPU 없이 정수→float 비트), `cpClearRefuse`/`cpClear`(게이트 → 색 10 워드·깊이 47 워드(`cpR6State` 26 그대로 + DEPTHOFFSET/PITCH + 클립 + 사각형) → `cpR6Submit`); 상수 `C_CNTL_PAINT_MULTI`·`C_P3`·`C_CLEAR_GMC 0x10f036d2`·`C_CLEAR_PRIM`·`C_CLEAR_ONE`·`C_DP_WRITE_MASK` |
| `osrdn_mode.h/.m` | `osrdn_mode_clear`(present 와 같은 통로) |
| `OSRDNDisplay.m/.h` | ioctl 디스패치 + `r7bClear:`(판정별 1 회 `RDN-G3 clear`); **`RDN-R7B submit` 줄을 `if (!quiet \|\| live != CP_RC_RAN)` 뒤로**(loud 리스·실패만) |
| 이름표 | `osrdn_modelog.m`·`rdnr5cp.m` 에 "clear"(OP_COUNT 22) |
| 라이브러리 | `OSRDNMesaDepth.c`: CPU 루프 대신 `osrdn_card_clear(flags, colour, depth16, w, h)` ioctl(`depthFloatBits` = value/65536), `osrdn_depth_clear`/`osrdn_colour_clear` 는 래퍼; `OSRDNMesaHook.c` `osrdnHookClear`: 색 비트가 오면 `ClearColor`→`FLOAT_TO_UBYTE`→`osrdnColourWord` 로 묶어 한 ioctl(flags 3), 성공 시 **`DD_FRONT_LEFT_BIT` 를 `left` 에서 뺀다**, 깊이 비트는 그대로 넘김; 카운터 `colourClears/colourClearBad`, `depthCounts.colourClears/lastVerdict` |
| 검사 | `present_oracle.py` `clear_words`(참조식, 자체검사 57/10/47); `sim_r5.py` `clear_expect.h` + 변이 6; `world5.c`: `PAINT_MULTI` 2D 채우기 모델 + CLEAR 시험(거절 14, 57 워드 일치, 색 채움, 깊이 = case A 가 쓴 값, 색만·깊이만); `check_r5_src.py` `g3b-clear`(검증기 미사용·`cpR6State` 그대로·상수·**제출 줄 게이트**) + 자체 변이 4; `check_hook.py` `g3b-clear-hook`(색 비트는 성공 분기에서만, 깊이 비트는 절대 안 뺌) + 변이 2 |
| 데모 | 카운터 출력에 카드 색 클리어 수 |

호스트: `check_r5_src` PASS, `sim_r5` PASS(변이 85), `check_compile/check_units/check_hook` PASS, 인용 전 문서 0 실패; `check-all` 은 아래 6 절.

## 6. 게이트·설치 (2026-09-26)

| 게이트 | 결과 |
|---|---|
| `check-all.sh` | **PASS** |
| 타깃 드라이버 **`ddecf5fa`** / runid 790405064, 미정의 심볼 21 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 라이브러리 runid **790405103** | **RDNMESA PASS** |
| 설치 `closed=yes fresh live` | **DONE** — reloc sum 45433 515, `Instance0.table` 1024×768 RGB:888/32 |

부팅 5: `LIBRUN=790405103 BOOT=<nonce> BUILD=ddecf5fa bash build/g3/run_g3.sh`(사용자 gcdsd).  읽을 것: PRESENT 팔의 `glClear`·`draw`·`glFinish` 분해, `card colour N bad 0`, `RDN-G3 clear … verdict=0` 1 줄, `RDN-R7B submit` 0 줄, 화면의 배경색(클리어 색 남색)·teapot·방향.

## 7. 부팅 5 결과와 G3c 정정 — 깊이 clear 의 형식 (2026-09-26)

**측정(부팅 5, 드라이버 `ddecf5fa`·라이브러리 790405103·nonce edda3efa, `build/g3/run-790407020`)**: sw 12.17 fps, rb 0.81 fps, PRESENT 팔 **29.53 fps**(render+finish 13.27 ms, 스탬프 20.21 ms; 34,800 행 전부 ok). 계수기는 `card depth 60 bad 0, card colour 60 bad 0`. 사용자: "첫번째는 빨라졌고, 두번째는 화면에 잔상이 남네요" — "teapot 이 움직인 만큼 이전꺼 잔상이 남는 형태".

**계수기는 예라고 했고 그림이 알았다** (`build/g3c/ghostprobe.c`, 오프스크린·SDL 없음·같은 장면, 사용자 gcdsd 불필요):
- VRAM 색 표면을 CPU 로 읽은 그림은 teapot 의 **뒤 면이 앞 면 위에** 그려져 있다(깊이 순서 없음); stock 링크의 같은 장면과 실루엣이 36,718 화소 다르고 56,747 화소가 32 넘게 다르다(`build/g3c/judge_ghost.py`).
- 깊이 영역(창 +0x500000)을 clear 값 0.25 / 0.75 로 clear 만 하고 읽으면 워드마다 **바이트 2 만** 0x40 / 0xc0 로 바뀐다 — 즉 clear 는 **24 비트 형식**(z 를 [23:0] 에, 스텐실 [31:24] 은 마스크 0 이라 그대로)으로 워드마다 쓴다. 클라이언트(teapot)가 쓴 값은 0xa4–0xc2 범위의 **16 비트 하프워드**(장면 깊이 0.64–0.76 과 일치)이고, 그 LESS 판정은 clear 가 남긴 하프워드 배치(0x0000/0x00ff 류)와 만나 대부분 떨어졌다(2,330 개만 기록).
- 원인: 2-1 절이 cpR6State[9] = 0x42227072(형식 nibble **2** = `DEPTH_FORMAT_24BIT_INT_Z`)를 "클라이언트가 그리는 형식과 같다"고 빌려 썼다. 클라이언트의 깊이 ON 값은 `OSRDNMesaTriTable.h:41` 0x42227010 — nibble **0**(16 비트). **`M1I_PLAN.md` 11 절 (2) 가 같은 필드로 태운 실기를 이미 기록**하고 있었고(`R6F_PLAN.md` 1 절 D2 가 16 비트 값 0x42227070 을 명명), 4 절의 codex 판정표에서도 이 값을 검증 없이 채택했다(기억 `read-the-reference-before-measuring`: 빌려 온 값은 전 필드 분해).

**참조가 하는 것**: `radeon_state.c:1145` `tempRB3D_ZSTENCILCNTL = depth_clear->rb3d_zstencilcntl` → `:1205` 그대로 기록; 그 값은 `radeon_cp.c:1191-1198` 의 `depth_fmt`(깊이 bpp 16 이면 16 비트 정수)에 `:1213-1221` Z_TEST_ALWAYS·스텐실 ALWAYS/REPLACE·Z_WRITE_ENABLE 을 OR 한 것 — **clear 는 클라이언트의 깊이 형식을 그대로 쓴다.**

**G3c 수정(커널 1 워드, 57 워드 유지, purge 꼬리 없음 — 참조 모양 유지)**: `osrdn_cp.m:1499` `C_CLEAR_ZSTENCIL 0x42227070`(형식 0·Z_TEST_ALWAYS·스텐실 ALWAYS·ops 0x0222·Z_WRITE_ENABLE; python 비트 분해 = 클라이언트 LESS 0x42227010 의 [6:4] 만 7), `osrdn_cp.m:4079` 이 상태 블록의 9 번째 워드를 이 값으로 바꾼다. 오라클 `present_oracle.py` `CLEAR_ZSTENCIL` 은 표의 `OSRDN_TRI_ZSTENCIL_LESS` 에서 같은 식으로 유도해 자체검사; `world5.c` 가짜 3D 는 16 비트 직사각형을 r6Tri 와 같은 하프워드 형태로 쓰고 clear 시험은 **표면 8 KiB 만 값이고 그 뒤는 스크리블 그대로**를 요구; `check_r5_src.py` g3b-clear 규칙에 치환 줄·값(표에서 유도)과 변이 2 개(치환 줄 제거, 24 비트 값).

**첫 가설의 기각**: "2D 채우기 뒤 3D 캐시 purge 누락" — 삼각형 배치 꼬리마다 이미 purge 가 있고(`osrdn_cp.m` cpZclear 꼬리), 참조의 clear 도 purge 없이 끝난다; 위 측정이 형식을 지목해 purge 편집은 되돌렸다.

**재부팅 게이트(실기 뒤)**: `ghostprobe 1 0.0 1.5 a.ppm` + `GHOST_SEQ=1 ghostprobe 0 … seq.ppm`(내 gcdsd) → `judge_ghost.py` **PASS**(clear 값이 48 만 하프워드 전부, teapot 이 실루엣의 절반 이상을 더 가깝게 기록, stock 과 실루엣 2 %·색 3 % 안), 그다음 `run_g3.sh` 의 PRESENT 팔을 사용자 gcdsd 로 화면 확인(잔상 없음·속도).

### 7-1. 게이트·설치 (2026-09-26, G3c)

| 게이트 | 결과 |
|---|---|
| `present_oracle.py` 자체검사(표의 LESS 값에서 유도), `check_r5_src.py`(g3b-clear 변이 +2), `sim_r5.py`, 인용 루프 | **PASS** |
| `judge_ghost.py` on 부팅 5 드라이버(`run_g3c.sh`, 내 gcdsd) | **FAIL**(기대대로: clear 48 만 하프워드 전부 미기록, teapot 2,330 개, 실루엣 36,787 차이) — 재부팅 뒤 PASS 가 게이트 |
| `check-all.sh` | **PASS** |
| 타깃 드라이버 **`68353c45`** / runid 790410169, 미정의 심볼 21, reloc 40819 515 | **PASS** |
| `check_reloc_r2b0` | **PASS** |
| 설치 `closed=yes fresh live` | **DONE** — runid 790410169, reloc 40819 515, `Instance0.table` 유지 |

## 7-2. 부팅 6 — 깊이는 고쳐졌고, 색 clear 는 한 번도 쓴 적이 없었다 (2026-09-26, G3d)

`run_g3c.sh`(CP 기동 추가, 낡은 출력 제거) + `judge_ghost.py`(16 비트 타일 배치 `mba_z16` 로 덮임 집합 계산):
- **깊이 PASS**: clear 1.0/0.75 가 덮인 하프워드 461,312 개 중 1,024 개(원점 32×32 타일 = 마지막 z 캐시 줄, 다음 제출 때 내려간다 — 참조도 clear 뒤 purge 없음) 빼고 전부 값; teapot 이 48,996 하프워드를 전부 더 가깝게 기록(stock 실루엣 49,004).
- 그림은 여전히 실루엣 +37k 의 "부채꼴".  직교 투영·뒷면 컬링에서도 **동일**, 배치 끔(`RDNMesaBatch=0`)에서도 동일, 부채꼴 화소엔 **z 가 없다** → 3D 그리기가 아니다.
- 창을 패턴 0x404040 으로 채우고 clear+teapot 을 그리자 부채꼴이 사라지고 teapot 만 남았다 → 부채꼴 = **이전 실행들의 teapot 들이 색 clear 에 덮이지 않고 남은 것**(각도가 다른 teapot 이 겹쳐 줄무늬).  색은 R/B 가 뒤바뀐 이유는 다음 항목.
- 결정 실험: 패턴 → 깊이 clear 제출(fence) → **빨강 색 clear** → 창 7.5 MB 전수: 빨강 워드 **0 개**, 색 영역 48 만 워드 **전부 패턴 그대로**, 훅 계수기는 `card colour clears 1 bad 0`.  **PAINT_MULTI 패킷은 이 CP 를 통해 아무것도 쓰지 않는다.**  present 블릿(PACKET0 레지스터 방식)은 그린다.  원인 후보 둘 — CP 의 2D PACKET3 경로, 또는 누구도 쓴 적 없는 `DP_CNTL`(방향 비트; X 서버는 항상 `radeon_exa_funcs.c:207`) — 를 가르지 않았다: 어느 쪽이든 답이 같다.
- 부팅 5 의 "잔상" 도 이것이었다: 화면 배경은 이전 프레임들의 teapot 이 남는다(색 clear 없음) + 깊이 형식 불일치.  (부팅 5 의 `b`·`ab` 그림에서 배경이 clear 색이었던 것은 그 이전 어느 실행의 잔재였다.)
- 덤으로: 몸통 화소의 VRAM 바이트가 stock 배열 바이트와 **정확히 같다**(바이트 0 = R) — 제 PNG 변환의 R/B 스왑이 틀렸었고, 훅의 clear 색 워드 `osrdnColourWord`(정점용 R/B 스왑)는 2D 채우기엔 틀린 패킹이다(화소 패킹 `osrdnWantWord` 가 맞다).

**G3d 수정**
- 커널 `cpClear` 색 블록 = **X 드라이버의 단색 채우기 레지스터 시퀀스**(`radeon_exa_funcs.c:90` `Emit2DState`: DEFAULT_SC_BOTTOM_RIGHT·DP_GUI_MASTER_CNTL·DP_BRUSH_FRGD/BKGD_CLR·DP_SRC_FRGD/BKGD_CLR·DP_WRITE_MASK·**DP_CNTL**(`radeon_exa_funcs.c:114`)·DST_PITCH_OFFSET; `RADEONSolid`: DST_Y_X·DST_HEIGHT_WIDTH `radeon_exa_funcs.c:243`; 주소 `radeon_reg.h:670` 부근) — present 블릿과 같은 PACKET0 형태, 앞뒤 WAIT 3D|HOST / 2D|HOST.  13 쌍 26 워드, 총 **73**.  `osrdn_cp.m:4070`.
- 라이브러리 `osrdnHookClear`: 색 워드를 `osrdnWantWord`(화소 패킹)로 `OSRDNMesaHook.c:711`; `check_hook.py` 규칙·변이.
- `present_oracle.py` 새 색 블록·자체검사, `world5.c` 가짜 2D 는 `DST_HEIGHT_WIDTH` 쓰기에서 GMC·DP_CNTL·피치/오프셋·마스크로 칠한다(PAINT_MULTI 모델은 남겨 둠), `check_r5_src.py` g3b-clear 규칙에 PAINT_MULTI 금지·DP_CNTL·h<<16|w·레지스터 값 + 변이 2.
- 발견한 검사기 결함: G3c 때 `check_r5_src.py` 의 g3b-clear 규칙 안에 `tab = …` 줄들을 else 블록 중간에 넣어 그 뒤 검사(E_MAGIC…·IOLog)가 `if (less & 0xf)` 아래로 들어가 **실행되지 않았다** — 새 변이 2 개가 "caught by []" 로 드러냈다(기억 `checker-discipline`: 안 걸린 것은 미검사).  블록 밖으로 옮겨 복구.
- `judge_ghost.py`: 가속 그림 바이트 순서 스왑 제거, 16 비트 타일 배치, 마지막 타일 허용치 1,024.
- 참고: 제출 fence(WBINVD)는 M2e 이후 기본 꺼짐(`osrdn_cp.m:757`); CPU 가 창에 쓴 패턴은 다음 제출의 직렬화 뒤에야 보였다(캐시성은 이 부팅에서 가르지 않았다 — 되읽기는 진실이었다).

**재부팅 7 게이트**: `run_g3c.sh` → `judge_ghost.py` **PASS**(깊이 + 그림: 배경 = clear 색, 실루엣 2 %·색 3 %), 그다음 사용자 gcdsd 로 PRESENT 팔.

### 7-3. 게이트·설치 (2026-09-26, G3d)

| 게이트 | 결과 |
|---|---|
| `present_oracle.py`·`check_r5_src.py`(변이 +2, 규칙 블록 복구)·`sim_r5.py`·`check_hook.py`·인용 루프 | **PASS** |
| 타깃 드라이버 **`ef6c16c1`** / runid 790413834, 미정의 심볼 21, reloc 59356 515; `check_reloc_r2b0` | **PASS** |
| 라이브러리 **790413900**(clear 색 워드 = 화소 패킹) | **RDNMESA PASS** |
| 설치 `closed=yes fresh live` | **DONE** — runid 790413834 |
| `check-all.sh` | **PASS** |

부팅 7: `LIBRUN=790413900 BUILD=ef6c16c1 bash build/g3c/run_g3c.sh`(내 gcdsd) → `judge_ghost.py` PASS + `filltest` 의 빨강 워드 48 만 개 → 그다음 `LIBRUN=790413900 BOOT=<nonce> BUILD=ef6c16c1 bash build/g3/run_g3.sh`(사용자 gcdsd).

### 7-4. 부팅 7 결과 (2026-09-26, 드라이버 `ef6c16c1`·라이브러리 790413900·nonce 014e24f8)

- 오프스크린 `run_g3c.sh`(내 gcdsd): `judge_ghost.py` **PASS** — 빨강 clear 가 색 영역 480,000 워드 전부에 `ff0000ff`(화소 패킹) 기록, 깊이 clear 는 덮인 하프워드 전부(마지막 z 캐시 타일 1,024 만 지연), teapot 실루엣 stock 대비 차이 28 화소·색 32 화소.
- 화면 `run_g3.sh`(사용자 gcdsd, `build/g3/run-790420008`): sw 11.66 fps, rb 0.85 fps, **PRESENT 32.07 fps**(render+finish 11.99 ms, 스탬프 18.80 ms, 34,800 행 ok).  커널 로그 `RDN-G3 clear … verdict=0 flags=3 colour=ff23140f` 1 줄, present 1 줄.  사용자: "첫번째는 정상작동했습니다. 두번째는 별도의 잔상은 없습니다."  **G3 종료.**

