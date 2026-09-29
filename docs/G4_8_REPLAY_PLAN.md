# G4-8 — 멈춘 스트림의 오프스크린 재생 (도구만, 재부팅 없음) (계획, 2026-09-28, 코딩 전)

## 0. 범위와 전제

- 출발: `docs/G4_6_GLQUAKE_PLAN.md` §11 — 정지는 혼합 두 모드에 특정된다; 남은 후보는 양·이력·GLQuake 의 텍스처 조합.  사용자 선택(2026-09-28): 후보 ① **멈춘 스트림을 그대로 다시 보내는 도구**.
- 만드는 것: `tools/g48/rdnreplay.c` 하나(순수 C, 타깃에서 `cc -O -Wall`).  커널·라이브러리·검증기 규칙 **불변**.  재생하는 것: `build/g46/trace-last.bin` 의 앞 **4,067 워드**(`trace.txt` 마지막 기록 `000004c1 00000fe3 …` 의 워드 수; 파일은 4,068 워드로 끝 한 워드는 앞 스트림의 잔여).
- 규칙: 계산은 python, codex 는 계획에(§6), 참조는 연 줄만, 실기 실행은 승인 뒤(정지 위험), 재부팅은 사용자.

## 1. 참조 (항목마다 연 것)

| # | 사실 | 근거(연 줄) |
|---|---|---|
| P1 | 라이브러리의 제출: `osrdn_r7b_submit2` 를 magic·version·nwords·seed·words(자기 캐시 버퍼)로 채우고 `SUBMIT2` ioctl 한 번; 성공 판정은 `status == 0 && why == 0 && drawn != 0`; open 은 제출마다 `open(NODE, NODE_RDWR)`(`/dev/rdnvram0`, 2) | `OSRDNMesaTri.c:40-41`·`:384-390`·`:904-938` |
| P2 | 커널 SUBMIT2: magic/version 2·`1 ≤ n ≤ 4068`·seed ≠ 0·words ≠ 0·장치 준비를 본 뒤 `CP_R7_APPEND_MAX` 워드씩 `copyin` 해 stage, 그 뒤는 R7a 와 같은 검증·그리기 | `OSRDNDisplay.m:1124-1178`; `osrdn_r7b.h:24`·`:29`·`:87-98` |
| P3 | 장치 도구의 열기·CAPS: `mknod`(major<<8)·`open(NODE, O_RDWR)`·`CAPS` ioctl 로 magic/version/window/bytes/maxWords/build/ready/cpRunning/**winStart** 를 받는다; 시드는 run id(0 아님·반복 안 함) | `rdnr7dev.c:66`·`:587-612`·`:676-678` |
| P4 | 시드 규칙: 0 이 아니고 직전 연산의 것과 달라야(`CP_WHY_SEED`) | `OSRDNMesaTri.c:874-876`; [[runner-must-seed-every-accel-process]] |
| P5 | breadcrumb: fd 하나를 열어 두고 record 마다 write + fsync (재open 은 마지막 하나만 남긴다) | `ghostprobe_v20.c:108-124`; `nxbreadcrumb.c` 머리말 |
| P6 | 멈춘 스트림의 모양(해독 `build/g46/trace-last.decoded.txt`): `RB3D_COLOROFFSET` 0x00400000·`RB3D_DEPTHOFFSET` 0x00900000·`PP_TXOFFSET_0` 0x00cffe00–0x00d4a800, 전부 창 [0x400000, 0x7c00000) 안; PACKET3 다섯 개가 워드 60·1473·1565·1659·2511 에서 시작, 끝 4067(python); `verify_oracle.verify(words, 0x400000, 0x7c00000)` → `(0, None)` = OK(이 세션에서 재실행) | `build/g46/trace-last.decoded.txt`; `verify_oracle.py:246-264` |
| P7 | 화면은 VRAM 0(`CRTC_OFFSET` 0), 창은 0x400000 부터 — 재생은 화면 밖에 그린다 | `build/g46/messages-after-trace-freeze.txt` 의 `RDN-R2B reg CRTC_OFFSET snap=00000000 got=00000000` |

## 2. 설계 (`tools/g48/rdnreplay.c`)

```
rdnreplay <runid> <major> <file> words=<N> reps=<R> [crumb=<path>] [stop=<k>]
```
1. `rdnr7dev.c` 의 열기·CAPS 절차를 그대로(P3): mknod/open, CAPS, magic·version·`ready`·`cpRunning`·`maxWords ≥ N` 게이트(C5: 커널의 `nodev` 전제 — 창 고정·record·MMIO — 는 `ready`/`cpRunning` 으로 드러난다; "winStart 만 같으면 된다" 가 아니다).  mmap 은 하지 않는다(SUBMIT2 는 클라이언트 메모리에서 copyin, P2).
2. 파일을 읽어 `N` 워드를 `malloc` 버퍼에.  **스트림 자체 게이트**(제출 전, 실패면 아무것도 안 보내고 종료): (a) PACKET0/2/3 헤더를 따라 걸어 정확히 `N` 에서 끝나는가(경계 밖이면 거절 — 접두 재생 때 잘못 자른 것을 잡는다), (b) 스트림 안의 `RB3D_COLOROFFSET` 값이 `caps.winStart` 와 같은가 — **재배치는 하지 않는다**(같지 않으면 다른 부팅의 창이라 그대로 보내면 안 된다), (c) 모든 PACKET0 레지스터가 `cpR7Allow` 42 개 안인가(오라클과 같은 표를 `verify_oracle.py --c-tables` 에서 복사, `check_r7b` 방식대로 생성본과 대조).
3. **CAPS 에 쓴 fd 를 먼저 닫는다**(C2: 커널의 open 은 이진 걸쇠라 쥔 채 두 번째 open 은 거절).  반복 `k = 0..R−1`: crumb `"rep k seed s"` (fsync) → `s2` 를 라이브러리와 **같은 필드·같은 순서**로 채워(P1) `open → SUBMIT2 → close` → crumb `"done k status why at drawn"`.  시드 `s = (runid mod 4,000,000) × 1000 + k + 1`(C3: `runid + k` 는 다음 호출의 runid 와 겹칠 수 있다; 러너들의 SEEDBASE 방식, k < 999).  **ioctl 반환값이 0 이 아니면 회신 필드는 무효**(C4, `osrdn_r7b.h:15-16`) — errno 를 찍고 멈춘다; 0 이면 `status ≠ 0 || why ≠ 0 || drawn == 0` 에서 멈추고 마지막 회신을 찍는다.  `stop=k` 는 k 회에서 멈춰 마지막 crumb 가 어디까지인지 시험하는 자기검사용.
4. 모든 출력 줄은 `RDNREPLAY ` 로 시작(판정 스크립트가 grep).

## 3. 호스트 검사 (코딩 전에 정한다)

- `tools/g48/check_replay.py`: (1) `rdnreplay.c` 안의 허용 표가 `verify_oracle.ALLOW` 와 같다, (2) 재생 파일의 앞 N 워드가 도구의 걷기 규칙과 같은 python 걷기로 경계에서 끝난다·`verify()` OK, (3) 접두 후보 목록(§4 의 이분 탐색용)이 전부 경계에 있다, (4) 소스 규칙: `mmap` 호출 없음, `SUBMIT`(구형) 없음, `#import` 없음(순수 C, `rdnr7dev.c` 의 취지), 출력은 `RDNREPLAY ` 접두.  자체시험은 각 규칙에 변이 하나.
- `gcc -m32 -fsyntax-only`(호스트, 타깃 헤더 없이 컴파일되는 순수 C 부분) — `rdnr7dev.c` 가 같은 방식으로 검사되는지 `check_r7b.py` 를 보고 맞춘다.
- 싼 검사 먼저, 마지막에 `check-all` 한 번(새 검사기는 `check-all.sh` 에 한 줄).

## 4. 실기 (재부팅 없음, 지금 부팅 11, 사용자 gcdsd 아래 오프스크린 — 화면엔 아무것도 안 그린다, P7)

1. 타깃 빌드 `cc -O -Wall -o rdnreplay rdnreplay.c` → `nm -u` 로 미정의 심볼이 libc 것뿐인지.
2. **reps=1**: 멈춘 스트림 한 번.  crumb `build/g48/replay.crumbs`.  멈추면 4,067 워드 재현기 확정(→ 재부팅 뒤 접두 이분: 60·1473·1565·1659·2511 경계).
3. 멀쩡하면 **reps=436**(멈춘 실행에서 혼합 모드가 돈 제출 수): 같은 스트림을 436 번.  멈추면 "양·반복" 이 원인 축; crumb 의 마지막 `rep k` 가 몇 번째인지 남는다.
4. 둘 다 멀쩡하면 **이력 의존** 확정 → G4-6 §11 후보 ②(전 스트림 기록 라이브러리)로.
- 매 단계는 정지 위험이 있으므로 **각 단계 전에 승인**을 받는다.  판정: `check_r6a` 가 아니라 crumb 파일과 커널 로그(`RDN-R5 … rc=`·`RDN-R4 open`)로, `tools/g48/judge_replay.py` 가 crumb 짝(rep/done)과 status/why/drawn 을 센다.

## 5. 위험

| 위험 | 완화 |
|---|---|
| 재생이 머신을 굳힌다 | 그것이 실험의 목적; crumb 가 회차를 남긴다; 재부팅은 사용자 |
| 다른 부팅의 창 주소로 보낸다 | §2-2(b) 게이트: `caps.winStart` 와 스트림의 COLOROFFSET 이 다르면 안 보낸다 |
| 텍셀 내용이 원래와 다르다(업로드 없음) | 정지가 텍셀 값에 달렸다면 놓친다 — 결과 해석에 적는다; 레벨 배치·크기·필터는 그대로 |
| 접두를 패킷 중간에서 자른다 | §2-2(a) 걷기 게이트 + python 사전 계산(§3-3) |
| 시드 충돌 | runid + k, 호출마다 새 runid |
| 화면을 덮는다 | 창은 0x400000 부터, 화면은 0(P7); present 안 함 |

## 6. codex 교차검토 (코딩 전, 한 호출 = 한 주장·국지적)

주장: "`rdnreplay` 의 SUBMIT2 호출은 라이브러리 `triSubmit` 의 copyin 경로와 같은 계약(구조체 필드·ioctl·제출마다 open/close·시드 규칙)이고, `caps.winStart` 가 스트림의 COLOROFFSET 과 같으면 재배치 없이 그 워드 그대로 보내도 된다."  codex 에 물을 것: `OSRDNMesaTri.c:377-404`·`:883-938`, `OSRDNDisplay.m:1124-1178`, `osrdn_r7b.h`, `rdnr7dev.c:580-612` 에서 이 주장을 깨는 전제(버퍼 정렬·페이지·held fd·open 모드·시드·nwords 상한·`words` 의 의미)가 있는가.

### 6-1. codex 판정표 (2026-09-28, GPT-6-Astra 한 호출; 전부 원문을 열어 확인)

| # | codex 주장 | 내 검증(연 것) | 판정 |
|---|---|---|---|
| C1 | 라이브러리는 hold 가 켜지면 open/close 를 제출마다 하지 않는다(`triHeldFd`) | `OSRDNMesaTri.c:383-384`·`:398-400` | ✅ 사실 — 도구는 hold 없는 경로(제출마다 open/close)를 따른다고 §2-3 에 명시 |
| C2 | CAPS 용 fd 를 쥔 채 반복 open 을 하면 거절된다(gate C) | `rdnr7dev.c:620-626` "a second open while this one holds the node. It must be refused" | ✅ 채택 — §2-3 CAPS fd 닫기 |
| C3 | `runid + k` 는 다음 호출의 runid 와 겹칠 수 있다; 라이브러리는 `triSeed++` 로 0 도 피한다 | `osrdn_r7b.h:58`, `OSRDNMesaTri.c:905-907`, `osrdn_cp.m:1220`·`:1230`(lastSeed 는 커널에 남는다) | ✅ 채택 — 시드 식 교체 |
| C4 | ioctl 반환값 검사를 복사해야(비0 이면 회신 무효) | `OSRDNMesaTri.c:922-929`·`:969-972`, `osrdn_r7b.h:15-16` | ✅ 채택 |
| C5 | winStart 외에 `nodev` 전제(`rdnR7bVirt`·창 고정·record·MMIO) | `OSRDNDisplay.m:1147-1148` | ✅ 채택 — §2-1 문구 |
| C6 | malloc 버퍼·mmap 생략을 깨는 조건 없음(`words` 는 클라이언트 캐시 메모리, copyin) | `osrdn_r7b.h:92`, `OSRDNDisplay.m:1171-1172` | ✅ 사실 |
| C7 | 토큰은 커널이 만든다(스트림에 부팅 값 없음); `NODE_RDWR` 정의는 범위 밖 | `OSRDNDisplay.m:1165`; `OSRDNMesaTri.c:42` = 2 = `O_RDWR`(내가 열어 확인) | ✅ 사실 |

## 7. 구현과 호스트 게이트 (2026-09-28)

- `tools/g48/rdnreplay.c`(순수 C): §2 대로 — CAPS 뒤 fd 닫기(C2), 시드 `(runid mod 4,000,000) × 1000 + k + 1`(C3), `rc != 0` 이면 회신 무효로 종료(C4), 걷기·허용 표·창 게이트, crumb `rep`/`done`/`ioctl`, `stop=k` 자기검사.  crumb 열기는 `O_WRONLY|O_CREAT|O_APPEND` = `1|01000|010`(`bsd/sys/fcntl.h` 35·38·40 을 미러에서 열어 확인).
- `tools/g48/check_replay.py`: 허용 표 = `verify_oracle.ALLOW`(42), 접두 후보 6 개(60·1473·1565·1659·2511·4067) 전부 패킷 경계·COLOROFFSET 0x400000·허용 레지스터만, 전체 스트림 `verify()` OK, 소스 규칙 8(mmap 없음·구형 SUBMIT 없음·`#import` 지시문 없음·출력 접두·시드 식·CAPS fd 닫기 순서·rc 검사·성공 판정·fsync).  자체시험: 변이 12 전부 잡힘.  `tools/g48/judge_replay.py`: crumb 의 rep/done 짝·status/why/drawn·시드 반복, 자체시험 7.
- 호스트 컴파일: hostcheck 와 같은 타깃 헤더로 `gcc-12 -m32 -nostdinc … -std=c89 -Wall -pedantic -fsyntax-only` 깨끗.  `check-all.sh` 에 세 줄.
- 타깃 빌드: `cc -O -Wall` OK, `nm -u` 는 libc 심볼뿐(`_open _ioctl _close _write _fsync _mknod _stat _fopen _fread …`), `build/g48/rdnreplay`(sum 38997 32).

## 8. 실기 (부팅 11 = 026a93c8, 드라이버 f0d603c0, 사용자 gcdsd 아래 오프스크린)

- **마른 실행**(`stop=0`, runid 790541045): `caps … max=4068 build=f0d603c0 ready=1 cprunning=1 winstart=00400000` → `gates words=4067 colour=00400000` → `stop k=0`; crumb `rep 0 2541045001`(시드 = 790541045 mod 4,000,000 × 1000 + 1, python 확인).  노드는 `crw------- 38, 0`.  **제출 없이 게이트 셋 통과.**
- 러너 `build/g48/run_replay.sh <reps> [words]`: 새 runid, 재생, 커널 로그 꼬리, `judge_replay`.
- **1 단계, reps=1**(runid 790541149, 05:32): `done reps=1 words=4067 last: status=0 why=0 at=4067 drawn=1`, 커널 로그에 rc≠0 없음, `judge_replay` PASS.  **멈추지 않았다** — 멈춘 스트림 하나만으로는 재현되지 않는다(텍셀 내용은 원래와 다르다는 단서 유지).
- **2 단계, reps=436**(runid 790565344): crumb `rep 0..5` 는 전부 `done … 0 0 4067 1`, **`rep 6 2565344007` 뒤 `done` 없음 — 7 번째 제출에서 머신 정지**(ping 무응답, gcds 무응답).  `judge_replay`: "rep 6 has no done: the submission never returned (freeze)".  **재현기 확보**: GLQuake·창·텍스처 업로드 없이, 기록된 4,067 워드 스트림을 같은 부팅에서 7 번 보내면 굳는다(1 번은 멀쩡, 1 단계).
- 해석: 스트림은 회마다 같으므로 카드 상태도 회마다 같아야 한다 — 다른 것은 **링 위치**(제출마다 wptr 가 앞으로 가고 4,067 워드 제출은 매번 링 끝을 넘는다; 넘는 자리가 회마다 16 워드씩 이동)·시드/표지 값·누적되는 무엇.  가장 싼 가르기: **같은 반복을 혼합 모드가 아닌 스트림으로**(NMN 실행의 마지막 스트림 `build/g47/trace-nmn-last.bin`) — 그것도 굳으면 원인은 혼합 모드가 아니라 큰 스트림의 반복(링 감기)이고, 안 굳으면 혼합 모드 + 반복이다.  그다음 접두 길이(2511 등)로 링 전진량을 바꿔 굳는 회차가 움직이는지.

## 9. 다음 실험 (재부팅 뒤, 부팅 12; 계획, 코드 변경 없음)

**쌍둥이 스트림** `build/g48/trace-last-nmn.bin`: 멈춘 스트림과 **워드 셋만 다르다** — `PP_TXFILTER_0` 값 세 곳(워드 33·1654·2502)의 MIN 필드 6(혼합, hw 0xc) → 2(NEAREST_MIPMAP_NEAREST, hw 0x4); 길이·패킷·표면·MAX_MIP·다른 필드 전부 같다(python 으로 만들고 차이 워드 = {33, 1654, 2502} 확인, 오라클 `verify` OK, `check_replay` 의 `g48-twin` 규칙이 이 사실을 고정).  실기 실험(NMN GLQuake 는 910,916 삼각형에도 멀쩡)과 같은 필터 값이다.

| 순서 | 실행 | 갈리는 것 |
|---|---|---|
| 1 | 마운트 → **내 gcdsd**(오프스크린) → CP 여섯 단계 → 커널 로그 저장 | — |
| 2 | `run_replay.sh 436 4067 /ndrv/openstep-radeon9250/build/g48/trace-last-nmn.bin` (쌍둥이, 436 회) | **굳으면** 원인은 혼합 모드가 아니라 큰 스트림의 반복(링 감기·크기) 축; **안 굳으면** 혼합 모드 + 반복 축 |
| 3a | (2 가 굳었으면, 재부팅 뒤) 접두 2511 워드로 436 회 — 링 전진량이 달라 굳는 회차가 움직이는지 | 링 위치 의존 여부 |
| 3b | (2 가 안 굳었으면) 원본 스트림으로 회차 재현성: 다시 436 회 → 같은 7 번째에서 굳는가 | 결정적/확률적 |

- 각 실행은 정지 위험 → 단계마다 승인.  crumb 가 회차를 남긴다.
- 참고 대조(오프라인, 재부팅 대기 중): 링 감기 축이면 FreeBSD `radeon_cp.c`/`radeon_state.c` 의 링 관리(commit_ring·`RADEON_WAIT_UNTIL` 배치·BEGIN_RING 크기)와 우리 `cpR6Submit` 의 차이를 다시 본다([[r200-ring-wrap-like-bsd]]); 혼합 축이면 mesa-amber `r200_texstate.c` 의 T0/LRU 우회 조건과 TAM_DEBUG3 를 RV280 에서 시험할지(커널 허용 목록 변경·재부팅) 계획한다.
- **참고 대조(링 축, 오프라인, 재부팅 대기 중)**: 참조의 링은 **1 MB = 256 K 워드**(xorg `radeon_dri.h:44` 기본), 클라이언트 명령 버퍼는 16 KB(`radeon_common_context.h:332` `MAX_CMD_BUF_SZ`), DRM 은 한 cmdbuf 를 64 KB 까지 받는다(`radeon_state.c:2856`); `BEGIN_RING` 은 `radeon_wait_ring` 으로 `space > n` 을 기다리는데 `space = (head − tail) × 4`, 0 이하면 `+= size`(`radeon_cp.c:1901-1914`) — 빈 링에 size−1 까지 허용하므로 **규칙상** 우리처럼 4,096 워드 링에 4,080 워드를 넣는 것을 막지는 않지만, 참조에서는 한 제출이 링의 1.6 % 를 넘지 않아 **"제출 하나가 링을 거의 다 채우고 rptr 16 워드 앞까지 wptr 가 간다"** 는 상황 자체가 한 번도 없다.  우리 링은 `CP_RING_WORDS` 4,096(`osrdn_cp.h:51`), 최대 제출 4,068 + 12 = 4,080.  쌍둥이 실험이 링 축을 가리키면 다음 조치는 **링을 키우거나 제출 상한을 줄이는 것**(둘 다 커널)이다.

## 10. 구현 검토 — 링 제출 경로를 참조와 대조 (2026-09-28, 재부팅 대기 중, 사용자 지시 "지금 구현이 잘못됐는지")

| 항목 | 우리 | FreeBSD DRM / Linux KMS | 판정 |
|---|---|---|---|
| `CP_RB_CNTL` | 0x0804090b(부팅 로그 `rbcntl=`) | FreeBSD 식 `(1<<27) | (fetch_l2ow 1 << 18) | (rptr_update_l2qw 9 << 8) | bufsz 11` = **0x0804090b**(python 재계산, `radeon_cp.c:752-760`·`:1392-1396`); Linux `rb_blksz 9`·`max_fetch 1`(`r100.c` cp_init) | **같다** |
| `CP_RB_WPTR_DELAY` | 0(`osrdn_cp.m:991`) | 0(`radeon_cp.c:729`, `r100.c:1180`) | 같다 |
| 커밋 순서 | 16 정렬 PACKET2 패딩 → 펜스(serialize + `RBBM_STATUS` 읽기; WBINVD 는 `doWb` 일 때만, 지금은 nowb=1 이라 **생략**) → WPTR 쓰기 → RPTR 읽기(포스팅) → WPTR 되읽기 → RPTR==WPTR·idle 대기 | 16 정렬 패딩 → `DRM_MEMORYBARRIER` → **`GET_RING_HEAD`(RPTR 레지스터 읽기, 목적 미기재)** → WPTR 쓰기 → RPTR 읽기(포스팅) (`radeon_cp.c:2100-2128`) | 순서 같음; 다른 것은 **도어벨 앞의 RPTR 읽기 하나**(우리는 `RBBM_STATUS` 읽기) — 하드웨어 필수라는 근거는 없음 |
| 링 감기·마스킹 | `cpPut` 마스크, 끝 넘김 허용(M3f) | `write &= mask`(`radeon_drv.h:2096-2097`), `tail &= tail_mask`(`radeon_cp.c:2116`) | 같다 |
| 한 제출의 상한 | 4,068 + 12 = **4,080** 워드를 빈 4,096 링에(rptr 앞 16 워드 남김) | `BEGIN_RING(n)`: `_align_nr = 16 − ((tail+n)&15) + n`, `space > _align_nr×4` 를 기다림(`radeon_drv.h:2059-2063`, `radeon_cp.c:1910-1914`) — python: n=4079 → 4080 통과, **n=4080 → 4096 은 영원히 대기**(`FIXME: return value is ignored`, `:1925`); 실제 참조 링은 256 K 워드라 이 경계를 밟은 적이 없다 | **발자국은 같다(4,080 쓰고 16 남김)**; 참조가 실제로는 한 번도 안 가 본 자리 |
| CP 캐시 | — | Linux `r100.c:1130-1138`: CP 캐시 96 dw 중 **링 캐시 16 dw**(> 2 × max_fetch 4 dw) | 우리가 남기는 여유가 **정확히 링 캐시 크기(16 dw)** — 규칙으로 적힌 제약은 없지만, §9 의 접두 2,511 실험(여유 1,568)이 이 축을 가른다 |
| `RING_HIGH_MARK` 128 | — | 정의만 있고 커밋·대기에 안 쓰임(`radeon_drv.h:1821`, `radeon_cp.c:1399`) | 무관 |
| GART/AIC | aic=3(TRANSLATE_EN·DIS_OUT_OF_GART) | 같은 두 비트 | 같다(R5) |

결론: **링 설정·커밋 순서는 참조와 같다.**  참조와 실제로 다른 것은 링 크기(16 KiB vs 1 MiB)에서 오는 "제출 하나가 링을 16 워드만 남기고 채운다" 는 상황이며, 이는 참조가 규칙으로 금지하진 않지만 한 번도 실행해 본 적 없는 영역이다.  구현 오류로 단정할 근거는 없고, 이 축은 §9 의 접두 실험으로 잰다.  펜스의 WBINVD 생략(nowb)은 스누핑 실측([[openstep-i386-pci-snoops]])에 기대며 NMN 7,203 제출이 그 아래서 멀쩡했다.

### 6-2. codex 판정표 (§10 의 주장, GPT-6-Astra 한 호출; 전부 원문 확인)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| D1 | 참조는 도어벨 앞에 `GET_RING_HEAD`(RPTR 읽기)를 한다, 목적 미기재·반환값 미사용 | `radeon_cp.c:2118-2119`·`:2126-2128` 열어 확인 | ✅ 사실 — 표에 기록, 필수 근거 없음 |
| D2 | `radeon_wait_ring` 은 `space > n` — 완전 충전 불허 | `:1910-1914` | ✅ 사실 |
| D3 | `BEGIN_RING(4080)` 은 정렬 tail 에서 `_align_nr` 4096 → 통과 불가; n ≤ 4079(패딩 뒤 4080) | `radeon_drv.h:2059-2063`, python 재계산(n 4064/4079/4080) | ✅ 사실 — 발자국은 같다(4080) |
| D4 | 패딩·마스킹은 일치, wrap 금지 반례 없음 | `radeon_cp.c:2100-2116`, `radeon_drv.h:2096-2097` | ✅ |
| D5 | `RING_HIGH_MARK` 128 은 안 쓰인다 | `radeon_drv.h:1821` | ✅ |
| D6 | Linux 캐시 주석은 용량 설명이지 간격 규칙이 아니다 | `r100.c:1130-1138` | ✅ — 단 16 dw 일치는 실험 축으로 남긴다 |
| D7 | WPTR 쓰기의 idle/busy 규칙 없음; WPTR_DELAY 0 | `radeon_cp.c:729`, `r100.c:1180` | ✅ |
| D8 | 우리 WBINVD 는 `doWb` 조건부 | `osrdn_cp.m:757-758`, `:2978`(nowb 1 → doWb 0) | ✅ 사실 — 표에 기록 |

### 9-1. 데이터 구성 보강 (2026-09-28, 실행 전 재검토 — 사용자 지시 "freeze 상황에서도 필요한 데이터는 최대로")

빠져 있던 것: 굳은 회차 k 는 남지만 **그때 스트림이 링의 어디에 있었는가**(링 축의 정량)는 안 남았다.  부팅 12 는 깨끗하다 — CP START 뒤 제출이 없고(`RDN-R5 ptrs … wafter=16`, boot 1382650a; 마른 실행은 CAPS 만), 내 gcdsd 아래 다른 클라이언트도 없다.  따라서 회차마다의 링 위치는 **계산으로 확정**된다(커널 원문: 앞머리 15 쌍 30 워드 → 32, 클라이언트 `need = subWords + 2 + 10` → 4,067 이면 4,080, 16 정렬 `len = (n + 15) & ~15`; `osrdn_cp.m:2370`·`:3171`):

- rep k 의 클라이언트 워드 0 은 링 색인 `(16 + 32 + 2 + 4112 k) mod 4096` 에 놓이고, 회마다 **16 씩** 전진한다(4112 ≡ 16).  링 끝을 넘는 클라이언트 워드는 `4046 − 16k`(python 표: rep 0 → 4046, rep 6 → 3950, …).
- `judge_replay.py … --w0 16 --stream <file> --words 4067` 이 회차별 링 시작·교차 워드·그 워드가 든 패킷을 찍고, 굳은 회차에 FROZEN 을 붙인다(자체시험 PASS; 부팅 11 crumb 로 형식 확인 — 그 부팅은 w0 미상이라 수치는 무효).
- 실행 순서(같은 부팅에서 얻는 것을 최대로): ① 쌍둥이 436 회.  굳으면 회차 k 와 교차 워드가 남는다.  ② 안 굳으면 **원본 436 회를 같은 부팅에서** — 그때의 w0 는 `16 + 436 × 4112 mod 4096 = 2896`(python) 로 역시 확정; 원본이 부팅 11 의 rep 6 과 **다른 회차**에서 굳으면 링 위치 의존(w0 가 다르므로), 같은 6 이면 회수 의존.
- 굳은 뒤 남는 것: crumb(회차·시드), 러너 로그(시각), 위 계산(링 위치·패킷).  커널 msgbuf 의 마지막 줄들은 하드 행에서 유실될 수 있어 근거로 삼지 않는다.
- **부팅 12(1382650a), 쌍둥이 436 회**(runid 790568143, `build/g48/replay-790568143.crumbs`): 436 회 전부 `done … 0 0 4067 1`, 커널 로그 rc≠0 없음, `judge_replay` PASS.  **안 굳었다.**  회당 16 워드 전진이라 436 회는 256 가지 링 정렬을 전부 지났다(rep 0 교차 워드 4046 → rep 435 교차 워드 1182, 판정기 계산).  **링 감기·크기 축 배제**: 같은 길이·같은 패킷·같은 링 위치에서 필터 비트 셋만 다르면 굳지 않는다 → 정지는 **혼합 밉 모드(hw MIN 6) + 반복**에 특정된다.
- 다음: 같은 부팅에서 원본 436 회(w0 = 2896).  부팅 11 의 rep 6 과 회차가 같은지(회수 의존) 다른지(위치 의존)를 본다 — 링 축이 배제됐으니 "다른 회차" 는 위치가 아니라 확률·이력을 뜻할 수 있다; 어느 쪽이든 굳으면 교차 워드·패킷을 판정기가 남긴다.
- **부팅 12, 원본 436 회**(runid 790568209, w0 2896, `build/g48/replay-790568209.crumbs`): rep 0–4 `done … 1`, **`rep 5` 뒤 `done` 없음 — 6 번째 제출에서 머신 정지**(ping 무응답 13:13).  판정기: rep 5 의 클라이언트 워드 0 은 링 3008, 교차 워드 1086(첫 PACKET3 [60, 1469) 안) — 부팅 11 의 rep 6 과 **회차도 링 위치도 다르다**(그 부팅의 위치는 미상이지만 회차 6 ≠ 5).  쌍둥이가 같은 위치를 전부 지났으므로 위치는 무관.
- **확정**: 정지 = 혼합 밉 모드(hw MIN 6) 스트림의 반복, 6–7 회 근처(결정적이지 않고 근처에서 흔들림).  텍셀 내용 무관(업로드 없음), GLQuake 무관, 링 무관, TRI_PERF 무관.

## 11. 다음 계획 — 참조의 "텍스처 캐시 LRU 행 우회" 를 RV280 에서 시험 (코딩 전, codex 검토 대상)

- 근거: mesa-amber `r200_texstate_amber.c:1577-1587` — "Texture cache LRU hang workaround … the cases below attempt to only enable the workaround in the specific cases necessary, they were insufficient (bugzilla #1519, #729, #814)" → `PP_TAM_DEBUG3`(0x2d9c, `r200_reg_amber.h:1122`) = **0x6** 을 늘 쓴다.  R200 전용(`CHIP_FAMILY_R200`) 이고 "not needed for r200 derivatives" 라 적혀 있지만, 우리 증상(같은 삼선형 스트림을 6–7 회 반복하면 하드 행, 단일 레벨 모드는 무한 반복 OK)은 **텍스처 캐시가 누적되어 걸리는 무늬**와 맞고, 참조는 RV280 에서 이 우회를 시험한 적이 없다(꺼 두었을 뿐).  DRM 은 이 레지스터를 패킷 표로 통과시킨다(freebsd `radeon_state.c:694` `{R200_PP_TAM_DEBUG3, 1, "R200_PP_TAM_DEBUG3"}`, 칩 조건 없음).  초기값은 0(`r200_state_init_amber.c:1020`).
- 설계(커널만, 재부팅 1 회): G4-7 과 같은 자리 — 앞머리에 `P0(PP_TAM_DEBUG3) 0x6` 한 쌍(TRI_PERF 쌍 뒤, 표지 앞), `cpR6PreRegs` 끝에 추가(되읽기 기록, 게이트 아님), REC3D 에 0x2d9c 추가(4 의 배수 유지: 0x2d9c + 0x2d18(TXOFFSET_1)·0x2d04·0x2d08 같은 이웃 셋? → **후보를 codex 검토에서 정한다**), `R6_RING_OK`·`verify_oracle.RESERVED`·`prefix_words/expect`·`sim_r6` UC 순서·`check_r6a` 파서(zpre 12)·`design3` 34 워드 — G4-7 의 목록을 그대로 한 번 더.
- 실기: 재부팅 → 여섯 단계 → **원본 436 회**(우회 켜진 상태).  안 굳으면 우회가 답(→ 라이브러리 혼합 모드 개방, GLQuake 재실행으로 확인); 굳으면 회차를 비교하고 T0 우회(유닛 1 LOOKUP_DISABLE, 검증기 변경)로.
- 위험: 디버그 레지스터의 뜻을 모른다(비트 1·2). 참조가 R200 에서 3 년 넘게 늘 쓴 값이라는 것만 안다.  되읽기로 값이 박히는지 확인하고, 안 박히면(0 으로 읽힘) 쓰기 전용으로 기록.

### 11-1. codex 판정표 (§11 주장, GPT-6-Astra 한 호출; 전부 원문 확인)

| # | codex 주장 | 내 검증 | 판정 |
|---|---|---|---|
| E1 | 값 0x6 은 무조건이지만 GPU 쓰기는 **바뀔 때만**(`dbg != tam.cmd[TAM_DEBUG3]` 일 때 STATECHANGE) — "매 draw 방출" 은 부정확 | `r200_texstate_amber.c:1616-1618` | ✅ 사실 — 우리는 앞머리에서 매 제출 쓴다(같은 값을 다시 쓰는 것, 상위집합) |
| E2 | tam 원자는 `tex_any`(텍스처 유닛 하나라도 켜짐)일 때 활성, 비-R200 은 `never` | `r200_state_init_amber.c:255`·`:638-642`·`:671`·`:676` | ✅ |
| E3 | 초기값 0, 패킷은 헤더 1 + 데이터 1(`TAM_STATE_SIZE 2`), 동반 레지스터 없음 | `r200_state_init_amber.c:1020`·`:116`, `r200_context.h` TAM_* | ✅ |
| E4 | 방출 순서(tam 대 tex)는 지정 파일로는 확정 불가 | 내가 `r200_cmdbuf_amber.c:80`(tam) 과 `:84`(tex[i] 루프) 를 열어 확인: **tam 이 tex 앞** — 우리 앞머리(클라이언트 TXFILTER 앞)와 같은 순서 | ✅ 보완 — 순서 일치 |
| E5 | 비트 뜻은 주석 없음(옛 조건: 유닛 0/2/4 → 0x02, 유닛 1/3/5 → 0x04) | `r200_texstate_amber.c:1589-1614` | ✅ — §11 위험 항목 그대로 |
| E6 | T0 우회 정확한 조건·레지스터(TEX_1_ENABLE, TXFORMAT_1 LOOKUP_DISABLE, 첫 패스 변형은 PP_CNTL_X·TXMULTI_CTL) | `:1524-1532`·`:1544-1552`, `r200_state_init_amber.c:668`·`:546-553` | ✅ 기록 — 대체 후보 |
| E7 | DRM 은 패킷 50 을 칩 검사 없이 통과(`case R200_EMIT_PP_TAM_DEBUG3:` → "These packets don't contain memory offsets") | freebsd `radeon_state.c:220`·`:256-257`·`:694`, 방출 `:2610-2625` | ✅ |

설계 확정(G4-9 로 진행할 때): 앞머리에 `P0(PP_TAM_DEBUG3) 0x6` 한 쌍(TRI_PERF 쌍 뒤·표지 앞 = 클라이언트 TXFILTER 앞, E4), `cpR6PreRegs` 끝(기록만), REC3D +4(0x2d9c 와 이웃 셋은 코딩 때 정한다), 도구·판정기·인용은 G4-7 절차 그대로.  실기: 원본 436 회 재생 — 안 굳으면 우회 채택(라이브러리 혼합 모드 개방 → GLQuake 확인), 굳으면 T0 우회(E6)로.

## 12. G4-9 구현 (2026-09-28, 재부팅 13 대기 중 코딩; 설치 전 승인)

- 커널: `C_PP_TAM_DEBUG3 0x2d9c`·`C_PP_TAM_DEBUG3_LRU 0x6`; 앞머리에 한 쌍(PERF_CNTL 뒤·표지 앞 = 클라이언트 TXFILTER 앞, r200 DRI 의 tam→tex 순서); `cpR6PreRegs` 끝(비트 11, `cpR6PreWant` 가 0x6 을 기대, 게이트 아님) → `CP_R6_PRE_COUNT` 12; REC3D +4(0x2d9c, TXFORMAT_X_0, TXSIZE_0, TXPITCH_0) → 72; zpre 12 개; 주석 (1 + 12)·32-word.  `verify_oracle.RESERVED` +0x2d9c(허용 목록 42 불변, 생성 블록 재생성·`gen_r7verify --check` PASS·`sim_verify` PASS); `check_r5_src.R6_RING_OK` +1.
- 판정기·오라클: `prefix_words/expect` +(TAM_DEBUG3, 6), 14 쌍 28 워드; `check_r6a` zpre `{9,12}`·`REC_WANT['g49'] 72`·`ORDERS['g49']`·합성 REC3D +4·`advance(28)`; `design3` 32; `build/g49/plan_ops.txt`(`check_plan_ops` PASS, 4 checked)·`run_g49.sh`(2d9c 읽기 세 번).
- 자체시험 PASS: zclear_oracle, tri_oracle, verify_oracle, check_plan_ops, check_replay, design3, check_r5_src, hostcheck-r2b0.  인용: 편집 전 사본 대응표로 264 곳 재조준, 값이 바뀐 want 8 개 갱신(68→72, 1+11→1+12, 13→14 쌍, 26→28, 30→32, {9,11}→{9,12}), 전 문서 0 failed.
- 빌드 **OSRDNBUILD PASS stamp=9b4c110a runid=790570491 symbols=21**, `check_reloc_r2b0` PASS, check_r6a·sim_r6 자체시험 PASS, **check-all PASS(실패 0)**, 설치 `INSTALL DONE runid=790570491`(옛 번들 .prev).  재부팅 13 에서: 마운트 → 내 gcdsd → `run_g49.sh` → 원본 436 회(`run_replay.sh 436 4067 <원본> 16`; g49 러너 뒤엔 w0 가 16 이 아니므로 판정기의 링 위치는 `RDN-R5 ptrs … wafter=` 의 마지막 값으로 준다).
- **부팅 13(0251b539), `run_g49.sh`**: TAM_DEBUG3 — 전원 값 0 · START 뒤 0 · **첫 앞머리 뒤 6**(되읽힘; `zpre` 12 번째 값 00000006, `prebad=00`), 11 연산 rc 0, `check_r6a … --procedure g49` PASS.  재생 시작 wptr = **112**(커널 `RDN-R5 state … wptr=112` = 오라클 계산 16 + 32 + 64, 교차 확인).
- **부팅 13, TAM_DEBUG3 = 0x6 아래 원본 436 회**(runid 790573590, w0 112): **`rep 0` 뒤 `done` 없음 — 첫 제출에서 머신 정지**(14:43, ping 무응답).  지난 두 부팅(값 0)은 6·7 번째였다.  판정기: rep 0 클라이언트 링 144, 교차 워드 3950(마지막 PACKET3 안).
- **해석**: r200 DRI 의 LRU 우회 값은 RV280 에서 이 스트림의 정지를 막지 못하고 **즉시 일으킨다** — TAM(텍스처 주소 모듈) 디버그 비트 1·2 가 이 경로에 직접 작용한다는 뜻이며, 정지가 **텍스처 주소/캐시 유닛의 혼합 밉 경로**에 있다는 방증.  R200 의 옛 조건부 코드는 `(MIN & 0x04) == 0`, 즉 **밉 아닌** 필터의 유닛에 비트를 켰다(`r200_texstate_amber.c:1589-1614`) — 이 비트는 단일 레벨 접근용 캐시 모드로 보이고, RV280 에서는 밉 혼합과 양립하지 않는다.  G4-9 가설 사망.
- 조치: 다음 빌드에서 앞머리의 TAM_DEBUG3 값을 **0**(참조의 비-R200 초기값)으로 되돌린다 — 되읽기·REC3D·도구는 그대로(0 을 기대).  현재 설치본(9b4c110a, 값 6)은 혼합 스트림을 첫 제출에서 굳히므로 **재부팅 뒤 바로 교체**(라이브러리 기본은 혼합 거절이라 GLQuake 는 안 굳지만, 실험용으로 두지 않는다).

## 13. "왜" 를 참고자료에서 (2026-09-28, 부팅 13 정지 뒤, 사용자 질문)

- 다시 훑은 곳: xorg ChangeLog(lockup/hang × r200·texture·mip: 해당 없음, 버그 #1519/#729/#814 는 언급 없음), Linux KMS(RV280 분기는 마이크로코드 선택 `r100.c:1009-1013`·PLL 에라타 `:2434-2445`·PCI 애퍼처 `:2727-2732` 뿐), Linux `radeon_cp_linux.c:614-622`(CP RESYNC 행 우회는 R420 전용).  **RV280 의 텍스처/밉 에라타는 어느 참조에도 없다.**
- 남은 단서는 r200 DRI 의 필터 대응(`r200_tex_amber.c:233-250`): 하드웨어 MIN 값과 GL 모드의 짝은 6 = GL_NEAREST_MIPMAP_LINEAR(텍셀 최근접·레벨 사이 선형), 3 = GL_LINEAR_MIPMAP_NEAREST, 7 = GL_LINEAR_MIPMAP_LINEAR(삼선형).  굳는 값 6 은 **실제 앱이 거의 안 쓰는 조합**이다(GLQuake 원본 기본은 LMN=3, 흔한 삼선형은 7; LibreQuake 만 NML 을 기본으로 둔다).  참조 스택이 이 모드의 RV280 결함을 모른 채 지나쳤을 수 있다 — 가설이며, **값 7 쌍둥이**(`build/g48/trace-last-lml.bin`, 워드 33·1654·2502 만 6→7, 오라클 OK, `check_replay` 쌍둥이 규칙에 등록)로 가른다.
- 실험(재부팅 뒤, 되돌린 커널 설치 뒤): 값 7 쌍둥이 436 회.  **안 굳으면** 결함은 값 6 하나에 있고, 라이브러리가 GL_NEAREST_MIPMAP_LINEAR 를 값 7 로 보내면(텍셀 필터가 최근접 → 선형으로 **올라가는** 대체, 레벨 혼합은 그대로) 근사 A 보다 화질을 잃지 않고 GLQuake 전가속을 얻는다; GL_LINEAR_MIPMAP_LINEAR 는 그대로 개방.  **굳으면** 혼합 모드 전부의 결함이고 근사 A(레벨 선택)로 간다.

### 13-1. 참고자료 추가 조사 (2026-09-28, 사용자 지시 "남은 단서도 참고자료에서")

| 본 것 | 사실 | 뜻 |
|---|---|---|
| R100 드라이버 `radeon_tex_amber.c:175-190` | GL_NEAREST_MIPMAP_LINEAR → `MIN_FILTER_NEAREST` 강등은 **큐브맵 전용**("r100 chips can't handle mipmaps/aniso for cubemap/volume textures"); 2D 는 값 6 그대로(`:203-206`) | 값 6 을 피하는 참조는 없다 |
| Mesa-6.5.3 `r200_tex.c:224-225`, R100 헤더 `radeon_reg_r100.h:1211-1221` | 옛 DRI 도 같은 대응; R100 도 같은 값 표 | 값 6 은 R100 시절부터 늘 쓰인 모드 |
| Mesa 상태 추적기 `st_cb_texture.c:882-891` | "the initial MinFilter is GL_NEAREST_MIPMAP_LINEAR" — GL 의 **기본** 최소화 필터가 값 6 이고, 필터를 안 건드리는 앱은 전부 이 모드로 돈다 | 값 6 자체가 RV280 에서 굳는다면 참조 세계에서 진작 드러났을 것 → **"값 6 자체" 가설 약화** |
| amber `radeon_mipmap_tree_amber.c:257-264`(§9 에서 연 것) | DRI 의 밉 트리는 `MaxLevel`(기본 1000)과 크기로 잘려 **언제나 1×1 까지** 체인을 만든다; 잘리는 것은 앱이 `GL_TEXTURE_MAX_LEVEL` 을 줄 때뿐(드묾) | 참조 세계에서 "잘린 체인 + 레벨 혼합" 은 거의 실행된 적 없는 조합 |
| 우리 실측 | 사다리 S1–S13(**온전한 체인** + 혼합 두 모드·λ 초과)은 통과; GLQuake·재생(**8×8 에서 잘린 체인** + 혼합)만 굳음; 잘린 체인 + NMN(쌍둥이 2)은 멀쩡 | 갈리는 변수는 **"레벨 혼합이 MAX_MIP_LEVEL 너머를 건드리는가"** |

**가설(현재 최우선)**: 레벨 혼합 모드(값 6·7)에서 λ 가 `MAX_MIP_LEVEL` 을 넘으면 하드웨어가 MAX+1 레벨의 주소를 만들며, 체인이 크기가 뜻하는 레벨 수보다 짧을 때 그 주소가 잘못돼(정의되지 않은 레벨) 몇 번 누적되면 버스가 선다.  온전한 체인이면 λ 클램프가 정상이라 사다리가 통과했다.  8×8 캡은 우리 포트(`gl_vidsdl.c` `GL_FilterAudit`, Matrox M12 유래)가 넣은 것이라 참조와 다른 우리 쪽 결정이다.

**가르는 쌍둥이 3**: `build/g48/trace-last-full.bin` — TXFILTER 의 `MAX_MIP_LEVEL`[19:16] 을 그 텍스처 크기의 온전한 체인 값으로(128² → 7, 64² → 6), MIN 6 은 그대로.  올린 레벨(5–7)의 텍셀은 업로드된 적 없는 아레나 메모리에서 읽히지만(정지 시험엔 무관) 주소는 하드웨어의 정상 계산 범위다.  오라클 OK.
- 실기 순서(재부팅 뒤·되돌린 커널): ① 쌍둥이 3(온전한 MAX) 436 회 — **안 굳으면 원인 = 잘린 체인 + 혼합**(조치: 포트의 8×8 캡 제거 또는 라이브러리가 1×1 까지 채워 올리기 → 근사 없이 혼합 모드 개방); ② 그다음 같은 부팅에서 쌍둥이 2(값 7) 436 회 — 값 7 도 온전/잘림 구분에 쓰인다.  ①이 굳으면 ②를 다음 부팅에.
- 되돌린 커널(TAM_DEBUG3 = 0): **OSRDNBUILD PASS stamp=2d3234bf runid=790575684 symbols=21**, `check_reloc_r2b0` PASS, check-all PASS, `INSTALL DONE`.  다음 부팅(15)에서 §13-1 순서: `run_g49.sh`(TAM 0 되읽기 확인) → 쌍둥이 3(온전한 MAX) 436 회 → 쌍둥이 2(값 7) 436 회.
- **부팅 15(01bae910), 드라이버 2d3234bf**: `run_g49.sh` — TAM_DEBUG3 전원 0 · START 뒤 0 · 첫 앞머리 뒤 **0**(되돌림 확인, prebad=00), 11 연산 rc 0.  재생 시작 wptr 112.

## 14. 쌍둥이 3 결과와 부하 가설 (2026-09-28, 부팅 15)

- **쌍둥이 3(MAX 를 전체 체인 값으로, MIN 6) 436 회**(runid 790577733, w0 112): rep 0 `done`, **`rep 1` 뒤 `done` 없음 — 2 번째 제출에서 정지**(15:52).  잘린 체인의 클램프 가설(§13-1) **사망** — MAX 를 올리자 더 빨리 굳었다.
- 지금까지의 정지 회차를 페치 부하로 놓고 보면 한 줄로 늘어선다:

| 스트림 | 샘플당 텍스처 페치(대략) | 정지 회차 |
|---|---|---|
| 쌍둥이 2: NMN(레벨 선택, 최근접 텍셀) | 1 | 436 회 통과 |
| 원본: 값 6(레벨 혼합, 최근접 텍셀), 레벨 5 개 | 2 | 6~7 회 |
| 쌍둥이 3: 값 6, 레벨 8 개(작은 레벨까지 혼합, 캐시 미스 증가) | 2 + 미스 | 2 회 |
| 원본 + TAM_DEBUG3 = 6(캐시 모드 변경) | ? | 1 회 |
| GLQuake 혼합(텍스처가 매 제출 다름 = 캐시 스래시) | 2 + 미스 | 436 제출 뒤 |

  **가설(부하)**: 정지는 특정 값이 아니라 **텍스처 유닛의 메모리 트래픽/전력이 문턱을 넘을 때** 난다(PCI 슬롯 전원·카드 전원부 한계 같은 하드웨어 사정, 또는 텍스처 캐시/메모리 컨트롤러의 결함).  참조 세계에서 안 보인 이유도 설명된다(이 개체·이 슬롯의 문제일 수 있다).
- **가르는 쌍둥이 4**: 쌍둥이 2(NMN, 안 굳음)에 `MAG_FILTER_LINEAR`(TXFILTER 비트 0)만 켠 것 — 레벨 혼합 없이 텍셀 페치만 4 배(확대 구간)·이중선형 미니화… 정확히는 MAG 만 바뀌므로 확대되는 픽셀에서만 4 텍셀.  `build/g48/trace-last-nmn-maglin.bin`(워드 셋, 오라클 OK, 검사기 규칙).  **굳으면** 부하 가설 확정(혼합 모드 무죄; 조치는 페치 부하를 낮추는 쪽 — 혼합 모드는 소프트웨어 유지, 이중선형도 재검토); **안 굳으면** 혼합 경로 고유 → 값 7 쌍둥이로.
- 실기 순서(재부팅 16): `run_g49.sh` → 쌍둥이 4 436 회 → (안 굳으면) 쌍둥이 2 값 7 436 회.
- **부팅 16(239e0a53), 쌍둥이 4(NMN + MAG LINEAR) 436 회**(w0 112): 436 회 전부 done, judge PASS, 커널 로그 정상.  **안 굳었다** — 텍셀 페치를 늘려도(확대 구간 4 텍셀) 레벨 혼합이 없으면 무해.  단순 페치 부하 가설 약화; 정지는 **레벨 사이 혼합 경로**에 특정된다(값 6 에서 확인, 값 7 은 다음).
- **부팅 16, 쌍둥이 2(값 7 = GL LINEAR_MIPMAP_LINEAR) 436 회**(runid 790578986, w0 2992 = 112 + 436×4112 mod 4096; 러너엔 3088 을 잘못 줬고 판정은 2992 로 다시 냈다): rep 0 done, **`rep 1` 뒤 `done` 없음 — 2 번째 제출에서 정지**(16:12).  값 6(6~7 회)보다 빠르다.

## 15. 결론 (2026-09-28, 여섯 부팅·재생 8 회)

| 스트림(같은 기하·같은 텍스처 메모리·같은 링) | 결과 |
|---|---|
| NMN(레벨 선택, 최근접 텍셀) 436 회 | 통과 |
| NMN + MAG LINEAR(페치 4 배, 혼합 없음) 436 회 | 통과 |
| 값 6(레벨 혼합, 최근접 텍셀), MAX 4 | 6~7 회에 정지(2 부팅) |
| 값 6, MAX 7(작은 레벨까지 혼합) | 2 회에 정지 |
| 값 7(레벨 혼합, 선형 텍셀) | 2 회에 정지 |
| 값 6 + TAM_DEBUG3 = 6 | 1 회에 정지 |

- **확정**: 이 카드(RV280, PCI)에서 **레벨 사이 혼합 경로(하드웨어 MIN 6·7)** 는 몇 제출 만에 머신을 굳히고, 혼합 경로의 페치가 많을수록 빨리 굳는다.  레벨 선택 모드는 페치를 늘려도 무해.  링·크기·위치·텍셀 내용·잘린 체인·TRI_PERF·GLQuake·창·소리 전부 무관(실측으로 배제).
- **참조에 없는 이유**: RV280 의 텍스처/밉 에라타는 xorg·Linux·DRI 어디에도 없고, r200 DRI 의 두 우회는 R200 전용이며 그중 LRU 우회는 RV280 에서 정반대로 작용했다.  이 개체(카드·슬롯·전원) 고유 결함일 가능성을 배제 못 한다.
- **"왜" 의 마지막 층(혼합 경로가 왜 굳는가)은 하드웨어 문서 없이는 닿을 수 없다** — 남은 수단은 값을 찍어 보는 탐침뿐이고, 여섯 부팅으로 그 방향은 충분히 밟았다.
- **조치**: 라이브러리가 혼합 두 모드를 레벨 선택 모드로 대체해 카드에 보낸다(GL_NEAREST_MIPMAP_LINEAR → NMN, GL_LINEAR_MIPMAP_LINEAR → LMN; Matrox M12 의 "문서화된 근사" 와 같은 결정, 단 여기서는 정지 회피가 이유).  체인이 8×8 에서 잘려 있어 레벨 전환의 시각 차는 작다.  커널·검증기 불변, 정지 위험 없음.  계획·codex 검토 뒤 코딩(G4-10).
