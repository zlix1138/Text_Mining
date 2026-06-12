# -*- coding: utf-8 -*-
"""
입력 파일:
- quality_jobs_clean.csv
- quantity_region_jobgroup.csv

출력:
- 키워드 빈도 CSV
- 전체 TF-IDF CSV
- 지역별/직무군별 차별 TF-IDF CSV
- 토픽 키워드 CSV
- 지역별/직무군별 토픽 비중 CSV
- 발표/보고서용 차트 PNG
"""

from pathlib import Path
import re
import warnings

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import NMF

warnings.filterwarnings("ignore")


# 1. 경로 설정

BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
INPUT_PATH = BASE_DIR.parent / "quality_jobs_clean.csv"
# 파일을 같은 폴더에서 실행하는 경우도 대비
if not INPUT_PATH.exists():
    INPUT_PATH = BASE_DIR / "quality_jobs_clean.csv"

OUTPUT_DIR = BASE_DIR / "textmining_outputs"
if BASE_DIR.name == "textmining_outputs":
    OUTPUT_DIR = BASE_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 2. 한글 폰트 설정

def set_korean_font():
    """Windows/Mac/Linux 환경별 한글 폰트 후보를 설정한다."""
    import matplotlib.font_manager as fm

    candidates = [
        "Malgun Gothic",       # Windows
        "AppleGothic",         # macOS
        "NanumGothic",         # Linux/Colab
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False

set_korean_font()


# 3. 데이터 로드 및 텍스트 결합

df = pd.read_csv(INPUT_PATH)

TEXT_COLS = [
    "title",
    "task_description",
    "qualification",
    "preference",
    "benefits",
]

# 실제 존재하는 컬럼만 사용
TEXT_COLS = [col for col in TEXT_COLS if col in df.columns]

# 결측값을 빈 문자열로 바꾼 뒤 분석용 텍스트 생성
df["analysis_text"] = df[TEXT_COLS].fillna("").agg(" ".join, axis=1)

# 너무 짧은 텍스트 제거
df = df[df["analysis_text"].str.len() >= 10].copy()

print(f"분석 공고 수: {len(df):,}건")
print(f"분석 지역: {df['region'].nunique()}개")
print(f"직무군: {df['job_group'].nunique()}개")


# 4. 텍스트 정제 함수 및 불용어 설정

STOPWORDS = set("""
채용 모집 공고 담당업무 담당 업무 주요업무 주요 업무 지원자격 자격요건 우대사항 우대 조건 근무지 근무지역
근무조건 근무 시간 회사 소개 기업 소개 지원 바랍니다 가능자 가능 우대자 이상 이하 관련 해당 기타 등 및 또는 위한 통한 있는 없는
합니다 됩니다 입니다 바랍니다 확인해주세요 상세요강 확인 지원부문별 상이 수 있음 예정 기간 입사 인턴십 전형 서류 면접 최종
사람인 잡코리아 워크넷 홈페이지 접수 이메일 전화 문의 제출 서류 이력서 자기소개서 포트폴리오
신입 경력 신입경력 정규직 계약직 인턴 학력 무관 대졸 고졸 초대졸 졸업 예정자
서울 경기도 경기 강원도 강원 충청북도 충북 충청남도 충남 전라북도 전북 전라남도 전남 경상북도 경북 경상남도 경남 제주도 제주
강남구 서초구 송파구 마포구 성동구 종로구 중구 구로구 금천구 성남시 수원시 용인시 화성시 안산시 천안시 청주시 전주시 창원시
""".split())

# 조사/어미/기호 제거 후 의미 있는 토큰만 남김
TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9+#./]{2,}")

def clean_text(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"\s+", " ", text)
    tokens = TOKEN_PATTERN.findall(text)
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) >= 2]
    return " ".join(tokens)

# 정제된 텍스트 생성
df["clean_text"] = df["analysis_text"].map(clean_text)
df = df[df["clean_text"].str.len() > 0].copy()


# 5. 키워드 빈도 분석

count_vec = CountVectorizer(
    max_features=3000,
    ngram_range=(1, 2),
    min_df=3,
    max_df=0.85,
)
count_mat = count_vec.fit_transform(df["clean_text"])
count_terms = np.array(count_vec.get_feature_names_out())
count_sum = np.asarray(count_mat.sum(axis=0)).ravel()

keyword_freq = (
    pd.DataFrame({"keyword": count_terms, "count": count_sum})
    .sort_values("count", ascending=False)
    .reset_index(drop=True)
)
keyword_freq.insert(0, "rank", keyword_freq.index + 1)
keyword_freq.head(50).to_csv(OUTPUT_DIR / "01_keyword_frequency_top50.csv", index=False, encoding="utf-8-sig")


# 6. 전체 TF-IDF 분석

tfidf_vec = TfidfVectorizer(
    max_features=4000,
    ngram_range=(1, 2),
    min_df=3,
    max_df=0.85,
)
tfidf_mat = tfidf_vec.fit_transform(df["clean_text"])
tfidf_terms = np.array(tfidf_vec.get_feature_names_out())
mean_tfidf = np.asarray(tfidf_mat.mean(axis=0)).ravel()

global_tfidf = (
    pd.DataFrame({"keyword": tfidf_terms, "mean_tfidf": mean_tfidf})
    .sort_values("mean_tfidf", ascending=False)
    .reset_index(drop=True)
)
global_tfidf.insert(0, "rank", global_tfidf.index + 1)
global_tfidf.head(50).to_csv(OUTPUT_DIR / "02_global_tfidf_top50.csv", index=False, encoding="utf-8-sig")


# 7. 지역별/직무군별 차별 TF-IDF 키워드

def distinctive_keywords(group_col: str, top_n: int = 15) -> pd.DataFrame:
    """전체 평균보다 특정 집단에서 상대적으로 더 높은 TF-IDF 키워드를 추출한다."""
    rows = []
    global_mean = np.asarray(tfidf_mat.mean(axis=0)).ravel()

    for group_value, idx in df.groupby(group_col).groups.items():
        idx = list(idx)
        group_mean = np.asarray(tfidf_mat[idx].mean(axis=0)).ravel()
        score = group_mean - global_mean
        top_idx = score.argsort()[::-1][:top_n]
        for rank, i in enumerate(top_idx, start=1):
            rows.append({
                group_col: group_value,
                "rank": rank,
                "keyword": tfidf_terms[i],
                "group_mean_tfidf": group_mean[i],
                "global_mean_tfidf": global_mean[i],
                "distinctive_score": score[i],
            })
    return pd.DataFrame(rows)

region_kw = distinctive_keywords("region", top_n=15)
jobgroup_kw = distinctive_keywords("job_group", top_n=15)

region_kw.to_csv(OUTPUT_DIR / "03_region_distinctive_tfidf_top15.csv", index=False, encoding="utf-8-sig")
jobgroup_kw.to_csv(OUTPUT_DIR / "04_jobgroup_distinctive_tfidf_top15.csv", index=False, encoding="utf-8-sig")


# 8. NMF 토픽모델링

N_TOPICS = 6
nmf = NMF(n_components=N_TOPICS, random_state=42, init="nndsvda", max_iter=500)
doc_topic = nmf.fit_transform(tfidf_mat)
topic_word = nmf.components_

# 토픽명은 키워드를 확인한 뒤 사람이 해석해서 붙인 라벨
topic_labels = {
    0: "복지·근무조건",
    1: "생산·물류·현장직",
    2: "사무·데이터·분석역량",
    3: "서비스·상담·매장/호텔",
    4: "엔지니어·연구개발·품질",
    5: "마케팅·콘텐츠·브랜드",
}

topic_rows = []
for topic_idx, weights in enumerate(topic_word):
    top_idx = weights.argsort()[::-1][:15]
    for rank, term_idx in enumerate(top_idx, start=1):
        topic_rows.append({
            "topic_id": topic_idx + 1,
            "topic_label": topic_labels[topic_idx],
            "rank": rank,
            "keyword": tfidf_terms[term_idx],
            "weight": weights[term_idx],
        })

topic_keywords = pd.DataFrame(topic_rows)
topic_keywords.to_csv(OUTPUT_DIR / "05_topic_keywords.csv", index=False, encoding="utf-8-sig")

# 문서별 대표 토픽 부여
df["dominant_topic_id"] = doc_topic.argmax(axis=1) + 1
df["dominant_topic"] = df["dominant_topic_id"].map(lambda x: topic_labels[x - 1])

# 지역별/직무군별 토픽 비중
region_topic = (
    pd.crosstab(df["region"], df["dominant_topic"], normalize="index") * 100
).round(1)
jobgroup_topic = (
    pd.crosstab(df["job_group"], df["dominant_topic"], normalize="index") * 100
).round(1)

region_topic.to_csv(OUTPUT_DIR / "06_region_topic_distribution_percent.csv", encoding="utf-8-sig")
jobgroup_topic.to_csv(OUTPUT_DIR / "07_jobgroup_topic_distribution_percent.csv", encoding="utf-8-sig")

# 각 지역/직무군에서 가장 비중이 큰 토픽
region_dominant = region_topic.idxmax(axis=1).to_frame("dominant_topic")
region_dominant["percent"] = region_topic.max(axis=1)
region_dominant.to_csv(OUTPUT_DIR / "08_region_dominant_topic_percent.csv", encoding="utf-8-sig")

jobgroup_dominant = jobgroup_topic.idxmax(axis=1).to_frame("dominant_topic")
jobgroup_dominant["percent"] = jobgroup_topic.max(axis=1)
jobgroup_dominant.to_csv(OUTPUT_DIR / "09_jobgroup_dominant_topic_percent.csv", encoding="utf-8-sig")


# 9. 시각화

def save_global_tfidf_chart():
    top = global_tfidf.head(20).iloc[::-1]
    plt.figure(figsize=(10, 7))
    plt.barh(top["keyword"], top["mean_tfidf"])
    plt.title("전체 채용공고 TF-IDF 상위 키워드 Top 20")
    plt.xlabel("평균 TF-IDF")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart_01_global_tfidf_top20.png", dpi=200)
    plt.close()


def save_stacked_topic_chart(table: pd.DataFrame, filename: str, title: str):
    table = table.copy()
    plt.figure(figsize=(12, 7))
    bottom = np.zeros(len(table))
    x = np.arange(len(table.index))
    for col in table.columns:
        plt.bar(x, table[col].values, bottom=bottom, label=col)
        bottom += table[col].values
    plt.xticks(x, table.index, rotation=45, ha="right")
    plt.ylabel("비중(%)")
    plt.title(title)
    plt.legend(loc="center left", bbox_to_anchor=(1, 0.5))
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / filename, dpi=200)
    plt.close()


def save_region_keyword_table():
    # 지역별 상위 5개 차별 키워드를 표 이미지로 저장
    pivot = (
        region_kw[region_kw["rank"] <= 5]
        .groupby("region")["keyword"]
        .apply(lambda x: ", ".join(x))
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.axis("off")
    table = ax.table(
        cellText=pivot.values,
        colLabels=["지역", "차별 TF-IDF 키워드 Top 5"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.8)
    plt.title("지역별 차별 TF-IDF 키워드", pad=20)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart_04_region_distinctive_keywords_table.png", dpi=200)
    plt.close()

save_global_tfidf_chart()
save_stacked_topic_chart(region_topic, "chart_02_region_topic_distribution.png", "지역별 채용공고 토픽 비중")
save_stacked_topic_chart(jobgroup_topic, "chart_03_jobgroup_topic_distribution.png", "직무군별 채용공고 토픽 비중")
save_region_keyword_table()

print("분석 완료")
print(f"결과 저장 폴더: {OUTPUT_DIR}")
