# G5-4 — 뒤집힌 표면의 ReadPixels, 그리고 정리 항목 (라이브러리만, 재부팅 없음)

남은 작업 목록의 5 번(1 안: ReadPixels)과 8 번(정리 여섯).  **커널은 바꾸지 않는다** — 8c 의 커널 안은 이미 측정으로 기각된 설계이고(§2-3), 나머지는 라이브러리·도구·문서다.  그래서 G5-2 로 설치된 드라이버(stamp 81450f91)는 그대로 가고 재부팅은 한 번이다.

## 1. 5-1 — present 모드의 ReadPixels

### 1-1. 사실 (열어서)

- G5-1b 이후 present 모드의 표면은 위→아래다: 정점 y′ = H − y(`OSRDNMesaHook.c:888-891`, `:1003`), 미러는 행 r 을 H−1−r 에서 복사한다(`OSRDNMesaSurface.c` `osrdn_surf_mirror`).  그런데 OSMesa 의 버퍼가 곧 그 표면이고(`osrdn_surf_take` 가 `surfBase` 를 돌려준다), OSMesa 는 행 y 를 아래→위로 주소 짓는다(`osmesa.c:441-490` `compute_row_addresses`, `PIXELADDR4` `:948`).
- `glReadPixels` 는 드라이버 훅이 `GL_TRUE` 를 돌려주면 끝나고, `GL_FALSE` 면 Mesa 가 스팬 읽기로 한다(`readpix.c:771-774`).  지금의 훅은 flush 하고 `GL_FALSE` 를 돌려준다(`OSRDNMesaHook.c` `osrdnHookReadPixels`) — present 모드에서 Mesa 가 뒤집힌 행을 읽는다.
- GLQuake 의 `screenshot` 명령이 `glReadPixels(GL_RGB, GL_UNSIGNED_BYTE)` 를 부른다(upstream `gl_screen.c:627`, 포트에 이 파일의 대체 없음).  그림이 위아래로 뒤집혀 저장될 것이다(추론, 재부팅 뒤 확인).  `envmap`(개발용)도 ReadPixels 다.
- OSMesa 의 `OSMESA_Y_UP` 으로 행 주소를 뒤집는 길은 없다: 가속 중에 `yup` 이 0 이 되면 `osmesa_leave_accel`(`osmesa.c:755-761`) — 이 프로젝트는 Mesa 트리를 고치지 않는다.

### 1-2. 설계

새 단위 `mesa/OSRDNMesaReadPix.c` — Mesa 형식을 모르는 순수 C 함수 하나:

    osrdn_readpix_flipped(surf, rowPixels, surfH, shifts r g b a,
                          x, y, w, h, comps(3|4), clip [xmin,xmax]x[ymin,ymax],
                          pack alignment, rowLength, skipPixels, skipRows, dest) -> 1 읽음 / 0 거절

- **Mesa 빠른 경로와 같은 조건·같은 잘라내기**(`readpix.c:497-590` `read_fast_rgba_pixels`): 전송 연산(스케일·바이어스·맵·색 행렬·색 표·최소최대·히스토그램)이 하나라도 켜져 있으면, SwapBytes·LsbFirst 가 켜져 있으면 훅이 거절한다.  잘라내기는 그 함수의 식 그대로(`Xmin/Xmax/Ymin/Ymax` 는 **포함** 경계, 식에 `- 1`).
- 형식: `GL_RGBA`·`GL_RGB` × `GL_UNSIGNED_BYTE`.  Mesa 빠른 경로는 RGBA·정렬 1 만 받지만, 우리는 정렬 1·2·4·8 을 GL 규칙대로 받는다: 한 행의 바이트 = comps × rowLength, 정렬 a > 1 이면 a 의 배수로 올림(python 오라클이 같은 식).  그 밖(BGR·BGRA·LUMINANCE·다른 type)은 거절.
- 화소: GL 행 `sy` 는 표면 행 `surfH − 1 − sy`(미러와 같은 규칙), 워드 `W` 에서 R = (W >> rs) & 255 … A = (W >> as) & 255 (OSMesa 의 RGBA 스팬 읽기와 같은 성분; `osrdn_surf_shifts`).
- 거절되면 `GL_FALSE` 로 Mesa 가 읽는다 — 그 수는 새 계수 `readpixFlipDeclined` 로 RDN-C 에 찍는다(0 이어야 정상).  UseSoftwareAlphaBuffers 가 켜져 있으면 거절(알파가 다른 버퍼에 있다).
- 훅: `osrdn_present_active() && osrdn_surf_flipped()` 일 때만 이 함수를 부른다.  그 밖은 오늘과 같다.

### 1-3. 검증

- `tools/mesa/sim_readpix.py`(새): 단위를 호스트에서 빌드해 무작위 표면(각 워드 다른 값)과 수백 개의 경우(정렬 1·2·4·8, rowLength 0·w·w+3, skip, 창 밖으로 걸친 x·y, w·h 1..17, RGB·RGBA)를 돌리고 **python 오라클**(같은 규칙을 파이썬으로)과 바이트 대조.  목적지 버퍼 앞뒤 경계 바이트가 안 바뀌었는지도 본다.
- 변이: 행을 뒤집지 않음, 정렬 무시, 포함 경계를 배타로, 알파 레인 틀림, skipRows 무시 — 각각 잡혀야 한다.
- `check_hook`: 훅이 뒤집힌 present 에서만 부르고 `GL_TRUE` 를 돌려주는지, 계수가 거절 때 오르는지(변이).
- 재부팅 뒤: GLQuake 에서 `screenshot` 한 장 → python 으로 TGA 와 표면 덤프(rdndump) 대조.

## 2. 8 — 정리 여섯

### 2-1. 8a trace-last 가 잘리지 않는다

`triTrace` 는 마지막 스트림을 `lseek(0) + write(n×4)` 로 덮는다(`OSRDNMesaTri.c:853`, 절단은 `:857`) — 더 긴 옛 스트림의 꼬리가 남는다.  실제로 `build/g410/trace-g411-last.bin` 은 4,064 워드인데 마지막 스트림은 4,057 워드였다(G5-2 §3, python).  → 쓴 뒤 `ftruncate(fd, n×4)`.  타깃 libc 에 있다(`nm libsys_s` 에 `_ftruncate`, `libc.h` 선언).  `judge_m1b` 허용 목록에 `_ftruncate`.

### 2-2. 8b 아레나 블록 표 512

`OSRDN_TEXARENA_BLOCKS` 512(`OSRDNMesaTexArena.h:20`).  GLQuake 의 상한은 텍스처 1,024(`gl_draw.c:68` `MAX_GLTEXTURES`) + 라이트맵 64(`gl_rsurf.c:40`); G4-6 사다리가 정확히 512 에서 멈췄다.  → 2,048.  표 비용 = 2,048 × 8 B(python 으로 재계산해 적는다).  할당·해제는 선형 탐색이라 N 에 비례 — 업로드 때만 불리고 G5-1a 실측 업로드는 레벨당 1.4 ms 라 무시할 크기(python 으로 상한 계산).  `sim_arena.py` 의 `BLOCKS = 512` 는 헤더에서 읽도록 바꾼다(숫자를 두 곳에 두지 않는다).  **바이트 용량**은 별개다 — 아레나 바이트는 그대로이고, 표를 늘리면 다음에 차는 것이 바이트일 수 있다; 재부팅 뒤 실행의 `texAbsent` 계수로 본다.

### 2-3. 8c `RDN-R4` open/close 가 4 KB 로그 버퍼를 넘친다 — **커널은 고치지 않는다**

- M2f 가 이 두 줄을 knob 뒤로 숨겼다가 **되돌렸다**: 측정이 210 us 떨어진 두 무리로 갈라졌다(`OSRDNDisplay.m` 의 `rdnDevOpen` 주석, `docs/M2F_PLAN.md` 8).  금지 목록 대조 결과 이 설계는 기각된 것이다.
- 넘침이 일어나는 것은 fd 를 쥐지 않는 클라이언트(사다리·teapot)가 제출마다 열고 닫을 때다.  GLQuake 는 present 모드에서 fd 를 쥔다(`osrdn_tri_hold_set`, G3) — 제출·RETIRE 모두 쥔 fd 를 쓴다(`triOpen`).  진단 실행에는 이미 `RDNMesaHold=1` 이 있다.
- → 코드 없음.  G4-6 의 증거 손실 절에 "진단 실행은 RDNMesaHold=1; present 모드는 자동으로 쥔다" 를 적는다.

### 2-4. 8d 첫 카드 clear 의 CP 대기 초과(복구됨)

G4-6: GLQuake(present) 실행 직후 다른 프로세스의 첫 glClear 가 `RDN-G3 clear rc=8`(RECOVERED).  원인 불명, 드라이버가 복구했다.  G5-2 가 바로 이 자리(프로세스 사이의 링 상태, 마지막 close 의 retire)를 바꿨으므로 **맹목으로 고치지 않고 재현을 게이트에 넣는다**: `run_g52_on.sh` 의 GLQuake 세 실행 뒤 clear 를 부르는 오프스크린 시험(`test/osrdn-mesa-teapot.c` 의 첫 프레임 clear)을 한 번 돌리고 `RDN-G3 clear rc` 를 판정기가 읽는다(0 이어야).  재현되면 그때 원인을 판다.

### 2-5. 8e 밉 체인이 8×8 에서 끝난다 — **사용자 결정 필요**

추적 기록 집계(python, `build/g410/trace-g411.txt`): 레벨 수 = min(5, log2(짧은 변) − 2) — 128² 5, 64² 4, 32² 3, 256² 5, 32×128 3, 128×64 4.  GLQuake 는 1×1 까지 올리고(upstream `gl_draw.c:1060-1070`), Mesa 의 M 은 log2 대로다(`texobj.c:197-215`).  자르는 것은 **GLQuake 포트**: 필터 감사가 텍스처마다 `GL_TEXTURE_MAX_LEVEL` 을 **Matrox 하드웨어 한계**(8×8, 최대 4 단)로 고정한다(`gl_vidsdl.c:574-595`, 파일은 `openstep-quake/port/openstep/`).  radeon 빌드에도 같이 걸려 있다.  RV280 은 16 레벨까지 받는다(`OSRDNMesaTriTable.h:510`).  영향: 먼 표면이 8×8 레벨에서 멈춰 축소가 덜 된다(반짝임).  **고치는 자리가 게임 포트라 사용자 지시("퀘이크를 고치는 게 방법이 아니다")와 부딪힌다 — 결정을 여쭌다.**  라이브러리가 앱의 MAX_LEVEL 을 무시하는 것은 GL 계약 위반이라 하지 않는다.

### 2-6. 8f `cpdec.py` 는 없다

G4-10 §4·§7 은 "추적 디코더 표기(코드 4·5 → 필드 2·3)는 `cpdec.py` 주석에" 라고 적었지만 저장소 어디에도 없다(find·git log).  → 문서를 정정하고, 그 표기를 추적 줄을 만드는 `triTrace`(`OSRDNMesaTri.c`) 의 주석에 둔다 — 추적을 읽는 사람이 실제로 여는 자리다.

## 3. codex 에 묻는 것 (코딩 전, 한 호출 = 한 주장)

"§1-2 의 읽기(표면 행 surfH−1−sy, 성분 시프트, 포함 경계 잘라내기, GL 정렬 규칙)는 present 모드 표면에서 Mesa 가 뒤집히지 않은 표면에서 `read_fast_rgba_pixels` 로 읽었을 바이트와 같다" — `readpix.c`·`osmesa.c`(스팬 읽기·행 주소)·`OSRDNMesaSurface.c`(미러)·`OSRDNMesaHook.c`(뒤집기)만 보고 반증.

## 4. 단계

1. 코드: ReadPix 단위·훅·계수, trace 절단, 아레나 표, 문서 정정, 러너에 clear 재현
2. 싼 검사: sim_readpix, check_hook, sim_arena, check_units, judge_m1b 자체, check_compile, 인용
3. 타깃 라이브러리 빌드 → judge_m1b → GLQuake 재링크(GLQuake 가 꺼져 있을 때만)
4. check-all → 커밋 → 재부팅 요청(드라이버는 이미 설치됨)

## 5. codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전, 한 주장)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| (a) GL_RGB 와 정렬 ≠ 1 의 RGBA 는 빠른 경로가 아니라 일반 경로로 가고, 일반 경로는 요청한 모든 행·폭(최대 MAX_WIDTH)을 쓴다 — 창 밖에 걸친 요청에서 잘라내는 읽기와 바이트가 다르다; 변환(부동소수·클램프·바이트 순서)은 없다 | 열었다: 빠른 경로 거절 `readpix.c:521`·`:583-585`, 일반 경로 `:657`·`:695-722`, RGB 복사 `image.c:1516-1525` | ⚖️ 사실.  **화면 안쪽 요청은 같다**; 창 밖 화소는 GL 에서 정의되지 않은 값이라 빠른 경로의 잘라내기를 따르고 차이를 여기 적는다 |
| (b) `_mesa_image_address` 는 SkipImages × (행 × ImageHeight) 도 더한다 | 열었다: `image.c:420-440`·`:479-492` | ✅ 채택 — SkipImages ≠ 0 이면 거절 |
| (c) 알파는 메모리의 워드에서, 표면 시프트와 같은 레인에서 온다 | OSMesa 스팬 읽기(`osmesa.c` `read_rgba_span`)와 `osrdn_surf_shifts` 의 유도 규칙 | ✅ 반증 안 됨 |
| (d) 뒤집을 때 쓰는 H 와 `ReadBuffer->Height` 가 같다는 것은 이 파일들만으로 증명 안 된다 | 사실 | ⚖️ 채택 — ReadBuffer 의 폭·높이가 표면과 다르면 거절 |

## 6. 구현 (2026-09-29, 재부팅 전, 라이브러리·도구·문서)

| 항목 | 한 일 | 검사 |
|---|---|---|
| 5-1 | 새 단위 `mesa/OSRDNMesaReadPix.c/.h`(순수 C).  훅의 `osrdnReadFlipped` 가 Mesa 빠른 경로의 전송 연산 여덟과 SwapBytes·LsbFirst·SkipImages·소프트웨어 알파·ReadBuffer 크기를 보고 거절하거나 읽는다; 뒤집힌 present 에서만.  표면 기준 주소 접근자 `osrdn_surf_base`.  RDN-C 에 `readpix_flipped`·`readpix_declined` | `tools/mesa/sim_readpix.py`(새): 146 경우 전 바이트·보호 바이트를 python 오라클과 대조 + 변이 6; `check_hook` `g54-readpix` + 변이 4; `check_compile`(디렉터리 전수) |
| 8a | `triTrace` 가 마지막 스트림을 쓴 뒤 `ftruncate` | `judge_m1b` 허용 목록 `_ftruncate`(타깃 빌드 B3 PASS, 미정의 23) |
| 8b | `OSRDN_TEXARENA_BLOCKS` 2,048 | `sim_arena` 가 헤더에서 읽는다(표가 2,048 에서 차고 둘이 거절) |
| 8c | 코드 없음 — G4-6 문서에 M2f 의 기각과 fd 유지 경로를 적었다 | — |
| 8d | `run_g52_on.sh` G8: GLQuake 세 실행 뒤 새 라이브러리의 ghostprobe_v20 한 프레임, 커널 clear 줄 수집; `judge_g52 on` 이 비정상 clear·걸쇠를 FAIL | 판정기 자체검사 |
| 8e | **하지 않는다** — 사용자 결정(2026-09-29): "quake 수정은 하지 않습니다".  8×8 상한은 게임 포트의 설정으로 남는다 | — |
| 8f | G4-10 문서 정정, 추적 줄 형식과 MIN 코드의 뜻을 `triTrace` 머리 주석에 | — |

- 타깃 라이브러리 **RDNMESA PASS runid=790613340**, `judge_m1b` PASS; GLQuake 재링크(새 문자열 확인).
- 러너의 타깃 명령에서 `grep '…\|…'` 를 `egrep` 으로 바꿨다 — NeXT grep 은 교대를 모른다(기록된 함정; G7 의 커널 줄 수집이 비어 나올 뻔했다).
- 곁에서 찾은 것: 인용 검사기는 경로를 붙인 인용(`openstep-quake/…/x.c:N`)을 **조용히 건너뛴다** — 기존 문서에 30 개.  이 칸에서는 내 인용만 PATHS 이름으로 고쳤고, 나머지는 남은 작업으로 올린다.
- 재부팅 뒤 5-1 의 실기 확인: GLQuake 콘솔에서 `screenshot` → 저장된 TGA 를 python 으로 표면 덤프(`rdndump`)와 대조(위아래 방향).  이것은 사용자 화면에서 한 번.

## 7. 실기 결과 (2026-09-29, 부팅 ee4b61a6)

- **5-1 PASS (실기, 오프스크린)**: `build/g54/readpix_probe.c` — OSMesa 64×48, present 모드 켜고 아래 절반 빨강·위 절반 파랑을 카드가 그린 뒤 `glReadPixels`:

| 라이브러리 | 아래 행(GL y=0) | 위 행 | 표면 행 반전과 대조 |
|---|---|---|---|
| G5-4 (790613340) | ff0000 빨강 | 0000ff 파랑 | RGBA 0 불일치, RGB(정렬 4, rowLength w+3) 0 불일치, `readpix_flipped` 2, `declined` 0 |
| 대조군 G5-3 (790608134) | 0000ff 파랑 | ff0000 빨강 | — (뒤집혀 나온다: 고치기 전의 결함이 실기에서 재현) |

- **`screenshot` 은 확인 수단이 못 된다**: GLQuake 포트의 `Sys_FileWrite` 가 `fwrite` 가 아니라 `fread` 를 부른다(`sys_sdl.c:265`) — 그래서 스크린샷 TGA 는 늘 0 바이트다(9월 23 일의 `quake00.tga` 도).  게임 쪽이라 고치지 않는다(사용자 지시); 기록만.
- **8d**: G5-2 게이트 G8 — GLQuake 직후 첫 카드 clear 가 rc 0(이 부팅의 유일한 clear, 부팅 구간 걸쇠·skip·복구 0).  재현되지 않았다.
