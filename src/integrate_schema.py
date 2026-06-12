# -*- coding: utf-8 -*-
"""
[통합 1단계] 공통 스키마 맞추기.
- 사람인(기준) + 잡코리아(보완)을 하나의 결합 CSV(data/integrated_jobs.csv)로 정렬한다.
- 두 원천은 이미 동일한 30컬럼(constants.JOBS_COLUMNS) 구조이므로, 여기서는
  (1) 값 수준 정합(공백 정리·도메인 점검), (2) 고유 식별자 job_id 부여, (3) 결합만 수행한다.
- 행 제거(품질 필터)·잡코리아 미분류 재분류는 이 단계에서 하지 않는다(2단계 담당).
- 원천 파일(data/jobs.csv, data/saramin_jobs_raw.csv)은 읽기만 하고 수정하지 않는다.

출력: data/integrated_jobs.csv  (컬럼 = ['job_id', 'source_priority'] + JOBS_COLUMNS)
실행: python src/integrate_schema.py
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

INTEGRATED_CSV = C.DATA_DIR / "integrated_jobs.csv"
OUT_COLUMNS = ["job_id", "source_priority"] + list(C.JOBS_COLUMNS)

# 결합 순서: 사람인=기준(primary), 잡코리아=보완(secondary)
SOURCES = [
    # (CSV 경로, source명, job_id 접두, source_priority)
    (CS.SARAMIN_RAW_CSV, CS.SOURCE_NAME, "SR", "primary"),     # 사람인
    (C.JOBS_CSV,         C.SOURCE_NAME,  "JK", "secondary"),   # 잡코리아
]

# 값 도메인(정합 점검용; 위반 시 삭제하지 않고 카운트만 보고)
DOM_REGION = set(C.BASE_REGIONS) | set(C.EXTRA_REGIONS) | {""}
DOM_JOBGROUP = set(C.JOB_GROUP_NAMES) | {"미분류", ""}


def load_rows(path):
    if not path.exists():
        return None
    with open(path, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def align_value(row):
    """값 수준 정합: 모든 셀 공백 정리, 누락 컬럼은 빈값으로 채움(스키마 고정)."""
    out = {}
    for col in C.JOBS_COLUMNS:
        v = row.get(col, "")
        v = "" if v is None else str(v).strip()
        out[col] = v
    return out


def main():
    all_rows = []
    report = []
    seq = 0

    for path, source_name, prefix, priority in SOURCES:
        rows = load_rows(path)
        if rows is None:
            print(f"⚠️  파일 없음: {path} — 건너뜀")
            continue
        # 스키마 점검
        cols = list(rows[0].keys()) if rows else []
        missing = [c for c in C.JOBS_COLUMNS if c not in cols]
        extra = [c for c in cols if c not in C.JOBS_COLUMNS]

        bad_region = bad_jg = 0
        idx = 0
        for r in rows:
            a = align_value(r)
            # source는 원천 표기를 신뢰하되, 비었으면 보정
            if not a.get("source"):
                a["source"] = source_name
            # 도메인 점검(보고용; 값은 보존)
            if a.get("region") not in DOM_REGION:
                bad_region += 1
            if a.get("job_group") not in DOM_JOBGROUP:
                bad_jg += 1
            idx += 1
            seq += 1
            a["job_id"] = f"{prefix}{idx:06d}"
            a["source_priority"] = priority
            all_rows.append(a)

        report.append({
            "source": source_name, "rows": len(rows),
            "missing": missing, "extra": extra,
            "bad_region": bad_region, "bad_jg": bad_jg,
        })

    # 결합 파일 기록(사람인 먼저 → 잡코리아)
    with open(INTEGRATED_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(OUT_COLUMNS)
        for a in all_rows:
            w.writerow([a.get(c, "") for c in OUT_COLUMNS])

    # ── 리포트 ──
    print("=" * 64)
    print("[통합 1단계] 공통 스키마 맞추기 결과")
    print("=" * 64)
    for rp in report:
        print(f"- {rp['source']}: {rp['rows']}행 | "
              f"누락컬럼 {rp['missing'] or '없음'} | 여분컬럼 {rp['extra'] or '없음'} | "
              f"region 도메인위반 {rp['bad_region']} | job_group 도메인위반 {rp['bad_jg']}")
    print(f"\n결합 산출물: {INTEGRATED_CSV}")
    print(f"총 행 수: {len(all_rows)} (컬럼 {len(OUT_COLUMNS)}개)")
    print("출처별:", dict(Counter(a["source"] for a in all_rows)))
    print("source_priority별:", dict(Counter(a["source_priority"] for a in all_rows)))
    print("\n[참고] 행 제거·잡코리아 미분류 재분류는 2단계(품질 필터링)에서 진행합니다.")
    print("=" * 64)


if __name__ == "__main__":
    main()
