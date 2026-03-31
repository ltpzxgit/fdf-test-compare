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

def extract_uuid(text):
    m = re.search(UUID_REGEX, text)
    return m.group(1) if m else None

def extract_request_id(text):
    m = re.search(REQUEST_ID_REGEX, text, re.IGNORECASE)
    return m.group(1) if m else None

# =========================
# SAFE JSON
# =========================
def safe_json_extract(text):
    if "Response:" not in text:
        return None
    try:
        part = text.split("Response:", 1)[1]
        start = part.find("{")
        end = part.rfind("}") + 1

        if start == -1 or end == -1:
            return None

        clean = part[start:end]
        clean = clean.replace('""', '"').replace('\\n', '').replace('\\r', '')

        return json.loads(clean)
    except:
        return None

# =========================
# REGEX FALLBACK
# =========================
def extract_by_regex(text):
    clean = text.replace('""', '"')

    vins = re.findall(r'"vin"\s*:\s*"([A-Z0-9]+)"', clean)
    messages = re.findall(r'"message"\s*:\s*"([^"]*)"', clean)
    statuses = re.findall(r'"status"\s*:\s*"(\d+)"', clean)

    rows = []
    max_len = max(len(vins), len(messages), len(statuses))

    for i in range(max_len):
        rows.append({
            "VIN": vins[i] if i < len(vins) else None,
            "Message": messages[i] if i < len(messages) else None,
            "Status": statuses[i] if i < len(statuses) else None,
        })

    return rows

# =========================
# 🔥 FIXED PRODUCTION PARSER
# =========================
def parse_fdf_datahub(df):
    rows = []
    uuid_groups = {}

    # GROUP UUID
    for val in df:
        if pd.isna(val):
            continue

        text = str(val)
        uuid = extract_uuid(text)

        if not uuid:
            continue

        uuid_groups.setdefault(uuid, []).append(text)

    # PROCESS
    for uuid, logs in uuid_groups.items():
        request_id = None
        temp_rows = []
        extracted = False

        # 🔥 loop ทั้งหมดก่อน (ห้าม break)
        for log in logs:
            # หา request_id ให้ครบ
            if not request_id:
                request_id = extract_request_id(log)

            # JSON
            data = safe_json_extract(log)

            if data and "data" in data:
                vehicle_list = data["data"].get("vehicleList", [])

                for item in vehicle_list:
                    temp_rows.append({
                        "VIN": item.get("vin"),
                        "Message": item.get("message"),
                        "Status": str(item.get("status"))
                    })

                extracted = True

        # 🔥 fallback ถ้า JSON ไม่มา
        if not extracted:
            for log in logs:
                if "Response:" in log:
                    fallback_rows = extract_by_regex(log)
                    temp_rows.extend(fallback_rows)

        # 🛟 last resort
        if not temp_rows:
            for log in logs:
                vins = re.findall(r'\b[A-Z0-9]{17}\b', log)
                for vin in vins:
                    temp_rows.append({
                        "VIN": vin,
                        "Message": "UNKNOWN",
                        "Status": "UNKNOWN"
                    })

        # assign request_id ทีหลัง (สำคัญ)
        for r in temp_rows:
            rows.append({
                "RequestID": request_id,
                "VIN": r["VIN"],
                "Message": r["Message"],
                "Status": r["Status"]
            })

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out = df_out[df_out["VIN"].notna()]

        # 🔥 VIN ซ้ำ → เอาล่าสุด
        df_out = (
            df_out.iloc[::-1]
            .drop_duplicates(subset=["VIN"], keep="first")
            .iloc[::-1]
            .reset_index(drop=True)
        )

        df_out.insert(0, "No.", df_out.index + 1)

    return df_out

# =========================
# FDFTCAP
# =========================
def extract_json_from_log(log):
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
        if not data:
            continue

        uuid = extract_uuid(text)

        rows.append({
            "UUID": uuid,
            "RequestID": uuid_to_req.get(uuid),
            "CountInsert": data.get("countInsert", 0),
            "StatusCode": data.get("statusCode"),
            "Message": data.get("message")
        })

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
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
# UI
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("### FDFDataHub")
    file1 = st.file_uploader("", key="f1")

with c2:
    st.markdown("### FDFTCAP")
    file2 = st.file_uploader("", key="f2")

with c3:
    st.markdown("### VehicleSettingRequester")
    file3 = st.file_uploader("", key="f3")

def read_file(file):
    return pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)

df1 = df2 = df3 = pd.DataFrame()

if file1:
    df = read_file(file1)
    df1 = parse_fdf_datahub(df["@message"] if "@message" in df.columns else df)

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

s1, s2, s3 = st.columns(3)

s1.metric("FDFDataHub", len(df1))
s2.metric("FDFTCAP", df2["CountInsert"].sum() if not df2.empty else 0)
s3.metric("VehicleSettingRequester", len(df3))

# =========================
# TABLE
# =========================
st.divider()

if not df1.empty:
    st.dataframe(df1, use_container_width=True)

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

    output.seek(0)

    st.download_button(
        "Download Excel",
        data=output,
        file_name="fdf-summary.xlsx"
    )
