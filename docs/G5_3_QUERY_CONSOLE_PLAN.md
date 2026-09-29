# G5-3 — 창 위치 질의와 콘솔 프레임 (라이브러리만, 재부팅 없음)

남은 작업 목록의 2·3 번.  사용자 요청: G5-2 와 함께 한 번에 재부팅.  **둘 다 커널을 바꾸지 않는다** — 그래서 재부팅이 필요한 부분은 없고, 필요한 것은 **재부팅 뒤 한 번의 실행이 두 질문에 답하게 하는 준비**다.

## 0. 왜 지금 고치지 않고 먼저 재는가

두 비용 모두 G5-2 가 바꾸는 자리에 걸려 있다:

- **질의**(2 번): `OSRDNMesaBufferPresentRect` 는 첫 행에서 `presentShiftFor` → `presentServerFrame`(서버 왕복) 을 한 뒤 `presentBlit` ioctl 을 부른다(`OSRDNMesaPresent.c` 의 순서, 열어 확인).  present 모드의 glFinish 는 배치를 내보내고 미러 없이 돌아간다(`osrdnHookFinish`, flush 이유 OUTSIDE — G5-2 retire 표에서 0).  G5-2 뒤에는 그 마지막 배치가 **수락만 되고** 카드는 아직 그리고 있다(§3-1: 카드 시간의 90 % 가 그리기).  그러면 질의 0.5 ms 는 CPU 가 어차피 기다릴 카드의 꼬리와 겹친다 — present ioctl 이 그 꼬리를 기다리기 때문이다(카드 안 `WAIT_UNTIL 3D_IDLECLEAN` 뒤 블릿, cpR6Submit 의 W_RPTR·W_IDLE).  **겹친다면 고칠 것이 없다.**
- **콘솔**(3 번): 콘솔 프레임은 글자 쿼드 3,000 개(삼각형 ~6,000)라 제출이 월드의 몇 배다.  G5-2 가 제출당 동기 대기와 검증 장치를 뺀다.  남는 것이 훅 자체(삼각형당 ~1.5 us)인지 Mesa 인지 모르고, 지금의 계기는 **실행 전체의 합**만 내서 콘솔과 월드를 가르지 못한다.

그래서 이번 재부팅 전에 하는 일은 **계기 하나**(콘솔/월드 분할)와 **판정 절차**다.  고치는 코드는 재부팅 뒤의 숫자가 정한다 — 그 코드도 라이브러리라 재부팅이 필요 없다.

## 1. 실측 (python, G5-1c 실행 `build/g51c/g51c-r1.log`)

| 항목 | 값 |
|---|---|
| 질의 | 296 회, 평균 507 us, 최대 41.4 ms(창 찾기), 프레임당 0.50 ms |
| 프레임 1–100 | 23.2 ms/프레임 (콘솔 + 기동) |
| 프레임 2–115 | 18.6 ms/프레임 |
| 프레임 115–150 | 28.6 ms/프레임 (맵 적재 전환) |
| 프레임 150–300 | 20.0 ms/프레임 (월드) |

- G5-0 의 "콘솔 34 ms" 는 G5-1b(한 블릿) 전의 값이다.  지금은 월드와 비슷하다.
- 틱 줄은 0.1 s 해상도라 구간 값은 ±1 ms 쯤 흔들린다.

## 2. 계기 — `RDNMesaTimeSplit=N`

`osrdn_time_frame_present` 가 N 번째 프레임을 셀 때 `osrdn_time_report` 와 같은 형식의 누계를 **`RDN-TS`** 머리로 한 번 찍는다(`RDN-TS wall …`, `RDN-TS site=… `, `RDN-TS end`).  끝의 `RDN-T` 는 그대로 전체 합이다.  판정기(`build/g50/judge_g50.py`)는 `RDN-TS` 가 있으면 **앞 구간(1..N) = TS**, **뒤 구간 = T − TS** 로 같은 분할표를 두 번 찍는다.

- 비용: 한 번의 write 줄 몇 개.  knob 이 없으면 한 줄의 비교뿐.
- `tools/mesa/sim_time.py` 에 시험: N 에서 한 번만 찍힌다, 두 번 찍히지 않는다, knob 없으면 안 찍힌다, TS 의 n 은 T 의 n 이하다(변이로).

## 3. 판정 (G5-2 의 `run_g52_on.sh` 세 실행에 knob 을 더한다)

G4(동기)·G5(수락) 두 실행이 같은 부팅, 같은 장면이다.  `RDNMesaTimeSplit=150` 으로 콘솔·전환(1–150)과 월드(150–300)를 가른다.

| 질문 | 읽는 법 |
|---|---|
| 2: 질의가 카드 꼬리와 겹치나 | 월드 구간에서 (query + present) us/프레임 이 G5 에서 G4 보다 **query 만큼 이상** 줄지 않았으면(= 질의가 꼬리 안에 들어갔으면) 고칠 것 없음.  꼬리가 질의보다 짧아 질의가 여전히 드러나면 → 격프레임 질의(드래그 시작에 잔상 1 프레임 더) — **화면 품질을 바꾸므로 사용자 확인 뒤에** |
| 3: 콘솔 프레임은 어디에 쓰나 | 앞 구간 표에서 submit / tri self / remainder 의 몫.  submit 이 G5-2 로 사라졌으면 끝.  tri self 가 크면 → 삼각형당 비용(쿼드 두 삼각형이 상태 판정을 두 번 하는지) 을 별도 계획으로 |

## 4. codex 에 묻는 것 (한 주장)

"present 모드에서 G5-2(수락 제출) 뒤, 한 프레임의 마지막 배치가 카드에서 그려지는 동안 CPU 는 glFinish → PresentRect → 서버 질의 → present ioctl 순으로 가고, 그 사이 어느 자리도 카드를 기다리지 않는다(retire 없음) — 그래서 질의는 카드 꼬리와 겹친다" — `OSRDNMesaHook.c` 의 `osrdnHookFinish`·`osrdnFlushFor`·flush 이유 표, `OSRDNMesaPresent.c` 의 `OSRDNMesaBufferPresentRect`·`presentShiftFor`·`presentBlit` 만 보고 반증할 것.

## 5. codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전, 한 주장)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| glFinish 는 OUTSIDE 이유로 flush 하고 그 표 값이 0 이라 retire 가 없다; present 모드면 미러 없이 돌아간다 | 열었다: 표 OUTSIDE 행 `OSRDNMesaHook.c:516`, `osrdnFlushFor` 끝의 조건 `:546-547`, `osrdnFlushOutside` 의 이유 `:631`, `osrdnHookFinish` 의 present 분기 `:1414-1424` | ✅ 반증 안 됨 |
| PresentRect 는 질의(`presentShiftFor` → `presentServerFrame`) 뒤에 블릿 ioctl 을 부르고 그 사이 retire 가 없다 | 열었다: 질의 뒤 블릿 `OSRDNMesaPresent.c:288-297`, 서버 질의 `:184`, present ioctl `:375` | ✅ 반증 안 됨 |
| 겹칠 수 **있다** 는 것이지 카드가 질의 내내 그리고 있다는 **보장은 아니다** | 맞다 — 카드의 꼬리가 질의(0.5 ms)보다 짧으면 일부가 드러난다 | ⚖️ 사실 — §3 의 판정이 바로 이것을 잰다(수락 모드의 present ioctl 이 동기보다 긴 만큼이 질의 뒤에도 남은 꼬리) |
| 동기 대안(`RDNMesaSync`, copyin 아닌 경로)은 조건부로 있다 | 사실; 정상 운용은 copyin + SUBMIT3 | ⏭️ 행동 불변 |

## 6. 구현 (재부팅 전, 라이브러리·판정기만)

- `mesa/OSRDNMesaTime.c`: `RDNMesaTimeSplit=N` — N 번째 프레임을 셀 때 `RDN-TS` 블록 한 번(보고 본문을 `timeBlock(pfx)` 로 뽑아 끝의 `RDN-T` 와 같은 형식).  `tools/mesa/sim_time.py` 에 분할 시험(한 번만·프레임 2·그 전에 더해진 자리만·최종 이하·knob 없으면 안 찍힘) + 변이 3(매 프레임 찍음·knob 안 읽음·한 프레임 늦음).
- `build/g50/judge_g50.py`: `query` 가 분할표의 제 행을 가진다(전에는 나머지에 섞였다); `RDN-TS` 가 있으면 앞·뒤 구간을 같은 항목으로 따로 찍는다.  G5-1c 로그에 절반 값의 `RDN-TS` 를 끼운 합성 로그로 두 구간 합이 전체와 맞음을 확인.
- `build/g52/run_g52_on.sh`: 세 실행 모두 `RDNMesaTimeSplit=150`.  `build/g52/judge_g52.py on`: 월드 구간의 present ioctl(수락 − 동기)과 질의를 찍고 질의가 숨었는지 판정; 자체검사에 월드 구간 계산과 "분할 없음" 변이.
- 판정 결과에 따른 코드(격프레임 질의, 콘솔의 삼각형당 비용)는 재부팅 **뒤**, 재부팅 없이 한다.

## 7. 실기 결과 (2026-09-29, G5-2 와 같은 부팅, `build/g52/on.log`, `RDNMesaTimeSplit=150`)

- **2 번(질의): 고칠 것 없음.**  월드 구간 질의는 0.16–0.17 ms/프레임(G5-1c 전체 평균 0.50 은 콘솔 구간이 끌어올린 값이었다), 그리고 수락 모드의 present ioctl 이 동기보다 1.53 ms/프레임 길다 — 질의가 끝난 뒤에도 카드가 그리고 있었다, 즉 **질의는 카드 꼬리 아래에 숨었다**(`judge_g52 on`).  격프레임 질의는 하지 않는다.
- **3 번(콘솔): G5-2 가 대부분 가져갔다.**  콘솔·적재 구간 38.6 → 23.3 ms/프레임.  남은 몫(수락 실행): 제출 6.87, 삼각형 훅 3.73(2,596 삼각형/프레임), 질의 2.27, 나머지(게임·T&L·맵 적재) 8.21.  질의가 콘솔 구간에서만 큰 것(2.27 vs 월드 0.17)은 창이 뜨고 자리를 잡는 초반 프레임의 비용이다(창 찾기 최대 41 ms, G5-1c).  게임 시작 전 화면이라 더 쫓지 않는다.
