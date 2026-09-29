# M2a — 제출마다의 `WBINVD` 를 상류대로 되돌린다 (드라이버, 재부팅 필요)

M1z 가 잰 값: **`cpFence` 의 `WBINVD` 가 제출당 94.46 us, ZCLEAR 당 188.91 us,
커널 연산 400.72 us 의 47 %.**  명령어 하나가.

이 칸의 근거는 우리 측정이 아니라 **참고 구현 전수 조사**다.

## 1. 참고들은 제출 경로에서 CPU 캐시를 건드리지 않는다

`ref/upstream` 전체에서 CPU 캐시 관리 낱말을 셌다(`wbinvd`, `clflush`, `flush_cache`,
`cache_flush`, `bus_dmamap_sync`, `pci_dma_sync`, `dma_sync`):

| 파일 | 무엇 |
|---|---|
| `linux-ati_pcigart.c:190-194` | **`wbinvd()` 한 번** — GART 표를 다 채운 **직후**.  x86 아니면 `mb()` |
| `freebsd-stable9/sys/dev/drm/ati_pcigart.c` | **아무것도 없다**(위 낱말 전부 0 건) |
| `radeon_cp.c` 의 `cache_flush` | `radeon_do_pixcache_flush` — **GPU** 쪽 캐시다(`RB3D_DSTCACHE`), CPU 가 아니다 |
| `xf86-video-ati-6.14.6/src/` | 0 건 |
| `Mesa-6.5.3` 의 `dri/radeon`·`dri/r200` | 0 건 |

그리고 제출 경로 자체(`radeon_commit_ring`)는 **배리어 하나**뿐이다:

    /* pad with some CP_PACKET2 */            <- 우리 cpR6Submit 과 같다
    dev_priv->ring.tail &= dev_priv->ring.tail_mask;
    DRM_MEMORYBARRIER();                      <- 여기가 우리의 WBINVD 자리다
    GET_RING_HEAD( dev_priv );
    RADEON_WRITE(RADEON_CP_RB_WPTR, dev_priv->ring.tail);
    RADEON_READ(RADEON_CP_RB_RPTR);           /* posting */   <- 우리도 한다

(`radeon_cp.c:2090-2126` — FreeBSD.  리눅스의 같은 파일 `linux-radeon_cp.c:2203-2239` 도
같은 함수 같은 모양이다.)

## 2. 왜 배리어로 충분한가 — GART 엔트리가 말한다

`ati_pcigart.c` 는 GART 엔트리에 인터페이스별로 플래그를 붙인다:

    case DRM_ATI_GART_IGP:  page_base |= ATI_GART_READ | ATI_GART_WRITE;
                            page_base |= ATI_GART_NOSNOOP;      break;
    case DRM_ATI_GART_PCIE: ... | ATI_GART_NOSNOOP;             break;
    default:
    case DRM_ATI_GART_PCI:                                      break;   <- 우리

**우리 경우(RV280, 평범한 PCI)는 `default:` 이고 플래그가 하나도 안 붙는다.**
`ATI_GART_NOSNOOP` 은 **0x1**(`ati_pcigart.c:42-44`) — 그것을 안 붙인다는 것은
**스누핑을 켜 둔다**는 뜻이다.  카드의 GART 읽기가 CPU 캐시를 스누프하므로 더러운
라인을 본다.  **그래서 상류는 플러시를 안 한다.**

우리 엔트리도 같다.  `osrdn_cp_pte` 는 `(phys + off) & 0xfffff000UL` 을 돌려주고
**하위 12 비트가 전부 0** 이다 — 플래그 없음, 즉 상류의 PCI 분기와 **바이트 단위로 같은 규약**.

(두 참고가 IGP/PCIe 에서는 어긋난다: FreeBSD 는 `READ|WRITE|NOSNOOP` = 0xd,
리눅스는 0xc 로 **NOSNOOP 을 안 붙인다**(python 으로 상수 대조).  우리 경우가 아니므로
기록만 한다 — 참고가 서로 다를 때 어느 쪽을 믿을지는 별개 문제다.)

### 2-0. 상류의 링도 **우리 블록과 같은 종류의 메모리**다

"상류는 링을 캐시 안 되는 메모리에 두었기 때문에 플러시가 필요 없는 것 아닌가" 를
확인했다.  아니다.  AGP 가 아닐 때:

    RADEON_WRITE(RADEON_CP_RB_RPTR_ADDR,
        dev_priv->ring_rptr->offset - dev->sg->vaddr + dev_priv->gart_vm_start);

`radeon_cp.c:742-746` 이 rptr 영역을 그렇게 잡고, **링 자체도 같은 식**이다:

    ring_start = (dev_priv->cp_ring->offset - dev->sg->vaddr + dev_priv->gart_vm_start);
    RADEON_WRITE(RADEON_CP_RB_BASE, ring_start);

`radeon_cp.c:723-726`.  **링의 베이스가 `dev->sg` 안의 오프셋으로 문자 그대로 계산된다.**
그리고 그 sg 는 GART 로 카드에 보이게 한 **평범한 커널 RAM** 이다 —
`linux-ati_pcigart.c:112-113` 이 직접 그렇게 말한다("PCI: no table in VRAM: using **normal RAM**").

**우리 블록과 같은 종류다.**  그러니 상류가 링 메모리에 대해 우리가 안 하는 무언가를
하고 있는 것이 아니다.

### 2-0-1. 리눅스의 그 한 번의 `wbinvd` 가 링까지 덮는 것 아닌가 — 아니다

`ati_pcigart.c` 의 `wbinvd()` 는 **초기화 때 한 번**이다.  그 시점에 쓴 것을 되쓸 뿐,
**나중에 쓰는 링 워드를 덮을 수 없다**.  그리고 FreeBSD 판에는 **그 한 번조차 없는데도**
같은 카드가 돈다 — 낱말 전수 0 건(§1).

### 2-1. 반대 방향도 마찬가지다 — 카드가 쓴 것을 **무효화 없이 읽는다**

상류에서 카드가 시스템 메모리에 쓰고 CPU 가 읽는 자리가 둘 있다: RPTR 되쓰기와
스크래치 되쓰기.  AGP 가 아닐 때 그 읽기는 **그냥 volatile 읽기**다:

    *(((volatile u32 *) dev_priv->ring_rptr->virtual) + (off / sizeof(u32)))

`radeon_cp.c:73-80` 와 `radeon_cp.c:55-65`.  **무효화가 없다.**

그리고 상류는 그것이 되는지 **실행 시점에 시험한다**(`radeon_cp.c:794-823`):
메모리 자리에 0 을 쓰고, `SCRATCH_REG1` 에 `0xdeadbeef` 를 넣고, 그 메모리 자리를
**캐시 연산 없이 폴링**해서 값이 오면 `writeback_works = 1`.  캐시를 한 번도 안 건드린다.

즉 **양방향 모두 스누핑이 설계 전제**다.  (우리 드라이버는 `RB_NO_UPDATE` 와
`SCRATCH_UMSK = 0` 으로 되쓰기를 꺼 두므로 카드→CPU 방향에는 애초에 의존하지 않는다.
이 칸이 건드리는 것은 CPU→카드 방향뿐이다.)

### 2-2. 가장 강한 근거는 **이 머신에서 이미 도는 우리 드라이버들**이다

상류는 다른 머신에서 돈다.  같은 OPENSTEP, **같은 물리 머신**에서 이미 동작하며 공개까지
끝난 우리 드라이버 다섯을 전수로 훑었다(`wbinvd`·`WBINVD`·`clflush`·`invd`):

| 드라이버 | 캐시 명령 | DMA 메모리를 어떻게 잡나 |
|---|---:|---|
| `openstep-intel1000` (Intel 8254x 기가비트) | **0 건** | `IOMalloc` + `IOPhysicalFromVirtual`(`Pro1000.m:674-709`) |
| `openstep-emu10k1` (SB Live!) | **0 건** | `IOMalloc`/**`IOMallocLow`** + `IOPhysicalFromVirtual` |
| `openstep-ac97` (ICH5) | **0 건** | 같은 방식 |
| `openstep-matrox-remade` (G450, WARP 3D) | **0 건** | |
| `openstep-mdh10` | **0 건** | |

세 드라이버 모두 **인라인 asm 이 0 줄**이다 — 캐시 명령을 쓸 수단조차 없다.

**그중 `openstep-intel1000` 이 결정적이다.**  기가비트 NIC 의 서술자 링은 우리 링과 똑같은
모양이다: CPU 가 서술자를 쓰고 카드가 읽고, 카드가 상태를 되쓰고 CPU 가 읽는다.  그 메모리는
`IOMalloc` 으로 잡은 **평범한 캐시 메모리**이고 물리 주소는 `IOPhysicalFromVirtual` 로 얻는다 —
**우리 CP 블록과 같은 방식**(`emu10k1` 은 `IOMallocLow` 까지 같다).  그 드라이버는 **v1.0 으로
완성돼 공개됐고 이 머신에서 돈다.**

**이 머신이 스누프하지 않는다면 그 NIC 는 애초에 동작할 수 없다.**  §5-2 가 "참고가
증명하지 못한다" 고 적은 바로 그 빈칸을, 우리 저장소가 메운다.

그래도 **손잡이는 기본 꺼짐으로 간다**: 이것은 강한 정황이지 이 드라이버의 이 경로에 대한
측정이 아니고, 이 프로젝트의 규칙은 하드웨어를 판정하는 것은 실기뿐이라는 것이다.

## 3. 우리 `cpFence` 와 상류의 차이는 한 줄이다

    cpFence(base):                      상류의 제출 경로:
        osrdn_cpu_wbinvd();      <---   (없다)
        osrdn_cpu_serialize();   <===   DRM_MEMORYBARRIER()
        rdnMmioRead32(RBBM_STATUS);     RADEON_READ(CP_RB_RPTR)  /* posting */

`osrdn_cpu_serialize` 는 잠금 `xchg` 하나다(`osrdn_cpu.m`) — **그것이 바로 메모리
배리어**다.  그러니 `cpFence` 는 이미 상류가 하는 일을 다 하고 있고, **`wbinvd` 만 더 한다.**

그리고 MAP 의 펜스는 리눅스가 `wbinvd()` 를 두는 바로 그 자리다: `cpMap` 은
`cpFillBlock`(= GART 표를 채운다) 다음에 `cpFence` 를 부른다.  **거기는 그대로 둔다.**

## 4. 이 칸이 하는 일

`cpR6Submit` **한 자리에서만**, 손잡이로 `wbinvd` 를 건너뛴다.

    if (!c->noWbinvd)
        osrdn_cpu_wbinvd();
    osrdn_cpu_serialize();
    (void)rdnMmioRead32(base, C_RBBM_STATUS);

- 기본값은 **오늘 그대로**(`wbinvd` 함).  손잡이를 켜야 상류 모양이 된다.
- 나머지 여섯 `cpFence` 호출처(MAP·START·PREPARE·ZPREP·프리필 둘)는 **안 건드린다**.
- 값은 **M1z 의 `fence` 누적기가 그대로 잰다** — 새 계측기가 필요 없다.
  한 부팅에서 손잡이 끈 팔과 켠 팔을 나란히 돌리면 두 값이 같은 줄에 나온다.

## 4-1. 우리 쪽 방향은 하나뿐이다 — 그리고 그것이 약해지는 곳도 하나다

드라이버의 설계 노트가 못 박아 두었다(`osrdn_cp.h:21-27`):

> the GPU only ever READS system memory: RB_NO_UPDATE and SCRATCH_UMSK 0,
> and the one address a writeback could reach is the spare page, whose canary
> every operation checks

그러니 **카드→CPU 방향은 설계상 없다**.  이 칸이 건드리는 것은 CPU→카드 하나뿐이고,
그것이 바로 상류가 배리어로 처리하는 방향이다.

**정직하게 약해지는 것 하나**: `cpCheckBlock` 의 카나리아는 **빗나간** 카드 쓰기를 잡으려고
있다.  오늘은 제출마다의 `wbinvd` 가 블록 전체를 무효화하므로 그 다음 읽기가 반드시
메모리를 본다.  `wbinvd` 를 빼면, 빗나간 쓰기를 보려면 **스누핑이 그 라인을 무효화해
주어야** 한다.

즉 카나리아의 민감도가 **이 칸이 시험하려는 바로 그 성질에 묶인다**.  스누핑이 되면
카나리아도 그대로 동작하고, 안 되면 카나리아는 눈이 멀지만 **그때는 그림이 먼저 깨지고**
마커와 프리픽스 되읽기가 잡는다(§5).  그래서 손잡이는 **기본 꺼짐**이고, 실기가
스누핑을 증명하기 전에는 기본값을 바꾸지 않는다.

## 5. 틀렸을 때 무엇이 잡나

이 머신의 칩셋이 스누프하지 않는다면 카드가 **낡은 링 워드**를 읽는다.  그때:

| 잡는 것 | 어떻게 |
|---|---|
| `cpCheckBlock` 의 링 대 그림자 | 제출마다 4,096 워드를 비교한다.  카드가 링 밖에 쓰면 카나리아가 센다 |
| 마커 `SCRATCH_REG0 == seed` | 프리픽스가 소비됐는지.  낡은 워드를 읽었으면 seed 가 안 온다 |
| 프리픽스 레지스터 9 개 되읽기 | 낡은 PACKET0 이 실행됐으면 값이 어긋난다 |
| R6 다이제스트·커버리지 | 그린 것이 오라클 예측과 다르면 판정기가 FAIL |
| `cpWait` 의 한도 + `cpLatch` | CP 가 멈추면 100 ms 뒤 걸쇠, 패닉이 아니다 |

**가장 그럴듯한 실패는 걸쇠이지 크래시가 아니다**: 낡은 링 워드는 직전 제출이 남긴
`CP_PACKET2`(무동작)이거나 옛 PACKET0 이고, 프리픽스가 레지스터를 매번 다시 세운다.
그래도 손잡이는 **기본 꺼짐**이고, 켜는 팔은 **가장 작은 경우부터** 돈다.

## 5-2. 참고가 **증명하지 못하는** 것 — 그래서 실기가 필요하다

참고 전수 조사가 보여 주는 것은 "상류는 제출 경로에서 CPU 캐시를 안 건드린다" 와
"그 설계가 스누핑을 전제한다" 까지다.  **이 머신의 `IOMallocLow` 메모리가 실제로
일관성 있는 스누핑에 참여하는지는 참고가 말해 주지 않는다.**

구체적 차이가 하나 있다.  리눅스는 GART 가 가리킬 페이지마다 매핑을 세운다:

    entry->busaddr[i] = pci_map_page(dev->pdev, entry->pagelist[i],
                                     0, PAGE_SIZE, PCI_DMA_BIDIRECTIONAL);

`linux-ati_pcigart.c:154-155`.  우리 드라이버는 그런 DMA 매핑 API 를 **부르지 않는다** —
`IOMallocLow` 로 잡고 `IOPhysicalFromVirtual` 로 물리 주소만 얻는다.  x86 에서 그 호출은
주소 변환이지 캐시 작업이 아니지만, **없다는 사실 자체는 참고가 메워 주지 않는 구멍**이다.

그러므로 이 칸의 구조는 이렇게 된다:

| 증명하는 것 | 누가 |
|---|---|
| "플러시가 없으면 **스누핑 없는 세계**에서 깨진다" | 호스트(`world5`, §6-1) |
| "상류는 제출 경로에서 캐시를 안 건드린다" | 참고 전수 조사(§1·§2) |
| **"이 머신은 스누프한다"** | **실기뿐** — 그래서 손잡이는 기본 꺼짐 |

## 5-1. 미러에서 확인 **못 한** 것 하나

`DRM_MEMORYBARRIER` 의 정의는 이 미러에 **없다**(drmP.h 계열이 안 들어 있다).
DRM 관례로는 `mb()` 이고 x86 에서 그것은 잠금 접두 명령 또는 `MFENCE` 이며, 우리
`osrdn_cpu_serialize` 의 잠금 `xchg` 와 같은 급이다 — 그러나 **그것은 관례에 대한 내 지식이지
이 미러가 증명한 것이 아니다**.  근거의 등급을 낮춰 적어 둔다
([[absence-claims-need-history-grep]] 의 정신: 못 본 것은 못 본 것).

실질적으로는 문제가 안 된다: 우리는 `osrdn_cpu_serialize` 를 **빼지 않는다**.  이 칸은
`wbinvd` 하나만 건너뛴다.

## 5-3. codex 교차검토 — 판정표

물은 것은 **참고를 내가 제대로 읽었는가, 그리고 무엇을 안 덮는가**.  전건을 원문에서
직접 열어 확인했다([[codex-cross-review-practice]]).

| codex 주장 | 내가 확인한 방법 | 판정 |
|---|---|---|
| **리눅스는 IGP/PCIe 에도 `0x1` 을 안 붙인다 — "NOSNOOP 은 IGP/PCIe 에만" 은 FreeBSD 트리 얘기다** | 두 파일을 열어 python 으로 상수를 맞췄다: FreeBSD 0xd, 리눅스 0xc | ✅ 사실 — **그런데 §2 가 이미 그렇게 적고 있다**(내가 먼저 찾았다) |
| 두 트리 모두 **평범한 PCI 는 플래그 없는 생 페이지 주소**로 일치한다 | 같은 두 분기 | ✅ 사실 |
| (b) 참고의 링은 `dev->sg`(평범한 RAM)에 있고, 제출 경로가 링 메모리에 하는 캐시 작업은 없다 | `radeon_cp.c:2090-2126` 전문 | ✅ 사실 |
| (b) **"`ring.start` 가 `dev->sg` 의 어느 오프셋인지는 허용된 발췌에 없어 추론"** | **원문에 있다**: `radeon_cp.c:723-726` 이 `ring_start = cp_ring->offset - dev->sg->vaddr + gart_vm_start` 를 계산해 `CP_RB_BASE` 에 쓴다 | ❌ **기각 — 추론이 아니라 명시**(codex 가 덜 읽었다) |
| (c) 리눅스의 그 한 번의 `wbinvd` 는 **나중의 링 쓰기를 덮을 수 없다**, FreeBSD 는 그것조차 없다 | `linux-ati_pcigart.c:190-194` 의 위치와 FreeBSD 파일의 낱말 0 건 | ✅ 채택 — §2-0-1 이 그 말을 한다 |
| (d) `DRM_MEMORYBARRIER` 의 전개는 **이 미러에 없다**; 잠금 `xchg` 는 순서로는 동등하거나 강하지만 **되쓰기는 아니다** | grep 0 건.  `osrdn_cpu.m` 의 `xchgl` + `"memory"` | ✅ 채택 — §5-1 이 근거 등급을 낮춰 적는다 |
| (e) 오늘의 `wbinvd` 는 **WPTR 쓰기 앞**이므로, 그 제출이 만들어 낼 카드 쓰기를 보이게 하는 장치일 수 없다 | `osrdn_cp.m:2396-2405` 를 열었다: 펜스 → `CP_RB_WPTR` → posting.  맞다 | ✅ 사실.  §4-1 의 논리는 그와 별개다(펜스가 **무효화**해 두면 그 뒤 첫 읽기가 메모리를 본다) |
| **참고는 이 머신의 `IOMallocLow` 메모리가 실제로 스누핑에 참여하는지 증명하지 못한다**; 리눅스는 `pci_map_page(..., PCI_DMA_BIDIRECTIONAL)` 로 매핑을 세우는데 우리는 그런 호출이 없다 | `linux-ati_pcigart.c:154-155` 를 열었다.  우리 쪽은 `IOMallocLow` + `IOPhysicalFromVirtual` 뿐(전수) | ✅ **채택 — §5-2 를 새로 썼다.  이 칸의 구조를 정하는 지적이다** |

**내가 틀렸던 것**: 없다.  다만 (b) 에서 codex 가 "추론"이라고 한 것을 원문에서 찾아
**명시로 올렸다** — 참고를 더 읽으면 근거가 올라간다는 쪽의 예다.

## 6. 게이트 — 돌린 것과 그 결과

| # | 게이트 | 결과 |
|---|---|---|
| 1 | `check_r5_src` — 새 규칙 `m2a-nowb` + 변이 5 개 | **PASS**, 다섯 전부 목표 규칙이 잡음 |
| 1b | `world5` 새 절 — **손잡이를 켜면 스누핑 없는 모델이 깨진다** | **`world5: PASS`**, 깨지는 방식까지 단언(`CP_WHY_MARKER`) |
| 1c | `sim_r5` 전체 | **`sim_r5: PASS`** — 기존 변이 하나를 재조준하고 새 변이 하나 추가 |
| 1d | `judge_m1l --self-test` | **PASS**; `t-stage` 대 `t-nowb` 를 **워드 단위로** 비교하는 짝을 넣었다 |
| 1e | `check_cp`·`check_r5d` 자체시험 | **PASS** — `nowb=` 를 붙인 상태 줄에 합성 줄을 맞췄다 |
| 2 | `sh tools/check-all.sh` 전건 | **FAIL 줄 0, `CHECKALL_RC=0`** (178 줄); 인용 860 건 0 실패 |
| 3 | 타깃 빌드 + `nm -u` | **`OSRDNBUILD PASS stamp=b2192cf5 runid=790146260 symbols=21`** |
| 3b | 호스트 `check_reloc_r2b0` | **처음엔 FAIL** — 아래 6-3 |
| 3c | 실린 바이트 `calls_in.py` | 아래 6-4 |
| 4 | 설치 | **`INSTALL DONE runid=790146260`** (`closed=yes fresh live`) |

### 6-3. 릴로크 게이트가 새 함수를 **거부했다** — 그게 그 게이트의 일이다

    FAIL _rdnMmioRead32 is called from _cpSubmitFence at 000087ac,
         which is not on its list [...]

`check_reloc_r2b0.py` 는 **어떤 함수가 MMIO 를 읽어도 되는지 이름으로 적어 둔다**.
`cpSubmitFence` 는 새 함수이므로 목록에 없었다.  느슨하게 하지 않고 **이름을 등록**했다 —
"하드웨어에 닿는 새 함수는 발견되는 게 아니라 선언돼야 한다" 가 그 목록의 요지다.

### 6-4. 실린 바이트

    _cpR6Submit    460 B  calls: 12  [_cpPut, _cpPut, <ext>, _cpSubmitFence, <ext>, ...]
    _cpSubmitFence  52 B  calls: 3   [_osrdn_cpu_wbinvd, _osrdn_cpu_serialize, _rdnMmioRead32]
    _cpFence        44 B  calls: 3   [_osrdn_cpu_wbinvd, _osrdn_cpu_serialize, _rdnMmioRead32]
    _cpNoWb         32 B  calls: 0

제출 경로는 `_cpSubmitFence` 를 부르고 `_cpFence` 는 **안 부른다**.  일반 펜스는 그대로 있다.

### 6-1. 호스트 모델은 **느슨해지지 않았다**

`world5.c` 는 여전히 스누핑 없는 세계다.  새 절은 그 세계에서 손잡이를 켜고
**깨지는 것을 단언한다**:

    ok  M2a: the knob skips the submission wbinvd, and a world without snooping
            breaks when it does

그리고 `sim_r5` 에 "손잡이를 켰는데도 플러시가 난다" 변이를 넣어, 이 단언이 **발동한다**는
것을 같은 실행에서 보였다.

| 증명하는 것 | 누가 |
|---|---|
| "플러시가 없으면 스누핑 없는 세계에서 깨진다" | 호스트(위) |
| "상류는 제출 경로에서 캐시를 안 건드린다" | 참고 전수 조사(§1·§2) |
| **"이 머신은 스누프한다"** | **실기뿐** — 손잡이 기본 꺼짐 |

### 6-2. 곁가지로 고친 것

- `cpOpNames` 와 도구의 `opNames` 는 **각자 자기 크기만 검사**하고 있었고, **둘이 서로
  맞는지는 아무도 안 봤다** — 새 연산을 넣기 전에 그 이음매를 규칙으로 박았다
  (`m1z-opnames` 가 두 표와 헤더 상수를 대조; 변이 3 개)
  ([[checker-discipline]]).
- `check_cp` 의 "드라이버의 모든 IOLog 형식에 합성 줄이 있어야 한다" 검사가 또 걸렸다 —
  `RDN-R5 state` 줄에 `nowb=` 를 붙였기 때문.  **그 검사의 존재 이유가 그것이다.**

## 7. 부팅 뒤에 할 일

`t-stage`(손잡이 끔)와 `t-nowb`(켬)의 `tstage` 줄을 나란히 놓는다.

    RDN-R5 tstage ... s1ring=.. s2ring=.. fence=<여기> wait=..

- **`fence=` 가 거의 0 으로 내려가야** 한다(오늘 188.91 us/ZCLEAR).
- **그림이 안 움직여야** 한다 — 판정기가 두 팔의 삼각형을 워드 단위로 비교한다.
- `canary`·`ring` 이 0 이어야 한다.  `RDN-R5 state ... nowb=1` 이 그 팔의 줄에 있어야 한다.
- 하나라도 어긋나면 **이 머신은 스누프하지 않는 것**이고, 그때 답은 `wbinvd` 가 아니라
  §5-2 가 말한 대로 블록만 CLFLUSH 하는 쪽이다(다음 칸).

## 8. 실기 결과 (2026-09-23, 부팅 `0751eca4`, 재부팅 1 회)

손잡이 끈 팔과 켠 팔, 같은 제출 수(2,166):

    OFF  ... s1ring=267051 s2ring=373791 ... fence=410124 wait=125797
    ON   ... s1ring=66482  s2ring=175151 ... fence=17689  wait=128383

| 구간 | 끔 us/ZCLEAR | 켬 | 차이 |
|---|---:|---:|---:|
| gates | 6.97 | 6.96 | −0.2 % |
| preamble | 20.04 | 20.01 | −0.1 % |
| **stage1 ring** | 123.29 | 30.69 | **−75.1 %** |
| stage1 read-backs | 10.95 | 10.50 | −4.1 % |
| stage2 assemble | 5.83 | 4.76 | −18.4 % |
| **stage2 ring** | 172.57 | 80.86 | **−53.1 %** |
| pixcache flush | 12.70 | 12.30 | −3.2 % |
| tail | 46.45 | 45.78 | −1.5 % |
| **커널 연산** | **398.81** | **211.86** | **−46.9 %** |
| `fence` | **189.35** | **8.17** | **−95.7 %** |
| `wait` | 58.08 | 59.27 | +2.1 % |

**`WBINVD` 하나가 ZCLEAR 당 181.18 us 였다.**  남은 8.17 us 가 배리어와 상태 읽기다.
그리고 그 181 us 가 두 링 구간이 잃은 184.31 us 의 **98.3 %** 를 설명한다.

### 8-1. 안전 — 그림도 카나리아도 움직이지 않았다

    ok  t-stage.out vs t-nowb.out: all 8 logged triangles identical word for word
    ok  leg=2 drew 3 pixels ... leg=32 drew 528 pixels, exactly what the raster rule predicts
    RDN-R5 block table=0 guard=0 spare=0 canary=0 ring=0
    RDN-R5 state ... failed=0 ... nowb=1

상태 줄 **848 개 전부 `failed=0`, `failed=1` 은 0 개**.  손잡이를 켠 팔이 2,166 제출을
끝까지 돌았다는 것 자체가 증거다 — 카나리아가 한 번이라도 울렸다면 `failed` 가 걸려
그 뒤 모든 ZCLEAR 이 거절됐을 것이고 계수는 거기서 멈췄을 것이다.

**§5-2 가 "실기뿐"이라고 적은 칸이 채워졌다: 이 머신은 스누프한다.**

### 8-2. 커널이 잃은 것보다 **더** 빨라졌다 — 그 차이가 캐시다

    커널 연산      398.81 -> 211.86 us   (−186.95)
    제출당 고정비  476    -> 256    us   (−221)

**34 us 가 더 빠지다.**  `WBINVD` 는 캐시 **전체**를 버리므로, 그 뒤 라이브러리는 차가운
캐시로 돌았다.  그 34 us 는 그 명령이 버리고 있던 캐시다.  추정이 아니라 **서로 독립인 두
측정**(드라이버의 단계 계측기, 클라이언트의 벽시계)의 차이가 정확히 **드라이버 바깥에서
일어나는 일**만큼이다.

한계비는 **안 움직였다**: 2.021 → 2.065 us/삼각형.  제출당 명령을 뺐으니 그래야 맞다.

### 8-3. 교차점이 내려왔다

| | n=72 | n=131 | n=∞ |
|---|---:|---:|---:|
| M1y 전 (고정 565) | 722 | 424 | 62 |
| M1y 뒤 (477) | 619 | 368 | 62 |
| **M2a 뒤 (256, 실측)** | **360** | **226** | 62 |
| 제출이 공짜라면 | 62 | 62 | 62 |

### 8-4. 판정기 규칙을 **쪼갰다**(느슨하게가 아니라)

실기 결과가 처음엔 FAIL 이었다: 판정기는 짝의 **고정비가 다르면 비교 불가**로 본다.
그 규칙은 한계비만 건드리는 손잡이(M1r·M1t·M1v)를 위한 것이고, M2a 는 **고정비가 결과**다.

쪼갠 뒤:

- 고정비가 **오르면** FAIL(이 손잡이는 일을 뺄 수만 있다)
- **한계비가 움직이면** FAIL(제출당 명령이므로 삼각형당이 바뀔 리 없다)
- 그 외에는 고정비 변화를 **값으로 보고**한다

자체시험 세 개가 세 갈래를 다 돈다 — 통과 한 개, FAIL 두 개.

