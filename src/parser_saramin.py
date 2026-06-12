# -*- coding: utf-8 -*-
"""
사람인(Saramin) HTML 파싱 모듈.
- 검색목록(/zf_user/search/recruit) → 공고 행(rec_idx/URL/제목/회사/요약셀/직종/마감) + 전체 검색건수
- 상세 팝업(/zf_user/jobs/view/popup) → 요약 dl(경력/학력/근무형태/급여/근무시간/근무지역/자격요건/우대사항/복리후생)
  + 본문(.user_content) 텍스트
모든 함수는 실패 시 예외를 던지지 않고 가능한 범위까지 파싱해 부분 결과를 돌려준다.
개인정보(담당자/연락처/이메일)는 추출하지 않는다. 원문 HTML 전체는 저장하지 않는다.
"""

import re
import html as _html

from bs4 import BeautifulSoup


def _clean(text):
    """HTML 엔티티 해제 + 공백 정리."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _strip_deadline_suffix(title):
    """제목 끝에 붙는 ' ~ MM/DD(요일)' 마감 표기를 제거."""
    return re.sub(r"\s*~\s*\d{1,2}/\d{1,2}.*$", "", title or "").strip()


# ── 검색목록 ─────────────────────────────────────────────────────────────────
def parse_search_count(html_text):
    """검색 결과 전체 건수(search_total_count)를 int로 반환(실패 시 None)."""
    soup = BeautifulSoup(html_text, "lxml")
    node = soup.select_one(".cnt_result")
    if not node:
        return None
    digits = re.sub(r"[^\d]", "", node.get_text())
    return int(digits) if digits else None


def _detect_headhunting(item):
    """목록 아이템이 헤드헌팅 공고인지 best-effort 판별(robots상 상세 미수집 대상)."""
    cls = " ".join(item.get("class", []))
    if "headhunt" in cls.lower():
        return True
    txt = item.get_text(" ", strip=True)
    if "헤드헌팅" in txt or "헤드헌터" in txt:
        return True
    # 상세 링크에 headhunting 캠페인 파라미터가 있으면 헤드헌팅
    for a in item.select("a[href]"):
        if "headhuntingView" in (a.get("href") or ""):
            return True
    return False


def parse_listing_rows(html_text):
    """
    검색목록 HTML → 공고 행(dict) 리스트.
    각 행: rec_idx, url(상세 팝업), title, company_name, region_cell,
           career_raw, education, employment_raw, job_category_raw, deadline_raw, is_headhunting
    셀 위치가 가변적이라 .job_condition span을 패턴으로 분류한다.
    """
    soup = BeautifulSoup(html_text, "lxml")
    rows = []
    for it in soup.select(".item_recruit"):
        rec = it.get("value") or ""
        if not rec.isdigit():
            # value가 없으면 scrap 버튼 rec_idx 폴백
            sb = it.select_one("[rec_idx]")
            rec = (sb.get("rec_idx") if sb else "") or ""
        if not rec.isdigit():
            continue

        a_tit = it.select_one(".job_tit a")
        title = _strip_deadline_suffix(_clean(a_tit.get("title") if a_tit and a_tit.get("title")
                                              else (a_tit.get_text(" ", strip=True) if a_tit else "")))
        co = it.select_one(".corp_name a") or it.select_one(".corp_name")
        company = _clean(co.get_text(" ", strip=True)) if co else ""

        # 근무지역: .job_condition 첫 span(지역 링크들)
        region_cell = ""
        cond_spans = it.select(".job_condition span")
        if cond_spans:
            locs = [a.get_text(strip=True) for a in cond_spans[0].select("a")]
            region_cell = " ".join(locs) if locs else _clean(cond_spans[0].get_text(" ", strip=True))

        # 나머지 조건 셀(경력/학력/고용형태)을 패턴으로 분류
        career_raw = education = employment_raw = ""
        for sp in cond_spans[1:]:
            t = _clean(sp.get_text(" ", strip=True))
            if not t:
                continue
            if re.search(r"정규직|계약직|인턴|파견|프리랜|위촉|기간제", t) and not employment_raw:
                employment_raw = t
            elif re.search(r"신입|경력|무관", t) and not career_raw:
                career_raw = t
            elif re.search(r"졸|학력", t) and not education:
                education = t

        # 직종(.job_sector) → job_category_raw (분류 정확도 향상)
        sectors = [a.get_text(strip=True) for a in it.select(".job_sector a")]
        job_category_raw = ", ".join(s for s in sectors if s)[:120]

        # 마감일(.job_date .date) — '~ MM/DD(요일)' 또는 '상시채용' 등
        d = it.select_one(".job_date .date")
        deadline_raw = _clean(d.get_text(" ", strip=True)) if d else ""

        rows.append({
            "rec_idx": rec,
            "url": f"https://www.saramin.co.kr/zf_user/jobs/view/popup?rec_idx={rec}",
            "title": title,
            "company_name": company,
            "region_cell": region_cell,
            "career_raw": career_raw,
            "education": education,
            "employment_raw": employment_raw,
            "job_category_raw": job_category_raw,
            "deadline_raw": deadline_raw,
            "is_headhunting": _detect_headhunting(it),
        })
    return rows


# ── 상세 팝업 ────────────────────────────────────────────────────────────────
_DETAIL_LABELS = {
    "경력": "career", "학력": "education", "근무형태": "employment", "고용형태": "employment",
    "급여": "salary", "근무일시": "work_time", "근무시간": "work_time",
    "근무지역": "region_detail", "근무지": "region_detail",
    "자격요건": "qualification", "우대사항": "preference",
    "복리후생": "benefits", "복지": "benefits",
}

# dd 텍스트에서 제거할 사이트 UI 상투어(토글/링크 라벨)
_DD_NOISE = ["상세보기", "지도보기", "닫기", "근무형태 상세", "자격요건 상세", "우대사항 상세"]


def _clean_dd(label, dd_text):
    """요약 dd 값에서 라벨 반복·토글 UI 텍스트를 제거."""
    t = _clean(dd_text)
    for noise in _DD_NOISE:
        t = t.replace(noise, " ")
    # 라벨이 값 앞에 반복되는 경우 제거(예: '자격요건 • ...')
    if t.startswith(label):
        t = t[len(label):]
    return _clean(t)


def _parse_deadline(soup):
    """접수기간 영역에서 마감일을 추출('상시채용'/'채용시 마감'도 보존)."""
    node = soup.select_one(".info_period")
    if not node:
        return ""
    txt = _clean(node.get_text(" ", strip=True))
    for kw in ("상시채용", "채용시", "채용 시", "수시채용", "충원시"):
        if kw in txt:
            return kw.replace(" ", "")
    m = re.search(r"마감일\s*([\d]{4}[.\-/][\d]{1,2}[.\-/][\d]{1,2})", txt)
    return m.group(1) if m else ""


def parse_detail(html_text):
    """
    상세 팝업 HTML → 필드 dict.
    반환 키: company_name, title, employment_type_raw, career, education, salary,
            work_time, deadline, region_detail, task_description, qualification,
            preference, benefits, body_text, is_headhunting
    개인정보는 추출하지 않는다(요약 dl + 본문 텍스트만 사용).
    """
    soup = BeautifulSoup(html_text, "lxml")

    # 제목 / 회사
    t = soup.select_one(".tit_job") or soup.select_one(".wrap_jv_header .tit")
    title = _strip_deadline_suffix(_clean(t.get_text(" ", strip=True))) if t else ""
    co = (soup.select_one(".company a") or soup.select_one(".corp_name a")
          or soup.select_one(".corp_name") or soup.select_one(".company_nm"))
    company = _clean(co.get_text(" ", strip=True)) if co else ""

    # 요약 dl(라벨→값) 매핑
    fields = {}
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not (dt and dd):
            continue
        label = _clean(dt.get_text(" ", strip=True))
        key = None
        for lab, k in _DETAIL_LABELS.items():
            if label.startswith(lab):
                key, label = k, lab
                break
        if key and key not in fields:
            fields[key] = _clean_dd(label, dd.get_text(" ", strip=True))

    # 본문(.user_content) — JD 텍스트(이미지형 공고는 짧거나 빌 수 있음)
    uc = soup.select_one(".user_content")
    body_text = _clean(uc.get_text(" ", strip=True)) if uc else ""

    return {
        "company_name": company,
        "title": title,
        "employment_type_raw": fields.get("employment", ""),
        "career": fields.get("career", ""),
        "education": fields.get("education", ""),
        "salary": fields.get("salary", ""),
        "work_time": fields.get("work_time", ""),
        "deadline": _parse_deadline(soup),
        "region_detail": fields.get("region_detail", ""),
        "qualification": fields.get("qualification", ""),
        "preference": fields.get("preference", ""),
        "benefits": fields.get("benefits", ""),
        "body_text": body_text,
        "is_headhunting": "headhuntingView" in html_text,
    }
