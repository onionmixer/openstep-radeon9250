# R4 — 2D 엔진과 VRAM 매핑 (계획, 코딩 전, 교차검토 대상, 2026-09-18)

`PLAN.md` R4 의 구체화.  V 단계는 operator 결정으로 줄었다(`PLAN.md` V 절 끝: VRAM 128 MiB 가정,
탑재량 실측 안 함, 할당·소유는 이 계획에 합침).

## 0. 한 줄 요약

화면 밖 VRAM 에서 2D 엔진으로 **채우기(R4a)** 와 **블릿(R4b, 겹침 네 방향 포함)** 을 하고, 그 결과를
커널이 **uncached 별칭**으로 되읽어 산술 기대값과 픽셀 전수 대조한다.  그다음 **R4c** 로 화면 밖
VRAM 을 문자 디바이스 `d_mmap` 으로 유저 태스크에 내놓는다.  엔진은 **MMIO 로만**(CP 없음) 쓰고,
모든 대기는 상한이 있으며, 엔진을 **리셋하지 않는다**.

## 1. 확인한 사실 (원문을 열어 확인, 2026-09-18)

### 1-1. 레지스터 (헤더 두세 개가 같은 값)

`RBBM_STATUS` 0x0e40 — `FIFOCNT` 비트 6:0(빈 칸 수, 64 칸), `RBBM_ACTIVE` 비트 31.
`DP_GUI_MASTER_CNTL` 0x146c — `SRC_PITCH_OFFSET_CNTL` 비트 0, `DST_PITCH_OFFSET_CNTL` 비트 1,
브러시 7:4(`SOLID_COLOR` 13, `NONE` 15), 목적지 데이터형 11:8(CI8 2, 15bpp 3, 16bpp 4, 32bpp 6),
`SRC_DATATYPE_COLOR` 3<<12, ROP3 23:16(`ROP3_P` 0xf0, `ROP3_S` 0xcc), `DP_SRC_SOURCE_MEMORY` 2<<24,
`CLR_CMP_CNTL_DIS` 비트 28.  `DP_CNTL` 0x16c0 — `DST_X_LEFT_TO_RIGHT` 비트 0, `DST_Y_TOP_TO_BOTTOM` 비트 1.
`DST_PITCH_OFFSET` 0x142c, `SRC_PITCH_OFFSET` 0x1428, `DEFAULT_OFFSET`(=`DEFAULT_PITCH_OFFSET`) 0x16e0.
`DP_WRITE_MASK` 0x16cc, `DP_BRUSH_FRGD_CLR` 0x147c, `DST_Y_X` 0x1438, `SRC_Y_X` 0x1434,
`DST_WIDTH_HEIGHT` 0x1598(`w<<16|h`, **마지막 쓰기가 실행**), `DEFAULT_SC_BOTTOM_RIGHT` 0x16e8,
`SC_TOP_LEFT` 0x16ec.  dest cache: `RB2D_DSTCACHE_CTLSTAT` 0x342c, `RB3D_DSTCACHE_CTLSTAT` 0x325c —
둘 다 `FLUSH_ALL` 0xf, `BUSY` 비트 31.
(NetBSD `radeonfbreg.h`·xf86 `radeon_reg.h`·FreeBSD `radeon_drv.h` 를 grep 해 한 표로 대조 — 이 절의 모든 값.)

### 1-2. 피치·오프셋 인코딩

`(pitch_bytes / 64) << 22 | (카드주소 >> 10)` — 오프셋은 **1 KiB 단위의 카드(MC) 주소**, 피치는 64 바이트
단위(`radeon_cp.c:1315-1317`, xf86 `radeon_exa.c:160-161`).  NetBSD 는 오프셋 자리에 애퍼처 주소를 넣고
원저자가 "우연히 동작한다" 고 적는다(`radeonfb.c:3874-3882`) — 우리 `MC_FB_LOCATION` 은 `1fff0000`(FB 가
카드 주소 0, R1) 이라 **카드 주소 = VRAM 오프셋**이다.  오프셋 필드 22 비트 × 1 KiB = 4 GiB 도달.
피치는 64 바이트 배수여야 한다 — **우리 시험 표면은 우리가 고르므로**(1024 바이트) 문제없다.  화면
모드 중 800×600 8bpp(800 바이트)는 64 배수가 아니지만 R4 는 **보이는 화면을 엔진으로 건드리지 않는다**.

### 1-3. dest cache flush — 참고 구현이 갈린다

| 참고 | RV280 에서 flush 하는 것 | 대기 |
|---|---|---|
| NetBSD `radeonfb_engine_flush` | `RB2D_DSTCACHE_CTLSTAT`(0x342c) | **상한 없음**(`radeonfb.c:3784-3805`) |
| xf86 `RADEONEngineFlush` | `RB3D_DSTCACHE_CTLSTAT`(0x325c), `ChipFamily <= RV280` | 상한 있음, 넘으면 로그만(`radeon_accel.c:183-195`) |
| FreeBSD `radeon_do_pixcache_flush` | 0x325c, `<= CHIP_RV280` | 상한, `-EBUSY`(`radeon_cp.c:315-330`) |

모든 참고가 **유휴 뒤, CPU 가 VRAM 을 읽기 전** 에 dest cache 를 flush 한다.  → **둘 다** flush 하고
각각 상한 있는 대기, 어느 것이 실제로 BUSY 를 보였는지 기록한다(실기가 답한다).

### 1-4. 대기와 리셋 — 참고의 것은 그대로 쓸 수 없다

- FIFO·유휴 대기: NetBSD 는 FIFO 대기를 넘기면 **조용히 반환**, 유휴·flush 는 **무한 루프**.  xf86 는
  넘기면 리셋+복원 후 **영원히 재시도**.  (ANALYSIS.md 8 절, 이번에 재확인.)
- 소프트 리셋: 참고마다 비트 집합(`SOFT_RESET_HI` 유무)·MCLK 강제·HDP 리셋 여부가 다르고, NetBSD 는 리셋
  **앞에서** 무한 flush 를 돈다.  Matrox 는 소프트 리셋 뒤 VRAM 읽기가 어긋났고 **복구 수단은 재부팅뿐**이었다
  (`openstep-matrox-remade/docs/REMAINING_WORK.md`, W11).  → **R4 는 엔진을 리셋하지 않는다.**

### 1-5. Matrox 선례에서 옮기는 것 (원문 확인)

| 사실 | 근거 | R4 에서 |
|---|---|---|
| 엔진이 쓴 VRAM 을 CPU 가 읽을 때 `mapFrameBuffer` 매핑의 캐시 속성은 증명된 적 없다 → 시험 블록만 **`IOMapPhysicalIntoIOTask` 로 만든 uncached 별칭**으로 기록·되읽기 | Matrox `S1_STORM_ENGINE_LIVENESS_PLAN.md` 3-1 | 그대로 |
| FIFO 빈 칸보다 많이 쓰면 버스가 멈춘다(하드 프리즈) | Matrox `REMAINING_WORK.md` | 쓰기 묶음마다 빈 칸 ≥ n 확인 |
| 실행(EXEC) 뒤 대기가 넘치면 **소프트웨어 폴백 금지**(늦은 엔진 쓰기가 덮는다) → 영구 실패 걸쇠, 복구 시도 없음 | Matrox S3 | 그대로 |
| `d_mmap` 은 페이지당 **최소 두 번** 불리고 두 번째 호출의 `-1` 은 검사되지 않아 물리 `0xFFFFF000` 이 된다 → 판정은 **등록 수명 동안 불변인 상태만 쓰는 순수 산술** | Matrox `S4A_VRAM_MMAP_PLAN.md` 1-3(실기 `mach_kernel` IDA) | 그대로 |
| VM 페이지 **8 KiB**(`PAGE_SIZE=8192`) | 같은 문서 10-1(실측) | 커널 전역 `page_size` 로 |
| `mmap` 은 4.2BSD 판: `MAP_FIXED` 없음, 주소를 `vm_allocate` 로 먼저 잡고, 성공 반환은 **0** | 같은 문서 10-2(실측) | 시험 도구에 그대로 |
| 매핑은 `close()`·등록 해제보다 오래 산다 → 매핑이 켜지면 **언로드 금지** | 같은 문서 7-2 | 그대로(디스플레이 드라이버는 부팅 적재라 언로드 경로도 없다) |
| **open/close 로는 단일 클라이언트 임대를 강제할 수 없다**: `d_close` 는 클라이언트마다가 아니라 **마지막 참조가 사라질 때 한 번** 온다(실측 "open 163, open 164, close 89"), fd 배타성은 매핑 배타성이 아니다 | Matrox `REMAINING_WORK.md` 3-35 | **6 절 — operator 결정 필요** |

## 2. VRAM 구간 (python 계산, 128 MiB 가정)

| 구간 | 카드 주소 | 크기 | 용도 |
|---|---|---:|---|
| 보이는 화면 | `[0x00000000, 0x00800000)` | 8 MiB | 매핑 길이 `OSRDN_FB_LENGTH`.  가장 큰 모드 1600×1200×4 = 7 680 000 B |
| 드라이버 전용 | `[0x00800000, 0x01000000)` | 8 MiB | R4a/R4b 시험 표면, 이후 드라이버 소유 객체 |
| 유저 창(R4c) | `[0x01000000, 0x08000000)` | 112 MiB | 14 336 페이지(8 KiB), 첫 PFN 오프셋 2048 |

세 구간은 겹치지 않고 합이 128 MiB, 경계가 모두 8 KiB·1 KiB 정렬(python 단언).  R5 의 링·GART 표는
계획상 **시스템 메모리**(`PLAN.md` R5b 기본안)라 이 표와 겹치지 않는다 — VRAM 에 두기로 바뀌면 이 표를
다시 연다.  엔진 좌표는 13 비트(8191, 9-1 E7) 한계가 있으므로 **표면 기준을 `*_PITCH_OFFSET` 으로 옮기고 y 는 작게**
쓴다(1024 바이트 피치로 8191 행은 8 MiB — 시험 표면은 수백 행).

## 3. 설계

### 3-1. 호출 통로

R2c 순환과 같은 모양: `setIntValues` 매개변수 **`RDNR4Engine`**, 첫 낱말은 매직, 둘째는 연산 코드.
`"RDN R2B0 Record" = "Yes"` 일 때만, 그리고 **모드 클레임**(`modeClaim`) 을 잡은 채로 — 진입·복귀·전달표
적용과 겹치지 않는다.  클레임을 못 잡으면 기다리지 않고 `IO_R_BUSY`.  결과는 IOLog 줄(부팅 nonce 포함)과
반환 코드; 호스트 판정기가 로그를 판정한다(`check_select.py` 와 같은 방식).  유저 도구는 `rdnr2b0` 에
연산을 더한다.

| 연산 | 하는 일 | 엔진 쓰기 |
|---|---|---|
| `RECORD` | 엔진 레지스터 읽기만(`RBBM_STATUS`, `CP_CSQ_CNTL`, 두 dest cache, `RB2D_DSTCACHE_MODE`, `DEFAULT_OFFSET`, `DEFAULT_SC_BOTTOM_RIGHT`, `DP_DATATYPE`, `SURFACE_CNTL`, `RB3D_CNTL`) | 없음 |
| `FILL` | R4a | 있음 |
| `BLIT` | R4b | 있음 |

**한 부팅 안에서 단계적으로**: `RECORD` → 호스트에서 값 검토 → `FILL` → 판정 → `BLIT`.  엔진 연산은 각각
따로 불리므로 앞 단계가 이상하면 뒤를 부르지 않는다.  (빌드마다 재부팅이 들지만 단계마다는 들지 않는다.)

### 3-2. 엔진 사용 전 게이트 (하나라도 다르면 쓰기 0 회로 거절)

`RBBM_ACTIVE` = 0, `FIFOCNT` = 64, `CP_CSQ_CNTL >> 28` = 0(CP 꺼짐 — R2 `cpmode` 게이트와 같은 조건),
두 dest cache `BUSY` = 0, `SURFACE_CNTL` 스왑 비트 0(R2 `surface` 게이트), 영구 실패 걸쇠 없음,
모드가 들어가 있음(`modeWritten`).  **`SURFACE_CNTL`·`RB3D_CNTL`·`RBBM_SOFT_RESET`·`HOST_PATH_CNTL` 은 쓰지 않는다**
(참고 초기화의 앞 절반 — 살아 있는 화면의 CPU 경로를 바꾸거나 리셋이다).

### 3-3. 연산마다 전체 상태를 쓴다

초기화에 기대지 않는다(Matrox 3-64: 다음 사용자는 클립까지 전부 다시 써야 한다).  한 연산의 쓰기:
`DST_PITCH_OFFSET`, (블릿이면) `SRC_PITCH_OFFSET`, `DEFAULT_SC_BOTTOM_RIGHT = 0x1fff1fff`,
`DP_GUI_MASTER_CNTL`(`*_PITCH_OFFSET_CNTL` 을 **세워** 기본 피치 레지스터에 기대지 않는다 — 참고가 셋을 같게
써서 어느 것을 읽는지 가리지 못한다), `DP_WRITE_MASK = ffffffff`, 채우기면 `DP_BRUSH_FRGD_CLR`, `DP_CNTL`,
블릿이면 `SRC_Y_X`, `DST_Y_X`, 마지막에 `DST_WIDTH_HEIGHT`.  최대 9 칸 — 한 번의 FIFO 확인(≥ 9)으로 쓴다.
데이터형은 **시험 표면의 것**(32bpp, 6) — 화면 모드와 무관하다.  클리핑 비트는 세우지 않는다.

### 3-4. 대기 (모두 상한, 넘기면 영구 실패 걸쇠)

- FIFO: 쓰기 묶음 **앞에서** 빈 칸 ≥ n 이 될 때까지, 상한.  넘기면 **실행 전이므로** 아무것도 쓰지 않고 반환.
- 유휴: 실행 뒤 `RBBM_ACTIVE` = 0, 상한.  → dest cache 두 개 flush, 각각 `BUSY` = 0 까지 상한.
- 상한은 R2 의 대기와 같은 방식(`IODelay` 단위 판정 횟수, 한도는 명목 2 배 — `MODE_TURN_FACTOR`,
  이 기계의 `IODelay` 는 명목의 약 0.94 배, `docs/R2_CLOSEOUT.md`)이고 판정 횟수·소요를 로그한다.
- **실행 뒤 넘치면**: 걸쇠(이 부팅 엔진 영구 금지), 정리 쓰기 없음, 소프트웨어 폴백 없음, 리셋 없음.

### 3-5. 되읽기

드라이버 전용 구간의 시험 블록(최대 256 KiB)만 `IOMapPhysicalIntoIOTask(bar0 + 8 MiB, len)` 로 **uncached 별칭**
을 만들고(첫 엔진 연산 때 한 번, 해제하지 않음), 표지 쓰기·원본 패턴 쓰기·되읽기를 전부 이 포인터로 한다.
`mapFrameBuffer` 매핑은 쓰지 않는다.

### 3-6. R4a 채우기

256×64 32bpp 표면(피치 1024) — 먼저 CPU 가 표지 `0x5A5A5A5A` 를 전체에 쓰고 되읽어 확인(거짓 PASS 차단),
그다음 가운데 사각형 `(x=16, y=8, w=200, h=40)` 을 색 `0xDEADBEEF` 로 채운다.  판정: 사각형 안 **전부** 색,
사각형 밖 **전부** 표지(넘침 없음), 불일치 수·첫 불일치 좌표·체크섬 로그.  색을 바꿔 두 번(`0xDEADBEEF`, `0x00000000`).

### 3-7. R4b 블릿

위치 인코딩 패턴 `px(y, x) = 0xFF000000 | (y << 8) | x`(Matrox S2) 를 CPU 가 256×256 표면에 쓰고 되읽어 확인.
- 서로 다른 표면(겹침 없음) 복사 1 건.
- **같은 표면 안 겹치는 복사 4 건**: (dx, dy) = (+8,+8), (−8,−8), (+8,−8), (−8,+8).  방향은 NetBSD 규칙
  (`dsty < srcy` 면 위→아래, 아니면 시작점을 `h−1` 로 옮기고 아래→위; x 도 같게, `radeonfb.c:3703-3732`).
  각 경우 전에 패턴을 다시 쓴다.
판정: 목적지 사각형은 **원본의 복사 전 값**, 그 밖은 패턴 그대로 — 기대값은 커널이 산술로 만든다.
방향을 틀리면 겹친 부분이 이미 덮인 값을 복사해 불일치가 난다(그래서 겹침 경우가 판정력이 있다).

### 3-8. R4c 문자 디바이스 (R4a/R4b 가 실기 PASS 한 뒤, 별도 빌드)

- 켜는 키 `"RDN VRAM Mmap" = "Yes"`(기본 꺼짐).  `addToCdevswFromDescription:…mmap:` 로 **자동 major**(-1),
  유저는 `IOCharacterMajor` 로 읽는다.  `mknod` 는 root 가 0600 으로.
- `d_mmap(dev, off, prot)`: minor 0, `prot == PROT_READ|PROT_WRITE` 정확히, `off` 는 페이지 정렬·음수 아님,
  `off <= 창길이 − page_size`(넘침 없는 형태), PFN = `(bar0 + 16 MiB + off) >> page_shift`.  **등록 수명 동안
  불변인 값만** 쓰는 순수 산술 — 할당·수면·로그·잠금 없음.
- 창 `[16 MiB, 128 MiB)` 는 **고정**(부팅 중 바뀌지 않음 — 모드는 부팅당 하나).
- 시험 도구(`rdnr4map`): `vm_allocate` → `mmap` → 창 처음·끝 페이지에 쓰고 읽기, 경계 밖(끝 다음 페이지·
  비정렬·RO/EXEC) 거절 확인, 그리고 **엔진 채우기(R4a 경로, 목적지를 유저 창 안으로) 뒤 유저가 읽어 같은 값** —
  CPU 도달(창 끝 = 128 MiB 직전)과 캐시 일관성을 한 번에 본다.

## 4. 검사 (호스트, 코딩 단계 — 기준 PASS 와 변이 FAIL 을 같은 실행에서)

1. **엔진 오라클** `tools/r4/engine_oracle.py`: 레지스터 값(피치·오프셋·GMC·DP_CNTL·트리거)을 사실표에서 독립
   계산, 생성 헤더와 대조(R2/R3 의 생성기 방식).
2. **가짜 엔진 시뮬레이터**(`simworld2b.c` 확장): FIFO 빈 칸 계수, `DST_WIDTH_HEIGHT` 쓰기 때 가짜 VRAM 에
   채우기/블릿을 **하드웨어 규칙대로** 실행(방향 비트를 따르는 순서 복사 — 틀린 방향이면 겹침에서 결과가
   달라진다), `RBBM_ACTIVE`·cache `BUSY` 를 설정 가능한 시간만큼 유지.  변이: 방향 규칙 뒤집기, FIFO 확인
   빼기(빈 칸보다 많이 쓰면 시뮬레이터가 실패로 기록), 상한 없는 대기, 실행 뒤 넘침에서 폴백, 게이트 하나씩
   빼기, `*_PITCH_OFFSET_CNTL` 안 세우기(시뮬레이터는 기본 피치 레지스터를 다른 값으로 둔다).
3. **`d_mmap` 산술 시험**: 창 경계 전수(0, 끝 페이지, 끝, 끝+1 페이지, 비정렬, 음수, 거대 오프셋, prot 조합),
   같은 입력 두 번 같은 답(결정성), 넘침 없는 비교 형태 — 32 비트로 컴파일해 실행.
4. **레지스터 표**: `tools/oracle/regtable.py` 에 새 레지스터(0x342c, 0x325c, 0x16c0, 0x16cc, 0x147c, 0x1438,
   0x1434, 0x1598, 0x16e0, 0x16e8, 0x3428)를 더해 세 헤더 대조.
5. **로그 판정기** `tools/r4/check_engine.py`: 연산별 줄, 불일치 0, 대기 판정 횟수 > 0 이고 한도 미만, 게이트 값.
6. **역어셈블 게이트**: 엔진 레지스터 쓰기 호출자가 엔진 단위뿐, `SURFACE_CNTL`·`RBBM_SOFT_RESET`·
   `HOST_PATH_CNTL` 쓰기 0 회.

## 5. 실기 절차

1. 빌드(R4a+R4b) → 설치(`closed=yes fresh live`) → **operator 재부팅**.
2. 부팅 판정(`check_select` — R3 동작이 그대로인가).
3. `RECORD` → 값 검토(특히 `DEFAULT_SC_BOTTOM_RIGHT`·`RB2D_DSTCACHE_MODE`·dest cache 상태).
4. `FILL` → 판정.  PASS 면 `BLIT` → 판정.  각 단계 뒤 telnet 생존·화면 이상 없음(operator).
5. R4c 빌드 → 재부팅 → 시험 도구.
시작 전 `tools/nx-logcatch.sh start`(하드 프리즈 때 로그 보존 — Matrox 규칙).

## 6. operator 결정이 필요한 것

**`PLAN.md` R4 게이트의 "임대가 없는 태스크의 거절" 은 이 커널 인터페이스로 강제할 수 없다**(1-5 마지막 행,
Matrox 가 실측으로 확증).  선택지:
- **(가, 권고)** Matrox 와 같이 **고정 창 + 협조적 단일 클라이언트 규칙**(문서로), 강제는 하지 않는다.  게이트의
  그 항목을 "경계 밖 거절·결정성" 으로 바꾼다.  엔진 **제출**은 드라이버가 클레임으로 직렬화하므로 겹쳐도
  명령이 섞이지는 않는다 — 섞일 수 있는 것은 유저 쪽 쓰기뿐.
- (나) 클라이언트별 핸들·마이너와 할당 — 인터페이스 설계가 새로 필요(Mesa 통합 M 에서 할당자가 필요해질 때).

## 7. 위험

| 위험 | 완화 |
|---|---|
| FIFO 넘침·엔진 정지로 버스가 멈춘다 → 하드 프리즈 → 루트 fsck | 쓰기 전 빈 칸 확인, 모든 대기 상한, 실행 뒤 넘침은 걸쇠, 리셋 없음, 로그 보존 |
| BIOS 가 둔 엔진 상태(가위·dest cache 모드)가 예상과 다르다 | `RECORD` 로 먼저 보고, 연산마다 필요한 상태 전부 쓰기 |
| dest cache 를 잘못 골라 되읽기가 낡는다 | 둘 다 flush, 어느 쪽이 BUSY 였는지 기록, 되읽기를 두 번 해 같은지 |
| 종료 복귀(VGA)가 엔진 상태에 영향받는다 | 엔진 레지스터는 VGA 경로가 쓰지 않는다(추론) — R4 부팅 뒤 종료 화면을 operator 가 한 번 본다 |
| 유저 창과 R4 시험이 같은 VRAM 을 쓴다 | 구간 분리(2 절), 시험은 드라이버 전용 구간만 |

## 8. 교차검토에 물을 것

1. 3-2 게이트와 3-3 연산별 쓰기 목록에 빠진 것 — 특히 BIOS 가 켜 둔 상태 중 엔진 결과를 바꿀 수 있는 것.
2. dest cache 둘 다 flush 가 해로울 수 있나(RB3D 쪽은 3D 를 안 쓰는데 flush 해도 되나).
3. 되읽기를 uncached 별칭으로만 하는 근거가 RV280·이 커널에서도 서는가(`IOMapPhysicalIntoIOTask` 가 uncached 라는
   Matrox 의 증명은 BAR1 MMIO 였다 — BAR0 prefetch 애퍼처에서는?).
4. 겹침 블릿 네 경우로 방향 규칙이 충분히 판정되는가.
5. 2 절 구간과 R4c 창 크기(112 MiB)가 이후 R5·R6·M 에서 다시 열어야 할 결정인가.
6. 6 절 (가) 가 게이트를 약하게 만드는 것인가, 아니면 강제 불가능한 것을 정직하게 적는 것인가.

## 9. 교차검토 판정 (2026-09-18 — codex 는 사용량 한도(2026-09-19 19:23 까지)로 실패, 내부 agent 2 건(A: 엔진 정확성, B: 구간·d_mmap·검사·절차).  전 건 원문·실측 확인)

### 9-1. 내가 틀린 것

| # | 틀린 것 | 확인 |
|---|---|---|
| E1 | **MMIO 매핑이 8 KiB(`OSRDN_MMIO_LENGTH 0x2000`)인데 계획이 0x3428·0x342c·0x325c 를 읽고 쓴다** — 첫 `RECORD` 가 커널 폴트(→ 루트 fsck).  두 검토가 독립적으로 잡음 | `osrdn_record.h` 의 `#define OSRDN_MMIO_LENGTH 0x2000`, `OSRDNDisplay.m` 의 `IOMapPhysicalIntoIOTask(bar2, OSRDN_MMIO_LENGTH, …)`; 시뮬레이터도 `MMIO_WORDS 0x2000`·경계 검사 없음(`simworld2b.c` `rdnMmioRead32` 가 `mmio[offset / 4]` 를 그대로 반환) — 호스트 검사가 이 결함을 **통과시켰을 것** |
| E2 | 겹침 블릿 네 경우는 모두 dy≠0 이라 **X 방향을 판정하지 못한다**: 행 단위 엔진에서 Y 순서가 맞으면 X 비트와 무관하게 결과가 같다 | NetBSD 규칙(`radeonfb.c:3703-3732`)을 따라 논리 확인; B 의 python 모형(X 만 틀림 → 0 불일치, (±8,0) → 768) |
| E3 | 유휴 판정을 `RBBM_ACTIVE` 하나로 적었다 — 참고 셋 모두 **FIFO 64 칸을 먼저** 기다린 뒤 ACTIVE 를 본다 | xf86 `radeon_commonfuncs.c` 1012·1016, FreeBSD `radeon_cp.c` 384·389, NetBSD `radeonfb.c` 3768–3770 |
| E4 | dest cache flush 를 `0xf` 쓰기로 적었다 — 참고 셋 모두 **읽어서 OR 해 쓴다** | NetBSD `SET32`(`radeonfbvar.h` 327), xf86 `OUTREGP`(`radeon_macros.h` 75), FreeBSD `tmp |= …` |
| E5 | `GMC_AUX_CLIP_DIS`(비트 29)·`AUX_SC_CNTL`(0x1660) 를 다루지 않았다 — BIOS 가 보조 클립을 켜 두었으면 조용히 잘린다 | 두 헤더에 `(1 << 29)`, NetBSD 초기화가 `AUX_SC_CNTL = 0` |
| E6 | 256×256×4 = 256 KiB 표면 하나가 이미 별칭 한도(256 KiB)를 채우는데 "서로 다른 표면 복사" 가 둘째 표면을 요구 | python |
| E7 | "14 비트(8191)" — 0x1fff 는 **13 비트** | python `bit_length` = 13 |
| E8 | 3-1 "`modeClaim` 을 잡은 채로" 만 적었다 — 클레임 중 커널 복귀는 **표시만 하고 미뤄지며** `modeFinish` 만 그것을 수행한다(`modeRelease` 는 표시를 지운다).  엔진 연산이 `modeRelease` 로 끝나면 **종료 복귀를 잃는다**.  세 함수는 `osrdn_mode.m` 의 `static` 이다 | `osrdn_mode.m` 의 `osrdn_mode_revert`(`if (mode->inSequence) { mode->kernelRevertSeen = 1; … got = 0; }`), `modeRelease`, `modeFinish` |
| E9 | R4c 시험의 "엔진 채우기 목적지를 유저 창 안으로" 와 7 절 "시험은 드라이버 전용 구간만" 이 모순, 그리고 목적지 사각형 검사가 없다(유저가 엔진 쓰기를 화면으로 겨눌 수 있다) | 계획 본문; Matrox `osmgaProbeFill` 은 사각형 전체를 창과 대조 |
| E10 | 6 절 "강제할 수 없다" 가 **과하다**: Matrox 3-35 가 배제한 것은 **close 로 풀리는** 배타성뿐이다.  커널은 `_pfind`·`_current_task_EXTERNAL`·`_proc_from_thread` 를 export 한다(`tools/host/kernel_symbols.py` 로 실기 `mach_kernel` 확인) — open 때 신원+생존 확인은 **조사하지 않았을 뿐**이다.  정말 불가능한 것은 (1) 기존 매핑 회수, (2) `d_mmap` 안에서의 임대 판정(두 번 호출 결정성), (3) fork·close 뒤 남는 매핑 | 위 도구 실행 결과, Matrox `REMAINING_WORK.md` 3-35 원문(판정 (a)(b) 는 close 에 기댄 것) |
| E11 | 로그 수집기 경로 — 프로젝트 안에 없고 워크스페이스 루트 `tools/nx-logcatch.sh` | `ls` |

### 9-2. 채택 (계획을 이렇게 고친다)

1. **MMIO 매핑 0x4000**(E1).  근거: PCI BAR 크기는 2 의 거듭제곱이고 0x342c 를 담는 가장 작은 것은 0x4000(python);
   radeonfb 가 이 칩(RV280, NetBSD 는 R300 아님)에서 0x342c 를 쓴다.  **BAR2 크기 자체는 여전히 측정하지 않았다**고
   적는다.  함께: `check_r2b0_src.py`·`check_r2a_src.py` 의 0x2000 고정값, 시뮬레이터 `MMIO_WORDS` 0x4000 + 두 접근자가
   범위 밖이면 **실패로 기록**, 새 검사 "엔진 단위가 쓰는 모든 오프셋 < `OSRDN_MMIO_LENGTH`"(변이 FAIL).
2. **블릿 경우**: 대각 넷 + **(+8,0), (−8,0), (0,+8), (0,−8)**.  시뮬레이터 변이 "X 비트만 뒤집기"·"Y 만" 이 각각 FAIL.
   (±8,0) 은 **일부러 틀린 X** 로 한 번 더 — 불일치가 나야 X 판정력이 있는 것이고, 안 나면 "이 하드웨어에서 X 는
   판정 불가(행 전체 버퍼)" 로 **기록**(PASS 로 세지 않는다).  드라이버 전용 구간만 쓴다.
3. **유휴 = FIFO 64 칸 AND `ACTIVE` 0**(게이트와 같은 술어), 둘 다 로그.
4. **flush = 읽기 → OR 0xf → 쓰기**, 앞값 로그; dest cache 레지스터는 **유휴 뒤에만** 읽는다.  0x342c·0x325c 둘 다.
   0x325c 는 참고들이 `RB3D_CNTL = 0` 뒤에만 건드리므로 **`RB3D_CNTL` ≠ 0 이면 멈추고 operator 에게**(게이트).
5. **GMC 워드 고정**(python): 채우기 `0x30f036d2`, 블릿 `0x32cc36f3`(32bpp, `AUX_CLIP_DIS`·`CLR_CMP_CNTL_DIS`·
   `*_PITCH_OFFSET_CNTL` 포함).  연산마다 `SC_TOP_LEFT = 0`, `SC_BOTTOM_RIGHT = 0x1fff1fff` 도 쓴다(클립 비트는 끔).
6. **`RECORD` 확장**: `AUX_SC_CNTL`, `DEFAULT_PITCH`(0x16e4), `DSTCACHE_CTLSTAT`(0x1714), `RB3D_CNTL`, PLL `SCLK_CNTL`(0x0d)·
   `SCLK_MORE_CNTL`(0x35)·`CLK_PWRMGT_CNTL`(0x14) **읽기만**, 연산이 쓸 **모든 레지스터의 앞값**.  `RBBM_STATUS` 를 먼저 읽고
   2D·0x3xxx 레지스터는 FIFO 64·`ACTIVE` 0 일 때만.  **기대값과 중단 기준을 값을 보기 전에 이 문서에 적는다**(10 절).
7. **어느 피치 레지스터를 읽는지 판정**(A F6): 시험 동안 `DEFAULT_OFFSET` 을 드라이버 전용 구간의 **미끼 표면**(다른
   피치)으로 두고 표지로 채워 둔다 → 미끼가 바뀌면 엔진이 기본 레지스터를 읽은 것.  끝나면 `RECORD` 앞값으로 되돌린다.
   표지는 별칭 전체에, 각 표면 둘레에 **가드 띠**.
8. **별칭 1 MiB**(`[8 MiB, 9 MiB)`) — 표면 둘·미끼·가드 띠를 담는다.  크기 단언은 오라클에.  **초기화 때 MMIO 매핑 옆에서**
   한 번 만들고(엔진 키가 켜졌을 때만), 실패하면 걸쇠(연산마다 재시도하지 않음), 해제하지 않음(Matrox `osmgaProbeAlias` 선례).
9. **쓰기→실행 울타리를 명시**: 원본 패턴을 쓰고 **전부 되읽는 단계가 곧 울타리**(PCI 읽기는 앞선 게시 쓰기를 앞지를 수
   없다)이며 지우지 말 것이라고 코드·문서에 적는다.  불일치는 "시험 전 값(표지/패턴)과 같음"(낡음 또는 미실행)과 "그 밖" 으로
   나눠 세고, **첫 불일치 위치(특히 바이트 0..63)** 를 기록 — Matrox 3-18 은 창 첫 64 바이트만 낡았다.
10. **엔진 진입점은 `osrdn_mode.m` 안**: `modeClaim` → `noSleep = 1` → 연산 → **`modeFinish`** → 그 뒤에만 IOLog.  시뮬레이터 경우:
    엔진 대기 중 커널 복귀 주입(`simHookMode`) → 카드는 복귀됨·클레임 풀림, 연산 중 전달표 도착 → 해제 때 적용,
    `sleepCalls == 0`, `simSplMax` 불변.
11. **실행 뒤 넘침**: 걸쇠를 **RAM 에 먼저** 세우고(`PLAN.md` 금지 8) 그 뒤에만 진단 읽기.
12. **엔진 전용 키** `"RDN Engine Test" = "Yes"`(기본 꺼짐) — `PLAN.md` 4 절 "R3 이후 추가 기능은 키" 규칙.
13. **호스트 검사의 이름을 정직하게**: 가짜 엔진은 "드라이버 = **우리 모형**" 을 증명할 뿐 하드웨어를 증명하지 않는다.
    오라클은 생성 헤더가 아니라 **세 참고 헤더(regtable)** 와 **시뮬레이터가 기록한 실제 MMIO 쓰기 순서**에 대조한다.
14. **R4c**: `d_mmap` 에 Matrox 의 네 검사 더하기 — 물리 덧셈 넘침(`bar0 > 0xFFFFFFFF − off`), 물리 페이지 정렬, PFN ≤ 0x7FFFFFFF,
    빈 창; minor = dev 하위 바이트.  `d_open` 은 창이 쓸 수 있을 때만 성공.  **등록은 `initFromDeviceDescription:` 의 마지막**
    (그 뒤에 실패 반환이 없도록).  등록 게이트: `CONFIG_APER_SIZE`·`CONFIG_MEMSIZE` ≥ 128 MiB, `bar0 + 128 MiB − 1` 이 브리지
    prefetch 창 안, `bar0 % page_size == 0`; `page_size`·`page_shift`·bar0·첫/끝 PFN 로그.  유저가 겨누는 엔진 채우기는
    사각형 전체를 `[16 MiB, 128 MiB)` 와 **넘침 없는 형태로** 대조.  시험 도구: 작은 매핑부터(전체 창 매핑은 페이지 14 336 개
    삽입 — 커널 비용 미측정, 따로 관찰), **읽기 → 엔진 채우기 → 다시 읽기**와 역방향(유저 쓰기 → 드라이버 전용으로 블릿 →
    별칭 대조), 128 MiB 직전 채우기 뒤 **64 MiB 아래 같은 오프셋의 표지 불변**(에일리어싱, 빠진 V-1 을 공짜로 대신).
    매핑은 복귀 뒤에도 같은 BAR0 물리 페이지를 가리킨다고 명시.
15. **유저 창은 "R4c 스모크 구간, R6/M 에서 다시 연다"** 로 표기(1600×1200 색+깊이 ≈ 14.6 MiB 는 드라이버 전용 8 MiB 에 안 들어간다).
    `PLAN.md` 9 절에 올린다.  R5 는 충돌 없음(GART 창은 MC 공간 `0x20000000` — VRAM 밖, R1).
16. **절차(5 절 보강)**: 로그 수집기는 워크스페이스 루트 `tools/nx-logcatch.sh`; runid 를 원자적으로 선점하고 연산마다 진행
    표지; **하드 행 한 번 → 중단하고 오프라인 분류**(`PLAN.md` 중단 조건); operator 가 볼 것 — 화면 **왼쪽 위의 200×40 상자**
    (`0xDEADBEEF` 색, 이어서 검정)가 보이면 오프셋 필드가 무시되어 카드 주소 0(보이는 화면 원점)에 그려진 것; 종료 화면 한 번
    보기 대신 **같은 부팅에서 `BLIT` 뒤 `RDNR2bCycle`** 로 엔진 상태가 더럽혀진 뒤의 복귀를 로그로 판정; 연산 중 로그아웃·창 서버
    재시작 금지(`enterLinearMode` 는 클레임 중 BUSY 이고 재시도가 없다).
17. **소요 예산**: 연산마다 걸린 판정 횟수·추정 시간을 로그(R2c 순환이 약 200 ms 전형·600 ms 최악).  `IODelay` 는 이 기계에서
    짧게(0.94 배)도 길게(R2a `IODelay(2000)` = 4.1 ms)도 측정됐다 — 상한은 어느 쪽이든 안전하게.

### 9-3. 기록만 (행동 변화 없음)

- A F8·F10·F12·F13: 두 cache flush 는 RV280 에서 참고와 정합(0x325c 잠금 경고는 RV280 초과에만, FreeBSD `radeon_cp.c` 343);
  클럭은 참고들이 BIOS 상태 그대로 2D 를 쓴다(`SCLK_CNTL 00007ffa`, R2a 실측) — 읽기만; `DP_DATATYPE` 빅엔디언 비트는 호스트
  데이터 전송에만 영향; 측정값과 모순 없음(`RBBM_STATUS 00000140` = FIFO 64·ACTIVE 0 등).
- B 13: 상위 클래스 `revertToVGAMode` 는 클레임 밖에서 먼저 돈다 — 유저 태스크가 죽은 뒤라 위험은 낮다(7 절에 적는다).

## 10. operator 결정 (다시 묻는다 — 6 절을 대체)

**임대**: R4c 에서 **강제하지 않는다**(Matrox 와 같은 고정 창 + 협조적 단일 클라이언트).  정직하게 적으면 — 기존 매핑 회수·
`d_mmap` 안의 판정·fork 뒤 매핑은 **불가능**, open 때 신원+생존 확인(`pfind` 등)은 **조사하지 않음**.  이것은 게이트의 **연기**
이며, `PLAN.md` 의 V-2("드라이버가 강제하는 단일 클라이언트 임대")·R4 게이트("임대가 없는 태스크의 거절")·7 절 위험 행을
"R4c 는 비강제, R6/M 의 할당·소유 설계로 연기" 로 고친다 — **operator 승인 뒤에.**

## 11. Matrox 의 창 결정 방식 조사 (operator 지시 "matrox 정도 기준, 해상도에 따라 판단", 2026-09-18)

### 11-1. Matrox 가 하는 것 (원문: `OSMGADisplay_reloc.tproj/OpenStepMGAWindowMath.h/.c`, 드라이버 `.m`)

| 항목 | Matrox 규칙 |
|---|---|
| 창 **시작** | 모드마다: `pageup(보이는 화면 w×h×bpp + 가드 256 행 × w×bpp)` — `OSMGAWindowGeometry`, 드라이버의 등록 식과 같은 식 |
| 창 **끝**(천장) | `min(선언, 애퍼처) − 위쪽 여유 4 MiB`, 페이지 내림 — `OSMGAWindowCeiling`.  여유의 이유는 "보드가 위쪽에 무언가를 두는데 무엇인지 아무도 확인하지 않았다" |
| 등록 판정 | 보수적 한계가 아니라 **천장** 기준으로 "이 창이 언젠가 비지 않을 수 있는가" — 1600×1200 이 보수적 한계로 판정되어 등록 거절 → 증명 미실행 → 창 없음이 된 실측 사고 뒤 고침(`OSMGAWindowMayRegister`) |
| 여는 시점 | 빈 채로 등록 → 부팅 VRAM 증명(쓰기) → **한 번** 연다(`OSMGAWindowOpenDecision`), 그 전에는 `open` 거절.  "창 아래에 쓰는 증명은 첫 open 전에 끝나야 한다" |
| 가속 판정 | 32bpp 만.  `ready` = 320×240 색+깊이가 들어가는가, `fullScreen` = 화면 크기 색+깊이가 들어가는가(보고만, `ready` 를 막지 않음) — `OSMGAAccelVerdict`/`OSMGAAccelReadyBits` |
| 공유 계산 | 같은 C 파일을 커널과 Configure 인스펙터가 **함께 컴파일** — 패널의 "would give … MB, up to WxH" 문장이 여기서 나온다 |
| 임대 | **없다** — 고정 창, 협조적 단일 클라이언트(3-35) |

Matrox 에서 해상도가 중요했던 것은 **VRAM 이 16/32 MiB** 였기 때문이다: 16 MiB 에서 1600×1200×32 는 화면 크기 색+깊이가
들어가지 않았다(`docs/R3_16M_RENDER_BUDGET.md`).

### 11-2. 같은 규칙을 우리 20 모드·128 MiB 에 (python, 천장 124 MiB)

| 모드 | 32bpp 창 시작 → 크기 | 555/16 | 8bpp·BW:8 | 전체 화면 GL(32bpp) |
|---|---|---|---|---|
| 640×480 | 1 884 160 → 122.20 MiB | 123.10 MiB | 123.55 MiB | 들어감 |
| 800×600 | 2 744 320 → 121.38 MiB | 122.69 MiB | 123.34 MiB | 들어감 |
| 1024×768 | 4 194 304 → 120.00 MiB | 122.00 MiB | 123.00 MiB | 들어감 |
| 1280×1024 | 6 553 600 → 117.75 MiB | 120.88 MiB | 122.44 MiB | 들어감 |
| 1600×1200 | **9 322 496** → 115.11 MiB | 119.55 MiB | 121.77 MiB | 들어감 |

- 가장 작은 창도 115 MiB — **128 MiB 에서는 해상도가 "되느냐 안 되느냐" 를 가르지 않고 창 크기만 바꾼다.**
- **내 계획의 고정 구간이 틀렸다**: 1600×1200×32 의 창 시작(가드 포함 9 322 496 B = **8.89 MiB**; 처음에 "9.32 MiB" 로 적은 것은 10 진 백만 단위로 읽은 오기)이 내가 둔 "드라이버 전용 `[8, 16) MiB`" 와 겹친다.
  고정 16 MiB 시작은 작은 모드에서 최대 15 MiB 를 버리기도 한다.

### 11-3. 개정 제안 (Matrox 기준)

1. **R4c 창 = Matrox 식 그대로**: 시작 `pageup(보이는 화면 + 가드 256 행)`, 끝 `128 MiB − 4 MiB`, 모드마다 부팅 때 한 번 계산하고 부팅 중
   불변(`d_mmap` 결정성).  `OSRDN_FB_LENGTH`(8 MiB 커널 매핑)와는 무관하다 — `d_mmap` 은 물리 주소를 준다.
2. **R4a/R4b 시험 표면**: 고정 구간을 없애고 **창 시작 자리**를 쓴다(Matrox S1 이 `y = height + 256` 에 그린 것과 같은 자리).
   조건은 Matrox R11 규칙 — **창이 한 번도 열리지 않았을 때만** 시험을 허용(R4c 빌드에서 `open` 이 한 번이라도 성공했으면 시험은
   거절).  R4a/R4b 빌드에는 문자 디바이스가 아예 없으므로 조건이 저절로 선다.
3. **증명 단계는 없다**(operator 결정: 128 MiB 가정) — 창은 등록 때 바로 연다.  대신 R4c 시험 도구가 창 끝 페이지 읽기·쓰기와
   64 MiB 아래 표지 불변(에일리어싱)을 본다(9-2 의 14).
4. **임대 = Matrox 와 같이 없음**(협조적 단일 클라이언트, 문서로).  10 절의 "연기" 표기는 그대로 — R6/M 의 할당자가 필요해지면 연다.
5. **창 계산은 순수 C 한 파일**(`osrdn_window.h` 식)에 두고 호스트 검사가 20 모드 전부를 이 표와 대조 — 나중에 인스펙터가
   Matrox 처럼 "would give …" 를 보여 주고 싶으면 같은 파일을 번들에 컴파일하면 된다(이번 범위 밖).
6. 위쪽 여유 4 MiB 는 **Matrox 의 보수적 선택을 그대로** 쓴다 — Radeon 이 VRAM 위쪽을 예약하는지는 참고 자료로 확인하지 않았다.

## 12. R4a/R4b 확정 명세 (9·11 절을 반영, 코딩 전 교차검토 대상, 2026-09-18)

operator 결정: 창은 Matrox 식(11 절), **임대 없음**(`PLAN.md` V 절 2026-09-18).  이 절이 1–8 절의 설계를 대체한다
(충돌하면 이 절이 이긴다).  R4c(문자 디바이스)는 R4a/R4b 가 실기 PASS 한 뒤 따로 계획한다.

### 12-1. 이번 빌드의 변경 범위

| 무엇 | 어떻게 |
|---|---|
| MMIO 매핑 | `OSRDN_MMIO_LENGTH` 0x2000 → **0x4000**(9-2 의 1).  `checkBar`·R1 게이트·`check_r2b0_src.py`·`check_r2a_src.py` 의 고정값·시뮬레이터 `MMIO_WORDS` 함께; 시뮬레이터 접근자는 범위 밖이면 실패 기록 |
| 켜는 키 | `"RDN Engine Test" = "Yes"`(없으면 꺼짐).  이 시험 빌드의 번들 표에는 넣는다 |
| 별칭 | 키가 켜지고 MMIO 가 매핑됐을 때 **초기화에서 한 번**: `IOMapPhysicalIntoIOTask(bar0 + winStart, 256 KiB)`.  실패하면 걸쇠(연산은 전부 거절), 해제 안 함 |
| `winStart` | 부팅 모드의 `pageup(w·h·bpp + 256·w·bpp, page_size)` — 11 절 식.  20 모드 중 최대 9 322 496 B(8.89 MiB), 별칭 끝 9.14 MiB < 천장 124 MiB(python) |
| 새 단위 | `osrdn_engine.h/.m`(순수 C, `rdnMmio*` 접근자만) — 게이트·쓰기 묶음·대기·flush·되읽기·판정 |
| 진입점 | `osrdn_mode.m` 에 `osrdn_mode_engine(mode, base, op, arg)`: `modeClaim` 실패 → `IO_R_BUSY`(기다리지 않음) → `noSleep = 1` → 엔진 단위 호출 → **`modeFinish`** → 그 뒤 IOLog |
| 호출 통로 | `setIntValues` 매개변수 `"RDNR4Engine"`, 낱말 3 개 `{매직 0x52344530 ("R4E0"), 연산, 인자}` |
| 유저 도구 | `rdnr2b0` 에 `engine record|fill|blit <case>` |

### 12-2. 시험 표면 (별칭 안, 32bpp, python 배치)

| 표면 | 별칭 안 오프셋 | 크기(px) | 피치 | 바이트 |
|---|---:|---|---:|---:|
| 앞 가드 | 0 | — | — | 16 384 |
| S0 채우기 | 16 384 | 256×64 | 1024 | 65 536 |
| S1 블릿 | 98 304 | 128×128 | 512 | 65 536 |
| S2 복사 목적지 | 180 224 | 128×64 | 512 | 32 768 |
| D 미끼 | 229 376 | 64×64 | 256 | 16 384 |
| (사이·뒤 가드) | | | | 합계 256 KiB 중 가드 81 920 |

카드 주소 = `winStart + 오프셋`(4 KiB 정렬 → 1 KiB 오프셋 필드 정렬).  피치는 모두 64 의 배수.  `*_PITCH_OFFSET = (pitch/64) << 22 | (카드주소 >> 10)`.

### 12-3. 연산

**공통 앞부분** — 게이트(하나라도 다르면 쓰기 0 회로 거절, 사유 코드): 키 켜짐, 별칭 있음, 걸쇠 없음, `modeWritten`,
`RBBM_STATUS` 를 먼저 읽어 FIFO = 64·`ACTIVE` = 0, 그다음에만 `CP_CSQ_CNTL >> 28` = 0, 두 dest cache `BUSY` = 0, `RB3D_CNTL` = 0,
`SURFACE_CNTL` 스왑 비트 0.

**`RECORD`**(쓰기 없음): 위 값 + `DSTCACHE_CTLSTAT`(0x1714), `RB2D_DSTCACHE_MODE`(0x3428), `DEFAULT_OFFSET`, `DEFAULT_PITCH`,
`DEFAULT_SC_BOTTOM_RIGHT`, `SC_TOP_LEFT`, `SC_BOTTOM_RIGHT`, `AUX_SC_CNTL`, `DP_DATATYPE`, `DP_GUI_MASTER_CNTL`, `DP_CNTL`, `DP_WRITE_MASK`,
`DST_/SRC_PITCH_OFFSET`, `DP_BRUSH_FRGD_CLR`, PLL `SCLK_CNTL`(0x0d)·`SCLK_MORE_CNTL`(0x35)·`CLK_PWRMGT_CNTL`(0x14)(PLL 읽기는 기존
접근자에 표 항목 추가, 색인 복원).  2D·0x3xxx 레지스터는 FIFO 64·`ACTIVE` 0 을 본 뒤에만 읽는다.

**`FILL <색>`**: ① 별칭 256 KiB 전체에 표지 `0x5A5A5A5A` 를 쓰고 **전부 되읽어 확인**(울타리 겸 거짓 PASS 차단 — 지우지 말 것).
② FIFO ≥ 12 대기(넘치면 쓰기 없이 거절).  ③ 쓰기 12 칸: `DEFAULT_OFFSET = D 의 피치·오프셋`, `DST_PITCH_OFFSET = S0`,
`DEFAULT_SC_BOTTOM_RIGHT = 0x1fff1fff`, `SC_TOP_LEFT = 0`, `SC_BOTTOM_RIGHT = 0x1fff1fff`, `DP_GUI_MASTER_CNTL = 0x30f036d2`,
`DP_WRITE_MASK = 0xffffffff`, `DP_BRUSH_FRGD_CLR = 색`, `DP_CNTL = 3`, `DST_Y_X = (8 << 16) | 16`, **마지막** `DST_WIDTH_HEIGHT = (200 << 16) | 40`.
④ 유휴 대기(FIFO 64 AND `ACTIVE` 0).  ⑤ flush: 0x342c 읽기 → OR 0xf → 쓰기 → `BUSY` 0 대기, 0x325c 같게; 앞값 로그.
⑥ 256 KiB 전체 되읽기 판정: S0 의 (16,8,200,40) 안은 색, 나머지 **전부**(S0 밖·가드·S1·S2·D) 표지.  ⑦ `DEFAULT_OFFSET` 을 `RECORD`
앞값으로 되돌림(FIFO ≥ 1).  색은 `0xDEADBEEF` 와 `0x00000000` 두 번 부른다.
해석: 사각형 불일치 = 엔진이 안 그렸거나 낡은 읽기, D 가 바뀜 = **엔진이 기본 피치 레지스터를 읽었다**, 가드가 바뀜 = 피치·오프셋 오류.

**`BLIT <경우>`**(한 호출에 한 경우 — 호출당 스핀 시간을 짧게): ① 별칭 전체 표지, S1 에 `px(y,x) = 0xFF000000 | (y << 8) | x`,
**전부 되읽어 확인**.  ② 경우 0: S1 (32,32,64,64) → S2 (8,0) (다른 표면, 겹침 없음).  경우 1–8: S1 안에서 (32,32,64,64) 를
(dx,dy) = (+8,+8)(−8,−8)(+8,−8)(−8,+8)(+8,0)(−8,0)(0,+8)(0,−8) 만큼.  경우 9–12: 경우 5–8 을 **일부러 틀린 방향 비트**로(판정력 시험).
③ 방향: `dsty < srcy` 면 위→아래(비트 1), 아니면 `srcy,dsty += h−1`; `dstx < srcx` 면 왼→오(비트 0), 아니면 `srcx,dstx += w−1`
(NetBSD, `radeonfb.c:3703-3732`).  ④ 쓰기 12 칸: `DEFAULT_OFFSET = D`, `SRC_PITCH_OFFSET`, `DST_PITCH_OFFSET`, 가위 셋,
`DP_GUI_MASTER_CNTL = 0x32cc36f3`, `DP_WRITE_MASK`, `DP_CNTL = dir`, `SRC_Y_X`, `DST_Y_X`, 마지막 `DST_WIDTH_HEIGHT`.
⑤ 유휴 → flush → 판정: 목적지 사각형 = **복사 전 원본**, 그 밖 = 복사 전 값 그대로.  ⑥ `DEFAULT_OFFSET` 복원.
경우 9–12 의 기대는 "불일치 > 0"; 0 이면 **"이 방향은 이 하드웨어에서 판정 불가"** 로 기록(PASS 로 세지 않는다).

**대기 상한**(명목, `modeWaitUs` 와 같은 방식 — 한도는 명목 × `MODE_TURN_FACTOR`, 판정 횟수·소요 로그): FIFO 10 ms, 유휴 100 ms,
flush 각 10 ms.  **실행 뒤 넘침** → 걸쇠를 RAM 에 먼저 → 그 뒤 진단 읽기(`RBBM_STATUS` 하나) → 정리 쓰기·폴백·리셋 없음.

**판정 로그 한 줄**(연산마다, `modeFinish` 뒤): `RDN-R4 <op> boot=<nonce> case=<n> gate=<g> rc=<r> in=<사각형 불일치> not=<표지/원본과
같은 불일치> out=<사각형 밖 불일치> decoy=<D 변화> guard=<가드 변화> first=<첫 불일치 오프셋> f64=<0..63 바이트 안 불일치>
fifo=<판정 횟수> idle=<…> fl2=<앞값/횟수> fl3=<…>`.  불일치가 있으면 짧은 지연 뒤 한 번 더 읽어 `reread=<불일치>`.

### 12-4. 호스트 검사

1. `tools/r4/engine_oracle.py`: GMC 워드·피치오프셋·방향·트리거를 **세 참고 헤더(regtable)** 에서 독립 계산, 시뮬레이터가 기록한
   **실제 MMIO 쓰기 순서**와 대조(생성물끼리 비교 금지).
2. 시뮬레이터 가짜 엔진(`simworld2b.c`): FIFO 계수(빈 칸보다 많이 쓰면 실패 기록), 트리거 때 가짜 VRAM 에 채우기/블릿을 **행 단위·
   방향 비트대로** 실행, `ACTIVE`/`BUSY` 지속 설정.  **이름은 "드라이버 = 우리 모형"** — 하드웨어 증명이 아니다.
   변이: X 방향만 뒤집기, Y 만, FIFO 확인 빼기, 유휴에서 FIFO 조건 빼기, flush 를 쓰기로(RMW 아님), 대기 상한 없애기, 실행 뒤 넘침에
   폴백, 게이트 하나씩, `*_PITCH_OFFSET_CNTL` 빼기(시뮬레이터가 `DEFAULT_OFFSET` 을 미끼로 둔다), `AUX_CLIP_DIS` 빼기(시뮬레이터가 보조
   클립을 켠 채 시작), `modeFinish` 대신 `modeRelease`(대기 중 커널 복귀 주입 → 복귀가 사라지면 실패), 표지 되읽기(울타리) 빼기.
   불변: `sleepCalls == 0`, `simSplMax` 불변.
3. 엔진 단위가 쓰는 모든 MMIO 오프셋 < `OSRDN_MMIO_LENGTH`(변이 FAIL).
4. `regtable.py` 에 새 레지스터 추가(세 헤더 대조).
5. 창 계산: 20 모드 `winStart` 가 11-2 표와 같다(python 독립 계산 대 C 단위 실행).
6. 로그 판정기 `tools/r4/check_engine.py` 와 자체 시험.
7. 역어셈블 게이트: 엔진 레지스터 쓰기 호출자는 엔진 단위뿐, `SURFACE_CNTL`·`RBBM_SOFT_RESET`·`HOST_PATH_CNTL`·`RB3D_CNTL` 쓰기 0 회.
8. `hostcheck`(C89·`#import`)에 새 단위 포함.

### 12-5. 실기 절차

1. check-all PASS → 묶기 → 실기 빌드·역어셈블 게이트 → 설치(`closed=yes fresh live`) → **operator 재부팅**.
2. 재부팅 뒤: 실제 경로로 `/ndrv` 마운트 → gcdsd → `tools/nx-logcatch.sh start`(워크스페이스 루트) → 부팅 판정(`check_select`).
3. **값을 보기 전에 적어 둔 기대**: `RB3D_CNTL` = 0(아니면 중단), FIFO 64·`ACTIVE` 0, `CP_CSQ_CNTL >> 28` = 0, `SURFACE_CNTL` = `00000100`(R1).
   그 밖의 값(가위·`AUX_SC_CNTL`·dest cache 모드·클럭)은 기록만 하고, 우리가 연산마다 쓰는 값이므로 결과에 영향이 없어야 한다.
4. `engine record` → 호스트 검토 → `engine fill deadbeef` → 판정 → `engine fill 0` → `engine blit 0` … `12` → 판정.
   **operator 가 볼 것**: 화면 왼쪽 위 200×40 상자(오프셋 무시로 화면에 그림 = 실패), 그 밖 화면 이상.  telnet 생존.
5. 같은 부팅에서 `RDNR2bCycle` 한 번(엔진 상태가 바뀐 뒤의 복귀를 로그로 판정).
6. **하드 행 한 번이면 중단**, 오프라인 분류.  연산 중 로그아웃·창 서버 재시작 금지.

## 13. 12 절 검토 판정 (2026-09-18, 내부 agent 1 건 — codex 한도.  전 건 원문·python 확인)

산술(GMC 워드·표면 배치·피치오프셋·사각형·매직·`winStart`)은 **전부 맞다**(검토자 python, 내가 GMC·배치·매직을 따로 재계산).
결함은 코드 구조와의 맞춤에 있다.

| # | 지적 | 내 확인 | 판정 → 12 절 수정 |
|---|---|---|---|
| 1 | PLL 읽기를 기존 표에 더하면 스냅샷·복귀 집합이 넓어져 R2c 복귀 판정이 클럭 레지스터까지 비교한다 | `osrdn_snap.h` 6 행 "THE SET THIS FILE CAN WRITE IS THE SET IT SNAPSHOTS", `osrdn_snap.m` 134 행 표 색인, `osrdn_mode.m` 1150–1152 행 비교 | ✅ **읽기 전용 별도 표·접근자**(`osrdn_pll_peek`, put 없음, 색인 복원), `CALL_WANT` 에 추가 |
| 2 | 경우 9–12 에 뒤집을 비트·시작 좌표가 안 정해졌다 | 내 python 모형(시작 좌표를 뒤집은 방향에 맞게 재계산): 5·6 에서 X 뒤집기 = 3584(픽셀 단위)/0(행 버퍼), 7·8 에서 Y 뒤집기 = 3584/3584, 대각에서 X 뒤집기 = 0 | ✅ **9·10 = 경우 5·6 의 X 뒤집기, 11·12 = 경우 7·8 의 Y 뒤집기, 시작 좌표는 뒤집은 방향으로 다시 계산**(발자국이 옳은 경우와 같다).  11·12 가 0 이면 **이상**(판정 불가가 아니다); 9·10 만 0 이 정당(원본 버퍼 ≥ 64 px) |
| 3 | `osrdn_mode.m` 은 로그 금지 | `check_r2b_src.py` 226–229 행, `OSRDNDisplay.m` 27–28 행 | ✅ 결과 구조체를 돌려주고 `osrdn_modelog.m` 이 찍는다(순환과 같게) |
| 4 | 클래스의 `IOMapPhysicalIntoIOTask` 는 정확히 하나(MMIO) 라는 검사 규칙 | `check_r2b0_src.py` 206–208 행 | ✅ 규칙을 **둘(MMIO, 별칭)** 로 정밀화하고 각각의 길이를 고정(약화가 아니라 분리), 해제는 여전히 `free` 에서만 |
| 5 | 별칭 범위(1600×1200×32 에서 9.14 MiB 까지)를 아무 검사도 보지 않는다 | `osrdn_record.m` BAR0 검사 길이 `OSRDN_FB_LENGTH` | ✅ 초기화 때 `[bar0, bar0 + winStart + 256 KiB)` 가 브리지 창 안, 연산 게이트에서 `CONFIG_MEMSIZE`·`CONFIG_APER_SIZE` ≥ `winStart + 256 KiB`(기존 `osrdn_peek`) |
| 6 | `DEFAULT_OFFSET` 복원값을 "RECORD 앞값" 에서 가져오면 안 된다 | 논리 | ✅ **같은 연산 안에서** 게이트 뒤·쓰기 전에 읽고, flush 직후(판정 읽기 전)에 복원.  거절·실행 전 넘침은 쓴 것이 없어 복원할 것도 없다.  **실행 뒤 넘침**은 쓰기 금지 규칙 우선 — 로그에 `default=decoy` |
| 7 | 엔진 걸쇠를 `mode->latched` 로 쓰면 다음 `enterLinearMode` 가 막힌다 | `osrdn_mode.m` 305–307 행 | ✅ **별도 필드**(`engineLatched`) |
| 8 | 클레임 순서·`noSleep` | `osrdn_mode.m` 1350–1355 행(순환의 모양), 1236 행(`modeFinish` 가 빚진 복귀를 수행할 때 `modeWaitUs` 가 자는 경로) | ✅ 클레임 → `kernelRevertSeen = 0`·`noSleep = 1`·`wantRevertCheck = 0` → **게이트는 클레임 뒤** → 모든 경로(거절 포함)를 `modeFinish` 로.  엔진 대기는 술어+시간 두 한도의 자체 폴링(`modeWaitUs` 는 시간만) |
| 9 | 시뮬레이터가 "행 단위" 면 X 뒤집기 변이가 절대 실패하지 않는다 | 2 의 표(행 버퍼 모형은 X 뒤집기 전부 0) | ✅ 가짜 엔진은 **픽셀 단위**(행 안에서 X 비트 순서로 한 픽셀씩 읽고 쓴다).  빠졌던 "연산 중 전달표 도착 → 해제 때 적용" 경우 복원 |
| 10 | "왼쪽 위 200×40 상자" 는 1024×768 8bpp 에서만 그 모양 | 내 python: 오프셋이 무시되면 바이트 8 256..48 991 → 모드마다 **화면 맨 위 1..76 행 사이의 줄무늬**(예 800×600×32 → 2..15 행) | ✅ operator 안내를 "화면 맨 위 몇십 행의 줄무늬/색 띠" 로, 모드별 행을 표로 |
| 11 | 9-2 의 runid 선점·진행 표지·연산별 소요 시간이 12 절에서 빠졌다 | 12 절 본문 | ✅ 되살림 |
| 12 | FILL 은 12 가 아니라 **11** 쓰기 | 목록 셈 | ✅ 오라클의 쓰기 수는 11/12 |
| 13 | `RECORD` 도 PLL 색인 바이트를 쓴다 | `osrdn_snap.m` | ✅ 문구 "엔진 쓰기 없음(PLL 색인은 쓰고 되돌린다)" |
| 14–17 | 별칭 이중 매핑은 Matrox 와 같은 모양(S1 은 16 MiB 매핑 안의 fb+4 MiB), `winStart` 는 MMIO 매핑 전에 알려진다, 별칭은 fb 매핑 성공 뒤에 만든다, 대기 상한·스핀 예산 타당, 레지스터 목록 | 원문 | ✅ 별칭 생성 위치만 반영, 나머지 기록 |

미확인으로 남는 것: BAR0 별칭의 실제 메모리 형식(uncached 인지), HDP 읽기 버퍼의 낡음, 엔진 원본 버퍼 크기, `RB3D_CNTL` 값,
PCI 읽기 지연·setIntValues 문맥의 spl — 모두 실기 `RECORD`·판정 로그가 답한다.

## 14. R4a/R4b 구현 기록 (호스트, 2026-09-18)

### 14-1. 만든 것

| 파일 | 내용 |
|---|---|
| `osrdn_window.h/.m` | Matrox 식 창 시작(`pageup(보이는 화면 + 가드 256 행)`)·천장(`128 MiB − 4 MiB`), 넘침 검사, 순수 C89 |
| `osrdn_engine.h/.m` | 게이트·`RECORD`·`FILL`·`BLIT`(경우 0–12)·상한 둘인 대기·RMW flush·미끼·판정.  `rdnMmio*` 만 쓴다, 로그·수면 없음 |
| `osrdn_mode.m` | `osrdn_mode_engine`: 클레임 → `noSleep` → (클레임 안에서) 모드 확인 → 엔진 → `modeFinish` |
| `osrdn_snap.h/.m` | 읽기 전용 PLL 표 `osrdnPllPeek`(0x0d·0x35·0x14)와 `osrdn_pll_peek`(`PLL_WR_EN` 이면 거절, 색인 바이트 복원) |
| `osrdn_record.h/.m` | `OSRDN_MMIO_LENGTH` 0x2000 → **0x4000**, `osrdn_fb_reach_ok`(별칭 범위의 브리지 창 검사) |
| `OSRDNDisplay.h/.m` | 키 `"RDN Engine Test"`, `-engineAliasFor:format:`(fb 매핑 뒤, 창·천장·브리지 확인 뒤 256 KiB 별칭), `"RDNR4Engine"` 통로, `-free` 에서 별칭 해제 |
| `osrdn_modelog.h/.m` | `osrdn_engine_line`: 결과 한 줄 + `RECORD` 3 줄 또는 결과·대기 2 줄, 모두 `(unsigned int)` + `%08x` |
| `tools/r2b0/rdnr2b0.m` | `engine record|fill <hex8>|blit <0-12>`.  **5–6 낱말인데 `engine` 이 아니면 거절**(원래는 기록으로 흘러갈 수 있었다) |
| 번들 표 | `"RDN Engine Test" = "Yes"` |

### 14-2. 검사 (모두 기준 PASS 와 변이 FAIL 을 같은 실행에서)

| 검사 | 내용 | 변이 |
|---|---|---:|
| `tools/r4/check_r4_src.py` | 규칙 12(매핑 둘, 엔진 쓰기 집합, 금지 레지스터, 매핑 안, 묶음 11/12·트리거 마지막, GMC 워드를 xf86 비트에서, 대기 두 상한, RMW, 걸쇠 먼저, 울타리, 감싸기, PLL 읽기 전용) | 22 |
| `tools/r4/sim_r4.py` + `sim/world4.c` | 픽셀 단위 가짜 엔진(FIFO·ACTIVE·dest cache·미끼·보조/기본 가위·방향·PLL 색인), 세계 검사 21 | 21 — 변이마다 **의도한 경우**가 잡는지 출력으로 확인 |
| `tools/r2b/sim_r2b.py` | 감싸기 경우 5(평상·도중 전달표·도중 커널 복귀·모드 없음·클레임 잡힘), 수면 0 | +3 |
| `tools/r4/check_window.py` | 15 기하(20 모드) + 이상 입력 9: C 단위 = python = 계획서 11-2 표 | 5 |
| `tools/oracle/regtable.py --self-test` | 같은 값 중복은 통과(`+DUP` 표시), 다른 값 중복은 실패 — NetBSD 가 `RB3D_DSTCACHE_CTLSTAT` 를 두 번 정의한다 | 5 경우 |
| `tools/r4/check_engine.py --self-test` | 실기 로그 판정 + **드라이버의 실제 IOLog 형식을 채워 파서가 읽는지** | 11 |
| `tools/r2b0/check_reloc_r2b0.py` | 호출자 표에 엔진·PLL peek, 필수 간선 `osrdn_pll_peek→Read32`·`engDraw→Write32` | — |

### 14-3. 구현 중 잡은 것

- **가짜 카드의 결함이 변이를 엉뚱한 이유로 잡게 했다**: "끝나지 않는 엔진" 이 트리거 전부터 `ACTIVE` 를 세워 게이트가 거절했고,
  dest cache 바쁨 비트를 읽을 때 늘 지웠다 → 기준 FAIL 5 건이 났고, 몇몇 변이("RB3D 게이트 빠짐" 등)가 그 엉뚱한 경우로
  잡히고 있었다.  모형을 고친 뒤 각 변이가 자기 경우로 잡힌다(FIFO 막힘은 게이트 뒤에, `ACTIVE` 가 내려간 뒤 FIFO 가 두 읽기
  늦게 찬다).
- **판정기가 실기 로그의 별칭 줄을 놓칠 뻔했다**: 드라이버는 초기화에서 별칭 줄을 select 줄보다 **먼저** 찍는다.  자체 시험에
  드라이버 형식 대조를 넣자 드러났고, 부팅 번호를 먼저 찾도록 고쳤다.
- **`check_r4_src` 의 대기 규칙이 약했다**: `maxTurns` 이름만 보아 "횟수 상한 비교 삭제" 변이를 놓쳤다 → 비교문 자체를 요구하도록
  정밀화(시간 상한도 같게).
- **`check_r2b0_src.py` 는 R2b-0 보관본의 클래스를 읽는다**(설계대로) — 매핑이 둘이 된 것을 거기서 못 보는 것은 정상이고,
  R4 규칙은 `check_r4_src.py` 가 현재 파일로 본다.

## 15. 실기 전 코드 검토 판정 (2026-09-18, 내부 agent 1 건.  전 건 원문 확인)

결론: 커널 폴트·FIFO 넘침·보이는 화면 쓰기로 가는 경로는 **찾지 못함**(검토자가 호스트 검사도 다시 돌려 PASS).  고칠 것 4 건과
참고 5 건을 모두 반영했다.

| # | 지적 | 확인 | 조치 |
|---|---|---|---|
| 1 | `-free` 가 `rdnEngine.alias` 를 해제하는데 초기화는 그것을 0 으로 두지 않는다 — 인스턴스가 0 으로 채워진다는 가정 | `OSRDNDisplay.m` 초기화는 `mmioMapped`·`mmioBase` 만 손으로 0 | 엔진 상태 다섯 필드를 초기화 첫머리에서 손으로 0 |
| 2 | 로그를 클레임을 푼 **뒤** `rdnEngine` 에서 읽는다 — 다른 호출이 섞일 수 있고, BUSY/NOT_LIVE 는 **이전 연산의 이름**으로 찍혀 판정기가 좋은 결과를 덮어쓸 수 있다 | 코드 | `osrdn_mode_engine` 이 클레임을 쥔 채 **사본**을 떠 준다; 엔진이 안 돈 호출은 요청의 op/arg 로 `RDN-R4 skip` 한 줄 |
| 3 | 표지색 `5a5a5a5a` 로 채우면 엔진이 아무것도 안 해도 PASS | `destValue` 가 `*want = arg` | 드라이버·도구 둘 다 거절(`ENG_WHY_MARK_COLOUR`), 시뮬레이터 변이로 판정력 확인 |
| 4 | `f64` 가 목적지 **표면** 첫 64 바이트를 본다 — 채우기·블릿 1–12 에서 엔진이 쓰지 않는 곳이라 Matrox 3-18 을 볼 수 없다 | python: 채우기 사각형 첫 바이트 24 640, 창은 16 384 | 목적지 **사각형** 왼쪽 위 64 바이트로; 시뮬레이터에 "첫 16 픽셀 낡음" 경우와 변이 |
| 5 | flush 쓰기가 FIFO 로 들어가면 BUSY 를 flush 시작 전에 0 으로 읽을 수 있다 | 논리(xf86 도 같은 모양) | flush 뒤 유휴 대기 한 번 더(`idle2`, 넘치면 걸쇠); 시뮬레이터가 큐에 든 flush 를 흉내 내고 그 대기를 뺀 변이가 FAIL |
| 6 | 게이트가 거절한 `RECORD` 는 읽은 값을 버린다(`RB3D_CNTL ≠ 0` 의 "멈추고 묻기" 에 필요한 값) | `osrdn_modelog.m` | 게이트 거절이면 `RECORD` 는 읽은 값을 찍는다 |
| 7 | 도구가 첫 글자만 본다(`engine flip 0` 이 채우기), 빈 문자열·`-1` 이 숫자로 통과 | `rdnr2b0.m` | 낱말 전체 `strcmp`, 빈 인자·부호 거절 |
| 8 | 도구 둘을 동시에 돌리면 PLL 색인이 섞일 수 있다(로그 값만 틀림); 걸쇠 뒤에도 `modeFinish` 가 화면 레지스터는 쓴다(엔진 범위 밖) | 코드 | 절차: **도구는 한 번에 하나**, 어느 줄이든 `latched=1` 이면 12-5 의 순환(5 단계)을 **건너뛴다** |
| 9 | runid 가 엔진 요청에 없다(부팅 nonce 와 `n=` 로만 묶인다), 게이트가 `osrdn_peek` 대신 직접 읽는다 | 코드 | 기록만 — 효과 같음 |

재실행: `sim_r4` 변이 24 전부 의도한 경우로 FAIL, `sim_r2b` PASS(세계 24, R4 변이 3), `check_r4_src`·`check_engine` PASS.

## 16. 첫 실기 빌드의 역어셈블 게이트 실패와 고침 (2026-09-18, stamp `7652a0e7`, runid 789705506)

- 실기 빌드 PASS(커널 심볼 16 개, 새 것은 `_page_size`).  **역어셈블 게이트 FAIL**: `__text` 의 `0x17d8–0x1824` 69 바이트가
  어느 심볼에도 속하지 않음 — **설치 전에 멈췄다**(게이트가 제 일을 했다).
- 원인: 그 바이트는 `osrdn_record.m` 의 `static elapsedUs` 였다.  엔진 단위에 **같은 이름의 `static elapsedUs`** 를 또 만들었고,
  게이트(`tools/r2a/check_reloc.py` `function_ranges`)가 코드 범위를 **이름을 키로** 모아 하나가 덮였다.  코드 결함은 아니지만
  이름이 겹치면 게이트의 판정이 흐려진다.
- 고침: 엔진 쪽을 `engElapsedUs` 로; `check_reloc_r2b0.py` 가 **같은 이름의 코드 심볼 둘이면 이름을 대고 실패**(자체 시험에 발동
  증명, 이번 reloc 에서 `_elapsedUs` 를 이름으로 잡음); 호스트에서 먼저 막도록 `check_r4_src.py` 에 `r4-unique-names`(변이 포함).

## 17. 첫 실기 부팅 `027d9173`: `RECORD` 가 멈춘 곳과 operator 결정 (2026-09-18)

- 부팅 판정 PASS(`check_select`: 800×600 RGB:888/32, R3 그대로).  별칭 `ok`, 창 시작 `0x29e000` = 2 744 320 = 11-2 표의 800×600 값.
- `engine record` → **게이트가 `ENG_WHY_RB3D` 로 거절**(엔진 쓰기 0 회).  `RB3D_CNTL = 0x00001800`.  나머지는 12-5 의 기대 그대로:
  `RBBM_STATUS 00000140`(FIFO 64·유휴), `CP_CSQ_CNTL 02010080`(CP 꺼짐), dest cache 둘 다 `00000000`.
- `0x1800` = `RADEON_COLOR_FORMAT_ARGB8888`(6 << 10) — **3D 색 버퍼 형식 필드뿐**이고 3D 기능을 켜는 비트(0–9: 블렌드·평면 마스크·디더·
  반올림·ROP·스텐실·Z·깊이 오프셋, 14: CLRCMP_FLIP)는 **모두 0**(xf86 `radeon_reg.h`·NetBSD `radeonfbreg.h` 의 `RB3D_CNTL` 비트 정의,
  python `6 << 10 = 0x1800`).
- **operator 결정: 참고 구현처럼 `RB3D_CNTL = 0` 을 쓴다**(9-2 #4 의 "멈추고 묻기" 에 대한 답).  구현:
  - 게이트는 `RB3D_CNTL` 로 거절하지 않고 값을 기록만 한다;
  - 채우기·블릿의 쓰기 묶음 **맨 앞**에 `RB3D_CNTL = 0`(유휴 확인 뒤, FIFO 칸 수에 포함: 채우기 12, 블릿 13) — xf86 `RADEONEngineInit`,
    NetBSD `radeonfb_engine_init` 이 초기화에서 쓰는 것과 같은 값;
  - **복원하지 않는다**(참고 구현도 복원하지 않는다; VGA 경로는 3D 를 쓰지 않고, 재부팅하면 BIOS 가 다시 설정).  원래 값은 `RECORD` 와 로그에 남는다;
  - `RB3D_CNTL` 은 쓰기 허용 목록으로 옮기되 **0 으로만** 쓸 수 있다는 규칙(`check_r4_src`), 가짜 카드는 3D 가 켜진 채 실행되면 실패 기록.
- 반영 빌드: check-all PASS → stamp **`937ebd28`**, runid 789707076 → 실기 빌드 PASS → 역어셈블 게이트 PASS(`engFillBatch` 9 + `engClip` 3 = 12,
  `engBlitBatch` 10 + 3 = 13 — 소스와 일치) → `closed=yes fresh live` 설치.  `sim_r4` 변이 24(새 변이 "RB3D_CNTL 을 0 으로 안 씀" 은
  가짜 카드가 "RB3D_CNTL 00001800 인 채 실행" 으로 잡음), `check_r4_src` 에 "RB3D_CNTL 은 0 으로만, 묶음 맨 앞" 규칙.

## 18. R4a/R4b 실기 결과 — 부팅 `e91d6ef1`, build `937ebd28` (2026-09-18): **PASS**

기록 `build/r4/e91d6ef1/rdn-all.log`, 판정 `python3 tools/r4/check_engine.py build/r4/e91d6ef1/rdn-all.log 937ebd28` → **PASS**.

- 부팅 판정 `check_select` PASS(800×600 RGB:888/32, R3 동작 그대로).  별칭 `ok`, 창 시작 `0x29e000`(= 11-2 표의 800×600 값).
- **`RECORD`**: `RBBM_STATUS 00000140`, `CP_CSQ_CNTL 02010080`, dest cache 둘 `0`, `SURFACE_CNTL 00000100` — 12-5 의 기대 그대로.
  `RB3D_CNTL 00001800`(형식 필드만, 17 절), **`DEFAULT_SC_BOTTOM_RIGHT 00000000`**(기본 가위가 0 — 연산마다 `0x1fff1fff` 를 쓰지 않았다면
  모든 그리기가 잘렸다; 가짜 카드의 "BIOS 가 작게 남긴 가위" 가 실제였다), `RB2D_DSTCACHE_MODE 00000f00`(비트 8–11, 참고 헤더에 정의 없음,
  기록만), 클럭 `SCLK_CNTL 00007ffa`·`SCLK_MORE_CNTL 000a0607`·`CLK_PWRMGT_CNTL 00011100`(비트 12 `ENGIN_DYNCLK_MODE` 켜짐 — 참고들도 BIOS
  상태 그대로 2D 를 쓴다).
- **채우기** `deadbeef`·`0`: 불일치 0(사각형 8 000 픽셀), 사각형 밖·가드·미끼 불변 → **엔진은 `DST_PITCH_OFFSET` 을 읽는다**(미끼 불변),
  오프셋 필드가 VRAM 오프셋으로 동작, 보이는 화면 무사.  유휴까지 판정 2 회, 연산 전체 약 103 ms.
- **블릿 0–8**: 전부 불일치 0 — 다른 표면 복사와 **겹침 8 방향**(대각 넷, 가로 둘, 세로 둘) 모두 NetBSD 방향 규칙대로 맞다.
- **일부러 틀린 방향(9–12)**:

| 경우 | 불일치 | 해석(python) |
|---|---:|---|
| 9: 가로 +8, X 틀림 | **16** | 첫 불일치 S1 (x 96, y 76) — 목적지 오른쪽 끝 8 열 × 2 행.  픽셀 단위 모형은 3 584, 행 버퍼 모형은 0 → **엔진이 원본을 거의 한 행씩 버퍼링**, X 오류는 드물게만 드러난다 |
| 10: 가로 −8, X 틀림 | **0** | 이 방향에서 **X 는 판정 불가**(버퍼가 덮는다) — PASS 로 세지 않음 |
| 11: 세로 +8, Y 틀림 | 3 328(81.2 %) | Y 는 판정 가능 |
| 12: 세로 −8, Y 틀림 | 3 136(76.6 %) | Y 는 판정 가능 |

  결론: **Y 방향 규칙은 이 하드웨어에서 결정적으로 확인**, X 방향 규칙은 겹침 가로 복사 두 경우(5·6)가 불일치 0 이고 틀린 X 가 한쪽(9)에서
  드러나므로 **옳은 쪽임이 확인**되나, 버퍼 때문에 X 오류는 늘 보이지는 않는다 — 가로 겹침 복사에서 X 비트를 틀려도 대개 맞게 나오므로
  **이후 가속 코드는 X 비트를 규칙대로 둘 것**(버퍼에 기대지 않는다).
- **대기**: 한도에 걸린 적 없음, 걸쇠 없음, 미끼 레지스터는 매번 복원(`left=0`).
- **같은 부팅의 VGA 복귀 순환**(`RDNR2bCycle`, 엔진을 14 번 쓴 뒤): `checked=1 bad=0 vga=0 palette=0 verdict=0`, 재진입 `live=1` — 엔진 상태가
  바뀐 뒤에도 복귀가 스냅샷 전체를 되돌린다.
- 이 부팅에서 operator 가 화면 이상을 보고하지 않았다(맨 위 줄무늬 없음).

R4a·R4b **완료**.  남은 R4 는 R4c(문자 디바이스 `d_mmap`, 창은 11 절의 Matrox 식, 임대 없음) — 계획서를 따로 쓴다.
