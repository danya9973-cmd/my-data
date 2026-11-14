import re
from collections import defaultdict

import pandas as pd


BLANK_TOKENS = {"-", "·", "n/a", "na", "없음", "null", "공백만"}
NUMERIC_SUFFIXES = ("원", "점", "건", "개", "분", "%")


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value)
    text = text.replace("\ufeff", "").replace("\x00", "")
    text = re.sub(r"[\u200b-\u200d\u2060]", "", text)
    text = text.strip()
    if text == "":
        return None
    return text


def _collapse_spaces(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value).strip())


def _blank_like(value):
    text = _as_text(value)
    if text is None:
        return True
    normalized = text.lower()
    return normalized in BLANK_TOKENS or text.strip() == ""


def is_numeric_like_text(value):
    text = _as_text(value)
    if text is None:
        return False

    candidate = text
    if candidate.startswith("(") and candidate.endswith(")"):
        candidate = "-" + candidate[1:-1]
    candidate = candidate.replace(",", "")
    for suffix in NUMERIC_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            break
    candidate = candidate.strip()
    if candidate == "":
        return False

    return bool(re.fullmatch(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$", candidate))


def is_date_like_text(value):
    text = _as_text(value)
    if text is None:
        return False

    for pattern in [
        r"^\d{4}-\d{1,2}-\d{1,2}$",
        r"^\d{4}/\d{1,2}/\d{1,2}$",
        r"^\d{4}\.\d{1,2}\.\d{1,2}$",
    ]:
        if re.fullmatch(pattern, text):
            try:
                pd.to_datetime(text, errors="raise")
                return True
            except (TypeError, ValueError):
                return False
    return False


def trim_invisible_and_space(value):
    if value is None:
        return None
    text = str(value)
    text = text.replace("\ufeff", "").replace("\x00", "")
    text = re.sub(r"[\u200b-\u200d\u2060]", "", text)
    text = text.strip()
    return text if text != "" else None


def normalize_blank_tokens(value):
    text = _as_text(value)
    if text is None:
        return None
    if text.lower() in BLANK_TOKENS or text.strip() == "":
        return None
    return text


def normalize_date_value(value):
    text = _as_text(value)
    if text is None:
        return value
    if is_date_like_text(text):
        try:
            return pd.to_datetime(text, errors="raise").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return value
    return value


def normalize_numeric_value(value):
    text = _as_text(value)
    if text is None:
        return value

    candidate = text
    if candidate.startswith("(") and candidate.endswith(")"):
        candidate = "-" + candidate[1:-1]
    candidate = candidate.replace(",", "")
    for suffix in NUMERIC_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            break
    candidate = candidate.strip()
    if is_numeric_like_text(candidate):
        return candidate
    return value


def detect_column_types(df, numeric_threshold=0.8, date_threshold=0.8):
    date_columns = []
    numeric_columns = []
    for column in df.columns:
        series = df[column].dropna()
        if series.empty:
            continue
        numeric_ratio = series.map(is_numeric_like_text).mean()
        date_ratio = series.map(is_date_like_text).mean()
        if numeric_ratio >= numeric_threshold:
            numeric_columns.append(str(column))
        if date_ratio >= date_threshold:
            date_columns.append(str(column))
    return date_columns, numeric_columns


def build_case_variant_groups(df):
    grouped = defaultdict(set)
    for column in df.columns:
        for value in df[column].astype("object"):
            text = _as_text(value)
            if text is None:
                continue
            key = _collapse_spaces(text).lower()
            grouped[key].add(str(value))

    rows = []
    for key, raw_values in sorted(grouped.items()):
        vals = sorted({str(v) for v in raw_values})
        if len(vals) <= 1:
            continue
        rows.append(
            {
                "묶음": key,
                "원본 값들": ", ".join(vals[:10]) + (" ..." if len(vals) > 10 else ""),
                "개수": len(vals),
            }
        )
    return rows


def normalize_case_variants(value, selected_groups):
    text = _as_text(value)
    if text is None:
        return value
    key = _collapse_spaces(text).lower()
    if key in selected_groups:
        return key
    return value


def flag_numeric_outliers(df, numeric_columns):
    result = df.copy()
    if "_표시" not in result.columns:
        result["_표시"] = ""

    for column in numeric_columns:
        if column not in result.columns:
            continue

        values = []
        for value in result[column].astype("object"):
            text = _as_text(value)
            if text is None:
                continue
            normalized = normalize_numeric_value(value)
            if normalized is None:
                continue
            try:
                values.append(float(normalized))
            except (TypeError, ValueError):
                continue

        if not values:
            continue

        series = pd.Series(values)
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 3 * iqr
        upper_bound = q3 + 3 * iqr

        for idx, value in result[column].items():
            text = _as_text(value)
            if text is None:
                continue
            normalized = normalize_numeric_value(value)
            if normalized is None:
                continue
            try:
                numeric_value = float(normalized)
            except (TypeError, ValueError):
                continue

            reasons = []
            if numeric_value < 0:
                reasons.append(f"{column} 음수")
            if numeric_value < lower_bound or numeric_value > upper_bound:
                reasons.append(f"{column} 동떨어진 값")

            if reasons:
                current = str(result.at[idx, "_표시"]).strip()
                if current:
                    current = current + "; "
                result.at[idx, "_표시"] = current + "; ".join(reasons)

    return result


def _apply_valuewise(df, func):
    result = df.copy()
    for column in result.columns:
        result[column] = result[column].map(func)
    return result


def rule_trim_invisible(df):
    return _apply_valuewise(df, trim_invisible_and_space)


def rule_blank_tokens(df):
    return _apply_valuewise(df, normalize_blank_tokens)


def rule_date_columns(df, date_columns):
    result = df.copy()
    for column in date_columns:
        if column in result.columns:
            result[column] = result[column].map(normalize_date_value)
    return result


def rule_numeric_columns(df, numeric_columns):
    result = df.copy()
    for column in numeric_columns:
        if column in result.columns:
            result[column] = result[column].map(normalize_numeric_value)
    return result


def rule_case_variants(df, selected_case_groups):
    result = df.copy()
    selected = set(selected_case_groups)
    for column in result.columns:
        result[column] = result[column].map(lambda value: normalize_case_variants(value, selected))
    return result


def rule_duplicate_rows(df):
    return df.drop_duplicates(ignore_index=True)


def rule_outlier_flags(df, numeric_columns):
    return flag_numeric_outliers(df, numeric_columns)


def compute_rule_impact(rule_key, df, selected_date_columns, selected_numeric_columns, selected_case_groups):
    if rule_key == "trim_invisible":
        changed = 0
        for column in df.columns:
            for value in df[column].astype("object"):
                normalized = trim_invisible_and_space(value)
                if _as_text(value) is not None and normalized != value:
                    changed += 1
        return {"value_count": changed, "row_count": 0}

    if rule_key == "blank_tokens":
        changed = 0
        for column in df.columns:
            for value in df[column].astype("object"):
                if _blank_like(value):
                    normalized = normalize_blank_tokens(value)
                    if normalized is None:
                        changed += 1
        return {"value_count": changed, "row_count": 0}

    if rule_key == "date_columns":
        changed = 0
        for column in selected_date_columns:
            if column not in df.columns:
                continue
            for value in df[column].astype("object"):
                if is_date_like_text(value):
                    if normalize_date_value(value) != value:
                        changed += 1
        return {"value_count": changed, "row_count": 0}

    if rule_key == "numeric_columns":
        changed = 0
        for column in selected_numeric_columns:
            if column not in df.columns:
                continue
            for value in df[column].astype("object"):
                if is_numeric_like_text(value):
                    if normalize_numeric_value(value) != value:
                        changed += 1
        return {"value_count": changed, "row_count": 0}

    if rule_key == "case_variants":
        changed = 0
        for column in df.columns:
            for value in df[column].astype("object"):
                text = _as_text(value)
                if text is None:
                    continue
                key = _collapse_spaces(text).lower()
                if key in set(selected_case_groups):
                    if normalize_case_variants(value, set(selected_case_groups)) != value:
                        changed += 1
        return {"value_count": changed, "row_count": 0}

    if rule_key == "duplicate_rows":
        before = len(df)
        after = len(rule_duplicate_rows(df))
        return {"value_count": 0, "row_count": max(before - after, 0)}

    if rule_key == "outlier_flags":
        flagged = rule_outlier_flags(df.copy(), selected_numeric_columns)
        marked = flagged["_표시"].astype(str).str.len().gt(0).sum() if "_표시" in flagged.columns else 0
        return {"value_count": int(marked), "row_count": int(marked)}

    return {"value_count": 0, "row_count": 0}


def apply_general_rules(df, rule_states, selected_date_columns, selected_numeric_columns, selected_case_groups):
    result = df.copy()

    if rule_states.get("trim_invisible"):
        result = rule_trim_invisible(result)

    if rule_states.get("blank_tokens"):
        result = rule_blank_tokens(result)

    if rule_states.get("date_columns"):
        result = rule_date_columns(result, selected_date_columns)

    if rule_states.get("numeric_columns"):
        result = rule_numeric_columns(result, selected_numeric_columns)

    if rule_states.get("case_variants"):
        result = rule_case_variants(result, selected_case_groups)

    if rule_states.get("duplicate_rows"):
        result = rule_duplicate_rows(result)

    if rule_states.get("outlier_flags"):
        result = rule_outlier_flags(result, selected_numeric_columns)

    return result
