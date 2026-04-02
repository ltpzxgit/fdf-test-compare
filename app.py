import streamlit as st
import pandas as pd
import re
import json
from io import BytesIO

st.set_page_config(page_title="ITOSE - FDF", layout="wide")
st.title("ITOSE Tools - FDF Summary")

# =========================
# CSS
# =========================
st.markdown("""
<style>
.card {
    padding: 20px;
    border-radius: 14px;
    background: linear-gradient(145deg, #0f172a, #111827);
    border: 1px solid #374151;
    text-align: center;
}
.card-title {
    font-size: 14px;
    color: #9ca3af;
}
.card-value {
    font-size: 42px;
    font-weight: bold;
    color: white;
}
.card-error {
    margin-top: 12px;
    padding: 12px;
    border-radius: 10px;
    color: #4ade80;
    background: rgba(34,197,94,0.1);
    border: 1px solid rgba(34,197,94,0.3);
}
</style>
""", unsafe_allow_html=True)

# =========================
# REGEX
# =========================
UUID_REGEX = r'([a-f0-9\-]{36})'
REQUEST_ID_REGEX = r'Request\s*ID[:\s]*([a-f0-9\-]{36})'
VIN_REGEX = r'"vin"\s*:\s*"([A-Z0-9]+)"'

def extract_uuid(text):
    m = re.search(UUID_REGEX, text)
    return m.group(1) if m else None

def extract_request_id(text):
    m = re.search(REQUEST_ID_REGEX, text, re.IGNORECASE)
    return m.group(1) if m else None

def extract_vin(text):
    return re.findall(VIN_REGEX, text)

# =========================
# FDFDataHub
# =========================
def extract_response_json(text):
    if "Response:" not in text:
        return None
    try:
        part = text.split("Response:", 1)[1].strip()
        part = part.replace('""', '"')
        return json.loads(part)
    except:
        return None

def parse_fdf_datahub(df):
    rows = []
    uuid_groups = {}

    for val in df:
        if pd.isna(val): continue
        text = str(val)
        uuid = extract_uuid(text)
        if not uuid: continue
        uuid_groups.setdefault(uuid, []).append(text)

    for uuid, logs in uuid_groups.items():
        request_id = None
        response_data = None

        for log in logs:
            if not request_id:
                request_id = extract_request_id(log)
            if not response_data:
                response_data = extract_response_json(log)

        if response_data and "data" in response_data:
            vehicle_list = response_data["data"].get("vehicleList", [])
            for item in vehicle_list:
                rows.append({
                    "RequestID": request_id,
                    "VIN": item.get("vin"),
                    "Message": item.get("message"),
                    "Status": str(item.get("status"))
                })

    df_out = pd.DataFrame(rows)
    df_error = pd.DataFrame()

    if not df_out.empty:
        df_out = df_out[df_out["VIN"].notna()]

        df_error = df_out[
            df_out["Message"].str.contains("Not Valid|Device serial no. is duplicated", case=False, na=False)
        ].copy()

        df_out = df_out[
            ~df_out["Message"].str.contains("Not Valid|Device serial no. is duplicated", case=False, na=False)
        ].copy()

        df_out = df_out.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_out = df_out.reset_index(drop=True)
        df_out["No."] = range(1, len(df_out)+1)
        df_out = df_out[["No."] + [c for c in df_out.columns if c != "No."]]

        if not df_error.empty:
            df_error = df_error.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
            df_error = df_error.reset_index(drop=True)
            df_error["No."] = range(1, len(df_error)+1)
            df_error = df_error[["No."] + [c for c in df_error.columns if c != "No."]]

    return df_out, df_error

# =========================
# FDFTCAP
# =========================
def extract_json_from_log(log):
    if "Response" not in log:
        return None
    try:
        part = log.split("Response", 1)[1]
        start = part.find("{")
        end = part.rfind("}") + 1
        clean = part[start:end].replace('""', '"').replace('\\n','').replace('\\r','')
        return json.loads(clean)
    except:
        return None

def parse_fdf_tcap(df):
    rows = []
    logs = [str(x) for x in df if not pd.isna(x)]

    for text in logs:
        data = extract_json_from_log(text)
        vins = extract_vin(text)

        if vins:
            for vin in vins:
                rows.append({
                    "VIN": vin,
                    "StatusCode": data.get("statusCode") if data else None,
                    "Message": data.get("message") if data else None
                })

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out = df_out.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_out = df_out.reset_index(drop=True)
        df_out["No."] = range(1, len(df_out)+1)
        df_out = df_out[["No."] + [c for c in df_out.columns if c != "No."]]

    return df_out

# =========================
# VehicleSettingRequester
# =========================
def parse_vehicle_setting(df):
    rows = []
    for val in df:
        text = str(val)
        vin_match = re.search(r'vin=([A-Z0-9]+)', text)
        if vin_match:
            rows.append({"VIN": vin_match.group(1)})

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out = df_out.drop_duplicates(subset=["VIN"])
        df_out = df_out.reset_index(drop=True)
        df_out["No."] = range(1, len(df_out)+1)
        df_out = df_out[["No."] + [c for c in df_out.columns if c != "No."]]

    return df_out

# =========================
# UPLOAD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    file1 = st.file_uploader("FDFDataHub")

with c2:
    file2 = st.file_uploader("FDFTCAP")

with c3:
    file3 = st.file_uploader("VehicleSettingRequester")

# =========================
# PROCESS
# =========================
def read_file(file):
    return pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)

df1 = df2 = df3 = df_error = df_broken = df_fdf_error = pd.DataFrame()

if file1:
    df = read_file(file1)
    df1, df_error = parse_fdf_datahub(df["@message"] if "@message" in df.columns else df)

if file2:
    df = read_file(file2)
    df2 = parse_fdf_tcap(df["@message"] if "@message" in df.columns else df)

if file3:
    df = read_file(file3)
    df3 = parse_vehicle_setting(df["@message"] if "@message" in df.columns else df)

# =========================
# DEVICE BROKEN
# =========================
if not df1.empty:
    vins1 = set(df1["VIN"])
    vins2 = set(df2["VIN"]) if not df2.empty else set()

    broken = vins1 - vins2

    if broken:
        df_broken = df1[df1["VIN"].isin(broken)].copy()
        df_broken = df_broken.drop_duplicates(subset=["VIN"])

        df_broken["No."] = range(1, len(df_broken)+1)
        df_broken = df_broken[["No."] + [c for c in df_broken.columns if c != "No."]]

        # 🔥 remove from df1
        df1 = df1[~df1["VIN"].isin(broken)].copy()
        df1 = df1.reset_index(drop=True)
        df1["No."] = range(1, len(df1)+1)
        df1 = df1[["No."] + [c for c in df1.columns if c != "No."]]

# =========================
# FDF ERROR
# =========================
if not df1.empty:
    vins1 = set(df1["VIN"])
    vins3 = set(df3["VIN"]) if not df3.empty else set()

    err = vins1 - vins3

    if err:
        df_fdf_error = df1[df1["VIN"].isin(err)].copy()
        df_fdf_error = df_fdf_error.drop_duplicates(subset=["VIN"])

        df_fdf_error["No."] = range(1, len(df_fdf_error)+1)
        df_fdf_error = df_fdf_error[["No."] + [c for c in df_fdf_error.columns if c != "No."]]

# =========================
# SUMMARY
# =========================
st.markdown("## Summary")

s1, s2, s3, s4, s5, s6 = st.columns(6)

def card(title, value):
    return f"""
    <div class="card">
        <div class="card-title">{title}</div>
        <div class="card-value">{value}</div>
        <div class="card-error">Error: 0</div>
    </div>
    """

with s1:
    st.markdown(card("FDFDataHub", len(df1)), unsafe_allow_html=True)
with s2:
    st.markdown(card("FDFTCAP", len(df2)), unsafe_allow_html=True)
with s3:
    st.markdown(card("VehicleSettingRequester", len(df3)), unsafe_allow_html=True)
with s4:
    st.markdown(card("Not Valid & Duplicate", len(df_error)), unsafe_allow_html=True)
with s5:
    st.markdown(card("Device Broken", len(df_broken)), unsafe_allow_html=True)
with s6:
    st.markdown(card("FDF Error", len(df_fdf_error)), unsafe_allow_html=True)

# =========================
# TABLE
# =========================
st.divider()

if not df1.empty:
    st.subheader("FDFDataHub")
    st.dataframe(df1)

if not df2.empty:
    st.subheader("FDFTCAP")
    st.dataframe(df2)

if not df3.empty:
    st.subheader("VehicleSettingRequester")
    st.dataframe(df3)

if not df_error.empty:
    st.subheader("Not Valid & Duplicate")
    st.dataframe(df_error)

if not df_broken.empty:
    st.subheader("Device Broken")
    st.dataframe(df_broken)

if not df_fdf_error.empty:
    st.subheader("FDF Error")
    st.dataframe(df_fdf_error)

# =========================
# EXPORT
# =========================
if not df1.empty or not df2.empty or not df3.empty:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:

        if not df1.empty:
            df1.to_excel(writer, index=False, sheet_name='FDFDataHub')

        if not df2.empty:
            df2.to_excel(writer, index=False, sheet_name='FDFTCAP')

        if not df3.empty:
            df3.to_excel(writer, index=False, sheet_name='VehicleSettingRequester')

        if not df_error.empty:
            df_error.to_excel(writer, index=False, sheet_name='Not Valid & Duplicate')

        if not df_broken.empty:
            df_broken.to_excel(writer, index=False, sheet_name='Device Broken')

        if not df_fdf_error.empty:
            df_fdf_error.to_excel(writer, index=False, sheet_name='FDF Error')

    output.seek(0)

    st.download_button("Download Excel", data=output, file_name="fdf-summary.xlsx")
