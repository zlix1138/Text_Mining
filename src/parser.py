# -*- coding: utf-8 -*-
"""
HTML 파싱 모듈.
- _GI_List 목록 응답(HTML 조각) → 공고 행(공고번호/URL/요약) 파싱
- GI_Read 상세 응답 → JSON-LD(schema.org/JobPosting) + meta description 파싱
- 상세 본문(주요업무/자격요건/우대사항/복리후생)은 모던 RSC 페이지라 정적 HTML에 없음 →
  crawler의 Playwright 폴백으로 보완(여기서는 정적 추출만 시도하고 없으면 빈 값 반환).
모든 함수는 실패 시 예외를 던지지 않고 가능한 범위까지 파싱해 부분 결과를 돌려준다.
"""

import json
import re
import html as _html

from bs4 import BeautifulSoup

from constants import EMPLOYMENT_TYPE_MAP


def _clean(text):
    """HTML 엔티티 해제 + 공백 정리."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _classify_cell(c):
    """요약셀 텍스트를 의미(경력/학력/지역/고용형태/급여/직급)로 분류."""
    if re.search(r"정규직|계약직|인턴|파견|프리랜|촉탁|기간제", c):
        return "employment", c
    if re.search(r"경력|신입|무관", c) and "졸" not in c:
        return "career", c
    if re.search(r"졸|학력", c):
        return "education", c
    if re.search(r"만원|시급|연봉|월급", c) or re.search(r"\d{3,}\s*~", c):
        return "salary", c
    if re.search(r"(사원|주임|대리|과장|차장|부장|임원|급)", c) and ("서울" not in c):
        return "rank", c
    # 지역 접두로 시작하면 지역
    if re.match(r"(서울|경기|인천|강원|충북|충남|대전|세종|전북|전남|광주|경북|경남|대구|부산|울산|제주)", c):
        return "region", c
    return "etc", c


def parse_listing_rows(html_fragment):
    """
    _GI_List 응답에서 공고 행을 파싱(목록 기반 데이터).
    - 정규공고만 수집(헤드헌팅 organic 행=data-sccode 없음 → 제외).
    - 각 행: gno, 상세URL, 회사명(tplCo), 제목(tplTit), 요약셀(경력/학력/지역/고용형태/급여), 마감일(MM/DD).
    셀 순서가 가변적이라 위치가 아니라 내용 패턴으로 분류한다.
    반환: list[dict]
    """
    rows = []
    chunks = re.split(r'<tr class="devloopArea"', html_fragment)[1:]
    for ch in chunks:
        if "data-sccode=" not in ch:      # 헤드헌팅 행 제외
            continue
        m_gno = re.search(r'data-gno="(\d+)"', ch)
        if not m_gno:
            continue
        gno = m_gno.group(1)
        # 회사명: tplCo 영역의 첫 a 텍스트
        m_co = re.search(r'class="tplCo">.*?<a[^>]*>([^<]+)</a>', ch, re.S)
        # 제목: tplTit 영역 a의 title 속성(없으면 텍스트)
        m_ti = re.search(r'class="tplTit">.*?<a[^>]*title="([^"]+)"', ch, re.S)
        if not m_ti:
            m_ti = re.search(r'class="tplTit">.*?<a[^>]*>([^<]+)</a>', ch, re.S)
        # 요약셀 분류
        fields = {"career": "", "education": "", "region": "", "employment": "",
                  "salary": "", "rank": ""}
        for c in re.findall(r'<span class="cell"[^>]*>([^<]+)</span>', ch):
            kind, val = _classify_cell(_clean(c))
            if kind in fields and not fields[kind]:
                fields[kind] = val
        # 마감일(MM/DD가 여러 개면 마지막이 마감일인 경우가 많음 — 근사값, 정확값은 Tier-2 상세)
        dates = re.findall(r"(\d{2}/\d{2})", ch)
        deadline = dates[-1] if dates else ""

        rows.append({
            "gno": gno,
            "url": f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}",
            "company_name": _clean(m_co.group(1)) if m_co else "",
            "title": _clean(m_ti.group(1)) if m_ti else "",
            "career_raw": fields["career"],
            "education": fields["education"],
            "region_cell": fields["region"],
            "employment_raw": fields["employment"],
            "salary_raw": fields["salary"],
            "rank": fields["rank"],
            "deadline_raw": deadline,
        })
    return rows


def extract_jsonld(html_text):
    """상세 페이지의 JSON-LD(JobPosting) 블록을 dict로 반환(없으면 {})."""
    m = re.search(r'type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1).strip())
    except Exception:
        return {}
    # 리스트로 올 수도 있음 → JobPosting 우선
    if isinstance(data, list):
        for d in data:
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _meta_description(html_text):
    """meta description의 '경력 : .., 학력 : .., 급여 : .., 마감일 : ..' 요약을 dict로 파싱."""
    m = re.search(r'<meta name="description" content="([^"]+)"', html_text)
    out = {}
    if not m:
        return out
    desc = _html.unescape(m.group(1))
    for part in desc.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _summary_field(html_text, label):
    """상세 HTML 요약영역에서 '라벨 …값' 패턴을 best-effort로 추출(없으면 '')."""
    m = re.search(rf'{label}\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]{{1,40}})', html_text)
    return _clean(m.group(1)) if m else ""


def parse_detail(html_text):
    """
    GI_Read 상세 HTML → 필드 dict.
    - JSON-LD를 1차 소스로, meta description/요약영역을 보강 소스로 사용.
    - 본문(task_description 등)은 정적 HTML에 없으면 빈 값(crawler가 Playwright로 보완).
    반환 dict 키: company_name,title,employment_type_raw,career,education,salary,
                  deadline,region_detail,task_description,qualification,preference,benefits,work_time
    """
    d = extract_jsonld(html_text)
    meta = _meta_description(html_text)

    # 회사/제목
    company = ""
    ho = d.get("hiringOrganization")
    if isinstance(ho, dict):
        company = _clean(ho.get("name", ""))
    title = _clean(d.get("title", ""))

    # 고용형태: 상세 HTML 한글값 우선, 없으면 JSON-LD employmentType 매핑
    emp_html = _summary_field(html_text, "고용형태") or _summary_field(html_text, "근무형태")
    emp_jsonld = d.get("employmentType")
    if isinstance(emp_jsonld, list):
        emp_jsonld = emp_jsonld[0] if emp_jsonld else ""
    employment_type_raw = emp_html or EMPLOYMENT_TYPE_MAP.get(emp_jsonld, "")

    # 경력/학력/급여/마감: JSON-LD → meta → 요약영역 순으로 보강
    career = _clean(d.get("experienceRequirements", "")) or meta.get("경력", "") or _summary_field(html_text, "경력")
    education = _clean(d.get("educationRequirements", "")) or meta.get("학력", "") or _summary_field(html_text, "학력")
    salary = meta.get("급여", "") or _summary_field(html_text, "급여")
    deadline = _clean(d.get("validThrough", "")) or meta.get("마감일", "")
    work_time = _summary_field(html_text, "근무시간") or _summary_field(html_text, "근무일시")

    # 근무지(상세주소)
    region_detail = ""
    jl = d.get("jobLocation")
    if isinstance(jl, dict):
        addr = jl.get("address", {})
        if isinstance(addr, dict):
            region_detail = _clean(addr.get("streetAddress", "")
                                   or " ".join(filter(None, [addr.get("addressRegion"),
                                                             addr.get("addressLocality")])))

    # 본문 섹션(정적 HTML엔 보통 없음 → Playwright 폴백 대상)
    body = _extract_body_sections(html_text)

    return {
        "company_name": company,
        "title": title,
        "employment_type_raw": employment_type_raw,
        "career": career,
        "education": education,
        "salary": salary,
        "deadline": deadline,
        "region_detail": region_detail,
        "work_time": work_time,
        "task_description": body.get("task_description", ""),
        "qualification": body.get("qualification", ""),
        "preference": body.get("preference", ""),
        "benefits": body.get("benefits", ""),
        "is_headhunting": "PageGbn=HH" in html_text or "헤드헌팅" in (title or ""),
    }


def _extract_body_sections(html_text):
    """
    정적 HTML에서 본문 섹션을 best-effort 추출.
    모던 RSC 상세는 본문이 비어 있을 수 있음 → 그 경우 빈 dict(상위에서 Playwright 폴백).
    """
    out = {}
    soup = BeautifulSoup(html_text, "lxml")
    labels = {
        "주요업무": "task_description", "담당업무": "task_description",
        "자격요건": "qualification", "지원자격": "qualification",
        "우대사항": "preference",
        "복리후생": "benefits", "복지": "benefits",
    }
    for tag in soup.find_all(["h2", "h3", "h4", "strong", "dt", "th", "b"]):
        label = _clean(tag.get_text())
        for key, field in labels.items():
            if label.startswith(key):
                nxt = tag.find_next(["dd", "p", "div", "ul", "td"])
                if nxt:
                    val = _clean(nxt.get_text(" "))
                    if val and field not in out:
                        out[field] = val
    return out


def parse_playwright_body(text_blob):
    """
    Playwright로 렌더된 상세 '상세요강' 영역의 텍스트(통짜)를 받아 섹션 분할(best-effort).
    섹션 헤더를 못 찾으면 전체를 task_description에 넣고 note로 표시.
    반환: dict(task_description, qualification, preference, benefits, segmented:bool)
    """
    blob = re.sub(r"\s+\n", "\n", text_blob or "").strip()
    sections = {"task_description": "", "qualification": "", "preference": "", "benefits": ""}
    # 모집분야(직무명) 추출 → job_category_raw (분류 정확도 향상)
    m_cat = re.search(r"모집분야[:\s]+(.+?)\s*(?:모집인원|고용형태|급여|근무|마감|$)", blob)
    cat = _clean(m_cat.group(1))[:40] if m_cat else ""
    # 접수방법 등 오추출 가드(모집분야가 없는 공채에서 '홈페이지 지원' 등을 잡는 경우 제외)
    if cat and any(bad in cat for bad in ["지원", "홈페이지", "이메일", "방문", "접수", "온라인", "우편"]):
        cat = ""
    sections["job_category"] = cat
    header_map = [
        (r"주요업무|담당업무|수행업무", "task_description"),
        (r"자격요건|지원자격|자격조건", "qualification"),
        (r"우대사항|우대조건", "preference"),
        (r"복리후생|복지|혜택", "benefits"),
    ]
    # 헤더 위치 탐색
    found = []
    for pat, field in header_map:
        m = re.search(pat, blob)
        if m:
            found.append((m.start(), field))
    found.sort()
    if not found:
        sections["task_description"] = blob[:4000]
        sections["segmented"] = False
        return sections
    for i, (pos, field) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(blob)
        sections[field] = _clean(blob[pos:end])[:4000]
    sections["segmented"] = True
    return sections
