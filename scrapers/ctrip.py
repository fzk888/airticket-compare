"""携程爬虫 - Playwright 方案（支持 cookies 登录）"""
import json
import os
from .base import BaseScraper
from loguru import logger
from utils.city_mapper import CityMapper

COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies.json")

class CtripScraper(BaseScraper):
    """携程机票爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "携程"

    def load_cookies(self):
        """加载 cookies - 优先从文件，失败从环境变量"""
        # 1. 先尝试从文件加载
        if os.path.exists(COOKIES_FILE):
            try:
                with open(COOKIES_FILE, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for account, cookies in data.items():
                        if cookies:
                            return cookies
                elif isinstance(data, list):
                    return data
            except Exception as e:
                logger.warning(f"加载 cookies 失败: {e}")

        # 2. 从环境变量加载 (CTRIP_COOKIES)
        env_cookies = os.environ.get("CTRIP_COOKIES")
        if env_cookies:
            try:
                data = json.loads(env_cookies)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    for cookies in data.values():
                        if cookies:
                            return cookies
            except Exception as e:
                logger.warning(f"解析 CTRIP_COOKIES 环境变量失败: {e}")

        return None

    async def search_flights(self, from_city: str, to_city: str, date: str, **kwargs):
        from playwright.async_api import async_playwright

        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date})")

            from_code = CityMapper.get_ctrip_code(from_city) or from_city
            to_code = CityMapper.get_ctrip_code(to_city) or to_city

            cookies = self.load_cookies()

            # 没有cookies或过期，弹窗让用户登录
            if not cookies:
                await self._login_and_get_cookies()
                cookies = self.load_cookies()

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    locale="zh-CN"
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                """)

                page = await context.new_page()

                # 注入 cookies
                logger.info(f"{self.platform}: 使用 cookies 登录")
                pw_cookies = []
                for c in cookies:
                    pw_cookie = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".ctrip.com"),
                        "path": c.get("path", "/"),
                    }
                    pw_cookies.append(pw_cookie)
                await context.add_cookies(pw_cookies)

                url = f"https://flights.ctrip.com/online/list/oneway-{from_code}-{to_code}?depdate={date}"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                # 直接等待航班列表出现，然后提取数据
                dom_data = await self.extract_from_page(page)

                await browser.close()

                if dom_data:
                    return dom_data

                # cookies可能过期，重新登录
                await self._login_and_get_cookies()
                cookies = self.load_cookies()
                if cookies:
                    # 重试一次
                    async with async_playwright() as p2:
                        browser2 = await p2.chromium.launch(
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"]
                        )
                        context2 = await browser2.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                        )
                        page2 = await context2.new_page()
                        pw_cookies2 = []
                        for c in cookies:
                            pw_cookies2.append({
                                "name": c["name"],
                                "value": c["value"],
                                "domain": c.get("domain", ".ctrip.com"),
                                "path": c.get("path", "/"),
                            })
                        await context2.add_cookies(pw_cookies2)
                        await page2.goto(url, wait_until="domcontentloaded", timeout=15000)
                        dom_data = await self.extract_from_page(page2)
                        await browser2.close()
                        if dom_data:
                            return dom_data

                return {
                    "platform": self.platform,
                    "status": "failed",
                    "error": "携程查询失败"
                }

        except Exception as e:
            logger.error(f"{self.platform} 查询失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": str(e)}

    async def _login_and_get_cookies(self):
        """弹窗让用户登录，返回cookies"""
        import asyncio
        from playwright.async_api import async_playwright

        print(f"\n{'='*50}")
        print(f"{self.platform}: 需要登录，正在打开浏览器...")
        print(f"{'='*50}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto('https://flights.ctrip.com/online/list/oneway-SZX-PEK?depdate=2026-04-20')

            print("请在浏览器中登录携程账号...")
            print("如果有图形验证码，请完成验证...")
            print("登录成功后系统会自动继续...\n")

            # 等待登录成功
            for i in range(120):  # 最多等10分钟（给足够时间完成验证码）
                await asyncio.sleep(5)
                try:
                    cookies = await context.cookies()
                    has_login = any(c['name'] in ['cticket', 'login_uid', 'login_type'] for c in cookies)
                    if has_login:
                        # 检查页面是否有验证码弹窗
                        captcha = await page.query_selector('[class*="captcha"], [class*="Captcha"], [id*="captcha"], .tcaptcha, #tcaptcha')
                        if captcha:
                            print(f"检测到验证码，请完成验证... ({(i+1)*5}秒)")
                            continue

                        # 检查是否有航班数据加载
                        flight_items = await page.query_selector_all("[class*=flight-item]")
                        if len(flight_items) > 0:
                            # 有航班数据了，说明登录+验证都完成
                            break

                        print(f"登录成功，等待页面加载... ({(i+1)*5}秒)")
                except Exception as e:
                    pass

            # 保存cookies
            ctrip_cookies = []
            for c in await context.cookies():
                ctrip_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".ctrip.com"),
                    "path": c.get("path", "/"),
                })
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump({"": ctrip_cookies}, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 登录成功，Cookies已保存！\n")
            await browser.close()
            return ctrip_cookies

    async def extract_from_page(self, page):
        """从页面 DOM 提取航班和价格"""
        try:
            # 等待页面加载
            await page.wait_for_timeout(5000)

            # 直接查找元素，不要求可见
            flights = await page.evaluate("""
                () => {
                    const results = [];
                    const items = document.querySelectorAll('[class*="flight-item"]');
                    items.forEach(item => {
                        const priceEl = item.querySelector('[class*="price"]');
                        // 航班号：优先从 span id 提取，其次从全文找
                        let flightNo = 'Unknown';
                        const airlineSpan = item.querySelector('[class*="airline-name"] span');
                        if (airlineSpan && airlineSpan.id) {
                            const match = airlineSpan.id.match(/[A-Z]+\\d+/);
                            if (match) flightNo = match[0];
                        }
                        // 备用：从 item 全文匹配航班号
                        if (flightNo === 'Unknown') {
                            const html = item.innerHTML;
                            const m = html.match(/[A-Z]{2}\\d{3,4}/);
                            if (m) flightNo = m[0];
                        }
                        const airlineEl = item.querySelector('[class*="airline-name"]');
                        // 时间在 [class*=time] 元素里
                        const timeEls = item.querySelectorAll('[class*="time"]');
                        const depTimeEl = timeEls.length > 0 ? timeEls[0] : null;
                        const arrTimeEl = timeEls.length > 1 ? timeEls[1] : null;

                        if (priceEl) {
                            const priceMatch = priceEl.textContent.match(/\\d+/);
                            if (priceMatch) {
                                const price = parseInt(priceMatch[0]);
                                // 跳过无效价格或未知航班
                                if (price > 100 && flightNo !== 'Unknown') {
                                    results.push({
                                        price: price,
                                        flightNo: flightNo,
                                        airline: airlineEl ? airlineEl.innerText.split('\\n')[0].trim() : 'Unknown',
                                        depTime: depTimeEl ? depTimeEl.textContent.trim() : '',
                                        arrTime: arrTimeEl ? arrTimeEl.textContent.trim() : ''
                                    });
                                }
                            }
                        }
                    });
                    return results;
                }
            """)

            logger.debug(f"{self.platform}: DOM提取到 {len(flights)} 个航班")

            if flights:
                valid = [f for f in flights if f["price"] > 50]
                if valid:
                    lowest = min(valid, key=lambda x: x["price"])
                    return {
                        "platform": self.platform, "status": "success",
                        "lowest_price": lowest["price"],
                        "tax": 0, "currency": "CNY",
                        "flight": {
                            "number": lowest["flightNo"], "airline": lowest["airline"],
                            "departure": lowest["depTime"], "arrival": lowest["arrTime"],
                            "duration": "", "from_airport": "", "to_airport": "",
                        },
                        "url": "https://flights.ctrip.com"
                    }
            return None
        except Exception as e:
            logger.debug(f"{self.platform}: DOM 提取失败 - {e}")
            return None
