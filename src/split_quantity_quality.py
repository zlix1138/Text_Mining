# -*- coding: utf-8 -*-
"""
[통합 4단계] 일자리 '양(quantity)' 분석과 '질(quality)' 분석 분리.

■ 양(quantity) — 모집단 규모 (개별 공고가 아니라 검색 전체 건수 기반)
  - 사람인(기준): saramin_collection_summary.csv 의 region×job_group×keyword search_total_count.
    · 직무군 대표값 = 소속 키워드 중 max(키워드 검색 모집단이 겹치므로 합산은 과대 → 하한 추정).
    · 키워드별 건수도 병기(sr_keyword_detail).
  - 잡코리아(참고): search_counts.csv 의 지역 총량(직무 무관)을 jk_region_total 로 병기(읽기 전용).
  출력: data/quantity_region_jobgroup.csv

■ 질(quality) — 상세 텍스트 표본(중복 제거된 최종 분석셋)에 질 피처 부여
  - 차원별 키워드 카운트(constants.SCORE_KEYWORDS): 임금/근로시간/복지/성장/청년친화
  - 고용안정성(employment_stability) = 정규직 여부, salary_disclosed = 급여 수치 공개 여부
  - 정규화·가중합 점수화는 이후(EDA/스코어링) 단계에서 수행.
  출력: data/quality_jobs.csv

입력:  data/integrated_dedup.csv, data/saramin_collection_summary.csv, data/search_counts.csv(읽기)
실행:  python src/split_quantity_quality.py
"""

import csv
import os
import sys
from collections import defaultdict, Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C

DEDUP_CSV = C.DATA_DIR / "integrated_dedup.csv"
SR_SUMMARY_CSV = C.DATA_DIR / "saramin_collection_summary.csv"
JK_COUNTS_CSV = C.DATA_DIR / "search_counts.csv"

QUANTITY_CSV = C.DATA_DIR / "quantity_region_jobgroup.csv"
QUALITY_CSV = C.DATA_DIR / "quality_jobs.csv"

QUANTITY_COLUMNS = ["region", "job_group", "sr_search_total_max", "sr_keyword_detail",
                    "sr_collected_sample", "analysis_sample_count", "jk_region_total"]


def _load(path):
    with open(path, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def _int(x):
    try:
        return int(str(x).replace(",", "").strip())
    except Exception:
        return 0


# ── 양(quantity) ─────────────────────────────────────────────────────────────
def build_quantity():
    sr = _load(SR_SUMMARY_CSV)
    dedup = _load(DEDUP_CSV)
    jk_counts = _load(JK_COUNTS_CSV)

    # 잡코리아 지역 총량(전체 행)
    jk_region_total = {r["region"]: _int(r["search_total_count"])
                       for r in jk_counts if r.get("job_group") == "전체"}

    # 사람인 region×job_group → 키워드별 search_total_count, collected
    by_combo = defaultdict(dict)        # (region,jg) -> {keyword: total}
    collected = Counter()               # (region,jg) -> collected sample
    for r in sr:
        key = (r["region"], r["job_group"])
        by_combo[key][r["job_keyword"]] = _int(r["search_total_count"])
        collected[key] += _int(r["collected_count"])

    # 최종 분석셋 표본 수(양쪽 출처 합) region×job_group
    sample_cnt = Counter((r["region"], r["job_group"]) for r in dedup)

    rows = []
    for region in C.BASE_REGIONS:
        for jg in C.JOB_GROUP_NAMES:
            key = (region, jg)
            kw = by_combo.get(key, {})
            smax = max(kw.values()) if kw else ""
            detail = "; ".join(f"{k}:{v}" for k, v in kw.items())
            rows.append({
                "region": region, "job_group": jg,
                "sr_search_total_max": smax,
                "sr_keyword_detail": detail,
                "sr_collected_sample": collected.get(key, 0),
                "analysis_sample_count": sample_cnt.get(key, 0),
                "jk_region_total": jk_region_total.get(region, ""),
            })

    with open(QUANTITY_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(QUANTITY_COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in QUANTITY_COLUMNS])
    return rows, jk_region_total


# ── 질(quality) ──────────────────────────────────────────────────────────────
def _kw_count(text, keywords):
    """raw_text 내 차원 키워드 매칭 수(공백 제거·소문자 비교)."""
    low = (text or "").lower().replace(" ", "")
    return sum(1 for kw in keywords if kw.lower().replace(" ", "") in low)


def build_quality():
    rows = _load(DEDUP_CSV)
    in_cols = list(rows[0].keys()) if rows else []
    feat_cols = ["q_wage", "q_work_time", "q_welfare", "q_growth", "q_youth_friendly",
                 "employment_stability", "salary_disclosed"]
    out_cols = in_cols + [c for c in feat_cols if c not in in_cols]

    dim_map = {  # constants.SCORE_KEYWORDS 키 → 출력 컬럼
        "wage": "q_wage", "work_time": "q_work_time", "welfare": "q_welfare",
        "growth": "q_growth", "youth_friendly": "q_youth_friendly",
    }
    for r in rows:
        txt = r.get("raw_text", "")
        for dim, col in dim_map.items():
            r[col] = _kw_count(txt, C.SCORE_KEYWORDS[dim])
        r["employment_stability"] = 1 if r.get("employment_type") == "정규직" else 0
        r["salary_disclosed"] = 1 if (r.get("salary_min") or r.get("salary_max")) else 0

    with open(QUALITY_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(out_cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in out_cols])
    return rows, feat_cols


def main():
    for p in (DEDUP_CSV, SR_SUMMARY_CSV, JK_COUNTS_CSV):
        if not p.exists():
            print(f"⚠️  입력 없음: {p}")
            return

    qrows, jk_tot = build_quantity()
    quality_rows, feat_cols = build_quality()

    # ── 리포트 ──
    print("=" * 64)
    print("[통합 4단계] 양/질 분석 분리 결과")
    print("=" * 64)
    print(f"\n■ 양(quantity): {QUANTITY_CSV.name}  (region×job_group {len(qrows)}행)")
    print("  [사람인 직무군 양 = 키워드 max(하한) | 잡코리아 지역총량 참고]")
    # 직무군별 전국 합(사람인 max 합), 지역별 잡코리아 총량
    jg_sum = Counter()
    for r in qrows:
        jg_sum[r["job_group"]] += _int(r["sr_search_total_max"])
    print("  사람인 직무군별 전국 합(max 기준):")
    for jg in C.JOB_GROUP_NAMES:
        print(f"     {jg.ljust(12)} {jg_sum[jg]:,}")
    print("  서울 예시(region×job_group):")
    for r in qrows:
        if r["region"] == "서울":
            print(f"     {r['job_group'].ljust(12)} max={_int(r['sr_search_total_max']):>6,} "
                  f"| {r['sr_keyword_detail']}")
    print(f"  잡코리아 지역총량(참고): " + ", ".join(f"{k} {v:,}" for k, v in jk_tot.items()))

    print(f"\n■ 질(quality): {QUALITY_CSV.name}  ({len(quality_rows)}행, 피처 {feat_cols})")
    n = len(quality_rows)
    print(f"  고용안정(정규직) 비율: {sum(int(r['employment_stability']) for r in quality_rows)}/{n} "
          f"({100*sum(int(r['employment_stability']) for r in quality_rows)/n:.1f}%)")
    print(f"  급여 수치 공개 비율: {sum(int(r['salary_disclosed']) for r in quality_rows)}/{n} "
          f"({100*sum(int(r['salary_disclosed']) for r in quality_rows)/n:.1f}%)")
    for col in ["q_wage", "q_work_time", "q_welfare", "q_growth", "q_youth_friendly"]:
        vals = [int(r[col]) for r in quality_rows]
        nz = sum(1 for v in vals if v > 0)
        print(f"  {col.ljust(18)} 평균 {sum(vals)/n:.2f} | 1개↑ 보유 {nz}/{n} ({100*nz/n:.1f}%)")
    print(f"  공공기관(질셋 내): {sum(1 for r in quality_rows if r.get('is_public_sector')=='1')}건 (플래그)")
    print("\n[다음] 5단계 기초 EDA.")
    print("=" * 64)


if __name__ == "__main__":
    main()
