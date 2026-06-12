# 텍스트마이닝 코드 진행 설명

## 1. 내가 맡은 작업 범위
채용공고 텍스트를 활용해 지역별 청년 일자리 특성을 분석하는 파트입니다. 구체적으로는 다음 세 가지를 진행했습니다.

1. 채용공고 키워드 빈도 및 TF-IDF 분석
2. NMF 기반 토픽모델링
3. 지역별·직무군별 비교 시각화 및 해석 문장 정리

## 2. 사용 데이터
- `quality_jobs_clean.csv`
- 분석 건수: 6,575건
- 주요 컬럼: `title`, `task_description`, `qualification`, `preference`, `benefits`, `region`, `job_group`

텍스트 분석에는 채용공고 제목, 담당업무, 지원자격, 우대사항, 복리후생 텍스트를 결합해서 사용했습니다.

## 3. 코드에서 한 작업

### 3-1. 텍스트 결합
채용공고의 여러 텍스트 컬럼을 하나로 합쳐 `analysis_text` 컬럼을 만들었습니다.

사용 컬럼:
- 제목: `title`
- 담당업무: `task_description`
- 지원자격: `qualification`
- 우대사항: `preference`
- 복리후생: `benefits`

### 3-2. 텍스트 전처리
정규표현식을 이용해 한글, 영어, 숫자 중심의 단어만 남기고, 채용공고에 반복적으로 등장하지만 분석 의미가 낮은 단어를 불용어로 제거했습니다.

제거 예시:
- 채용, 모집, 공고, 담당업무, 지원자격, 우대사항
- 사람인, 잡코리아, 접수, 이메일, 제출서류
- 서울, 경기, 충북 등 단순 지역명

### 3-3. 키워드 빈도 분석
`CountVectorizer`를 사용해 전체 채용공고에서 많이 등장하는 단어와 2단어 조합을 추출했습니다.

출력 파일:
- `01_keyword_frequency_top50.csv`

### 3-4. TF-IDF 분석
`TfidfVectorizer`를 사용해 단순히 많이 나온 단어가 아니라, 채용공고의 특성을 설명하는 데 상대적으로 중요한 키워드를 추출했습니다.

출력 파일:
- `02_global_tfidf_top50.csv`
- `03_region_distinctive_tfidf_top15.csv`
- `04_jobgroup_distinctive_tfidf_top15.csv`

### 3-5. 토픽모델링
`NMF` 모델을 사용해 채용공고 텍스트를 6개 주제로 요약했습니다.

토픽명:
1. 복지·근무조건
2. 생산·물류·현장직
3. 사무·데이터·분석역량
4. 서비스·상담·매장/호텔
5. 엔지니어·연구개발·품질
6. 마케팅·콘텐츠·브랜드

출력 파일:
- `05_topic_keywords.csv`
- `06_region_topic_distribution_percent.csv`
- `07_jobgroup_topic_distribution_percent.csv`

### 3-6. 시각화
분석 결과를 발표자료에 넣기 쉽게 PNG 차트로 저장했습니다.

출력 차트:
- `chart_01_global_tfidf_top20.png`
- `chart_02_region_topic_distribution.png`
- `chart_03_jobgroup_topic_distribution.png`
- `chart_04_region_distinctive_keywords_table.png`

## 4. 분석 결과 요약
전체 채용공고에서는 복지, 혜택, 휴무, 연차 등 근무조건 키워드와 생산, 공정관리, 품질관리, 물류관리 등 직무 특성 키워드가 함께 높게 나타났습니다.

지역별로는 서울은 마케팅·콘텐츠·브랜드 관련 키워드가 두드러졌고, 충북·충남·경북은 생산·공정·품질·반도체·엔지니어 관련 키워드가 강했습니다. 제주도는 호텔, 바리스타, 프론트, 안내데스크 등 관광·서비스업 관련 키워드가 상대적으로 높게 나타났습니다.

따라서 채용공고 텍스트는 지역별 산업구조와 직무 구성 차이를 보여주며, 청년 일자리 매력도를 해석할 때 단순 공고 수뿐 아니라 근무조건과 직무의 질적 특성도 함께 고려해야 한다고 정리할 수 있습니다.


