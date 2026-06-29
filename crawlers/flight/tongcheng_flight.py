"""
同程旅行机票爬虫 - DrissionPage headless + Vue DOM 解析

同程机票搜索走 www.ly.com/flights/itinerary/oneway（Vue CSR），需等待渲染后解析DOM。
- 容器: .flight-item
- 航班名: .flight-item-name → 中国联合航空KN5978
- 出发时间: .f-startTime strong → 08:15
- 出发机场: .f-startTime em → 浦东机场T1
- 到达时间: .f-endTime strong → 10:25
- 到达机场: .f-endTime em → 大兴机场
- 飞行时长: .f-line-to i → 2h10m
- 价格: .head-prices strong em → ¥400
- 舱位信息: .head-prices i → 2.5折经济舱

搬自 RideClawAPI app/clients/spiders/tongcheng_flight_spider.py。
改动：
- import 改为 crawlers.core 路径。
抓取逻辑零改动。
"""
import re
import time
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import quote

from crawlers.core.browser_base import FliggyBrowserMixin, parse_browser_cookies
from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)


class TongchengFlightSpider(FliggyBrowserMixin):
    """同程旅行机票爬虫 (DrissionPage + Vue DOM 解析)"""

    BASE_URL = "https://www.ly.com/flights/itinerary/oneway"

    def __init__(self, headless: bool = True, cookie: Optional[str] = None):
        super().__init__()
        self.headless = headless
        self.cookie = cookie

    def search_flights(
        self,
        from_code: str,
        to_code: str,
        flight_date: str,
        from_city: str,
        to_city: str,
        flight_number: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索航班

        Args:
            from_code: 出发城市三字码 (如 SHA)
            to_code: 到达城市三字码 (如 PEK)
            flight_date: 出发日期 YYYY-MM-DD
            from_city: 出发城市中文名 (如 上海)
            to_city: 到达城市中文名 (如 北京)
            flight_number: 可选航班号。提供时会优先展开目标航班，抓取下拉舱位产品。

        Returns:
            航班列表
        """
        try:
            start = time.time()
            self._ensure_page(headless=self.headless, user_dir_name='drission_tongcheng_flight')

            # 注入 Cookie（CDP方式）
            self._inject_cookies_for_domain(cookie_str=self.cookie, domain='.ly.com')

            # 构造 URL
            url = (
                f"{self.BASE_URL}/{from_code}-{to_code}"
                f"?date={flight_date}"
                f"&from={quote(from_city)}"
                f"&to={quote(to_city)}"
                f"&fromairport=&toairport=&p=&childticket=0,0"
            )
            logger.info("同程机票搜索: %s->%s %s", from_city, to_city, flight_date)
            self.page.get(url)

            # 等待 Vue 渲染完成（等待航班列表出现）
            loaded = False
            for i in range(24):
                wait = min(0.5 * (i + 1), 2.0)
                time.sleep(wait)
                try:
                    if self.page.ele('css:.flight-item', timeout=0.3):
                        logger.info("同程机票页面加载完成, 耗时 %.1fs", time.time() - start)
                        loaded = True
                        break
                except Exception:
                    pass
            if not loaded:
                logger.warning("等待同程机票元素超时，用已加载的HTML解析")

            # 用 JS 直接读取 DOM 中的航班数据
            flights = self._fetch_flights_via_js(flight_number=flight_number)
            logger.info("解析到 %d 条同程机票", len(flights))

            if loaded and len(flights) < 3:
                logger.warning(
                    "⚠️ 同程机票解析数量异常: 仅 %d 条，可能DOM结构变更",
                    len(flights),
                )
            return flights

        except Exception as e:
            logger.error("同程机票搜索失败: %s", e, exc_info=True)
            return []

    def _inject_cookies_for_domain(self, cookie_str: Optional[str], domain: str = '.ly.com'):
        """为同程域名注入 Cookie（CDP 直接注入）"""
        if not cookie_str:
            return
        try:
            # 先导航到 about:blank，避免旧页面干扰
            try:
                self.page.get("about:blank")
            except Exception:
                pass

            ly_domains = ['.ly.com', '.www.ly.com', 'www.ly.com', '.elongstatic.com', '.40017.cn']
            count = 0
            for cookie in parse_browser_cookies(cookie_str, ly_domains):
                domains = [cookie.get("domain")] if cookie.get("domain") else ly_domains
                for d in domains:
                    try:
                        kwargs = {
                            'name': cookie['name'],
                            'value': cookie['value'],
                            'domain': d,
                            'path': cookie.get('path') or '/',
                        }
                        if cookie.get('secure') is not None:
                            kwargs['secure'] = cookie['secure']
                        if cookie.get('httpOnly') is not None:
                            kwargs['httpOnly'] = cookie['httpOnly']
                        self.page.run_cdp(
                            'Network.setCookie',
                            **kwargs,
                        )
                    except Exception:
                        pass
                count += 1
            logger.info("同程 Cookie 注入完成 (CDP), %d 个 → %s", count, ly_domains)
        except Exception as e:
            logger.warning("同程 Cookie 注入失败: %s", e)

    def _fetch_flights_via_js(self, flight_number: Optional[str] = None) -> List[Dict[str, Any]]:
        """通过 JS 直接读取 DOM 中的航班数据"""
        try:
            target_no = (flight_number or "").upper().strip()
            if target_no:
                try:
                    self.page.run_js(f"""
                        var targetNo = {target_no!r};
                        var items = Array.prototype.slice.call(document.querySelectorAll('.flight-item'));
                        var target = items.find(function(item) {{
                            var flightName = item.querySelector('.flight-item-name');
                            var text = flightName ? flightName.textContent.trim().toUpperCase() : '';
                            return text.indexOf(targetNo) >= 0;
                        }});
                        if (target) {{
                            var button = target.querySelector('.btn-select, .btn-submit, button, [class*="select"], [class*="book"]');
                            if (button) button.click();
                        }}
                    """)
                    time.sleep(2.0)
                    clicked_more = self._expand_more_cabin_rows()
                    if clicked_more:
                        logger.info("同程目标航班舱位加载更多: clicked=%d", clicked_more)
                except Exception as e:
                    logger.warning("展开同程目标航班舱位失败: flight=%s error=%s", target_no, e)

            result = self.page.run_js(f"""
                var targetNo = {target_no!r};

                function normText(node) {{
                    return node ? ((node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ')) : '';
                }}

                function parsePrice(text) {{
                    var match = (text || '').match(/[¥￥]?\\s*(\\d{{2,5}})/);
                    return match ? (parseFloat(match[1]) || 0) : 0;
                }}

                function cabinTextFromNode(node) {{
                    var cabinNode = node.querySelector('.gray-style, [class*="cabin"], [class*="seat"], [class*="service"]');
                    var cabinText = normText(cabinNode);
                    if (cabinText && /舱|商务|公务|头等|经济|折扣|折/.test(cabinText)) return cabinText;

                    var priceNode = node.querySelector('.price-show, [class*="price"]');
                    var text = normText(node);
                    if (priceNode) {{
                        text = text.replace(normText(priceNode), ' ');
                    }}
                    text = text.replace(/[¥￥]?\\s*\\d{{2,5}}\\s*(起)?/g, ' ');
                    text = text.replace(/退改|预订|订|提供行程单|免费托运行李额\\d+KG|免费托运行李额|无餐食/g, ' ');
                    var match = text.match(/([^\\s]*?(?:头等|商务|公务|经济)舱|\\d+(?:\\.\\d+)?折[^\\s]*(?:折扣)?|全价[^\\s]*)/);
                    return match ? match[1].trim() : text.trim();
                }}

                function dropdownCabinsForTarget() {{
                    var rows = [];
                    if (!targetNo) return rows;

                    document.querySelectorAll('.cabins-item, [class*="cabins-item"], [class*="cabin-item"], [class*="cabinItem"], [class*="product-item"], [class*="price-item"]').forEach(function(node) {{
                        var text = normText(node);
                        var priceNode = node.querySelector('.price-show, [class*="price"]');
                        var priceText = normText(priceNode) || text;
                        var price = parsePrice(priceText);
                        var cabinText = cabinTextFromNode(node);
                        if (!price || !/舱|商务|公务|头等|经济|折扣|折|全价/.test(cabinText || text)) return;
                        rows.push({{
                            price: price,
                            priceText: priceText,
                            cabinText: cabinText,
                            text: text
                        }});
                    }});

                    return rows;
                }}

                function extractBookingTax(scope) {{
                    var text = normText(scope || document);
                    if (!text) return null;

                    function amountAfter(patterns) {{
                        for (var i = 0; i < patterns.length; i++) {{
                            var match = text.match(patterns[i]);
                            if (match) return parseFloat(match[1]) || 0;
                        }}
                        return null;
                    }}

                    var combined = amountAfter([
                        /(?:机建\\s*[+＋]\\s*燃油|机建燃油)[^¥￥\\d]{{0,8}}[¥￥]?\\s*(\\d{{1,4}})/,
                        /[¥￥]?\\s*(\\d{{1,4}})[^¥￥\\d]{{0,8}}(?:机建\\s*[+＋]\\s*燃油|机建燃油)/
                    ]);
                    var airportTax = amountAfter([
                        /(?:机建|机场建设|民航发展基金)[^¥￥\\d]{{0,8}}[¥￥]?\\s*(\\d{{1,4}})/,
                        /[¥￥]?\\s*(\\d{{1,4}})[^¥￥\\d]{{0,8}}(?:机建|机场建设|民航发展基金)/
                    ]);
                    var oilTax = amountAfter([
                        /燃油[^¥￥\\d]{{0,8}}[¥￥]?\\s*(\\d{{1,4}})/,
                        /[¥￥]?\\s*(\\d{{1,4}})[^¥￥\\d]{{0,8}}燃油/
                    ]);

                    if (combined !== null) {{
                        if (airportTax === null || airportTax === combined) airportTax = 50;
                        if (oilTax === null || oilTax === combined) oilTax = Math.max(combined - airportTax, 0);
                    }}
                    if (airportTax === null && oilTax === null) return null;
                    return {{
                        airport_tax: airportTax,
                        oil_tax: oilTax
                    }};
                }}

                var expandedCabinItems = dropdownCabinsForTarget();
                var items = document.querySelectorAll('.flight-item');
                var flights = [];
                items.forEach(function(item) {{
                    var flightName = item.querySelector('.flight-item-name');
                    var flightNameText = flightName ? flightName.textContent.trim() : '';
                    if (targetNo && flightNameText.toUpperCase().indexOf(targetNo) < 0) return;
                    var depTime = item.querySelector('.f-startTime strong');
                    var arrTime = item.querySelector('.f-endTime strong');
                    var depAirport = item.querySelector('.f-startTime em');
                    var arrAirport = item.querySelector('.f-endTime em');
                    var duration = item.querySelector('.f-line-to i');
                    var priceEl = item.querySelector('.head-prices strong em');
                    var cabinInfo = item.querySelector('.head-prices i');
                    var aircraft = item.querySelector('.flight-item-type');

                    if (!flightName) return;

                    var price = 0;
                    if (priceEl) {{
                        var priceText = priceEl.textContent.trim().replace(/[¥￥,]/g, '');
                        price = parseFloat(priceText) || 0;
                    }}
                    var cabinPrices = [];
                    item.querySelectorAll('.head-prices, [class*="price"], [class*="cabin"], [class*="seat"], [class*="product"]').forEach(function(priceNode) {{
                        var text = (priceNode.innerText || priceNode.textContent || '').trim();
                        if (!text) return;
                        var match = text.match(/[¥￥]?\\s*(\\d{{2,5}})/);
                        if (!match) return;
                        if (!/舱|商务|公务|头等|经济|折扣|折|全价/.test(text)) return;
                        cabinPrices.push({{
                            price: parseFloat(match[1]) || 0,
                            cabinInfo: text.replace(/\\s+/g, ' ')
                        }});
                    }});

                    flights.push({{
                        flightName: flightNameText,
                        depTime: depTime ? depTime.textContent.trim() : '',
                        arrTime: arrTime ? arrTime.textContent.trim() : '',
                        depAirport: depAirport ? depAirport.textContent.trim() : '',
                        arrAirport: arrAirport ? arrAirport.textContent.trim() : '',
                        duration: duration ? duration.textContent.trim() : '',
                        price: price,
                        cabinInfo: cabinInfo ? cabinInfo.textContent.trim() : '',
                        cabinPrices: cabinPrices,
                        expandedCabinItems: targetNo ? expandedCabinItems : [],
                        bookingTax: extractBookingTax(document),
                        aircraft: aircraft ? aircraft.textContent.trim() : '',
                    }});
                }});
                return JSON.stringify(flights);
            """)
            if result:
                import json
                raw = json.loads(result)
                booking_tax = None
                if target_no and raw:
                    booking_tax = self._fetch_booking_tax_for_target(target_no)
                flights: List[Dict[str, Any]] = []
                for row in raw:
                    if booking_tax:
                        row["bookingTax"] = booking_tax
                    flights.extend(self._parse_flight_card(row))
                return flights
        except Exception as e:
            logger.warning("JS 获取航班失败: %s", e)
        return []

    def _fetch_booking_tax_for_target(self, target_no: str) -> Optional[Dict[str, float]]:
        """进入目标航班最低经济舱预订页，抓取真实机建/燃油费。"""
        if not target_no:
            return None
        try:
            current_url = getattr(self.page, "url", "")
            clicked = self.page.run_js(f"""
                var targetNo = {target_no!r};
                function normText(node) {{
                    return node ? ((node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ')) : '';
                }}
                function parsePrice(text) {{
                    var match = (text || '').match(/[¥￥]?\\s*(\\d{{2,5}})/);
                    return match ? (parseFloat(match[1]) || 0) : 0;
                }}
                var rows = Array.prototype.slice.call(document.querySelectorAll(
                    '.cabins-item, [class*="cabins-item"], [class*="cabin-item"], [class*="cabinItem"], [class*="product-item"], [class*="price-item"]'
                )).filter(function(node) {{
                    var text = normText(node);
                    return text && /经济舱|折|全价/.test(text) && parsePrice(text) > 0;
                }});
                rows.sort(function(a, b) {{ return parsePrice(normText(a)) - parsePrice(normText(b)); }});
                var row = rows[0];
                if (!row) {{
                    var items = Array.prototype.slice.call(document.querySelectorAll('.flight-item'));
                    var target = items.find(function(item) {{
                        var flightName = item.querySelector('.flight-item-name');
                        var text = flightName ? flightName.textContent.trim().toUpperCase() : '';
                        return text.indexOf(targetNo) >= 0;
                    }});
                    row = target || null;
                }}
                if (!row) return false;
                function isVisible(node) {{
                    var style = window.getComputedStyle(node);
                    var rect = node.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                }}
                function actionText(node) {{
                    return /预订|订|选择|选购/.test(normText(node));
                }}
                var buttons = Array.prototype.slice.call(row.querySelectorAll(
                    'button, a, [role="button"], [class*="book"], [class*="Book"], [class*="select"], [class*="Select"], [class*="submit"], [class*="Submit"], [class*="btn"], [class*="Btn"], [class*="order"], [class*="Order"]'
                ));
                var candidates = buttons.filter(function(btn) {{
                    var text = normText(btn);
                    if (!text || !/预订|订|选择|选购/.test(text) || !isVisible(btn)) return false;
                    var childHasAction = Array.prototype.slice.call(btn.children || []).some(actionText);
                    return !childHasAction && text.length <= 12;
                }});
                candidates.sort(function(a, b) {{
                    var at = normText(a);
                    var bt = normText(b);
                    var aExact = /^(预订|订|选择|选购)$/.test(at) ? 0 : 1;
                    var bExact = /^(预订|订|选择|选购)$/.test(bt) ? 0 : 1;
                    if (aExact !== bExact) return aExact - bExact;
                    return at.length - bt.length;
                }});
                var button = candidates[0];
                if (!button) return false;
                var action = button.closest('button, a, [role="button"], [class*="book"], [class*="Book"], [class*="select"], [class*="Select"], [class*="submit"], [class*="Submit"], [class*="btn"], [class*="Btn"], [class*="order"], [class*="Order"]') || button;
                action.scrollIntoView({{block: 'center', inline: 'center'}});
                ['mouseover', 'mousedown', 'mouseup', 'click'].forEach(function(type) {{
                    action.dispatchEvent(new MouseEvent(type, {{bubbles: true, cancelable: true, view: window}}));
                }});
                if (typeof action.click === 'function') action.click();
                return true;
            """)
            if not clicked:
                logger.info("同程预订页税费: flight=%s 未找到可点击预订按钮", target_no)
                return None
            time.sleep(3.0)
            logger.info("同程预订页税费: flight=%s click 后 URL=%s", target_no, getattr(self.page, "url", ""))
            tax_text = self.page.run_js("""
                function normText(node) {
                    return node ? ((node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ')) : '';
                }
                return normText(document.body);
            """)
            tax = self._extract_tax_components(tax_text)
            if tax.get("airport_tax") is not None or tax.get("oil_tax") is not None:
                logger.info(
                    "同程预订页税费: flight=%s airport=%s oil=%s",
                    target_no,
                    tax.get("airport_tax"),
                    tax.get("oil_tax"),
                )
                if current_url:
                    try:
                        self.page.get(current_url)
                        time.sleep(1.0)
                    except Exception:
                        pass
                return tax
            logger.info(
                "同程预订页税费: flight=%s 未识别到税费，文本片段=%s",
                target_no,
                str(tax_text or "")[:300],
            )
            if current_url:
                try:
                    self.page.get(current_url)
                    time.sleep(1.0)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("同程预订页税费抓取失败: flight=%s error=%s", target_no, e)
        return None

    def _expand_more_cabin_rows(self, max_clicks: int = 8, wait_seconds: float = 0.8) -> int:
        """点击目标航班舱位列表中的“加载更多”，直到没有更多产品。"""
        clicked = 0
        for _ in range(max_clicks):
            try:
                did_click = self.page.run_js("""
                    function normText(node) {
                        return node ? ((node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ')) : '';
                    }
                    var lists = Array.prototype.slice.call(document.querySelectorAll('.flight-item-cabins-lists, [class*="cabins-lists"], [class*="cabin-list"], [class*="cabinList"]'));
                    var scopes = lists.length ? lists : [document.body];
                    for (var i = 0; i < scopes.length; i++) {
                        var scope = scopes[i];
                        var nodes = Array.prototype.slice.call(scope.querySelectorAll('button, a, span, div, i, em, [class*="more"], [class*="load"]'));
                        var candidates = nodes.filter(function(node) {
                            var text = normText(node);
                            if (!text || !/加载更多|更多/.test(text)) return false;
                            if (/没有更多|暂无更多|收起/.test(text)) return false;
                            var style = window.getComputedStyle(node);
                            var rect = node.getBoundingClientRect();
                            var childHasSameText = Array.prototype.slice.call(node.children || []).some(function(child) {
                                return /加载更多|更多/.test(normText(child));
                            });
                            return !childHasSameText
                                && text.length <= 12
                                && style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && rect.width > 0
                                && rect.height > 0;
                        });
                        candidates.sort(function(a, b) {
                            return normText(a).length - normText(b).length;
                        });
                        var target = candidates[0];
                        if (target) {
                            target.scrollIntoView({block: 'center', inline: 'center'});
                            ['mouseover', 'mousedown', 'mouseup', 'click'].forEach(function(type) {
                                target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                            });
                            return true;
                        }
                    }
                    return false;
                """)
            except Exception as e:
                logger.debug("同程舱位加载更多点击失败: %s", e)
                break
            if not did_click:
                break
            clicked += 1
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        return clicked

    def _parse_flight(self, raw: dict) -> Dict[str, Any]:
        """解析单个航班数据"""
        flights = self._parse_flight_card(raw)
        return flights[0] if flights else {}

    def _parse_flight_card(self, raw: dict) -> List[Dict[str, Any]]:
        """解析单个航班卡片，保留卡片中能识别出的多个舱位价格。"""
        flight_name = raw.get('flightName', '')
        airline, flight_no = self._parse_flight_name(flight_name)

        cabin_prices = self._extract_expanded_cabin_prices(raw)
        has_expanded_cabin_prices = bool(cabin_prices)
        if not cabin_prices:
            cabin_prices = raw.get('cabinPrices') or []

        headline_price = self._parse_price_yuan(raw.get('price'))
        headline_cabin_info = str(raw.get('cabinInfo') or '').strip()
        if headline_price > 0 and not has_expanded_cabin_prices:
            headline = {
                "price": headline_price,
                "cabinInfo": headline_cabin_info,
            }
            if not any(
                self._parse_price_yuan(item.get("price")) == headline_price
                and (item.get("cabinInfo") or "") == headline_cabin_info
                for item in cabin_prices
                if isinstance(item, dict)
            ):
                cabin_prices.insert(0, headline)

        if not cabin_prices:
            cabin_prices = [{
                "price": raw.get('price', 0.0),
                "cabinInfo": raw.get('cabinInfo', ''),
            }]

        flights: List[Dict[str, Any]] = []
        seen = set()
        booking_tax = self._normalize_booking_tax(raw.get('bookingTax'))
        for cabin in cabin_prices:
            if not isinstance(cabin, dict):
                continue
            try:
                price_yuan = float(cabin.get('price') or 0)
            except (TypeError, ValueError):
                price_yuan = 0.0
            if price_yuan <= 0:
                continue
            cabin_info = str(cabin.get('cabinInfo') or raw.get('cabinInfo') or '').strip()
            cabin_name = self._parse_cabin_name(cabin_info)
            cabin_class = self._cabin_class_from_name(cabin_name)
            dedupe_key = (flight_no, cabin_class, price_yuan)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            flight = {
                'flight_no': flight_no,
                'airline': airline,
                'dep_time': raw.get('depTime', ''),
                'arr_time': raw.get('arrTime', ''),
                'dep_airport': raw.get('depAirport', ''),
                'arr_airport': raw.get('arrAirport', ''),
                'duration': raw.get('duration', ''),
                'base_fare': price_yuan,
                'price_yuan': price_yuan,
                'price': yuan_to_fen(price_yuan),
                'cabin_info': cabin_info,
                'cabin_class': cabin_class,
                'cabin_name': cabin_name,
                'aircraft': raw.get('aircraft', ''),
                'source': 'tongcheng',
            }
            if booking_tax:
                airport_tax = booking_tax.get('airport_tax')
                oil_tax = booking_tax.get('oil_tax')
                service_fee = booking_tax.get('service_fee', 0.0)
                total = price_yuan + (airport_tax or 0.0) + (oil_tax or 0.0) + (service_fee or 0.0)
                flight.update({
                    'airport_tax': airport_tax,
                    'oil_tax': oil_tax,
                    'service_fee': service_fee,
                    'total': total,
                    'total_price_yuan': total,
                    'price_yuan': total,
                    'price': yuan_to_fen(total),
                    'tax_supplemented': False,
                })
            flights.append(flight)
        return flights

    @staticmethod
    def _normalize_booking_tax(value: Any) -> Optional[Dict[str, float]]:
        if not isinstance(value, dict):
            return None

        def to_float(raw: Any) -> Optional[float]:
            if raw in (None, ''):
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        airport_tax = to_float(value.get('airport_tax') or value.get('airportTax'))
        oil_tax = to_float(value.get('oil_tax') or value.get('oilTax'))
        service_fee = to_float(value.get('service_fee') or value.get('serviceFee')) or 0.0
        if airport_tax is None and oil_tax is None:
            return None
        return {
            'airport_tax': airport_tax,
            'oil_tax': oil_tax,
            'service_fee': service_fee,
        }

    @staticmethod
    def _extract_tax_components(text: str) -> Dict[str, Optional[float]]:
        text = str(text or "").replace(",", "")

        def amount_after(patterns: List[str]) -> Optional[float]:
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return float(match.group(1))
            return None

        combined = amount_after([
            r"(?:机建\s*[+＋]\s*燃油|机建燃油)[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}(?:机建\s*[+＋]\s*燃油|机建燃油)",
        ])
        airport_tax = amount_after([
            r"(?:机建|机场建设|民航发展基金)[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}(?:机建|机场建设|民航发展基金)",
        ])
        oil_tax = amount_after([
            r"燃油[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}燃油",
        ])

        if combined is not None:
            if airport_tax is None or airport_tax == combined:
                airport_tax = 50.0
            if oil_tax is None or oil_tax == combined:
                oil_tax = max(combined - airport_tax, 0.0)

        return {
            'airport_tax': airport_tax,
            'oil_tax': oil_tax,
        }

    @staticmethod
    def _extract_expanded_cabin_prices(raw: dict) -> List[Dict[str, Any]]:
        """解析点击目标航班后出现的 .cabins-item 产品价格。"""
        expanded_items = raw.get('expandedCabinItems') or []
        cabin_prices: List[Dict[str, Any]] = []
        for item in expanded_items:
            if not isinstance(item, dict):
                continue
            price_value = item.get('price') or item.get('priceText') or item.get('text')
            price = TongchengFlightSpider._parse_price_yuan(price_value)
            if price <= 0:
                continue
            cabin_text = str(item.get('cabinText') or item.get('text') or '')
            cabin_info = (
                TongchengFlightSpider._extract_cabin_info_from_text(cabin_text)
                or str(item.get('cabinText') or raw.get('cabinInfo') or '').strip()
            )
            if not cabin_info:
                continue
            cabin_prices.append({
                "price": price,
                "cabinInfo": cabin_info,
            })
        return cabin_prices

    @staticmethod
    def _parse_price_yuan(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").replace(',', '').replace('，', '')
        match = re.search(r'[¥￥]?\s*(\d+(?:\.\d+)?)', text)
        return float(match.group(1)) if match else 0.0

    @staticmethod
    def _extract_cabin_info_from_text(text: str) -> str:
        match = re.search(r'((?:\d+(?:\.\d+)?折|全价)?(?:头等|商务|公务|经济)舱)', text or '')
        if match:
            return match.group(1).strip()
        discount_match = re.search(r'(\d+(?:\.\d+)?折[^¥￥\s]*(?:折扣)?|全价[^¥￥\s]*)', text or '')
        return discount_match.group(1).strip() if discount_match else ''

    @staticmethod
    def _parse_cabin_name(cabin_info: str) -> str:
        match = re.search(r'(头等|商务|公务|经济)舱', cabin_info or '')
        if match:
            return f"{match.group(1)}舱"
        if re.search(r'折扣|超值|折|全价', cabin_info or ''):
            return '经济舱'
        return cabin_info or ''

    @staticmethod
    def _cabin_class_from_name(cabin_name: str) -> str:
        if '头等' in cabin_name:
            return 'F'
        if '商务' in cabin_name or '公务' in cabin_name:
            return 'C'
        return 'Y'

    @staticmethod
    def _parse_flight_name(name: str) -> tuple:
        """解析航班名 → (airline, flight_no)

        例: '中国联合航空KN5978' → ('中国联合航空', 'KN5978')
        """
        match = re.search(r'^(.+?)([A-Z0-9]{2}\d{3,4})$', name)
        if match:
            return match.group(1).strip(), match.group(2)
        return '', name

    def close(self):
        self._close_page()
