# Q1 판정 — §1 입력 사실 교차검토

질문: `Q1_prompt.md`, codex 회신: `Q1_reply.md` (gpt-5.6-sol, read-only, 2026-09-15).
**codex 회신은 입력이지 결론이 아니다.**  아래 판정은 전부 이 세션에서 원문을
연 결과다.  인용 42곳은 Python 스크립트로 해당 줄에 기대 문자열이 있는지
대조했고(42/42), 계획을 바꾸는 주장은 본문을 직접 읽었다.  `U/` =
`ref/upstream/`, `X/` = `U/unpacked/xf86-video-ati-6.14.6/src/`.

## 검토 전에 내가 스스로 찾은 오류 (먼저 적는다)

| 내 오류 | 근거 | 조치 |
|---|---|---|
| "RV280 PLL 기준표 `radeonfb.c:424`" — 실제는 TMDS(DVI) PLL 표 | `radeonfb.c:412-424` `radeon_tmds_pll plls[4]` | 수정함 (codex 도 C23 에서 같은 사실 확인, 수정 후 판을 봤다) |
| `OSRadeonDisplay` 여유 3 → 실제 4 | Python: Matrox C3 표 5 행 모두 `최장-이름길이=81`, `100-(15+81)=4` | 수정함 |

## 판정표

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| C1 | RV280 에는 AGP·PCI 제품이 모두 있다, 실물 식별은 소스로 불가 | `X/pcidb/ati_pciids.csv:189` "Radeon 9250 5960 (AGP)", `:193` "FireMV 2200 (PCI)" 열람 | ✅ 사실. 행동 변화 없음(R1 에서 ID 실측) |
| C2 | 비-AGP 는 `AIC_*` PCI GART | `U/freebsd-stable9/.../radeon_cp.c:1042-1066` 열람 | ✅ |
| C7 | 칩 사진 128 MiB 는 소스로 확인 불가 | 사실(사진 근거) | ⏭️ 계획에 이미 "사진 기준·실측할 것" |
| C9–C10 | radeonfb 는 `CONFIG_APER_SIZE` 를 `sc_memsz` 로, 64 MiB 로 자름 | `radeonfb.c:2872-2880`, `:661-665` 열람 | ✅ (계획과 일치) |
| C11–C12 | xf86 은 전체 VRAM=`CONFIG_MEMSIZE`, 접근 가능량은 `CONFIG_APER_SIZE` 기반이고 **RV280 은 ×2**, BAR0 크기로 다시 자름 | `X/radeon_driver.c:1653-1719`(`RADEONGetAccessibleVRAM`), `:1721-1783`(`RADEONPreInitVRAM`) 본문 열람 | ✅ **채택.** 추가로 codex 가 말하지 않은 사실: RV280 분기는 `OUTREGP(RADEON_HOST_PATH_CNTL, RADEON_HDP_APER_CNTL, …)` 로 **쓰기**를 한다(`:1694-1704`) → R1 은 `HOST_PATH_CNTL` 을 읽기만 |
| C13 | BIOS 포인터는 이중 역참조, RV280 의 refdiv 는 **살아 있는 `PPLL_REF_DIV` 레지스터가 먼저**, BIOS 는 폴백 | `radeonfb.c:1709-1726` 본문 열람: `tmp = GETPLL(PPLL_REF_DIV)` → `refdiv = refdiv ? refdiv : tmp & MASK` → `refdiv ? : GETBIOS16(ptr+0x10)` | ✅ **채택** — 계획 표기 수정, refdiv 는 PLL 인덱스 읽기가 필요 |
| C14 | 무BIOS 기본값·단위 | `radeonfb.c:1671-1687`, `:1730-1734` 열람; Python: 2700×10=27000 kHz, 12500×10→125 MHz, 40000×10→400 MHz | ✅ (계획과 일치) |
| C15 | `0xC0000` 셰도 읽기는 소스로 확인 안 됨 | codex 인용 `radeon_atombios.c:185-188`, `radeon_bios.c:372-375`, `radeonfb.c:1418-1438` 열람 — 사실이나 **codex 가 놓친 선례가 있다**: `X/radeon_bios.c:80-90` 은 PCI ROM 읽기가 실패하고 주 디스플레이면 `info->BIOSAddr = 0x000c0000; xf86ReadDomainMemory(...)` 로 레거시 공간을 읽는다. int10 경로(`:372-375`)도 `BIOSseg << 4` 의 BIOS 사본을 쓴다 | ⚖️ **부분 채택** — "소스 선례 없음" 은 기각(선례 있음), "실기 미검증" 은 유지. 서명 0x55 0xAA 확인(`:80`, `:93`)을 R1 판정에 추가 |
| C16 | PCI ID 두 목록이 다르다: FreeBSD 에 5963 없음, NetBSD 에 5965 없음 | `drm_pciids.h:113-117,128-129`, `radeonfb.c:314-320` 열람 | ✅ **채택** — 합집합 5960 5961 5962 5963 5964 5965 5c61 5c63 |
| C18 | G450 은 `00:1e.0` 직속이 아니라 **`03:0d.0`(HiNT HB4) 브리지 뒤** | `pcils/scan-nextonion.txt:87-95` 열람 | ✅ **채택.** 추가(내가 Python 으로 해독): 두 브리지의 prefetch 창이 모두 `f8000000-f9ffffff` = **32.0 MiB** (G450 BAR0 크기). Radeon BAR0 가 더 크면 BIOS 가 창을 다시 잡아야 하므로 **R1 에서 브리지 창도 기록** |
| C21 | radeonfb 2D 는 MMIO 직접, CP 기호 0 건 | `radeonfb.c:1504-1507`, `:3696-3710` 열람 | ✅ |
| C22 | "G450 Storm 과 같은 모양" 은 소스로 확인 불가 | Matrox 자료는 질문 범위 밖이었다 | ⏭️ 비유일 뿐, 설계 근거로 쓰지 않는다 |
| C23 | `:424` 는 TMDS 표 | `radeonfb.c:412-415, 2096-2110, 2167-2174` 열람 | ✅ (이미 수정) |
| C24 | `DRM_ATI_GART_FB` 는 **유저가 `PCIGART_LOCATION` 을 준 경우에만**, xf86 6.14.6 은 그 호출을 **PCIE 에서만** 한다 → 재래식 PCI 의 기본은 `GART_MAIN` | `radeon_cp.c:1398-1443` 본문, `radeon_state.c:3127-3129`, `X/radeon_driver.c:3763-3769`(`cardType==CARD_PCIE`) 열람 | ✅ **채택** — "PCI 카드는 VRAM 에 둘 수 있다" 를 "커널 경로는 있으나 **재래식 PCI 에서는 참고 구현이 쓴 적 없는 조합**" 으로 수정 |
| C25 | 테이블 32 KiB | `radeon_drv.h:1823`, `radeon_cp.c:2060-2066` 열람 | ✅ |
| C26 | "창 32 MiB" 는 틀림 — 창은 `init->gart_size`, xf86 의 R300 이전 기본값은 **8 MB** | `radeon_cp.c:1329`, `X/radeon_driver.c:2438-2442`, `X/radeon_dri.h:42-43` 열람; Python: 32 KiB/4 = 8192 항목 × 4 KiB = 32 MiB 는 **테이블 용량** | ✅ **채택** — 내 오류. 계획 수정 |
| C27 | 항목 4 KiB 단위 | `ati_pcigart.c:39, 184-216` 열람 | ✅ |
| C28 | 마이크로코드 두 판, MIT | `radeon_microcode.h:2-14`, `radeon_cp.c:481-486` 열람; `WHENCE` 는 앞서 직접 확인 | ✅ |
| C29 | `CSQ_PRIPIO_*` 25 건 전부 `#define`, FreeBSD·Linux 는 PRIBM 두 모드 외 **거절** | Python `os.walk`+바이트 정규식으로 7 트리 재집계: 3/3/3/0/3/7/6 = **25**, 비정의 줄 **0**; `radeon_cp.c:1168-1176`, Linux `:1228-1236` 열람 | ✅ **채택** — "참고 구현이 PIO 모드를 명시적으로 거절한다" 를 계획에 추가 |
| C30 | VERTEX 모드 비유는 소스 근거 없음 | Matrox 실측 기록이 근거(질문 범위 밖) | ⏭️ |

## 2차 자기검사

✅ 행을 다시 읽었다.  C11–C12 는 처음에 부분 문자열 대조만 했고 본문을 안
읽었다 → 본문(`:1653-1783`)을 열어 확인했고, 그 과정에서 `HOST_PATH_CNTL`
쓰기를 새로 발견했다.  C15 도 처음엔 codex 인용만 열었다 → `radeon_bios.c`
의 `radeon_read_bios` 를 추가로 열어 선례를 찾았다.  C18 의 창 크기와 C26·C29
의 수는 Python 출력으로 재계산했다.
