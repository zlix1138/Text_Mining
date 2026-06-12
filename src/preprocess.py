# -*- coding: utf-8 -*-
"""
전처리/표준화 모듈.
- 지역/직무군/고용형태/경력 표준화, 임금 정제, 텍스트 정제(raw_text), 청년친화성, 중복 처리.
- 직무군은 사이트 필터가 없어 제목+직무명+본문 키워드로 사후 분류한다(미분류 시 note).
"""

import re
import html as _html

import constants as C


# ── 텍스트 정제 ──────────────────────────────────────────────────────────────
def clean_text(text):
    """HTML 태그 제거 → 엔티티 해제 → 공백/특수문자 정리."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[•▶■●◆※★☆▲▽]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_raw_text(title, task, qualification, preference, benefits):
    """제목+주요업무+자격요건+우대사항+복리후생 → 분석용 raw_text."""
    parts = [title, task, qualification, preference, benefits]
    return clean_text(" ".join(p for p in parts if p))


# ── 지역 표준화 ──────────────────────────────────────────────────────────────
def standardize_region(region_detail):
    """상세주소 접두를 분석 지역명으로 매핑(매칭 실패 시 '')."""
    rd = (region_detail or "").strip()
    for prefix, region in C.REGION_PREFIX_MAP.items():
        if rd.startswith(prefix):
            return region
    return ""


# ── 직무군 사후 분류 ────────────────────────────────────────────────────────
def _normalize_for_classify(text):
    """분류 오탐 방지: 고용형태·채용 상투어 제거(예: '무기계약직'의 '기계' 오매칭, '교육 프로그램' 등)."""
    text = (text or "").lower()
    for noise in ["무기계약직", "무기계약", "계약직", "정규직", "인턴", "신입", "경력사원",
                  "채용공고", "채용", "모집", "수시", "공채", "교육 프로그램", "복리후생"]:
        text = text.replace(noise, " ")
    return text


def _best_match(text):
    """키워드 매칭 수가 가장 많은 직무군 반환((group, keyword, hits) 또는 (None,'',0))."""
    best_group, best_hits, best_kw = None, 0, ""
    for group, cfg in C.JOB_GROUPS.items():
        hits = [kw for kw in cfg["keywords"] if kw in text]
        if len(hits) > best_hits:
            best_group, best_hits, best_kw = group, len(hits), hits[0]
    return best_group, best_kw, best_hits


def classify_job_group(title, job_category_raw="", body_text=""):
    """
    5개 직무군 사후 분류. 정밀도를 위해 2단계:
      1차) 제목+직무명(권위 소스) 매칭 → 1개라도 매칭되면 채택(짧고 정밀)
      2차) 1차 실패 시에만 본문 키워드 매칭 — 단, 본문은 노이즈가 많아 '2개 이상' 매칭만 채택
    반환: (job_group, job_keyword, note)
    """
    primary = _normalize_for_classify(" ".join([title or "", job_category_raw or ""]))
    g, kw, _ = _best_match(primary)
    if g:
        return g, kw, ""
    body = _normalize_for_classify(body_text)
    g, kw, hits = _best_match(body)
    if g and hits >= 2:                      # 본문 단일 키워드 오탐 방지
        return g, kw, "본문 기반 분류(제목 미매칭)"
    return "미분류", "", "직무군 키워드 미매칭(사후 분류 실패)"


# ── 고용형태 표준화 ──────────────────────────────────────────────────────────
def standardize_employment_type(raw):
    """원문 고용형태 → 표준 카테고리(정규직/계약직/인턴/파견직/프리랜서/기타)."""
    r = (raw or "")
    if "정규" in r:
        return "정규직"
    if "인턴" in r or "전환형" in r:
        return "인턴"
    if "파견" in r:
        return "파견직"
    if "프리랜" in r:
        return "프리랜서"
    if "계약" in r or "촉탁" in r or "기간제" in r:
        return "계약직"
    return "기타" if r else ""


# ── 경력 표준화 ──────────────────────────────────────────────────────────────
def standardize_career(raw):
    """원문 경력 → 표준 카테고리(신입/경력무관/1년 이하/1~3년/3년 초과/기타·미상)."""
    r = (raw or "").replace(" ", "")
    if not r:
        return "기타/미상"
    if "경력무관" in r or "무관" in r:
        return "경력무관"
    # 'N년' 숫자 추출
    nums = [int(n) for n in re.findall(r"(\d+)\s*년", r)]
    has_new = "신입" in r
    if nums:
        mn = min(nums)
        if mn <= 1:
            cat = "1년 이하"
        elif mn <= 3:
            cat = "1~3년"
        else:
            cat = "3년 초과"
        # '신입·경력N년'처럼 신입 포함이면 신입 우선 표기 가능하나, 경력 구간을 유지
        return cat
    if has_new:
        return "신입"
    return "기타/미상"


# ── 임금 정제 ────────────────────────────────────────────────────────────────
def parse_salary(raw):
    """
    임금 원문 → (salary_type, salary_min, salary_max).
    - 연봉/월급/시급/회사내규/면접후결정/비공개 구분.
    - 숫자 정제 가능 시 만원 단위 정수로 min/max(연봉 기준). 협의/비공개는 빈 값.
    """
    r = (raw or "").strip()
    if not r:
        return "", "", ""
    low = r.replace(" ", "")
    if "내규" in low:
        return "회사내규", "", ""
    if "면접" in low and ("후" in low or "결정" in low):
        return "면접후결정", "", ""
    if "협의" in low or "비공개" in low or "추후" in low:
        return "비공개", "", ""

    salary_type = ""
    if "시급" in low:
        salary_type = "시급"
    elif "월급" in low or "월" in low:
        salary_type = "월급"
    elif "연봉" in low or "만원" in low:
        salary_type = "연봉"

    # 숫자 구간 추출: '3,000~4,000만원' / '3000만원' 등
    nums = re.findall(r"([\d,]{2,})\s*만", low)
    vals = [int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit()]
    if vals:
        smin = min(vals)
        smax = max(vals)
        return (salary_type or "연봉"), smin, smax
    return (salary_type or ""), "", ""


# ── 청년 친화성 ──────────────────────────────────────────────────────────────
def is_youth_friendly(career, employment_type, raw_text):
    """신입가능/경력무관/채용전환/인턴/교육제공 등 신호가 있으면 1, 없으면 0."""
    blob = " ".join([career or "", employment_type or "", raw_text or ""])
    return 1 if any(sig in blob for sig in C.YOUTH_FRIENDLY_SIGNALS) else 0


def eligibility_note(career_std, title, raw_text=""):
    """
    청년 부적합(senior-only) 여부를 '삭제하지 않고' note 사유로만 표시(분석 단계 필터용).
    - 경력 '3년 초과'이고 신입/경력무관 신호가 없으면 → 경력 부적합 표시.
    - 제목에 임원·관리자급 신호가 있으면 → 직급 부적합 표시.
    반환: note 문자열(해당 없으면 '').
    """
    notes = []
    blob = (title or "") + " " + (raw_text or "")
    has_entry = any(sig in blob for sig in ["신입", "경력무관"])
    if career_std == "3년 초과" and not has_entry:
        notes.append("경력 3년 초과(청년 부적합 가능)")
    low = (title or "").lower()
    if any(sig in low for sig in C.SENIOR_TITLE_SIGNALS):
        notes.append("관리자·임원급(청년 부적합 가능)")
    return " | ".join(notes)


# ── 중복 처리 ────────────────────────────────────────────────────────────────
def dedupe_rows(rows):
    """
    1차: url 기준 중복 제거.
    2차: company_name+title+region 기준 중복 가능성은 삭제하지 않고 note에 표시.
    반환: 정제된 rows(list[dict]).
    """
    seen_url = set()
    seen_key = {}
    out = []
    for row in rows:
        url = row.get("url", "")
        if url and url in seen_url:
            continue   # 1차 중복 제거
        seen_url.add(url)
        key = (row.get("company_name", ""), row.get("title", ""), row.get("region", ""))
        if key in seen_key and all(key):
            note = row.get("note", "")
            row["note"] = (note + " | 2차중복가능(회사+제목+지역)").strip(" |")
        else:
            seen_key[key] = url
        out.append(row)
    return out
