# R6 — 최소 3D 하드웨어 시험기: 첫 조각 R6a (계획, 코딩 전, 교차검토 대상, 2026-09-19)

입력: `PLAN.md` R6, `docs/R6_CLEAR_QUAD.md`(선례 워드열, `tools/oracle/r200_clear_oracle.py`), `docs/R6_VERIFIER_FACTS.md`, `docs/review/Q4_verdict.md`,
R4(엔진·오프스크린 창·uncached 별칭), R5·R5d·R5 STOP 수정(CP 링).  참고 조사는 내부 agent 가 했고, 아래 인용은 **이 세션에서 원문을 연 것만** 적었다.

## 0. 한 줄 요약

R6 는 PLAN 의 사다리(평면색 → 구로 → 깊이 → 텍스처 → 블렌드 → 시저 → 배치 → 재사용)로 가기 전에, **참고 선례를 그대로 되풀이하는 조각 R6a** 로 3D 엔진을
처음 깨운다: FreeBSD 의 R200 **깊이 지우기 사각형**(`radeon_state.c` 1124–1247 행)을 드라이버가 스스로 만든 링 워드로 한 번 그리고, 오프스크린 깊이 버퍼를
CPU 로 되읽어 python 오라클과 **워드 단위로** 대조한다.  유저 제출·검증기·색 쓰기·정점 색은 R6a 에 없다.

## 1. 확인한 사실 (이 세션에서 연 것)

| # | 사실 | 근거 |
|---|---|---|
| F1 | 선례가 쓰는 레지스터와 값(상태 26 워드, 클립 4, `3D_DRAW_IMMD_2` 14) — `RB3D_CNTL=0x1902`(32 bpp, 평면 마스크 사용·Z 켬), `RB3D_ZSTENCILCNTL=0x42227072`(24 비트·항상 통과·깊이 쓰기), `RB3D_PLANEMASK=0`(색 쓰지 않음), `SE_VTE_CNTL=0x300`, `SE_VTX_FMT_0=3`(Z0·W0), `SE_VAP_CNTL=0x00240000`(TCL 끔), 정점 w = 1.0 | `docs/R6_CLEAR_QUAD.md` 생성표(오라클이 FreeBSD 본문을 파싱해 대조) |
| F2 | 선례는 **깊이 버퍼 주소·피치를 쓰지 않는다** — 클라이언트(Mesa 문맥 상태)가 먼저 보낸다: `RB3D_DEPTHOFFSET`(0x1c24)=깊이 오프셋+FB 위치, `RB3D_DEPTHPITCH`(0x1c28)=피치(**픽셀**, 마스크 0x1ff8)·엔디언 무교환 | Mesa `r200_state_init.c` 581–590 행, 마스크·엔디언 `r200_reg.h` 92–95 행(열어 확인) |
| F3 | **Radeon 계열은 깊이 타일링이 늘 켜져 있다**; 표면 레지스터로 번역하지 않으면 CPU 는 `r200_mba_z32`/`r200_mba_z16` 공식으로 주소를 계산해야 한다 | Mesa `r200_span.c` 110–172 행(열어 확인) |
| F4 | 깊이 피치는 32 픽셀 배수, 높이는 16 행 배수(타일 때문) | xf86 `radeon_accel.c` 1183–1189 행(열어 확인) |
| F5 | RV280 은 HiZ 목록에 없다(`RADEON_HAS_HIERZ` 는 R100·RV200·R200·R300…) — 선례의 압축·계층 비트는 플래그가 있을 때만 | FreeBSD `radeon_cp.c` 2004–2018 행(열어 확인) |
| F6 | CPU 가 VRAM 을 읽기 전 참고의 유휴: 링에 `PURGE_CACHE`(`DSTCACHE_CTLSTAT(0x325c)=DC_FLUSH\|DC_FREE`=0xf)·`PURGE_ZCACHE`(`ZCACHE_CTLSTAT(0x3254)=ZC_FLUSH\|ZC_FREE`=5)·`WAIT_UNTIL_IDLE` | FreeBSD `radeon_cp.c` 551–563 행, `radeon_drv.h` 1941–1980·923–934 행(열어 확인) |
| F7 | KMS 는 같은 자리에서 `HOST_PATH_CNTL` 의 `HDP_READ_BUFFER_INVALIDATE` 도 켰다 끈다 | Linux `r100.c` 852–866 행(열어 확인) — R4 는 `HOST_PATH_CNTL` 을 **쓰지 않는** 규칙(`docs/R4_ENGINE_PLAN.md` 106 행) |
| F8 | Mesa 는 CPU 되읽기 전에 첫 픽셀을 읽어 다시 쓴다 — "온카드 읽기 캐시가 갱신을 못 본다" | Mesa `r200_span.c` 239–263 행(열어 확인) |
| F9 | DRM 규칙: `SE_VAP_CNTL` 을 보내기 전에 `SE_TCL_STATE_FLUSH`(0x2284)=0 | FreeBSD `radeon_state.c` 172–178 행(열어 확인) |
| F10 | FB 는 카드 주소 0(MC_FB_LOCATION `1fff0000`) — 참고의 오프셋은 카드 주소이므로 VRAM 오프셋 = 카드 주소 | R1 실측, FreeBSD `radeon_cp.c` 1312–1315 행(열어 확인): `fb_location = (reg & 0xffff) << 16` = 0 |
| F11 | R4 오프스크린 창 + 창 시작 256 KiB 의 uncached 별칭이 엔진의 쓰기를 본다(실측) | `osrdn_engine.h` 주석, R4a/R4b PASS |
| F12 | python: 피치 64·높이 64 에서 `r200_mba_z32` 는 버퍼 안의 1:1 사상(최대 16380 < 16384); 사각형 (5,3)–(37,21) 576 픽셀의 타일 주소와 선형 주소는 190 곳만 겹친다 → 되읽기가 두 가설을 가른다 | python(이 세션) |

## 2. R6a 설계

### 2-1. 연산 (R5 연산 표에 추가, 키 `"RDN 3D Test"` 옵트인, 모드 클레임·noSleep, CP 가 RUNNING 이고 걸쇠 아닐 때만)
- **REC3D**: 3D 관련 레지스터를 **읽기만**(RBBM 먼저) — 0x1c14–0x1c50, 0x1d7c–0x1d84, 0x2080–0x2094, 0x20b0, 0x2140, 0x2180, 0x2250, 0x26c4, 0x26f0, 0x2cc4, 0x3254, 0x325c.
  부팅값·RESET 뒤 값을 처음으로 실측(참고 없음 → 기록).
- **ZPREP**: CPU 가 별칭으로 깊이 버퍼 영역(16 KiB)과 희생 색 버퍼 영역(16 KiB)을 **위치 부호 패턴**으로 채우고 되읽어 확인(엔진 무관).
- **ZCLEAR** (arg = 경우 번호, 2 경우 표): 링에 다음을 한 번에 넣고 WPTR, 따라잡기·유휴(R5 대기·걸쇠 규칙 그대로) —
  1. 전제 상태: `SE_TCL_STATE_FLUSH=0`(F9), `RB3D_DEPTHOFFSET`=깊이 버퍼 카드 주소, `RB3D_DEPTHPITCH`=64(엔디언 무교환), `RB3D_COLOROFFSET`=희생 색 버퍼, `RB3D_COLORPITCH`=64(타일 끔)
  2. 선례 워드열 **그대로**(F1: 상태 26·클립 4·그리기 14) — 사각형·z 만 경우 표에서
  3. 꼬리: `PURGE_CACHE`·`PURGE_ZCACHE`·`WAIT_UNTIL_IDLE`(F6) → **`RB3D_CNTL` 복원**(D1)
  그다음 MMIO 로 `DSTCACHE` RMW 비우기·BUSY 대기(R4 의 비우기와 같음), 그리고 판정 읽기.
- 경우 표: A = 사각형 (5,3)–(37,21), z = 1.0(→ 0xffffff, 반올림 무관); B = 같은 사각형, z = 0.5(24 비트 변환 규칙을 **기록**: 0x7fffff 또는 0x800000).

### 2-2. 판정 (python 오라클 `tools/r6/zclear_oracle.py`, 판정기 `tools/r6/check_r6a.py`)
- 깊이 버퍼 4096 워드 전부: 사각형 픽셀(x 5..36, y 3..20 — 가위가 끝 포함 `(x2-1,y2-1)` 이므로 [x1,x2)×[y1,y2))의 **`r200_mba_z32` 주소**는 비트 23:0 = 기대 깊이,
  나머지 워드는 패턴 그대로.  비트 31:24(스텐실)는 **기록**(선례의 `STENCILREFMASK=0` 이 쓰기 마스크 0 인지 참고로 확정 못 함).
- 판정기는 **타일 가설과 선형 가설을 둘 다 계산**해 어느 쪽과 맞는지 말한다(F12) — 타일이 맞아야 PASS, 선형이 맞으면 FAIL 과 함께 사실로 기록.
- 희생 색 버퍼 4096 워드 전부 패턴 그대로(`PLANEMASK=0`).  그 밖 창 범위(별칭 256 KiB 의 나머지)도 전부 패턴 그대로.
- 되읽기 두 번(F8 의 낡은 읽기 캐시 대비) — 두 번이 다르면 FAIL 이 아니라 **기록**, 둘째 값으로 판정.

### 2-3. 안전
- GPU 쓰기 대상은 VRAM 두 버퍼뿐: 깊이는 가위(사각형) 안, 색은 평면 마스크 0.  두 버퍼 모두 R4 창 안·별칭 안, 드라이버가 주소를 계산하고 **게이트가 창 안인지 검사**.
- 시스템 메모리 쓰기 경로 없음(writeback 둘 다 끔, R5 그대로).  3D 레지스터는 **링으로만**(MMIO 쓰기 0 — 참고와 같음; 예외는 꼬리 뒤 MMIO `DSTCACHE` 비우기, R4 와 같음).
- 걸쇠·대기·STOP 은 R5 규칙 그대로.  ZCLEAR 뒤 CP 는 RUNNING, 이후 R5 STOP 으로 끈다.

### 2-4. 실기 (한 부팅)
RECORD → LOAD → MAP → RESET → START → **REC3D** → ZPREP → **ZCLEAR A** → ZPREP → **ZCLEAR B** → REC3D → STOP → RECORD → cycle.
판정 `check_r6a.py <log>`: 두 경우 모두 워드 전수 대조.

### 2-5. 호스트 검사
시뮬레이터에 R200 깊이 사각형 모형(가위 사각형 × `r200_mba_z32` 주소 × 깊이 값) + 변이(피치 필드 틀림, 가위 끝 포함 규칙 틀림, 타일 대신 선형, 꼬리 비우기 없음,
`RB3D_CNTL` 복원 없음, 전제 상태 누락, 창 밖 오프셋).  오라클은 `r200_clear_oracle.py` 의 워드열을 **재사용**(복제 금지), 새 판정기 자체 시험.

## 3. operator 결정이 필요한 것
- **D1 `RB3D_CNTL`**: 선례는 3D 동안 `0x1902` 를 쓴다.  R4 는 "묶음 맨 앞에서 0 을 씀"(operator 결정)이고 R4 게이트는 0 이 아니면 멈췄다.  R6a 꼬리에서 **0 으로 복원**(R4 결정과 일치, 권장) / 부팅값 `0x1800` 으로 복원 / 복원 안 함.
- **D2 HDP 읽기 버퍼 무효화**(F7): KMS 는 CPU 되읽기 전에 `HOST_PATH_CNTL` 을 건드리지만 R4 규칙은 이 레지스터를 쓰지 않는다.  **쓰지 않고**(권장 — R4 별칭 되읽기가 이미 엔진 쓰기를 봤다) 두 번 읽기로 낡음을 기록 / KMS 대로 씀.

## 4. 교차검토에 물을 것
1. 선례가 기대는 전제 상태(F2)로 충분한가 — Mesa 초기 상태 원자 중 깊이 사각형에 필요한데 빠진 레지스터가 있는가(예: `RE_MISC`, `SE_VAP_CNTL_STATUS`, `SE_VTX_STATE_CNTL`, `PP_CNTL_X`, `RE_SCISSOR_*`).
2. RESET(FreeBSD 엔진 리셋: SE·RE·PP·RB 소프트 리셋) 뒤의 3D 레지스터 값에 기대도 되는가, 아니면 모두 명시해야 하는가(REC3D 가 실측).
3. 깊이 되읽기 판정(타일 공식·가위 끝 포함·24 비트 변환·스텐실 기록)에 빠진 경우.
4. 3D 쓰기가 창 밖·버퍼 밖으로 갈 수 있는 경로(타일 블록 반올림, 피치·높이 정렬).
5. `RB3D_CNTL`·HDP 결정(D1·D2)의 위험.

## 5. operator 결정 (2026-09-19)
- **D1**: `RB3D_CNTL` 은 R6a 링 꼬리에서 **0 으로 복원**(R4 결정과 같은 값).
- **D2**: `HOST_PATH_CNTL`(HDP 읽기 버퍼 무효화)은 **쓰지 않는다** — 두 번 읽어 낡음을 기록.
- **교차검토**: 내부 agent 로 진행(codex 는 2026-09-19 19:23 까지 한도).

## 6. 계획 검토 판정 (내부 agent; 인용 전부 열어 확인)

### 6-1. 내가 틀린 것
- **F3 의 읽기**: "표면 레지스터로 번역하면 선형" 을 엔진이 선형으로 쓴다는 뜻처럼 적었다 — 표면 레지스터는 **CPU(호스트 조리개) 쪽 보기**를 바꾼다(xf86 `radeon_dri.c` 411–412 행
  "Rely on surface regs to translate the addresses", Mesa `radeon_screen.c` 703–705 행 "ddx has set up a surface reg to cover depth buffer").  그러므로 선형 일치는
  `SURFACE_CNTL` 비트 8(`SURF_TRANSLATION_DIS`, R1 실측 `00000100`, `docs/R1_RESULT.md` 43 행)이 서 있고 어떤 표면도 버퍼를 덮지 않을 때만 하드웨어 사실이다.
- **REC3D 의 "부팅값"**: RUNNING 에서만 부르게 적어 RESET·START 뒤 값만 잡힌다.
- **선례가 자급적이라는 전제**: 정점 앞단(VAP) 레지스터가 빠졌다 — xf86 은 R200 3D 전에 `SE_VAP_CNTL_STATUS`·`PP_CNTL_X`·`PP_TXMULTI_CTL_0`·`SE_VTX_STATE_CNTL` 을 0 으로 쓴다
  (`radeon_commonfuncs.c` 777–792 행 열어 확인).
- PLAN 은 "깊이는 16 비트부터"(PLAN.md R6 5 항)인데 선례는 24 비트다 — R6a 는 선례대로 24 비트, 16 비트는 다음 조각.

### 6-2. 판정
| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| E1 | 래스터 경로의 문(가위 `RE_CNTL` 비트 1, 보조 가위, DEPTHXY 오프셋, 블렌드·ROP·디더·스텐실, 알파·안개, Z 바이어스, 뷰포트)은 선례 값으로 전부 닫힌다 | ✅ | `r200_reg.h` 267–270 행(`SCISSOR_ENABLE 0x2`) 열어 확인; 나머지 비트는 선례 값과 헤더로 코딩 때 python 대조 |
| E2/M1 | 앞단 레지스터 넷을 전제 상태에 추가 | ✅ | 위 xf86 행 |
| E3/M2 | 이 카드의 부팅 `RB3D_COLOROFFSET=e65de360`(VRAM·GART 밖), `DEPTHOFFSET=0`(보이는 화면) — 전제 쓰기가 사라지면 거기로 간다 → **전제 상태만 먼저 제출·유휴·MMIO 되읽기 일치해야 그린다** | ✅ | R5 로그 rec4 `coloff=e65de360 depthoff=00000000`(이 세션의 여러 RECORD 에서 읽음) |
| E4/M5 | `SURFACE_CNTL == 0x100` 게이트, REC3D 가 `SURFACE0..7`(0x0b04–0x0b7c) 기록 | ✅ | R1 43 행 |
| E5/m4 | z=1.0→0xffffff 는 Mesa 의 `d*0xffffff` 절삭과 일치(`r200_state.c` 379–391 행); B 는 사각형 전 워드가 같고 {0x7fffff, 0x800000} 중 하나여야, 어느 쪽인지 기록; **스텐실 바이트는 불변으로 판정**(쓰기 마스크 = `STENCILREFMASK` 31:24, `r200_reg.h` 303–309 행, 값 0) | ✅ | 위 행들 열어 확인 |
| M3 | 버퍼 배치를 카드 주소 4 KiB 정렬로, R4 블록(S0·S1·S2·D)과 안 겹치게 | ✅ | python: 빈 구간 [0,16K)·[80K,96K)·[160K,176K)·[208K,224K)·[240K,256K) — 깊이 = 창+0, 색 = 창+0x3c000 |
| M4 | 버퍼 밖 불변 판정은 256 KiB 전체를 패턴으로 채워야(R4 FILL 과 같이) | ✅ | — |
| M6 | 경우 C: 기하가 가위보다 큼(기하 (0,0)–(64,32), 가위 (5,3)–(37,21)) — 가위가 실제로 자르는지 증명(안전 주장과 이후 검증기의 전제) | ✅ | 버퍼 안이라 가위가 안 먹어도 안전 |
| E9/m5 | 꼬리 뒤 MMIO 비우기의 근거는 R4 가 아니라 참고의 `radeon_do_cp_idle` → `pixcache_flush`(CP 켜진 채 MMIO RMW) | ✅ | FreeBSD `radeon_cp.c` 551–563 행(이 세션 열람) |
| E10 | 별칭은 엔진 키가 있어야 — 표에 `"RDN Engine Test" = "Yes"` 이미 있음 | ✅ | `OSRDNDisplay.m` 558–580 행, `Default.table` 19 행 |
| m1 | 스크래치 표지(REG0 앞, REG2 는 `WAIT_UNTIL_IDLE` 뒤)·씨앗 규칙 | ✅ | R5 규칙 |
| m2 | REC3D 는 RUNNING 무관(RESET 전에도), FIFO 64·ACTIVE 0 먼저 | ✅ | — |
| m3 | REC3D 에 0x26c0, 0x1cd8–0x1cec, 0x1d60, `PP_TXMULTI_CTL_0`, 0x3250/0x3258, 표면 레지스터 추가 | ✅ | — |
| m7 | R6a 뒤 COLOROFFSET·DEPTHOFFSET 은 부팅값이 아니다 → 다음 warm reboot 뒤 값 기록 | ✅ | — |
| m8 | 호스트 검사: 링 레지스터 허용 목록, MMIO 계수, 역어셈블 게이트(`HOST_PATH_CNTL`·`SURFACE_*`·`RBBM_SOFT_RESET` 쓰기 0), 패턴과 기대값 충돌, 표면 비트 변이, IMMD_2 워드 수 대 `SE_VTX_FMT_0`, 낡은 로그 | ✅ | — |
| D2 | 같은 경로로 두 번 읽어도 낡은 버퍼는 새로워지지 않는다 — FAIL 때만 Mesa 식 "첫 워드 읽고 다시 쓰기" | ⚖️ | 두 번 읽기는 기록으로 남기고, 실패 진단 절차에 Mesa 식을 적는다 |

## 7. 개정 명세 (6 반영 — 2 절과 충돌하면 이 절이 이긴다)
- 키: `"RDN 3D Test"`(새) + `"RDN CP Test"` + `"RDN Engine Test"`(별칭).  게이트: CP RUNNING·걸쇠 아님·엔진 걸쇠 아님·`SURFACE_CNTL == 0x100`.
- 배치(카드 주소, 4 KiB 정렬): 깊이 = `winStart + 0`(64×64×4 = 16 KiB, 피치 64 px), 색 = `winStart + 0x3c000`(16 KiB, 피치 64 px).  게이트: 둘 다 창·별칭 안.
- **REC3D**(RUNNING 불필요, FIFO 64·ACTIVE 0 먼저): 1 절 목록 + m3 추가분 + `SURFACE_CNTL`·`SURFACE0..7`.
- **ZPREP**: 별칭 256 KiB 전체를 위치 부호 패턴으로 채우고 되읽어 확인.  패턴의 하위 24 비트는 0xffffff·0x7fffff·0x800000 과 결코 같지 않다(python 검사).
- **ZCLEAR**(경우 A·B·C): 링 두 번 —
  (1) 전제 상태: `SE_TCL_STATE_FLUSH=0`(참고의 상태 패킷 경로에서 온 **추가**), 앞단 넷 = 0, DEPTHOFFSET·DEPTHPITCH·COLOROFFSET·COLORPITCH, 스크래치 REG0 표지 → 따라잡기·유휴 →
      **MMIO 로 전제 레지스터 되읽기 전부 일치해야** 다음 단계(아니면 그리지 않고 거절 — CP 는 건강, 걸쇠 없음);
  (2) 선례 워드열 그대로(경우별 사각형·z·기하) → 꼬리 `PURGE_CACHE`·`PURGE_ZCACHE`·`WAIT_UNTIL_IDLE` → `RB3D_CNTL=0`(D1) → 스크래치 REG2 표지 → 따라잡기·유휴 →
      MMIO `DSTCACHE` RMW 비우기·BUSY 대기(참고 `pixcache_flush`) → 표지 되읽기.  링 감김을 가로지르지 않게 채움.
- 경우: A 사각형 (5,3)–(37,21) z 1.0; B 같은 사각형 z 0.5; C 기하 (0,0)–(64,32)·가위 (5,3)–(37,21) z 1.0.  경우마다 앞에 ZPREP.
- 판정: 깊이 버퍼 워드 전부(가위 사각형의 `r200_mba_z32` 주소 = 기대 깊이 23:0·스텐실 31:24 불변, 나머지 = 패턴), 색 버퍼·블록 나머지 전부 패턴, 타일/선형 두 가설 보고,
  B 는 사각형 전 워드 같고 {0x7fffff, 0x800000}; 되읽기 두 번은 기록.
- 실기: RECORD → **REC3D** → LOAD → MAP → RESET → START → REC3D → (ZPREP → ZCLEAR) × A·B·C → REC3D → STOP → RECORD → cycle.  다음 부팅 첫 RECORD·REC3D 로 m7.
- 호스트 검사: m8 전부 + 시뮬레이터의 R200 깊이 사각형 모형(가위·타일 주소·깊이 변환·스텐실 마스크·전제 레지스터 되읽기) + 변이.

## 8. 구현과 실기 전 코드 검토 (2026-09-19)

### 8-1. 만든 것
`osrdn_cp.m` R6a 절(REC3D·ZPREP·ZCLEAR, 링으로만 3D 레지스터, 부동소수 없음 — 정점 워드는 오라클이 계산한 IEEE 비트 상수), `tools/r6/zclear_oracle.py`
(선례 워드열은 `r200_clear_oracle.py` 재사용), 시뮬레이터 `world5.c` 의 가짜 3D(`3D_DRAW_IMMD_2` 해석·가위·Mesa 타일 주소) + `tools/r6/sim_r6.py`(CP 가 실행한 워드 순서와
드라이버 요약값을 오라클과 대조, 변이 15 — 링 끝 가로지름 변이는 처음 빠져나가 근처 경우를 추가), 실기 판정기 `tools/r6/check_r6a.py`(자체 시험 변이 10), 소스 규칙 정밀화
(`r5-forbidden` 을 이름이 아닌 **쓰기**로 — MMIO·링 둘 다, `r6-ring` 허용 목록) + 변이 5, reloc 호출자 표.

### 8-2. 코드 검토 판정 (내부 agent; 인용 열어 확인)
| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| M1 | `RB3D_DEPTHXY_OFFSET`(0x1d60)을 쓰지도 게이트하지도 않는다 | ⚖️ 부분 채택 | 선례 `RB3D_CNTL=0x1902` 의 켜진 비트 {1,8,11,12} — `DEPTH_XZ_OFFEST_ENABLE` 은 비트 9(`r200_reg.h` 195 행)로 **꺼져 있어** 오프셋은 쓰이지 않을 것(python).  그래도 Mesa 가 초기값 0 을 쓴다(`r200_state_init.c` 697 행) → **전제 상태에 0 을 쓰고 되읽기 게이트에 넣는다**(비용 없음) |
| M2 | 커널 스택: `setIntValues` 프레임이 이미 812 B(직전 빌드 `sub $0x32c,%esp` — python 으로 reloc 바이트 검색, 오프셋 0x13af), CP 상태가 1020 B 로 커져 ~1.3 KiB, 커널 스택은 4 KiB(`vm_param.h` 47 행 `KERNSTACK_SIZE 1*I386_PGBYTES`) | ✅ | 위 실측.  **`cpCopy`·`engCopy` 를 파일 정적 저장소로**(클레임이 연산을 직렬화, 경쟁은 로그만 흐림); 새 빌드에서 프레임 재측정 |
| m1 | 앞단 네 레지스터를 정확히 0 으로 게이트하면 읽기 전용 비트 하나가 부팅을 버린다 | ✅ | 게이트는 주소에 영향 주는 다섯(깊이·색 오프셋·피치, DEPTHXY)만; 네 개는 기록 |
| m2 | 판정기가 D1(`RB3D_CNTL`=0 복원)을 실기에서 보지 않는다 | ✅ | 마지막 REC3D 의 0x1c3c = 0 판정 |
| m3 | 판정기의 별칭 줄 정규식이 "ok" 를 요구하지 않는다 | ✅ | — |
| m4 | `CP_R6_ALIAS_BYTES` 가 `ENG_ALIAS_BYTES` 와 묶이지 않았다 | ✅ | 컴파일 시간 검사(`OSRDNDisplay.m`, 음수 배열) |
| m5 | `zprepped` 가 R4 엔진 연산을 건너 남는다 | ✅ | ZPREP 은 CP RUNNING 에서만(그동안 엔진 연산은 거절) |
| m6 | REC3D 가 LOAD 전에 SE/RE/PP 레지스터를 MMIO 로 읽는다(처음) | 기록 | 계획 m2 가 요구한 부팅값 기록; begin 줄이 클레임 전에 찍혀 행이면 위치가 남는다 |
| m7–m9 | 시뮬레이터 비교 범위(PACKET0 헤더 비트 13–15 는 `C_P0` 이 만들지 않음), 판정은 워드가 아니라 요약값(위치 가중), GART 페이지 가로지름은 이번 절차에 없음 | 기록 | — |
| 타이밍 | ZCLEAR ≈ 100 ms, ZPREP ≈ 50 ms(R4 FILL 실측 비례) — 소리 재생 중에는 돌리지 말 것 | 기록 | — |

### 8-3. 빌드 (2026-09-19)
전체 검사 PASS(검토 반영 뒤), stamp `30a9a1b7`, runid 789753594, reloc 게이트 PASS, `nm -u` 는 R5 STOP 수정 빌드와 동일(20).
스택 프레임 재측정(python, reloc 의 `sub $imm32,%esp`): 812 B 프레임(`setIntValues`) 사라짐, 최대 572 B(이전부터 있던 것), 새 228 B(ZCLEAR 의 워드 배열).
**설치됨**(두 표에 `"RDN 3D Test"`·`"RDN Engine Test"`).  재부팅 대기.  실기 절차 7 절, 판정 `tools/r6/check_r6a.py <log> --boot N --build 30a9a1b7`.

## 9. 실기 (2026-09-19, 부팅 e3ec4d0c, build 30a9a1b7) — 첫 3D 동작, 가위 가설 하나 반박

로그 `build/r6/boot-e3ec4d0c.full.log`, `check_r6a.py` → **FAIL 1(경우 C, 아래)**, 나머지 전 항목 통과.  모든 연산 rc 0, 걸쇠 없음, STOP 깨끗, 순환 verdict 0.
- **REC3D(부팅값, 처음 읽음, 행 없음)**: `SURFACE_CNTL=00000100`, 표면 8 개 모두 INFO 0(UPPER 0x7ff) — 표면 번역 없음.  정점 앞단 부팅값은 제각각:
  `SE_VAP_CNTL=00420011`(TCL 켬 비트 포함), `SE_VTX_FMT_0=81388ee8`, `SE_VTX_STATE_CNTL=0006a5af`, `SE_VTE_CNTL=0000041c` — 전제 상태를 명시해야 한다는 검토 판단을 실측이 뒷받침.
  `RB3D_COLOROFFSET=e65de360`, `DEPTHXY_OFFSET=0`, `RB3D_CNTL=00001800`.  RESET·START 뒤 REC3D 와 **차이 없음**(소프트 리셋이 이 레지스터들을 바꾸지 않는다).
- 전제 상태 되읽기 9 개 전부 일치(`prebad=00`), 표지 둘 도착, 색 버퍼·블록 나머지 불변(세 경우 모두), 두 번 읽기 동일.
- **경우 A(z 1.0)**: 576 워드 = `a5ffffff`, 요약값이 **Mesa 타일 배치와 일치**(python: tiled `726dc460` MATCH, linear `fb3760a0` 불일치) — 깊이 타일링이 켜져 있다는 Mesa 주석을 실측으로 확인.
- **경우 B(z 0.5)**: `a5800000` — **하드웨어는 z → 24 비트를 반올림**(0x800000)한다; Mesa 의 CPU 쪽 절삭(0x7fffff)과 다르다.  스텐실 바이트(a5)는 그대로.
- **경우 C(기하 (0,0)–(64,32), 가위 (5,3)–(37,21))**: 777 워드 — 요약값 다섯이 **[0,37)×[0,21)** 과 정확히 일치(python, 7 가설 중 유일).
  즉 **`RE_WIDTH_HEIGHT`(끝, 포함)는 적용되고 `RE_TOP_LEFT` 는 적용되지 않았다**.  쓰기는 원점 쪽으로만 넓어졌고 버퍼 안(색·나머지 불변) — 안전 문제 없음.
  함의: 이후 검증기는 왼쪽 위 가위에 기대면 안 된다(기하를 직접 제한하거나 `RE_CNTL` 의 `SCISSOR_ENABLE`+`RE_SCISSOR_TL/BR` 경로를 따로 조사).
- 첫 예상 밖 결과에서 그리기를 멈추고 정리(REC3D·STOP·RECORD·순환)만 했다.

남은 것(다음 계획): `RE_TOP_LEFT` 가 왜 무시됐는지 참고로 조사(R200 에서 이 레지스터의 뜻, xf86 R200 은 WIDTH_HEIGHT 만 씀) → 가위 경로 결정; 이후 PLAN 사다리(평면색 삼각형 등).

### 9-1. 뒤이은 결과 (2026-09-19)
R6b(`docs/R6B_PLAN.md` 7, 부팅 feca1cba)가 가설 H 를 확인했다: `RE_TOP_LEFT` 는 `R200_RE_CNTL.SCISSOR_ENABLE` 일 때만 자른다.  위 경우 C 의 FAIL 은 R6a 계획의 규칙
("TL 은 늘 자른다")이 틀렸기 때문이고, 그 규칙은 반박된 채로 여기 남긴다.
