# -*- coding: utf-8 -*-
"""
전처리 심화
jobs.csv(수집 원본)를 읽어 텍스트마이닝·스코어링에 바로 쓸 수 있도록 가공하여
data/jobs_clean.csv를 생성한다(원본 컬럼 보존 + 파생 컬럼 추가).

추가 작업:
  1) 텍스트 정제 심화: 보일러플레이트·이모지·연락처 제거, 공백 정리 → text_clean
  2) 한국어 형태소 분석(kiwipiepy) → 명사 추출 + 불용어 제거 → nouns
  3) 임금 숫자화/공개여부, 경력 연수화, 마감일 정규화
  4) 8개 스코어링 차원 키워드 피처(이진/카운트) + 고용안정(정규직) 피처
  5) 제외·품질 플래그(상세내용 부족/공공기관/2차중복)

실행: python src/build_clean.py
"""

import csv
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C

JOBS_CLEAN_CSV = C.DATA_DIR / "jobs_clean.csv"

# 파생 컬럼(원본 JOBS_COLUMNS 뒤에 추가)
DERIVED_COLUMNS = [
    "text_clean", "nouns",
    "salary_disclosed", "career_min_year", "career_max_year",
    "deadline_norm", "deadline_type",
    "feat_wage", "feat_work_time", "feat_welfare", "feat_growth",
    "feat_youth_friendly", "feat_employment_stability",
    "flag_low_content", "flag_exclude_public", "flag_dup2",
]
CLEAN_COLUMNS = C.JOBS_COLUMNS + DERIVED_COLUMNS

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")


def clean_text_deep(text):
    """보일러플레이트·이모지·연락처(개인정보) 제거 + 공통 푸터 절단 후 정제한 분석용 텍스트."""
    t = text or ""
    # 본문 뒤 공통 푸터 절단 — 본문 확보 위치(MIN_POS) 이후 가장 먼저 등장하는 마커에서 자름
    cut = len(t)
    for marker in C.FOOTER_CUT_MARKERS:
        idx = t.find(marker)
        if C.FOOTER_CUT_MIN_POS <= idx < cut:
            cut = idx
    t = t[:cut]
    for pat in C.BOILERPLATE_PATTERNS:
        t = re.sub(pat, " ", t)
    t = _EMAIL.sub(" ", t)          # 윤리: 본문에 섞인 이메일 제거
    t = _PHONE.sub(" ", t)          # 윤리: 전화번호 제거
    t = _EMOJI.sub(" ", t)
    t = re.sub(r"[^\w가-힣\s]", " ", t)   # 특수문자 정리(한글/영숫자/공백만)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def extract_nouns(kiwi, text):
    """kiwipiepy로 명사(NNG/NNP) 추출 → 불용어·1글자·숫자 제거 → 공백조인."""
    if not text:
        return ""
    out = []
    for tok in kiwi.tokenize(text):
        if tok.tag in ("NNG", "NNP", "SL"):      # 일반/고유명사 + 영문
            w = tok.form.strip()
            if len(w) >= 2 and w not in C.STOPWORDS and not w.isdigit():
                out.append(w)
    return " ".join(out)


def career_years(career_std):
    """표준 경력 카테고리 → (최소, 최대) 연수. 미상/무관은 빈 값."""
    return {
        "신입": (0, 0), "1년 이하": (0, 1), "1~3년": (1, 3), "3년 초과": (3, ""),
        "경력무관": ("", ""), "기타/미상": ("", ""),
    }.get(career_std, ("", ""))


def normalize_deadline(raw):
    """마감일 → (정규화값, 유형). YYYY-MM-DD / MM/DD / 상시 등."""
    r = (raw or "").strip()
    if not r:
        return "", ""
    if "상시" in r:
        return "상시채용", "상시"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", r)        # validThrough(Tier-2)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "마감일"
    m = re.match(r"(\d{2})/(\d{2})", r)                 # 목록 MM/DD(Tier-1) — 연도 2026 가정
    if m:
        return f"2026-{m.group(1)}-{m.group(2)}", "마감일(근사)"
    return r, "기타"


def kw_count(text, keywords):
    """텍스트 내 키워드 매칭 수(차원 피처)."""
    low = (text or "").lower().replace(" ", "")
    return sum(1 for kw in keywords if kw.lower().replace(" ", "") in low)


def main():
    if not C.JOBS_CSV.exists():
        print("jobs.csv 없음 — 먼저 수집을 실행하세요.")
        return
    from kiwipiepy import Kiwi
    kiwi = Kiwi()

    rows = list(csv.DictReader(open(C.JOBS_CSV, encoding=C.CSV_ENCODING)))
    print(f"입력 {len(rows)}건 전처리 심화 시작...")

    out_rows = []
    for i, r in enumerate(rows):
        # 1) 텍스트 정제 + 토큰화
        text_clean = clean_text_deep(r.get("raw_text", ""))
        nouns = extract_nouns(kiwi, text_clean)

        # 2) 임금 공개여부
        salary_disclosed = 1 if (r.get("salary_min") or r.get("salary_max")) else 0

        # 3) 경력 연수
        cmin, cmax = career_years(r.get("career", ""))

        # 4) 마감일 정규화
        dl_norm, dl_type = normalize_deadline(r.get("deadline", ""))

        # 5) 8개 차원 키워드 피처(+고용안정)
        feat = {f"feat_{k}": kw_count(text_clean, kws) for k, kws in
                {"wage": C.SCORE_KEYWORDS["wage"], "work_time": C.SCORE_KEYWORDS["work_time"],
                 "welfare": C.SCORE_KEYWORDS["welfare"], "growth": C.SCORE_KEYWORDS["growth"],
                 "youth_friendly": C.SCORE_KEYWORDS["youth_friendly"]}.items()}
        feat_stability = 1 if r.get("employment_type") == "정규직" else 0

        # 6) 플래그
        flag_low = 1 if len(text_clean) < C.LOW_CONTENT_MIN_LEN else 0
        co_ti = (r.get("company_name", "") + " " + r.get("title", ""))
        flag_pub = 1 if any(s in co_ti for s in C.EXCLUDE_PUBLIC_SIGNALS) else 0
        flag_dup2 = 1 if "2차중복" in r.get("note", "") else 0

        new = dict(r)
        new.update({
            "text_clean": text_clean, "nouns": nouns,
            "salary_disclosed": salary_disclosed,
            "career_min_year": cmin, "career_max_year": cmax,
            "deadline_norm": dl_norm, "deadline_type": dl_type,
            "feat_wage": feat["feat_wage"], "feat_work_time": feat["feat_work_time"],
            "feat_welfare": feat["feat_welfare"], "feat_growth": feat["feat_growth"],
            "feat_youth_friendly": feat["feat_youth_friendly"],
            "feat_employment_stability": feat_stability,
            "flag_low_content": flag_low, "flag_exclude_public": flag_pub,
            "flag_dup2": flag_dup2,
        })
        out_rows.append(new)
        if (i + 1) % 1000 == 0:
            print(f"  진행 {i+1}/{len(rows)}")

    with open(JOBS_CLEAN_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(CLEAN_COLUMNS)
        for r in out_rows:
            w.writerow([r.get(c, "") for c in CLEAN_COLUMNS])

    # 요약
    n = len(out_rows)
    import statistics
    print(f"\n완료 → {JOBS_CLEAN_CSV}  ({n}건, {len(CLEAN_COLUMNS)}컬럼)")
    print(f"  nouns 평균 토큰수: {statistics.mean(len(r['nouns'].split()) for r in out_rows):.1f}")
    print(f"  임금 공개: {sum(r['salary_disclosed'] for r in out_rows)}건")
    print(f"  정규직(고용안정): {sum(r['feat_employment_stability'] for r in out_rows)}건")
    for k in ["feat_wage", "feat_work_time", "feat_welfare", "feat_growth", "feat_youth_friendly"]:
        print(f"  {k}>0: {sum(1 for r in out_rows if r[k] > 0)}건")
    print(f"  상세내용 부족 플래그: {sum(r['flag_low_content'] for r in out_rows)}건 | "
          f"공공기관 플래그: {sum(r['flag_exclude_public'] for r in out_rows)}건")


if __name__ == "__main__":
    main()
