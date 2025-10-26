# my_shelf_st
# 📦 JANCodeLookup + Google Sheets連携 + OpenAI OCR（gpt-4o-mini対応）
# ☁️ Streamlit Cloud / ローカル 両対応（openai>=1.x専用）

import streamlit as st
st.set_page_config(page_title="my_shelf v1.207", layout="wide")
st.title("📦 my_shelf v1.207（新API対応版・Cloud/Local共通）")

from PIL import Image
import io, base64, re, unicodedata, requests, os, json
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pandas as pd
from io import BytesIO
from dotenv import load_dotenv
from openai import OpenAI  # ✅ 新SDK方式

# ------------------------------------------------------------
# 🔐 APIキー（Secrets / .env 両対応）
# ------------------------------------------------------------
api_key = None
try:
    api_key = st.secrets.get("OPENAI_API_KEY")
except Exception:
    pass
if not api_key:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)
    api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("❌ OpenAI APIキーが見つかりません。Secretsまたは.envを確認してください。")
    st.stop()

client = OpenAI(api_key=api_key)

# ------------------------------------------------------------
# 🧮 正規化関数
# ------------------------------------------------------------
def normalize_code(s: str, allow_alnum=False, uppercase=True):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[\u200B-\u200D\uFEFF\s\n\r\t]+", "", s)
    if allow_alnum:
        s = re.sub(r"[^A-Za-z0-9]", "", s)
        if uppercase:
            s = s.upper()
    else:
        s = re.sub(r"\D", "", s)
    return s

# ------------------------------------------------------------
# 🤖 OCR（新SDK: gpt-4o-mini）
# ------------------------------------------------------------
def analyze_code_with_openai(image_bytes: bytes, allow_alnum=False):
    try:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        directive = "数字のみを半角で返してください。" if not allow_alnum else "英数字のみを半角で返してください。"
        prompt = f"この画像の中央付近に印字されたコードを読み取り、{directive}説明や余計な文字は不要です。"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたはバーコードや印字コードを正確に読むOCRアシスタントです。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                }
            ],
            max_tokens=50,
        )
        raw = response.choices[0].message.content.strip()
        return normalize_code(raw, allow_alnum)
    except Exception as e:
        st.error(f"OCR処理中にエラー: {e}")
        return ""

# ------------------------------------------------------------
# 🔐 Google Sheets 認証
# ------------------------------------------------------------
def _authorize_gspread():
    try:
        if "gcp_service_account" in st.secrets:
            from gspread import service_account_from_dict
            return service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    except Exception as e:
        st.warning(f"GSheet認証(Secrets)で例外: {e}")

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(base_dir, "my-shelf-st-56b62d75dd45.json")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ GSheet認証エラー: {e}")
        return None

# ------------------------------------------------------------
# 🛒 JANCodeLookup
# ------------------------------------------------------------
def get_product_info(raw_code: str):
    try:
        jan_query = re.sub(r"\D", "", raw_code or "")
        if not jan_query:
            st.warning("⚠️ クエリが空です。コードを入力してください。")
            return None, None
        url = f"https://www.jancodelookup.com/search/?q={jan_query}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            name_tag = soup.select_one("div.search-result-item p")
            title = name_tag.get_text(strip=True) if name_tag else "商品名不明"
            img_tag = soup.select_one("div.search-result-item img.image")
            image_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else None
            st.success(f"🟢 JANCodeLookupヒット: {title}")
            if image_url:
                st.image(image_url, width=200, caption="取得された商品画像")
            return title, image_url
        else:
            st.warning(f"⚠️ HTTPエラー: {res.status_code}")
            return None, None
    except Exception as e:
        st.error(f"商品情報取得中にエラー: {e}")
        return None, None

# ------------------------------------------------------------
# 🔍 Google Sheets 検索／登録
# ------------------------------------------------------------
def search_gsheet(code_to_find):
    try:
        gs_client = _authorize_gspread()
        if gs_client is None:
            return None, None
        sheet = gs_client.open_by_key("1lIDwaGMx-bMUXsLsF4p9_KmaXCyDPZIVeIdBen6ebE0").sheet1
        df = pd.DataFrame(sheet.get_all_records())
        left = df.iloc[:, 0].astype(str).str.lstrip("0")
        right = str(code_to_find).lstrip("0")
        hit = df[left == right]
        if not hit.empty:
            name = hit.iloc[0]["商品名"] if "商品名" in hit.columns else hit.iloc[0, 1]
            img_url = hit.iloc[0]["画像URL"] if "画像URL" in hit.columns else None
            st.success(f"🟣 Google Sheetsヒット: {name}")
            if img_url:
                st.image(img_url, width=200, caption="GS登録画像")
            return name, img_url
        else:
            st.warning("⚠️ Google Sheetsに一致データなし。")
            return None, None
    except Exception as e:
        st.error(f"GS検索エラー: {e}")
        return None, None

def append_to_gsheet(code_to_save, product_name, img_url):
    try:
        gs_client = _authorize_gspread()
        if gs_client is None:
            return
        sheet = gs_client.open_by_key("1lIDwaGMx-bMUXsLsF4p9_KmaXCyDPZIVeIdBen6ebE0").sheet1
        header = sheet.row_values(1)
        col_map = {name: idx + 1 for idx, name in enumerate(header)}
        next_row = len(sheet.get_all_values()) + 1
        if "コード" in col_map:
            sheet.update_cell(next_row, col_map["コード"], code_to_save)
        if "商品名" in col_map:
            sheet.update_cell(next_row, col_map["商品名"], product_name)
        if "登録日" in col_map:
            sheet.update_cell(next_row, col_map["登録日"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if "画像URL" in col_map:
            sheet.update_cell(next_row, col_map["画像URL"], img_url or "")
        st.success("✅ Google Sheetsに登録しました。")
    except Exception as e:
        st.error(f"GS登録中にエラー: {e}")

# ------------------------------------------------------------
# 🧠 OCR + 検索UI
# ------------------------------------------------------------
input_mode = st.radio("入力方法を選択", ["📷 カメラで撮影", "📁 ファイルアップロード"], horizontal=True)
allow_alnum = st.toggle("英数字もOCRで拾う（Code128対応）", value=False)

image_bytes = None
if input_mode == "📷 カメラで撮影":
    image_file = st.camera_input("バーコードを撮影してください")
else:
    image_file = st.file_uploader("画像をアップロード", type=["jpg", "jpeg", "png"])

if image_file is not None:
    try:
        image_bytes = image_file.getvalue()
        if image_bytes:
            st.image(Image.open(io.BytesIO(image_bytes)), caption="読み取り対象", use_container_width=True)
        else:
            st.warning("⚠️ 画像が空のためプレビューをスキップしました。")
    except Exception as e:
        st.error(f"画像の読み込み中にエラー: {e}")

if image_bytes:
    with st.spinner("🔍 OCR解析中..."):
        ai_code = analyze_code_with_openai(image_bytes, allow_alnum)
    if ai_code:
        st.success(f"📖 認識コード: {ai_code}")
        st.session_state["ai_code"] = ai_code

st.subheader("① コード確認")
jan_input = st.text_input("コード入力（OCR結果を上書き可）", value=st.session_state.get("ai_code", ""))
effective_code = normalize_code(jan_input, allow_alnum=True)
if effective_code:
    st.info(f"🔢 現在の桁数: {len(effective_code)} 桁")

col1, col2 = st.columns(2)
product_name, product_image = None, None
with col1:
    if st.button("🟢 JANCodeLookupから取得"):
        product_name, product_image = get_product_info(effective_code)
with col2:
    if st.button("🟣 Google Sheetsから取得"):
        product_name, product_image = search_gsheet(effective_code)

if product_name:
    st.session_state["product_title"] = product_name
    st.session_state["product_image"] = product_image

st.subheader("② Google Sheetsに登録")
if st.button("💾 登録する", use_container_width=True):
    title = st.session_state.get("product_title", "商品名未取得")
    img_url = st.session_state.get("product_image", None)
    append_to_gsheet(effective_code, title, img_url)
    st.success(f"💾 登録完了：{effective_code} / {title}")
    if img_url:
        st.image(img_url, width=200, caption="登録商品画像")

st.subheader("③ Excelエクスポート")
def export_excel():
    try:
        gs_client = _authorize_gspread()
        if gs_client is None:
            return
        sheet = gs_client.open_by_key("1lIDwaGMx-bMUXsLsF4p9_KmaXCyDPZIVeIdBen6ebE0").sheet1
        df = pd.DataFrame(sheet.get_all_records())
        buf = BytesIO()
        df.to_excel(buf, index=False, engine="xlsxwriter")
        buf.seek(0)
        st.download_button("📥 Excelをダウンロード", buf, "my_shelf_data.xlsx")
    except Exception as e:
        st.error(f"Excel出力エラー: {e}")

export_excel()

st.subheader("④ Google Sheetsを開く")
sheet_url = "https://docs.google.com/spreadsheets/d/1lIDwaGMx-bMUXsLsF4p9_KmaXCyDPZIVeIdBen6ebE0/edit#gid=0"
st.markdown(f"🔗 [Google Sheetsを開く]({sheet_url})", unsafe_allow_html=True)
st.caption("© 2025 my_shelf v1.207 — 新SDK完全対応版（openai>=1.52.0）")
