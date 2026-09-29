# R0-4 — 참고 자료 라이선스표와 사용 규칙

작성 2026-09-15.  라이선스는 **각 파일 머리말이 정본**이다.  아래는 2026-09-15 에
머리말을 열어 확인한 것이다(`head -40 <file>`).

## 1. 표

| 자료 | 머리말의 저작권 | 조건 | 이 프로젝트에서 |
|---|---|---|---|
| NetBSD `radeonfb.c`, `radeonfbvar.h`, `radeonfb_bios.c` | (c) 2006 Itronix Inc. | BSD 3-clause: 소스·바이너리에 고지 유지, **Itronix 이름으로 파생물 보증·홍보 금지** | 모드셋·2D 의 **주 참고**. 코드 이식 시 고지 복제 |
| NetBSD `radeonfbreg.h` | 2000 ATI Technologies Inc. 외 | MIT 계열(고지·허가문 포함) | 레지스터 정의 — **사실**로 사용, 헤더 복사 시 고지 |
| NetBSD `pcireg.h`, `ppbreg.h` | 파일 머리말의 NetBSD 기여자 | BSD 계열 | PCI 레지스터 비트 정의 — **사실**로만 사용, 코드 복사 없음 |
| FreeBSD stable/9 `sys/dev/drm/radeon_cp.c` | 2000 Precision Insight, 2000 VA Linux, 2007 AMD | MIT 계열 | CP·링·GART 주 참고 |
| FreeBSD `radeon_microcode.h` | 2007 AMD | MIT 계열 | **드라이버에 컴파일된다**(`osrdn_cp_ucode.h`, R5) → `NOTICE` 의 "R200 CP microcode" 절에 전문(2026-09-24, 원문과 바이트 동일을 python 으로 확인) |
| FreeBSD `ati_pcigart.c`, `radeon_state.c` | 2000 VA Linux | MIT 계열 | GART·검증기 참고 |
| linux-firmware `radeon/R200_cp.bin` | 2007-2009 AMD (`WHENCE`) | MIT | 헤더판과 대조용 |
| xf86-video-ati 6.14.6 `legacy_crtc.c`, `radeon_driver.c` 등 | 2000 ATI Technologies 외 | MIT 계열 | 교차확인·VGA 복귀 참고 |
| Mesa 6.5.3 / Amber `r200_*` | 예: (C) The Weather Channel 2002 (`r200_swtcl.c`) | MIT 계열 | R6·M 참고 |
| Linux 3.10 UMS DRM | 파일별 | MIT 계열(DRM) | 교차확인만 |
| Configure.app `DisplayInspector.nib`(OPENSTEP 4.2, 실기 `/NextAdmin/Configure.app/English.lproj/`) | NeXT | 스톡 리소스 — 머리말 없음 | R3d 인스펙터 nib 의 **바탕**(파생 리소스, 코드 복사 없음).  고지는 `NOTICE` 의 "Configure inspector nib" 문단이 진다(2026-09-18, `docs/R3_MULTIMODE_PLAN.md` 25-10).  스톡 nib 자체는 커밋하지 않는다(`build/stocknib/`) |

BSD 2-Clause(이 프로젝트) 는 위 조건들과 양립한다 — 고지 유지 의무를 지키고,
Itronix 이름을 홍보에 쓰지 않으면 된다.

## 2. 사용 규칙

1. **사실과 코드를 구분한다.**  레지스터 오프셋·비트·순서·공식은 사실로 적고
   출처를 단다(`ANALYSIS.md`).  함수 본문·주석·표를 옮기면 **코드 이식**이다.
2. 코드를 옮기는 커밋은 같은 커밋에서 `NOTICE` 에 그 고지를 넣는다.
3. 이식한 파일 머리말에 원본 파일·리비전(예: NetBSD `radeonfb.c` 1.125)을 적는다.
4. 공개 전 점검: `NOTICE` 에 적힌 것과 트리에서 원본 고지를 가진 파일이 일치하는지.

## 3. 라이선스 방침 (2026-09-24, 사용자 결정)

- 이 프로젝트는 **matrox(`openstep-matrox-remade`)와 같은 BSD 2-Clause** 다.  `LICENSE` 는
  matrox 의 것과 한 글자도 다르지 않다(`diff` 로 확인).  소스 파일 머리에는 라이선스를 두지
  않고 최상위 `LICENSE` 로 정하는 것도 matrox 와 같다(두 프로젝트 모두 `mesa/` 파일 0 개).
- **Mesa 모듈(`libGL_radeon.a`)도 matrox 의 Mesa 모듈과 같은 조건**이다: 우리 코드는
  BSD 2-Clause, 라이브러리는 스톡 `libGL.a` 를 복사해 만들므로 Mesa 코드를 담고, 그것을
  싣는 패키지는 Mesa 의 `COPYRIGHT`·`COPYING` 을 바이트 그대로 싣는다(`NOTICE` 의 Mesa 절).
- 공개는 **모든 작업이 끝난 뒤**다.
