# main.py
import os
import uvicorn
from datetime import datetime
from typing import List

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from playwright.async_api import async_playwright, Browser
from tenacity import retry, stop_after_attempt, wait_exponential

# Cấu hình
class Settings:
    HSX_URL = "https://www.hsx.vn/Modules/Listed/Web/NonMarginList"
    HNX_URL = "https://hnx.vn/vi-vn/co-phieu-etfs/chung-khoan-ny-khong-ky-quy.html"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    TIMEOUT = 20.0
    MAX_PAGES = 50

settings = Settings()

app = FastAPI(
    title="Stock Crawler API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Models
class StockItem(BaseModel):
    ticker: str
    name: str
    date: str
    reason: str
    exchange: str

    @field_validator("date")
    def validate_date(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            raise ValueError("Invalid date format")

class APIResponse(BaseModel):
    data: List[StockItem]
    metadata: dict

# HSX Crawler
class HSXCrawler:
    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch_page(page: int) -> List[dict]:
        params = {
            "_search": "false",
            "rows": 30,
            "page": page,
            "sidx": "id",
            "sord": "desc"
        }
        
        async with httpx.AsyncClient(timeout=settings.TIMEOUT) as client:
            response = await client.get(
                settings.HSX_URL,
                params=params,
                headers={"User-Agent": settings.USER_AGENT}
            )
            response.raise_for_status()
            return response.json().get("rows", [])

    @staticmethod
    def process_data(rows: List[dict]) -> List[StockItem]:
        return [
            StockItem(
                ticker=row["cell"][1].strip(),
                name=row["cell"][4].strip(),
                date=datetime.strptime(row["cell"][5], "%d/%m/%Y").strftime("%Y-%m-%d"),
                reason=BeautifulSoup(row["cell"][6], "html.parser").get_text().strip(),
                exchange="HOSE"
            )
            for row in rows if len(row.get("cell", [])) >= 7
        ]

# HNX Crawler
class HNXCrawler:
    _browser: Browser = None

    @classmethod
    async def get_browser(cls) -> Browser:
        if not cls._browser or not cls._browser.is_connected():
            cls._browser = await async_playwright().start().chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        return cls._browser

    @staticmethod
    def parse_html(html: str) -> List[StockItem]:
        soup = BeautifulSoup(html, "html.parser")
        return [
            StockItem(
                ticker=cols[1].get_text(strip=True),
                name=cols[2].get_text(strip=True),
                date=datetime.strptime(cols[3].get_text(strip=True), "%d/%m/%Y").strftime("%Y-%m-%d"),
                reason=cols[4].get_text(strip=True).replace("- ", ""),
                exchange="HNX"
            )
            for row in soup.select("table#_tableDatas tbody tr")
            if len(cols := row.find_all("td")) >= 5
        ]

    @classmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def crawl(cls) -> List[StockItem]:
        browser = await cls.get_browser()
        context = await browser.new_context()
        
        try:
            page = await context.new_page()
            await page.goto(settings.HNX_URL, wait_until="networkidle")
            
            items = []
            for _ in range(settings.MAX_PAGES):
                items += cls.parse_html(await page.content())
                
                if await page.locator("#next").is_disabled():
                    break
                
                await page.click("#next")
                await page.wait_for_load_state("domcontentloaded")
            
            return items
        finally:
            await context.close()

# API Endpoints
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/stocks", response_model=APIResponse)
async def get_stocks(request: Request):
    try:
        # HSX
        hsx_data = []
        for page in range(1, settings.MAX_PAGES + 1):
            if not (rows := await HSXCrawler.fetch_page(page)):
                break
            hsx_data.extend(HSXCrawler.process_data(rows))

        # HNX
        hnx_data = await HNXCrawler.crawl()

        return {
            "data": hsx_data + hnx_data,
            "metadata": {
                "total": len(hsx_data) + len(hnx_data),
                "generated_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(500, detail=f"Crawling failed: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Thay đổi về 10000
    uvicorn.run(app, host="0.0.0.0", port=port)
