# G4-6 — GLQuake 가 느린 이유와 멈춤 (기록, 2026-09-27)

## 1. 측정 (드라이버 4d2ee38a, 라이브러리 790470099 → 790513797, 1 분 이내 자가측정)

- `run-glquake-self.sh glquake_radeon 100 55`: 100 프레임 17.8–18.9 초(약 178 ms/프레임, 5.6 fps), 카드 삼각형 184,729, 삼각형 단위 소프트웨어 0 — 그러나 상태 전환 가운데 **카드 1,598 / 분류기 거절 2,845**.
- 거절 사유(진단 계수기: shim 의 `GateWhy`·`BuildWhy` 가 radeon 의 `why[]`·`texWhy[]` 를 내보내게 함, 포트 불변): TEXTURE 2,841 + RASTER 4; TEXTURE 2,841 건 **전부 MIN 필터 = 0x2702 `GL_NEAREST_MIPMAP_LINEAR`**.
- 원인: LibreQuake 의 `default.cfg` 가 `gl_texturemode gl_nearest_mipmap_linear` 를 설정하고, 포트의 `GL_KeepFilterDrawable` 은 Matrox 1.3 이 네 밉 모드를 다 받으므로 그대로 둔다.  radeon 은 G4-5 에서 두 혼합 모드를 기본 소프트웨어로 두었으므로 월드 표면이 Mesa 의 가장 느린 경로로 그려졌다.

## 2. 판단과 시도

- G4-5 는 M12-C 의 사전 기준(1/16)으로 혼합 모드를 막았으나, Matrox 의 **최종 판정은 같은 가수-선형 근사(f 오차 최대 1/8)를 "문서화된 근사로 개방"** 이었다(`M12_WARP_MIPMAP_PLAN.md` 10-1 판정 2); r200 DRI 도 네 모드를 카드로 보낸다.  우리 오차는 최대 0.086.  → 측정 마스크에 두 혼합 모드를 넣어 라이브러리 790513969 를 빌드하고 GLQuake 를 다시 돌렸다.
- **그 실행 도중(으로 보이는 시점에) OPENSTEP 머신이 멈췄다**: ping 무응답, telnet 접속 실패, 사용자 확인 "freeze".  NFS 에 측정 로그가 남지 않아 glquake 가 시작됐는지, 몇 프레임 갔는지 모른다.

## 3. 조치와 다음

- 소스의 기본값을 부팅 9 상태(레벨 선택 두 모드만)로 되돌렸다(`OSRDNMesaClass.c` `OSRDN_MIP_MEASURED`, HELD BACK 주석).  `sim_class`·`check_hook`·`check_compile` PASS.
- 재부팅(사용자) 뒤: 마운트 → 내 gcdsd → **아무것도 실행하기 전에** `/usr/adm/messages` 에서 멈춤 직전의 커널 줄(RDN-R5 wait/latch/recover, RDN-R7B submit)을 읽는다 — 멈춤이 CP 쪽인지(검증기를 통과한 스트림이 카드를 세웠는지), 전혀 다른 곳인지.
- 가설을 실기에 걸기 전에 오프라인에서 먼저: G4-5 장면 D 는 같은 두 모드로 18 사각형을 문제없이 그렸다 — GLQuake 와의 차이(텍스처 크기·레벨 수·원근 사각형·배치 크기)를 호스트에서 좁힌다(`kernel-crash-costs-the-disk`: 가설은 오프라인·유저랜드·decline 모드로 먼저).

## 4. 재부팅 뒤 로그 (2026-09-27, 부팅 f3398ebf 에서 읽음, `build/g46/messages-after-freeze.txt`)

- 14:26:18–20: radeon 노드가 열리고 닫히기를 반복(glquake 기동 중 탐침·CAPS), **14:26:20 의 open 은 닫히지 않았다** — present 모드로 fd 를 쥔 `glquake_radeon`.
- 14:26:22: EMU10K1 오디오 틱 한 줄(게임이 소리까지 켰다).
- 그 뒤 재부팅(14:36)까지 **한 줄도 없다**: `RDN-R5 wait/latch/recover` 가 없으므로 드라이버가 감지·복구하는 CP 대기 초과가 아니라 시작 약 2 초 뒤 **머신 전체가 굳었다**(로그를 쓸 틈이 없었다).
- 참조 대조: Linux r100/r200 명령 검증기도 텍스처 크기를 레벨 0..MAX_MIP_LEVEL 로 센다(`r100.c:1790`, `r100.c:2154`) — 우리 검증기(`cpR7TextureBytes`)와 같은 범위이고 오히려 우리가 보수적(행 32 B 반올림·폭 1 클램프).  "존재하지 않는 레벨을 읽는다" 는 참조로 뒷받침되지 않는다.

## 5. 다음 실험 계획 (코딩 전, codex 검토 대상)

G4-5 장면 D(혼합 두 모드, MAG NEAREST, 64² 가 아닌 128² 8 레벨, λ 1..2, 16 px 사각형 18 개)는 멀쩡했고 GLQuake(같은 모드 NEAREST_MIPMAP_LINEAR, MAG LINEAR, 월드 텍스처 수백 개의 체인, 원근, 큰 배치)는 2 초 만에 굳었다.  차이를 한 번에 하나씩 더하는 사다리를 `ghostprobe_v20` 한 프로세스 안에서, **위험한 단계 직전마다 breadcrumb**(Matrox W10 의 `tools/nxbreadcrumb.c` 규칙: NFS 파일 fd 하나를 열어 두고 레코드마다 write + fsync — 레코드마다 open/close 하면 마지막 하나만 남는다)를 남기며 오른다.  각 단계 = 한 사각형(또는 한 배치) + `glFinish`.

| 단계 | 더하는 것 |
|---|---|
| S1 | NEAREST_MIPMAP_LINEAR, MAG NEAREST, 64² 7 레벨, λ = 0…M + 2(마지막 레벨을 넘는 λ — 장면 D 는 λ ≤ 2 만 봤다) |
| S2 | 같은 것에 MAG LINEAR(GLQuake 의 조합; 카드 필드는 MIN `LINEAR_MIP_NEAREST` + MAG LINEAR) |
| S3 | 비정사각 체인(64×32, 128×16 — 한 축이 먼저 1 에 닿는다) |
| S4 | LINEAR_MIPMAP_LINEAR |
| S5 | 원근(사다리꼴) 사각형 — 한 삼각형 안에서 λ 가 0 에서 M 너머까지 |
| S6 | 체인 텍스처 200 개를 올리고(아레나 부하) 한 배치에 여러 텍스처(세그먼트) |

각 단계 앞 breadcrumb `S<n> begin`, 뒤 `S<n> ok` + 계수기.  멈추면 마지막 `begin` 이 원인 단계다.  실행은 내 gcdsd(오프스크린), 1 분 이내; 라이브러리는 `RDNMesaMip=all` 일 때만 혼합 모드를 받으므로(소스 기본은 되돌려 둠) 탐침만 그 손잡이를 켠다.  **이 실험은 머신을 다시 굳힐 수 있다**(재부팅·fsck) — 사용자 확인 뒤에 돌린다.

## 6. codex 검토 판정 (2026-09-27, 한 호출)과 수정한 계획

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 사다리가 **present 경로**를 빼먹는다(GLQuake 는 present 모드로 fd 를 쥐었다; 사다리는 오프스크린) | 로그 14:26:20 의 닫히지 않은 open 이 그것 | ⚖️부분채택 — 단, 같은 present 경로로 GLQuake 100 프레임이 이 세션에 두 번 멀쩡했다(라이브러리 790470099·790513797, 밉 혼합 모드만 거절); 바뀐 것은 마스크 하나 |
| 256·512 텍스처, RGB 업로드, 깊이·알파, 그리기 사이 업로드, 제출 크기도 안 갈린다; S6 은 여러 변수를 한꺼번에 더한다; S1 도 128²/8 → 64²/7 로 둘을 바꾼다 | 계획 §5 원문 | ✅채택 |
| breadcrumb 귀속은 `glFinish` 가 **카드 완료까지 기다릴 때만** 성립 | `cpR6Submit` 가 W_RPTR 와 W_IDLE(재시도 16)을 기다린 뒤 돌아온다 — 제출 하나가 곧 카드 완료 | ✅사실 확인 — 귀속 성립 |
| 먼저 **카드에 안 보내는** 실험으로 좁혀라 | 타당 | ✅채택 |

**새로 보이는 차이(내 분석)**: 멈춘 실행은 월드 텍스처 수백 개가 **처음으로 아레나에 올라가 카드가 읽은** 실행이다(그 전엔 월드 상태가 전부 거절돼 올라간 적이 없다).  버스를 잡아 CPU 의 MMIO 읽기까지 멈추게 하는 전형은 잘못된 주소 읽기인데, 부팅 로그상 VRAM 128 MiB·창 0x400000–0x7c00000·아레나 끝 ≈ 44 MiB 로 범위 문제는 보이지 않는다.

**수정한 순서**:
1. **E0 — 카드 없는 GLQuake**(`RDNMesaMip=all RDNMesaNullSend=1`): 분류·체인 상주(CPU 가 VRAM 창에 쓰는 업로드)는 전부 일어나고 제출만 안 한다.  멈추면 CPU 쪽(업로드), 안 멈추면 카드 실행 쪽.  shim 통계로 업로드 수·체인 수를 얻는다.  1 분, 사용자 gcdsd(창이 필요).
2. E0 가 멀쩡하면 사다리를 **한 변수씩**(128²/8 에서 λ 확장만 → MAG LINEAR → 256·512 → RGB → 비정사각 → 원근 → 텍스처 수·아레나 끝 쪽 오프셋 → 세그먼트) 오프스크린 + breadcrumb 로.  present 경로는 맨 끝.

## 7. 실측 (2026-09-27, 부팅 f3398ebf, 라이브러리 790514875, `RDNMesaMip=all` 은 시험에서만)

- **E0 — 카드 없는 GLQuake**(`RDNMesaNullSend=1`, 110 초): 상태 24,277 수락 / 4 거절, 텍스처 510 개(전부 체인) VRAM 업로드, 카드 제출 0 — 머신 정상.  **CPU 쪽 업로드는 무죄**; 멈춤은 카드 실행 쪽.  (첫 시도는 재부팅 뒤 CP 를 안 올려 무효였다 — CP 기동 여섯 단계 뒤 재실행.)
- **사다리 S1–S13**(`ghostprobe_v20`, breadcrumb `build/g46/ladder.crumbs`·`ladder2.crumbs`): 13 단계 전부 `ok`, 머신 정상.  혼합 두 모드·마지막 레벨 너머 λ·MAG LINEAR·256²/512²·RGB·비정사각·원근·체인 텍스처 640 개·세그먼트 62·업로드 교차·깊이·라이트맵 2 패스 — **어느 것도 멈춤을 재현하지 않았다.**
- 곁에서 드러난 것 셋:
  1. **첫 카드 clear 의 CP 대기 초과(복구됨)**: 사다리 첫 실행의 첫 glClear 에서 `RDN-G3 clear rc=8`(RECOVERED) — 직전이 E0(GLQuake, present 경로 사용)였다.  드라이버가 리셋으로 살렸다.
  2. **아레나 블록 표 512 가 찬다**: S13 에서 업로드가 정확히 512 에서 멈추고 삼각형 548 개가 소프트웨어로 — GLQuake 의 텍스처 수(510)가 이 상한에 걸쳐 있다(`OSRDN_TEXARENA_BLOCKS`).
  3. **증거 손실**: 제출마다 `RDN-R4 open/close` 두 줄이 4 KB 메시지 버퍼를 넘쳐 S13 무렵 줄이 잘렸다(실패 한 건의 커널 기록이 없다).  **(G5-4 8c: 커널에서 이 줄을 knob 뒤로 숨기는 안은 M2f 가 측정으로 되돌렸다 — 두 무리로 갈라진 시간.  넘침은 fd 를 쥐지 않는 클라이언트의 것이다: GLQuake 는 present 모드에서 fd 를 쥐고(`osrdn_tri_hold_set`), 진단 실행은 `RDNMesaHold=1` 로 쥔다.)**
- **남은 차이(사다리 밖)**: 실제 GLQuake 의 present 경로(SDL 창·fd 유지)와 **동시 오디오 DMA**(EMU10K1 — 멈춘 실행은 소리를 켠 2 초 뒤였다), 그리고 실제 기하 규모.  다음 후보는 `-nosound` 로 GLQuake(`RDNMesaMip=all`) — 머신을 다시 굳힐 수 있다.
- **E1 — 소리 끈 GLQuake**(`RDNMesaMip=all ... -nosound`, 22:28:47 시작): **다시 머신 정지**(ping 무응답).  오디오 DMA 가설 배제.  같은 라이브러리에서 혼합 모드를 거절하면 GLQuake 가 정상(두 번), 카드로 보내면 두 번 다 정지, 오프스크린 탐침 13 단계는 정상 — 남은 것은 실제 GLQuake 스트림에만 있는 것(present 경로·실제 월드 기하·텍스처 조합·블록 표 512 포화).
- 다음: 라이브러리에 **제출 직전 스트림 요약을 NFS 에 fsync 로 남기는 모드**(텍스처 크기·레벨·필터·오프셋·워드 수)를 넣어 GLQuake 안에서 멈춘 제출을 잡고, 그 스트림을 오프스크린 탐침으로 재생해 좁힌다.  그때까지 기본 라이브러리(790514875)는 혼합 모드를 소프트웨어로 둔다.

## 8. 제출 기록으로 잡은 스트림 (2026-09-27, 라이브러리 790517229, `RDNMesaTrace`)

- 실행: `RDNMesaMip=all RDNMesaTrace=… RDNMesaTraceLast=… glquake_radeon -nosound`(22:55:11) — **세 번째 머신 정지**.  기록은 살았다: 제출 1,217 개의 요약(`build/g46/trace.txt`), 마지막 스트림(`build/g46/trace-last.bin`, 4,067 워드 — 파일 끝 한 워드는 앞 스트림의 잔여; 다음엔 길이를 같이 적는다).
- **혼합 모드 첫 제출은 781 번째**이고 그 뒤 436 제출이 멀쩡했다 — "혼합 모드가 카드에 가면" 이 아니라 특정 조합이다.  멈춘 스트림의 세그먼트 전환(혼합 밉 ↔ 단일 레벨 LINEAR, 5 레벨 ↔ 4 레벨)은 모두 앞선 성공 스트림에 수십 번씩 있었다.
- 멈춘 스트림은 오라클 판정 OK, 정점 NaN/Inf 없음, 좌표·w·텍스처 좌표 정상 범위.
- **사다리가 안 본 차이**: GLQuake 의 체인은 **8×8 에서 끊긴다** — 128² 5 레벨(`TXFILTER 0x0004000c` = MAX_MIP_LEVEL 4, TXFORMAT 은 128², log2 7), 64² 4 레벨, 32² 3 레벨.  `GL_TEXTURE_MAX_LEVEL` 로 레벨을 자르는 것은 LibreQuake 가 아니라 **우리 OPENSTEP 포트**다(`openstep-quake/port/openstep/gl_vidsdl.c` 의 `GL_FilterAudit`, Matrox M12 §8 에서 온 "8×8 까지" 캡 — 2026-09-27 재확인으로 정정); Mesa 는 그것을 완결로 본다.  사다리의 텍스처는 전부 1×1 까지 온전한 체인이었다.  즉 "MAX_MIP_LEVEL 이 크기가 뜻하는 레벨 수보다 작은 텍스처를 혼합(삼선형)으로 샘플" 이 미검증 — 첫 번째 용의자.  (Matrox 도 8×8 까지로 체인을 잘랐지만 그건 Matrox 칩의 제약이었다.)
- 다음(재부팅 뒤): 사다리 S14 = 128² 체인을 5 레벨로 잘라(MAX_LEVEL 4) NEAREST_MIPMAP_LINEAR, λ 0–9, breadcrumb.  멈추면 원인 확정 → 라이브러리는 **혼합 모드일 때 잘린 체인을 소프트웨어로**(또는 1×1 까지 채워 올리기)를 참조(r200 DRI 가 잘린 체인을 어떻게 보내는지)와 함께 설계.

## 9. 참고 비교 (2026-09-27, 머신 정지 중 오프라인) — BSD·Linux DRM·r200 DRI

| 질문 | 참고가 하는 일 | 근거(연 줄) | 우리 |
|---|---|---|---|
| 잘린 체인(MAX_MIP_LEVEL < 크기의 log2) | r200 DRI 도 그대로 보낸다: TXFORMAT 은 기본 크기 log2, MAX_MIP_LEVEL 은 레벨 수 − 1 / maxLod(MaxLevel 로 자름) | Mesa-6.5.3 `r200_texstate.c:338-339`·`:346-347`; mesa-amber `r200_texstate_amber.c:1332-1334`, `radeon_mipmap_tree_amber.c:262-263` | 같다 — §8 의 첫 용의자는 **약해졌다** |
| 캐시 플러시 | `RADEON_FLUSH_CACHE`/`PURGE_CACHE` 는 **RB3D 목적지(픽셀) 캐시**이고, 호스트 블릿 업로드 앞에서만 쓴다(블릿이 텍스처를 쓰므로) | freebsd `radeon_drv.h:1942-1960`, `radeon_state.c:1688`; `radeon_cp.c` 의 idle·start | 우리는 CPU 가 카드 idle 중에 쓴다(제출마다 W_IDLE) — 해당 없음.  **텍스처 캐시 무효화 명령은 어느 참고에도 없다**(r100/r200 범위 grep 0) |
| TXFORMAT_X LOD 바이어스 | 초기값 `LOD_BIAS_CORRECTION`(0x00600000 = 12/256 ≈ 0.047) — conform mipsel 용 | mesa-amber `r200_state_init_amber.c:1074-1076`, `r200_reg_amber.h:954`, `r200_tex_amber.c:333-339` | 우리 0 — 화질 차이일 뿐 멈춤 원인 아님 |
| **T0 hang 우회** | 텍스처 유닛 0 만 켜고 MIN 필터 > LINEAR(= 밉 모드 전부)면 유닛 1 을 켜고 `TXFORMAT_LOOKUP_DISABLE`(비트 27) | mesa-amber `r200_texstate_amber.c:1518-1533` | 우리는 유닛 0 만 켠다.  **단 참고는 `CHIP_FAMILY_R200` 에만 적용, "not needed for r200 derivatives"**; RV280 은 `CHIP_FAMILY_RV280`(`radeon_screen_amber.c:462`) |
| **텍스처 캐시 LRU hang 우회** | `PP_TAM_DEBUG3`(0x2d9c) = 0x6 을 늘 — "조건부로는 부족했다(bugzilla #1519·#729·#814)" | mesa-amber `r200_texstate_amber.c:1577-1587`; RV280 에선 tam 상태가 `never`(`r200_state_init_amber.c:671`·`:676`) | 우리는 안 쓴다.  역시 R200 전용.  버그 원문은 fetch 403 으로 못 읽음 |
| 명령 반복 hang | 같은 cmdbuf 를 cliprect 마다 반복할 때 두 번째부터 `WAIT_UNTIL_3D_IDLE` — "원인 모를 락업 회피" | linux `radeon_state_linux.c:2804-2818` | 우리 스트림은 제출 하나에 cliprect 반복 없음 — 해당 약함 |

**추적 재집계(python, `build/g46/trace.txt`)**: 제출 781 전 세그먼트의 MIN 코드는 NEAREST 824 · LINEAR 72 뿐이다 — **GLQuake 에서 밉 모드가 카드에 간 것은 혼합 모드가 처음**이다(781 부터 NEAREST_MIPMAP_LINEAR 930, 레벨 3·4·5 = 전부 8×8 에서 잘린 체인).  즉 GLQuake 의 증거는 "혼합 모드" 와 "유닛 0 단독 + 밉 필터 일반"(T0 hang 조건) 과 "잘린 체인" 을 **가르지 못한다**.  사다리 S1–S13 은 셋 다 포함했는데도 멀쩡했으므로 부하·시간 의존일 수 있다.

**가르는 실험(재부팅 뒤, 코드 변경 없음, 정지 위험 — 사용자 승인 후)**: 기본 라이브러리(혼합 거절)로 GLQuake 를 `+gl_texturemode GL_NEAREST_MIPMAP_NEAREST` 로 120 초.  월드가 NEAREST_MIPMAP_NEAREST(측정된 모드)로 카드에 간다.
- 멈추면: 혼합이 아니라 "유닛 0 단독 밉"/"잘린 체인" 쪽 → T0 우회(유닛 1 LOOKUP_DISABLE — **커널 검증기가 지금 유닛 1–5 활성을 거절한다**, `osrdn_cp.m:2624-2625`; 커널 수정·재부팅 필요)를 codex 계획 검토 뒤 시험.
- 안 멈추면: 혼합 모드 고유 → 혼합 + 잘린 체인 / TAM_DEBUG3 쪽으로 좁힌다(TAM_DEBUG3 0x2d9c 는 `osrdn_cp.m` 에 없다 — 커널 허용 목록 추가·재부팅 필요).

**재부팅 뒤(부팅 10, 2026-09-27)**: 추적 실행 부팅의 커널 로그는 `RDN-G3 present` 한 줄에서 끊겼고 정지·복구 줄은 없다(`build/g46/messages-after-trace-freeze.txt`).  CP 여섯 단계 rc 0.  가르는 실험의 명령(사용자 gcdsd, 120 초 안):

```
T=/ndrv/openstep-radeon9250/build/g46
RDNMesaTrace=$T/trace-nmn.txt RDNMesaTraceLast=$T/trace-nmn-last.bin RDNMesaSeed=$SEED \
  sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon 300 110 0 \
  -nosound +gl_texturemode GL_NEAREST_MIPMAP_NEAREST
```
`RDNMesaMip` 을 주지 않으므로 마스크는 측정된 두 모드(NEAREST_MIPMAP_NEAREST 포함)다.  `+` 명령은 quake.rc 의 stuffcmds 로 default.cfg 뒤에 실행되고, `Draw_TextureMode_f` 가 이미 만든 텍스처의 필터도 다시 건다(`gl_vidsdl.c` 의 주석).  포트의 `GL_KeepFilterDrawable` 은 이 모드를 그대로 둔다.

## 10. 오프라인 대조: 멈춘 스트림 ↔ r200 DRI 가 내보내는 상태 (2026-09-27, 실기 없이)

사용자 지시 "원인을 테스트하기 전에 참고·기존 분석부터" 에 따라 §9 끝의 실기 실험을 보류하고 대조했다.  근거 규칙: R5 계획 §5 위험 표 "하드 행 한 번이면 중단·오프라인 분류"(이미 세 번), 링 멈춤 교훈 "원인 불명 멈춤은 참조가 하는 일부터 옮겨라".

- **해독**: `build/g46/trace-last.bin` 앞 4,067 워드를 PACKET0/3 로 풀어 `build/g46/trace-last.decoded.txt` 에 남겼다(레지스터 이름은 mesa-amber `r200_reg.h`·`radeon/server/radeon_reg.h`).  세그먼트 전환은 바뀐 레지스터만 다시 쓴다(`TXFILTER`·`TXOFFSET`·`RB3D_CNTL`·`BLENDCNTL`, 크기가 바뀔 때 `TXFORMAT`·`TXSIZE`·`TXPITCH`).
- **우리가 쓰는 텍스처 값은 참조의 뜻과 같다**: `TXFILTER 0x0004000c` = MIN 필드 6<<1 은 r200 DRI 가 GL_NEAREST_MIPMAP_LINEAR 에 쓰는 `R200_MIN_FILTER_LINEAR_MIP_NEAREST`(교차 대응, `r200_tex_amber.c:242-243`), MAX_MIP_LEVEL 4; `TXFORMAT 0x7746` = ARGB8888·ALPHA_IN_MAP·log2 7/7; `TXFORMAT_X` 0(참조는 LOD 바이어스 보정 0.047 — §9); `PP_CNTL_X`·`TXMULTI_CTL_0` 0 은 참조 초기값과 같다(`r200_state_init_amber.c:1028`·`:1080`).
- **참조가 늘 쓰는데 우리가 한 번도 안 쓰는 레지스터**(`r200_state_init.c` 의 패킷 표 92 항목 전수 대조, python): 대부분 r100 전용·TCL·큐브·경계색·유닛 1–5 로 우리 경로와 무관하다.  **우리 경로(유닛 0, 삼선형)에 걸리는 것은 둘뿐**:
  - `R200_PP_TRI_PERF`(0x2cf8, `TRI_CUTOFF` 비트 0–4)와 `R200_PP_PERF_CNTL`(0x2cfc) — r200 DRI 는 `prf` 상태를 **always** 로 내보내며 값은 `0x1f − 0x1f × texture_blend_quality`(기본 1.0) = **0**, PERF_CNTL 도 0(`r200_state_init_amber.c:748`·`:984-986`, 옵션 설명 "“brilinear” texture filtering", `radeon_screen_amber.c:128-129`).  **혼합 밉(삼선형) 샘플링의 레벨 사이 보간을 다루는 유일한 레지스터**인데 우리는 전원 투입/BIOS 값 그대로 쓰고 있다.  그 값은 모른다 — xorg·BSD·Linux DRM 어디도 이 레지스터를 초기화하지 않는다(DRM 은 통과 패킷 표에만 있다: freebsd `radeon_state.c:245`·`:729`).
  - `R200_PP_TAM_DEBUG3` — RV280 에선 참조도 안 쓴다(§9).
- **한계**: 오프스크린 사다리 S1–S13 은 같은 카드·같은 미지의 TRI_PERF 값으로 혼합 모드를 통과했다.  TRI_PERF 가 원인이라면 부하·시간 의존이어야 한다.  반대로 TRI_PERF 가설은 "NEAREST_MIPMAP_NEAREST 로는 안 멈춘다" 를 예측한다 — §9 의 실기 실험과 서로를 가른다.

**다음(계획, 코딩 전 codex 검토 대상)**: 커널 변경 하나에 둘을 묶는다 — ① REC3D 목록에 0x2cf8·0x2cfc 를 더해 **지금 값을 읽기만**(레지스터 읽기는 비파괴), ② 참조처럼 제출 앞머리에서 두 레지스터를 0 으로 쓴다(앞머리의 되읽기 대조에도 포함).  ①의 값이 0 이 아니면 참조와 다른 상태로 삼선형을 돌려 왔다는 사실이 확정된다.  재부팅 1 회.

## 11. 가르는 실험 (2026-09-28, 부팅 11 = 026a93c8, 드라이버 f0d603c0, 라이브러리 790517229 기본 마스크, 사용자 gcdsd)

- G4-7 의 실측(`docs/G4_7_TRIPERF_PLAN.md` 8)이 TRI_PERF 를 배제한 뒤 §9 의 실험: `RDNMesaTrace=… RDNMesaSeed=… run-glquake-self.sh glquake_radeon 300 110 0 -nosound +gl_texturemode GL_NEAREST_MIPMAP_NEAREST`(05:15:28, `build/g47/nmn.log`·`trace-nmn.txt`·`glq-self-nmn.log`).
- **멈추지 않았다.** 300 프레임 41.9 초, exit 0, 커널 로그에 rc≠0·복구 줄 없음.  제출 7,203 개(최대 4,068 워드); 세그먼트의 MIN 코드: NEAREST 1,186 · LINEAR 6,193 · **NEAREST_MIPMAP_NEAREST 20,236(삼각형 910,916)**, 첫 밉 제출은 **781 번째**(혼합 실행과 같은 자리), 레벨 2/3/4/5 = 8×8 에서 잘린 체인 그대로(python 집계).
- 따라서 정지는 **"유닛 0 단독 + 밉 필터"·"잘린 체인"·"GLQuake 의 부하·present 경로" 가 아니라 혼합 두 모드(하드웨어 MIN 필드 0xc·0xe) 에 특정**된다.  r200 DRI 의 T0 우회(밉 필터 전부에 적용)는 후보에서 빠진다(NMN 도 그 조건인데 멀쩡).
- 남은 후보는 좁다: 같은 스트림에서 TXFILTER 의 MIN 필드만 다르다.  사다리 S1–S13 은 그 값으로 통과했으므로 **양(수십만 삼각형)·이력(436 제출)·GLQuake 의 특정 텍스처 조합** 중 하나다.  다음 수단 후보: ① 멈춘 스트림(`trace-last.bin` 4,067 워드)을 오프스크린으로 그대로 재생(`rdnr7sub`) — 멈추면 4,067 워드짜리 재현기(이분 탐색 가능), 안 멈추면 이력 의존; ② 라이브러리에 **전 스트림 기록** 모드를 넣고 `RDNMesaMip=all`(TRI_PERF=0 아래) 로 다시 — 멈춰도 전체 이력이 남아 오프스크린에서 조각별 재생·이분 탐색.
