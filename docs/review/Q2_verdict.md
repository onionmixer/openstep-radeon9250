# Q2 판정 — R1(조사)·R2(첫 점등) 안전성

질문 `Q2_prompt.md`, 회신 `Q2_reply.md` (gpt-5.6-sol, read-only, 2026-09-15).
회신의 인용 89곳을 Python 으로 해당 줄 범위와 기대 문자열 대조 → 87 일치, 2 곳은
필드가 소문자(`dac2_cntl`, `surface_cntl`)라 문자열이 안 맞았을 뿐 본문을 열어
내용 일치 확인(`legacy_output.c:1492-1520`, `legacy_crtc.c:737-759`).  계획을
바꾸는 주장은 아래 "내 검증" 칸의 본문을 직접 읽었다.  `X/` = xf86-video-ati
6.14.6 `src/`, `N/` = NetBSD `radeonfb.c`, `F/` = FreeBSD stable/9 drm.

## 내가 틀렸던 것 (먼저)

| 내 계획의 서술 | 사실 | 근거(이 세션에서 연 곳) |
|---|---|---|
| 금지 2: "리셋 레지스터 쓰기 직후 레지스터를 읽지 않는다" | **두 참고 구현 모두 `RBBM_SOFT_RESET` 을 쓴 직후 같은 레지스터를 읽는다**(posted write 밀어내기), 명시적 대기 0 | `N/:3948-3964`, `F/radeon_cp.c:650-669` 본문 |
| R1 "스캔아웃 생존: 라인 카운터 단조 증가" | `CRTC_VLINE_CRNT_VLINE` 은 11 비트 필드라 **프레임마다 되감긴다** | `radeonfbreg.h:573-575` `(0x7ff << 16)` |
| R1 Gate "VRAM 실측" | R1 은 레지스터 **보고값**만 읽는다. 실측은 VRAM 쓰기가 필요하다(Matrox H1 S3 도 쓰기 등급) | `openstep-matrox-remade/docs/H1_HARDWARE_INTERROGATION_DECISION.md:39-45` S3 행 |
| R1 "쓰기 0 건(BAR 크기 측정 제외)" 을 read-only 단계로 부름 | BAR write-1s 는 config **쓰기**, PLL 인덱스 읽기는 `CLOCK_CNTL_INDEX` **쓰기**를 포함 | `N/:1571-1584`, `radeonfbreg.h:329-332`, Matrox `OpenStepMGAProbe.m:115-119` |
| R2 "PLL(RV280 기준표, 락 대기)" | RV280 기준표는 TMDS 표였고(이미 정정), 락 대기는 참고에서 50 ms **고정 지연**이지 판정 대기가 아니다 | `N/:2259-2264` `delay(50000)` |
| R2 "모든 쓰기 후 되읽기" | 리셋 레지스터·되읽기가 반전되는 비트(RV280 `TMDS_PLL_CNTL` bit 22) 등 **되읽기가 성립하지 않는 레지스터**가 있다 | `N/:2621-2627` "reads back inverted, DON'T trust the readback", `X/legacy_output.c:380-404` |

## 판정표

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| 1a | BAR write-1s 는 살아 있는 디코더의 base 를 순간 바꾸는 config 쓰기이고, G450 선례는 한 번의 성공이지 RV280 보증이 아니다 | Matrox probe `:115-119`, H1 `:39-44`(command reg 미변경으로 VGA 창 유지) 열람. RV280 에서의 안전성은 소스에 없음 | ⚖️ **부분 채택** — 위험 분류는 받는다. 다만 이 측정은 **필요 없다**: 애퍼처는 `CONFIG_APER_SIZE` 로, BAR 창은 브리지 창과 BAR 값 읽기로 얻는다. → R1 에서 **BAR sizing 을 뺀다**(필요가 생기면 별도 승인 단계) |
| 1b | ROM BAR 에 all-ones 를 쓰면 enable 비트까지 선다 | `N/:1474-1480` 열람 | ✅ (1a 로 함께 제거) |
| 1c | 명명 레지스터 읽기에 부작용이 있다는 근거는 없다, 그러나 PCI 트랜잭션이 안 돌아오면 카운터도 소용없다 | `F/radeon_irq.c:308-318`, `F/radeon_cp.c:298-309`, `:172-184`; Matrox `REMAINING_WORK.md:3999-4007` 본문 | ✅ 채택 — R1 은 **nxlogd(NFS fsync) 로그를 켠 부팅**에서만(`REMAINING_WORK.md:4051-4056`: "켜지 않은 것이 가장 값비싼 실수") |
| 1d | VLINE 은 되감긴다 | 위 "틀렸던 것" | ✅ 채택 — 판정을 "`CRTC_CRNT_FRAME`(0x0214) 증가 + VLINE 값이 여러 표본에서 달라짐" 으로 |
| 1e | PLL 인덱스 읽기는 쓰기를 포함, RV280 전용 에라타는 확인 안 됨 | `X/radeon_driver.c:566-605, 1976-1992` 본문 — 에라타 플래그는 R300/RV200/RS200/RV100/RS100 뿐 | ✅ 채택 — R1 기본 조사에서 빼고, 필요하면 인덱스 저장·복원 등급으로 분리 |
| 1f | `0xC0000` 매핑 자체의 위험은 미확인, **확정 위험은 신뢰할 수 없는 포인터 파싱** | `N/:1710-1726` 이중 역참조 확인 | ✅ 채택 — 셰도는 **고정 크기로 복사한 뒤 호스트에서 파싱**(커널 안 파싱 금지) |
| 2 | `0xC0000` 은 주 디스플레이 폴백일 뿐 BDF 를 식별하지 못한다, xf86 은 PCIR vendor/device 를 대조하지 않는다 | `X/radeon_bios.c:67-97, 380-427` 본문 — 대조 코드 없음 확인 | ✅ 채택 — 이 머신은 카드 한 장(G450 대체)이라 모호성은 작지만, **셰도의 PCIR vendor/device 를 이 카드 config 와 대조**하는 계획을 유지 |
| 3 | R2 가 빠뜨린 레지스터군 14 종(MC 정지·전체 MC 맵·GEN/EXT 필드·MERGE·CRTC2·DAC 경로/전원·FP/TMDS 비활성·RMX·전체 PPLL 전이·팔레트 접근·공용 클라이언트·SURFACE·엔진/CP 정지) | 인용 대조 통과 + `N/:2340-2634`(modeswitch/setcrtc), `N/:2136-2334`(PLL), `N/:2843-2923`(fbloc), `N/:2924-3052`(misc/palette), `X/legacy_crtc.c:60-425`, `X/legacy_output.c:1492-1520` 본문을 읽었다 | ✅ **채택** — R2 단계 설명을 "레지스터군 목록은 R0-2 해독 문서가 정본" 으로 바꾸고, 그 문서의 필수 항목으로 넣는다 |
| 3b | 레거시 RV280 의 "VGA 디코더 끄기" 전용 시퀀스는 확인 안 됨, AVIVO 레지스터를 가져오면 안 된다 | `X/radeon_driver.c:4031-4035` AVIVO 분기 확인 | ✅ 채택 |
| 4 | 첫 부팅 `revertToVGAMode` 는 스냅샷이 유효하고 하드웨어를 바꾼 경우에만 복원, 재진입·부분 진입 대비 | Matrox `REMAINING_WORK.md:3310-3317`(revert 가 enter 보다 먼저), `:3580-3605`(로그아웃은 둘 다 안 부름, 부팅 revert 는 초기화), `:3640-3647`(종료는 revert 를 부름) 본문 | ✅ **채택** |
| 4b | xf86 저장 목록과 복원 순서(DAC 마지막, "crtc by accident … hang") | `X/radeon_driver.c:5753-5900` 본문 | ✅ 채택 — R0-3 문서의 정본 입력 |
| 5a | "generic VGA 소유라 안전" 은 G450 결과의 외삽 | 사실 | ✅ 채택 — 문구를 "G450 에서 안전했던 방법" 으로 |
| 5b | 참고 구현에 무한 대기가 있다: `radeonfb_pllwriteupdate` 의 `while`, 엔진 대기, xf86 MC 대기는 타임아웃 로그 후에도 계속 돈다 | `N/:2136-2147` 본문, `X/radeon_driver.c:4127-4145` 본문 — 로그·2 초 대기 후 루프 탈출 없음 확인 | ✅ 채택 — **모든 대기에 상한 + 실패 시 종결 걸쇠**(Matrox 3-61) |
| 5c | 모듈 재적재 금지, 새 활성화 부팅에서만 | 사실 | ✅ (계획 금지 3 과 일치, R2 에 명시) |
| 6a | CP 상태는 `CP_CSQ_CNTL` 하나로 표현되지 않는다 | `F/radeon_cp.c:726-779` 본문 | ✅ 채택 — R1 읽기 목록에 `CP_RB_CNTL`, `CP_RB_RPTR/WPTR`, `BUS_CNTL`(BUS_MASTER_DIS) 추가 |
| 6b | MC 레지스터는 값이 바뀔 때만 쓴다 | `X/radeon_driver.c:4081-4086` 본문 | ✅ 채택 — R1 에서 BIOS 가 둔 `MC_FB_LOCATION` 을 기록하고 R2 는 같으면 쓰지 않는다 |
| 6c | RV280 은 MC 위치를 크기에 정렬해야 한다 | `X/radeon_driver.c:1498-1513` 본문 "Affected chips are rv280" 확인 | ✅ 채택 |
| 6d | 크기 선택: 0 이면 8 MiB, 애퍼처가 크면 애퍼처 | `X/radeon_driver.c:1441-1451` 본문 | ✅ 채택(사실표에) |
| 6e | RBBM 리셋 후 참고 대기는 0 | 위 "틀렸던 것" | ✅ 채택 — 금지 2 를 "참고 시퀀스를 그대로, **참고에 없는 읽기를 리셋 창에 넣지 않는다**" 로 정밀화 |
| 6f | 확인된 지연: PPLL 50 ms, MC 재배치 전후 100 ms | `N/:2259-2264, 2863-2869, 2903-2909` | ✅ |

## 새로 발견한 것 (codex 가 말하지 않음, 내가 소스에서)

1. `radeonfb_set_fbloc` 는 `HOST_PATH_CNTL` 을 **0 으로 쓴다**(`N/:2889`) — xf86 이
   RV280 에서 세우는 `HDP_APER_CNTL` 을 지운다.  두 참고가 충돌한다 → R0-1 사실표에
   "충돌, R1 실측값 기록 후 결정" 으로.
2. `RADEON_PPLL_ATOMIC_UPDATE_R` 와 `_W` 는 **같은 비트 15**(`radeonfbreg.h:1529-1530`).
   xf86 은 쓰기 후 그 비트가 **내려갈 때까지** 기다리는데(`X/legacy_crtc.c:216-228`),
   radeonfb 의 `radeonfb_pllwaitatomicread` 는 비트가 **설 때까지** 기다려
   (`N/:2150-2166`) 방금 세운 비트를 보고 곧장 빠진다 → xf86 의미를 따른다.
3. radeonfb 는 `PPLL_DIV_0` 을 덮어쓰고(`N/:2237-2238`), xf86 은 `PPLL_DIV_3` 에
   쓰며 `PLL_DIV_SEL=3`(`X/legacy_crtc.c:348-380`).  VGA 가 쓰는 분주 슬롯을
   건드리지 않는 쪽이 복귀에 유리할 수 있다 `[미검증 설계 논점]`.
4. radeonfb 의 `init_misc` 는 `BUS_CNTL` 에 `BUS_MASTER_DIS` 를 쓴다(`N/:2926-2937`)
   → R5 에서 버스 마스터를 켜려면 이 비트를 다룬다.

## 2차 자기검사

✅ 행을 다시 읽었다.  6b·6c·6d·5b 는 처음엔 인용 대조만 했다 → 본문
(`X/radeon_driver.c:1436-1520`, `:4076-4150`)을 열어 확인했다.  4 의 Matrox
기록 세 곳도 본문을 열었다.  1a 는 codex 결론(“깨끗한 방법이 없다”)을 그대로
받지 않고, **측정 자체가 필요 없다**는 다른 결론으로 부분 채택했다 — 그 근거(애퍼처
레지스터·브리지 창 읽기)는 Q1 판정에서 이미 연 소스다.
