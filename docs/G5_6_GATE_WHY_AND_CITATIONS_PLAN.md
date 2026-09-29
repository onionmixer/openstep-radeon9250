# G5-6 — `gate refused Hook.c:5 ×4` 의 정체, 경로 인용 30 개, 그리고 수락 제출 중 CP 멈춤

남은 작업 목록의 3·4 번과, 그 사이에 드러난 것 하나.

## 1. 3 번 — `gate refused : Hook.c:5 x4` 와 `kernel : declined 4` (조사 끝, 고칠 것 없음)

두 줄은 GLQuake 포트의 Matrox 형식 통계다.  radeon 빌드에서는 `test/mgashim/osrdn-mga-shim.h` 가 이어 준다: `Hook.c:<n>` 의 n 은 분류기의 거절 사유(5 = `OSRDN_WHY_RASTER`), `declined` 는 훅의 leave 수.  진단 계수를 라이브러리의 새 `RDN-G` 줄에 싣고(동작 불변) GLQuake 를 돌렸다(`build/g55/g56-raster5.log`):

    RDN-G raster_declined=256 raster_seen=4359 leaves=4 leaves_unbound=1 leaves_watched=4 renders_left=0

- 거절된 비트는 0x100 = `ALPHABUF_BIT`(소프트웨어 알파 버퍼, Mesa `types.h` 1457) 하나다.
- OSMesa 는 표면에 묶이기 전 소프트웨어 알파 버퍼를 켜 두고, 묶는 순간 끄고 래스터 플래그를 다시 계산한다(`osmesa.c` 의 가속 분기).  그 사이에 상태 판정이 한 번씩 더 온다 — leave 넷 중 하나는 묶이기 전, 셋은 묶인 직후 플래그가 다시 계산되기 전이다.
- **그 상태에서 시작된 그리기는 0 회다**: leave 넷 모두 우리 RenderStart 가 걸린 채였고(`leaves_watched=4` — 그래서 0 은 "잴 수 없었다" 가 아니다), leave 동안 시작된 렌더 패스는 없다(`renders_left=0`).
- → 과도 상태이고 그림에 영향이 없다.  계수는 남긴다(값이 바뀌면 그때 본다).
- 곁에서 고친 것: RDN-C 줄이 256 바이트 줄 버퍼를 넘어 잘렸다(`…renders_left=0 leav` 에서 끊기고 개행이 없어 다음 줄과 붙었다).  진단은 제 줄(`RDN-G`)로 옮겼고, 줄이 잘리면 `RDN-CUT` 줄이 따라오게 했다(`sim_time` 에 시험 + 변이 2).

## 2. 4 번 — 경로를 붙인 인용 30 개

`tools/oracle/check_citations.py` 의 `citations()` 는 `x/y/z.c:N` 모양의 토큰을 PATHS 이름과도, `UNKNOWN` 모양과도 맞추지 못해 **조용히 건너뛴다**.  문서 25 개 파일을 가리키는 30 개가 검사 밖이었다.  하나씩 원문을 열어 문서의 주장과 대조한 결과 **다섯이 이미 다른 줄로 밀려 있었다**:

| 인용 | 문서의 주장 | 지금의 줄 |
|---|---|---|
| judge_m1d.py 498–503 (M1K) | 씨앗 게이트는 `sd <= 1` 을 본다 | `judge_m1d.py:514-520` |
| sim_r6.py 509–515 (M1O) | UC 의 커버리지 맵을 T1 과 대조 | `sim_r6.py:540-546` |
| OSRDNMesaTri.c 193–217 (M2F) | fd 유지 knob 은 `triOpen`/`triClose` 에서만 읽힌다 | `OSRDNMesaTri.c:377-402` |
| judge_r7b.py 101 (M2F ×2) | 거절 줄 하나를 요구한다 | `judge_r7b.py:107` |
| target-build-r2b0.sh 110 (R3) | `make "OTHER_CFLAGS=-DOSRDN_BUILD=…"` | `target-build-r2b0.sh:127` |

나머지 25 개는 문서의 주장과 줄이 맞는다(원문 확인).

**고치는 것**:
1. `citations()` 에 한 갈래 — 경로가 붙은 `x/…:N` 은 `PATHED:` 로 실패시킨다.  앞으로는 조용히 건너뛸 수 없다.
2. 30 개를 PATHS 키 이름으로 바꾸고(같은 파일의 키가 이미 있으면 그것, 없으면 새 키 12 개), 밀린 다섯은 새 줄로, 각각 EXPECT 앵커.
3. 경로 인용 바로 뒤에 맨 `:N` 이 오는 곳이 없음을 확인했다 — 키로 바꿔도 다른 인용의 묶임이 바뀌지 않는다.

## 3. 새로 드러난 것 — 수락 제출 중 CP 멈춤 세 번 (복구됨, 이 칸에서 고치지 않는다)

부팅 ee4b61a6 에서 수락 제출(`asubmit`) 중 CP 가 **세 번** 멈췄고, 드라이버가 세 번 다 복구했다(`recover=2`: 엔진 리셋 + CP 재시작, M3J).  각 사건에서 떠 있던 배치 하나를 잃었다(커널 `lost=3`).  두 번은 timedemo 초반, 한 번은 그 뒤 첫 GLQuake 실행 중이다(수락 제출 ~93,000 건에 셋).

    asubmit … rc=8 us=110571   latch … rptr=00000800 wptr=000008a0 … recover=2
    asubmit … rc=8 us=110564   latch … rptr=00000a60 wptr=00000b00 … recover=2
    asubmit … rc=8 us=110579   latch … rptr=00000400 wptr=000004a0 … recover=2

- 셋 다 **rptr 이 wptr 보다 정확히 0xa0 = 160 워드 뒤**에서 멈췄고, rptr 은 0x20 의 배수다.
- 멈춤 자체는 G5-2 이전에도 있던 종류다(M3 계열, [[r200-ring-wrap-like-bsd]]: 링 중간 멈춤, 참조식 복구).  G5-2 이전 실행들의 빈도와 비교해야 G5-2 가 늘렸는지 말할 수 있다 — 이 칸의 판단 밖이다.
- 사용자 영향: 한 프레임의 일부가 빠지고 ~110 ms 끊긴다.  남은 작업으로 올린다: 160 워드의 정체(그 자리의 스트림을 기록 추적으로 잡아 해독), 그리고 동기 모드의 멈춤 빈도와 비교.

## 4. codex 에 묻는 것 (코딩 전, 한 주장)

"`citations()` 에서 이름 붙은 토큰이 PATHS 에 없고 경로 구분자를 담으면 `PATHED:` 로 실패시키는 갈래를 더하면, 지금 조용히 건너뛰는 경로 인용은 전부 잡히고, 다른 토큰(맨 `:N`, 이름 인용, UNKNOWN, PREFIXED, 인용이 아닌 코드 조각)의 판정은 바뀌지 않는다."

## 5. codex 교차검토 판정 (2026-09-29, `gpt-6-astra`, 코딩 전, 한 주장)

| codex 주장 | 내 검증 | 판정 |
|---|---|---|
| 지금은 경로 인용이 어느 갈래에도 안 맞아 조용히 건너뛴다 | `citations()` 를 열었다 — 이름 갈래는 PATHS 키만, UNKNOWN 은 `/` 없는 모양만, PREFIXED 는 공백 뒤만 | ✅ 반증 안 됨 |
| 새 갈래는 `cur` 를 안 바꾸고 다른 토큰의 판정을 안 바꾼다; `<!-- BEGIN` 뒤와 백틱 밖은 원래 안 본다 | 새 자체검사가 다섯 모양(이름·경로·맨·UNKNOWN·PREFIXED)을 한 줄에서 확인 | ✅ |
| `http://a/b:80` 은 이름에 `:` 가 있어 모양에 안 맞는다; 스킴 없는 `a/b:80` 은 새로 실패할 수 있다; 지금 문서에는 파일이 아닌 것이 없다 | 내 재집계: 31 곳·서로 다른 27 토큰, 전부 파일 인용(codex 의 34/30 은 재현 안 됨 — 검사기가 고친 뒤 스스로 0 을 확인) | ⚖️ 결론 채택, 숫자는 기각 |

## 6. 구현 (2026-09-29)

- `check_citations.py`: `PATHED:` 갈래, PATHS 새 키 12(기준 디렉터리는 `ref/upstream` — 처음에 `tools/oracle` 기준으로 셋을 틀리게 적어 파일을 못 찾았다), EXPECT 앵커 25(같은 파일·범위 중복 제외), `--self-test`(다섯 모양 + 갈래를 지우는 변이가 잡힘, check-all 등록).
- 문서 31 곳을 키 이름으로; 밀린 다섯은 새 줄로.  **2,058 인용 0 실패, 경로 인용 0**.
- 3 번 진단 계수(`RDN-G`)와 줄 잘림 표지(`RDN-CUT`)는 라이브러리 790646807 에 들어갔다.

## 7. 남은 작업 5 — 소리 켠 GLQuake (측정만, 코드 없음)

사용자 gcdsd, `+map start` 300 프레임, 소리 켬(11,025 Hz, `build/g55/g57-sound.log`) — 소리 끈 G5-2 실행(`build/g52/g52-r1.log`)과 같은 판정기로:

| | 소리 끔 | 소리 켬 |
|---|---|---|
| 월드 150–300, tick 기준 | 15.3 ms | 15.3 ms |
| 월드, 벽시계 분할 | 15.1 ms | 18.2 ms |
| 콘솔·적재 1–150 | 23.3 ms | 50.0 ms |
| present 줄 / tick 프레임 | 297 / 300 | 296 / 300 |
| RDN-P coalesced · busy · lost | 293 · 1 · 0 | 292 · 1 · 0 |

- **월드 그리기는 소리와 무관하다**: tick 기준 월드 프레임이 같다(15.3 ms).  벽시계 분할의 18.2 ms 는 마지막 tick 뒤 종료까지의 시간을 월드에 얹은 값이다 — 벽시계와 tick 폭의 차가 소리 끔 0.21 s, 소리 켬 0.66 s(python), 곧 소리 초기화·정리 시간이다.  콘솔 구간이 두 배인 것도 소리 파일 적재(로그의 `sound/*.wav` 줄들)다.
- **판정기 FAIL(296 vs 299) 은 present 거절이 아니다**: 판정기는 tick 폭(마지막 − 처음 = 299)과 present 줄 수를 ±2 로 대조한다.  present 없는 프레임은 적재 중 GLQuake 가 화면을 안 그리는 프레임이다 — 분할(150 번째 present)이 소리 끔은 tick 152, 소리 켬은 tick 153 에서 났다(python): 적재 중 한 프레임이 더 그려지지 않았을 뿐이다.  RDN-P 가 두 실행에서 같다(lost 0, busy 1).  판정기는 고치지 않는다(허용폭을 늘릴 근거가 소리 적재뿐이다).
- 새 CP 멈춤·유실 없음.
