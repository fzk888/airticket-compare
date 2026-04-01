"""同程艺龙爬虫 - 仅支持直飞航班"""
from .base import BaseScraper
from loguru import logger

class ElongScraper(BaseScraper):
    """同程艺龙机票爬虫 - 网页版仅显示直飞"""

    def __init__(self):
        super().__init__()
        self.platform = "同程"

    async def search_flights(self, from_city: str, to_city: str, date: str, **kwargs):
        """搜索航班 - 网页版仅支持直飞"""
        from playwright.async_api import async_playwright
        from utils.city_mapper import CityMapper

        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date})")

            from_airports = CityMapper.get_airports(from_city)
            to_airports = CityMapper.get_airports(to_city)

            if not from_airports or not to_airports:
                return {"platform": self.platform, "status": "failed", "error": "城市代码无效"}

            from_code = from_airports[0]
            to_code = to_airports[0]

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                url = f"https://www.ly.com/flights/itinerary/oneway/{from_code}-{to_code}?date={date}"
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)

                html = await page.content()
                await browser.close()

                return self.parse_html(html)

        except Exception as e:
            logger.error(f"{self.platform} 查询失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": str(e)[:100]}

    def parse_html(self, html: str):
        """解析HTML提取航班数据"""
        from lxml import etree
        import re

        try:
            tree = etree.HTML(html)
            flight_divs = tree.xpath('//div[contains(@class, "flight-item")]')

            if not flight_divs:
                return {"platform": self.platform, "status": "failed", "error": "未找到航班"}

            flights = []
            for div in flight_divs:
                text = etree.tostring(div, encoding='unicode', method='text')

                # 提取价格 (¥1050起)
                price_match = re.search(r'¥(\d+)起', text)
                if not price_match:
                    continue
                price = int(price_match.group(1))
                if price < 100 or price > 50000:
                    continue

                # 提取航班信息
                p_texts = div.xpath('.//p/text()')
                strong_texts = div.xpath('.//strong/text()')
                em_texts = div.xpath('.//em/text()')

                airline = re.split(r'[|｜]', p_texts[0])[0].strip() if p_texts else "Unknown"
                flight_no = re.search(r'[A-Z\d]{2}\d{3,4}', text)

                flights.append({
                    "price": price,
                    "airline": airline,
                    "flight_no": flight_no.group(0) if flight_no else "",
                    "dep_time": strong_texts[0].strip() if len(strong_texts) > 0 else "",
                    "arr_time": strong_texts[1].strip() if len(strong_texts) > 1 else "",
                    "dep_airport": em_texts[0].strip() if len(em_texts) > 0 else "",
                    "arr_airport": em_texts[1].strip() if len(em_texts) > 1 else "",
                })

            if not flights:
                return {"platform": self.platform, "status": "failed", "error": "未提取到航班"}

            lowest = min(flights, key=lambda x: x["price"])
            logger.info(f"{self.platform}: 找到 {len(flights)} 个直飞航班，最低价 ¥{lowest['price']}")

            return {
                "platform": self.platform,
                "status": "success",
                "lowest_price": lowest["price"],
                "tax": 0,
                "currency": "CNY",
                "flight": {
                    "number": lowest["flight_no"],
                    "airline": lowest["airline"],
                    "departure": lowest["dep_time"],
                    "arrival": lowest["arr_time"],
                    "duration": "",
                    "from_airport": lowest["dep_airport"],
                    "to_airport": lowest["arr_airport"],
                },
                "url": "https://www.ly.com"
            }

        except Exception as e:
            logger.error(f"{self.platform} 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": f"解析失败: {e}"}
