import streamlit as st
import pandas as pd
import re
import json
from io import BytesIO

st.set_page_config(page_title="ITOSE - VIN Extractor", layout="wide")
st.title("VIN Extractor (All Patterns)")

# =========================
# REGEX + FILTER
# =========================
VIN_JSON_REGEX = r'"vin"\s*:\s*"([A-Z0-9]+)"'
VIN_BODY_REGEX = r'vin=([A-Z0-9]+)'

INVALID_KEYWORDS = ["not valid", "duplicate"]

def is_valid_line(text):
    text_lower = text.lower()
    return not any(k in text_lower for k in INVALID_KEYWORDS)

# =========================
# CORE LOGIC
# =========================
def extract_all_vins(df):
    vin_set = set()
    rows = []

    for val in df:
        if pd.isna(val): 
            continue

        text = str(val)

        # ❌ ตัด log ที่มี not valid / duplicate
        if not is_valid_line(text):
            continue

        # ✅ JSON pattern
        vins_json = re.findall(VIN_JSON_REGEX, text)

        # ✅ Request body pattern
        vins_body = re.findall(VIN_BODY_REGEX, text)

        vins = set(vins_json + vins_body)

        for vin in vins:
            if vin not in vin_set:
                vin_set.add(vin)
                rows.append({
                    "VIN": vin,
                    "Source": "log"
                })

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out.insert(0, "No.", range(1, len(df_out)+1))

    return df_out

# =========================
# UI
# =========================
file = st.file_uploader("Upload Log File")

def read_file(file):
    return pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)

df_out = pd.DataFrame()

if file:
    df = read_file(file)
    df_out = extract_all_vins(df["@message"] if "@message" in df.columns else df)

# =========================
# RESULT
# =========================
st.markdown("## Result")
st.write("Total VIN:", len(df_out))

if not df_out.empty:
    st.dataframe(df_out, use_container_width=True)

# =========================
# EXPORT
# =========================
if not df_out.empty:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_out.to_excel(writer, index=False, sheet_name='VIN_List')

    output.seek(0)

    st.download_button("Download Excel", data=output, file_name="vin-all-clean.xlsx")
