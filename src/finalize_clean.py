# -*- coding: utf-8 -*-
"""
[전달용 정리] quality_jobs.csv → quality_jobs_clean.csv (분석·스코어링 팀 전달본).

목적: 분석에 필요 없는 컬럼 제거 + 임금 단위 정합(월급→연봉 환산).
- 기존 파이프라인/원본(quality_jobs.csv)은 수정하지 않고 새 파일만 생성.

■ 임금 정합 — salary_annual_min/max (만원, 연봉 환산) 신설
  · 연봉: 그대로
  · 월급: ×12
  · 시급/회사내규/면접후결정/비공개/빈값: 결측(정확한 수치 없음 → 동일 결측 처리)
  · 이상치(연봉환산 1,000~20,000만원 밖): 오추출로 보고 결측 처리
  · salary_disclosed 재계산 = 연봉환산 수치 존재 여부
  · salary(원문)·salary_min/max 는 제거, salary_type 과 연봉 환산값만 유지

■ 컬럼 정리
  · 제거(상수·파이프라인 잔재): crawl_status, detail_status, tier2_backfilled,
    include_in_analysis, is_duplicate, duplicate_of, dup_scope, exclude_reason, other_job_hint
  · 제거(분석무관·오용위험): deadline, search_total_count(행값 신뢰불가→양은 quantity파일),
    source_priority(source와 중복), collected_date, note, job_keyword, salary_min, salary_max
  · 유지: 텍스트 섹션(task/qualification/preference/benefits) 포함

입력:  data/quality_jobs.csv
출력:  data/quality_jobs_clean.csv
실행:  python src/finalize_clean.py
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

IN_CSV = C.DATA_DIR / "quality_jobs.csv"
OUT_CSV = C.DATA_DIR / "quality_jobs_clean.csv"

ANNUAL_MIN, ANNUAL_MAX = 1000, 20000   # 연봉환산 합리적 범위(만원); 밖이면 결측

# 전달본 컬럼 순서(논리 그룹)
OUT_COLUMNS = [
    # 식별
    "job_id", "source", "url",
    # 기본
    "company_name", "title", "region", "region_detail", "job_group",
    "job_category_raw", "career", "education", "employment_type",
    # 임금
    "salary_type", "salary_annual_min", "salary_annual_max", "salary_disclosed",
    # 텍스트
    "work_time", "raw_text", "task_description", "qualification", "preference", "benefits",
    # 질 피처
    "q_wage", "q_work_time", "q_welfare", "q_growth", "q_youth_friendly",
    "is_youth_friendly", "employment_stability",
    # 플래그
    "is_public_sector",
]


def _num(x):
    x = (x or "").strip()
    return int(x) if x.isdigit() else None


def annual(r):
    """연봉 환산 (만원). 연봉/월급만 산출, 그 외 결측. 이상치 결측."""
    t = r.get("salary_type", "")
    mn, mx = _num(r.get("salary_min")), _num(r.get("salary_max"))
    if t == "연봉":
        a_mn, a_mx = mn, mx
    elif t == "월급":
        a_mn = mn * 12 if mn else None
        a_mx = mx * 12 if mx else None
    else:                      # 시급/회사내규/면접후결정/비공개/빈값
        a_mn = a_mx = None

    def clip(v):
        return v if (v is not None and ANNUAL_MIN <= v <= ANNUAL_MAX) else None
    return clip(a_mn), clip(a_mx)


def main():
    if not IN_CSV.exists():
        print(f"⚠️  입력 없음: {IN_CSV}")
        return
    with open(IN_CSV, encoding=C.CSV_ENCODING) as f:
        rows = list(csv.DictReader(f))

    src_type = Counter()       # 환산 결과 진단
    clipped = 0
    disclosed_new = 0
    for r in rows:
        before = (_num(r.get("salary_min")), _num(r.get("salary_max")))
        a_mn, a_mx = annual(r)
        # 이상치로 결측 처리된 건수(원래 숫자 있었는데 환산 후 사라진 경우)
        if r.get("salary_type") in ("연봉", "월급") and before[0] and a_mn is None:
            clipped += 1
        r["salary_annual_min"] = a_mn if a_mn is not None else ""
        r["salary_annual_max"] = a_mx if a_mx is not None else ""
        r["salary_disclosed"] = 1 if (a_mn is not None or a_mx is not None) else 0
        if r["salary_disclosed"]:
            disclosed_new += 1
        src_type[r.get("salary_type", "") or "(빈값)"] += 1

    with open(OUT_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(OUT_COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in OUT_COLUMNS])

    # ── 리포트 ──
    n = len(rows)
    removed = [c for c in rows[0].keys() if c not in OUT_COLUMNS]
    print("=" * 64)
    print("[전달용 정리] quality_jobs_clean.csv 생성")
    print("=" * 64)
    print(f"행수: {n} | 컬럼: {len(rows[0].keys())} → {len(OUT_COLUMNS)}")
    print(f"제거 컬럼({len(removed)}): {removed}")
    print(f"신설: salary_annual_min/max (연봉 환산, 만원)")
    print(f"\n[임금 환산]")
    print(f"  연봉환산 수치 보유(=salary_disclosed): {disclosed_new}/{n} ({100*disclosed_new/n:.1f}%)")
    print(f"  이상치로 결측 처리: {clipped}건 (범위 {ANNUAL_MIN}~{ANNUAL_MAX}만원 밖)")
    av = [int(r["salary_annual_min"]) for r in rows if str(r["salary_annual_min"]).isdigit()]
    if av:
        av.sort()
        print(f"  연봉환산 min분포(만원): 최소 {av[0]:,} | 중앙값 {av[len(av)//2]:,} | 최대 {av[-1]:,}")
    print(f"\n산출물: {OUT_CSV}")
    print("=" * 64)


if __name__ == "__main__":
    main()
