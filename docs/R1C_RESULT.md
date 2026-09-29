# R1c 결과 — 2026-09-15 실기

**게이트 PASS**:
- `parse_bios.py full build/r1c/rdn-bios-789464097-512.bin build/r1c/rdn-bios-789464097-53248.bin build/r1/rdn-r1-789453017.log 789453017 --out build/r1c`
- 두 `read` 모두 `R1CREAD DONE`, 복사본 sum 일치.

사용자 공간 `/dev/mem` 읽기 두 번(512 바이트, 53248 바이트)이 행 없이 끝났고, 이후 타깃은 정상 응답했다.  재부팅 없음.

- **실행 기록**(`build/r1c/`):
  - `rdn-r1c-789464097-facts.log`
  - `rdn-r1c-789464097-512.log`
  - `rdn-r1c-789464097-53248.log`
  - 첫 read 시도의 실패 기록 `rdn-r1c-789464097-512.attempt1-positional.log`
  - 셸 탐침 `shprobe*.sh/.out`
- **사용한 파일**(NFS 낡은 캐시 회피용 새 이름): `build/r1c/target-r1c-31170.sh`(sum `31170 8`), `build/r1c/rdnbios-58680.c`(sum `58680 4`).
  둘 다 타깃에서 크기·sum 이 호스트와 같음을 확인하고 썼다.
- **facts 파일**: `build/r1c/bios-facts-7124ae93f71ea149.txt`(이미지 SHA-256 `7124ae93…`, 앞 512 `72dc80b5…`).

## 1. 실행 중 드러난 것 (도구·타깃)

| # | 사실 | 조치 |
|---|---|---|
| 1 | 첫 `facts`(run 789463413)가 `ps ax \| grep nxlogd …` 에서 멈춤.  `sh -x` 추적으로 위치를 확인했고, 백그라운드에서 따로 띄운 `ps ax` 도 돌아오지 않았다.  같은 `ps` 가 telnet(nxrun) 에서는 된다 | 타깃 스크립트에서 `ps` 제거.  nxlogd 확인은 호스트 `nx-logcatch.sh status`(telnet) 로.  하네스 린트 규칙 + 변이 |
| 2 | 타깃 `/bin/sh` 는 따옴표 없는 `${NAME:-a b}`(기본값에 공백) 에서 **"bad substitution"** 을 내고 변수를 비운 채 계속 간다 — 탐침으로 확인, 따옴표 두면 된다 | `LOGGERS` 를 공백 없는 변수 셋으로.  린트 규칙 + 변이 |
| 3 | 호스트에서 스크립트를 고친 뒤(7035 → 7244 바이트) 타깃이 NFS 로 **`ls` 는 새 크기, 읽기는 앞 7035 바이트만** 돌려줬다(sum `27203 7` = 새 파일 앞 7035 바이트의 sum, Python) — 낡은 크기 캐시 | 고칠 때마다 **새 파일 이름**(`target-r1c-<sum>.sh`)으로 내고, 타깃에서 `wc -c`·sum 이 호스트와 같음을 확인한 뒤 실행 |
| 4 | 첫 `read 512` 시도가 2 단계(sum 비교) 에서 FAIL — 로그 문구 "sum `rdnbios.c sum 58680 4, …` differs".  타깃 sh 는 **함수 호출 뒤 위치 매개변수를 복원하지 않는다**(탐침: `set -- A B; f X; echo $1` → `X`, 호스트 dash 는 `A`).  클레임·빌드·장치 접근 전이라 영향 없음 | `set --` 대신 `awk` 로 이름 붙은 변수, 인자는 맨 위에서 한 번에.  린트 규칙("함수 정의 뒤 `$1..$9` 금지, `set --` 금지") + 변이 둘 |
| 5 | `logger` 표지가 `/usr/adm/messages` 에 남지 않음.  기본 `user.notice` 는 `syslog.conf` 가 그 파일로 보내지 않고, `-p daemon.notice` 도 종료 0 인데 기록이 없다(syslogd pid 94 는 실행 중) | 원인 미확인.  이번 실행은 표지 없이 진행 — 스크립트 출력과 NFS 산출물로 판정 |
| 6 | 나머지 구성(`egrep -c`, `mkdir … \|\| 함수`, 함수 안 `exit`, `$?`, `wc -c <`, `awk`, 공백 든 `case` 패턴) 은 타깃·호스트 결과 동일(탐침 3) | — |

## 2. BIOS

| 항목 | 값 | 해석 |
|---|---|---|
| 서명·크기 | `55 AA`, 크기 바이트 104 → 53248 바이트 | Python 104 × 512 = 53248 |
| 체크섬 | 선언 이미지 8 비트 합 **0** | 오프셋과 무관한 독립 확인 — 길이·내용 온전 |
| ATI 표지·날짜 | 0x30 에 ` 761295520`, `2005/03/30 04:20` | ATI 레거시 BIOS |
| PCIR | 포인터 0x190, `PCIR`, vendor 1002 device 5960(= R1 카드), 이미지 길이 104, code type 0 | 게이트 3 — device 도 R1 과 같음 |
| ROM 헤더 | 0x124, +4 는 ATOM/MOTA 아님 | 레거시 |
| PLL 블록 | 0x938, rev **10** | 원시 바이트: `+0x0e 8c0a`(2700) `+0x10 0c00`(12) `+0x12 204e0000`(20000) `+0x16 409c0000`(40000) `+0x08 3147`(18225) `+0x0a 2a5d`(23850) — 파서 값과 같다 |
| refclk | 2700(10 kHz) = **27.00 MHz** | NetBSD 기본값과 같음 |
| refdiv | **12** | R2a 실측 `PPLL_REF_DIV` 와 대조 예정(기록 항목) |
| PLL 출력 범위 | **200.00–400.00 MHz** | NetBSD 기본 최소(125 MHz)보다 높다 — 오라클은 BIOS 값을 쓴다 |
| rev>9 필드 | `pll_in_min` 40, `pll_in_max` 3000 | 기록(xf86 의 PLL 계산만 씀, 우리 선택식은 NetBSD) |
| mclk / sclk | 182.25 / 238.50 MHz | FIFO 오라클 입력(R2 계획 §8) |
| 1024×768 분주 | post 6(4 도 범위 안이지만 표 순서상 6), feedback 173, 목표 390000 kHz, 실제 VCO 389250 kHz, 픽셀 클럭 64.875 MHz, 리프레시 ≈ 59.888 Hz | Python 재계산.  VCO ≥ 300 MHz → PVG 이득 7(R2 계획 §4 6b).  NetBSD 주석의 "RV280 은 360 MHz 미만에서 불안" 보다 높다 |

## 3. 다음

- **R2a**: `PPLL_REF_DIV`(refdiv 12 대조), `MEM_TIMING_CNTL`·`MEM_CNTL` 을 측정하면 FIFO 오라클 입력이 다 모인다.
- **R2 계획 §6 출처 사슬**: R1c 캡처 SHA-256 `7124ae93f71ea1497b4bc01b8623ae41a4916f4033aa4cf108f466a5ce7ada8c` 를 R2b 빌드 스탬프 입력으로.
- **R2a 타깃 스크립트**: 위 1 절의 셸 규칙(ps 금지, 공백 기본값 금지, 함수 뒤 위치 매개변수 금지, 새 파일 이름 발행) 을 처음부터 적용.
