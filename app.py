import pandas as pd
import streamlit as st

from 정제.읽기 import load_dataframe, summarize_columns
from 정제.일반규칙 import (
    apply_general_rules,
    build_case_variant_groups,
    compute_rule_impact,
    detect_column_types,
)
from 정제.보고서 import (
    build_change_log,
    build_report_summary,
    build_side_by_side,
    build_workbook_bytes,
    export_settings_json,
    load_settings_json,
)


st.set_page_config(page_title="정제 대시보드", layout="wide")
st.title("정제 대시보드 — 올리고, 정리하고, 숫자를 본다")

uploaded_file = st.file_uploader(
    "파일 업로드",
    type=["xlsx", "csv"],
    help="엑셀(.xlsx) 또는 CSV 파일을 올려 주세요.",
)

settings_file = st.file_uploader(
    "설정 파일 업로드 (.json, 선택)",
    type=["json"],
    help="이전에 내려받은 설정을 다시 불러와 같은 규칙과 칸 선택으로 돌립니다.",
)

if uploaded_file is None:
    st.info("파일을 올리면 원본 데이터를 기준으로 칸별 통계를 보여 줍니다.")
    st.stop()

file_name = uploaded_file.name.lower()

if file_name.endswith(".xlsx") or file_name.endswith(".xls"):
    excel_file = pd.ExcelFile(uploaded_file)
    sheet_names = excel_file.sheet_names
    selected_sheet = st.selectbox("시트를 고르세요", sheet_names, index=0)
    header_row = st.selectbox(
        "머리글이 있는 줄 번호를 고르세요",
        list(range(1, 11)),
        index=0,
    )
    raw_df = load_dataframe(uploaded_file, sheet_name=selected_sheet, header_row=header_row)
else:
    header_row = st.selectbox(
        "머리글이 있는 줄 번호를 고르세요",
        list(range(1, 11)),
        index=0,
    )
    raw_df = load_dataframe(uploaded_file, header_row=header_row)

st.subheader("① 원본 그대로")
summary_cols = st.columns(2)
with summary_cols[0]:
    st.metric("줄 수", raw_df.shape[0])
with summary_cols[1]:
    st.metric("칸 수", raw_df.shape[1])

summary_df = summarize_columns(raw_df)
summary_df["숫자로 읽히는 값의 비율"] = summary_df["숫자로 읽히는 값의 비율"].map(lambda x: f"{x:.2%}")
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.subheader("② 일반 정제")

all_columns = list(raw_df.columns)
detected_date_columns, detected_numeric_columns = detect_column_types(raw_df)
selected_settings_date = {}
selected_settings_numeric = {}
selected_settings_case = {}
selected_settings_report = {}
_settings = {}

if settings_file is not None:
    _settings = load_settings_json(settings_file)

selected_settings_date = _settings.get("date_columns", detected_date_columns)
selected_settings_numeric = _settings.get("numeric_columns", detected_numeric_columns)
selected_settings_case = _settings.get("selected_case_groups", [])
selected_settings_report = _settings.get("report_columns", [])

st.caption("날짜 칸 · 숫자 칸은 빈칸을 뺀 값의 80% 이상이 그 형식으로 읽히면 자동으로 감지합니다.")

col_date, col_numeric = st.columns(2)
with col_date:
    date_columns = st.multiselect(
        "날짜 칸 선택",
        options=all_columns,
        default=[col for col in selected_settings_date if col in all_columns],
        help="선택한 칸은 YYYY-MM-DD 형식으로 맞춥니다.",
    )
with col_numeric:
    numeric_columns = st.multiselect(
        "숫자 칸 선택",
        options=all_columns,
        default=[col for col in selected_settings_numeric if col in all_columns],
        help="선택한 칸은 쉼표와 단위 글자를 제거해 숫자값으로 정리합니다.",
    )

rule_specs = [
    {
        "key": "trim_invisible",
        "label": "가. 앞뒤 공백과 보이지 않는 글자를 뗀다",
        "description": "앞뒤 공백, 제로폭 문자 같은 보이지 않는 문자를 제거합니다.",
    },
    {
        "key": "blank_tokens",
        "label": "나. 빈칸을 뜻하는 표기를 빈칸으로 맞춘다",
        "description": "- · N/A n/a 없음 null 공백만 같은 표기를 빈칸으로 통일합니다.",
    },
    {
        "key": "date_columns",
        "label": "다. 날짜로 읽히는 칸은 YYYY-MM-DD로 맞춘다",
        "description": "2025-03-14 같은 형식으로 날짜 값을 표준화합니다.",
    },
    {
        "key": "numeric_columns",
        "label": "라. 숫자로 읽히는 칸은 쉼표와 단위 글자를 뗀다",
        "description": "쉼표와 원·점·건·개·분·%를 제거해 숫자 본문만 남깁니다.",
    },
    {
        "key": "case_variants",
        "label": "마. 대소문자·띄어쓰기만 다른 표기 하나로 맞춘다",
        "description": "같은 의미의 표기 묶음만 고른 값으로 통일합니다.",
    },
    {
        "key": "duplicate_rows",
        "label": "바. 모든 칸이 같은 줄은 하나만 남긴다",
        "description": "중복 행을 제거합니다. 이 규칙만 줄을 지웁니다.",
    },
    {
        "key": "outlier_flags",
        "label": "사. 숫자 칸의 음수와 동떨어진 값은 _표시 칸에 적는다",
        "description": "값을 지우지 않고 이유를 _표시 칸에 기록합니다.",
    },
]

rule_state = {}
for spec in rule_specs:
    default_rule = _settings.get("rule_state", {}).get(spec["key"], spec["key"] != "duplicate_rows")
    rule_state[spec["key"]] = st.toggle(
        spec["label"],
        value=default_rule,
        key=f"rule_{spec['key']}",
    )

case_variant_groups = build_case_variant_groups(raw_df)
case_variant_keys = [item["묶음"] for item in case_variant_groups]
selected_case_groups = []
if case_variant_keys:
    selected_case_groups = st.multiselect(
        "대소문자·띄어쓰기만 다른 표기 묶음 선택",
        options=case_variant_keys,
        default=[key for key in selected_settings_case if key in case_variant_keys],
        help="선택한 묶음만 통일합니다.",
    )

st.info("적용 순서: 가 → 사. 순서 때문에 결과가 달라지는 규칙이 있으면 화면에 표시합니다.")

for spec in rule_specs:
    impact = compute_rule_impact(
        spec["key"],
        raw_df,
        date_columns,
        numeric_columns,
        selected_case_groups,
    )
    st.markdown(f"### {spec['label']}")
    st.write(spec["description"])
    st.caption(f"이 파일에서 바꾸는 값 {impact['value_count']}개 · 줄 {impact['row_count']}개")

    if spec["key"] == "case_variants":
        if case_variant_groups:
            st.dataframe(pd.DataFrame(case_variant_groups).head(10), use_container_width=True, hide_index=True)
        else:
            st.caption("대소문자·띄어쓰기만 다른 표기 후보가 없습니다.")

preview_df = apply_general_rules(
    raw_df,
    {
        "trim_invisible": rule_state.get("trim_invisible", False),
        "blank_tokens": rule_state.get("blank_tokens", False),
        "date_columns": rule_state.get("date_columns", False),
        "numeric_columns": rule_state.get("numeric_columns", False),
        "case_variants": rule_state.get("case_variants", False),
        "duplicate_rows": rule_state.get("duplicate_rows", False),
        "outlier_flags": rule_state.get("outlier_flags", False),
    },
    date_columns,
    numeric_columns,
    selected_case_groups,
)
preview_df = preview_df.reset_index(drop=True)
raw_df_for_compare = raw_df.reset_index(drop=True)
compare_columns = [col for col in raw_df_for_compare.columns if col in preview_df.columns]

st.subheader("미리보기")
preview_meta = st.columns(3)
with preview_meta[0]:
    st.metric("정리본 줄 수", preview_df.shape[0])
with preview_meta[1]:
    st.metric("정리본 칸 수", preview_df.shape[1])
with preview_meta[2]:
    st.metric(
        "변경 건수",
        int(
            (
                raw_df_for_compare[compare_columns].astype(str).fillna("")
                != preview_df[compare_columns].astype(str).fillna("")
            ).sum().sum()
            if compare_columns and not preview_df.empty
            else 0
        ),
    )

with st.expander("정리 본 보기", expanded=True):
    st.dataframe(preview_df.head(50), use_container_width=True, hide_index=True)

st.subheader("변경 로그")
enabled_rules = [key for key, enabled in rule_state.items() if enabled]
change_log_df = build_change_log(raw_df, preview_df, enabled_rules)
if not change_log_df.empty:
    preview_log = change_log_df.head(20)
    log_meta = st.columns(2)
    with log_meta[0]:
        st.metric("로그 총 건수", len(change_log_df))
    with log_meta[1]:
        st.metric("화면 표시", len(preview_log))
    st.caption("화면에는 앞 20줄만 보여 주고, 전체는 엑셀 파일에 포함됩니다.")
    with st.expander("변경 로그 상세", expanded=False):
        st.dataframe(preview_log, use_container_width=True, hide_index=True)
else:
    st.info("변경된 값이 없습니다.")

st.subheader("③ 보고서용 숫자")
report_columns = st.multiselect(
    "보고서용 칸 고르기",
    options=all_columns,
    default=[col for col in selected_settings_report if col in all_columns],
    help="선택한 칸만 원본/정리본/차이를 보고 평균·합계·값 분포를 뽑습니다.",
)

if report_columns:
    report_df, value_distributions = build_report_summary(raw_df, preview_df, report_columns, numeric_columns)
    st.dataframe(report_df, use_container_width=True, hide_index=True)

    for _, row in report_df.iterrows():
        with st.container():
            st.markdown(f"- {row['칸']} ({row['종류']})")
            if row["종류"] == "숫자":
                st.caption(f"{row['기준']}")
            else:
                dist = value_distributions.get(row["칸"])
                if dist is not None and not dist.empty:
                    top = dist.head(3).copy()
                    top["비율"] = top["비율"].map(lambda x: f"{x:.2%}")
                    st.caption(f"{row['칸']} — {top.to_dict(orient='records')}")
                else:
                    st.caption(f"{row['칸']} — 값 분포가 없습니다.")

    with st.expander("원본 / 정리본 / 차이 비교", expanded=False):
        comparison_df = build_side_by_side(raw_df, preview_df, report_columns)
        st.dataframe(comparison_df.head(50), use_container_width=True, hide_index=True)
else:
    st.caption("보고서에 넣을 칸을 선택해 주세요.")

st.subheader("④ 내려받기")
enabled_rules = [key for key, enabled in rule_state.items() if enabled]
change_log_df = build_change_log(raw_df, preview_df, enabled_rules)
report_summary_df, _ = build_report_summary(raw_df, preview_df, report_columns, numeric_columns)

excel_bytes = build_workbook_bytes(preview_df, change_log_df, report_summary_df, enabled_rules)
settings_bytes = export_settings_json(
    rule_state,
    date_columns,
    numeric_columns,
    selected_case_groups,
    report_columns,
)

col_excel, col_json = st.columns(2)
with col_excel:
    st.download_button(
        "엑셀로 내려받기",
        data=excel_bytes,
        file_name="정리_결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with col_json:
    st.download_button(
        "설정 파일 내려받기 (.json)",
        data=settings_bytes,
        file_name="정제_설정.json",
        mime="application/json",
    )

st.caption("변경 기록은 화면에 앞 20줄만 보여 주고, 전체는 엑셀 파일로 내려받습니다.")
