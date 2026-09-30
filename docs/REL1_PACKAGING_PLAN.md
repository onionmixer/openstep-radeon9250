# REL1 — radeon 첫 릴리스와, radeon 때문에 바뀐 모든 프로젝트의 패키징 계획 (계획, 2026-09-29, 코딩 전)

사용자 지시(2026-09-29): 저장소 이름은 `openstep-radeon9250`, 버전 이름은 Matrox 규칙을 따른다.  **Mesa 변경 때문에 Matrox 를 다시 컴파일해야 하면 Matrox 도 새 버전으로 릴리스한다.**  패키징 계획은 radeon 을 위해 수정·추가된 **모든 프로젝트**를 대상으로 한다.

틀은 Matrox v1.3 의 릴리스 절차 그대로다(`openstep-matrox-remade/release-packaging/PAYLOAD_MANIFEST.md`).  원칙도 같다: **Mesa 를 대체하지 않고 옆에 더한다**, 각 저장소의 공식 산출물은 **그 저장소만으로** 빌드된다, 다른 프로젝트의 데모는 Mesa Demos 의 **변종**으로만 싣는다.

## 1. 대상 프로젝트 — 전수

상위 저장소의 2026-09-15(radeon 착수) 이후 커밋을 경로별로 전수 집계했고, 독립 저장소 셋(`openstep-mesa342`·`openstep-sdl20`·`openstep-kernel-remade`)의 이력과 작업 트리도 봤다.  같은 기간 `openstep-mdh10`(128 파일)·`SMInputKor-remade`·`openstep-kernel-remade` 의 커밋은 radeon 과 무관하다(m68k·README·별도 분석).

| 프로젝트 | radeon 때문에 바뀐 것 | 근거 | 릴리스 |
|---|---|---|---|
| `openstep-radeon9250` | 새 프로젝트 | — | **v1.0 (첫 릴리스)** |
| `openstep-mesa342` | `osmesa.c` 형식 게이트 | `f2ab89f`(2026-09-26), **아직 push 안 됨**(origin 보다 1 커밋 앞) | 소스 push + 변종 `.info` 하나 추가(§3.C) |
| `openstep-matrox-remade` | 소스 변경 없음 — **다시 빌드하면 `f2ab89f` 가 들어간다** | `tools/build-matrox-mesa.csh` 64·73·134 가 이 `osmesa.c` 를 hook 매크로로 컴파일 | **v1.4** (사용자 지시) |
| `openstep-quake` (sdl2quake-openstep) | `build/build-glquake.sh` 에 `ACCEL=radeon` | `6a6c572`(2026-09-28); Matrox 기본 경로의 컴파일 옵션은 이전과 같음(diff 확인) | **v1.3 후보**(§3.D, 결정 필요) |
| `openstep-sdl20` (openstep-sdl2) | **없음** — 09-09 이후 커밋 0, 작업 트리 깨끗, 원격과 일치 | `git -C openstep-sdl20 status -sb` | 없음 — 의존 판(openstep.4)만 기록 |

`f2ab89f` 의 Matrox 영향 판단은 `openstep-matrox-remade/docs/MESA_F2AB89F_IMPACT.md`(ARGB 소비자는 변화 없음, RGB/BGR 문맥의 메모리 넘침이 고쳐짐).

## 2. 이름과 버전 — Matrox 규칙

Matrox: 태그 `v1.x`, 모든 부분이 한 버전, 자산 이름 `OpenStep-<제품>-<버전>-i486-<부분>.pkg.tar.gz`, Demos 변종은 **Mesa 포트의 버전을 유지하고** `+mga.N` 을 붙인다(파일 이름에서는 `-mga.N`, `pkg/make-release-assets.sh`).

| 산출물 | `.info` Title / Version | 자산 이름 |
|---|---|---|
| radeon 드라이버 | `OSRDNDisplay` / `1.0` | `OpenStep-Radeon9250-1.0-i486-Display.pkg.tar.gz` |
| radeon 가속 라이브러리 | `OSRDNMesaAccel` / `1.0` | `OpenStep-Radeon9250-1.0-i486-MesaAccel.pkg.tar.gz` |
| radeon 데모(Mesa Demos 변종) | `OpenStepMesa342DemosRDN` / `3.4.2-openstep.1+rdn.1` | `OpenStep-Mesa-3.4.2-openstep.1-rdn.1-i486-Demos.pkg.tar.gz` |
| Matrox 드라이버 | `OSMGADisplay` / `1.4` | `OpenStep-MGA-G450-1.4-i486-Display.pkg.tar.gz` |
| Matrox 가속 라이브러리 | `OSMGAMesaAccel` / `1.4` | `OpenStep-MGA-G450-1.4-i486-MesaAccel.pkg.tar.gz` |
| Matrox 데모 변종 | `OpenStepMesa342DemosMGA` / `3.4.2-openstep.1+mga.2` | `OpenStep-Mesa-3.4.2-openstep.1-mga.2-i486-Demos.pkg.tar.gz` |

제품 문자열 `Radeon9250` 은 Matrox 의 `MGA-G450` 자리다(칩 이름 대신 카드 이름 — 저장소 이름과 같게).  **결정 필요 D1.**

## 3. 프로젝트별 산출물

### A. `openstep-radeon9250` v1.0 — 패키지 둘 + 데모 변종 하나

**A1. `OSRDNDisplay.pkg`** — `DefaultLocation /`, 재배치 불가, 설치만 하고 활성화하지 않는다.

| 목적지 | 출처 |
|---|---|
| `/private/Drivers/i386/OSRDNDisplay.config/OSRDNDisplay_reloc` | 타깃 빌드 |
| `.../OSRDNDisplay`(인스펙터 실행 파일), `English.lproj/{Localizable.strings,DisplayInspector.nib/*}` | 타깃 빌드 |
| `.../Default.table`, `.../Instance0.table` | **릴리스 표**(§4 B1) — 개발 표가 아니다 |
| `.../Display.modes` | 원본 그대로(20 줄, 5×4 곱을 검증기가 확인) |
| `/usr/local/Documentation/OpenStep-Radeon9250/{LICENSE,NOTICE,INSTALL.md}` | 저장소 — `NOTICE` 는 **CP 마이크로코드 MIT 고지가 컴파일되어 들어가므로 필수** |

pre/post_install 로 기계의 인스턴스 표를 보존한다(Matrox 와 같은 이유).

**A2. `OSRDNMesaAccel.pkg`** — `DefaultLocation /LocalDeveloper`, 재배치 가능, 드라이버 패키지를 요구.

| 목적지 | 출처 |
|---|---|
| `Libraries/libGL_radeon.a` | `tools/mesa/target-build-mesa.sh` — stock `libGL.a` 사본에 hook `osmesa.o` 교체 + `osrdnaccel.o`.  **stock 옆에, 위가 아니라** |
| `Headers/OSRDNMesaPresent.h` 와 그것이 끌어오는 헤더 | 사설 prefix 에 데모를 빌드해 **필요한 헤더 집합을 측정으로** 정한다(Matrox 가 셋째 헤더를 그렇게 찾았다) |
| `Documentation/OpenStep-Radeon9250-Accel/Mesa-3.4.2/{COPYRIGHT,COPYING,README.Mesa}` | Mesa 포트의 `upstream/.../docs/*` 바이트 그대로 — PRERELEASE #6 을 닫는다.  Mesa 문서 경로와 겹치지 않게 **이 패키지 디렉터리 아래**(Matrox §2a) |
| `Documentation/OpenStep-Radeon9250-Accel/{PORT-NOTES.md,LICENSE,NOTICE}` | 새로 쓴다 / 저장소 |
| `Tools/OpenStepRDNAccel-Intel` | 아키텍처 표지(i386-only BOM) |

post_install 은 `ranlib`(재배치된 `.a` 의 색인).  **시험 전용 심볼 거절 목록**(Matrox 의 `build-accel-pkg.sh` 처럼): 러너 전용 knob·계측 심볼이 릴리스 아카이브에 정의돼 있으면 빌드를 거절한다 — 목록은 `mesa/` 를 전수해 정한다(`RDNMesaNullSend`·`RDNMesaPoison`·`RDNMesaTrace*` 후보; **결정 필요 D5**: 거절인지, 남기고 문서화인지).

**A3. `OpenStepMesa342DemosRDN.pkg`** — Mesa 빌더가 radeon 오버레이를 받아 만드는 **변종**.  Matrox 데모와 같은 규칙: 소스 하나 → 두 바이너리(`_sw` 는 radeon 코드 0 을 심볼로 확인), 소스·빌드 스크립트·README·NOTICE(SGI teapot 허락)·Mesa `COPYRIGHT` 동봉.  후보:

| 디렉터리 | 소스 | 바이너리 |
|---|---|---|
| `Examples/Mesa342/RDNTeapot` | `test/osrdn-mesa-teapot.c` | `rdnteapot_sw` / `rdnteapot_hybrid` — 파일로 쓴다 |
| `Examples/Mesa342/RDNSDLTeapot` | `test/osrdn-sdl-teapot.c` | SDL2 창 + present 계약 — SDL2 openstep.4 설치본 필요 |

**데모는 Matrox 무의존**(사용자 지시, 이전 결정) — `test/mgashim` 은 시험용이지 데모 경로가 아니다.  데모 빌드 스크립트는 `examples/` 에 새로 둔다(지금은 `tools/mesa/target-build-teapot.sh` 가 개발용).

### B. `openstep-matrox-remade` v1.4 — 다시 빌드, 소스 변경 없음

- `libGL_mga.a` 를 Mesa `f2ab89f` 로 다시 만든다 → `OSMGAMesaAccel` 1.4.
- 데모 변종 `+mga.2`: `_hybrid` 바이너리가 새 라이브러리로 다시 링크된다.
- 드라이버 패키지: **바이너리는 같고 버전 문자열만 1.4** — Matrox 의 "한 릴리스 = 한 버전" 규칙.  대안은 MesaAccel·Demos 만 1.4.  **결정 필요 D2.**
- `RELEASE_NOTES_v1.4.md`: 변경은 Mesa 계약층의 RGB/BGR 형식 게이트 하나(`docs/MESA_F2AB89F_IMPACT.md` 요약), 드라이버 동작 불변.
- **검증의 한계 — 실기에 G450 이 없다.**  빌드·패키지 검증(cmp·BOM·심볼)은 카드 없이 된다.  그러나 Matrox v1.3 이 한 "네 경로" 검증 중 **하드웨어 경로는 할 수 없다** — 드라이버 없는 경로만(`teapot_hybrid` 가 소프트웨어로 그려 `teapot_sw` 와 바이트 동일, v1.3 에서 확인된 성질).  `f2ab89f` 는 ARGB 경로를 바꾸지 않으므로(영향 판단 문서 §3) 하드웨어 경로의 위험은 낮지만 **실측이 아니라 원문 판단**이다.  릴리스 노트에 그대로 적는다.  **결정 필요 D3**: 이 한계로 릴리스할지, 카드를 다시 꽂고 검증할지.

### C. `openstep-mesa342` — 소스 push, 변종 `.info`, 바이너리 재릴리스 없음(예정)

- `f2ab89f` 를 push 한다 — radeon·Matrox 가속 라이브러리의 `osmesa.o` 가 이 커밋에서 나오므로 공개 소스에 있어야 한다.
- `packaging/openstep/OpenStepMesa342DemosRDN.{info,pre_install}` 추가(Matrox 변종의 선례, `build-split-packages.csh` 의 오버레이 분기).  두 변종이 같은 빌더에 들어가도 오버레이가 없으면 **plain Demos 가 이전과 같게** 나오는지 재확인.
- **stock 라이브러리는 다시 릴리스하지 않는다(예정)**: `f2ab89f` 의 변경은 전부 `#ifdef OPENSTEP_MESA_ACCEL_HOOK`(545–667) 안이고 `osmesa.c`·Mesa 헤더에 `assert`/`__LINE__` 이 없다 → stock `osmesa.o` 는 같아야 한다.  **추론이므로** 빌드 때 stock `libGL.a` 를 v3.4.2-openstep.1 자산과 `cmp` 해 확인한다.  다르면 재릴리스 여부를 다시 정한다.
- 새 Mesa 태그를 만들지(예: 소스 기준점) — **결정 필요 D4.**

### D. `openstep-quake` (sdl2quake-openstep) — v1.3 후보

- `sdl2quake` 패키지(1.2)는 `squake` 와 Matrox 링크 `glquake` 를 싣는다.  radeon 판 `glquake_radeon` 을 **같은 패키지에 더할지**, 별도 패키지로 둘지, 싣지 않고 빌드 스크립트만 공개할지 — **결정 필요 D6.**
- 싣는다면: `glquake`(Matrox)도 v1.4 라이브러리로 다시 링크(ARGB 라 동작 불변이지만 패키지가 한 Mesa 기준점을 갖게).
- **저장소 간 빌드 의존**: `ACCEL=radeon` 은 radeon 저장소의 `test/mgashim/` 을 include 한다.  공개된 radeon 저장소가 그 디렉터리를 계속 가져야 하고, Quake README 에 적는다.  게임 소스는 고치지 않는다(사용자 결정 — 8×8 밉 상한·screenshot 은 그대로).

### E. `openstep-sdl20` — 릴리스 없음

radeon 은 SDL2 의 기존 present 계약만 쓴다.  radeon README·INSTALL 과 데모 README 에 **SDL2 openstep.4 기준**으로 확인했다고 적는다.

## 4. 릴리스 전에 고쳐야 할 것 — 코드·표 (각각 별도 계획·codex 검토·실기)

| # | 무엇 | 근거 | 제안 |
|---|---|---|---|
| **B1** | 드라이버 표가 개발용이다: `Title "OSRDNDisplay R2b-0 record build"`, `Version "0.1"`, 스위치 다섯(`RDN R2B0 Record`·`RDN Engine Test`·`RDN VRAM Mmap`·`RDN CP Test`·`RDN 3D Test`)이 전부 `Yes` | `OSRDNDisplay/Default.table`·`Instance0.table`(둘이 같다) | 이름과 달리 **전부 기능 스위치**다(`OSRDNDisplay.m` 65–80: "off unless Yes").  특히 **`RDN R2B0 Record` 는 주 스위치** — 꺼지면 드라이버가 디스플레이를 소유한 채 모드를 설정하지 않고(`OSRDNDisplay.m:515-522` "owns the display but drives nothing"), 3D 창도 `"record"` 로 거절된다(1312).  릴리스 표: 제목·버전을 고치고, 스위치 기본값과 키 이름(첫 릴리스라 지금 바꾸면 호환 부담이 없다)은 **결정 필요 D7** |
| B2 | 3D 창 상한이 **128 MiB 가정**(상한 124 MiB)에서 나온다 — **VRAM 이 그보다 작은 보드에서는 3D 가 없다** | `osrdn_window.h:26-27`, `OSRDNDisplay.m:492`; 등록 전에 `CONFIG_MEMSIZE`·`CONFIG_APER_SIZE` 와 비교해 모자라면 `"reach"` 로 **거절**(`OSRDNDisplay.m:1372-1374`, `osrdn_engine.m:159-160`) | 안전 문제는 아니다(codex 가 잡은 내 오류, §10).  64 MiB 보드도 가속하려면 상한을 `CONFIG_MEMSIZE` 에서 만드는 드라이버 변경이 필요 — **결정 필요 D11**(고칠지, 한계로 적을지) |
| B3 | 지원 ID 가 `0x59601002` 하나 | `Default.table` `Auto Detect IDs` | 넓히지 않는다 — README·`.info` 에 "1002:5960 rev 1 에서만 확인" |
| B4 | 프로젝트 밖을 가리키는 인용 45 개 — 떼어낸 저장소에서 `check_citations` 가 판정 없이 죽는다 | PRERELEASE #4 | 형제 대상은 "건너뜀(이름과 수)" 을 말하고 프로젝트 안 대상이 없을 때만 FAIL — 검사기 규칙 정밀화 |
| B5 | CP 멈춤(~93,000 제출에 3 회, 복구됨, 한 번에 ~110 ms 끊김) | G5-6 §3 | 알려진 한계로 싣는다 vs 먼저 조사 — **결정 필요 D8** |
| B6 | present 모드의 소프트웨어 폴백은 뒤집혀 그려진다 | G5-1b §1-4 | 알려진 한계로 README 에 이미 적음 |

## 5. 공개 저장소 위생 (radeon)

- **이력 전수 검사**: 공개는 `git subtree split --prefix=openstep-radeon9250` — 현재 트리가 아니라 **split 브랜치의 blob 전수**(`git rev-list --objects` + `git cat-file --batch`)로 사설 주소·키·토큰 패턴을 본다(mdh10 선례).  걸리면 결정적 필터로 치환하고 다시 전수.
- 100 MiB 초과 blob 0 확인(`build/` 산출물 2.0 GB 는 무시 대상, 추적 파일 최대 1.5 MB).
- `.pyc` 60 개는 2026-09-29 추적 해제, `.gitignore` 에 `*.pyc`.  **이력에는 남는다** — split 에 그대로 실린다(내용 문제는 아님).
- `docs/review/` 의 codex 원문 로그 58 개(최대 1.5 MB, 로컬 절대 경로 포함) — Matrox 는 원문 로그를 공개하지 않았고 판정표(`Q*_verdict.md`)만 있다.  **결정 필요 D9**: 원문 로그를 추적 해제(판정표만 공개) vs 유지.  해제해도 이력에는 남으므로, 빼려면 split 필터가 필요하다.
- 로컬 절대 경로(`/mnt/USERS/...`)가 추적 파일 136 개(대부분 `build/` 러너와 원문 로그)에 있다 — 저장소 규약(IP·계정·토큰 금지)에 걸리지 않고 Matrox 도 5 개 공개했다.  그대로 둔다(D9 와 함께 재확인).
- `HANDOFF.md` 는 무시 대상(내부 전용) 확인됨.

## 6. 빌드 순서 (타깃, Matrox 절차를 따른다)

1. Mesa `f2ab89f` push(호스트), radeon·Matrox·Quake 의 커밋 고정.
2. radeon: 드라이버 릴리스 빌드(B1·B2 반영본) → `pkg/build-driver-pkg.sh` → `pkg/build-accel-pkg.sh` → 데모 오버레이 → Mesa 빌더로 `DemosRDN`.
3. Matrox: `tools/build-matrox-mesa.csh` 로 `libGL_mga.a` 재빌드 → 기존 `pkg/` 스크립트로 세 패키지(버전 1.4 / `+mga.2`).
4. Mesa stock `libGL.a` 를 openstep.1 자산과 `cmp`(§3.C).
5. 검증기: 패키지마다 `cmp`(원본과 바이트 대조), BOM 아키텍처(i386 있음·m68k 없음), 심볼 게이트(`_sw` 에 radeon/Matrox 심볼 0), **BOM 겹침 검사를 Matrox·radeon·Mesa 패키지 전부에 걸쳐**(두 가속 패키지·두 데모 변종이 같은 경로를 청구하지 않는지).
6. radeon 설치 리허설: `diff-against-installed` 로 개발 번들과 파일 단위 비교(읽기 전용) → 설치 → 재부팅(사용자) → teapot·GLQuake timedemo 로 릴리스 패키지 실측.
7. 호스트: `make-release-assets.sh` → SHA256SUMS → GitHub(split → blob 검사 → push → 태그 → release 자산 → 재다운로드 sha256).

**페이로드 파일을 고치면 해당 패키지를 다시 빌드한다**(Matrox 에서 두 번 낡은 문서가 실릴 뻔했다 — 검증기가 `cmp` 하는 이유).

## 7. 두 데모 변종의 충돌

Demos 변종은 "plain Demos 와 둘 중 하나만 설치" 다.  radeon 변종이 생기면 `DemosMGA` 와 `DemosRDN` 도 서로 배타가 된다(같은 plain Demos 내용을 둘 다 싣는다).  한 기계에는 카드가 하나라 실사용 충돌은 드물지만, 두 카드를 다 쓰는 사람이나 데모만 보려는 사람에게는 불편하다.  **결정 필요 D10**: 변종 둘(배타) / radeon 데모를 radeon 저장소의 별도 패키지로(Mesa 변종 아님) / 합친 변종 하나.

## 8. 결정 필요 목록

| # | 질문 | 제안 |
|---|---|---|
| D1 | 자산 제품 문자열 `Radeon9250` | 그대로 |
| D2 | Matrox v1.4 에 드라이버 패키지도 포함(바이너리 동일, 버전만) | 포함 — 한 릴리스 한 버전 |
| D3 | G450 없이 Matrox v1.4 를 낼지 | 한계를 노트에 적고 낸다, 또는 카드 재장착 |
| D4 | Mesa 새 태그 | 태그 없이 push, 릴리스 노트에 커밋 해시 |
| D5 | radeon 가속 아카이브의 시험 전용 knob | 전수 후 거절 목록 |
| D6 | Quake 에 `glquake_radeon` 을 실을지 | 같은 `sdl2quake` 패키지에 추가, v1.3 |
| D7 | radeon 릴리스 표의 기본값·키 이름 | 제목·버전 수정; 스위치 다섯은 **켬**(Record 는 주 스위치, 나머지는 가속 경로) — 키 이름 정리는 선택 |
| D11 | 128 MiB 미만 보드의 3D | 이번 판은 한계로 적는다(시험할 보드가 없다) |
| D8 | CP 멈춤을 먼저 조사할지 | 알려진 한계로 싣고 다음 판에서 |
| D9 | codex 원문 로그 공개 | 판정표만(Matrox 와 같게) |
| D10 | 두 데모 변종 | 변종 둘(배타), 설명을 `.info` 에 |

## 9. codex 에 묻는 것 (코딩 전, 한 주장씩)

1. "`f2ab89f` 의 `osmesa.c` 변경은 전부 `#ifdef OPENSTEP_MESA_ACCEL_HOOK` 안에 있어 stock Mesa 라이브러리(hook 매크로 없이 컴파일)의 `osmesa.o` 를 바꾸지 않는다."
2. "radeon 드라이버의 오프스크린 창 상한은 VRAM 을 128 MiB 로 가정하며 `CONFIG_MEMSIZE` 를 보지 않는다 — 64 MiB 보드에서 창이 VRAM 밖에 걸린다."

## 10. codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 1: 변경은 전부 hook 블록(545–667) 안이지만, 포함 헤더를 읽지 않고서는 "stock 오브젝트 동일" 을 판정할 수 없다 | 내가 전수: `osmesa.c` 는 변경 뒤쪽에서 `ASSERT` 를 쓴다(968·969·1017·1994) — `macros.h:40-43` 이 `DEBUG` 일 때만 `assert` 로 펼치고, `types.h` 의 `RENDER_START`/`FINISH` 의 `assert` 도 `#ifdef DEBUG` 안; `src/*.h`·`include/GL/*.h` 에 `__LINE__` 0; stock 플래그는 `-traditional-cpp -DOPENSTEP -O4`(`Make-config:841`, `DEBUG`·`-g` 없음) | ⚖️ codex 는 판정 보류, **내 검증으로 성립** — 그래도 빌드 때 `cmp`(§3.C) |
| 2: **거짓** — 창 등록 전에 `CONFIG_MEMSIZE`·`APER_SIZE` 를 상한과 비교해 거절한다 | `OSRDNDisplay.m:1370-1374`, `osrdn_engine.m:157-161` 을 열었다 — 맞다 | ✅ **채택 — 내 주장이 틀렸다**.  B2 를 안전 결함에서 기능 한계로 고쳤다 |
| (재검증 중 내가 찾은 것) `RDN R2B0 Record` 가 주 스위치 | `OSRDNDisplay.m:515-522`·`1312` | 내가 처음 적은 "Record 끔" 제안이 틀렸다 — D7 수정 |

## 11. 구현 계획 (2026-09-29, 사용자: "패키지 빌드 진행 — 모든 빌드·검증이 끝난 뒤 프로젝트별 커밋")

결정은 §8 의 제안대로 둔다(사용자가 달리 말하지 않았다).  D7 확정: **다섯 스위치 켬 = 모든 G 측정의 구성 그대로**.  근거를 다시 열었다: `RDN Engine Test` 는 부팅 때 256 KiB 별칭을 매핑할 뿐이고 엔진 조작은 ioctl 로만 돈다(`OSRDNDisplay.m` `engineAliasAt:`, `osrdn_engine.m:642`) — Matrox `Raster Test` 처럼 부팅마다 엔진을 돌리는 진단이 아니다.

### 11-1. radeon (`openstep-radeon9250`) — 새 파일

Matrox `pkg/` 를 **복사해 이름과 목록만** 바꾼다(검증된 절차를 새로 쓰지 않는다).

| 파일 | Matrox 원본 | 바뀌는 것 |
|---|---|---|
| `pkg/OSRDNDisplay.{info,pre_install,post_install}` | `OSMGADisplay.*` | 이름·설명(PCI `1002:5960`, 128 MiB 3D 조건), stash `OSRDNDisplay.instances` |
| `pkg/osrdn-identity-keys.awk` | `osmga-identity-keys.awk` | 이름만 — 다섯 키 규칙 그대로 |
| `pkg/build-driver-pkg.sh` | 같은 이름 | **번들 출처 = `target-build-r2b0.sh` 의 `/tmp/OSRDNDisplay-r2b0/OSRDNDisplay/OSRDNDisplay.config`**(설치 스크립트와 같은 것), 그 빌드의 `R2B0RELOC_PASS`(호스트 역어셈블 게이트) 요구; Instance0 은 번들의 것(릴리스 표 = 소스 표, §11-3); 문서 디렉터리 `OpenStep-Radeon9250` |
| `pkg/verify-driver-pkg.sh` | 같은 이름 | 개발 스위치 검사 대신 **다섯 스위치가 `Yes` 이고 `Title` 에 `R2b-0` 이 없다**; Class Names = `OSRDNDisplay`; NOTICE 에 `Advanced Micro Devices` |
| `pkg/OSRDNMesaAccel.{info,pre_install,post_install}` | `OSMGAMesaAccel.*` | `libGL_radeon.a` |
| `pkg/build-accel-pkg.sh`, `pkg/verify-accel-pkg.sh` | 같은 이름 | 멤버 `osrdnaccel.o`, hook 심볼 판정은 `OpenStepMesaAccelBuffer` 정의 여부, 헤더 = 데모가 설치 prefix 에서 빌드되는 집합(측정) |
| `pkg/build-demos-overlay.sh`, `pkg/build-demos-rdn-pkg.csh`, `pkg/verify-demos-rdn-pkg.sh` | `*-mga-*` | `RDNTeapot`(파일로 쓰는 teapot) + `RDNSDLTeapot`(SDL2 창).  `_sw` 게이트 = `OpenStepMesaAccelBuffer` 미정의(stock 은 `osrdn-mesa-nocount.c` 스텁을 링크하므로 OSRDN 이름 유무로는 못 가른다) |
| `pkg/collect-release-pkgs.sh`, `pkg/check-bom-overlap.sh`, `pkg/make-release-assets.sh`, `pkg/diff-against-installed.sh` | 같은 이름 | 이름; 겹침 검사 대상에 **Matrox 두 패키지도** 넣는다 |
| `examples/{build-teapot.csh,README_teapot.md,build-sdl-teapot.csh,README_sdlteapot.md}` | Matrox `examples/` | radeon 소스·라이브러리 이름, Matrox 무의존 |
| `release-packaging/{INSTALL.md,PORT-NOTES.md,PAYLOAD_MANIFEST.md}`, `RELEASE_NOTES_v1.0.md` | Matrox 같은 이름 | radeon 내용 |

### 11-2. radeon — 고치는 파일

- `OSRDNDisplay/Default.table`·`Instance0.table`: `Title` → `"OpenStep Radeon 9250 Display"`, `Version` → `"1.0"`.  나머지 키는 그대로(`target-build-r2b0.sh` 게이트 5 가 보는 것 — Display Mode 한 줄, Record `Yes`, Server Name — 불변).
- `OSRDNDisplay/English.lproj/Localizable.strings`: `"Radeon 9250 R2b-0 Record"` → `"OpenStep Radeon 9250 Display"`(Matrox 의 `"OpenStep MGA G450 Display"` 와 같은 모양, 40 자 예산 안).

### 11-3. Mesa (`openstep-mesa342`)

- `packaging/openstep/build-split-packages.csh`: 새 변수 `MESA_DEMO_VARIANT`(오버레이가 있을 때만 읽음, **없으면 `MGA`** — 지금의 Matrox 빌드와 같은 결과), 값 `MGA`·`RDN` 외에는 거절.  `.info`·`.pre_install`·`dname` 을 `OpenStepMesa342Demos$variant` 로.
- 새 `OpenStepMesa342DemosRDN.{info,pre_install}`(`3.4.2-openstep.1+rdn.1`), `OpenStepMesa342DemosMGA.info` 의 버전 `+mga.2`(Matrox v1.4 데모는 새 라이브러리로 다시 링크된다).
- 한 빌더 실행이 `dist` 를 지우므로 **변종은 한 번에 하나** — MGA 실행 → Matrox 수집 → RDN 실행 → radeon 수집.

### 11-4. Matrox (`openstep-matrox-remade`) v1.4

- `pkg/OSMGADisplay.info`·`OSMGAMesaAccel.info` 버전 1.4, `OSMGADisplay/Default.table` 의 `Version`(검증기가 `.info` 와 대조), `pkg/make-release-assets.sh` 의 변종 자산 이름 `-mga.2`, `RELEASE_NOTES_v1.4.md`, README 의 릴리스 줄.
- 타깃: `tools/build-matrox-driver.sh`(번들), `tools/build-matrox-mesa.csh`(라이브러리) → 기존 `pkg/` 절차 그대로.  하드웨어 검증 불가(D3) — `teapot_hybrid`(드라이버 없음) 와 `teapot_sw` 의 출력 바이트 동일만.

### 11-5. Quake (`openstep-quake`) v1.3

- `pkg/build-sdl2quake-pkg.sh` 에 `glquake_radeon` 추가, `pkg/sdl2quake.info` 1.3, README.  `glquake`(Matrox) 도 v1.4 라이브러리로 다시 링크.  빌드 스크립트 자체는 이미 커밋된 것(`6a6c572`).

### 11-6. 검증 (각 패키지)

타깃에서 빌드 → 각 검증기(`cmp`·BOM 아키텍처·심볼·버전 대조) → BOM 겹침(Mesa 라이브러리·헤더 + Matrox 둘 + radeon 둘 + 변종 하나씩) → stock `libGL.a` 를 openstep.1 자산의 것과 `cmp`(§3.C) → radeon `diff-against-installed`(설치된 개발 번들과, 읽기 전용).  **설치·재부팅 리허설은 사용자 결정**(재부팅은 사용자 몫).  커밋은 전부 끝난 뒤 프로젝트별로(사용자 지시).

## 12. codex 교차검토 판정 — 구현 계획 (2026-09-29, `gpt-6-astra`, 코딩 전, 한 주장씩)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| Mesa 빌더: 변종 이름은 세 대입 말고 87 행에도 나온다 | 87 행은 주석이다(`# variant produces OpenStepMesa342DemosMGA.pkg`) — codex 도 실행 줄은 셋뿐이라고 했다 | ⚖️ 동작 영향 없음; 주석도 함께 고친다 |
| Title·Version·패널 문자열만 바꾸면 드라이버·인스펙터·게이트 어느 것도 읽지 않는다 | `OSRDNDisplay.m` 363–396 의 표 읽기(여섯 RDN 키·Display Mode·Gray Levels)를 앞서 열었다; 설치기 3b 는 Server Name 만 | ✅ |
| 빌드 트리의 번들은 설치기가 복사하는 그것이지만, 설치기는 마커 둘 외에 **`.lastBuildTime` 삭제·표마다 Server Name 하나·멤버 비어 있지 않음·심볼릭 링크/쓰기 권한 거절**을 더 한다 | `target-install-r2b0.sh` 111–121·140·166·169–180·183–196 을 열었다 — 맞다 | ✅ 채택 — 패키지 빌더가 같은 검사를 한다 |
| (실행이 잡은 것) Mesa 빌더가 오버레이 안의 **Matrox 데모 이름**(`Teapot/teapot_sw` 등)을 검사한다 — 190–192·207 행 | 첫 RDN 빌드가 "overlay is missing teapot_sw" 로 멈췄다.  내가 codex 에 물은 주장은 "변종 이름(MGA)이 나오는 곳" 이었고, 이 검사는 MGA 라는 글자를 쓰지 않아 grep 에도 codex 에도 걸리지 않았다 | 수정: 변종마다 `tdir`/`tbin`(MGA = Teapot/teapot, RDN = RDNTeapot/rdnteapot).  수정안은 codex 에 한 주장으로 다시 물었다(TRUE — 오버레이 내용에 기대는 곳은 그 둘뿐, 둘 다 `if ("$dovl" != "")` 안) |

## 13. 결과 (2026-09-29, 타깃 빌드·검증 전부 PASS, 설치·재부팅은 하지 않음)

| 프로젝트 | 산출물 | 검증 | 이전 판·측정본과의 관계 |
|---|---|---|---|
| radeon 1.0 | 드라이버 stamp `844b835c` runid 790654423, 라이브러리 runid 790654424, 패키지 셋 | 호스트 게이트(역어셈블·B3·F) → `verify-driver`(판정 바이트 대조 포함)·`verify-accel`·`verify-demos-rdn`(teapot 쌍 실행: 가속 끔 = stock 바이트 동일, 가속 켬 6,400 삼각형 전부 카드) PASS | reloc 은 G5 측정 드라이버와 크기 같고 **스탬프 세 곳 12 바이트만** 다르다; 라이브러리 84 멤버가 GLQuake 측정 라이브러리와 **전부 같다** |
| Matrox 1.4 | 기존 `pkg/` 절차 그대로(11 단계 사슬) | 검증기 셋·BOM 겹침·수집 PASS; G450 없음 → `teapot_hybrid` 가 소프트웨어로 `teapot_sw` 와 바이트 동일 | 공개 v1.3 자산(체크섬 대조로 공개본임을 확인)과: 드라이버 파일 13 중 12 동일, `Default.table` 은 Version 줄만; 라이브러리 84 멤버 중 `osmesa.o`(+심볼표)만 |
| Mesa | 빌더 `MESA_DEMO_VARIANT`, `DemosRDN` 변종, `DemosMGA` +mga.2 | 두 변종 모두 빌드 | **stock `osmesa.o` 가 openstep.1 설치본과 바이트 동일**(§3.C 추론을 실측으로) → 라이브러리 재릴리스 없음 |
| Quake 1.3 | `squake`(v1.2 바이트), `glquake`(Matrox 1.4), `glquake_radeon` | 패키지 내용·버전·아키텍처·README 대조 | `glquake_radeon` 은 G5 측정 바이너리와 **엔진의 빌드 시각 문자열(`Exe:`) 5 바이트만** 다르다; `squake` 는 공개 v1.2 와 sum 동일 |

프로젝트 간 BOM 겹침: radeon 둘·Matrox 둘·Mesa 라이브러리·헤더·변종 하나씩(두 번: RDN, MGA) — 겹침 0.  음성 대조(가짜 목록의 중복)를 타깃 awk 로 잡는 것도 확인.

실행 중에 잡은 것(계획에서 못 본 것): Mesa 빌더의 Matrox 데모 이름 검사(§12 끝 행), 이 셸의 `grep` 교대·`awk -v` 부재·`set -e` 와 `grep -c`(기록된 함정 — 코딩 중에 대조해 고쳤다), 오버레이 안에 표지 파일을 두면 페이로드에 실린다(밖으로 옮김).

남은 것: 설치 리허설과 재부팅 뒤 릴리스 패키지로 한 번 실행(사용자 결정), 공개(subtree split·blob 검사·태그·자산), PRERELEASE #4(형제 인용).

## 14. 설치 리허설 (재부팅 한 번, 사용자 지시 2026-09-29: "재부팅해서 마지막 체크 → 그다음 commit·릴리스")

**보존(재부팅 전, 완료)**: `/tmp` 는 부팅 때 비워진다.  `build/rel1-preserve.sh` 가 패키지 7 개(`/tmp/pkgout` 의 다섯 + NFS 수집 tar 의 데모 변종 둘)·드라이버 빌드 트리·Quake 바이너리·데모 오버레이 둘을 `/usr/local/rel1/` 로, 되돌리기용으로 설치된 개발 번들(표 포함)·`System.config/Instance0.table`·설치된 Quake 바이너리·라이브러리와 receipt 목록을 `/usr/local/rel1/backup/` 로 옮겼다.  옛 tar 의 100 자 제한이 빌드 트리의 nib 한 개를 떨어뜨려 그 트리만 `cp -r` 로 다시 옮겼고, `build/rel1-preserve-check.sh` 가 원본과 사본을 파일마다 `cmp`(10 곳 PASS).

**배치(사용자 지시: `/me/packages/` 안쪽)**: `build/rel1-place.sh` — 새 이름은 그대로(`drivers/OSRDNDisplay/`, `mesa/OSRDNMesaAccel.pkg`, `mesa/OpenStepMesa342DemosRDN.pkg`), 새 판으로 바뀌는 셋(Matrox 1.4 둘·데모 MGA 변종·sdl2quake 1.3)은 옛 판을 `/me/packages/old/<같은 경로>` 로 옮긴 뒤 그 자리에(아무것도 지우지 않음), 파일마다 `cmp` PASS.

**설치(사용자, Installer.app — receipt 까지가 패키지 설치다)**: `/me/packages/drivers/OSRDNDisplay/OSRDNDisplay.pkg`(`/`), `/me/packages/mesa/OSRDNMesaAccel.pkg`(`/LocalDeveloper`), `/me/packages/quake/sdl2quake.pkg`(`/usr/local/quake`).  데모 변종은 설치하지 않는다(설치된 Matrox 변종과 배타; 데모는 패키징 때 이미 실행 검증).  Matrox 1.4 도 설치하지 않는다(카드 없음).

**설치 직후, 재부팅 전(Claude)**: receipt 셋; 설치된 번들 = 페이로드(표 제외)이고 `Instance0.table` 은 기계의 것(Location·스위치·Display Mode 가 백업과 같음)에 `Version` 만 1.0; `libGL_radeon.a` 가 판정 바이트와 같은 멤버이고 색인이 새로 만들어짐; Quake 바이너리 sum.

**재부팅 뒤(사용자: `/ndrv` 마운트 → gcdsd)**: 커널 로그의 빌드 스탬프 `844b835c`·CP·3D 창 등록; 설치된 prefix 로 teapot(오프스크린); `/usr/local/quake/glquake_radeon` `+map start` 300 프레임(화면, 사용자 gcdsd, 120 초 상한)과 수치 대조; Configure.app 이 "OpenStep Radeon 9250 Display" 1.0 을 보이는지(사용자 눈).

**되돌리기**: 화면이 안 나오면 `boot:` 에서 `config=Default`, 또는 telnet 으로 `/usr/local/rel1/backup/OSRDNDisplay.config` 를 `/private/Drivers/i386/` 에 되돌린다(번들 교체 전 `.prev` 로 옮긴다).

**이름 변경(사용자 제안, 2026-09-29)**: sdl2quake 1.3 은 Matrox 판을 `glquake_g450` 으로 설치한다 — 두 GL 바이너리가 각자 한 카드 전용이라 이름도 짝을 맞춘다.  빌드·시험 스크립트는 `glquake` 그대로(개발 트리 이름), 패키지 빌더만 설치 이름을 바꾼다.  보존 바이너리로 다시 묶어(`build/rel1-quake-repack.sh`) 세 바이너리 바이트 대조·`glquake` 부재·README 대조 PASS, `/me/packages/quake/` 교체(이전 것은 `/usr/local/rel1/sdl2quake.pkg.before-rename`), NFS 수집 tar·호스트 자산 갱신.  1.2 위에 덮어 설치하면 옛 `glquake` 가 남을 수 있어 README·`.info` 가 "옛 sdl2quake 를 먼저 지우라" 고 안내한다 — 리허설도 그 순서로(옛 패키지 삭제 → 설치).

## 15. 리허설 결과 (부팅 e88f23e4, 2026-09-29) — 릴리스를 막는 것 둘

**설치 직후(재부팅 전)**: receipt 셋, 번들 전 파일 = 페이로드, 기계의 `Instance0.table` 은 다섯 식별 키 밖이 바이트 동일하고 `Version` 0.1→1.0 만, `System.config` 불변, 라이브러리 오브젝트 83 개 = 판정본, 설치 경로 링크, Quake 세 바이너리 = 패키지 — `build/rel1-installed-check.sh` PASS.  `/usr/local/quake/glquake` 는 어느 receipt 도 갖지 않은 9 월 9 일 개발본(sum 02169, 공개 v1.2 와 다름)이다.

**재부팅 뒤**: 커널 로그에 `build=844b835c`, `key=yes`, 스위치 `3d=1`, 3D 창 등록(`mem=08000000 aper=08000000`).

**B7 — CP 가 스스로 기동하지 않는다(차단).**  설치된 스택 그대로의 hybrid teapot: `installs=0 leaves=7`, 삼각형 0 개가 카드로 — probe 가 가속 불가로 판정.  모든 측정 러너는 개발 도구 `rdnr5cp` 로 여섯 op(`record rec3d load map reset start`, `build/g3c/run_g3c.sh` 22 행)를 보내 CP 를 올렸고, 그 도구는 패키지에 없다.  같은 부팅에서 릴리스 빌드의 `rdnr5cp`(스탬프 844b835c)로 여섯 op 를 보내자(전부 `r=0`) teapot 6,400 삼각형 전부 카드, 설치된 `glquake_radeon`(시드 없이, 사용자 조건) `+map start` 300 프레임 월드 15.3 ms·위임 0·유실 0·judge_g50 PASS, CP 복구 0 — **막힌 것은 CP 기동 하나다.**

**B8 — 시드가 프로세스마다 1 에서 시작한다(좁지만 실제).**  커널은 직전 제출과 **같은** 시드만 거절한다(`osrdn_cp.m` 1220·3197·3737: `seed == c->lastSeed`).  `RDNMesaSeed` 가 없으면 라이브러리 시드는 1 부터(`OSRDNMesaTri.c` `triSeed++`) — 바로 앞 프로세스가 제출을 딱 한 번 했다면 다음 프로세스의 첫 제출이 `CP_WHY_SEED` 로 거절된다(라이브러리에는 EIO).  러너는 프로세스마다 시드를 줘서 가려져 있었다.  이번 부팅에서는 앞 프로세스가 여러 번 제출해 걸리지 않았다.

**고칠 방향(계획·codex 검토 전)**: B7 — 드라이버가 CP 를 스스로 올린다(부팅 때 모드 설정 뒤, 또는 첫 클라이언트 open 때; 여섯 op 가 각각 무엇을 하는지 먼저 읽는다).  B8 — 라이브러리가 `RDNMesaSeed` 없을 때 프로세스마다 다른 시작값을 쓴다.  둘 다 바이너리가 바뀌므로 드라이버·라이브러리·데모·`glquake_radeon`(정적 링크)까지 다시 빌드·포장·설치·재부팅한다.

## 16. B7·B8 수정 계획 (2026-09-29, 코딩 전)

### 사실 (원문·실측)

- op 는 `setIntValues:forParameter:`(`OSRDN_CP_PARAM`) → `osrdn_mode_cp`(모드 claim) → `osrdn_cp_run` 으로 들어온다.  **일반 사용자는 이 길을 못 쓴다**: 사용자 `me` 로 무해한 `tdump` 를 보내자 `IODeviceMaster` 가 `r=-705` = `IO_R_PRIVILEGE`(`driverkit/return.h` 20 행), 커널 로그에 op 줄 없음 — 그래서 **라이브러리만 고치는 길은 없다**.
- 상태 사슬: `LOAD`(NONE 에서)→`MAP`(LOADED)→`RESET`(MAPPED, 한 번)→`START`(MAPPED·리셋 뒤)→RUNNING.  `RECORD`·`REC3D` 는 레지스터를 `c->rec`·`c->r3` 로 읽을 뿐이고 둘 다 op 마다 0 으로 지워지며 로그에만 쓰인다 — 사슬의 전제가 아니다.  STOP 뒤의 LOAD 는 거절된다(부팅당 한 주기).
- 장치 open(`rdnDevOpen`)은 커널 안에서 돌고, 제출마다 열고 닫는 클라이언트도 있다(M2f).  close 는 이미 인스턴스 메서드로 CP op 를 부른다(`r7bCloseRetire` → `osrdn_mode_*`, G5-2 실측 retires=42).
- 커널의 시드 판정은 직전과 **같은** 값만 거절(`seed == c->lastSeed`).  라이브러리가 부를 수 있는 libc 는 `judge_m1b.py` 의 허용 목록 — `gettimeofday` 는 있고 `getpid` 는 없다.

### B7 설계 — 첫 클라이언트 open 때 드라이버가 CP 를 올린다

- `rdnDevOpen` 이 open 을 받아들인 뒤(`rdnR7bHeld = 1` 이후) **이번 부팅에서 아직 시도하지 않았고 CP 가 `CP_ST_NONE` 일 때만** 인스턴스 메서드 `r7bAutoStart` 를 부른다.
- `r7bAutoStart` 는 측정 러너와 **같은 여섯 op 를 같은 순서로**(`record rec3d load map reset start`, `build/g3c/run_g3c.sh` 22 행) `osrdn_mode_cp` 로 돌린다.  한 op 라도 `CP_RC_RAN` 이 아니면 거기서 멈춘다(러너가 그랬다).  로그는 op 줄 대신 요약 한 줄(`RDN-R5 autostart ... ops=… rc=… why=… state=…`).
- "시도함" 표지는 **claim 을 얻어 사슬을 실제로 돌렸을 때만** 세운다 — claim 이 바빠(`CP_RC_BUSY`) 첫 op 도 못 돌면 다음 open 에서 다시 시도한다.  사슬이 도중에 실패하면 이번 부팅에는 다시 하지 않는다(러너도 재시도하지 않았다; 라이브러리는 NOT_RUNNING 으로 소프트웨어).
- 키가 꺼져 있거나(`keyOn`·`key3d`) 모드가 안 쓰였으면 `osrdn_cp_run`·`osrdn_mode_cp` 가 스스로 거절한다 — 새 판정은 없다.
- 개발 도구로 이미 올린 경우(RUNNING)·멈춘 경우(STOPPED)에는 아무것도 하지 않는다.
- 부팅 경로에는 손대지 않는다: GL 을 안 쓰는 기계에서는 한 번도 돌지 않는다.

### B8 설계 — 시드 시작값

- `RDNMesaSeed` 가 **있으면 지금과 똑같다**.  없을 때만 시작값을 `gettimeofday` 의 초·마이크로초를 섞어 만들고 0 이면 1.  이전 프로세스의 마지막 시드와 같아질 확률은 32 비트 우연뿐이다.  새 libc 심볼 없음(허용 목록 불변).

### 검증

호스트: 드라이버 소스 규칙(자동 기동이 여섯 op 를 그 순서로, 표지 규칙), 라이브러리 `sim_*`·check-all.  타깃: 빌드 → 패키지 재생성·검증 → Installer 로 재설치(사용자) → 재부팅(사용자) → **개발 도구를 쓰지 않고** teapot·GLQuake, 그리고 "한 번만 제출하는 프로그램 뒤 다른 프로그램" 으로 B8 재현 시도.  드라이버가 바뀌므로 드라이버·라이브러리·데모 변종·`glquake_radeon`(정적 링크) 재빌드·재포장; Matrox 1.4 는 무관.

### codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전, 한 주장씩)

| codex 주장 | 내 검증 | 판정 → 설계 변경 |
|---|---|---|
| B7-1: 같은 처리 함수를 탄다(TRUE) — 그러나 "첫 op 가 BUSY 가 아니면 표지" 는 `RECORD` 가 순간의 FIFO/ACTIVE 로 거절돼도 부팅의 기회를 소모한다 | `cpRecord`(`osrdn_cp.m` 856 이하)의 두 거절을 열었다 | ✅ 채택 — **표지 없이 `state == CP_ST_NONE` 만으로**: LOAD 전 실패는 NONE 이라 다음 open 에 재시도, LOAD 뒤 실패는 NONE 이 아니라 재시도 없음; 로그 폭주를 막는 시도 상한 8 |
| B7-2: claim 은 op 마다라 사슬 전체는 원자적이 아니다(op 사이 끼어들기 가능), NONE 검사도 claim 밖 | `osrdn_mode.m` 1450·1474 를 열었다 | ⚖️ 사실 — 각 op 가 claim 안에서 자기 상태를 다시 검사해 거절할 뿐이고 root 도구 경로와 같은 성질; 결함 아님, 기록 |
| B7-3: `RECORD`·`REC3D` 는 모드 게이트를 건너뛰고(`osrdn_mode.m:1456`) `RECORD` 는 클럭 인덱스 바이트를 쓴다(`osrdn_cp.m:907`) — `key3d` 꺼짐·모드 미작성에서도 하드웨어에 닿는다 | 두 줄을 열었다 | ✅ 채택 — 자동 기동은 **`keyOn && key3d && modeWritten && snapshotValid`** 일 때만 |
| B8-1·3·4: 환경 변수가 있을 때 불변, 새 libc 심볼 없음, 1 을 전제한 곳 없음(TRUE); 헤더 주석은 낡는다 | `OSRDNMesaTri.c` 873–887, `judge_m1b.py` ALLOW 를 열었다 | ✅ — 헤더 주석도 고친다 |
| B8-2: 시작값이 `ULONG_MAX` 면 증가·랩으로 1 이 된다 | `OSRDNMesaTri.c` 884–886 | ✅ 채택 — 시작값을 `0x10000..0x3fffffff` 로 가둔다(한 프로세스가 10 억 번 제출하지 않는 한 랩 없음) |

## 17. B7·B8 구현과 재포장 (2026-09-29, 부팅 e88f23e4 에서, 재설치·재부팅 대기)

- **B8(라이브러리)**: `RDNMesaSeed` 가 없을 때 시작값 = `65536 + ((sec·1000003) ^ usec) % 1e9`(2^30 미만, python 확인).  첫 시도의 `0x3fffffff` 마스크는 `check_hook` m1d-tri-pure 가 "상수 주소" 로 잡았다 — 규칙을 느슨하게 하지 않고 10 진 나머지로.  **재현과 확인(같은 부팅, 개발 도구 없이, 시드 없이 두 번씩)**: 옛 라이브러리 `seed=1 submitted=1` → `seed=1 submitted=0 lastStatus=5`, 커널 `asubmit ... rc=1 why=13`; 새 라이브러리 `seed=241109399 submitted=1` → `seed=241079624 submitted=1`(`build/rel1/b8probe.c`·`b8run.sh`).  라이브러리 790662776: 바뀐 멤버는 `osrdnaccel.o` 하나, `judge_m1b` PASS.
- **B7(드라이버)**: `rdnDevOpen` 이 open 을 받아들인 뒤 `r7bAutoStart` — §16 판정대로 `CP_ST_NONE`·키·모드 확인 뒤 여섯 op, 첫 실패에서 멈춤, 시도 상한 8, 요약 한 줄 `RDN-R5 autostart`.  `check_r5_src` 에 규칙 `rel1-autostart` 와 변이 넷(순서·3D 키·실패 뒤 계속·open 호출 제거) 전부 잡힘.  드라이버 stamp e09f4f8b runid 790662775(reloc +772 바이트), 역어셈블 게이트 PASS.  **자동 기동 자체는 재부팅 뒤에만 볼 수 있다**(이번 부팅은 CP 가 이미 RUNNING).
- 인용: 라이브러리 두 번·드라이버 한 번 줄이 밀려 편집 전 사본(두 번째는 역적용으로 만든 중간 판)으로 `reaim_diff` + `reaim_bare` — 57+18, 23+8, 58+1 곳, 실패 0.
- 재포장(`build/rel1-repack-b78.sh`, NFS 크기 대조 먼저): 드라이버·가속·데모 변종 검증 PASS(데모 쌍 실행 포함), 프로젝트 간 BOM 겹침 PASS, 수집; `glquake_radeon` 을 새 라이브러리로 다시 링크해 sdl2quake 재포장.  `/me/packages` 교체(첫 후보판은 `/usr/local/rel1/superseded-rc1/`), 산출물 보존 `/usr/local/rel1/build-b78/`, 호스트 자산 갱신.

## 18. 두 번째 리허설 (부팅 01966cc5, 2026-09-29) — B7·B8 해결, B9 발견

개발 도구를 하나도 쓰지 않고, 설치된 패키지 그대로:

- **B7 해결**: 첫 클라이언트(hybrid teapot, root)의 open 에서 `RDN-R5 autostart boot=01966cc5 try=1 ran=6 rc=0 why=0 state=3` — 그 첫 실행이 6,400 삼각형 전부 카드.
- **B8 해결**: 설치된 헤더·라이브러리(`/LocalDeveloper`)만으로 빌드한 `b8probe` 를 시드 없이 세 번 연속 — 셋 다 `submitted=1 lastStatus=0`, 이번 부팅 `why=13` 0 건.
- 설치된 `glquake_radeon` `+map start` 300 프레임: 월드 15.3 ms·위임 0·유실 0·failed 0·CP 복구 0, judge_g50 PASS.

**B9 — 3D 장치 노드(차단, 결정 필요)**:
1. **노드를 아무도 만들지 않는다.**  `/dev/rdnvram0`(`c 38 0`)은 R4c 개발 때(9 월 16 일) 손으로 만든 것이고, 패키지는 만들지 않는다 — 새로 설치한 기계에는 노드가 없어 가속이 전혀 없다.  major 는 번들 표의 `"Character Major" = "38"` 로 고정이라(`R4C_VMAP_PLAN.md` 14 절) 설치 스크립트가 만들 수 있다.  (Matrox 1.3 도 같다 — `openstep-matrox-remade/docs/REMAINING_WORK.md` 505–506 "노드를 자동으로 만드는 것은 아직", 설치 안내에도 없음.)
2. **노드는 root 전용(0600)이다 — 의도된 보안 결정이었다.**  사용자 `me` 로 돌린 teapot 은 open 조차 못 해(커널 로그에 `RDN-R4 open` 없음) 소프트웨어로 그렸다.  R4c 가 0600 으로 둔 이유: OPENSTEP 커널 `smmap` 이 길이 ≥ 2^31 인 mmap 의 검증을 건너뛰어(E1, `R4C_VMAP_PLAN.md` 229 행) 노드를 열 수 있는 누구나 커널 패닉 또는 물리 `0xFFFFE000` 매핑에 닿는다 — 드라이버의 `d_mmap` 으로는 못 막는다.  "비 root 에게 열기 전 open 신원 게이트" 는 차단 요건으로 넘겨졌고(같은 문서 428 행) 구현되지 않았다.
→ 누가 카드를 쓸 수 있게 할지(root 만 / 한 그룹 / 모두)는 **사용자 결정**이다.  어느 쪽이든 설치 스크립트가 노드를 만들어야 한다.

## 19. B9 결정과 계획 (2026-09-29, 코딩 전)

**사용자 결정: C — 노드 0666, 모든 사용자가 카드를 쓴다.  Matrox 도 같게.**  대가는 문서에 적는다: 커널 `smmap` 결함(E1) 때문에 노드를 여는 로컬 사용자는 누구나 기계를 세울 수 있다.

### 사실

- `mknod` 는 `/usr/etc/mknod`(`/etc/mknod` 는 링크).  `/dev` 는 `private/dev` 로 가는 링크.
- radeon: 번들 표의 `"Character Major" = "38"` 로 major 고정, 노드 `/dev/rdnvram0` = `c 38 0`.
- Matrox: 표에 `"Character Major"` 가 **없다** → `addToCdevswFromDescription` 이 첫 빈 major(이 기계 1)를 준다 — 설치 스크립트가 미리 알 수 없다.  라이브러리는 `/dev/osmgavram` 을 열고 노드 major 와 CAPS 의 `CAP_MAJOR` 가 다르면 `STALE_NODE` 로 거절(`OpenStepMGAMesaProbe.c` 160–162).  자동 major 1 은 world-writable `/dev/pp0`(major 1)와 겹친다(R4C 14 절).
- 이 기계의 `/dev`: major 37 노드 없음, 38 은 `rdnvram0` 하나, 1 은 `pp0`·`osmgavram`·`osmgavramf`.  설치된 드라이버 표의 고정 major 는 15(EIDE)·41(Floppy)·38(우리).

### 설계

1. **Matrox major 고정 37**: `OSMGADisplay/Default.table`·`pkg/Instance0.release.table` 에 `"Character Major" = "37";`.
2. **업그레이드에도 닿게**: 설치 스크립트는 기계의 표를 보존하므로 식별 키 변환(awk)이 `"Character Major"` 를 여섯째 패키지 소유 키로 다룬다 — 없으면 덧붙이고, 있으면 패키지 값으로.  post_install 의 "다섯 키 밖은 불변" 검사도 여섯으로.  radeon 도 같게(값 38 은 이미 기계와 같다).
3. **노드 생성(두 post_install, 표 복원 뒤)**: `${prefix}/private/dev/<노드>` 를 지우고 `/usr/etc/mknod <노드> c <major> 0`, `chmod 666`; `ls -l` 로 `c`·major·minor·`crw-rw-rw-` 를 확인, 실패면 말하고 exit 1(번들은 이미 설치됨 — 가속만 없다는 것을 Installer 가 보이게).  major 는 스크립트 상수가 아니라 **설치된 Default.table 에서 읽는다**(표와 노드가 어긋날 수 없게).
4. 검증기: 두 드라이버 패키지 검증기가 post_install 의 노드 생성·0666 과 두 표의 `"Character Major"` 를 확인.  INSTALL(둘)·Matrox 릴리스 노트에 노드와 E1 위험.
5. 바뀌는 것: 두 드라이버 패키지(표·스크립트·문서) — 드라이버·라이브러리 바이너리는 불변.  Matrox 는 표만 바뀌므로 드라이버 패키지만 다시(가속·데모 패키지는 그대로 1.4).
6. 실기: radeon 재설치 → 재부팅 → **사용자 `me` 로** teapot·GLQuake·B8.  Matrox 는 카드가 없어 설치 스크립트가 노드와 표를 만드는 데까지(드라이버는 비활성이라 무해).

### codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전)

| codex 주장 | 내 검증 | 판정 → 설계 변경 |
|---|---|---|
| 새 설치에서는 post_install 이 `if (! -d "$stash") exit 0` 으로 곧장 끝나 표 복원 뒤의 노드 생성에 닿지 않는다 | 두 post_install 29 행을 열었다 — Matrox·radeon 똑같다 | ✅ 채택 — 노드 생성을 그 분기 **앞**(인자 확인 직후)으로 |
| major 는 "class' config table" 에서 읽힌다(driverkit IODevice.h 78 행), 인스턴스 표가 아니다 | 78–79 행을 열었다 | ⚖️ 채택 — `Default.table`(번들 표)과 인스턴스 표 **둘 다**에 키를 둔다; awk 여섯째 키는 업그레이드용으로 유지 |
| Matrox 는 `"VRAM Mmap" = "No"` 로 나가서 major 를 넣어도 장치가 등록되지 않는다; 등록 실패 경로도 있다 | 표 61·68 행, `.m` 4500 행 | ⚖️ 사실 — Matrox 의 "가속은 기본 꺼짐" 설계(VRAM 크기)는 유지; 노드는 만들고, 켜면 모든 사용자가 쓴다고 문서화 |
| 노드가 0666 이어도 드라이버가 준비되지 않으면 open 은 실패한다 | `OpenStepMGAMesaProbe.c` 107 | ⚖️ 사실, 의도대로(소프트웨어로 떨어짐) |

## 20. B9 구현 (2026-09-29, 부팅 01966cc5 에서, radeon 재설치·재부팅 대기)

- 두 post_install: 인자 확인 직후(첫 설치 `exit 0` **앞**) `${prefix}/private/dev/<노드>` 를 지우고 `/usr/etc/mknod <노드> c <major> 0`, `chmod 666`, `ls -l` 로 `crw-rw-rw- <major>, 0` 확인 — major 는 설치된 `Default.table` 의 `"Character Major"` 줄에서 읽는다.  두 awk 에 여섯째 키 `"Character Major"`, 불변식 egrep 도 여섯.  Matrox 표 둘에 `"Character Major" = "37";`(주석은 따로 줄 — post_install 이 그 줄의 숫자를 읽으므로).
- 실기 시험(설치 없이): 가짜 prefix 로 두 post_install 의 새 설치 경로 — `crw-rw-rw- 38, 0`·`crw-rw-rw- 37, 0` rc 0.  1.3 판 Matrox 인스턴스 표(키 없음)에 새 awk — `"Version" = "1.4"`·`"Character Major" = "37"` 덧붙음, 여섯 키 밖 76 줄 불변.  radeon 의 설치된 표는 awk 전후 바이트 동일.
- 검증기 둘에 노드 검사(mknod·666·첫 설치 exit 앞·두 표의 major) — 로그에서 여덟 항목 ok.  재생성 사슬(`build/rel1-repack-b9.sh`, NFS 크기 대조 먼저; `/tmp` 가 재부팅으로 비어 보존된 빌드 트리 사용): 두 드라이버 패키지 검증·프로젝트 간 BOM 겹침 PASS.
- Matrox 새 번들 대 공개 1.3: reloc·인스펙터 바이트 동일, 다른 것은 두 표(버전·major)·awk·INSTALL.md 뿐.  **Matrox 는 이 기계에 설치하지 않는다** — 주차된 Matrox 번들에 첫 설치 경로로 `Instance0.table` 이 다시 생겨 Configure 의 디스플레이 인스턴스 둘 문제를 되살릴 수 있다; 노드 생성과 업그레이드 키는 위의 두 시험까지.
- 문서: 두 INSTALL 에 노드·0666·E1 위험·`chmod 600` 으로 좁히는 법(재설치 때 다시), Matrox 릴리스 노트에 노드 절과 "37 등록은 G450 에서 부팅해 보지 못했다".

## 21. 세 번째 리허설 — 최종 점검 PASS (부팅 e87a9044, 2026-09-29)

재설치(Installer.app) → 재부팅 → 개발 도구 없이, **첫 클라이언트는 일반 사용자 `me`**:
- `/dev/rdnvram0` 은 재설치가 `crw-rw-rw- 38, 0` 으로 다시 만들었고 재부팅 뒤에도 그대로.
- `me` 의 hybrid teapot 이 부팅 뒤 첫 open — `RDN-R5 autostart boot=e87a9044 try=1 ran=6 rc=0 why=0 state=3`, 6,400 삼각형 전부 카드.
- `me` 로 설치된 헤더·라이브러리만으로 빌드한 `b8probe` 세 번 연속 전부 `submitted=1 lastStatus=0`, 이 부팅 `why=13` 0.
- `me` 로 설치된 `glquake_radeon` `+map start` 300 프레임: 월드 16.0 ms(부팅 직후 첫 실행), 위임 0·유실 0·failed 0, CP 복구 0, judge_g50 PASS(`build/rel1-final3-glquake-me.log`).

**B7·B8·B9 해결.**  릴리스 노트의 "What the release is" 를 최종 빌드(드라이버 e09f4f8b/790662775, 라이브러리 790662776)로 고쳤다.

## 22. 공개 직전 문구 수정 — "다섯 키" → "여섯 키" (2026-09-29)

B9 에서 식별 키가 여섯(`Character Major` 추가)이 됐는데, 페이로드 문서 셋이 "다섯" 으로 남아 있었다: radeon `INSTALL.md`("rewrites only the five keys", 목록도 다섯), 두 awk 의 머리 주석("FIVE KEYS")과 END 주석("All five are required for the driver to load" — `Character Major` 는 적재 필수가 아니다).  비페이로드 `PAYLOAD_MANIFEST.md`·`diff-against-installed.sh` 주석도 같이.
- 두 Display 패키지만 실기에서 다시 만들었다(`build/rel1-repack-6k.sh`, `build/rel1-6k.log`): 두 검증기·BOM 겹침 PASS, radeon reloc 은 여전히 790662775.
- 옛 패키지와 파일 단위 대조(python, 바깥 tar 와 안쪽 페이로드 전부): radeon 은 `INSTALL.md`·awk·BOM, Matrox 는 awk·BOM 만 다르고 바뀐 파일은 소스와 바이트 동일.  나머지 16 개는 바이트 동일.
- `/me/packages` 교체(`build/rel1-place4.sh`, 옛 것은 `/usr/local/rel1/superseded-rc3`).  SHA256SUMS 는 두 Display 줄만 바뀌었다.  리허설로 설치된 것과의 차이는 문서 한 개와 awk 주석뿐이라 재설치·재부팅은 하지 않았다.

## 23. 공개 (2026-09-29)

D9 = **판정표만**(사용자).  `docs/review/` 58 개 중 `Q*_verdict.md` 14 개만 공개한다 — 나머지 44 개(원문 로그·프롬프트·회신·`PLAN_en.md`)는 다른 추적 파일 어디서도 참조되지 않는다(참조는 전부 `_verdict`).
- **radeon**: 첫 공개라 이력 없이 단일 커밋 — 워크스페이스 `openstep-radeon9250` 트리에서 44 개를 뺀 트리로 `git commit-tree`(`publish/openstep-radeon9250` = `7a4d489`, 721 파일).  blob 전수 검사(경로: site.conf·gcds.cnf·HANDOFF·ref/·doc/·.i64·.img·원문 로그류, 내용: 사설 IP·개인 키 머리줄·토큰·메일) 676 blob 0 건.  `onionmixer/openstep-radeon9250` 생성, main·`v1.0` = `7a4d489`, 릴리스 자산 3 + SHA256SUMS.
- **Mesa 포트**: `f2ab89f`·`a8467f4` 를 origin main 으로 push(태그 없음, D4).
- **Matrox**: subtree split `6af5e34`(원격 `c5ac4a3` 에서 fast-forward), 2,820 blob 0 건, `v1.4` 릴리스.
- **Quake**: subtree split `9123d4f`(원격 `67f6240` 에서 fast-forward), 374 blob 0 건, `v1.3` 릴리스(`--target` split SHA, libre 1.0 자산은 1.2 공개본과 sha256 동일).
- 세 릴리스 모두 자산을 GitHub 에서 다시 받아 `sha256sum -c` 전부 성공, 받은 SHA256SUMS 는 로컬과 바이트 동일.
