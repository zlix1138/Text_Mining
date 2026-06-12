# -*- coding: utf-8 -*-
"""
[통합 3단계] 중복 제거 (사람인 기준 보존, 잡코리아 중복 제거).

판정 기준: 회사명(정규화) + 제목(정규화) 완전일치.
제거 범위: 출처 내 + 출처 간 모두.
보존 규칙: 사람인=기준이므로 사람인을 먼저 보존하고, 동일 키가 다시 나오면 제거.
          (입력 파일은 사람인 먼저 → 잡코리아 순서라, 파일 순서대로 처리하면 사람인이 보존됨)

입력:  data/integrated_analysis.csv          (2단계 품질필터 통과분)
출력:  data/integrated_dedup.csv             (중복 제거된 최종 분석셋; is_duplicate=0)
       data/integrated_duplicates_removed.csv (제거된 중복행 감사 로그)
실행:  python src/dedup.py
"""

import csv
import os
import re
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C

IN_CSV = C.DATA_DIR / "integrated_analysis.csv"
OUT_CSV = C.DATA_DIR / "integrated_dedup.csv"
REMOVED_CSV = C.DATA_DIR / "integrated_duplicates_removed.csv"

_LEGAL = ["(주)", "㈜", "(유)", "(재)", "(사)", "주식회사", "유한회사", "co.,ltd",
          "co.ltd", "ltd", "inc", "corp"]


def ncompany(s):
    s = (s or "").lower()
    for t in _LEGAL:
        s = s.replace(t, "")
    return re.sub(r"[^0-9a-z가-힣]", "", s)


def ntitle(s):
    s = (s or "").lower()
    s = re.sub(r"\[[^\]]*\]", " ", s)          # [대괄호] 제거
    s = re.sub(r"\([^)]*\)", " ", s)           # (괄호) 제거
    s = re.sub(r"~?\s*\d{1,2}/\d{1,2}.*$", " ", s)   # 끝 마감일 제거
    return re.sub(r"[^0-9a-z가-힣]", "", s)


def main():
    if not IN_CSV.exists():
        print(f"⚠️  입력 없음: {IN_CSV} — 먼저 python src/quality_filter.py 실행")
        return
    with open(IN_CSV, encoding=C.CSV_ENCODING) as f:
        rows = list(csv.DictReader(f))
    in_cols = list(rows[0].keys()) if rows else []
    extra = [c for c in ["is_duplicate", "duplicate_of", "dup_scope"] if c not in in_cols]
    out_cols = in_cols + extra

    seen = {}            # (company,title) -> (job_id, source)
    kept, removed = [], []
    rm_scope = Counter()
    rm_source = Counter()

    for r in rows:
        c, t = ncompany(r.get("company_name", "")), ntitle(r.get("title", ""))
        r["is_duplicate"], r["duplicate_of"], r["dup_scope"] = 0, "", ""
        if not c or not t:                 # 키 불완전 → 안전하게 보존
            kept.append(r)
            continue
        key = (c, t)
        if key in seen:
            keep_id, keep_src = seen[key]
            scope = "출처간" if r.get("source") != keep_src else "출처내"
            r["is_duplicate"], r["duplicate_of"], r["dup_scope"] = 1, keep_id, scope
            removed.append(r)
            rm_scope[scope] += 1
            rm_source[r.get("source", "")] += 1
        else:
            seen[key] = (r["job_id"], r.get("source", ""))
            kept.append(r)

    with open(OUT_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f); w.writerow(out_cols)
        for r in kept:
            w.writerow([r.get(col, "") for col in out_cols])
    with open(REMOVED_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f); w.writerow(out_cols)
        for r in removed:
            w.writerow([r.get(col, "") for col in out_cols])

    # ── 리포트 ──
    print("=" * 64)
    print("[통합 3단계] 중복 제거 결과 (회사+제목 완전일치, 사람인 보존)")
    print("=" * 64)
    print(f"입력: {IN_CSV.name} ({len(rows)}행)")
    print(f"제거: {len(removed)}건  → 최종 {len(kept)}행")
    print(f"  범위별 제거: {dict(rm_scope)}")
    print(f"  제거된 출처: {dict(rm_source)}")
    print(f"\n[최종 분석셋 출처별]")
    for s, n in Counter(r.get("source", "") for r in kept).most_common():
        print(f"   {s.ljust(8)} {n}")
    print(f"\n[최종 직군 분포]")
    jg = Counter(r["job_group"] for r in kept)
    for g in C.JOB_GROUP_NAMES:
        print(f"   {g.ljust(12)} {jg.get(g,0)}")
    print(f"\n[최종 지역 분포]")
    for rg, n in Counter(r["region"] for r in kept).most_common():
        print(f"   {rg.ljust(8)} {n}")
    print(f"\n산출물: {OUT_CSV.name}(최종 {len(kept)}행) / {REMOVED_CSV.name}(제거 {len(removed)}건)")
    print("[다음] 4단계 일자리 양/질 분석 분리.")
    print("=" * 64)


if __name__ == "__main__":
    main()
