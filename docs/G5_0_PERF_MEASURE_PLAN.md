# G5-0 — GLQuake 프레임 시간의 내역을 잰다 (계측만, 커널 불변, 재부팅 없음) (계획, 2026-09-29, 코딩 전)

## 0. 지금 손에 있는 숫자 (전부 python 으로 로그에서 다시 계산)

`mgastats tick t=… frames=…` 의 `t` 는 `Sys_FloatTime`(`gettimeofday`, `sys_sdl.c:331`) 이므로 벽시계다(`gl_vidsdl.c:416-427`).  프레임 1 → 마지막의 차로 프레임당 시간:

| 실행(로그) | 장면 | ms/프레임 | fps | 카드 삼각형/프레임 | 제출/프레임 |
|---|---|---|---|---|---|
| `build/g410/glq-g411.log` | `+map start`, 정지 | **46.8** | 21.4 | 1,443 | 8.27 (`trace-g411.txt` 2,480/300) |
| `build/g410/glq-start.log` | 같은 장면(라이브러리 790585730) | 57.2 | 17.5 | 1,456 | 8.34 |
| `build/g410/glq-shot-radeon.log` | `+map start` 450 프레임 | 38.5 | 26.0 | 989 | — |
| `build/g410/glq-self.log` | 기본 데모(demo1), 300 프레임 | **134.1** | 7.5 | 4,262 | 24.1 (`trace-glq.txt` 7,221/300) |
| `build/g46/self-radeon*.log` | 데모 100 프레임(G4-6 당시) | 164–173 | 5.8–6.1 | 1,847 | — |
| `build/g46/e0-nullsend.log` | 데모 60 프레임, **제출 없음**(`RDNMesaNullSend=1`, `G4_6_GLQUAKE_PLAN.md:54-59`) | 115.3 | 8.7 | 0 (카드에 안 보냄) | 0 |

- G4-10 §7 의 "7–8 fps" 는 **데모 장면**의 값이고, 사용자가 실제로 보는 시작 맵은 21 fps 다.  G4-10 §7 이 "남는 병목은 제출 경로" 라고 적은 것은 **측정 없이 적은 추정**이었다 — 이 계획이 그것을 잰다.
- 장면 둘의 차: (134.1 − 46.8) ms / (4,262 − 1,443) 삼각형 ≈ **31 us / 삼각형**(제출 수 차이 16/프레임이 섞여 있음).  Matrox 의 호스트 빌드 실측은 4.5 us/삼각형(`W5_ASYNC_SUBMIT_DESIGN.md:313-406`) 이었으니, 31 us 는 삼각형 자체보다 **파이프라인 실행 횟수·제출 횟수 같은 고정비**를 의심하게 한다.
- E0(제출 없음) 115 ms 는 60 프레임짜리라 같은 장면이 아니지만, **카드에 아무것도 안 보내도 데모가 115 ms** 라는 것은 CPU 쪽(게임 + Mesa T&L + 우리 분류·묶음)이 프레임의 대부분이라는 단서다.  제출 ioctl 24 회가 (134 − 115) ≈ 19 ms 안에 들어간다면 제출당 ≤ 0.8 ms.
- Matrox(같은 게임·Mesa·머신): 레벨 프레임 153 ms = 제출 66.4 ms(155 회 × 429 us) + CPU 86.6 ms(`M11_ASYNC_RETIRE_PLAN.md:7-15`).  비동기 제출은 **NO-GO** — 완료를 알아차릴 주체(인터럽트·타이머)가 없어 ioctl 이 일찍 돌아오면 아무도 폴링하지 않는다(`W5_ASYNC_SUBMIT_DESIGN.md:217-237`, 판정 `:253-275`).  이 드라이버도 인터럽트 없음(폴링 `cpWait`, `osrdn_cp.m:217-287`)이라 같은 벽이다.  **그래서 G5 는 비동기가 아니라 "동기 경로를 싸게" 와 "CPU 쪽" 을 본다 — 어느 쪽인지는 이 계측이 정한다.**

## 1. 가설과 예상 신호

| # | 가설 | 참이면 보이는 것 |
|---|---|---|
| H-A | SUBMIT2 ioctl(copyin·검증·링 쓰기·펜스·대기)이 프레임의 ≥ 40 % | `ioctl us` 합이 프레임의 40 % 이상; 커널 tstage 가 어느 단계인지 가른다 |
| H-B | Mesa 파이프라인 실행(RenderStart→Finish 묶음) 횟수가 많고 실행당 고정비가 크다 | 프레임당 bracket 수 수백, bracket 안 시간 ≫ 삼각형 훅 시간 합 |
| H-C | 우리 삼각형 훅(분류·정점 변환·묶음 적재) 이 삼각형당 ≥ 5 us | 훅 안 사이클 합 / 삼각형 |
| H-D | 나머지(Quake 논리 + Mesa T&L: 우리 훅 밖, bracket 밖)가 ≥ 50 % | 벽시계 − (위의 전부) |
| H-E | present 행 480 회 + clear 가 ≥ 15 % | present us 합 (G3 실측 600 행 18.9 ms `G3_PRESENT_PLAN.md:138`; SDL 자체 실측 행당 커널 진입 7.21 us `SDL_openstepvideo.m:2549-2593`) |

Mesa 3.4.2 의 사실(연 것): 즉시 모드 VB 는 최대 216 정점(`config.h:179-194`), `glBindTexture` 는 `ASSERT_OUTSIDE_BEGIN_END_AND_FLUSH` 로 VB 를 비운다(`texobj.c:520-533`, `FLUSH_VB` 정의 `types.h:2064-2069`).  GLQuake 는 표면마다 텍스처·라이트맵을 바꾸므로 파이프라인 실행이 표면 수만큼 일어날 수 있다 — H-B 의 근거.  RenderStart/Finish 는 래스터 단계 앞뒤(`vbrender.c:699-729`)라 **T&L(변환·클립·투영)은 bracket 밖**에 있다.

## 2. 계측 설계 (라이브러리만, 기본 꺼짐)

### 2-1. 시계
- `rdtsc`(P4 Celeron, TSC 상수 2.66 GHz; `.byte 0x0f, 0x31` 로 — 타깃 as 가 mnemonic 을 모를 수 있다; `__asm__ __volatile__` 선례 `osrdn_cpu.m:10`).  32×2 비트를 `unsigned long` 둘로 받아 64 비트 차를 **python 처럼 정확히**: lo/hi 를 그대로 누적하지 않고, 차이를 (hi 차 × 2^32 + lo 차) 로 계산해 `unsigned long` 두 개(하위·상위 캐리)로 누적.
- 보정: 실행 시작·끝에 `gettimeofday` 와 rdtsc 를 함께 읽어 **사이클/us 를 실측**(추정 2660 과 대조).  `gettimeofday` 비용도 시작 때 1,000 회 루프로 잰다(보고에 넣는다).
- knob `RDNMesaTime=1` 일 때만 켜진다(정적 int, 첫 호출에 한 번 읽음).  꺼져 있으면 각 자리의 비용은 `if (!on)` 하나.

### 2-2. 자리 (전부 라이브러리 안)

| 자리 | 파일:줄 | 재는 것 |
|---|---|---|
| 삼각형 훅 | `OSRDNMesaHook.c:1140-1145` (`osrdnHookTriangle`: `osrdnTriStateOf` + `osrdnTriangleWith`), 묶음 경로 `:1140`(`osrdnTriStateOf`)·`:1225-1228`(루프) — 상태 준비(`TriStateOf` 안의 상주화·업로드 `:833`→`:361-364`)를 **포함**하도록 두 자리 모두 진입에서 이탈까지 | 호출 수, 안 사이클 합·최대, `outsideRender` 수(`:1070-1072`) |
| bracket | `:1349`(`osrdnHookRenderStart`) → `:1429`(`osrdnHookRenderFinish`) | 수, 안 사이클 합; bracket 당 삼각형 |
| 호스트 검증 | `OSRDNMesaTri.c:1631-1646` (`osrdn_tri_batch_verify` → `osrdn_r7_verify`) | 수, 사이클 합 |
| SUBMIT2 ioctl | `OSRDNMesaTri.c:864-964` (`triSubmit`, ioctl `:936`) | 수, 사이클 합·최대, 워드 합 |
| present 행 | `OSRDNMesaPresent.c:375` | 수, 사이클 합; **프레임 경계** = `dstY` 가 직전보다 커지는 호출(SDL 은 행을 역순으로 찍는다 `SDL_openstepvideo.m:2578-2583`) |
| clear | `OSRDNMesaDepth.c:129` | 수, 사이클 합 |
| 텍스처 업로드 | `OSRDNMesaTex.c:87`(`osrdn_tex_upload_level`, 잎) — `:68-77` 의 `_at` 은 이것을 부르고, 훅은 `OSRDNMesaHook.c:362`·`:370` 에서 둘 다 부른다 | 수, 사이클 합, 바이트, 꼬리표 |
| 벽 | 첫 bracket 시각 → 보고 시각 | 전체 us; 프레임 수(present 경계 수, clear 수 둘 다 기록해 대조) |

### 2-3. 보고
- 라이브러리가 첫 훅 설치 때 `atexit()` 로 보고 함수를 등록(게임은 `Sys_Quit` → `exit()` `sys_sdl.c:83`): stderr 에 `RDN-T …` 줄(로그 `/tmp/glq-self.log` 에 남는다).  줄 모양을 고정하고 판정기가 그것만 읽는다.
- shim 의 빈 함수 두 개를 채운다(`osrdn-mga-shim.h:152-164`): `OSMGAMesaHookSubmitStats` ← SUBMIT2 수·us·워드, `OSMGAMesaHookBracketStats` ← bracket 수·us.  포트(`gl_vidsdl.c:356-357`)는 손대지 않는다 — 이미 그 값을 찍고 있다.

### 2-4. 커널 쪽 내역 (기존 knob, 드라이버 변경 없음)
- `r5op.sh time 1` → 실행 → `r5op.sh tdump`: `RDN-R5 tstage … pre= s1ring= s1read= s2asm= s2ring= flush= tail= fence= wait= put=`(`osrdn_modelog.m:346-357`).  M2c 의 계기가 SUBMIT2 경로에서 도는지: `osrdn_cp.m:3166-3169` (`c->timeOn` → `tOn`), `cpTimeSet` `:2981-2990`, 도구 op 이름 `rdnr5cp.m:51-58`.  **한 실행에서 켜고, 한 실행에서 끄고** 둘 다 잰다(계기 자체 비용 = 시계 17 회/제출, M2c).
- 이 계기는 M2c 부터 여러 부팅에서 돌았다 — 정지 위험 없음.

## 3. 실행 (사용자 gcdsd 불필요: 자가 실행은 오프스크린이 아니라 창을 띄운다 → **사용자 gcdsd 필요**, 화면 실행 ≈ 2 분 규칙)

| # | 실행 | 목적 |
|---|---|---|
| R1 | `+map start` 300 프레임, `RDNMesaTime=1`, 커널 `time 1` | 시작 맵 내역 |
| R2 | 기본 데모 300 프레임, 같은 설정 | 데모 내역(무거운 장면) |
| R3 | R1 을 `RDNMesaTime` 없이, 커널 `time 0` | 계기 비용(프레임 시간 차) |

각 실행 뒤 `tdump` 한 번(누적을 읽고 0 으로).

## 4. 판정 (`build/g50/judge_g50.py`, python)
- `RDN-T` 줄 + tick 줄 + tstage 줄을 읽어 표를 만든다.  **모든 타이머는 포함(inclusive) 시간이고, 호출마다 `bracket 안(osrdnInRender)`·`훅 안(osrdnTimeInHook)` 꼬리표로 나눠 누적**한다(§7 의 codex 판정: 업로드·제출이 훅 안에서 일어난다).  배타 분할은 판정기가 만든다:
  - 벽 = bracket(포함) + 제출·present·clear·업로드 의 **bracket 밖** 몫 + 나머지
  - bracket(포함) = 훅(포함) + 검증 + 제출(bracket 안·훅 밖) + 업로드(bracket 안·훅 밖) + bracket 기타
  - 훅(포함) = 훅 자체 + 제출(훅 안) + 업로드(훅 안)
  - 업로드는 `osrdn_tex_upload_level`(잎) 한 자리에서만 잰다 — `osrdn_tex_upload_at` 은 그것을 부른다(`OSRDNMesaTex.c:77`)
- 자기검사: (a) 벽 ≈ tick 의 t 차(±5 %), (b) 부분 합 ≤ 벽, (c) 훅 ⊂ bracket, 검증 ⊂ bracket 안팎 어느 쪽인지 표기(osrdnBracketEnd 가 부른다), (d) 계기 비용 = R3 대비 < 5 %(넘으면 rdtsc 자리를 줄인다), (e) TSC 보정값이 2,660 ± 5 % 안.
- 결정표: H-A/B/C/D/E 가운데 **가장 큰 조각**이 G5-1 의 대상.  둘이 비슷하면 둘 다 적고 싼 쪽부터.

## 5. 하지 않는 것
- 커널 변경, Quake·SDL 변경, 비동기 제출.  성능 개선 코드는 이 계획에 없다 — 숫자가 나오기 전의 최적화는 G4-10 §7 의 추정과 같은 실수다.

## 6. codex 교차검토 (한 주장·국지적)
주장: "위 2-2 의 여덟 자리는 모두 라이브러리 함수의 진입/이탈에서 rdtsc 두 번으로 잴 수 있고, 삼각형 훅과 bracket 은 포함 관계(훅 ⊂ bracket)이며 SUBMIT2·present·clear·업로드는 서로 겹치지 않는다 — 즉 부분들을 더해 벽시계와 비교하는 산술이 성립한다."  확인할 것: 삼각형 훅이 bracket 밖에서 불리는 경로(`osrdnFlushOutside`, 점·선 경로), present 가 bracket 안에서 불리는 경우, 업로드가 삼각형 훅 안(텍스처 상주화)에서 일어나는 경우.

## 7. codex 교차검토 판정 (2026-09-29, gpt-6-astra, 한 주장·국지적) — 주장은 그대로는 성립하지 않음, 설계 수정(§2-2·§4)

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| 업로드가 삼각형 훅 안에서 일어난다: `osrdnHookTriangle`→`osrdnTriStateOf`(`OSRDNMesaHook.c:1140`)→`osrdnTexResident`(`OSRDNMesaHook.c:833`)→`OSRDNMesaHook.c:361-364` `osrdn_tex_upload_at`→`OSRDNMesaTex.c:77` `_level`; 추가 밉 `OSRDNMesaHook.c:370`; 묶음 경로도 `OSRDNMesaHook.c:1203` | 줄을 전부 열어 확인 | ✅ 채택 — 훅 타이머는 `TriStateOf` 를 포함, 업로드는 잎(`_level`)에서만, 꼬리표로 분리 |
| 제출 진입점: 훅 안 `OSRDNMesaHook.c:1075`(단독 전송 전)·`OSRDNMesaHook.c:1085`(ctx 변경)·`OSRDNMesaHook.c:1089`(가득/불일치)·`OSRDNMesaHook.c:1110`(위임 전); bracket 끝 `OSRDNMesaHook.c:1438`→`OSRDNMesaHook.c:577`/`OSRDNMesaHook.c:606`; 업로드 전 `OSRDNMesaHook.c:361`; TexDrop `OSRDNMesaHook.c:284`(호출자 `OSRDNMesaHook.c:334`·`OSRDNMesaHook.c:404`·`OSRDNMesaHook.c:431`); clear `OSRDNMesaHook.c:665`; 점·선 `OSRDNMesaHook.c:1465`·`OSRDNMesaHook.c:1479`; Flush/ReadPix/CopyPix/DrawPix/Bitmap `OSRDNMesaHook.c:1521`·`OSRDNMesaHook.c:1575`·`OSRDNMesaHook.c:1592`·`OSRDNMesaHook.c:1603`·`OSRDNMesaHook.c:1613`; UpdateState `OSRDNMesaHook.c:1912`→`OSRDNMesaHook.c:1659`; 표면 `OSRDNMesaHook.c:1929`; 해제 `OSRDNMesaHook.c:1995`; `osrdnFlushOutside` `OSRDNMesaHook.c:631`(호출자 `OSRDNMesaHook.c:1372`·`OSRDNMesaHook.c:1414`·`OSRDNMesaHook.c:1781`·`OSRDNMesaHook.c:1984`); 공통 꼬리 `OSRDNMesaHook.c:544`→`OSRDNMesaHook.c:469`→`OSRDNMesaTri.c:1578`→`OSRDNMesaTri.c:936`; 단독 전송 `OSRDNMesaHook.c:1075`→`OSRDNMesaTri.c:1155` | 전부 열어 확인 | ✅ 채택 — 제출 타이머는 ioctl 자리(`OSRDNMesaTri.c:936`) 하나에, 꼬리표(bracket 안·훅 안)로 분리 |
| 호스트 검증은 bracket 끝에서만: `OSRDNMesaHook.c:1438`→`OSRDNMesaHook.c:587`→`OSRDNMesaTri.c:1631`, 플래그는 그 뒤 `OSRDNMesaHook.c:1439` 에서 내린다 | 열어 확인 | ✅ 검증 ⊂ bracket |
| 삼각형 훅이 bracket 밖에서 도는 경로는 방어 코드(`OSRDNMesaHook.c:1070-1072` `outsideRender`)만 확인, 실제 호출자는 범위 밖 | 열어 확인 | ⚖️ 계수기 `outsideRender` 를 보고에 넣어 실측으로 답한다 |
| present·clear 는 bracket 검사가 없다(`OSRDNMesaPresent.c:244-287`, `OSRDNMesaDepth.c:81-138`), 열린 bracket 안에서 불리는지는 범위 밖 | 열어 확인 | ⚖️ 꼬리표로 실측 |
| (4)~(7) 끼리는 중첩 반례 없음: 업로드 전 제출은 `OSRDNMesaHook.c:361` 에서 끝난 뒤 `OSRDNMesaHook.c:362`; clear 전 제출 `OSRDNMesaHook.c:665` 뒤 `OSRDNMesaHook.c:714`→`OSRDNMesaDepth.c:129`; PresentRect(`OSRDNMesaPresent.c:375`)는 제출·검증을 안 부른다 | 열어 확인 | ✅ |
| `osrdn_tri_release` 는 제출 없이 리셋(`OSRDNMesaTri.c:512-527`) | 열어 확인 | ✅ (해제는 타이머 대상 아님) |

codex 줄번호는 전부 실제와 일치(python 으로 62 줄을 출력해 대조).

## 8. 실측 (2026-09-29, 라이브러리 790593936, 드라이버 2d3234bf, 사용자 gcdsd, `build/g50/run_g50.sh` → `run.log`, `judge-r1.txt`, `judge-r2.txt`)

세 실행 모두 300 프레임 완주, 정지 없음, 위임 0.  TSC 보정 2,660 MHz(예상과 일치), `gettimeofday` 4.6 us.  구현: `mesa/OSRDNMesaTime.c`(호스트 시뮬레이터 `tools/mesa/sim_time.py` 8 변이), 자리는 §2-2 그대로; shim 이 포트의 `submit`/`bracket` 줄을 채운다.

### 8-1. 프레임 예산 (ms/프레임, 판정기의 배타 분할)

| 조각 | R1 시작 맵 (43.8 ms, 22.8 fps) | R2 데모 (82.3 ms, 12.2 fps) | 비고 |
|---|---|---|---|
| present 행(480 회) | **15.8 (35 %)** — 32.9 us/행 | 15.1 (18 %) — 31.4 us/행 | G3 실측(600 행 18.9 ms)과 같은 행당 비용 |
| SUBMIT2 ioctl(전부) | 11.4 (25 %) — 1,323 us/제출 × 8.6 | 21.1 (25 %) — 829 us/제출 × 25 | 커널 내역은 8-2 |
| 텍스처 업로드(훅 안) | 4.6 (10 %) — **10.9 ms/레벨** × 124 | **22.6 (27 %)** — 11.1 ms/레벨 × 607 | 8-3: 전수 되읽기 |
| 삼각형 훅 자체 | 2.4 (5 %) | 8.8 (10 %) | 상태 준비·분류·적재 |
| 호스트 검증 | 0.14 | 0.69 | 5.5 us/bracket |
| bracket 기타 | 0.3 | 1.1 | |
| 나머지(게임 + Mesa T&L) | 10.5 (23 %) | 14.4 (17 %) | 우리 밖 |
| clear | 0 회 | 0 회 | GLQuake 는 `gl_ztrick` 이라 clear 를 안 부른다 |

- 제출·업로드는 전부 훅 **안**에서 일어났다(bracket 안·훅 밖 0, bracket 밖은 프레임당 1 회 = present 앞의 flush).  codex §7 의 지적이 맞았다: 꼬리표 없이는 훅 17.5 ms 가 "훅 비용" 으로 읽혔을 것이다.
- 데모의 fps 12.2 는 G4-10 §7 의 7.5 와 다르다(그때는 라이브러리 790580725·깊이 버그 상태·다른 부팅) — 비교는 이 부팅 안에서만.
- R3(knob 없음, 커널 계기 off) 36.5 ms 대 R1 43.8 ms: +20 % 이지만 같은 장면이 이전 실행들에서 38.5–57.2 ms 로 흔들렸으므로(§0 표) 한 쌍으로는 계기 비용을 못 판정한다.  자리별 계수로 상한을 잡으면 rdtsc 2 회 × (훅 1,540 + 행 480 + 제출 9)/프레임 ≈ 4,000 회 × ~100 사이클 = 0.15 ms.  커널 계기(제출당 시계 17 회)는 별도.  → 다음 실행부터 A/B 를 번갈아 두 쌍.

### 8-2. 커널 단계 (tstage, 제출당 us; 프레임당 ms 는 python)

| | R1 | R2 |
|---|---|---|
| gates·pre·s1ring·s1read·s2asm·flush·tail(검증 장치) + put + fence + wait | 290 us → **2.5 ms/프레임** | 307 us → 7.8 ms/프레임 |
| s2ring − (put + fence + wait) = **카드가 스트림을 소비·그리는 시간** | 976 us → **8.4 ms/프레임** | 450 us → 11.5 ms/프레임 |
| 합 | 10.9 ms (라이브러리의 ioctl 합 11.4 와 일치) | 19.3 ms (21.1) |

`wait` 79–93 us 가 카드 시간을 안 담는 이유: `cpWait` 의 W_RPTR 대기는 rptr 이 움직일 때마다 시계를 **다시 시작**한다(`osrdn_cp.m:245-250`, 참조 `radeon_wait_ring` 의 `head != last_head → i = 0`, `osrdn_cp.h:448`).  그래서 소비 중인 시간은 s2ring(마크 4→5 = `cpR6Submit` 한 번, `osrdn_cp.m:3505-3509`)에만 남는다.  제출당 ~1 ms 는 4,000 워드(16 KB)를 PCI 로 가져오는 시간 + 그리기 — R1 이 R2 보다 제출당 2 배 긴 것은 삼각형이 커서(화소가 많아서)다.  **이 시간 동안 CPU 는 동기 대기한다**(프레임의 19 % / 14 %).

### 8-3. 업로드 11 ms 의 정체

`osrdn_tex_upload_level` 은 텍셀을 VRAM 창에 쓴 뒤 **전부 되읽어 대조**한다(`OSRDNMesaTex.c:145-177`): 128² 레벨 = 16,384 워드의 비캐시 PCI 읽기 ≈ 10 ms(읽기 ~0.6 us/워드; 쓰기 루프는 그 1/10).  M1 계보의 "썼는지 확인" 게이트가 생산 경로에 그대로 남아 있었다.  데모는 300 프레임에 607 레벨을 처음 쓰므로(축출 0) 프레임당 2 회 = 22.6 ms.

### 8-4. 판정 — 어느 가설이 맞았나

| 가설 | 결과 |
|---|---|
| H-A 제출 ≥ 40 % | ❌ 25 % — 그중 8.4/11.5 ms 는 카드 시간(동기 대기), 2.5/7.8 ms 가 검증 장치 |
| H-B bracket 횟수·고정비 | ❌ bracket 26/123 회/프레임, 검증 5.5 us, 기타 0.3/1.1 ms |
| H-C 훅 ≥ 5 us/삼각형 | ❌ 1.6 us(R1), 1.9 us(R2) |
| H-D 나머지 ≥ 50 % | ❌ 23 % / 17 % |
| H-E present + clear ≥ 15 % | ✅ **35 % / 18 %** |
| (예상 밖) 업로드 되읽기 | ✅ 10 % / **27 %** |

### 8-5. G5-1 후보 (프레임당 이득 순, 재부팅 여부)

| # | 항목 | R1 이득 | R2 이득 | 어디 | 재부팅 |
|---|---|---|---|---|---|
| 1 | present 를 프레임당 **한 블릿**으로: 라이브러리가 y 를 뒤집어 그려(정점 y′ = H−1−y, 컬링 방향 반전, 시저 y 반전) 표면을 위→아래로 만들면 SDL 의 행 루프는 그대로 두고 `present_rect` 가 행을 모아 한 번에 보낼 수 있다 — 또는 드라이버 블릿이 뒤집기를 배우는 길(SDL 주석이 "부호 비트가 겹침 순서에 쓰인다" 고 적은 것을 R200 2D 사양으로 확인해야) | ~15 ms | ~15 ms | 라이브러리(±드라이버) | 라이브러리만이면 없음 |
| 2 | 업로드 되읽기를 knob 뒤로(기본 끔; `RDNMesaTexVerify=1` 로 켬) — 쓰기 뒤 표본 4 워드 대조로 "썼는지" 는 계속 본다 | ~4 ms | ~20 ms | 라이브러리 | 없음 |
| 3 | 카드 소비 시간과 CPU 의 겹침(지연 대기): W5 §8 의 "완료를 알아차릴 주체" 문제를 이 드라이버에서 다시 본다 — 링은 순서대로 소비되므로 다음 링 접촉(제출·present·업로드 전 flush) 에서 대기하면 된다; 검증 장치의 되읽기(s1read·flush·tail)가 완료를 전제하므로 4 와 묶인다 | ≤ 8 ms | ≤ 11 ms | 커널 | 있음 |
| 4 | 제출당 검증 장치(prefix 재전송·되읽기 13·digest·tail) 를 생산 모드에서 생략 | ~2 ms | ~7 ms | 커널 | 있음 |

권장 순서: **2 → 1**(둘 다 라이브러리, 재부팅 없음; 2 는 반나절, 1 은 뒤집기 분석 필요) → 그다음 3·4 를 한 계획으로.

### 8-6. 보충 (G5-1a §5 에서 알게 된 것)
- `+map start` 300 프레임 중 처음 ~115 프레임은 콘솔(글자 쿼드 3,000 개/프레임, 34 ms)이라 §8-1 의 시작 맵 숫자는 희석된 평균이다.  **월드 프레임(150–300)만 보면 G5-0 라이브러리로 36.7 / 34.7 ms** 였고, 데모는 전부 월드라 그대로다.  판정기가 그 줄을 따로 찍는다.
- §8-1 의 "계기 비용 +20 %" 는 재링크 직후 첫 실행의 콜드 캐시(첫 100 프레임 52 ms → 다음 실행 34 ms)였다; knob 켜고/끄고 번갈아 잰 실제 계기 비용은 ≈ 2 %.
- 업로드 되읽기는 G5-1a 로 제거됐다(레벨당 11 → 1.4 ms).
