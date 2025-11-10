# -*- coding: utf-8 -*-

import time
import os
from typing import List, Tuple, Optional, Dict, Any
import re
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# 載入環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ 已載入 .env 檔案")
except ImportError:
    print("⚠️ 未安裝 python-dotenv，請執行: pip install python-dotenv")
    print("⚠️ 或手動設定環境變數")

# ========= 設定區 =========
# 從環境變數讀取帳號密碼
USERNAME = os.getenv('SHU_USERNAME')
PASSWORD = os.getenv('SHU_PASSWORD')

# 檢查是否有設定帳號密碼
if not USERNAME or not PASSWORD:
    print("❌ 錯誤：請在 .env 檔案中設定 SHU_USERNAME 和 SHU_PASSWORD")
    print("📝 .env 檔案格式範例：")
    print("SHU_USERNAME=你的學號")
    print("SHU_PASSWORD=你的密碼")
    raise ValueError("❌ 致命錯誤：SHU_USERNAME 或 SHU_PASSWORD 環境變數未設定！")

#HOME_URL = "https://www.shu.edu.tw/System-info.aspx"
HOME_URL = "https://stulb.shu.edu.tw/"
HEADLESS = False
MAX_WAIT = 25

print(f"🔐 使用帳號：{USERNAME[:3]}***{USERNAME[-3:] if len(USERNAME) > 6 else '***'}")  # 部分遮蔽帳號

# ---------------- 基礎工具函數 ----------------
def build_driver():
    opt = webdriver.ChromeOptions()
    HEADLESS = os.getenv("HEADLESS", "False").lower() in ("true", "1")
    if HEADLESS:
        opt.add_argument("--headless=new")
            # ====== 修正：禁用 GCM 和其他會引發錯誤的服務 ======
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-notifications") # 禁用瀏覽器通知
    opt.add_argument("--disable-infobars")
    # 禁用所有不需要的 Chrome 服務，特別是 GCM/Cloud Messaging
    opt.add_argument("--disable-features=NetworkService,NetworkServiceInProcess")
    opt.add_argument("--disable-background-networking")
    opt.add_argument("--disable-default-apps")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--disable-logging") # 減少日誌輸出
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1440,900")
    opt.add_argument("--disable-dev-shm-usage") # 尤其在 Docker 中非常重要
    opt.add_argument("--disable-software-rasterizer")
    opt.add_argument("--disable-extensions")
    opt.add_argument("--log-level=3") # 減少日誌輸出
    chrome_bin = os.getenv('CHROME_BIN') 
    if chrome_bin:
        opt.binary_location = chrome_bin
    return webdriver.Chrome(options=opt)
    #return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)

def js_click(driver, el):
    driver.execute_script("""
        const el = arguments[0];
        el.scrollIntoView({block:'center'});
        try{ el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true})); }catch(e){}
        try{ el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true})); }catch(e){}
        try{ el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true})); }catch(e){}
        try{ el.click(); }catch(e){}
    """, el)

def find_and_js_click(driver, selector: str, by="css") -> bool:
    try:
        el = driver.find_element(By.CSS_SELECTOR, selector) if by=="css" else driver.find_element(By.XPATH, selector)
        js_click(driver, el)
        return True
    except Exception:
        return False

def click_first_working(driver, selectors: List[Tuple[str, str]]) -> bool:
    for by, sel in selectors:
        if find_and_js_click(driver, sel, by=by):
            return True
    return False

def save_html(driver, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)

def _die(driver, msg, png, html):
    driver.save_screenshot(png)
    save_html(driver, html)
    raise RuntimeError(f"{msg}；已存 {png} / {html}")

# ---------------- 導覽函數 ----------------
def goto_student_system_from_home(driver):
    driver.get(HOME_URL)
    # 學生教務系統
    """ok = click_first_working(driver, [
        ("css",  "body > div:nth-child(10) > div > div.sm-page-all-area > div:nth-child(2) > div.ct-sub-sbox.ct-sub-nsbox.ct-sub-nsortbox > a:nth-child(9)"),
        ("css",  "body > div:nth-child(11) > div > div.sm-page-all-area > div:nth-child(2) > div.ct-sub-sbox.ct-sub-nsbox.ct-sub-nsortbox > a:nth-child(9)"),
        ("xpath","//a[contains(@href,'stulb.shu.edu.tw')]"),
        ("xpath","//a[normalize-space()='學生教務系統' or contains(normalize-space(.),'學生教務系統')]"),
    ])
    if not ok:
        driver.execute_script("window.open('https://stulb.shu.edu.tw/','_blank');")

    driver.switch_to.window(driver.window_handles[-1])"""

def login_if_needed(driver):
    try:
        u = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'],input[autocomplete='username']"))
        )
        p = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'],input[autocomplete='current-password']"))
        )
        u.clear()
        u.send_keys(USERNAME)
        p.clear()
        p.send_keys(PASSWORD)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'],button[type='submit']")
            js_click(driver, btn)
        except NoSuchElementException:
            p.submit()
        time.sleep(1.2)
    except TimeoutException:
        pass

def open_grade_history(driver):
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame("main")
    except Exception:
        _die(driver, "找不到 main frame", "no_main_frame.png", "frameset_outer.html")

    WebDriverWait(driver, 8).until(lambda d: d.execute_script("return document.readyState") == "complete")
    try:
        WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".label")))
    except TimeoutException:
        _die(driver, "main frame 內未出現 .label", "main_no_labels.png", "main_no_labels.html")

    def click_label(text) -> bool:
        return driver.execute_script("""
            const wanted = arguments[0].trim();
            const els = Array.from(document.querySelectorAll('.label, a, button, span, div'));
            for (const el of els) {
              const t = (el.textContent || '').trim();
              if (t === wanted) {
                el.scrollIntoView({block:'center'});
                try { el.click(); return true; } catch(e){}
                try { el.parentElement?.click(); return true; } catch(e){}
              }
            }
            return false;
        """, text)

    # 點擊成績作業
    if not click_label("成績作業"):
        ok = click_first_working(driver, [("xpath","//span[@class='label' and normalize-space()='成績作業']")])
        if not ok:
            _die(driver, "點不到『成績作業』", "click_fail_grade.png", "click_fail_grade.html")
    time.sleep(0.6)

    # 點擊SD0101-歷年成績查詢
    ok = click_label("SD0101-歷年成績查詢")
    if not ok:
        ok = driver.execute_script("""
            const wanted = "SD0101-歷年成績查詢".replace(/\s+/g,'');
            const els = Array.from(document.querySelectorAll('.label, a, button, span, div'));
            for (const el of els) {
              const t = (el.textContent||'').replace(/\s+/g,'');
              if (t.includes(wanted)) {
                el.scrollIntoView({block:'center'});
                try { el.click(); return true; } catch(e){}
                try { el.parentElement?.click(); return true; } catch(e){}
              }
            }
            return false;
        """)
    if not ok:
        _die(driver, "點不到『SD0101-歷年成績查詢』", "click_fail_sd0101.png", "click_fail_sd0101.html")

# ---------------- 工具函數 ----------------
def safe_int(value):
    """安全轉換為整數"""
    if not value or value in ['---', '-', '', 'nan', None]:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None

def safe_grade(value):
    """安全處理成績"""
    if not value or value in ['---', '-', '', 'nan', None]:
        return None
    value = str(value).strip()
    if value in ['---', '-', '']:
        return None
    return value

def clean_subject_name(subject):
    """清理科目名稱"""
    if not subject:
        return ""
    
    subject = str(subject).strip()
    # 移除開頭的數字前綴（如 "0 大一外文英文" -> "大一外文英文"）
    subject = re.sub(r'^[0０]\s*', '', subject)
    # 統一空格
    subject = re.sub(r'\s+', ' ', subject)
    return subject.strip()

# ---------------- 表格解析函數 ----------------
def parse_grade_table_precisely(driver):
    """
    修正版本：更精確解析成績表格，正確處理跨學期課程
    """
    driver.switch_to.default_content()
    driver.switch_to.frame("main")
    
    # 確保頁面完全載入
    time.sleep(2)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)
    
    print("🔍 開始精確解析表格...")
    
    # 保存頁面HTML供除錯
    save_html(driver, "debug_page.html")
    
    # 方法1: 嘗試直接解析HTML表格
    try:
        print("🔧 嘗試HTML表格解析...")
        courses_df, summaries_df = parse_html_table(driver)
        if not courses_df.empty:
            print("✅ HTML表格解析成功")
            return courses_df, summaries_df
    except Exception as e:
        print(f"❌ HTML表格解析失敗: {e}")
    
    # 方法2: 改進的文字解析
    try:
        print("🔧 使用改進的文字解析...")
        return parse_text_content(driver)
    except Exception as e:
        print(f"❌ 文字解析失敗: {e}")
        raise

def parse_html_table(driver):
    """
    直接解析HTML表格
    """
    print("📊 使用HTML表格解析...")
    
    courses = []
    summaries = []
    current_year = None
    
    # 尋找包含成績的表格
    tables = driver.find_elements(By.TAG_NAME, "table")
    main_table = None
    
    for table in tables:
        table_text = table.text
        if "學年" in table_text and ("必" in table_text or "選" in table_text):
            main_table = table
            break
    
    if not main_table:
        raise Exception("找不到成績表格")
    
    rows = main_table.find_elements(By.TAG_NAME, "tr")
    print(f"找到表格，共 {len(rows)} 行")
    
    for i, row in enumerate(rows):
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) == 0:
                continue
            
            # 取得每個cell的文字內容
            cell_texts = []
            for cell in cells:
                text = cell.text.strip()
                cell_texts.append(text)
            
            row_text = " ".join(cell_texts)
            
            # 識別學年標題
            year_match = re.search(r'(\d{3})\s*學年', row_text)
            if year_match:
                current_year = year_match.group(1)
                print(f"📅 處理學年: {current_year}")
                continue
            
            # 跳過表頭和空行
            if (len(cell_texts) < 3 or 
                any(header in row_text for header in ['選別', '科目', '學分', '成績', '上學期', '下學期'])):
                continue
            
            # 解析課程行
            if current_year and len(cell_texts) >= 6:  # 至少要有選別、科目、上學期學分、成績、下學期學分、成績
                course = parse_table_row(cell_texts, current_year)
                if course:
                    courses.append(course)
                    
                    # 檢查跨學期課程
                    if course['上學期_成績'] and course['下學期_成績']:
                        print(f"   ⭐ 跨學期課程: {course['科目']} (上:{course['上學期_成績']}, 下:{course['下學期_成績']})")
            
            # 解析彙總資料
            if current_year:
                parse_summary_from_row(row_text, current_year, summaries)
                
        except Exception as e:
            print(f"處理第 {i} 行失敗: {e}")
            continue
    
    print(f"✅ HTML解析完成：{len(courses)} 筆課程，{len(summaries)} 筆彙總")
    
    courses_df = pd.DataFrame(courses) if courses else pd.DataFrame()
    summaries_df = pd.DataFrame(summaries) if summaries else pd.DataFrame()
    
    if not courses_df.empty:
        courses_df = clean_courses_df(courses_df)
    if not summaries_df.empty:
        summaries_df = clean_summary_df(summaries_df)
    
    return courses_df, summaries_df

def parse_table_row(cell_texts, current_year):
    """
    解析表格行
    """
    try:
        if len(cell_texts) < 3:
            return None
        
        # 基本結構假設：選別 | 科目 | 上學期學分 | 上學期成績 | 下學期學分 | 下學期成績
        category = cell_texts[0].strip()
        subject = cell_texts[1].strip()
        
        # 驗證選別
        if category not in ['必', '選', '通']:
            return None
        
        # 清理科目名稱
        subject = clean_subject_name(subject)
        if not subject:
            return None
        
        # 解析學分和成績（根據實際表格結構調整）
        up_credit = safe_int(cell_texts[2]) if len(cell_texts) > 2 else None
        up_grade = safe_grade(cell_texts[3]) if len(cell_texts) > 3 else None
        down_credit = safe_int(cell_texts[4]) if len(cell_texts) > 4 else None
        down_grade = safe_grade(cell_texts[5]) if len(cell_texts) > 5 else None
        
        # 創建課程記錄
        course = {
            '學年': current_year,
            '選別': category,
            '科目': subject,
            '上學期_學分': up_credit,
            '上學期_成績': up_grade,
            '下學期_學分': down_credit,
            '下學期_成績': down_grade
        }
        
        # 檢查是否有有效資料
        if any([up_credit, up_grade, down_credit, down_grade]):
            return course
        
        return None
        
    except Exception as e:
        print(f"解析表格行失敗: {e}")
        return None

def parse_text_content(driver):
    """
    改進的文字內容解析
    """
    print("📝 使用文字內容解析...")
    
    # 取得頁面所有文字內容
    body_text = driver.find_element(By.TAG_NAME, "body").text
    lines = [line.strip() for line in body_text.split('\n') if line.strip()]
    
    # 保存除錯資訊
    with open("debug_text_lines.txt", "w", encoding="utf-8") as f:
        for i, line in enumerate(lines):
            f.write(f"{i:3d}: {line}\n")
    
    courses = []
    summaries = []
    current_year = None
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # 識別學年標題
        year_match = re.match(r'^(\d{3})\s*學年', line)
        if year_match:
            current_year = year_match.group(1)
            print(f"📅 處理學年: {current_year}")
            i += 1
            continue
        
        # 跳過表頭和無關行
        skip_keywords = [
            '選別', '科目', '學分', '成績', '上學期', '下學期', 
            'SD0101', '個人歷年成績', '資管AI', '林廷叡',
            '學業成績總平均', '修習學分數', '實得學分數', '操行成績'
        ]
        
        if any(keyword in line for keyword in skip_keywords):
            # 但是要檢查是否包含彙總資訊
            if current_year:
                parse_summary_from_row(line, current_year, summaries)
            i += 1
            continue
        
        # 解析課程行
        if current_year and line.startswith(('必 ', '選 ', '通 ')):
            course = parse_course_line_improved(line, current_year)
            if course:
                courses.append(course)
                
                # 檢查跨學期課程
                if course['上學期_成績'] and course['下學期_成績']:
                    print(f"   ⭐ 跨學期課程: {course['科目']} (上:{course['上學期_成績']}, 下:{course['下學期_成績']})")
        
        i += 1
    
    print(f"✅ 文字解析完成：{len(courses)} 筆課程，{len(summaries)} 筆彙總")
    
    courses_df = pd.DataFrame(courses) if courses else pd.DataFrame()
    summaries_df = pd.DataFrame(summaries) if summaries else pd.DataFrame()
    
    if not courses_df.empty:
        courses_df = clean_courses_df(courses_df)
    if not summaries_df.empty:
        summaries_df = clean_summary_df(summaries_df)
    
    return courses_df, summaries_df

def parse_course_line_improved(line, current_year):
    """
    改進的課程行解析，支持多種格式
    """
    try:
        # 分割行內容
        parts = line.split()
        if len(parts) < 3:
            return None
        
        category = parts[0]  # 必/選/通
        
        # 更智能的分割：分離科目名稱和數據
        subject_parts = []
        data_parts = []
        found_first_data = False
        
        for part in parts[1:]:
            # 檢查是否是數據部分的開始
            is_data = (
                re.match(r'^\d+$', part) or  # 純數字（學分）
                part in ['---', '-', '停修', '不及格'] or  # 特殊標記
                re.match(r'^\d+\.\d+$', part) or  # 小數
                (part.isdigit() and 0 <= int(part) <= 100)  # 0-100的數字（成績）
            )
            
            if is_data and not found_first_data:
                found_first_data = True
            
            if not found_first_data:
                subject_parts.append(part)
            else:
                data_parts.append(part)
        
        if not subject_parts:
            return None
        
        # 組合科目名稱並清理
        subject = ' '.join(subject_parts)
        subject = clean_subject_name(subject)
        
        if not subject:
            return None
        
        # 解析數據部分 - 支持多種格式
        up_credit, up_grade, down_credit, down_grade = None, None, None, None
        
        # 根據數據數量判斷格式
        if len(data_parts) == 1:
            # 只有一個數據，可能是學分或成績
            if data_parts[0].isdigit():
                up_credit = safe_int(data_parts[0])
            else:
                up_grade = safe_grade(data_parts[0])
                
        elif len(data_parts) == 2:
            # 兩個數據：學分 成績 或 上學期成績 下學期成績
            if data_parts[0].isdigit():
                up_credit = safe_int(data_parts[0])
                up_grade = safe_grade(data_parts[1])
            else:
                up_grade = safe_grade(data_parts[0])
                down_grade = safe_grade(data_parts[1])
                
        elif len(data_parts) == 3:
            # 三個數據：可能是 學分 上學期成績 下學期成績
            if data_parts[0].isdigit():
                up_credit = safe_int(data_parts[0])
                down_credit = up_credit  # 假設兩學期學分相同
                up_grade = safe_grade(data_parts[1])
                down_grade = safe_grade(data_parts[2])
            else:
                # 或其他組合
                up_grade = safe_grade(data_parts[0])
                down_grade = safe_grade(data_parts[1])
                
        elif len(data_parts) >= 4:
            # 四個或更多數據：上學期學分 上學期成績 下學期學分 下學期成績
            up_credit = safe_int(data_parts[0])
            up_grade = safe_grade(data_parts[1])
            down_credit = safe_int(data_parts[2])
            down_grade = safe_grade(data_parts[3])
        
        # 創建課程記錄
        course = {
            '學年': current_year,
            '選別': category,
            '科目': subject,
            '上學期_學分': up_credit,
            '上學期_成績': up_grade,
            '下學期_學分': down_credit,
            '下學期_成績': down_grade
        }
        
        # 檢查是否有有效資料
        if any([up_credit, up_grade, down_credit, down_grade]):
            return course
        
        return None
        
    except Exception as e:
        print(f"解析課程行失敗: {e}, line: {line}")
        return None

def parse_summary_from_row(text, current_year, summaries):
    """從文字中解析彙總資料"""
    try:
        current_summary = {'學年': current_year}
        
        if '學業成績總平均：' in text or '學業成績總平均' in text:
            scores = re.findall(r'(\d+\.?\d*)', text)
            if len(scores) >= 2:
                current_summary['上學期_平均'] = float(scores[0])
                current_summary['下學期_平均'] = float(scores[1])
        
        elif '修習學分數：' in text or '修習學分數' in text:
            credits = re.findall(r'(\d+)', text)
            if len(credits) >= 2:
                current_summary['上學期_修習學分'] = int(credits[0])
                current_summary['下學期_修習學分'] = int(credits[1])
        
        elif '實得學分數：' in text or '實得學分數' in text:
            credits = re.findall(r'(\d+)', text)
            if len(credits) >= 2:
                current_summary['上學期_實得學分'] = int(credits[0])
                current_summary['下學期_實得學分'] = int(credits[1])
        
        elif '操行成績：' in text or '操行成績' in text:
            grades = re.findall(r'([甲乙丙丁戊])', text)
            if len(grades) >= 2:
                current_summary['上學期_操行'] = grades[0]
                current_summary['下學期_操行'] = grades[1]
                
                # 操行成績通常是最後一項，保存彙總資料
                for semester in ['上學期', '下學期']:
                    summary_record = {
                        '學年': current_year,
                        '學期': semester,
                        '學業成績總平均': current_summary.get(f'{semester}_平均'),
                        '修習學分數': current_summary.get(f'{semester}_修習學分'),
                        '實得學分數': current_summary.get(f'{semester}_實得學分'),
                        '操行成績': current_summary.get(f'{semester}_操行')
                    }
                    summaries.append(summary_record)
    except Exception as e:
        print(f"解析彙總資料失敗: {e}")

# ---------------- 資料清理函數 ----------------
def clean_courses_df(df: pd.DataFrame) -> pd.DataFrame:
    """清理課程資料"""
    if df.empty:
        return df
    
    print(f"🧹 清理前：{len(df)} 筆課程")
    
    # 保存原始順序
    df = df.reset_index(drop=True)
    df['_original_order'] = df.index
    
    # 移除重複項（但保持第一次出現的順序）
    df = df.drop_duplicates(subset=['學年', '選別', '科目'], keep='first').reset_index(drop=True)
    
    # 清理科目名稱
    df['科目'] = df['科目'].astype(str).str.strip()
    df['科目'] = df['科目'].str.replace(r'\s+', ' ', regex=True)  # 統一空格
    
    # 過濾無效記錄
    df = df[df['科目'].notna() & (df['科目'] != '') & (df['科目'] != 'nan')].copy()
    df = df[df['選別'].isin(['必', '選', '通'])].copy()
    
    # 確保至少有一個學期有資料
    has_data = (
        df['上學期_學分'].notna() | df['上學期_成績'].notna() |
        df['下學期_學分'].notna() | df['下學期_成績'].notna()
    )
    df = df[has_data].copy()
    
    # 轉換成績為字串（保留"停修"等特殊值）
    for col in ['上學期_成績', '下學期_成績']:
        df[col] = df[col].astype(str).replace('nan', None)
        df.loc[df[col] == 'None', col] = None
    
    # 按照原始出現順序排序，而不是按字母順序
    df = df.sort_values(['學年', '_original_order']).reset_index(drop=True)
    
    # 移除輔助欄位
    df = df.drop(columns=['_original_order'])
    
    print(f"🧹 清理後：{len(df)} 筆課程")
    return df

def clean_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    """清理彙總資料"""
    if df.empty:
        return df
    
    # 移除重複項
    df = df.drop_duplicates(subset=['學年', '學期']).reset_index(drop=True)
    
    # 排序
    semester_order = {'上學期': 1, '下學期': 2}
    df['_sort'] = df['學期'].map(semester_order)
    df = df.sort_values(['學年', '_sort']).reset_index(drop=True)
    df = df.drop(columns=['_sort'])
    
    return df

# ---------------- 主程式 ----------------
def main():
    driver = build_driver()
    try:
        print("🚀 開始執行成績爬蟲（完整修正版）...")
        
        goto_student_system_from_home(driver)
        print("✅ 已進入學生教務系統")
        
        login_if_needed(driver)
        print("✅ 登入完成")
        
        open_grade_history(driver)
        print("✅ 已開啟成績查詢頁面")
        
        courses_df, summary_df = parse_grade_table_precisely(driver)
        
        # 輸出檔案
        if not courses_df.empty:
            courses_df.to_csv("grades_courses_fixed.csv", index=False, encoding="utf-8-sig")
            courses_df.to_json("grades_courses_fixed.json", orient="records", force_ascii=False, indent=2)
            print(f"✅ 已輸出課程資料：{len(courses_df)} 筆")
            
            # 顯示詳細統計
            year_counts = courses_df['學年'].value_counts().sort_index()
            category_counts = courses_df['選別'].value_counts()
            print(f"   學年分佈：{dict(year_counts)}")
            print(f"   選別分佈：{dict(category_counts)}")
            
            # 檢查跨學期課程
            cross_semester = courses_df[
                courses_df['上學期_成績'].notna() & courses_df['下學期_成績'].notna()
            ]
            print(f"   跨學期課程：{len(cross_semester)} 筆")
            if len(cross_semester) > 0:
                print("   跨學期課程列表：")
                for _, course in cross_semester.iterrows():
                    print(f"     - {course['學年']}學年 {course['科目']} (上:{course['上學期_成績']}, 下:{course['下學期_成績']})")
            
            # 顯示所有有成績的課程統計
            has_up_grade = courses_df['上學期_成績'].notna().sum()
            has_down_grade = courses_df['下學期_成績'].notna().sum()
            print(f"   上學期有成績：{has_up_grade} 筆")
            print(f"   下學期有成績：{has_down_grade} 筆")
            
        else:
            print("⚠️ 沒有找到課程資料")
        
        if not summary_df.empty:
            summary_df.to_csv("grades_summary_fixed.csv", index=False, encoding="utf-8-sig")
            summary_df.to_json("grades_summary_fixed.json", orient="records", force_ascii=False, indent=2)
            print(f"✅ 已輸出彙總資料：{len(summary_df)} 筆")
        else:
            print("⚠️ 沒有找到彙總資料")
        
        # 顯示前幾筆資料預覽
        if not courses_df.empty:
            print("\n📊 課程資料預覽：")
            # 只顯示有成績的欄位，避免顯示過多None
            display_columns = ['學年', '選別', '科目']
            if courses_df['上學期_學分'].notna().any():
                display_columns.append('上學期_學分')
            if courses_df['上學期_成績'].notna().any():
                display_columns.append('上學期_成績')
            if courses_df['下學期_學分'].notna().any():
                display_columns.append('下學期_學分')
            if courses_df['下學期_成績'].notna().any():
                display_columns.append('下學期_成績')
            
            preview_df = courses_df[display_columns].head(15)
            print(preview_df.to_string(index=False, max_colwidth=20))
        
        if not summary_df.empty:
            print("\n📊 彙總資料：")
            print(summary_df.to_string(index=False))
        

        print("✅ 爬蟲執行完成！")
        
    except Exception as e:
        print(f"❌ 執行失敗: {e}")
        driver.save_screenshot("error_final.png")
        save_html(driver, "error_final.html")
        
        # 輸出除錯資訊
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame("main")
            page_text = driver.find_element(By.TAG_NAME, "body").text
            with open("page_text_debug.txt", "w", encoding="utf-8") as f:
                f.write(page_text)
            print("已儲存除錯資訊到 page_text_debug.txt")
        except:
            pass
        
        raise
    finally:
        time.sleep(2 if not HEADLESS else 0)
        driver.quit()

if __name__ == "__main__":
    main()