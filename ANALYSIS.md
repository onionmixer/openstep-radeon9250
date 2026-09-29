# RV280 하드웨어 사실표 (R0-1)

작성 2026-09-15.  **실기로 확인한 것은 아직 없다** — 모든 항목은 참고 소스에서
읽은 사실이고, 출처는 `파일:줄` 로 적는다.  `tools/oracle/check_citations.py` 가
이 문서의 인용 전부를 원문과 대조한다(대조표에 없는 인용은 실패로 친다).

약어 — `radeonfb.c`, `radeonfbreg.h`: NetBSD `ref/upstream/netbsd/sys/dev/pci/`.
`radeon_cp.c`, `radeon_drv.h`, `ati_pcigart.c`, `drm_pciids.h`, `radeon_microcode.h`:
FreeBSD stable/9 `ref/upstream/freebsd-stable9/sys/dev/drm/`.
`radeon_driver.c`, `radeon_reg.h`, `legacy_crtc.c`, `legacy_output.c`, `radeon_bios.c`:
xf86-video-ati 6.14.6 `ref/upstream/unpacked/xf86-video-ati-6.14.6/src/`.

**주 참고**: 디스플레이·2D 는 NetBSD radeonfb, CP·GART 는 FreeBSD 레거시 DRM.
xf86-video-ati 는 교차확인과 VGA 복귀(radeonfb 에 없음)에 쓴다.

---

## 1. 식별

- RV280 PCI ID 두 목록이 다르다.  FreeBSD `drm_pciids.h:113-117` 는
  5960 5961 5962 5964 5965, `:128-129` 는 5c61 5c63(모바일).  NetBSD
  `radeonfb.c:311-317` 은 5960 5961 5962 **5963** 5964 5c61 5c63.
  **합집합 8 개**를 매칭 후보로 쓴다.  실제 카드 ID 는 R1 에서 읽는다.
- 이 칩은 "레거시" 계열이다 — AVIVO/ATOM 경로의 레지스터를 가져오면 안 된다
  (`radeon_driver.c:4031-4035` 는 AVIVO 분기 안에서만 VGA 코어를 끈다).

## 2. VRAM 크기 — 세 값을 따로 읽는다

| 값 | 레지스터/출처 | 누가 무엇으로 쓰나 |
|---|---|---|
| 보고 탑재량 | `CONFIG_MEMSIZE` | xf86 이 전체 VRAM 으로(`radeon_driver.c:1755-1757`). 0 이면 8 MiB 로 간주(`:1441-1446`), 애퍼처가 더 크면 애퍼처로(`:1447-1451`) |
| CPU 애퍼처 | `CONFIG_APER_SIZE` | radeonfb 가 `sc_memsz` 로(`radeonfb.c:2872-2880`), 64 MiB 로 자름(`:658-662`). xf86 은 RV280 이면 **×2**(2 세대 PCI 인터페이스, `radeon_driver.c:1694-1704`) |
| BAR0 크기 | PCI config | xf86 이 접근 가능량을 다시 자름(`radeon_driver.c:1761-1775`) |

주의(충돌): xf86 은 ×2 를 위해 `HOST_PATH_CNTL.HDP_APER_CNTL` 을 **쓰고**
(`radeon_driver.c:1694-1704`), radeonfb 는 `HOST_PATH_CNTL` 을 **0 으로 쓴다**
(`radeonfb.c:2889`).  → R1 에서 BIOS 가 둔 값을 읽고 R2 계획에서 결정한다.

## 3. 메모리 컨트롤러 맵

- radeonfb: `mcfbloc = (aperbase >> 16) | ((aperbase + apersize - 1) & 0xffff0000)`,
  AGP 위치는 FB 바로 뒤, `DISPLAY_BASE_ADDR` = 애퍼처 기준(`radeonfb.c:2860-2903`).
  바꾸기 전 `CRTC_GEN_CNTL.DISP_REQ_EN_B`·`CRTC_EXT_CNTL.DISPLAY_DIS` 를 세우고
  100 ms, 바꾼 뒤 100 ms(`radeonfb.c:2852-2869`, `:2903-2909`).
- xf86: **값이 바뀔 때만** 다시 쓴다(`radeon_driver.c:4076-4081`).  바꿀 때는
  엔진 유휴 → 오버레이 끔 → 표시·메모리 요청 차단 → 100 ms → MC 유휴 대기 →
  **AGP 위치를 먼저 치워** 일시 겹침 방지(`radeon_driver.c:4089-4150`).
- **RV280 은 FB 위치를 크기에 정렬**해야 한다: `aper0_base &= ~(mem_size - 1)`
  (`radeon_driver.c:1498-1513`, "Affected chips are rv280").
- xf86 의 MC 유휴 대기는 타임아웃을 로그한 뒤에도 **루프를 빠져나오지 않는다**
  (`radeon_driver.c:4127-4145`).
- radeonfb 의 첫 디스플레이는 VRAM 오프셋 0(`rd_offset = sc_fboffset * i`,
  `radeonfb.c:922`), 설정 CRTC 오프셋 0(`radeonfb.c:2582`).

## 4. PLL 공간 접근

- 인덱스 `CLOCK_CNTL_INDEX`(MMIO 0x08) 의 하위 6 비트가 PLL 레지스터 번호,
  `PLL_WR_EN` bit 7, `PLL_DIV_SEL` bits 8-9(`radeonfbreg.h:329-332`).
  읽기도 **인덱스 쓰기**를 포함한다(`radeonfb.c:1565-1578`).  radeonfb 는 읽기 뒤
  인덱스를 되돌리지 않고, 쓰기 뒤에는 0 으로 둔다(`radeonfb.c:1588-1599`).
- **주의: MMIO 0x08 과 PLL 0x08(`VCLK_ECP_CNTL`) 은 다른 레지스터다.**  공간은
  헤더 주석이 아니라 참고 소스의 접근자로 판별했다(`regtable.py`): 예를 들어
  `PIXCLKS_CNTL`(0x2d) 은 헤더 주석에 PLL 표시가 없지만 PLL 접근자로만 쓰이고
  (`radeonfb.c:2276`), `TMDS_PLL_CNTL`(0x2a8) 은 이름과 달리 MMIO 다
  (`radeonfb.c:621`).
- xf86 의 PLL 에라타 셋은 R300 / RV200·RS200 / RV100·RS100·RS200 전용이고
  **RV280 은 해당 없음**(`radeon_driver.c:1976-1992`).

## 5. 픽셀 PLL

- 기준값: 레거시 BIOS 블록 `p = BIOS16(0x48); p = BIOS16(p+0x30)`, refclk `+0x0e`,
  refdiv `+0x10`, minpll `+0x12`, maxpll `+0x16`.  **비-R300(RV280) 의 refdiv 는
  `PPLL_REF_DIV` 레지스터 값이 먼저**, BIOS 는 폴백(`radeonfb.c:1697-1714`).
  BIOS 없음 기본값 27.00 MHz / 12 / 125–400 MHz(`radeonfb.c:1671-1687`),
  저장 시 ×10(`:1730-1734`).
- 후분주 표(분주→코드): 16→5, 12→7, 8→3, 6→6, 4→2, 3→4, 2→1, 1→0.  radeonfb
  (`radeonfb.c:397-407`) 와 xf86 `post_divs` 가 같은 대응이다(`radeon_modeset.py`
  자체검사가 확인).  radeonfb 는 이 순서로 VCO 가 범위 안에 드는 첫 분주를 고르고
  피드백 = `DIVIDE(refdiv × vco, refclk)`(`radeonfb.c:1736-1776`).
- 전이 순서(radeonfb, `radeonfb.c:2101-2270`): 이미 같은 값이면 PLL 을 안 건드림 →
  `VCLK_ECP_CNTL` CPU 클럭 선택 → `PPLL_CNTL` 리셋·원자 갱신 켬 → `PLL_DIV_SEL`
  0 → `PPLL_REF_DIV` → `PPLL_DIV_0` 두 번 → 갱신 요청 → 대기 → `HTOTAL_CNTL`=0 →
  리셋 해제 → **50 ms** → PPLL 클럭 선택 → 픽셀 클럭 게이트 해제.
- **원자 갱신 비트 R 과 W 는 같은 비트 15**(`radeonfbreg.h:1529-1530`).  xf86 은
  요청 뒤 그 비트가 **내려갈 때까지** 상한 10000 회 대기(`legacy_crtc.c:214-226`),
  요청 전 대기는 상한 없는 `while`(`legacy_crtc.c:230-238`).  radeonfb 의 요청 전
  대기도 상한 없음(`radeonfb.c:2128-2139`), 요청 뒤 대기는 비트가 **설 때까지**라
  (`radeonfb.c:2150-2166`) 방금 세운 비트를 보고 곧장 빠진다.
- 분주 슬롯이 다르다: radeonfb 는 `PPLL_DIV_0`(`radeonfb.c:2237-2238`), xf86 은
  `PPLL_DIV_3` 에 쓰고 `PLL_DIV_SEL`=3(`legacy_crtc.c:348-380`).
- 65 MHz 에서 기본 클럭(27 MHz/12)이면 분주 6·피드백 173 → `PPLL_DIV` 워드
  `0x000600ad`, 실제 64.875 MHz(−1923 ppm, 59.888 Hz).  xf86 의 iBook 하드코딩 값과
  같다(`legacy_crtc.c:1264`).  모든 모드 값은 `python3 tools/oracle/radeon_modeset.py`.

## 6. CRTC

- 타이밍 워드 공식은 radeonfb(`radeonfb.c:2528-2576`) 와 xf86
  (`legacy_crtc.c:928-953`) 이 표의 다섯 모드에서 같은 값을 낸다(오라클 자체검사).
- `CRTC_GEN_CNTL`: 픽셀 폭 필드 shift 8(`radeonfbreg.h:439`), `EXT_DISP_EN` bit 24,
  `CRTC_EN` bit 25(`:446-447`).  radeonfb 형식 코드 8bpp=2, 32bpp=6
  (`radeonfb.c:929-935`); xf86 은 15bpp=3, 16bpp=4 도 둔다(`legacy_crtc.c:888-895`).
- `CRTC_EXT_CNTL`: radeonfb 는 `XCRT_CNT_EN | VGA_ATI_LINEAR | CRT_ON` 을 세우고
  sync 비활성 비트를 보존하지 않는다(`radeonfb.c:2493-2510`).  표시 끔
  (`DISPLAY_DIS`) 과 메모리 요청 차단(`CRTC_GEN_CNTL.DISP_REQ_EN_B`) 은 다른 제어다.
- 되읽기 함정: RV280 `TMDS_PLL_CNTL` bit 22 는 반전되어 읽힌다(`radeonfb.c:2617-2623`).

## 7. DAC·팔레트

- radeonfb 는 `DAC_CNTL` 에 `DAC_MASK_ALL | DAC_8BIT_EN` 을 세운다(`radeonfb.c:761-764`).
  xf86 은 여기에 `DAC_VGA_ADR_EN` 을 더하고, RV280 주 DAC 경로를
  `DAC_CNTL2.DAC_CLK_SEL` 로 고른다(`legacy_output.c:1483-1504`).
- 팔레트 쓰기 프로토콜: `VCLK_ECP_CNTL` 의 `PIXCLK_DAC_ALWAYS_ONb` 를 잠시 내리고,
  `DAC_CNTL2.DAC2_PALETTE_ACC_CTL` 로 CRTC 를 고른 뒤 `PALETTE_INDEX` →
  `PALETTE_30_DATA = r<<22 | g<<12 | b<<2`, 끝나면 VCLK 복원(`radeonfb.c:2953-2995`).

## 8. 2D 엔진 (CP 없이 MMIO)

- 초기화: `RB3D_CNTL`=0 → 엔진 리셋 → `SURFACE_CNTL`=`SURF_TRANSLATION_DIS` →
  피치·오프셋 → `DP_GUI_MASTER_CNTL` → 브러시·클립 기본값 → 유휴
  (`radeonfb.c:3771-3860`).  피치 레지스터에 애퍼처 상위 비트를 섞는 것은 원저자도
  "우연히 동작한다고 의심" 한다(`radeonfb.c:3858-3870`).
- 채우기: `DP_GUI_MASTER_CNTL`, `DP_BRUSH_FRGD_CLR`, `DP_WRITE_MASK`, `DP_CNTL`,
  `DST_Y_X`, `DST_WIDTH_HEIGHT`(마지막 쓰기가 실행) (`radeonfb.c:3688-3711`).
  블릿: 겹침 방향으로 시작점을 옮기고 `SRC_Y_X` 추가(`radeonfb.c:3721-3759`).
- **대기 셋 모두 그대로 쓸 수 없다**: `radeonfb_wait_fifo` 는 상한이 있으나 실패해도
  조용히 반환(디버그 빌드만 출력, `radeonfb.c:3775-3789`), `radeonfb_engine_idle`
  (`:3763-3770`) 과 `radeonfb_engine_flush`(`:3784-3805`) 는 상한 없는 `while`.
- 엔진 리셋: `RBBM_SOFT_RESET` 에 CP·SE·RE·PP·E2·RB 를 세우고 **곧바로 같은 레지스터를
  읽은 뒤** 내리고 다시 읽는다 — 대기 없음.  HDP 는 `HOST_PATH_CNTL.HDP_SOFT_RESET`
  으로 따로(`radeonfb.c:3904-3967`).  FreeBSD 도 같은 모양(`radeon_cp.c:631-650`).

## 9. Command Processor

- R200 계열(RV280 포함) 마이크로코드 배열 `R200_cp_microcode`
  (`radeon_microcode.h:292`), 선택은 `radeon_cp.c:481-486`.  적재는 유휴 대기 뒤
  `CP_ME_RAM_ADDR`=0, 256 번 `DATAH`=`cp[i][1]`·`DATAL`=`cp[i][0]`(`radeon_cp.c:523-530`).
  `linux-firmware/radeon/R200_cp.bin`(2048 바이트, 라이선스 MIT `WHENCE:1834-1838`)은
  그 쓰기 순서의 빅엔디안 워드열로 **헤더와 같은 데이터**다 — `tools/oracle/check_microcode.py`
  가 확인(순서를 뒤집은 대조는 불일치해야 통과).
- **어느 참고 구현도 CP 마이크로코드를 되읽지 않는다**: `CP_ME_RAM_RADDR` 의 정의
  외 사용이 7 트리 전체에서 0 건(Radeon 계열; 잡힌 2 건은 무관한 Adreno XML).
  PLAN R5a 의 "되읽기 대조" 는 선례 없는 조작이다.
- 명령 큐 모드: `CSQ_PRIPIO_*` 는 7 트리 25 건 전부 `#define`, FreeBSD 는 PRIBM
  두 모드 외 cp_mode 를 거절한다(`radeon_cp.c:1165-1173`).
- 링 상태는 `CP_CSQ_CNTL` 하나로 표현되지 않는다: `CP_RB_BASE`, `CP_RB_CNTL`,
  `CP_RB_RPTR/WPTR`, `CP_RB_RPTR_ADDR`, 스크래치 writeback 주소·마스크, 버스 마스터
  (`radeon_cp.c:726-779`).
- radeonfb 는 `BUS_CNTL` 에 `BUS_MASTER_DIS` 를 쓴다(`radeonfb.c:2916-2927`).
- 초기화 순서(FreeBSD): GART 켬 → 마이크로코드 적재 → 링 초기화 → 엔진 리셋 →
  writeback 시험(`radeon_cp.c:1477-1487`).  적재기는 유휴 대기의 반환값을 무시한다
  (`radeon_cp.c:470-532`).  링 초기화는 `SCRATCH_UMSK`=7 로 writeback 을 켠 **뒤**
  버스 마스터를 켠다(`radeon_cp.c:752-777`).
- writeback 을 끄려면 **둘 다**: `CP_RB_CNTL |= RB_NO_UPDATE`(bit 27), `SCRATCH_UMSK`=0
  (`radeon_cp.c:840-844`, `radeon_drv.h:1116-1119`).  `CP_RB_RPTR_ADDR` 는 남는다.
- 대기의 함정: `radeon_wait_ring` 은 head 가 움직이면 기한을 되돌리고(`radeon_cp.c:1901-1925`),
  `BEGIN_RING` 은 그 결과를 무시한다(`radeon_drv.h:2054-2067`).  lastclose 는 유휴를
  무한 재시도한다(`radeon_cp.c:1693-1704`).

## 10. PCI GART

- 레거시(비-PCIE) 경로는 `AIC_CNTL`/`AIC_PT_BASE`/`AIC_LO_ADDR`/`AIC_HI_ADDR`
  (`radeon_cp.c:1036-1060`).
- 테이블 32 KiB(`radeon_drv.h:1823`) = 8192 항목 × 4 KiB(`ati_pcigart.c:39`) =
  용량 32 MiB.  실제 창은 `init->gart_size`(`radeon_cp.c:1329`), xf86 의 R300 이전
  기본값 8 MB(`radeon_dri.h:42`).
- PCI PTE 는 `le32(bus & 0xfffff000)`, 플래그 없음(`ati_pcigart.c:168-214`).  **FreeBSD 의
  테이블 크기 계산은 `PAGE_SIZE > 4096` 에서 넘친다** — 항목 수 상한을 페이지 수에 쓰고
  페이지마다 `PAGE_SIZE/4096` 항목을 쓴다(`ati_pcigart.c:162-194`).  8 KiB 페이지면 32 KiB
  테이블(8192 항목)에 최대 16384 항목을 쓴다(Python 계산).  Linux 는 `max_real_pages` 로
  고쳤다(Linux 3.10 `drivers/gpu/drm/ati_pcigart.c` 139–143 행 — 대조기가 파일명을 FreeBSD 로 해석하므로 형식을 풀어 적음, 2026-09-15 열어 확인).
- PCI GART 창: FB 끝 바로 뒤(넘치면 앞), 4 MiB 내림 정렬(`radeon_cp.c:1346-1361`).
- 테이블을 VRAM 에 두는 `DRM_ATI_GART_FB` 는 유저가 위치를 준 경우에만
  (`radeon_cp.c:1398-1443`), xf86 은 PCIE 에서만 준다(`radeon_driver.c:3763-3769`).
  **재래식 PCI + VRAM 테이블은 참고 구현이 쓴 적 없는 조합.**

## 11. 참고 구현이 읽지 않는 것 (조사 설계 주의)

- `CRTC_VLINE_CRNT_VLINE` 의 정의 외 사용 0 건.  11 비트라 되감긴다
  (`radeonfbreg.h:573-575`).  `CRTC_CRNT_FRAME` 은 FreeBSD 가 읽는다
  (`radeon_irq.c:305-315`).

---

## 12. 레지스터 오프셋 대조표 (생성)

`python3 tools/oracle/regtable.py --markdown` 의 출력이다.  세 헤더에서 뽑아 서로
대조했고, **SINGLE-SOURCE 는 한 헤더만 정의해 교차확인이 안 된 것**이다.  공간(MMIO /
PLL idx) 은 참고 소스의 접근자로 판별했고, `?` 는 어느 참고도 접근하지 않아
판별 근거가 헤더뿐인 것이다.  `python3 tools/oracle/sync_analysis.py --check` 로
이 표가 생성기와 같은지 확인한다.

<!-- BEGIN regtable.py --markdown (generated; do not edit) -->
| 군 | 레지스터 | 오프셋 | 공간 | 주 | NetBSD radeonfbreg.h | xf86 radeon_reg.h | FreeBSD radeon_drv.h | 대조 |
|---|---|---|---|---|---|---|---|---|
| config | `CONFIG_MEMSIZE` | `0x00f8` | MMIO | N | :386=0xf8 | :344=0xf8 | :611=0xf8 | OK |
| config | `CONFIG_APER_SIZE` | `0x0108` | MMIO | N | :379=0x108 | :337=0x108 | :610=0x108 | OK |
| config | `CONFIG_APER_0_BASE` | `0x0100` | MMIO | N | :377=0x100 | :335=0x100 | — | OK |
| config | `HOST_PATH_CNTL` | `0x0130` | MMIO | N | :1045=0x130 | :992=0x130 | :858=0x130 | OK |
| config | `BUS_CNTL` | `0x0030` | MMIO | N | :275=0x30 | :244=0x30 | :587=0x30 | OK |
| config | `SURFACE_CNTL` | `0x0b00` | MMIO | N | :1669=0xb00 | :1591=0xb00 | :1054=0xb00 | OK |
| mc | `MC_FB_LOCATION` | `0x0148` | MMIO | N | :1117=0x148 | :1058=0x148 | :878=0x148 | OK |
| mc | `MC_AGP_LOCATION` | `0x014c` | MMIO | N | :1116=0x14c | :1057=0x14c | :877=0x14c | OK |
| mc | `MC_STATUS` | `0x0150` | MMIO | N | :1173=0x150 | :1113=0x150 | — | OK |
| mc | `DISPLAY_BASE_ADDR` | `0x023c` | MMIO | N | :1118=0x23c | :1059=0x23c | — | OK |
| mc | `DISPLAY2_BASE_ADDR` | `0x033c` | MMIO | N | :1119=0x33c | :1060=0x33c | — | OK |
| mc | `OV0_BASE_ADDR` | `0x043c` | MMIO | N | :1120=0x43c | :1061=0x43c | — | OK |
| crtc | `CRTC_GEN_CNTL` | `0x0050` | MMIO | N | :435=0x50 | :391=0x50 | — | OK |
| crtc | `CRTC_EXT_CNTL` | `0x0054` | MMIO | N | :420=0x54 | :378=0x54 | — | OK |
| crtc | `CRTC2_GEN_CNTL` | `0x03f8` | MMIO | N | :449=0x3f8 | :401=0x3f8 | — | OK |
| crtc | `CRTC_H_TOTAL_DISP` | `0x0200` | MMIO | N | :491=0x200 | :443=0x200 | — | OK |
| crtc | `CRTC_H_SYNC_STRT_WID` | `0x0204` | MMIO | N | :477=0x204 | :429=0x204 | — | OK |
| crtc | `CRTC_V_TOTAL_DISP` | `0x0208` | MMIO | N | :563=0x208 | :515=0x208 | — | OK |
| crtc | `CRTC_V_SYNC_STRT_WID` | `0x020c` | MMIO | N | :551=0x20c | :503=0x20c | — | OK |
| crtc | `CRTC_VLINE_CRNT_VLINE` | `0x0210` | MMIO? | N | :573=0x210 | :525=0x210 | — | OK |
| crtc | `CRTC_CRNT_FRAME` | `0x0214` | MMIO | N | :419=0x214 | :377=0x214 | :1360=0x214 | OK |
| crtc | `CRTC_OFFSET` | `0x0224` | MMIO | N | :503=0x224 | :455=0x224 | :612=0x224 | OK |
| crtc | `CRTC_OFFSET_CNTL` | `0x0228` | MMIO | N | :510=0x228 | :462=0x228 | :613=0x228 | OK |
| crtc | `CRTC_PITCH` | `0x022c` | MMIO | N | :540=0x22c | :492=0x22c | — | OK |
| crtc | `DISP_MERGE_CNTL` | `0x0d60` | MMIO | N | :700=0xd60 | :651=0xd60 | — | OK |
| crtc | `CRTC_MORE_CNTL` | `0x027c` | MMIO | N | :467=0x27c | :419=0x27c | — | OK |
| crtc | `GRPH_BUFFER_CNTL` | `0x02f0` | MMIO | N | :397=0x2f0 | :355=0x2f0 | — | OK |
| config | `MEM_SDRAM_MODE_REG` | `0x0158` | MMIO | N | :1162=0x158 | :1102=0x158 | :757=0x158 | OK |
| pll | `CLOCK_CNTL_INDEX` | `0x0008` | MMIO | N | :330=0x8 | :289=0x8 | :609=0x8 | OK |
| pll | `CLOCK_CNTL_DATA` | `0x000c` | MMIO | N | :329=0xc | :288=0xc | :607=0xc | OK |
| pll | `PPLL_CNTL` | `0x0002` | PLL idx | N | :1511=0x2 | :1451=0x2 | — | OK |
| pll | `PPLL_REF_DIV` | `0x0003` | PLL idx | N | :1527=0x3 | :1465=0x3 | — | OK |
| pll | `PPLL_DIV_0` | `0x0004` | PLL idx | N | :1521=0x4 | :1459=0x4 | — | OK |
| pll | `PPLL_DIV_3` | `0x0007` | PLL idx | N | :1524=0x7 | :1462=0x7 | — | OK |
| pll | `VCLK_ECP_CNTL` | `0x0008` | PLL idx | N | :1734=0x8 | :1655=0x8 | — | OK |
| pll | `HTOTAL_CNTL` | `0x0009` | PLL idx | N | :1048=0x9 | :995=0x9 | — | OK |
| pll | `MCLK_CNTL` | `0x0012` | PLL idx | N | :1127=0x12 | :1068=0x12 | :879=0x12 | OK |
| pll | `PIXCLKS_CNTL` | `0x002d` | PLL idx (주석과 다름) | N | :1480=0x2d | :1420=0x2d | — | OK |
| dac | `DAC_CNTL` | `0x0058` | MMIO | N | :594=0x58 | :546=0x58 | — | OK |
| dac | `DAC_CNTL2` | `0x007c` | MMIO | N | :606=0x7c | :558=0x7c | — | OK |
| dac | `DAC_MACRO_CNTL` | `0x0d04` | MMIO | N | :628=0xd04 | :580=0xd04 | — | OK |
| dac | `TV_DAC_CNTL` | `0x088c` | MMIO | N | :632=0x88c | :584=0x88c | — | OK |
| dac | `DISP_OUTPUT_CNTL` | `0x0d64` | MMIO | N | :661=0xd64 | :613=0xd64 | — | OK |
| dac | `DISP_HW_DEBUG` | `0x0d14` | MMIO | N | :659=0xd14 | :611=0xd14 | — | OK |
| dac | `PALETTE_INDEX` | `0x00b0` | MMIO | N | :1478=0xb0 | :1418=0xb0 | — | OK |
| dac | `PALETTE_30_DATA` | `0x00b8` | MMIO | N | :1477=0xb8 | :1417=0xb8 | — | OK |
| fp | `FP_GEN_CNTL` | `0x0284` | MMIO | N | :888=0x284 | :839=0x284 | — | OK |
| fp | `FP2_GEN_CNTL` | `0x0288` | MMIO | N | :913=0x288 | :863=0x288 | — | OK |
| fp | `TMDS_PLL_CNTL` | `0x02a8` | MMIO | N | :1724=0x2a8 | :1645=0x2a8 | — | OK |
| fp | `TMDS_TRANSMITTER_CNTL` | `0x02a4` | MMIO | N | :1725=0x2a4 | :1646=0x2a4 | — | OK |
| misc | `OVR_CLR` | `0x0230` | MMIO | N | :1355=0x230 | :1295=0x230 | — | OK |
| misc | `OVR_WID_LEFT_RIGHT` | `0x0234` | MMIO | N | :1356=0x234 | :1296=0x234 | — | OK |
| misc | `OVR_WID_TOP_BOTTOM` | `0x0238` | MMIO | N | :1357=0x238 | :1297=0x238 | — | OK |
| misc | `OV0_SCALE_CNTL` | `0x0420` | MMIO | N | :1297=0x420 | :1237=0x420 | — | OK |
| misc | `SUBPIC_CNTL` | `0x0540` | MMIO | N | :1667=0x540 | :1589=0x540 | — | OK |
| misc | `VIPH_CONTROL` | `0x0c40` | MMIO | N | :1767=0xc40 | :1688=0xc40 | — | OK |
| misc | `I2C_CNTL_1` | `0x0094` | MMIO | N | :1065=0x94 | :1012=0x94 | — | OK |
| misc | `GEN_INT_CNTL` | `0x0040` | MMIO | N | :996=0x40 | :945=0x40 | :841=0x40 | OK |
| misc | `GEN_INT_STATUS` | `0x0044` | MMIO | N | :997=0x44 | :946=0x44 | :847=0x44 | OK |
| misc | `CAP0_TRIG_CNTL` | `0x0950` | MMIO | N | :1374=0x950 | :1314=0x950 | — | OK |
| misc | `CAP1_TRIG_CNTL` | `0x09c0` | MMIO | N | :1439=0x9c0 | :1379=0x9c0 | — | OK |
| misc | `BIOS_0_SCRATCH` | `0x0010` | MMIO | N | :141=0x10 | :110=0x10 | — | OK |
| misc | `BIOS_4_SCRATCH` | `0x0020` | MMIO | N | :154=0x20 | :123=0x20 | — | OK |
| engine | `RBBM_STATUS` | `0x0e40` | MMIO | N | :1547=0xe40 | :1485=0xe40 | :981=0xe40 | OK |
| engine | `RBBM_SOFT_RESET` | `0x00f0` | MMIO | N | :1538=0xf0 | :1476=0xf0 | :953=0xf0 | OK |
| engine | `RBBM_CNTL` | `0x0e44` | MMIO | N | :1550=0xe44 | — | — | SINGLE-SOURCE |
| engine | `RB3D_CNTL` | `0x1c3c` | MMIO | N | :2199=0x1c3c | :2120=0x1c3c | :906=0x1c3c | OK |
| engine | `DP_GUI_MASTER_CNTL` | `0x146c` | MMIO | N | :732=0x146c | :683=0x146c | :788=0x146c | OK |
| engine | `DP_DATATYPE` | `0x16c4` | MMIO | N | :730=0x16c4 | :681=0x16c4 | — | OK |
| engine | `DEFAULT_PITCH_OFFSET` | `0x16e0` | MMIO | N | :690=0x16e0 | — | — | SINGLE-SOURCE |
| engine | `DST_PITCH_OFFSET` | `0x142c` | MMIO | N | :833=0x142c | :784=0x142c | :806=0x142c | OK |
| engine | `SRC_PITCH_OFFSET` | `0x1428` | MMIO | N | :1658=0x1428 | :1580=0x1428 | :805=0x1428 | OK |
| engine | `DEFAULT_SC_BOTTOM_RIGHT` | `0x16e8` | MMIO | N | :692=0x16e8 | :643=0x16e8 | — | OK |
| engine | `SC_TOP_LEFT` | `0x16ec` | MMIO | N | :1608=0x16ec | :1530=0x16ec | — | OK |
| engine | `SC_BOTTOM_RIGHT` | `0x16f0` | MMIO | N | :1603=0x16f0 | :1525=0x16f0 | — | OK |
| engine | `RB2D_DSTCACHE_MODE` | `0x3428` | MMIO | N | :1571=0x3428 | :1493=0x3428 | — | OK |
| engine | `WAIT_UNTIL` | `0x1720` | MMIO | N | :1784=0x1720 | :1705=0x1720 | :1097=0x1720 | OK |
| engine | `RB2D_DSTCACHE_CTLSTAT` | `0x342c` | MMIO | N | :1555=0x342c | :1488=0x342c | — | OK |
| engine | `RB3D_DSTCACHE_CTLSTAT` | `0x325c` | MMIO | N | :1560=0x325c, :1592=0x325c | :1514=0x325c | :932=0x325c | OK+DUP |
| engine | `DSTCACHE_CTLSTAT` | `0x1714` | MMIO? | N | :1572=0x1714 | :1494=0x1714 | — | OK |
| engine | `DEFAULT_OFFSET` | `0x16e0` | MMIO? | N | :689=0x16e0 | :641=0x16e0 | — | OK |
| engine | `DEFAULT_PITCH` | `0x16e4` | MMIO? | N | :691=0x16e4 | :642=0x16e4 | — | OK |
| engine | `AUX_SC_CNTL` | `0x1660` | MMIO | N | :115=0x1660 | — | — | SINGLE-SOURCE |
| engine | `DP_CNTL` | `0x16c0` | MMIO | N | :719=0x16c0 | :670=0x16c0 | — | OK |
| engine | `DP_WRITE_MASK` | `0x16cc` | MMIO | N | :816=0x16cc | :767=0x16cc | :804=0x16cc | OK |
| engine | `DP_BRUSH_FRGD_CLR` | `0x147c` | MMIO | N | :718=0x147c | :669=0x147c | — | OK |
| engine | `DST_Y_X` | `0x1438` | MMIO | N | :849=0x1438 | :800=0x1438 | — | OK |
| engine | `SRC_Y_X` | `0x1434` | MMIO | N | :1665=0x1434 | :1587=0x1434 | — | OK |
| engine | `DST_WIDTH_HEIGHT` | `0x1598` | MMIO | N | :841=0x1598 | :792=0x1598 | — | OK |
| cp | `CP_CSQ_CNTL` | `0x0740` | MMIO | F | :3226=0x740 | :3141=0x740 | :1131=0x740 | OK |
| cp | `CP_RB_BASE` | `0x0700` | MMIO | F | :3217=0x700 | :3132=0x700 | :1116=0x700 | OK |
| cp | `CP_RB_CNTL` | `0x0704` | MMIO | F | :3218=0x704 | :3133=0x704 | :1117=0x704 | OK |
| cp | `CP_RB_RPTR` | `0x0710` | MMIO | F | :3220=0x710 | :3135=0x710 | :1122=0x710 | OK |
| cp | `CP_RB_WPTR` | `0x0714` | MMIO | F | :3221=0x714 | :3136=0x714 | :1123=0x714 | OK |
| cp | `CP_RB_RPTR_ADDR` | `0x070c` | MMIO | F | :3219=0x70c | :3134=0x70c | :1121=0x70c | OK |
| cp | `CP_ME_RAM_ADDR` | `0x07d4` | MMIO | F | :3212=0x7d4 | :3127=0x7d4 | :1111=0x7d4 | OK |
| cp | `CP_ME_RAM_RADDR` | `0x07d8` | MMIO? | F | :3213=0x7d8 | :3128=0x7d8 | :1112=0x7d8 | OK |
| cp | `CP_ME_RAM_DATAH` | `0x07dc` | MMIO | F | :3214=0x7dc | :3129=0x7dc | :1113=0x7dc | OK |
| cp | `CP_ME_RAM_DATAL` | `0x07e0` | MMIO | F | :3215=0x7e0 | :3130=0x7e0 | :1114=0x7e0 | OK |
| cp | `SCRATCH_ADDR` | `0x0774` | MMIO | F | — | — | :820=0x774 | SINGLE-SOURCE |
| cp | `SCRATCH_UMSK` | `0x0770` | MMIO | F | — | — | :819=0x770 | SINGLE-SOURCE |
| cp | `SCRATCH_REG0` | `0x15e0` | MMIO | F | :1028=0x15e0 | :975=0x15e0 | :813=0x15e0 | OK |
| cp-pio | `CP_CSQ_APER_PRIMARY` | `0x1000` | MMIO? | N | :3241=0x1000 | :3156=0x1000 | — | OK |
| gart | `AIC_CNTL` | `0x01d0` | MMIO | F | :3248=0x1d0 | :3163=0x1d0 | :1140=0x1d0 | OK |
| gart | `AIC_STAT` | `0x01d4` | MMIO | F | — | — | :1143=0x1d4 | SINGLE-SOURCE |
| gart | `AIC_PT_BASE` | `0x01d8` | MMIO | F | — | — | :1144=0x1d8 | SINGLE-SOURCE |
| gart | `AIC_LO_ADDR` | `0x01dc` | MMIO | F | :3250=0x1dc | :3165=0x1dc | :1145=0x1dc | OK |
| gart | `AIC_HI_ADDR` | `0x01e0` | MMIO | F | — | — | :1146=0x1e0 | SINGLE-SOURCE |
<!-- END regtable.py -->
