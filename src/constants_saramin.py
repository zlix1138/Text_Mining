# -*- coding: utf-8 -*-
"""
사람인(Saramin) 전용 상수·설정.
- 잡코리아 constants.py는 그대로 두고(수정 금지), 사람인 전용 값만 여기에 모은다.
- 출력 컬럼은 잡코리아 공통 스키마(constants.JOBS_COLUMNS)를 그대로 재사용한다(병합 호환).
- 표준화/분류 사전(JOB_GROUPS, REGION_PREFIX_MAP 등)·요청설정도 constants의 값을 재사용한다.

robots.txt(2026-06 확인) 허용 경로만 사용한다.
  - 검색목록: GET /zf_user/search/recruit            (Disallow 미지정 → 허용)
  - 상세(팝업): GET /zf_user/jobs/view/popup          (robots.txt Allow 명시)
금지 경로(헤드헌팅 view, recruit_view.php, /zf_user/recruit/view 등)는 사용하지 않는다.
"""

import constants as C

# ──────────────────────────────────────────────────────────────────────────
# 출력 경로 (잡코리아 산출물과 완전 분리 — data/jobs.csv 등은 절대 건드리지 않음)
# ──────────────────────────────────────────────────────────────────────────
SARAMIN_RAW_CSV = C.DATA_DIR / "saramin_jobs_raw.csv"
SARAMIN_SUMMARY_CSV = C.DATA_DIR / "saramin_collection_summary.csv"
SARAMIN_CRAWL_LOG_CSV = C.DATA_DIR / "saramin_crawl_log.csv"
SARAMIN_FAILURES_CSV = C.DATA_DIR / "saramin_failures.csv"

SOURCE_NAME = "사람인"   # 잡코리아 값과 동일 규칙(한국어 출처명)

# ──────────────────────────────────────────────────────────────────────────
# 사람인 지역 코드(loc_mcd) — 표준 분석 지역명 → 사람인 시·도 코드
# (스모크 테스트로 코드별 대표 근무지를 실측 확인해 매핑 확정)
# 주의: 사람인은 114000=충북, 115000=충남 (실측). 표준 지역명은 잡코리아와 동일.
# ──────────────────────────────────────────────────────────────────────────
SARAMIN_REGIONS = {
    "서울": "101000",
    "경기도": "102000",
    "강원도": "109000",
    "충청북도": "114000",
    "충청남도": "115000",
    "전라북도": "113000",
    "전라남도": "112000",
    "경상북도": "111000",
    "경상남도": "110000",
    "제주도": "116000",
}

# ──────────────────────────────────────────────────────────────────────────
# 직무군별 사람인 검색 키워드 (5개 직무군; constants.JOB_GROUPS 기준).
# - 검색은 키워드로 수행하고, 최종 job_group은 preprocess.classify_job_group으로 사후 분류한다.
# - job_keyword(요약파일)에는 '검색에 사용한 키워드'를 기록한다.
# ──────────────────────────────────────────────────────────────────────────
SARAMIN_JOB_QUERIES = {
    "IT·데이터":    ["개발", "데이터"],
    "사무·회계":    ["사무", "회계", "인사"],
    "기획·마케팅":  ["기획", "마케팅"],
    "연구개발·품질": ["연구개발", "품질"],
    "생산·기술":    ["생산", "설비"],
}

# ──────────────────────────────────────────────────────────────────────────
# 엔드포인트 (전부 robots.txt 허용 경로)
# ──────────────────────────────────────────────────────────────────────────
BASE = "https://www.saramin.co.kr"
SEARCH_URL = BASE + "/zf_user/search/recruit"        # GET: 키워드×지역 검색목록
DETAIL_URL = BASE + "/zf_user/jobs/view/popup"       # GET: 상세(팝업, Allow 명시)

# 검색 파라미터 기본값
SEARCH_PAGE_SIZE = 40            # recruitPageCount(1페이지당 공고 수)
MAX_PAGES_PER_COMBO = 25         # 지역×키워드 1조합당 페이지 상한(과도 요청 방지)
DEFAULT_PER_COMBO = 100          # 지역×키워드 1조합당 상세 수집 목표

# 요청 설정은 잡코리아와 동일하게 constants에서 재사용
USER_AGENT = C.USER_AGENT
REQUEST_DELAY = C.REQUEST_DELAY
REQUEST_TIMEOUT = C.REQUEST_TIMEOUT
MAX_RETRY = C.MAX_RETRY

# ──────────────────────────────────────────────────────────────────────────
# CSV 스키마
# ──────────────────────────────────────────────────────────────────────────
# 원천/중간 수집 컬럼 = 잡코리아 공통 스키마 그대로(병합 호환)
RAW_COLUMNS = list(C.JOBS_COLUMNS)

SUMMARY_COLUMNS = [
    "region", "job_group", "job_keyword", "search_total_count",
    "collected_count", "success_count", "failed_count", "low_content_count",
    "source",
]
CRAWL_LOG_COLUMNS = ["timestamp", "level", "message", "url", "region", "job_group"]
FAILURES_COLUMNS = ["url", "region", "job_group", "error_type", "error_message", "collected_date"]
