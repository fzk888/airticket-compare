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
        flight_type_filter = kwargs.get("flight_type", "all")

        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date}) [筛选:{flight_type_filter}]")

            from_code = CityMapper.get_ctrip_code(from_city) or from_city
            to_code = CityMapper.get_ctrip_code(to_city) or to_city

            cookies = self.load_cookies()

            # 没有 cookies 则先登录（登录流程自己启动浏览器）
            if not cookies:
                await self._login_and_get_cookies()
                cookies = self.load_cookies()

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
                        "--disable-gpu"
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
                
                # 注入中文字体 CSS，解决 Linux 下中文显示方框问题
                await context.add_init_script("""
                    const style = document.createElement('style');
                    style.textContent = `
                        * {
                            font-family: "Microsoft YaHei", "SimHei", "SimSun", "WenQuanYi Zen Hei", sans-serif !important;
                        }
                        body, html {
                            font-family: "Microsoft YaHei", "SimHei", "SimSun", "WenQuanYi Zen Hei", sans-serif !important;
                        }
                    `;
                    document.head.appendChild(style);
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
                logger.info(f"{self.platform}: 访问 {url}")
                
                # 增加超时时间，添加重试
                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(5000)  # 等待页面渲染
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"{self.platform}: 页面加载失败，重试 ({attempt+1}/{max_retries}): {e}")
                            await page.wait_for_timeout(2000)
                        else:
                            raise

                # 直接等待航班列表出现，然后提取数据
                dom_data = await self.extract_from_page(page, flight_type_filter=flight_type_filter)

                await browser.close()

                if dom_data:
                    return dom_data

                # 数据提取失败，检查 cookies 是否存在，存在则不重新登录
                cookies_now = self.load_cookies()
                if not cookies_now:
                    # cookies 过期或无效，重新登录
                    await self._login_and_get_cookies()
                    cookies = self.load_cookies()
                    if cookies:
                        # 重试一次
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
                                "domain": c.get("domain", ".ctrip.com"),
                                "path": c.get("path", "/"),
                            })
                        await context2.add_cookies(pw_cookies2)
                        await page2.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page2.wait_for_timeout(5000)
                        dom_data = await self.extract_from_page(page2, flight_type_filter=flight_type_filter)
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
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale="zh-CN",
                viewport={"width": 1920, "height": 1080}
            )
            
            # 注入中文字体 CSS
            await context.add_init_script("""
                const style = document.createElement('style');
                style.textContent = `
                    * {
                        font-family: "Microsoft YaHei", "SimHei", "SimSun", "WenQuanYi Zen Hei", sans-serif !important;
                    }
                    body, html {
                        font-family: "Microsoft YaHei", "SimHei", "SimSun", "WenQuanYi Zen Hei", sans-serif !important;
                    }
                `;
                document.head.appendChild(style);
            """)
            
            page = await context.new_page()
            await page.goto('https://flights.ctrip.com/online/list/oneway-SZX-PEK?depdate=2026-04-20')

            print("请在浏览器中登录携程账号...")
            print("如果有图形验证码，请完成验证...")
            print("登录成功后系统会自动继续...\n")

            # 等待登录成功（最多30秒，每2秒检测一次）
            login_detected = False
            for i in range(15):
                await asyncio.sleep(2)
                try:
                    cookies = await context.cookies()
                    has_login = any(c['name'] in ['cticket', 'login_uid', 'login_type'] for c in cookies)
                    if has_login:
                        # 检查页面是否有验证码弹窗
                        captcha = await page.query_selector('[class*="captcha"], [class*="Captcha"], [id*="captcha"], .tcaptcha, #tcaptcha')
                        if captcha:
                            print(f"检测到验证码，请完成验证... ({(i+1)*2}秒)")
                            continue

                        # 检查是否有航班数据加载
                        flight_items = await page.query_selector_all("[class*=flight-item]")
                        if len(flight_items) > 0 or login_detected:
                            print(f"登录成功！")
                            login_detected = True
                            break
                        print(f"登录成功，等待页面加载... ({(i+1)*2}秒)")
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

    async def extract_from_page(self, page, flight_type_filter: str = "all"):
        """从页面 DOM 提取航班和价格

        Args:
            page: Playwright page 对象
            flight_type_filter: 筛选类型 "all" | "direct" | "connecting"
        """
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

                        // 检测航班类型：查找"经停"或"中转"标识
                        const itemText = item.innerText || '';
                        const isConnecting = itemText.includes('经停') || itemText.includes('中转');
                        const journeyType = isConnecting ? '中转' : '直达';

                        // 统计航班段数：查找所有航班号
                        const flightNosInItem = itemText.match(/[A-Z]{2}\\d{3,4}/g) || [];
                        const segmentsCount = flightNosInItem.length || 1;

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
                                        arrTime: arrTimeEl ? arrTimeEl.textContent.trim() : '',
                                        journeyType: journeyType,
                                        segmentsCount: segmentsCount
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

                # 按类型筛选
                if flight_type_filter == "direct":
                    filtered = [f for f in valid if f["journeyType"] == "直达"]
                    valid = filtered if filtered else valid
                elif flight_type_filter == "connecting":
                    filtered = [f for f in valid if f["journeyType"] == "中转"]
                    valid = filtered if filtered else valid

                if valid:
                    lowest = min(valid, key=lambda x: x["price"])
                    # 构建所有符合筛选条件的航班列表（最多10条）
                    all_flights = [{
                        "price": f["price"],
                        "flightNo": f["flightNo"],
                        "airline": f["airline"],
                        "depTime": f["depTime"],
                        "arrTime": f["arrTime"],
                        "duration": "",
                        "from_airport": "",
                        "to_airport": "",
                        "journey_type": f["journeyType"],
                        "segments_count": f["segmentsCount"]
                    } for f in sorted(valid, key=lambda x: x["price"])[:10]]

                    return {
                        "platform": self.platform, "status": "success",
                        "lowest_price": lowest["price"],
                        "tax": 0, "currency": "CNY",
                        "flight": {
                            "number": lowest["flightNo"], "airline": lowest["airline"],
                            "departure": lowest["depTime"], "arrival": lowest["arrTime"],
                            "duration": "", "from_airport": "", "to_airport": "",
                            "journey_type": lowest["journeyType"],
                            "segments_count": lowest["segmentsCount"]
                        },
                        "flights_list": all_flights,
                        "url": "https://flights.ctrip.com"
                    }
            return None
        except Exception as e:
            logger.debug(f"{self.platform}: DOM 提取失败 - {e}")
            return None
