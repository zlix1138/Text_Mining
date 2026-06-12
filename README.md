# youth-job-score — 청년 일자리 채용공고 데이터 수집

민간 채용사이트(잡코리아)의 **공개 채용공고**를 크롤링하여, 서울 + 9개 도의 청년 대상 채용공고를
텍스트마이닝 분석용 **CSV 데이터셋**으로 구축하는 비상업(수업) 연구 프로젝트입니다.

> 설계·검증 경위: [`docs/계획.md`](docs/계획.md), [`docs/jobkorea_codes.md`](docs/jobkorea_codes.md),
> [`docs/pilot_results.md`](docs/pilot_results.md)

---

## 1. 프로젝트 목적
- 지역 청년 일자리가 청년에게 얼마나 신뢰성 있는 일자리를 제공하는지 정량화하기 위한 **원천 데이터셋** 구축.
- 두 축: **일자리 양**(지역별 전체 공고 수) · **일자리 질**(상세 공고 텍스트 표본).

## 2. 수집 대상 지역
서울(기준) + 9개 도: 경기도·강원도·충청북도·충청남도·전라북도·전라남도·경상북도·경상남도·제주도.
- KOSIS 청년순이동률로 청년 유출 상위 지역 확정 시 `src/constants.py`의 `EXTRA_REGIONS`에 값만 추가(광주/충주/전주 등).

## 3. 수집 대상 직무군 (5개)
IT·데이터 / 사무·회계 / 기획·마케팅 / 연구개발·품질 / 생산·기술.
- 잡코리아 직무 필터가 비동기 SPA 전용이라 서버 필터링이 불가 → **지역 단위로 수집 후 제목·직무·본문 키워드로 사후 분류**(미분류는 `note` 기록).

## 4. 수집 컬럼 설명 (`data/jobs.csv`, UTF-8-SIG)
| 컬럼 | 설명 |
|---|---|
| source | 출처(잡코리아) |
| collected_date | 수집일 |
| url | 공고 URL(1차 중복 키) |
| company_name / title | 회사명 / 공고 제목 |
| region / region_detail | 분석 지역 / 상세 근무지 |
| job_group / job_keyword / job_category_raw | 분류 직무군 / 분류 키워드 / 원본 직무명 |
| career / education / employment_type | 경력·학력·고용형태(표준화) |
| salary / salary_min / salary_max / salary_type | 임금 원문/정제값/유형(연봉·월급·시급·회사내규·면접후결정·비공개) |
| work_time / benefits | 근무시간 / 복리후생 |
| task_description / qualification / preference | 주요업무 / 자격요건 / 우대사항 |
| deadline | 마감일 |
| search_total_count | 해당 **지역** 전체 공고 수(지역 단위 공식값) |
| raw_text | 제목+주요업무+자격요건+우대사항+복리후생 합친 분석용 텍스트 |
| is_youth_friendly | 신입가능·경력무관·인턴·교육제공 등 청년친화 신호 시 1 |
| crawl_status | success / skipped / failed |
| note | 결측·제외 사유·2차 중복 가능성 등 |

보조 CSV: `search_counts.csv`(지역별 전체/수집 건수), `crawl_log.csv`(로그), `failures.csv`(실패), `validation_report.txt`(검증).

## 5. 실행 방법
```bash
# 1) 의존성 설치
pip install -r requirements.txt
python -m playwright install chromium      # 상세 본문 폴백을 쓸 경우만 필요

# 2) 스모크 테스트 (서울에서 상세 5건)
python src/main.py --regions 서울 --limit 5

# 3) 지역별 전체 건수만 수집 (일자리 '양')
python src/main.py --counts-only

# 4) Tier-1 본 수집 (전체 지역, 지역당 550건, requests 메타데이터 — 빠름)
python src/main.py --per-region 550

# 5) Tier-2 본문 backfill (층화 표본 ~1,800건, Playwright — 텍스트마이닝 질 분석용)
python src/main.py --backfill-body --body-per-region 180

# 6) 검증
python src/validate_dataset.py

# 7) 전처리 심화 — 분석용 데이터셋 구축 (텍스트 정제·토큰화·8차원 피처)
pip install kiwipiepy
python src/build_clean.py        # → data/jobs_clean.csv
```
> 수집 정책(2-tier·균등 550/지역·전수+플래그) 상세: [`docs/collection_policy.md`](docs/collection_policy.md)

### 전처리 심화 산출물: `data/jobs_clean.csv`
`jobs.csv`(원본) 컬럼 + 분석용 파생 컬럼(총 46):
- **text_clean / nouns**: 보일러플레이트·푸터·연락처 제거한 정제 텍스트 / kiwipiepy 명사 토큰(불용어 제거) — TF-IDF·토픽모델 입력
- **salary_disclosed / career_min_year / career_max_year / deadline_norm / deadline_type**: 임금 공개여부·경력 연수·마감일 표준화
- **feat_wage / feat_work_time / feat_welfare / feat_growth / feat_youth_friendly / feat_employment_stability**: 기획서 8개 차원 키워드 피처(카운트·이진) → 스코어링 직접 입력
- **flag_low_content / flag_exclude_public / flag_dup2**: 상세내용 부족·공공기관·2차중복 플래그(삭제 대신 표시)

**분석 시 권장 필터**: 텍스트마이닝은 `flag_low_content==0 & flag_exclude_public==0` 부분집합 사용(약 3,000건).
> ⚠️ JobKorea 상세요강은 상당수가 **이미지 기반 JD**라 추출 가능한 텍스트가 구조화 필드(직무·스킬·자격증·우대·복리후생)로 제한됨 → 토큰 수가 공고마다 편차 큼(저내용은 `flag_low_content`로 식별).
- 중간 저장: 매 건 `jobs.csv`에 append → 중단되어도 결과 보존, 재실행 시 기존 url 자동 skip.
- 요청 간격: `constants.REQUEST_DELAY`(기본 1.5~3초 + 지터).

## 6. 크롤링 윤리 기준
- 로그인 없이 접근 가능한 **공개 공고만** 수집. 개인정보·연락처·이메일·지원자 정보는 **수집하지 않음**.
- 캡차·차단·접근 제한을 **우회하지 않음**(발생 시 즉시 중단). 일반 브라우저 User-Agent 사용, 비정상 우회 로직 없음.
- **robots.txt 준수**: 허용 경로(`/recruit/joblist`, `/Recruit/Home/_GI_List`, `/Recruit/Home/_SearchCount`, `/Recruit/GI_Read`)만 사용. 차단된 키워드검색(`/Search/?stext=`)·로그인·마이페이지·기업관리 영역 미사용.
- 원문 HTML을 대량 저장하지 않고 **분석에 필요한 필드만** CSV로 저장. 결과물은 원문 재배포가 아니라 데이터셋·요약.

## 7. 데이터 한계
- 단일 사이트(잡코리아) 기반 → 사이트 편향 가능.
- **직무군은 사후 분류**(사이트 필터 부재) → 일부 `미분류` 발생, 분류 정확도는 키워드 사전에 의존.
- `search_total_count`는 **지역 단위 공식값**만 신뢰. 지역×직무 건수는 표본 비율 추정.
- 목록 정렬상 초기 페이지에 프로모션 공고 편향이 일부 존재(deep 페이지네이션으로 완화).
- 상세 본문(주요업무/자격요건 등)은 모던 RSC 페이지라 **Playwright 폴백 시에만 안정 수집**. requests 단독이면 본문이 빌 수 있음(→ `note` 기록).
- 임금 비공개·회사내규 다수 → 임금 분석은 결측/별도 범주 처리 필요.

## 8. CSV 파일 설명
| 파일 | 내용 |
|---|---|
| `data/jobs.csv` | 메인 데이터셋(상세 공고 표본) |
| `data/search_counts.csv` | 지역별 전체 공고 수 + 수집 건수(일자리 양) |
| `data/crawl_log.csv` | 수집 이벤트 로그 |
| `data/failures.csv` | 실패 공고(원인 포함) |
| `data/validation_report.txt` | 검증 스크립트 결과 |

## 9. 수집 실패 시 원인과 해결
| 증상 | 원인 | 해결 |
|---|---|---|
| 상세 본문 컬럼이 빔 | requests로 RSC 본문 미렌더 | `--with-body`로 Playwright 폴백 사용 |
| 다수 `미분류` | 제목/직무 키워드 부족 | `constants.JOB_GROUPS` 키워드 보강, 상세 직무필드 파싱 추가(TODO) |
| 403/차단/캡차 | 과도 요청 | `REQUEST_DELAY` 상향, 즉시 중단 후 재개. **우회 금지** |
| 건수 0 | 세션 쿠키 미설정 | `init_session`(joblist GET)이 선행되는지 확인 |

## 10. 향후 확장 (잡코리아/사람인 API 승인 후)
- 공식 API 승인 시 `crawler.py`에 수집 함수를 추가하거나 `crawler_saramin.py` 한 파일만 추가하고,
  **CSV 스키마는 동일하게 유지**한다. `source` 컬럼으로 출처를 구분해 한 데이터셋에 통합.
- `parser.py`·`preprocess.py`·`validate_dataset.py`는 사이트와 무관하게 재사용.
