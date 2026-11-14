import io
import re
from typing import Optional

import pandas as pd


_NUMERIC_PATTERN = re.compile(r"^[+-]?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?%?$")


def _as_text(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


def _is_numeric_like(value):
    text = _as_text(value)
    if text is None:
        return False

    candidate = text
    if candidate.startswith("(") and candidate.endswith(")"):
        candidate = "-" + candidate[1:-1]
    candidate = candidate.replace(",", "")
    if candidate.endswith("%"):
        candidate = candidate[:-1]

    return bool(_NUMERIC_PATTERN.fullmatch(candidate))


def load_dataframe(uploaded_file, sheet_name: Optional[str] = None, header_row: int = 1):
    """업로드된 파일을 원본 문자열 그대로 읽어 DataFrame으로 반환한다."""
    if uploaded_file is None:
        raise ValueError("업로드된 파일이 없습니다.")

    file_name = uploaded_file.name.lower()

    if file_name.endswith(".csv"):
        file_obj = io.StringIO(uploaded_file.getvalue().decode("utf-8-sig"))
        return pd.read_csv(
            file_obj,
            header=header_row - 1,
            dtype=str,
            keep_default_na=False,
            na_values=[],
        )

    if file_name.endswith(".xlsx") or file_name.endswith(".xls"):
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_to_read = sheet_name or excel_file.sheet_names[0]
        return pd.read_excel(
            uploaded_file,
            sheet_name=sheet_to_read,
            header=header_row - 1,
            dtype=str,
            engine="openpyxl",
        )

    raise ValueError("지원하지 않는 파일 형식입니다. .xlsx 또는 .csv만 허용합니다.")


def summarize_columns(df: pd.DataFrame):
    """열 단위로 빈칸 수, 고유값 수, 숫자 비율, 예시값을 계산한다."""
    rows = []

    for column_name in df.columns:
        series = df[column_name].copy()
        cleaned = series.map(_as_text)
        blank_count = int(cleaned.isna().sum())
        non_blank = cleaned.dropna()
        unique_count = int(non_blank.nunique())
        numeric_count = int(non_blank.map(_is_numeric_like).sum())
        total_count = int(len(cleaned))
        numeric_ratio = numeric_count / total_count if total_count else 0.0
        examples = []
        for value in non_blank.head(3):
            examples.append(str(value))
        rows.append(
            {
                "칸 이름": str(column_name),
                "빈칸 수": blank_count,
                "값의 종류 수": unique_count,
                "숫자로 읽히는 값의 비율": numeric_ratio,
                "예시 값 셋": " / ".join(examples) if examples else "",
            }
        )

    return pd.DataFrame(rows)
