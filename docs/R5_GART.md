# R5b — PCI GART 산술 (창·표·배치)

작성 2026-09-15.  **사실 추출**이다 — 링 위치 결정(PLAN §9-3)과 구현은 R5 계획서의 몫.
codex 검토 없이 쓴 문서라 수치는 전부 `tools/oracle/gart_oracle.py` 가 낸다.  그 자체검사는
원본 C 문장을 **실제로 컴파일한 프로그램**과 20,005 입력에서 대조하고(불일치 0), 486,510 개
배치(FB 시작 256 KiB 간격 전 구간 × FB 4–128 MiB × 창 4–64 MiB, 둘 다 2 의 거듭제곱)를 훑어
아래 성질을 확인한다 — 성질 1·2 는 **이 범위에서** 참이다.

## 1. 공식 (출처)

| 항목 | 공식 | 출처 |
|---|---|---|
| FB 위치·크기 | `fb_location = (MC_FB & 0xffff) << 16`, `fb_size = ((MC_FB & 0xffff0000) + 0x10000) − fb_location` (u32) | `radeon_cp.c:1312-1314` |
| GART 창 | `base = fb_location + fb_size`; u32 넘침이거나 `base + gart_size` 가 넘치면 `base = fb_location − gart_size`; `gart_vm_start = base & 0xffc00000` | `radeon_cp.c:1355-1361` |
| 레지스터 | `AIC_LO_ADDR = gart_vm_start`, `AIC_HI_ADDR = gart_vm_start + gart_size − 1` | `radeon_cp.c:1047-1066` |
| 표 | 32 KiB = 8192 항목, 항목 하나가 4 KiB(용량 32 MiB), 호스트 페이지마다 `PAGE_SIZE/4096` 항목 | `radeon_drv.h:1823`, `ati_pcigart.c:162-194` |
| PCI PTE | FreeBSD `le32(bus & 0xfffff000)`, Linux 3.10 `le32(bus)` — 플래그 없음 | 위, Linux `ati_pcigart.c` 139–189 행 |
| 창 안 배치(xf86) | 링 0, 링 맵 = 링 + **한 페이지**(`getpagesize()`), rptr 한 페이지, 버퍼 2 MiB, 나머지 텍스처 | xf86 `radeon_dri.c` 654–679 행 |

## 2. 계산으로 확인한 성질

1. **창이 FB 와 겹치는 것은 4 MiB 내림이 창을 실제로 옮긴 경우뿐이다**(훑은 범위에서 예외 0).
   FB 끝이 4 MiB 경계가 아니면 참고 구현은 **겹친 창을 경고 없이 쓴다**(겹침 검사가 없다 —
   `radeon_cp.c:1355-1361` 에 비교가 없음).  xf86 은 RV280 의 `MC_FB_LOCATION` 을 메모리 크기에
   맞춰 두므로(R1 파서의 판정 항목) 보통은 경계에 떨어지지만, BIOS 값이 그렇지 않을 수 있다 —
   PLAN R5b 의 "정렬 **뒤** 비겹침 계산" 이 필요한 이유가 이것이다.
2. **창은 "AGP 끔" 위치(`MC_AGP_LOCATION = 0xffffffc0` → `0xffc00000-0xffffffff`)에 들어가지
   않는다**(훑은 범위, 창 4–64 MiB).  넘침 규칙이 창을 FB 앞으로 보내기 때문이다.
3. **표 넘침(FreeBSD)은 창이 32 MiB 를 넘을 때만** 일어난다.  8 KiB 호스트 페이지에서 64 MiB 창은
   16,384 항목을 8,192 칸에 쓴다.  기본 8 MiB 창은 2,048 항목으로 넉넉하다.  Linux 식은 호스트
   페이지 수를 줄여 넘치지 않지만 창 뒷부분이 **매핑되지 않은 채** 남는다.  어느 쪽이든 32 MiB
   넘는 창은 32 KiB 표로 표현할 수 없다.
4. **8 KiB 페이지는 배치를 4 KiB 밀어낸다**: rptr 가 `0x101000` → `0x102000`, 버퍼가 `0x102000`
   → `0x104000`.  텍스처 크기는 입자(2^17) 내림이라 8 MiB 창에서는 둘 다 `0x4e0000`.
5. **PTE 마스크 차이**는 페이지 경계에 맞는 주소에서는 결과가 같고, 어긋난 주소에서만 다르다
   (FreeBSD 는 내림, Linux 는 그대로) — 우리 구현은 버스 주소가 페이지 경계인지 **확인**하는 쪽이
   두 해석을 모두 피한다.
6. 8 KiB 호스트 페이지 하나는 **4 KiB 항목 두 개**가 된다: 두 번째 항목의 주소는 `bus + 0x1000`.
   `translate()` 가 GPU 주소 → 버스 주소를 되풀어 확인한다.

## 3. R5 계획서가 정할 것

| # | 사실 | 결정할 것 |
|---|---|---|
| 1 | Linux 3.10 은 x86 에서 표를 쓴 뒤 `wbinvd()` 를 부른다(`ati_pcigart.c` 192 행).  FreeBSD 는 부르지 않는다 | OPENSTEP 커널에서 같은 조치가 필요한지·가능한지 — 소스로 **미확인** |
| 2 | 창이 FB 와 겹쳐도 참고 구현은 멈추지 않는다 | 겹치면 R5 를 거절(PLAN 금지 6 과 같은 방향) |
| 3 | 표는 32 KiB 고정, 창 32 MiB 초과는 표현 불가 | 창 크기 상한을 32 MiB 이하로 고정 |
| 4 | 8 KiB 페이지에서 항목 두 개 | R5b 게이트의 "두 반쪽" 시험(PLAN) 과 `translate()` 기대값을 연결 |

## 4. 생성표

<!-- BEGIN gart_oracle.py --markdown (generated; do not edit) -->
### 생성표 — 창·표·배치 시나리오

호스트 페이지 8 KiB(OPENSTEP i386 커널) 과 4 KiB(참고 구현의 전제) 를 나란히 둔다.

| MC_FB_LOCATION | GART | 페이지 | fb | 창(AIC_LO..HI) | 넘침 | 표 항목(FreeBSD/Linux/용량) | 문제 |
|---|---|---|---|---|---|---|---|
| `e7ffe000` | 8 MiB | 8 KiB | `e0000000`+`0x8000000` | `e8000000..e87fffff` | — | 2048 / 2048 / 8192 | — |
| `e7ffe000` | 8 MiB | 4 KiB | `e0000000`+`0x8000000` | `e8000000..e87fffff` | — | 2048 / 2048 / 8192 | — |
| `e7ffe000` | 32 MiB | 8 KiB | `e0000000`+`0x8000000` | `e8000000..e9ffffff` | — | 8192 / 8192 / 8192 | — |
| `e7ffe000` | 32 MiB | 4 KiB | `e0000000`+`0x8000000` | `e8000000..e9ffffff` | — | 8192 / 8192 / 8192 | — |
| `e7ffe000` | 64 MiB | 8 KiB | `e0000000`+`0x8000000` | `e8000000..ebffffff` | — | 16384 / 8192 / 8192 | FreeBSD table fill overflows: 16384 entries into 8192; window needs 16384 entries, table holds 8192 |
| `e7ffe000` | 64 MiB | 4 KiB | `e0000000`+`0x8000000` | `e8000000..ebffffff` | — | 8192 / 8192 / 8192 | window needs 16384 entries, table holds 8192 |
| `fffff800` | 8 MiB | 8 KiB | `f8000000`+`0x8000000` | `f7800000..f7ffffff` | 예 | 2048 / 2048 / 8192 | — |
| `fffff800` | 8 MiB | 4 KiB | `f8000000`+`0x8000000` | `f7800000..f7ffffff` | 예 | 2048 / 2048 / 8192 | — |
| `e07ee000` | 8 MiB | 8 KiB | `e0000000`+`0x7f0000` | `e0400000..e0bfffff` | — | 2048 / 2048 / 8192 | GART window [e0400000,+800000) overlaps the framebuffer [e0000000,+7f0000); aligned down from e07f0000 to e0400000 |
| `e07ee000` | 8 MiB | 4 KiB | `e0000000`+`0x7f0000` | `e0400000..e0bfffff` | — | 2048 / 2048 / 8192 | GART window [e0400000,+800000) overlaps the framebuffer [e0000000,+7f0000); aligned down from e07f0000 to e0400000 |
| `e3ffe000` | 8 MiB | 8 KiB | `e0000000`+`0x4000000` | `e4000000..e47fffff` | — | 2048 / 2048 / 8192 | — |
| `e3ffe000` | 8 MiB | 4 KiB | `e0000000`+`0x4000000` | `e4000000..e47fffff` | — | 2048 / 2048 / 8192 | — |

### 생성표 — xf86 창 안 배치 (8 MiB 창)

| 페이지 | 링 | rptr | 버퍼 | 텍스처 | 텍스처 입자 |
|---|---|---|---|---|---|
| 4 KiB | `0x000000`+`0x101000` | `0x101000`+`0x1000` | `0x102000`+`0x200000` | `0x302000`+`0x4e0000` | 2^17 |
| 8 KiB | `0x000000`+`0x102000` | `0x102000`+`0x2000` | `0x104000`+`0x200000` | `0x304000`+`0x4e0000` | 2^17 |
<!-- END gart_oracle.py -->
