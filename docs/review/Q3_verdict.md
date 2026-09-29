# Q3 판정 — R5 Command Processor

질문 `Q3_prompt.md`(첫 시도는 codex 사용 한도로 실패, 10:20 재실행), 회신 `Q3_reply.md`
(gpt-5.6-sol, read-only, 2026-09-15).  인용 68곳을 Python 으로 해당 범위·기대 문자열
대조 → 67 일치, 1 곳(`radeon_drv.h:2061-2065`) 은 범위가 어긋남(실제 `BEGIN_RING` 은
`:2054-2067`, 내용은 맞음).  계획을 바꾸는 주장은 본문을 직접 읽었다.
`F/` = FreeBSD stable/9 `sys/dev/drm/`, `L/` = Linux 3.10 `drivers/gpu/drm/`.

## 내가 틀렸던 것 / 계획의 결함 (먼저)

| 계획 서술 | 사실 | 근거(이 세션에서 연 곳) |
|---|---|---|
| R5a "`CP_ME_RAM_RADDR/DATA` 로 되읽기 대조" 를 게이트로 둠 | 어느 참고 구현도 ME RAM 을 되읽지 않는다 — 읽기 의미 미확인 | 내 독립 전수 검색(정의 외 사용 0 건, `ANALYSIS.md` 9 절) + codex 동일 결론 |
| R5b 선택지 셋에 PIO 큐를 "링 위치" 로 넣음 | PIO 큐는 링 위치가 아니고 운용 프로토콜이 소스에 없다 | `radeon_reg.h:3141-3157` 정의만, 사용처 0 |
| R5c "첫 패킷 = 스크래치 `PACKET0`" 을 "무해" 하다고 씀 | writeback 이 켜져 있으면 스크래치 쓰기가 **시스템 메모리 DMA** 를 일으킨다 | `F/radeon_cp.c:765-775` "scratch register values to be written out to memory whenever they are updated" |
| writeback 끄기를 `SCRATCH_UMSK=0` 으로만 적음 | `CP_RB_CNTL.RB_NO_UPDATE`(bit 27) 도 세워야 rptr DMA 가 멈춘다 | `F/radeon_cp.c:841-845`, `F/radeon_drv.h:1119` |

## 판정표

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| 1 | 적재기는 유휴 대기 뒤 256 쌍 쓰기, **유휴 대기 반환값을 무시** | `F/radeon_cp.c:470-532` 본문 — `radeon_do_wait_for_idle(dev_priv);` 반환 미사용 확인 | ✅ 채택: 우리 적재는 유휴 확인 **성공 시에만** |
| 1b | 유휴 = FIFO 64 대기 후 `RBBM_ACTIVE` 해제, 최대 `usec_timeout`(≤100 ms) | `F/radeon_cp.c:354-404`, `F/radeon_drv.h:1805` 인용 대조 통과 | ✅ |
| 1c | 참고 순서: GART 켬 → 적재 → 링 초기화 → **엔진 리셋** → writeback 시험 | `F/radeon_cp.c:1477-1487` 본문 확인 — 리셋이 적재 **뒤** | ✅ 사실. 리셋이 ME RAM 을 지우지 않는다는 뜻으로 읽히나 명시 근거는 없음 `[미확인]` |
| 1d | 적재 전 CP 리셋·클럭·지연 전제는 소스에 없음 → 새로 만들지 말 것 | 본문 확인 | ✅ 채택 |
| 2 | 소스가 뒷받침하는 PCI 설계는 **시스템 메모리(SG) 링 + PCI GART**, 테이블은 시스템 메모리가 기본 | `xf86 radeon_dri.c:658-669, 1044-1066`, `F/radeon_cp.c:721-726, 1435-1443` 인용 통과 | ✅ 채택 |
| 2b | "계획이 `GART_MAIN` 선택지를 빠뜨렸다" | 원래 계획은 빠뜨렸으나 Q1 반영으로 R5b (가) 에 이미 추가됨(`PLAN.md` R5b) | ⚖️ 사실은 맞고 이미 고쳐짐 |
| 2c | PCI `gart_vm_start` = FB 끝 바로 뒤(넘치면 앞), 4 MiB 내림 정렬 / 옛 맵은 `fb_location + CONFIG_APER_SIZE` 이고 FB 위치를 줄여 씀 | `F/radeon_cp.c:1340-1368, 699-707` 본문 | ✅ 채택 — 정렬 **뒤** 구간 비겹침을 따로 검증해야 함(codex 결론 4) |
| 2d | `CP_RB_BASE` 를 FB 안에 두는 소스는 없다(VRAM 에 있는 것은 GART **테이블**) | 전수 grep 은 codex 가 함; 내가 `CP_RB_BASE` 쓰기 지점 확인: `F/radeon_cp.c:721-726` 한 곳, GART 주소 | ✅ 채택 — VRAM 링은 **미확인** 선택지로 강등 |
| 3 | PIO 큐는 헤더뿐 | 위 "틀렸던 것" | ✅ |
| 4 | writeback 끄기에 둘 다 필요, `CP_RB_RPTR_ADDR` 는 그대로 남음 | `F/radeon_cp.c:744-747, 758-761, 841-845` 본문 | ✅ 채택 |
| 4b | (내 추가) 참고 순서는 writeback 을 **켠 채** 버스 마스터를 켜고 그 뒤 시험 | `F/radeon_cp.c:765-790`(`SCRATCH_UMSK=0x7` → `radeon_enable_bm`), `:1486-1487` | 우리 설계는 **끈 상태에서 버스 마스터를 켠다** |
| 5 | PCI PTE = `le32(bus & 0xfffff000)`, 플래그 없음, 32 비트 | `F/ati_pcigart.c:176-222` 본문 | ✅ |
| 5b | **FreeBSD 크기 결함**: 항목 기준 상한을 페이지 수에 쓰고 페이지마다 `PAGE_SIZE/4096` 항목 → 8 KiB 페이지에서 넘침, Linux 는 `max_real_pages` 로 고침 | `F/ati_pcigart.c:184-216`, `L/ati_pcigart.c:139-143` 본문; Python: 32 KiB 테이블 = 8192 항목, FreeBSD 식은 8192 페이지 × 2 = 16384 항목 → **32 KiB 초과 기록**, Linux 상한 4096 페이지 | ✅ **채택** — 이식 시 Linux 식 |
| 5c | 8 KiB 페이지의 두 반쪽은 연속 버스 주소라고 가정 | `F/ati_pcigart.c:192-216` 의 `entry_addr += 4096` | ✅ 채택 — OPENSTEP 에서 반쪽마다 `IOPhysicalFromVirtual` 로 확인 |
| 6 | 스크래치 `PACKET0` 은 정상 문법이나 첫 패킷 선례는 없음; 참고의 시작 스트림은 `ISYNC_CNTL` → 캐시 퍼지 → `WAIT_UNTIL` | `F/radeon_cp.c:557-566, 582-593` 인용 통과, `F/radeon_drv.h:1920-1982` 매크로 본문(RV280 은 `RB3D_DSTCACHE/ZCACHE_CTLSTAT` 분기) | ✅ 채택 |
| 6b | `radeon_do_cp_flush` 는 `#if 0` 으로 비어 있다 | `F/radeon_cp.c:536-550` 본문 | ✅ |
| 7 | 정지 계약: 정지 전 flush·유휴 필요, 유휴 실패 시 정지를 안 하고 반환; lastclose 는 유휴를 **무한 재시도** | `F/radeon_cp.c:613-624, 1652-1684` 인용, `:1700-1718` 본문 | ✅ 채택 — 무한 재시도는 옮기지 않는다 |
| 7b | GART 끄기 후 테이블 해제 | `F/radeon_cp.c:1522-1529, 1067-1069` | ✅ |
| 7c | `BUS_MASTER_DIS` 는 켤 때만 지우고 정리에서 세우지 않는다 | `F/radeon_cp.c:263-279` 본문(`radeon_enable_bm`) | ✅ 사실 — 해제 시 처리는 우리 결정(스냅샷 복원) |
| 8 | `radeon_wait_ring` 은 head 가 움직이면 `i=0` 으로 **기한을 되돌리고**, `BEGIN_RING` 이 반환값을 무시 | `F/radeon_cp.c:1901-1925` 본문, `F/radeon_drv.h:2054-2067` 본문 | ✅ 채택(인용 범위만 정정) |
| 8b | Mesa·X 의 무한 대기 / 무한 리셋 재시작 | `radeon_ioctl.c:854-860`, `radeon_commonfuncs.c:956-978` 인용 통과 | ✅ |
| 결론 3 | `IOMallocLow` 링은 선례 없고 불필요 | 선례 없음은 사실. "불필요" 는 **8 KiB 페이지 반쪽 연속성·물리 주소 조회가 되느냐**에 달렸다 | ⚖️ 부분 — 선택지로 남기되 기본안은 일반 wired 페이지 + GART |
| 결론 8 | 해제 상태 기계(거절 걸쇠 → 유휴(절대 기한) → CSQ 끔 → writeback 끔 → CP 정지 → GART 끔 → 메모리 해제 → BUS_CNTL 처리) | 각 단계 근거는 위 행들 | ✅ 채택(R5d 로) |
| 결론 9 | 대기 규칙(절대 기한, 진행으로 기한 연장 금지, 실패 전파, GPU 읽기 전에 RAM 기록, 영구 비활성화) | Matrox `REMAINING_WORK.md:3958-3968, 3984-3988, 4003-4006, 4043-4049` 인용 통과 | ✅ 채택 — PLAN 금지 8 을 보강 |

## 2차 자기검사

✅ 행 재확인: 1, 1c, 2c, 5, 5b, 6b, 7, 7c, 8 은 본문을 열었다(위 칸의 범위).  6 의 매크로는
`radeon_drv.h:1920-1982` 를 열었다.  2 와 8b 는 인용 대조만 했고 결론이 계획의 기본안
선택에만 쓰이므로 행동 영향이 작다 — 그래도 R5 계획서를 쓸 때 본문을 연다고 기록해 둔다.
