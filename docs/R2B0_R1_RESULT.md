# R-1 결과 — 2026-09-16 실기 (재부팅 없는 Configure 왕복)

태그 `R1b`(`build/r2b0/cfg/R1b/`), 설치 `runid 789519594` `stamp b84d08fe` reloc `33404 161`.
`R1/pre` 는 `Server Name` 중복의 증거라 지우지 않고 남겼다(§14).

| 단계 | 명령 | 결과 |
|---|---|---|
| 1 | `cfgsnap pre R1b` → `check_cfgdiff precheck` | **PASS**(표 17, `PRECHECK_PASS`).  Adaptec 낡은 `Location` 은 키 있는 예외로 `NOTE` |
| 2 | `pack_restore_r2b0.py R1b` → `stage-restore R1b` → `check.sh` | **차이 0**(`set=R1b tables=16 differ=0 extra=0`) |
| 3 | operator: Configure 에서 VGA → OSRDNDisplay 저장 → `cfgsnap post R1b` → `check_cfgdiff activate` | **FAIL**(아래) — 계획대로 재부팅 없이 4 로 |
| 4 | operator: Configure 에서 OSRDNDisplay → VGA 저장 → `cfgsnap post2 R1b` → `record` | 기록 |
| 5 | `restore.sh` → `cfgsnap post3 R1b` → `check_cfgdiff restored` | **PASS**(17 표 바이트 동일), 재실행 `wrote=0 parked=0` |

복귀 확인: `Active Drivers` = `SpaceSaver2Mouse Pro1000 Adaptec2940SCSIDriver MDH10Disk EMU10K1 VGA`,
`OSRDNDisplay.config`·`VGA.config` 둘 다 인스턴스 표 있음.

## 1. Configure 가 실제로 한 일 (pre → post, `RECORD-pre-post.txt`)

1. **설치된 `Instance0` 을 두고 `Instance1` 을 새로 만들었다** — 활성화 부팅이면 **한 카드에 인스턴스 둘**.
2. `Instance1` 의 `"Location" = "Dev:11 Func:0 Bus:3"` — **빈 `Location` 을 채운다.**  계획 S28 의
   "빈 `Location` 을 채운 사례는 없다" 는 **틀렸다**(그때는 캡처한 VGA 표만 보고 적은 것이다).
3. `Instance1` 에 **`"Default Table"` 키가 없다.**  Matrox 선례(S28)와 다르다 — 그 키는 템플릿
   이름이 `Default` 가 아닐 때만 붙는 것으로 보인다(VGA 는 `SVGABIOS` 라 붙었다, 아래 5).
4. 우리 `Instance0` 은 키 순서만 바뀌어 다시 쓰였고 **모드가 `444` → `644`** 가 됐다.
   `EIDE`·`EMU10K1` 도 값 변화 없이 키 순서만 바뀌었다(S28 대로).
5. `Active Drivers` 는 `VGA` 토큰 하나만 `OSRDNDisplay` 로 바뀌었고 `VGA.config/Instance0.table` 이
   삭제됐다.
6. 복구 집합은 이 상태를 정확히 읽었다: `/me/rdn-r2b0/check.sh` → `differ=5 extra=1`
   (`Instance1` 을 extra 로 지목, `build/r2b0/cfg/R1b/check-after-activate.txt`).

## 2. 되돌릴 때 (pre → post2, post → post2)

- **Configure 는 OSRDNDisplay 인스턴스를 둘 다 지웠다** — 설치기가 넣은 `Instance0` 까지.
  되돌린 뒤 번들에는 인스턴스 표가 하나도 없었다.
- `VGA.config/Instance0.table` 을 `"Default Table" = "SVGABIOS"` 템플릿에서 다시 만들었고,
  **키→값은 `pre` 와 완전히 같다**(바이트 순서만 다름).
- `System.config/Instance0.table` 은 `pre` 와 키→값이 같아졌다(`Active Drivers` 복귀).
- 그래서 5 단계의 집합 복원이 쓴 것은 4 개뿐이다(`OSRDNDisplay.config/Instance0.table`,
  `VGA.config/Instance0.table`, `EIDE`, `EMU10K1` — 뒤 셋은 바이트 순서 되돌리기).

## 3. 활성화 부팅 전에 반드시 고칠 것 — 인스턴스가 둘

두 인스턴스 모두 `"RDN R2B0 Record" = "Yes"` 이고, 하나는 `Location` 이 카드(03:0b.0), 하나는 빈 값
(→ PCIBus 가 ID 로 스캔해 같은 카드를 찾는다, S25).  **같은 카드를 두 인스턴스가 물면** 2026-09-15 의
VGA 인스턴스 둘 사고와 같은 모양이 된다(그때는 Configure 사운드 탭 주소 충돌로 드러났다).

**원인(2026-09-16 정정)**: 인스턴스 표를 담은 것 자체가 아니라, 담은 표가 **`Location = ""` 인
카탈로그 모양**이었다는 것이다.  이 워크스페이스 정본 `doc/driverkit.md` 는 `Default.table` 을 지원
장치의 **카탈로그**, `InstanceN.table` 을 **이 기계에서 발견된 개체의 기록**(실제 `Location` 을 담는다)
으로 적고, **`driverLoader` 가 구성에 성공하면 `InstanceN.table` 이 생긴다**고 한다.  Configure 가
제대로 된 인스턴스(`Location` = 실제 슬롯)를 새로 만든 것은 그 모형과 정합한다.

정품 i386 디스플레이 번들 9 개가 인스턴스 표를 담지 않는다는 **관측은 사실**이다(VGA·S3·
CirrusLogicGD542X·TsengLabsET4000·QVision·Wingine·JAWS·HPXPDisplayDriver·Number9; 담는 것은
버스 드라이버 셋뿐).  다만 거기서 "담으면 안 된다" 를 끌어내면 안 된다 — Matrox 는 담았고,
실기 `driverLoader` 는 인스턴스 0 이 없으면 `Default.table` 로 폴백한다.  조치는 계획 §15 에 있다.


## 4. R-1c — 주차 경로 리허설 (2026-09-16, 재부팅 없음, 태그 R1c)

설치 `runid 789526262` `stamp e48c2e8d` reloc `52874 161`(probe 걸쇠 포함).

| 단계 | 결과 |
|---|---|
| `cfgsnap pre R1c` → `precheck` | PASS(표 17) |
| `pack_restore`/`stage-restore R1c` → `check.sh` | `differ=0 extra=0` |
| operator: Configure 로 VGA → OSRDNDisplay | R-1 과 **동일하게 재현**(`RECORD-pre-postraw.txt`): `Instance1` 추가·`Location`=실제 슬롯, 우리 `Instance0` 키 순서만·모드 `444`→`644`, `EIDE`·`EMU10K1` 재기록, VGA 인스턴스 삭제, `Active Drivers` 토큰 하나 교체 |
| `cfgsnap postraw R1c` | 주차 전 상태 보존 |
| `target-park-extra-r2b0.sh closed=yes` | `PARK DONE tag=R1c parked=1 left: Instance0.table` |
| `cfgsnap post R1c` → `check_cfgdiff activate` | **PASS**.  NOTE 둘(VGA 인스턴스 삭제, 우리 표 `444`→`644`) |
| `cfgsnap postb R1c` → `same post postb` | **PASS**(§7-3 7 번 규칙) |
| operator: Configure 로 OSRDNDisplay → VGA | `RECORD-pre-post2.txt`: 우리 인스턴스 표 삭제, VGA 인스턴스 재생성(키→값 동일) |
| `restore.sh` → `cfgsnap post3` → `restored` | **PASS**(17 표 바이트 동일), 재실행 `wrote=0 parked=0` |

복귀 확인: `Active Drivers` 끝이 `VGA`, 두 번들 모두 인스턴스 표 있음, 주차본은
`/me/rdn-r2b0/parked-activate.R1c/OSRDNDisplay.config/Instance1.table` 로 보존.

**활성화 부팅에 필요한 디스크 상태를 재부팅 없이 만들고 게이트로 검증했다.**  남은 미확인은
§15-4 에 적은 대로 실제 부팅에서만 드러난다(`driverLoader` 가 우리 번들을 probe 하는지, 빈
`Location` 으로 서술자가 채워지는지, 걸쇠 코드의 실행, 바뀐 소유자 아래 telnet·`/ndrv`·nxlogd).
