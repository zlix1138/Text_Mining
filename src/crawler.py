# -*- coding: utf-8 -*-
"""
잡코리아 수집 모듈 (requests 중심, Playwright는 상세 본문 폴백 전용).
확정 경로(2단계 파일럿, docs/pilot_results.md):
  - 세션:   GET  /recruit/joblist?menucode=local&local=<코드>   (쿠키 설정)
  - 카운트: POST /Recruit/Home/_SearchCount/                    (지역 전체 건수)
  - 목록:   POST /Recruit/Home/_GI_List/                        (지역 목록 페이지네이션)
  - 상세:   GET  /Recruit/GI_Read/{gno}                         (JSON-LD)
robots.txt 허용 경로만 사용. 차단된 키워드검색(stext)·로그인영역은 사용하지 않는다.
요청 간격을 두고, 일부 공고 실패해도 전체가 멈추지 않도록 예외를 격리한다.
"""

import random
import time
import urllib.parse

import requests

import constants as C
import parser as P


# ── 공통 헬퍼 ───────────────────────────────────────────────────────────────
def _sleep():
    """요청 간격(지터 포함)을 두어 과도한 요청을 피한다."""
    lo, hi = C.REQUEST_DELAY
    time.sleep(random.uniform(lo, hi))


class JobKoreaCrawler:
    """requests.Session 기반 잡코리아 수집기. Playwright는 필요 시 지연 로딩."""

    def __init__(self, logger=None):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": C.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        self.log = logger or (lambda *a, **k: None)   # logger(level,msg,url,region,job_group)
        self._pw = None        # Playwright(지연 초기화)
        self._browser = None
        self._ctx = None
        self._page = None

    # ── 세션/요청 ───────────────────────────────────────────────────────────
    def init_session(self, local_code):
        """지역 joblist를 1회 GET하여 세션 쿠키(ASP.NET_SessionId 등)를 설정한다."""
        url = C.JOBLIST_URL.format(local=local_code)
        try:
            self.s.get(url, timeout=C.REQUEST_TIMEOUT)
            return url
        except requests.RequestException as e:
            self.log("ERROR", f"세션 초기화 실패: {e}", url, "", "")
            return url

    def _post(self, url, data, referer):
        """form-encoded POST(공통). 실패 시 None 반환(예외 격리)."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        }
        for attempt in range(C.MAX_RETRY + 1):
            try:
                r = self.s.post(url, data=urllib.parse.urlencode(data),
                                headers=headers, timeout=C.REQUEST_TIMEOUT)
                if r.status_code == 200:
                    return r.text
                self.log("WARN", f"HTTP {r.status_code} (시도 {attempt+1})", url, "", "")
            except requests.RequestException as e:
                self.log("WARN", f"요청 예외 {e} (시도 {attempt+1})", url, "", "")
            _sleep()
        return None

    # ── 지역 전체 건수 ───────────────────────────────────────────────────────
    def fetch_region_count(self, local_code, referer):
        """지역 전체 공고 수(search_total_count, 지역 단위 공식값)를 반환(실패 시 None)."""
        body = self._post(C.SEARCHCOUNT_URL,
                          {"condition[local]": local_code, "condition[menucode]": "local"},
                          referer)
        if body is None:
            return None
        digits = "".join(ch for ch in body if ch.isdigit())
        return int(digits) if digits else None

    # ── 지역 목록(페이지네이션) ──────────────────────────────────────────────
    def iter_region_postings(self, local_code, referer, max_pages=None, seen=None):
        """
        _GI_List를 페이지 순회하며 정규공고 행(dict)을 yield.
        - 중복(같은 gno)·헤드헌팅은 건너뛴다.
        - 빈 페이지 또는 새 공고가 없으면 종료.
        """
        max_pages = max_pages or C.MAX_PAGES_PER_REGION
        seen = seen if seen is not None else set()
        for page in range(1, max_pages + 1):
            data = {
                "page": page, "condition[local]": local_code, "condition[menucode]": "",
                "direct": 0, "order": 20, "pagesize": C.PAGE_SIZE,
                "tabindex": 0, "onePick": 0, "confirm": 0, "profile": 0,
            }
            html_fragment = self._post(C.GILIST_URL, data, referer)
            if not html_fragment:
                self.log("WARN", f"목록 페이지 {page} 응답 없음", C.GILIST_URL, "", "")
                break
            rows = P.parse_listing_rows(html_fragment)
            if not rows:
                break
            new_count = 0
            for row in rows:
                if row["gno"] in seen:
                    continue
                seen.add(row["gno"])
                new_count += 1
                yield row
            if new_count == 0:   # 새 공고 없음 → 사실상 끝
                break
            _sleep()

    # ── 상세 ────────────────────────────────────────────────────────────────
    def fetch_detail(self, gno):
        """상세 페이지 HTML을 GET(실패 시 None)."""
        url = C.DETAIL_URL.format(gno=gno)
        for attempt in range(C.MAX_RETRY + 1):
            try:
                r = self.s.get(url, timeout=C.REQUEST_TIMEOUT)
                if r.status_code == 200:
                    return r.text
                self.log("WARN", f"상세 HTTP {r.status_code}", url, "", "")
            except requests.RequestException as e:
                self.log("WARN", f"상세 예외 {e}", url, "", "")
            _sleep()
        return None

    # ── Playwright 폴백(상세 본문) ───────────────────────────────────────────
    def _ensure_playwright(self):
        """Playwright 브라우저+컨텍스트+페이지를 지연 초기화하고 재사용(속도)."""
        if self._page is not None:
            return True
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._ctx = self._browser.new_context(user_agent=C.USER_AGENT, locale="ko-KR")
            self._page = self._ctx.new_page()
            return True
        except Exception as e:
            self.log("ERROR", f"Playwright 초기화 실패: {e}", "", "", "")
            return False

    def fetch_body_playwright(self, url):
        """
        모던 RSC 상세의 '상세요강' 본문을 Playwright로 렌더해 텍스트로 반환(페이지 재사용).
        실패 시 '' 반환. `main` 영역이 가장 깨끗(모집분야·고용형태·급여·복리후생 포함).
        """
        if not self._ensure_playwright():
            return ""
        pg = self._page
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            for sel in ["button:has-text('상세요강')", "a:has-text('상세요강')"]:
                el = pg.query_selector(sel)
                if el:
                    try:
                        el.click(timeout=3000)
                    except Exception:
                        pass
                    break
            pg.wait_for_timeout(2000)
            for sel in ["main", "section.details-section", "#container", "article"]:
                el = pg.query_selector(sel)
                if el:
                    text = el.inner_text()
                    if text and len(text) > 100:
                        return text
            return ""
        except Exception as e:
            self.log("WARN", f"Playwright 본문 폴백 실패: {e}", url, "", "")
            # 페이지가 깨졌을 수 있으니 재생성 유도
            try:
                self._page.close(); self._page = self._ctx.new_page()
            except Exception:
                self._page = None
            return ""

    def close(self):
        """리소스 정리."""
        try:
            self.s.close()
        except Exception:
            pass
        if self._browser is not None:
            try:
                self._browser.close()
                self._pw.stop()
            except Exception:
                pass
