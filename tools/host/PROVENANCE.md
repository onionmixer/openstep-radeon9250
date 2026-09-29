# tools/host — 출처

실기 없이 커널 코드를 검사하는 부품.  2026-09-15 에 복사했다.

| 파일 | 원본 |
|---|---|
| `kernel_symbols.py` | `openstep-emu10k1/tools/kernel_symbols.py` (그 원본은 `openstep-mdh10/hosttest/`) — NeXT Mach-O `LC_SYMTAB` 파서 |
| `check_symbols.py` | `openstep-emu10k1/tools/check_symbols.py` — `nm -u` 결과를 커널 export 와 대조, `--prefix` 로 모듈 자신의 이름을 구분 |
| `hostshim/architecture/ARCH_INCLUDE.h` | `openstep-emu10k1/tools/hostshim/architecture/ARCH_INCLUDE.h` — 현대 cpp 용 `ARCH_INCLUDE` 대체 |

커널 이미지는 워크스페이스 `ref/openstep/ps2/mach_kernel`(i386) 을 쓴다.
`check_symbols.py` 의 기본 접두사는 `emu_` 이므로 **반드시 `--prefix` 를 준다**.
