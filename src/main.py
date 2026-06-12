# -*- coding: utf-8 -*-
"""
수집 오케스트레이션 (Path B: 지역 수집 + 사후 직무분류).

흐름(지역별):
  1) 세션 쿠키 설정(joblist GET)
  2) 지역 전체 건수(_SearchCount) → search_counts.csv
  3) 목록 페이지네이션(_GI_List)로 정규공고 수집(중복/HH 제외)
  4) 상세(GI_Read) JSON-LD 파싱 → (본문 누락 & --with-body 시) Playwright 폴백
  5) 전처리·표준화·직무군 분류 → jobs.csv 누적 저장(중간 저장으로 중단 대비)
  6) 실패는 failures.csv, 모든 이벤트는 crawl_log.csv

CLI 예:
  python src/main.py --regions 서울 --limit 5            # 스모크 테스트(상세 5건)
  python src/main.py --per-region 150 --with-body        # 전체 지역, 본문 Playwright 폴백 포함
  python src/main.py --counts-only                       # 4단계: 지역 건수만 수집
"""

import argparse
import csv
import datetime as dt
import random
import sys
import time
import os

# Windows 콘솔(cp949) 한글 출력 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# src 디렉터리를 모듈 경로에 추가(상대 import 단순화)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants as C
import parser as P
import preprocess as PP
from crawler import JobKoreaCrawler


# ── CSV 입출력 헬퍼(UTF-8-SIG, 헤더 자동, append) ────────────────────────────
def _ensure_csv(path, columns):
    """파일이 없으면 헤더를 쓴다."""
    if not path.exists():
        with open(path, "w", newline="", encoding=C.CSV_ENCODING) as f:
            csv.writer(f).writerow(columns)


def append_row(path, columns, row):
    """dict 행을 스키마 순서로 한 줄 append(중간 저장)."""
    _ensure_csv(path, columns)
    with open(path, "a", newline="", encoding=C.CSV_ENCODING) as f:
        csv.writer(f).writerow([row.get(c, "") for c in columns])


def load_existing_urls():
    """재실행 시 이어받기: 이미 수집한 url 집합을 반환."""
    urls = set()
    if C.JOBS_CSV.exists():
        with open(C.JOBS_CSV, encoding=C.CSV_ENCODING) as f:
            for r in csv.DictReader(f):
                if r.get("url"):
                    urls.add(r["url"])
    return urls


def make_logger():
    """crawl_log.csv에 기록하면서 터미널에도 출력하는 로거를 만든다."""
    _ensure_csv(C.CRAWL_LOG_CSV, C.CRAWL_LOG_COLUMNS)

    def log(level, message, url="", region="", job_group=""):
        ts = dt.datetime.now().isoformat(timespec="seconds")
        append_row(C.CRAWL_LOG_CSV, C.CRAWL_LOG_COLUMNS,
                   {"timestamp": ts, "level": level, "message": message,
                    "url": url, "region": region, "job_group": job_group})
        if level in ("ERROR", "WARN", "INFO"):
            print(f"[{level}] {message}" + (f" ({region})" if region else ""))
    return log


def record_failure(url, region, job_group, err_type, err_msg):
    """실패를 failures.csv에 기록(숨기지 않음)."""
    append_row(C.FAILURES_CSV, C.FAILURES_COLUMNS, {
        "url": url, "region": region, "job_group": job_group,
        "error_type": err_type, "error_message": str(err_msg)[:200],
        "collected_date": dt.date.today().isoformat(),
    })


# ── Tier-1: 목록 기반 1건 처리(상세 GET 없음) ────────────────────────────────
def build_row_from_listing(posting, region, search_total_count):
    """
    목록(_GI_List) 파싱 결과 1건 → jobs.csv 행 dict (Tier-1, 상세 페이지 미수집).
    - 회사/제목/경력/학력/지역/고용형태/급여/마감은 목록에서, 직무군은 제목으로 분류.
    - 본문(task/qual/pref/benefits)·정확한 마감·상세주소는 Tier-2(detail_status=pending)에서 채움.
    """
    today = dt.date.today().isoformat()
    base = {c: "" for c in C.JOBS_COLUMNS}

    title = posting.get("title", "")
    region_std = PP.standardize_region(posting.get("region_cell", "")) or region
    job_group, job_kw, jg_note = PP.classify_job_group(title)
    emp = PP.standardize_employment_type(posting.get("employment_raw", ""))
    career = PP.standardize_career(posting.get("career_raw", ""))
    s_type, s_min, s_max = PP.parse_salary(posting.get("salary_raw", ""))
    raw_text = PP.build_raw_text(title, "", "", "", "")   # Tier-1은 제목 수준(본문은 Tier-2)
    youth = PP.is_youth_friendly(posting.get("career_raw", ""), emp, raw_text)

    note_parts = []
    if jg_note:
        note_parts.append(jg_note)
    elig = PP.eligibility_note(career, title, raw_text)
    if elig:
        note_parts.append(elig)
    note_parts.append("Tier-1 목록기반(본문·상세 미수집)")

    base.update({
        "source": C.SOURCE_NAME, "collected_date": today, "url": posting["url"],
        "company_name": posting.get("company_name", ""), "title": title,
        "region": region_std, "region_detail": posting.get("region_cell", ""),
        "job_group": job_group, "job_keyword": job_kw, "job_category_raw": "",
        "career": career, "education": posting.get("education", ""), "employment_type": emp,
        "salary": posting.get("salary_raw", ""), "salary_min": s_min, "salary_max": s_max,
        "salary_type": s_type, "work_time": "", "benefits": "",
        "task_description": "", "qualification": "", "preference": "",
        "deadline": posting.get("deadline_raw", ""),
        "search_total_count": search_total_count, "raw_text": raw_text,
        "is_youth_friendly": youth, "crawl_status": "success",
        "note": " | ".join(note_parts),
        "detail_status": "pending", "tier2_backfilled": 0,
    })
    return base


# ── 2-tier: Playwright 본문 backfill (질 분석용 층화 표본) ────────────────────
def read_all_jobs():
    """jobs.csv 전체를 list[dict]로 읽는다."""
    if not C.JOBS_CSV.exists():
        return []
    with open(C.JOBS_CSV, encoding=C.CSV_ENCODING) as f:
        return list(csv.DictReader(f))


def write_all_jobs(rows):
    """jobs.csv를 스키마 순서로 전체 재기록(backfill 갱신용)."""
    with open(C.JOBS_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(C.JOBS_COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in C.JOBS_COLUMNS])


def select_body_sample(rows, per_region):
    """
    지역별로 본문 미수집 success 공고를 per_region개씩 층화 선택.
    - 본문이 이미 있는 행은 제외. 지역 내에서 직무군 다양성을 위해 round-robin 비슷하게 섞어 선택.
    반환: 선택된 행의 url 집합.
    """
    from collections import defaultdict
    by_region = defaultdict(list)
    for r in rows:
        if r.get("crawl_status") != "success":
            continue
        if str(r.get("tier2_backfilled", "")) == "1":
            continue   # 이미 Tier-2 처리됨(플래그 기준 — 재처리 방지)
        by_region[r.get("region", "")].append(r)
    chosen = set()
    for region, lst in by_region.items():
        for r in lst[:per_region]:
            chosen.add(r["url"])
    return chosen


def run_backfill_body(crawler, per_region, log):
    """
    Tier-2: 선택 표본에 Playwright로 본문을 채우고, 본문 기반으로 분류·raw_text·청년플래그를 갱신.
    중간 저장: 일정 건마다 jobs.csv를 재기록(중단 대비).
    """
    rows = read_all_jobs()
    if not rows:
        log("WARN", "jobs.csv 없음 — 먼저 Tier-1 수집을 실행하세요")
        return
    targets = select_body_sample(rows, per_region)
    log("INFO", f"Tier-2 상세·본문 backfill 대상 {len(targets)}건 (지역당 {per_region})")
    done = 0
    for r in rows:
        if r["url"] not in targets:
            continue
        gno = r["url"].rstrip("/").split("/")[-1].split("?")[0]
        # (1) 상세 JSON-LD(requests)로 메타데이터 보강 — 급여/마감/상세주소/근무시간 등
        html = crawler.fetch_detail(gno)
        if html:
            d = P.parse_detail(html)
            if d.get("is_headhunting"):
                r["crawl_status"] = "skipped"
                r["note"] = (r.get("note", "") + " | 헤드헌팅 확인(Tier-2)").strip(" |")
            if d.get("region_detail"):
                r["region_detail"] = d["region_detail"]
                std = PP.standardize_region(d["region_detail"])
                if std in C.BASE_REGIONS or std in C.EXTRA_REGIONS:
                    r["region"] = std                      # 실제 근무지역(분석 대상)
                elif std:                                   # 광역시 등 분석 대상 외
                    r["region"] = ""
                    r["note"] = (r.get("note", "") + " | 근무지 기본 10개 지역 외").strip(" |")
                # std가 비면 수집 지역(region) 유지
            if d.get("deadline"):
                r["deadline"] = d["deadline"]
            if d.get("work_time"):
                r["work_time"] = d["work_time"]
            if not r.get("salary") and d.get("salary"):
                r["salary"] = d["salary"]
                s_type, s_min, s_max = PP.parse_salary(d["salary"])
                r["salary_type"], r["salary_min"], r["salary_max"] = s_type, s_min, s_max
            for k in ("task_description", "qualification", "preference", "benefits"):
                if d.get(k):
                    r[k] = d[k]
        # (2) 본문이 여전히 비면 Playwright 폴백
        if not (r.get("task_description") or r.get("qualification")):
            blob = crawler.fetch_body_playwright(r["url"])
            if blob:
                seg = P.parse_playwright_body(blob)
                r["task_description"] = seg.get("task_description", "")
                r["qualification"] = seg.get("qualification", "")
                r["preference"] = seg.get("preference", "")
                r["benefits"] = seg.get("benefits", "")
                if seg.get("job_category") and not r.get("job_category_raw"):
                    r["job_category_raw"] = seg["job_category"]   # 모집분야 → 분류 정확도↑
                if not seg.get("segmented", True):
                    r["note"] = (r.get("note", "") + " | 본문 섹션분할 실패(통짜)").strip(" |")
            else:
                r["note"] = (r.get("note", "") + " | 본문 backfill 실패").strip(" |")
        # (3) 본문 반영해 분류·raw_text·청년플래그 재계산 + 상태 갱신
        r["note"] = " | ".join(p for p in r.get("note", "").split(" | ")
                               if "미수집" not in p and "Tier-1 목록기반" not in p).strip(" |")
        jg, kw, _ = PP.classify_job_group(
            r["title"], r.get("job_category_raw", ""),
            " ".join([r.get("task_description", ""), r.get("qualification", "")]))
        if jg != "미분류":
            r["job_group"], r["job_keyword"] = jg, kw
        r["raw_text"] = PP.build_raw_text(r["title"], r.get("task_description", ""),
                                          r.get("qualification", ""), r.get("preference", ""),
                                          r.get("benefits", ""))
        r["is_youth_friendly"] = PP.is_youth_friendly(r.get("career", ""),
                                                      r.get("employment_type", ""), r["raw_text"])
        r["detail_status"] = "done"
        r["tier2_backfilled"] = 1
        done += 1
        time.sleep(random.uniform(0.8, 1.5))   # 요청 간격(예절) — PW 대기와 합쳐 폴라이트
        if done % 25 == 0:
            write_all_jobs(rows)   # 중간 저장
            log("INFO", f"Tier-2 진행 {done}/{len(targets)}")
    write_all_jobs(rows)
    log("INFO", f"Tier-2 상세·본문 backfill 완료: {done}건 갱신")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="잡코리아 청년 일자리 데이터셋 수집")
    ap.add_argument("--regions", nargs="*", default=None,
                    help="수집할 지역명(미지정 시 서울+9개 도 전체)")
    ap.add_argument("--per-region", type=int, default=C.TARGET_PER_REGION,
                    help="지역당 상세 수집 목표 건수")
    ap.add_argument("--limit", type=int, default=None,
                    help="(스모크) 지역당 수집 상한")
    ap.add_argument("--counts-only", action="store_true",
                    help="지역 전체 건수만 수집(4단계)")
    ap.add_argument("--backfill-body", action="store_true",
                    help="(Tier-2) 기존 jobs.csv 표본에 Playwright로 본문을 채움")
    ap.add_argument("--body-per-region", type=int, default=C.BODY_SAMPLE_PER_REGION,
                    help="본문 backfill 시 지역당 표본 수")
    args = ap.parse_args()

    log = make_logger()

    # Tier-2 본문 backfill 모드(단독 실행)
    if args.backfill_body:
        crawler = JobKoreaCrawler(logger=log)
        try:
            run_backfill_body(crawler, args.body_per_region, log)
        finally:
            crawler.close()
        print("본문 backfill 완료. 검증: python src/validate_dataset.py")
        return
    regions = {}
    src = args.regions or list(C.BASE_REGIONS.keys())
    for name in src:
        if name in C.BASE_REGIONS:
            regions[name] = C.BASE_REGIONS[name]
        elif name in C.EXTRA_REGIONS:
            regions[name] = C.EXTRA_REGIONS[name]
        else:
            log("WARN", f"알 수 없는 지역명 무시: {name}")

    # 실패 0건이어도 failures.csv는 헤더로 항상 존재하게(필수 산출물)
    _ensure_csv(C.FAILURES_CSV, C.FAILURES_COLUMNS)

    crawler = JobKoreaCrawler(logger=log)
    existing = load_existing_urls()
    seen_gno = set()
    target = args.limit or args.per_region
    total_new = 0
    region_totals = {}

    try:
        for region, code in regions.items():
            codes = code if isinstance(code, list) else [code]
            collected = 0
            count_recorded = 0
            for c in codes:
                referer = crawler.init_session(c)
                # (2) 지역 전체 건수
                cnt = crawler.fetch_region_count(c, referer)
                count_recorded = (count_recorded or 0) + (cnt or 0)
                log("INFO", f"{region}({c}) 전체 건수={cnt}", referer, region)
                if args.counts_only:
                    continue
                # (3) 목록(_GI_List) → Tier-1 목록기반 행 → 저장 (상세 GET 없음)
                for posting in crawler.iter_region_postings(c, referer, seen=seen_gno):
                    if collected >= target:
                        break
                    if posting["url"] in existing:
                        continue
                    try:
                        row = build_row_from_listing(posting, region, count_recorded)
                    except Exception as e:   # 1건 실패가 전체를 멈추지 않게
                        log("WARN", f"공고 처리 예외: {e}", posting["url"], region)
                        record_failure(posting["url"], region, "", "process", e)
                        continue
                    append_row(C.JOBS_CSV, C.JOBS_COLUMNS, row)   # 중간 저장
                    existing.add(posting["url"])
                    collected += 1
                    total_new += 1
                if collected >= target:
                    break
            region_totals[region] = count_recorded
            log("INFO", f"{region} 완료: 수집 {collected}건 / 전체 {count_recorded}건", "", region)
    except KeyboardInterrupt:
        log("WARN", "사용자 중단 — 지금까지 결과는 보존됨")
    finally:
        crawler.close()

    # search_counts.csv: 지역×직무군 수집량 + 지역 전체건수(공식, 직무별은 미제공이라 지역값)
    write_search_counts(region_totals)
    print(f"\n완료. 신규 수집 {total_new}건 → {C.JOBS_CSV}")
    print("검증: python src/validate_dataset.py")


def write_search_counts(region_totals):
    """
    jobs.csv를 읽어 지역×직무군 collected_count를 집계하고 search_counts.csv를 재생성.
    - search_total_count: 지역 전체건수(_SearchCount, 공식값). 직무별 사이트건수는 미제공 → 지역값을 표기.
    - 직무군별 행 + 지역합계(job_group='전체') 행을 함께 기록.
    """
    from collections import Counter
    rows = read_all_jobs()
    grid = Counter((r.get("region", ""), r.get("job_group", "")) for r in rows)
    today = dt.date.today().isoformat()
    # 헤더부터 새로 기록
    with open(C.SEARCH_COUNTS_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(C.SEARCH_COUNTS_COLUMNS)
        for region, total in region_totals.items():
            # 지역 합계 행
            region_collected = sum(n for (rg, _), n in grid.items() if rg == region)
            w.writerow([region, "전체", "", total, region_collected, today, C.SOURCE_NAME])
            # 직무군별 행(미분류 포함)
            for jg in C.JOB_GROUP_NAMES + ["미분류"]:
                w.writerow([region, jg, "", total, grid.get((region, jg), 0), today, C.SOURCE_NAME])


if __name__ == "__main__":
    main()
