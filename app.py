import streamlit as st
import pandas as pd
import re
import json
from io import BytesIO

st.set_page_config(page_title="ITOSE - FDF", layout="wide")
st.title("ITOSE Tools - FDF Summary")

# =========================
# REGEX + FILTER
# =========================
UUID_REGEX = r'([a-f0-9\-]{36})'
REQUEST_ID_REGEX = r'Request\s*ID[:\s]*([a-f0-9\-]{36})'
VIN_REGEX = r'"vin"\s*:\s*"([A-Z0-9]+)"'
BODY_VIN_REGEX = r'vin=([A-Z0-9]+)'

NOT_VALID_KEYWORDS = ["not valid", "duplicate"]

def is_valid_message(msg):
    if not msg:
        return True
    msg_lower = msg.lower()
    return not any(k in msg_lower for k in NOT_VALID_KEYWORDS)

def extract_uuid(text):
    m = re.search(UUID_REGEX, text)
    return m.group(1) if m else None

def extract_request_id(text):
    m = re.search(REQUEST_ID_REGEX, text, re.IGNORECASE)
    return m.group(1) if m else None

# =========================
# JSON Extract
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

# =========================
# CORE PARSER (🔥 FINAL FIX)
# =========================
def parse_fdf_datahub(df):
    rows = []
    uuid_groups = {}

    # group logs by UUID
    for val in df:
        if pd.isna(val): continue
        text = str(val)
        uuid = extract_uuid(text)
        if not uuid: continue
        uuid_groups.setdefault(uuid, []).append(text)

    for uuid, logs in uuid_groups.items():
        request_id = None
        response_data = None
        request_vins = []

        for log in logs:
            if not request_id:
                request_id = extract_request_id(log)

            # ดึง VIN จาก request body
            if "body=" in log and "vin=" in log:
                request_vins.extend(re.findall(BODY_VIN_REGEX, log))

            # ดึง response json
            if not response_data:
                response_data = extract_response_json(log)

        # =========================
        # รวม logic (ไม่ใช้ if/else)
        # =========================
        vehicle_list = []
        if response_data and "data" in response_data:
            vehicle_list = response_data["data"].get("vehicleList", [])

        has_success = any('"status":"0000"' in log for log in logs)

        added_vins = set()

        # ✅ 1. จาก JSON response
        for item in vehicle_list:
            status = str(item.get("status"))
            message = item.get("message")
            vin = item.get("vin")

            if status == "0000" and is_valid_message(message):
                rows.append({
                    "RequestID": request_id,
                    "VIN": vin,
                    "Message": message,
                    "Status": status
                })
                added_vins.add(vin)

        # 🔥 2. จาก request (ถ้ามี success แต่ JSON ไม่ครบ)
        if has_success:
            for vin in request_vins:
                if vin not in added_vins:
                    rows.append({
                        "RequestID": request_id,
                        "VIN": vin,
                        "Message": "Recovered from request+success",
                        "Status": "0000"
                    })
                    added_vins.add(vin)

        # 🔥 3. fallback จาก raw response
        for log in logs:
            if '"status":"0000"' in log:
                vins = re.findall(VIN_REGEX, log)
                for vin in vins:
                    if vin not in added_vins:
                        rows.append({
                            "RequestID": request_id,
                            "VIN": vin,
                            "Message": "Recovered from raw response",
                            "Status": "0000"
                        })
                        added_vins.add(vin)

    df_out = pd.DataFrame(rows)

    if not df_out.empty:
        df_out = df_out[df_out["VIN"].notna()]

        # dedupe ทั้งไฟล์
        df_out = df_out.iloc[::-1].drop_duplicates(subset=["VIN"], keep="first").iloc[::-1]

        df_out = df_out.reset_index(drop=True)
        df_out.insert(0, "No.", df_out.index + 1)

    return df_out

# =========================
# UI
# =========================
file1 = st.file_uploader("Upload FDFDataHub File")

def read_file(file):
    return pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)

df1 = pd.DataFrame()

if file1:
    df = read_file(file1)
    df1 = parse_fdf_datahub(df["@message"] if "@message" in df.columns else df)

# =========================
# RESULT
# =========================
st.markdown("## Result")

st.write("Total VIN:", len(df1))

if not df1.empty:
    st.dataframe(df1, use_container_width=True)

# =========================
# EXPORT
# =========================
if not df1.empty:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df1.to_excel(writer, index=False, sheet_name='FDFDataHub')

    output.seek(0)

    st.download_button("Download Excel", data=output, file_name="fdf-datahub-clean.xlsx")
