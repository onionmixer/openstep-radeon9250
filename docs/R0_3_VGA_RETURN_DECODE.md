# R0-3 — VGA 복귀(`revertToVGAMode`) 해독과 설계 초안

작성 2026-09-15.  하드웨어 무접촉.  1–3 절은 소스·기록에서 읽은 사실(인용은
`tools/oracle/check_citations.py docs/R0_3_VGA_RETURN_DECODE.md`), 4 절은 **검토 전
설계**.  radeonfb 는 VGA 로 돌아가지 않으므로 이 절의 참고는 xf86-video-ati 와
Matrox 프로젝트의 실측 기록이다.

## 1. OPENSTEP 의 호출 계약

- DriverKit 헤더: 모드 전환을 단순하게 하려고 **`revertToVGAMode` 를 먼저 부르고**
  (`IOFrameBufferDisplay.h:47-50`), 표준 VGA 로 되돌리는 일은 **하위 클래스가 장치별로
  구현한다**(`IOFrameBufferDisplay.h:56-61`) — 상위 클래스는 하드웨어를 되돌려 주지 않는다.
- Matrox 실측(같은 커널):
  - 부팅 때 `revertVGA 1`·`enterLinear 1` — revert 가 enter 보다 먼저
    (`REMAINING_WORK.md:3310-3317`).
  - 로그아웃은 둘 다 부르지 않는다, 부팅 때의 revert 는 **초기화의 일부**
    (`REMAINING_WORK.md:3579-3604`).
  - 종료 경로는 revert 를 부른다 — 복원을 켜자 종료 중 콘솔이 돌아왔다
    (`REMAINING_WORK.md:3639-3646`).
  - 복원을 안 하면 재부팅 중 화면이 검다: 드라이버가 바꾼 클럭 선택을 아무도 되돌리지
    않기 때문(`REMAINING_WORK.md:3278-3292`).
  - 인덱스 레지스터 스냅샷은 "읽기만" 이 아니다 — 인덱스를 써야 읽히고, 속성 레지스터는
    팔레트 주소 소스 비트를 지워야 읽힌다(`REMAINING_WORK.md:3327-3333`).
  - 텍스트/그래픽 판정의 정본은 `ATTR[0x10]` 비트 0(X.Org generic VGA 와 같음), 스캔
    라인 수로 판정한 것은 틀렸었다(`REMAINING_WORK.md:3384-3399`).  그 머신의 콘솔은
    640×480 그래픽이었다(`REMAINING_WORK.md:3354-3371`).

## 2. xf86-video-ati 의 레거시 저장·복원

저장(`RADEONSave`, `radeon_driver.c:5738-5801`):
1. 표준 VGA: `vgaHWSave(... VGA_SR_MODE | VGA_SR_FONTS)` — **I/O 포트** 방식
   (`radeon_driver.c:5777`; 포트 함수 선택은 `radeon_driver.c:3132-3135`).
2. `DP_DATATYPE`, `RBBM_SOFT_RESET`, `CLOCK_CNTL_INDEX`(`radeon_driver.c:5790-5793`).
3. MC 맵(`MC_FB/AGP_LOCATION`, `DISPLAY_BASE_ADDR`, `DISPLAY2_BASE_ADDR`,
   `OV0_BASE_ADDR`, `radeon_driver.c:4462-4475`), 공용(`legacy_crtc.c:498-516`),
   PLL1(`legacy_crtc.c:599-616` — **`PPLL_DIV_3` 만 저장**, `legacy_crtc.c:602`),
   CRTC1(`legacy_crtc.c:529-562`), FP(`legacy_output.c:380-404`),
   DAC(`legacy_output.c:362-376`), CRTC2/PLL2, 표면 8 조.
4. BIOS 스크래치 0–7 은 초기화 때 따로(`radeon_driver.c:5711-5737`).

복원(`RADEONRestore`, `radeon_driver.c:5814-5928`) — **순서가 의도적이다**:
1. 블랭크(`radeon_driver.c:5837`).
2. `RBBM_SOFT_RESET`·`DP_DATATYPE`·`GRPH(2)_BUFFER_CNTL`(`radeon_driver.c:5844-5847`).
3. MC 맵 → 공용 → 팔레트 → CRTC2/PLL2 → CRTC1 → PLL1 → RMX/FP/FP2/LVDS
   (`radeon_driver.c:5845-5863`).
4. `CLOCK_CNTL_INDEX` 를 저장값으로(`radeon_driver.c:5873`) — PLL1 복원이 세운
   `PLL_DIV_SEL`=3(`legacy_crtc.c:348-351`) 을 콘솔의 선택으로 되돌린다.
5. BIOS 스크래치(`radeon_driver.c:5876`), 100 ms(`radeon_driver.c:5886`), 표면.
6. **원래 켜져 있던 CRTC 만** 다시 켠다 — "crtc 를 실수로 켜면 행이 날 수 있다"
   (`radeon_driver.c:5882-5892`).
7. 표준 VGA 모드·폰트 복원(`radeon_driver.c:5914`).
8. **DAC 마지막** — 그러지 않으면 화면이 빌 수 있다(`radeon_driver.c:5912-5920`).
   DAC 복원은 `DAC_CNTL` 의 범위·블랭킹 비트만 남기고 나머지와 `DAC_CNTL2`,
   `TV_DAC_CNTL`, `DISP_OUTPUT_CNTL`, `DISP_HW_DEBUG`, `DAC_MACRO_CNTL`
   (`legacy_output.c:246-276`).

## 3. 분주 슬롯과 VGA 클럭 — 근거와 한계

- xf86 은 "지금 쓰는 분주" 를 `PPLL_DIV_0 + (CLOCK_CNTL_INDEX 둘째 바이트 & 3)` 으로
  읽는다(`radeon_driver.c:1070-1079`, `legacy_output.c:205-207`).
- xf86 은 모드 설정에서 `PPLL_DIV_3` 만 쓰고(`legacy_crtc.c:348-380`), 콘솔 저장도
  `PPLL_DIV_3` 만 하며(`legacy_crtc.c:602`), 복원 끝에 인덱스를 되돌린다(2 절 4).
  → **xf86 은 `PPLL_DIV_0..2` 를 건드리지 않는 설계**다.  radeonfb 는 `DIV_0` 을
  덮어쓴다(`radeonfb.c:2237-2238`).
- **확인 못 한 것**: VGA 텍스트/그래픽 모드에서 VGA `MISC` 의 클럭 선택 비트가
  `PPLL_DIV_0..2` 중 무엇을 고르는지 명시한 소스는 참고 트리에 없다 `[미확인]`.
  그래서 "DIV_0 을 덮으면 VGA 클럭이 망가진다" 는 **추론**이고, xf86 방식(DIV_3 +
  인덱스 복원)은 그 추론이 맞든 틀리든 안전하다.

## 4. 설계 초안 — **검토 전**

**원칙**: 복원은 "이 드라이버가 바꾼 것을, 바꾸기 전 값으로" 되돌린다.
xf86 처럼 콘솔 전체 상태를 재구성하지 않는다(R0-2 4 절의 최소 변경 원칙과 짝).

상태 기계(Matrox 3-54 의 교차검토 교훈 포함, `REMAINING_WORK.md:3474-3485`):

| 상태 변수 | 의미 |
|---|---|
| `snapshotValid` | `enterLinearMode` 첫 쓰기 **직전**에 스냅샷을 찍었다 |
| `hardwareTouched` | 스냅샷 뒤 첫 쓰기가 일어났다(부분 진입 포함) |
| `consoleIsGraphics` | 스냅샷의 `ATTR[0x10]` bit0 |

`revertToVGAMode`:
1. 생명주기(플래그 해제, super 호출)는 **항상** 한다 — 조건은 하드웨어 쓰기만 감싼다.
2. `snapshotValid && hardwareTouched` 가 아니면 하드웨어를 건드리지 않는다.
   부팅 때의 첫 revert 가 여기 해당한다.
3. `consoleIsGraphics` 가 거짓(텍스트)이면: 폰트 평면을 저장하지 않았으므로 레지스터
   복원이 옳을 수 없다 → **복원을 무장하지 않는다**(판정은 `enterLinearMode` 의 스냅샷
   시점에 내리고 기록).  모드 진입 자체는 막지 않는다 — Matrox 기록은 텍스트면 복원 기능을
   켜는 일을 멈췄지 진입을 막지 않았고(`REMAINING_WORK.md:3503-3511`), 결과는 종료 중 검은
   콘솔이며 다음 부팅의 BIOS 가 복구한다.  텍스트 콘솔에서의 복원은 폰트 평면 저장·복원이
   선행 조건이다(Q5 7a 부분 채택).
4. 복원 순서(xf86 순서를 줄여서): 블랭크·요청 차단 → MC 맵(바꿨을 때만, AGP 먼저) →
   공용 클라이언트 레지스터 → CRTC1 워드(`GEN`/`EXT` 는 요청 차단 유지한 채) → PPLL 공통
   상태(`PPLL_CNTL`·`PPLL_REF_DIV`)·**`PPLL_DIV_3`**·`VCLK_ECP_CNTL` → `CLOCK_CNTL_INDEX`
   저장값(콘솔의 `PLL_DIV_SEL` 로) → `SURFACE_CNTL`(바꿨을 때만) → 팔레트 → **표준 VGA
   레지스터 전체(MISC/SEQ/CRTC/GR/ATTR) 스냅샷 값으로** → 요청 차단·블랭크 해제를 스냅샷의
   원래 값으로 → **DAC 마지막**.
5. 모든 대기는 상한 + 종결 걸쇠, 반복 호출은 멱등(`hardwareTouched` 를 복원 끝에 내림).

표준 VGA 레지스터(MISC/SEQ/CRTC/GR/ATTR): **스냅샷·복원한다**(Q5 6 채택).  확장 비트를
끄는 것만으로 VGA 타이밍이 돌아온다는 근거는 참고 트리에 없고, xf86 은 Radeon 상태 뒤에 표준
VGA 모드·폰트를 따로 복원한다(`radeon_driver.c:5914`).  Matrox 가 실기에서 성공한 방식도
표준 레지스터 전체 스냅샷·복원이었다(`REMAINING_WORK.md:3327-3333` 과 3-54).  VGA 레지스터
접근은 I/O 포트(xf86 방식) 또는 MMIO 미러 중 R2 계획에서 정하고, 속성 레지스터 읽기는 상태를
바꾸므로(플립플롭·팔레트 주소 소스) 인덱스 쓰기 등급으로 스냅샷 단계에서만 한다.

## 5. 열린 질문

1. VGA `MISC` 클럭 선택 ↔ `PPLL_DIV_n` 대응(3 절) — **미확인으로 확정**(Q5, 참고 트리 전수).
   설계는 대응과 무관하게 안전한 DIV3 방식으로 닫는다.
2. ~~확장 비트 해제만으로 VGA 스캔아웃 복귀가 되는가~~ — 근거 없음, 표준 VGA 레지스터를
   복원하는 설계로 닫는다.
3. 이 머신의 부팅 콘솔이 그래픽인가 텍스트인가 — R1 에서 `ATTR[0x10]` 을 읽으려면
   속성 인덱스 쓰기가 필요하다(쓰기 등급 E) → R1 에서는 읽지 않고 **R2 스냅샷에서** 판정.
4. 표준 VGA I/O 포트 접근이 OPENSTEP 커널 드라이버에서 이 카드로 가는가(generic VGA
   드라이버와 같은 포트) — Matrox 는 MMIO 미러를 썼다.  xf86 은 I/O 포트.
