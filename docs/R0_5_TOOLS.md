# R0-5 — 실기 도구 목록과 자립화 시점

작성 2026-09-15.  워크스페이스 루트의 도구를 이 폴더로 **언제** 복사할지 정한다.

## 결정

**R1 착수(카드 설치 뒤, 첫 실기 사용) 때 복사한다.**  지금 복사하면 쓰이기 전에
루트 원본과 어긋날 수 있고(루트 도구는 다른 프로젝트가 계속 고친다), 공개는 한참
뒤다.  복사하는 커밋에서 원본 경로와 원본 커밋 해시를 이 문서에 적는다.

## 필요한 것 (2026-09-15 존재 확인)

| 원본 | 용도 | 단계 |
|---|---|---|
| `tools/site.sh`, `tools/gen-conf.sh` | `etc/site.conf` 에서 주소·계정 읽기 — **커밋 파일에 실 IP 금지** | 전부 |
| `tools/nx-mount.sh` | 실기에서 워크스페이스 NFS 마운트 | R1~ |
| `tools/nx-daemon.sh` | gcdsd 배포·기동(재부팅마다 필요, 마운트 **뒤에**) | R1~ |
| `tools/nxrun.sh` | telnet 자동 로그인 한 줄 실행(180 초 제한 — 긴 작업은 nohup) | R1~ |
| `tools/nx-logcatch.sh`, `tools/nxlogd.c` | 시스템 로그를 NFS 로 fsync 하며 밀어냄 — **위험 부팅의 전제** | R1~ |
| `tools/nx-install-driver.sh` | 드라이버 번들 빌드·설치·검증 | R2~ |
| `pcils/pcils.c`, `pcils/Makefile` | PCI 열거·config 덤프(읽기) | R1 |
| `openstep-matrox-remade/OSMGAProbe/` | bare loadable 조사 모듈의 뼈대(CALL/WIRE/START, 광고 없음) | R1 probe 의 출발점 |

## 이미 이 폴더에 있는 호스트 도구 (실기 불필요)

| 도구 | 하는 일 |
|---|---|
| `tools/fetch-ref.sh` | 참고 소스 재취득 |
| `tools/oracle/radeon_modeset.py` | CRTC·PLL 값 오라클(자체검사 + Matrox 표 대조) |
| `tools/oracle/regtable.py` | 세 헤더의 레지스터 오프셋·공간 대조 |
| `tools/oracle/sync_analysis.py` | `ANALYSIS.md` 표를 생성기와 동기화/검사 |
| `tools/oracle/check_citations.py` | 문서의 `파일:줄` 인용을 원문과 대조 |
| `tools/oracle/check_microcode.py` | CP 마이크로코드 두 사본 동일성 |
