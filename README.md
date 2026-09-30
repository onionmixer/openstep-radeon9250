# openstep-radeon9250

OPENSTEP 4.2(i386)의 **PCI ATI Radeon 9250 (RV280)** 을 위한 새 DriverKit
디스플레이 드라이버와, 그 위에서 Mesa 3.4.2가 카드의 3D 엔진으로 그리게 하는
가속 라이브러리다. 기존 바이너리 드라이버를 고친 것이 아니라 공개 하드웨어
자료와 공개 Radeon 구현(주로 BSD: NetBSD `radeonfb`, FreeBSD 레거시
`sys/dev/drm`)을 근거로 새로 만든 `IOFrameBufferDisplay` 서브클래스이고,
[openstep-matrox-remade](https://github.com/onionmixer/openstep-matrox-remade)
(G450)의 후속이다.

**v1.2 릴리스**: [releases/tag/v1.2](https://github.com/onionmixer/openstep-radeon9250/releases/tag/v1.2)
— 설치용 `.pkg` 세 개와 SHA256SUMS. 설치와 복구 절차는
[release-packaging/INSTALL.md](release-packaging/INSTALL.md)에 있고,
내용은 [RELEASE_NOTES_v1.2.md](RELEASE_NOTES_v1.2.md)에 있다.
1.2 는 부팅 때의 색 시험 패턴이 로그인 화면에 비치던 것과, 화면이 오른쪽으로 밀리던 것을
고쳤다(가로 위치는 Configure.app 의 `H position` 으로 조정). 1.1 은 부팅 뒤 clear 를
하지 않는 GL 프로그램(GLQuake)의 화면 멈춤을 고친 판이다
([RELEASE_NOTES_v1.1.md](RELEASE_NOTES_v1.1.md)) — 1.0 을 쓰고 있다면 1.2 로 올릴 것.

## 무엇이 되나

| | |
|---|---|
| **화면** | 5 해상도 × 4 형식 = 20 조합, Configure.app 에서 고른다 |
| **회색 단계** | Configure.app 인스펙터의 `Gray Levels` 라디오(256/16/4/2) |
| **가로 위치** | Configure.app 인스펙터의 `H position` 슬라이더(−16~48 픽셀, 기본 7) — 다음 부팅부터 |
| **3D** | OSMesa 백엔드 `libGL_radeon.a` — 삼각형을 CP 링으로 카드에 보낸다 |
| **SDL2** | [SDL2 openstep](https://github.com/onionmixer/openstep-sdl2) 의 present 계약으로 프레임을 화면에 VRAM→VRAM 블릿 |
| **GLQuake** | [sdl2quake-openstep](https://github.com/onionmixer/sdl2quake-openstep) 이 **월드 삼각형 전부를 카드로** 그린다 |

실기: PCI `1002:5960` rev 1, VRAM 128 MiB, 한 대의 i865 기계(Celeron 2.66 GHz).
AGP 는 대상이 아니다 — 링과 GART 는 칩 내장 PCI GART 로 둔다.

## SDL2 가속

SDL2 프로그램은 드라이버의 present 함수 셋을 한 번 등록하고 평범한
`SDL_GL_SwapWindow` 루프를 돈다. Matrox 와 같은 계약이고 이름만 다르다:

```c
#include <SDL_openstepglpresent.h>

static const SDL_OpenStepGLPresent hooks = {
    SDL_OPENSTEP_GLPRESENT_ABI, sizeof(hooks),
    OSRDNMesaBufferOrigin, OSRDNMesaBufferPresentMode,
    OSRDNMesaBufferPresentRect
};
SDL_SetWindowData(window, SDL_OPENSTEP_GLPRESENT_KEY, (void *)&hooks);
```

present 모드에서 라이브러리는 장면을 **y 를 뒤집어** 그리고, SDL2 가 행 단위로
부르는 전달을 **프레임당 블릿 한 번**으로 바꾼다(`docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md`).
창을 끌어 옮기는 동안은 서버에게 창 위치를 물어 전달을 잠시 거절하고 SDL2 의 AppKit
경로에 맡긴다 — 드래그 잔상 방지(`docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md`).

## 성능 (실측)

GLQuake(sdl2quake-openstep, LibreQuake pak, 640×480):

| 측정 | 값 |
|---|---|
| `timedemo demo1` | **4,527 프레임 111.7 초 = 40.5 fps** |
| `+map start` 월드 구간(프레임 150–300) | **15.1 ms/프레임(66 fps)** |
| 같은 구간, 가속 초기(G4-10) | 7–8 fps |

그 사이의 지렛대는 차례로: 텍스처 업로드 전수 되읽기 제거(G5-1a), 프레임당 한
블릿 present(G5-1b), 완료가 아니라 **수락**으로 끝나는 제출(G5-2). 지금은
**카드가 병목**이다 — CPU 는 배치 크기와 무관하게 프레임당 ~5 ms 를 카드를
기다린다(`docs/G5_5_BATCH_SIZE_PLAN.md`).

teapot, 800×600, SDL2 창(`test/osrdn-sdl-teapot.c`, G3b): 소프트웨어 11.66 fps,
되읽기 경로 0.85 fps, **present 경로 32.07 fps**. (G5 의 개선 이전 값이고 그 뒤
다시 재지 않았다.)

## 화면

- **해상도** 5종(640×480 ~ 1600×1200, 60 Hz)
- **형식** 4종: RGB:888/32, RGB:555/16, RGB:256/8, BW:8
- **회색 단계**는 형식이 아니라 별도 키 `Gray Levels`(256/16/4/2) — 같은 8bpp
  스캔아웃에 램프만 다르다
- 전송표: 888/32·555/16 은 선형 램프(WindowServer 의 감마 표를 싣지 않는다 —
  실으면 32bpp 가 16 비트처럼 보였다, `docs/G2_LUT_PLAN.md`), RGB:256/8·BW:8 은 표를 싣는다

부팅으로 확인한 조합은 800×600 네 형식, 640×480/32, 1024×768/32, 1024×768 BW:8
(16 단계)이다. 1280×1024·1600×1200 은 모니터가 없어 **시험하지 못했다**.
나머지 조합의 타이밍은 NetBSD `videomode.c` 와 독립 대조했다(`docs/R3_MULTIMODE_PLAN.md`).

활성화는 Configure.app 이다(번들의 Location 은 빈 값). 되돌리기와
모드 복구 도구는 `tools/r3/target-mode-reset.sh`.

## 3D — Mesa 3.4.2가 카드에서 돈다

OSMesa 백엔드가 삼각형을 R200 3D 엔진으로 보내고, 받을 수 없는 상태만 Mesa 의
래스터라이저로 내려보낸다. 커널은 클라이언트 스트림을 **검증기**(허용 레지스터
목록·값 규칙)로 읽은 뒤에만 링에 싣는다 — 라이브러리의 제출이 카드를 세우거나
표면 밖을 쓸 수 없게 하는 곳이 커널이다.

카드가 그리는 것:

| | |
|---|---|
| 셰이딩 | flat, Gouraud |
| 깊이 | LESS · LEQUAL · GEQUAL · ALWAYS, 쓰기 켬/끔 |
| 블렌드 | (SRC_ALPHA, 1−SRC_ALPHA) · (ZERO, 1−SRC_COLOR) · (ONE, ONE) |
| 알파 테스트 | 8 함수 전부 |
| 텍스처 | 2D 하나, RGB/RGBA, 8–512 의 2 의 거듭제곱, REPEAT, REPLACE · MODULATE, NEAREST/LINEAR |
| 밉맵 | 네 MIN 모드 — 두 **레벨 혼합** 모드는 같은 텍셀 필터의 **레벨 선택** 모드로 대체해 보낸다 |

밉맵 대체는 **문서화된 근사**다. 이 카드의 레벨 혼합 모드는 몇 번의 제출 안에
기계를 세운다(`docs/G4_8_REPLAY_PLAN.md`, 재현기 `tools/g48/rdnreplay`). 그래서
기본값은 대체이고, `RDNMesaMip=all` 은 **재현기로만** 남겼다 — 켜면 기계가 선다.

그 밖(안개, 스텐실, 시저, 논리 연산, 폴리곤 스무스·스티플, 다른 블렌드 쌍,
다른 텍스처 환경·감기·크기)은 Mesa 소프트웨어로 그린다. 그림은 맞고 느리다.

### 환경 변수

| 변수 | |
|---|---|
| `RDNMesaAccelOff` | 값이 있으면 가속을 끈다(켜는 값은 없다) |
| `RDNMesaSync=1` | 수락 제출 대신 완료까지 기다리는 제출 |
| `RDNMesaMip` | `0` 은 밉맵을 전부 소프트웨어로; `all` 은 위의 재현기 |
| `RDNMesaTexVerify=1` | 텍스처 업로드를 전수 되읽어 확인(기본은 네 모서리 표본) |
| `RDNMesaTime=1` | 프레임 예산 계기(rdtsc), `RDNMesaTimeSplit=N` 은 N 번째 present 에서 구간을 나눈다 |
| `RDNMesaBatchWords=N` | 배치 상한을 줄인다(256 이상; 측정용) |

### 알려진 한계

- **CP 멈춤**: 수락 제출 ~93,000 건에 세 번 CP 가 멈췄다. 드라이버가 매번
  엔진 리셋과 CP 재시작으로 복구했고, 그때마다 배치 하나를 잃어 한 프레임에
  ~110 ms 끊김이 생긴다. 원인은 미해결이다(`docs/G5_6_GATE_WHY_AND_CITATIONS_PLAN.md` §3).
- **present 모드의 소프트웨어 폴백은 거꾸로 그려진다**: 장면을 뒤집어 그리므로
  Mesa 로 위임된 삼각형·점·선·비트맵이 표면에 쓰면 뒤집힌다. GLQuake 정상
  경로에서는 0 이고, 0 이 아니면 라이브러리 통계 줄이 그 수를 남긴다.
  `glReadPixels` 는 뒤집힌 표면에서 바로 읽도록 고쳤다(`docs/G5_4_READPIX_AND_CLEANUP_PLAN.md`).
- **3D 는 VRAM 128 MiB 보드에서만 켜진다**: 3D 창 상한을 128 MiB 에서 만들고, 보드의
  `CONFIG_MEMSIZE` 가 그보다 작으면 드라이버가 창 등록을 거절한다(화면은 동작, 3D 는
  소프트웨어).  확인한 보드는 128 MiB 한 장이다.
- GLQuake 포트의 밉맵이 8×8 에서 멈추는 것은 포트의 Matrox 전용 설정 탓이고,
  이 프로젝트는 게임을 고치지 않는다.

## 저장소

| | |
|---|---|
| `OSRDNDisplay/` | 드라이버 번들 — 커널 부분은 `OSRDNDisplay_reloc.tproj`, Configure 인스펙터 |
| `mesa/` | `libGL_radeon.a` 의 소스(OSMesa 백엔드) |
| `probe/` | 초기 조사 probe(R1·R2a) |
| `test/` | 실기 시험·데모 프로그램, `test/mgashim/`(Matrox 이름의 시험을 원본 그대로 radeon 에 링크) |
| `tools/` | 호스트 검사·오라클·생성기와 타깃 스크립트 |
| `build/` | 단계별 러너·판정기(`*.py`·`*.sh` 만 추적, 산출물은 무시) |
| `docs/` | 단계별 계획·결과. R(드라이버)·M(3D 사다리)·G(GL 응용) 순 |

- 작업 계획 [PLAN.md](PLAN.md), 하드웨어 사실표 [ANALYSIS.md](ANALYSIS.md)
- 전체 호스트 검사: `sh tools/check-all.sh` — 오라클 자체검사, 생성표 동기화,
  인용 대조, 단위 시뮬레이터. **새로 받은 트리에서는 먼저
  `sh tools/fetch-ref.sh`** — 인용 대조가 `ref/upstream/` 을 읽는다
- 참고 자료 목록과 재취득: [ref/README.md](ref/README.md)
- 공개 전 점검 목록: [docs/PRERELEASE.md](docs/PRERELEASE.md)

라이선스는 BSD 2-Clause(`LICENSE`). 드라이버에 컴파일되어 들어가는 R200 CP
마이크로코드(MIT, AMD)와 그 밖의 제3자 고지는 `NOTICE`, 참고 자료 라이선스표는
`docs/R0_4_LICENSES.md`.
