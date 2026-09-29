# M3b — 뒷면 컬링과 양면 조명을 받는다 (라이브러리만, 재부팅 없음)

선행: M3a(`docs/M3A_PLAN.md` 8, 14 의 A).  **이 문서는 코딩 전에 쓴다.**

## 1. 왜

분류기는 `DD_SW_SETUP` 의 비트가 **하나라도** 서면 상태 전체를 거절한다
(M3b 이전 판 OSRDNMesaClass.c 138-139행).  그 안에 **뒷면 컬링**이 있고, 실제 GL 응용은 거의 다
`glEnable(GL_CULL_FACE)` 를 켠다 — 그러면 삼각형이 하나도 카드로 안 간다.

## 2. 비트마다 — Mesa 가 우리보다 먼저 무엇을 하나 (읽은 것)

| 비트 | Mesa 가 우리 함수 전에 | 우리 훅 | 판정 |
|---|---|---|---|
| `DD_TRI_CULL` | `render_triangle` 이 뒷면이면 **우리를 부르지 않고 반환**(`vbrender.c:292-293`); 또는 정점 버퍼 단계에서 걸러 **컬링 표**를 쓴다(`vbrender.c:679-680`) | 살아남은 것만 받는다 | **받는다** |
| `DD_TRI_LIGHT_TWOSIDE` | 부르기 직전에 `VB->ColorPtr = VB->Color[facing]` | 색을 `VB->ColorPtr` 에서 읽는다(`OSRDNMesaHook.c:954`) | **받는다** |
| `DD_TRI_OFFSET` | `offset_polygon` 이 `ctx->PolygonZoffset` 를 계산 | z 를 `VB->Win.data[][2]` 에서만 읽는다 — **offset 을 안 더한다**(`OSRDNMesaHook.c:1005`) | 계속 거절 |
| `DD_TRI_UNFILLED` | 선·점 경로 — 소프트웨어가 Mesa 의 깊이로 그린다 | — | 계속 거절(깊이가 섞인다, M1i) |
| `DD_TRI_CULL_FRONT_BACK` | `null_triangle`; 사각형 경로는 따로 따질 것이 남는다 | — | 계속 거절(드물다) |

## 3. 묶음 경로를 먼저 막는다

우리 묶음 raw 표(`osrdnRenderVBTriangles`)는 `ctx->TriangleFunc` 를 **거치지 않고** 카드로 보낸다.
컬링이 `render_triangle` 에서 일어나는 설정이면 묶음 모드에서 **뒷면이 카드로 간다.**  그리고
M3a §11 D3 — 거절된 상태에서도 묶음 표가 다시 깔린다 — 도 같은 자리다.

고침: `osrdnRenderVBTriangles` 는 **`ctx->TriangleFunc == osrdnHookTriangle` 일 때만** 카드로
보낸다.  그 조건은 (가) 분류기가 이 상태를 받았고(우리 함수가 `Driver.TriangleFunc` 로 설치됨)
(나) Mesa 가 그 사이에 `render_triangle` 같은 준비 함수를 끼우지 않았다는 뜻이다
(`vbrender.c:758-775`).  아니면 저장해 둔 Mesa 의 raw 함수로 간다.  묶음은 기본 꺼짐.

## 4. 바꾸는 것

| 자리 | |
|---|---|
| `OSRDNMesaClass.c` | 거절 마스크를 `DD_SW_SETUP_` 에서 **`DD_TRI_OFFSET | DD_TRI_UNFILLED | DD_TRI_CULL_FRONT_BACK`** 로 좁힌다 |
| `OSRDNMesaHook.c` | §3 의 조건 한 줄 |
| `tools/mesa/sim_class.py` | 줄: 컬링 **받음**, 양면 **받음**, 컬링+양면 **받음**, offset·unfilled·앞뒤컬링 **거절** 유지; 변이 |
| `tools/mesa/check_hook.py` | §3 조건이 있는지 규칙 + 변이 |

## 5. 실기 판정 — 주전자로

`test/osrdn-mesa-teapot.c` 에 선택 인자 하나: **뒷면 컬링 + 양면 조명**.  64×64, 두 링크.

- 계수기: 위임 0, 거절 0, `submitted > 0`, 그리고 **`submitted < 64·grid²`**(뒷면이 걸러졌다).
  컬링된 수는 미리 모른다 — 그래서 그림이 판정한다:
- 그림: 스톡(같은 상태)과 M3a 의 면적 규칙 — 뒷면이 그려졌거나 색이 반대면이면 **면적**이 바뀐다.

## 6. codex 1 차 검토 — 판정, 그리고 **내 §2 의 컬링 판단은 틀렸다**

| # | codex 주장 | 내 확인 | 판정 |
|---|---|---|---|
| E1 | **컬링만 켜면 아무도 컬링하지 않는다**: 소프트웨어 래스터 비트가 서 있으면 Mesa 가 `IndirectTriangles` 에서 `DD_TRI_CULL` 을 뺀다 — 소프트웨어 삼각형 함수가 **스스로** 컬링하므로.  그 자리를 우리가 차지하면 정점 버퍼 컬링도(`vbcull.c:819`) `render_triangle` 도 안 돈다 | `state.c:1127-1130`, `vbcull.c:819`, 소프트웨어는 `tritemp.h:100`·`:150` 에서 스스로.  **저장소의 모형이 이미 이것을 단언한다**: `sim_trifunc.py:202-203` "D12: with culling on and us installed, NOBODY culls" | ✅ — **§2 의 첫 줄과 §3 의 "묶음 조건이면 된다" 가 틀렸다.**  지금까지 컬링을 거절해 온 이유가 이것이었다 |
| E2 | 양면 조명은 안전: `DD_TRI_LIGHT_TWOSIDE` 가 `render_triangle` 을 끼워 넣고, 그것이 facing 으로 `ColorPtr` 를 고른 뒤 우리를 부른다; 클리핑·스트립·사각형·평면 음영 `pv` 도 맞다 | `vbrender.c:307-310`(ColorPtr), `OSRDNMesaHook.c:954` | ✅ |
| E3 | **컬링+양면 시험은 컬링 단독의 결함을 가린다** — 양면이 `render_triangle` 을 끼워 넣어 그것이 대신 컬링하므로 | E1·E2 에서 따라 나온다 | ✅ — §7-3 에 **컬링 단독** 시험을 넣는다 |

## 7. 바뀐 설계 — 우리가 스스로 컬링한다

### 7-1. 식

소프트웨어가 하던 것을 우리가 한다.  `render_triangle`(`vbrender.c:283-293`) 과 같은 식:

    c = (x1-x0)*(y2-y0) - (y1-y0)*(x2-x0)          (VB->Win.data)
    c * ctx->backface_sign > 0   ->  그리지 않는다(컬링)

`tritemp.h` 는 꼭짓점을 Y 로 정렬하고 홀수 치환이면 부호를 뒤집는 다른 식을 쓴다.  두 식이
**같은 삼각형을 버리는지** python 으로 확인했다: 임의 삼각형 20 만 개 × 부호 {−1, 0, +1}(y 가 같은
경우 5 % 섞음) = 60 만 경우, **불일치 0**.

`backface_sign` 은 `state.c:1036-1064` 가 컬링 모드·앞면 방향으로 정한다(0 이면 컬링 없음,
앞뒤 모두면 0 이고 `DD_TRI_CULL_FRONT_BACK` — 그 비트는 계속 거절).

### 7-2. 자리

`OSRDNMesaHook.c` 의 공통 본체 `osrdnTriangleWith` — 삼각형별 경로와 묶음 경로가 **둘 다**
지나는 곳 — 에서 보내기 전에.  계수기 `culled` 를 새로 센다.  §3 의 묶음 조건은 그대로 둔다
(M3a §11 D3 를 닫는다).

### 7-3. 실기 판정 — 셋, 그리고 첫째가 핵심

| 상태 | Mesa 가 먼저 컬링하나 | 기대 |
|---|---|---|
| **컬링 단독** | 아니오 — **우리만** | `submitted + culled == 64·grid²`(독립 기대값이 되살아난다), `culled > 0`, 위임 0; 그림은 스톡(같은 상태)과 면적 규칙 |
| 양면 단독 | — | `submitted == 64·grid²`, 그림 대조 |
| 컬링 + 양면 | 예(`render_triangle`) | 우리 `culled == 0`, `submitted < 64·grid²`, 그림 대조 |

## 8. codex 2 차 검토(7 절) — 없음, 확인함.  그리고 **양면 조명은 빼야 한다** (내가 찾음)

codex: 자체 컬링은 Mesa 소프트웨어와 다른 결과를 내지 않는다 — 클리핑 fan 은 방향을 지키고
(`vbrender.c:237-241`), 스트립 parity 는 우리와 소프트웨어가 같은 순서를 받고, `backface_sign` 은
`glBegin` 때 갱신되며(`vbfill.c:83-84`), 훅은 받은 순서를 그대로 쓴다(`OSRDNMesaHook.c:892-894`).
주의점 하나: Mesa 와 같은 `GLfloat` 식·순서·엄격한 `> 0`(`vbrender.c:283-288`).  전부 원문으로 확인.

**그러나 양면 조명은 묶음의 재생을 깬다.**  `gen_tri_prologue.py` 가 이미 지키는 불변식
(`gen_tri_prologue.py:727-733`): 묶음 전송이 실패하면 묶음을 소프트웨어 함수로 **재생**하는데,
그것은 분류기가 offset 과 양면 조명을 거절하기 때문에만 맞다 — 둘 다 삼각형 호출 **직전에**
문맥에 값을 넣고(`VB->ColorPtr = VB->Color[facing]`) 직후에 되돌리므로, 나중에 재생하면 틀린
값을 읽는다.  codex 의 "양면 안전" 은 보내는 경로만 본 것이다.

**컬링은 재생해도 안전하다**: 우리가 컬링한 삼각형은 묶음에 들어가지 않고, 들어간 삼각형은
소프트웨어(`tritemp.h`)도 같은 식으로 앞면이라 판정한다(§7-1, 60 만 경우 불일치 0).  컬링은
삼각형마다 문맥을 바꾸지 않는다.

### 8-1. 그래서 이 칸은 **컬링 하나만** 받는다

| 비트 | 판정 |
|---|---|
| `DD_TRI_CULL` | **받는다** — 우리가 스스로 컬링(§7) |
| `DD_TRI_LIGHT_TWOSIDE` | 계속 거절(재생) |
| `DD_TRI_OFFSET`·`UNFILLED`·`CULL_FRONT_BACK` | 계속 거절 |

거절 마스크는 `0x00400660 & ~DD_TRI_CULL` = **`0x00400260`**.  이름을 `DD_DECLINE_` 로 따로 두고,
`gen_tri_prologue.py` 의 자체시험이 offset·양면 비트를 **그 마스크**(실제로 거절하는 것) 안에서
찾게 고친다 — 지금은 `DD_SW_SETUP_` 을 보는데, 앞으로 둘이 다르다.

실기 판정은 §7-3 의 **첫 줄(컬링 단독)** 만 한다.

## 9. 구현 — 호스트까지

| 자리 | 무엇 |
|---|---|
| `OSRDNMesaClass.c` | `DD_DECLINE_ 0x00400260` — `DD_SW_SETUP_` 에서 컬링 비트만 뺀 것.  분류기는 이 마스크로 거절 |
| `OSRDNMesaHook.c` `osrdnTriangleWith` | 호출 수를 센 직후, 보내기 전에 `render_triangle` 의 식 그대로 자체 컬링, 계수기 `culled` |
| `OSRDNMesaHook.c` `osrdnRenderVBTriangles` | `ctx->TriangleFunc != osrdnHookTriangle` 이면 카드로 안 보낸다(M3a D3 도 닫음) |
| `tools/mesa/gen_tri_prologue.py` | 재생 불변식을 `DD_DECLINE_`(실제로 거절하는 마스크)에 대해 검사 |
| `tools/mesa/sim_class.py` | 컬링 **받음**, 컬링+양면·컬링+offset **거절**; 변이 셋(마스크가 컬링을 다시 거절 / offset 을 놓침 / 양면을 놓침) |
| `tools/mesa/check_hook.py` | `m3b-we-cull`(식 그대로, 호출 수와 보내기 사이) · `m3b-group-only-ours`; 변이 셋(컬링 삭제 / 부호 반대 / 묶음 조건 삭제) — 모두 잡힘 |
| 주전자 | `cull` 인자(뒷면 컬링만, 양면 없음), `culled` 출력; 판정기에 `CULL`(`sent + culled == 64·grid²`, `culled > 0`) + 자체시험 셋 |

호스트: `sim_class`·`check_hook`·`sim_trifunc`·`gen_tri_prologue`·`sim_pack`·`sim_batch`·`sim_texrun`·
`sim_probe`·`check_compile`·`judge_teapot` 모두 PASS.
