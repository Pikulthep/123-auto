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
# 🌟 ตั้งค่าหมวดหมู่ที่ต้องการดึง (สามารถเพิ่ม/ลด และแก้ลิงก์ได้ตามต้องการ)
CATEGORIES = [
    {
        "name": "หนังใหม่ 2026", 
        "url": "https://www.123-hds.com/%e0%b8%ab%e0%b8%99%e0%b8%b1%e0%b8%87%e0%b9%83%e0%b8%ab%e0%b8%a1%e0%b9%88-2026", 
        "max_page": 1 # ดึง 3 หน้าแรก
    },
    {
        "name": "หนัง Netflix", 
        "url": "https://www.123-hds.com/%e0%b8%94%e0%b8%b9%e0%b8%ab%e0%b8%99%e0%b8%b1%e0%b8%87-netflix", 
        "max_page": 1 # ดึง 2 หน้าแรก
    },
    {
        "name": "หนังไทย", 
        "url": "https://www.123-hds.com/%e0%b8%94%e0%b8%b9%e0%b8%ab%e0%b8%99%e0%b8%b1%e0%b8%87%e0%b8%ad%e0%b8%ad%e0%b8%99%e0%b9%84%e0%b8%a5%e0%b8%99%e0%b9%8c/%e0%b8%ab%e0%b8%99%e0%b8%b1%e0%b8%87%e0%b9%84%e0%b8%97%e0%b8%a2", 
        "max_page": 1 # ดึง 1 หน้าแรก
    }
]

SAVE_DIR = "output"
OUTPUT_FILE = os.path.join(SAVE_DIR, "movies.txt")
MAX_WORKERS = 3 # จำนวนหน้าต่างที่จะเปิดพร้อมกัน

# ================== ฟังก์ชันช่วยเหลือ ==================
def extract_m3u8(logs):
    for entry in logs:
        try:
            log_data = json.loads(entry["message"])["message"]
            if log_data["method"] in ["Network.requestWillBeSent", "Network.responseReceived"]:
                req_url = log_data["params"].get("request", {}).get("url") or log_data["params"].get("response", {}).get("url", "")
                if ".m3u8" in req_url: return req_url
        except: continue
    return None

def get_movie_links(category_url, max_page):
    """กวาดลิงก์หน้ารวม (รองรับทีละหมวดหมู่)"""
    all_links = []
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    
    try:
        for page in range(1, max_page + 1):
            page_url = category_url if page == 1 else f"{category_url}/page/{page}"
            print(f"  -> สแกนหน้า {page}/{max_page}: {page_url}")
            try:
                driver.get(page_url)
                time.sleep(3) 
                soup = BeautifulSoup(driver.page_source, "html.parser")
                halim_box = soup.find("div", class_="halim_box")
                if halim_box:
                    for article in halim_box.find_all("article"):
                        a_tag = article.find("a")
                        if a_tag and "href" in a_tag.attrs:
                            all_links.append(a_tag["href"])
            except Exception as e:
                print(f"     [Error] อ่านหน้า {page} ไม่สำเร็จ: {e}")
    finally:
        driver.quit()
            
    return list(set(all_links))

# ================== ฟังก์ชันหลักสำหรับดึงข้อมูล (1 เรื่อง) ==================
def process_movie(movie_url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(60)

    movie_data = None
    try:
        driver.get(movie_url)
        time.sleep(3) 
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # --- ดึงชื่อ รูป และ Info ---
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
                
        tag_str = ""
        if tags:
            tags = list(dict.fromkeys([t.upper() for t in tags if t]))
            tag_str = " | ".join(tags)

        # --- หาลิงก์ m3u8 ---
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
                    time.sleep(4)
                    driver.execute_script("let v = document.querySelector('video'); if(v) v.play(); else document.body.click();")
                except: pass
                
                for _ in range(10): 
                    time.sleep(1)
                    m3u8_url = extract_m3u8(driver.get_log("performance"))
                    if m3u8_url: break

        if m3u8_url:
            print(f"    ✅ สำเร็จ: {title}")
            movie_data = {
                "name": title,
                "image": image,
                "url": m3u8_url,
                "info": tag_str if tag_str else "ไม่ระบุ"
            }
        else:
            print(f"    ❌ ไม่พบลิงก์: {title}")
            
    except Exception as e:
        print(f"    ⚠️ Error เกิดข้อผิดพลาด: {e}")
    finally:
        driver.quit()
        
    return movie_data

# ================== Main Program ==================
if __name__ == "__main__":
    start_time = time.time()
    print("🚀 เริ่มต้นกระบวนการดึงข้อมูลแบบ Multi-Category\n")
    
    all_groups_data = [] # ตะกร้าใบใหญ่สำหรับเก็บหนังทุกหมวดหมู่
    
    for category in CATEGORIES:
        cat_name = category["name"]
        cat_url = category["url"]
        cat_max_page = category["max_page"]
        
        print(f"==================================================")
        print(f"🎬 กำลังเริ่มหมวดหมู่: {cat_name} (จำนวน {cat_max_page} หน้า)")
        print(f"==================================================")
        
        # 1. กวาดลิงก์ของหมวดหมู่นั้นๆ
        links = get_movie_links(cat_url, cat_max_page)
        
        print(f"🎯 พบลิงก์ในหมวด '{cat_name}' ทั้งหมด: {len(links)} เรื่อง")
        print(f"⏳ เริ่มเจาะดึงข้อมูลวิดีโอ (รันขนาน {MAX_WORKERS} หน้าต่าง)...\n")
        
        movies_data = []
        
        # 2. ดึงข้อมูลหนัง
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = executor.map(process_movie, links)
            for res in results:
                if res: movies_data.append(res)
                    
        # 3. จัดกลุ่มหนังใส่โฟลเดอร์ของหมวดหมู่นั้นๆ
        if movies_data:
            all_groups_data.append({
                "name": f"📂 {cat_name}",
                "image": "https://www.123-hds.com/wp-content/uploads/2023/10/logo.png",
                "stations": movies_data
            })
        print("\n")
                
    # 🌟 แก้ไขการเยื้องบรรทัด (Indentation) ตรงนี้ให้ถูกต้องแล้ว
    print(f"💾 รวบรวมสำเร็จทั้งหมด {len(all_groups_data)} หมวดหมู่, กำลังสร้างไฟล์ {OUTPUT_FILE}")
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    current_date = datetime.now().strftime("%d/%m/%Y")
    
    final_data = {
        "name": "หนัง 123-HDS", 
        "author": f"Auto Update ({current_date})", 
        "info": "รวมหนังและซีรีส์อัปเดตอัตโนมัติ",
        "image": "https://www.123-hds.com/wp-content/uploads/2023/10/logo.png",
        "groups": all_groups_data 
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    elapsed = time.time() - start_time
    print(f"🎉 จบการทำงานทั้งหมดภายในเวลา {elapsed / 60:.2f} นาที!")
