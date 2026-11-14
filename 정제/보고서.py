import io
import json

import pandas as pd

from 정제.일반규칙 import _as_text, normalize_numeric_value


RULE_LABELS = {
    "trim_invisible": "가. 앞뒤 공백과 보이지 않는 글자를 뗀다",
    "blank_tokens": "나. 빈칸을 뜻하는 표기를 빈칸으로 맞춘다",
    "date_columns": "다. 날짜로 읽히는 칸은 YYYY-MM-DD로 맞춘다",
    "numeric_columns": "라. 숫자로 읽히는 칸은 쉼표와 단위 글자를 뗀다",
    "case_variants": "마. 대소문자·띄어쓰기만 다른 표기를 하나로 맞춘다",
    "duplicate_rows": "바. 모든 칸이 같은 줄은 하나만 남긴다",
    "outlier_flags": "사. 숫자 칸의 음수와 동떨어진 값은 _표시 칸에 적는다",
}


def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None

    candidate = normalize_numeric_value(value)
    if candidate is None:
        return None
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def build_side_by_side(original_df, cleaned_df, selected_columns):
    if not selected_columns:
        return pd.DataFrame()

    original_df = original_df.reset_index(drop=True)
    cleaned_df = cleaned_df.reset_index(drop=True)

    frames = []
    for column in selected_columns:
        original_series = original_df[column].astype("object")
        cleaned_series = cleaned_df[column].astype("object")
        diff_series = []
        for before, after in zip(original_series, cleaned_series):
            if str(before) == str(after):
                diff_series.append("변경 없음")
            else:
                diff_series.append(f"{before} → {after}")
        frames.append(
            pd.DataFrame(
                {
                    f"{column} / 원본": original_series,
                    f"{column} / 정리본": cleaned_series,
                    f"{column} / 차이": diff_series,
                }
            )
        )

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


def _describe_numeric_column(series):
    numeric_values = [value for value in series.map(_safe_float).dropna().tolist()]
    if not numeric_values:
        return {
            "평균": None,
            "합계": None,
            "읽힌 줄 수": 0,
            "설명": "숫자로 읽힌 값이 없어 평균과 합계를 계산하지 않았습니다.",
            "기준": "평균은 숫자로 읽힌 0줄만 계산했습니다.",
        }

    avg_value = sum(numeric_values) / len(numeric_values)
    total_value = sum(numeric_values)
    return {
        "평균": avg_value,
        "합계": total_value,
        "읽힌 줄 수": len(numeric_values),
        "설명": f"평균은 숫자로 읽힌 {len(numeric_values)}줄만 계산했습니다. 합계는 같은 기준으로 {len(numeric_values)}줄의 합입니다.",
        "기준": f"평균과 합계는 숫자로 읽힌 {len(numeric_values)}줄만 기준으로 계산했습니다.",
    }


def _describe_text_column(series):
    text_values = series.map(_as_text).dropna()
    if text_values.empty:
        return pd.DataFrame(columns=["값", "건수", "비율"]), "글자 값이 없어 분포를 계산하지 않았습니다.", "값마다 건수와 비율은 문자가 남은 줄만 기준으로 계산했습니다."

    counts = text_values.value_counts()
    distribution = pd.DataFrame(
        {
            "값": counts.index.astype(str),
            "건수": counts.to_numpy(dtype=int),
            "비율": (counts / counts.sum()).round(6).to_numpy(),
        }
    )
    top = ", ".join(
        f"{row['값']}({row['건수']}/{row['비율']:.2%})" for _, row in distribution.head(3).iterrows()
    )
    return distribution, f"이 칸의 값 분포는 {top} 순으로 보입니다.", f"값마다 건수와 비율은 비어 있지 않은 {len(text_values)}줄만 기준으로 계산했습니다."


def build_report_summary(original_df, cleaned_df, selected_columns, numeric_columns):
    rows = []
    distributions = {}

    for column in selected_columns:
        original_series = original_df[column].astype("object")
        cleaned_series = cleaned_df[column].astype("object")
        diff_count = int((original_series.astype(str).fillna("") != cleaned_series.astype(str).fillna("")).sum())
        unique_count = int(cleaned_series.dropna().nunique())

        if column in numeric_columns:
            numeric_summary = _describe_numeric_column(cleaned_series)
            rows.append(
                {
                    "칸": column,
                    "종류": "숫자",
                    "줄 수": len(cleaned_df),
                    "평균": numeric_summary["평균"],
                    "합계": numeric_summary["합계"],
                    "서로 다른 값 수": unique_count,
                    "차이 값 수": diff_count,
                    "설명": numeric_summary["설명"],
                    "기준": numeric_summary["기준"],
                }
            )
        else:
            distribution, explanation, basis = _describe_text_column(cleaned_series)
            distributions[column] = distribution
            rows.append(
                {
                    "칸": column,
                    "종류": "글자",
                    "줄 수": len(cleaned_df),
                    "평균": None,
                    "합계": None,
                    "서로 다른 값 수": unique_count,
                    "차이 값 수": diff_count,
                    "설명": explanation,
                    "기준": basis,
                }
            )

    return pd.DataFrame(rows), distributions


def build_change_log(original_df, cleaned_df, enabled_rules):
    changed_rows = []
    rule_names = ", ".join(RULE_LABELS.get(key, key) for key in enabled_rules)

    for column in original_df.columns:
        original_series = original_df[column].astype("object")
        cleaned_series = cleaned_df[column].astype("object")
        for idx in range(len(original_series)):
            before = original_series.iloc[idx]
            after = cleaned_series.iloc[idx]
            if str(before) != str(after):
                changed_rows.append(
                    {
                        "줄": idx + 1,
                        "칸": column,
                        "전": before,
                        "후": after,
                        "규칙": rule_names,
                    }
                )

    return pd.DataFrame(changed_rows)


def export_settings_json(rule_state, date_columns, numeric_columns, selected_case_groups, report_columns):
    payload = {
        "rule_state": rule_state,
        "date_columns": list(date_columns),
        "numeric_columns": list(numeric_columns),
        "selected_case_groups": list(selected_case_groups),
        "report_columns": list(report_columns),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def load_settings_json(file_obj):
    return json.loads(file_obj.getvalue().decode("utf-8"))


def build_workbook_bytes(cleaned_df, change_log_df, summary_df, enabled_rules):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        cleaned_df.to_excel(writer, sheet_name="정리본", index=False)

        if change_log_df is not None and not change_log_df.empty:
            change_log_df.to_excel(writer, sheet_name="변경 기록", index=False)
        else:
            pd.DataFrame([{"줄": None, "칸": None, "전": None, "후": None, "규칙": None}]).to_excel(
                writer,
                sheet_name="변경 기록",
                index=False,
            )

        summary_rows = [{"항목": "켜진 규칙", "값": ", ".join(RULE_LABELS.get(rule, rule) for rule in enabled_rules)}]
        for _, row in summary_df.iterrows():
            if row["종류"] == "숫자":
                summary_rows.append(
                    {
                        "항목": f"{row['칸']} (숫자)",
                        "값": f"평균={row['평균']} / 합계={row['합계']} / 서로 다른 값 수={row['서로 다른 값 수']} / 차이 값 수={row['차이 값 수']} / {row['설명']}",
                    }
                )
            else:
                summary_rows.append(
                    {
                        "항목": f"{row['칸']} (글자)",
                        "값": f"서로 다른 값 수={row['서로 다른 값 수']} / 차이 값 수={row['차이 값 수']} / {row['설명']}",
                    }
                )
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="요약", index=False)

    return buffer.getvalue()
