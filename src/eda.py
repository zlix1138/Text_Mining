# -*- coding: utf-8 -*-
"""
[통합 5단계] 기초 EDA (기술통계 — 정규화·가중합 점수화는 범위 밖).
산출물: data/eda/  아래 표(EDA_report.md) + 차트(PNG).
14개 산출물 + 양/질·출처·공공vs민간·양↔질 교차 분석.

입력(모두 읽기 전용):
  data/jobs.csv, data/saramin_jobs_raw.csv            (원본 수집)
  data/integrated_labeled.csv                          (필터 플래그 포함 전체 11,000)
  data/integrated_analysis.csv                         (필터 통과 6,885)
  data/integrated_duplicates_removed.csv               (제거된 중복 310)
  data/integrated_dedup.csv / data/quality_jobs.csv    (최종 6,575 + 질 피처)
  data/quantity_region_jobgroup.csv                    (양)
실행: python src/eda.py
"""

import csv
import os
import statistics
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C

EDA_DIR = C.DATA_DIR / "eda"
EDA_DIR.mkdir(exist_ok=True)
REPORT = EDA_DIR / "EDA_report.md"

REGIONS = list(C.BASE_REGIONS.keys())
JGS = list(C.JOB_GROUP_NAMES)
DIMS = [("q_wage", "임금"), ("q_work_time", "근로시간"), ("q_welfare", "복지"),
        ("q_growth", "성장"), ("q_youth_friendly", "청년친화")]


def load(name):
    p = C.DATA_DIR / name
    if not p.exists():
        return []
    with open(p, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def i(x):
    try:
        return int(str(x).replace(",", "").strip())
    except Exception:
        return 0


def pct(n, d):
    return f"{100.0*n/d:.1f}%" if d else "0%"


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def savefig(fig, name):
    path = EDA_DIR / name
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return name


def main():
    jk_raw = load("jobs.csv")
    sr_raw = load("saramin_jobs_raw.csv")
    labeled = load("integrated_labeled.csv")
    analysis = load("integrated_analysis.csv")
    removed = load("integrated_duplicates_removed.csv")
    final = load("quality_jobs.csv")          # 최종 6,575 + 질 피처
    quant = load("quantity_region_jobgroup.csv")

    md = ["# 통합 데이터셋 기초 EDA 리포트", "",
          f"- 원본: 사람인 {len(sr_raw)} + 잡코리아 {len(jk_raw)} = {len(sr_raw)+len(jk_raw)}",
          f"- 통합 라벨셋: {len(labeled)} / 필터통과: {len(analysis)} / 최종(중복제거): {len(final)}",
          "- 점수화(정규화·가중합)는 범위 밖, 기초 기술통계만.", ""]

    # 1) 원본 데이터 수집 현황표
    def raw_stat(rows):
        regs = len({r["region"] for r in rows if r.get("region")})
        uncl = sum(1 for r in rows if r.get("job_group") == "미분류")
        return [len(rows), regs, uncl, pct(uncl, len(rows))]
    md += ["## 1. 원본 데이터 수집 현황",
           md_table(["출처", "행수", "지역수", "미분류(원본)", "미분류율"],
                    [["사람인"] + raw_stat(sr_raw), ["잡코리아"] + raw_stat(jk_raw)]), ""]

    # 2) 출처별 품질 비교표 (라벨셋 11,000 기준)
    def qual_stat(src):
        rs = [r for r in labeled if r.get("source") == src]
        n = len(rs)
        reg = sum(1 for r in rs if r.get("employment_type") == "정규직")
        sal = sum(1 for r in rs if r.get("salary_min") or r.get("salary_max"))
        yf = sum(1 for r in rs if r.get("is_youth_friendly") == "1")
        ml = statistics.median([len(r.get("raw_text", "")) for r in rs]) if rs else 0
        return [n, pct(reg, n), pct(sal, n), pct(yf, n), int(ml)]
    md += ["## 2. 출처별 품질 비교 (통합 라벨셋)",
           md_table(["출처", "행수", "정규직", "급여공개", "청년친화", "raw_text 중앙값"],
                    [["사람인"] + qual_stat("사람인"), ["잡코리아"] + qual_stat("잡코리아")]), ""]

    # 3) 중복 제거 전후 비교표
    rm_scope = Counter(r.get("dup_scope", "") for r in removed)
    rm_src = Counter(r.get("source", "") for r in removed)
    md += ["## 3. 중복 제거 전후 비교",
           md_table(["구분", "값"],
                    [["제거 전(필터통과)", len(analysis)], ["제거", len(removed)],
                     ["제거 후(최종)", len(final)],
                     ["출처내 제거", rm_scope.get("출처내", 0)],
                     ["출처간 제거", rm_scope.get("출처간", 0)],
                     ["사람인 제거", rm_src.get("사람인", 0)],
                     ["잡코리아 제거", rm_src.get("잡코리아", 0)]]), ""]

    # 4) 최종 포함/제외 공고 수 요약 (퍼널)
    inc = sum(1 for r in labeled if r.get("include_in_analysis") == "1")
    md += ["## 4. 최종 포함/제외 요약 (퍼널)",
           md_table(["단계", "행수"],
                    [["통합 라벨셋", len(labeled)],
                     ["품질필터 포함", inc],
                     ["품질필터 제외", len(labeled) - inc],
                     ["중복 제거", len(removed)],
                     ["최종 분석셋", len(final)]]), ""]

    # 5) 제외 사유별 분포 (표 + 막대)
    reason_all = Counter()
    for r in labeled:
        for x in (r.get("exclude_reason", "") or "").split(";"):
            if x:
                reason_all[x] += 1
    md += ["## 5. 제외 사유별 분포 (중복집계)",
           md_table(["사유", "건수"], reason_all.most_common()),
           f"\n![제외사유](exclude_reasons.png)", ""]
    if reason_all:
        fig, ax = plt.subplots(figsize=(7, 4))
        labels, vals = zip(*reason_all.most_common())
        ax.bar(labels, vals, color="#d9534f")
        ax.set_title("제외 사유별 분포"); ax.set_ylabel("건수")
        for x, v in enumerate(vals):
            ax.text(x, v, str(v), ha="center", va="bottom", fontsize=9)
        savefig(fig, "exclude_reasons.png")

    # 6) 지역별 최종 분석 공고 수 (표 + 막대)
    reg_cnt = Counter(r["region"] for r in final)
    md += ["## 6. 지역별 최종 분석 공고 수",
           md_table(["지역", "공고수"], [[rg, reg_cnt.get(rg, 0)] for rg in REGIONS]),
           "\n![지역별](region_counts.png)", ""]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(REGIONS, [reg_cnt.get(rg, 0) for rg in REGIONS], color="#5b9bd5")
    ax.set_title("지역별 최종 분석 공고 수"); ax.set_ylabel("공고수")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    savefig(fig, "region_counts.png")

    # 7) 지역×직무군 분포 (표 + 누적 막대)
    grid = Counter((r["region"], r["job_group"]) for r in final)
    md += ["## 7. 지역 × 직무군 분포",
           md_table(["지역"] + JGS + ["합계"],
                    [[rg] + [grid.get((rg, g), 0) for g in JGS]
                     + [sum(grid.get((rg, g), 0) for g in JGS)] for rg in REGIONS]),
           "\n![지역직군](region_jobgroup_stacked.png)", ""]
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = [0] * len(REGIONS)
    for g in JGS:
        vals = [grid.get((rg, g), 0) for rg in REGIONS]
        ax.bar(REGIONS, vals, bottom=bottom, label=g)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_title("지역 × 직무군 분포(누적)"); ax.set_ylabel("공고수")
    ax.legend(fontsize=8, ncol=3)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    savefig(fig, "region_jobgroup_stacked.png")

    # 8) 출처 × 직무군 분포 (표)
    src_jg = Counter((r["source"], r["job_group"]) for r in final)
    md += ["## 8. 출처 × 직무군 분포",
           md_table(["출처"] + JGS, [[s] + [src_jg.get((s, g), 0) for g in JGS]
                                    for s in ("사람인", "잡코리아")]), ""]

    # 9) 임금 공개율 및 임금 분포 (표 + 히스토그램)
    sal_open = sum(1 for r in final if r.get("salary_disclosed") == "1")
    sal_vals = [i(r.get("salary_min")) for r in final
                if r.get("salary_type") == "연봉" and i(r.get("salary_min")) > 0]
    sal_vals = [v for v in sal_vals if 1000 <= v <= 12000]   # 연봉(만원) 이상치 컷
    md += ["## 9. 임금 공개율 및 분포",
           md_table(["지표", "값"],
                    [["급여 수치 공개율", pct(sal_open, len(final))],
                     ["연봉 표본수(만원)", len(sal_vals)],
                     ["연봉 중앙값", f"{int(statistics.median(sal_vals)):,}만원" if sal_vals else "-"],
                     ["연봉 평균", f"{int(statistics.mean(sal_vals)):,}만원" if sal_vals else "-"]]),
           "\n![임금](salary_hist.png)", ""]
    if sal_vals:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(sal_vals, bins=30, color="#70ad47", edgecolor="white")
        ax.set_title("연봉(salary_min) 분포 — 공개 공고"); ax.set_xlabel("만원"); ax.set_ylabel("공고수")
        savefig(fig, "salary_hist.png")

    # 10) 고용형태 분포 (표 + 막대)
    emp = Counter(r.get("employment_type", "") or "(빈값)" for r in final)
    md += ["## 10. 고용형태 분포",
           md_table(["고용형태", "건수"], emp.most_common()),
           "\n![고용형태](employment_types.png)", ""]
    fig, ax = plt.subplots(figsize=(7, 4))
    labels, vals = zip(*emp.most_common())
    ax.bar(labels, vals, color="#ed7d31")
    ax.set_title("고용형태 분포"); ax.set_ylabel("건수")
    savefig(fig, "employment_types.png")

    # 11) 텍스트 길이 분포 (히스토그램)
    tlens = [len(r.get("raw_text", "")) for r in final]
    md += ["## 11. raw_text 길이 분포",
           md_table(["지표", "값"],
                    [["중앙값", int(statistics.median(tlens))],
                     ["평균", int(statistics.mean(tlens))],
                     ["최소/최대", f"{min(tlens)} / {max(tlens)}"]]),
           "\n![텍스트길이](textlen_hist.png)", ""]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist([min(t, 5000) for t in tlens], bins=40, color="#7030a0", edgecolor="white")
    ax.set_title("raw_text 길이 분포(5000자 클립)"); ax.set_xlabel("문자수"); ax.set_ylabel("공고수")
    savefig(fig, "textlen_hist.png")

    # 12) 지역별 키워드 피처 포함 비율 (표 + 히트맵)
    heat = []   # region × dim (% rows with feature>0)
    md_rows = []
    for rg in REGIONS:
        rs = [r for r in final if r["region"] == rg]
        n = len(rs)
        row = []
        for col, _ in DIMS:
            p = sum(1 for r in rs if i(r.get(col)) > 0) / n if n else 0
            row.append(p)
        heat.append(row)
        md_rows.append([rg] + [pct(int(p*len(rs)), len(rs)) for p in row])
    md += ["## 12. 지역별 키워드 피처 포함 비율",
           md_table(["지역"] + [d[1] for d in DIMS], md_rows),
           "\n![피처히트맵](region_feature_heatmap.png)", ""]
    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(heat, cmap="YlGnBu", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(DIMS))); ax.set_xticklabels([d[1] for d in DIMS])
    ax.set_yticks(range(len(REGIONS))); ax.set_yticklabels(REGIONS)
    for y in range(len(REGIONS)):
        for x in range(len(DIMS)):
            ax.text(x, y, f"{heat[y][x]*100:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="피처 보유 비율")
    ax.set_title("지역 × 질 피처 보유 비율(%)")
    savefig(fig, "region_feature_heatmap.png")

    # 13) 공공기관 플래그 분포 (표)
    pub = [r for r in final if r.get("is_public_sector") == "1"]
    pub_reg = Counter(r["region"] for r in pub)
    md += ["## 13. 공공기관 플래그 분포 (최종셋)",
           md_table(["구분", "값"],
                    [["공공기관", len(pub)], ["민간", len(final)-len(pub)],
                     ["공공 비율", pct(len(pub), len(final))]]),
           md_table(["지역", "공공기관수"], [[rg, pub_reg.get(rg, 0)] for rg in REGIONS if pub_reg.get(rg, 0)]),
           ""]
    # 공공 vs 민간 품질 비교
    def grp_mean(rs, col):
        return statistics.mean([i(r.get(col)) for r in rs]) if rs else 0
    priv = [r for r in final if r.get("is_public_sector") != "1"]
    md += ["### 13-1. 공공 vs 민간 질 비교",
           md_table(["구분", "정규직", "급여공개", "청년친화(평균)", "복지(평균)"],
                    [["공공", pct(sum(1 for r in pub if r['employment_stability']=='1'), len(pub)),
                      pct(sum(1 for r in pub if r['salary_disclosed']=='1'), len(pub)),
                      f"{grp_mean(pub,'q_youth_friendly'):.2f}", f"{grp_mean(pub,'q_welfare'):.2f}"],
                     ["민간", pct(sum(1 for r in priv if r['employment_stability']=='1'), len(priv)),
                      pct(sum(1 for r in priv if r['salary_disclosed']=='1'), len(priv)),
                      f"{grp_mean(priv,'q_youth_friendly'):.2f}", f"{grp_mean(priv,'q_welfare'):.2f}"]]), ""]

    # 14) 최종 분석 가능 데이터셋 요약 (표)
    md += ["## 14. 최종 분석셋 요약",
           md_table(["항목", "값"],
                    [["행수", len(final)],
                     ["출처", dict(Counter(r['source'] for r in final))],
                     ["지역수", len({r['region'] for r in final})],
                     ["직무군수", len({r['job_group'] for r in final})],
                     ["정규직 비율", pct(sum(1 for r in final if r['employment_stability']=='1'), len(final))],
                     ["급여공개 비율", pct(sum(1 for r in final if r['salary_disclosed']=='1'), len(final))],
                     ["공공기관", len(pub)]]), ""]

    # 분석 A) 지역별 양/질
    qmax = defaultdict(int)   # region -> 사람인 직무군 max 합
    for r in quant:
        qmax[r["region"]] += i(r["sr_search_total_max"])
    md += ["## A. 지역별 양 ↔ 질",
           md_table(["지역", "사람인 양(max합)", "최종표본수", "정규직", "급여공개", "청년친화(평균)"],
                    [[rg, f"{qmax.get(rg,0):,}", reg_cnt.get(rg, 0),
                      pct(sum(1 for r in final if r['region']==rg and r['employment_stability']=='1'), reg_cnt.get(rg,1)),
                      pct(sum(1 for r in final if r['region']==rg and r['salary_disclosed']=='1'), reg_cnt.get(rg,1)),
                      f"{grp_mean([r for r in final if r['region']==rg],'q_youth_friendly'):.2f}"]
                     for rg in REGIONS]), ""]

    # 분석 B) 직군별 양/질
    qjg = defaultdict(int)
    for r in quant:
        qjg[r["job_group"]] += i(r["sr_search_total_max"])
    md += ["## B. 직무군별 양 ↔ 질",
           md_table(["직무군", "사람인 양(max합)", "최종표본수", "정규직", "급여공개"],
                    [[g, f"{qjg.get(g,0):,}",
                      sum(1 for r in final if r['job_group']==g),
                      pct(sum(1 for r in final if r['job_group']==g and r['employment_stability']=='1'),
                          max(1,sum(1 for r in final if r['job_group']==g))),
                      pct(sum(1 for r in final if r['job_group']==g and r['salary_disclosed']=='1'),
                          max(1,sum(1 for r in final if r['job_group']==g)))]
                     for g in JGS]), ""]

    # 분석 C) 양↔질 교차 산점도 (region×job_group): x=양(sr max), y=정규직비율
    pts = []
    qmap = {(r["region"], r["job_group"]): i(r["sr_search_total_max"]) for r in quant}
    for rg in REGIONS:
        for g in JGS:
            cell = [r for r in final if r["region"] == rg and r["job_group"] == g]
            if not cell:
                continue
            x = qmap.get((rg, g), 0)
            y = sum(1 for r in cell if r["employment_stability"] == "1") / len(cell)
            pts.append((x, y, rg, g))
    md += ["## C. 양 ↔ 질 교차 (지역×직무군 산점도)",
           "x=사람인 양(search_total max), y=정규직 비율. 우하단(양 많고 질 낮음) 주목.",
           "\n![양질교차](quantity_vs_quality.png)", ""]
    if pts:
        fig, ax = plt.subplots(figsize=(7, 5))
        xs = [p[0] for p in pts]; ys = [p[1]*100 for p in pts]
        ax.scatter(xs, ys, c="#5b9bd5", alpha=0.7)
        ax.set_xlabel("사람인 양(search_total max)"); ax.set_ylabel("정규직 비율(%)")
        ax.set_title("양 ↔ 질 교차 (지역×직무군)")
        savefig(fig, "quantity_vs_quality.png")

    REPORT.write_text("\n".join(md), encoding="utf-8")

    # ── 콘솔 요약 ──
    print("=" * 64)
    print("[통합 5단계] 기초 EDA 완료")
    print("=" * 64)
    print(f"리포트: {REPORT}")
    pngs = sorted(p.name for p in EDA_DIR.glob("*.png"))
    print(f"차트 {len(pngs)}개: {pngs}")
    print(f"최종 분석셋 {len(final)}행 | 정규직 "
          f"{pct(sum(1 for r in final if r['employment_stability']=='1'), len(final))} | "
          f"급여공개 {pct(sum(1 for r in final if r['salary_disclosed']=='1'), len(final))} | "
          f"공공 {len(pub)}건")
    print("=" * 64)


if __name__ == "__main__":
    main()
