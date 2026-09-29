# R5 — 참고 구현의 CP 수명주기 (RV280 PCI 경로)

작성 2026-09-15.  **사실 추출**이다 — 설계 결정은 R5 계획서의 몫이고, 이 문서는 그 입력이다.
codex 검토 없이 쓴 문서이므로 판정 근거는 전부 기계 검사로 둔다: `tools/oracle/cp_sequence.py`
가 FreeBSD `radeon_cp.c` 의 해당 함수 23 개에서 **레지스터 접근과 보조 함수 호출 165 개를 모두**
뽑아, 각각 RV280 경로(P)·경로 밖(X)·실행 중 결정(R) 으로 분류하고, 분류를 정한 조건 문장이 그
접근 **위에 실제로 있는지**와 RV280 에서의 참거짓(칩 계열 enum 순서를 `radeon_drv.h` 에서 파싱)을
검사한다.  빠진 접근·남는 분류·거짓 조건 아래의 P 는 실패다(음성 대조 6 종 포함,
`--self-test`).  아래 생성표는 그 출력이다.

전제(검사기 `FACTS`): PCI(AGP·PCIE·IGP 아님), 리틀엔디안, 테이블은 시스템 메모리
(`DRM_ATI_GART_MAIN`), **새 메모리 맵**.  새 메모리 맵의 근거: xf86 은 `SETPARAM_NEW_MEMMAP`
을 `radeon_driver.c:3681` 에서 보내고 CP 초기화(`RADEONDRIFinishScreenInit`)는 그 뒤
`radeon_driver.c:3780` 에서 한다.

## 1. 순서 (초기화 → 시작 → 제출 → 정지·해제)

**초기화** — `radeon_do_init_cp` 의 성공 경로(오류 출구 13 개는 전부 `radeon_do_cleanup_cp` 후 반환):

1. `MC_FB_LOCATION` 을 두 번 읽어 `fb_location`·`fb_size`(`radeon_cp.c:1312-1314`).
2. GART 창: `base = fb_location + fb_size`, 넘치면 `fb_location - gart_size`, **4 MiB 내림**
   (`radeon_cp.c:1355-1361`).  `MC_FB_LOCATION` 은 **다시 쓰지 않는다** — 옛 맵에서만 쓴다
   (`radeon_cp.c:704-707`).
3. `SURFACE_CNTL` 저장 → 0 → 테이블 구성(메모리) → 복원(`radeon_cp.c:1447-1453`).
4. GART 테이블 영역을 **서피스 0 의 경계**로 등록: `SURFACE0_INFO`=0, `LOWER`=테이블 버스 주소,
   `UPPER`=+table_size(`radeon_cp.c:1104-1106`).
5. GART 켬: `AIC_CNTL |= PCIGART_TRANSLATE_EN`, `AIC_PT_BASE`, `AIC_LO_ADDR`, `AIC_HI_ADDR`,
   그리고 **PCI 카드인데도** `MC_AGP_LOCATION = 0xffffffc0`, `AGP_COMMAND = 0`
   (`radeon_cp.c:1047-1066`).
6. 마이크로코드: 유휴 대기(결과 무시) → `CP_ME_RAM_ADDR`=0 → 256 쌍.
7. 링 초기화: `CP_RB_BASE`, `WPTR_DELAY`=0, `WPTR`=`RPTR`, `RPTR_ADDR`, `CP_RB_CNTL`,
   `SCRATCH_ADDR`=`RPTR_ADDR`+32, `SCRATCH_UMSK`=7(**writeback 켬**) → **그 뒤 버스 마스터 켬**
   (`radeon_cp.c:772-777`) → 스크래치 0 초기화 → 유휴 대기 → `ISYNC_CNTL`.
8. **엔진 리셋이 마이크로코드 적재·링 초기화 뒤에 온다**(`radeon_cp.c:1478-1487`): 캐시 플러시,
   `CLOCK_CNTL_INDEX`·`MCLK_CNTL`(PLL 공간) 저장 → `MCLK_CNTL` 강제 켬 → `RBBM_SOFT_RESET`
   세움·읽음·내림·읽음(대기 없음) → `MCLK_CNTL`·`CLOCK_CNTL_INDEX`·`RBBM_SOFT_RESET` 복원
   (`radeon_cp.c:603-641`) → `WPTR`=`RPTR`.
9. writeback 시험: 메모리 스크래치 1=0, `SCRATCH_REG1`=0xdeadbeef, 메모리 폴링 → 실패면
   `RB_NO_UPDATE` 와 `SCRATCH_UMSK`=0(`radeon_cp.c:814-844`).

**시작** — `radeon_do_cp_start`: 유휴 대기(결과 무시) → `CP_CSQ_CNTL = cp_mode`(xf86 은
`CSQ_PRIBM_INDBM`, `radeon_dri.c:1193`) → 링에 8 워드(생성표 B) → 커밋(`radeon_cp.c:561-578`).

**제출마다** — `radeon_commit_ring`: 꼬리를 16 워드 단위로 `PACKET2` 패딩 → `CP_RB_WPTR` 쓰기 →
"버스 게시 확인용" `CP_RB_RPTR` 읽기(`radeon_cp.c:2107-2123`).

**정지·해제** — `radeon_do_release`: CP 가 돌고 있으면 유휴를 **상한 없이 재시도** →
`CSQ_CNTL`=PRIDIS → 엔진 리셋(`radeon_cp.c:1692-1704`) → `GEN_INT_CNTL`=0, 서피스 전부 0
(`radeon_cp.c:1711-1722`) → `radeon_do_cleanup_cp`: GART 끔(`TRANSLATE_EN` 만 내림) **뒤에**
테이블 해제(`radeon_cp.c:1522-1531`).

## 2. PLAN R5 에 없던 사실 (계획서가 다뤄야 할 것)

| # | 사실 | 근거 | R5 계획서에서 정할 것 |
|---|---|---|---|
| 1 | 참고 순서는 **적재 → 링 → 엔진 리셋 → writeback 시험**이고, CP 시작은 별도 ioctl.  소프트 리셋(`SOFT_RESET_CP` 포함)이 마이크로코드 **뒤에** 온다 — 리셋 뒤에도 적재가 유지된다는 전제 | `radeon_cp.c:1478-1487` | R5a "적재만" 을 이 순서의 어디에서 끊을지.  리셋 후 ME RAM 유지 여부는 소스로 **미확인**(주석 없음) — R5c 기능 시험이 닫는다 |
| 2 | 엔진 리셋은 **PLL 공간**(`MCLK_CNTL`)을 강제 켬·복원하고 `CLOCK_CNTL_INDEX` 를 복원한다 | `radeon_cp.c:603-641` | 금지 2(참고 순서 그대로) 에 따라 그대로 옮긴다.  PLL 인덱스 접근 규약은 R0-2 와 같아야 한다(`PLL_DIV_SEL` 보존) |
| 3 | PCI GART 를 켤 때 `MC_AGP_LOCATION = 0xffffffc0`, `AGP_COMMAND = 0` 을 쓴다 | `radeon_cp.c:1047-1066` | 스냅샷·복원 목록에 두 레지스터 추가 여부 |
| 4 | `SURFACE_CNTL` 을 0 으로 내렸다 올리고, 서피스 0 경계를 GART 테이블 **버스 주소**로 쓴다(시스템 메모리 테이블인데도).  해제 때 서피스를 전부 0 으로 | `radeon_cp.c:1447-1453`, `:1104-1106`, `:1711-1722` | 금지 1 은 살아 있는 소유자 밑의 `SURFACE_CNTL` 재프로그래밍을 금한다 — R5 가 드라이버 소유 창에서만 도는지 확인.  서피스 레지스터의 의미(바이트 스왑 영역) 는 이 소스로 **미확인** |
| 5 | 해제는 `TRANSLATE_EN` 만 내린다: `AIC_PT_BASE/LO/HI`, `MC_AGP_LOCATION`, `AGP_COMMAND` 는 복원하지 않고, **버스 마스터를 다시 막지 않는다**(`BUS_MASTER_DIS` 재설정 없음) | `radeon_cp.c:1522-1531`, 생성표 A 의 `radeon_do_release` | PLAN R5d 의 "`BUS_MASTER_DIS` 스냅샷 값으로" 는 **참고보다 강한 조치**다 — 선례 없음을 계획서에 명시 |
| 6 | 모든 유휴 대기가 `RB3D_DSTCACHE_CTLSTAT` 에 `FLUSH_ALL` 을 **쓴다**(대기 함수 안의 쓰기) | `radeon_cp.c:323-332` | 우리 대기 함수를 쓰기 없는 폴링으로 둘지, 참고대로 플러시를 포함할지 |
| 7 | FIFO·유휴 대기 실패 시 디버그 출력이 `R300_VAP_CNTL_STATUS` 라는 이름으로 오프셋 0x2140 을 읽는다.  **같은 오프셋이 R100/R200 이름으로는 `RADEON_SE_CNTL_STATUS` / `R200_SE_VAP_CNTL_STATUS`** 다(FreeBSD `radeon_drv.h` 1039·1314 행, xf86 `radeon_reg.h` 2327·2622·4351 행) — RV280 에 없는 레지스터가 아니라 상태 패킷이 쓰는 R200 레지스터(`r200_verifier.py` 생성표 A id 10·57) | `radeon_cp.c:361-369` | 실패 뒤 진단 읽기이므로 옮기지 않는다(금지 8: 추가 GPU 읽기 전에 RAM 기록).  *정정 2026-09-15: 처음엔 "R300 전용 레지스터" 로 적었다 — 이름만 보고 판단한 오류, 검증기 표를 만들다 발견* |
| 8 | 제출마다 `WPTR` 뒤에 `RPTR` 을 읽는다("PCI 게시 확인") | `radeon_cp.c:2107-2123` | 우리 커밋 경로에 같은 읽기를 둘지(참고에 있는 조작이라 넣어도 금지 2 위반 아님) |

## 3. 생성표

`python3 tools/oracle/cp_sequence.py --markdown` 의 출력.  손으로 고치지 않는다.

<!-- BEGIN cp_sequence.py --markdown (generated; do not edit) -->
### 생성표 A — 함수별 레지스터 접근과 RV280 판정

판정: **P** RV280 PCI 경로, **X** 경로 밖, **R** 실행 중 결정.  줄은 `radeon_cp.c`.

#### `radeon_enable_bm` (`radeon_cp.c:263-280`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 270 | `RADEON_READ` | `RADEON_BUS_CNTL` | X | `== CHIP_RS690` | RS600_BUS_MASTER_DIS variant |
| 271 | `RADEON_WRITE` | `RADEON_BUS_CNTL` | X | `== CHIP_RS690` |  |
| 277 | `RADEON_READ` | `RADEON_BUS_CNTL` | P | `<= CHIP_RV350` |  |
| 278 | `RADEON_WRITE` | `RADEON_BUS_CNTL` | P | `<= CHIP_RV350` | clears BUS_MASTER_DIS |

#### `radeon_do_pixcache_flush` (`radeon_cp.c:323-352`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 331 | `RADEON_READ` | `RADEON_RB3D_DSTCACHE_CTLSTAT` | P | `<= CHIP_RV280` |  |
| 333 | `RADEON_WRITE` | `RADEON_RB3D_DSTCACHE_CTLSTAT` | P | `<= CHIP_RV280` | \|= RB3D_DC_FLUSH_ALL |
| 336 | `RADEON_READ` | `RADEON_RB3D_DSTCACHE_CTLSTAT` | P | `<= CHIP_RV280` | poll !RB3D_DC_BUSY, usec_timeout x 1 us |

#### `radeon_do_wait_for_fifo` (`radeon_cp.c:354-376`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 361 | `RADEON_READ` | `RADEON_RBBM_STATUS` | P | `—` | poll FIFOCNT >= entries |
| 368 | `RADEON_READ` | `RADEON_RBBM_STATUS` | P | `—` | debug print on timeout |
| 369 | `RADEON_READ` | `R300_VAP_CNTL_STATUS` | P | `—` | debug print on timeout: 0x2140, R200_SE_VAP_CNTL_STATUS on RV280 |

#### `radeon_do_wait_for_idle` (`radeon_cp.c:378-405`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 384 | `radeon_do_wait_for_fifo` | `dev_priv` | P | `—` | 64 entries |
| 389 | `RADEON_READ` | `RADEON_RBBM_STATUS` | P | `—` | poll !RBBM_ACTIVE |
| 391 | `radeon_do_pixcache_flush` | `dev_priv` | P | `—` | return value ignored |
| 397 | `RADEON_READ` | `RADEON_RBBM_STATUS` | P | `—` | debug print on timeout |
| 398 | `RADEON_READ` | `R300_VAP_CNTL_STATUS` | P | `—` | debug print on timeout |

#### `radeon_init_pipes` (`radeon_cp.c:407-458`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 412 | `RADEON_READ` | `RV530_GB_PIPE_SELECT2` | X | `== CHIP_RV530` |  |
| 422 | `RADEON_READ` | `R400_GB_PIPE_SELECT` | X | `>= CHIP_R420` |  |
| 447 | `RADEON_WRITE_PLL` | `R500_DYN_SCLK_PWMEM_PIPE` | X | `>= CHIP_RV515` |  |
| 448 | `RADEON_WRITE` | `R300_SU_REG_DEST` | X | `>= CHIP_RV515` |  |
| 450 | `RADEON_WRITE` | `R300_GB_TILE_CONFIG` | X | `—` | whole function is only called for >= CHIP_R300 |
| 451 | `radeon_do_wait_for_idle` | `dev_priv` | X | `—` | idem |
| 452 | `RADEON_WRITE` | `R300_DST_PIPE_CONFIG` | X | `—` | idem |
| 452 | `RADEON_READ` | `R300_DST_PIPE_CONFIG` | X | `—` | idem |
| 453 | `RADEON_WRITE` | `R300_RB2D_DSTCACHE_MODE` | X | `—` | idem |
| 453 | `RADEON_READ` | `R300_RB2D_DSTCACHE_MODE` | X | `—` | idem |

#### `radeon_cp_load_microcode` (`radeon_cp.c:465-533`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 525 | `radeon_do_wait_for_idle` | `dev_priv` | P | `case CHIP_RV280:` | R200_cp_microcode; result ignored |
| 527 | `RADEON_WRITE` | `RADEON_CP_ME_RAM_ADDR` | P | `case CHIP_RV280:` | 0 |
| 530 | `RADEON_WRITE` | `RADEON_CP_ME_RAM_DATAH` | P | `for (i = 0; i != 256; i++)` | cp[i][1], 256 times |
| 531 | `RADEON_WRITE` | `RADEON_CP_ME_RAM_DATAL` | P | `for (i = 0; i != 256; i++)` | cp[i][0], 256 times |

#### `radeon_do_cp_idle` (`radeon_cp.c:552-567`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 559 | `RADEON_PURGE_CACHE` | `` | P | `—` | ring: PACKET0(RB3D_DSTCACHE_CTLSTAT), DC_FLUSH\|DC_FREE |
| 560 | `RADEON_PURGE_ZCACHE` | `` | P | `—` | ring: PACKET0(RB3D_ZCACHE_CTLSTAT), ZC_FLUSH\|ZC_FREE |
| 561 | `RADEON_WAIT_UNTIL_IDLE` | `` | P | `—` | ring: PACKET0(WAIT_UNTIL), 2D\|3D\|HOST idleclean |
| 566 | `radeon_do_wait_for_idle` | `dev_priv` | P | `—` |  |

#### `radeon_do_cp_start` (`radeon_cp.c:571-596`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 576 | `radeon_do_wait_for_idle` | `dev_priv` | P | `—` | result ignored |
| 578 | `RADEON_WRITE` | `RADEON_CP_CSQ_CNTL` | P | `—` | cp_mode (xf86: CSQ_PRIBM_INDBM) |
| 584 | `OUT_RING` | `CP_PACKET0` | P | `—` | ring: PACKET0(ISYNC_CNTL) |
| 585 | `OUT_RING` | `RADEON_ISYNC_ANY2D_IDLE3D` | P | `—` | ring: ISYNC value |
| 589 | `RADEON_PURGE_CACHE` | `` | P | `—` |  |
| 590 | `RADEON_PURGE_ZCACHE` | `` | P | `—` |  |
| 591 | `RADEON_WAIT_UNTIL_IDLE` | `` | P | `—` |  |

#### `radeon_do_cp_reset` (`radeon_cp.c:602-611`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 607 | `RADEON_READ` | `RADEON_CP_RB_RPTR` | P | `—` |  |
| 608 | `RADEON_WRITE` | `RADEON_CP_RB_WPTR` | P | `—` | = RPTR |
| 609 | `SET_RING_HEAD` | `dev_priv` | P | `—` | memory: rptr page word 0 |

#### `radeon_do_cp_stop` (`radeon_cp.c:617-624`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 621 | `RADEON_WRITE` | `RADEON_CP_CSQ_CNTL` | P | `—` | CSQ_PRIDIS_INDDIS |

#### `radeon_do_engine_reset` (`radeon_cp.c:628-691`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 634 | `radeon_do_pixcache_flush` | `dev_priv` | P | `—` |  |
| 638 | `RADEON_READ` | `RADEON_CLOCK_CNTL_INDEX` | P | `<= CHIP_RV410` | saved |
| 639 | `RADEON_READ_PLL` | `RADEON_MCLK_CNTL` | P | `<= CHIP_RV410` | saved |
| 641 | `RADEON_WRITE_PLL` | `RADEON_MCLK_CNTL` | P | `<= CHIP_RV410` | \| FORCEON_MCLKA\|MCLKB\|YCLKA\|YCLKB\|MC\|AIC |
| 650 | `RADEON_READ` | `RADEON_RBBM_SOFT_RESET` | P | `—` | saved |
| 652 | `RADEON_WRITE` | `RADEON_RBBM_SOFT_RESET` | P | `—` | \| SOFT_RESET_CP\|HI\|SE\|RE\|PP\|E2\|RB |
| 660 | `RADEON_READ` | `RADEON_RBBM_SOFT_RESET` | P | `—` | no delay |
| 661 | `RADEON_WRITE` | `RADEON_RBBM_SOFT_RESET` | P | `—` | & ~ those bits |
| 669 | `RADEON_READ` | `RADEON_RBBM_SOFT_RESET` | P | `—` | no delay |
| 672 | `RADEON_WRITE_PLL` | `RADEON_MCLK_CNTL` | P | `<= CHIP_RV410` | restored |
| 673 | `RADEON_WRITE` | `RADEON_CLOCK_CNTL_INDEX` | P | `<= CHIP_RV410` | restored |
| 674 | `RADEON_WRITE` | `RADEON_RBBM_SOFT_RESET` | P | `<= CHIP_RV410` | restored to the saved value |
| 679 | `radeon_init_pipes` | `dev_priv` | X | `>= CHIP_R300` |  |
| 682 | `radeon_do_cp_reset` | `dev_priv` | P | `—` |  |
| 688 | `radeon_freelist_reset` | `dev` | P | `—` | software only |

#### `radeon_cp_init_ring_buffer` (`radeon_cp.c:693-804`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 705 | `radeon_write_fb_location` | `dev_priv` | X | `!dev_priv->new_memmap` | MC_FB_LOCATION rewrite only with the old map |
| 711 | `radeon_write_agp_base` | `dev_priv` | X | `RADEON_IS_AGP` |  |
| 713 | `radeon_write_agp_location` | `dev_priv` | X | `RADEON_IS_AGP` |  |
| 726 | `RADEON_WRITE` | `RADEON_CP_RB_BASE` | P | `—` | ring offset in the SG area + gart_vm_start |
| 729 | `RADEON_WRITE` | `RADEON_CP_RB_WPTR_DELAY` | P | `—` | 0 |
| 732 | `RADEON_READ` | `RADEON_CP_RB_RPTR` | P | `—` |  |
| 733 | `RADEON_WRITE` | `RADEON_CP_RB_WPTR` | P | `—` | = RPTR |
| 734 | `SET_RING_HEAD` | `dev_priv` | P | `—` | memory |
| 739 | `RADEON_WRITE` | `RADEON_CP_RB_RPTR_ADDR` | X | `RADEON_IS_AGP` |  |
| 745 | `RADEON_WRITE` | `RADEON_CP_RB_RPTR_ADDR` | P | `—` | rptr page offset in the SG area + gart_vm_start |
| 752 | `RADEON_WRITE` | `RADEON_CP_RB_CNTL` | X | `#ifdef __BIG_ENDIAN` | BUF_SWAP_32BIT variant |
| 758 | `RADEON_WRITE` | `RADEON_CP_RB_CNTL` | P | `—` | (fetch_l2ow << 18) \| (rptr_update_l2qw << 8) \| size_l2qw |
| 772 | `RADEON_WRITE` | `RADEON_SCRATCH_ADDR` | P | `—` | = RPTR_ADDR + RADEON_SCRATCH_REG_OFFSET |
| 772 | `RADEON_READ` | `RADEON_CP_RB_RPTR_ADDR` | P | `—` |  |
| 775 | `RADEON_WRITE` | `RADEON_SCRATCH_UMSK` | P | `—` | 0x7: writeback of scratch 0-2 ON |
| 777 | `radeon_enable_bm` | `dev_priv` | P | `—` | bus mastering ON after writeback ON |
| 779 | `radeon_write_ring_rptr` | `dev_priv` | P | `—` | memory scratch 0 = 0 |
| 780 | `RADEON_WRITE` | `RADEON_LAST_FRAME_REG` | P | `—` | 0 |
| 782 | `radeon_write_ring_rptr` | `dev_priv` | P | `—` | memory scratch 1 = 0 |
| 783 | `RADEON_WRITE` | `RADEON_LAST_DISPATCH_REG` | P | `—` | 0 |
| 785 | `radeon_write_ring_rptr` | `dev_priv` | P | `—` | memory scratch 2 = 0 |
| 786 | `RADEON_WRITE` | `RADEON_LAST_CLEAR_REG` | P | `—` | 0 |
| 795 | `radeon_do_wait_for_idle` | `dev_priv` | P | `—` | result ignored |
| 798 | `RADEON_WRITE` | `RADEON_ISYNC_CNTL` | P | `—` | ANY2D_IDLE3D\|ANY3D_IDLE2D\|WAIT_IDLEGUI\|CPSCRATCH_IDLEGUI |

#### `radeon_test_writeback` (`radeon_cp.c:806-847`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 816 | `radeon_write_ring_rptr` | `dev_priv` | P | `—` | memory scratch 1 = 0 |
| 818 | `RADEON_WRITE` | `RADEON_SCRATCH_REG1` | P | `—` | 0xdeadbeef |
| 823 | `radeon_read_ring_rptr` | `dev_priv` | P | `—` | poll memory, usec_timeout x 1 us |
| 843 | `RADEON_WRITE` | `RADEON_CP_RB_CNTL` | R | `if (!dev_priv->writeback_works)` | \|= RB_NO_UPDATE |
| 843 | `RADEON_READ` | `RADEON_CP_RB_CNTL` | R | `if (!dev_priv->writeback_works)` |  |
| 845 | `RADEON_WRITE` | `RADEON_SCRATCH_UMSK` | R | `if (!dev_priv->writeback_works)` | 0 |

#### `radeon_set_pcigart` (`radeon_cp.c:1026-1071`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 1033 | `radeon_set_igpgart` | `dev_priv` | X | `== CHIP_RS690` |  |
| 1038 | `rs600_set_igpgart` | `dev_priv` | X | `== CHIP_RS600` |  |
| 1043 | `radeon_set_pciegart` | `dev_priv` | X | `RADEON_IS_PCIE` |  |
| 1047 | `RADEON_READ` | `RADEON_AIC_CNTL` | P | `—` |  |
| 1050 | `RADEON_WRITE` | `RADEON_AIC_CNTL` | P | `if (on)` | \| PCIGART_TRANSLATE_EN  (on) |
| 1055 | `RADEON_WRITE` | `RADEON_AIC_PT_BASE` | P | `if (on)` | table bus address  (on) |
| 1059 | `RADEON_WRITE` | `RADEON_AIC_LO_ADDR` | P | `if (on)` | gart_vm_start  (on) |
| 1060 | `RADEON_WRITE` | `RADEON_AIC_HI_ADDR` | P | `if (on)` | gart_vm_start + gart_size - 1  (on) |
| 1065 | `radeon_write_agp_location` | `dev_priv` | P | `if (on)` | 0xffffffc0: AGP aperture off  (on) |
| 1066 | `RADEON_WRITE` | `RADEON_AGP_COMMAND` | P | `if (on)` | 0  (on) |
| 1068 | `RADEON_WRITE` | `RADEON_AIC_CNTL` | P | `} else {` | & ~PCIGART_TRANSLATE_EN  (off) |

#### `radeon_setup_pcigart_surface` (`radeon_cp.c:1073-1111`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 1104 | `RADEON_WRITE` | `RADEON_SURFACE0_INFO` | P | `—` | first free surface i: 0 |
| 1105 | `RADEON_WRITE` | `RADEON_SURFACE0_LOWER_BOUND` | P | `—` | table bus address |
| 1106 | `RADEON_WRITE` | `RADEON_SURFACE0_UPPER_BOUND` | P | `—` | bus address + table_size |

#### `radeon_read_fb_location` (`radeon_cp.c:167-185`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 171 | `RADEON_READ` | `R700_MC_VM_FB_LOCATION` | X | `>= CHIP_RV770` |  |
| 173 | `RADEON_READ` | `R600_MC_VM_FB_LOCATION` | X | `>= CHIP_R600` |  |
| 175 | `R500_READ_MCIND` | `dev_priv` | X | `== CHIP_RV515` |  |
| 178 | `RS690_READ_MCIND` | `dev_priv` | X | `== CHIP_RS690` |  |
| 180 | `RS600_READ_MCIND` | `dev_priv` | X | `== CHIP_RS600` |  |
| 182 | `R500_READ_MCIND` | `dev_priv` | X | `> CHIP_RV515` |  |
| 184 | `RADEON_READ` | `RADEON_MC_FB_LOCATION` | P | `—` | the final else |

#### `radeon_write_fb_location` (`radeon_cp.c:187-204`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 190 | `RADEON_WRITE` | `R700_MC_VM_FB_LOCATION` | X | `>= CHIP_RV770` |  |
| 192 | `RADEON_WRITE` | `R600_MC_VM_FB_LOCATION` | X | `>= CHIP_R600` |  |
| 194 | `R500_WRITE_MCIND` | `RV515_MC_FB_LOCATION` | X | `== CHIP_RV515` |  |
| 197 | `RS690_WRITE_MCIND` | `RS690_MC_FB_LOCATION` | X | `== CHIP_RS690` |  |
| 199 | `RS600_WRITE_MCIND` | `RS600_MC_FB_LOCATION` | X | `== CHIP_RS600` |  |
| 201 | `R500_WRITE_MCIND` | `R520_MC_FB_LOCATION` | X | `> CHIP_RV515` |  |
| 203 | `RADEON_WRITE` | `RADEON_MC_FB_LOCATION` | P | `—` | the final else (only reached with the old map) |

#### `radeon_write_agp_location` (`radeon_cp.c:206-226`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 210 | `RADEON_WRITE` | `R700_MC_VM_AGP_BOT` | X | `>= CHIP_RV770` |  |
| 211 | `RADEON_WRITE` | `R700_MC_VM_AGP_TOP` | X | `>= CHIP_RV770` |  |
| 213 | `RADEON_WRITE` | `R600_MC_VM_AGP_BOT` | X | `>= CHIP_R600` |  |
| 214 | `RADEON_WRITE` | `R600_MC_VM_AGP_TOP` | X | `>= CHIP_R600` |  |
| 216 | `R500_WRITE_MCIND` | `RV515_MC_AGP_LOCATION` | X | `== CHIP_RV515` |  |
| 219 | `RS690_WRITE_MCIND` | `RS690_MC_AGP_LOCATION` | X | `== CHIP_RS690` |  |
| 221 | `RS600_WRITE_MCIND` | `RS600_MC_AGP_LOCATION` | X | `== CHIP_RS600` |  |
| 223 | `R500_WRITE_MCIND` | `R520_MC_AGP_LOCATION` | X | `> CHIP_RV515` |  |
| 225 | `RADEON_WRITE` | `RADEON_MC_AGP_LOCATION` | P | `—` | the final else |

#### `radeon_do_cleanup_cp` (`radeon_cp.c:1492-1543`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 1524 | `radeon_set_pcigart` | `dev_priv` | P | `if (dev_priv->gart_info.bus_addr)` | off: clears only PCIGART_TRANSLATE_EN |
| 1526 | `r600_page_table_cleanup` | `` | X | `== CHIP_RS600` |  |
| 1528 | `drm_ati_pcigart_cleanup` | `` | P | `if (dev_priv->gart_info.bus_addr)` | frees the table after translation is off |

#### `radeon_do_release` (`radeon_cp.c:1689-1745`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 1698 | `r600_do_cp_idle` | `dev_priv` | X | `>= CHIP_R600` |  |
| 1704 | `radeon_do_cp_idle` | `dev_priv` | R | `if (dev_priv->cp_running)` | retried with no bound until it succeeds |
| 1711 | `r600_do_cp_stop` | `dev_priv` | X | `>= CHIP_R600` |  |
| 1712 | `r600_do_engine_reset` | `dev` | X | `>= CHIP_R600` |  |
| 1714 | `radeon_do_cp_stop` | `dev_priv` | R | `if (dev_priv->cp_running)` |  |
| 1715 | `radeon_do_engine_reset` | `dev` | R | `if (dev_priv->cp_running)` |  |
| 1722 | `RADEON_WRITE` | `RADEON_GEN_INT_CNTL` | P | `if (dev_priv->mmio)` | 0 |
| 1726 | `RADEON_WRITE` | `RADEON_SURFACE0_INFO` | P | `for (i = 0; i < RADEON_MAX_SURFACES; i++)` | 0 for every surface |
| 1727 | `RADEON_WRITE` | `RADEON_SURFACE0_LOWER_BOUND` | P | `for (i = 0; i < RADEON_MAX_SURFACES; i++)` | 0 |
| 1729 | `RADEON_WRITE` | `RADEON_SURFACE0_UPPER_BOUND` | P | `for (i = 0; i < RADEON_MAX_SURFACES; i++)` | 0 |
| 1743 | `radeon_do_cleanup_cp` | `dev` | P | `< CHIP_R600` | the else of >= CHIP_R600 |

#### `radeon_commit_ring` (`radeon_cp.c:2094-2130`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 2119 | `GET_RING_HEAD` | `dev_priv` | P | `—` | after padding the tail to 16 words with PACKET2 |
| 2122 | `RADEON_WRITE` | `R600_CP_RB_WPTR` | X | `>= CHIP_R600` |  |
| 2124 | `RADEON_READ` | `R600_CP_RB_RPTR` | X | `>= CHIP_R600` |  |
| 2126 | `RADEON_WRITE` | `RADEON_CP_RB_WPTR` | P | `—` | tail |
| 2128 | `RADEON_READ` | `RADEON_CP_RB_RPTR` | P | `—` | "read from PCI bus to ensure correct posting" |

#### `radeon_get_ring_head` (`radeon_cp.c:63-73`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 66 | `radeon_read_ring_rptr` | `dev_priv` | R | `if (dev_priv->writeback_works)` | memory copy of RPTR |
| 69 | `RADEON_READ` | `R600_CP_RB_RPTR` | X | `>= CHIP_R600` |  |
| 71 | `RADEON_READ` | `RADEON_CP_RB_RPTR` | R | `if (dev_priv->writeback_works)` | register, when writeback failed |

#### `radeon_do_init_cp` (`radeon_cp.c:1113-1490`)

| 줄 | 접근 | 대상 | 판정 | 조건 | 비고 |
|---|---|---|---|---|---|
| 1312 | `radeon_read_fb_location` | `dev_priv` | P | `—` | fb_location = (MC_FB_LOCATION & 0xffff) << 16 |
| 1314 | `radeon_read_fb_location` | `dev_priv` | P | `—` | fb_size = ((MC_FB_LOCATION & 0xffff0000) + 0x10000) - fb_location |
| 1368 | `RADEON_READ` | `RADEON_CONFIG_APER_SIZE` | X | `!dev_priv->new_memmap` | old map: gart_vm_start = fb_location + APER_SIZE |
| 1404 | `radeon_set_pcigart` | `dev_priv` | X | `RADEON_IS_AGP` | AGP: PCI GART off |
| 1452 | `RADEON_READ` | `RADEON_SURFACE_CNTL` | P | `—` | saved |
| 1453 | `RADEON_WRITE` | `RADEON_SURFACE_CNTL` | P | `—` | 0 while the table is built |
| 1455 | `r600_page_table_init` | `dev` | X | `== CHIP_RS600` |  |
| 1457 | `drm_ati_pcigart_init` | `` | P | `—` | table in system memory (DRM_ATI_GART_MAIN) |
| 1458 | `RADEON_WRITE` | `RADEON_SURFACE_CNTL` | P | `—` | restored |
| 1466 | `radeon_setup_pcigart_surface` | `dev_priv` | P | `—` |  |
| 1470 | `r600_page_table_cleanup` | `` | X | `== CHIP_RS600` | error exit |
| 1472 | `drm_ati_pcigart_cleanup` | `` | X | `—` | error exit only |
| 1478 | `radeon_set_pcigart` | `dev_priv` | P | `—` | on |
| 1481 | `radeon_cp_load_microcode` | `dev_priv` | P | `—` |  |
| 1482 | `radeon_cp_init_ring_buffer` | `dev_priv` | P | `—` |  |
| 1486 | `radeon_do_engine_reset` | `dev` | P | `—` |  |
| 1487 | `radeon_test_writeback` | `dev_priv` | P | `—` |  |

### 생성표 B — 계산값

| 항목 | 값 | 근거 |
|---|---|---|
| `CP_RB_CNTL` (링 1 MiB, 리틀엔디안) | `0x00040911` (size_l2qw=17, rptr_update_l2qw=9, fetch_size_l2ow=1) | `drm_order` = Linux `drm_bufs.c` 1602–1613, 링 1 MB = xf86 `radeon_dri.h:44` |
| `RB_NO_UPDATE` | `0x08000000` | `radeon_drv.h` |
| `SCRATCH_ADDR` − `CP_RB_RPTR_ADDR` | `32` (0x20) | `RADEON_SCRATCH_REG_OFFSET` |
| `RBBM_SOFT_RESET` 비트 CP·HI·SE·RE·PP·E2·RB | `0x0000007f` | 엔진 리셋 |
| `MCLK_CNTL` FORCEON 비트 | `0x003f0000` | 엔진 리셋(PLL 공간) |
| `CP_CSQ_CNTL` 모드 | PRIBM_INDBM `0x40000000`(xf86), PRIBM_INDDIS `0x20000000`, PRIDIS_INDDIS `0x00000000`(stop) | `radeon_drv.h`, xf86 `radeon_dri.c:1193` |

CP 시작 스트림(`radeon_do_cp_start` 의 8 워드, `radeon_commit_ring` 이 16 워드로 `PACKET2` 패딩):

```
 0  0x000005c9  PACKET0(ISYNC_CNTL)
 1  0x00000033  ISYNC value
 2  0x00000c97  PACKET0(RB3D_DSTCACHE_CTLSTAT)
 3  0x0000000f  DC_FLUSH|DC_FREE
 4  0x00000c95  PACKET0(RB3D_ZCACHE_CTLSTAT)
 5  0x00000005  ZC_FLUSH|ZC_FREE
 6  0x000005c8  PACKET0(WAIT_UNTIL)
 7  0x00070000  2D|3D|HOST_IDLECLEAN
 8  0x80000000  PACKET2
 9  0x80000000  PACKET2
10  0x80000000  PACKET2
11  0x80000000  PACKET2
12  0x80000000  PACKET2
13  0x80000000  PACKET2
14  0x80000000  PACKET2
15  0x80000000  PACKET2
```

레지스터 오프셋(`radeon_drv.h` 에서 계산):

N = NetBSD `radeonfbreg.h`, X = xf86 `radeon_reg.h`, L = Linux 3.10 `radeon_drv.h`(FreeBSD 와 같은 계보라 사본 확인일 뿐).

| 레지스터 | 오프셋 | 다른 헤더 |
|---|---|---|
| `RADEON_MCLK_CNTL` | `0x0012` | N: same, X: same, L: same |
| `RADEON_BUS_CNTL` | `0x0030` | N: same, X: same, L: same |
| `RADEON_GEN_INT_CNTL` | `0x0040` | N: same, X: same, L: same |
| `RADEON_RBBM_SOFT_RESET` | `0x00f0` | N: same, X: same, L: same |
| `RADEON_MC_FB_LOCATION` | `0x0148` | N: same, X: same, L: same |
| `RADEON_MC_AGP_LOCATION` | `0x014c` | N: same, X: same, L: same |
| `RADEON_AIC_CNTL` | `0x01d0` | N: same, X: same, L: same |
| `RADEON_AIC_PT_BASE` | `0x01d8` | N: —, X: —, L: same |
| `RADEON_AIC_LO_ADDR` | `0x01dc` | N: same, X: same, L: same |
| `RADEON_AIC_HI_ADDR` | `0x01e0` | N: —, X: —, L: same |
| `RADEON_CP_RB_BASE` | `0x0700` | N: same, X: same, L: same |
| `RADEON_CP_RB_CNTL` | `0x0704` | N: same, X: same, L: same |
| `RADEON_CP_RB_RPTR_ADDR` | `0x070c` | N: same, X: same, L: same |
| `RADEON_CP_RB_RPTR` | `0x0710` | N: same, X: same, L: same |
| `RADEON_CP_RB_WPTR` | `0x0714` | N: same, X: same, L: same |
| `RADEON_CP_RB_WPTR_DELAY` | `0x0718` | N: same, X: same, L: same |
| `RADEON_CP_CSQ_CNTL` | `0x0740` | N: same, X: same, L: same |
| `RADEON_SCRATCH_UMSK` | `0x0770` | N: —, X: —, L: same |
| `RADEON_SCRATCH_ADDR` | `0x0774` | N: —, X: —, L: same |
| `RADEON_CP_ME_RAM_ADDR` | `0x07d4` | N: same, X: same, L: same |
| `RADEON_CP_ME_RAM_DATAH` | `0x07dc` | N: same, X: same, L: same |
| `RADEON_CP_ME_RAM_DATAL` | `0x07e0` | N: same, X: same, L: same |
| `RADEON_SURFACE_CNTL` | `0x0b00` | N: same, X: same, L: same |
| `RADEON_AGP_COMMAND` | `0x0f60` | N: same, X: same, L: same |
| `RADEON_SCRATCH_REG1` | `0x15e4` | N: —, X: —, L: same |
| `RADEON_WAIT_UNTIL` | `0x1720` | N: same, X: same, L: same |
| `RADEON_ISYNC_CNTL` | `0x1724` | N: —, X: —, L: same |
| `RADEON_RB3D_ZCACHE_CTLSTAT` | `0x3254` | N: same, X: same, L: same |
| `RADEON_RB3D_DSTCACHE_CTLSTAT` | `0x325c` | N: same, X: same, L: same |
<!-- END cp_sequence.py -->
