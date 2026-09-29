# G5-1a — 텍스처 업로드의 전수 되읽기를 표본으로 (라이브러리만, 재부팅 없음) (계획, 2026-09-29, 코딩 전)

## 0. 사실 (G5-0 §8-3, 전부 연 것)

- `osrdn_tex_upload_level`(몸체 `osrdnTexUploadLevelBody`, `OSRDNMesaTex.c:106-178`)은 텍셀을 VRAM 창에 쓴 뒤(`:135-143`) **모든 워드를 되읽어 대조**한다(`:145-177`).  128² 레벨 = 16,384 워드의 비캐시 PCI 읽기 ≈ 10 ms; G5-0 실측 레벨당 **10.9–11.1 ms**, 프레임의 10 %(시작 맵) / 27 %(데모).
- 되읽기가 거절한 적: GLQuake 전 실행에서 `texture: uploads N, refused 0`(`build/g50/g50-r*.log`, `build/g410/glq*.log`) — 0 회.
- 계수기의 소비처(codex §4 검증): `readBad`·`refused[READBACK]` 는 출력·계수뿐(`osrdn-mesa-tri.c:375-376`, shim `osrdn-mga-shim.h:119`·`:123` 은 `texUploadBad` 를 돌려준다); 호출자 `osrdnTexResident` 는 0/1 반환만 본다(`OSRDNMesaHook.c:359`, 실패 `:363-364`·`:373-374`, 성공 뒤에만 `:378` `r->valid = 1`).
- 8×8 rung 의 `osrdn_tex_upload`(`OSRDNMesaTex.c:235-240`)에도 자체 전수 되읽기가 있다 — 64 워드, 시험 rung 전용이라 **그대로 둔다**.
- 검사기: `check_hook.py:118` 은 Tex.c 를 입력으로 받지 않고, `:896` 는 flush 규칙; `sim_texrun.py:87` 은 `readbad=0` 인 정상 fixture(judge_m1d 에 readbad 규칙 없음).  두 번째 루프를 고정하는 규칙은 없다 → 새 규칙이 필요하다.

## 1. 설계

- knob `RDNMesaTexVerify`: **없으면 표본**, 있으면 오늘의 전수 루프.  Tex.c 는 libc 헤더 없이 `extern char *getenv` 로(관례).
- 표본 = 첫 행의 첫·끝 워드, 끝 행의 첫·끝 워드 — `w == 1`·`h == 1`(codex: `OSRDNMesaTex.c:119-121` 는 1×N 을 허용)이면 겹치는 좌표는 한 번만 센다.  기대 워드는 쓰기와 같은 식으로 `px` 에서 다시 만든다.  거절 의미 불변: 하나라도 다르면 `readBad += bad`, `refused[READBACK]++`, 0.
- 새 계수기 `texCounts.verifyWords`(대조한 워드 수) — 판정기가 "표본 4 / 전수 w×h" 를 읽는다.
- 무엇을 잡고 무엇을 놓치나(codex §4 (e) 채택): 쓰기와 읽기가 **같은 주소식**(`OSRDNMesaTex.c:137`·`:148`)이므로 전수 루프도 "주소가 맞다" 는 증거는 아니었다; 창 크기 부족은 `:128-132` 가 먼저 거절한다.  표본은 첫·끝 행이 덮어써지는 별칭, 값 실종을 잡고, **중간 워드의 고정 비트 불량·중간 주소 별칭은 놓친다** — 그것을 보려면 knob 으로 전수를 켠다(진단용).  G4-8 의 얼굴 텍스처 실측(그림 대조)이 이미 카드가 텍셀을 제대로 읽는다는 증거다.

## 2. 검사

- 호스트 시뮬레이터 `tools/mesa/sim_texupload.py`: Tex.c 를 가짜 창(malloc)으로 링크해 `upload_level` 을 부른다 — 기본: `verifyWords` = 4(w,h > 1), 2(1×N·N×1), 1(1×1); knob: w×h; NO_WINDOW 거절 경로.  변이: 끝 행 표본 누락(→ 2), knob 무시(기본에서 w×h), 중복 미제거(1×N 에서 4).
- check-all 에 등록.  check_compile(-m32 문법)·check_hook·judge_m1b 그대로.

## 3. 실측 (사용자 gcdsd, 재부팅 없음)

- `run_g50.sh` 의 R1·R2 를 새 라이브러리로(`RDNMesaTime=1`): 업로드 레벨당 us 가 11,000 → **< 1,500**(쓰기 루프만: 16,384 워드 비캐시 쓰기 ≈ 1 ms); 프레임 −4 / −20 ms 근처.  `texture: refused 0` 유지.
- 그림 게이트: 시작 맵 300 프레임 뒤 `tools/g48/rdndump` 컬러 표면을 G4-11 의 `build/g410/dump3-colour.raw`(같은 장면, 같은 라이브러리 계보)와 python 으로 대조 — **화소 차이 0**(장면·시드·카메라가 고정이면 같아야 한다; 다르면 그 수와 위치를 적고 원인을 찾는다).
- knob 켠 실행 1 회(짧게, 100 프레임): `verifyWords` = w×h 합, refused 0 — 전수 경로가 살아 있음.

## 4. codex 교차검토 판정 (2026-09-29, gpt-6-astra, 한 주장·국지적) — 주장 (a)(b)(c)(d) 성립, (e) 정정

| codex 주장 | 내 검증 방법 | 결과 |
|---|---|---|
| (a) `readBad`·`refused[READBACK]` 로 분기하는 코드 없음: `osrdn-mesa-tri.c:375-376` 출력뿐, shim `osrdn-mga-shim.h:119`·`:123` 은 `texUploadBad` | 줄을 열어 확인 | ✅ |
| (b) 호출자는 0/1 만: `OSRDNMesaHook.c:359`·`:363-364`·`:373-374`·`:378` | 열어 확인 | ✅ |
| (c) `osrdn_tex_upload` 는 자체 전수 되읽기(`OSRDNMesaTex.c:235-240`, 거절 `:242-247`), `texImage` 는 입력 복사(`:226-227`, getter `:46`) | 열어 확인 | ✅ — 시험 rung 은 그대로 |
| (d) 검사기 규칙 없음: `check_hook.py:118` 인자·`:896` flush 규칙, `sim_texrun.py:87` fixture·`:117` judge 호출 | 열어 확인 + `judge_m1d.py` 에 readbad grep 0 | ✅ |
| (e) 네 모서리가 잘못된 byteOff/stride 를 잡는다는 말은 틀림 — 쓰기·읽기가 같은 주소식(`OSRDNMesaTex.c:137`·`:148`)이라 전수도 못 잡고, 창 부족은 `OSRDNMesaTex.c:128-132` 가 먼저 거절; 표본은 중간 워드 불량·중간 별칭을 놓친다; 1×N 표본 중복 | 줄을 열어 확인 | ✅ 채택 — §1 에 "무엇을 놓치나" 와 중복 제거를 명시, knob 은 진단용으로 남긴다 |

codex 줄번호 26 곳 전부 실제와 일치(python 으로 출력해 대조).

## 5. 구현·실측 (2026-09-29, 라이브러리 **790595436**, 드라이버 2d3234bf, 사용자 gcdsd, 재부팅 없음; `build/g51a/run_g51a.sh` → `run.log`)

- 구현: `OSRDNMesaTex.c:33-41` knob, `:145-177` 전수/표본 분기(`verifyWords` 계수기 `OSRDNMesaTex.h`).  호스트 시뮬레이터 `tools/mesa/sim_texupload.py`(모서리 4/2/1, knob 은 w×h, NO_WINDOW 거절, 변이 3 종) PASS; check_compile·check_hook·sim_texrun·judge_m1b PASS.
- 레벨당 업로드: **11.0 ms → 1.4 ms**(R1 117 회, R2 484 회), `refused 0`, `readBad 0`.  knob 켠 R4: 전수 경로 살아 있음(3 레벨 × 58.8 ms — 256² 급 2D 텍스처).

| | G5-0(790593936) | G5-1a | 차 |
|---|---|---|---|
| 데모 300 프레임 | 82.3 ms (12.2 fps) | **60.2 ms (16.6 fps)** | −22.1 ms(예측 −20) |
| 시작 맵 **월드 프레임 150–300** | 36.7 / 34.7 ms | **30.7 ms (32.6 fps)**; 재실행 30.7·31.3·30.7 | −4~−6 ms(예측 −4) |
| 시작 맵 300 프레임 평균 | 43.8 | 39.1 / 33.4 | (콘솔 프레임이 섞여 있음, 아래) |

- **발견 1 — 콘솔 프레임**: `+map start` 실행의 처음 ~115 프레임은 월드가 아니라 **콘솔**이다(틱의 `texture: uploads` 가 프레임 115 까지 3 개(charset·conback·로고)이고 월드 텍스처는 그 뒤에 올라온다; `drawn` 은 그 사이 프레임당 ~3,000 삼각형 = 글자 쿼드).  콘솔 프레임이 34 ms 나 든다(글자 쿼드 3,000 개).  그래서 G5-0 §8-1 의 "시작 맵 43.8 ms" 는 콘솔 115 + 월드 185 프레임의 평균이고, 판정기는 이제 `world frames 150-300` 줄을 따로 찍는다(`build/g50/judge_g50.py tick_span(first)`).
- **발견 2 — 첫 실행의 콜드 캐시**: 재링크 직후 첫 실행은 첫 100 프레임이 51–52 ms(다음 실행부터 34 ms) — G5-0 §8-1 의 "계기 비용 +20 %" 는 이것이었다.  knob 켜고/끄고 번갈아 두 번: 월드 31.3 / 30.7 ms → **계기 비용 ≈ 2 %**.
- **그림 게이트**: R1 뒤 `rdndump` 컬러 표면과 G4-11 의 `dump3` 는 20 % 화소가 다르지만 전부 **바닥 조명 띠**(행 320–440)의 균일한 어두워짐(비율 p50 0.92, |Δ|≥16 은 0.86 %)이고, 같은 라이브러리로 두 번 덤프해도 17.5 % 가 비율 0.98 로 다르다(|Δ|≥16 은 2 화소) — Quake 의 조명 스타일 애니메이션이 게임 시간(프레임 300 에서 15.6 / 13.0 / 11.4 s)에 따라 바닥 밝기를 바꾼 것이지 렌더링 차이가 아니다.  구조적 차이 없음(`build/g51a/r1-vs-dump3.png`).  게이트는 "|Δ|≥16 < 1 %, 비율 균일" 로 적는다.
- G5-1a 종결.  다음: G5-1b present 한 블릿.
