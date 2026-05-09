from __future__ import annotations

import pandas as pd
import streamlit as st
from pandas.api.types import is_object_dtype


def prepare_display_dataframe(data, max_rows: int | None = None) -> pd.DataFrame:
    """
    Streamlit 표 표시용 데이터 정리.

    object 컬럼에 문자/숫자가 섞이면 pyarrow 경고가 길게 뜰 수 있음.
    화면에 보여주는 표는 문자/숫자 섞인 컬럼을 문자열로 통일해서 안전하게 표시함.
    """

    if data is None:
        return pd.DataFrame()

    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        try:
            df = pd.DataFrame(data)
        except Exception:
            df = pd.DataFrame({"value": [str(data)]})

    if max_rows is not None:
        df = df.head(max_rows).copy()

    df.columns = [str(c) for c in df.columns]

    for col in df.columns:
        try:
            dtype_name = str(df[col].dtype)

            if is_object_dtype(df[col]) or dtype_name == "category":
                df[col] = df[col].map(lambda x: "" if pd.isna(x) else str(x))

        except Exception:
            df[col] = df[col].astype(str)

    return df


def safe_dataframe(data, max_rows: int | None = None, **kwargs):
    """
    st.dataframe 대신 쓰는 안전 출력 함수.
    """

    if data is None:
        st.info("표시할 데이터가 없습니다.")
        return

    try:
        total_rows = len(data)
    except Exception:
        total_rows = 1

    df = prepare_display_dataframe(data, max_rows=max_rows)

    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    st.dataframe(df, **kwargs)

    if max_rows is not None and total_rows > max_rows:
        st.caption(
            f"속도 보호를 위해 전체 {total_rows:,}건 중 상위 {max_rows:,}건만 화면에 표시합니다."
        )
        