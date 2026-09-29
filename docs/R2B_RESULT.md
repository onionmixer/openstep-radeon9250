# R2b 결과 — 2026-09-16 실기 (첫 모드셋, 800x600@60)

**판정 `R2B: PASS`.**  부팅 `ffb43f7d`, build stamp `eb2cae40`, runid `789543933`,
reloc `14259 230`.  증거: `build/r2b/ffb43f7d/`(진입·복귀 44 줄, probe/init 5 줄),
설정 스냅샷 `build/r2b0/cfg/R2B/{pre,postraw,post,postb}`.

**이 카드에 드라이버가 처음으로 모드를 쓴 부팅이고, 들어갔다.**

## 1. operator 가 본 것

> "boot logo 이후 next login 화면이 나오기 전에 잠시 상단부터 RGB 가 보이고 next login 화면이 나왔습니다."

시험 패턴(상단부터 색 띠)이 보였고 그 뒤 **로그인 화면까지 떴다** — 계획 §9 의 1·2 항이 모두 참이다.
WindowServer 가 우리가 세운 모드 위에 정상적으로 그렸다는 뜻이기도 하다.

## 2. 드라이버가 기록한 것

| 줄 | 뜻 |
|---|---|
| `probe rc=0 loc=03:0b.0 id=59601002 accept` / `claim held=0 result=claim` | 빈 `Location` 으로 카드에 묶였다(R2b-0 과 같다) |
| `init boot=ffb43f7d build=eb2cae40 loc=03:0b.0 key=yes cmode=2 ... ok` | 초기화 성공, 옵트인 키 읽힘, 패킹한 stamp 와 일치 |
| `revert n=1 written=0 snap=0` | 커널이 **진입보다 먼저** 복귀를 부른다 — 쓴 것이 없으므로 아무것도 하지 않았다(설계대로) |
| `enter n=1 live=1` | **진입 성공** |
| `mode why=0 step=14 refdiv=12 div3=0003008e bad=0 written=1 snap=1` | 0–14 단계 완주, 12 단계 되읽기 전부 일치 |
| `wait aw=5 ar=5 awl=0 arl=0 lim=0/0 settle=58343` | PLL 원자갱신이 쓰기 5 us·읽기 5 us 에 끝났고 **한도에 걸린 대기가 없다**; 잠금 대기 58343 us |

## 3. 값 대조 (python, 오라클·생성 헤더와)

이 부팅의 콘솔은 `PPLL_REF_DIV = 0x0c`(=12) 였고 드라이버는 그 행을 골랐다.

| 레지스터 | 스냅샷(콘솔) | 우리가 쓴 값 | 대조 |
|---|---|---|---|
| `CRTC_H_TOTAL_DISP` | `004f005f` | `00630083` | 헤더와 같음 |
| `CRTC_H_SYNC_STRT_WID` | `000002a0` | `00100340` | 헤더와 같음 |
| `CRTC_V_TOTAL_DISP` | `01df020b` | `02570273` | 헤더와 같음 |
| `CRTC_V_SYNC_STRT_WID` | `000c01ea` | `00040258` | 헤더와 같음 |
| `CRTC_PITCH` | `00000028` | `00640064` | 헤더와 같음 |
| `GRPH_BUFFER_CNTL` | `20205c5c` | `20005c5c` | `(snap & preserve) \| set` 계산과 같음 |
| `PPLL_DIV_3` | `00030065` | `0003008e` | 오라클 refdiv=12 행(fb 142, post 8)과 같음 |

실현 VCO 319500 kHz, 도트 클럭 39937.5 kHz, 새로고침 60.2223 Hz.

**건드리지 않은 것이 그대로다**: `PPLL_REF_DIV` `0000000c` 불변(공유 슬롯 규칙),
`PPLL_CNTL` `0000a700` 으로 복귀(RESET 해제·PVG 불변, 12-1), `VCLK_ECP_CNTL` `000000c3` 불변,
`HTOTAL_CNTL` `00000000`, `DISP_MERGE_CNTL` `ffff0000` 불변, `CRTC_OFFSET` `00000000` 불변.
VGA 코어 스냅샷은 `misc=e3 crtcport=3d4 taken=1 seq0=03 crtc0=5f gr0=02 attr10=01`.

## 4. 활성화 절차 (R2b-0 과 같은 게이트, 전부 PASS)

`precheck PASS`(NOTE 없음) → 복원 묶음 staged `differ=0 extra=0`(16 표) →
operator Configure 전환(VGA 인스턴스 표 삭제 + `OSRDNDisplay/Instance1` 추가, R2b-0 과 동일) →
주차 `parked=1` → `activate PASS`(NOTE 2: VGA 인스턴스 삭제, 우리 표 모드 444→644) →
`same PASS` → operator 재부팅.

VGA 구제 번들은 재부팅 전에 확인했다(`Default.table` 505 바이트, `VGA_reloc` 온전).

## 5. 이번에 처음 돈 검사

- **역어셈블 호출자 규칙**(개정 2, 13-7)이 실기 빌드에서 처음 돌았고 PASS.  호출자 표가 소스 감사와
  정확히 일치했다: `rdnMmioWrite32` 는 `osrdn_mmio_put`·`osrdn_palette_put`·`osrdn_pll_put`·
  `osrdn_snap_take`·`osrdn_mode_pattern`·`pllGroup` 여섯 곳에서만 불린다.  모드·복귀 함수가
  하드웨어 도우미를 **직접 부르는 곳은 한 군데도 없다**.
- 74 개 함수 범위 중 포트 명령은 네 포트 함수 안에 하나씩만, 간접 점프 없음.

## 6. 남은 것

- **복귀(§9 3 항)는 아직 판정되지 않았다.**  이 부팅의 복귀는 진입 전에 불린 빈 복귀였다.
  진짜 복귀는 종료 때 돌고, 종료 중에는 로그가 남지 않는다 — 판정은 **다음 부팅의 스냅샷 값**과
  operator 육안으로 한다.
- 절차 기록: 호스트 NFS 서버(gnfsd)가 내려가 있어 operator 가 올렸고, 재부팅 뒤 `/ndrv` 는 수동
  마운트가 필요했다(export 경로를 심볼릭 링크가 아닌 실제 경로로 지정해야 한다).

## 7. 분주 표를 넓힌 빌드 (2026-09-16, stamp `59f67e42`, runid 789546463)

R2b 가 통과한 뒤 **드라이버를 켠 채로 두기로** operator 가 결정했고, 그러면 표에 없는
`PPLL_REF_DIV` 로 부팅했을 때 화면이 깨진 채 남는 구멍이 살아 있는 위험이 된다.  그래서
분주 표를 두 행에서 **refdiv 5–172 의 168 행**으로 넓혔다(규칙과 한계는 구현 계획 §14).

- 호스트: 오라클 자체검사(경계 음성 대조 포함) → 생성 헤더 168 행(문서가 규칙·경계·개수·지문을
  승인) → 시뮬레이터에 합성 refdiv 세계(5·6·12·71·172 는 진입·복귀 항등, 0·4·173·512 는
  **레지스터를 하나도 쓰지 않고** 거절) → 표 게이트를 없애는 변이가 잡힘.
- 타깃: 빌드 PASS(reloc `63712 230`) → **역어셈블 게이트 PASS, 호출자 표가 이전 빌드와 동일**
  (표가 커진 것은 데이터라 코드가 안 바뀐다) → `restore.sh` 로 `Active Drivers` 를 VGA 로 되돌린 뒤
  설치(`fresh`) → 새 기준선 `R2C`: `precheck PASS`, 복원 묶음 `differ=0 extra=0`.

### 7-1. 절차 기록 — 게이트를 건너뛴 부팅

operator 가 Configure 전환 뒤 **주차·`post`·`activate`·`postb`·`same` 를 기다리지 않고
재부팅**했고, 인스턴스 표가 둘인 것을 직접 정리했다.  사후에 같은 판정을 돌렸다:
`activate PASS`(NOTE 2, 이전과 같은 둘) — **손으로 정리한 결과가 주차 스크립트의 결과와 같다.**
복구 묶음은 `set.R2C` 로 그대로 서 있고 `CURRENT` 가 그것을 가리킨다.

### 7-2. 세 부팅 연속 성공

| 부팅 | 빌드 | 결과 |
|---|---|---|
| `ffb43f7d` | `eb2cae40` | `revert n=1 written=0` → `enter live=1 step=14 refdiv=12 bad=0` |
| `f94ce36c` | `59f67e42` | 같음 |
| `df5f7425` | `59f67e42` | 같음 |

세 번 모두 콘솔이 refdiv 12 였고, 되읽기 값이 전부 같았다(§3 의 표와 동일).

### 7-3. 종료 복귀에 대해 말할 수 있는 것과 없는 것

`f94ce36c` → `df5f7425` 는 **모드를 쓴 채로 종료했다가 다시 켠** 첫 사이클이다.  종료 경로가
끝까지 돌았고 다음 부팅이 정상이었다 — 복귀가 카드를 **걸어두지 않는다**는 것은 이것으로 말할 수
있다.  하지만 **복귀가 스냅샷을 되돌렸다는 증명은 아니다**: 소프트 재부팅도 VGA BIOS POST 가
카드를 다시 프로그램하므로, 복귀가 아무것도 안 했더라도 다음 부팅은 같아 보인다.
종료 중에는 로그가 디스크에 닿지 않아 되읽기 기록을 뺄 수 없다.  **여전히 미판정이다.**
