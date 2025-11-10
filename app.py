import os
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, flash
from linebot import LineBotApi
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.v3.messaging import MessagingApi
import Login
import requests
import sys
import time
import glob
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

# --- 導入 Google Drive 相關套件 ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
logged_in_users = {}
app.secret_key = os.getenv('APPSECRET', '135e933ae3e4b0a3a0d2282804ff62b9')

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'KhSmwJno9143P5bt4klOIOxcWM6bNEBXDGb2XO+vEP6z9yN4eSI6rp98MH2cM/AYRar2syaGbEzZHimXv5XFjErtIFk3isMgBd5AqecVxinW/S3JTB/vxqWC2BBHE/CbFRXXisJsy6xECx7RCkHoFAdB04t89/1O/w1cDnyilFU=')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
MAKE_LOGIN_SUCCESS_WEBHOOK = "https://hook.us2.make.com/1y1j6dav8u18s38s4s45qaa7od3qst7k"

# ====================================
# === Google Drive 設定與函式 ===
# ====================================

# 存取權限範圍：讀取和寫入 Google Drive 中由程式創建和開啟的檔案
SCOPES = ['https://www.googleapis.com/auth/drive.file']
# 儲存認證結果的檔案名稱
TOKEN_FILE = 'token.json'
# 您的 Google Cloud 下載的憑證檔案名稱
CLIENT_SECRETS_FILE = 'client_secrets.json'

# TODO: 請將此變數替換成您 Google Drive 上的目標資料夾 ID
# 如果留空 (None)，檔案會上傳到 My Drive 的根目錄
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", None) 
# 您也可以在 .env 檔案中設定 GDRIVE_FOLDER_ID="您的資料夾ID"

def authenticate():
    """
    處理 Google Drive API 的 OAuth 認證流程。
    會檢查 token.json，若過期或不存在，則會開啟瀏覽器要求用戶授權。
    """
    creds = None
    # 檢查是否有儲存的 token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # 如果沒有有效的憑證，或憑證過期
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # 啟動應用程式流程 (InstalledAppFlow)
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES)
            # 在本地伺服器上執行流程，自動在瀏覽器中完成授權
            creds = flow.run_local_server(port=0)

        # 儲存憑證以供下次使用
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
    return creds
def find_or_create_folder(service, folder_name, parent_folder_id=None):
    """
    在 Google Drive 上尋找指定名稱的資料夾。
    如果找不到，則建立一個新的資料夾。
    """
    # 建立查詢字串
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    
    # 如果有指定父資料夾，則只在該資料夾內尋找
    if parent_folder_id:
        query += f" and '{parent_folder_id}' in parents"
    
    # 執行搜尋
    response = service.files().list(
        q=query,
        spaces='drive',
        fields='nextPageToken, files(id, name)'
    ).execute()
    
    # 如果找到，回傳第一個資料夾的 ID
    files = response.get('files', [])
    if files:
        print(f"📂 找到現有資料夾: {folder_name} (ID: {files[0]['id']})")
        return files[0]['id']

    # 如果沒找到，則建立新的資料夾
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
        
    folder = service.files().create(body=file_metadata, fields='id').execute()
    print(f"📁 已建立新資料夾: {folder_name} (ID: {folder.get('id')})")
    return folder.get('id')

BASE_DIR = Path(__file__).parent.resolve()
SCRIPTS = {
    "timetable": str((BASE_DIR / "Mainreptile" / "schedule_scraper.py").resolve()),
    "grades":    str((BASE_DIR / "Mainreptile" / "grade.py").resolve()),
    "ranking":   str((BASE_DIR / "Mainreptile" / "ranking_scraper.py").resolve()),
    "attendance":str((BASE_DIR / "Mainreptile" / "attendance_scraper.py").resolve()),
}

# 各腳本跑完後**預期**會產生的檔案（用來找最新一份）
OUTPUTS = {
    "timetable": ["timetable_list1.csv"],
    "grades":    ["grades_courses_fixed.csv", "grades_summary_fixed.csv"],
    "ranking":   ["ranking_records.csv"],
    "attendance":["attendance_records.csv"],
}


# 在 Windows 通常用 "python"，在虛擬環境/其他系統用 sys.executable 比較穩
PYTHON_BIN = sys.executable or "python"

# 使用者資料夾根目錄
DATA_ROOT = Path("data")
DATA_ROOT.mkdir(exist_ok=True)

# 各類型預設逾時秒數（避免子行程無限卡住）
SCRIPT_TIMEOUTS = {
    "timetable": int(os.getenv("TIMEOUT_TIMETABLE", "240")),
    "grades":    int(os.getenv("TIMEOUT_GRADES", "300")),
    "ranking":   int(os.getenv("TIMEOUT_RANKING", "300")),
    "attendance":int(os.getenv("TIMEOUT_ATTENDANCE", "300")),
}

# ... [您原來的 run_script, _log_contains_login_error, _diagnose_message, latest_existing, load_csv_safely, filter_df 函式]
def run_script(kind: str, env_override: Dict[str, Any], work_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    呼叫對應的爬蟲腳本。回傳 process returncode。
    會把 SHU_USERNAME / SHU_PASSWORD / HEADLESS 等環境變數覆寫進去（不落地存檔）。
    """
    script = SCRIPTS.get(kind)
    if not script or not Path(script).exists():
        raise FileNotFoundError(f"找不到爬蟲腳本：{script}（請確認 SCRIPTS 設定與檔名）")

    env = os.environ.copy()
    env.update({k: str(v) for k, v in env_override.items() if v is not None})
    # 強制子行程以 UTF-8 輸出，避免 Windows cp950 解碼錯誤
    env["PYTHONIOENCODING"] = "utf-8"

    # 讓 selenium 在 server 上能跑
    if "HEADLESS" not in env:
        env["HEADLESS"] = os.getenv("HEADLESS", "True")

    # 執行
    run_cwd = Path(work_dir) if work_dir else Path.cwd()
    print(f"[RUN] {PYTHON_BIN} {script} (cwd={run_cwd})")
    try:
        proc = subprocess.run(
            [PYTHON_BIN, script],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(run_cwd),
            timeout=SCRIPT_TIMEOUTS.get(kind, 300)
        )
        ret_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as te:
        ret_code = 124 # 常見的 timeout 代碼
        stdout = (te.stdout or "") if hasattr(te, "stdout") else ""
        stderr = (te.stderr or "") if hasattr(te, "stderr") else ""
        stderr += "\n[ERROR] 子行程執行逾時，已中止。"
    # 把標準輸出／錯誤留檔方便除錯（存到使用者資料夾下的 logs/）
    ts = int(time.time())
    logs_dir = run_cwd/"logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_path = logs_dir/f"{kind}_{ts}.out.txt"
    err_path = logs_dir/f"{kind}_{ts}.err.txt"
    out_path.write_text(stdout, encoding="utf-8")
    err_path.write_text(stderr, encoding="utf-8")
    print(f"[RET] code={ret_code}")
    return {"code": ret_code, "out": str(out_path), "err": str(err_path)}

def latest_existing(path_patterns):
    """
    回傳符合任一 pattern 的**最新**檔案路徑（找不到回傳 None）
    """
    candidates = []
    for pat in path_patterns:
        candidates.extend(glob.glob(pat))
    if not candidates:
        return None
    candidates.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
    return candidates[0]


def load_csv_safely(path: str) -> pd.DataFrame:
    """
    嘗試用 UTF-8-SIG 讀，失敗就用 UTF-8。
    """
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.read_csv(path, encoding="utf-8")

def upload_replace(service, local_path: str, remote_name: str, parent_folder_id: str, mime_type: str) -> str:
    """
    將 local_path 上傳到 Google Drive 的 parent_folder_id，
    上傳前先刪除該資料夾內同名 (remote_name) 舊檔，只保留最新檔。
    回傳新檔 fileId。
    """
    # 1) 刪除同名舊檔（僅該資料夾內）
    query = (
        f"name='{remote_name}' and '{parent_folder_id}' in parents and trashed=false"
    )
    resp = service.files().list(q=query, spaces="drive", fields="files(id,name)").execute()
    for f in resp.get("files", []):
        try:
            service.files().delete(fileId=f["id"]).execute()
            print(f"🗑️ 已刪除舊檔：{f['name']} ({f['id']})")
        except Exception as de:
            print(f"⚠️ 刪除舊檔失敗：{de}")

    # 2) 上傳新檔（同名）
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    metadata = {
        "name": remote_name,
        "parents": [parent_folder_id],
    }
    newf = service.files().create(body=metadata, media_body=media, fields="id").execute()
    print(f"📤 已上傳新檔：{remote_name} -> {newf.get('id')}")
    return newf.get("id")
def callscraper():
    
    data = request.get_json()
    line_user_id = data.get('lineUserId')
    student_id = data.get('studentId').strip()
    password = data.get('password')
           # 主要訊息內容，統一管理
    msg = "系統已開始自動同步教務資料，可關閉此網頁並稍後於雲端查詢。"
    # 執行爬蟲與上傳流程（不把細節/結果回傳給前端，只印 terminal log）
    try:
        effective_user = student_id
        work_dir = DATA_ROOT / str(effective_user)
        work_dir.mkdir(parents=True, exist_ok=True)
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)
        root_folder_id = GDRIVE_FOLDER_ID
        target_folder_id = find_or_create_folder(service, effective_user, parent_folder_id=root_folder_id)
        for kind, script_path in SCRIPTS.items():
            res = run_script(kind, {"SHU_USERNAME": student_id, "SHU_PASSWORD": password}, work_dir=work_dir)
            print(f"[{kind}] 爬蟲 code={res.get('code')}")
            if kind == 'timetable':
                png_path = work_dir / 'timetable_list2.png'
                if png_path.exists():
                    try:
                        upload_replace(service, str(png_path), 'timetable_list2.png', target_folder_id, "image/png")
                        print("[timetable] PNG 上傳成功")
                    except Exception as ex:
                        print(f"[timetable] PNG 上傳失敗：{ex}")
                else:
                    print("[timetable] PNG 檔案不存在，略過")
            outputs = OUTPUTS.get(kind, [])
            for output_name in outputs:
                csv_path = latest_existing([str(work_dir / output_name)])
                
                if csv_path:
                    try:
                        creds = authenticate()
                        service = build('drive', 'v3', credentials=creds)

                        root_folder_id = GDRIVE_FOLDER_ID
                        target_folder_id = find_or_create_folder(service, effective_user, parent_folder_id=root_folder_id)

                        # 固定雲端檔名（= 本地檔名），確保覆蓋同名舊檔
                        remote_filename = Path(csv_path).name

                        # 先刪同名舊檔（只在該資料夾中）
                        query = f"name='{remote_filename}' and '{target_folder_id}' in parents and trashed=false"
                        resp = service.files().list(q=query, spaces="drive", fields="files(id,name)").execute()
                        for f in resp.get("files", []):
                            try:
                                service.files().delete(fileId=f["id"]).execute()
                                print(f"🗑️ 已刪除舊檔：{f['name']} ({f['id']})")
                            except Exception as de:
                                print(f"⚠️ 刪除舊檔失敗：{de}")

                        # 上傳並轉成 Google 試算表
                        file_metadata = {
                            'name': remote_filename,
                            'mimeType': 'application/vnd.google-apps.spreadsheet',
                            'parents': [target_folder_id]
                        }
                        media = MediaFileUpload(csv_path, mimetype='application/vnd.google-apps.spreadsheet')

                        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

                        print(f"[{kind}] CSV 上傳成功: {remote_filename}")
                        success = True

                    except Exception as e:
                        print(f"[{kind}] CSV 上傳失敗: {ex}")
                        success = False
                else:
                    print(f"[{kind}] 未產生 {output_name}")
    except Exception as ex:
        print(f"整體同步失敗：{ex}")

    response_data = {
            "success": True,
            "message": msg,
            "studentId": student_id,
            "password": password
        }
    # API直接回傳統一成功訊息，讓前端可顯示
    return jsonify(response_data)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/verify_login', methods=['POST'])
def verify_login():
    data = request.get_json()
    line_user_id = data.get('lineUserId')
    student_id = data.get('studentId').strip()
    password = data.get('password')

    # 1. 檢查是否已登入
    if line_user_id in logged_in_users:
        # 已登入的邏輯
        msg = "您已成功登入，不須再登入"
        
        # 提取之前儲存的資料
        stored_data = logged_in_users[line_user_id]

        # 推播訊息給 Line 用戶並在推播完成後執行爬蟲
        if line_user_id:
            try:
                # 使用 push_message 代替 reply_message，因為此處沒有 replyToken
                line_bot_api.push_message(line_user_id, TextSendMessage(text=msg))
                
            except Exception as e:
                print(f"推播訊息失敗: {e}")

        # 回傳成功狀態與儲存的資料
        return jsonify({
            "success": True,
            "message": msg,
            "studentId": stored_data['student_id'],
            "password": stored_data['password']
        })
    
    # 2. 執行新的登入驗證
    success = Login.main(student_id, password)

    response_data: Dict[str, Any] = {}

    if success:
        msg = "教務系統登入成功！可以關閉此網頁。"

        # 3. 登入成功後儲存 Line User ID 與憑證
        logged_in_users[line_user_id] = {
            'student_id': student_id,
            'password': password
        }
        # ***** 新增：將資料發送到 Make *****
        if MAKE_LOGIN_SUCCESS_WEBHOOK:
            try:
                make_payload = {
                    "success": True,
                    "lineUserId": line_user_id,
                    "studentId": student_id,
                    "password": password
                }
                # 發送 POST 請求給 Make
                response = requests.post(MAKE_LOGIN_SUCCESS_WEBHOOK, json=make_payload, timeout=10)
                # 增加狀態碼檢查，讓日誌更清晰
                if response.status_code == 200 or response.status_code == 202:
                    print(f"🎉 成功發送登入通知到 Make. 狀態碼: {response.status_code}")
                else:
                    print(f"⚠️ 發送登入通知到 Make 失敗. 狀態碼: {response.status_code}. 錯誤內容: {response.text}")
            except Exception as e:
                print(f"發送登入成功通知到 Make 失敗: {e}")
        # **********************************
        # 將成功登入的資料回傳
        response_data = {
            "success": True,
            "message": msg,
            "studentId": student_id,
            "password": password
        }
        # 發送完成後觸發爬蟲，同步教務資料
        callscraper()
        msg = "系統已自動同步教務資料，可關閉此網頁並稍後於雲端查詢。"   

    else:
        msg = "教務系統登入失敗，請確認帳號密碼後重試。"
        response_data = {
            "success": False,
            "message": msg
        }
        
    line_bot_api.push_message(line_user_id, TextSendMessage(text=msg))
    # 回傳最終結果
    
    return jsonify(response_data)
    

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
    
