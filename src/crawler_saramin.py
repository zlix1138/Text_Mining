# -*- coding: utf-8 -*-
"""
사람인(Saramin) 수집 모듈 (requests 전용).
robots.txt 허용 경로만 사용:
  - 검색목록: GET /zf_user/search/recruit          (searchword, loc_mcd, recruitPage, ...)
  - 상세팝업: GET /zf_user/jobs/view/popup         (rec_idx)  ← robots.txt Allow 명시
요청 간격(지터)을 두고, 일부 공고 실패가 전체를 멈추지 않도록 예외를 격리한다.
캡차/차단/접근제한은 우회하지 않으며, 감지 시 호출부에서 즉시 중단한다.
"""

import random
import time

import requests

import constants_saramin as CS
import parser_saramin as PS


def _sleep():
    """요청 간격(지터 포함)."""
    lo, hi = CS.REQUEST_DELAY
    time.sleep(random.uniform(lo, hi))


class BlockedError(Exception):
    """차단/접근제한(캡차·로그인 강제·403 등) 감지 시 발생 — 즉시 중단·보고용."""


class SaraminCrawler:
    """requests.Session 기반 사람인 수집기."""

    def __init__(self, logger=None):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": CS.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": CS.BASE + "/",
        })
        self.log = logger or (lambda *a, **k: None)

    def _get(self, url, params, region="", job_group=""):
        """GET 요청(재시도 포함). 차단 의심 시 BlockedError. 실패 시 None."""
        for attempt in range(CS.MAX_RETRY + 1):
            try:
                r = self.s.get(url, params=params, timeout=CS.REQUEST_TIMEOUT)
                if r.status_code == 200:
                    text = r.content.decode("utf-8", "replace")
                    low = text[:3000]
                    if ("자동입력 방지" in low or "captcha" in low.lower()
                            or "비정상적인 접근" in low or "접근이 차단" in low):
                        raise BlockedError(f"차단/캡차 의심 페이지: {url}")
                    return text
                if r.status_code in (403, 429):
                    raise BlockedError(f"HTTP {r.status_code} (차단/제한): {url}")
                self.log("WARN", f"HTTP {r.status_code} (시도 {attempt+1})", url, region, job_group)
            except BlockedError:
                raise
            except requests.RequestException as e:
                self.log("WARN", f"요청 예외 {e} (시도 {attempt+1})", url, region, job_group)
            _sleep()
        return None

    # ── 검색목록 ────────────────────────────────────────────────────────────
    def fetch_search_page(self, keyword, loc_mcd, page, region="", job_group=""):
        """검색목록 1페이지 HTML 반환(실패 시 None)."""
        params = {
            "searchword": keyword,
            "loc_mcd": loc_mcd,
            "recruitPage": page,
            "recruitPageCount": CS.SEARCH_PAGE_SIZE,
            "recruitSort": "relation",
        }
        return self._get(CS.SEARCH_URL, params, region, job_group)

    def fetch_search_count(self, keyword, loc_mcd, region="", job_group=""):
        """지역×키워드 전체 검색건수(search_total_count)와 1페이지 HTML을 함께 반환.
        반환: (count:int|None, first_page_html:str|None)
        """
        html = self.fetch_search_page(keyword, loc_mcd, 1, region, job_group)
        if html is None:
            return None, None
        return PS.parse_search_count(html), html

    def iter_listings(self, keyword, loc_mcd, region="", job_group="",
                      max_pages=None, first_page_html=None, seen=None):
        """
        검색목록을 페이지 순회하며 공고 행(dict)을 yield.
        - 중복(rec_idx)은 건너뛴다. 빈 페이지/새 공고 없음 시 종료.
        - first_page_html: fetch_search_count로 이미 받은 1페이지를 재사용(중복요청 방지).
        """
        max_pages = max_pages or CS.MAX_PAGES_PER_COMBO
        seen = seen if seen is not None else set()
        for page in range(1, max_pages + 1):
            if page == 1 and first_page_html is not None:
                html = first_page_html
            else:
                html = self.fetch_search_page(keyword, loc_mcd, page, region, job_group)
                _sleep()
            if not html:
                break
            rows = PS.parse_listing_rows(html)
            if not rows:
                break
            new_count = 0
            for row in rows:
                if row["rec_idx"] in seen:
                    continue
                seen.add(row["rec_idx"])
                new_count += 1
                yield row
            if new_count == 0:
                break

    # ── 상세 ────────────────────────────────────────────────────────────────
    def fetch_detail(self, rec_idx, region="", job_group=""):
        """상세 팝업 HTML 반환(실패 시 None)."""
        return self._get(CS.DETAIL_URL, {"rec_idx": rec_idx}, region, job_group)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
