# -*- coding: utf-8 -*-
"""
사람인(Saramin) 수집 오케스트레이션.
잡코리아 산출물(data/jobs.csv 등)은 절대 건드리지 않고, 사람인 전용 파일만 사용한다.
  - data/saramin_jobs_raw.csv           (원천/중간 수집; 컬럼=constants.JOBS_COLUMNS)
  - data/saramin_collection_summary.csv (지역×직무군×키워드 요약)
  - data/saramin_crawl_log.csv          (모든 이벤트)
  - data/saramin_failures.csv           (공고 단위 실패)

흐름(지역 × 직무군 × 검색키워드):
  1) 검색목록 1페이지로 전체 검색건수(search_total_count) 확보
  2) 검색목록 페이지네이션으로 공고 목록 수집(중복 rec_idx 제외)
  3) 상세 팝업(robots Allow)에서 요약/본문 파싱 → 공통 전처리(preprocess 재사용)
  4) 행을 saramin_jobs_raw.csv에 append(중간 저장)
  5) 헤드헌팅 공고는 robots 준수로 상세 미수집(목록 기반 행만 보존·note 표시)
  6) 실패는 saramin_failures.csv, 이벤트는 saramin_crawl_log.csv

CLI 예:
  python src/main_saramin.py --regions 서울 --limit 5
  python src/main_saramin.py --regions 서울 경기도 --per-combo 10
  python src/main_saramin.py            # 전체 지역×직무군 기본 수집
"""

import argparse
import csv
import datetime as dt
import os
import random
import sys
import time

# Windows 콘솔(cp949) 한글 출력 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants as C
import constants_saramin as CS
import preprocess as PP
import parser as P                      # parse_playwright_body(본문 텍스트 섹션 분할) 재사용
import parser_saramin as PS
from crawler_saramin import SaraminCrawler, BlockedError


# ── CSV 입출력 헬퍼 ──────────────────────────────────────────────────────────
def _ensure_csv(path, columns):
    if not path.exists():
        with open(path, "w", newline="", encoding=C.CSV_ENCODING) as f:
            csv.writer(f).writerow(columns)


def append_row(path, columns, row):
    _ensure_csv(path, columns)
    with open(path, "a", newline="", encoding=C.CSV_ENCODING) as f:
        csv.writer(f).writerow([row.get(c, "") for c in columns])


def load_existing_urls():
    """재실행 이어받기: 이미 수집한 url 집합."""
    urls = set()
    if CS.SARAMIN_RAW_CSV.exists():
        with open(CS.SARAMIN_RAW_CSV, encoding=C.CSV_ENCODING) as f:
            for r in csv.DictReader(f):
                if r.get("url"):
                    urls.add(r["url"])
    return urls


def make_logger():
    _ensure_csv(CS.SARAMIN_CRAWL_LOG_CSV, CS.CRAWL_LOG_COLUMNS)

    def log(level, message, url="", region="", job_group=""):
        ts = dt.datetime.now().isoformat(timespec="seconds")
        append_row(CS.SARAMIN_CRAWL_LOG_CSV, CS.CRAWL_LOG_COLUMNS,
                   {"timestamp": ts, "level": level, "message": message,
                    "url": url, "region": region, "job_group": job_group})
        if level in ("ERROR", "WARN", "INFO"):
            print(f"[{level}] {message}" + (f" ({region})" if region else ""))
    return log


def record_failure(url, region, job_group, err_type, err_msg):
    append_row(CS.SARAMIN_FAILURES_CSV, CS.FAILURES_COLUMNS, {
        "url": url, "region": region, "job_group": job_group,
        "error_type": err_type, "error_message": str(err_msg)[:200],
        "collected_date": dt.date.today().isoformat(),
    })


# ── 행 빌드(목록 + 상세 → 공통 스키마) ───────────────────────────────────────
def _segment_body(body_text):
    """본문 텍스트를 섹션 분할(잡코리아 parser.parse_playwright_body 재사용)."""
    if not body_text:
        return {}
    try:
        return P.parse_playwright_body(body_text)
    except Exception:
        return {}


def build_row(posting, detail, region_std, search_total_count, log):
    """목록 행 + 상세 dict → saramin_jobs_raw.csv 행(dict). 공통 전처리 재사용."""
    today = dt.date.today().isoformat()
    base = {c: "" for c in CS.RAW_COLUMNS}
    detail = detail or {}

    title = detail.get("title") or posting.get("title", "")
    company = detail.get("company_name") or posting.get("company_name", "")
    region_detail = detail.get("region_detail") or posting.get("region_cell", "")
    job_category_raw = posting.get("job_category_raw", "")

    # 본문 섹션 분할(주요업무는 본문에서, 자격/우대/복지는 요약 dl 우선)
    body_text = detail.get("body_text", "")
    seg = _segment_body(body_text)
    task = seg.get("task_description", "")
    qualification = detail.get("qualification") or seg.get("qualification", "")
    preference = detail.get("preference") or seg.get("preference", "")
    benefits = detail.get("benefits") or seg.get("benefits", "")
    if seg.get("job_category") and not job_category_raw:
        job_category_raw = seg["job_category"]

    # 직무군 사후 분류(제목+직종+본문)
    job_group, job_kw, jg_note = PP.classify_job_group(
        title, job_category_raw, " ".join([task, qualification]))

    # 경력/학력/고용형태/급여 표준화
    career_raw = detail.get("career") or posting.get("career_raw", "")
    career = PP.standardize_career(career_raw)
    education = detail.get("education") or posting.get("education", "")
    emp = PP.standardize_employment_type(detail.get("employment_type_raw")
                                         or posting.get("employment_raw", ""))
    salary_raw = detail.get("salary", "")
    s_type, s_min, s_max = PP.parse_salary(salary_raw)

    raw_text = PP.build_raw_text(title, task, qualification, preference, benefits)
    youth = PP.is_youth_friendly(career_raw, emp, raw_text)

    # ── note 플래그(삭제하지 않고 보존) ──
    notes = []
    if jg_note:
        notes.append(jg_note)
    elig = PP.eligibility_note(career, title, raw_text)
    if elig:
        notes.append(elig)
    if posting.get("is_headhunting") or detail.get("is_headhunting"):
        notes.append("헤드헌팅 비공개 가능")
    if any(sig in company for sig in C.EXCLUDE_PUBLIC_SIGNALS):
        notes.append("공공기관 중심 공고 가능")
    blob_for_alba = " ".join([title, job_category_raw])
    if any(sig in blob_for_alba for sig in C.EXCLUDE_SIGNALS):
        notes.append("아르바이트·단기·행사성 가능")
    if ("전국" in region_detail or "해외" in region_detail) and not PP.standardize_region(region_detail):
        notes.append("근무지 전국/해외만 표시")
    low_content = len(raw_text) < C.LOW_CONTENT_MIN_LEN
    if low_content:
        notes.append("상세내용 부족(저정보)")

    detail_status = ("skipped_headhunting" if posting.get("is_headhunting")
                     else ("done" if detail else "listing_only"))
    if detail and not detail.get("is_headhunting"):
        notes.append("상세 수집 완료")
    elif not detail and not posting.get("is_headhunting"):
        notes.append("목록 기반(상세 미수집)")

    base.update({
        "source": CS.SOURCE_NAME, "collected_date": today, "url": posting["url"],
        "company_name": company, "title": title,
        "region": region_std, "region_detail": region_detail,
        "job_group": job_group, "job_keyword": job_kw, "job_category_raw": job_category_raw,
        "career": career, "education": education, "employment_type": emp,
        "salary": salary_raw, "salary_min": s_min, "salary_max": s_max, "salary_type": s_type,
        "work_time": detail.get("work_time", ""), "benefits": benefits,
        "task_description": task, "qualification": qualification, "preference": preference,
        "deadline": detail.get("deadline") or posting.get("deadline_raw", ""),
        "search_total_count": search_total_count if search_total_count is not None else "",
        "raw_text": raw_text, "is_youth_friendly": youth,
        "crawl_status": "success",
        "note": " | ".join(notes),
        "detail_status": detail_status,
        "tier2_backfilled": 1 if (detail and not posting.get("is_headhunting")) else 0,
    })
    base["_low_content"] = low_content   # 요약 집계용(임시; CSV엔 미기록)
    return base


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="사람인 청년 일자리 데이터 수집(잡코리아와 분리)")
    ap.add_argument("--regions", nargs="*", default=None,
                    help="수집 지역명(미지정 시 표준 10개 지역 전체)")
    ap.add_argument("--job-groups", nargs="*", default=None,
                    help="수집 직무군(미지정 시 5개 직무군 전체)")
    ap.add_argument("--keywords", nargs="*", default=None,
                    help="직무군 기본 키워드 대신 사용할 검색 키워드(스모크용)")
    ap.add_argument("--per-combo", type=int, default=CS.DEFAULT_PER_COMBO,
                    help="지역×키워드 1조합당 상세 수집 목표")
    ap.add_argument("--limit", type=int, default=None,
                    help="(스모크) 지역×키워드 1조합당 수집 상한")
    ap.add_argument("--max-pages", type=int, default=CS.MAX_PAGES_PER_COMBO,
                    help="지역×키워드 1조합당 목록 페이지 상한")
    ap.add_argument("--no-detail", action="store_true",
                    help="상세 팝업 미수집(목록 기반만 — 초고속 점검용)")
    args = ap.parse_args()

    log = make_logger()

    # 지역 매핑
    regions = {}
    for name in (args.regions or list(CS.SARAMIN_REGIONS.keys())):
        if name in CS.SARAMIN_REGIONS:
            regions[name] = CS.SARAMIN_REGIONS[name]
        else:
            log("WARN", f"알 수 없는 지역명 무시: {name}")

    # 직무군 → 검색키워드 매핑
    if args.keywords:
        combos = [("(검색)", kw) for kw in args.keywords]   # 직무군 미지정 키워드 직접검색
    else:
        groups = args.job_groups or list(CS.SARAMIN_JOB_QUERIES.keys())
        combos = []
        for g in groups:
            if g not in CS.SARAMIN_JOB_QUERIES:
                log("WARN", f"알 수 없는 직무군 무시: {g}")
                continue
            for kw in CS.SARAMIN_JOB_QUERIES[g]:
                combos.append((g, kw))

    # 산출물(빈 결과여도 헤더 보장)
    _ensure_csv(CS.SARAMIN_RAW_CSV, CS.RAW_COLUMNS)
    _ensure_csv(CS.SARAMIN_FAILURES_CSV, CS.FAILURES_COLUMNS)
    _ensure_csv(CS.SARAMIN_SUMMARY_CSV, CS.SUMMARY_COLUMNS)

    crawler = SaraminCrawler(logger=log)
    existing = load_existing_urls()
    target = args.limit or args.per_combo
    total_new = 0
    summary_rows = []

    try:
        for region, loc in regions.items():
            for job_group, keyword in combos:
                seen = set()
                # (1) 전체 검색건수 + 1페이지 재사용
                try:
                    total_count, first_html = crawler.fetch_search_count(
                        keyword, loc, region, job_group)
                except BlockedError as e:
                    log("ERROR", f"차단 감지 — 즉시 중단: {e}", "", region, job_group)
                    raise
                if total_count is None:
                    log("WARN", f"검색건수 파싱 실패(빈값 처리): {region}/{keyword}", "", region, job_group)
                log("INFO", f"{region} × {job_group}[{keyword}] 전체={total_count}",
                    "", region, job_group)

                collected = success = failed = low_content = 0
                try:
                    for posting in crawler.iter_listings(
                            keyword, loc, region, job_group,
                            max_pages=args.max_pages, first_page_html=first_html, seen=seen):
                        if collected >= target:
                            break
                        if posting["url"] in existing:
                            continue
                        # (3) 상세 — 헤드헌팅은 robots 준수로 미수집
                        detail = None
                        if not args.no_detail and not posting["is_headhunting"]:
                            try:
                                html = crawler.fetch_detail(
                                    posting["rec_idx"], region, job_group)
                                if html:
                                    detail = PS.parse_detail(html)
                                else:
                                    log("WARN", "상세 응답 없음(목록기반 보존)",
                                        posting["url"], region, job_group)
                            except BlockedError:
                                raise
                            except Exception as e:
                                record_failure(posting["url"], region, job_group, "detail", e)
                                log("WARN", f"상세 처리 예외(목록기반 보존): {e}",
                                    posting["url"], region, job_group)
                        # (4) 행 빌드·저장(공고 단위 예외 격리)
                        try:
                            row = build_row(posting, detail, region, total_count, log)
                        except Exception as e:
                            failed += 1
                            record_failure(posting["url"], region, job_group, "process", e)
                            log("WARN", f"공고 처리 예외: {e}", posting["url"], region, job_group)
                            continue
                        lc = row.pop("_low_content", False)
                        append_row(CS.SARAMIN_RAW_CSV, CS.RAW_COLUMNS, row)
                        existing.add(posting["url"])
                        collected += 1
                        total_new += 1
                        if detail is not None:
                            success += 1
                        if lc:
                            low_content += 1
                        time.sleep(random.uniform(0.4, 0.9))   # 상세 간 추가 간격(예절)
                except BlockedError as e:
                    log("ERROR", f"차단 감지 — 즉시 중단: {e}", "", region, job_group)
                    raise

                summary_rows.append({
                    "region": region, "job_group": job_group, "job_keyword": keyword,
                    "search_total_count": total_count if total_count is not None else "",
                    "collected_count": collected, "success_count": success,
                    "failed_count": failed, "low_content_count": low_content,
                    "source": CS.SOURCE_NAME,
                })
                log("INFO", f"{region} × {job_group}[{keyword}] 수집 {collected}건 "
                    f"(상세성공 {success}, 실패 {failed}, 저정보 {low_content})",
                    "", region, job_group)
    except BlockedError:
        log("ERROR", "차단/접근제한으로 수집을 중단했습니다. 잠시 후 재시도하세요.")
    except KeyboardInterrupt:
        log("WARN", "사용자 중단 — 지금까지 결과는 보존됨")
    finally:
        crawler.close()

    # 요약 파일 재기록(헤더부터)
    with open(CS.SARAMIN_SUMMARY_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(CS.SUMMARY_COLUMNS)
        for r in summary_rows:
            w.writerow([r.get(c, "") for c in CS.SUMMARY_COLUMNS])

    print(f"\n완료. 신규 수집 {total_new}건 → {CS.SARAMIN_RAW_CSV}")
    print("검증: python src/validate_saramin.py")


if __name__ == "__main__":
    main()
