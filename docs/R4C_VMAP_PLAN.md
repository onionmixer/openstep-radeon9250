# R4c — 오프스크린 VRAM 을 문자 디바이스 `d_mmap` 으로 유저 태스크에 (계획, 코딩 전, 교차검토 대상, 2026-09-18)

선행: R4a/R4b 실기 PASS(`docs/R4_ENGINE_PLAN.md` 18 절).  operator 결정: 창은 **Matrox 식**(모드마다 시작, 끝 124 MiB),
**임대 없음**(`PLAN.md` V 절 2026-09-18), VRAM 128 MiB 가정.  이 문서가 `docs/R4_ENGINE_PLAN.md` 3-8·9-2 의 14·11-3 의 R4c
부분을 대체한다(충돌하면 이 문서가 이긴다).

## 0. 한 줄 요약

키 `"RDN VRAM Mmap" = "Yes"` 일 때 init 의 **마지막 단계**로 문자 디바이스를 자동 major 로 등록하고, `d_mmap` 은 창
`[winStart, 124 MiB)` 안의 페이지만 PFN 으로 답하는 **등록 뒤 불변인 상태 위의 순수 산술**로 둔다.  유저 도구 `rdnr4map` 이
경계(창 첫·끝 페이지 허용, 그 밖 거절), 캐시 일관성(엔진·커널 별칭 → 유저, 유저 → 엔진), 64 MiB 에일리어싱을 실기에서 본다.

## 1. 확인한 사실 (이 세션에서 원문·IDA 를 열어 확인, 2026-09-18)

실기 커널 이미지 `ref/openstep/ps2/mach_kernel`(Matrox 가 IDA 로 본 것과 같은 주소 — `_smmap` 0x106e58, `_vm_object_special` 0x17c17c).

| # | 사실 | 근거 |
|---|---|---|
| F1 | `smmap` 은 `d_mmap(dev, fileOffset + i·page_size, prot)` 을 요청 길이만큼 **먼저 전부** 부르고, 하나라도 `-1` 이면 EINVAL(매핑 없음).  `dev` 는 vnode 의 16 비트 rdev 를 부호 확장, `prot` 은 유저가 준 값 그대로 | `_smmap` 어셈블리 0x106fa0–0x106fc8(`push prot; push off+ebx; push dev; call esi; cmp eax,-1`) |
| F2 | 장치 매핑은 `MAP_SHARED`(flags = 1) 만, `PROT_WRITE` 를 청하려면 fd 가 쓰기로 열려 있어야, 주소는 호출자가 이미 읽기·쓰기로 소유한 곳(`vm_map_check_protection(…, 3)`) — **4.2BSD `mmap`, 성공 반환 0** | 같은 함수 0x106fcd(`cmp [ecx+0Ch],1`), Hex-Rays `(v19 & 2) && !(fp->f_flag & 2)` → 22, 0x106f2f |
| F3 | 이어서 `vm_object_special` 이 **페이지마다 한 번 더** `d_mmap` 을 부르고 반환값을 **검사 없이** `<< page_shift` 해 물리 주소로 쓴다 → `d_mmap` 은 같은 입력에 늘 같은 답이어야 한다(Matrox S4A 1-3 과 같음) | `_vm_object_special` Hex-Rays: `v10 = a2(a1, a4 + (v8 << page_shift), a3); *v9 = v10 << page_shift;` |
| F4 | **매핑마다 `kalloc(48 × 페이지 수 + 16)`** 을 한 번에 잡고 모든 페이지를 즉시 삽입한다.  창 전체(14 734–15 814 페이지)를 한 번에 매핑하면 커널 메모리 707–759 KB(python).  **새 사실** — Matrox 문서에 없다 | 같은 함수 `v5 = 48 * v14 + 16; v6 = kalloc(v5); bzero(v6, v5)` (kalloc 실패 검사 없음) |
| F5 | `pmap_enter` 가 만드는 PTE 는 `phys | 보호(비트 1–2) | P(비트 0)` 와 wired 표시 0x200 뿐 — **PCD(0x10)·PWT(0x08) 를 세우는 명령이 함수 안에 없다**.  8 KiB VM 페이지당 PTE 2 개 | `_pmap_enter`(0x19065c) 어셈블리 전체: 0x190a66–0x190a95, 0x19082e–0x19085d |
| F6 | `IOMapPhysicalIntoIOTask` 도 같은 `pmap_enter(…, prot 3, wired 1)` 로 매핑한다 → R4a/R4b 가 "uncached 별칭" 이라 부른 매핑과 유저 매핑은 **PTE 캐시 속성이 같다**.  실효 메모리 형식은 이 물리 구간의 **MTRR**(BIOS 설정, 미측정)이 정한다 | `_IOMapPhysicalIntoIOTask`(0x1a9368) Hex-Rays |
| F7 | 따라서 R4a/R4b 판정(별칭으로 표지를 쓰고 되읽은 뒤, 엔진이 쓴 색을 같은 별칭으로 읽어 불일치 0)은 **이 구간이 WB 로 캐시되지 않는다**는 간접 증거다 — WB 였다면 되읽기가 캐시의 표지를 돌려줬을 것.  유저 매핑도 같은 물리 구간이므로 **같게 동작할 것으로 예측**한다.  예측일 뿐이고 판정은 5 절의 stale 시험이 한다 | F5·F6 + `docs/R4_ENGINE_PLAN.md` 18 절 |
| F8 | export: `_page_size`·`_page_shift`·`_IOAddToCdevswAt`·`_IOAddToCdevsw`·`_IORemoveFromCdevsw`·`_nodev`·`_nulldev`·`_vm_object_special`·`_smmap` 있음, `_enodev` 없음 | `tools/host/kernel_symbols.py ref/openstep/ps2/mach_kernel --check …` |
| F9 | `+addToCdevswFromDescription:open:close:read:write:ioctl:stop:reset:select:mmap:getc:putc:` — 키 `"Character Major"` 가 없으면 첫 빈 major, 실패면 NO, `+characterMajor` 와 매개변수 `"IOCharacterMajor"` 로 조회 | `ref/openstep/headers/.../driverkit/IODevice.h` 77–104·187 행 |
| F10 | `PROT_READ 1`, `PROT_WRITE 2`, `PROT_EXEC 4`, `MAP_SHARED 1` | 같은 헤더 트리 `bsd/sys/mman.h` 29–35 행 |
| F11 | 브리지 prefetch 창 `e0000000–efffffff`, BAR0 `e0000000` — 창 끝 `bar0 + 124 MiB = e7c00000` 를 담는다 | `docs/R1_RESULT.md` 25–26 행 |
| F12 | 우리 모드 설정은 `CRTC_GEN_CNTL` 을 `EXT_DISP_EN | 형식` 으로 통째로 쓴다 → 하드웨어 커서(비트 16) 꺼짐, 커서 VRAM 은 창과 무관 | `osrdn_mode.m` `modeGenCntl`; 실측 `got=03000600`(`docs/R3_MULTIMODE_PLAN.md` 933 행) |
| F13 | Matrox 는 같은 설계(고정 창, 순수 산술 `d_mmap`, open 은 창이 열렸을 때만, close 는 세기만, 등록은 init 말미, 실패하면 장치 없이 계속, **언로드 금지**)로 실기 PASS 했다 | `openstep-matrox-remade` `OpenStepMGAReplacementDisplay.m` `osmgaDevOpen`/`osmgaDevClose`/`osmgaDevMmap`/등록 블록, `docs/S4A_VRAM_MMAP_PLAN.md` 9 절 |

### 1-1. 정정 (R4 문서의 표현)

"uncached 별칭" 은 **PTE 로 uncached 가 아니다**(F5·F6).  R4a/R4b 의 판정은 여전히 유효하다(이 구간에서 별칭 읽기가 엔진 쓰기를 봤다는 실측).
다만 "별칭이 uncached 라서" 가 아니라 "이 물리 구간의 실효 형식이 캐시하지 않아서" 다.  `osrdn_engine.h`·`R4_ENGINE_PLAN.md` 의
표현은 이 빌드에서 "별칭(PTE 는 유저 매핑과 같음, R4C 1 절 F6)" 로 고친다.

## 2. 창 (python, 128 MiB 가정, page 8192, BAR0 `e0000000`)

- 시작 `winStart` = `osrdn_window_start(w, h, bpp, page_size)`(R4 11 절, 이미 있음), 끝 `ceiling` = `osrdn_window_ceiling(128 MiB)` = `0x07c00000`.
- `d_mmap` 오프셋 = **카드 주소**(Matrox 와 같음): 유저는 `mmap(…, off = winStart + k)` 로 청한다.
- 20 모드 전부: 시작·끝 페이지 정렬, 첫 PFN `0x7003a`–`0x70472`, 끝 PFN `0x73dff` 로 `0x7FFFFFFF` 아래, `bar0 + ceiling` 은 32 비트 안.
- 이 부팅의 모드(800×600 RGB:888/32): 시작 `0x0029e000`(2 744 320), 15 537 페이지.

**엔진 시험 블록과 겹침 — 결정**: R4a/R4b 의 시험 블록 `[winStart, winStart + 256 KiB)` 는 **창의 첫 32 페이지**다.  `docs/R4_ENGINE_PLAN.md` 11-3 의 2 는
"창이 한 번도 열리지 않았을 때만 엔진 시험 허용" 이었으나, 이 계획은 그것을 **바꾼다**: 두 키가 모두 켜진 부팅은 시험 부팅이고, 유일한 클라이언트는
시험 도구이며, 엔진 시험 연산이 창의 첫 256 KiB 를 덮어쓴다는 것을 문서·키 설명에 적는다.  이유: 5 절의 캐시 일관성 시험은 **유저가 매핑한 바로 그 페이지에
엔진이 쓰는** 것을 봐야 한다 — 그 자리가 이미 판정 장치(표지·가드·미끼·전수 대조)를 갖춘 시험 블록이므로, 유저가 겨누는 새 엔진 연산(목적지 검사가
필요한 새 공격면, R4 9-1 E9)을 만들지 않는다.  엔진 키는 기본 꺼짐이고 Mesa 단계(R6/M)에서 할당자와 함께 다시 연다.

## 3. 드라이버 변경

### 3-1. 새 단위 `osrdn_vmap.h/.m` (순수 C89, 호출 0, 호스트 컴파일)

```c
typedef struct {
    int           fixed;      /* 1 once osrdn_vmap_fix succeeded; never cleared */
    unsigned long start, end; /* card addresses, [start, end) */
    unsigned long bar0;
    unsigned long page, shift;
} osrdn_vmap;

/* write-once: refuses (returns a reason code) if already fixed, if page is not a
   power of two, if start/end/bar0 are not page aligned, if start >= end or
   end - start < page, if bar0 + end wraps 32 bits, or if the last PFN exceeds
   0x7FFFFFFF.  0 on success. */
int osrdn_vmap_fix(osrdn_vmap *v, unsigned long start, unsigned long end,
                   unsigned long bar0, unsigned long page);

/* d_mmap's decision.  -1 unless: fixed, minor(dev) == 0, offset >= 0,
   prot == (PROT_READ|PROT_WRITE) exactly, start <= off <= end - page (no sum
   formed), bar0 + off does not wrap, phys page aligned, PFN <= 0x7FFFFFFF.
   Reads only *v; no call, no store. */
int osrdn_vmap_pfn(const osrdn_vmap *v, int dev, int offset, int prot);

/* the boot self-test: every page from 0 to end + 2 pages, each asked twice,
   plus the fixed list in 3-3; returns the number of wrong answers */
unsigned long osrdn_vmap_selftest(const osrdn_vmap *v, unsigned long *cases);
```

- `shift` 는 `page` 에서 계산(루프)해 `1 << shift == page` 를 확인 — `_page_shift` 를 새로 들이지 않는다.
- 상태는 **단위 안의 한 전역**(`osrdn_vmap_fixed` 등 이름 하나)이고, `osrdn_vmap_fix` 만 쓴다 — 쓰기 한 번(`fixed` 가 1 이면 거절).
  `d_mmap` 은 이 전역만 읽는다.  **판정에 쓰는 값은 등록 전에 고정되고 부팅 동안 바뀌지 않는다**(F3).
- 모드 상태(`modeWritten`, 복귀 여부)는 **판정에 쓰지 않는다**: VGA 복귀 뒤에도 창 구간은 텍스트 모드가 쓰는 낮은 VRAM 위이고, 가변 상태를
  쓰면 F3 의 경로(`0xFFFFE000` 물리)가 열린다.

### 3-2. `OSRDNDisplay.m`

1. 키 `OSRDN_VMAP_KEY "RDN VRAM Mmap"` 을 init 에서 한 번 읽는다(엔진 키와 같은 방식).
2. 창 `start`·`ceiling` 을 init 에서 **한 번** 계산해 엔진 별칭과 vmap 이 **같은 값**을 쓴다(`engineAliasFor:` 는 계산하지 않고 받는다).
3. init 의 **마지막**(엔진 별칭 뒤, `RDN-R3 select` 줄 뒤, `return self` 바로 앞 — 그 뒤에 실패 반환이 없다)에 `-registerVmap`:
   게이트(하나라도 아니면 등록하지 않고 사유를 로그, 디스플레이는 그대로):
   `key` → `recordEnabled`(이 드라이버가 모드를 설정하는 부팅만) → `mmioMapped` → 창 계산 성공 →
   `osrdn_fb_reach_ok(&rdnState, ceiling)`(브리지) → **`CONFIG_MEMSIZE`·`CONFIG_APER_SIZE` ≥ ceiling**(읽기 둘, 새 함수
   `osrdn_engine_vram_reach(base)` 를 엔진 단위에 — 엔진 게이트가 이미 읽는 두 레지스터, 엔진 게이트도 이 함수를 쓰게 고친다) →
   `osrdn_vmap_fix` → **자체 시험 `bad == 0`**(틀리면 등록하지 않는다 — 실제 `page_size`·bar0 로 답을 확인한 뒤에만 연다) →
   `addToCdevswFromDescription:` → 성공이면 `vmapRegistered = 1`(`d_open` 이 보는 값; 등록 뒤에만 1).
4. 로그 한 줄: `RDN-R4 vmap boot= start= end= page= shift= bar0= pfn0= pfnN= mem= aper= self=<cases>/<bad> major=<n> ok|<why>`.
5. `d_open(dev, flag, devtype)`: `minor != 0` 또는 `!vmapRegistered` → `ENXIO`; 성공 수를 세고 한 줄 로그(시스템콜 문맥, Matrox 와 같음).
   `d_close`: 세고 한 줄 로그, 0.  나머지 슬롯(read·write·ioctl·stop·reset·select·getc·putc)은 `ENODEV` 를 돌려주는 함수(Matrox 와 같음).
6. `d_mmap(dev, offset, prot)`: `return osrdn_vmap_pfn(&…, dev, offset, prot);` **한 줄뿐**(검사가 강제).
7. 조회 매개변수 `getIntValues "RDNR4Vmap"` 낱말 7: `{magic 0x52344D30 ("R4M0"), 상태(0 꺼짐/1 등록/2 거절), start, end, page, major, engineWinStart}`.
   도구는 `start == engineWinStart` 를 확인한다(키가 둘 다 켜졌을 때).
8. **언로드·해제 없음**: 디스플레이 드라이버는 부팅 적재이고, 매핑은 close·등록 해제보다 오래 산다(Matrox S4A 7-2).  `-free` 는 등록 전의
   init 실패에서만 불리므로 등록을 되돌릴 일이 없다 — 등록이 init 의 마지막이라는 것이 그 전제이며 검사가 텍스트로 붙든다.

### 3-3. 자체 시험 목록 (커널, 등록 전, 순수 함수 호출만)

각 오프셋을 **두 번** 불러 같은 답인지(F3) + 기대 허용/거절:
창 첫 페이지 ✓, 첫+1 페이지 ✓, 끝 페이지(`end − page`) ✓, `end` ✗, `end + page` ✗, `start − page` ✗, `start + 4` ✗(비정렬), 0 ✗,
`0x7FFFE000` ✗, 음수(`0x80000000`) ✗, minor 1 ✗, `PROT_READ` ✗, `PROT_READ|PROT_WRITE|PROT_EXEC` ✗, `prot 0` ✗.
그리고 **전 페이지 걷기**: `off = 0, page, …, end + 2·page` 마다 허용 ⇔ `start ≤ off < end`, 허용이면 PFN = `(bar0 + off) >> shift`.
(약 16 000 페이지 × 2 호출, 순수 산술 — init 에서 한 번.)

### 3-4. 엔진 단위 변경 (`osrdn_engine.h/.m`) — 유저→엔진 방향 시험용 연산 하나

`ENG_OP_UBLIT 4`, 인자 = 씨앗 `seed`(하위 16 비트 0, 최상위 바이트 `0x5a`·`0xff` 거절 — 표지·패턴과 겹치지 않게):
블릿 경우 0(S1 (32,32,64×64) → S2 (8,0))과 같지만 **원본이 유저가 쓴 값** `U(seed, off) = seed | (off / 4)`(블록 안 `off/4 < 65 536`).

- 준비: S1 **밖**만 표지를 쓰고, 블록 **전체**를 되읽는다 — S1 밖은 표지, S1 은 `U` 여야 한다.  S1 불일치가 있으면 **엔진을 돌리지 않고**
  거절 `ENG_WHY_USER`(값 = 불일치 수, `first` = 첫 오프셋) — "유저의 쓰기가 VRAM 에 닿지 않았다" 는 증거.  되읽기는 기존처럼 울타리.
- 판정: 목적지 사각형 = 대응하는 S1 의 `U`, 그 밖 = 준비 값(S1 은 `U`, 나머지 표지).
- `preValue(op, arg, off)` 로 일반화(UBLIT 이고 S1 안이면 `U`); `destValue`·`destStart`·쓰기 수(`E_BLIT_WRITES`)는 경우 0 그대로.
- `FILL`·`BLIT`·`RECORD` 의 동작은 **바뀌지 않는다**(시뮬레이터 기준선이 그대로 PASS 해야 한다).

### 3-5. 번들 표

`Default.table`·`Instance0.table` 에 `"RDN VRAM Mmap" = "Yes";`(시험 빌드).  `"Character Major"` 키는 **두지 않는다**(자동 할당, F9).

## 4. 유저 도구 `tools/r4/rdnr4map.m`

`cc -O -Wall -o rdnr4map rdnr4map.m -lDriver`(실기 빌드 스크립트에 한 줄).  사용: `rdnr4map <runid> <build hex8>`.  모든 줄은 `RDNR4M ` 로 시작,
`setbuf(stdout, 0)`.  단계마다 실패하면 고유 종료 코드.

1. `Display0` 조회 → `RDNR2b0State` 로 빌드 확인 → `RDNR4Vmap` 조회(상태 1, `start`·`end`·`page`, `major`) → `IOCharacterMajor` 와 major 가 같은지.
2. `/dev/rdnvram0` 을 지우고 `mknod(S_IFCHR | 0600, major << 8 | 0)`, `/dev/rdnvram1`(minor 1) 도 — `open` 이 `ENXIO` 여야.
3. `open("/dev/rdnvram0", O_RDWR)`.  매핑 헬퍼는 Matrox 와 같다: `vm_allocate` → `mmap(addr, len, PROT_READ|PROT_WRITE, MAP_SHARED, fd, off)` → 반환 `-1` 이면 실패, 아니면 **자기가 잡은 주소** 사용(F2).
   **한 매핑은 32 페이지 이하**(F4, 도구 상수 — 검사가 강제).  `munmap` 이 없으므로 매핑은 종료까지 남는다(총 36 페이지).
4. **경계**(각각 새 매핑): `start` 1 페이지 ✓ · `end − page` 1 페이지 ✓ · `end − page` 2 페이지 ✗(검증 루프가 둘째 페이지에서 거절) · `end` ✗ ·
   `start − page` ✗ · 0 ✗ · `start + 4` ✗ · `PROT_READ` 만 ✗ · `PROT_READ|PROT_WRITE|PROT_EXEC` ✗ · `off = 0x80000000`(음수) ✗.  허용된 두 매핑은 한 워드 읽기만.
5. **블록 매핑** `[start, start + 256 KiB)` 32 페이지.
6. **자체 왕복**: 블록 전체에 `U(seedA)` 쓰기 → 전부 읽어 대조(`self bad`).  이 읽기가 캐시를 데운다.
7. **UBLIT seedA**(엔진 키 필요): 커널이 S1 의 `U` 를 별칭으로 확인하고(유저 → VRAM), 엔진이 S1 → S2 복사(VRAM → 엔진), 커널 판정.
   그다음 도구가 블록 전체를 읽는다: S1 = `U`, S2 사각형 = 복사, 나머지 = 표지.  불일치를 `stale`(= 그 자리의 옛 `U(seedA)`)과 `other` 로 나눠 센다.
   → 커널 별칭 쓰기(표지)와 엔진 쓰기(복사)가 **캐시를 데운 유저 매핑**에 보이는가.
8. **FILL**: 블록에 `U(seedB)` 쓰기 → 전부 읽기(데우기) → `FILL colour`(`0x96000000 | runid 하위 24 비트`, 표지와 다름) →
   도구가 읽기: S0 (16,8,200×40) = 색, 나머지 = 표지; `stale`/`other`.
9. **에일리어싱**(7·8 이 `stale = 0`·`other = 0` 일 때만 판정, 아니면 `UNDECIDED` — 캐시된 매핑의 되읽기는 VRAM 을 증명하지 않는다):
   `hi = end − page`, `lo = hi − 64 MiB`(20 모드 모두 블록보다 50 MiB 이상 위, python) 두 페이지를 매핑 → 두 페이지 **원래 내용 저장** →
   `lo` 에 `L(i)`, `hi` 에 `H(i)`(서로 다른 위치 인코딩) 쓰기 → `lo` 다시 읽어 `L` 그대로, `hi` 읽어 `H` → **원래 내용 복원 후 되읽어 확인**.
   `hi` 는 CPU 가 처음 닿는 124 MiB 근처이므로 **맨 마지막 단계**(앞의 증거가 이미 출력된 뒤).
10. 끝: `RDNR4M exit=0` 과 요약 줄.

도구의 상수(S0/S1/S2 배치, 채우기 사각형, 경우 0, 표지)는 드라이버 헤더와 **같아야** 하며 호스트 검사가 두 소스에서 숫자를 뽑아 대조한다(도구는 실기에서
빌드되므로 헤더를 공유하지 않는다 — `check_tool_mode.py` 선례).  이를 위해 `E_MARK`·`E_FILL_*` 을 `osrdn_engine.h` 로 옮겨 `ENG_MARK`·`ENG_FILL_*` 로 공개한다.

## 5. 게이트 (R4c PASS = 전부)

| # | 항목 | 기대 |
|---|---|---|
| G1 | 등록 줄 | `ok`, `self=<n>/0`, `pfn0 = (bar0+start)>>13`, `pfnN = (bar0+end−page)>>13`(호스트가 python 으로 재계산), major 가 도구의 `IOCharacterMajor` 와 같음 |
| G2 | 경계 10 건 | 4 절 4 의 기대 그대로, minor 1 `open` = `ENXIO` |
| G3 | 자체 왕복 | `self bad = 0` |
| G4 | UBLIT | 커널 `rc=0`, `in/out/decoy/guard = 0`; 도구 `stale = 0`, `other = 0` |
| G5 | FILL(데운 뒤) | 커널 `rc=0`, 불일치 0; 도구 `stale = 0`, `other = 0` |
| G6 | 에일리어싱 | `hi` = `H`, `lo` = `L`(64 MiB 에일리어싱 없음), 두 페이지 복원 확인 |
| G7 | 뒤처리 | 같은 부팅에서 `RDNR2bCycle` verdict 0, `open`/`close` 줄 수가 도구 호출과 맞음, telnet 생존, 화면 정상 |

**G4·G5 에서 `stale > 0` 이면** 유저 매핑이 캐시된다는 뜻이다 — 그 자리에서 멈추고(에일리어싱은 `UNDECIDED`), 결과를 기록한 뒤 operator 와 다음을
정한다(유저 매핑은 CPU 읽기에 못 쓴다; 해결책은 MTRR 을 읽는 것부터이며 이 빌드 범위 밖).  위험: WB 로 캐시된 유저 쓰기가 나중에 VRAM 으로 되써질 수 있으나
대상은 창 안(보이지 않는 곳)뿐이다.

## 6. 호스트 검사 (기준 PASS 와 변이 FAIL 을 같은 실행에서)

1. `tools/r4/check_vmap.py` — `osrdn_vmap.m` 을 32 비트로 컴파일해 **독립 python 오라클**과 대조: 20 모드 × 전 페이지 걷기 + 경계 목록 +
   무작위 입력(고정 씨앗) + 이상 입력(비정렬 bar0, page 3000, `start ≥ end`, `bar0 + end` 넘침, PFN > 0x7FFFFFFF), `fix` 두 번째 호출 거절.
   변이: 끝 비교 `>` ↔ `>=`, minor 검사 빼기, prot 을 `&` 로(부분 일치 허용), 음수 검사 빼기, 정렬 검사 빼기, 넘침 검사 빼기, shift 하나 틀리기,
   `fix` 재호출 허용, 자체 시험의 두 번 호출을 한 번으로.
2. `check_r4_src.py` 에 규칙 추가: `d_mmap` 함수 본문은 `osrdn_vmap_pfn` 호출 하나뿐; `osrdn_vmap.m` 은 함수 호출 0·IOLog 0·전역 쓰기는 `fix` 안만;
   등록 호출은 init 의 `return self` 바로 앞 블록에만, 그 뒤에 `return [self free]`/`return nil` 없음; `vmapRegistered = 1` 은 등록 성공 분기 안;
   `"Character Major"` 가 번들 표에 없음.  각각 변이.
3. `sim_r4.py`: UBLIT 기준선(가짜 엔진) + 변이 — 준비가 S1 을 덮음, S1 확인 빼기(유저 쓰기 없이도 PASS 가 되는지), UBLIT 판정이 패턴을 기대,
   씨앗 검사 빼기.  기존 24 변이는 그대로 잡혀야 한다.
4. `tools/r4/check_tool_r4map.py`: 도구 상수 = 드라이버 상수(두 소스에서 추출), 매핑 길이 상수 ≤ 32 페이지, 단계 순서(에일리어싱이 stale 시험 뒤,
   `hi` 접근이 맨 뒤), 경계 목록 10 건, `PROT_*`·`MAP_SHARED` 값 = 헤더(F10).  변이.
5. `tools/r4/check_vmap_log.py`: 커널 로그 + 도구 출력으로 G1–G7 판정, `--self-test`(합성 로그로 PASS 하나·FAIL 여럿).
6. `check_window.py` 는 그대로(창 식 불변).  `check_reloc_r2b0.py` 역어셈블 게이트: 새 코드 심볼 이름 중복 없음, `osrdn_vmap_*` 은 MMIO 접근자를
   부르지 않음, 엔진 레지스터 쓰기 호출자는 여전히 엔진 단위뿐.  `hostcheck.sh` UNITS 에 `osrdn_vmap.m`.  `nm -u` 에 새 미해결 심볼이 없어야
   (클래스 메서드는 메시지, `page_shift` 는 쓰지 않음) — 설치 전 확인.
7. `check_citations.py` 에 이 문서.

## 7. 실기 절차

1. check-all PASS → 묶기 → 실기 빌드(드라이버 + `rdnr2b0` + `rdnr4map`) → 역어셈블 게이트 → `nm -u` → 설치(`closed=yes fresh live`) → **operator 재부팅**.
2. 재부팅 뒤: `/ndrv` 마운트(실제 경로) → gcdsd → `tools/nx-logcatch.sh start` → `check_select` → `vmap` 줄 확인(G1).
3. `rdnr2b0 … state` → `rdnr4map <runid> <build>` **한 번**(대상 도구는 한 번에 하나) → 호스트 판정 → `rdnr2b0 … cycle` → 판정(G7).
4. **operator 가 볼 것**: 화면 변화 없음이 정상(모든 쓰기는 보이는 화면 밖).  화면에 무언가 나타나면 창 판정이 틀린 것 — 알려 주면 중단.
5. **하드 행 한 번이면 중단**, 오프라인 분류.  시험 중 로그아웃·창 서버 재시작 금지.

## 8. 위험

| 위험 | 완화 |
|---|---|
| `d_mmap` 이 잘못된 PFN 을 준다 → 임의 물리 메모리(커널 포함) 노출 | 순수 산술·불변 상태, 커널 안 자체 시험 통과 뒤에만 등록, 호스트 전수 대조·변이 |
| 두 번째 호출이 다른 답 → 물리 `0xFFFFE000`(F3) | 판정에 가변 상태 없음(모드 상태도 안 봄), 자체 시험이 두 번씩 부름 |
| 큰 매핑의 `kalloc` 실패 → 커널 패닉(F4, 실패 검사 없음) | 도구는 32 페이지 이하.  외부 클라이언트의 큰 매핑은 막지 못한다 — 노드 0600 root, 키 기본 꺼짐; 문서에 적고 R6/M 의 할당자에서 다시 연다 |
| 유저 매핑이 WB 로 캐시 | G4·G5 가 판정, 캐시면 멈춤(5 절) |
| 124 MiB 근처 첫 CPU 접근이 버스를 건다 | APER·MEMSIZE ≥ 124 MiB 게이트, 브리지 창 확인, 도구의 마지막 단계, 읽기 먼저 |
| 등록 뒤 init 실패로 `-free` → 슬롯이 해제된 객체를 가리킴 | 등록은 init 의 마지막(검사가 강제), 그 뒤 실패 반환 없음 |
| 엔진 시험이 유저 데이터를 덮음 | 두 키가 켜진 부팅은 시험 부팅(2 절 결정), 엔진 키 기본 꺼짐 |
| 다른 클라이언트와의 덮어쓰기, fork·close 뒤 남는 매핑 | 이 인터페이스로 강제 불가(Matrox 3-35) — 임대 없음(operator 결정), R6/M 에서 |

## 9. 교차검토에 물을 것

1. 3-1 의 `osrdn_vmap_pfn` 검사 목록에 빠진 것(특히 F1 의 `dev` 부호 확장, `offset` 이 `int` 인 것, `prot` 정확 일치).
2. 자체 시험 실패 시 등록하지 않는 것, 등록 게이트의 레지스터 읽기(init 에서 `CONFIG_MEMSIZE`·`APER_SIZE`)가 새 위험을 만드는가.
3. 2 절 결정(엔진 시험 블록 = 창의 첫 32 페이지, 11-3 의 2 를 뒤집음)이 옳은가.
4. UBLIT 설계(준비가 S1 을 건드리지 않고 되읽기로 유저 쓰기 도달을 판정)의 울타리·판정에 구멍이 있는가.
5. 4 절 시험 순서와 G4–G6 가 F5–F7 의 캐시 질문을 실제로 판정하는가(특히 WC 형식이면 무엇이 보이나).
6. F4(매핑당 `kalloc`) 를 더 막아야 하는가 — `d_mmap` 은 길이를 모른다.

## 10. 교차검토 판정 (2026-09-18 — codex 는 사용량 한도(2026-09-19 19:23 까지)로 실패, 내부 agent 2 건: A 커널 안전, B 시험·게이트.  전 건 원문·IDA·python 으로 재확인)

### 10-1. 내가 틀린 것

| # | 틀린 것 | 확인 |
|---|---|---|
| E1 | F1 이 불완전: `smmap` 은 **길이가 부호 있는 정수로 0 이하(≥ 2^31)면 검증 루프를 통째로 건너뛴다** → 검사 없는 채우기 호출만 남고, `-1` 은 물리 `0xFFFFE000` 이 되며 `kalloc` 12 582 928 B(길이 `0x80000000`, python)는 NULL 검사 없이 `bzero` | `_smmap` 0x106f8c–0x106f94(`xor ebx,ebx; cmp [edi+4],ebx; jle`), `_vm_object_special` 0x17c1c1–0x17c1ca(`call _kalloc; mov esi,eax; push ebx; push esi; call _bzero`) |
| E2 | G4/G5 가 "유저 매핑이 캐시되는가" 를 판정한다고 적었다 — F6(같은 PTE)와 x86 의 물리 태그 캐시 때문에 커널 별칭과 유저 매핑은 **같은 형식**이고, WB·WT·WP 는 이미 R4a/R4b 가 배제했다.  남는 UC·WC 는 되읽기로 **구별할 수 없다**.  또 WB 였다면 증상은 옛 `U`(stale)가 아니라 기대 자리의 **표지**였다 | F5·F6, `osrdn_engine.m` 379–384(준비 쓰기·되읽기), `R4_ENGINE_PLAN.md` 18 절 |
| E3 | UBLIT 준비의 별칭 S1 확인을 "유저 쓰기가 VRAM 에 닿음" 의 증거로 적었다 — 같은 이유로 CPU 쪽 시야일 뿐이다.  유저 → VRAM 의 증거는 **엔진이 S1 을 읽어 S2 에 쓴 결과**뿐 | 위와 같음(내 자체 점검에서도 같은 결론) |
| E4 | 4 절 4 의 "허용된 두 매핑은 한 워드 읽기" — `end − page` = `0x07bfe000` 은 곧 `hi` 여서, "124 MiB 근처는 맨 마지막" 순서를 깨뜨린다 | python: `0x7c00000 − 8192 = 0x7bfe000` |
| E5 | 3-4 "경우 0 그대로" 가 구현을 정하지 않았다 — `destValue`·`destStart`·`engDraw` 가 `engCases[arg]` 로 색인하므로 씨앗을 그대로 넘기면 배열 밖을 읽고 엉뚱한 배치를 쓴다 | `osrdn_engine.m` `destValue`(`c = &engCases[arg]`), `destStart`, `engDraw`(`engBlitBatch(e, base, &engCases[arg])`), `osrdn_engine_run` 의 인자 한계는 BLIT 에만 |
| E6 | "엔진 키 기본 꺼짐" — 코드는 키가 없으면 꺼짐이지만 **현재 번들 표는 둘 다 `Yes`** | `OSRDNDisplay/Default.table`·`Instance0.table` 19 행 |
| E7 | "20 모드" 창 — 기하는 **15 개**(8bpp 형식 둘이 하나를 공유) | `tools/r4/check_window.py` 146 행 |
| E8 | 위험 표의 "등록 뒤 `-free`" 는 도달할 수 없는 경로다 — 진짜 위험은 **슬롯이 찬 채 모듈이 내려가는 것**(텍스트가 사라지고 cdevsw 가 그리로 가리킴).  `Unload_Commands.sect` 주석은 "nothing to run at unload" | `Unload_Commands.sect`; init 의 등록 뒤 실패 반환 없음 |

### 10-2. 채택 (11 절 명세에 반영)

| 지적 | 판정 | 근거 |
|---|---|---|
| A1 길이 ≥ 2^31 우회 → 노드를 O_RDWR 로 열 수 있으면 패닉·`0xFFFFE000` 매핑 | ✅ 위험 표·F1 정정, **R6/M 의 차단 요건**(비 root 클라이언트 전에 open 신원 게이트) | E1 |
| A2 자동 major 에 옛 노드(Matrox 는 이 기계에서 major 1)가 있을 수 있다 | ✅ 도구가 `/dev` 의 같은 major 문자 노드를 전부 나열, 우리 둘 외에 있으면 실패 | `openstep-matrox-remade/docs/S4A_VRAM_MMAP_PLAN.md` 316 행 `character major = 1` |
| A3·B5 `engCases[arg]` | ✅ `engCaseFor(op, arg)`, 씨앗 검사는 `engGate` 앞, 변이 "UBLIT 이 씨앗으로 색인" | E5 |
| A4·B3 같은 씨앗 재사용이면 유저 쓰기 없이 PASS | ✅ 커널이 마지막 UBLIT 씨앗을 기억해 재사용 거절(`ENG_WHY_SEED`), 도구는 6 단계 전 S1 에 `U(seedA)` 가 이미 있으면 중단; 변이 | `osrdn_engine.m` 준비가 S1 을 쓰지 않는 설계(3-4) |
| A4·B 9-4 S1 확인의 뜻 | ✅ `ENG_WHY_USER` = "이 물리 페이지에서 유저 쓰기가 보이지 않음", 유저 → VRAM 은 S2 판정 | E3 |
| A5 언로드 위험 | ✅ 위험 행·`Unload_Commands.sect` 주석·등록 로그에 "언로드 금지"(Matrox 등록 로그와 같음) | E8 |
| A6 minor = `dev & 0xFF` 만, 전체 dev 비교·`dev >> 8` 금지 | ✅ 변이 "전체 dev 비교" | `_smmap` 0x106f96·0x107002, `_vm_object_special` 0x17c210 — 세 호출 모두 같은 16 비트 rdev 의 `movsx` |
| A8 자체 시험의 기대 PFN 이 같은 식 | ✅ 첫 PFN 은 나눗셈 `(bar0+start)/page`, 허용 PFN 은 +1 씩, 허용 수 = `(end−start)/page` — 로그 | 3-3 원문 |
| A9 전역에 명시 초기값 | ✅ | — |
| A10·E6 키 기본값 | ✅ 문구 "키가 없으면 꺼짐, 이 시험 번들은 켬" | E6 |
| A11·E7 | ✅ | E7 |
| B1·E2 G4/G5 의 뜻 | ✅ 11-4 로 재정의: F6 확인 + **유저 페이지가 맞는 카드 주소에 닿음** 확인; 칸은 `stale`(옛 U)·`mark`(기대 자리의 표지)·`other`; 판정표; WC/UC 는 **정보용** 쓰기·읽기 속도 한 줄(구별 불가를 적는다) | E2 |
| B2·E4 `hi` 선접근 | ✅ 4 단계는 `end − page` 를 매핑만(접근 없음), 도구 검사 "천장 − 64 MiB 이상 오프셋의 매핑 역참조는 9 단계에서만" | E4 |
| B4 블록 32 페이지 중 20 페이지가 위치 부호 없이 표지만 | ✅ UBLIT 준비가 **블록 전체**를 먼저 읽어 `U(seed, off)` 를 요구(6 단계가 전체에 `U` 를 쓴다), 불일치 수를 `ENG_WHY_USER` 로 — 그다음에만 S1 밖에 표지 | `osrdn_engine.h` 배치, `osrdn_engine.m` `preValue` 는 S1 밖이 균일 표지 |
| B6 로그 이름·판정기 | ✅ `engOpName` 에 `ublit`, `check_engine.py` 정규식·자체 시험 BAD 경우, `E_MARK`→`ENG_MARK` 이름 바꿈이 건드리는 `check_r4_src.py` 허용 목록·`sim_r4.py` 변이 닻 목록화 | `osrdn_modelog.m` `engOpName`(4 → `bad`), `check_engine.py` `(record|fill|blit|bad)` |
| B7 도구의 기대값·분류 코드가 호스트 검사 밖 | ✅ 도구의 `want(op, arg, off)`·분류를 순수 C 파일로 두고 호스트에서 드라이버 `preValue`/`destValue` 와 65 536 오프셋 전수 대조 + 변이(S2 피치, 원본 오프셋, stale 정의) — Matrox 10-3 의 검사기 산술 오류 선례 | `S4A_VRAM_MMAP_PLAN.md` 10-3 |
| B8 close 수의 기대값 없음 | ✅ open 수만 고정(성공 1 + ENXIO 1, 거절도 한 줄), close 는 관찰(0 또는 1, 시점) | `d_close` 는 마지막 close 에만 |
| B9 색·씨앗 충돌 | ✅ 씨앗 최상위 바이트는 A = `0xC3`, B = `0x3C` 고정(하위 8 비트 = runid 하위 바이트, 하위 16 비트 0), 색 최상위 `0x96`; 커널은 `0x5a`·`0xff`·`0x96` 거절 | python: 충돌은 씨앗 최상위 바이트가 `0x96` 일 때뿐, 고른 바이트와 교집합 없음 |
| B10 경계 | ✅ errno 기록(기대 EINVAL), 길이 0 은 목록에 넣지 않음, **뜻밖에 성공한 매핑은 건드리지 않고 즉시 고유 코드로 종료** | F1 |
| B11 WC 비움 | ✅ 쓰기 루프 뒤 잠긴 `xchg` 하나(명시적 직렬화) | — |
| B12 검사 공백 | ✅ check-all 에 새 검사 전부, 드리프트 검사에 매개변수 이름·매직·op 번호·낱말 배치·G2 기대표(**이 문서에서** 읽음), G1 의 bar0 를 R1 의 `e0000000` 과 대조 | `check_window.py` 의 문서 읽기 선례 |
| B13 G6 순서 | ✅ `lo` 쓰기 → `hi` 쓰기 → `lo` 읽기 → `hi` 읽기(검사가 강제) | — |
| B14 절차 | ✅ 종료 때 두 노드 unlink, 경로가 문자 장치가 아니면 거절, major 0·두 출처 불일치 거절, `IO_R_BUSY` 고유 종료 코드, `RDNR2bCycle` 전 도구 종료 확인, 재실행은 새 runid | — |

### 10-3. 기각·부분

| 지적 | 판정 | 반증 |
|---|---|---|
| A7 "`CONFIG_MEMSIZE` 는 비트 0x1F000000 만 크기" → 마스크 | ⚖️ 마스크는 **기각**: 우리 참고 xf86 6.14.6 은 원값을 그대로 쓴다(`radeon_driver.c:1441` `mem_size = INREG(RADEON_CONFIG_MEMSIZE)`), 미러에 마스크 정의 없음(grep).  받는 것: 원값을 로그하고 호스트 판정이 R1 실측 128 MiB(`docs/R1_RESULT.md` 35 행)와 **정확히 같은지** 본다; `APER_SIZE` 가 BAR 크기를 대신한다고 적는다 | grep 결과 |

## 11. 개정 명세 (10 절 반영 — 3·4·5·6·8 절과 충돌하면 이 절이 이긴다)

### 11-1. `osrdn_vmap`
- 3-1 그대로 + minor 는 `(dev & 0xFF) == 0` **만**(전체 dev·`dev >> 8` 금지), 전역은 명시 초기값 `= { 0 }`.
- 자체 시험(3-3)의 기대는 독립 유도: 첫 허용 PFN = `(bar0 + start) / page`(나눗셈), 이후 허용 PFN 은 정확히 +1, 허용 수 = `(end − start) / page`,
  두 번 호출 일치.  로그에 허용 수.

### 11-2. 엔진 단위
- `ENG_OP_UBLIT 4`, `ENG_WHY_USER 16`, `ENG_WHY_SEED 17`.  씨앗 검사는 `osrdn_engine_run` 의 op 검사 자리(게이트 전): 하위 16 비트 0, 최상위 바이트가
  `0x5a`·`0xff`·`0x96` 아님, **직전 UBLIT 씨앗과 다름**(`lastSeed` 는 연산이 실행(`RAN`)되었거나 `USER` 로 거절됐을 때 갱신).
- `engCaseFor(op, arg)`: BLIT → `&engCases[arg]`, UBLIT → `&engCases[0]`; `destValue`·`destStart`·`engDraw` 는 이것만 쓴다(검사: `engCases[` 첨자는
  `engCaseFor` 안에서만).
- `preValue(op, arg, off)`: BLIT 은 지금 그대로(S1 패턴), UBLIT 은 S1 안 `U(arg, off)`, 나머지 표지.  **FILL·BLIT 의 동작은 바이트 단위로 불변**
  (시뮬레이터 기준선·기존 24 변이가 그대로).
- UBLIT 준비: ① 블록 **전체**를 별칭으로 읽어 `U(arg, off)` 와 대조 — 불일치 수가 0 이 아니면 쓰기 없이 `ENG_WHY_USER`(값 = 불일치 수, `first`).
  ② S1 밖에 표지 쓰기, ③ 블록 전체 되읽기(울타리; S1 = `U`, 밖 = 표지).  ④ 이후 BLIT 과 같은 경로(경우 0).
- `osrdn_engine_vram_reach(base, &mem, &aper)`: 두 레지스터 원값 읽기(쓰기 없음), 엔진 게이트도 이것을 쓴다.
- `engOpName` 에 `ublit`.  `E_MARK`·`E_FILL_*` → 헤더의 `ENG_MARK`·`ENG_FILL_*`(이 이름 바꿈이 건드리는 `check_r4_src.py` 허용 목록·`sim_r4.py` 닻을 함께).
- 주석 정정: "uncached alias" → "alias (same PTE as a user mapping: R4C_VMAP_PLAN F6)".

### 11-3. `OSRDNDisplay.m`·번들
- 3-2 그대로 + 등록 게이트의 레지스터 원값을 로그(`mem=`·`aper=`), 등록 로그 끝에 "must NOT be unloaded".
- `Unload_Commands.sect` 주석: 이 드라이버는 문자 디바이스 슬롯을 채우므로 **내리면 안 된다**.
- 번들 표: `"RDN VRAM Mmap" = "Yes"`(시험 번들).  문구는 "키가 없으면 꺼짐, 이 시험 번들은 두 키 모두 켬".

### 11-4. 도구 `rdnr4map` (4 절 대체)
1. 조회: `Display0` → `RDNR2b0State`(빌드) → `RDNR4Vmap`(상태 1) → `IOCharacterMajor`; major 0·두 출처 불일치면 거절.
2. `/dev` 의 문자 노드 중 major 가 같은 것을 **전부 나열**(`stat`); `rdnvram0`/`rdnvram1` 밖에 있으면 종료(고유 코드).  경로가 있는데 문자 장치가 아니면 거절.
   `mknod` 0600 두 개, minor 1 `open` → `ENXIO` 기대.
3. `open(O_RDWR)`.  매핑 헬퍼는 32 페이지 이하, `mmap` 실패는 errno 와 함께.  **뜻밖에 성공한 매핑은 건드리지 않고 즉시 고유 코드로 종료.**
4. 경계 10 건(4 절 목록) — **허용된 매핑은 역참조하지 않는다**(`end − page` 는 `hi`).  길이 0 은 넣지 않는다.
5. 블록 매핑(32 페이지).  **신선도**: S1 에 이미 `U(seedA)` 가 있으면 종료(재실행은 새 runid).
6. 블록 전체에 `U(seedA)` → 잠긴 `xchg` → 전부 읽어 자체 대조.  쓰기·읽기 소요를 정보용으로(WC/UC 는 되읽기로 구별 불가, 속도는 참고일 뿐).
7. UBLIT seedA → 커널 판정(준비가 블록 전체 `U` 확인 = **유저 페이지 32 개가 맞는 카드 페이지에 닿음**, S2 = **유저 → VRAM → 엔진**).
   도구가 블록 전체를 읽어 세 칸: `stale`(그 자리의 옛 `U`), `mark`(엔진 결과 자리의 표지), `other`.
8. `U(seedB)` → `xchg` → 전부 읽기 → FILL 색 → 도구 읽기, 같은 세 칸.
9. 에일리어싱(7·8 이 세 칸 모두 0 일 때만, 아니면 `UNDECIDED`): `hi`·`lo` 매핑 → 원래 내용 저장 → `lo` 쓰기 → `hi` 쓰기 → `lo` 읽기 → `hi` 읽기
   → 복원 → 되읽어 확인.  **`ceiling − 64 MiB` 이상 오프셋의 역참조는 이 단계에서만**(검사가 강제).
10. 두 노드 unlink, 요약, `exit=0`.  `IO_R_BUSY`(모드 클레임)는 고유 종료 코드(실패 아님).
- 씨앗: A = `0xC3000000 | (runid & 0xff) << 16`, B = `0x3C000000 | (runid & 0xff) << 16`, 색 = `0x96000000 | (runid & 0xffffff)`.
- 기대값·분류 코드는 **순수 C 파일**(`tools/r4/r4map_want.c`)로 두고 도구가 `#include` 한다 — 호스트가 같은 파일을 드라이버의 `preValue`/`destValue` 와
  65 536 오프셋 전수 대조.

### 11-5. 게이트 (5 절 대체)

| # | 기대 |
|---|---|
| G1 | 등록 `ok`, 자체 시험 bad 0·허용 수 = `(end−start)/page`, bar0 = R1 의 `e0000000`, `mem`·`aper` 원값 = `0x08000000`(R1), pfn0·pfnN 을 호스트가 python 으로 재계산, major 일치, `/dev` 에 같은 major 의 다른 노드 없음 |
| G2 | 경계 10 건(기대표는 **이 문서의 4 절**에서 읽는다) + minor 1 ENXIO, 허용 매핑 역참조 0 회 |
| G3 | 자체 왕복 0 |
| G4 | UBLIT 커널 `rc=0`, 준비 불일치 0, `in/out/decoy/guard = 0`; 도구 `stale = mark = other = 0` |
| G5 | FILL 커널 불일치 0; 도구 세 칸 0 |
| G6 | `lo` = `L`, `hi` = `H`, 복원 확인 |
| G7 | 도구 종료 확인 뒤 `RDNR2bCycle` verdict 0; open 줄 = 성공 1 + ENXIO 1(close 는 관찰만); telnet·화면 정상 |

판정 해석: 커널 판정 깨끗 + `stale > 0` → F6 이 틀림(두 매핑의 형식이 다름) — 멈춤.  `mark > 0` → 두 매핑 모두 캐시(R4 결과와 모순) — 멈춤.  `other > 0` → 주소 오류 — 멈춤.
**이 시험이 판정하지 못하는 것**: UC 와 WC 의 구별(되읽기로 불가, MTRR 을 읽어야 함 — 범위 밖).

### 11-6. 위험 (8 절에 더함)

| 위험 | 완화 |
|---|---|
| 길이 ≥ 2^31 인 `mmap` 은 `d_mmap` 검증을 건너뛰어 `0xFFFFE000` 매핑·12 MB `kalloc` 실패 시 패닉(E1) | `d_mmap` 으로는 막을 수 없다 — 노드 0600 root, 키 없으면 꺼짐, 도구는 32 페이지; **R6/M 의 차단 요건**: 비 root 클라이언트 전에 open 신원 게이트 |
| 슬롯이 찬 채 모듈이 내려감(E8) | 언로드 금지(주석·로그), 디스플레이는 부팅 적재 |
| 옛 노드가 같은 major 를 가리킴 | 도구의 `/dev` 나열·거절, 종료 때 unlink |

### 11-7. 호스트 검사 (6 절에 더함)
`check_vmap.py` 변이에 "전체 dev 비교"; `check_tool_r4map.py` 에 매개변수 이름·매직(`0x52344D30`)·op 번호·낱말 배치·씨앗/색 바이트, 경계 기대표를 이 문서에서
읽어 대조, "`hi` 이전 역참조 없음"; `sim_r4.py` 변이 "UBLIT 이 씨앗으로 색인", "씨앗 재사용 허용", "준비가 블록 전체를 확인하지 않음"; `check_engine.py`
`ublit` 과 자체 시험; `r4map_want.c` 전수 대조와 변이(S2 피치·원본 오프셋·stale 정의); 모두 `tools/check-all.sh` 에.

## 12. 구현 기록 (호스트, 2026-09-18)

### 12-1. 만든 것
- `osrdn_vmap.h/.m`: `osrdn_vmap_fix`(한 번 쓰기, 사유 코드 7 종), `osrdn_vmap_pfn`(호출 0), `osrdn_vmap_selftest`(고정 목록 18 건 + 0 부터 끝+2 페이지까지 걷기,
  각 두 번, 기대 PFN 은 나눗셈과 셈으로).  전역 `osrdn_vmap_window` 명시 초기값.
- `OSRDNDisplay.m`: 키 `"RDN VRAM Mmap"`, 창은 init 에서 한 번(엔진 별칭과 같은 두 수), init 의 마지막 `-registerVmap:start:ceiling:`(게이트 순서는
  11-3 그대로, 거절이면 사유 한 줄), `rdnDevOpen`/`rdnDevClose`(한 줄씩, 성공·거절·close 셈), `rdnDevMmap`(한 줄), 나머지 슬롯 `ENODEV`,
  `getIntValues "RDNR4Vmap"`(7 낱말), `mman.h` 의 `PROT_READ|PROT_WRITE` 와 단위의 상수를 컴파일 때 대조.
- 엔진: `ENG_OP_UBLIT`, `engCaseFor`, `preValue(op, arg, off)`, 준비의 블록 전체 사전 확인, `engSeedOk`, `lastSeed`(준비 **전에** 기록 — 10-2 의
  "RAN 또는 USER 일 때" 보다 넓다: 준비가 시작되면 S1 에 그 씨앗의 낱말이 있을 수 있으므로), `osrdn_engine_vram_reach`(게이트도 이것을 쓴다),
  `ENG_MARK`·`ENG_FILL_*`·`ENG_USER_VALUE`·씨앗 규칙은 헤더로.  `.m` 안의 `E_MARK`·`E_FILL_*` 는 헤더 값을 가리키는 별명으로 남겨
  기존 시뮬레이터 변이 닻을 그대로 쓴다.
- 도구 `tools/r4/rdnr4map.m` + 순수 C `r4map_want.c`(기대값·분류; 시뮬레이터가 같은 파일을 컴파일해 VRAM 과 전수 대조).
- 번들 표 두 곳에 키, `Unload_Commands.sect` 주석, 실기 빌드 스크립트 7·8 단계(두 번째 도구, `rdnr4map.sum`), 묶음에 두 파일.

### 12-2. 검사 (기준 PASS 와 변이 FAIL 을 같은 실행에서)

| 검사 | 기준 | 변이 |
|---|---|---|
| `check_vmap.py` | 창 28 개(15 기하 + 이상·raw 13), 답 258 718 개 = python 오라클, 자체 시험 15 창 모두 0 | 17 개 모두 잡힘(자체 시험도 8 개를 잡음, "2 의 거듭제곱 아님" 은 shift 루프가 끝나지 않아 멈춤으로 잡힘) |
| `check_r4c_src.py` | 규칙 11 | 22 |
| `sim_r4.py` | 가짜 세계 22 검사(UBLIT·씨앗 재사용·쓰기 없음·한 페이지 빠짐·나쁜 씨앗 4, 도구 기대값 = VRAM) | 29(새 5: 씨앗으로 색인 → 신호 11, 재사용, 블록 전체 확인 빠짐, 씨앗 검사 빠짐, S1 패턴 기대) |
| `check_r4_src.py` | 기존 규칙, 울타리 규칙 정밀화 | "울타리를 쓰기 루프 앞으로" 변이 추가 |
| `check_tool_r4map.py` | 규칙 5 + 가짜 세계에서 `r4map_want.c` 전수 | 20 + 6 |
| `check_vmap_log.py --self-test` | 합성 로그 PASS, 드라이버의 실제 IOLog 형식을 읽음 | 23 |
| `check_engine.py --self-test` | `ublit` 줄 | +2 |
| `hostcheck` | 새 단위·도구 엄격 C89, 커널 심볼 13 개(변화 없음) | — |
| `check_target_r2b0.py` | 도구 빌드 실패 분기 추가 | — |

### 12-3. 구현 중 잡은 것
- 시뮬레이터 모형: 연산 뒤 `DEFAULT_OFFSET` 복원 쓰기 한 칸이 FIFO 에 남아 다음 연산의 게이트가 FIFO 63 을 봤다 — 기존 시험은 연산마다 `boot()` 해서 숨었다.
  두 연산을 잇는 시험에서만 `settle()`(호출 사이에 시간이 흐름)을 명시(실기 R4 는 14 연산 연속 게이트 통과).
- 울타리 규칙이 UBLIT 의 사전 확인 루프를 울타리로 오인할 수 있었다 → "쓰기 루프 **뒤의** `preValue` 대조 되읽기" 로 정밀화, 변이 둘.
- `check_r4c_src` 의 한 번 쓰기 규칙: `fixed` 가 두 번 저장돼도 "마지막이 `fixed`" 로 통과, 캐스트한 포인터 저장을 못 봄 → 둘 다 정밀화.
- `check_vmap`: 음수 오프셋 검사와 "고정 안 된 창" 은 기존 입력으로 도달 불가였다(같은 답) → 끝이 2^31 을 넘는 raw 창·값만 있고 `fixed=0` 인 raw 창 추가.
- 도구: `S_ISCHR` 는 이 헤더에서 POSIX 전용(호스트 엄격 컴파일이 잡음), 변수 `major` 를 매크로와 구분해 `cmajor` 로.

## 13. 실기 전 코드 검토 판정 (2026-09-18, 내부 agent 1 건 — codex 한도.  전 건 원문 확인)

블로커 없음.  검토자가 호스트 검사 다섯 개를 다시 돌려 PASS 를 확인했다(참고일 뿐, 판정은 아래 확인으로).

| # | 지적 | 판정 | 확인 |
|---|---|---|---|
| 1 | 자동 major 에 이미 있는 노드가 느슨한 권한이면, 도구가 돌기 전까지 비 root 가 열 수 있다(→ E1 경로) | ✅ **부팅 전** `/dev` 문자 노드 전부를 권한·major 와 함께 기록(실기 절차 1 에 추가, 읽기만).  `d_open` 의 신원 검사는 R6/M 차단 요건 그대로(11-6) | `OSRDNDisplay.m` `rdnDevOpen` 은 minor·상태만 본다 |
| 2 | 씨앗은 runid 하위 바이트만 → 같은 부팅의 256 차이 재실행이 `SEED` 로 거절되어 "실패" 로 보인다 | ✅ 도구가 UBLIT 거절 때 안내 한 줄 | `rdnr4map.m` 씨앗 식, `osrdn_engine_run` 의 재사용 거절 |
| 3 | `USER` 거절의 `first` 가 로그에 안 나간다(11-2 는 요구) | ✅ `RDN-R4 user bad= first=` 한 줄 | `osrdn_modelog.m` `osrdn_engine_line`: 거절이면 첫 줄 뒤 반환 |
| 4 | 엔진 별칭이 없을 때 종료 코드 5 가 원인을 가린다 | ✅ 고유 메시지·종료 21 | `rdnr4map.m` vmap 단계 |
| 5 | 시그널로 죽으면 노드가 남는다 | ✅ 실기 절차에 실행 뒤 `rm -f /dev/rdnvram0 /dev/rdnvram1`(도구는 시작 때도 지우고 다시 만든다) | `finish()` 만 지운다 |
| 6 | `lastSeed` 가 11-2 보다 넓게 기록된다 | ⏭️ 12-1 에 이미 적은 의도된 강화 | `engDraw` |

실기 절차 1 보강: 재부팅 **전** `ls -l /dev` 전체를 호스트에 저장(문자 노드의 권한·major), 부팅 뒤 `vmap` 줄의 major 와 대조 — 같은 major 의 노드가 있으면 도구 전에 멈춘다.

## 14. major 는 자동이 아니라 38 로 고정 (2026-09-18, 13 절 1 을 따라 실기 `/dev` 를 읽고 나서 — 3-5 를 대체)

**내가 틀린 것**: 3-5 "`Character Major` 키는 두지 않는다(자동 할당)" 는 이 기계에서 안전하지 않다.
- 실기 `ls -l /dev/`(읽기만, `/dev` 는 `private/dev` 로 가는 링크라 끝의 `/` 가 필요했다): 문자 노드 284 개, **`pp0` 가 major 1 minor 0 이고 `crw-rw-rw-`**,
  Matrox 시험이 남긴 `osmgavram`·`osmgavramf` 도 major 1(0600 root).
- 커널 이미지(`ref/openstep/ps2/mach_kernel`)의 정적 `cdevsw`(0x1e2f38, `nchrdev` 43, 빈 틀 0x1e5100 과 44 바이트 대조, python):
  비어 있는 칸 1, 7–11, 13, 15–32, 34–41 — **자동 할당은 1** 을 준다(Matrox 가 이 기계에서 받은 값과 같다).
- 그러면 누구나 `/dev/pp0` 를 O_RDWR 로 열어 우리 `d_mmap` 에 닿고, 10-1 E1 의 길이 ≥ 2^31 경로(물리 `0xFFFFE000` 매핑 또는 12 MB `kalloc` 실패 패닉)가
  비 root 에게 열린다.

**결정**: 두 번들 표에 `"Character Major" = "38";`.  38 은 정적 표에서 비었고 `/dev` 에 그 major 의 노드가 없다(후보 17–32, 35, 37, 38 중 자동 할당이
가져가는 낮은 번호에서 가장 먼 것).  부팅 때 누가 38 을 먼저 차지했으면 `IOAddToCdevswAt` 가 실패하고(비어 있을 때만 성공, Matrox S4A 6 Q2) 등록은
`cdevsw` 사유로 거절된다 — 장치가 생기지 않는 쪽으로 닫힌다.  도구의 `/dev` 검사는 그대로(38 의 노드가 새로 생겼으면 멈춤).
규칙 `r4c-tables` 는 38 을 요구하고(변이 둘), 판정기 G1 은 `major = 38` 을 요구한다(자체 시험 변이 "자동 major").

## 15. R4c 실기 결과 — 부팅 `0282b8d0`, build `7f8db842`(runid 789714773), 도구 runid 789719910 (2026-09-18): **PASS**

판정: `tools/r4/check_vmap_log.py build/r4c/0282b8d0/rdn-all.log build/r4c/0282b8d0/r4map-1.out 7f8db842` → **PASS**(G1–G7), 같은 로그에
`check_engine.py` → PASS, `latched=1` 0 줄.

| 게이트 | 실측 |
|---|---|
| G1 | `vmap start=0029e000 end=07c00000 page=8192 shift=13 bar0=e0000000 pfn0=0007014f pfnN=00073dff mem=08000000 aper=08000000 fix=0 self=15893/0 allowed=15537 major=38 ok`, "must NOT be unloaded" 줄; 도구의 `IOCharacterMajor` = 38 = 드라이버; `/dev` 에 major 38 의 다른 노드 없음 |
| G2 | 경계 10 건 기대대로(허용 2 = 창 첫 페이지·끝 페이지, 거절 8 모두 errno 22), minor 1 `open` → ENXIO(6) |
| G3 | 자체 왕복 256 KiB 불일치 0 |
| G4 | 커널 UBLIT(씨앗 `c3660000`) `rc=0`, 준비의 블록 전체 확인 통과, 결과 불일치 0; 도구 읽기 `ok=65536 stale=0 mark=0 other=0` — **유저 페이지 32 개가 맞는 카드 페이지에 닿고, 유저가 쓴 값을 엔진이 읽는다** |
| G5 | 도구가 블록을 쓰고 읽어(데움) 불일치 0 → 커널 FILL `rc=0` 불일치 0 → 도구 읽기 `ok=65536` 나머지 0 — **엔진·커널 별칭의 쓰기가 유저 매핑에 보인다** |
| G6 | `lo=03bfe000`·`hi=07bfe000`: `lo_changed=0 hi_wrong=0`(64 MiB 에일리어싱 없음, 124 MiB 직전 CPU 접근 정상), 두 페이지 복원 `bad=0` |
| G7 | 도구 `exit=0`; open 줄 minor 1 거절·minor 0 성공 각 1; close 1 줄(도구 종료 때 — 관찰); 이후 `RDNR2bCycle` `live=1`, `checked=1 bad=0 vga=0 palette=0 verdict=0` |

기록만(판정 아님): 유저 매핑의 쓰기 262 144 B / 7 005 µs(37.4 MB/s), 읽기 / 52 914 µs(5.0 MB/s) — 읽기가 캐시되지 않는다는 것과는 맞지만
UC 와 WC 는 이것으로 가를 수 없다(11-5).  UBLIT 연산 152 ms, FILL 103 ms.

R4c **완료**.  남은 것(차단 요건으로 넘김): 비 root 클라이언트 전에 open 신원 게이트(10-1 E1, 11-6) — R6/M 의 할당·소유 설계에서.
