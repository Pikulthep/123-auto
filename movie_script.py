import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json
import time
import os
from datetime import datetime
import concurrent.futures

# ================== CONFIG ==================
MAIN_URL = "https://www.123-hds.com/%e0%b8%ab%e0%b8%99%e0%b8%b1%e0%b8%87%e0%b9%83%e0%b8%ab%e0%b8%a1%e0%b9%88-2026"
SAVE_DIR = "output"
OUTPUT_FILE = os.path.join(SAVE_DIR, "movies.txt")

MAX_PAGE = 1
# ลดเหลือ 2 เพื่อไม่ให้เซิร์ฟเวอร์เว็บหนังบล็อก IP เพราะ Request รัวเกินไป
MAX_WORKERS = 2 

# ================== ฟังก์ชันช่วยเหลือ ==================
def extract_m3u8(logs):
    """ฟังก์ชันสกัดลิงก์ m3u8 จาก Network Log"""
    for entry in logs:
        try:
            log_data = json.loads(entry["message"])["message"]
            if log_data["method"] in ["Network.requestWillBeSent", "Network.responseReceived"]:
                req_url = log_data["params"].get("request", {}).get("url") or log_data["params"].get("response", {}).get("url", "")
                if ".m3u8" in req_url:
                    return req_url
        except:
            continue
    return None

def get_movie_links():
    """กวาดลิงก์หน้ารวมด้วย Requests"""
    all_links = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for page in range(1, MAX_PAGE + 1):
        page_url = MAIN_URL if page == 1 else f"{MAIN_URL}/page/{page}"
        print(f"กำลังสแกนลิงก์จากหน้า {page}/{MAX_PAGE}...")
        try:
            res = requests.get(page_url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            halim_box = soup.find("div", class_="halim_box")
            if halim_box:
                for article in halim_box.find_all("article"):
                    a_tag = article.find("a")
                    if a_tag and "href" in a_tag.attrs:
                        all_links.append(a_tag["href"])
        except Exception as e:
            print(f"  -> Error อ่านหน้า {page}: {e}")
            
    return list(set(all_links))

# ================== ฟังก์ชันหลักสำหรับดึงข้อมูล (1 เรื่อง) ==================
def process_movie(movie_url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--mute-audio")
    
    # 🌟 เพิ่มเกราะป้องกัน Bot (ปิดการแจ้งเตือนว่าเป็น Automation)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    # ⚠️ เอาส่วนที่บล็อกรูปภาพและ CSS ออก เพื่อให้ Player ทำงานได้สมบูรณ์

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    # จำลองเป็นคนจริงๆ มากขึ้น
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(60)

    movie_data = None
    try:
        driver.get(movie_url)
        # รอให้เว็บโหลดโครงสร้างเบื้องต้น
        time.sleep(3) 
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # --- 1. ดึงชื่อ รูป และ Tags ---
        title = "ไม่ทราบชื่อเรื่อง"
        image = "https://via.placeholder.com/150"
        
        img_tag = soup.find("img", class_="movie-thumb")
        if img_tag:
            title = img_tag.get("alt", title)
            raw_img = img_tag.get("src", image)
            image = f"https://www.123-hds.com{raw_img}" if raw_img.startswith("/") else raw_img
            
        tags = []
        quality_tag = soup.select_one(".status, .quality, .halim-status, .resolution")
        if quality_tag: tags.append(quality_tag.get_text(strip=True))
        audio_tag = soup.select_one(".episode, .sound, .halim-episode, .audio")
        if audio_tag: tags.append(audio_tag.get_text(strip=True))
        
        if not audio_tag or not quality_tag:
            info_box = soup.find("div", class_="movie_info") or soup
            info_text = info_box.get_text()
            if not audio_tag:
                if "พากย์ไทย" in info_text: tags.append("พากย์ไทย")
                elif "ซับไทย" in info_text: tags.append("ซับไทย")
            if not quality_tag:
                if any(kw in info_text for kw in ["ชนโรง", "ซูม", "CAM"]): tags.append("หนังซูม")
                elif any(kw in info_text for kw in ["HD", "Master"]): tags.append("HD")
                
        if tags:
            tags = list(dict.fromkeys([t.upper() for t in tags if t]))
            tag_str = " | ".join(tags)
            if tag_str not in title: title = f"[{tag_str}] {title}"

        # --- 2. หาลิงก์ m3u8 ---
        m3u8_url = None
        
        for _ in range(12): 
            time.sleep(1)
            m3u8_url = extract_m3u8(driver.get_log("performance"))
            if m3u8_url: break

        # ท่าเจาะเกราะ Player
        if not m3u8_url:
            iframe = soup.select_one("#ajax-player iframe, .halim-player-wrapper iframe")
            if not iframe:
                try:
                    driver.execute_script("let btn = document.querySelector('.halim-list-server li a'); if(btn) btn.click();")
                    time.sleep(3)
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    iframe = soup.select_one("#ajax-player iframe, .halim-player-wrapper iframe")
                except: pass
            
            if iframe and iframe.has_attr("src"):
                iframe_url = iframe["src"]
                iframe_url = "https:" + iframe_url if iframe_url.startswith("//") else iframe_url
                driver.get(iframe_url)
                
                try:
                    # เพิ่มเวลาให้ Player โหลดสคริปต์วิดีโอเสร็จ
                    time.sleep(4)
                    driver.execute_script("let v = document.querySelector('video'); if(v) v.play(); else document.body.click();")
                except: pass
                
                for _ in range(10): 
                    time.sleep(1)
                    m3u8_url = extract_m3u8(driver.get_log("performance"))
                    if m3u8_url: break

        if m3u8_url:
            print(f"✅ สำเร็จ: {title}")
            movie_data = {"name": title, "image": image, "url": m3u8_url}
        else:
            print(f"❌ ไม่พบลิงก์: {title}")
            
    except Exception as e:
        print(f"⚠️ Error เกิดข้อผิดพลาด: {e}")
    finally:
        driver.quit()
        
    return movie_data

# ================== Main Program ==================
if __name__ == "__main__":
    start_time = time.time()
    print("🚀 เริ่มต้นกระบวนการดึงข้อมูล (Optimized & Stealth Version)")
    
    links = get_movie_links()
    # 🌟 เทสระบบ: ถ้าอยากเทสว่าใช้งานได้ไหม แนะนำให้รันแค่ 5 เรื่องก่อน จะได้รู้ผลไวๆ
    # links = links[:5] 
    
    print(f"\n🎯 พบลิงก์ทั้งหมด: {len(links)} เรื่อง (กำลังเริ่มดึงข้อมูลขนานกัน {MAX_WORKERS} หน้าต่าง...)\n")
    
    movies_data = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = executor.map(process_movie, links)
        for res in results:
            if res:
                movies_data.append(res)
                
    # ================== สร้างไฟล์ JSON ==================
    print(f"\n💾 รวบรวมสำเร็จ {len(movies_data)} เรื่อง, กำลังสร้างไฟล์ {OUTPUT_FILE}")
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    current_date = datetime.now().strftime("%d/%m/%Y")
    final_data = {
        "name": f"หนังใหม่ 2026 @ {current_date}",
        "author": "Auto Update (Pro)",
        "image": "https://www.123-hds.com/wp-content/uploads/2023/10/logo.png",
        "groups": [{
            "name": f"หนังใหม่ 2026 (รวม {MAX_PAGE} หน้า)",
            "image": "https://www.123-hds.com/wp-content/uploads/2023/10/logo.png",
            "stations": movies_data
        }]
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    elapsed = time.time() - start_time
    print(f"🎉 จบการทำงานทั้งหมดภายในเวลา {elapsed / 60:.2f} นาที!")
