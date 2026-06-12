# 온통청년 정책 데이터 개인 소프로젝트용 노트북

이 노트북들은 팀원 채용공고 스코어링 파일 `job_region_scores.csv` 없이 실행되도록 수정한 버전입니다.

## 실행 순서

1. `01_policy_preprocessing_solo.ipynb`
   - 온통청년 정책 CSV 로드
   - 결측/중복/텍스트 잡음 정리
   - 정책 재분류
   - `outputs/policy_preprocessed_solo.csv` 생성

2. `02_policy_scoring_keyword_fit_solo.ipynb`
   - 정책 공급 점수 계산
   - 일자리 문제 유형 키워드 사전 기반 정책 대응도 계산
   - `outputs/policy_region_score_solo.csv` 생성
   - `outputs/policy_issue_region_coverage_solo.csv` 생성

3. `03_policy_textmining_analysis_solo.ipynb`
   - 키워드 빈도 분석
   - 지역별 TF-IDF 분석
   - 분류별 TF-IDF 분석
   - LDA 토픽모델링
   - 시각화 PNG 저장

## 입력 파일

노트북과 같은 폴더에 아래 파일을 둡니다.

```text
youth_policies_categorized.csv
```

## 설치 패키지

```bash
pip install pandas numpy matplotlib scikit-learn
```

## 기존 버전과 달라진 점

기존 `02_policy_scoring_mismatch.ipynb`는 팀원 채용공고 분석 결과인 `job_region_scores.csv`를 요구했습니다. 이 개인 소프로젝트용 버전은 해당 파일을 사용하지 않습니다.

대신 온통청년 정책 텍스트에서 다음을 계산합니다.

- 지역별 정책 공급 점수
- 고용기회, 임금소득, 직무성장, 워라밸환경, 주거안정, 창업생태계, 참여관계 키워드 대응도
- 지역별 정책 대응 부족 분야
- 지역별·분류별 TF-IDF 키워드
- LDA 토픽 분포

## 보고서 해석 주의

이 분석은 실제 채용공고 원자료와 직접 결합한 미스매치 분석이 아니라, 채용공고 분석에서 일반적으로 확인하는 일자리 문제 유형을 기준으로 온통청년 정책 텍스트가 얼마나 대응하는지를 보는 정책 키워드 대응도 분석입니다. 따라서 보고서에는 “채용공고 분석 결과를 직접 결합한 미스매치”가 아니라 “정책 텍스트 기반 일자리 문제 대응도”로 표현하는 것이 적절합니다.