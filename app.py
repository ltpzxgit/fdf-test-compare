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
.card-red {
    padding: 20px;
    border-radius: 14px;
    background: linear-gradient(145deg, #2a0f0f, #1a0f0f);
    border: 1px solid #7f1d1d;
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
.card-error-red {
    margin-top: 12px;
    padding: 12px;
    border-radius: 10px;
    color: #f87171;
    background: rgba(248,113,113,0.1);
    border: 1px solid rgba(248,113,113,0.3);
}
</style>
""", unsafe_allow_html=True)

# =========================
# CARD FUNCTION
# =========================
def card(title, value, is_red=False):
    card_class = "card-red" if is_red else "card"

    return f"""
    <div class="{card_class}">
        <div class="card-title">{title}</div>
        <div class="card-value">{value}</div>
    </div>
    """

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
        df_out["No."] = range(1, len(df_out)+1)
        df_out = df_out[["No."] + [c for c in df_out.columns if c != "No."]]

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
# DEVICE BROKEN (แก้ตรงนี้อย่างเดียว)
# =========================
if not df1.empty:
    vins_1 = set(df1["VIN"].dropna())
    vins_2 = set(df2["VIN"].dropna()) if not df2.empty else set()

    broken_vins = vins_1 - vins_2

    if broken_vins:
        df_broken = df1[df1["VIN"].isin(broken_vins)].copy()
        df_broken = df_broken.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_broken = df_broken.reset_index(drop=True)

        df_broken["No."] = range(1, len(df_broken)+1)
        df_broken = df_broken[["No."] + [c for c in df_broken.columns if c != "No."]]

        # ❌ ไม่ลบ df1 แล้ว

# =========================
# FDF ERROR
# =========================
if not df1.empty:
    vins_1 = set(df1["VIN"].dropna())
    vins_3 = set(df3["VIN"].dropna()) if not df3.empty else set()

    error_vins = vins_1 - vins_3

    if error_vins:
        df_fdf_error = df1[df1["VIN"].isin(error_vins)].copy()
        df_fdf_error = df_fdf_error.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_fdf_error = df_fdf_error.reset_index(drop=True)

        df_fdf_error["No."] = range(1, len(df_fdf_error)+1)
        df_fdf_error = df_fdf_error[["No."] + [c for c in df_fdf_error.columns if c != "No."]]

# =========================
# SUMMARY
# =========================
st.markdown("## Summary")

r1 = st.columns(3)
r2 = st.columns(3)

with r1[0]:
    st.markdown(card("FDFDataHub", len(df1)), unsafe_allow_html=True)
with r1[1]:
    st.markdown(card("FDFTCAP", len(df2)), unsafe_allow_html=True)
with r1[2]:
    st.markdown(card("VehicleSettingRequester", len(df3)), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

with r2[0]:
    st.markdown(card("Not Valid & Duplicate", len(df_error), True), unsafe_allow_html=True)
with r2[1]:
    st.markdown(card("Device Broken", len(df_broken), True), unsafe_allow_html=True)
with r2[2]:
    st.markdown(card("FDF Error", len(df_fdf_error), True), unsafe_allow_html=True)

# =========================
# TABLE
# =========================
st.divider()

if not df1.empty:
    st.subheader("FDFDataHub")
    st.dataframe(df1, use_container_width=True)

if not df2.empty:
    st.subheader("FDFTCAP")
    st.dataframe(df2, use_container_width=True)

if not df3.empty:
    st.subheader("VehicleSettingRequester")
    st.dataframe(df3, use_container_width=True)

if not df_error.empty:
    st.subheader("Not Valid & Duplicate")
    st.dataframe(df_error, use_container_width=True)

if not df_broken.empty:
    st.subheader("Device Broken")
    st.dataframe(df_broken, use_container_width=True)

if not df_fdf_error.empty:
    st.subheader("FDF Error")
    st.dataframe(df_fdf_error, use_container_width=True)

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
