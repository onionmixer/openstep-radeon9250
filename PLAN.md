# openstep-radeon9250 — 작업 계획

작성 2026-09-15.  출발 자료는 워크스페이스 루트의
`radeon9250_rv280_opensource_driver_openstep_notes.md` 이고, 선례는
`openstep-matrox-remade`(G450, v1.3) 이다.  이 문서는 **계획**이며 아직
검토를 받지 않았다 — 순서는 계획 → 교차검토 → 재검증 → 코드다.

실기로 확인하지 않은 것은 `[미검증]` 으로 적는다.

---

## 0. 목표와 완료 정의

**목표**: OPENSTEP 4.2(i386) 에서 **PCI Radeon 9250(RV280)** 을 구동하는
새 `IOFrameBufferDisplay` 드라이버, 그리고 그 위에서 Mesa 3.4.2 포트
(`openstep-mesa342`)가 카드의 3D 엔진으로 그리게 하는 가속 라이브러리.

완료 정의 (단계별로 끊는다 — 앞 단계만으로도 쓸모가 있어야 한다):

| 마일스톤 | 완료 조건 |
|---|---|
| **D** 디스플레이 | 드라이버 단독으로 WindowServer/Workspace 가 여러 해상도·심도에서 동작, Configure.app 에서 선택, VGA 복구 절차 실증 |
| **V** VRAM·소유 | 실제로 쓸 수 있는 VRAM 하한을 에일리어싱 시험으로 증명, 드라이버가 강제하는 단일 클라이언트 임대 |
| **E** 엔진 | 오프스크린 단색 채우기·블릿이 CPU 되읽기로 비트 단위 일치, V 의 범위·임대 안에서 오프스크린 VRAM 을 유저 태스크에 매핑 |
| **C** CP | 마이크로코드 적재 후 링으로 보낸 패킷이 레지스터·스크래치에 반영됨을 되읽기로 확인, 유휴·타임아웃·영구 비활성화 경로 실증 |
| **R6** 3D 시험기 | 창 좌표 원시가 R200 래스터라이저로 그려짐 — Mesa 없이 소프트웨어 오라클과 픽셀 대조, 깊이·텍스처·블렌드 순으로 |
| **G1** Mesa(M 단계) | Mesa 삼각형 훅이 R6 의 경로로 그림 — 강제 HW/SW/섞인 프레임 대조와 계수기로 어느 층이 그렸는지 증명 |
| **G2** 3D(하드웨어 TCL) | Mesa 변환 앞단에 새 훅을 두고 정점을 객체 좌표로 보내 카드가 변환·조명 — 선택 목표, G1 의 측정이 이득을 보여줄 때만 |
| **P** 배포 | `.pkg` 드라이버·가속 분리, 설치·제거·복구 절차, 공개 저장소 |

## 1. 입력 사실 (확인된 것)

**하드웨어**
- 카드는 **PCI** Radeon 9250 (operator, 2026-09-15).  AGP 는 대상이 아니다.
  → AGP 브리지·AGP GART 는 계획에서 빠지고, 칩 내장 **PCI GART**(`AIC_*`)
  를 쓴다.
- VRAM 128 MiB(칩 사진 기준, Elixir N2DS25H16BT-5T ×4).  **레지스터로
  실측**할 것 — G450 은 탑재량을 끝내 못 재서 7 MiB 가드를 둬야 했다.
  주의: 두 참고가 다른 레지스터를 본다.  radeonfb 는 `CONFIG_APER_SIZE` 를
  `sc_memsz` 로 쓰고(`radeonfb.c:2880`) 64 MiB 로 자른다(`radeonfb.c:658-662`).
  xf86-video-ati 는 **전체** = `CONFIG_MEMSIZE`(0x00f8), **CPU 접근 가능량**
  = `CONFIG_APER_SIZE` 기반이며 RV280 은 그 ×2(2 세대 PCI 인터페이스), 다시
  **BAR0 크기로 자른다** (xf86 `radeon_driver.c:1523-1653`).  단 xf86 은 그
  ×2 를 위해 `HOST_PATH_CNTL.HDP_APER_CNTL` 을 **쓴다**(`radeon_driver.c:1694-1704`) —
  R1 은 이 레지스터를 읽기만 한다.  세 값(MEMSIZE, APER_SIZE×HDP, BAR0)을
  모두 읽어 대조한다.
- PLL 기준값(refclk/refdiv/minpll/maxpll): radeonfb 는 레거시 BIOS 의 PLL
  블록(`p = BIOS16(0x48); p = BIOS16(p+0x30)`; refclk `+0x0e`, refdiv `+0x10`,
  minpll `+0x12`, maxpll `+0x16`)에서 읽는다.  **단 RV280(비-R300) 의
  refdiv 는 살아 있는 `PPLL_REF_DIV` 레지스터 값이 먼저**이고 BIOS 는
  폴백이다(`radeonfb.c:1697-1714`).  BIOS 가 없으면 기본값
  27.00 MHz / 12 / 125–400 MHz(`:1671-1687`, 저장 시 ×10 kHz).
  주 VGA 로 POST 된 카드면 BIOS 사본이 `0xC0000` 셰도에 있어 **ROM 을 켜지
  않고 읽을 수 있다** `[미검증]` — 선례: xf86 `radeon_bios.c:77-87` 은 PCI
  ROM 읽기가 실패하고 주 디스플레이면 `0x000c0000` 을 읽는다(서명 55 AA 확인).
- RV280 PCI ID: 두 목록이 다르다 — FreeBSD `drm_pciids.h:113-117,128-129`
  는 5960 5961 5962 5964 5965 5c61 5c63, NetBSD `radeonfb.c:311-317` 은
  5960 5961 5962 **5963** 5964 5c61 5c63.  합집합 8 개를 쓴다.
  이 카드의 실제 ID 는 R1 에서 읽는다.
- 실기 기록(`pcils/scan-nextonion.txt`)상 머신은 Intel 865G.  G450 은
  `04:00.0` 이고 `00:1e.0` → **`03:0d.0`(HiNT HB4 PCI-PCI 브리지)** 두 단
  뒤에 있다(`scan-nextonion.txt:79-87`).  두 브리지의 prefetch 창은 모두 `f8000000-f9ffffff`
  = 32 MiB(Python 해독) — G450 BAR0 크기다.  Radeon 의 BAR0 가 더 크면
  BIOS 가 창을 다시 잡아야 하므로 **R1 에서 브리지 창도 기록**한다.
- **Radeon 은 G450 을 빼고 그 대신 쓴다** (operator, 2026-09-15).  두 카드
  공존은 대상이 아니다.  주 VGA 로 POST 되는지는 R1 에서 확인한다(865G
  내장 그래픽이 있으므로 BIOS 의 주 디스플레이 선택이 PCI 카드인지 확인).

**참고 구현 (BSD 가 주, `ref/README.md`)**
- NetBSD `radeonfb`: 2D 엔진을 **CP 없이 MMIO 로 직접** 구동한다
  (`radeonfb_engine_init` — `RB3D_CNTL=0`, `DP_GUI_MASTER_CNTL`, 피치 오프셋).
  G450 Storm 과 같은 모양이다.  (`radeonfb.c:424` 의 RV280 행은 **TMDS
  (DVI) PLL 표**라 VGA 전용 첫 판과 무관 — 픽셀 PLL 은 `radeonfb_calc_dividers`.)
- FreeBSD 레거시 DRM: GART 페이지 테이블을 **VRAM 안(`DRM_ATI_GART_FB`)**
  에 두는 커널 경로가 있으나 **유저가 `PCIGART_LOCATION` 을 준 경우에만**
  이다(`radeon_cp.c:1398-1443`).  xf86 6.14.6 은 그 값을 **PCIE 에서만**
  준다(`radeon_driver.c:3763-3769`) → 재래식 PCI 의 참고 기본은 시스템
  메모리 테이블(`GART_MAIN`)이고, **"PCI + VRAM 테이블" 은 참고 구현이 쓴 적
  없는 조합**이다.  테이블 32 KiB(`radeon_drv.h:1823`) = 8192 항목 × 4 KiB
  = **용량** 32 MiB, 실제 창은 `init->gart_size`(`radeon_cp.c:1329`)이고
  xf86 의 R300 이전 기본값은 **8 MB**(`radeon_dri.h:42`).  항목은 4 KiB
  단위(`ati_pcigart.c:39`).
- CP 마이크로코드는 헤더판 `radeon_microcode.h`(MIT, AMD) 와
  linux-firmware `R200_cp.bin`(MIT) 둘 다 확보.
- `CSQ_PRIPIO_*`(PIO 명령 큐) 는 헤더에 **정의만 있다** — 7 트리 25 건
  전부 `#define`(Python 재집계).  게다가 FreeBSD·Linux DRM 은 PRIBM 두 모드
  외의 cp_mode 를 **명시적으로 거절**한다(`radeon_cp.c:1165-1173`).  G450 의
  1 차 DMA VERTEX 모드처럼 "선례 없는 모드" 다.

**OPENSTEP 플랫폼 (Matrox 에서 실측, 그대로 유효)**
- **`IODisplayDoBlit` 은 사문화됐다** — WindowServer 는 프레임버퍼를
  `mmap` 해서 CPU 로 그린다.  **노트 문서 §11 Phase 4 의 "2D 가속이
  WindowServer 체감 성능을 올린다"는 OPENSTEP 4.2 에서 성립하지 않는다.**
  2D 엔진의 쓸모는 엔진 생존 확인과 Mesa 의 clear/present 뿐이다.
- 커서는 커널 소프트웨어 커서(FB 를 CPU 로 저장·복원), 락은 비공개.
- FB 매핑은 `mapFrameBufferAtPhysicalAddress:length:` 로(생 매핑은 부팅
  WindowServer 를 걸었다).  MMIO 는 `IOMapPhysicalIntoIOTask` 로 된다.
- 커널 VM 페이지 **8 KiB**.  GART 항목(4 KiB) 은 페이지당 2 개.
- `mmap` 은 4.2BSD 판(자리를 `vm_allocate` 로 먼저 잡고, 반환값은 성공
  여부뿐), `d_mmap` 은 같은 오프셋에 두 번 불리고 2 차에 `-1` 검사가 없다.
- `IOMallocLow` 는 **64 KiB 이하, conventional memory 아레나**.
- `IOPhysicalFromVirtual` 은 `driverkit/kernelDriver.h:80` 에 있다
  — 비연속 페이지를 GART 에 올릴 때 쓸 후보 `[미검증]`.
- syslog 는 버스트를 버린다.  타깃 grep 은 `\|` 교대를 조용히 0 건 처리.
- Mesa 포트는 **특정 드라이버 이름이 없는 가속 훅** 10 개를 `OPENSTEP_MESA_ACCEL_HOOK`
  매크로 안에 선언한다(`openstep-mesa342/upstream/Mesa-3.4.2/src/OSmesa/osmesa.c` 52–117 행):
  `UpdateState`, `Buffer`, `DepthBuffer`, `ReleaseBuffer`, `BoundTo`, `AppBuffer`,
  `CopyDepth`, `Mirror`, `Stride`, `ClearPixel`(접두 `OpenStepMesaAccel`).  stock 빌드는
  매크로 없이 컴파일되어 훅이 없고, 가속 라이브러리는 **10 개 모두** 정의해야 한다.
  (정정 2026-09-15: 처음 계획은 7 개로 적었다.)
  Matrox 는 `libGL_mga.a` 로 이것을 채운다.  Radeon 도 **같은 훅을 채우는
  `libGL_radeon.a`** 로 가면 `openstep-mesa342` 를 건드리지 않고 G1 까지 간다.
  SDL2 의 present 훅 ABI(`SDL_OpenStepGLPresent`) 도 같다.

## 2. 비목표와 금지

**비목표**: AGP·AGP GART, 듀얼 헤드·DVI/TMDS(첫 판은 VGA 출력 하나),
TV-out, 하드웨어 커서, WindowServer 2D 가속, 비POST 카드 초기화(첫 판은
BIOS 가 POST 한 카드 전제 — 설치 전제이자 조건부 차단 요인), m68k.
**미룬 대비책(비목표 아님)**: IRQ — 첫 판은 폴링이지만, CP 단계에서 설명되지 않는 행이나
과도한 폴링 간섭이 나오면 다시 연다(Matrox 3-62 에서 폴링 완료 토폴로지가 유일하게 남은
구조적 차이였다, Q6).

**금지** (기존 사고에서 나온 규칙 — 설계 전에 대조할 것):
1. 살아 있는 소유자(VGA 콘솔·WindowServer) 밑에서 CRTC·PLL·DAC·
   `MC_FB_LOCATION`·`SURFACE_CNTL` 을 kl_util 등으로 재프로그래밍하지 않는다.
   모드 변경은 **부팅 활성화 경로**에서만.
2. 리셋·PLL 전이 시퀀스는 **참고 구현의 순서를 그대로** 따르고, **참고에 없는
   읽기·쓰기를 그 창에 끼워 넣지 않는다**.  (정정, Q2: 82547 의 "리셋 직후 읽기
   금지" 를 일반화했었으나 radeonfb·FreeBSD DRM 은 `RBBM_SOFT_RESET` 을 쓴 직후
   같은 레지스터를 **일부러 읽는다**, 대기 0 — `radeonfb.c:3919-3935`,
   `radeon_cp.c:631-650`.)  근거는 문서에 적는다.
3. 실험용 커널 모듈은 `ADVERTISE` 하지 않는다(재적재가 kern_loader 를 태운다).
4. 설치 전 `nm -u` 로 미해결 심볼 0 확인 — 컴파일 성공은 적재의 증거가 아니다.
5. 재부팅은 operator 몫.  설치까지만 하고 요청한다.
6. 버스 마스터(CP 링·GART) 를 켜는 코드는 **주소 창을 검증한 뒤**에만 —
   잘못된 GART 항목은 GPU 가 시스템 메모리를 임의로 쓰게 한다.
7. 커밋 파일에 실 IP 금지(`etc/site.conf`), 공개 전 이력 blob 전수 검사.
8. **모든 대기 루프에 상한과 종결 실패 걸쇠**를 둔다.  참고 구현에는 무한 대기가
   있다(`radeonfb_pllwriteupdate` 의 `while`, xf86 MC 대기는 타임아웃 로그 후에도
   계속 돈다 — `radeonfb.c:2128-2139`, `radeon_driver.c:4127-4145`).  그대로
   옮기지 않는다(Matrox `REMAINING_WORK.md` 3-61).  대기는 **절대 기한**(진행이 보여도
   기한을 되돌리지 않는다 — `radeon_wait_ring` 은 되돌린다), 실패는 반환값으로 전파
   (참고의 `BEGIN_RING`·적재기는 무시한다), 실패 기록은 **추가 GPU 읽기 전에 RAM 에**
   (진단 읽기가 행이면 기록까지 사라진다, Matrox `REMAINING_WORK.md:4043-4049`),
   로그 한 번 뒤 영구 비활성화 — 무한 리셋·재시작 금지.  단 **PCI 읽기 자체가 안
   돌아오는 행은 루프 상한으로 못 막는다** — 그래서 위험 작업은 nxlogd(NFS
   fsync) 로그를 켠 부팅에서만 한다.
9. "모든 쓰기 후 되읽기" 는 **되읽기가 성립하는 레지스터에만**.  리셋 레지스터,
   되읽기 반전 비트(RV280 `TMDS_PLL_CNTL` bit 22, `radeonfb.c:2617-2623`),
   원자적 갱신 비트(`PPLL_ATOMIC_UPDATE_R` = `_W`, `radeonfbreg.h:1529-1530`)는 제외.

## 3. 저장소 구조 (계획)

Matrox 와 같은 모양, 이름만 짧게(§9 결정 1).

```
openstep-radeon9250/
  README.md  PLAN.md  ANALYSIS.md(하드웨어 사실)  LICENSE  NOTICE  .gitignore
  docs/            단계별 계획서·결과 (R1_…, R5_…, M1_…)
  ref/             README.md 만 커밋, upstream/ 은 fetch-ref.sh
  tools/           fetch-ref.sh, 빌드·설치·로그 수집(루트 tools/ 사본을 자립화)
  probe/           R1 bare loadable probe
  OSRDNDisplay/    디스플레이 드라이버 번들 (+ 인스펙터, nib-src)
  hw3d/            CP·명령 인코더·검증기 (호스트 테스트 가능한 C89)
  mesa/            libGL_radeon.a — OpenStepMesaAccel* 훅 구현
  test/            실기 프로브, 호스트 회귀
  pkg/             OSRDNDisplay.pkg, OSRDNMesaAccel.pkg
```

## 4. 공통 절차

모든 단계: **계획 문서(docs/) → codex 교차검토(질문은 내 선택지를 전제하지
않게) → 회신 재검증 → 코드 → 호스트 검사(C89·`#import` 규칙·심볼표 대조)
→ 실기 빌드 → `nm -u` → 설치 → 재부팅 요청 → 로그/되읽기 판정 → 결과를
docs/ 와 TEST_STATUS 에 기록.**

- 새 하드웨어 동작은 **config 키로 옵트인**, 기본값은 꺼짐.  평상시 부팅은
  새 레지스터를 쓰지 않는다.
  **예외(operator 승인 2026-09-15, D-3)**: 디스플레이 소유자 교체(R2 첫 모드셋)는 `Active Drivers`
  편집 자체가 옵트인이다 — 기본 꺼짐 키는 VGA 가 빠진 부팅에 화면 소유자를 없앨 뿐이다.  R3 이후
  추가 기능은 규칙 그대로 키.
- 판정은 로그 문구가 아니라 **되읽기 값**(체크섬은 독립 재계산).  로그
  grep 은 이번 부팅 마커와 함께.
- 위험은 쪼갠다: 화면 밖에서 먼저(오프스크린), 가시 영역은 앞 것이 PASS
  했을 때 런타임 조건으로만.
- 실패를 보면 피검체보다 검사기를 먼저 의심한다.
- **아무것도 검증하지 않는 게이트 금지**(Q6, Matrox 3-26·3-48·3-51·3-70 회고): 모든 게이트는
  대상 경로의 **양의 진입·완료 계수**와 0 이 아닌 작업량을 요구하고, 검사기 자신이 실패하는
  **변이**(한 줄을 망가뜨린 사본)를 같은 실행에서 함께 돌린다.
- **산출물 출처 사슬**(Q6, Matrox 3-44·3-50): 소스 리비전 → 깨끗한 타깃 빌드(종료 코드를 버리지
  않음) → 설치된 바이트의 해시 → 부팅 로그에 찍힌 빌드 식별자가 한 줄로 이어져야 판정한다.
- **FIFO 정확 계수**(Q6, Matrox 3-63): 엔진 레지스터 묶음마다 예약한 칸 수 ≥ 실제 쓰기 수를
  호스트에서 기계적으로 검사, 반복문 안 쓰기는 따로 선언.  (radeonfb 는 반복문 밖 경로에서
  예약과 쓰기가 모두 일치한다 — Python 계수, `docs/review/Q6_verdict.md` 3d.)
- **엔진 상태 소유**(Q6): 2D 블릿·CP/3D·present·모드 전환·복구가 같은 엔진을 쓰므로, 사용
  뒤 중립 상태 복원 또는 상태 소유자·세대(epoch) 중 하나를 V/R4 계획서에서 정한다.

---

## 5. 단계

### R0 — 기준선 (하드웨어 무접촉)

1. `ANALYSIS.md`: RV280 레지스터 사실표 — MMIO BAR 배치, `CONFIG_MEMSIZE`,
   `CONFIG_APER_SIZE`, `MC_FB_LOCATION`, CRTC/PLL 인덱스 접근(`CLOCK_CNTL_INDEX`),
   2D 엔진·FIFO(`RBBM_STATUS`), CP(`CP_RB_*`, `CP_CSQ_CNTL`, `CP_ME_RAM_*`),
   `AIC_*`, 스크래치.  각 항목에 **BSD 출처 파일:줄** + 교차확인 출처.
2. radeonfb 의 RV280 모드셋 경로를 순서대로 해독한 문서
   (`radeonfb_setcrtc` → `radeonfb_program_vclk` → `radeonfb_calc_dividers`,
   RV280 분기 `radeonfb.c:2626` 등).
3. VGA 복귀 경로: radeonfb 는 VGA 로 돌아가지 않는다 →
   xf86-video-ati `legacy_crtc.c` 의 저장·복원을 해독(`revertToVGAMode` 용).
4. 라이선스표(옮길 코드 / 사실만 참고) → `NOTICE` 초안.
5. 실기 도구 자립화: 루트 `tools/`·`pcils`·Matrox 의 `hostcheck` 류를 복사.

**Gate**: 사실표의 모든 항목에 출처가 있고, 모드셋·VGA 복귀 시퀀스가
레지스터 단위로 적혀 있다.

### R1 — 카드 설치와 조사 (하드웨어 쓰기 없음)

전제: operator 가 G450 을 빼고 Radeon 을 설치한다(결정됨).  G450 드라이버
(`OSMGADisplay`)가 Active Drivers 에 남아 있으면 먼저 VGA 로 되돌린다.
**복구 기준선은 generic VGA(`IOVGADisplay`) 단독 소유 부팅** — G450 에서
안전했던 방법(Matrox H1)이지 RV280 에서 증명된 것은 아니다(Q2).
**nxlogd(NFS fsync) 로그를 켠 부팅에서만** 한다 — PCI 읽기가 돌아오지 않는 행은
루프 상한으로 못 막고, 로컬 로그는 행과 함께 사라진다(Matrox `REMAINING_WORK.md`
`REMAINING_WORK.md:4048-4053`).

조작 등급을 섞지 않는다:

| 등급 | 항목 | R1 에서 |
|---|---|---|
| A. PCI config 읽기 | vendor/device/rev/subsystem/class, command/status, BAR 0/1/2 값, ROM BAR 값, 상위 브리지(`00:1e.0`·`03:0d.0` 또는 새 위치)의 memory/prefetch 창 | **한다** |
| B. MMIO 직접 읽기 | 아래 목록 | **한다** (bare loadable, CALL/WIRE/START, 광고 없음) |
| C. 셰도 메모리 복사 | `0xC0000` 고정 크기(예: 64 KiB) **복사만**, 파싱은 호스트 Python 에서 | **한다** |
| D. config 쓰기 | BAR write-1s sizing | **안 한다** — 애퍼처는 `CONFIG_APER_SIZE`, 창은 A 로 충분 (Q2) |
| E. 인덱스 읽기(= 인덱스 쓰기 포함) | `CLOCK_CNTL_INDEX` 경유 PLL 레지스터 | **안 한다** — 필요하면 저장·복원 등급으로 별도 계획 |
| F. VRAM 쓰기 | 탑재량 실측(패턴 쓰기·에일리어싱) | **안 한다** — R2 이후 드라이버 소유 상태에서 |

B 목록: `CRTC_CRNT_FRAME`(0x0214)·`CRTC_VLINE_CRNT_VLINE`(0x0210) 여러 번 표본
(VLINE 은 11 비트라 **되감긴다** → 판정은 "FRAME 증가 + VLINE 값이 표본마다
다름"), `CONFIG_MEMSIZE`, `CONFIG_APER_SIZE`, `CONFIG_APER_0_BASE`,
`HOST_PATH_CNTL`(HDP_APER_CNTL), `CLOCK_CNTL_INDEX`(현재 인덱스·`PLL_DIV_SEL` — MMIO
직접 읽기, 인덱스를 바꾸지 않음), `MC_FB_LOCATION`, `MC_AGP_LOCATION`,
`DISPLAY_BASE_ADDR`, `CRTC_GEN_CNTL`, `CRTC_EXT_CNTL`, `CRTC2_GEN_CNTL`,
`DAC_CNTL`, `DAC_CNTL2`, `DISP_OUTPUT_CNTL`, `FP_GEN_CNTL`, `SURFACE_CNTL`,
`BUS_CNTL`(BUS_MASTER_DIS), `RBBM_STATUS`, `CP_CSQ_CNTL`, `CP_RB_CNTL`,
`CP_RB_RPTR`, `CP_RB_WPTR`, `AIC_CNTL`, `GEN_INT_CNTL`, `GEN_INT_STATUS`.
각 레지스터 오프셋은 R0-1 사실표에서 가져오고, 읽기 부작용이 소스에 적힌
레지스터(인터럽트 상태 ack 등)가 있으면 목록에서 뺀다.

C 판정: `55 AA`, PCIR 구조의 vendor/device 가 A 의 값과 같음, ATOM 이 아닌
레거시 BIOS(xf86 `radeon_bios.c:380-427` 의 판별).  PLL 블록은 경계 검사하며
`p = BIOS16(0x48); p = BIOS16(p+0x30)` 을 따라간다.  refdiv 는 RV280 에서
레지스터 값이 우선이라(E 를 안 하므로) BIOS 값만 기록한다.

**Gate**: A·B·C 결과 기록, 탑재량 **보고값**(MEMSIZE·APER×HDP·BAR0) 대조표,
스캔아웃 생존 판정, BIOS 가 둔 MC 맵·출력 경로 스냅샷, **등급 D·E·F 조작 0 건**.

### R2 — 첫 점등 (단일 모드)

G450 교훈: BIOS 가 남긴 VGA 모드는 리니어 고해상도가 아니므로 노트의
"Phase 2 BIOS 모드 유지" 는 건너뛰고 **네이티브 모드셋 하나**로 간다.
새 활성화 부팅에서만(모듈 재적재 금지), nxlogd 켠 상태로.

1. `OSRDNDisplay : IOFrameBufferDisplay` — PCI Auto Detect 매칭, init 에서
   BAR 런타임 읽기, **init 은 하드웨어 쓰기 없음**.
2. `enterLinearMode`: 안전 모드 **1024×768@60, RGB:888/32** 하나.  **쓰는
   레지스터군과 순서의 정본은 R0-2 해독 문서**다.  계획 단계에서 확정한 필수
   항목(Q2): 첫 쓰기 전에 전체 상태 스냅샷 → 블랭크(`CRTC_EXT_CNTL.DISPLAY_DIS`)와
   메모리 요청 차단(`CRTC_GEN_CNTL.DISP_REQ_EN_B`)은 **다른 제어**로 다룸 →
   MC 맵은 **R1 값과 다를 때만** 다시 쓰고, 쓸 때는 CP 정지·엔진 유휴·CRTC1/2
   요청 차단·오버레이 끔·AGP 위치 먼저 치움·RV280 크기 정렬
   (xf86 `radeon_driver.c:1498-1513`)·100 ms 전후 대기 → CRTC_GEN/EXT 필드 →
   타이밍 4 워드(`tools/oracle/radeon_modeset.py` 값) → PPLL 전이(CPU 클럭 선택 →
   리셋·원자 갱신 → 분주 → 갱신 요청 → **비트 15 가 내려갈 때까지 상한 있는
   대기** → `HTOTAL_CNTL` → 리셋 해제 → 50 ms → PPLL 선택 → 픽셀 클럭 게이트 해제)
   → 오프셋·피치·`DISP_MERGE_CNTL` → DAC 경로·전원(`DAC_CNTL` MASK_ALL/8BIT,
   `DAC_CNTL2`, `CRTC_EXT_CNTL.CRT_ON`) → 비활성 출력(FP/TMDS/CRTC2) 정책 →
   `SURFACE_CNTL` 타일링 해제 → 팔레트(클럭 게이트·팔레트 선택 프로토콜) →
   언블랭크 → FB clear(애퍼처·보고 VRAM 경계 안).
3. `revertToVGAMode`: **스냅샷이 유효하고 이 드라이버가 하드웨어를 바꾼 경우에만**
   복원한다 — OPENSTEP 은 부팅 때 revert 를 enter **보다 먼저** 부르고, 종료 때는
   revert 를 부르고, 로그아웃은 둘 다 안 부른다(Matrox `REMAINING_WORK.md`
   `REMAINING_WORK.md:3310-3317`, `REMAINING_WORK.md:3579-3604`, `REMAINING_WORK.md:3639-3646`).  부분 진입 실패에서도 복원,
   반복 호출은 멱등.  복원 목록·순서의 정본은 R0-3 문서(xf86 `RADEONRestore`:
   DAC 마지막, 원래 켜져 있던 CRTC 만 다시 켬).
4. FB 매핑은 `mapFrameBufferAtPhysicalAddress:length:`.
5. 모든 쓰기 후 되읽기 로그, 모드 레지스터 스냅샷을 NFS 로.

**Gate**: 활성화(System.config Active Drivers) 부팅에서 Workspace 동작 — 단 **이 드라이버가
그렸다는 양의 증거**(부팅 로그의 빌드 식별자·설치 바이너리 해시 일치, 모드 레지스터 되읽기가
1024×768 오라클 값과 일치; generic VGA 나 낡은 번들로도 Workspace 는 뜬다, Q6), 복구(설정
되돌림+재부팅) 실증, 종료 시 VGA 콘솔 복귀 확인, 대기 루프는 **진입 횟수 > 0 이고** 상한 도달 0
(진입 0 이면 경로가 안 돈 것).

### R3 — 다중 모드·심도·Configure

해상도표 × 포맷표(RGB:888/32, RGB:555/16 또는 565/16 — RV280 이 무엇을
스캔아웃하는지 R0 에서 확정, RGB:256/8, BW:8), `setTransferTable:count:`,
`IO_DISPLAY_HAS_TRANSFER_TABLE` 광고, `Display.modes`, Matrox 식 인스펙터
(Configure 의 `DisplayInspector.nib` 재사용 + openstep-nibmaker 로 스위치 이식).

**Gate**: **광고하는 조합(`Display.modes`) 전부**를 실기에서 확인한다 — 확인 못 한 조합은
광고에서 뺀다(Q6: "대표 조합 + 미확인 표기" 는 실패할 수 없는 게이트였다).  각 조합에서 모드
레지스터 되읽기, 팔레트/전달표 픽셀 확인, 재부팅 뒤 설정 유지.

**operator 결정 (2026-09-18, 위 게이트를 대체)**: `Display.modes` 는 Matrox 처럼 **20 줄 전부**
광고하고(`docs/R3_MULTIMODE_PLAN.md` 24-21), 부팅해 보지 않은 조합의 실기 확인에는 매달리지 않는다
("부팅해보지 않은 조합은 집착하지 마세요").  모든 행의 값은 오라클이 만들고 NetBSD·Matrox 와 대조돼
있으며 호스트 시뮬레이터가 20 조합을 돌린다.  실기 확인 7 조합과 Configure 인스펙터(Gray Levels,
16 단계 회색 실기 확인)로 **R3 완료**(`docs/R3_MULTIMODE_PLAN.md` 27-7).

### V — VRAM 실측과 할당·소유 (R3 뒤, R4 앞 — Q6)

R1 은 레지스터 **보고값**만 읽는다.  매핑·GART 창·색/깊이 표면·텍스처 범위를 내놓기 전에
실제로 쓸 수 있는 VRAM 범위를 증명하고, 그 범위를 나눠 줄 주체를 정한다.

1. **탑재량 실측**: 드라이버가 화면을 소유한 부팅에서, 가시 영역 밖 고역부터 저장 → 위치
   인코딩 패턴 쓰기 → 에일리어싱(낮은 주소에 같은 패턴이 비치는지) 되읽기 → 원복.  결과는
   "증명된 하한" 이고, 증명 전에는 보수적 하한만 쓴다(Matrox 가 끝내 못 재 7 MiB 가드를 둔
   교훈).
2. **할당자와 소유**: 첫 판은 **드라이버가 강제하는 단일 클라이언트 임대**(동시에 한 태스크만
   가속 표면·제출 권한을 가짐)로 단순화한다 — Matrox 3-35 는 공유 창으로는 두 클라이언트의
   덮어쓰기를 "이 인터페이스로는 못 고친다" 로 끝났다.  임대마다 세대(epoch), 모드 전환·임대
   회수 시 매핑 수명 규칙(회수 뒤 접근 금지), 동시 모드 전환/제출/재바인드 시험.
3. 이 단계의 산출물(증명된 범위, 임대·할당 표)을 R4c·R5b·R6·M 이 입력으로 쓴다.

**operator 결정 (2026-09-18)**: **VRAM 은 128 MiB 로 가정한다**("VRAM 은 현재 128M 로 가정해도 됩니다").
R1 의 보고값과 같다 — `CONFIG_MEMSIZE` 128 MiB, `CONFIG_APER_SIZE` 128 MiB(`docs/R1_RESULT.md` 35 행).
따라서 1 항(탑재량·에일리어싱 실측)은 하지 않는다.  남는 것은 2 항(할당·소유: 단일 클라이언트 임대,
세대, 회수 뒤 접근 금지)이며, 첫 소비자가 R4c(오프스크린 매핑)이므로 **R4 계획에 합쳐** 설계한다.
오프스크린은 가시 프레임버퍼 매핑(`OSRDN_FB_LENGTH` 8 MiB) 뒤부터 128 MiB 끝까지이고, R5 의 GART 창·
링 배치와 겹치지 않게 R4 계획에서 구간표를 python 으로 만든다.

**operator 결정 (2026-09-18, "matrox 정도 기준")**: 창은 **Matrox 식** — 시작 = 모드마다 `pageup(보이는 화면 + 가드 256 행)`,
끝 = 128 MiB − 위쪽 여유 4 MiB(`docs/R4_ENGINE_PLAN.md` 11 절).  **임대는 두지 않는다**(Matrox 와 같이 고정 창 +
협조적 단일 클라이언트, 문서로) — close 가 클라이언트마다 오지 않고 매핑은 회수할 수 없다(Matrox 3-35·S4a 7-2).
2 항의 강제 임대·세대·회수 규칙과 아래 게이트의 "임대" 항목은 **R6/M 의 할당자 설계로 연기**한다(그때 다시 연다).

**Gate**: 실측 하한과 에일리어싱 판정 로그(양의 패턴 수), 임대 거절·회수·세대 불일치 경로가
각각 한 번 이상 실행된 계수, 변이(에일리어싱을 흉내 낸 가짜 되읽기)가 실패함.

### R4 — 2D 엔진과 VRAM 매핑

1. R4a 오프스크린 단색 채우기 + uncached 별칭 되읽기 체크섬
   (radeonfb `radeonfb_rectfill` 레지스터열, FIFO 대기).
2. R4b 오프스크린→오프스크린 블릿(위치 인코딩 패턴), 겹침 방향.
3. R4c 오프스크린 VRAM 을 문자 디바이스 `d_mmap` 으로 유저 태스크에
   (major 자동 할당, 창은 **Matrox 식 모드별 시작 ~ 124 MiB**, 가시 영역·창 밖 거부; 임대 없음 — V 절 operator 결정).
   **매핑이 켜지면 드라이버 언로드 금지**(매핑이 close 보다 오래 산다).

**Gate**: Matrox S1/S2/S4a 와 같은 판정표 전항 PASS — 단 공개 창의 **상한 경계**(끝 페이지 허용·다음 페이지 거절)와
`d_mmap` 결정성, 창 끝 근처 쓰기 뒤 64 MiB 아래 표지 불변(에일리어싱)을 포함한다.  ~~임대가 없는 태스크의 거절~~ — 이
인터페이스로 강제할 수 없어 R6/M 으로 연기(V 절 operator 결정 2026-09-18).

### R5 — Command Processor

이 단계가 이 프로젝트의 최대 미지수다.  위험 순서로 쪼갠다.  (Q3 판정
`docs/review/Q3_verdict.md` 반영.)

- **R5a 마이크로코드 적재만**: CSQ 가 꺼져 있음(`CSQ_PRIDIS_INDDIS`)과 엔진 유휴
  (FIFO 64 → `RBBM_ACTIVE` 0, 절대 기한)를 **확인한 경우에만** `CP_ME_RAM_ADDR`=0 →
  256 쌍 `DATAH=cp[i][1]`, `DATAL=cp[i][0]`(`radeon_cp.c:523-530`).  참고 적재기는
  유휴 대기 실패를 무시하지만 우리는 중단한다.  **ME RAM 되읽기는 게이트에서 뺀다** —
  어느 참고도 되읽지 않아 읽기 의미가 미확인이다.  데이터 검증은 CPU 쪽
  (`tools/oracle/check_microcode.py`)과 R5c 의 기능 시험으로 한다.  적재 전 CP 리셋·
  클럭 강제·지연 같은 전제는 **만들어 넣지 않는다**(소스에 없음).
- **R5b 링 위치** (§9 결정 3, R5 계획서에서 결정):
  | 선택지 | 근거 |
  |---|---|
  | (가) 일반 wired 커널 페이지 링 + PCI GART, **테이블은 시스템 메모리** | 참고 기본(`GART_MAIN`) — **기본안** |
  | (나) (가) 와 같되 테이블은 VRAM | 커널 경로는 있으나 재래식 PCI 에서 쓴 적 없음 |
  | (다) `IOMallocLow`(≤64 KiB, <640 KiB 공유 아레나) 링 + GART 항목 몇 개 | 선례 없음, 아레나 소비 |
  | (라) VRAM 안 링(`CP_RB_BASE` 가 FB 안) / GART 없는 버스 주소 링 | **미확인** — 소스에 없음 |
  | PIO 큐(`CSQ_PRIPIO_*`) | 링 위치가 아님, 운용 프로토콜 미확인 |
  GART 조건: PTE = `le32(bus & 0xfffff000)`, 32 비트, 4 KiB 단위 — **8 KiB 페이지는
  반쪽마다 물리 주소를 확인**하고, 테이블 용량은 Linux `max_real_pages` 식으로
  (FreeBSD 식은 8 KiB 페이지에서 테이블을 넘친다 — Q3 판정 5b).  창은 FB 끝 뒤 4 MiB
  정렬(`radeon_cp.c:1346-1361`), **정렬 뒤** FB·GART 창·테이블·오프스크린 할당 구간이
  서로 겹치지 않음을 계산으로 검증.
- **R5c 첫 명령**: 순서 — writeback **둘 다 끈 상태**(`CP_RB_CNTL.RB_NO_UPDATE`,
  `SCRATCH_UMSK=0`)에서 `BUS_MASTER_DIS` 해제·CSQ 켬(참고는 writeback 을 켠 채 버스
  마스터를 켜지만 우리는 반대) → 참고 시작 스트림(`ISYNC_CNTL`, `RB3D_DSTCACHE/ZCACHE`
  퍼지, `WAIT_UNTIL`, `radeon_cp.c:582-593`) → 스크래치 `PACKET0` 표지 → **레지스터
  직접 되읽기** 일치 + `CP_RB_RPTR` 전진 → 유휴(절대 기한).  `PACKET2` 는 패딩일 뿐
  완료 판정이 아니다.
- **R5d 실패·해제 상태 기계**: 새 제출 거절 + 영구 실패 걸쇠 → (응답하면) 유휴 시퀀스와
  절대 기한 대기 → 유휴 실패여도 CSQ 끔 → writeback 둘 다 끔 → CP 정지/리셋 → GART
  `PCIGART_TRANSLATE_EN` 해제 → **그 뒤에만** 링·rptr 페이지·GART 테이블 해제 →
  `BUS_CNTL.BUS_MASTER_DIS` 는 스냅샷 값으로.  참고의 무한 유휴 재시도(lastclose,
  `radeon_cp.c:1693-1704`)와 진행 시 기한 연장(`radeon_wait_ring`)은 옮기지 않는다.
  늦게 도착한 쓰기가 SW 폴백 결과를 덮는 Matrox S3a 교훈에 따라 실패 뒤 가속은 영구 비활성.
  **개정(2026-09-18, `docs/R5_PLAN.md` 7-1 E1·`docs/R5D_PLAN.md` 7)**: 걸쇠 뒤에는 **`CSQ_CNTL=0` 쓰기 하나 + `RBBM_STATUS` 읽기 하나**만 —
  유휴 시도·GART 해제·블록 해제·AGP 창 복원은 **하지 않는다**(멈춘 CP 가 페치 중이면 GART 를 끄는 순간 번역 없는 주소로, AGP 창을 되돌리면
  응답 없는 구간으로 나간다).  블록은 해제하지 않아 모든 PTE 가 계속 응답하는 메모리를 가리키고, 회복은 재부팅.  `BUS_CNTL` 은 읽기만 하므로
  복원할 것이 없다.  위 순서는 **깨끗한 STOP**(유휴 확인 뒤)에만 해당한다.

**Gate** (Q6 로 강화):
- R5a 는 **노출·안전 하위 게이트**일 뿐(유휴 확인 후 적재 완료) — 마이크로코드가 맞는지는 R5c 가
  닫는다.
- R5b 는 구간 비겹침 계산 + GPU 가 실제로 읽는 시험: **8 KiB 페이지의 두 반쪽**, 여러 PTE, 링
  **감김(wrap)**, 경계 밖 가드 PTE·카나리아 불변.
- R5c 는 무작위 표지 여러 개를 순서대로, 링 여러 바퀴·페이지 경계 넘김, 레지스터 직접 되읽기
  일치·RPTR 전진·유휴, 가드 불변.
- R5d 는 **실제 제출이 있은 뒤** 실패 주입(주입 계수 > 0, 제출 증명), 걸쇠 뒤 제출 거절, 해제
  순서 로그, 카나리아 불변·늦은 쓰기 없음, 부팅 회귀 없음(WindowServer·커서·모드 전환).
  **개정(2026-09-18, `docs/R5D_PLAN.md` 7)**: 해제 순서 로그 = 연산별 MMIO 쓰기·읽기 계수(걸쇠 STOP `wr=1 rd=1`), 걸쇠 뒤 GART·AGP 는 그대로임을
  되읽기로, 재부팅 회복은 이 드라이버만 쓰는 레지스터 값들이 부팅값으로 돌아왔음으로(warm reboot).  주입은 건강한 CP 에서(페치 중 걸쇠는 시험하지
  않음 — 한계).
  **R5d 실기 PASS(2026-09-18, 부팅 eae3072b + e457149e, `docs/R5D_PLAN.md` 10).**  R5 전체(C 마일스톤) 닫힘 — 단 깨끗한 STOP 의 잠복 결함(CSQ 를 끄면
  `RB_RPTR` 이 0 으로 읽히는데 그 뒤에 rptr==wptr 를 본다) 수정이 남음.

### R6 — 최소 3D 하드웨어 시험기 (창 좌표 정점, TCL 우회, **Mesa 없음** — Q6)

(Q4 판정 `docs/review/Q4_verdict.md` 반영.)  모델은 일반 r200 swtcl 이 **아니다** —
그 경로는 NDC/클립 좌표와 하드웨어 뷰포트, GART 정점 버퍼(`3D_LOAD_VBPNTR` +
`3D_DRAW_VBUF_2`)를 쓴다.  창 좌표 직접 선례는 FreeBSD **R200 깊이 지우기 사각형**
(`radeon_state.c:1124-1229`)이고, 이 경로가 Mesa 3.4.2 의 `VB->Win` 을 받는 기존 삼각형
훅 자리에 들어간다(Matrox WARP 층과 같은 자리).

1. **정점 계약**(구현 전에 R6 계획서에서 확정): `SE_VAP_CNTL` 에서 TCL·정점셰이더 끔,
   `SE_VTE_CNTL` 은 뷰포트 6 비트 끄고 `VTX_XY_FMT|VTX_Z_FMT`, `SE_VTX_FMT_0 =
   Z0|W0|PK_RGBA`, `SE_VTX_FMT_1 = 0`, W 는 1.0(선례 `0x3f800000`), 목적지 오프셋·
   피치·플레인 마스크·시저·`SE_CNTL` 을 매 제출 명시.  좌표: Mesa 3.4.2 창 좌표는
   아래가 원점·y 위(뒤집지 않음), `win.z` 는 깊이 코드 단위 → R200 규약으로 정규화
   (16 비트 `/0xffff`, 24 비트 `/0xffffff`), `win.w = 1/w`.  뷰포트를 끄면 R200 DRI 의
   `+0.125` 서브픽셀 이동도 사라지므로 **픽셀 위상은 분수 좌표 커버리지 시험으로 정한다**
   (Matrox 의 −0.5 는 장치별 — 옮기지 않음).  **텍스처 정점의 W·원근 규약은 실측으로 정해졌다(2026-09-20/21)**:
   가중치는 정점 W0 를 그대로 쓰고(`(Σλ·s·W0)/(Σλ·W0)`), `RE_CNTL.PERSPECTIVE_ENABLE` 이 꺼지면 W 는 무시되며,
   `SE_VTE_CNTL.VTX_W0_FMT` 를 켜면 하드웨어가 역수를 취한다.  **깊이는 원근 보정되지 않고 색은 된다.**
   ST 표본 위치는 픽셀 중심(+½)이다 — `docs/R6I_PLAN.md` 8, `docs/R6I2_PLAN.md` 8, `docs/R6I3_PLAN.md` 7.
   **블렌드도 실측으로 정해졌다(2026-09-21)**: 항마다 인자를 `F+1` 로 올려 곱하고 8 비트 버림,
   두 항을 더해 0..255 로 클램프한다(그래서 `ONE` 이 정확하다).  `SUB_CLAMP` 은 원본−목적지,
   `RB3D_CNTL.ROUND_ENABLE` 은 무효, 두 그리기 사이 대기는 필요 없다 — `docs/R6J_PLAN.md` 7.
   **시저도 끝났다(2026-09-21)**: 주 시저는 R6b, 보조 시저(`RE_AUX_SCISSOR_CNTL`+`RE_SCISSOR_TL/BR_0..2`)는 R6k —
   끝 포함·`EXCLUSIVE` 가 뒤집음·켜진 사각형 교집합·반 워드 **11 비트**·부호 없음·`RE_CNTL` 비트 1 과 무관,
   그리고 **주 시저가 허락한 영역을 넓히지 못한다**(검증기가 그 일곱 레지스터를 허용해도 안전) — `docs/R6K_PLAN.md` 11.
   **배치도 끝났다(2026-09-21, R6l)**: 한 `3D_DRAW_IMMD_2` 에 **정점 240(1250 워드)** 까지 실측으로 그려지고
   (헤더 count = 정점 워드 × 정점 수 — KMS 검사기가 거절 조건으로 쓰는 식, 이제 우리 소스 검사 규칙),
   한 제출의 **패킷 여러 개가 순서대로** 실행되며, 패킷 사이의 상태 변경은 그 뒤 패킷에만 걸린다.
   **클립을 옮길 때는 앞에 `WAIT_UNTIL(3D_IDLECLEAN|HOST_IDLECLEAN)` 을 넣는다**(DRM 의 잠금 선례).
   링 되감기는 "정확히 끝" 경로가 실기에서 돌았고, 패딩 경로는 산술만 덮여 있다 — `docs/R6L_PLAN.md` 9.
   **버퍼 재사용도 끝났다(2026-09-21, R6m)**: `RB3D_COLOROFFSET`·`RB3D_DEPTHOFFSET`·`PP_TXOFFSET` 을 창 안
   다른 자리로 옮겨도 그림은 그대로고 옛 표면은 한 워드도 안 변한다(`restChanged = 0`).  **색은 16 바이트,
   텍스처는 32 바이트 눈금이면 되고 4 KiB 정렬은 필요 없다**(일부러 `0x08010`·`0x14020` 에 두어 확인 —
   페이지로 반올림하는 구현이면 실패한다).  그리기는 텍스처 표면에 흘려 쓰지 않는다.  깊이 오프셋의
   최소 정렬은 참고 어디에도 없어 4 KiB 로 남겼다 — `docs/R6M_PLAN.md` 8.
   **CP 는 부팅당 한 주기**다: `cpLoad` 가 `CP_ST_NONE` 을 요구해 STOP 뒤에는 그 부팅에서 다시 못 올린다.
   **링 되감기 두 가지가 모두 실기에서 돌았다**: "끝에 정확히 맞음"은 R6l(`2800→0`), **패딩 가지**는
   R6m 둘째 부팅 `e5d55a94`(`2816→1264`, 1248 워드 패딩) — 작업 #30 완료.
   이로써 R6 5 의 여덟 칸이 전부 실측으로 닫혔다.
   **R6 3 항(커널 제출·검증기)의 절반도 끝났다(2026-09-21, R7a — `docs/R7_PLAN.md`)**: 유저 공간이
   CP 워드 스트림을 건네고 커널이 **전량 검증 뒤에만** 링에 복사한다.  실기에서 클라이언트가 조립한
   스트림이 T1 을 그렸고(통째로·세 조각 모두), **11 개 규칙이 각자 자기 스트림을 거절**했으며 거절
   때마다 표면은 그대로였다.  허용 목록 41 개는 **측정에서 유도**되고 C 표는 오라클이 생성한다.
   남은 것은 R7b(문자 디바이스 `ioctl` + 배치 mmap 창) — 가속 라이브러리는 순수 C 라 `IODeviceMaster`
   를 못 쓰므로 그 통로가 필요하다.  그다음이 M.
2. **패킷**: `3D_DRAW_IMMD_2`(정점 인라인, AOS·GART 정점 버퍼 불필요).
   `RNDR_GEN_INDX_PRIM` 은 R200 에서 거절된다.
3. **커널 제출·검증기**: 참고의 R200 검증은 상태 패킷 ID 허용 목록 + 주소 한 점 검사일 뿐
   (`radeon_state.c:228-256`, `radeon_drv.h:415-428`)이라 **그보다 강하게**: 입력 전체를
   스냅샷, 고정 최대 크기·32 비트 정렬·정확한 소비, 좁은 레지스터 **및 비트** 허용, 패킷 3 은
   `3D_DRAW_IMMD_2` 만, 길이·정점 형식·정점 수 교차 검사, 목적지·깊이·텍스처의
   **소유 할당 전체 범위** 검사, 배치 전체 검증 뒤에만 링 복사(부분 그리기 금지), 문맥별
   상태 추적 또는 매 제출 완전 상태.  유저는 링·GART 를 못 본다.
4. **텍스처 업로드**: 참고 ioctl 은 GART 버퍼 → `CNTL_BITBLT_MULTI` 로 버스 마스터를 쓴다
   (`radeon_state.c:1769-1866`).  첫 판 기본안은 **CPU 가 VRAM 매핑(R4c)에 직접 복사** —
   Matrox 가 증명한 구조, RV280 캐시 일관성은 S4a 식 시험으로 확인.
5. 순서: 평면색 → 구로 → 깊이(16 비트부터; 24 비트 공유 가능성은 미확인) → 텍스처 →
   블렌드 → 시저 → 배치 → 버퍼 재사용.  각 항목은 **소프트웨어 Mesa 오라클과 픽셀 전수 대조**.

이 단계는 **Mesa 를 연결하지 않는다**: 고정된 창 좌표 원시(삼각형·사각형)를 시험기가 직접
제출하고, 되읽기를 소프트웨어 오라클과 픽셀 전수 대조한다.  Mesa 훅·주전자는 M 이 맡는다
(훅·`osmesa.o`·공유 표면은 M 에서 만들어지므로 R6 에 주전자 게이트를 두면 순서 위반, Q6).

**Gate**: 기능 사다리 각 항목(평면색·구로·깊이·텍스처·블렌드·시저·배치·재사용)마다 제출
원시 수 > 0, 검증기 수락·거절 경로 각각 실행, 오라클 픽셀 전수 일치, 일부러 틀린 정점을 넣은
변이가 실패.

### M — Mesa 3.4.2 통합 (`libGL_radeon.a`)

1. **빌드**: stock `libGL.a` 복사 → `OPENSTEP_MESA_ACCEL_HOOK` 로 `osmesa.o` 재빌드 → 훅
   **10 개 전부** 구현, 빌드 시 10 개 모두 `nm` 감사(Matrox 감사는 4 개만 본다).
   `openstep-mesa342` 소스는 바꾸지 않는다.
2. **공존**: 설치 이름(라이브러리·헤더·문서 디렉터리·도구·패키지·공개 심볼)은 Radeon 고유,
   이름중립 훅 10 개의 이름은 **그대로**(바꾸면 `osmesa.c` 가 못 찾는다).  한 실행 파일에
   `libGL_mga.a` 와 `libGL_radeon.a` 를 함께 링크하는 것은 지원하지 않는다.
3. **M1 훅 구현 요건**(Matrox 선례): CPU 가 접근하는 공유 색 표면·정확한 픽셀 배치와 피치,
   바인드 시 앱 버퍼 import·출력 mirror, `OSMesaGetColorBuffer`·`glFinish`·폴백 동기화,
   공유 깊이와 떠날 때 깊이 복사(**`CopyDepth` 반환값은 호출자가 버린다** — 거절하면 깊이가
   초기화 안 된 채 남으므로 거절하지 않는다), present 모드와 SDL2 present 함수 셋
   (origin·mode·rect), clear 워드 그대로 사용·처리 못 한 마스크는 이전 clear 로 체인,
   **콜백 설치 전에** 상태 게이트(설치 뒤 거절은 삼각형을 잃는다), 소프트웨어 삼각형 보존,
   텍스처 할당·무효화·삭제, 색·깊이·텍스처 비겹침과 소유, 다중 문맥·재바인드, 앱이 현재
   버퍼에 직접 쓰는 경우의 규칙(감지 불가 — 재바인드가 경계).
4. M2: GL 확장 노출 — 광고를 늘리지 않는다(가속 여부는 폴백으로 투명).

**Gate (G1, Q6)**: (1) 훅 10 개 `nm` 감사, (2) **의미 시험**: 강제 하드웨어·강제 소프트웨어·섞인
프레임 각각의 이미지를 소프트웨어 Mesa 와 대조, `CopyDepth`·재바인드·문맥 둘·앱 버퍼 import/
mirror·present 경로가 실제로 실행된 계수, (3) 주전자 데모 — **판정 전에** 하드웨어/소프트웨어/
섞인 삼각형·거절 사유·업로드·mirror·present 계수가 기대대로 0 이 아님을 먼저 확인(폴백만으로도
주전자는 맞게 그려진다), (4) 성능은 같은 작업량의 SW/HW 두 팔, 원시 수 > 0, 업로드·그리기·
대기·mirror·present 시간을 따로(Matrox 3-28·3-32: fps 만으로는 잘려 나간 기하나 mirror 를 쟀다).
5. M3 (선택, G2): 하드웨어 TCL — Mesa 3.4.2 에 변환 앞단 훅이 없어 `openstep-mesa342` 에
   새 이름중립 훅이 필요하다.  별도 저장소 변경·독립 계획서·드리프트 점검.  G1 측정에서
   CPU 변환이 병목일 때만.

### P — 배포

`OSRDNDisplay.pkg`(드라이버), `OSRDNMesaAccel.pkg`(가속 라이브러리),
데모 오버레이.  Matrox `pkg/` 스크립트 재사용: 경로 100 자 규칙 검사, BOM
겹침 검사, 설치 시 config 보존, i386 마커.  README(영문)·LICENSE(BSD-2)·
NOTICE, subtree split, 이력 blob 전수 검사.

**Gate (Q6)**: 깨끗한 빌드의 해시 목록, 페이로드·리소스 목록(`Instance0.table`, `Display.modes`,
nib 등)이 원본과 일치, **시험용 주입 API·계수기 조작 심볼이 출하본에 없음**(심볼 감사), 설치·
업그레이드·제거·복구 절차를 실기에서, 설치된 패키지로 콜드 부팅 후 빌드 식별자 확인.

---

## 6. 운용

- 역할 (operator 결정, 2026-09-15): **계획·코딩은 Claude**, codex
  (`gpt-5.6-sol`) 는 **교차검토만**.  codex 회신은 검증 대상 입력이다.
- 실기 상태를 바꾸는 명령은 gcdsd 로(상시 허가), 재부팅은 operator.
- 오디오 시험 중이 아니어도, 측정 중 폴링은 최소화.

## 7. 위험과 중단 조건

| 위험 | 대응 |
|---|---|
| PCI 9250 이 비POST 상태(보조 카드) | 첫 판은 주 VGA 로 설치 전제, 아니면 R1 에서 중단·재계획 |
| PLL 락 실패·신호 불안정(G450 에서 겪음) | radeonfb 알고리즘 충실 포팅, 락 판정 되읽기, 1 모드로 먼저 |
| VGA 복귀 불완전 → 콘솔 먹통 | telnet 복구 경로(설정 되돌림) 를 R2 전에 실증 |
| CP·GART 오설정 → 시스템 메모리 훼손 | R5 를 4 조각으로, writeback 끄기, 창 검증 후에만 버스 마스터 |
| 64 KiB·conventional 메모리 한계 | 링·GART 테이블은 일반 wired 페이지(시스템 메모리 테이블이 기본안), `IOMallocLow` 는 쓰지 않는 것이 기본 |
| 공유 표면·제출의 다중 클라이언트 덮어쓰기(Matrox 3-35) | R4c 는 협조적 단일 클라이언트(문서) + 엔진 제출은 드라이버가 직렬화; 강제 할당·소유는 R6/M 설계로 연기(V 절 2026-09-18) |
| 폴링 완료에서 설명 안 되는 행(Matrox 3-62) | IRQ 를 미룬 대비책으로 재개 |
| Mesa 3.4.2 에 TCL 훅 없음 | G2 는 선택 목표, G1 만으로 완료 가능 |

**중단 조건** (Q6 로 강화 — Matrox 3-62 는 "두 번" 을 기다리다 여섯 번이 되었고 일곱 번째는
문서 모순이 만들었다):
1. 하드 행·PCI/MMIO 무응답·telnet/ICMP/NFS 상실·강제 전원 재시작이 **한 번**이라도 나면 실기
   작업을 멈추고 마지막으로 좋았던 빌드로 되돌린다.
2. runid·설치 해시·설정 스냅샷·진행 표지·nxlogd 출력으로 **오프라인 분류**하기 전에는 재시도 없음.
3. 재현은 진단 가치가 전원 재시작 한 번을 정당화할 때, **검토된 단일 변수 실험 1 회**까지.
4. 같은 행이 두 번째 나면 그 기능·설정 조합을 **격리**하고, 금지는 문서가 아니라 **실행기
   (runner)가 강제**한다.
5. 알려진 행 서명 주변의 매개변수 스윕 금지.
6. 새 실행 계획은 격리 목록과 **자동 대조**한다(한 절이 처방한 것을 다른 절이 금지한 사고 방지).
7. 확률적 행은 짧은 통과로 해제되지 않는다 — 승격에는 콜드 부팅 횟수·지속 부하 횟수를 미리 정한다.
8. 루트 fsck 가 필요한 크래시는 그 하위 시험이 아니라 **하드웨어 쓰기 마일스톤 전체**를 저장소
   무결성·복구가 확인될 때까지 멈춘다.

## 8. 첫 작업 묶음 — 진행 상황 (2026-09-15)

1. ✅ R0-1 사실표 `ANALYSIS.md` (인용 대조기·3 헤더 대조기 통과)
2. ✅ R0-2 모드셋 해독 `docs/R0_2_MODESET_DECODE.md` — Q5 반영(4 절은 R2 계획에서 확정)
3. ✅ R0-3 VGA 복귀 해독 `docs/R0_3_VGA_RETURN_DECODE.md` — Q5 반영
4. ✅ R0-4 라이선스표·`LICENSE`·`NOTICE`, R0-5 도구(`tools/host/` 복사됨)
5. ✅ R1 조사 계획 `docs/R1_INTERROGATION_PLAN.md` — Q5·Q6 반영, 구현 차이는 `[구현]` 표시
6. ✅ R1 코드(Claude): `probe/RDNR1Probe`, `tools/r1/` — 파서, 32 비트 시뮬레이터(바꾸지 않은
   probe 소스 + 가짜 PCI/MMIO), 묶기(스탬프·runid·BSD sum), 타깃 빌드·실행 스크립트와 그
   호스트 시험.  `tools/r1/hostcheck.sh` 9 단계 PASS.  시뮬레이터가 코드 결함 둘(생존 표본
   간격 22 ms, 브리지 표 넘침 뒤 매핑)을, 대조가 계획 이탈 하나(정적 VLINE 뒤 계속 읽기)와
   cc 2.7.2.1 함정 하나(변수 `id`)를 찾아 고쳤다.
7. ✅ codex 코드 교차검토 Q7 — 결론 "차단", 판정표 `docs/review/Q7_verdict.md`: probe 결함 3(버스 0 wrap, 64 비트 prefetch 상위 무시, 헤더 형 미확인)·config 경합 탐지·파서 독립 재계산·타깃 스크립트 5 건 고침, 2 건 문구/무조치(이유 기록).  hostcheck PASS.
8. ✅ codex 없이 한 호스트 사실 추출(2026-09-15, 전부 기계 검사 — **codex 가 돌아오면 검토 대상**):
   `docs/R5_CP_SEQUENCE.md`(CP 수명주기, 접근 165 개 분류), `docs/R5_GART.md`(창·표·배치 산술,
   컴파일한 C 와 차등 시험), `docs/R6_VERIFIER_FACTS.md`(참고 검증기 계산표),
   `docs/R6_CLEAR_QUAD.md`(깊이 지우기 사각형 워드열), `docs/R1_CLOSES.md`(R1 이 닫는 것),
   `tools/mesa/audit_hooks.py`(훅 10 개 계약).  전체 검사 `sh tools/check-all.sh`.
   계획에 반영할 새 사실: 엔진 리셋이 적재 **뒤**·PLL 공간 `MCLK_CNTL` 을 씀, GART 켤 때
   `MC_AGP_LOCATION`·`AGP_COMMAND` 도 씀, 참고 해제는 버스마스터를 다시 막지 않음, 창이 FB 와
   겹칠 수 있음(4 MiB 정렬), 참고 검증기의 주소 검사는 창 한 점·고쳐서 받음·id 끼리 레지스터 겹침
   26 쌍, `3D_DRAW_IMMD_2` 무검사, R6 정점 표기 `PK_RGBA` 는 bit 11 필드 값.  R1 확장 제안
   (MMIO 13 개)은 검토 대기.
9. ✅ **R1 실기 게이트 PASS(2026-09-15)** — `docs/R1_RESULT.md`.  실기가 드러낸 도구 결함 둘(tar mtime 0,
   커널 `sprintf` 가 `l` 변환 폭 무시)을 고치고 새 run id 로 재실행.  핵심: RV280 `03:0b.0` BAR2 `d0200000`,
   128 MiB, BIOS MC 맵은 FB 를 카드 주소 0 에(크기 정렬은 만족), 콘솔은 **VGA 코어 구동**(`EXT_DISP_EN` 0),
   `PLL_DIV_SEL`=3, `SURFACE_CNTL` 은 `SURF_TRANSLATION_DIS` 만, CP·GART 꺼짐·엔진 유휴, PCI 버스마스터 켜짐, `/dev/mem` 있음.
10. 🟡 R2 계획서 **개정 2** `docs/R2_FIRST_LIGHT_PLAN.md`(2026-09-15).
    - 개정 1: codex Q8 재검증(`docs/review/Q8_verdict.md`, 내 오류 8).
    - 개정 2: codex 불가로 **자체 agent 둘** 이 Q9 교차검토, 전건 재검증(`docs/review/Q9_verdict.md`, 내 오류 10).
      - 진입·복귀를 xf86 `legacy_crtc` 순서로(PLL 창 동안 `CRTC_EN` 0, 복귀는 CRTC→PLL→인덱스→100 ms→CRTC 켜기→VGA→DAC).
      - VGA 는 I/O 포트로, 블랭크 전에 읽음.
      - 8m 의 클럭 게이팅 쓰기 제거.
      - 플래그 분리(`modeWritten`), 대기 상한은 기록 후 계속.
      - R2a 는 1 바이트 인덱스 + 저장마다 재읽기 중단.
      - R1c 는 `dd skip` 대신 `lseek` 도구.
      - 0 단계 애퍼처 게이트, 시험 패턴, FB 계약에 `setMemoryRangeList`·`frameBuffer`.
    - operator D-3(옵트인 예외)·D-4(telnet 단일) 결정.
    - R1c·R2a **구현 계획 개정 1** `docs/R1C_R2A_IMPL_PLAN.md`(2026-09-15): Q10 자체 agent 검토 재검증(`docs/review/Q10_verdict.md`, 내 오류 14) — R2a PLL 을 `splhigh` 묶음 + DATA 뒤 재확인 + 묶음마다 직전 값 복원으로, 목적 파일 규칙 재정의(스택 저장 제외·`-O0 -fno-inline`), stab 제외, R1c `sync`·반환값·strace 동적 검사, PCIR device 는 기록만, R1 Python 은 import(셸만 복사+drift).  R2 계획 개정 3 에 맞춤.
    - **R1c 코드 완료(호스트)** `tools/r1c/`(2026-09-15): 사용자 도구 `rdnbios.c`, 타깃 스크립트, BIOS 파서(NetBSD·xf86 따로 추출+단위 교차), strace 동적 검사, 스크립트 시험 — `hostcheck-r1c` PASS, `check-all` PASS.
    - **R1c 실기 PASS(2026-09-15)** `docs/R1C_RESULT.md`: ATI 레거시 BIOS 53248 바이트(체크섬 0), refclk 27.00 MHz·refdiv 12·PLL 200–400 MHz·mclk 182.25·sclk 238.50 MHz, 1024×768 은 post 6·feedback 173(VCO 389.25 MHz).  타깃 셸 함정 셋(함수 뒤 위치 매개변수, 공백 기본값, 백그라운드 ps 행)·NFS 낡은 크기 읽기를 실기에서 찾아 도구에 반영.
    - **R2a 코드 완료(호스트)** `probe/RDNR2aProbe/`·`tools/r2a/`(2026-09-15): PLL 묶음 probe(헬퍼 분리 단위), 파서(R1 게이트 재사용·R1 비교), PLL 인덱스/데이터 모형 시뮬레이터(세계 44·변이 20), 소스·목적 파일 규칙(저장 출처 추적, 규칙 18·변이 24), 타깃 reloc 역어셈블 게이트, 타깃 스크립트(drift 25 hunk)·하니스 — `hostcheck-r2a` PASS, `check-all` PASS.  계획과 달라진 곳은 구현 계획 §2-10.
    - **R2a 실기 PASS(2026-09-15)** `docs/R2A_RESULT.md`: `CLOCK_CNTL_INDEX` 바이트 저장 20 번 무사고(중단·32 비트 되쓰기 0), 바이트 레인이 상위 비트 보존·DATA 읽기 부작용 없음 실측.  콘솔 PLL: `PLL_DIV_SEL` 3, `PPLL_DIV_3` `00030047`(fb 71·/8), `PPLL_REF_DIV` 6(BIOS 표 12 와 다름), 픽셀 클럭 39937.5 kHz = VESA 800×600@60.  `OV0_SCALE_CNTL` `807f0000`(스케일러 꺼짐), 카드 경로 브리지 VGA 전달 1, `IODelay(2000)` 실측 4.1 ms(R1 때 2.05 ms).  패키저의 PASS 문자열 결함 1 건(거절 쪽) 수정.
    - **R2 계획 개정 4** `docs/R2_FIRST_LIGHT_PLAN.md`(2026-09-15): R2a 실측 §1b(G1–G10) — 레지스터 refdiv 6 이 콘솔 `PPLL_DIV_3` 를 NetBSD 선택식으로 정확히 재현(12 는 불일치) → refdiv {6, 12} 분주 표(6: `0x00060057`, 65250 kHz, 60.2346 Hz), `PPLL_DIV_0` 은 refdiv 12 용 VGA 슬롯이라 `PLL_DIV_SEL` 3 외 금지, `OV0_SCALE_CNTL` 은 소프트 리셋 중이라 쓰지 않음, 복귀 PVG 는 스냅샷 값 4(D-6 제안, xf86 식은 7), 0 단계 브리지 VGA 전달 게이트, 시간은 `IOGetTimestamp`, 활성화 부팅 스냅샷이 R2a 와 다를 수 있어 1 단계 refdiv 는 표 선택.  인용 7 개 EXPECT 등록.
    - **Q11 교차검토(자체 agent 둘) 재검증 → R2 계획 개정 5**(2026-09-15, `docs/review/Q11_verdict.md`, 내 오류 7): 새 단계 **R2b-0**(활성화 부팅 첫 실행은 모드 레지스터 쓰기 없이 0–2 단계 기록·거절 + telnet 복구 실제 수행 — R1·R2a 값은 VGA 드라이버 부팅 값이고 Matrox 활성화 부팅은 순수 VGA 클럭 0 이었다), `PLL_DIV_SEL` 규칙은 "바꾸는 쓰기는 6c 뿐", G3 xf86 대조 정정(CRT 경로는 refdiv 탐색), D-6 스냅샷 PVG 유지(NetBSD 는 PVG 불변), `IOGetTimestamp` 규약(`t1<=t0`→0, 32 비트로 자른 뒤 나눔 — `___udivdi3` 커널에 없음), 호스트 규칙 구멍(0x08–0x0b, 클럭·인터럽트 레지스터, 9 단계 복원 전 경로).  인용 9 개 EXPECT 등록, `R2A_RESULT.md` 정정 줄.
    - **R2b-0 구현 계획 개정 0** `docs/R2B0_IMPL_PLAN.md`(2026-09-15, 검토 전): 금지 8(nxlogd 켠 부팅에서만) 때문에 하드웨어 기록을 부팅 경로에서 빼서 **부팅 뒤 사용자 도구가 파라미터 `RDNR2b0Record` 로 트리거**(Matrox WarpQual 선례), 부팅 경로는 PCI config 읽기·FB/MMIO 매핑만·`enterLinearMode` 무접근.  기록 = R2a 전체 + `PPLL_DIV_1·2` + VGA 표준(인덱스 포트만 쓰기, ATTR 0x10–0x14 는 PAS 세운 채) + `IOGetTimestamp` 로 `IODelay`/`IOSleep` 실측 + 0·1 단계 게이트 판정(R2b 공유 코드).  `[super revertToVGAMode]` 는 커널 method 목록상 빈 구현.  복구 = telnet + `config=Default`(네트워크 없음) 대비 로컬 복구 스크립트, 리허설 R-1·R-2.  operator 결정: 번들 이름, R-2 여부.
    - **Q12 교차검토(자체 agent 둘) 재검증 → R2b-0 계획 개정 1·R2 계획 개정 5.1**(2026-09-15, `docs/review/Q12_verdict.md`, 내 오류 17): VGA 레지스터 주체는 부트 로더가 아니라 **커널 VGA 콘솔**(`_VGASetGraphicsMode` 표 = Matrox 스냅샷, 파서 독립 기대값), get/setIntValues super 전달 규칙, 재진입 `splhigh` test-and-set(커널이 직렬화 안 함), pllabort 뒤 VGA 금지, 포트 이음새·`out` 역어셈블 게이트, 64 비트 나눗셈 변이는 목적 파일 규칙으로, 부팅 nonce·옵트인 키·1 s 시각 창, 복구 스크립트 고정 발행·권한 대조·`cmp`.  **설치된 EMU10K1 인스턴스 `Location` 이 Radeon 슬롯(Dev:11)을 가리킴** 발견.
    - **Q13 교차검토(자체 agent 둘) 재검증 → R2b-0 계획 개정 2·R2 계획 개정 5.2**(2026-09-15, `docs/review/Q13_verdict.md`, 내 오류 26): 활성화는 Configure.app·원복은 항상 `/me` **집합 복원**(pre 스냅샷 전 인스턴스 표, 활성화 부팅엔 GUI 없음), R-1 은 재부팅 없는 Configure 왕복, `check_cfgdiff` 키→값·파일 집합; 도구 `IOGetDisplayInfo` 는 **getInt count 5**(getChar 는 -711, 개정 1 대로면 매 실행 종료 4); 기록 사이 종결 걸쇠·임계 구간 내용·거절 코드 분리; 파서는 R1 대비 판정을 기록으로; 역어셈블 게이트는 심볼 범위별(선형 스윕은 PASS 한 R2a reloc 에서 거짓 `in`); 읽기 포트 허용 목록.  실측(읽기만): 현 부팅 `_basicConsoleMode` 1·VGA 콘솔(커널이 VGA 표를 씀), 타깃 `PCIBus_reloc` sum = 미러 `09451 40` — 빈 `Location` 은 PCIBus 가 ID 스캔으로 묶는다(역어셈블).  재부팅 4 회.
    - **operator 결정(2026-09-16)**: 옵트인 키는 권장안 (a) — R2b-0 기록 전용 빌드는 `Default.table` 도 `"RDN R2B0 Record" = "Yes"`(PLAN §4 기본 꺼짐 예외, D-3 확장; R2b 빌드는 "No").  금지 8 예외 승인됨, EMU10K1 `Location` 조치 완료, `OSRDNDisplay` `Location` = `""`.
    - **R2b-0 코드 완료(호스트, 2026-09-16)** `OSRDNDisplay/`(ObjC 클래스 + 순수 C `.m` 단위: `osrdn_record`·`osrdn_pll`(R2a 원본, 드리프트 6 hunk)·`osrdn_port`·`RDNR2aMMIO` 복사, 생성 `osrdn_expect.h`), `tools/r2b0/`(`rdnr2b0.m`, 파서·시뮬레이터·소스 규칙·역어셈블 게이트·스냅샷 판정·복원 묶음·타깃 스크립트 7 개·하니스), `sh tools/r2b0/hostcheck.sh` 11 단계 PASS, `check-all` PASS.  코드 중 확정·정정은 `docs/R2B0_IMPL_PLAN.md` §12(판정 32 항목 명시, R1 사람 값 출처, `out`/`id` 식별자, `/me` 실측, NFS 표지).  **다음: 실기 — pack → 타깃 build → 호스트 reloc 게이트 → install → R-1(재부팅 없음) → R-2 → 활성화.**
(이전 항목) **여기서 실기가 필요하다**: operator 가 G450 → Radeon 교체·generic VGA 부팅 →
   `pack_probe.py` → 타깃 `target-build.sh`(첫 `nm -u`) → `target-run.sh` → 호스트
   `parse_r1.py`.

## 9. operator 결정이 필요한 것

1. **이름**: 번들 `OSRDNDisplay` — **결정됨(2026-09-15, operator)**.  가속 `OSRDNMesaAccel`, 심볼 접두 `osrdn`(제안 유지).
   근거는 `installer_tar` 100 자 — 가장 긴 페이로드 경로가 번들 이름 +81 자
   (Matrox C3 실측)라 `OSRadeonDisplay`(15) 는 96 자로 여유 4,
   `OSRDNDisplay`(12) 는 93 자로 Matrox 와 같은 여유 7.
2. ~~설치 형태~~ — **결정됨(2026-09-15): G450 대신 Radeon 단독.**
3. **링 위치**(R5b) — R5 계획서에서 선택지 비교 후 결정.
4. ~~역할 분담~~ — **결정됨(2026-09-15): 코딩은 Claude, codex 는 교차검토만.**
5. 노트 문서를 이 폴더의 `docs/` 로 복사할지(공개 시 자립성).
6. ~~R2b 옵트인(D-3)~~ — **결정됨(2026-09-15): 예외 승인, §4 에 반영.**  "디스플레이 소유자 교체는
   `Active Drivers` 편집이 옵트인".  근거: 기본 꺼짐 키는 VGA 가 빠진 부팅에 화면 소유자를 없앤다
   (`docs/R2_FIRST_LIGHT_PLAN.md` §6).
7. ~~R2b 복구 채널(D-4)~~ — **결정됨(2026-09-15): telnet(Pro1000) 단일 채널 수용**(Matrox 와 같음).  R2b 전 리허설 1 회는 유지.
