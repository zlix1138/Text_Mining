# -*- coding: utf-8 -*-
"""
[통합 2단계-a] 잡코리아·사람인 '미분류' 재분류 (규칙 강화) + 5개 직군 외 직종 세분 태깅.

원칙:
- 기존 preprocess.classify_job_group / constants.JOB_GROUPS 는 수정하지 않는다(잡코리아 기존 동작 보존).
- 이미 5개 직군으로 분류된 행은 건드리지 않는다(미분류만 재시도 → 미분류는 줄기만 함).
- 강화 규칙:
    (1) 5개 직군 키워드를 확장(ENHANCED_KEYWORDS)해 제목+직종에서 1개라도 매칭되면 채택
    (2) (1) 실패 시 본문(주요업무+자격요건+우대)에서 확장 키워드 2개↑ 매칭 시 채택(노이즈 가드)
- 그래도 미분류면 5개 직군 외 직종을 other_job_hint(외식·조리/운전·배송·물류/서비스·CS/영업…)로 태깅.
  (job_group 은 '미분류' 유지 — 삭제·강제분류 아님. 범위 한정·필터 판단은 2단계-b에서.)

입력:  data/integrated_jobs.csv         (1단계 산출물)
출력:  data/integrated_reclassified.csv  (other_job_hint 컬럼 추가)
실행:  python src/reclassify.py
"""

import csv
import os
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import constants as C
import preprocess as PP

IN_CSV = C.DATA_DIR / "integrated_jobs.csv"
OUT_CSV = C.DATA_DIR / "integrated_reclassified.csv"

# ── 5개 직군 확장 키워드(기존 JOB_GROUPS keywords + 보강) ─────────────────────
_EXTRA = {
    "IT·데이터":   ["퍼블리셔", "qa엔지니어", "dba", "정보보안", "보안관제", "네트워크",
                   "시스템엔지니어", "클라우드", "전산", "임베디드", "펌웨어", "ios",
                   "android", "react", "java", "python", "si개발", "sm개발"],
    "사무·회계":   ["정산", "경리", "구매", "자재", "무역", "원가", "전산회계", "결산",
                   "자금", "감사", "경영기획", "총무회계", "회계사", "세무사"],
    "기획·마케팅": ["전략기획", "상품기획", "브랜딩", "커뮤니케이션", "그로스", "crm",
                   "퍼포먼스마케팅", "콘텐츠기획", "제휴", "프로모션기획", "광고기획"],
    "연구개발·품질": ["연구원", "시험", "평가", "실험", "임상", "인허가", "검교정",
                    "신뢰성", "품질보증", "품질관리", "분석원", "시험분석"],
    "생산·기술":   ["반도체", "조립", "포장", "가공", "금형", "사출", "cnc", "기술직",
                   "현장직", "보전", "배관", "도장", "생산직", "오퍼레이터", "plc",
                   "설비보전", "제관", "열처리", "생산기술", "전기기사", "기계설계"],
}
ENHANCED_KEYWORDS = {
    g: list(dict.fromkeys([kw.lower() for kw in cfg["keywords"]] + [e.lower() for e in _EXTRA.get(g, [])]))
    for g, cfg in C.JOB_GROUPS.items()
}

# ── 5개 직군 외 직종 세분 태그(우선순위 순; 먼저 매칭되는 라벨 채택) ──────────
OTHER_JOB_GROUPS = [
    ("외식·조리",      ["주방", "조리", "요리", "쉐프", "셰프", "홀서빙", "바리스타", "카페",
                       "레스토랑", "한정식", "파스타", "제빵", "베이커리", "식당", "뷔페",
                       "급식", "반찬", "주방보조", "찬모"]),
    ("운전·배송·물류", ["운전", "배송", "기사", "택배", "물류", "배달", "상하차", "지게차",
                       "퀵", "화물", "운송", "라이더"]),
    ("서비스·CS·상담", ["고객상담", "콜센터", "텔러", "안내데스크", "접객", "리셉션", "민원",
                       "고객센터", "cs상담", "tm", "서비스직"]),
    ("영업",          ["영업", "세일즈", "판촉", "영업관리", "영업사원"]),
    ("판매·매장",      ["판매", "매장", "캐셔", "점원", "입고", "검수", "진열", "마트",
                       "판매직", "매장관리"]),
    ("의료·보건",      ["간호", "의료", "약사", "요양", "간병", "물리치료", "병원", "치과",
                       "한의원", "수의", "방사선", "임상병리", "치위생"]),
    ("교육",          ["강사", "교사", "교육", "학원", "튜터", "지도사", "보육", "어린이집",
                       "방과후", "교습"]),
    ("건축·시설·시공", ["시공", "시설관리", "인테리어", "전기공사", "경비", "미화", "청소",
                       "방재", "조경", "토목", "건축시공", "설비기사"]),
    ("디자인",        ["디자이너", "디자인", "편집디자", "웹디자", "그래픽", "ui디자", "ux디자"]),
    ("미용·뷰티",      ["미용", "헤어", "네일", "피부관리", "에스테틱", "왁싱", "메이크업"]),
    ("금융·보험",      ["보험", "설계사", "대출상담", "펀드", "증권", "은행", "여신"]),
]


def _norm(text):
    """분류용 정규화(고용형태·상투어 제거) — preprocess 재사용."""
    return PP._normalize_for_classify(text or "")


def _enhanced_match(text):
    """확장 키워드로 (group, keyword, hits) 반환."""
    best_g, best_hits, best_kw = None, 0, ""
    for g, kws in ENHANCED_KEYWORDS.items():
        hits = [kw for kw in kws if kw in text]
        if len(hits) > best_hits:
            best_g, best_hits, best_kw = g, len(hits), hits[0]
    return best_g, best_kw, best_hits


def _match_other(text):
    """5개 직군 외 직종 라벨 best-effort 태깅(없으면 '복합·기타')."""
    for label, kws in OTHER_JOB_GROUPS:
        if any(kw in text for kw in kws):
            return label
    return "복합·기타"


# 본문 단독 매칭은 노이즈가 심해(예: '급여'/'관리'가 복지·일반설명에서 매칭) 사용하지 않는다.
# 정확도 우선: 권위 있는 신호인 '제목 + 직종태그(job_category_raw)'만 재분류 근거로 사용.
def reclassify_row(row):
    """
    미분류 행만 재분류 시도. 반환: (job_group, job_keyword, note_add, other_job_hint)
    - 제목 + 사이트 직종태그(job_category_raw)에서 확장 키워드가 매칭되면 5개 직군으로 재분류.
    - 그래도 미분류면 job_group='미분류' 유지, other_job_hint=5개 직군 외 세부직종.
    """
    title_cat = _norm(" ".join([row.get("title", ""), row.get("job_category_raw", "")]))
    g, kw, _ = _enhanced_match(title_cat)
    if g:
        return g, kw, "재분류:제목·직종(규칙강화)", ""
    # 5개 직군 외 → 세부 직종 태깅(원문 유지: 정규화 전 텍스트로 매칭)
    raw_blob = " ".join([row.get("title", ""), row.get("job_category_raw", "")]).lower()
    return "미분류", "", "", _match_other(raw_blob)


def main():
    if not IN_CSV.exists():
        print(f"⚠️  입력 없음: {IN_CSV} — 먼저 python src/integrate_schema.py 실행")
        return
    with open(IN_CSV, encoding=C.CSV_ENCODING) as f:
        rows = list(csv.DictReader(f))
    in_cols = list(rows[0].keys()) if rows else []
    out_cols = in_cols + (["other_job_hint"] if "other_job_hint" not in in_cols else [])

    reclassified = 0
    by_source_reclass = Counter()
    hint_counter = Counter()
    before_unclass = sum(1 for r in rows if r.get("job_group") == "미분류")

    for r in rows:
        r.setdefault("other_job_hint", "")
        if r.get("job_group") != "미분류":
            continue
        g, kw, note_add, hint = reclassify_row(r)
        if g != "미분류":
            r["job_group"] = g
            r["job_keyword"] = kw
            r["note"] = (r.get("note", "") + " | " + note_add).strip(" |")
            reclassified += 1
            by_source_reclass[r.get("source", "")] += 1
        else:
            r["other_job_hint"] = hint
            hint_counter[hint] += 1

    with open(OUT_CSV, "w", newline="", encoding=C.CSV_ENCODING) as f:
        w = csv.writer(f)
        w.writerow(out_cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in out_cols])

    after_unclass = sum(1 for r in rows if r.get("job_group") == "미분류")

    # ── 리포트 ──
    print("=" * 64)
    print("[통합 2단계-a] 미분류 재분류(규칙 강화) 결과")
    print("=" * 64)
    print(f"입력: {IN_CSV.name} ({len(rows)}행)")
    print(f"미분류: {before_unclass} → {after_unclass}  (재분류 {reclassified}건)")
    print(f"  재분류 출처별: {dict(by_source_reclass)}")
    print("\n[남은 미분류의 5개 직군 외 세부직종(other_job_hint)]")
    for label, n in hint_counter.most_common():
        print(f"   {label.ljust(14)} {n}")
    print(f"\n[직군 분포(재분류 후, 전체)]")
    jg = Counter(r.get("job_group", "") for r in rows)
    for g in C.JOB_GROUP_NAMES + ["미분류"]:
        print(f"   {g.ljust(12)} {jg.get(g, 0)}")
    # 출처×직군 교차(미분류 잔량 확인용)
    print(f"\n[출처별 미분류 잔량]")
    for src in ("사람인", "잡코리아"):
        tot = sum(1 for r in rows if r.get("source") == src)
        un = sum(1 for r in rows if r.get("source") == src and r.get("job_group") == "미분류")
        print(f"   {src}: {un}/{tot} ({100*un/tot:.1f}%)")
    print(f"\n산출물: {OUT_CSV}")
    print("[다음] 재분류 결과 확인 후 2단계-b 품질 필터링 진행(기준은 별도 확인).")
    print("=" * 64)


if __name__ == "__main__":
    main()
