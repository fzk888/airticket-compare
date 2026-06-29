#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DrissionPage 携程 H5 爬虫 - 完整可用版

搬自 RideClawAPI app/clients/spiders/ctrip_h5_spider_v2.py。
改动：
- import 改为 crawlers.core 路径；
- 移除 sys.path hack；
- __main__ 自测块改用标准库 logging。
抓取逻辑零改动。
"""
import time
import ast
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

from DrissionPage import ChromiumPage, ChromiumOptions

from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)


class CtripH5Drission:
    """携程 H5 爬虫 (DrissionPage)"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None

    def _init_page(self):
        co = ChromiumOptions()
        if self.headless:
            co.headless()
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--window-size=414,896')
        co.set_user_agent(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        )
        self.page = ChromiumPage(co)
        logger.info("DrissionPage 浏览器初始化成功")

    def search_flights(self, from_city: str, to_city: str, date: str,
                       timeout: int = 30) -> List[Dict[str, Any]]:
        """搜索航班"""
        flights = []
        start = time.time()
        try:
            if not self.page:
                self._init_page()

            # 1. 先启动监听（在访问任何页面之前），防止首页跳转期间漏包
            self.page.listen.start('flightListSearchForH5')

            # 2. 首页建立 session（智能等待，替代硬 sleep 3s）
            logger.info("访问携程首页")
            self.page.get("https://m.ctrip.com/html5/flight/")
            # 智能轮询等待首页加载，最多等 5s，比 sleep(3) 更快且更稳
            for i in range(10):
                elapsed = time.time() - start
                if elapsed > 5:
                    break
                time.sleep(0.5)
                try:
                    # 页面有任意内容就认为加载完成
                    if self.page.title:
                        logger.info("携程首页加载完成, 耗时 %.1fs", elapsed + 0.5)
                        break
                except Exception:
                    pass

            if time.time() - start > timeout - 8:
                logger.warning("首页加载后剩余时间不足，跳过搜索")
                return flights

            # 3. 搜索页（监听已提前启动，不会漏包）
            url = (
                f"https://m.ctrip.com/html5/flight/swift/domestic/"
                f"{from_city.lower()}/{to_city.lower()}/{date}/y/1/0/0"
            )
            logger.info(f"搜索: {url}")
            self.page.get(url)

            # 4. 等待拦截（剩余时间用完为止）
            remaining = max(timeout - int(time.time() - start) - 2, 5)
            pkt = self.page.listen.wait(timeout=remaining)
            if pkt and pkt.response:
                body = pkt.response.body
                raw = body if isinstance(body, bytes) else str(body).encode('utf-8')
                logger.info(f"响应: {len(raw)} bytes, 耗时 {time.time()-start:.1f}s")
                flights = self._parse(raw)
                logger.info(f"解析到 {len(flights)} 条航班")
            else:
                logger.warning("未拦截到API (耗时 %.1fs)", time.time() - start)

        except Exception as e:
            logger.error(f"搜索失败: {e}", exc_info=True)

        return flights

    def _parse(self, raw: bytes) -> List[Dict[str, Any]]:
        """解析携程 H5 API 响应"""
        flights = []
        try:
            text = raw.decode('utf-8')
            data = ast.literal_eval(text)
            items = data.get('fltitem', [])
            if not items:
                items = data.get('data', {}).get('flightItineraryList', [])

            for item in items:
                f = self._extract(item)
                if f:
                    flights.append(f)
        except Exception as e:
            logger.error(f"解析失败: {e}", exc_info=True)
        return flights

    def _extract(self, item: Dict) -> Dict[str, Any]:
        """提取单条航班"""
        try:
            stns = item.get('mutilstn', [])
            if not stns:
                return None
            stn = stns[0]

            # 航班号
            bas = stn.get('basinfo', {})
            flight_no = bas.get('flgno', '')
            airline_code = bas.get('aircode', '')

            # 机场
            dep_airport = stn.get('dportinfo', {}).get('aport', '')
            arr_airport = stn.get('aportinfo', {}).get('aport', '')

            # 时间
            dt = stn.get('dateinfo', {})
            dep_raw = dt.get('ddate', '')
            arr_raw = dt.get('adate', '')
            dep_time = dep_raw[-8:-3] if dep_raw else ''
            arr_time = arr_raw[-8:-3] if arr_raw else ''

            # 机型
            aircraft = stn.get('craftinfo', {}).get('cdisnames', '')

            # 价格：取 policyinfo 中最低的 tprice
            policies = item.get('policyinfo', [])
            min_price = None
            cabin_class = 'Y'
            discount_text = ''
            for p in policies:
                tp = p.get('tprice', 0)
                if tp and (min_price is None or tp < min_price):
                    min_price = tp
                    # 舱位信息
                    class_info = p.get('classinfor', [])
                    if class_info:
                        cnotes = class_info[0].get('classNoteList', [])
                        for cn in cnotes:
                            if cn.get('notetype') == 2:
                                cabin_class = cn.get('notecnt', 'Y')
                    # 折扣信息
                    fnote = p.get('fnotelst', [])
                    for fn in fnote:
                        if fn.get('notetype') == 4:
                            discount_text = fn.get('notecnt', '')

            if min_price is None:
                min_price = 0

            return {
                'flight_no': flight_no,
                'airline': airline_code,
                'dep_time': dep_time,
                'arr_time': arr_time,
                'dep_airport': dep_airport,
                'arr_airport': arr_airport,
                'aircraft': aircraft,
                'price': yuan_to_fen(min_price),       # 分
                'price_yuan': float(min_price),       # 元
                'cabin_class': cabin_class,
                'discount': discount_text,
                'source': 'ctrip_h5',  # 与 CtripSpiderService.CTRIP_SOURCE 保持一致
            }
        except Exception as e:
            logger.warning(f"提取失败: {e}")
            return None

    def close(self):
        if self.page:
            try:
                self.page.quit()
            except Exception:
                pass
            self.page = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from_city = "TNA"
    to_city = "SHA"
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("[Spider][CtripH5] 搜索: %s -> %s %s", from_city, to_city, tomorrow)

    with CtripH5Drission(headless=True) as spider:
        flights = spider.search_flights(from_city, to_city, tomorrow)

    if flights:
        logger.info("[Spider][CtripH5] 成功获取 %d 条航班", len(flights))
        for f in flights:
            dep_ap = f['dep_airport'] or '?'
            arr_ap = f['arr_airport'] or '?'
            craft = f['aircraft'] or ''
            disc = f.get('discount', '') or ''
            logger.info(
                "[Spider][CtripH5] %s %s %s-%s %s-%s %s ¥%.0f %s",
                f["flight_no"],
                f["airline"],
                f["dep_time"],
                f["arr_time"],
                dep_ap,
                arr_ap,
                craft,
                f["price_yuan"],
                disc,
            )
    else:
        logger.info("[Spider][CtripH5] 未获取到航班")
