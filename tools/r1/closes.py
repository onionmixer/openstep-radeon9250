#!/usr/bin/env python3
"""Which open design items the R1 log closes, and which it cannot.

  closes.py --self-test
  closes.py --markdown          the table for docs/R1_CLOSES.md

Each item names the R1 log fields that close it (register names from
parse_r1.REGS, or the other line kinds: pci, cfg, bridge, mmio, live, frame60)
or says NOT_R1 with the later step that must close it.  The check is mechanical:
  - every field an item cites must be something the R1 parser really produces;
  - every register listed as "needed later, not read by R1" must be a real
    register (defined in at least one of the three reference header trees)
    and really absent from REGS -- so the list cannot claim a gap that R1
    in fact covers, or cite a register that does not exist;
  - every item names the document section it comes from, and that section
    heading must exist in that document.
"""

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pr = load('parse_r1', os.path.join(HERE, 'parse_r1.py'))
rt = load('regtable', os.path.join(PROJ, 'tools', 'oracle', 'regtable.py'))

KINDS = set(pr.GRAMMAR)            # begin pci cfg bridge mmio live frame60 reg stop end

# (source document, section heading text, item, R1 fields or 'NOT_R1', decision / later owner)
ITEMS = [
    ('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', '5-1 분주 슬롯: 콘솔이 쓰는 `PLL_DIV_SEL`',
     ['CLOCK_CNTL_INDEX'], '기록만(설계는 DIV3 로 이미 닫힘).  bits 8-9 해독은 parse_r1'),
    ('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', '5-2 PLL 이득(PVG): BIOS 가 둔 `PPLL_CNTL` 보존 여부',
     'NOT_R1', 'PLL 인덱스 읽기라 R1 금지 — R2 스냅샷'),
    ('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', '5-3 `HOST_PATH_CNTL` 스냅샷 값',
     ['HOST_PATH_CNTL'], '값과 `HDP_APER_CNTL` 비트를 기록 → R2 가 보존'),
    ('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', '5-5 BIOS 가 CP 를 켜 두는가',
     ['CP_CSQ_CNTL', 'CP_RB_CNTL', 'RBBM_STATUS'], '모드 비트 28-31 이 0 이 아니면 R2 3 단계가 중단'),
    ('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', '5-6 부분 실패 시 복원 경계',
     'NOT_R1', 'R2 계획서(R0-3 상태 기계와 함께)'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-3 엔진 유휴·CP 꺼짐',
     ['RBBM_STATUS', 'CP_CSQ_CNTL'], 'R1 스냅샷에서 CP 꺼짐 확인'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-4 MC 맵: 스냅샷과 목표값이 다른가',
     ['MC_FB_LOCATION', 'MC_AGP_LOCATION', 'CONFIG_APER_0_BASE', 'CONFIG_MEMSIZE', 'CONFIG_APER_SIZE', 'cfg'],
     'parse_r1 판정 "RV280-aligned aperture base" 가 같음/다름을 낸다'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-5/4-6 CRTC1 생성·확장 레지스터의 현재 값',
     ['CRTC_GEN_CNTL', 'CRTC_EXT_CNTL'], '`CRT_ON` 보존의 기준값'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-7 콘솔 타이밍',
     ['CRTC_H_TOTAL_DISP', 'CRTC_H_SYNC_STRT_WID', 'CRTC_V_TOTAL_DISP', 'CRTC_V_SYNC_STRT_WID'],
     '역해독(radeon_decode) 으로 콘솔 해상도 추정'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-8 목표 분주가 현재와 다른가',
     'NOT_R1', '`PPLL_DIV_3`·`PPLL_REF_DIV` 는 PLL 공간 — R2 스냅샷'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-9 스캔아웃 주소·피치',
     ['CRTC_OFFSET', 'CRTC_PITCH', 'DISPLAY_BASE_ADDR'], '`CRTC_OFFSET_CNTL`·`DISP_MERGE_CNTL` 은 R1 에 없음(아래 표)'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-10 `SURFACE_CNTL` 이 0 인가',
     ['SURFACE_CNTL'], '0 이 아니면 R2 가 쓰기 대상에 넣는다'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-11/11b DAC·FIFO·센터링',
     ['DAC_CNTL', 'DAC_CNTL2', 'DAC_MACRO_CNTL', 'GRPH_BUFFER_CNTL', 'CRTC_MORE_CNTL'],
     'xf86 만의 조치를 할지 R2 계획서가 이 값으로 정한다(Q5 4b)'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-12 팔레트 접근 비트',
     ['DAC_CNTL2'], '`DAC2_PALETTE_ACC_CTL` 은 `DAC_CNTL2` 의 bit 5(`radeonfbreg.h:610`)'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-12b 방해 가능 클라이언트',
     ['GEN_INT_CNTL'], '나머지 7 개는 R1 에 없음(아래 표) — R2 스냅샷'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '비활성 출력 확인(CRTC2·FP·TV)',
     ['CRTC2_GEN_CNTL', 'FP_GEN_CNTL', 'DISP_OUTPUT_CNTL'], '켜져 있으면 진입 중단(Q5 4c).  `TV_DAC_CNTL` 은 R1 에 없음'),
    ('docs/R0_2_MODESET_DECODE.md', '## 4. 첫 점등 시퀀스 초안', '4-14 FB 매핑 길이 ≤ 보고 VRAM·애퍼처',
     ['CONFIG_MEMSIZE', 'CONFIG_APER_SIZE', 'cfg', 'bridge'], 'BAR0 크기는 R1 이 재지 않는다(sizing 은 쓰기)'),
    ('docs/R0_3_VGA_RETURN_DECODE.md', '## 5. 열린 질문', '5-3 콘솔이 그래픽인가 텍스트인가',
     'NOT_R1', '`ATTR[0x10]` 읽기는 인덱스 쓰기 — R2 스냅샷'),
    ('docs/R0_3_VGA_RETURN_DECODE.md', '## 5. 열린 질문', '5-4 표준 VGA I/O 포트가 이 카드로 가는가',
     ['cfg'], '명령 레지스터 I/O 디코드 비트만 기록.  포트 접근 자체는 R2'),
    ('docs/R5_GART.md', '## 3. R5 계획서가 정할 것', 'GART 창이 FB 와 겹치는가(4 MiB 정렬)',
     ['MC_FB_LOCATION'], '`gart_oracle.py <MC_FB_LOCATION>` 에 R1 값을 넣으면 판정'),
    ('docs/R5_CP_SEQUENCE.md', '## 2. PLAN R5 에 없던 사실', '#3 `MC_AGP_LOCATION` 원래 값',
     ['MC_AGP_LOCATION'], 'R5 스냅샷 복원 목록의 기준값'),
    ('docs/R5_CP_SEQUENCE.md', '## 2. PLAN R5 에 없던 사실', '#3 `AGP_COMMAND` 원래 값',
     'NOT_R1', 'R1 목록에 없음 — R5 스냅샷'),
    ('docs/R5_CP_SEQUENCE.md', '## 2. PLAN R5 에 없던 사실', '#5 `BUS_CNTL.BUS_MASTER_DIS` 원래 값',
     ['BUS_CNTL', 'cfg'], 'parse_r1 판정이 bit 6 과 PCI 명령 버스마스터 비트를 낸다'),
]

# registers a later step needs that R1 does not read, with the step and why
NOT_IN_R1 = [
    ('PPLL_CNTL', 'R2', 'PLL 공간 — 인덱스 쓰기'),
    ('PPLL_REF_DIV', 'R2', 'PLL 공간 — 인덱스 쓰기'),
    ('PPLL_DIV_3', 'R2', 'PLL 공간 — 인덱스 쓰기'),
    ('VCLK_ECP_CNTL', 'R2', 'PLL 공간 — 인덱스 쓰기'),
    ('MCLK_CNTL', 'R5', 'PLL 공간, 엔진 리셋이 저장·복원'),
    ('CRTC_OFFSET_CNTL', 'R2', '4-9'),
    ('DISP_MERGE_CNTL', 'R2', '4-9 `RGB_OFFSET_EN`'),
    ('OVR_CLR', 'R2', '4-12b'),
    ('OVR_WID_LEFT_RIGHT', 'R2', '4-12b'),
    ('OV0_SCALE_CNTL', 'R2', '4-12b'),
    ('SUBPIC_CNTL', 'R2', '4-12b'),
    ('VIPH_CONTROL', 'R2', '4-12b'),
    ('I2C_CNTL_1', 'R2', '4-12b'),
    ('CAP0_TRIG_CNTL', 'R2', '4-12b'),
    ('TV_DAC_CNTL', 'R2', '비활성 출력 확인'),
    ('AGP_COMMAND', 'R5', 'GART 켤 때 0 으로 씀(R5 사실 #3)'),
    ('SURFACE0_INFO', 'R5', 'GART 표 서피스 경계(R5 사실 #4)'),
    ('RBBM_SOFT_RESET', 'R5', '엔진 리셋이 저장·복원'),
]


def check():
    problems = []
    headers = dict((k, rt.load(p)) for k, p in rt.HEADERS)
    for doc, section, item, fields, note in ITEMS:
        path = os.path.join(PROJ, doc)
        text = open(path).read() if os.path.exists(path) else ''
        if not text:
            problems.append('%s does not exist' % doc)
        elif not any(line.startswith(section) for line in text.split('\n')):
            problems.append('%s has no heading starting %r' % (doc, section))
        if fields == 'NOT_R1':
            continue
        for f in fields:
            if f not in pr.REGS and f not in KINDS:
                problems.append('%r cites %s, which the R1 parser does not produce' % (item, f))
    for name, step, why in NOT_IN_R1:
        if name in pr.REGS:
            problems.append('%s is listed as not read by R1, but REGS has it' % name)
        if not any(name in t for t in headers.values()):
            problems.append('%s is not defined in any reference header' % name)
    return problems


def markdown():
    problems = check()
    if problems:
        raise SystemExit('\n'.join(problems))
    out = ['### 생성표 A — 열린 항목 → R1 필드', '',
           '| 출처 | 항목 | R1 이 주는 것 | 판정·다음 |', '|---|---|---|---|']
    for doc, section, item, fields, note in ITEMS:
        f = '**R1 로 못 닫음**' if fields == 'NOT_R1' else ', '.join('`%s`' % x for x in fields)
        out.append('| `%s` %s | %s | %s | %s |' % (os.path.basename(doc), section.lstrip('# '), item, f, note))
    out += ['', '### 생성표 B — 뒤 단계가 필요로 하는데 R1 이 읽지 않는 레지스터', '',
            '| 레지스터 | 오프셋(헤더) | 공간 | 필요한 단계 | 이유 |', '|---|---|---|---|---|']
    headers = dict((k, rt.load(p)) for k, p in rt.HEADERS)
    for name, step, why in NOT_IN_R1:
        defs = [d for t in headers.values() for d in t.get(name, [])]
        off = sorted(set(d[0] for d in defs))
        pll = any(d[2] for d in defs)
        out.append('| `%s` | %s | %s | %s | %s |' % (name, ', '.join('`0x%04x`' % o for o in off),
                                                    'PLL' if pll else 'MMIO', step, why))
    return '\n'.join(out)


def self_test():
    bad = 0
    problems = check()
    print('%-4s real tables: %s' % ('ok' if not problems else 'FAIL', '; '.join(problems) or 'consistent'))
    bad += 1 if problems else 0
    global ITEMS, NOT_IN_R1
    saved = (list(ITEMS), list(NOT_IN_R1))
    for label, items, notin, want in (
        ('an item citing a field R1 does not produce', ITEMS + [('docs/R0_2_MODESET_DECODE.md', '## 5. 열린 질문', 'x', ['PPLL_CNTL'], '')],
         NOT_IN_R1, 'does not produce'),
        ('a gap that R1 in fact covers', ITEMS, NOT_IN_R1 + [('CRTC_OFFSET', 'R2', '')], 'REGS has it'),
        ('a register that does not exist', ITEMS, NOT_IN_R1 + [('NO_SUCH_REGISTER', 'R2', '')], 'not defined'),
        ('a section heading that does not exist', ITEMS + [('docs/R0_2_MODESET_DECODE.md', '## 9. 없음', 'x', 'NOT_R1', '')],
         NOT_IN_R1, 'no heading'),
    ):
        ITEMS, NOT_IN_R1 = items, notin
        try:
            got = check()
        finally:
            ITEMS, NOT_IN_R1 = saved
        ok = any(want in p for p in got)
        print('%-4s control: %s' % ('ok' if ok else 'FAIL', label))
        bad += 0 if ok else 1
    print('closes self-test:', 'PASS' if bad == 0 else 'FAIL (%d)' % bad)
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ['--self-test']:
        return self_test()
    if argv[1:] == ['--markdown']:
        print(markdown())
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
