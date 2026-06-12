# -*- coding: utf-8 -*-
"""
데이터셋 검증 스크립트.
- jobs.csv를 읽어 기획서 검증 항목을 점검하고 결과를 터미널 + data/validation_report.txt로 저장.
검증 항목: 필수컬럼/URL중복/region·job_group 도메인/collected_date 결측/raw_text·salary 결측률/
          지역·직무별 수집수/지역 검색 전체건수 저장 여부/최종 행수 5000 이상.
실행: python src/validate_dataset.py
"""

import csv
import os
import sys
from collections import Counter

# Windows 콘솔(cp949)에서 한글·기호(✓) 출력이 깨지거나 크래시하지 않도록 UTF-8로 설정
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C


def load_rows(path):
    """CSV → list[dict]."""
    if not path.exists():
        return []
    with open(path, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def validate():
    lines = []

    def out(s=""):
        """터미널 출력 + 리포트 버퍼 적재."""
        print(s)
        lines.append(s)

    rows = load_rows(C.JOBS_CSV)
    out("=" * 60)
    out("청년 일자리 데이터셋 검증 리포트")
    out("=" * 60)
    out(f"파일: {C.JOBS_CSV}")
    out(f"총 행 수: {len(rows)}")
    if not rows:
        out("⚠️  데이터가 없습니다. 먼저 수집을 실행하세요(python src/main.py).")
        _save(lines)
        return

    cols = list(rows[0].keys())

    # 1) 필수 컬럼
    missing = [c for c in C.JOBS_COLUMNS if c not in cols]
    out(f"\n[1] 필수 컬럼 누락: {missing if missing else '없음 ✓'}")

    # 2) URL 중복
    urls = [r["url"] for r in rows if r.get("url")]
    dup_url = len(urls) - len(set(urls))
    out(f"[2] URL 중복: {dup_url}건 {'✓' if dup_url == 0 else '⚠️'}")
    dup2 = sum(1 for r in rows if "2차중복가능" in r.get("note", ""))
    out(f"    2차 중복 가능(회사+제목+지역) 표시: {dup2}건")

    # 3) region 도메인
    allowed_regions = set(C.BASE_REGIONS) | set(C.EXTRA_REGIONS) | {""}
    bad_region = [r["region"] for r in rows if r.get("region") not in allowed_regions]
    out(f"[3] region 도메인 위반: {len(bad_region)}건 {'✓' if not bad_region else '⚠️ ' + str(set(bad_region))}")

    # 4) job_group 도메인
    allowed_jg = set(C.JOB_GROUP_NAMES) | {"미분류", ""}
    bad_jg = [r["job_group"] for r in rows if r.get("job_group") not in allowed_jg]
    out(f"[4] job_group 도메인 위반: {len(bad_jg)}건 {'✓' if not bad_jg else '⚠️'}")
    unclassified = sum(1 for r in rows if r.get("job_group") == "미분류")
    out(f"    미분류 비율: {unclassified}/{len(rows)} ({_pct(unclassified, len(rows))})")

    # 5) collected_date 결측
    no_date = sum(1 for r in rows if not r.get("collected_date"))
    out(f"[5] collected_date 결측: {no_date}건 {'✓' if no_date == 0 else '⚠️'}")

    # 6) raw_text / salary 결측률
    empty_raw = sum(1 for r in rows if not r.get("raw_text"))
    empty_sal = sum(1 for r in rows if not r.get("salary"))
    out(f"[6] raw_text 결측: {empty_raw}/{len(rows)} ({_pct(empty_raw, len(rows))})")
    out(f"    salary 결측:  {empty_sal}/{len(rows)} ({_pct(empty_sal, len(rows))})")

    # 7) 지역·직무별 수집 개수
    out("\n[7] 지역 × 직무군 수집 개수:")
    grid = Counter((r.get("region", ""), r.get("job_group", "")) for r in rows)
    regions = sorted({r.get("region", "") for r in rows})
    out("    " + "지역".ljust(8) + "".join(g[:8].ljust(10) for g in C.JOB_GROUP_NAMES) + "미분류".ljust(8) + "합계")
    for rg in regions:
        cells = []
        rtotal = 0
        for g in C.JOB_GROUP_NAMES + ["미분류"]:
            n = grid.get((rg, g), 0); rtotal += n
            cells.append(str(n).ljust(10 if g in C.JOB_GROUP_NAMES else 8))
        out("    " + (rg or "(공란)").ljust(8) + "".join(cells) + str(rtotal))

    # 7-1) 30건 미만 셀(부족) 기록 — 기획서 8.3·항목4: 억지로 채우지 않고 기록
    short = [(rg, g, grid.get((rg, g), 0)) for rg in regions if rg
             for g in C.JOB_GROUP_NAMES if grid.get((rg, g), 0) < 30]
    out(f"\n[7-1] 지역×직무군 30건 미만(부족) 셀: {len(short)}개 (강제로 채우지 않고 기록)")
    for rg, g, n in short:
        out(f"      - {rg} × {g}: {n}건")

    # 8) crawl_status 분포
    out("\n[8] crawl_status 분포: " + str(dict(Counter(r.get("crawl_status", "") for r in rows))))

    # 9) 지역 검색 전체건수 저장 여부(search_counts.csv)
    sc = load_rows(C.SEARCH_COUNTS_CSV)
    have_counts = sum(1 for r in sc if r.get("search_total_count"))
    out(f"\n[9] search_counts.csv 행: {len(sc)} (전체건수 기록 {have_counts}건) "
        f"{'✓' if have_counts else '⚠️ 미기록'}")

    # 10) 최종 5000건 이상
    success = sum(1 for r in rows if r.get("crawl_status") == "success")
    out(f"\n[10] success 행 수: {success} → 목표 5,000건 "
        f"{'달성 ✓' if success >= C.TARGET_TOTAL else '미달 ⚠️'}")

    out("=" * 60)
    _save(lines)


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "0%"


def _save(lines):
    """리포트를 파일로 저장."""
    with open(C.VALIDATION_REPORT, "w", encoding=C.CSV_ENCODING) as f:
        f.write("\n".join(lines))
    print(f"\n리포트 저장: {C.VALIDATION_REPORT}")


if __name__ == "__main__":
    validate()
