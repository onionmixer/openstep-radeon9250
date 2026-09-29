# Q10 판정 — R1c·R2a 구현 계획 교차검토(자체 agent) 재검증

작성 2026-09-15.  회신 `docs/review/Q10_reply.md`, 질문 `docs/review/Q10_prompt.md`.  **agent 회신은 검증 대상
입력이다.**  아래는 이 세션에서 원문을 열었거나 직접 측정·계산한 것만 적는다.

## 0. 내가 틀린 것 (먼저)

1. **B1 — R2a 가 DATA 읽기 뒤 인덱스를 다시 확인하지 않는다**: 재읽기와 DATA 읽기 사이에 인덱스가 바뀌면 다른
   레지스터 값이 흔적 없이 기록된다.
2. **B2 — 호스트 목적 파일 규칙이 옳은 코드를 떨어뜨린다**: 아래 헬퍼를 gcc-12 `-m32 -O0` 로 직접 빌드했더니
   `rdnMmioWrite8` 에 바이트 저장이 **둘**(`mov %al,-0x4(%ebp)` 스택, `mov %al,(%edx)` MMIO).  `-O2` 에서는 하나
   (`mov %dl,(%eax)`).  R1 규칙은 `-O0 -fno-inline` 이 전제(`tools/r1/hostcheck.sh` 142 행).
3. **B3 — reloc 의 stab 을 몰랐다**: `MDH10Disk_reloc` 을 Python 으로 파싱 — nsyms 3122, `N_SLINE`(0x44) 994 개,
   `N_SECT` 외부 7·지역 67.  타깃 빌드는 `-g -O`(`makefiles/.../app/common.make` 110–112 행).  "다음 text 심볼" 은
   stab 을 빼야 한다.
4. **B4 — R1c 소스 규칙 "`open(` 1 곳"** 이 출력 파일 open 과 모순, fd 동일성 규칙은 grep 으로 판정 불가.
5. **B5 — R1c 위험 읽기 전 `sync` 없음**, write/fsync/close 반환 미검사, 첫 캡처 길이 = 512 미요구.
6. **B6 — PCIR device 하드 게이트**(R2 계획 §3 게이트 3, Q9 에서 내가 넣음): xf86 은 PCIR ID 를 보지 않고 서명이
   틀려도 경고만(`radeon_bios.c:380-427` — 389·391·395 행을 열었고, `dptr` 사용은 0x18·서명·+0x14 뿐, grep).
7. **B7 — R2 계획 §3 게이트 "오프셋 8 저장이 전부 1 바이트"** 가 같은 문서의 32 비트 중단 쓰기와 모순.
8. **ISA 구멍 단정**: "관리 밖 페이지(ISA 구멍)" 은 근거 없음 — `vm_first_phys` 는 실행 시 값.
9. **`TV_DAC_CNTL`·`DISP_HW_DEBUG` 읽기 선례 인용**이 Dell 서버 조건부 줄(xf86 `legacy_crtc.c` 549–553 행)이었다.
   무조건 읽기는 `legacy_output.c` 369·372 행.
10. **R1 교훈 미채택**: R1 결과 §1-6 "다음 실기 스크립트는 백그라운드 실행+타깃 파일로 완료 판정".
11. **run id 부모 디렉터리 생성 누락**(R1 `target-run.sh` 89 행은 만든다).
12. **`& 0x3f` 제거 변이는 등가 변이**: 표의 모든 인덱스가 bit 6–7 = 0(Python) — 시뮬레이터로는 못 죽인다.
13. **R2a 게이트 3 이 `CLOCK_CNTL_INDEX` 하위 바이트까지 R1(다른 부팅) 과 비교**: 하위 바이트는 "마지막 PLL 접근자"
    값이라 건강해도 달라진다.
14. **`pllend store=` 게이트는 항등식**(찍은 값이 계산값).

## 1. 판정표

| # | agent 주장 | 내 검증 | 판정 |
|---|---|---|---|
| C1.1 | `lseek`→`f_offset`→`rwuio` 가 `uio_offset` 에 복사→`vno_rw`→`spec_rdwr`(VCHR)→`cdevsw[3].d_read`=`_mmread` | Ghidra `0010cd54.c` 17 행, `0010ceac.c` 19·43·46·58 행, `0011b984.c` 35–40 행, `00139e18.c` 36–40 행(VCHR=4 → `PTR__cnread_001e2f40[major*0xb]`), `references.tsv` 115827·116280–116282 행, `symbols.tsv` `_cdevsw 0x1e2f38`·`_nulldev 0x10ccb0`·`_mmread 0x194bf4`, Python `0x1e2f38+3*44` = `0x1e2fbc`; lseek `0011d558.c` 26·42·67 행(VFIFO 만 거절); `vnode.h` 37 행 VCHR=4·VFIFO=8 | ✅ **R1c 설계 전제 확인**(open/close 는 `_nulldev`) |
| C1.1b | 타깃 `/mach_kernel` 이 같은 이미지인지 미확인 | 미러 `sha256` = `33469393…` = Ghidra 머리 | ⚠️ 유지 |
| E1.8/9 | `pmap_remove` 는 관리 밖 페이지 PTE 만 0, `splvm` 은 무동작, `splhigh` 는 CLI | `0018f7f8.c` 51–53 행; `whole-program.asm` 208529–208534(`0x18b964` = `_splvm`, IPL 읽기만)·209111 행 `CLI` | ✅ |
| B1 | DATA 뒤 인덱스 재확인 | 내 오류 1 | ✅ + 설계 강화(§2) |
| C2.3 | 중단 경로의 **낡은 `S`** 되쓰기가 소유자 변경을 덮을 수 있다; WR_EN 래치 방식 미확인 | xf86 `OUTPLL` 은 `idx|WR_EN` 저장 후 DATA 쓰고 WR_EN 을 안 내린다(`radeon_driver.c:609-621` 부근 629 행) | ✅ → 그룹마다 직전 값 `P` 기준으로 복원·중단(§2) |
| C2.4 | `splhigh`/`splx` 로 그룹 원자화 | `symbols.tsv` `_splhigh 0x18c0d8`·`_splx 0x18b544`(IMPORTED), `CLI` 확인 | ✅ 채택 — `nm -u` 가 적재 가능성을 판정(안 되면 계획 개정) |
| C2.7 | 두 비교를 `||` 로 묶지 말 것(long long 버그의 32 비트 변형은 미확인) | 메모리 `openstep-cc-longlong-bug` | ⚖️ 비용 0 이라 채택(분리 `if`, `long long` 금지 규칙) |
| B2 | 목적 파일 규칙 재정의 | 내 오류 2(측정) | ✅ 저장 = 기준 레지스터가 `%esp`/`%ebp` 가 아닌 메모리 쓰기, 폭은 원천 레지스터 이름; 호출·`out` 규칙은 `-O0 -fno-inline` 에서만 |
| B3 | stab 제외, 심볼 → 파일 오프셋 계산, 자체검사 사례 | 내 오류 3(측정) | ✅ |
| C3.3 | 타깃 게이트는 헬퍼 폭만 증명, 다른 저장·호출 수·오프셋은 소스 규칙·시뮬레이터 몫; kl_ld 는 모듈 내부 PC 상대 호출 재배치를 남기지 않음 | 텍스트 재배치 분류는 agent 측정(`pcrel-extern-undef` 340 등) — **내가 다시 세지 않음** | ⚖️ 결론(역할 분리)은 채택, 수치는 문서에 옮기지 않음 |
| E3.6 | R1 정규식이 `((volatile …*)base)[2] = S` 를 놓친다 | 이 세션 grep 시험: 둘째 줄만 매치 | ✅ → `RDNR2aProbe.m` 에 `volatile`·포인터 캐스트 0 건 |
| B4 | strace 동적 검사 | 호스트 `/usr/bin/strace` — **내가 확인 안 함** | ⚖️ 채택하되 코드 단계에서 존재 확인 |
| B5 | `sync`·반환값·길이 | 내 오류 5 | ✅ |
| B6 | vendor 만 하드, device 는 기록 | 내 오류 6 | ✅ |
| B7 | R2P 게이트 문구 수정 | 내 오류 7 | ✅ |
| C4.1 | 프로브에 직접 `mmioRead` 금지, 시뮬레이터 매핑 `PROT_NONE`, 헬퍼가 base·해제 뒤 접근·오프셋 검사 | R1 probe 347–351 행 `mmioRead`, R1 sim `mmap(... PROT_READ ...)` | ✅ |
| C4.2–4 | 세계·위반·변이 추가, `& 0x3f` 등가 변이 | 내 오류 12 | ✅ |
| C5.1a | 게이트 3 은 `CLOCK_CNTL_INDEX` bit 8–31 만, 미정의 비트만 다르면 "기록+재계획" | 내 오류 13 | ✅ |
| C5.1c | 단위 교차: NetBSD 기본값 12500/40000(10 kHz) ×10 = 오라클 `DEFAULT_CLOCKS` 125000/400000 | `radeonfb.c:1671-1687`, `radeon_modeset.py` 98 행 | ✅ |
| C5.1d | rev > 9 이면 `+0x36`/`+0x3a` 기록 | `radeon_bios.c` 1006–1008 행(Q9 에서 확인) | ✅ |
| C5.2 | `store=` 항등식, `ctl` 게이트는 독립 재계산으로 이름 | 내 오류 14 | ✅ |
| C5.3 | 생성기·파서 오프셋을 서로 다른 참고에서 추출, 겹침 일치 검사 | 논리 | ✅ |
| C6 | R1 Python 은 읽기 전용 import, 셸만 복사, drift 는 정확한 hunk 허용 목록 + 자기 변이, 환경 변수 접두어 규칙 | R1 스크립트 `${R1_TMP:-/tmp}` 등 | ✅ |
| C7.2 | 백그라운드 실행 + 완료 표지 | 내 오류 10 | ✅ |
| C7.4 | 인용 고침, `M_SPLL_REF_FB_DIV` = `X_MPLL_REF_FB_DIV`(0x0a), 브리지 0x3e = 0x3c bit 19 | xf86 `radeon_reg.h` 293·1727 행 둘 다 0x000a; `pcireg.h:1420-1425` | ✅ |
| C7.5 | 부모 디렉터리 | 내 오류 11 | ✅ |
| C1.2 | 출력 경로 `/tmp/..` 허용 | 논리 | ✅ 도구가 경로를 인자로 받지 않고 이름을 짓는다 |
| C1.4d | `libc.h` 와 `unistd.h` 의 `read`/`write` 원형 충돌 | `bsd/libc.h` 102 행 `int` 길이, `bsd/unistd.h` 112 행 `size_t` | ✅ 헤더는 `libc.h` + `sys/fcntl.h`(open 125·lseek 136·fsync 120·close 91 행 확인) |

## 2. R2a PLL 그룹 설계(채택 결과)

레지스터마다 인터럽트를 막은 한 묶음:

```
s = splhigh()
  P = R32(0x08)
  if (P & 0x80) -> splx; stop pll-index-busy (그룹 k 에서)
  W8(0x08, idx & 0x3f)
  C = R32(0x08);  if (C & ~0xff) != (P & ~0xff) -> 중단(P)
                  if (C & 0xff)  != idx         -> 중단(P)
  V = R32(0x0c)
  D = R32(0x08);  if D != C                       -> 중단(P)
  W8(0x08, P & 0xff)
  E = R32(0x08);  if E != P                       -> 중단(P)
splx(s)
```

- 중단(P) = `W32(0x08, P)` → 재읽기 → `splx` → 줄 → 언매핑 → 끝.  `P` 는 인터럽트가 막힌 같은 묶음 안에서 읽은
  값이라 소유자 변경을 덮지 않는다.
- 묶음 사이에 소유자가 인덱스를 바꾸면 다음 묶음의 `P` 가 달라진다 → 게이트가 아닌 **기록**(`P` 변화 = 소유자
  활동) + 판정은 FAIL(값 신뢰 불가) 로 재계획.
- 묶음 안에 sleep·로그 없음.

## 3. 2차 자기검사

- 커널 경로·기호 주소·asm 줄·pmap 코드는 이 세션에서 열었다.  gcc 폭·정규식·stab 수는 이 세션에서 직접 돌렸다.
- agent 수치 중 재배치 분류 수, strace 존재는 다시 확인하지 않았고 문서 결론이 거기에 의존하지 않게 적었다.
- ⚠️ 남김: 타깃 커널 동일성, WR_EN 래치 방식, `vm_first_phys`, cc 2.7.2.1 `-O` 의 프레임 포인터 유지, `_splhigh`
  적재 링크(타깃 `nm -u`), `CLOCK_CNTL_INDEX`·`DAC_CNTL`·`CRTC_EXT_CNTL` 미정의 비트의 휘발성.
