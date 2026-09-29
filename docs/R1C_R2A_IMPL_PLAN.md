# R1c·R2a 구현 계획 (개정 1)

작성 2026-09-15.  **개정 1 — Q10 교차검토(자체 agent)를 재검증해 반영(`docs/review/Q10_verdict.md`), 코드 없음.**
순서: 이 계획 → 교차검토 → 재검증 → 코드 → 호스트 검사 → 실기.  상위 문서는 `docs/R2_FIRST_LIGHT_PLAN.md` §3(R1c·R2a
의 **무엇**) 이고, 이 문서는 **어떻게**(파일·도구·로그 문법·검사·실행 절차) 를 정한다.

- R1 의 틀(`docs/R1_INTERROGATION_PLAN.md` §5·§7, `tools/r1/`)을 따른다.
- **R1 의 파서·게이트는 고치지 않는다** — R1 판정은 같은 파서를 같은 로그에 다시 돌려 재현돼야 한다
  (`docs/R1_RESULT.md` 첫 줄의 명령).
- 수치는 모두 이 세션의 Python 출력 또는 직접 측정이다.

## 0. 공통

| 항목 | 규칙 | 근거 |
|---|---|---|
| 기준 부팅 | generic VGA(`Active Drivers` 에 `VGA`, Matrox 없음), `/ndrv` 마운트, gcdsd, **nxlogd 실행 중** | R1 과 같음 |
| 실행 시점 | 부팅 뒤 충분히 지나 WindowServer 가 안정된 뒤, 로그인·로그아웃·종료·밝기 조작 없이.  R1c 와 R2a 는 같은 부팅이든 다른 부팅이든 상관없다 | 소유자가 비디오 BIOS 를 부를 수 있다(Q9 B8) |
| 순서 | R1c(읽기만) 먼저.  R1c 가 패닉으로 루트 fsck 를 부르면 PLAN §7 에 따라 하드웨어 쓰기 마일스톤 전체가 멈추고 R2a 는 디스크 검사 뒤로 밀린다 — 받아들인다 | Q10 C7.3 |
| 한 번만 | 부모 디렉터리가 없으면 만들고(`if [ ! -d ... ]; then mkdir ...`), `mkdir /me/rdn-<stage>-ran.d/<id>` 로 원자 선점(적재·읽기 **전**) → `sync` | R1 `target-run.sh` 89–92 행 |
| 실행 방식 | 타깃 스크립트는 `nohup` 백그라운드로 띄우고 **완료 표지 파일**로 판정.  probe·읽기의 예상 시간 동안은 폴링하지 않고, 지난 뒤 한 번 확인 | R1 결과 §1-6(gcds 반환 5 분 이상) |
| 행 | operator 전원 재시작 → 같은 기준선 → nxlogd·스크립트 출력의 마지막 줄로 멈춘 조작 특정 → **같은 조작 재시도 금지**, 재계획 | R1 계획 §2-4 |
| 전달 | 호스트 `build/<stage>/` = 타깃 `/ndrv/openstep-radeon9250/build/<stage>/`(NFS).  타깃 쓰기는 `/tmp` 에 만들고 한 번에 복사, 복사본 `sum` 을 원본과 대조(16 비트 BSD sum — 우발 손상 탐지용이지 치환 방지는 아니다) | NFS 레코드 재열기 함정 |
| 셸 | 타깃 스크립트는 `/bin/sh`, ASCII, `$(...)`·`printf`·`cut`·`grep -q`·`\|`·`mkdir -p`·`test -e`·`dirname` 금지 | R1 린트 |
| 코드 재사용 | **Python 도구는 R1 모듈을 읽기 전용 import**(문법 도우미, BSD sum, `pci`/`cfg`/`reg`/`bridge` 줄 파서).  **복사는 `/bin/sh` 타깃 스크립트만**(import 불가) — `tools/r2a/check_drift.py` 가 원본 대비 **정확한 hunk 허용 목록**(원문·새 문장·개수) 만 있음을 확인하고, 같은 실행에서 복사본의 `fail` 한 줄을 지운 변이가 FAIL 해야 PASS.  복사본의 `${NAME:-…}` 는 모두 새 접두어이고 시험 하네스가 정확히 그 집합을 설정 | Q10 C6 |
| 전체 검사 | `tools/check-all.sh` 에 R1c·R2a 단계 추가, 기존 R1 단계는 그대로 PASS | — |

## 1. R1c — BIOS 셰도 읽기

### 1-1. 사실(설계 입력, 이 세션에서 확인)

- **읽기 경로**(Ghidra, 미러 커널 SHA-256 `33469393…` — 타깃 `/mach_kernel` 과 같은 이미지인지는 미확인):
  - `lseek` 은 VFIFO 만 거절하고 SEEK_SET 을 `f_offset` 에 넣는다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
  - `rwuio` 가 `uio_offset = f_offset` 로 fileops rw 를 부른다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
  - `vno_rw` → `spec_rdwr` 의 VCHR 분기가 `cdevsw[major].d_read` 로 uio 를 그대로 넘긴다(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
  - `cdevsw[3]` = open `_nulldev`, close `_nulldev`, read `_mmread`(`references.tsv`, Python `0x1e2f38+3*44` = `0x1e2fbc`).
  - `/dev/mem` 은 3,0(R1 로그 3 행).
- **`_mmrw` minor 0**:
  - `uio_offset ≥ mem_size` 면 EFAULT.
  - 아니면 한 페이지씩: `vm_map_find` → `pmap_enter(prot 3, wired)` → `uiomove`(읽기 방향 `copyout`) → `vm_map_remove`.
  - `pmap_enter` 는 `[vm_first_phys, vm_last_phys)` 안에서만 pv 목록을 만지고, `pmap_remove` 는 밖이면 PTE 만 0 으로 한다.
    0xC0000 이 어느 쪽인지는 **실행 시 값이라 미확인**.
  - 물리 페이지에 쓰는 코드는 없다.
- `splvm` 은 이 커널에서 무동작(IPL 읽기만), `splhigh` 는 `CLI`(**근거 미확정**(2026-09-16 출처 규칙, §15-5)).
- ROM 구조(`pcireg.h:1503-1506`, `pcireg.h:1511-1523`): 헤더 `+0x18` PCIR 포인터, PCIR `+0x04` vendor·`+0x06` device·
  `+0x10` `rom_len`(512 단위)·`+0x14` code type.
- 사용자 헤더: `bsd/libc.h` 에 `open`(125 행), `close`(91), `read`/`write`(102, `int` 길이), `fsync`(120),
  `lseek`(136), `exit`.  `O_*` 는 `bsd/sys/fcntl.h`(34·35·40·42 행).  `bsd/unistd.h` 의 `read`/`write`(`size_t`) 와 원형이 달라
  **같이 쓰지 않는다**.  `SEEK_SET` 이 이 헤더 집합에 없으면 값 0 을 이름 상수로 정의하고 호스트 검사가 `bsd/unistd.h` 의
  값과 대조.
- Python: `0xC0000` = 786432, 끝 `0xD0000`, 64 KiB = 512 × 128.

### 1-2. 도구 `tools/r1c/rdnbios.c`

```
rdnbios <runid> <length>
  runid: 1..999999999 십진, length ∈ {512·k | k = 1..128}, 아니면 종료 2, 장치를 열지 않음
  출력 경로는 도구가 짓는다: /tmp/rdn-bios-<runid>-<length>.bin  (인자로 경로를 받지 않음)
  out = open(경로, O_WRONLY|O_CREAT|O_EXCL, 0644)   실패 종료 2
  dev = open(RDN_MEM_PATH, O_RDONLY)                 RDN_MEM_PATH 기본 "/dev/mem", 실패 종료 3
  lseek(dev, 0xC0000, SEEK_SET) != 0xC0000         → 종료 3
  read 를 length 가 찰 때까지(0/-1 → 종료 4, 받은 수 출력)
  close(dev) != 0 → 종료 5
  write(out, buf, length) != length → 종료 6;  fsync(out) != 0 → 6;  close(out) != 0 → 6
  표준출력 한 줄: "RDNBIOS runid=<id> offset=000c0000 length=<n> got=<n> first=<hex2><hex2> exit=<e>"
```

- 오프셋은 컴파일된 상수 하나.
- 장치는 `O_RDONLY` 로 **먼저 출력 파일을 만든 뒤** 연다.  출력 실패로 장치를 괜히 읽지 않게.
- `mmap`·`ioctl` 없음.  `long long` 없음.  시그널·재시도 없음.
- 호스트 시험 빌드만 `-DRDN_MEM_PATH=<가짜 파일>`.  타깃 빌드 명령은 스크립트에 고정되고 `-D` 가 없다.

### 1-3. 호스트 검사 `tools/r1c/hostcheck.sh`

1. **C89**: 타깃 헤더(`libc.h`, `sys/fcntl.h`)로 `gcc-12 -std=c89 -pedantic-errors -nostdinc
   -Werror=implicit-function-declaration`(+ clang).
2. **`#import` 규칙**(R1 과 같은 검사, R1 스크립트 import).
3. **소스 규칙**(주석 제거 뒤, 각 규칙에 변이):
   - `open(` 은 **2 곳**: 하나는 `RDN_MEM_PATH, O_RDONLY` 를 정확히, 다른 하나는 `O_WRONLY|O_CREAT|O_EXCL` 를 정확히.
   - `0xC0000` 1 곳.
   - `lseek(` 1 곳.
   - `mmap`·`ioctl`·`O_RDWR`·`long long` 0 건.
4. **동적 검사** `tools/r1c/sim_r1c.py`: 호스트 빌드를 `strace -f -e trace=open,openat,lseek,_llseek,read,write,
   mmap,mmap2,ioctl,close` 로 실행하고, 장치 경로의 fd 에 대해 open `O_RDONLY` 정확히 1 번, `lseek(fd, 786432, SEEK_SET)`
   정확히 1 번, 읽기만, close 1 번임을 확인(fd 동일성은 텍스트로 판정 불가, Q10 B4).
   - **세계**:
     - 정상 이미지(0xC0000 에 합성 BIOS)
     - 파일이 0xC0000 보다 짧음(→ 종료 4)
     - 길이 인자 0·511·513·65537·음수·문자
     - runid 0·문자
     - 출력 파일이 이미 있음
     - 장치 없음
     - `/tmp` 가득(쓰기 제한 파일시스템을 흉내 낼 수 없으면 생략하고 사유 기록)
   - **변이**(각각 실패해야):
     - 오프셋 인자화
     - 장치 `O_RDWR`(쓰지는 않음 — 텍스트 규칙이 잡음)
     - 복제한 fd 로 장치에 write(동적 규칙만 잡음)
     - 짧은 읽기 무시
     - `O_EXCL` 제거
     - write 반환 무시
   - 머리말에 "가짜 장치는 정규 파일이라 페이지 단위 읽기·`mem_size` EFAULT 는 보여 줄 수 없다 — 커널 코드 판독이 대신한다"
     를 적는다.
   - strace 가 호스트에 있는지는 코드 단계에서 확인한다.
5. **파서 자체검사**(§1-5).

### 1-4. 타깃 스크립트 `tools/r1c/target-r1c.sh`

```
sh target-r1c.sh facts <runid>
sh target-r1c.sh read <runid> <length> <sum> <blocks>      <sum blocks> = rdnbios.c 의 BSD sum
```

둘 다 `nohup sh target-r1c.sh ... > /tmp/rdn-r1c-<runid>-<step>.out 2>&1 &` 로 띄우고, 끝에 `/tmp/rdn-r1c-<runid>-<step>.done` 을
만든다.

**`facts`**(장치 접근 없음):
- `ls -l /dev/mem`, `id`, `ls -l /usr/ucb/logger /usr/bin/logger /bin/logger`
- `ps ax | grep nxlogd`, `Active Drivers` 줄, `ls -l /bin/cc /usr/bin/cc`
- 결과를 `/ndrv/.../build/r1c/` 로 복사하고 sum 대조

**`read`**:
1. `rdnbios.c` sum = 인자.
2. root·nxlogd·`Active Drivers` 에 `VGA` 있고 Matrox 없음.
3. 부모 디렉터리 확인·생성 → `mkdir /me/rdn-r1c-ran.d/<runid>-<length>`(있으면 FAIL) → `sync`.
4. `cc -O -o /tmp/rdnbios-<runid>-<length> <소스>`(고정 명령, 종료 코드 확인).
5. (logger 있으면) `RDN-R1C <runid> start length=<n>` → `sync`.
6. 실행.  종료 코드·표준출력을 기록.
7. 표지 `RDN-R1C <runid> done exit=<e>`.
8. 출력 파일 크기 = length 확인(`ls -l` 의 크기 열) → `sum` → `/ndrv/.../build/r1c/` 로 복사 → 복사본 sum 대조.
9. `R1CREAD DONE` 또는 `R1CREAD FAIL <이유>`, `.done` 표지.

두 번 실행한다:
1. `read <runid> 512`.
2. 호스트 `parse_bios.py first` 가 크기 바이트로 길이를 계산 → `read <runid> <length>`.

크기 바이트 < 2 는 `first` 가 거절한다(선점 이름 충돌 방지).

### 1-5. 호스트 파서 `tools/r1c/parse_bios.py`

```
parse_bios.py first <cap512> <r1log> <r1runid>
    → 캡처가 정확히 512 바이트, 55AA, 크기 바이트 ≥ 2, 두 번째 길이 = 512 × 크기 바이트(≤ 65536) 출력.  게이트 1 만.
parse_bios.py full <cap512> <capN> <r1log> <r1runid> [<r2afacts>]
    → R2 계획 §3 R1c 하드 게이트 1–7, 기록 항목, facts 파일 build/r1c/bios-facts-<sha256 앞 16>.txt
parse_bios.py --self-test
```

**게이트**(R2 계획 §3 에서 이번에 고친 것 포함):
- **vendor = 0x1002, code type = 0** 이 하드.  **device 는 기록** — R1 RV280 목록 안이면 "목록 안" 으로 표시.
  xf86 은 PCIR ID 를 보지 않는다(Q10 B6).
- 필드 오프셋:
  - **파서는 NetBSD `radeonfb.c:1697-1714` 에서** 기계 추출(refclk·refdiv·min·max).
  - **합성 생성기는 xf86 `radeon_bios.c:997`·`radeon_bios.c:1017` 부근 줄에서** 추출(같은 넷 + mclk·sclk·rev).
  - 두 추출이 겹치는 넷에서 같은지 자체검사가 대조한다 — 한 표를 둘이 import 하면 추출 오류가 공유돼 항등식이 된다.
- **단위**: BIOS 값은 10 kHz.  kHz 변환은 한 곳.  자체검사가 NetBSD 기본값 12500/40000(`radeonfb.c:1671-1687`) 을 그 변환에
  넣어 오라클 `DEFAULT_CLOCKS` 의 125000/400000(`tools/oracle/radeon_modeset.py` 98 행) 과 같은지 확인한다 — 서로 다른 저자의
  두 파일.
- rev > 9 이면 `+0x36`·`+0x3a`(경계 검사) 를 기록.
- R2a facts 가 주어지면 BIOS refdiv 와 `PPLL_REF_DIV & 0x3ff` 의 일치 여부를 **이름 붙은 경고 줄**로 찍고, R1C 결과
  문서에 필수 기록.  이것이 오프셋 사슬 0x48 → +0x30 → +0x10 의 유일한 독립 검사다.

**자체검사**(합성 이미지):
- 변이 각각 FAIL:
  - 서명
  - 크기 바이트 < 2 · > 캡처
  - 두 캡처 앞 512 불일치
  - PCIR 포인터 경계 밖·서명·vendor·code type
  - 크기 바이트 > `rom_len`
  - `BIOS16(0x48)` = 0
  - ATOM·MOTA
  - PLL 블록 경계 밖
  - refclk 2950·0
  - min ≥ max
  - mclk 0
  - 분주 선택 실패
  - 첫 캡처 511 바이트
- PASS 여야:
  - 크기 바이트 < `rom_len`
  - max 350 MHz(post 4 선택)
  - device 0x5964(목록 안, 기록만)

### 1-5b. [구현] R1c 코드(2026-09-15) — 계획과 달라진 곳

`tools/r1c/`: `rdnbios.c`, `target-r1c.sh`, `parse_bios.py`, `sim_r1c.py`, `check_target_r1c.py`, `hostcheck.sh`,
`hostsim/libc.h`.  `tools/check-all.sh` 에 `hostcheck-r1c` 추가, 전체 PASS.

- **파서 게이트 7 에 refdiv 2..0x3ff 추가**: R2 계획 §3 목록(개정 2)에서 빠져 있었다.  0 이면 분주 계산이 "성공" 으로
  보이기 때문이다.
- mclk(+0x08)·sclk(+0x0a)·rev>9 의 +0x36/+0x3a 는 NetBSD 가 읽지 않는다.  그래서 파서는 손으로 적고, 생성기는 xf86
  추출로 둔다.  어긋나면 자체검사가 드러낸다.
- 오라클 출력은 목표 PLL 출력(`sel_target_khz` = post × 모드 클럭) 과 정수 feedback 이 주는 실제 VCO
  (`sel_vco_actual_khz` = 분수) 를 따로 기록한다(27 MHz/12/173 이면 389250 kHz, Python).
- **캡처 경로는 `/tmp` 고정**이다(도구가 이름을 짓는다).  스크립트의 `TMP` 재정의 대상이 아니다 — 시험 하네스가 이
  불일치를 잡았다.
- 소스 텍스트 규칙에 `dup`·`fcntl`·`pwrite` 금지와 "`write` 는 `ofd` 에 한 번" 을 추가했다.
  - 변이는 **자기 규칙으로** 잡혀야 PASS 다.
  - 처음에는 `#import <sys/fcntl.h>` 가 `fcntl` 규칙에 걸리면서, 다른 변이들이 엉뚱한 규칙으로 "잡힌" 것처럼 보였다.
    전처리 줄을 단어 규칙에서 빼고, 기대 규칙 이름을 요구하도록 고쳤다.
- 동적 검사(strace) 세계 17·변이 8, 스크립트 사례 24(facts 1, read 20, usage 3), 파서 자체검사 40 항목.
- 호스트 게이트가 `rdnbios.c` 의 BSD sum 을 찍는다(`target-r1c.sh read` 인자).
- root 확인은 `id` 출력 해석 대신 **`[ -r /dev/mem ]`**.  실제로 필요한 것은 읽기 권한이고, `id` 가 타깃에 없으면
  검사가 조용히 통과할 수 있다.
- 캡처 크기 확인은 `ls -l` 열 대신 `wc -c < 파일`(열 배치가 R1 기록마다 달랐다).
- `rdnbios` 의 종료 코드는 대입+명령 치환이 아니라 명령 자체의 `$?` 로 받는다(옛 Bourne 셸의 대입 상태 불확실).

### 1-6. R1c 게이트·결과

- 게이트 = 파서 `full` PASS + 두 `read` 모두 `R1CREAD DONE` + 크기·복사본 sum 일치.
- 결과는 `docs/R1C_RESULT.md`.
- 실패는 재시도 금지, 원인별 재계획(예: 오프셋이 안 먹으면 C2 — probe 가 매핑해 IOLog).

## 2. R2a — MMIO·PLL 스냅샷 probe

### 2-1. 트리

`probe/RDNR2aProbe/` — R1 bundle 뼈대에서 서버 이름·진입점만 바꾼다:

| 파일 | 내용 |
|---|---|
| `RDNR2aProbe.m` | 로직.  **`volatile`·포인터 캐스트가 한 번도 없다** — MMIO 는 전부 아래 헬퍼로(R1 의 직접 `mmioRead` 는 가져오지 않는다).  PCI 스캔·BAR 판정은 R1 코드를 옮기되 MMIO 접근만 헬퍼로 바꾼다 |
| `RDNR2aMMIO.m` | `unsigned long rdnMmioRead32(vm_address_t, unsigned int)`, `void rdnMmioWrite8(vm_address_t, unsigned int, unsigned char)`, `void rdnMmioWrite32(vm_address_t, unsigned int, unsigned long)` — 각 한 줄의 `volatile` 접근.  `static`·`inline` 없음, **별도 컴파일 단위**라 cc 2.7.2.1 에서 인라인될 수 없고 타깃 reloc 에 심볼로 남는다 |
| `Load_Commands.sect.in` | `CALL radeonR2aEntry <runid>` / `WIRE` / `START`, ADVERTISE 없음 |

### 2-2. 순서 (`radeonR2aEntry(runId)`)

1. `begin version=1 build=<hex8>`.
2. **A**: PCI 스캔·브리지·카드 1 장·cfg 덤프(R1 과 같은 판정).  브리지 줄에 `ctl3c=<hex8>` — config 0x3c 워드이고, 상위 16 비트가
   브리지 제어(R2 계획이 말한 "0x3e" 와 같은 필드), bit 19 = VGA 전달(`pcireg.h:1420-1425`).
3. **B**: BAR2 검사·매핑(0x2000)·생존 8 표본(정적이면 `stop reason=vline-static` → 언매핑 → 끝, **인덱스 쓰기 없음**)·`frame60`.
4. **레지스터**: R1 의 35 개 + 15 개(§2-3).
5. **PLL 그룹 10 개**(§2-4).
6. 언매핑, `end lines=<n>`.

- 줄 수(Python): 54 + 15 + 1 + 10 + 1 = 81 줄 × `IOSleep(20)` ≈ 1.6 s.
- 모든 표본·PLL 값은 **먼저 다 읽고** 줄을 찍는다.

### 2-3. 추가 MMIO 레지스터 (15 개)

오프셋은 NetBSD·xf86 두 헤더가 같다(Python 대조).  최대 오프셋은 R1 의 0x0e40 그대로(0x0e44 ≤ 0x2000).

| 레지스터 | 오프셋 | 참고 읽기(xf86) |
|---|---|---|
| `CRTC_OFFSET_CNTL` | 0x0228 | `legacy_crtc.c` 542 행 |
| `DISP_MERGE_CNTL` | 0x0d60 | `legacy_crtc.c` 544 행 |
| `TV_DAC_CNTL` | 0x088c | `legacy_output.c` 369 행(무조건) |
| `DISP_HW_DEBUG` | 0x0d14 | `legacy_output.c` 372 행(무조건) |
| `OVR_CLR` · `OVR_WID_LEFT_RIGHT` · `OVR_WID_TOP_BOTTOM` | 0x0230·0x0234·0x0238 | `legacy_crtc.c` 503–505 행 |
| `OV0_SCALE_CNTL` · `SUBPIC_CNTL` · `VIPH_CONTROL` · `I2C_CNTL_1` | 0x0420·0x0540·0x0c40·0x0094 | `legacy_crtc.c` 506–509 행 |
| `CAP0_TRIG_CNTL` · `CAP1_TRIG_CNTL` | 0x0950·0x09c0 | `legacy_crtc.c` 511–512 행 |
| `MEM_CNTL` | 0x0140 | `radeon_driver.c:1629-1634` |
| `MEM_TIMING_CNTL` | 0x0144 | `legacy_crtc.c` 1437 행 |

### 2-4. PLL 그룹

**인덱스(10 개, 두 헤더 같음)**:

| 레지스터 | 인덱스 | 참고 읽기 |
|---|---|---|
| `PPLL_CNTL` | 0x02 | xf86 `legacy_crtc.c` 402 행 |
| `PPLL_REF_DIV` | 0x03 | `radeonfb.c:1697-1714` |
| `PPLL_DIV_0` | 0x04 | `radeonfb.c` 2197 행 |
| `PPLL_DIV_3` | 0x07 | xf86 `legacy_crtc.c` 602 행 |
| `VCLK_ECP_CNTL` | 0x08 | `radeonfb.c` 2979 행 |
| `HTOTAL_CNTL` | 0x09 | xf86 `legacy_crtc.c` 603 행 |
| `X_MPLL_REF_FB_DIV` | 0x0a | xf86 `radeon_driver.c` 1132 행 — NetBSD 헤더의 `M_SPLL_REF_FB_DIV` 와 같은 인덱스(xf86 `radeon_reg.h` 293·1727 행 둘 다 0x000a) |
| `SCLK_CNTL` | 0x0d | xf86 `radeon_driver.c` 1182 행 |
| `MCLK_CNTL` | 0x12 | xf86 `radeon_driver.c` 1166 행 |
| `PIXCLKS_CNTL` | 0x2d | xf86 `legacy_crtc.c` 625 행 |

`PPLL_DIV_1`·`2` 는 뺀다(고정 이름 읽기 선례 없음, R2b 불사용).

**그룹 알고리즘**(Q10 B1·C2.3·C2.4 반영).  레지스터 k 마다 인터럽트를 막은 한 묶음:

```
s = splhigh()
  P = R32(0x08)
  if (P & 0x80)              { splx(s); 기록 busy(k); 끝 }          ← 인덱스 쓰기 없음
  W8(0x08, idx[k] & 0x3f)
  C = R32(0x08)
  if ((C & ~0xff) != (P & ~0xff)) 중단(k, P, 'upper')
  if ((C & 0xff) != (idx[k] & 0x3f)) 중단(k, P, 'low')
  V = R32(0x0c)
  D = R32(0x08)
  if (D != C)                 중단(k, P, 'after-data')
  W8(0x08, P & 0xff)
  E = R32(0x08)
  if (E != P)                 중단(k, P, 'restore')
splx(s)
```

- **중단(k, P, why)** = `W32(0x08, P)` → `A = R32(0x08)` → `splx(s)` → 줄 `pllabort k=<n> why=<w> p=<hex8> c=<hex8> d=<hex8> e=<hex8>
  a=<hex8>` → `stop reason=pll-index-disturbed` → 언매핑 → 끝.
  - `P` 는 인터럽트가 막힌 같은 묶음 안에서 읽은 값이라 소유자 변경을 덮지 않는다(Q10 C2.3 b·d — 낡은 시작값 되쓰기
    제거).
  - 32 비트 쓰기는 이 경로에만 있다.
  - 비교는 분리된 `if` 로(cc 2.7.2.1 `||` 결합 함정 방지 — 32 비트 변형은 미확인이지만 비용 0).
- 묶음 안에는 sleep·로그·다른 함수 호출(헬퍼 제외) 이 없다.  묶음 사이에 소유자가 인덱스를 바꾸면 다음 묶음의 `P` 가
  첫 `P` 와 달라진다 → 파서가 판정.
- `_splhigh`/`_splx` 는 미러 커널 심볼표에 있다.  적재 링크 가능성은 타깃 `nm -u` 게이트가 판정하고, 안 되면 계획 개정.
- **남는 위험**(명시):
  1. 소유자가 `idx|WR_EN` 저장과 DATA 쓰기 사이에서 선점된 뒤 우리 묶음이 돌면: `P & 0x80` 이면 쓰지 않고 끝.  단 WR_EN
     없이 이미 저장된 경우는 해당 없음.
  2. 바이트 레인이 무시되고 32 비트 되쓰기도 안 먹으면(`A != P`) `PLL_DIV_SEL` 이 바뀐 채 끝난다 — operator 는 **추가 실행
     전 재부팅**.
  3. xf86 `OUTPLL` 은 WR_EN 을 세운 채 두므로(xf86 `radeon_driver.c` 629 행), 마지막 PLL 접근이 쓰기였으면 첫 묶음에서
     busy 로 끝난다 — 안전하지만 실행 한 번을 쓴다.  R1 실측 `0x303` 은 WR_EN 0.
  4. 인덱스 레지스터 bit 10–31 휘발 비트나 예약 bit 6 되읽기 차이 → 첫 묶음 중단(거짓 실패 가능, 받아들임).

**줄**(값을 모은 뒤):
- `pllstart p0=<hex8>`
- `pll k=<n> idx=<hex2> name=<NAME> p=<hex8> c=<hex8> val=<hex8> d=<hex8> e=<hex8>` × 10
- `pllend groups=10`

### 2-5. 로그 문법·파서 `tools/r2a/parse_r2a.py`

`RDN-R2A <runid> <kind> ... seq=<k>`.

- R1 kind 는 R1 파서 함수를 import(`bridge` 는 `ctl3c=` 확장).
- 새 kind: `pllstart`, `pll`, `pllend`, `pllabort`, `stop reason=pll-index-busy`.
- 16 진은 `%08x` + `(unsigned int)`.

**하드웨어 게이트**:
1. R1 과 같은 사슬·문법·카드 1 장·매핑 판정 독립 재계산·생존.
2. 레지스터 50 개.
3. **안정 레지스터 R1 대조** — R1 로그의 35 개에서 휘발 `{GEN_INT_STATUS, RBBM_STATUS}` 를 빼고, `CLOCK_CNTL_INDEX` 는
   **bit 8–31 만** 비교한다.
   - 정의된 제어 비트가 다르면 FAIL.
   - 정의 안 된 비트만 다르면(`DAC_CNTL` bit 14·21·22, `CRTC_EXT_CNTL` bit 19·25·26·28·29) 판정 **"기록 + 재계획"**
     (FAIL 과 구분).
4. PLL:
   - `pll` 10 줄이 k 순서.
   - 모든 k 에서 `p` 의 bit 7 = 0.
   - `c` = `(p & ~0xff) | idx`, `d` = `c`, `e` = `p`.
   - **모든 `p` 가 `p0` 와 같다**(묶음 사이 소유자 활동 없음).
   - `pllabort` 가 있으면 FAIL.  단 `a = p` 인지로 "안전 중단" 을 구분해 적는다.
5. `p0` 의 bit 8–9 = R1 `CLOCK_CNTL_INDEX` bit 8–9.

**코드 자기검사**(하드웨어 증거가 아니라 probe 판정의 독립 재계산 — 이렇게 이름 붙인다): 게이트 4 의 비교는 probe 가
통과시킨 값이라 target 오컴파일이나 probe 결함에서만 실패한다.

**기록**(게이트 아님):
- `PPLL_CNTL` bit 1·4·5·16·17·18
- `VCLK_ECP_CNTL` 소스·`PIXCLK_*ALWAYS_ONb`
- refdiv·FB·POST(DIV_3)
- `HTOTAL_CNTL` bit 28
- 방해 클라이언트 0 여부
- `TV_DAC_CNTL`·`DISP_HW_DEBUG`
- `MEM_CNTL` bit 0·`MEM_TIMING_CNTL`
- `X_MPLL_REF_FB_DIV`·`MCLK_CNTL`·`SCLK_CNTL`
- 브리지 VGA 전달 비트

→ facts 파일 `build/r2a/r2a-facts-<runid>.txt`.  R2 계획 §9 "R2a 결과에 따라 개정" 항목을 표시한다.

**자체검사 합성 로그**:
- 정상
- 줄 누락
- 다른 runid
- `c` bit 9 변화
- 하위 바이트 불일치
- `d` ≠ `c`
- `e` ≠ `p`
- k=5 에서 `p` ≠ `p0`
- `pllabort`(안전·불안전)
- busy
- 정의 비트 차이(FAIL)
- 미정의 비트만 차이(재계획)
- `CLOCK_CNTL_INDEX` 하위 바이트만 차이(PASS)
- 휘발 차이(PASS)
- `ctl3c` 누락
- PLL 줄 순서

### 2-6. 호스트 검사 `tools/r2a/hostcheck.sh`

1–3. C89(`-Werror=implicit-function-declaration`)·`#import`·심볼(두 .m).  `_splhigh`·`_splx` 포함.

4. **소스 규칙**(주석 제거 뒤, 각 규칙에 변이):
   - `RDNR2aProbe.m`:
     - `volatile` 0 건
     - `*)` 포인터 캐스트 0 건
     - `long long` 0 건
   - `rdnMmioWrite8(` 호출 2 곳, 둘 다 한 함수(PLL 그룹) 안.  오프셋 인자는 `CLOCK_CNTL_INDEX` 이름 상수, 값 인자는
     `& 0x3f` 식 또는 `& 0xff` 식.
   - `rdnMmioWrite32(` 호출 1 곳(중단 함수), 값 인자는 그룹에서 읽은 `P` 변수.
   - `splhigh(` 과 `splx(` 가 짝을 이루고, 그 사이에 `IOSleep`·`IODelay`·`IOLog`·`sprintf` 없음.
   - `outb/outw/inb/inw` 0 건, `outl` 은 0xCF8 만.
   - VGA 포트 상수 0 건.
   - `IOMapPhysicalIntoIOTask` 길이 0x2000 만.
   - 형식의 폭 + `l` 0 건.
   - `RDNR2aMMIO.m`: 함수 셋만, `static`/`inline` 없음.
   - 두 컴파일 줄에 `-flto` 없음.
5. **목적 파일**(Q10 B2 반영):
   - **저장** = 메모리 목적지 쓰기 중 기준 레지스터가 `%esp`·`%ebp` 가 아닌 것.
     - `mov` 외 `or/and/xor/add/sub/inc/dec/xchg/stos/setcc` 도 포함.
     - **폭은 원천 레지스터 이름**(`%al/%bl/%cl/%dl` → 8, `%ax…` → 16, `%e..` → 32) 또는 즉치 저장의 접미사.
   - `RDNR2aMMIO.o` 를 `-O0` 과 `-O2` 두 번: Write8 = 8 비트 저장 1, Write32 = 32 비트 저장 1, Read32 = 저장 0.
   - `RDNR2aProbe.o` 는 **`-O0 -fno-inline` 에서만**: `out` 명령어는 `outl` 헬퍼 안뿐, 호출 재배치 수(`rdnMmioWrite8` 2,
     `rdnMmioWrite32` 1, `splhigh` = `splx` 짝), 헬퍼 밖 저장 0.
6. 적재 명령.
7. 레지스터·PLL 표 = 파서 표, 파서 자체검사.
8. 변이는 같은 실행에서 전부 FAIL.
9. 시뮬레이터(§2-7).
10. 타깃 스크립트 시험(§2-8).
11. `check_drift.py`(자기 변이 포함).

### 2-7. 시뮬레이터 `tools/r2a/sim_r2a.py`

- `RDNR2aProbe.m` 은 바꾸지 않고 32 비트로 컴파일.  `RDNR2aMMIO.m` 자리에는 `tools/r2a/sim/mmio_sim.c`, `splhigh`/`splx` 도
  시뮬레이터 구현(깊이 계수).
- **`IOMapPhysicalIntoIOTask` 는 `PROT_NONE` 매핑을 돌려준다** — 헬퍼를 거치지 않은 접근은 즉시 fault.
- 헬퍼 검사: base = 매핑 주소, 해제 뒤 접근 없음, `off < 0x2000`, 32 비트 접근은 `off % 4 == 0`.
- 모형: `CLOCK_CNTL_INDEX`(바이트 저장은 하위 바이트만), `CLOCK_CNTL_DATA` = 현재 인덱스의 PLL 값, PLL 표 64 개.
- 머리말에 "보여 줄 수 없는 것"(WR_EN 래치, 실제 바이트 레인, 읽기 부작용, cc 2.7.2.1 코드 생성) 을 적는다.

**세계**:
- 정상
- 바이트 레인 무시(첫 저장이 bit 8–9 를 지움 → 중단·`a = p`)
- 바이트 레인 무시 + 32 비트도 안 먹음(`a ≠ p`: 32 비트 쓰기 정확히 1 번, 재시도 없음, stop 줄, 언매핑)
- 재읽기 뒤·DATA 전 인덱스 변경(→ `after-data` 중단)
- 묶음 사이 소유자가 bit 8–9 변경(→ 다음 `p` ≠ `p0`, 파서 FAIL, 하드웨어는 `p` 로 복원)
- bit 10–31 만 변경
- 하위 바이트만 변경
- k=9 에서 교란
- 복원 저장 뒤 교란(`restore` 중단)
- 예약 bit 6 되읽기 1(k=0 중단)
- 시작 WR_EN 1(busy, 쓰기 0)
- 정적 스캔(인덱스 쓰기 0)
- 매핑·언매핑 실패
- 카드 없음·둘
- R1 세계 전부(회귀)

**위반**:
- `W8` 오프셋 ≠ 0x08, 또는 값에 bit 7
- `W32` 오프셋 ≠ 0x08, 또는 값 ≠ 같은 묶음의 P, 또는 중단 조건이 아닌데 호출
- 0x0c 또는 다른 오프셋 쓰기
- 인덱스 저장 뒤 재읽기 없이 DATA 읽기
- `splhigh` 밖에서 인덱스 저장
- 묶음 안 `IOSleep`/`IODelay`/`IOLog`
- 생존 창 안 sleep
- R1 PCI·매핑 위반 전부

**변이**(각각 실패해야):
- 인덱스 저장 32 비트
- 재읽기 검사 제거
- DATA 뒤 재읽기 제거
- 복원 제거
- 중단에서 `P` 대신 `C` 되쓰기
- 복원을 `W32(P)` 로
- 상위 비교를 bit 8–9 만
- DATA 먼저 읽기
- `splhigh` 제거
- 묶음 안 sleep
- WR_EN 검사 제거
- 정적 스캔 뒤 PLL 진행
- DATA 쓰기 추가
- 11 번째 인덱스

`& 0x3f` 제거는 표에서 등가 변이라 시뮬레이터 변이로 쓰지 않고 소스 규칙(4)이 맡는다.

### 2-8. 타깃 스크립트와 역어셈블 게이트

- `tools/r2a/target-build.sh`·`target-run.sh` = R1 셸 복사본 + 허용 hunk.
  - 이름 `RDNR2aProbe`·`radeonR2aEntry`·`RDN-R2A`, 선점 `/me/rdn-r2a-ran.d`(부모 생성).
  - 기준선: `Active Drivers` 에 `VGA` 있음·Matrox 없음.
  - build PASS 뒤 reloc 을 `/ndrv/openstep-radeon9250/build/r2a/<runid>/` 로 복사하고 sum 대조.
  - run 은 역어셈블 표지를 요구하고, `nohup` + `.done` 표지로 끝을 알린다.
  - `pack_probe.py` 는 R1 모듈 함수를 import 한 새 얇은 스크립트.
- **`tools/r2a/check_reloc.py <reloc> <sum> <blocks>`**(호스트):
  1. Mach-O(`0xfeedface`, cputype 7) 를 Python 으로 파싱: `__TEXT,__text` 바이트·주소·파일 오프셋, `LC_SYMTAB`.
     - `llvm-objdump --macho` 는 이 파일을 거절, 추출 + `objdump -D -b binary -m i386` 은 동작 — 이 세션에서
       `MDH10Disk_reloc` 으로 시험.
  2. **심볼 범위**: `(n_type & N_STAB) == 0`, `(n_type & N_TYPE) == N_SECT`, `n_sect` = `__text` 서수인 심볼만.  범위는 주소가
     **엄격히 큰** 다음 그런 심볼 또는 섹션 끝까지.  파일 오프셋 = `sect.offset + (n_value − sect.addr)`.
     - 같은 reloc 에 stab 이 수천 개(`N_SLINE` 994 등) 있다.
     - 섹션 끝 정렬 패딩(`lea 0x0(%esi,%eiz,1)`) 은 저장이 아니다.
  3. `_rdnMmioWrite8`/`_rdnMmioWrite32`/`_rdnMmioRead32` 에 §2-6 5 의 저장 규칙.  심볼이 없으면 FAIL.
  4. 증명 범위를 출력에 적는다: **타깃 컴파일 헬퍼의 저장 폭만**.  다른 저장 부재·호출 수·오프셋은 소스 규칙·호스트 목적
     파일·시뮬레이터 몫.  kl_ld 는 모듈 내부 PC 상대 호출에 재배치를 남기지 않으므로 호출 수는 여기서 세지 않는다.
     재배치는 주소 필드만 고치므로 저장 폭 판정은 재배치 전 바이트로 충분하다.
  5. PASS 면 `build/r2a/<runid>/R2ARELOC_PASS` 에 `<sum> <blocks>`.
  6. 자체검사(`as --32` 로 만든 바이트열 + 합성 Mach-O 머리):
     - 정상
     - write8 에 `movl`
     - 헬퍼 안에 `N_SLINE` 이 끼어 있음(PASS 여야)
     - 헬퍼 심볼 없음(FAIL)
     - 저장이 `%ebp` 기준(프레임 포인터 생략 코드면 숨는다 — 헬퍼 규칙은 "기준 레지스터 무관 메모리 쓰기 수" 로도 한 번 더
       세어 둘을 모두 출력)
- `tools/r2a/check_target_scripts.py` 새 사례:
  - 역어셈블 표지 없음·sum 불일치
  - 복사본 sum 불일치
  - `Active Drivers` 에 VGA 없음
  - 부모 디렉터리 없음(생성 뒤 진행)
  - 백그라운드 `.done` 표지

### 2-9. 실행 절차와 게이트

**순서**:
1. 호스트 `hostcheck.sh` PASS → `pack`.
2. 타깃 `target-build.sh`(nohup).
3. 호스트 `check_reloc.py`.
4. 타깃 `target-run.sh`(nohup, 약 2 s 뒤 한 번 확인).
5. 호스트 `parse_r2a.py <log> <runid> <build> <r1log> 789453017`.

- **게이트**: 파서 PASS, 언로드 성공, 역어셈블 PASS, 타깃 `nm -u` ⊆ 커널(`_splhigh`/`_splx` 포함).
- 결과는 `docs/R2A_RESULT.md`.
- `pllabort` 는 FAIL.  `a ≠ p` 면 추가 실행 전 재부팅(operator).

### 2-10. [구현] R2a 코드(2026-09-15) — 계획과 달라진 곳

- **probe**: `probe/RDNR2aProbe/` 에 `RDNR2aProbe.m`, `RDNR2aMMIO.{h,m}` 이 있다.
- **도구**: `tools/r2a/` 에 `parse_r2a.py`, `sim_r2a.py`·`sim/simworld2a.c`, `stores.py`, `check_r2a_src.py`, `check_reloc.py`,
  `pack_probe.py`, `target-build.sh`, `target-run.sh`, `check_drift.py`·`drift-allow.txt`, `check_target_r2a.py`, `hostcheck.sh` 가 있다.
- `tools/check-all.sh` 에 `hostcheck-r2a` 를 추가했고, 전체 PASS 다.

**계획 오류 — §2-6 5 "헬퍼 밖 저장 0" 은 성립하지 않는다**
- 호스트 `-O0` 목적 파일에서 측정했다. 비스택 저장은 다음 세 곳에 있다.
  - `pllGroup` 의 `r2aPllRead[k]` 필드
  - `scanPci` 의 `r2aBridges` 필드
  - `scanPci` 의 출력 포인터 매개변수
- 규칙을 약화하지 않고 **출처 추적**으로 정밀화했다(`check_r2a_src.py obj-stores`).
  - 허용: 기준 레지스터가 재배치된 정적 주소(`.bss`/`.data`)에서 왔거나, 소스가 포인터로 선언한 매개변수에서 온 경우.
  - 그 밖(MMIO base 인 `vm_address_t` 매개변수 포함)은 FAIL 이다.
  - 변이 "pllGroup 안 포인터 캐스트 저장" 이 이 규칙과 `probe-cast` 두 규칙에 모두 걸린다.

**시뮬레이터 위반 규칙 추가**
- §2-7 에 적힌 위반만으로는 세 변이를 잡을 수단이 없었다.
  - "복원을 W32 로"
  - "WR_EN 검사 제거"
  - "상위 비교를 bit 8–9 만"
- 그래서 넷을 추가했다.
  - `write32-no-abort`: 묶음의 인덱스 읽기가 모두 깨끗한데 32 비트 저장
  - `store-while-busy`: 첫 읽기 전, 또는 P 에 WR_EN 이 선 채로 저장
  - `group-after-stop`: busy·중단 뒤 다음 묶음
  - `data-from-wrong-index`: 교란된 인덱스에서 DATA 읽기
- 변이 "복원 제거" 는 E 가 C 로 읽혀 probe 가 스스로 중단한다. 그래서 `write32-no-abort` 로 잡힌다.

**남는 위험 4 보강**
- 예약 bit 6 이 1 로 되읽히는 세계에서 중단 경로의 `W32(P)` 는 읽은 P 를 bit 6 포함 그대로 쓴다(최종 인덱스 0x343).
- 읽은 값을 되쓰는 것이라 받아들인다. 실기에서 k=0 `why=low` 이고 `p` bit 6 = 1 이면 이 경우다.

**세계 설계**
- "재읽기 뒤·DATA 전 인덱스 변경" 은 모형에서 **DATA 읽기가 끝난 직후** 교란(`afterdata`)으로 둔다.
  - 인터럽트를 막은 묶음 안에서 두 읽기 사이 교란은 소유자 코드로는 생길 수 없다.
  - 판정 경로(D ≠ C → `after-data`)는 같다.
- R1 비교 게이트는 합성 로그가 아니라 **같은 세계에서 R1 probe(`tools/r1/sim`)가 쓴 로그**와 대조한다.
  - R1 세계에는 `mmio 8 <시작 인덱스>` 를 넣는다.

**`parse_r2a.py`**
- R1 파서는 수정하지 않고, 사본 모듈 인스턴스의 `parse`·`REGS` 만 바꿔 R1 게이트를 그대로 돌린다.
- 자체검사는 86 항목이다. 오프셋 60(레지스터 50 + PLL 10)과 사례·손상 로그를 합친 수다.
  - 실제 R1 로그(`build/r1/rdn-r1-789453017.log`)가 R1 게이트 PASS 이고 인덱스가 `0x303` 인지도 확인한다.
- **자체검사 오류 둘을 고쳤다**
  - 합성 R1 로그의 `CLOCK_CNTL_INDEX` 가 0 이었다. 그래서 정상 사례가 PLL_DIV_SEL 게이트에 걸렸고, "PLL_DIV_SEL 차이 → PASS" 사례의 기대가 틀렸다.
  - 줄을 번호 매기기 전에 빼면 syslog 누락(seq 틈)이 흉내내지지 않는다. 사례를 둘로 나눴다.

**`check_reloc.py`**
- 실제 cc 2.7.2.1 reloc(`MDH10Disk_reloc`)에서 검증했다.
  - stab 3010 개를 거른 코드 심볼 51 개의 범위가 모두 `push %ebp` 로 시작한다(범위 계산 확인).
  - 이 빌드는 프레임 포인터를 유지한다(미확인 4 의 정황, 헬퍼 규칙은 두 수를 다 찍는다).
- 자체검사는 12 사례다.

**타깃 스크립트**
- R1 복사본 대비 차이는 검토한 hunk 25 개뿐이다(`drift-allow.txt`, 목록 밖 차이·낡은 허용은 FAIL).
- 실측 셸 규칙을 적용했다.
  - `ps` 제거: nxlogd 는 호스트 `nx-logcatch.sh status` 로 확인한다.
  - `set --` 대신 awk 를 쓴다.
- `target-build.sh` 는 reloc 을 `build/r2a/<runid>/` 로 복사하고, 복사본 sum 대조와 `reloc.sum` 기록을 한다.
- `target-run.sh` 는 다음을 한다.
  - `R2ARELOC_PASS`(= reloc sum) 를 요구한다.
  - Active Drivers 에 VGA 가 있어야 한다.
  - 런 ID 를 안 뒤의 모든 종료에서 `run.done` 을 쓰고, 로그를 NFS 에 복사한다.
- 하니스: lint 7(규칙·변이), build 10, run 14 사례.

**수치**(이 세션 실행 출력)
- `sim_r2a.py`: 프로토타입 16, 세계 44(R2a 21 + R1 회귀 23), 변이 20.
- `check_r2a_src.py`: 규칙 18, 변이 24.

## 3. 구현 순서

1. **R1c**:
   1. `parse_bios.py` + 두 참고에서 따로 추출하는 생성기·단위 교차 자체검사
   2. `rdnbios.c` + `hostcheck.sh` + `sim_r1c.py`(strace)
   3. `target-r1c.sh` + 스크립트 시험
2. **R2a**:
   1. `parse_r2a.py` + 자체검사
   2. probe 두 파일 + 시뮬레이터 + 변이
   3. `check_reloc.py` + 자체검사
   4. 셸 복사·`check_drift.py`·스크립트 시험
3. `check-all.sh` 통합 → 전체 PASS.
4. **실기**: R1c `facts` → `read` 512 → `read` N → R2a.  재부팅 없음.

## 4. 미확인

1. 타깃 `/mach_kernel` 이 미러와 같은 이미지인지(R1 `nm -u` 일치는 정황).
2. 0xC0000 이 `vm_first_phys` 안인지, 셰도 페이지 PTE 설치의 칩셋 동작.
3. RV280 의 WR_EN 래치 방식.
4. cc 2.7.2.1 `-O` 가 프레임 포인터를 유지하는지(헬퍼 규칙은 둘 다 센다).
5. `_splhigh`/`_splx` 의 적재 링크 가능성(타깃 `nm -u`).
6. `CLOCK_CNTL_INDEX`·`DAC_CNTL`·`CRTC_EXT_CNTL` 미정의 비트의 휘발성.
7. 호스트 `strace` 존재, 타깃 `logger`·`cc` 경로(`facts`).
