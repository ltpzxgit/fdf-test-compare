import streamlit as st
import pandas as pd
import re
import json
from io import BytesIO

st.set_page_config(page_title="ITOSE - FDF", layout="wide")
st.title("ITOSE Tools - FDF Summary")

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
# FDFDataHub (เดิม + แยก error)
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
        df_out.insert(0, "No.", range(1, len(df_out)+1))

        if not df_error.empty:
            df_error = df_error.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
            df_error = df_error.reset_index(drop=True)
            df_error.insert(0, "No.", range(1, len(df_error)+1))

    return df_out, df_error

# =========================
# FDFTCAP (เดิม + VIN)
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
        df_out.insert(0, "No.", range(1, len(df_out)+1))

    return df_out

# =========================
# VehicleSettingRequester (ห้ามแตะ)
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

file1 = c1.file_uploader("FDFDataHub")
file2 = c2.file_uploader("FDFTCAP")
file3 = c3.file_uploader("VehicleSettingRequester")

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
    broken_vins = set(df1["VIN"]) - set(df2["VIN"]) if not df2.empty else set(df1["VIN"])

    if broken_vins:
        df_broken = df1[df1["VIN"].isin(broken_vins)].copy()
        df_broken = df_broken.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_broken = df_broken.reset_index(drop=True)
        df_broken.insert(0, "No.", range(1, len(df_broken)+1))

        # ลบออกจาก df1
        df1 = df1[~df1["VIN"].isin(broken_vins)].copy()
        df1 = df1.reset_index(drop=True)
        df1.insert(0, "No.", range(1, len(df1)+1))

# =========================
# FDF ERROR
# =========================
if not df1.empty:
    error_vins = set(df1["VIN"]) - set(df3["VIN"]) if not df3.empty else set(df1["VIN"])

    if error_vins:
        df_fdf_error = df1[df1["VIN"].isin(error_vins)].copy()
        df_fdf_error = df_fdf_error.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]
        df_fdf_error = df_fdf_error.reset_index(drop=True)
        df_fdf_error.insert(0, "No.", range(1, len(df_fdf_error)+1))

# =========================
# SUMMARY
# =========================
s = st.columns(6)
labels = [
    ("FDFDataHub", df1),
    ("FDFTCAP", df2),
    ("VehicleSettingRequester", df3),
    ("Not Valid & Duplicate", df_error),
    ("Device Broken", df_broken),
    ("FDF Error", df_fdf_error)
]

for col, (name, df_) in zip(s, labels):
    col.metric(name, len(df_))

# =========================
# TABLE
# =========================
for name, df_ in labels:
    if not df_.empty:
        st.subheader(name)
        st.dataframe(df_)

# =========================
# EXPORT
# =========================
if any(len(df_) for _, df_ in labels):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for name, df_ in labels:
            if not df_.empty:
                df_.to_excel(writer, index=False, sheet_name=name)

    st.download_button("Download Excel", data=output.getvalue(), file_name="fdf_summary.xlsx")
