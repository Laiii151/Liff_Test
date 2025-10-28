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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from webdriver_manager.chrome import ChromeDriverManager


HOME_URL = "https://www.shu.edu.tw/System-info.aspx"
HEADLESS = False
MAX_WAIT = 25

# --- 瀏覽器初始化 ---
# 建議將瀏覽器設定放在主流程中，而不是全域範圍
def build_driver():
    """建立 Chrome WebDriver"""
    opt = webdriver.ChromeOptions()
    if HEADLESS:
        opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--window-size=1440,900")
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    opt.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def js_click(driver, el):
    """JavaScript 點擊元素"""
    driver.execute_script("""
        const el = arguments[0];
        el.scrollIntoView({block:'center'});
        try{ el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true})); }catch(e){}
        try{ el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true})); }catch(e){}
        try{ el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true})); }catch(e){}
        try{ el.click(); }catch(e){}
    """, el)

def find_and_js_click(driver, selector: str, by="css") -> bool:
    """尋找元素並點擊"""
    try:
        if by == "css":
            el = driver.find_element(By.CSS_SELECTOR, selector)
        else:
            el = driver.find_element(By.XPATH, selector)
        js_click(driver, el)
        return True
    except Exception as e:
        print(f"點擊失敗 ({by}: {selector}): {e}")
        return False

def click_first_working(driver, selectors: List[Tuple[str, str]]) -> bool:
    """嘗試多個選擇器，點擊第一個成功的"""
    for by, sel in selectors:
        if find_and_js_click(driver, sel, by=by):
            print(f"✅ 成功點擊: {by}={sel}")
            return True
    return False

def save_html(driver, path):
    """保存頁面HTML"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)

def _die(driver, msg, png, html):
    """錯誤處理：截圖並保存HTML"""
    driver.save_screenshot(png)
    save_html(driver, html)
    print(f"❌ {msg}")
    print(f"📸 截圖已保存：{png}")
    print(f"📄 HTML已保存：{html}")
    raise RuntimeError(f"{msg}；已存 {png} / {html}")

# --- 登入函式 ---
def goto_student_system_from_home(driver):
    driver.get(HOME_URL)
    # 點擊學生教務系統
    print("🔍 尋找學生教務系統連結...")
    ok = click_first_working(driver, [
        ("css", "body > div:nth-child(10) > div > div.sm-page-all-area > div:nth-child(2) > div.ct-sub-sbox.ct-sub-nsbox.ct-sub-nsortbox > a:nth-child(9)"),
        ("css", "body > div:nth-child(11) > div > div.sm-page-all-area > div:nth-child(2) > div.ct-sub-sbox.ct-sub-nsbox.ct-sub-nsortbox > a:nth-child(9)"),
        ("xpath", "//a[contains(@href,'stulb.shu.edu.tw')]"),
        ("xpath", "//a[normalize-space()='學生教務系統' or contains(normalize-space(.),'學生教務系統')]"),
    ])
    
    if not ok:
        print("⚠️ 找不到學生教務系統連結，直接開啟網址...")
        driver.execute_script("window.open('https://stulb.shu.edu.tw/','_blank');")
    
    # 切換到新分頁
    driver.switch_to.window(driver.window_handles[-1])
    time.sleep(2)

def login_if_needed(driver, student_id, password):
    """如需要則進行登入，改成接收動態帳號密碼"""
    print("🔐 檢查是否需要登入...")

    try:
        # 等待登入表單出現
        username_field = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'],input[autocomplete='username']"))
        )
        password_field = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'],input[autocomplete='current-password']"))
        )

        print("📝 輸入帳號密碼...")
        username_field.clear()
        username_field.send_keys(student_id)  # 用參數 student_id
        password_field.clear()
        password_field.send_keys(password)    # 用參數 password

        # 提交登入表單
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'],button[type='submit']")
            js_click(driver, submit_btn)
        except NoSuchElementException:
            password_field.submit()

        print("⏳ 等待登入完成...")
        time.sleep(0.8)

        # 可加額外判斷是否登入成功
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame("main")
            print("✅ 已切換到 main frame，登入成功")
        except Exception:
            print("ℹ️ 沒有找到 main frame，繼續使用預設內容")

        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # 檢查錯誤訊息
        end = time.time() + 8
        while time.time() < end:
            try:
                msg = driver.find_element(By.ID, 'lblMessage').text
            except Exception:
                msg = ''

            low = (msg or '').lower()
            if any(k in low for k in [
                '登入帳號或密碼錯誤', '輸入帳號或密碼錯誤', '帳號或密碼錯誤',
                'login failed', 'invalid password', 'authentication failed']):
                try:
                    driver.save_screenshot('login_error.png')
                    save_html(driver, 'login_error.html')
                except Exception:
                    pass
                print('❌ 登入失敗：', msg)
                driver.quit()
                return False

            try:
                body_text = driver.find_element(By.TAG_NAME, 'body').text
            except Exception:
                body_text = ''

            lowb = (body_text or '').lower()
            if any(k in lowb for k in [
                '登入帳號或密碼錯誤', '輸入帳號或密碼錯誤', '帳號或密碼錯誤',
                'login failed', 'invalid password', 'authentication failed']):
                try:
                    driver.save_screenshot('login_error.png')
                    save_html(driver, 'login_error.html')
                except Exception:
                    pass
                print('❌ 登入失敗（body）')
                driver.quit()
                return False

            time.sleep(0.5)

        return True

    except TimeoutException:
        print("ℹ️ 沒有找到登入表單，可能已經登入或頁面結構不同")
        return True

# --- 主執行流程 ---
def main(student_id: str, password: str) -> bool:
    driver = build_driver()
    goto_student_system_from_home(driver)
    success = login_if_needed(driver, student_id, password)
    return success
    

# --- 程式執行入口 ---
# ❗️【最重要的更正】將這段程式碼取消註解，程式才會真正執行
if __name__ == '__main__':
    main()