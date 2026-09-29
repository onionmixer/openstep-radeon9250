# M1d — 첫 하드웨어 삼각형 (계획, 코딩 전)

기준일 2026-09-22.  선행: M1c 완료(`docs/M1C_PLAN.md` 9).
**이 문서는 코드보다 먼저 쓰였다.**

## 1. 이 칸의 한 줄

**우리가 그릴 수 있다고 분류한 상태에서, 삼각형 하나가 카드로 간다.**

그 외의 모든 상태는 지금처럼 소프트웨어가 그린다.  그리고 **거절이 삼각형을 잃어서는 안 된다** —
선례가 이걸 놓쳐 프로세스의 가속을 통째로 회수하는 일을 두 번 겪었다.

## 2. 이미 있는 것

| | | |
|---|---|---|
| 제출 통로 | R7b: `ioctl(SUBMIT)` + 배치 창, 순수 C | 실기 PASS |
| 검증기 | R7a: 13 규칙, 허용 레지스터 41 개와 값 마스크 | 실기 PASS |
| 표면 | M1c: Mesa 가 카드 오프스크린에 그린다 | 실기 PASS |
| 래스터 규칙 | R6d·R6e·R6f: 1/16 절삭·표본 +1/2·top-left·구로 가중치·깊이 | 실측 확정 |
| 게이트 | M1a 프로브, M1b·M1c 의 규칙·판정기 | 전부 PASS |

M1d 는 **새 통로를 만들지 않는다**.  기존 넷을 잇는다.

## 3. 거절이 삼각형을 잃지 않게 하는 법 — 직접 읽어 확인

| | 사실 | 근거 |
|---|---|---|
| D1 | `choose_triangle_function` 이 non-NULL 을 주는 것은 `RasterMask` **8192 조합 중 1 개**뿐 | `build/m1b/design1.py` |
| D2 | 그러므로 **저장한 포인터로 폴백할 수 없다** | D1 |
| D3 | 그러나 `gl_set_triangle_function(ctx)` 는 **모든 상태에 대해 진짜 함수를 고른다**(스무스·오클루전·텍스처·일반) | `triangle.c:1476-1523` |
| D4 | **단, 그 함수는 `ctx->Driver.TriangleFunc` 가 이미 있으면 그냥 돌아간다**("Device driver will draw triangles") | `triangle.c:1529-1533` |
| D5 | 따라서 순서는 **NULL 로 지우고 → 부르고 → 고른 것을 저장하고 → 우리 것을 설치** | D3+D4 |
| D6 | Mesa 는 상태가 바뀔 때마다 이 포인터를 다시 정하므로, 설치는 **매 `UpdateState`** 마다 | `osmesa.c:2010-2027` |
| D7 | `gl_render_vb` 는 디스패치 표를 **루프 앞에서 래치**하므로 중간 교체는 불가 — **위임만이 방법** | `vbrender.c:652-680` |

**그래서 우리 삼각형 함수는 이렇게 생겨야 한다**: 이 삼각형을 카드로 보낼 수 있으면 보내고,
**보낼 수 없으면 저장해 둔 소프트웨어 함수를 그 자리에서 부른다.**  삼각형은 어느 쪽으로든
그려지고, 잃지 않는다.

## 3b. 설치했다고 불리는 것이 아니고, 불린다고 안전한 것도 아니다

*(이 절은 한 번 틀리게 썼다가 고쳤다.  처음엔 `render_triangle` 을 "우리를 건너뛰는 것" 으로 읽었는데,
열어보니 **마지막 줄에서 우리를 부르는 포장지**였다.  아래는 전부 원문을 연 결과다.)*

렌더 루프가 부르는 것은 `ctx->Driver.TriangleFunc` 가 아니라 `ctx->TriangleFunc` 이고
(`vbrender.c:214` · `:230` · `:241` · `:272` · `:488` · `:490` · `:543` · `:545`), 그 값은 프레임 앞에서 한 번 정해진다
(`vbrender.c:740-758`):

```c
ctx->TriangleFunc = ctx->Driver.TriangleFunc;
ctx->ClippedTriangleFunc = ctx->TriangleFunc;
if (ctx->IndirectTriangles & DD_SW_SETUP) {
    ctx->ClippedTriangleFunc = render_triangle;
    if (ctx->IndirectTriangles & (DD_SW_SETUP & ~DD_TRI_CULL)) {
        if (ctx->IndirectTriangles & DD_TRI_CULL_FRONT_BACK) ctx->TriangleFunc = null_triangle;
        else                                                 ctx->TriangleFunc = render_triangle;
    }
}
```

`ctx->IndirectTriangles = ctx->TriangleCaps & ~ctx->Driver.TriangleCaps;` 다음
`|= DD_SW_RASTERIZE` (`state.c:1092-1093`).

| | 사실 | 확인한 곳 |
|---|---|---|
| D8 | `DD_SW_SETUP` = `0x00400660` = CULL·CULL_FRONT_BACK·OFFSET·LIGHT_TWOSIDE·UNFILLED | `types.h:1521-1525`, python 으로 전개 |
| D9 | 무조건 OR 되는 `DD_SW_RASTERIZE` = `0x003c0000`, **교집합 0** | 같은 계산 — 그 OR 만으로는 아무 분기도 안 탄다 |
| D10 | `render_triangle` 은 우회가 **아니다**: 오프셋·양면을 VB 에 적용한 뒤 `(*ctx->Driver.TriangleFunc)` 로 **우리를 부른다** | `vbrender.c:229-279`, 호출은 `vbrender.c:321` |
| D11 | 단 `UNFILLED` 면 그 자리에서 `unfilled_polygon` 으로 빠져 **우리는 안 불린다**; `CULL_FRONT_BACK` 이면 `null_triangle` 이라 아무것도 안 그린다(그게 맞다) | `vbrender.c:318` · `vbrender.c:330-333` |
| D12 | **후면 컬링은 삼각형 함수 안에 있다**: `area * bf < 0.0` 이면 반환, `area == 0.0` 도 반환 | `tritemp.h:147-151`, `bf` 는 `tritemp.h:100` |
| D13 | `bf = ctx->backface_sign`(`GL_BACK`+`CCW` → −1, `GL_FRONT`+non-`CCW` → −1, 컬링 끄면 0), **Y 정렬 6 경우 중 3 경우에서 부호가 뒤집힌다** | `state.c:1018-1040`, `tritemp.h:117` · `:122` · `:125` |

| D19 | VB 단계에도 컬링이 있다(`vbcull.c:819`, `idx |= 0x1` 이 `DD_ANY_CULL` 일 때) — **그러나 우리가 설치하면 그 경로가 꺼진다**: `state.c:1127-1130` 의 조건이 `DD_TRI_SW_RASTERIZE|DD_QUAD_SW_RASTERIZE|DD_TRI_CULL` 인데 앞의 둘은 1093 이 항상 넣으므로, 앱이 컬링을 켜면 조건이 성립해 **`IndirectTriangles` 에서 `DD_TRI_CULL` 이 지워진다** | `vbcull.c:819`, `types.h:1529-1531`, `state.c:1127-1130` |
| D20 | **그래서 거절 조건은 `IndirectTriangles` 가 아니라 `ctx->TriangleCaps` 로 재야 한다.** 1130 은 `IndirectTriangles` 만 지우고 `TriangleCaps` 는 그대로 두므로, `IndirectTriangles` 로 재면 **컬링이 켜진 것을 못 본다** | 같은 줄들 |

**그래서 진짜 위험은 우회가 아니라 이것이다**: `DD_TRI_CULL` 만 켜면 안쪽 시험이 그 비트를 빼므로
`ctx->TriangleFunc` 는 **우리 것 그대로**인데, 자르는 코드는 우리가 대신한 그 함수 안에 있었다.
즉 **우리가 안 자르면 아무도 안 자르고, 뒷면이 그려진다.**  이건 그림이 조용히 틀리는 종류의
실패이고, 픽셀 동일성 게이트가 바로 잡아낼 것이다 — 하지만 설계에서 먼저 막는다.

**이 절 전체는 산문이 아니라 계산으로도 있다**: `tools/mesa/sim_trifunc.py` 가 `types.h` 에서
`DD_*` 상수를 읽어 위 다섯 파일의 결정을 그대로 모의하고, D8–D20 을 자기검사 17 항목으로 확인한다
(`sh tools/check-all.sh` 에 등록).  표를 보려면 인자 없이 실행한다.  *(이 모형도 한 번 틀렸다 —
`render_triangle` 의 `UNFILLED` 분기를 빼먹어, 라벨은 "우리를 빼놓는다" 인데 값은 `-> ours` 였다.
모형이 소스가 아니라 산문에 동의하고 있었다.)*

**결정**: M1d 의 분류기는 `ctx->TriangleCaps & DD_SW_SETUP` 이 0 이 아니면 `WOULD_DECLINE` 한다.
하나의 조건으로 D11 의 두 경우와 D12 의 컬링을 전부 덮고, 그 마스크는 Mesa 자신이 쓰는 마스크다.
`Driver.TriangleCaps` 는 0 으로 둔다(선언하지 않는다) — 그래야 위 식에서 `IndirectTriangles` 와
`TriangleCaps` 의 `DD_SW_SETUP` 부분이 같아진다.  **그 0 을 런타임에 확인**하고, 0 이 아니면 거절한다:
가정이 조용히 깨지는 것보다 계수에 잡히는 편이 낫다.

## 3c. 설치 지점 — 한 번의 `UpdateState` 가 하는 일 전부

훅이 언제 불리고 그 뒤 무엇이 우리 포인터를 건드리는지, 한 줄도 건너뛰지 않고 적는다.
(codex 회신은 1111 에서 1136 으로 건너뛰었고, **그 사이 1124 가 설계를 정한다.**)

```
state.c 1100   Driver.TriangleFunc = NULL                      ← 매번 지운다
state.c 1111   Driver.UpdateState(ctx)
                 osmesa.c 1997   = choose_triangle_function(ctx)
                 osmesa.c 2013   OpenStepMesaAccelUpdateState  ← 우리 훅
state.c 1121   if (IndirectTriangles & DD_SW_RASTERIZE)        ← 1093 이 무조건 OR → 항상 참
state.c 1124     gl_set_triangle_function(ctx)
                   triangle.c 1528  NoRaster      → null_triangle      (우리 것 교체)
                   triangle.c 1532  이미 non-NULL → **return, 우리 것 유지**
                   triangle.c 1539  SmoothFlag    → AA (우리가 NULL 일 때만)
                   triangle.c 1683/1687  FEEDBACK/SELECT → 교체 (GL_RENDER 블록 밖)
state.c 1136   gl_set_render_vb_function(ctx)  → vbrender.c 758 이 ctx->TriangleFunc 로 복사
```

| | 사실 | 확인한 곳 |
|---|---|---|
| D14 | **`Driver.TriangleFunc` 가 non-NULL 이면 Mesa 는 그대로 둔다** — 이것이 문서화된 드라이버 훅 지점이다(`dputs("Driver triangle")`) | `triangle.c:1529-1533` |
| D15 | 단 `NoRaster` 는 그 시험 **앞**(`triangle.c:1528`), `GL_FEEDBACK`·`GL_SELECT` 는 `GL_RENDER` 블록 **밖**(`triangle.c:1683` · `:1687`) → 그 세 상태에서는 Mesa 가 우리를 **알아서 치운다** | 같은 파일 |
| D16 | `SmoothFlag`(AA) 검사는 1532 **뒤**라, 우리가 설치하면 AA 가 통째로 사라진다 → 분류기가 거절해야 하고, **이미 한다**(`OSRDNMesaClass.c:71-288`) | `triangle.c:1539` |
| D17 | `Driver.TriangleFunc` 를 쓰는 곳은 `state.c:1100`(NULL), `osmesa.c:2011`, `triangle.c` 15줄, `aatriangle.c` 6줄뿐 — **전부 그 한 필드만** 쓴다 | 저장소 전수 grep |
| D18 | `state.c` 1127–1130: SW 래스터라이즈일 때 `IndirectTriangles` 에서 `DD_TRI_CULL` 을 **지운다** — Mesa 자신이 "삼각형 함수가 자른다"(D12)를 전제하고 있다는 반대쪽 증거 | `state.c:1127-1130` |

**따라서 설치 방법**(D5 그대로, 근거만 바뀜): 훅에서 분류가 `WOULD_TAKE` 일 때만
`Driver.TriangleFunc = NULL` 로 되돌리고 `gl_set_triangle_function(ctx)` 를 **우리가 불러**
Mesa 가 고른 소프트웨어 함수를 받아 보관한 뒤, 그 자리에 우리 것을 넣는다.  D17 이 그 호출을
안전하게 만들고, D14 가 1124 에서 살아남게 하고, D15 가 위험한 세 상태를 공짜로 막는다.
`WOULD_DECLINE` 이면 **아무것도 하지 않는다** — 그러면 1124 가 평소대로 고른다.

**분류기에 빠진 것 하나**: `ctx->Light.ShadeModel`.  현재 훅이 읽는 `smooth` 는
`ctx->Polygon.SmoothFlag`(안티앨리어싱)이지 셰이딩 모델이 아니다(`OSRDNMesaHook.c:1740-1915`).
D14 때문에 우리가 설치하면 1655–1678 의 flat/smooth 선택이 통째로 건너뛰어지므로,
**M1d 가 flat 만 그린다면 분류기가 `ShadeModel != GL_FLAT` 를 거절해야 한다.**  입력에 추가한다.

## 3d. codex 교차검토 판정 (요청 `kho42npjd`)

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| `gl_set_triangle_function` 은 `Driver.TriangleFunc` 만 바꾼다 (`triangle.c:1523`) | 1523–1688 전체에서 `ctx->…=` 를 뽑아 좌변 전수 확인 | ✅ 사실 (1523 은 함수 시작줄) |
| `_mesa_set_aa_triangle_function` 도 같은 포인터만 (`aatriangle.c:387`) | 실제 함수는 **391** 행, 본문 대입 6개 전부 그 필드 | ✅ 사실 / 인용 4행 어긋남 |
| 훅에서 설치한 포인터를 `gl_set_render_vb_function` 이 복사한다 (`state.c:1111`→`1136`) | 두 줄 다 정확. **그러나 그 사이 1124 `gl_set_triangle_function` 을 빠뜨렸다** | ⚖️ 결론은 맞고 **근거가 틀렸다** — 살아남는 이유는 `triangle.c:1532` 의 조기 탈출(D14)이고 codex 는 그걸 한 번도 말하지 않았다 |
| 저장 함수를 우리 콜백 안에서 부르면 안전하다 (`tritemp.h:96`, `triangle.c:144`) | 96 정확; 144 는 함수 시작줄이고 `VB->ColorPtr->data[pv]` 는 153–156 (codex 표기 `VB->ColorPtr[pv]` 는 틀린 철자) | ✅ 사실 / 인용·표기 어긋남 |
| 래치는 `RenderVB*Tab` 이고 삼각형 단위 혼합이 가능하다 (`vbrender.c:676`·`540`) | 실제 래치는 **680·682·684**, 호출은 **543·545** | ✅ 사실 / 인용 4·3행 어긋남 |
| 현재 제출 통로는 반환 전 GPU idle + dst-cache flush (`osrdn_cp.m:3494`·`2648`) | 2638 ✅ 퍼지, 링 안 `C_WAIT_IDLE` 은 **2640**, `cpWait` 는 **2653**; 2648 은 제출 호출 | ✅ 사실 / 인용 어긋남 |
| 분류기에 `RenderMode`·`NoRaster` 가 없어 그 상태에서 하드웨어를 고를 수 있다 | `triangle.c` 1528·1683·1687 을 열었다 — **그 세 상태에서는 Mesa 가 우리 포인터를 치운다**(D15) | ❌ **기각**.  거절해도 해롭진 않지만 codex 가 든 이유는 성립하지 않는다 |
| 분류기에 `Light.ShadeModel` 이 없다 | `OSRDNMesaHook.c` 90 의 `smooth` 는 `Polygon.SmoothFlag`; ShadeModel 은 훅·분류기 어디에도 없음(전수 grep) | ✅ **채택** — 입력에 추가 |
| 16비트 `DEPTH_BIT` 를 허용한다 | `OSRDNMesaClass.c` 45·47 — 허용이 맞다 | ✅ 사실.  단 M1d 범위 문제이지 결함은 아님 |
| 저장 포인터는 컨텍스트별로 보관해야 한다 | 전역 하나면 두 컨텍스트가 다른 상태를 공유한다 — 반박 실패 | ✅ **채택** |

**codex 가 놓친 것**: D12(후면 컬링이 삼각형 함수 안에 있다)와 D14(1532 조기 탈출).
전자는 그림이 조용히 틀리는 결함이고 후자는 설치가 성립하는 이유 자체다.  둘 다 회신에 없다.

## 3e. codex 2차 교차검토 판정 (요청 `k9vq43eoa`) — 컬링 하나만 물었다

§3b 를 쓰고 나서, **"컬링을 우리가 해야 하는가"** 한 가지만 다시 물었다(한 호출 = 한 주장).

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| 후면 삼각형은 드라이버 `TriangleFunc` 에 **도달한다**, 그 전에 거르는 행은 없다 | `tools/mesa/sim_trifunc.py` 가 같은 답(`컬링만` 행의 "누가 자르나" = NOBODY); 소스도 열어 확인 | ✅ **채택** — D12 와 일치 |
| `glEnable(GL_CULL_FACE)` 가 `TriangleCaps` 에 `DD_TRI_CULL` 을 넣는다 (`enable.c:123`) | 123 은 `case GL_CULL_FACE:`, 실제 `TriangleCaps ^= DD_TRI_CULL` 은 **126** (XOR 이고 `CullFlag!=state` 로 감싸여 있다) | ✅ 사실 / 인용 3행 어긋남 |
| `backface_sign` 설정 (`state.c:1039`) | `if (ctx->Polygon.CullFlag) {` — 정확 | ✅ 사실 |
| `state.c:1127-1130` 은 **OpenGL 컬링을 끄는 코드가 아니다**; `TriangleCaps` 와 `backface_sign` 은 그대로이고, 상위 setup 이 중복으로 자르지 않도록 **래스터라이저에 컬링을 맡긴다**는 뜻이다 | D18·D19·D20 과 같은 결론.  특히 "`TriangleCaps` 는 그대로" 가 **D20 의 근거**다 | ✅ **채택** — 내 D18 을 더 정확히 말한 것 |
| `triangle.c:1532` 의 조기 탈출로 설치한 함수가 교체되지 않는다 | 이미 D14 | ✅ 사실 — **1차에서 빠뜨렸던 것을 2차에서 스스로 찾았다** |
| `tritemp.h:150-151` 에서 걸러진다 | 148 이 `area` 계산, 151 이 `if` — 정확 | ✅ 사실 |
| 단서: 우리 훅이 `DD_TRI_SW_RASTERIZE`/`DD_QUAD_SW_RASTERIZE` 를 직접 지우면 결론이 달라진다 | 지우지 않는다.  `osmesa.c` 는 `IndirectTriangles`·`TriangleCaps` 를 **한 번도** 건드리지 않는다(전수 grep), `Driver.TriangleCaps` 를 쓰는 곳도 core/OSmesa 에 없다 | ✅ 타당한 단서, 전제 성립 확인 |

**2차 회신의 인용은 전부 정확했다**(1차는 여섯 개가 어긋났다).  그리고 두 번 다 같은 결론에
도달했다: **우리가 설치하면 후면 컬링은 우리 몫이다.**  1차에서 놓쳤던 `triangle.c:1532` 를
2차에서는 스스로 인용했다 — 같은 모델이라도 질문이 좁으면 답이 낫다는 근거로 남긴다.

## 4. 무엇을 보내는가

R6 가 이미 측정한 그대로다 — 창 좌표 정점, TCL 우회, `3D_DRAW_IMMD_2`.
M1d 는 **가장 좁은 경우 하나**만 켠다:

- 색만(깊이 없음, 블렌드 없음, 텍스처 없음) — 즉 분류기가 `WOULD_TAKE` 라 한 상태
- 평면 음영(`GL_FLAT`) 하나부터.  구로는 M1e.

## 4c. 한 삼각형이 정확히 어떤 워드 열인가 — 정본과 계산

정본은 `tools/r6/tri_oracle.py` 의 `draw_words()` 이고, 클라이언트가 보낼 수 있는 형태는
`tools/r7/verify_oracle.py` 의 `stream_u1()` 이다(드라이버가 스스로 넣는 `WAIT_UNTIL` 쌍을 뺀 것).
**M1d 는 이 모양을 C 에서 런타임에 만든다.**

python 으로 센 수(손으로 세지 않았다):

| | |
|---|---|
| `draw_words('T1')` 전체 | 65 워드(드라이버 꼬리 포함) |
| 클라이언트 형태 `stream_u1()` | **53 워드** |
| 그중 본체 = `VF_CNTL` + 정점 3 × 5 워드 | **16 워드** |
| 따라서 서두(상태·픽셀·클립) + PKT3 헤더 | **37 워드** |
| ioctl 한 번의 상한 | 2016 워드 |

정점 하나는 `(x, y, z, w, 색)` 다섯 워드 — `x·y·z·w` 는 IEEE 754 비트, 색은 한 워드.

드라이버 검증기가 클라이언트 스트림에 거는 조건(`osrdn_cp.m` 2110–2165 을 읽어 확인):

| | 조건 | 어기면 |
|---|---|---|
| S1 | PKT3 는 **`3D_DRAW_IMMD_2`(op 0x35) 하나뿐** | `WHY_P3_OP` |
| S2 | `VF_CNTL` 은 ring walk + TRIANGLES, 정점 수 > 0 이고 3 의 배수 | `WHY_VF` |
| S3 | **`SE_VTX_FMT_0` 를 클라이언트가 직접 써야 한다** — 프리픽스가 정의해도 | `WHY_VTX_UNSET` |
| S4 | 데이터 워드 수 − 1 == 정점당 워드 × 정점 수 | `WHY_COUNT` |
| S5 | 색 오프셋과 색 피치는 **둘 다 쓰거나 둘 다 안 쓰거나** | 짝이 안 맞으면 거절 |
| S6 | 쓴 표면 주소는 창 안에 들어와야 한다(`cpR7SurfaceFits`) | 거절 |
| S7 | 허용 레지스터·허용 값 밖이면 거절 | `WHY_P0_REG` / `WHY_P0_VALUE` |

**표면 주소는 클라이언트가 쓴다**: 서두의 고정 워드에는 winStart 가 들어 있지 않고
(`fixup_mask(stream_u1())` 가 전부 0 — python 으로 확인), M1d 는 M1c 가 매핑한 그 창에
그려야 하므로 `RB3D_COLOROFFSET`·`RB3D_COLORPITCH` 를 **CAPS 의 `winStart` 로부터** 만들어 쓴다.
파일에 카드 주소를 적지 않는 것은 M1c 의 `m1c-no-constant-address` 규칙과 같은 이유다.

## 4d. 깊이를 끄는 것은 "안 켜는 것" 이 아니다 — 두 비트를 지워야 한다

R6 의 서두를 그대로 쓰면 **깊이 테스트와 깊이 쓰기가 켜진 채로** 나간다.  python 으로 디코드:

| 레지스터 | 서두의 값 | 비트 | 결과 |
|---|---|---|---|
| `RB3D_ZSTENCILCNTL`(0x1c2c) | `0x42227072` | `R200_Z_WRITE_ENABLE` = 1<<30 (`r200_reg.h:155`) | **1 — 깊이를 쓴다** |
| `RB3D_CNTL`(0x1c3c) | `0x00001902` | `R200_Z_ENABLE` = 1<<8 (`r200_reg.h:194`) | **1 — 깊이로 시험한다** |

그리고 드라이버 프리픽스는 `RB3D_DEPTHOFFSET = winStart + CP_R6_DEPTH_OFF` 이고
`CP_R6_DEPTH_OFF` 는 **0** 이다(`osrdn_cp.h:312`).  M1c 가 매핑한 표면도 `winStart + 0` 이다
(`OSRDNMesaSurface.c` 의 `mmap` 이 `caps->winStart` 를 오프셋으로 준다).

**즉 그대로 보내면 깊이 버퍼가 M1c 의 색 표면 위에 쓴다.**  그림이 망가지고, 그것도
"래스터가 틀렸나" 처럼 보이는 방식으로 망가진다.  R6 의 색 버퍼가 `winStart + 0x3c000`
(`osrdn_cp.h:313`)에 있어서 R6 사다리에서는 겹치지 않았을 뿐이다.

**그러므로 M1d 의 서두는 그 두 비트를 적극적으로 지운다**, 그리고 생성기가 그것을
자기검사로 확인한다(지워졌다고 적는 것과 지워진 것은 다르다).  깊이를 켜는 칸이 오면
그때 표면 배치를 먼저 정한다 — 두 표면이 같은 주소에 있는 한 깊이는 켤 수 없다.

## 7. 구현 순서 (이 순서를 지킨다)

1. **서두를 생성한다** — `tools/mesa/gen_tri_prologue.py` 가 위 오라클에서 37 워드 서두를
   뽑아 `mesa/OSRDNMesaTriTable.h` 로 쓴다.  손으로 적지 않는다(R7a 의 `--c-cases` 와 같은 방식).
   표면 주소를 담는 자리는 마스크로 표시해 C 가 `winStart` 를 더한다.
2. **분류기**(`OSRDNMesaClass.{c,h}`) — §4b 의 세 조건을 입력·사유와 함께 추가.
3. **삼각형 단위**(`mesa/OSRDNMesaTri.{c,h}`) — 배치 창 매핑, 워드 조립, `SUBMIT`,
   그리고 **보낼 수 없으면 보관한 소프트웨어 함수 호출**.
4. **훅**(`OSRDNMesaHook.c`) — 설치·해제와 컨텍스트별 보관.
5. **호스트 검사** — `check_hook.py` 에 규칙과 변이, 그리고 우리가 만든 워드를
   `tools/r7/verify_oracle.py` 오라클로 판정(게이트 B).
6. **타깃 빌드** + `nm -u`.  그다음에야 재부팅을 요청한다.

## 4b. 분류기·보관에 더해야 하는 것 (§3d 에서 채택한 둘)

1. **`ctx->Light.ShadeModel` 을 입력에 넣고 `GL_FLAT` 이 아니면 거절한다.**  D14 때문에 우리가
   설치하면 `triangle.c:1650-1673` 의 flat/smooth 선택이 통째로 건너뛰어진다 — 즉 구로를
   거절하지 않으면 **평면 함수로 구로 삼각형을 그리게 된다.**  현재 입력의 `smooth` 는
   `ctx->Polygon.SmoothFlag`(안티앨리어싱)이지 셰이딩 모델이 아니다(`OSRDNMesaHook.c:1740-1915`).
2. **저장한 소프트웨어 포인터는 컨텍스트별로 보관하고 매 `UpdateState` 에서 갱신한다.**
   전역 하나면 두 컨텍스트가 서로의 상태용 함수를 부른다.  M1c 가 표면 하나에 대해 소유자와
   결속을 두 필드로 나눈 것과 같은 이유이고, 같은 실수를 반복하지 않는다.
3. **`ctx->TriangleCaps & DD_SW_SETUP` 이 0 이 아니면 거절한다**(§3b).  이것이 D12 의 컬링과
   D11 의 `UNFILLED` 를 한 조건으로 덮는다.

세 가지 모두 게이트 A 의 규칙으로 들어가고, 각각 변이로 발동을 증명한다.

## 4e. 실기가 가르쳐 준 것: 제출 한 번에 ZPREP 한 번 (실측, 부팅 ed7bef6a)

첫 실기 실행에서 스트림은 **검증기를 통과**했는데(`why=0 at=57`) 그리지 않았다.
드라이버 로그가 이유를 말해 준다:

```
RDN-R7B submit boot=ed7bef6a words=57 rc=1 why=0 at=57 word=c00f3500 drawn=0
RDN-R5 zclear  boot=ed7bef6a n=8 arg=00000002 len=171 rc=1 why=26
```

`rc=1` 은 `CP_RC_REFUSED`, **`why=26` 은 `CP_WHY_NOT_PREPPED`** — "ZCLEAR without a
ZPREP since the last one"(`osrdn_cp.h:244`).  `-r7bSubmit:` 는 클라이언트 스트림을
**`CP_OP_ZCLEAR` 로 실어 보내므로**(`OSRDNDisplay.m:264`), R6a 가 깊이 측정을 위해 건
인터록이 그대로 적용된다.  R7b 의 러너도 그래서 제출마다 `zprep` 을 먼저 돌렸다
(`run_r7b.sh:92`).

| | 사실 | 뜻 |
|---|---|---|
| D21 | 제출 한 번에 **바깥에서 온 ZPREP 한 번**이 필요하다 | 라이브러리가 스스로 준비할 수 없다 — 그건 드라이버 쪽 연산이다 |
| D22 | 준비 없이 보내면 **거절이고 크래시가 아니다**, 그리고 삼각형은 폴백으로 그려졌다 | 인터록이 안전하게 동작했고 M1d 의 "잃지 않는다" 도 같은 실행에서 증명됐다 |

**그래서 M1d 는 이렇게 좁힌다**: 러너가 가속 실행 직전에 `zprep` 을 한 번 돌리고,
평면 장면은 **삼각형 하나**를 그린다.  이 칸의 주장은 "한 삼각형이 카드로 간다" 이지
"프레임이 카드로 간다" 가 아니다 — 후자는 드라이버가 제출마다 스스로 준비하게 고쳐야
하고, 그건 드라이버 변경이고 따라서 재부팅이며, M1d 다음 칸의 일이다.

*(첫 실행을 낭비로 적지 않는다: 설치·호출·세 상태 거절·폴백·손실 0·매핑 1 이 전부 그
실행에서 통과했다.  빠진 것은 제출 하나였고, 그 이유를 드라이버가 로그로 말해 주었다.)*

## 5. 게이트

- **A** 호스트: 규칙·변이.  새 규칙: 우리 삼각형 함수는 **보내지 못하면 반드시 저장한 함수를 부른다**(그 경로가 없으면 삼각형을 잃는다).
- **B** 호스트: 우리가 만드는 CP 워드를 **R7 검증기 오라클**(`tools/r7/verify_oracle.py`)로 판정 — 실기에 보내기 전에 호스트에서 통과해야 한다.
- **C** 실기, **한 승인 실행**: 제출 줄이 **0 에서 0 이 아닌 수로** 바뀌고, 그 실행의 그림이
  **`tools/r6/tri_oracle.py` 의 `cover(pts, MEASURED)` 예측과 픽셀 단위로 같다.**

  *(처음엔 "소프트웨어 그림과 픽셀 단위로 같다" 라고 썼는데 **틀렸다**.  M1c 는 소프트웨어가
  어디에 그리는지만 바꿨으니 동일성이 옳은 요구였지만, M1d 는 **래스터라이저 자체를 바꾼다** —
  카드의 채움 규칙(R6d: 1/16 절삭·표본 +1/2·top-left)과 Mesa `tritemp.h` 의 규칙이 모서리에서
  같을 이유가 없다.  그대로 뒀으면 성공한 실행이 실패로 보고됐을 것이다.)*
- **D** 실기: 소프트웨어 그림과의 차이는 **요구가 아니라 측정**이다 — 다른 화소 수와 그 위치를
  보고하고, 전부 모서리인지 확인한다.  안쪽 화소가 다르면 그건 규칙 차이가 아니라 결함이다.
- **E** 실기: 검증기가 거절하는 스트림을 일부러 만들어, **그 삼각형이 소프트웨어로 그려졌는지**를 계수로 확인한다 — 잃지 않는다는 것이 이 칸의 핵심 주장이다.
- **F** 실기: **설치 > 0 이면 삼각형 > 0**(D11).  설치만 되고 한 번도 안 불리는 것은 조용한 실패다.  같은 실행에서 `Driver.TriangleCaps == 0` 도 함께 보고한다(D10 의 전제).

## 6. 이 칸이 하지 않는 것

- 깊이·블렌드·텍스처를 켜지 않는다.
- 구로 음영을 켜지 않는다(M1e).
- 화면에 올리지 않는다.
- 드라이버를 바꾸지 않는다.  다만 **CP 가 돌아야 하므로 부팅당 한 주기를 쓴다.**

## 8. M1d 실기 PASS — 첫 하드웨어 삼각형 (2026-09-22, 부팅 `ed7bef6a`)

빌드 `790037508`, 실행 `790037518`.  **`judge_m1d: PASS`, 15 항목 전부.**

```
ok   flat installs   +1 -- our triangle function went in
ok   flat triangles  +1 -- and was actually CALLED
ok   flat submitted  +1 -- and a triangle reached the ring
ok   the seed was 790037519, from the environment
ok   flat delegated +0 -- nothing had to fall back
ok   smooth triangles +0 -- declined, so Mesa drew it      (SHADE_MODEL)
ok   cull   triangles +0 -- declined, so Mesa drew it      (TRI_SETUP)
ok   unbound triangles +2 == delegated +2 -- every one fell back
ok   unbound submitted +0 -- nothing drawn into a surface we do not hold
ok   nosw = 0 -- no triangle was lost
ok   the batch window was mapped 1 time(s)
ok   refused 0 + not-bound 2 == delegated 2
ok   276 pixels match the MEASURED rasterisation rule exactly
--   the software picture differs in 0 pixels, 0 of them NOT on the edge
```

핵심은 열세 번째 줄이다: 카드가 그린 276 화소가 `tri_oracle.cover(pts, MEASURED)`
예측과 **하나도 틀리지 않았다**.  보낸 정점은 `(4,4) (28,4) (4,28)`, 색 워드 `ffff0000`.
그리고 게이트 D 는 요구가 아니라 측정이었는데, **소프트웨어와도 0 화소 차이**가 나왔다 —
이 경우에는 두 채움 규칙이 마침 같았다는 뜻이고, 일반적으로 그래야 할 이유는 없다.

### 네 번의 실행이 가르쳐 준 것 (전부 로그가 말해 주었다, 재부팅 0 회)

| 실행 | 결과 | 원인 | 고친 곳 |
|---|---|---|---|
| 1 | 제출 0, 나머지 12 항목 PASS | `why=26 CP_WHY_NOT_PREPPED` — 제출은 CP 층에서 ZCLEAR 이고 앞에 ZPREP 이 필요하다 | 러너가 `zprep` 을 돌리고 평면 장면은 삼각형 하나 (§4e) |
| 2 | 제출 **1** ✅, 그림은 전부 검정 | 시험이 **앱 버퍼를 스냅샷 배열로 같이 썼다** — 뒤 단계가 덮었다 | 묶는 버퍼와 스냅샷을 분리 |
| 3 | 제출 0 | `why=13 CP_WHY_SEED` — 씨앗 카운터가 프로세스마다 1 부터 시작 | 씨앗 기준을 환경(`RDNMesaSeed`)에서 |
| 4 | 제출 1, 예측 276/276 일치, **소프트웨어와 210 내부 화소 차이** | 카드 색 버퍼는 ARGB8888, `OSMESA_RGBA` 는 R,G,B,A 바이트(`osmesa.c` 191–194) | 정점 색을 osmesa 가 준 시프트로 만들고 **바이트 0·2 교환** |
| 5 | **PASS** | | |

**이 네 번 모두 재부팅 없이 끝났다.**  드라이버를 바꾸지 않았고, CP 는 M1a 가 켜 둔 한
주기를 그대로 썼으며, 러너는 `cprunning` 을 **묻고** 이미 켜져 있으면 프리앰블을 건너뛴다.

### 이 칸이 남긴 제약 (다음 칸의 일)

- **제출 한 번에 ZPREP 한 번**(§4e).  프레임을 통째로 보내려면 드라이버의 `-r7bSubmit:` 이
  스스로 준비하도록 고쳐야 하고, 그건 드라이버 변경이므로 재부팅이다.
- **라이브러리는 CP 의 거절 사유를 못 본다**: `sb->why` 는 R7 검증기의 사유이고,
  `CP_WHY_SEED`·`CP_WHY_NOT_PREPPED` 는 `status=EIO` 로만 보인다.  실행 1 과 3 의 원인은
  `/usr/adm/messages` 를 읽어야 알 수 있었다 — 계수만 보고는 둘을 구별할 수 없다.
- 구로(M1e), 깊이, 텍스처는 분류기가 거절한다.  깊이는 **표면 배치를 먼저 정해야** 한다(§4d).

### 드라이버 자신의 증언 (픽셀과 독립)

```
RDN-R7B submit boot=ed7bef6a words=57 rc=0 why=0 at=57 word=c00f3500 drawn=1 subs=6
RDN-R5  zclear boot=ed7bef6a n=16 arg=2f17040f len=171 rc=0 why=0 us=98437
```

`arg` 은 라이브러리가 보낸 씨앗 **790037519** 그 자체이므로(python 으로 확인: `0x2f17040f`),
이 줄은 다른 실행의 것이 아니다.  `drawn=1`·`rc=0`·`us=98437` — 연산이 실제로 돌았다.
M1c 의 게이트 D("제출 줄 증분 0")가 **여기서 뒤집혔다.**

### 독립 재계수

`build/m1d/indep_m1d.py` 가 판정기와 **코드를 하나도 공유하지 않고**(numpy 없음, 자체 파서,
R6d 규칙을 정수 산술로 다시 씀) 같은 그림을 센다: **276 화소 재계수, 0 불일치.**
자체검사는 T1 이 276 화소를 덮는지와 훅의 색 워드가 원하는 화소를 남기는지를 확인한다.

