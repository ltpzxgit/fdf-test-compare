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
# FDFDataHub (UPDATED)
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

        elif response_data is None:
            for log in logs:
                if "Response:" in log and '""vin""' in log:
                    clean = log.replace('""', '"')
                    vins = re.findall(r'"vin"\s*:\s*"([A-Z0-9]+)"', clean)
                    messages = re.findall(r'"message"\s*:\s*"([^"]+)"', clean)
                    statuses = re.findall(r'"status"\s*:\s*"(\d+)"', clean)

                    for i in range(len(vins)):
                        rows.append({
                            "RequestID": request_id,
                            "VIN": vins[i],
                            "Message": messages[i] if i < len(messages) else None,
                            "Status": statuses[i] if i < len(statuses) else None
                        })

    df_out = pd.DataFrame(rows)
    df_error = pd.DataFrame()

    if not df_out.empty:
        df_out = df_out[df_out["VIN"].notna()]

        # 🔥 แยก Error
        df_error = df_out[
            df_out["Message"].str.contains("Not Valid|Device serial no. is duplicated", case=False, na=False)
        ].copy()

        df_out = df_out[
            ~df_out["Message"].str.contains("Not Valid|Device serial no. is duplicated", case=False, na=False)
        ].copy()

        # 🔥 dedupe main
        df_out = df_out.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]

        df_out = df_out.reset_index(drop=True)
        df_out.insert(0, "No.", df_out.index + 1)

        # 🔥 dedupe error (เอาตัวล่าสุด)
        if not df_error.empty:
            df_error = df_error.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
            df_error = df_error.reset_index(drop=True)
            df_error.insert(0, "No.", range(1, len(df_error)+1))

    return df_out, df_error

# =========================
# FDFTCAP (VIN SUPPORT)
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

    uuid_to_req = {}
    for text in logs:
        uuid = extract_uuid(text)
        req = extract_request_id(text)
        if uuid and req:
            uuid_to_req[uuid] = req

    for text in logs:
        data = extract_json_from_log(text)
        uuid = extract_uuid(text)
        vins = extract_vin(text)

        if vins:
            for vin in vins:
                rows.append({
                    "UUID": uuid,
                    "RequestID": uuid_to_req.get(uuid),
                    "VIN": vin,
                    "StatusCode": data.get("statusCode") if data else None,
                    "Message": data.get("message") if data else None
                })

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out = df_out[df_out["VIN"].notna()]
        df_out = df_out.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_out = df_out.reset_index(drop=True)
        df_out.insert(0, "No.", range(1, len(df_out)+1))

    return df_out

# =========================
# VehicleSettingRequester
# =========================
def extract_body_data(text):
    if "body={" not in text:
        return {}
    try:
        part = text.split("body={", 1)[1].split("}", 1)[0]
        data = {}
        for item in part.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                data[k.strip()] = v.strip()
        return data
    except:
        return {}

def extract_response_data(text):
    if "Response:" not in text:
        return {}
    try:
        part = text.split("Response:", 1)[1]
        start = part.find("{")
        end = part.rfind("}") + 1
        clean = part[start:end].replace('""', '"').replace('\\n','').replace('\\r','')
        data = json.loads(clean)
        return {
            "StatusCode": data.get("statusCode"),
            "ResponseMessage": data.get("message")
        }
    except:
        return {}

def parse_vehicle_setting(df):
    logs = [str(x) for x in df if not pd.isna(x)]
    uuid_map = {}

    for text in logs:
        uuid = extract_uuid(text)
        if not uuid:
            continue

        uuid_map.setdefault(uuid, {})

        if "Request:" in text:
            uuid_map[uuid].update(extract_body_data(text))

        if "Response:" in text:
            uuid_map[uuid].update(extract_response_data(text))

    rows = []
    for i, (uuid, data) in enumerate(uuid_map.items(), start=1):
        rows.append({
            "No.": i,
            "UUID": uuid,
            "VIN": data.get("vin"),
            "DeviceID": data.get("deviceId"),
            "IMEI": data.get("IMEI"),
            "SimStatus": data.get("simStatus"),
            "SimPackage": data.get("simPackage"),
            "CAL_Flag": data.get("CAL_Flag"),
            "B2CFlag": data.get("B2CFlag"),
            "B2BFlag": data.get("B2BFlag"),
            "Tconnectflag": data.get("Tconnectflag"),
            "StatusCode": data.get("StatusCode"),
            "ResponseMessage": data.get("ResponseMessage"),
        })

    return pd.DataFrame(rows)

# =========================
# UPLOAD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    file1 = st.file_uploader("FDFDataHub", key="f1")

with c2:
    file2 = st.file_uploader("FDFTCAP", key="f2")

with c3:
    file3 = st.file_uploader("VehicleSettingRequester", key="f3")

# =========================
# PROCESS
# =========================
def read_file(file):
    return pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)

df1 = df2 = df3 = df_error = pd.DataFrame()

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
# SUMMARY
# =========================
st.markdown("## Summary")

s1, s2, s3, s4 = st.columns(4)

def card(title, value):
    return f"""
    <div class="card">
        <div class="card-title">{title}</div>
        <div class="card-value">{value}</div>
        <div class="card-error">Error: 0</div>
    </div>
    """

with s1:
    st.markdown(card("TCAPLinkageDatahub", len(df1)), unsafe_allow_html=True)

with s2:
    st.markdown(card("TCAPLinkage", len(df2)), unsafe_allow_html=True)

with s3:
    st.markdown(card("VehicleSettingRequester", len(df3)), unsafe_allow_html=True)

with s4:
    st.markdown(card("Not Valid & Duplicate", len(df_error)), unsafe_allow_html=True)

# =========================
# TABLE
# =========================
st.divider()

if not df1.empty:
    st.dataframe(df1, use_container_width=True)

if not df_error.empty:
    st.subheader("Not Valid & Duplicate")
    st.dataframe(df_error, use_container_width=True)

if not df2.empty:
    st.dataframe(df2, use_container_width=True)

if not df3.empty:
    st.dataframe(df3, use_container_width=True)

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

    output.seek(0)

    st.download_button("Download Excel", data=output, file_name="fdf-summary.xlsx")
