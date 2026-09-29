# Q4 판정 — R6(최소 3D)·M(Mesa 통합)

질문 `Q4_prompt.md`, 회신 `Q4_reply.md` (gpt-5.6-sol, read-only, 2026-09-15).
회신의 링크 인용 111곳을 Python 으로 모두 뽑아 각 줄과 앞뒤 3 줄을 열어 확인했다(파일 없음 0,
엉뚱한 줄 0).  결론에 쓰이는 주장은 본문 범위를 더 읽었다.

## 내가 틀렸던 것 (먼저)

| 계획 서술 | 사실 | 근거 |
|---|---|---|
| "Mesa 훅 7 개" | **10 개**(`BoundTo`, `AppBuffer`, `ClearPixel` 누락) | `osmesa.c:52-117` 에서 `extern` 10 줄(Python·grep 확인) — codex 회신 전에 스스로 찾아 계획 수정, codex 도 같은 결론 |
| R6 "r200 swtcl 경로가 모델 — 정점을 창 좌표로" | 일반 swtcl 은 **NDC/클립 좌표**를 쓰고 하드웨어 뷰포트를 켠 채다(`r200_swtcl.c:94-97`, `r200_state_init.c:806-809`).  창 좌표 직접 선례는 FreeBSD **R200 깊이 지우기 사각형**이다 | `radeon_state.c:1140-1245` 본문 |
| R6 "`3D_DRAW_IMMD`" | R200 패킷은 `3D_DRAW_IMMD_2` | `radeon_state.c:1229` |
| R6 "FreeBSD `radeon_state.c`/`r300_cmdbuf.c` 의 **레지스터 화이트리스트** 검증기" | R200 검증은 상태 패킷 **ID 허용 목록** + 주소 필드 고치기이고, 주소 검사는 주소 하나가 FB/GART 구간 안인지 뿐이다.  `r300_cmdbuf.c` 의 레지스터 플래그 표는 **R300 마이크로코드 전용** | `radeon_state.c:238-266`("These packets don't contain memory offsets"), `radeon_drv.h:425-438`(`radeon_check_offset`), `radeon_state.c:2879` |
| R6 "텍스처(VRAM 업로드)" 를 버스 마스터와 무관한 것처럼 둠 | 참고의 텍스처 ioctl 은 DMA 버퍼(GART) → `CNTL_BITBLT_MULTI` 로 VRAM 에 복사 = **버스 마스터** | `radeon_state.c:1769, 1858-1866` |

## 판정표

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| 1 | 훅 10 개, 약한 심볼 아님, 매크로 없이 빌드한 stock `osmesa.o` 는 참조가 없어 링크된다 | `osmesa.c:52` 매크로·주석, 호출 지점 인용 전부 열람 | ✅ |
| 1b | `CopyDepth` 반환값을 호출자가 버린다 → 거절하면 새 깊이 버퍼가 초기화 안 된 채 | `osmesa.c:385` `(void) OpenStepMesaAccelCopyDepth(`, 주석 `:97-99` | ✅ 채택 — Radeon 구현은 거절하지 말고 복사하거나 깊이 공유를 아예 안 한다 |
| 1c | Matrox 빌드의 심볼 감사는 이름중립 훅 10 개 중 **4 개**만 검사 | `build-matrox-mesa.csh:175` 를 Python 정규식으로 셈 → 4 | ✅ 사실(Matrox 쪽 결함 — 이 프로젝트는 10 개 모두 감사). Matrox 수정은 이 작업 범위 밖이라 **보고만** |
| 2 | 소스 변경 없이 가능, 방법은 stock `libGL.a` 복사 + 훅 켠 `osmesa.o` + 10 개 구현 | `build-matrox-mesa.csh:73, 127-132` 열람 | ✅ |
| 2b | MGA 특유 제약(0x00RRGGBB, 32 px 피치, 16 비트 깊이만, import/mirror)은 구현 쪽에 있다 | `OpenStepMGAMesaBuffer.c:359, 610, 663, 1002, 1029, 1050`, `OpenStepMGAMesaHook.c:4513` 열람 | ✅ |
| 2c | RV280 24 비트 깊이를 Mesa 3.4.2 깊이 표현과 직접 공유 가능한지 미확인 | 소스 근거 없음 | ✅ 미확인으로 기록 — 첫 판은 16 비트 깊이 또는 깊이 없는 삼각형부터 |
| 3 | 공존: 설치 이름은 모두 Radeon 고유, 훅 10 개 이름은 **바꾸면 안 된다**, 한 실행 파일에 두 가속 라이브러리 링크 불가 | `build-accel-pkg.sh:9, 120-127, 158` 열람 | ✅ 채택 |
| 4 | 창 좌표 직접 경로 조건: TCL/정점셰이더 끔, 뷰포트 6 비트 끔, `VTX_XY_FMT|VTX_Z_FMT`, W 를 명시(선례 1.0), `SE_VTX_FMT_0 = Z0|W0|PK_RGBA`, `3D_DRAW_IMMD_2`(링 인라인, AOS·GART 정점 버퍼 불필요) | `r200_tcl.c:551-555`, `radeon_state.c:1140-1245` 본문(`0x3f800000` = 1.0 — Python) | ✅ 채택 |
| 4b | 일반 swtcl 은 `3D_LOAD_VBPNTR` + `3D_DRAW_VBUF_2`(GART 버퍼) | `r200_swtcl.c:287-290`, `r200_cmdbuf.c:208, 303` 열람 | ✅ |
| 4c | `RNDR_GEN_INDX_PRIM` 은 R200 에서 거절 | `radeon_state.c:363-366` | ✅ |
| 4d | 텍스처 정점의 W·원근 규약을 창 좌표로 넣는 방법은 미확인 | 근거 없음 | ✅ 미확인 — 텍스처 단계 전에 따로 확정 |
| 5 | Mesa 3.4.2 창 좌표: `win.z = Z/w·sz+tz`, `DepthMax=(1<<bits)-1`, `win.w = 1/w`; R200 DRI 는 `+0.125` 서브픽셀·Y 뒤집기·깊이 스케일 `1/0xffff`(16)·`1/0xffffff`(24) | `clip_funcs.h:94-97`, `context.c:219-221, 1183-1186`, `r200_state.c:1691-1710`, `r200_state_init.c:211-213` 열람 | ✅ 채택 — 뷰포트를 끄면 `+0.125` 도 사라지므로 **위상은 커버리지 시험으로 정한다**(Matrox 는 WARP 에서 −0.5 가 필요했다, `OpenStepMGAMesaWarp.c:73-76` — 장치별이라 옮기지 않음) |
| 6 | 우리 검증기 요건(스냅샷, 고정 최대 크기, 좁은 레지스터·비트 허용, `3D_DRAW_IMMD_2` 만, 길이·정점 수 교차 검사, **소유 할당 전체 범위** 검사, 배치 전체 검증 후 링 복사) | 참고의 64 KiB 스냅샷 `radeon_state.c:2856`, 주소 한 점 검사 `radeon_drv.h:425-438` | ✅ 채택 — 참고보다 강하게(참고는 전체 범위를 안 봄) |
| 7 | 참고 텍스처 업로드는 버스 마스터, CPU 로 VRAM 매핑에 직접 쓰는 방식은 Matrox 가 증명했으나 RV280 에서 미확인 | `radeon_state.c:1769-1866`, `OpenStepMGAMesaTexture.c:282` 열람 | ✅ 채택 — 첫 판 기본안은 CPU 복사(R4c 매핑 재사용), 캐시 일관성은 Matrox S4a 식 시험 |
| 8 | Matrox 선례가 요구한 것들(공유 표면, import·mirror, 깊이 복사, present 모드, 상태 게이트를 콜백 설치 **전에**, 소프트웨어 삼각형 보존, clear 체인, 텍스처 무효화, 계수기, SDL present 함수 셋, 직접 쓰기 규칙) | 인용 11 곳 열람(`OpenStepMGAMesaHook.c:3491, 3522, 4443, 4452, 4525, 4533, 4558`, `OpenStepMGAMesaBuffer.c:247, 629, 677, 745, 767`, `OpenStepMGAMesaTexture.c:348`, `README.md:20`) | ✅ 채택 — M 절에 항목으로 |

## 2차 자기검사

✅ 행 모두 이 세션에서 인용 줄을 열었다(111 곳 일괄 출력 파일 확인 + 본문 추가 열람:
`radeon_state.c:238-266, 1140-1245`, `radeon_drv.h:425-445`, `r200_tcl.c:551-560`).
수치 두 개(1.0f, 감사 4 개)는 Python 으로 재계산했다.
