import pandas as pd


REQUIRED_SHEETS = ["stores", "products", "inventory", "routes"]


def _clean_basic_columns(df):
    """컬럼명 앞뒤 공백만 제거. 기존 코드 호환을 위해 영문 소문자 변환은 하지 않음."""
    if df is None:
        return pd.DataFrame()

    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _excel_time_to_text(value):
    """
    엑셀 시간값을 HH:MM 문자열로 변환한다.

    예)
    0.3333333333 -> 08:00
    0.9166666666 -> 22:00
    8.5 -> 08:30
    540 -> 09:00
    """
    try:
        if pd.isna(value):
            return value

        if hasattr(value, "hour") and hasattr(value, "minute"):
            return f"{int(value.hour):02d}:{int(value.minute):02d}"

        if isinstance(value, (int, float)):
            numeric = float(value)

            if 0 <= numeric < 1:
                total_minutes = int(round(numeric * 24 * 60))
                return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"

            if 1 <= numeric < 24:
                hour = int(numeric)
                minute = int(round((numeric - hour) * 60))
                return f"{hour % 24:02d}:{minute % 60:02d}"

            if 24 <= numeric < 24 * 60:
                total_minutes = int(round(numeric))
                return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"

        text = str(value).strip()

        if ":" in text:
            parts = text.split(":")
            hour = int(float(parts[0]))
            minute = int(float(parts[1])) if len(parts) > 1 else 0
            return f"{hour % 24:02d}:{minute % 60:02d}"

        numeric = float(text)

        if 0 <= numeric < 1:
            total_minutes = int(round(numeric * 24 * 60))
            return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"

        if 1 <= numeric < 24:
            hour = int(numeric)
            minute = int(round((numeric - hour) * 60))
            return f"{hour % 24:02d}:{minute % 60:02d}"

        if 24 <= numeric < 24 * 60:
            total_minutes = int(round(numeric))
            return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"

    except Exception:
        return value

    return value


def _normalize_stores_time_columns(df):
    if df is None or df.empty:
        return df

    out = df.copy()

    for col in ["available_start", "available_end"]:
        if col in out.columns:
            out[col] = out[col].apply(_excel_time_to_text)

    return out


def _normalize_transport_modes(df):
    if df is None or df.empty:
        return df

    out = df.copy()

    numeric_cols = ["base_cost", "cost_per_km", "capacity", "speed_factor"]

    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "cold_chain" in out.columns:
        out["cold_chain"] = out["cold_chain"].astype(str).str.upper().isin(["Y", "TRUE", "1", "YES"])

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

    if "stores" in data:
        data["stores"] = _normalize_stores_time_columns(data["stores"])

    # config 등 추가 시트도 읽기. 자동 조건 결정 기능에서 사용 가능.
    for sheet in sheet_names:
        if sheet in data:
            continue
        try:
            data[sheet] = _clean_basic_columns(excel_file.parse(sheet_name=sheet))
            if sheet == "transport_modes":
                data[sheet] = _normalize_transport_modes(data[sheet])
        except Exception:
            # 추가 시트는 실패해도 앱 전체가 멈추지 않게 함
            pass

    return data, []
