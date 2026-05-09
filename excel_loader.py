import pandas as pd


REQUIRED_SHEETS = ["stores", "products", "inventory", "routes"]


def _clean_basic_columns(df):
    """컬럼명 앞뒤 공백만 제거. 기존 코드 호환을 위해 영문 소문자 변환은 하지 않음."""
    if df is None:
        return pd.DataFrame()

    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def load_excel_file(uploaded_file):
    """엑셀 파일 로딩 속도 개선판.

    기존에는 같은 uploaded_file을 대상으로 pd.ExcelFile + pd.read_excel을 여러 번 호출했다.
    이 버전은 ExcelFile 객체를 한 번 만든 뒤 parse로 시트를 읽는다.
    config 같은 추가 시트도 같이 읽어서 기존 자동 분석 조건 기능을 살린다.
    """

    excel_file = pd.ExcelFile(uploaded_file, engine="openpyxl")
    sheet_names = excel_file.sheet_names

    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in sheet_names]

    if missing_sheets:
        return None, missing_sheets

    data = {}

    # 필수 시트 먼저 읽기
    for sheet in REQUIRED_SHEETS:
        data[sheet] = _clean_basic_columns(excel_file.parse(sheet_name=sheet))

    # config 등 추가 시트도 읽기. 자동 조건 결정 기능에서 사용 가능.
    for sheet in sheet_names:
        if sheet in data:
            continue
        try:
            data[sheet] = _clean_basic_columns(excel_file.parse(sheet_name=sheet))
        except Exception:
            # 추가 시트는 실패해도 앱 전체가 멈추지 않게 함
            pass

    return data, []
