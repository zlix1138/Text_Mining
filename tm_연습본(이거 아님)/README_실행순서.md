# 텍스트마이닝 기말 프로젝트 분석 노트북 실행 순서

## 입력 파일
노트북과 같은 폴더에 아래 CSV 2개를 두고 실행하세요.

- youth_policies_categorized.csv
- youth_policies_summary_by_region_category.csv

## 실행 순서

1. 01_policy_preprocessing.ipynb
   - 정책 데이터 전처리
   - 분석 텍스트 생성
   - 지역×분류 피벗표 생성

2. 02_policy_scoring_mismatch.ipynb
   - 정책지원점수 산출
   - 가중치/정규화 기준 정리
   - 채용공고 기반 일자리취약도 파일이 있으면 정책 미스매치 점수 계산

3. 03_policy_textmining_analysis.ipynb
   - 키워드 빈도 분석
   - 지역별 TF-IDF 분석
   - LDA 토픽모델링
   - 시각화 PNG 저장

## 선택 입력 파일

채용공고 분석팀 결과가 나오면 아래 파일명을 사용하세요.

- job_region_scores.csv

필수 컬럼:

- 지역
- 일자리취약도

없으면 02번 노트북에서 `job_region_scores_template.csv` 템플릿을 자동 생성합니다.

## 설치 라이브러리

```bash
pip install pandas numpy matplotlib scikit-learn
```

## 산출물

실행 결과는 `outputs/` 폴더에 CSV와 PNG 파일로 저장됩니다.