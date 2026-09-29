# M3g — `glFinish` 가 응용 버퍼를 채운다 (라이브러리만, 재부팅 없음)

G1 열린 항목 1(`docs/M3A_PLAN.md` 14): 가속 링크는 색 표면을 바꿔치기하고 응용 배열로는 osmesa.c 의 세 자리에서만
되돌린다.  `glFinish` 는 그중이 아니라, 보통의 OSMesa 프로그램은 `glFinish` 뒤 자기 배열에서 **빈 그림**을 본다.
**이 문서는 코딩 전에 쓴다.**

## 1. 사실 (열어 확인)

- `_mesa_Finish` 는 `ctx->Driver.Finish` 가 있으면 부른다(Mesa `src/context.c` 2016–2024).
- Mesa 3.4.2 전체에서 `Driver.Finish` 를 설정하는 곳은 `ddsample.c` 뿐 — **osmesa.c 는 비워 둔다**(grep).
- osmesa.c 888–895(`OSMesaGetColorBuffer`)는 `OpenStepMesaAccelBoundTo(c)` → `AppBuffer` → `OpenStepMesaAccelMirror()` 로 되돌린다.
  우리 `Mirror` 는 대기 묶음을 내보내고(`osrdnFlushOutside`) `osrdn_surf_mirror()` 를 부른다(`mesa/OSRDNMesaHook.c`).
- 표면 소유자는 `OSMesaMakeCurrent` 의 `OSMesaContext`(osmesa.c 553·561) = `ctx->DriverCtx`(osmesa.c 1980 의 단언).

## 2. 바꿀 것 (`mesa/OSRDNMesaHook.c`)

- `osrdnHookFinish(GLcontext *ctx)`: 대기 묶음을 내보내고, `osrdn_surf_bound_to(ctx->DriverCtx)` 이고 응용 배열이 있으면
  `osrdn_surf_mirror()`.  계수기 `finishes`·`finishMirrors`.
- 설치: `OpenStepMesaAccelUpdateState` 에서 **매번**, 삼각형 훅을 받든 말든(소프트웨어도 바꿔치기한 표면에 그린다).
  `Driver.Finish` 가 비어 있을 때만 넣는다; 다른 것이 있으면 **덮지 않고** `finishForeign` 만 센다.
- `glFlush` 는 건드리지 않는다(GL 이 요구하는 것은 `glFinish` 뒤의 완료; 필요해지면 따로).

## 3. 시험

- 호스트: `check_hook.py` 규칙(설치가 UpdateState 에 무조건, 비어 있을 때만, Finish 가 묶음을 먼저 내보낸다) + 변이.
- 타깃(CP 가 살아 있는 이 부팅): teapot 이 `glFinish` 직후 **자기 배열 `buf`** 와 `OSMesaGetColorBuffer` 를 바이트 비교해
  `step=finish-sync same=<1/0> differ=<n>` 을 찍는다.  가속 64×64 에서 `same=1`, 그리고 기존 판정(`judge_teapot`) 그대로 PASS.

## 4. codex 계획 검토 (한 질문: glFinish 때 `osrdn_surf_mirror` 가 올바르고 범위 안인가) — **계획이 막혔다**

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 방향은 맞다(표면 → 응용), GetColorBuffer 경로와 같은 복사 | `OSRDNMesaSurface.c` `osrdn_surf_mirror` 본문, osmesa.c 888–895 | ✅ |
| 응용 행 길이를 따르지 않는다: take 는 `appRowPixels < width` 만 거절, 복사는 평평한 `width × height` | `osrdn_surf_take` 의 조건(`appRowPixels < width`), mirror 의 단일 루프; osmesa.c 는 바인딩 뒤 `ctx->rowlength = accelRow`(=width) — 그래서 741 행 검사도 안 걸린다.  osmesa.c 주석 "the back end declines" 는 **거짓** | ✅ 기존 결함 |
| 형식을 안 본다: COLOR_INDEX(1 바이트)·RGB/BGR(3 바이트)도 4 바이트 표면을 받고, mirror 가 `4·w·h` 바이트를 써 **범위 밖** | osmesa.c 가속 진입(545–567)에 형식 조건 없음(612–621 은 알파 처리만), take 에 쉬프트 검사 없음(grep: 저장만) | ✅ 기존 결함 — **메모리 안전** |
| Y_UP=false 로 떠난 문맥이 다시 MakeCurrent 하면 방향 정보 없이 다시 바인딩 | osmesa.c 561 호출에 yup 없음, 741 검사는 PixelStore 에만; 분류기는 `yUp` 을 받기만(`OSRDNMesaClass.c` 사용처 0) | ✅ 기존 결함 |

**쉬프트로는 형식을 못 가린다**: RGB·BGR 은 ARGB 와 같은 `b0 g8 r16`(osmesa.c 178–262), COLOR_INDEX 만 전부 0.
형식과 방향은 `OSMesaContext`(osmesa.c 전용 구조체) 안에만 있어 우리 라이브러리가 알 길이 없다.

**결론**: Finish 훅을 계획대로 넣으면 기존 결함(특히 3 바이트 형식의 범위 밖 쓰기)을 **모든 glFinish** 로 넓힌다.  고치려면
공유 포트 `openstep-mesa342/osmesa.c` 가 형식·방향을 훅에 넘겨야 하고, 같은 훅을 **matrox** 도 구현한다
(`openstep-matrox-remade/mesa/OpenStepMGAMesaBuffer.c` 873).  → **사용자 결정 대기.  코드는 아직 한 줄도 바꾸지 않았다.**

## 5. 사용자 결정 (2026-09-25): 공유 포트 수정 — 그리고 조사로 바뀐 계획

matrox 를 읽고 계획을 좁혔다:

- **matrox 는 glFinish 를 백엔드에서 이미 한다**: 자기 UpdateState 훅에서 `ctx->Driver.Finish = osmgaMesaMirror`
  (`openstep-matrox-remade/mesa/OpenStepMGAMesaHook.c` 4576).  → Finish 는 **radeon 라이브러리에** 넣는다(처음 계획대로, matrox 와 같은 자리).
- **행 길이**: matrox 는 응용 행 길이를 따른다(`bufAppRow`, 행 단위 복사).  공유 포트에서 `rowlength == width` 로 거르면 matrox 가 잃는다
  → **radeon take 가 `appRowPixels != width` 를 스스로 거절**.
- **방향**: matrox 는 `!yUp` 이면 하드웨어 삼각형을 거절한다(같은 파일 4513).  소프트웨어는 표면에 같은 배치로 그리고 되복사는 1:1 이라
  그림은 맞다 → **radeon 도 UpdateState 에서 `!yUp` 또는 행 길이 ≠ 표면 폭이면 삼각형 훅을 받지 않는다**.
- **형식**: matrox 의 쉬프트 검사(r16 g8 b0)도 RGB·BGR(3 바이트, 같은 쉬프트)을 통과시킨다 → 두 백엔드 공통 위험.
  → **공유 포트 `osmesa.c` 가 4 바이트 형식(`OSMESA_RGBA`·`BGRA`·`ARGB`)에만 가속 표면을 제안**한다.  나머지는 훅을 부르지 않고 거절과 같게.
  `#ifdef OPENSTEP_MESA_ACCEL_HOOK` 안이라 공개된 기본 libGL 은 그대로.

matrox 소스는 바꾸지 않는다.  matrox 라이브러리는 다음에 다시 빌드할 때 새 osmesa.o 를 받는다 — **matrox 실기 회귀는 카드를 바꿔 끼울 때(사용자)**.

## 6. codex 계획 검토 2 (한 질문: 형식 게이트 뒤에도 4 바이트가 아닌 문맥이 백엔드에 닿는 곳)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| `ctx->format` 은 생성 때 한 번만 대입 | osmesa.c 311 `osmesa->format = format;`, 대입 grep 은 그 한 줄 | ✅ |
| 게이트 뒤 표면(색·깊이)을 얻는 길은 없다 — 깊이·ClearPixel(640) 은 `if (accelBuf)` 안 | osmesa.c 578–640 | ✅ |
| 남는 호출: UpdateState(2013), clear_color 의 ClearPixel(986), BoundTo, Destroy 의 ReleaseBuffer — 백엔드가 묶이지 않은 문맥을 거르면 무해 | radeon: 삼각형마다 바인딩 검사(`OSRDNMesaHook.c` 431–432 `notBound`), ClearPixel 은 스텁(`OSRDNMesaStubs.c` 55), Release 는 소유자 아닌 문맥에 무동작(`osrdn_surf_release`).  matrox: UpdateState 첫머리 `if (!OSMGAMesaBufferBoundTo(ctx->DriverCtx))`(4501), ClearPixel 은 문맥과 짝지어 기록만(4637–4641) | ✅ 두 백엔드 모두 무해 |

## 7. 구현·호스트

- **공유 포트** `openstep-mesa342/…/osmesa.c`(OSMesaMakeCurrent 의 훅 블록): `ctx->format` 이 `OSMESA_RGBA`·`BGRA`·`ARGB` 일 때만 `OpenStepMesaAccelBuffer` 를 부른다.  나머지는 `accelBuf = 0` — 기존 거절 경로 그대로.  매크로 안이라 공개 기본 libGL 은 불변.
- **radeon** `mesa/OSRDNMesaHook.c`: `osrdnHookFinish`(바인딩·응용 배열 확인 → 묶음 내보내기 → `osrdn_surf_mirror`), 설치는 `osrdnHookInstall` 첫머리(take 검사 **앞**, 빈 필드에만, 남의 것은 `finishForeign`).  UpdateState: `!yUp` 이면 받던 상태도 카드에서 뺀다(`notUp`).  계수기 넷은 `OSRDNMesaHook.h`.
- **radeon** `mesa/OSRDNMesaSurface.c` `osrdn_surf_take`: `appRowPixels != width` 거절(전에는 `<`).
- **teapot**: `glFinish` 직후 자기 배열을 떠서 GetColorBuffer 결과와 바이트 비교, `step=finish-sync same= differ= finishes= fmirrors= foreign= notup=`.
- 검사기: `check_hook` 규칙 `m3g-finish-sync` + 변이 5(되복사 없음 / 묶음 전 복사 / 묶이지 않은 문맥 복사 / yUp 거절 삭제 / 긴 행 허용) 전부 잡힘; 설치 줄은 `INSTALL_WRITES` 에 **이름으로** 등록(규칙 완화 아님), UpdateState 허용 목록에 `notUp`.  `audit_hooks` 가 형식 게이트를 요구(게이트를 `1 ||` 로 무력화한 변이 FAIL 확인).  `judge_teapot`: finish-sync 없음·same 0·fmirrors 0 을 FAIL(자체시험 3 종), 정상 짝의 ok 줄 수 4→6.
- 인용: `osmesa.c` 편집 전 판을 되살려 `reaim_diff` 10 키.  matrox 문서의 `osmesa.c` 줄 인용은 오늘 전부터 이미 옛 판 기준(예 GetColorBuffer 860)이라 건드리지 않는다.

## 8. 결과 (부팅 00d2c737, 드라이버 0b22f49d 그대로, 라이브러리 1790272400, teapot 1790272500, 실행 790337262) — **PASS, 재부팅 0 회**

`python3 tools/mesa/judge_teapot.py build/m3a/1790272500` → `judge_teapot: PASS`.

| 실행 | finish-sync | 그림 |
|---|---|---|
| 가속 64×64 CARD | `same=1 differ=0 finishes=1 fmirrors=1` | 6,400 전부 카드, 549 화소 차(덩어리 0) — M3a 와 같은 값 |
| 가속 128×128 GUARD | `same=1 differ=0 finishes=1 fmirrors=1` | 스톡과 바이트 단위 같음 |
| 가속 64×64 CULL | `same=1 differ=0 finishes=1 fmirrors=1` | 3,491 + 2,909 = 6,400, 20 화소 차(덩어리 0) |
| 스톡 셋 | `same=1 finishes=0`(훅 없음, 자기 배열에 직접) | 기준 |

`same=1` 은 "둘 다 검다" 가 아니다: 비교 상대인 GetColorBuffer 그림이 스톡과 대조해 PASS 한 그 그림이다.  M3a 첫 실행은 같은 자리에서 4,096 화소 전부 (0,0,0) 이었다(§A 13-3).

**G1 항목 1(glFinish) 닫힘.**  남은 일: matrox 라이브러리는 다음에 다시 빌드할 때 새 osmesa.o(형식 게이트)를 받는다 — **matrox 실기 회귀는 카드를 바꿔 끼울 때**.
