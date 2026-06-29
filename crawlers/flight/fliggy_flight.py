"""
飞猪航班爬虫 - DrissionPage headless + 正则解析SSR HTML
飞猪PC端(SSR): 访问 sjipiao.fliggy.com/flight_search_result.htm，航班数据直接在页面HTML中。

搬自 RideClawAPI app/clients/spiders/fliggy_flight_spider.py。
改动：
- import 改为 crawlers.core 路径；
- 移除模块级 ensure_utf8_stdio() 副作用调用与 sys.path hack；
- __main__ 自测块改用标准库 logging。
抓取逻辑零改动。
"""
import time, re, json, logging, os
from typing import List, Dict, Any, Optional

from crawlers.core.browser_base import FliggyBrowserMixin
from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)


class FliggyFlightSpider(FliggyBrowserMixin):
    """飞猪航班爬虫 (DrissionPage headless + 正则解析SSR)"""

    def __init__(self, headless: bool = True, cookie: Optional[str] = None):
        super().__init__()
        self.headless = headless
        self.cookie = cookie

    def search_flights(self, dep_city: str, arr_city: str, date: str,
                       timeout: int = 60) -> List[Dict[str, Any]]:
        """
        搜索航班 (飞猪PC端SSR)，返回全部航班，不做任何过滤。

        Args:
            dep_city: 出发城市三字码 (如 BJS)
            arr_city: 到达城市三字码 (如 HGH)
            date: 出发日期 YYYY-MM-DD
            timeout: 整体超时秒数（默认60s，原90s）

        Returns:
            航班列表（全部，未过滤）
        """
        flights = []
        start = time.time()
        try:
            self._ensure_page(headless=self.headless, user_dir_name='drission_fliggy_flight')

            # 1. 注入 Cookie
            logger.info("注入飞猪Cookie...")
            self._inject_cookies(cookie_str=self.cookie)

            if time.time() - start > timeout - 10:
                logger.warning("Cookie注入后已超时，跳过搜索")
                return flights

            # 2. 直接请求搜索结果页 (SSR渲染)
            url = (
                f"https://sjipiao.fliggy.com/flight_search_result.htm"
                f"?tripType=0&depCity={dep_city}&arrCity={arr_city}"
                f"&depDate={date}&classType=0&adultNum=1&childNum=0&infantNum=0"
            )
            logger.info("搜索: %s", url)
            self.page.get(url)

            # 智能轮询等待SSR渲染（递增间隔，最多等10秒）
            # 替代固定 sleep(1)*10，正常2-4秒就能出结果
            loaded = False
            for i in range(20):
                elapsed = time.time() - start
                if elapsed > timeout - 2:
                    logger.warning("搜索页加载超时")
                    break
                # 递增间隔：0.5s → 1s → 1.5s → ...
                wait = min(0.5 * (i + 1), 2.0)
                time.sleep(wait)
                try:
                    if self.page.ele('css:.J_FlightItem', timeout=0.3):
                        logger.info("页面加载完成, 等待 %.1f秒", time.time() - start)
                        loaded = True
                        break
                except Exception:
                    pass
            if not loaded:
                logger.warning("等待航班元素超时")

            # 3. 拿HTML用正则解析
            html = self.page.html
            logger.info("页面HTML长度: %d", len(html))
            flights = self._parse_html(html)
            logger.info("解析到 %d 条航班", len(flights))

            # 解析数量异常告警（正常国内线20-80条，低于5条可能DOM变了）
            if len(flights) < 5 and len(html) > 10000:
                logger.warning(
                    "⚠️ 飞猪航班解析数量异常: 仅 %d 条 (HTML %d 字符)，"
                    "可能是飞猪DOM结构变更，请检查选择器",
                    len(flights), len(html),
                )

        except Exception as e:
            logger.error("搜索失败: %s", e, exc_info=True)

        elapsed = time.time() - start
        logger.info("搜索完成, 耗时 %.1f秒, %d 条航班", elapsed, len(flights))
        return flights

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """从HTML字符串中用正则提取航班数据"""
        flights = []

        # 按 flight-list-item 分割
        blocks = re.split(r'<div\s+class="flight-list-item\s+', html)
        logger.info("找到 %d 个航班块", len(blocks) - 1)

        for block in blocks[1:]:
            try:
                flight = self._extract_from_html(block)
                if flight:
                    flights.append(flight)
            except Exception as e:
                logger.debug("提取单个航班失败: %s", e)
                continue

        return flights

    def _extract_from_html(self, block: str) -> Optional[Dict[str, Any]]:
        """从单个航班HTML块中提取数据（多选择器降级）"""

        # ── 航班号（优先级：J_TestFlight > data-flight-no > flight-number）──
        flight_text = ''
        for pattern in [
            r'J_TestFlight[^>]*>([^<]+)<',
            r'data-flight-no="([^"]+)"',
            r'class="flight-number[^"]*"[^>]*>([^<]+)<',
        ]:
            m = re.search(pattern, block)
            if m:
                flight_text = m.group(1).strip()
                break

        # 提取航班号 (2字母+3~4数字)
        flight_number = ''
        m2 = re.search(r'([A-Z]{2}\d{3,4})', flight_text)
        if m2:
            flight_number = m2.group(1)
        if not flight_number:
            return None

        # ── 航司: 从中文名中提取（厦航MF8130 → 厦航）──
        airline = ''
        m3 = re.match(r'([\u4e00-\u9fa5]+)', flight_text)
        if m3:
            airline = m3.group(1)

        # ── 出发时间（多选择器）──
        dep_time = ''
        for pattern in [
            r'class="flight-time-deptime"[^>]*>([^<]+)<',
            r'class="dep-time[^"]*"[^>]*>([^<]+)<',
        ]:
            m = re.search(pattern, block, re.DOTALL)
            if m:
                dep_time = m.group(1).strip()
                break

        # ── 到达时间（多选择器）──
        arr_time = ''
        for pattern in [
            r'class="s-time"[^>]*>([^<]+)<',
            r'class="arr-time[^"]*"[^>]*>([^<]+)<',
            r'class="flight-time-arrtime[^"]*"[^>]*>([^<]+)<',
        ]:
            m = re.search(pattern, block)
            if m:
                arr_time = m.group(1).strip()
                break

        # ── 出发机场（多选择器）──
        dep_airport = ''
        for pattern in [
            r'class="port-dep"[^>]*>([^<]+)<',
            r'class="airport-dep[^"]*"[^>]*>([^<]+)<',
            r'data-dep-airport="([^"]+)"',
        ]:
            m = re.search(pattern, block)
            if m:
                dep_airport = m.group(1).strip()
                break

        # ── 到达机场（多选择器）──
        arr_airport = ''
        for pattern in [
            r'class="port-arr"[^>]*>([^<]+)<',
            r'class="airport-arr[^"]*"[^>]*>([^<]+)<',
            r'data-arr-airport="([^"]+)"',
        ]:
            m = re.search(pattern, block)
            if m:
                arr_airport = m.group(1).strip()
                break

        # ── 机型（多选择器）──
        aircraft = ''
        for pattern in [
            r'data-flight-type="([^"]+)"',
            r'class="aircraft-type[^"]*"[^>]*>([^<]+)<',
            r'data-plane-type="([^"]+)"',
        ]:
            m = re.search(pattern, block)
            if m:
                aircraft = m.group(1).strip()
                break

        # ── 价格（多选择器）──
        price = 0
        for pattern in [
            r'J_FlightListPrice[^>]*>(\d+)<',
            r'class="price[^"]*"[^>]*>.*?(\d{2,})',
            r'data-price="(\d+)"',
        ]:
            m = re.search(pattern, block, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1))
                    break
                except ValueError:
                    continue

        # ── 折扣（多选择器）──
        discount = ''
        for pattern in [
            r'class="discount"[^>]*>([^<]+)<',
            r'class="tag-discount[^"]*"[^>]*>([^<]+)<',
        ]:
            m = re.search(pattern, block)
            if m:
                discount = m.group(1).strip()
                break

        # ── 准点率（多选择器）──
        ontime_rate = ''
        for pattern in [
            r'class="flight-ontime-rate"[^>]*>.*?<p>([^<]+)<',
            r'class="ontime-rate[^"]*"[^>]*>([^<]+)<',
            r'准点率[：:]\s*(\d+%)',
        ]:
            m = re.search(pattern, block, re.DOTALL)
            if m:
                ontime_rate = m.group(1).strip()
                break

        # ── 共享航班（多选择器）──
        share_flight = ''
        for pattern in [
            r'data-tooltip-type="share"[^>]*data-content="([^"]*)"',
            r'class="share-flight[^"]*"[^>]*title="([^"]+)"',
            r'共享航班[：:]\s*([^<]+)',
        ]:
            m = re.search(pattern, block)
            if m:
                share_flight = m.group(1).strip()
                break

        return {
            'flight_number': flight_number,
            'airline': airline,
            'dep_time': dep_time,
            'arr_time': arr_time,
            'dep_airport': dep_airport,
            'arr_airport': arr_airport,
            'aircraft': aircraft,
            'price_yuan': float(price),
            'price': yuan_to_fen(price),  # 分（与携程格式一致）
            'discount': discount,
            'ontime_rate': ontime_rate,
            'share_flight': share_flight,
            'source': 'fliggy_pc',
        }

    def close(self):
        self._close_page()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    spider = FliggyFlightSpider(headless=True)
    flights = spider.search_flights("BJS", "HGH", "2026-04-20")
    spider.close()

    out_path = os.path.join(os.getcwd(), 'fliggy_result.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(flights, f, ensure_ascii=False, indent=2)

    logger.info("[Spider][FliggyFlight] 找到 %d 条航班，结果已保存到 %s", len(flights), out_path)
    if flights:
        for fl in flights[:5]:
            logger.info(
                "[Spider][FliggyFlight] %s %s %s-%s %s->%s ¥%s %s",
                fl["flight_number"],
                fl["airline"],
                fl["dep_time"],
                fl["arr_time"],
                fl["dep_airport"],
                fl["arr_airport"],
                fl["price_yuan"],
                fl.get("discount", ""),
            )
