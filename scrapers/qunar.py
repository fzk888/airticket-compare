"""去哪儿爬虫 - Playwright 方案（需要登录）"""
import json
import os
from .base import BaseScraper
from loguru import logger
from utils.city_mapper import CityMapper

COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies_qunar.json")


class QunarScraper(BaseScraper):
    """去哪儿机票爬虫"""

    def __init__(self):
        super().__init__()
        self.platform = "去哪儿"

    def load_cookies(self):
        """加载 cookies - 优先从文件，失败从环境变量"""
        if os.path.exists(COOKIES_FILE):
            try:
                with open(COOKIES_FILE, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    for cookies in data.values():
                        if cookies:
                            return cookies
            except Exception as e:
                logger.warning(f"加载去哪儿 cookies 失败: {e}")

        env_cookies = os.environ.get("QUNAR_COOKIES")
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
                logger.warning(f"解析 QUNAR_COOKIES 环境变量失败: {e}")

        return None

    async def search_flights(self, from_city: str, to_city: str, date: str, **kwargs):
        from playwright.async_api import async_playwright
        flight_type_filter = kwargs.get("flight_type", "all")

        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date}) [筛选:{flight_type_filter}]")

            from_code = CityMapper.get_airports(from_city)[0] if CityMapper.get_airports(from_city) else from_city
            to_code = CityMapper.get_airports(to_city)[0] if CityMapper.get_airports(to_city) else to_city

            cookies = self.load_cookies()

            # 没有 cookies 则先登录（登录流程自己启动浏览器）
            if not cookies:
                logger.info(f"{self.platform}: 未找到 cookies，开始登录流程")
                await self._login_and_get_cookies()
                cookies = self.load_cookies()
                if not cookies:
                    return {"platform": self.platform, "status": "failed", "error": "登录失败，未获取到 cookies"}

            # 有 cookies 时静默查询
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    viewport={"width": 1920, "height": 1080}
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    // 移除 selenium 检测
                    Object.defineProperty(navigator, 'selenium', { get: () => undefined });
                """)
                # 注入中文字体
                await context.add_init_script("""
                    const style = document.createElement('style');
                    style.textContent = `
                        * { font-family: "Microsoft YaHei", "SimHei", "SimSun", sans-serif !important; }
                        body, html { font-family: "Microsoft YaHei", "SimHei", "SimSun", sans-serif !important; }
                    `;
                    document.head.appendChild(style);
                """)

                page = await context.new_page()

                # 注入 cookies
                pw_cookies = []
                for c in cookies:
                    pw_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".qunar.com"),
                        "path": c.get("path", "/"),
                    })
                await context.add_cookies(pw_cookies)

                url = f"https://flight.qunar.com/site/oneway_list.htm?searchDepartureAirport={from_city}&searchArrivalAirport={to_city}&searchDepartureTime={date}&nextNDays=0&startSearch=true&fromCode={from_code}&toCode={to_code}&from=flight_dom_search"
                logger.info(f"{self.platform}: 访问 {url}")

                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        # 等待动态内容加载（航班列表渲染）
                        await page.wait_for_timeout(5000)
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"{self.platform}: 页面加载失败，重试 ({attempt+1}/{max_retries}): {e}")
                            await page.wait_for_timeout(3000)
                        else:
                            raise

                dom_data = await self.extract_from_page(page, flight_type_filter=flight_type_filter)
                await browser.close()

                if dom_data:
                    return dom_data

                # 数据提取失败，检查 cookies 是否存在，存在则不重新登录
                cookies_now = self.load_cookies()
                if not cookies_now:
                    # cookies 过期或无效，重新登录
                    await self._login_and_get_cookies()
                if cookies:
                    async with async_playwright() as p2:
                        browser2 = await p2.chromium.launch(
                            headless=True,
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage"
                            ]
                        )
                        context2 = await browser2.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                            viewport={"width": 1920, "height": 1080}
                        )
                        page2 = await context2.new_page()
                        pw_cookies2 = []
                        for c in cookies:
                            pw_cookies2.append({
                                "name": c["name"],
                                "value": c["value"],
                                "domain": c.get("domain", ".qunar.com"),
                                "path": c.get("path", "/"),
                            })
                        await context2.add_cookies(pw_cookies2)
                        await page2.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page2.wait_for_timeout(4000)
                        dom_data = await self.extract_from_page(page2, flight_type_filter=flight_type_filter)
                        await browser2.close()
                        if dom_data:
                            return dom_data

                return {
                    "platform": self.platform,
                    "status": "failed",
                    "error": "去哪儿查询失败"
                }

        except Exception as e:
            logger.error(f"{self.platform} 查询失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": str(e)}

    async def _login_and_get_cookies(self):
        """打开浏览器让用户登录，检测到登录成功后关闭浏览器并保存 cookies"""
        import asyncio
        from playwright.async_api import async_playwright

        print(f"\n{'='*50}")
        print(f"{self.platform}: 需要登录，正在打开浏览器...")
        print(f"{'='*50}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="zh-CN",
                viewport={"width": 1920, "height": 1080}
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page = await context.new_page()

            # 直接打开去哪儿登录页
            login_url = 'https://user.qunar.com/passport/login.jsp?ret=https%3A%2F%2Fflight.qunar.com%2Fsite%2Foneway_list.htm'
            await page.goto(login_url, timeout=20000)
            print(f"已打开登录页: {page.url}")

            print("\n请在浏览器中完成去哪儿账号登录...")
            print("支持二维码扫码、账号密码等方式...")
            print("登录成功后浏览器将自动关闭...\n")

            # 等待登录成功：检测 URL 跳回 flight.qunar.com（不在 user.qunar.com）
            login_detected = False
            for i in range(30):
                await asyncio.sleep(2)
                try:
                    current_url = page.url
                    print(f"等待登录中... ({(i+1)*2}秒)")

                    if 'flight.qunar.com' in current_url and 'user.qunar.com' not in current_url:
                        print(f"\n✅ 检测到登录成功！")
                        login_detected = True
                        break
                except Exception as e:
                    print(f"异常: {e}")

            # 保存 cookies
            all_cookies = await context.cookies()
            qunar_cookies = []
            for c in all_cookies:
                if c['name'] and c['value'] and len(c['value']) > 5:
                    qunar_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".qunar.com"),
                        "path": c.get("path", "/"),
                    })

            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                json.dump({"": qunar_cookies}, f, ensure_ascii=False, indent=2)

            print(f"✅ 已保存 {len(qunar_cookies)} 个 cookies")

            await browser.close()
            return qunar_cookies if login_detected else None

    def _decode_qunar_prices(self, html: str) -> list:
        """解码去哪儿 CSS 字体混淆价格
        当前去哪儿使用 aria-label="报价：XXX元" 和 title="XXX" 属性存储明文价格
        """
        import re
        price_list = []

        # 方法1: 从 aria-label="报价：XXX元" 提取（最可靠）
        aria_prices = re.findall(r'aria-label="报价[：:]\s*(\d+)\s*元"', html)
        if aria_prices:
            price_list = [int(p) for p in aria_prices]
            return price_list

        # 方法2: 从 <span class="fix_price" title="XXX"> 提取
        fix_prices = re.findall(r'<span class="fix_price"[^>]*title="(\d+)"', html)
        if fix_prices:
            price_list = [int(p) for p in fix_prices]
            return price_list

        return price_list

    async def extract_from_page(self, page, flight_type_filter: str = "all"):
        """从页面 DOM 提取航班和价格"""
        try:
            # 轮询等待航班列表出现，最多等15秒
            for _ in range(15):
                count = await page.locator('.b-airfly').count()
                if count >= 5:
                    break
                await page.wait_for_timeout(1000)
            else:
                # 超时，尝试用 fallback
                logger.debug(f"{self.platform}: 等待航班列表超时")
            import re

            # 从 .b-airfly 精确提取每行航班信息和价格
            flights_raw = await page.evaluate("""
                () => {
                    const results = [];
                    const seen = new Set();
                    const airflys = document.querySelectorAll('.b-airfly');
                    airflys.forEach(airfly => {
                        // 价格：aria-label 在 .col-price .prc 上
                        const priceEl = airfly.querySelector('.col-price .prc');
                        if (!priceEl) return;
                        const aria = priceEl.getAttribute('aria-label') || '';
                        const priceMatch = aria.match(/\\d+/);
                        if (!priceMatch) return;
                        const price = parseInt(priceMatch[0], 10);
                        if (price < 100 || price > 10000) return;

                        // 航班号
                        const airlineEl = airfly.querySelector('.col-airline');
                        if (!airlineEl) return;
                        const flightText = airlineEl.innerText || '';
                        const flMatch = flightText.match(/[A-Z]{2}\\d{3,5}/);
                        if (!flMatch) return;
                        const flightNo = flMatch[0];

                        // 时间
                        const timeEls = airfly.querySelectorAll('.col-time h2');
                        if (timeEls.length < 2) return;
                        const depTime = timeEls[0].innerText.trim();
                        const arrTime = timeEls[1].innerText.trim();

                        const key = flightNo + depTime;
                        if (seen.has(key)) return;
                        seen.add(key);

                        // 中转判断
                        const fullText = airfly.innerText || '';
                        const allFlightNos = fullText.match(/[A-Z]{2}\\d{3,5}/g) || [];
                        const isConnecting = /中转|经停|停留|转机/.test(fullText) || allFlightNos.length > 1;
                        const segmentsCount = allFlightNos.length || 1;

                        results.push({
                            price,
                            flightNo,
                            depTime,
                            arrTime,
                            isConnecting,
                            segmentsCount
                        });
                    });
                    return results;
                }
            """)

            logger.debug(f"{self.platform}: DOM提取到 {len(flights_raw)} 个航班行")

            if not flights_raw:
                flights_raw = []

            # 分类：直飞和中转
            direct_flights = sorted([f for f in flights_raw if not f['isConnecting']], key=lambda x: x["price"])
            connecting_flights = sorted([f for f in flights_raw if f['isConnecting']], key=lambda x: x["price"])

            # 根据筛选类型决定返回哪些
            if flight_type_filter == "direct":
                show_flights = direct_flights
            elif flight_type_filter == "connecting":
                show_flights = connecting_flights
            else:
                show_flights = sorted(flights_raw, key=lambda x: x["price"])

            if show_flights:
                lowest = show_flights[0]
                return {
                    "platform": self.platform,
                    "status": "success",
                    "lowest_price": lowest["price"],
                    "lowest_direct_price": direct_flights[0]["price"] if direct_flights else None,
                    "lowest_connecting_price": connecting_flights[0]["price"] if connecting_flights else None,
                    "tax": 0,
                    "currency": "CNY",
                    "flight": {
                        "number": lowest["flightNo"],
                        "airline": "Unknown",
                        "departure": lowest.get("depTime", ""),
                        "arrival": lowest.get("arrTime", ""),
                        "duration": "",
                        "from_airport": "",
                        "to_airport": "",
                        "journey_type": "中转" if lowest["isConnecting"] else "直达",
                        "segments_count": lowest.get("segmentsCount", 1)
                    },
                    "flights_list": [{
                        "price": f["price"],
                        "flightNo": f["flightNo"],
                        "airline": "Unknown",
                        "depTime": f.get("depTime", ""),
                        "arrTime": f.get("arrTime", ""),
                        "duration": "",
                        "from_airport": "",
                        "to_airport": "",
                        "journey_type": "中转" if f["isConnecting"] else "直达",
                        "segments_count": f.get("segmentsCount", 1)
                    } for f in show_flights[:10]],
                    "url": "https://flight.qunar.com"
                }

            # 备用：价格日历
            try:
                cal_locs = page.locator("text=/\u00a5\\d+/")
                cal_count = await cal_locs.count()
                cal_prices = []
                for i in range(min(cal_count, 20)):
                    try:
                        t = await cal_locs.nth(i).inner_text(timeout=1000)
                        m = re.search(r'\u00a5(\d+)', t)
                        if m:
                            p = int(m.group(1))
                            if 100 < p < 10000:
                                cal_prices.append(p)
                    except:
                        continue
                if cal_prices:
                    lowest_price = min(cal_prices)
                    logger.info(f"{self.platform}: 从价格日历获取最低价 \u00a5{lowest_price}")
                    return {
                        "platform": self.platform,
                        "status": "success",
                        "lowest_price": lowest_price,
                        "lowest_direct_price": lowest_price,
                        "lowest_connecting_price": None,
                        "tax": 0,
                        "currency": "CNY",
                        "flight": {"number": "N/A", "airline": "N/A", "departure": "N/A",
                                   "arrival": "N/A", "duration": "", "from_airport": "",
                                   "to_airport": "", "journey_type": "直达", "segments_count": 1},
                        "flights_list": [],
                        "url": "https://flight.qunar.com"
                    }
            except Exception as e:
                logger.debug(f"{self.platform}: 价格日历提取失败: {e}")

            return None

        except Exception as e:
            logger.debug(f"{self.platform}: DOM 提取失败 - {e}")
            return None
