import requests
import pandas as pd
import xml.etree.ElementTree as ET
import time
from tqdm import tqdm

# 1. API 설정
API_KEY = 'api 키'  # 실제 키로 변경하세요
# 💡 핵심 수정: https -> http로 변경하여 포트 8080 리다이렉트 우회 시도
URL = 'http://www.youthcenter.go.kr/opi/empList.do'

# 💡 핵심 수정: 서버 방화벽 차단을 피하기 위해 브라우저 우회 헤더 추가
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 2. 분석 대상 지역 코드 (서울 + 9개 도)
REGION_CODES = {
    '서울': '003002001', '경기': '003002008', '강원': '003002009',
    '충북': '003002010', '충남': '003002011', '전북': '003002012',
    '전남': '003002013', '경북': '003002014', '경남': '003002015',
    '제주': '003002016'
}

# 3. 키워드 기반 카테고리 자동 분류 함수
def classify_policy(name, desc):
    text = f"{name} {desc}".lower()
    keywords = {
        '일자리': ['취업', '채용', '고용', '구직', '일자리', '면접'],
        '직무교육': ['교육', '훈련', '자격증', '실습', '역량', '학원', '인재양성'],
        '주거지원': ['주거', '월세', '전세', '임대', '주택', '보증금', '기숙사'],
        '창업지원': ['창업', '스타트업', '사업화', '창업공간'],
        '복지': ['수당', '건강', '심리', '교통비', '식비', '포인트', '지원금'],
        '참여 프로그램': ['동아리', '네트워크', '멘토링', '커뮤니티', '참여', '공모전']
    }
    matched_categories = []
    for category, kw_list in keywords.items():
        if any(kw in text for kw in kw_list):
            matched_categories.append(category)
    return ', '.join(matched_categories) if matched_categories else '기타'

# 4. 데이터 수집 실행 함수
def fetch_youth_policies():
    all_policies = []
    print("\n🚀 [우회 모드] 온통청년 API 청년정책 데이터 수집을 시작합니다...\n")
    
    for region_name, region_code in tqdm(REGION_CODES.items(), desc="전체 지역 수집 진행도"):
        page = 1
        
        while True:
            params = {
                'openApiVlak': API_KEY,
                'display': '100',
                'pageIndex': str(page),
                'srchPolyBizSecd': region_code
            }
            
            try:
                # 💡 핵심 수정: headers 추가 및 timeout=5 설정으로 무한 대기 방지
                response = requests.get(URL, params=params, headers=HEADERS, timeout=5)
                root = ET.fromstring(response.text)
                
                emp_list = root.findall('.//emp')
                if not emp_list:
                    break
                    
                for emp in emp_list:
                    poly_name = emp.findtext('polyBizSjnm', default='')
                    poly_desc = emp.findtext('polyItcnCn', default='')
                    
                    category = classify_policy(poly_name, poly_desc)
                    
                    all_policies.append({
                        '지역': region_name,
                        '정책명': poly_name,
                        '정책설명': poly_desc,
                        '분류': category
                    })
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"\n❌ 에러 발생 ({region_name} - {page}페이지): {e}")
                break
                
    print(f"\n✅ 데이터 수집 및 자동 분류 완료! (총 {len(all_policies)}건)")
    return pd.DataFrame(all_policies)

# 5. 실행 및 결과 저장
df_policies = fetch_youth_policies()

if not df_policies.empty:
    print("\n🔍 수집된 데이터 샘플:")
    print(df_policies.head())
    df_policies.to_csv('youth_policies_categorized.csv', index=False, encoding='utf-8-sig')
    print("\n💾 TM 폴더 안에 'youth_policies_categorized.csv' 파일이 성공적으로 저장되었습니다!")
else:
    print("\n⚠️ 수집된 데이터가 없습니다. 네트워크 환경을 변경(예: 스마트폰 핫스팟 연결 등) 후 다시 시도해 주세요.")