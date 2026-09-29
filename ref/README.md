# ref/ — 참고 자료

`ref/upstream/` 은 커밋하지 않는다(`.gitignore`).  `sh tools/fetch-ref.sh` 로
다시 받는다 — 이미 있는 파일은 건너뛴다.  압축본은 `ref/upstream/unpacked/`
에 풀어 두고 쓴다(2026-09-15 확보).

**주 참고는 BSD 쪽이다.**  Linux·Xorg·Mesa 는 교차확인용이다.

| 경로 (`ref/upstream/…`) | 무엇 | 쓰는 곳 | 라이선스 |
|---|---|---|---|
| `netbsd/sys/dev/pci/radeonfb.c` 외 3 | NetBSD radeonfb (trunk, rev 1.125) — RV280 식별, PLL 표, CRTC, 팔레트, MMIO 직접 2D 엔진, 비POST 카드 처리 | **R1–R4 주 참고** | BSD 3-clause(Itronix) + ATI MIT(reg.h) |
| `netbsd/sys/dev/pci/pcireg.h`, `ppbreg.h` | NetBSD PCI 레지스터 정의(trunk) — 헤더 형, BAR 형 비트, PCI-PCI 브리지 창(64 비트 prefetch 상위 절반) | R1 probe 경로 검사의 비트 정의 | BSD 계열(파일 머리말) — **사실**로만 사용 |
| `freebsd-stable9/sys/dev/drm/` | FreeBSD 레거시 DRM(비-KMS) — CP 마이크로코드 적재, 링, **PCI GART(테이블을 VRAM 에 둘 수 있음)**, 스크래치 writeback, r200 명령 검증기 | **R5–R6 주 참고** | MIT |
| `linux-3.10/drivers/gpu/drm/…` | 같은 계열 Linux UMS DRM | FreeBSD 판 교차확인 | MIT |
| `linux-firmware/radeon/R200_cp.bin`, `WHENCE` | R200 CP 마이크로코드 바이너리 | 헤더판(`radeon_microcode.h`)과 대조 | MIT(AMD, WHENCE 기재) |
| `xf86-video-ati-6.14.6.tar.bz2` | 레거시 CRTC/PLL/출력(`legacy_crtc.c`, `legacy_output.c`), VGA 상태 저장·복원, `radeon_reg.h` | revertToVGAMode, 레지스터 이름 교차확인 | MIT |
| `MesaLib-6.5.3.tar.gz` | r200 DRI(DRI1 시대, `r200_swtcl.c`, `r200_tcl.c`, `radeon/server/`) | R6–M 단계 | MIT |
| `mesa-amber.tar.gz` | r200 최종판(Amber 브랜치) | 6.5.3 판 교차확인 | MIT |
| `xfree86-4.4-DRI.pdf` | XFree86 DRI 사용자 안내 | 역사 자료 | — |

라이선스는 파일 머리말이 정본이다.  **레지스터 사실을 읽는 것과 코드를
옮기는 것을 구분**하고, 옮긴 코드는 `NOTICE` 에 출처를 적는다.
