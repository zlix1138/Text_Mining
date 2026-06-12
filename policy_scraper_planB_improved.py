"""
policy_scraper_planB_improved.py

온통청년 청년정책 OPEN API 수집 + 자동 분류 파이프라인 개선본

핵심 개선
1) 업로드된 온통청년 API 문서 기준의 공식 청년정책 API 사용
   - URL: https://www.youthcenter.go.kr/go/ythip/getPlcy
   - 인증키 파라미터: apiKeyNm
   - 페이지 파라미터: pageNum, pageSize
   - 응답 형식: rtnType=json 기본, XML도 지원
   - 지역 필터: zipCd(법정시군구코드 5자리)

2) 기존 /opi/youthPlcyList.do 호출 시 발생하던 8080 포트 리다이렉트 문제를 피함
3) JSON/XML 응답 모두 파싱 가능
4) 지역별 수집 실패 로그, 원본 응답 저장 옵션, 요약 CSV 생성
5) 로컬 네트워크가 막힌 경우 Google Colab/Codespaces 등 외부 실행환경에서 그대로 실행 가능

실행 예시
    # PowerShell
    $env:YOUTH_API_KEY="본인_인증키"
    python policy_scraper_planB_improved.py --page-size 100 --timeout 20 --save-raw

    # 또는 CLI로 인증키 전달
    python policy_scraper_planB_improved.py --api-key "본인_인증키"

필요 라이브러리
    pip install requests pandas tqdm
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from tqdm import tqdm


# =========================================================
# 1. 기본 설정
# =========================================================

DEFAULT_API_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"

# 서울 + 9개 도
# 온통청년 문서는 zipCd를 "법정시군구코드(5자리)"라고 설명하며,
# 11000을 서울특별시 예시로 제시한다.
# 강원/전북은 행정명 변경 이슈가 있어 신/구 코드를 함께 넣어 재현성을 높였다.
REGION_ZIP_CODES: Dict[str, List[str]] = {
    "서울": ["11000"],
    "경기": ["41000"],
    "강원": ["51000", "42000"],  # 강원특별자치도 / 구 강원도
    "충북": ["43000"],
    "충남": ["44000"],
    "전북": ["52000", "45000"],  # 전북특별자치도 / 구 전라북도
    "전남": ["46000"],
    "경북": ["47000"],
    "경남": ["48000"],
    "제주": ["50000"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "close",
}

OUTPUT_COLUMNS = [
    "지역",
    "조회_zipCd",
    "정책ID",
    "정책명",
    "정책키워드",
    "정책설명",
    "정책지원내용",
    "정책대분류",
    "정책중분류",
    "자동분류",
    "대표분류",
    "신청기간",
    "사업기간",
    "지원대상",
    "나이조건",
    "소득조건",
    "신청방법",
    "제출서류",
    "주관기관",
    "운영기관",
    "신청URL",
    "참고URL1",
    "참고URL2",
    "최초등록일시",
    "최종수정일시",
    "수집페이지",
    "수집출처",
]


# =========================================================
# 2. 텍스트 정리 및 자동 분류
# =========================================================

def clean_text(value: Any) -> str:
    """API 값의 공백/HTML 엔티티/None을 정리한다."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False)
    text = html_lib.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "일자리": [
        "일자리", "취업", "채용", "고용", "구직", "면접", "인턴", "근로", "청년일자리",
        "취업지원", "국민취업지원", "직장", "재직", "일경험", "현장실습", "채용연계",
    ],
    "직무교육": [
        "교육", "훈련", "직무", "자격증", "역량", "인재양성", "부트캠프", "아카데미",
        "디지털", "ai", "ict", "코딩", "프로그램", "스킬", "전문인력",
    ],
    "주거지원": [
        "주거", "월세", "전세", "임대", "주택", "보증금", "기숙사", "청년주택",
        "주거비", "임차", "전월세", "공공임대", "매입임대",
    ],
    "창업지원": [
        "창업", "스타트업", "사업화", "예비창업", "초기창업", "창업공간", "창업자",
        "벤처", "창직", "사업자", "액셀러레이팅", "투자유치",
    ],
    "복지": [
        "복지", "수당", "지원금", "생활비", "교통비", "식비", "건강", "심리",
        "마음", "상담", "문화", "자산형성", "적금", "통장", "금융", "의료",
    ],
    "참여 프로그램": [
        "참여", "권리", "동아리", "네트워크", "멘토링", "커뮤니티", "공모전",
        "청년활동", "위원회", "서포터즈", "봉사", "교류", "정책참여",
    ],
}


def classify_policy(row: Dict[str, str]) -> Tuple[str, str]:
    """
    정책 텍스트와 공식 분류를 함께 사용해 프로젝트용 정책 분야를 분류한다.
    반환: (자동분류 다중값, 대표분류)
    """
    text = " ".join([
        row.get("정책명", ""),
        row.get("정책키워드", ""),
        row.get("정책설명", ""),
        row.get("정책지원내용", ""),
        row.get("정책대분류", ""),
        row.get("정책중분류", ""),
    ]).lower()

    matched: List[str] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            matched.append(category)

    if not matched:
        matched = ["기타"]

    return ", ".join(matched), matched[0]


# =========================================================
# 3. API 응답 파싱 보조 함수
# =========================================================

def strip_namespace(tag: str) -> str:
    """XML 네임스페이스를 제거한다."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def element_to_dict(elem: ET.Element) -> Dict[str, str]:
    """XML Element의 직계 자식 태그를 dict로 변환한다."""
    result: Dict[str, str] = {}
    for child in list(elem):
        key = strip_namespace(child.tag)
        # 같은 태그가 여러 번 나오면 값을 이어붙인다.
        value = clean_text(child.text)
        if key in result and value:
            result[key] = f"{result[key]} | {value}"
        else:
            result[key] = value
    return result


def is_policy_like_dict(obj: Dict[str, Any]) -> bool:
    """dict가 정책 레코드처럼 보이는지 판단한다."""
    keys = set(obj.keys())
    return bool({"plcyNo", "plcyNm", "plcyExplnCn", "plcyKywdNm"} & keys)


def extract_policy_dicts_from_json(obj: Any) -> List[Dict[str, Any]]:
    """
    JSON 구조가 정확히 문서화되어 있지 않거나 래퍼가 있어도 정책 목록을 찾는다.
    예: {"youthPolicyList": [...]}, {"data": {"list": [...]}} 등 대응.
    """
    found: List[Dict[str, Any]] = []

    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and is_policy_like_dict(item):
                found.append(item)
            elif isinstance(item, (list, dict)):
                found.extend(extract_policy_dicts_from_json(item))
        return found

    if isinstance(obj, dict):
        if is_policy_like_dict(obj):
            return [obj]

        # 자주 쓰이는 목록 키를 우선 탐색
        preferred_keys = [
            "youthPolicyList", "policyList", "plcyList", "data", "result", "list",
            "items", "item", "rows", "row", "body",
        ]
        for key in preferred_keys:
            if key in obj:
                found.extend(extract_policy_dicts_from_json(obj[key]))

        # 위에서 못 찾으면 전체 재귀 탐색
        if not found:
            for value in obj.values():
                if isinstance(value, (list, dict)):
                    found.extend(extract_policy_dicts_from_json(value))

    # 중복 제거
    unique: List[Dict[str, Any]] = []
    seen = set()
    for item in found:
        sig = (
            clean_text(item.get("plcyNo")),
            clean_text(item.get("plcyNm")),
            clean_text(item.get("plcyExplnCn"))[:80],
        )
        if sig not in seen:
            seen.add(sig)
            unique.append(item)
    return unique


def extract_policy_dicts_from_xml(text: str) -> List[Dict[str, str]]:
    """XML 응답에서 정책 레코드를 추출한다."""
    root = ET.fromstring(text)

    nodes: List[ET.Element] = []
    for elem in root.iter():
        child_tags = {strip_namespace(child.tag) for child in list(elem)}
        if {"plcyNo", "plcyNm", "plcyExplnCn", "plcyKywdNm"} & child_tags:
            nodes.append(elem)

    # root가 곧 정책 1건인 경우
    if not nodes:
        root_dict = element_to_dict(root)
        if is_policy_like_dict(root_dict):
            return [root_dict]

    rows: List[Dict[str, str]] = []
    seen = set()
    for node in nodes:
        row = element_to_dict(node)
        sig = (
            row.get("plcyNo", ""),
            row.get("plcyNm", ""),
            row.get("plcyExplnCn", "")[:80],
        )
        if sig not in seen:
            seen.add(sig)
            rows.append(row)
    return rows


def parse_api_response(text: str, rtn_type: str) -> List[Dict[str, Any]]:
    """rtnType 또는 실제 응답 형태를 기준으로 JSON/XML을 파싱한다."""
    cleaned = text.strip()
    if not cleaned:
        return []

    # HTML 오류 페이지를 빨리 감지
    if cleaned[:20].lower().startswith(("<!doctype html", "<html")):
        raise RuntimeError(f"API가 데이터가 아닌 HTML을 반환했습니다. 응답 앞부분: {cleaned[:300]}")

    # rtnType=json이어도 서버가 XML을 줄 수 있으므로 실제 첫 글자도 확인
    if rtn_type.lower() == "json" or cleaned[0] in "[{":
        try:
            data = json.loads(cleaned)
            return extract_policy_dicts_from_json(data)
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 XML fallback
            pass

    return extract_policy_dicts_from_xml(cleaned)


# =========================================================
# 4. 정책 레코드 표준화
# =========================================================

def pick(raw: Dict[str, Any], *keys: str) -> str:
    """여러 후보 키 중 첫 번째 비어 있지 않은 값을 반환한다."""
    for key in keys:
        if key in raw:
            value = clean_text(raw.get(key))
            if value:
                return value
    return ""


def build_standard_row(raw: Dict[str, Any], region_name: str, zip_codes: Sequence[str], page: int) -> Dict[str, str]:
    """API 원본 레코드를 분석용 표준 컬럼으로 변환한다."""
    policy_id = pick(raw, "plcyNo", "policyNo", "bizId", "id")
    name = pick(raw, "plcyNm", "policyName", "title")
    keyword = pick(raw, "plcyKywdNm", "keyword", "keywords")
    desc = pick(raw, "plcyExplnCn", "policyDesc", "description", "cn")
    support = pick(raw, "plcySprtCn", "sprtCn", "sporCn", "supportContent")
    lclsf = pick(raw, "lclsfNm", "policyType", "category")
    mclsf = pick(raw, "mclsfNm", "middleCategory")
    apply_period = pick(raw, "aplyYmd", "rqutPrdCn", "applyPeriod", "period")

    biz_period = " ~ ".join(
        x for x in [
            pick(raw, "bizPrdBgngYmd"),
            pick(raw, "bizPrdEndYmd"),
        ]
        if x
    )
    biz_period_etc = pick(raw, "bizPrdEtcCn")
    if biz_period_etc:
        biz_period = f"{biz_period} ({biz_period_etc})" if biz_period else biz_period_etc

    age_min = pick(raw, "sprtTrgtMinAge")
    age_max = pick(raw, "sprtTrgtMaxAge")
    age_limited = pick(raw, "sprtTrgtAgeLmtYn")
    age_condition = ""
    if age_min or age_max:
        age_condition = f"{age_min or '?'}세~{age_max or '?'}세"
    if age_limited:
        age_condition = f"{age_condition} / 연령제한:{age_limited}".strip(" /")

    income_condition = " ".join(
        x for x in [
            pick(raw, "earnCndSeCd"),
            pick(raw, "earnMinAmt"),
            pick(raw, "earnMaxAmt"),
            pick(raw, "earnEtcCn"),
        ]
        if x
    )

    target = " ".join(
        x for x in [
            age_condition,
            income_condition,
            pick(raw, "addAplyQlfcCndCn"),
            pick(raw, "ptcpPrpTrgtCn"),
            pick(raw, "plcyMajorCd"),
            pick(raw, "jobCd"),
            pick(raw, "schoolCd"),
            pick(raw, "mrgSttsCd"),
            pick(raw, "sBizCd"),
        ]
        if x
    )

    row: Dict[str, str] = {
        "지역": region_name,
        "조회_zipCd": ",".join(zip_codes),
        "정책ID": policy_id,
        "정책명": name,
        "정책키워드": keyword,
        "정책설명": desc,
        "정책지원내용": support,
        "정책대분류": lclsf,
        "정책중분류": mclsf,
        "자동분류": "",
        "대표분류": "",
        "신청기간": apply_period,
        "사업기간": biz_period,
        "지원대상": target,
        "나이조건": age_condition,
        "소득조건": income_condition,
        "신청방법": pick(raw, "plcyAplyMthdCn"),
        "제출서류": pick(raw, "sbmsnDcmntCn"),
        "주관기관": pick(raw, "sprvsnInstCdNm", "rgtrHghrkInstCdNm", "rgtrUpInstCdNm"),
        "운영기관": pick(raw, "operInstCdNm", "rgtrInstCdNm"),
        "신청URL": pick(raw, "aplyUrlAddr", "rqutUrla", "url", "link"),
        "참고URL1": pick(raw, "refUrlAddr1"),
        "참고URL2": pick(raw, "refUrlAddr2"),
        "최초등록일시": pick(raw, "frstRegDt"),
        "최종수정일시": pick(raw, "lastMdfcnDt"),
        "수집페이지": str(page),
        "수집출처": "온통청년_OPEN_API_getPlcy",
    }

    auto_category, main_category = classify_policy(row)
    row["자동분류"] = auto_category
    row["대표분류"] = main_category

    return row


# =========================================================
# 5. API 요청 및 수집
# =========================================================

def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def request_with_retry(
    session: requests.Session,
    endpoint: str,
    params: Dict[str, Any],
    timeout: int = 20,
    max_retries: int = 3,
    sleep_sec: float = 1.5,
) -> requests.Response:
    """
    재시도 요청.
    8080 포트로 리다이렉트되는 경우는 로컬 방화벽 이슈로 이어지므로 명확히 진단한다.
    """
    last_error: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                endpoint,
                params=params,
                timeout=(timeout, timeout),
                allow_redirects=False,
            )

            location = response.headers.get("Location", "")
            if 300 <= response.status_code < 400:
                if ":8080" in location or "8080" in location:
                    raise RuntimeError(
                        "API 서버가 8080 포트로 리다이렉트했습니다. "
                        "현재 네트워크에서 8080 아웃바운드가 차단된 상태라면 "
                        "공식 /go/ythip/getPlcy 엔드포인트 사용 여부를 확인하거나 "
                        "Google Colab/Codespaces/모바일 핫스팟 같은 외부망에서 실행해야 합니다. "
                        f"Location={location}"
                    )
                raise RuntimeError(f"예상하지 못한 리다이렉트입니다. status={response.status_code}, Location={location}")

            response.raise_for_status()
            return response

        except (requests.exceptions.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(sleep_sec * attempt)

    raise RuntimeError(f"API 요청 실패: {last_error}") from last_error


def build_params(
    api_key: str,
    page: int,
    page_size: int,
    zip_codes: Sequence[str],
    rtn_type: str = "json",
    page_type: str = "1",
    lclsf_names: Optional[Sequence[str]] = None,
    mclsf_names: Optional[Sequence[str]] = None,
    keyword_names: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """온통청년 getPlcy 문서 기준 요청 파라미터를 구성한다."""
    params: Dict[str, Any] = {
        "apiKeyNm": api_key,
        "pageNum": page,
        "pageSize": page_size,
        "pageType": page_type,
        "rtnType": rtn_type,
    }

    if zip_codes:
        params["zipCd"] = ",".join(zip_codes)
    if lclsf_names:
        params["lclsfNm"] = ",".join(lclsf_names)
    if mclsf_names:
        params["mclsfNm"] = ",".join(mclsf_names)
    if keyword_names:
        params["plcyKywdNm"] = ",".join(keyword_names)

    return params


def save_raw_response(raw_dir: Path, region_name: str, page: int, text: str, rtn_type: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe_region = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", region_name)
    ext = "json" if rtn_type.lower() == "json" else "xml"
    (raw_dir / f"{safe_region}_page{page:04d}.{ext}").write_text(text, encoding="utf-8")


def fetch_region_policies(
    session: requests.Session,
    api_key: str,
    endpoint: str,
    region_name: str,
    zip_codes: Sequence[str],
    page_size: int = 100,
    timeout: int = 20,
    max_pages: int = 200,
    rtn_type: str = "json",
    save_raw: bool = False,
    raw_dir: Path = Path("raw_api_responses"),
) -> List[Dict[str, str]]:
    """특정 지역의 정책 데이터를 페이지 단위로 수집한다."""
    rows: List[Dict[str, str]] = []

    for page in range(1, max_pages + 1):
        params = build_params(
            api_key=api_key,
            page=page,
            page_size=page_size,
            zip_codes=zip_codes,
            rtn_type=rtn_type,
            page_type="1",
        )

        response = request_with_retry(
            session=session,
            endpoint=endpoint,
            params=params,
            timeout=timeout,
        )

        # 인코딩 보정
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        text = response.text.strip()
        if save_raw:
            save_raw_response(raw_dir, region_name, page, text, rtn_type)

        raw_items = parse_api_response(text, rtn_type=rtn_type)
        if not raw_items:
            break

        page_rows = [
            build_standard_row(raw=item, region_name=region_name, zip_codes=zip_codes, page=page)
            for item in raw_items
        ]

        # 정책명/정책설명 모두 비어 있으면 파라미터 또는 응답 구조 문제일 가능성이 큼
        valid_rows = [
            row for row in page_rows
            if row.get("정책명") or row.get("정책설명") or row.get("정책ID")
        ]
        rows.extend(valid_rows)

        if len(raw_items) < page_size:
            break

        time.sleep(0.35)

    return rows


# =========================================================
# 6. 저장 및 요약
# =========================================================

def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    # 정책ID가 있으면 지역+정책ID 기준, 없으면 지역+정책명 기준
    has_id = df["정책ID"].astype(str).str.strip().ne("").any()
    if has_id:
        df = df.drop_duplicates(subset=["지역", "정책ID"], keep="first")
    else:
        df = df.drop_duplicates(subset=["지역", "정책명"], keep="first")

    return df.reset_index(drop=True)


def make_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["지역", "자동분류", "정책수"])

    exploded = df.copy()
    exploded["자동분류"] = exploded["자동분류"].fillna("기타").astype(str).str.split(r"\s*,\s*")
    exploded = exploded.explode("자동분류")
    exploded["자동분류"] = exploded["자동분류"].replace("", "기타")

    return (
        exploded.groupby(["지역", "자동분류"], dropna=False)
        .size()
        .reset_index(name="정책수")
        .sort_values(["지역", "정책수"], ascending=[True, False])
        .reset_index(drop=True)
    )


def save_outputs(
    df: pd.DataFrame,
    output_path: Path,
    summary_path: Path,
) -> Tuple[Path, Path]:
    if not df.empty:
        for col in OUTPUT_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[OUTPUT_COLUMNS]

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    summary = make_summary(df)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return output_path, summary_path


# =========================================================
# 7. 전체 실행
# =========================================================

def fetch_all_policies(
    api_key: str,
    endpoint: str = DEFAULT_API_URL,
    page_size: int = 100,
    timeout: int = 20,
    max_pages: int = 200,
    rtn_type: str = "json",
    save_raw: bool = False,
    output_path: Path = Path("youth_policies_categorized.csv"),
    summary_path: Path = Path("youth_policies_summary_by_region_category.csv"),
    error_log_path: Path = Path("youth_policies_error_log.csv"),
) -> pd.DataFrame:
    api_key = clean_text(api_key)
    if not api_key or api_key.upper() in {"YOUR_API_KEY", "API_KEY", "TESTKEY"}:
        raise ValueError(
            "API 인증키가 설정되지 않았습니다. "
            "환경변수 YOUTH_API_KEY를 설정하거나 --api-key 옵션을 사용하세요."
        )

    all_rows: List[Dict[str, str]] = []
    error_logs: List[Dict[str, str]] = []

    print("\n🚀 온통청년 청년정책 API 수집을 시작합니다.")
    print(f"요청 URL: {endpoint}")
    print(f"응답 형식: {rtn_type}")
    print(f"페이지 크기: {page_size}\n")

    with make_session() as session:
        for region_name, zip_codes in tqdm(REGION_ZIP_CODES.items(), desc="지역별 수집 진행도"):
            try:
                rows = fetch_region_policies(
                    session=session,
                    api_key=api_key,
                    endpoint=endpoint,
                    region_name=region_name,
                    zip_codes=zip_codes,
                    page_size=page_size,
                    timeout=timeout,
                    max_pages=max_pages,
                    rtn_type=rtn_type,
                    save_raw=save_raw,
                )
                all_rows.extend(rows)
                print(f"✅ {region_name}: {len(rows)}건 수집")
            except Exception as exc:
                msg = str(exc)
                print(f"\n❌ {region_name} 수집 실패: {msg}")
                error_logs.append({
                    "지역": region_name,
                    "조회_zipCd": ",".join(zip_codes),
                    "에러": msg,
                    "진단": (
                        "1) 인증키(apiKeyNm) 오류, 2) 네트워크/방화벽 차단, "
                        "3) API 응답 구조 변경, 4) 해당 지역 결과 없음 가능성 확인"
                    ),
                })

    df = deduplicate(pd.DataFrame(all_rows))

    output_path, summary_path = save_outputs(df, output_path, summary_path)

    print("\n✅ 수집 프로세스 종료")
    print(f"총 수집 건수(중복 제거 후): {len(df)}건")
    print(f"💾 원자료 저장: {output_path}")
    print(f"💾 지역-분류 요약 저장: {summary_path}")

    if error_logs:
        pd.DataFrame(error_logs).to_csv(error_log_path, index=False, encoding="utf-8-sig")
        print(f"⚠️ 실패 로그 저장: {error_log_path}")

    if df.empty:
        print("\n⚠️ 수집된 데이터가 없습니다.")
        print("확인 순서:")
        print("1) API 인증키가 온통청년 마이페이지의 OPEN API 키와 일치하는지 확인")
        print("2) 브라우저에서 getPlcy URL이 8080으로 리다이렉트되는지 확인")
        print("3) 학교/회사망이면 Google Colab, GitHub Codespaces, 모바일 핫스팟에서 재실행")
        print("4) --save-raw 옵션으로 저장된 원본 응답이 HTML 오류 페이지인지 확인")

    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="온통청년 청년정책 API 수집기 개선본")
    parser.add_argument(
        "--api-key",
        default=os.getenv("YOUTH_API_KEY", ""),
        help="온통청년 OPEN API 인증키. 생략 시 환경변수 YOUTH_API_KEY 사용",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_API_URL,
        help=f"API 엔드포인트. 기본값: {DEFAULT_API_URL}",
    )
    parser.add_argument("--page-size", type=int, default=100, help="페이지당 수집 건수")
    parser.add_argument("--timeout", type=int, default=20, help="connect/read 타임아웃 초")
    parser.add_argument("--max-pages", type=int, default=200, help="지역별 최대 페이지 수")
    parser.add_argument(
        "--rtn-type",
        choices=["json", "xml"],
        default="json",
        help="API 응답 형식. 기본값 json",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="지역/페이지별 API 원본 응답을 raw_api_responses 폴더에 저장",
    )
    parser.add_argument(
        "--output",
        default="youth_policies_categorized.csv",
        help="수집 결과 CSV 경로",
    )
    parser.add_argument(
        "--summary-output",
        default="youth_policies_summary_by_region_category.csv",
        help="지역-분류 요약 CSV 경로",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    fetch_all_policies(
        api_key=args.api_key,
        endpoint=args.endpoint,
        page_size=args.page_size,
        timeout=args.timeout,
        max_pages=args.max_pages,
        rtn_type=args.rtn_type,
        save_raw=args.save_raw,
        output_path=Path(args.output),
        summary_path=Path(args.summary_output),
    )
