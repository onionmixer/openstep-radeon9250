# R5 — Command Processor: 마이크로코드·PCI GART·첫 명령 (계획, 코딩 전, 교차검토 대상, 2026-09-18)

입력: `PLAN.md` R5, `docs/R5_CP_SEQUENCE.md`(참고 CP 수명주기, 기계 추출), `docs/R5_GART.md`(GART 산술),
`docs/review/Q3_verdict.md`(Q3 판정), R4·R4c 결과.  이 문서는 R5a·R5b·R5c 를 **한 빌드의 연산 여섯 개**로 계획한다.
R5d(실패 주입)는 이 빌드가 PASS 한 뒤 따로 계획한다.

## 0. 한 줄 요약

`IOMallocLow` 64 KiB 블록 하나(물리 연속)에 GART 표·가드 페이지·16 KiB 링을 두고, 참고 순서대로 **writeback 을 끈 채**
마이크로코드를 적재하고 PCI GART 를 켜고 CP 를 시작해, 스크래치 레지스터 `PACKET0` 표지를 레지스터로 직접 되읽는다.
GPU 는 시스템 메모리를 **읽기만** 한다(쓰기 경로 둘 다 끔).  실기에서는 연산을 하나씩 부르고 이상이 보이면 멈춘다.

## 1. 확인한 사실

| # | 사실 | 근거 |
|---|---|---|
| S1 | RV280 은 `R200_cp_microcode`(256 쌍), 적재 = 유휴 대기(참고는 결과 무시) → `CP_ME_RAM_ADDR`=0 → `DATAH=cp[i][1]`, `DATAL=cp[i][0]` | `R5_CP_SEQUENCE.md` 생성표 A `radeon_cp_load_microcode`; 헤더판 = linux-firmware 판(`tools/oracle/check_microcode.py` → IDENTICAL, sha256 `2b7b4bf9…`) |
| S2 | 참고 PCI 초기화 순서: FB 위치 읽기 → GART 창 계산 → 표 구성 → **GART 켬**(`AIC_CNTL`·`AIC_PT_BASE`·`LO`·`HI`, `MC_AGP_LOCATION=0xffffffc0`, `AGP_COMMAND=0`) → 마이크로코드 → 링 초기화 → **엔진 리셋**(PLL `MCLK_CNTL` 강제 켬 포함) → writeback 시험; CP 시작은 별도 | 같은 문서 1 절, 생성표 A `radeon_do_init_cp` 1478–1487 |
| S3 | writeback 을 끄려면 둘 다: `CP_RB_CNTL |= RB_NO_UPDATE`(0x08000000), `SCRATCH_UMSK=0` | Q3 판정 4, `ANALYSIS.md` 9 절 |
| S4 | 이 카드: `MC_FB_LOCATION 1fff0000`(카드 주소 0–512 MiB), **`MC_AGP_LOCATION 27ff2000`(0x20000000–0x27ffffff)**, `CP_CSQ_CNTL 02010080`(모드 0 = 꺼짐), `CP_RB_*` 0, `AIC_CNTL 0`, PCI 명령 `0x0307`(**버스 마스터 켜짐**), `BUS_CNTL.BUS_MASTER_DIS=0` | `docs/R1_RESULT.md` 27·36·44 행; R2a 재확인(`docs/R2A_RESULT.md` 92 행) |
| S5 | 참고 식의 GART 창: `fb_location 0 + fb_size 0x20000000` → `0x20000000`, 4 MiB 내림 그대로, 8 MiB 창이면 `0x20000000–0x207fffff`, 2048 항목, 표 8 KiB — **BIOS 의 AGP 구간과 겹친다**(참고는 GART 를 켤 때 AGP 구간을 `0xffffffc0` 으로 치운다) | python(아래 2 절) |
| S6 | `IOMallocLow`: 한 번에 ≤ 64 KiB, 범프 할당자라 **물리 연속**, 640 KiB 아래 conventional 아레나, 대형 풀 64 KiB 정렬; `IOPhysicalFromVirtual` 로 물리 주소; **이 기계에서 Matrox 가 PCI 버스 마스터 DMA 링으로 실증** | Matrox `docs/S5_HW3D_DMA_FEASIBILITY.md` 3-2·3-3(IDA: `IOMallocLow` 0x1c87e0 → `dma_buf_alloc` 0x18980c → `alloc_cnvmem` 0x18ad9c), `OpenStepMGAReplacementDisplay.m` D1 경로 |
| S7 | 8 KiB VM 페이지는 물리 연속 8 KiB 다: `pmap_enter` 가 VM 페이지 하나에 PTE 두 개를 `phys`, `phys+0x1000` 으로 쓴다 | IDA `_pmap_enter` 0x1908dc–0x19090d(`add edx,1000h` 루프), R4c 계획 F5 |
| S8 | GART PTE = `le32(bus & 0xfffff000)`, 플래그 없음, 4 KiB 단위 | Q3 판정 5, `R5_GART.md` 1 절 |
| S9 | 참고 시작 스트림 8 워드(`ISYNC_CNTL`, `RB3D_DSTCACHE` 퍼지, `RB3D_ZCACHE` 퍼지, `WAIT_UNTIL`), 16 워드로 `PACKET2` 패딩, 커밋 = `WPTR` 쓰기 뒤 `RPTR` 읽기 | `R5_CP_SEQUENCE.md` 생성표 B, 생성표 A `radeon_commit_ring` |
| S10 | R4 의 엔진 게이트는 `CP_CSQ_CNTL` 모드 ≠ 0 이면 거절한다 → CP 가 켜진 동안 MMIO 2D 연산은 저절로 막힌다 | `osrdn_engine.m` `engGate`(`ENG_WHY_CPMODE`) |
| S11 | `RB3D_CNTL` 은 BIOS 값 `0x1800`, R4 는 2D 묶음마다 0 을 쓴다 | `docs/R4_ENGINE_PLAN.md` 17·18 절 |

## 2. 결정 (근거와 함께; 굵은 것은 operator 결정 필요)

### D1. 메모리 = `IOMallocLow` 64 KiB 블록 하나 (PLAN R5b 선택지 (다), 기본안 (가) 에서 바꿈)
- 이유: (가)(일반 wired 페이지)는 `IOMalloc` 의 wired·정렬·물리 조회가 이 커널에서 **미검증**이고, (다)는 같은 기계에서 버스 마스터 DMA 로
  **실증**됐으며 연속이라 표가 단순하다.  64 KiB 는 R5 의 첫 불빛에 충분하다(표 8 KiB + 링 16 KiB).  큰 버퍼가 필요한 R6/M 에서 (가) 를 다시 연다.
- 초기화에서 한 번 잡고 **해제하지 않는다**(Matrox 와 같음 — DMA 가 늦게 닿는 메모리를 돌려주지 않는다).
- 잡은 뒤 4 KiB 마다 `IOPhysicalFromVirtual` → **연속·64 KiB 정렬·16 MiB 아래**를 확인(아니면 R5 전체 거절).  S6 의 연속성 주장을 믿지 않고 잰다.

배치(python, 블록 오프셋):

| 구간 | 오프셋 | 크기 | 내용 |
|---|---|---|---|
| GART 표 | `0x0000` | 8 KiB | 2048 항목(8 MiB 창) |
| 가드 | `0x2000` | 4 KiB | `PACKET2`(0x80000000)로 채움.  링이 아닌 **모든** GART 항목이 여기를 가리킨다; `CP_RB_RPTR_ADDR` 도 여기 |
| 빈칸 | `0x3000` | 4 KiB | 카나리아 |
| 링 | `0x4000` | 16 KiB | GART 항목 0–3 = 호스트 8 KiB 페이지 2 개의 **네 반쪽**.  시작 전 전부 `PACKET2` |
| 카나리아 | `0x8000` | 32 KiB | 위치 부호 패턴, 매 연산 뒤 불변 확인 |

- 링이 GPU 주소 `0x20000000`(창 시작)부터 16 KiB, `CP_RB_CNTL = 0x0804090b`(size_l2qw 11, rptr_update 9, fetch 1, **`RB_NO_UPDATE`**; 참고 1 MiB 식을
  재현하면 `0x40911` — 식 확인).
- **writeback 끔**: `RB_NO_UPDATE` + `SCRATCH_UMSK=0`.  GPU 의 시스템 메모리 쓰기는 없어야 하고, 가드·빈칸·카나리아 불변이 그것을 잰다.

### D2. GART 창 = 참고 식 그대로 (`0x20000000`, 8 MiB)
- 표 항목: 0–3 → 링의 네 4 KiB 물리 페이지, 4–2047 → 가드 페이지.  Linux 는 빈 항목을 0 으로 둬 물리 0 을 가리키게 한다 — 우리는 가드로(엉뚱한 페치가
  무해한 `PACKET2` 를 읽게).
- 표를 쓴 뒤 **전부 되읽어** python 식과 같은지(CPU 쪽).  x86 PCI 버스 마스터는 CPU 캐시를 스누프한다(Matrox D1 이 플러시 없이 동작) — Linux 의
  `wbinvd`(`R5_GART.md` 3-1)는 옮기지 않는다 `[이 칩셋에서 스누프 가정 — R5c 가 판정]`.
- 서피스 레지스터(`SURFACE0_*` 에 표 주소 등록, `R5_CP_SEQUENCE.md` 2-4)는 **옮기지 않는다** — 리틀엔디안에서 바이트 스왑 영역 뿐이고 표는 시스템 메모리다
  (참고와 다름을 기록).

### **D3. `MC_AGP_LOCATION`·`AGP_COMMAND` (operator 결정)**
창이 BIOS AGP 구간과 겹친다(S5).  (가) **참고대로** GART 를 켤 때 `MC_AGP_LOCATION=0xffffffc0`, `AGP_COMMAND=0`, STOP·복귀에서 원래 값으로 되돌린다.
(나) 창을 AGP 구간 밖(`0x28000000`)으로 옮기고 두 레지스터는 건드리지 않는다 — 참고와 다른 배치, MC 가 AGP·GART 창을 어떻게 우선하는지 소스로 미확인.
**권고 (가)**: 참고가 쓴 조합이고, 메모리 컨트롤러 레지스터지만 FB 구간(`MC_FB_LOCATION`)은 건드리지 않는다.  쓰기 전후 값·화면을 로그로 남긴다.

### **D4. 엔진 리셋 (operator 결정)**
참고는 적재·링 초기화 **뒤** `RBBM_SOFT_RESET`(CP 포함 7 비트) + PLL `MCLK_CNTL` 강제 켬·복원을 한다(S2).  R4 는 "엔진 리셋 금지" 로 왔고, 메모리 원칙은
"클럭 레지스터를 라이브로 재프로그래밍하지 말 것" 이다.  CP 는 이번 부팅에 한 번도 켜진 적이 없다(S4).
(가) **리셋 없이** 첫 시도 — CP 가 표지를 처리하지 않으면 멈추고 그때 리셋을 따로 계획.  (나) 참고대로 리셋 포함.
**권고 (가)**: 리셋은 "알려진 상태로" 가 목적인데 이미 알려진 초기 상태(모드 0, 링 0)이고, PLL 쓰기를 새로 들이지 않는다.

### D5. CSQ 모드 = 참고(xf86) `CSQ_PRIBM_INDBM`(0x40000000)
간접 버퍼 패킷을 보내지 않으므로 INDBM/INDDIS 차이는 우리 스트림에 영향이 없다 — 참고값을 쓴다.

### D6. 첫 스트림과 판정
- START: 유휴 확인(FIFO 64 AND ACTIVE 0, 절대 기한) → `CP_CSQ_CNTL = 0x40000000` → 링에 참고 8 워드 + `PACKET2` 8 개 → `WPTR=16` → `RPTR` 읽기 →
  RPTR = 16 이 될 때까지 대기(절대 기한) → 유휴 대기.
- SUBMIT(k): `PACKET0(SCRATCH_REG0..2)` 표지(무작위 씨앗에서 만든 값) 여러 개 + `PACKET2` 패딩으로 16 워드 단위, `WPTR` 전진 → RPTR 따라잡음 →
  유휴 → **`SCRATCH_REGn` 을 MMIO 로 직접 읽어** 표지와 같음.  링 16 KiB = 4096 워드: SUBMIT 을 여러 번 해 **링 감김**과 **네 반쪽 페이지 경계**를
  모두 지나간다(python 으로 몇 번이면 되는지 정한다).
- `PACKET2` 는 완료 판정이 아니다; 판정은 스크래치 레지스터 값 + RPTR 전진 + 유휴 + 카나리아 불변.

### D7. 정지 (STOP, R5d 의 정상 경로)
유휴(절대 기한) → `CSQ_CNTL = 0`(PRIDIS_INDDIS) → `AIC_CNTL &= ~PCIGART_TRANSLATE_EN` → `MC_AGP_LOCATION`·`AGP_COMMAND` 복원(D3 가 (가) 면) →
카나리아·가드 확인.  블록은 해제하지 않는다.  `BUS_CNTL` 은 건드린 적이 없으므로 그대로.
**VGA 복귀(종료·`RDNR2bCycle`) 전에 CP 가 켜져 있으면 같은 정지를 먼저** 한다(모드 모듈의 복귀 경로 앞에 한 줄).

### D8. 걸쇠·대기 (R4 규칙 그대로)
모든 대기는 시간·횟수 둘 다 상한, 기한 연장 없음.  CP 를 켠 뒤 대기가 넘치면 **RAM 에 걸쇠 먼저** → 진단 읽기 하나 → 이후 CP 연산 전부 거절
(STOP 만 한 번 허용: CSQ 끔·GART 끔 시도, 유휴 실패여도).  폴백 없음.

## 3. 연산 (setIntValues `"RDNR5Cp"` {매직, 연산, 인자}, 모드 클레임 안, `noSleep`)

| # | 연산 | 하는 일 | 쓰기 |
|---|---|---|---|
| 1 | RECORD | `CP_CSQ_CNTL`, `CP_RB_BASE/CNTL/RPTR/WPTR/RPTR_ADDR/WPTR_DELAY`, `SCRATCH_UMSK/ADDR`, `SCRATCH_REG0-2`, `AIC_CNTL/PT_BASE/LO/HI`, `MC_AGP_LOCATION`, `AGP_COMMAND`, `BUS_CNTL`, `ISYNC_CNTL`, `RBBM_STATUS`, `CP_ME_RAM_ADDR` 읽기; 블록 물리 주소·연속성 | 없음 |
| 2 | LOAD | 게이트: CSQ 모드 0, 유휴.  `CP_ME_RAM_ADDR=0` → 256 쌍.  부팅당 한 번 | ME RAM |
| 3 | MAP | 게이트: 적재됨, CSQ 0.  표·가드·링(`PACKET2`)·카나리아 쓰고 되읽기(울타리) → D3 → `AIC_PT_BASE`, `LO`, `HI`, `AIC_CNTL |= TRANSLATE_EN` → 링 레지스터(`RB_BASE`, `WPTR_DELAY=0`, `WPTR=RPTR`, `RPTR_ADDR=가드`, `CNTL`, `SCRATCH_ADDR`, `SCRATCH_UMSK=0`) → `ISYNC_CNTL` | GART·링 레지스터 |
| 4 | START | D6 | CSQ, 링 |
| 5 | SUBMIT k | D6, k 번째 표지 묶음 | 링, WPTR |
| 6 | STOP | D7 | CSQ, AIC, (MC_AGP) |

각 연산 뒤 판정 줄 하나(모드 클레임을 푼 뒤 IOLog).  실기 절차는 RECORD → 호스트 검토 → LOAD → MAP → RECORD → START → SUBMIT × n → STOP → RECORD →
`RDNR2bCycle`.  어느 단계든 기대와 다르면 거기서 멈춘다(다음 연산을 부르지 않는다).

## 4. 검사 (호스트, 기준 PASS 와 변이 FAIL 을 같은 실행에서)

1. 가짜 CP(`tools/r5/sim/world5.c`): FIFO·유휴 모형, ME RAM 적재 기록(순서·쌍), GART 번역(표를 읽어 4 KiB 단위), 링 페치(RPTR→WPTR, 감김),
   `PACKET0`/`PACKET2` 실행(다른 패킷은 "모형 밖" 실패), writeback 비트가 켜지면 가드에 rptr 를 쓰는 동작(끄기가 빠지면 카나리아가 잡게).
   변이: 적재 쌍 순서 뒤집기, 유휴 확인 빼기, `RB_NO_UPDATE` 빼기, `SCRATCH_UMSK` 빼기, 표 항목 반쪽 주소 틀리기, 가드 대신 0, 울타리 빼기,
   WPTR 을 16 단위로 안 채우기, 대기 상한 빼기, 걸쇠 뒤 연산 허용, STOP 순서(GART 를 CSQ 보다 먼저 끔), D3 복원 빼기, 복귀 전 정지 빼기.
2. 오라클: `R5_CP_SEQUENCE.md`·`gart_oracle.py` 의 값(PTE, 창, `CP_RB_CNTL`, 시작 스트림)을 시뮬레이터가 기록한 실제 MMIO 순서·메모리와 대조.
3. 마이크로코드: 드라이버에 넣는 표 = 헤더 = 바이너리(`check_microcode.py` 확장).
4. 소스 규칙: CP 레지스터 쓰기는 새 단위만, 금지 레지스터(`RBBM_SOFT_RESET`, PLL, `MC_FB_LOCATION`, `SURFACE_*`, `BUS_CNTL`) 쓰기 0(D4 가 (가) 면),
   블록 해제 0, `IOLog` 는 클레임 밖에서만.
5. 로그 판정기(`check_cp.py`)와 자체 시험, 역어셈블 게이트의 호출자 표, `hostcheck`, `nm -u`(새 심볼 `IOMallocLow`·`IOPhysicalFromVirtual` 을
   `kernel_symbols.py` 로 미리 확인).

## 5. 위험

| 위험 | 완화 |
|---|---|
| 표가 틀려 CP 가 엉뚱한 RAM 을 명령으로 읽는다 → 임의 레지스터 쓰기·행 | 표 전수 되읽기·python 대조, 빈 항목은 `PACKET2` 가드, 링 전체 `PACKET2` 로 시작, 첫 START 는 참고 8 워드뿐 |
| GPU 가 시스템 메모리에 쓴다(writeback 이 안 꺼짐) | 두 비트 모두, 가드·카나리아 불변 확인, 쓰기 대상은 가드뿐 |
| CP 가 멈춰 FIFO·버스가 선다 → 하드 행 | 모든 대기 상한, 걸쇠, 한 번에 한 연산, 하드 행 한 번이면 중단·오프라인 분류 |
| MC 레지스터(D3) | 참고 조합만, 전후 값 로그, 복원 |
| 종료 때 CP 가 켜진 채 | 복귀 전 정지(D7), 실기 절차의 마지막이 STOP |
| conventional 아레나 소진 | 한 번 64 KiB, 실패하면 R5 거절(디스플레이는 그대로) |
| 칩셋이 스누프하지 않아 링 쓰기가 GPU 에 늦게 보임 | 첫 증상은 "RPTR 은 가는데 표지가 옛값" — 판정에서 구분해 기록, 그때 플러시를 계획 |

## 6. 교차검토에 물을 것

1. D1(IOMallocLow 블록) 이 GART·링 요건(정렬, 표 위치, 버스 주소 범위)을 모두 만족하는가.
2. 표 항목·가드 설계, `RPTR_ADDR` 를 가드에 두는 것이 안전한가.
3. D3·D4 권고가 옳은가 — 특히 리셋 없이 CP 가 적재된 마이크로코드로 도는가(참고 순서에서 리셋이 적재 뒤에 오는 이유).
4. D6 판정이 "CP 가 GART 를 거쳐 링을 읽고 실행했다" 를 증명하는가(스크래치 레지스터를 CPU 가 직접 써서 속일 수 없는가).
5. 빠진 레지스터·순서(예: `CP_RB_WPTR_DELAY`, `ISYNC_CNTL`, `WAIT_UNTIL`, `CP_ME_RAM_ADDR` 재설정, `SCRATCH_ADDR` 유효성).
6. 연산 순서와 모드 클레임·VGA 복귀·R4 엔진 연산의 상호작용.

## 7. 교차검토 판정 (2026-09-18 — codex 는 사용량 한도(2026-09-19 19:23 까지)로 실패, 내부 agent 2 건: A 참고 대비 정확성, B 안전·시험.  전 건 원문·python 으로 재확인)

A 가 로컬 트리에 없는 Linux 3.10 KMS 파일을 인용해, 같은 파일을 `tools/fetch-ref.sh` 목록에 넣고 받았다(`linux-3.10/drivers/gpu/drm/radeon/`
`r100.c` sha256 `cb655fe8…`, `radeon_reg.h` `2e0c5121…`, `radeon_asic.c` `c2254825…`) — 인용은 그 사본을 열어 확인했다.

### 7-1. 내가 틀린 것

| # | 틀린 것 | 확인 |
|---|---|---|
| E1 | 걸쇠 뒤 STOP 이 GART 까지 끄게 했다 — 멈춘 CP 가 페치 중이면 번역 없는 `0x20000000` 으로 나가고, `MC_AGP_LOCATION` 을 되돌리면 그 주소는 아무 장치도 응답하지 않는 AGP 구간이다(master-abort, 회수 수단 없음) | Matrox `docs/W11_SECONDARY_DMA_WITHOUT_RECOVERY.md` 1–2 절 |
| E2 | "복귀 경로 앞에 한 줄" 로는 네 경로 중 일부를 놓친다: 커널 복귀(`[super revertToVGAMode]` 가 먼저), 클레임 중 미뤄진 복귀(`osrdn_mode.m` `kernelRevertSeen` → `modeFinish` 의 `modeRevertBody`), 순환, 진입 실패 복귀; 게다가 `modeRevertBody` 는 모드가 살아 있지 않으면 곧 반환한다 | `osrdn_mode.m` 1197–1199, 1288–1291, 970–973, 1028–1032, 1357 |
| E3 | 모드 진입 게이트가 CP 모드·GART 켜짐을 거절한다 — 정지되지 않은 CP 에서 `RDNR2bCycle` 은 복귀만 하고 재진입을 거절당해 VGA 로 남는다 | `osrdn_mode.m` 316–318(주석 "R5 에서 다시"), 323–327 |
| E4 | 16 워드 SUBMIT 으로는 링 한 바퀴에 255 번이 필요하고, 1024 워드 경계를 **넘는 패킷이 생기지 않는다** | python |
| E5 | `RPTR_ADDR` 를 가드에 뒀다 — writeback 이 실수로 켜지면 모든 엉뚱한 페치가 읽는 페이지를 GPU 가 쓴다 | FreeBSD `radeon_cp.c:745-747`(GPU 주소), B 의 예: rptr 0x10 이 `PACKET2` 를 `PACKET0(0x0040)` 로 바꿈 |
| E6 | MAP 의 "되읽기(울타리)" 는 시스템 RAM 에는 울타리가 아니다(CPU 자기 시야); 스누프가 안 되면 증상은 "옛 표지" 가 아니라 **PTE 0 → 물리 페이지 0(실모드 인터럽트 벡터)을 명령으로 실행** | `IOMallocLow` 는 0 으로 채운다(Matrox S5 3-2 `bzero`) |
| E7 | 판정(스크래치 값)이 CPU 쓰기와 구분되지 않는다 — KMS 링 시험은 CPU 가 먼저 센티넬을 쓴다 | KMS `r100.c:3619-3634`(`0xCAFEDEAD` → `PACKET0(scratch)`, `0xDEADBEEF`) |

### 7-2. 채택 (8 절 명세에 반영)

| 지적 | 판정 | 근거(이 세션에서 연 곳) |
|---|---|---|
| A1·B7 `AIC_CNTL.DIS_OUT_OF_PCI_GART_ACCESS`(비트 1) 로 창 밖 요청을 버린다; 끌 때 비트는 두고 `TRANSLATE_EN` 만 내리고 `LO=HI=0` | ✅ | KMS `r100.c:641-672`(주석 "discard memory request outside of configured range"), RV280 = `r200_asic` `radeon_asic.c:1955-1956` |
| A1 D3 (나) 는 선례가 없다 — 두 참고 모두 PCI GART 전에 AGP 구간을 치운다 | ✅ D3 권고를 (가) 로 좁힌다(operator 확인은 그대로 받는다).  값은 **FreeBSD 의 `0xffffffc0`**(KMS 는 `0x0FFFFFFF` 에 `AGP_BASE`/`AGP_BASE_2` 도 0 — 서로 다르다; 우리 기준은 FreeBSD).  `AGP_BASE`(0x0170)·`AGP_BASE_2`(0x015c)는 RECORD 만 | FreeBSD `radeon_set_pcigart`(생성표 A 1065–1066), KMS `r100.c:3808-3812`, 헤더 `radeon_drv.h:758-760` |
| A2 D4 근거: 리셋은 ME RAM 을 지우지 않는다(참고의 CP 정지가 엔진 리셋을 부르고, X 는 다시 싣지 않고 CP 를 시작); KMS 는 적재 뒤 리셋 없이 링·CSQ 로 간다 | ✅ D4 권고 (가) 의 근거로 | FreeBSD `radeon_cp.c:1676-1684`, xf86 `radeon_driver.c:5966`·`6008`, `radeon_accel.c:148-152`, KMS `r100.c:1104-1182` |
| A3 `CP_CSQ_MODE`(0x0744): KMS 는 쓰고 FreeBSD 는 안 쓴다 | ⚖️ **FreeBSD 대로 쓰지 않고 RECORD 만**; `CP_CSQ_STAT`(0x07f8)·`AIC_STAT`(0x01d4) 도 RECORD | KMS `r100.c:1175-1181`, `radeonfbreg.h:3234` |
| A5·B11 센티넬: SUBMIT 앞에 CPU 가 REG0–2 에 표지와 다른 센티넬을 쓰고 되읽고(CP 유휴·RPTR==WPTR 일 때만), 그다음 WPTR; 표지는 커널이 씨앗에서 만들고 재사용 거절, 판정기는 씨앗으로 다시 계산 | ✅ | 위 E7 |
| A6 CP 클럭: 실측 `SCLK_CNTL 0x7ffa` 에 `FORCE_CP`(비트 16) **꺼짐** — KMS 는 켜고 FreeBSD 는 안 켠다 | ⚖️ **operator 결정 D9**(PLL 쓰기) — 권고: 쓰지 않는다(FreeBSD), CP 가 페치하지 않으면 그때 따로 | python 비트 분해, xf86·NetBSD·KMS 헤더 `SCLK_FORCE_CP (1<<16)` |
| A7·B5 `RPTR_ADDR`·`SCRATCH_ADDR` 는 GART 주소, 가드가 아닌 **빈칸 페이지**(블록 `0x3000`, GART 항목 4)로 | ✅ | E5 |
| A9 창 8 MiB 가 xf86 조건 충족, 표 정렬 충분; 감김에서 `WPTR` 은 4096 이 아니라 0 | ✅(시뮬레이터 경우 추가) | xf86 `radeon_dri.h:42`, FreeBSD `radeon_cp.c:2116`(`ring.tail &= tail_mask`; 처음에 검토자의 1383 행을 열지 않고 옮겼다 — 그 줄은 `DRM_DEBUG`) |
| A9 GART 는 TLB 한 항목을 캐시하고 플러시가 없다 → 번역이 켜진 동안 표를 바꾸지 않는다 | ✅ 규칙 | KMS `r100.c:639-644` |
| B1 걸쇠 뒤 STOP 은 **`CSQ_CNTL=0` 쓰기 하나 + `RBBM_STATUS` 읽기 하나**, GART·MC 는 그대로(블록은 해제하지 않으므로 모든 항목이 계속 응답하는 메모리) | ✅ | E1 |
| B2 CP 정지를 `modeRevertBody` **맨 앞**(모드가 살아 있는지 보기 전)과 `[super revertToVGAMode]` 앞(클레임 안)에; STOP 연산은 NOT_LIVE 게이트 없이; 미뤄진 복귀 경로를 시뮬레이터로 | ✅ | E2 |
| B3 CP 상태 기계 NONE/LOADED/MAPPED/RUNNING/STOPPED/LATCHED; `osrdn_mode_cycle` 은 NONE·STOPPED(깨끗) 가 아니면 **복귀 전에** 거절; 걸쇠면 그 부팅은 모드 변경 없이 재부팅 | ✅ | E3 |
| B4 SUBMIT 에 길이 인자(16 의 배수, ≤ 4080), 8 번 일정(1 바퀴: 1024 × 4 로 경계 셋과 감김을 **가로지름**, 2 바퀴: 1008·1024·1024·1024 로 WPTR 이 정확히 1024·2048·3072·0), 경계를 가로지르는 `PACKET0` 는 머리와 데이터가 다른 페이지 | ✅ | python(E4) |
| B6 가드와 링의 빈 곳을 `0x0000057d, 0x80000000`(`PACKET0(SCRATCH_REG5)`, 데이터) 쌍으로 — 어느 정렬로 읽어도 REG5=0x80000000; MAP 이 REG5 에 독을 쓰고 매 연산이 확인 → 엉뚱한 페치가 **보이면서** 무해 | ✅ | `radeon_drv.h:813`(`SCRATCH_REG0 0x15e0`) → REG5 0x15f4, python `PACKET0` = 0x57d |
| B8·E6 표·링을 쓴 뒤 **`wbinvd`**(참고 Linux, `R5_GART.md` 3-1) + 잠긴 연산 + MMIO 읽기로 직렬화하고 나서 `TRANSLATE_EN`·각 `WPTR`.  Matrox D1(같은 기계, 플러시 없이 동작)을 스누프의 보조 근거로 기록 | ✅ | 위 |
| B9 깨끗한 STOP: `CSQ=0` 뒤 유휴·`RPTR==WPTR`·`CP_CSQ_STAT` 비움 확인 → 그다음에만 번역 끔; 하나라도 실패면 걸쇠(B1 경로) | ✅ | — |
| B10 R4 연산은 CP 상태가 NONE·STOPPED(깨끗)일 때만, CP 연산은 엔진 걸쇠가 없을 때만; CP 걸쇠는 자기 필드 | ✅ | `osrdn_engine.m` 262–265(엔진 게이트는 모드 비트만 본다) |
| B11 음성 대조 연산(WPTR 쓰기만 뺀 SUBMIT → 스크래치 불변), 소스 규칙(스크래치 레지스터 CPU 쓰기는 독·센티넬 함수만), 매 연산 뒤 링 전체를 호스트 쪽 사본과 대조 | ✅ | — |
| B12 블록 할당은 새 키(기본 꺼짐) 뒤에서만; 물리 주소는 `< 0xA0000` | ✅ | Matrox S5 3-2(아레나 = conventional) |
| B13 변이·모형 추가(목록 그대로) | ✅ | — |
| B14 절차: 연산마다 클레임 **전** "begin op= runid=" 한 줄, `sync`, 한 번에 도구 하나, R4c 도구 안 돌림; START 는 MAP 레지스터 되읽기를 **드라이버가** 게이트(`RB_CNTL 0804090b`, `UMSK 0`, `PT_BASE`, `LO/HI`, AIC 비트 0·1, `RB_BASE 20000000`, `RPTR==WPTR==0`, `GEN_INT_CNTL 0`); 호스트가 2048 PTE 를 물리 주소에서 다시 계산해 MAP 의 합계와 대조; 걸쇠면 도구는 고유 코드로 "더 부르지 말 것, 순환 금지, 재부팅" | ✅ | — |
| B15 START: 링을 쓰고 직렬화 → CSQ → 마지막에 WPTR | ✅ | — |
| B16·B17 RECORD 에 `RB3D_COLOROFFSET`·`RB3D_DEPTHOFFSET`·`GEN_INT_CNTL/STATUS`·`AGP_COMMAND`(맨 뒤) | ✅ | — |
| B18 D4 (가) 에서 첫 START 의 걸쇠가 가장 그럴듯한 실패이고 그러면 그 부팅은 재부팅으로 끝난다 — 미리 적는다 | ✅ | — |

## 8. 개정 명세 요약 (7 절 반영 — 2·3·5 절과 충돌하면 이 절이 이긴다)

- **키** `"RDN CP Test" = "Yes"`(기본 꺼짐)일 때만 블록 할당·CP 연산.  블록 물리 주소는 연속·64 KiB 정렬·`< 0xA0000`.
- **배치**: 표 `0x0000`(8 KiB), 가드 `0x2000`(`0x57d, 0x80000000` 쌍), 빈칸 `0x3000`(GART 항목 4 — `RPTR_ADDR = 0x20004000`, `SCRATCH_ADDR = +32`, 카나리아),
  링 `0x4000`(항목 0–3, 빈 곳은 가드와 같은 쌍), 카나리아 `0x8000`.  항목 5–2047 → 가드.
- **MAP**: 표·가드·링·카나리아 쓰기 → `wbinvd` → 잠긴 연산 → MMIO 읽기 → `MC_AGP_LOCATION=0xffffffc0`, `AGP_COMMAND=0`(D3 (가), 앞값 저장) →
  `AIC_CNTL |= DIS_OUT_OF_PCI_GART_ACCESS` → `LO`, `HI`, `PT_BASE` → `AIC_CNTL |= TRANSLATE_EN` → 링 레지스터 → `SCRATCH_UMSK=0` → `ISYNC_CNTL` →
  REG5 독 → **되읽기 게이트**(B14) → 상태 MAPPED.
- **START**: 링 쓰기(참고 8 워드 + 패딩) → 직렬화 → `CSQ_CNTL=0x40000000` → `WPTR` → RPTR 따라잡음·유휴(절대 기한) → REG5 불변 → RUNNING.
- **SUBMIT(len, seed)**: 유휴·`RPTR==WPTR` → CPU 센티넬을 REG0–2 에 쓰고 되읽기 → 링에 표지 패킷(REG0 은 경계 앞, REG1 은 경계를 가로지르는 패킷,
  REG2 는 뒤) + 가드 쌍 채움 → 직렬화 → `WPTR` → 따라잡음·유휴 → REG0–2 = 표지, REG5 불변, 링 사본·카나리아 불변.  **NEGCTL**: 같은 준비에서 `WPTR` 만
  빼고 → REG0–2 = 센티넬 그대로.
- **STOP(깨끗)**: 유휴 → `CSQ=0` → 유휴·`RPTR==WPTR`·`CSQ_STAT` 비움 → 번역 끔(비트 1 은 둔 채)·`LO=HI=0` → `MC_AGP_LOCATION`·`AGP_COMMAND` 복원 →
  STOPPED.  **STOP(걸쇠)**: `CSQ=0` 하나, `RBBM_STATUS` 읽기 하나, 끝.
- **복귀 경로**: CP 가 MAPPED·RUNNING 이면 `modeRevertBody` 맨 앞과 커널 복귀의 `[super …]` 앞에서 깨끗한 STOP(실패면 걸쇠 STOP).
  `osrdn_mode_cycle` 은 NONE·STOPPED 가 아니면 복귀 전에 거절.  R4 연산도 같은 조건.
- **operator 결정**: D3(권고 (가)), D4(권고 (가) 리셋 없음), D9 `SCLK_CNTL.FORCE_CP`(권고: 쓰지 않음).

## 9. operator 결정 (2026-09-18)과 그 결과

| # | 결정 | 이 계획에서 |
|---|---|---|
| D3 | **참고대로 AGP 구간을 치운다** | MAP 에서 `MC_AGP_LOCATION=0xffffffc0`, `AGP_COMMAND=0`(앞값 저장), 깨끗한 STOP 에서 복원.  걸쇠 STOP 에서는 건드리지 않는다(7-2 B1) |
| D4 | **참고대로 엔진 리셋을 포함한다**(권고와 다름) | 아래 9-1 의 RESET 연산 |
| D9 | `SCLK_CNTL.FORCE_CP` 는 쓰지 않는다 | RECORD 에서 읽기만 |

### 9-1. RESET 연산 (FreeBSD `radeon_do_engine_reset` 그대로 — 금지 2)

위치: 참고 순서 "적재 → 링 초기화 → 엔진 리셋" 을 따라 **MAP 뒤·START 전**, 별도 연산(실기에서 한 단계씩 보기 위해).  게이트: CP 상태 MAPPED,
CSQ 모드 0, 유휴(FIFO 64 AND ACTIVE 0).  순서(`radeon_cp.c:1676-1684` 가 부르는 같은 함수, 본문은 이 세션에서 연 628–691 행):
1. 픽셀 캐시 플러시: `RB3D_DSTCACHE_CTLSTAT |= 0xf`(읽고 OR), `BUSY` 해제 대기(상한).
2. `CLOCK_CNTL_INDEX` 저장, PLL `MCLK_CNTL`(0x12) 읽기.
3. PLL `MCLK_CNTL = 저장값 | 0x003f0000`(FORCEON MCLKA·MCLKB·YCLKA·YCLKB·MC·AIC).
4. `RBBM_SOFT_RESET` 저장 → `| 0x7f`(CP·HI·SE·RE·PP·E2·RB) 쓰기 → 읽기 → `& ~0x7f` 쓰기 → 읽기(참고 그대로, 대기 없음).
5. PLL `MCLK_CNTL = 저장값`, `CLOCK_CNTL_INDEX = 저장값`, `RBBM_SOFT_RESET = 저장값`.
6. `WPTR = RPTR`(`radeon_do_cp_reset`).
그 뒤(창 밖에서만) 로그용 읽기: `MCLK_CNTL`, `CLOCK_CNTL_INDEX`, `RBBM_SOFT_RESET`(금지 9 — 리셋 레지스터는 게이트가 아니라 기록), `RBBM_STATUS`,
그리고 **MAP 레지스터 되읽기 게이트를 다시**(리셋이 GART·링 레지스터를 지웠으면 START 는 거절 — 참고 KMS 는 리셋 뒤 링을 다시 쓰지 않으므로 지워지지
않는다고 예상하나 확인한다).  MMIO 2D 상태(R4)는 리셋으로 사라져도 R4 연산이 매번 전부 쓴다.

- **PLL 접근**: 우리 접근자(`osrdn_pll_get/put`, R0-2 규칙대로 `PLL_DIV_SEL` 보존).  FreeBSD `RADEON_WRITE_PLL` 은 인덱스에 `(addr & 0x1f) | PLL_WR_EN` 을
  통째로 써 `PLL_DIV_SEL` 을 덮고 5 단계에서 인덱스를 되돌린다 — 끝 상태는 같고, 중간에 픽셀 PLL 선택을 흔들지 않는 쪽을 택한다(기록).
- **금지 1 의 예외(operator 결정)**: 살아 있는 WindowServer 밑의 PLL 쓰기.  범위를 좁힌다 — `MCLK_CNTL` 의 FORCEON 여섯 비트만 켜고 같은 연산 안에서
  원래 값으로 되돌린다, 분주값·픽셀 PLL 은 건드리지 않는다.  리셋 비트에 디스플레이 비트는 없다(CP·HI·SE·RE·PP·E2·RB).
- 시뮬레이터: 순서 전체를 기록과 대조(창 안에 끼운 접근이 있으면 실패), 변이 — 복원 빼기, FORCEON 을 분주 비트로, 인덱스 복원 빼기, 리셋 비트에
  다른 비트, 리셋 뒤 MAP 게이트 빼기, RESET 을 CSQ 가 켜진 상태에서 허용.

### 9-2. 연산 순서 (최종)

RECORD → (호스트 검토) → LOAD → MAP → RESET → RECORD → START → SUBMIT × 8(7-2 B4 일정) → NEGCTL → STOP → RECORD → `RDNR2bCycle`.
각 단계 앞에 `sync`, 각 연산 앞에 "begin" 줄, 이상이면 그 자리에서 멈춘다.  걸쇠면 더 부르지 않고 순환도 하지 않으며 operator 재부팅.

## 10. 구현 기록 (호스트, 2026-09-18)

### 10-1. 만든 것
- `osrdn_cp.h/.m`: 연산 여덟(RECORD·LOAD·MAP·RESET·START·SUBMIT·NEGCTL·STOP), 상태 NONE→LOADED→MAPPED→RUNNING→STOPPED, 걸쇠(RAM 먼저),
  블록 배치·PTE(`osrdn_cp_pte`)·표지(`osrdn_cp_marker`), 링 사본(`cpShadow`), 매 연산 뒤 블록 전체 대조, `osrdn_cp_quiesce`·`osrdn_cp_allows_mode`.
- `osrdn_cp_ucode.h`: `tools/r5/gen_ucode.py` 가 FreeBSD `radeon_microcode.h` 에서 AMD 고지와 함께 생성, `--check` 가 linux-firmware `R200_cp.bin` 과 적재
  순서로 대조(변이 4).
- `osrdn_cpu.h/.m`: `wbinvd` 와 잠긴 교환 — 시뮬레이터가 대신할 수 있게 따로.
- `osrdn_mode.h/.m`: `mode->cp`, `modeRevertBody` 맨 앞의 `osrdn_cp_quiesce`, 순환의 CP 거절(클레임 뒤, 복귀 전, `MODE_WHY_CP`), 엔진 진입점의 `ENG_RC_CP`,
  `osrdn_mode_cp`(STOP·RECORD 는 모드 없이도).
- `OSRDNDisplay.m`: 키 `"RDN CP Test"`, `-cpBlock`(4 KiB 마다 `IOPhysicalFromVirtual`, 연속·64 KiB 정렬·640 KiB 아래, 실패면 돌려줌, 성공이면 영원히),
  매개변수 `"RDNR5Cp"` {매직 `R5C0`, 연산, 씨앗, 길이}, 클레임 **전** "begin" 줄.  번들 표 두 곳에 키.
- 도구 `tools/r5/rdnr5cp.m`(연산 하나씩, 씨앗은 runid 에서), 실기 빌드 스크립트 세 번째 도구·`rdnr5cp.sum`, 묶음.
- 로그 `osrdn_cp_lines`(머리·상태·rec 6 줄·reset·marks·got·ptrs·block·wait).

### 10-2. 검사 (모두 기준 PASS 와 변이 FAIL 을 같은 실행에서)

| 검사 | 기준 | 변이 |
|---|---|---|
| `sim_r5.py`(가짜 CP: ME RAM 대조, GART 번역, GPU 시야는 `wbinvd` 때만 갱신, 링 페치·패킷 실행, writeback, AGP 겹침, CSQ 켠 채 GART 끔 금지) | 9 묶음: 절차 전체, 리셋 펄스 그대로·복원 셋, 두 바퀴·경계 셋·감김, 음성 대조, 걸쇠(STOP 은 CSQ 쓰기 하나), 리셋 전 START 거절, 리셋 뒤 GART 재확인, 엉뚱한 페치(START 중·SUBMIT 중·판정 뒤), GPU 의 링 쓰기, quiesce, 얼어붙은 시계 | 34(동치 하나는 불변식 확인으로 대체 — 걸쇠는 RUNNING 에서만 선다) |
| `sim_r2b.py`(모드 모듈 쪽) | 모드 없을 때 복귀도 CP 정지, 미뤄진 복귀가 `modeFinish` 에서 정지·잠들지 않음, 순환·엔진 거절, STOP 은 모드 없이 | +7 |
| `check_r5_src.py` | 규칙 9(오프셋 = FreeBSD/KMS 헤더, CP 레지스터는 이 단위만, 금지 레지스터, 조용함, 걸쇠 STOP, 스크래치 쓰기, 블록 해제, 울타리, 표) | 13 |
| `gen_ucode.py --check` | 생성물 = 재생성, 적재 순서 = 바이너리 | 4 |
| `check_cp.py --self-test` | 드라이버 IOLog 형식 대조, PTE 합·표지·경계를 독립 계산 | 13 |
| `hostcheck` | 새 단위 셋·도구 엄격 C89, 커널 심볼 17(새 넷: `IOMallocLow`·`IOFreeLow`·`IOPhysicalFromVirtual`·`IOVmTaskSelf`, 모두 export) | — |
| `check_reloc_r2b0.py` | CP 호출자 표, 필수 간선 넷(`cpLoad`·`cpMclkPut`·`cpStopLatched`·`cpMapGate`) | 자체 시험 |
| `check_target_r2b0.py` | 세 번째 도구 컴파일 실패 분기 | — |

### 10-3. 구현 중 잡은 것
- **반환값 혼동**(내 결함): `CP_RC_RAN` 이 0 인데 연산 함수가 게이트 헬퍼의 0 을 그대로 돌려 **거절이 "실행됨" 으로 보고될 뻔했다**; `cpPrepare` 는 게이트 실패(1)를
  성공으로 읽었다.  연산용 `cpRefused`(= `CP_RC_REFUSED`)로 가르고, `cpPrepare` 는 준비되면 `CP_RC_RAN` 을 돌려주게 바꿨다.  코드를 다시 읽다가 찾았다.
- **링 사본이 선언보다 앞에서 쓰임**, **GPU 의 링 쓰기를 세기만 하고 실패로 걸지 않음**(시뮬레이터가 잡음), START 가 REG5 를 보기만 함(계획은 "REG5 불변 → RUNNING").
- 시뮬레이터 모형: CP 가 움직이지 않은 상태 읽기에도 writeback 을 흉내 냈다; 기대값: 씨앗 규칙은 "직전" 재사용 거절인데 두 번 전 것을 썼다.
- 변이 넷이 빠져나갔다 — 리셋의 32 비트 인덱스 복원(뒤의 로그 코드가 바이트를 되돌려 겉보기 같음 → 기록 순서로 확인), 독 확인·실패 걸쇠(서로 가림 →
  각각만 보이는 경우 추가), 걸쇠의 모드 거절(구조상 동치 → 불변식으로).
- 소스 규칙의 헤더 파서가 `(1 << 1)` 을 1 로 읽었다; `rec%d` 형식 이름.
- 기존 변이 닻이 둘이 됨(CP 진입점의 `noSleep` 줄) → 주석으로 구분하고 CP 쪽 변이 추가.

## 11. 실기 전 코드 검토 판정 (2026-09-18, 내부 agent 1 건 — codex 한도.  전 건 원문 확인)

블로커 없음 — GPU 가 블록 밖을 읽거나 시스템 메모리를 쓰는 경로를 찾지 못했다(검토자가 PTE·창·writeback 비트·순서·시작 스트림·리셋 펄스를 대조).

| # | 지적 | 판정 | 확인·조치 |
|---|---|---|---|
| 1 | 판정이 틀린 START·SUBMIT·NEGCTL 이 `CP_RC_RAN` 으로 돌아가 도구가 exit 0 | ✅ | `CP_RC_CHECK_FAILED`(6) — 이 연산이 `failed` 를 세웠을 때; `setIntValues` 는 `IO_R_IO`, 도구 exit 6.  시뮬레이터 기대값 셋을 바꾸고 변이 "실패한 SUBMIT 이 성공으로" 추가 |
| 2 | 깨끗한 STOP 이 `CP_CSQ_STAT` 을 판정하지 않고, 값이 로그에 안 나간다 | ✅ | 필드 정의(주 큐 rptr 비트 0–7, wptr 8–15)는 NetBSD `radeonfbreg.h`·xf86·KMS 세 헤더가 같다(이 세션에서 연 3234–3238 행 등).  다르면 걸쇠 STOP(`CP_WHY_CSQ_QUEUE`), 값은 state 줄 `csqstat=`.  시뮬레이터 경우·변이 |
| 3 | 커널 복귀가 CP 정지보다 먼저 `[super revertToVGAMode]` | ✅ | `osrdn_mode_cp_stop`(클레임 → quiesce → `modeFinish`)을 super **앞**에; 클레임이 잡혀 있으면 그 주인의 `modeFinish` 가 정지 |
| 4 | CSQ 가 켜진 뒤의 센티넬 FIFO 대기가 `PRE_TIMEOUT` | ✅ | 걸쇠로.  시뮬레이터에 "게이트 뒤 FIFO 가 막힘" 손잡이와 변이 |
| 5 | RESET·MAP 이 쓰기 **뒤**의 실패를 `PRE_TIMEOUT`·`REFUSED`("아무것도 안 씀") 로 | ✅ | `CP_RC_POST`(7) |
| 6 | 걸쇠 뒤 RECORD 가 PLL 인덱스 바이트를 쓴다 | ✅ | 걸쇠면 PLL 읽기를 건너뛴다(값 `ffffffff`) |
| 7 | PLL 접근자가 참고에 없는 인덱스 바이트 쓰기 둘을 더한다(WR_EN 내림) | 기록만 | 펄스(쓰기–읽기–쓰기–읽기) 안이 아니고, 9-1 이 우리 접근자(`PLL_DIV_SEL` 보존)를 택했다 — "verbatim" 은 펄스와 복원 순서에 대한 말 |
| 8 | 연산마다 `w*.us`·리셋 값이 초기화되지 않아 낡은 값이 로그에 | ✅ | 초기화 |
| 9 | MAP 이 버스 마스터 비트를 보지 않는다 | ✅ | `BUS_CNTL.BUS_MASTER_DIS`(비트 6, FreeBSD `radeon_drv.h` 589) 읽기 게이트(`CP_WHY_BUSMASTER`), 시뮬레이터 경우·변이 |
| 10 | STOP 뒤 `AIC_CNTL` 이 0 이 아니라 2 | 기록만 | KMS `r100_pci_gart_disable` 과 같다(비트 1 은 둔다); 마지막 RECORD 가 읽고 판정기는 비트 0 만 본다 |
| 11 | 커널 스택: `osrdn_cp_state` 약 412 B + 엔진 사본 약 300 B | 기록만 | 허용 — 호출 사슬 앞의 프레임 0.75 KiB |

### 11-1. 실기 빌드 게이트 (2026-09-18)

- 첫 빌드(runid 789730780, stamp 6b360b0f)는 실기 컴파일·`nm -u` 가 PASS 였지만 호스트 reloc 게이트가 거절:
  `FAIL indirect jump 'jmp *0x58ec(,%eax,4)' at 000058e4 in _cpOpName` — 8 갈래 조밀 switch 를 cc 가 점프 테이블로 만들었다.
  `osrdn_modelog.m` 의 `cpOpName` 을 이미 쓰는 방식(`cpRecNames`)의 문자열 표로 바꿨다.  설치하지 않았다.
- 두 번째 빌드(runid 789730893, stamp de35dea5): reloc 게이트 PASS, `nm -u` 20개 모두 커널에 있음, 이전 설치본(789714773) 대비
  새 심볼은 `_IOFreeLow`·`_IOMallocLow`·`_IOPhysicalFromVirtual`·`_IOVmTaskSelf` 넷뿐.  `tools/check-all.sh` PASS.

## 12. 첫 실기 부팅 (2026-09-18, 부팅 eab8c318, build de35dea5) — MAP 게이트에서 멈춤

### 12-1. 결과 (로그 `build/r5/boot-eab8c318.full.log`, `check_cp.py` FAIL 2 — 둘 다 아래 MAP)
- 블록: `phys=00040000 len=00010000 ok`.
- RECORD(n=1) rc 0.  BUS_MASTER_DIS 0.  **AGP 창 `27ff2000` = 0x20000000–0x27ffffff 가 GART 창과 겹친다** — D3(치움)의 근거가 실측으로 섰다.
  `CSQ_STAT = 02000603` (CP 를 한 번도 안 쓴 상태).
- LOAD(n=2) rc 0, state 1.
- **MAP(n=3) rc 7(POST) why 10(MAPGATE) gv `000001e0` = `AIC_HI_ADDR`**: 0x207fffff 를 썼는데 다르게 읽혔다.  PT_BASE·LO 는 통과(그 앞 검사).
  드라이버가 스스로 되돌렸다(state 1).  읽힌 값은 **로그에 없다** — 게이트가 레지스터만 남기고 값을 버린다(설계 결함).
- 되돌린 뒤 RECORD(n=4) rc 0: `aic=2`(변환 꺼짐)·`lo=hi=0`·`agploc=27ff2000`·`agpcmd=200` 복원 확인.  링 레지스터는 쓴 값 그대로
  (`rbbase=20000000` `rbcntl=0804090b` `rptraddr=20004000` `saddr=20004020` `umsk=0` `s5=5a5a0005` `isync=33`) — CSQ 가 꺼져 있어 무해.
  **`CSQ_STAT` 가 `02000000` 으로 바뀌었다** — 링 레지스터 쓰기가 주 큐 포인터를 0 으로 되돌린다.
- 첫 이상에서 멈춤: RESET 이하와 cycle 은 부르지 않았다(걸쇠 아님).

### 12-2. 틀린 전제 둘 (내 결함)
1. **HI_ADDR 되읽기 = 쓴 값** — 근거 없음.  참고 넷(FreeBSD `radeon_cp.c:1060`, Linux 3.10 `radeon_cp.c` 1119 행, KMS `r100.c:677`)은 쓰기만 하고
   되읽어 대조하지 않는다; KMS `r100.c:3019` 는 디버그 출력뿐.
2. **§11 #2 의 CSQ_STAT 필드** — 세 헤더(8 비트: rptr 0–7, wptr 8–15)만 확인했다.  이 레지스터를 실제로 읽는 유일한 코드
   KMS `r100.c:2959` 는 **10 비트**(rptr 0–9, wptr 10–19, ib1 rptr 20–29)로 푼다.  부팅 값 `02000603` 은 8 비트로 3/6, 10 비트로 515/1 —
   **어느 쪽이든 CP 를 안 쓴 상태에서 rptr≠wptr** 이라, 링 레지스터를 안 썼다면 깨끗한 STOP 도 걸쇠가 됐을 것이다.

### 12-3. 수정 계획 (R5-fix1) — 검토 뒤 코딩
- **F1 게이트는 값을 남긴다**: 상태에 `gateReg` 추가, 모든 게이트 실패가 `gateReg`=레지스터·`gateValue`=**읽힌 값**; 연산마다 0 으로.  머리 줄에 `greg=`.
- **F2 HI_ADDR 는 4 KiB 단위로 대조**: `(v & ~0xfff) == (0x207fffff & ~0xfff)`.  근거: GART 항목이 4 KiB, 창의 마지막 페이지(항목 2047)는 가드,
  `DIS_OUT_OF_PCI_GART_ACCESS` 가 창 밖을 막는다 — 하위 12 비트가 잘려도 창은 넓어지지 않고, 줄어도 가드 한 페이지뿐.  상위 비트가 다르면 여전히 실패(F1 로 값이 남는다).
  쓰는 값은 참고 그대로 `...fff`.
- **F3 CSQ_STAT 는 두 배치 모두로**: 8 비트·10 비트 둘 다 rptr==wptr 여야 통과(어느 한쪽이라도 다르면 지금처럼 걸쇠).  측정값 `02000000` 은 둘 다 0/0.
  **START 앞에도 같은 판정**(다르면 거절, 아무것도 안 씀) — 큐에 낡은 항목이 남은 채 CSQ 를 켜지 않는다.
- **F4 나머지 MAP 게이트는 그대로 정확 대조**(`MC_AGP_LOCATION`=ffffffc0·`AIC_CNTL` 두 비트 — 되읽기 미관측); 실패하면 F1 로 값이 남아 다음 부팅 한 번에 답이 나온다.
- 시뮬레이터: HI 되읽기 모형 손잡이(그대로 / 하위 12 비트 0 / 상위 비트 다름), CSQ_STAT 초기값 손잡이(부팅 실측 `02000603`, 링 쓰기가 주 포인터 0),
  변이: 정확 대조 복원·`gateReg` 누락·한 배치만 판정·START 판정 제거.  판정기: `greg=` 파싱, MAP 실패면 레지스터 이름과 값을 출력.

### 12-4. 계획 검토 판정 (내부 agent — codex 는 2026-09-19 19:23 까지 한도; 인용 전부 열어 확인, 수치는 python 재계산)

| # | 지적 | 판정 | 내 검증 |
|---|---|---|---|
| B1 | F3(두 배치 모두 rptr==wptr)는 사실상 "0/0 만 통과" — 깨끗한 STOP 이 거의 불가능 | ✅ 채택 | python: 10 비트에서 같은 값 v 가 8 비트 판정을 통과하는 건 v∈{0,341,682,1023}, 8 비트에서 같은 값이 10 비트를 통과하는 건 0 뿐.  시뮬레이터 `world5.c` 299 행의 "빔" 값 `0x303` 은 10 비트로 771/0 — 모형이 문제를 가렸다.  참고 누구도 CSQ_STAT 로 판정하지 않는다: FreeBSD `radeon_cp.c:617-624`(정지 = CSQ_CNTL 쓰기 하나), KMS `r100.c:2957`(debugfs) |
| B2 | MAPPED 에서의 STOP 이 CSQ 판정으로 걸쇠 → `cpStopLatched`(그때 `osrdn_cp.m` 803–808 행)는 CSQ_CNTL 만 써서 **GART 켜짐·AGP 옮겨짐이 남는다**; F3 의 START 앞 판정도 같은 함정 | ✅ 채택 | 그때 `osrdn_cp.m` 817–848 행 열어 확인: MAPPED 는 RUNNING 블록을 건너 곧장 840 행 판정.  부팅 값 `02000603` 은 CP 를 안 쓴 채 불일치 → 이 판정은 정보가 없다 |
| M3 | F2 는 안전하나 느슨 — `0x207fffff & ~((1<<k)-1)`, k=0..12 만 받아라 | ✅ 채택 | python: 최대 색인 (0x207fffff−0x20000000)>>12 = 2047 < 2048(`osrdn_cp.h` 42·52–53 행).  근거 방향: RECORD 의 `rbbase=cdcdcdcc`·`saddr=cdcdcdc0`(로그 94·95 행)이 하위 비트를 지우는 레지스터를 보여 준다.  쓰는 값은 참고 그대로(FreeBSD `radeon_cp.c:1059-1060`, KMS `r100.c:677`) |
| m4 | 나머지 MAP 게이트(AGP_LOCATION·AIC_CNTL bit 0)는 미관측, 다른 항목은 되돌린 뒤 RECORD 에서 쓴 값 그대로 | ✅ 사실 | 로그 130–135 행 열어 확인(rbcntl·umsk·rbbase·rptraddr·rptr/wptr·intcntl·s5).  `agploc=27ff2000`·`mcfb=1fff0000` 은 16 비트 필드를 그대로 보존 |
| M5-1 | 게이트가 첫 실패에서 멈춘다 → 모든 항목을 평가하고 불일치 비트 마스크와 되읽기 전부를 한 줄로 | ✅ 채택 | 그때 `osrdn_cp.m` 369–394 행이 항목마다 `return` — 확인 |
| M5-2 | CSQ_STAT·CSQ2_STAT(0x7fc)을 연산마다 기록 | ✅ 채택(기록만) | Linux 3.10 `radeon_reg.h` 3349 행에 `RADEON_CP_CSQ2_STAT 0x07fc` 확인 |
| M5-3 | MAP 과 RESET 사이에 RECORD | ✅ 채택 | 절차 변경만 |
| M5-4 | CSQ_CNTL 하위 비트(`02010080`)는 START/STOP 이 덮으므로 판정기가 부팅값과 비교하면 안 됨 | ⚖️ 확인만 | FreeBSD `radeon_cp.c:578`(START)·`:621`(STOP) 이 CSQ_CNTL 전체를 쓴다 확인.  판정기가 비교하는지는 코딩 때 확인 |
| M5-5 | 시뮬레이터 경우: 같은 비영 포인터 뒤 깨끗한 STOP, MAPPED+불일치 STOP → 깨끗, HI `0x207ff7ff`·`0x20400000` 거절 | ✅ 채택 | — |

증거 정리: CSQ 배치는 10 비트 쪽이 더 그럴듯(KMS 가 `CSQ_MODE` 에 `0x4D4D`(`r100.c:1181`)를 쓰고, 실측도 `00004d4d`; `r100.c:2973-2974` 의 큐 주소가 8 비트를 넘는다) — 하지만 기록만 하므로 판정에 쓰지 않는다.

### 12-5. 수정 계획 확정 (R5-fix1, 12-3 의 F2·F3 을 대체)
- **G1 MAP 게이트 전부 평가**: 되읽기 13 개(`rbcntl umsk ptbase lo hi aic rbbase rptraddr rptr wptr intcntl agploc reg5`)를 상태에 저장, 불일치 비트 마스크 `mgBad`.
  실패면 **첫 불일치 항목**이 `why`(REG5 면 POISON)·`greg`(레지스터)·`gv`(**읽힌 값**).  판정용이 아닌 기록 둘: `agpcmd`·`aicstat`.  게이트를 부른 연산(MAP·RESET·START)마다 `RDN-R5 mapgate` 한 줄.
- **G2 HI**: `0x207fffff & ~((1<<k)-1)`, k=0..12 만 통과.
- **G3 CSQ 는 기록만**: STOP 의 CSQ_STAT 판정 제거(걸쇠 기준은 기존 RPTR==WPTR+idle 그대로), START 앞 판정 없음.  연산이 끝날 때마다(걸쇠면 제외) `CSQ_STAT`·`CSQ2_STAT` 을 읽어 state 줄에 `csqstat=`·`csq2stat=`.  `CP_WHY_CSQ_QUEUE` 는 더 이상 세우지 않는다.
- **G4 절차**: RECORD → LOAD → MAP → **RECORD** → RESET → RECORD → START → SUBMIT×8 → NEGCTL → STOP → RECORD → cycle.
- **G5 판정기**: 머리 줄 `greg=`, `mapgate` 줄 파싱; 실패면 레지스터 이름·값 출력; 새 절차.
- **G6 시뮬레이터**: HI 모형(그대로·`207ff000` 통과, `207ff7ff`·`20400000` 거절), CSQ_STAT 모형(부팅 `02000603`, 링 쓰기 → 주 포인터 0, START 뒤 같은 비영 값 10 비트 16/16, STOP 깨끗), MAPPED 에서 불일치인 채 STOP → 깨끗·unmap.
  변이: HI 정확 대조 복원, 게이트 첫 실패에서 멈춤, CSQ 판정 복원, 마스크 미기록, CSQ 연산 뒤 읽기 제거.

### 12-6. 실기 전 코드 검토 판정 (내부 agent; 인용한 행 전부 열어 확인)

드라이버 동작 결함 없음(검토자: `cpHiOk` 는 13 값만, 마스크 0–12 비트·첫 불일치 루프는 k<13 에서 끝남, MAP/RESET/START 에서 why·greg 올바름, 연산마다 초기화, C89·switch 없음·`(unsigned int)`+`%08x`).  지적은 시험 쪽:

| # | 지적 | 판정 | 조치 |
|---|---|---|---|
| 1 | 걸쇠 뒤 CSQ 읽기 금지가 시험되지 않는다(시뮬레이터가 쓰기만 셈, 걸쇠 경우마다 엔진이 바빠 idle 판정이 가림) | ✅ | 시뮬레이터가 걸쇠 감시 중 RBBM_STATUS 밖의 읽기도 센다; 엔진이 idle 인 걸쇠 STOP 경우 추가; 변이 "CP 걸쇠 무시" |
| 2 | REG5·RPTR 판정 삭제와 POISON why 삭제가 잡히지 않는다 | ✅ | 손잡이 `simReg5Mangle`·`simRptrDrift`, 각각 단독 경우; 변이 셋 |
| 3 | 연산 끝 읽기가 R4 엔진 걸쇠로 거절된 연산에서도 돈다; 주석 "카드에 닿은 연산" 이 부정확 | ✅ | `!engineLatched` 추가, 주석 수정, 경우·변이 |
| 4 | 판정기가 실패한 실행에서 CSQ 기록을 버리고 `csqread` 를 보지 않는다 | ⚖️ | 기록 출력을 조기 반환 앞으로; `csqread` 는 기록값이라 판정하지 않음(의도) |
| 5 | 깨끗한 STOP 의 걸쇠 경로는 상태를 두 번 읽는다(`cpLatch` + `cpStopLatched`) | 기록만 | 이전부터; 쓰기는 CSQ_CNTL 하나, 읽기는 RBBM_STATUS 뿐 |
| 6 | 판정기와 드라이버의 RPTR/WPTR 비교 방식 차이, START 판정의 `rafter==16` 은 RESET 뒤 RPTR 0 가정 | 기록만 | 부팅 eab8c318 에서 되돌린 뒤 `rptr=00000000`(로그 131 행) |

인용 검사: §12 의 Linux 파일·우리 코드 인용을 "행" 표기로 바꿨다(규약상 `radeon_cp.c`=FreeBSD, `radeon_reg.h`=xf86 — 내가 같은 표기로 Linux 파일을 가리켰다).  FreeBSD·KMS 인용 11 건은 원문 문자열 대조 뒤 `EXPECT` 에 등록.

## 13. R5 실기 PASS (2026-09-18, 부팅 fdca7cd1, build 65b66543 = R5-fix1)

로그 `build/r5/boot-fdca7cd1.full.log`, `tools/r5/check_cp.py` **PASS**.  절차 12-5 G4 그대로, 연산마다 새 runid, 이상 없음, 걸쇠 없음.

- MAP: 되읽기 13 개 전부 일치(`bad=0000`).  **`AIC_HI_ADDR` 은 `207ff000` 으로 읽힌다** — 하위 12 비트를 버리는 레지스터(12-4 M3 의 가설 확인); 첫 부팅의 MAP 실패 원인이 이것.
  표 합·xor `2100f000`/`00001000` = python 독립 계산(phys 0x40000).  `MC_AGP_LOCATION` 은 `ffffffc0` 그대로.
- RESET: 부팅 `MCLK_CNTL = aa3f1212` 는 FORCEON 6 비트가 이미 켜져 있어 강제가 값을 바꾸지 않았다; 인덱스 `308`·soft 0 복원.  RESET 전후 RECORD 동일.
- START: CP 가 GART 로 16 워드를 읽고 실행, rptr=wptr=16, REG5 불변, 블록 불일치 0.
- SUBMIT×8(1024×4, 1008, 1024×3): 두 바퀴, 경계 1024·2048·3072 와 감김(3088→16, 3072→0), 표지 전부 되읽힘.  NEGCTL: 센티넬 그대로, rptr 0 에 머묾.
- STOP 깨끗(state 4) → 마지막 RECORD: `aic=2`·`lo=hi=0`·`agploc=27ff2000` 복원.  이후 `RDNR2bCycle` verdict 0.

기록(판정 아님):
- **CSQ_STAT**: 부팅 `02000603` → 링 레지스터 쓰기 뒤 `02000000` → START 뒤 `02002010`(8 비트 16/32, 10 비트 16/8 — **정상 실행 뒤에도 불일치**, 옛 STOP 게이트였다면 거짓 걸쇠) → 다섯째 SUBMIT 부터 `02000000`.  CSQ2_STAT 은 내내 `04010080`.
- **AGP_COMMAND**: 0 을 써도 `00000200` 으로 읽힌다(비트 9; AGP 사용 비트 8 은 0).  복원 판정은 부팅값과 같아 통과.
- **미해결: `AIC_STAT` 이 4 → 6** — START 게이트(CSQ 켜기 전)까지 4, 마지막 RECORD 에서 6.  어느 참고에도 비트 정의가 없다(FreeBSD·Linux `radeon_drv.h` 는 오프셋만).  다음 CP 작업에서 SUBMIT/STOP 때마다 기록해 언제 켜지는지 좁힐 것; 가드·예비·카나리·REG5 가 모두 그대로라 GPU 가 블록 밖이나 가드를 읽은 증거는 없다.
