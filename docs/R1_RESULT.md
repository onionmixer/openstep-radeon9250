# R1 결과 — 2026-09-15 실기

**게이트 PASS**(`parse_r1.py build/r1/rdn-r1-789453017.log 789453017 ba397d2b`).  하드웨어 쓰기 없는 조사가
행 없이 끝났고, 모듈은 적재→실행(끝 줄 0 s)→언로드·삭제 모두 종료 코드 0.

- 실행 기록: `build/r1/build-789453017.log`, `build/r1/run-789453017.out`, 로그 `build/r1/rdn-r1-789453017.log`
  (호스트 nxlogd 사본 `logs/kernel-20260915-150235.log`).
- 사전 확인: `pcils` 스캔 `logs-pcils-20260915*.txt`(같은 부팅, 읽기 전용).
- 해석은 `docs/R1_CLOSES.md` 표 순서를 따른다.  수치 풀이는 Python.

## 1. 실행 중 드러난 것 (probe·도구)

| # | 사실 | 조치 |
|---|---|---|
| 1 | 첫 타깃 빌드 실패 "Don't know how to make RDNR1Probe.m" — tar 멤버 mtime 0 을 타깃 make 가 "없음" 으로 읽음 | `pack_probe.py` 가 고정 과거 시각(2000-01-01) 사용, mtime 0 이면 묶기 거절 |
| 2 | 첫 실행 `789452328` 게이트 FAIL: **커널 `sprintf` 는 `l` 변환의 폭을 무시**(`%08lx` → `303`) — 엄격 문법이 잡음 | probe 형식을 `(unsigned int)` + `%08x` 로, 시뮬레이터가 커널 동작을 흉내, hostcheck 텍스트 규칙+변이, 시뮬레이터 변이.  첫 실행 로그는 증거로 보존 |
| 3 | cc 2.7.2.1 컴파일·`kl_ld` 링크 성공, `nm -u` 8 개 전부 커널 export(`IODevice`/`Object` 클래스 참조 포함) | — |
| 4 | 번들 `Default.table` 의 `Server Name` 줄 2 개(원본 + postamble) | `target-build.sh` 판정이 예상대로 통과 |
| 5 | 타깃에 `uname` 없음, `egrep -i` 없음 | 로그에 에러 한 줄뿐, 판정 무관 |
| 6 | `target-run.sh` 는 수 초에 끝났는데 gcds 명령 반환은 5 분 이상 | 원인 미확인(스크립트는 정상 종료).  다음 실기 스크립트는 백그라운드 실행+타깃 파일로 완료 판정 |

## 2. 카드와 버스

- `03:0b.0` **1002:5960 rev 01**, class 030000, subsystem 1002:5960.  한 단 브리지 `00:1e.0`(버스 3).
- BAR0 `e0000008`(prefetch, VRAM 애퍼처), BAR1 io `3001`, **BAR2 `d0200000`**(MMIO).  브리지 메모리 창
  `d0200000–d02fffff`, prefetch 창 `e0000000–efffffff`(32 비트).  probe·호스트 재계산 일치, 두 번 읽기 일치.
- PCI 명령 `0x0307`: **버스 마스터가 BIOS 에서 이미 켜져 있다**.  칩 쪽 `BUS_CNTL.BUS_MASTER_DIS` = 0.
- `/dev/mem` 존재(`crw-r----- 3,0`) → BIOS 셰도는 R1 계획 §6 C1(셸 읽기) 선택지가 열려 있다.

## 3. 레지스터 해석

| 항목 | 값 | 해석·다음 |
|---|---|---|
| 생존 | VLINE 8 표본 8 값, FRAME 60 ms 에 +4 | MMIO 매핑이 캐시 없이 디코드됨.  FRAME 은 이 모드에서 증가(≈66.7 프레임/초 — 60 ms 창이라 거친 값) |
| VRAM | `CONFIG_MEMSIZE` 128 MiB, `CONFIG_APER_SIZE` 128 MiB, `HOST_PATH_CNTL` `70000000`(HDP_APER_CNTL 0) | 128 MiB 카드 |
| MC 맵 | `MC_FB_LOCATION` `1fff0000` → 카드 주소 `00000000–1fffffff`(512 MiB 창, VRAM 128 MiB), `MC_AGP_LOCATION` `27ff2000` → `20000000–27ffffff`, `DISPLAY_BASE_ADDR` 0 | BIOS 는 FB 를 카드 주소 0 에 두었다.  xf86 의 RV280 규칙은 **크기 정렬**이고(`radeon_driver.c` 1498–1513 행 주석 "must be aligned to the size") 시작 0 은 정렬을 만족한다(Python).  파서의 "DIFFERENT" 는 xf86 이 **고를 위치**(애퍼처 `e0000000`)와 다르다는 뜻이지 규칙 위반이 아니다 → R2 는 바꿀 필요가 없다(R2 계획서에서 결정), R5 GART 배치 때 다시 본다 |
| GART 산술 | `gart_oracle.py 1fff0000 8 8192`: 창 `20000000–207fffff`, 문제 없음 | 이 창은 BIOS 의 **AGP 위치 `20000000–27ffffff` 와 겹친다** — 참고 구현은 GART 를 켤 때 AGP 위치를 `ffffffc0` 으로 옮기므로(R5 사실 #3) 순서가 중요 |
| 콘솔 모드 | CRTC 워드 800×600, 총 1024×626, sync 양극.  **`CRTC_GEN_CNTL.EXT_DISP_EN` = 0**(형식 8 bpp, `CRTC_EN` 1) | 확장 CRTC 가 아니라 **VGA 코어가 화면을 구동**하는 상태 — 확장 타이밍 워드가 실제 스캔아웃 값인지는 **미확인**(VGA 레지스터 스냅샷이 필요, R2) |
| 분주 슬롯 | `CLOCK_CNTL_INDEX` `00000303`: `PLL_DIV_SEL` = **3**, 마지막 인덱스 3(`PPLL_REF_DIV`) | VGA 코어 구동 중이라 이 선택이 스캔아웃 클럭인지 **미확인**.  어느 쪽이든 R2 가 `PPLL_DIV_3` 을 쓰면 BIOS 값을 덮으므로 R0-3 복원의 `PPLL_DIV_3` 스냅샷·복원이 **필수**.  *정정 2026-09-15: 처음엔 "콘솔이 DIV3 을 쓴다" 로 적었다 — 증거보다 강한 표현* |
| CRTC | `CRTC_GEN_CNTL` `02000200`(CRTC_EN, 8 bpp), `CRTC_EXT_CNTL` `36088040`(`XCRT_CNT_EN`·`CRT_ON`, 그리고 **두 참고 헤더에 정의 없는 bit 19·25·26·28·29**), `CRTC_OFFSET` 0, `CRTC_PITCH` `32` | 미정의 비트가 서 있으므로 쓰기는 **읽고-바꾸고-쓰기**로만(R2) |
| 비활성 출력 | `CRTC2_GEN_CNTL` `04000000`(`CRTC2_DISP_REQ_EN_B` 만, `CRTC2_EN` 0), `FP_GEN_CNTL` 0, `DISP_OUTPUT_CNTL` `10000000`(bit 28 — 두 참고 헤더에 정의 없음) | CRTC2·FP 꺼짐 확인 |
| DAC | `DAC_CNTL` `ff604002`(범위 PS2, `MASK_ALL`, **`8BIT_EN` 0 = 6 비트 VGA 팔레트**, `DAC_PDWN` 0, 미정의 bit 14·21·22), `DAC_CNTL2` 0, `DAC_MACRO_CNTL` `00000607`(RGB 전원 끔 비트 0), `GRPH_BUFFER_CNTL` `20205c5c`(start 92·stop 92·critical 32·bit 29), `CRTC_MORE_CNTL` 0 | R0-2 4-11b 결정 입력.  DAC 는 켜져 있다 |
| `SURFACE_CNTL` | `00000100` = `SURF_TRANSLATION_DIS`(bit 8) 만, 바이트 스왑 비트 0 | 변환 **꺼짐** 비트라 R0-2 4-10("타일링·변환이 켜져 있으면 해제") 의 대상이 아니다 — 보존 |
| CP·엔진 | `CP_CSQ_CNTL` `02010080`(모드 0 = 꺼짐), `CP_RB_*` 0, `RBBM_STATUS` `00000140`(ACTIVE 0), `AIC_CNTL` 0 | CP·GART 꺼짐, 엔진 유휴 — R2 3 단계 조건 충족 |
| 인터럽트 | `GEN_INT_CNTL` 0, `GEN_INT_STATUS` `00080007` | 전부 마스크, 상태 비트 걸려 있음(읽기만) |
| 메모리 | `MEM_SDRAM_MODE_REG` `75320032` | 기록 |

## 4. 다음

- R2 계획서(첫 점등): 위 3 절의 "다름"·"필수"·"0 이 아님" 항목, `docs/R1_CLOSES.md` 의 "R1 로 못 닫음"
  항목과 생성표 B 레지스터(PLL 공간 포함)를 스냅샷 목록에 넣는다.  계획 → **codex 검토** → 코드 순서.
- BIOS 셰도(C1): `/dev/mem` 이 있으니 셸 읽기 계획을 따로 세운다(쓰기 없음, 계획서 먼저).
