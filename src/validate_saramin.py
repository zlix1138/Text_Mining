# -*- coding: utf-8 -*-
"""
사람인 수집물 검증 스크립트(사람인 파일만 대상).
- data/saramin_jobs_raw.csv 를 읽어 기획서 검증 항목을 점검하고 결과를 터미널 출력.
- 잡코리아 산출물(data/jobs.csv 등)이나 잡코리아 검증 스크립트는 절대 실행/수정하지 않는다.
실행: python src/validate_saramin.py
"""

import csv
import os
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C
import constants_saramin as CS

RAW_TEXT_MIN_LEN = 30   # raw_text가 이보다 짧으면 '너무 짧음'으로 집계


def load_rows(path):
    if not path.exists():
        return []
    with open(path, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "0%"


def validate():
    rows = load_rows(CS.SARAMIN_RAW_CSV)
    print("=" * 64)
    print("사람인(Saramin) 수집물 검증 리포트")
    print("=" * 64)
    print(f"파일: {CS.SARAMIN_RAW_CSV}")
    print(f"[전체] 총 수집 행 수: {len(rows)}")
    if not rows:
        print("⚠️  데이터가 없습니다. 먼저 수집을 실행하세요(python src/main_saramin.py --regions 서울 --limit 5).")
        return

    # 필수 컬럼 점검(공통 스키마 호환)
    cols = list(rows[0].keys())
    missing = [c for c in CS.RAW_COLUMNS if c not in cols]
    print(f"[스키마] 누락 컬럼: {missing if missing else '없음 ✓'}")

    # 지역별 수집 개수
    print("\n[지역별 수집 개수]")
    by_region = Counter(r.get("region", "") for r in rows)
    for rg, n in sorted(by_region.items(), key=lambda x: -x[1]):
        print(f"   {(rg or '(공란)').ljust(8)} {n}")

    # 직무군별 수집 개수
    print("\n[직무군별 수집 개수]")
    by_jg = Counter(r.get("job_group", "") for r in rows)
    for jg in C.JOB_GROUP_NAMES + ["미분류"]:
        print(f"   {jg.ljust(12)} {by_jg.get(jg, 0)}")

    # 지역 × 직무군
    print("\n[지역 × 직무군 수집 개수]")
    grid = Counter((r.get("region", ""), r.get("job_group", "")) for r in rows)
    header = "   " + "지역".ljust(8) + "".join(g[:7].ljust(9) for g in C.JOB_GROUP_NAMES) + "미분류".ljust(8) + "합계"
    print(header)
    for rg in sorted(by_region):
        cells, rtot = [], 0
        for g in C.JOB_GROUP_NAMES + ["미분류"]:
            n = grid.get((rg, g), 0); rtot += n
            cells.append(str(n).ljust(9 if g in C.JOB_GROUP_NAMES else 8))
        print("   " + (rg or "(공란)").ljust(8) + "".join(cells) + str(rtot))

    # search_total_count 입력 여부
    have_total = sum(1 for r in rows if str(r.get("search_total_count", "")).strip())
    print(f"\n[search_total_count] 입력된 행: {have_total}/{len(rows)} ({_pct(have_total, len(rows))}) "
          f"{'✓' if have_total else '⚠️ 미입력'}")

    # region 결측
    no_region = sum(1 for r in rows if not r.get("region"))
    print(f"[region 결측] {no_region}건 {'✓' if no_region == 0 else '⚠️'}")

    # job_group 미분류
    unclassified = sum(1 for r in rows if r.get("job_group") == "미분류")
    print(f"[job_group 미분류] {unclassified}건 ({_pct(unclassified, len(rows))})")

    # salary 결측
    no_salary = sum(1 for r in rows if not r.get("salary"))
    print(f"[salary 결측] {no_salary}건 ({_pct(no_salary, len(rows))})")

    # raw_text 너무 짧음
    short_raw = sum(1 for r in rows if len((r.get("raw_text") or "")) < RAW_TEXT_MIN_LEN)
    print(f"[raw_text {RAW_TEXT_MIN_LEN}자 미만] {short_raw}건 ({_pct(short_raw, len(rows))})")

    # 중복 URL
    urls = [r.get("url", "") for r in rows if r.get("url")]
    dup_url = len(urls) - len(set(urls))
    print(f"[중복 URL] {dup_url}건 {'✓' if dup_url == 0 else '⚠️'}")

    # 참고: 상세/크롤 상태 분포
    print("\n[참고] crawl_status:", dict(Counter(r.get("crawl_status", "") for r in rows)))
    print("[참고] detail_status:", dict(Counter(r.get("detail_status", "") for r in rows)))

    # 요약 파일 존재 확인
    summ = load_rows(CS.SARAMIN_SUMMARY_CSV)
    print(f"\n[요약파일] {CS.SARAMIN_SUMMARY_CSV.name} 행: {len(summ)}")
    print("=" * 64)


if __name__ == "__main__":
    validate()
