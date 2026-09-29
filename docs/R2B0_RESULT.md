# R2b-0 결과 — 2026-09-16 실기 (활성화 부팅, 기록 전용)

**판정 `R2B0: PASS-REFUSE`**(`parse_r2b0.py`), 120 줄, run `789526262`, stamp `e48c2e8d`,
reloc `52874 161`.  증거: `build/r2b0/789526262/`(로그·도구 출력·`r2b0-facts-789526262.txt`),
설정 스냅샷 `build/r2b0/cfg/ACT/{pre,postraw,post,postb,post3}`.

## 1. 이 부팅에서 드라이버가 한 일

| 줄 | 뜻 |
|---|---|
| `probe rc=0 loc=03:0b.0 id=59601002 accept` | **빈 `Location` 으로 카드에 묶였다** — PCIBus 가 `Auto Detect IDs` 스캔으로 서술자를 채웠다 |
| `claim held=0 result=claim` | 한 번만 잡혔다 — 주차로 인스턴스가 하나였다 |
| `init boot=dead5d96 build=e48c2e8d loc=03:0b.0 key=yes cmode=2 bar0=e0000000 bar2=d0200000 ok` | 초기화 성공, 옵트인 키 읽힘, **`cmode=2`**(VGA 부팅의 1 과 다르다) |
| `revert n=1` → `enter n=1 refused` | 커널이 리니어 모드를 요청했고 **계약대로 거절**.  모드 레지스터 쓰기 0 회 |
| `verdict gates=32 refused=1 result=refuse` | 32 게이트 중 `divsel` 하나가 거절 → 기록만 하고 진입 거부(이 빌드의 정답) |

화면은 깨져 보였다.  이 빌드는 모드 레지스터를 하나도 쓰지 않으므로 커널 콘솔이 남긴 상태가 그대로
남는다 — 예상된 결과이고 telnet 은 끝까지 살아 있었다.

## 2. 측정값 (R2 입력)

- **콘솔이 640×480**(CRTC1 words, totals 768×524, hsync/vsync 양극성), **`PLL_DIV_SEL = 1`**.
  R2a 때는 800×600·`DIV_SEL 3` 이었다 — **부팅마다 콘솔 모드가 다르다**.  R2a 와 다른 레지스터:
  `CLOCK_CNTL_INDEX`(00000103 vs 00000303), `CRTC_EXT_CNTL`, `CRTC_H_SYNC_STRT_WID`,
  `CRTC_H_TOTAL_DISP`, `CRTC_PITCH`, `CRTC_V_SYNC_STRT_WID`, `CRTC_V_TOTAL_DISP`.
  → **R2 의 복귀 스냅샷은 부팅 시점 값이어야 하고, R2a 값을 상수로 굳히면 안 된다.**
- **MC 맵은 R1 이후 그대로이고 자기 일관적이다**: `MC_FB_LOCATION = 1fff0000`(카드 주소 공간에서
  시작 0, 끝 `1fff0000`), `DISPLAY_BASE_ADDR = 0`, `displaybase` 게이트 통과.  R1 파서의
  "RV280 정렬 애퍼처 기준과 다르다 — R2 는 MC 맵을 다시 써야 한다" 는 **카드 주소(0)와 PCI 애퍼처
  기준(`e0000000`)이라는 서로 다른 공간을 비교한 것**이고, "카드 주소 = CPU 주소" 로 맞추려는
  드라이버에게만 뜻이 있다.  R2 계획은 MC 맵을 건드리지 않기로 했으므로(F4) **다시 쓸 일이 없다**.
  (2026-09-16 정정: 이 줄을 처음에 파서 문구 그대로 옮겨 적었다.)
- PLL 묶음 12 개 완주, `PPLL_DIV_0..3` VCO 301.5 / 339.75 / 202.5 / 227.25 MHz — 모두 200–400 MHz 안.
- VGA 레지스터가 **커널 콘솔 표와 일치**(커서·시작 바이트 차이 없음), MISC 클럭 선택 0, ATTR10 `01`.
- CP 큐 모드 0(꺼짐), 온칩 PCI GART 번역 꺼짐, `RBBM_ACTIVE=0`, PCI 명령 `0307`(버스마스터 켜짐),
  `CRTC_EN=1`·`EXT_DISP_EN=0`·`DISPLAY_DIS=0`.
- 시간: `IODelay(2000)` 이 1872–1881 µs, 60 프레임 69998 µs(4 회 실패), 1000 프레임 1010000 µs(60 회 실패).

## 3. 절차가 실제로 어떻게 돌았나

1. `cfgsnap pre ACT` → `precheck PASS`(그 직전 `restored PASS` 로 VGA 기준선임을 확인) →
   `pack_restore ACT` → `stage-restore ACT` → `check.sh differ=0 extra=0`.
2. operator 가 Configure.app 에서 VGA → OSRDNDisplay 저장·닫기.  R-1·R-1c 와 **똑같이**
   `Instance1` 이 추가되고 우리 `Instance0` 이 `444`→`644` 로 다시 쓰였다.
3. `cfgsnap postraw ACT` → `target-park-extra-r2b0.sh closed=yes` → `parked=1 left: Instance0.table`.
4. `cfgsnap post ACT` → **`activate PASS`**(NOTE 둘: VGA 인스턴스 삭제, 우리 표 모드) →
   `cfgsnap postb ACT` → **`same post postb PASS`** → operator 재부팅.
5. 부팅 뒤 telnet 생존.  `/ndrv` 는 **수동 마운트**가 필요했다(gcdsd 도 내려가 있어 gcds 경로는 못 쓴다 —
   telnet + expect 로 진행).  로그인 셸이 csh 라 `2>&1` 은 "Ambiguous output redirect", `>&` 를 썼다.
6. `target-run-r2b0.sh 789526262` → 상태 줄 확인 → 기록 120 줄 → 호스트 판정 `PASS-REFUSE`.
7. `restore.sh`(`wrote=5 parked=0`) → `cfgsnap post3 ACT` → **`restored PASS`**(17 표 바이트 동일) →
   operator 재부팅 → `Active Drivers` 끝이 `VGA`, 두 번들 온전.

## 4. 남은 것

- ~~계획 §15-5~~ **완료(2026-09-16)**: 근거로 쓰는 파일 6 곳(계획서 3, `OSRDNDisplay.m`,
  `parse_r2b0.py`, `rdnbios.c`)에서 인용을 걷어냈다 — 주장은 남기고 근거 칸을
  `근거 미확정(§15-5)` 으로 낮추되 같은 줄의 허용 근거는 보존.  재근거가 선 것: `SEQ1 = 01` 은
  R2a·R2b-0 두 실행의 실측, `IODelay` 는 "부팅마다 다르다" 는 실측만(1.87 / 2.05 / 4.1 ms).
  `docs/review/` 는 교차검토 원문 기록이라 그대로 두고 검사에서 제외한다.  재발 방지는
  `tools/check_sources.py`(`check-all` 의 `== sources ==` 단계): 그 프로젝트의 경로·디컴파일된
  함수 파일 이름·Ghidra 심볼·그 프로젝트가 내놓는 표와 어셈블리 덤프 파일 이름을 인용하면 거절하고,
  산문에서 이름을 부르는 것은 허용하며, 자체검사로 발동을 증명한다(패턴 자체는 그 파일에만 적는다).
- ~~Adaptec2940 의 낡은 `Location`~~ **정리 완료(2026-09-16)**: `Dev:11 Func:0 Bus:3` → `""`.
  새 바이트는 호스트에서 만들고(`build/r2b0/adaptec/Instance0.table.{orig,new}`), 타깃은 곁 파일
  → `chown root.wheel`·`chmod 644` → `cmp` → `mv` → `sync` 로 교체했다(622 → 603 바이트,
  sum `36916 1` → `34392 1`, **바뀐 줄은 `Location` 하나뿐**).  백업 `/me/rdn-adaptec-backup/
  Instance0.table.20260916`.  `check_cfgdiff` 의 키 있는 예외는 **비웠다** — 이제 낡은 `Location` 은
  다시 FAIL 이고, 스냅샷 `build/r2b0/cfg/ADP/pre` 로 `precheck PASS`(NOTE 없음).
- R2b(첫 모드셋): 복귀 스냅샷을 부팅 시점 값으로.  MC 맵은 건드리지 않는다(위 2 절).
