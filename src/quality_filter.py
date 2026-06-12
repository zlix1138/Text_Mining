# -*- coding: utf-8 -*-
"""
[통합 2단계-b] 품질 필터링 (하드 삭제 대신 플래그 + 분석셋 동시 산출).

분석 범위: 5개 직군으로 한정(미분류=타직종은 분석 제외).
제외(플래그) 기준 — include_in_analysis=0, exclude_reason에 사유 누적:
  - 범위외       : job_group == '미분류'(5개 직군 외)
  - 지역미상     : region 빈값(분석대상 외 광역시 등)
  - 수집실패     : crawl_status != 'success'
  - 저정보       : raw_text 길이 < LOW_INFO_MIN(이미지형 JD 등 질 분석 불가)
  - 헤드헌팅     : note '헤드헌팅' 또는 detail_status == 'skipped_headhunting'
  - 알바단기     : note '아르바이트/단기/행사' 또는 제목에 EXCLUDE_SIGNALS
  - 청년부적합   : note '경력 3년 초과' 또는 '관리자·임원급'(신입·경력무관 신호 없을 때만 표시됨)

공공기관: 제외하지 않고 is_public_sector=1 로 표시만 한다(양 분석 포함, 질 분석은 분리/민감도용).

입력:  data/integrated_reclassified.csv
출력:  data/integrated_labeled.csv   (전체 + 플래그 3컬럼)
       data/integrated_analysis.csv  (include_in_analysis==1 만; 3단계 중복제거 입력)
실행:  python src/quality_filter.py
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

IN_CSV = C.DATA_DIR / "integrated_reclassified.csv"
LABELED_CSV = C.DATA_DIR / "integrated_labeled.csv"
ANALYSIS_CSV = C.DATA_DIR / "integrated_analysis.csv"

LOW_INFO_MIN = 100          # raw_text 길이 하한(미만이면 저정보)
NEW_COLS = ["is_public_sector", "include_in_analysis", "exclude_reason"]


def _note_has(r, *kw):
    n = r.get("note", "") or ""
    return any(k in n for k in kw)


def is_public_sector(r):
    return 1 if (any(s in (r.get("company_name", "") or "") for s in C.EXCLUDE_PUBLIC_SIGNALS)
                 or _note_has(r, "공공기관")) else 0


def exclude_reasons(r):
    """제외 사유 리스트(없으면 빈 리스트 = 분석 포함)."""
    out = []
    if r.get("job_group") == "미분류":
        out.append("범위외")
    if not (r.get("region") or "").strip():
        out.append("지역미상")
    if r.get("crawl_status") != "success":
        out.append("수집실패")
    if len(r.get("raw_text", "") or "") < LOW_INFO_MIN:
        out.append("저정보")
    if _note_has(r, "헤드헌팅") or r.get("detail_status") == "skipped_headhunting":
        out.append("헤드헌팅")
    if _note_has(r, "아르바이트", "단기", "행사") or any(s in (r.get("title", "") or "")
                                                  for s in C.EXCLUDE_SIGNALS):
        out.append("알바단기")
    if _note_has(r, "경력 3년 초과", "관리자·임원급"):
        out.append("청년부적합")
    return out


def main():
    if not IN_CSV.exists():
        print(f"⚠️  입력 없음: {IN_CSV} — 먼저 python src/reclassify.py 실행")
        return
    with open(IN_CSV, encoding=C.CSV_ENCODING) as f:
        rows = list(csv.DictReader(f))
    in_cols = list(rows[0].keys()) if rows else []
    out_cols = in_cols + [c for c in NEW_COLS if c not in in_cols]

    reason_first = Counter()
    reason_all = Counter()
    inc = 0
    by_src_inc = Counter()
    pub_total = pub_inc = 0

    for r in rows:
        rs = exclude_reasons(r)
        pub = is_public_sector(r)
        r["is_public_sector"] = pub
        r["include_in_analysis"] = 0 if rs else 1
        r["exclude_reason"] = ";".join(rs)
        pub_total += pub
        if rs:
            reason_first[rs[0]] += 1
            for x in rs:
                reason_all[x] += 1
        else:
            inc += 1
            by_src_inc[r.get("source", "")] += 1
            pub_inc += pub

    # 전체 라벨 파일
    with open(LABELED_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(out_cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in out_cols])
    # 분석셋(포함만)
    inc_rows = [r for r in rows if r["include_in_analysis"] == 1]
    with open(ANALYSIS_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(out_cols)
        for r in inc_rows:
            w.writerow([r.get(c, "") for c in out_cols])

    # ── 리포트 ──
    print("=" * 64)
    print("[통합 2단계-b] 품질 필터링 결과")
    print("=" * 64)
    print(f"입력: {IN_CSV.name} ({len(rows)}행)")
    print(f"분석 포함: {inc} / 제외: {len(rows)-inc}")
    print(f"  포함 출처별: {dict(by_src_inc)}")
    print(f"\n[제외 1순위 사유]")
    for k, n in reason_first.most_common():
        print(f"   {k.ljust(10)} {n}")
    print(f"[제외 사유 전체(중복집계)]")
    for k, n in reason_all.most_common():
        print(f"   {k.ljust(10)} {n}")
    print(f"\n[분석셋 직군 분포]")
    jg = Counter(r["job_group"] for r in inc_rows)
    for g in C.JOB_GROUP_NAMES:
        print(f"   {g.ljust(12)} {jg.get(g,0)}")
    print(f"\n[분석셋 지역 분포]")
    for rg, n in Counter(r["region"] for r in inc_rows).most_common():
        print(f"   {rg.ljust(8)} {n}")
    print(f"\n공공기관: 전체 {pub_total}건(플래그) / 분석셋 내 {pub_inc}건 (제외 안 함)")
    print(f"\n산출물: {LABELED_CSV.name}(전체+플래그) / {ANALYSIS_CSV.name}(분석 포함 {inc}행)")
    print("[다음] 3단계 중복 제거(사람인 기준, 잡코리아 중복 제거).")
    print("=" * 64)


if __name__ == "__main__":
    main()
