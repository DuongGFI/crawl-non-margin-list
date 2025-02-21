from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from playwright.async_api import async_playwright
import logging
import sys
import asyncio
import uvicorn

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI()
logging.basicConfig(level=logging.INFO)


# --- HSX: Các hàm crawl dữ liệu (không thay đổi) ---
def remove_nested_spans(html_content: str) -> str:
    """Loại bỏ các thẻ span lồng nhau và chỉ giữ lại text."""
    soup = BeautifulSoup(html_content, 'html.parser')
    for span in soup.find_all('span'):
        span.replace_with(span.get_text())
    return soup.get_text()

def get_hsx_list(page: int) -> pd.DataFrame:
    """Lấy dữ liệu từ HSX cho một trang cụ thể."""
    timestamp = int(time.time())
    url = f"https://www.hsx.vn/Modules/Listed/Web/NonMarginList?_search=false&nd={timestamp}&rows=30&page={page}&sidx=id&sord=desc"
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Cookie': 'ASP.NET_SessionId=cf5g3zcoqpcfjmxveflvfxye; ...',
        'Host': 'www.hsx.vn',
        'Referer': 'https://www.hsx.vn/Modules/Listed/Web/NonMarginTradeView?fid=48cf424f8f1e47c6b00de6080e9350d2',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N)...',
        'X-Requested-With': 'XMLHttpRequest'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logging.error(f"Lỗi khi request HSX: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi request HSX: {e}")

    rows = data.get('rows', [])
    if not rows:
        return pd.DataFrame()

    all_cells = [d.get('cell', []) for d in rows]
    try:
        df = pd.DataFrame(all_cells, columns=['id', 'ticker', 'code1', 'code2', 'name', 'date', 'reason'])
    except Exception as e:
        logging.error(f"Lỗi khi tạo DataFrame từ HSX: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi tạo DataFrame từ HSX: {e}")

    df['reason'] = df['reason'].apply(remove_nested_spans)
    df['exchange'] = 'HOSE'
    df['ticker'] = df['ticker'].str.strip()
    df = df.drop(columns=['id', 'code1', 'code2'])
    return df

def get_hsx_list_all(max_pages: int = 100) -> pd.DataFrame:
    """Lấy toàn bộ dữ liệu HSX qua nhiều trang."""
    page = 1
    data_frames = []
    while page <= max_pages:
        df = get_hsx_list(page)
        if df.empty:
            break
        data_frames.append(df)
        page += 1
    return pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()

# --- HNX: Sử dụng async Playwright để crawl dữ liệu ---
def crawl_current_page_from_html(html: str) -> pd.DataFrame:
    """Crawl dữ liệu từ trang hiện tại của HNX từ nội dung HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='_tableDatas')
    
    data = []
    if table:
        tbody = table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
            for row in rows:
                columns = row.find_all('td')
                if len(columns) >= 5:
                    ticker = columns[1].get_text(strip=True)
                    name = columns[2].get_text(strip=True)
                    date_str = columns[3].get_text(strip=True)
                    reason = columns[4].get_text(strip=True).replace('- ', '').replace('-', '')
                    data.append({
                        'ticker': ticker,
                        'name': name,
                        'date': date_str,
                        'reason': reason,
                        'exchange': 'HNX'
                    })
    return pd.DataFrame(data)

async def crawl_hnx_data(max_iterations: int = 50) -> pd.DataFrame:
    """Crawl dữ liệu HNX với async Playwright."""
    all_data = pd.DataFrame()
    seen = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process',
                '--disable-infobars'
            ]
        )
        page = await browser.new_page()
        await page.goto("https://hnx.vn/vi-vn/co-phieu-etfs/chung-khoan-ny-khong-ky-quy.html")
        
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                await page.wait_for_selector("table#_tableDatas", timeout=10000)
            except Exception:
                logging.info("Không tìm thấy bảng dữ liệu, kết thúc crawl.")
                break
            html = await page.content()
            df_new = crawl_current_page_from_html(html)
            if df_new.empty:
                logging.info("Không có dữ liệu mới trên trang, kết thúc crawl.")
                break
            new_rows = df_new[~df_new['ticker'].isin(seen)]
            if new_rows.empty:
                logging.info("Đã crawl hết dữ liệu trùng lặp, kết thúc crawl.")
                break
            seen.update(new_rows['ticker'].tolist())
            all_data = pd.concat([all_data, new_rows], ignore_index=True)
            try:
                next_button = await page.query_selector("#next")
                if not next_button:
                    logging.info("Không tìm thấy nút next, kết thúc crawl.")
                    break
                await next_button.click()
                await page.wait_for_selector("table#_tableDatas", timeout=10000)
                await page.wait_for_timeout(500)  # đợi 0.5 giây
            except Exception:
                logging.info("Lỗi khi click nút next hoặc chờ dữ liệu, kết thúc crawl.")
                break
        
        await browser.close()
    return all_data

@app.get("/crawl")
async def main_handler():
    try:
        # Crawl HSX (blocking, có thể chạy thêm vào thread nếu cần)
        hsx_all = get_hsx_list_all()
        
        # Crawl HNX với async Playwright
        hnx_all = await crawl_hnx_data()
        
        # Combine dữ liệu
        combined_df = pd.concat([hsx_all, hnx_all], ignore_index=True)
        
        # Chuyển đổi định dạng ngày (nếu có giá trị không hợp lệ sẽ chuyển thành NaT)
        dates_converted = pd.to_datetime(
            combined_df['date'], 
            format='%d/%m/%Y', 
            errors='coerce'
        )
        combined_df['date'] = dates_converted.dt.strftime('%Y-%m-%d')
        
        result = combined_df.to_dict(orient='records')
        return JSONResponse(content={"data": result})
    
    except Exception as e:
        logging.error(f"Lỗi trong main_handler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
