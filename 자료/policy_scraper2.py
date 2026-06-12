"""
policy_scraper_planB.py
온통청년 청년정책 OPEN API 수집 + 자동 분류 파이프라인

수정 핵심
1. 기존 empList.do / http 접근 대신 공식 청년정책 API youthPlcyList.do / https 사용
2. XML 구조가 일부 달라도 동작하도록 태그 후보를 여러 개 탐색
3. 지역별 페이지 수집, 재시도, 타임아웃, 실패 로그 저장
4. 로컬 네트워크가 막힌 경우 Google Colab 등 외부 실행환경에서 그대로 실행 가능

실행 전 준비
- API_KEY 값을 본인의 온통청년 Open API 인증키로 바꾸거나,
- 환경변수 YOUTH_API_KEY에 인증키를 넣고 실행하세요.
"""

from __future__ import annotations

import os
import time
import argparse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests
import pandas as pd
from tqdm import tqdm


# =========================================================
# 1. 기본 설정
# =========================================================

# 방법 1) 코드 안에 직접 입력
API_KEY = "16757632-64c6-4350-86f2-e8cb825f3e42"  # 예: "123AAebad2758130bb123AA"

# 방법 2) 환경변수로 입력한 경우 자동 사용
API_KEY = os.getenv("YOUTH_API_KEY", API_KEY).strip()

# 공식 온통청년 청년정책 API 엔드포인트
API_URL = "https://www.youthcenter.go.kr/opi/youthPlcyList.do"

# 서울 + 9개 도
REGION_CODES: Dict[str, str] = {
    "서울": "003002001",
    "경기": "003002008",
    "강원": "003002009",
    "충북": "003002010",
    "충남": "003002011",
    "전북": "003002012",
    "전남": "003002013",
    "경북": "003002014",
    "경남": "003002015",
    "제주": "003002016",
}

# 브라우저처럼 보이도록 기본 헤더 설정
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml,text/xml,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# =========================================================
# 2. 정책 자동 분류
# =========================================================

def classify_policy(name: str, desc: str, keyword: str = "", biz_type: str = "") -> str:
    """정책명/설명/키워드/공식분류 텍스트를 기반으로 정책 분야 자동 분류."""
    text = f"{name} {desc} {keyword} {biz_type}".lower()

    keywords = {
        "일자리": ["취업", "채용", "고용", "구직", "일자리", "면접", "인턴", "근로", "청년일자리"],
        "직무교육": ["교육", "훈련", "자격증", "실습", "역량", "학원", "인재양성", "직무", "취업교육"],
        "주거지원": ["주거", "월세", "전세", "임대", "주택", "보증금", "기숙사", "청년주택"],
        "창업지원": ["창업", "스타트업", "사업화", "창업공간", "예비창업", "창업자"],
        "복지": ["수당", "건강", "심리", "교통비", "식비", "포인트", "지원금", "복지", "생활비"],
        "참여 프로그램": ["동아리", "네트워크", "멘토링", "커뮤니티", "참여", "공모전", "청년활동"],
    }

    matched = []
    for category, kw_list in keywords.items():
        if any(kw in text for kw in kw_list):
            matched.append(category)

    return ", ".join(matched) if matched else "기타"


# =========================================================
# 3. XML 파싱 보조 함수
# =========================================================

def find_policy_nodes(root: ET.Element) -> List[ET.Element]:
    """
    API 응답 XML에서 정책 item 노드를 찾는다.
    공식 문서의 실제 태그명이 환경/버전에 따라 다르게 보일 수 있어 후보를 넓게 둔다.
    """
    candidate_paths = [
        ".//youthPolicy",
        ".//youthPlcy",
        ".//policy",
        ".//emp",
        ".//item",
        ".//row",
    ]

    for path in candidate_paths:
        nodes = root.findall(path)
        if nodes:
            return nodes

    return []


def get_text_any(node: ET.Element, tag_names: List[str], default: str = "") -> str:
    """여러 후보 태그 중 먼저 발견되는 텍스트를 반환."""
    for tag in tag_names:
        value = node.findtext(tag)
        if value is not None and value.strip():
            return value.strip()
    return default


def parse_policy_node(node: ET.Element, region_name: str, page: int) -> Dict[str, str]:
    """정책 XML 노드 하나를 표준 컬럼 구조로 변환."""
    # 온통청년 API의 구/신규 태그 후보를 함께 대응
    policy_id = get_text_any(node, ["plcyNo", "polyBizSecd", "bizId", "id"])
    name = get_text_any(node, ["plcyNm", "polyBizSjnm", "policyName", "title"])
    desc = get_text_any(node, ["plcyExplnCn", "polyItcnCn", "policyDesc", "description", "cn"])
    keyword = get_text_any(node, ["plcyKywdNm", "keyword", "keywords"])
    biz_type_large = get_text_any(node, ["lclsfNm", "bizTycdSel", "policyType", "category"])
    biz_type_mid = get_text_any(node, ["mclsfNm", "bizTycdSelNm", "middleCategory"])
    apply_period = get_text_any(node, ["aplyYmd", "rqutPrdCn", "applyPeriod", "period"])
    support_content = get_text_any(node, ["sprtCn", "sporCn", "supportContent"])
    target = get_text_any(node, ["sprtTrgtCn", "ageInfo", "target"])
    org = get_text_any(node, ["operInstCdNm", "cnsgNmor", "organization", "instNm"])
    url = get_text_any(node, ["aplyUrlAddr", "rqutUrla", "url", "link"])

    combined_desc = " ".join([desc, support_content, target]).strip()
    official_type = " > ".join([x for x in [biz_type_large, biz_type_mid] if x])
    category = classify_policy(name, combined_desc, keyword, official_type)

    return {
        "지역": region_name,
        "정책ID": policy_id,
        "정책명": name,
        "정책설명": combined_desc,
        "정책키워드": keyword,
        "공식분류": official_type,
        "자동분류": category,
        "신청기간": apply_period,
        "지원대상": target,
        "운영기관": org,
        "신청URL": url,
        "수집페이지": page,
        "수집출처": "온통청년_OPEN_API",
    }


# =========================================================
# 4. API 요청 함수
# =========================================================

def request_with_retry(
    session: requests.Session,
    params: Dict[str, str],
    timeout: int = 15,
    max_retries: int = 3,
    sleep_sec: float = 1.5,
) -> requests.Response:
    """일시적 네트워크 오류에 대비한 재시도 요청."""
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(API_URL, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(sleep_sec * attempt)

    raise last_error if last_error else RuntimeError("알 수 없는 API 요청 오류")


def fetch_region_policies(
    session: requests.Session,
    region_name: str,
    region_code: str,
    display: int = 100,
    timeout: int = 15,
    max_pages: int = 200,
) -> List[Dict[str, str]]:
    """특정 지역의 정책 데이터를 페이지 단위로 수집."""
    policies: List[Dict[str, str]] = []

    for page in range(1, max_pages + 1):
        params = {
            "openApiVlak": API_KEY,
            "display": str(display),
            "pageIndex": str(page),
            "srchPolyBizSecd": region_code,
        }

        response = request_with_retry(session, params=params, timeout=timeout)

        # 응답 인코딩 보정
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        text = response.text.strip()
        if not text:
            break

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            # API 키 오류/HTML 오류 페이지가 온 경우 확인할 수 있게 일부 저장
            raise RuntimeError(
                f"XML 파싱 실패: {e}. 응답 앞부분: {text[:300]}"
            )

        nodes = find_policy_nodes(root)

        if not nodes:
            # 첫 페이지부터 결과가 없으면 해당 지역 결과 없음 또는 파라미터 문제
            break

        page_rows = [parse_policy_node(node, region_name, page) for node in nodes]

        # 정책명이 전부 비어있으면 구조가 맞지 않을 가능성이 큼
        valid_rows = [row for row in page_rows if row["정책명"] or row["정책설명"]]
        policies.extend(valid_rows)

        # 마지막 페이지 추정: display보다 적게 오면 종료
        if len(nodes) < display:
            break

        time.sleep(0.4)

    return policies


# =========================================================
# 5. 전체 수집 실행
# =========================================================

def fetch_all_policies(display: int = 100, timeout: int = 15) -> pd.DataFrame:
    if not API_KEY or API_KEY == "api 키":
        raise ValueError(
            "API_KEY가 설정되지 않았습니다. 코드 상단의 API_KEY를 수정하거나 "
            "환경변수 YOUTH_API_KEY를 설정하세요."
        )

    all_policies: List[Dict[str, str]] = []
    error_logs: List[Dict[str, str]] = []

    print("\n🚀 온통청년 공식 HTTPS API 기반 청년정책 데이터 수집을 시작합니다.\n")
    print(f"요청 URL: {API_URL}\n")

    with requests.Session() as session:
        for region_name, region_code in tqdm(REGION_CODES.items(), desc="지역별 수집 진행도"):
            try:
                rows = fetch_region_policies(
                    session=session,
                    region_name=region_name,
                    region_code=region_code,
                    display=display,
                    timeout=timeout,
                )
                all_policies.extend(rows)
                print(f"✅ {region_name}: {len(rows)}건 수집")
            except Exception as e:
                msg = str(e)
                print(f"\n❌ {region_name} 수집 실패: {msg}")
                error_logs.append({
                    "지역": region_name,
                    "지역코드": region_code,
                    "에러": msg,
                    "진단": "로컬 네트워크 차단, API 키 오류, 응답 구조 변경 가능성 확인 필요",
                })

    df = pd.DataFrame(all_policies)

    if not df.empty:
        # 중복 제거: 정책ID가 있으면 정책ID+지역 기준, 없으면 정책명+지역 기준
        if "정책ID" in df.columns and df["정책ID"].astype(str).str.strip().any():
            df = df.drop_duplicates(subset=["지역", "정책ID", "정책명"], keep="first")
        else:
            df = df.drop_duplicates(subset=["지역", "정책명"], keep="first")

        # 지역/분류별 요약도 함께 저장
        summary = (
            df.groupby(["지역", "자동분류"], dropna=False)
            .size()
            .reset_index(name="정책수")
            .sort_values(["지역", "정책수"], ascending=[True, False])
        )

        df.to_csv("youth_policies_categorized.csv", index=False, encoding="utf-8-sig")
        summary.to_csv("youth_policies_summary_by_region_category.csv", index=False, encoding="utf-8-sig")

        print("\n✅ 데이터 수집 및 자동 분류 완료")
        print(f"총 수집 건수: {len(df)}건")
        print("\n🔍 수집 데이터 샘플:")
        print(df.head())
        print("\n💾 저장 파일:")
        print("- youth_policies_categorized.csv")
        print("- youth_policies_summary_by_region_category.csv")
    else:
        print("\n⚠️ 수집된 데이터가 없습니다.")
        print("로컬 네트워크에서 실패한다면 같은 코드를 Google Colab에서 실행하세요.")

    if error_logs:
        pd.DataFrame(error_logs).to_csv("youth_policies_error_log.csv", index=False, encoding="utf-8-sig")
        print("\n⚠️ 일부 지역 수집 실패 로그 저장:")
        print("- youth_policies_error_log.csv")

    return df


# =========================================================
# 6. CLI 실행부
# =========================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="온통청년 청년정책 API 수집기")
    parser.add_argument("--display", type=int, default=100, help="페이지당 수집 건수, 기본값 100")
    parser.add_argument("--timeout", type=int, default=15, help="요청 타임아웃 초, 기본값 15")
    args = parser.parse_args()

    fetch_all_policies(display=args.display, timeout=args.timeout)
