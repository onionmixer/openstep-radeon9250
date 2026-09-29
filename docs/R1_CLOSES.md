# R1 결과가 닫는 것과 닫지 못하는 것

작성 2026-09-15.  R1 로그가 나오면 어느 열린 항목을 **어느 필드로** 닫는지, 그리고 R1 이 원칙상
읽지 않아서(인덱스 쓰기·PLL 공간·목록 밖) **뒤 단계 스냅샷이 맡아야 하는 것**을 미리 고정한다.
표는 `tools/r1/closes.py` 가 낸다: 항목이 인용한 필드가 R1 파서가 실제로 내는 것인지, "R1 이 읽지
않는다" 고 적은 레지스터가 정말 R1 목록에 없고 참고 헤더에 실재하는지, 출처 절 제목이 그 문서에
있는지를 검사한다(음성 대조 4 종).

읽는 법: R1 실행 뒤 `parse_r1.py` 보고서의 해당 필드를 이 표의 "판정·다음" 칸에 따라 해석해
`docs/R1_RESULT.md` 에 적는다.  "R1 로 못 닫음" 항목과 생성표 B 는 **R2/R5 계획서의 스냅샷 목록에
그대로 들어가야 한다** — 빠지면 그 계획서가 불완전하다.

## 제안 — R1 목록 확장 (**검토 필요, 코드 미반영**)

생성표 B 의 MMIO 레지스터 13 개는 모두 R1 의 0x2000 매핑 안(최대 `0x0f60`)이다 — PLL 공간 5 개와
달리 인덱스 쓰기 없이 읽을 수 있어서, R1 에 넣으면 R2·R5 가 스냅샷 전에 값을 안다.  그러나
**probe 변경은 계획 → 교차검토 → 코드 순서**이고(codex 사용 불가 기간), 이 레지스터들의
**읽기 부작용**은 R1 계획 §4-B 의 기준(참고 트리에서 읽기가 상태를 바꾸는 근거 없음)으로 하나씩
확인한 적이 없다.  특히 `I2C_CNTL_1`·`VIPH_CONTROL`(외부 버스 제어기)·`RBBM_SOFT_RESET`(리셋
레지스터, 참고 구현은 쓴 직후 읽는다) 은 확인 뒤에만 넣는다.  → R1 계획 개정안으로 codex 검토에
보낸다.

<!-- BEGIN r1/closes.py --markdown (generated; do not edit) -->
### 생성표 A — 열린 항목 → R1 필드

| 출처 | 항목 | R1 이 주는 것 | 판정·다음 |
|---|---|---|---|
| `R0_2_MODESET_DECODE.md` 5. 열린 질문 | 5-1 분주 슬롯: 콘솔이 쓰는 `PLL_DIV_SEL` | `CLOCK_CNTL_INDEX` | 기록만(설계는 DIV3 로 이미 닫힘).  bits 8-9 해독은 parse_r1 |
| `R0_2_MODESET_DECODE.md` 5. 열린 질문 | 5-2 PLL 이득(PVG): BIOS 가 둔 `PPLL_CNTL` 보존 여부 | **R1 로 못 닫음** | PLL 인덱스 읽기라 R1 금지 — R2 스냅샷 |
| `R0_2_MODESET_DECODE.md` 5. 열린 질문 | 5-3 `HOST_PATH_CNTL` 스냅샷 값 | `HOST_PATH_CNTL` | 값과 `HDP_APER_CNTL` 비트를 기록 → R2 가 보존 |
| `R0_2_MODESET_DECODE.md` 5. 열린 질문 | 5-5 BIOS 가 CP 를 켜 두는가 | `CP_CSQ_CNTL`, `CP_RB_CNTL`, `RBBM_STATUS` | 모드 비트 28-31 이 0 이 아니면 R2 3 단계가 중단 |
| `R0_2_MODESET_DECODE.md` 5. 열린 질문 | 5-6 부분 실패 시 복원 경계 | **R1 로 못 닫음** | R2 계획서(R0-3 상태 기계와 함께) |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-3 엔진 유휴·CP 꺼짐 | `RBBM_STATUS`, `CP_CSQ_CNTL` | R1 스냅샷에서 CP 꺼짐 확인 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-4 MC 맵: 스냅샷과 목표값이 다른가 | `MC_FB_LOCATION`, `MC_AGP_LOCATION`, `CONFIG_APER_0_BASE`, `CONFIG_MEMSIZE`, `CONFIG_APER_SIZE`, `cfg` | parse_r1 판정 "RV280-aligned aperture base" 가 같음/다름을 낸다 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-5/4-6 CRTC1 생성·확장 레지스터의 현재 값 | `CRTC_GEN_CNTL`, `CRTC_EXT_CNTL` | `CRT_ON` 보존의 기준값 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-7 콘솔 타이밍 | `CRTC_H_TOTAL_DISP`, `CRTC_H_SYNC_STRT_WID`, `CRTC_V_TOTAL_DISP`, `CRTC_V_SYNC_STRT_WID` | 역해독(radeon_decode) 으로 콘솔 해상도 추정 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-8 목표 분주가 현재와 다른가 | **R1 로 못 닫음** | `PPLL_DIV_3`·`PPLL_REF_DIV` 는 PLL 공간 — R2 스냅샷 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-9 스캔아웃 주소·피치 | `CRTC_OFFSET`, `CRTC_PITCH`, `DISPLAY_BASE_ADDR` | `CRTC_OFFSET_CNTL`·`DISP_MERGE_CNTL` 은 R1 에 없음(아래 표) |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-10 `SURFACE_CNTL` 이 0 인가 | `SURFACE_CNTL` | 0 이 아니면 R2 가 쓰기 대상에 넣는다 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-11/11b DAC·FIFO·센터링 | `DAC_CNTL`, `DAC_CNTL2`, `DAC_MACRO_CNTL`, `GRPH_BUFFER_CNTL`, `CRTC_MORE_CNTL` | xf86 만의 조치를 할지 R2 계획서가 이 값으로 정한다(Q5 4b) |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-12 팔레트 접근 비트 | `DAC_CNTL2` | `DAC2_PALETTE_ACC_CTL` 은 `DAC_CNTL2` 의 bit 5(`radeonfbreg.h:610`) |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-12b 방해 가능 클라이언트 | `GEN_INT_CNTL` | 나머지 7 개는 R1 에 없음(아래 표) — R2 스냅샷 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 비활성 출력 확인(CRTC2·FP·TV) | `CRTC2_GEN_CNTL`, `FP_GEN_CNTL`, `DISP_OUTPUT_CNTL` | 켜져 있으면 진입 중단(Q5 4c).  `TV_DAC_CNTL` 은 R1 에 없음 |
| `R0_2_MODESET_DECODE.md` 4. 첫 점등 시퀀스 초안 | 4-14 FB 매핑 길이 ≤ 보고 VRAM·애퍼처 | `CONFIG_MEMSIZE`, `CONFIG_APER_SIZE`, `cfg`, `bridge` | BAR0 크기는 R1 이 재지 않는다(sizing 은 쓰기) |
| `R0_3_VGA_RETURN_DECODE.md` 5. 열린 질문 | 5-3 콘솔이 그래픽인가 텍스트인가 | **R1 로 못 닫음** | `ATTR[0x10]` 읽기는 인덱스 쓰기 — R2 스냅샷 |
| `R0_3_VGA_RETURN_DECODE.md` 5. 열린 질문 | 5-4 표준 VGA I/O 포트가 이 카드로 가는가 | `cfg` | 명령 레지스터 I/O 디코드 비트만 기록.  포트 접근 자체는 R2 |
| `R5_GART.md` 3. R5 계획서가 정할 것 | GART 창이 FB 와 겹치는가(4 MiB 정렬) | `MC_FB_LOCATION` | `gart_oracle.py <MC_FB_LOCATION>` 에 R1 값을 넣으면 판정 |
| `R5_CP_SEQUENCE.md` 2. PLAN R5 에 없던 사실 | #3 `MC_AGP_LOCATION` 원래 값 | `MC_AGP_LOCATION` | R5 스냅샷 복원 목록의 기준값 |
| `R5_CP_SEQUENCE.md` 2. PLAN R5 에 없던 사실 | #3 `AGP_COMMAND` 원래 값 | **R1 로 못 닫음** | R1 목록에 없음 — R5 스냅샷 |
| `R5_CP_SEQUENCE.md` 2. PLAN R5 에 없던 사실 | #5 `BUS_CNTL.BUS_MASTER_DIS` 원래 값 | `BUS_CNTL`, `cfg` | parse_r1 판정이 bit 6 과 PCI 명령 버스마스터 비트를 낸다 |

### 생성표 B — 뒤 단계가 필요로 하는데 R1 이 읽지 않는 레지스터

| 레지스터 | 오프셋(헤더) | 공간 | 필요한 단계 | 이유 |
|---|---|---|---|---|
| `PPLL_CNTL` | `0x0002` | PLL | R2 | PLL 공간 — 인덱스 쓰기 |
| `PPLL_REF_DIV` | `0x0003` | PLL | R2 | PLL 공간 — 인덱스 쓰기 |
| `PPLL_DIV_3` | `0x0007` | PLL | R2 | PLL 공간 — 인덱스 쓰기 |
| `VCLK_ECP_CNTL` | `0x0008` | PLL | R2 | PLL 공간 — 인덱스 쓰기 |
| `MCLK_CNTL` | `0x0012` | PLL | R5 | PLL 공간, 엔진 리셋이 저장·복원 |
| `CRTC_OFFSET_CNTL` | `0x0228` | MMIO | R2 | 4-9 |
| `DISP_MERGE_CNTL` | `0x0d60` | MMIO | R2 | 4-9 `RGB_OFFSET_EN` |
| `OVR_CLR` | `0x0230` | MMIO | R2 | 4-12b |
| `OVR_WID_LEFT_RIGHT` | `0x0234` | MMIO | R2 | 4-12b |
| `OV0_SCALE_CNTL` | `0x0420` | MMIO | R2 | 4-12b |
| `SUBPIC_CNTL` | `0x0540` | MMIO | R2 | 4-12b |
| `VIPH_CONTROL` | `0x0c40` | MMIO | R2 | 4-12b |
| `I2C_CNTL_1` | `0x0094` | MMIO | R2 | 4-12b |
| `CAP0_TRIG_CNTL` | `0x0950` | MMIO | R2 | 4-12b |
| `TV_DAC_CNTL` | `0x088c` | MMIO | R2 | 비활성 출력 확인 |
| `AGP_COMMAND` | `0x0f60` | MMIO | R5 | GART 켤 때 0 으로 씀(R5 사실 #3) |
| `SURFACE0_INFO` | `0x0b0c` | MMIO | R5 | GART 표 서피스 경계(R5 사실 #4) |
| `RBBM_SOFT_RESET` | `0x00f0` | MMIO | R5 | 엔진 리셋이 저장·복원 |
<!-- END r1/closes.py -->
