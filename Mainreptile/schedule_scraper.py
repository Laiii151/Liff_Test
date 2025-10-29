# -*- coding: utf-8 -*-
"""
世新大學 SC0106 只抓《個人課表清單一》+ 截圖《個人課表清單二》
- 僅解析 id=GRD_DataGrid 的表格，欄位與網站相同順序
- 不讀、不截、不處理清單二（Schedule1）
- 匯出：timetable_list1.csv / .json / .xlsx
- 新增：截圖保存課表清單二區域
- 若解析不到，會輸出 list1_debug.html 供排查
"""

import os
import glob  # for font searching
import csv  # for CSV parsing in parse_csv_schedule
import time
import re
import json
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# --- 新增：產生課表圖片所需的 PIL 套件 ---
# Pillow 用於繪製自定義課表圖。若未安裝 Pillow，請在執行環境安裝。
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore


HEADLESS = False     # 需要背景跑可改 True
HOME_URL = "https://www.shu.edu.tw/System-info.aspx"
MAX_WAIT = 25

# 讀 .env 帳密
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

USERNAME = os.getenv("SHU_USERNAME")
PASSWORD = os.getenv("SHU_PASSWORD")
if not USERNAME or not PASSWORD:
    raise SystemExit("❌ 請在 .env 內設定 SHU_USERNAME / SHU_PASSWORD")

LIST1_ORDER = [
    "選別", "課程簡碼", "課程名稱(教材下載)", "開課系級", "學分", "年別",
    "授課老師", "星期節次週別", "教室", "座位序號(行-列)", "備註"
]

def build_driver():
    opt = webdriver.ChromeOptions()
    if HEADLESS:
        opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--lang=zh-TW")
    # 給大一點的視窗避免欄位自動換行造成解析偏差
    opt.add_argument("--window-size=1600,1400")

    # 可用環境變數調整，預設給足夠高度以容納整張清單二
    w = int(os.getenv("WINDOW_W", "1800"))
    h = int(os.getenv("WINDOW_H", "2200"))
    opt.add_argument(f"--window-size={w},{h}")

    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)


def js_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click',{bubbles:true}))", el)

def wait_present(driver, by, sel, timeout=MAX_WAIT):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, sel)))

def save_html(driver, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)

def detect_login_error_and_abort(driver):
    """若頁面顯示帳密錯誤等訊息，立刻截圖並結束程式（exit code 2）。"""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    text_low = (body_text or "").lower()
    keywords = [
        "登入帳號或密碼錯誤", "輸入帳號或密碼錯誤", "帳號或密碼錯誤",
        "login failed", "invalid password", "authentication failed"
    ]
    if any(k.lower() in text_low for k in keywords):
        try:
            driver.save_screenshot("login_error.png")
            save_html(driver, "login_error.html")
        except Exception:
            pass
        # 讓父程式能辨識為登入錯誤
        print("❌ 登入失敗：帳號或密碼錯誤", flush=True)
        try:
            driver.quit()
        except Exception:
            pass
        import os
        os._exit(2)

def wait_login_result_or_error(driver, timeout_seconds: int = 8):
    """提交後短暫輪詢：若出現錯誤訊息立即中止；否則返回繼續流程。"""
    end = time.time() + max(1, timeout_seconds)
    last_err = None
    while time.time() < end:
        try:
            # 先檢查常見訊息容器
            try:
                msg = driver.find_element(By.ID, "lblMessage").text
            except Exception:
                msg = ""
            if msg:
                low = msg.lower()
                if any(k in low for k in [
                    '登入帳號或密碼錯誤', '輸入帳號或密碼錯誤', '帳號或密碼錯誤',
                    'login failed', 'invalid password', 'authentication failed']):
                    print("❌ 登入失敗：", msg)
                    try:
                        driver.save_screenshot('login_error.png')
                        save_html(driver, 'login_error.html')
                    except Exception:
                        pass
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    import os
                    os._exit(2)

            # 泛化檢查
            detect_login_error_and_abort(driver)
        except SystemExit:
            raise
        except Exception as e:
            last_err = e
        time.sleep(0.5)
    # 沒檢出錯誤就返回繼續
    return

def text_clean(s: str) -> str:
    s = (s or "").replace("\xa0", " ")
    s = re.sub(r"[ \t\r]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s).strip()
    return s

# ── 導覽 ─────────────────────────────────────────────────────────────────────
def goto_student_system_from_home(driver):
    driver.get(HOME_URL)

    # 學生教務系統
    for by, sel in [
        (By.CSS_SELECTOR, "body > div:nth-child(10) > div > div.sm-page-all-area > div:nth-child(2) > div.ct-sub-sbox.ct-sub-nsbox.ct-sub-nsortbox > a:nth-child(9)"),
        (By.XPATH, "//a[contains(@href,'stulb.shu.edu.tw')]"),
        (By.XPATH, "//a[contains(.,'學生教務系統')]"),
    ]:
        try:
            el = driver.find_element(by, sel)
            js_click(driver, el)
            break
        except Exception:
            continue
    else:
        driver.execute_script("window.open('https://stulb.shu.edu.tw/','_blank');")

    driver.switch_to.window(driver.window_handles[-1])

def login_if_needed(driver):
    try:
        u = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'],input[autocomplete='username']"))
        )
        p = wait_present(driver, By.CSS_SELECTOR, "input[type='password'],input[autocomplete='current-password']", 8)
        u.clear(); u.send_keys(USERNAME)
        p.clear(); p.send_keys(PASSWORD)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'],button[type='submit']")
            js_click(driver, btn)
        except NoSuchElementException:
            p.submit()
        time.sleep(0.8)
        # 檢查是否顯示登入錯誤（包含輪詢）
        wait_login_result_or_error(driver, timeout_seconds=8)
    except TimeoutException:
        pass  # 沒有登入畫面就 SSO 直通

def open_sc0106(driver):
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame("main")
    except Exception:
        # 若找不到 frame，記錄並改用當前內容繼續，避免整段流程中斷
        try:
            save_html(driver, "frameset_outer.html")
            driver.save_screenshot("no_main_frame.png")
        except Exception:
            pass
        print("[WARN] 找不到 main frame，改用目前頁面繼續。")

    wait_present(driver, By.CSS_SELECTOR, ".label", 15)

    # 課務作業
    js_click(driver, driver.find_element(By.XPATH, "//span[@class='label' and contains(.,'課務作業')]"))
    time.sleep(0.2)

    # SC0106
    for by, sel in [
        (By.XPATH, "//span[contains(.,'SC0106-學生課表查詢')]"),
        (By.XPATH, "//span[contains(.,'學生課表查詢')]"),
    ]:
        try:
            js_click(driver, driver.find_element(by, sel))
            break
        except Exception:
            continue
    else:
        driver.save_screenshot("click_sc0106_fail.png")
        raise RuntimeError("點不到 SC0106-學生課表查詢")

    time.sleep(1.0)

def select_latest_and_search(driver):
    driver.switch_to.default_content()
    driver.switch_to.frame("main")
    # 學年/學期設為最大
    driver.execute_script("""
        const isYear = t => /^\\d{3}$/.test((t||'').trim());
        const isTerm = t => /^(1|2|3|4)$/.test((t||'').trim());
        const sels = Array.from(document.querySelectorAll('select'));
        let ySel=null,tSel=null, yMax=-1, tMax=-1;
        for (const s of sels) {
          const opts = Array.from(s.options).map(o => (o.textContent||o.value||'').trim());
          const ys = opts.filter(isYear).map(Number);
          if (ys.length) { const m=Math.max(...ys); if (m>=yMax){yMax=m;ySel=s;} }
          const ts = opts.filter(isTerm).map(v=>Number(String(v).replace(/\\D/g,'')));
          if (ts.length) { const m=Math.max(...ts); if (m>=tMax){tMax=m;tSel=s;} }
        }
        function setTo(sel, v){
          if(!sel) return false;
          const i = Array.from(sel.options).findIndex(o => (o.textContent||o.value||'').trim()==String(v));
          if(i>=0){ sel.selectedIndex=i; sel.dispatchEvent(new Event('change',{bubbles:true})); return true; }
          return false;
        }
        setTo(ySel, yMax);
        setTo(tSel, tMax);
    """)
    # 搜尋
    for by, sel in [(By.ID, "SRH_search_button"),
                    (By.XPATH, "//input[@type='submit' and contains(@value,'搜尋')]")]:
        try:
            js_click(driver, driver.find_element(by, sel))
            break
        except Exception:
            continue

    # 只等清單一的資料表
    wait_present(driver, By.ID, "GRD_DataGrid", 20)
    time.sleep(0.3)

# ── 只解析清單一 ─────────────────────────────────────────────────────────────
def parse_list1(driver) -> pd.DataFrame:
    driver.switch_to.default_content()
    driver.switch_to.frame("main")

    # 用 JS 從 #GRD_DataGrid 精準把 header + 每列文字抽出；避免拿到任何巢狀表格
    data = driver.execute_script("""
        const tbl = document.getElementById('GRD_DataGrid');
        if(!tbl) return {headers:[], rows:[]};

        const clean = (s) => (s||'').replace(/\\u00a0/g,' ').replace(/[ \\t\\r]+/g,' ')
                                    .replace(/\\n{2,}/g,'\\n').trim();

        const ths = Array.from(tbl.querySelectorAll(':scope > tbody > tr:first-child > td, :scope > tbody > tr:first-child > th'));
        const headers = ths.map(c => clean(c.innerText));

        const trs = Array.from(tbl.querySelectorAll(':scope > tbody > tr')).slice(1);
        const rows = [];
        for (const tr of trs) {
          const tds = Array.from(tr.querySelectorAll(':scope > td, :scope > th'));
          if (!tds.length) continue;
          const vals = [];
          for (let i=0;i<tds.length;i++){
            const td = tds[i];
            let txt = '';
            if (headers[i] && headers[i].includes('課程名稱')) {
              const a = td.querySelector('a');
              if (a) txt = a.innerText;
            }
            if (!txt) txt = td.innerText;
            vals.push(clean(txt));
          }
          // 濾掉整列空白
          if (vals.some(v => v && v.length)) rows.push(vals);
        }
        return {headers, rows};
    """)

    headers = [h for h in data.get("headers", [])]
    rows = data.get("rows", [])

    if not headers or not rows:
        # 萬一 header 沒抓到，用固定欄序備援
        headers = LIST1_ORDER[:]

    # 有些列會比表頭多/少，這裡對齊一下長度
    fixed_rows = []
    for r in rows:
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        fixed_rows.append(r)

    df = pd.DataFrame(fixed_rows, columns=headers)

    # 以網站欄序輸出（缺的就忽略，多的放最後）
    keep = [h for h in LIST1_ORDER if h in df.columns]
    others = [c for c in df.columns if c not in keep]
    return df[keep + others]

# ── 新增：截圖清單二區域 ───────────────────────────────────────────────────────
def screenshot_list2(driver):
    """
    只截《個人課表清單二》——不縮放、不改 CSS。
    作法：定位清單二表格 -> 量測元素尺寸 -> set_window_size 讓它完整可見 -> element.screenshot()
    若元素過高超過上限，改走全頁截圖 + 精準裁切。
    產出：timetable_list2.png
    """

    # 進入主要 frame（若沒有也不報錯）
    try:
        driver.switch_to.default_content()
        driver.switch_to.frame("main")
    except Exception:
        pass

    # 1) 精準找到清單二表格
    target = None
    try:
        heading = driver.find_element(
            By.XPATH,
            "//*[contains(normalize-space(.),'個人課表清單二') or contains(normalize-space(.),'《個人課表清單二》')]"
        )
        target = heading.find_element(By.XPATH, "following::table[1]")
        if target.get_attribute("id") == "GRD_DataGrid":  # 避免誤抓清單一
            target = None
    except Exception:
        target = None

    if target is None:
        try:
            target = driver.find_element(
                By.XPATH,
                "//table[.//text()[contains(.,'第01節')] "
                "and .//text()[contains(.,'星期一')] "
                "and (not(@id) or @id!='GRD_DataGrid')]"
            )
        except Exception:
            target = None

    if target is None:
        print("⚠️ 找不到《個人課表清單二》，改存全頁 timetable_list2_fullpage.png")
        driver.save_screenshot("timetable_list2_fullpage.png")
        return

    # 2) 量測元素尺寸（以 px）並調整視窗尺寸讓它一次容納
    #    留一點 padding 讓邊界方正清楚
    padding = 24
    rect = driver.execute_script("""
        const el = arguments[0];
        const r = el.getBoundingClientRect();
        return {
            x: r.x + window.scrollX,
            y: r.y + window.scrollY,
            w: Math.ceil(r.width),
            h: Math.ceil(r.height),
            vpw: window.innerWidth,
            vph: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        };
    """, target)

    # 目標視窗寬高（盡量讓整張表一次進可視區）
    desired_width  = max(rect["vpw"], rect["w"] + padding * 2)
    desired_height = max(rect["vph"], rect["h"] + padding * 2)

    # 視窗高度安全上限（避免某些環境下過大造成無法 set）
    MAX_H = 3000
    desired_height = min(desired_height, MAX_H)

    try:
        driver.set_window_size(int(desired_width), int(desired_height))
        time.sleep(0.5)  # 讓 layout 重新排定
    except Exception as e:
        print(f"⚠️ set_window_size 失敗：{e}")

    # 滾動使表格靠近視窗中央，避免被頂部工具列擋住
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
    time.sleep(0.5)

    # 3) 優先用 element.screenshot() —— 取得方正清楚的表格圖
    try:
        ok = target.screenshot("timetable_list2.png")
        if ok:
            print(f"📸 timetable_list2.png（element.screenshot，視窗 {desired_width}x{desired_height}）")
            return
    except Exception as e:
        print(f"⚠️ element.screenshot 失敗，fallback：{e}")

    # 4) Fallback：全頁截圖 + 精準裁切（只留小 padding，保持方正）
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.3)
    driver.save_screenshot("temp_full.png")

    try:
        from PIL import Image
    except ImportError:
        print("⚠️ 未安裝 Pillow，保留全頁 temp_full.png")
        return

    # 重新量測（避免 set_window_size 後數值變動）
    rect = driver.execute_script("""
        const el = arguments[0];
        const r = el.getBoundingClientRect();
        return {
            x: r.x + window.scrollX,
            y: r.y + window.scrollY,
            w: Math.ceil(r.width),
            h: Math.ceil(r.height),
            dpr: window.devicePixelRatio || 1
        };
    """, target)

    img = Image.open("temp_full.png")
    dpr = float(rect.get("dpr", 1.0)) or 1.0
    pad = int(padding * dpr)

    left   = max(0, int(rect["x"] * dpr) - pad)
    top    = max(0, int(rect["y"] * dpr) - pad)
    right  = min(img.width,  int((rect["x"] + rect["w"]) * dpr) + pad)
    bottom = min(img.height, int((rect["y"] + rect["h"]) * dpr) + pad)

    if right <= left or bottom <= top:
        print("⚠️ 裁切座標異常，保存全頁 timetable_list2_fullpage.png")
        img.save("timetable_list2_fullpage.png")
    else:
        img.crop((left, top, right, bottom)).save("timetable_list2.png")
        print(f"📸 timetable_list2.png（fallback 裁切，padding={padding}px）")

    try:
        os.remove("temp_full.png")
    except Exception:
        pass


# ── 新增：依 CSV 生出課表清單二圖檔 ─────────────────────────────────────
# 以下三個函式取自 generate_timetable.py，調整為在本腳本中使用。
def load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    嘗試載入適用的中文字型。若無可用字型，將退回 PIL 的預設字型。

    此函式盡可能地在不同平台上尋找支援中文的字型。它首先檢查
    環境變數 `SHU_TIMETABLE_FONT`（可設為自定義字型路徑），然後再
    在系統字型目錄中遞迴搜尋常見的中文字型，例如 Noto CJK、微軟正黑體、
    蘋方體等。若依然找不到合適字型，會回退至一般 Noto Sans 或系統預設字型。
    """
    # 若 Pillow 沒有成功導入，直接使用預設字型
    if ImageFont is None:
        return ImageFont.load_default()  # type: ignore

    # 如果使用者透過環境變數指定字型路徑，優先使用
    env_font = os.getenv("SHU_TIMETABLE_FONT")
    if env_font:
        # 環境變數可以是多個路徑以冒號分隔
        for candidate in env_font.split(":"):
            candidate = candidate.strip()
            if candidate and os.path.exists(candidate):
                try:
                    return ImageFont.truetype(candidate, size)  # type: ignore
                except Exception:
                    continue

    # 定義在不同平台常見的字型搜尋目錄
    search_dirs = [
        "/usr/share/fonts",               # Linux 系統常見
        "/usr/local/share/fonts",         # Linux 其他
        "/System/Library/Fonts",          # macOS 系統字型
        "/Library/Fonts",                # macOS 使用者安裝字型
        "C:\\Windows\\Fonts",           # Windows 系統字型
    ]
    # 定義優先搜尋的模式，包含 CJK、TC、SC、HK 等關鍵字
    search_patterns = [
        "*NotoSans*CJ*K*.*", "*NotoSerif*CJ*K*.*",   # Noto CJK 系列
        "*NotoSans*TC*.*", "*NotoSerif*TC*.*",       # Noto 臺灣用字型
        "*PingFang*.*", "*Heiti*.*", "*Song*.*", "*Kai*.*",  # 蘋方體、黑體、宋體、楷體
        "*SimSun*.*", "*SimHei*.*", "*Microsoft*JhengHei*.*",  # Windows 常見中文字型
        "*MS*JhengHei*.*", "*MingLiU*.*",            # 補充 Windows/台灣字型
    ]

    # 廣度搜尋函式：依序尋找第一個可用的字型檔
    def find_font_file() -> str:
        # 若開發環境中包含與本腳本同目錄的字型，優先取用。先挑含關鍵字的檔案，其次任何字型檔。
        local_dir = os.path.dirname(os.path.abspath(__file__))
        # 首先尋找檔名含有中文關鍵字（CJK/TC/SC/HK/Hei/Ming/Kai/Song）的字型
        for pattern in ["*.ttf", "*.ttc", "*.otf"]:
            for path in glob.glob(os.path.join(local_dir, pattern)):
                lower = os.path.basename(path).lower()
                if any(k in lower for k in ["cjk", "tc", "sc", "hk", "hei", "ming", "kai", "song"]):
                    return path
        # 若沒有符合關鍵字，再取第一個字型檔作為候選
        for pattern in ["*.ttf", "*.ttc", "*.otf"]:
            files = glob.glob(os.path.join(local_dir, pattern))
            if files:
                return files[0]
        # 遍歷所有搜尋目錄與模式
        for root in search_dirs:
            for sp in search_patterns:
                try:
                    for path in glob.glob(os.path.join(root, "**", sp), recursive=True):
                        if os.path.isfile(path):
                            return path
                except Exception:
                    continue
        # 若尚未找到，再嘗試掃描 Noto CJK 固定路徑
        fallback_paths = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
        ]
        for p in fallback_paths:
            if os.path.exists(p):
                return p
        return ""

    # 嘗試找到字型檔並載入
    font_file = find_font_file()
    if font_file:
        try:
            return ImageFont.truetype(font_file, size)  # type: ignore
        except Exception:
            pass

    # 最後退回一些較一般的字型，雖然可能不支援中文，但總比亂碼來得好
    general_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    for p in general_fonts:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)  # type: ignore
            except Exception:
                continue

    # 萬不得已，使用 PIL 預設字型
    return ImageFont.load_default()  # type: ignore


def parse_csv_schedule(csv_path: str):
    """
    解析課表 CSV，回傳課程事件清單。

    每個事件包含：
        - day (int): 星期幾，週一=1，週日=7
        - start (int): 起始節次（1–14）
        - end (int): 結束節次（1–14）
        - name (str): 課程名稱
        - classroom (str): 教室名稱

    CSV 預期包含標頭列，且具欄位「課程名稱(教材下載)」、「星期節次週別」、「教室」。
    若欄位缺失則略過。
    """
    day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
    events = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)  # type: ignore
            for row in reader:
                name = (row.get("課程名稱(教材下載)") or "").strip()
                classroom = (row.get("教室") or "").strip()
                schedule_field = (row.get("星期節次週別") or "").strip()
                if not schedule_field:
                    continue
                for sched in schedule_field.split("\n"):
                    sched = sched.strip()
                    if not sched:
                        continue
                    parts = sched.split("-")
                    if len(parts) >= 2:
                        day_char = parts[0].strip()
                        period_range = parts[1].strip()
                        if day_char not in day_map:
                            continue
                        day_num = day_map[day_char]
                        if "~" in period_range:
                            start_str, end_str = period_range.split("~", 1)
                            try:
                                start = int(start_str)
                                end = int(end_str)
                            except ValueError:
                                continue
                        else:
                            try:
                                start = end = int(period_range)
                            except ValueError:
                                continue
                        events.append({
                            "day": day_num,
                            "start": start,
                            "end": end,
                            "name": name,
                            "classroom": classroom,
                        })
    except Exception:
        # 若無法讀取 CSV，返回空清單
        return []
    # 移除重複事件
    unique_events = []
    seen = set()
    for e in events:
        key = (e["day"], e["start"], e["end"], e["name"], e["classroom"])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    return unique_events


def draw_timetable(events, output_path: str, width: int = 800, height: int = 800):
    """
    根據課程事件列表繪製一張 800×800 的課表圖，並將其存為 PNG。

    若 PIL 未安裝或無法載入，則不產生圖片。
    """
    # 若無 Pillow，直接略過生成圖片
    if Image is None or ImageDraw is None or ImageFont is None:
        print("⚠️ Pillow 未安裝，無法產生課表圖片。")
        return
    # 畫布設定
    title_height = 60
    header_height = 40
    period_count = 14
    period_height = (height - title_height - header_height) / period_count
    left_col_width = 150
    day_count = 7
    day_width = (width - left_col_width) / day_count
    period_times = {
        1: "08:10–09:00", 2: "09:10–10:00", 3: "10:10–11:00", 4: "11:10–12:00",
        5: "12:10–13:00", 6: "13:10–14:00", 7: "14:10–15:00", 8: "15:10–16:00",
        9: "16:10–17:00", 10: "17:10–18:00", 11: "18:10–19:00", 12: "19:10–20:00",
        13: "20:10–21:00", 14: "21:10–22:00",
    }
    day_labels = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(32)
    header_font = load_font(20)
    label_font = load_font(14)
    # 量測文字寬高的輔助函式，兼容不同 Pillow 版本
    def measure_text(text: str, font: ImageFont.FreeTypeFont):
        """Return (width, height) of the given text using available PIL methods."""
        # 首先嘗試使用 textbbox（Pillow 8.0+）
        try:
            bbox = draw.textbbox((0, 0), text, font=font)  # type: ignore
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            pass
        # 再試 font.getbbox（Pillow 9.2+）
        try:
            bbox = font.getbbox(text)  # type: ignore
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            pass
        # 最後退回 font.getsize（舊版 Pillow）
        try:
            return font.getsize(text)  # type: ignore
        except Exception:
            return (0, 0)

    # 標題
    title_text = "世新大學課表"
    tw, th = measure_text(title_text, title_font)
    draw.text(((width - tw) / 2, (title_height - th) / 2), title_text, fill=(0, 0, 0), font=title_font)
    # 分割線
    draw.line([(0, title_height), (width, title_height)], fill=(0, 0, 0))
    # 星期標題
    for i, label in enumerate(day_labels):
        x0 = left_col_width + i * day_width
        tw2, th2 = measure_text(label, header_font)
        tx = x0 + (day_width - tw2) / 2
        ty = title_height + (header_height - th2) / 2
        draw.text((tx, ty), label, fill=(0, 0, 0), font=header_font)
    header_bottom = title_height + header_height
    draw.line([(0, header_bottom), (width, header_bottom)], fill=(0, 0, 0))
    draw.line([(left_col_width, title_height), (left_col_width, height)], fill=(0, 0, 0))
    # 節次標籤與水平格線
    for p in range(1, period_count + 1):
        y0 = header_bottom + (p - 1) * period_height
        # 淡灰色水平線
        draw.line([(left_col_width, y0), (width, y0)], fill=(220, 220, 220))
        period_label = f"第{p:02d}節"
        time_label = period_times.get(p, "")
        draw.text((5, y0 + (period_height - 28) / 2), period_label, fill=(0, 0, 0), font=label_font)
        draw.text((60, y0 + (period_height - 28) / 2), time_label, fill=(0, 0, 0), font=label_font)
    # 最底水平線
    draw.line([(left_col_width, header_bottom + period_count * period_height), (width, header_bottom + period_count * period_height)], fill=(220, 220, 220))
    # 垂直格線
    for i in range(day_count + 1):
        x = left_col_width + i * day_width
        draw.line([(x, header_bottom), (x, height)], fill=(220, 220, 220))
    # 顏色配置
    fill_colors = [
        (233, 243, 255), (255, 242, 204), (230, 242, 255), (242, 230, 255)
    ]
    outline_color = (180, 200, 220)
    # 文字換行函式
    def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float):
        s = text.replace(" ", "")
        lines = []
        current = ""
        for ch in s:
            test = current + ch
            w, _ = measure_text(test, font)
            if w <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
        return lines
    # 畫課程區塊
    for idx, event in enumerate(events):
        day_index = event.get("day", 1) - 1
        start_period = max(1, min(period_count, event.get("start", 1)))
        end_period = max(1, min(period_count, event.get("end", 1)))
        x0 = left_col_width + day_index * day_width + 1
        y0 = header_bottom + (start_period - 1) * period_height + 1
        rect_width = day_width - 2
        rect_height = (end_period - start_period + 1) * period_height - 2
        fill_color = fill_colors[idx % len(fill_colors)]
        draw.rectangle([x0, y0, x0 + rect_width, y0 + rect_height], fill=fill_color, outline=outline_color)
        # 準備文字：課程名稱與教室
        name = event.get("name", "")
        classroom = event.get("classroom", "")
        # 動態調整字號與換行，使文字能在區塊內顯示完整不超界
        font_size = 14
        min_font_size = 8
        content_lines = None
        content_font = None
        while font_size >= min_font_size:
            content_font = load_font(font_size)
            avail_width = rect_width - 8
            lines_name = wrap_text(name, content_font, avail_width)
            lines_room = []
            if classroom:
                room = classroom.split("\n")[0]
                lines_room = wrap_text(room, content_font, avail_width)
            content_lines = lines_name + lines_room
            total_text_height = 0
            line_sizes = []
            for line in content_lines:
                w, h = measure_text(line, content_font)
                line_sizes.append((w, h))
                total_text_height += h
            total_text_height += max(len(content_lines) - 1, 0) * 2
            if total_text_height <= rect_height:
                break
            font_size -= 1
        ty = y0 + (rect_height - total_text_height) / 2
        current_y = ty
        for (line, (w, h)) in zip(content_lines, line_sizes):
            x_line = x0 + (rect_width - w) / 2
            draw.text((x_line, current_y), line, fill=(0, 0, 0), font=content_font)
            current_y += h + 2
    image.save(output_path)


# ── 主程式 ───────────────────────────────────────────────────────────────────
def main():
    driver = build_driver()
    try:
        print("🚀 啟動：只抓清單一 + 截圖清單二")
        goto_student_system_from_home(driver)
        login_if_needed(driver)
        open_sc0106(driver)
        select_latest_and_search(driver)

        df = parse_list1(driver)
        if df.empty:
            save_html(driver, "list1_debug.html")
            raise RuntimeError("清單一解析不到資料；已輸出 list1_debug.html 供檢查")

        # 匯出清單一（不做 pivot/merge/展開節次，完全照清單一）
        df.to_csv("timetable_list1.csv", index=False, encoding="utf-8-sig")
        df.to_json("timetable_list1.json", orient="records", force_ascii=False, indent=2)

        with pd.ExcelWriter("timetable_list1.xlsx", engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="清單一")
            ws = writer.sheets["清單一"]
            # 簡單寬度（可依需求調整）
            width_map = {
                "選別": 6, "課程簡碼": 18, "課程名稱(教材下載)": 28, "開課系級": 16,
                "學分": 6, "年別": 6, "授課老師": 12, "星期節次週別": 20, "教室": 18,
                "座位序號(行-列)": 14, "備註": 36
            }
            for col, w in width_map.items():
                if col in df.columns:
                    ci = df.columns.get_loc(col)
                    ws.set_column(ci, ci, w)

        print("✅ 清單一完成：timetable_list1.(csv/json/xlsx) 已產生")

        # ==== 產生清單二課表圖檔 ====
        # 解析剛產出的 CSV，並用內建函式繪製成固定大小的圖片。
        try:
            events = parse_csv_schedule("timetable_list1.csv")
            if events:
                draw_timetable(events, "timetable_list2.png")
                print("🎨 已依據 CSV 產生 timetable_list2.png")
            else:
                print("⚠️ CSV 解析沒有找到任何課程，未產生 timetable_list2.png")
        except Exception as e:
            print(f"⚠️ 產生清單二圖檔失敗：{e}")

        # 若仍想保留網站截圖作為備援，可取消以下註解
        # print("📸 開始截圖課表清單二...")
        # screenshot_list2(driver)
        # print("🎉 全部完成：清單一資料 + 清單二截圖")
        
        print("🎉 全部完成：清單一資料與 timetable_list2.png 圖檔")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()