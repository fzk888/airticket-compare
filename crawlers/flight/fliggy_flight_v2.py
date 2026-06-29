"""
飞猪机票 v2 网页爬虫。

v2 不依赖 FlyAI CLI，优先从飞猪网页渲染后的页面数据中解析多舱位价格，
找不到嵌入数据时退回到旧 PC 列表页最低价解析。

搬自 RideClawAPI app/clients/spiders/fliggy_flight_spider_v2.py。
改动：
- import 改为 crawlers.core / crawlers.flight 路径。
抓取逻辑零改动。
"""
import html as html_lib
import json
import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional

from crawlers.core.browser_base import FliggyBrowserMixin
from crawlers.flight.fliggy_flight import FliggyFlightSpider
from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)


class FliggyFlightSpiderV2(FliggyBrowserMixin):
    """飞猪机票 v2 爬虫 (DrissionPage 网页渲染 + 多舱位解析)。"""

    def __init__(self, headless: bool = True, cookie: Optional[str] = None):
        super().__init__()
        self.headless = headless
        self.cookie = cookie

    def search_flights(
        self,
        dep_city: str,
        arr_city: str,
        date: str,
        flight_number: Optional[str] = None,
        timeout: int = 60,
    ) -> List[Dict[str, Any]]:
        flights: List[Dict[str, Any]] = []
        start = time.time()
        try:
            user_dir_name = f"drission_fliggy_flight_v2_{os.getpid()}_{int(start * 1000)}"
            self._ensure_page(headless=self.headless, user_dir_name=user_dir_name)
            self._inject_cookies(cookie_str=self.cookie)

            url = (
                "https://sjipiao.fliggy.com/flight_search_result.htm"
                f"?tripType=0&depCity={dep_city}&arrCity={arr_city}"
                f"&depDate={date}&classType=0&adultNum=1&childNum=0&infantNum=0"
            )
            logger.info("飞猪 v2 搜索: %s", url)
            self.page.get(url)

            for _ in range(20):
                if time.time() - start > timeout - 2:
                    break
                time.sleep(0.75)
                html = self.page.html or ""
                if self._looks_loaded(html):
                    break

            html = self.page.html or ""
            logger.info("飞猪 v2 页面HTML长度: %d", len(html))
            flights = self._parse_html(html, flight_number=flight_number)

            if flight_number:
                expanded_flights = self._fetch_expanded_cabins_via_js(flight_number)
                if expanded_flights:
                    logger.info("飞猪 v2 展开目标航班舱位: %s 条", len(expanded_flights))
                    flights = expanded_flights

            if not flights:
                logger.info("飞猪 v2 未解析到嵌入多舱位数据，回退旧列表页解析")
                legacy_spider = FliggyFlightSpider(headless=self.headless, cookie=self.cookie)
                flights = legacy_spider._parse_html(html)
                if flight_number:
                    fn = flight_number.upper().strip()
                    flights = [
                        f for f in flights
                        if (f.get("flight_no") or f.get("flight_number") or "").upper().strip() == fn
                    ]
                for flight in flights:
                    flight["source"] = "fliggy_v2"
                    flight.setdefault("cabin_class", "Y")
                    flight.setdefault("cabin_name", "经济舱")

        except Exception as e:
            logger.error("飞猪 v2 搜索失败: %s", e, exc_info=True)

        logger.info("飞猪 v2 搜索完成, 耗时 %.1f秒, %d 条", time.time() - start, len(flights))
        return flights

    def _fetch_expanded_cabins_via_js(self, flight_number: str) -> List[Dict[str, Any]]:
        target_no = (flight_number or "").upper().strip()
        if not target_no or not self.page:
            return []

        try:
            clicked = self.page.run_js(f"""
                var targetNo = {target_no!r};
                var items = Array.prototype.slice.call(document.querySelectorAll('.J_FlightItem'));
                var target = items.find(function(item) {{
                    var flightName = item.querySelector('.J_TestFlight');
                    var text = flightName ? (flightName.textContent || '').trim().toUpperCase() : '';
                    return text.indexOf(targetNo) >= 0;
                }});
                if (!target) return false;
                var button = target.querySelector('.J_SelectFlight');
                if (!button) return false;
                button.click();
                return true;
            """)
            if not clicked:
                return []

            self._wait_for_agent_items(target_no)
            lowprice_rows = self._read_agent_items_via_js(target_no)

            try:
                self.page.run_js(f"""
                    var targetNo = {target_no!r};
                    var items = Array.prototype.slice.call(document.querySelectorAll('.J_FlightItem'));
                    var target = items.find(function(item) {{
                        var flightName = item.querySelector('.J_TestFlight');
                        var text = flightName ? (flightName.textContent || '').trim().toUpperCase() : '';
                        return text.indexOf(targetNo) >= 0;
                    }});
                    if (target) {{
                        var high = target.querySelector('.J_AgentType[data-agent-type="gaoduan"]');
                        if (high) high.click();
                    }}
                """)
                time.sleep(2.0)
            except Exception as e:
                logger.debug("飞猪 v2 切换高端舱位失败: %s", e)

            high_rows = self._read_agent_items_via_js(target_no)
            return self._rows_to_flights([*lowprice_rows, *high_rows], target_no)
        except Exception as e:
            logger.warning("飞猪 v2 展开舱位失败: flight=%s error=%s", target_no, e)
            return []

    def _wait_for_agent_items(self, target_no: str) -> None:
        for _ in range(12):
            try:
                count = self.page.run_js(f"""
                    var targetNo = {target_no!r};
                    var items = Array.prototype.slice.call(document.querySelectorAll('.J_FlightItem'));
                    var target = items.find(function(item) {{
                        var flightName = item.querySelector('.J_TestFlight');
                        var text = flightName ? (flightName.textContent || '').trim().toUpperCase() : '';
                        return text.indexOf(targetNo) >= 0;
                    }});
                    return target ? target.querySelectorAll('.J_AgentItem').length : 0;
                """)
                if count:
                    return
            except Exception:
                pass
            time.sleep(0.5)

    def _read_agent_items_via_js(self, target_no: str) -> List[Dict[str, Any]]:
        rows = self.page.run_js(f"""
            var targetNo = {target_no!r};

            function normText(node) {{
                return node ? ((node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ')) : '';
            }}

            function parsePrice(text) {{
                var match = (text || '').match(/[¥￥]?\\s*(\\d{{2,5}})/);
                return match ? (parseFloat(match[1]) || 0) : 0;
            }}

            function cabinTextFromNode(node) {{
                var direct = normText(node.querySelector('.cabin-tip, .cabin-no-tip, [class*="cabin"]'));
                if (direct && /头等|商务|公务|经济|舱/.test(direct)) return direct;

                var contentNodes = Array.prototype.slice.call(node.querySelectorAll('[data-content], [title], [aria-label]'));
                for (var i = 0; i < contentNodes.length; i++) {{
                    var content = contentNodes[i].getAttribute('data-content') || contentNodes[i].getAttribute('title') || contentNodes[i].getAttribute('aria-label') || '';
                    if (/头等|商务|公务|经济|舱/.test(content)) return content;
                }}

                var text = normText(node);
                var match = text.match(/((?:[A-Z舱位\\d\\.折全价\\s-]*)(?:头等|商务|公务|经济)舱)/);
                return match ? match[1].trim() : '';
            }}

            var items = Array.prototype.slice.call(document.querySelectorAll('.J_FlightItem'));
            var target = items.find(function(item) {{
                var flightName = item.querySelector('.J_TestFlight');
                var text = flightName ? (flightName.textContent || '').trim().toUpperCase() : '';
                return text.indexOf(targetNo) >= 0;
            }});
            if (!target) return [];

            var flightText = normText(target.querySelector('.J_TestFlight'));
            var taxText = normText(target);
            var depTime = normText(target.querySelector('.flight-time-deptime'));
            var arrTime = normText(target.querySelector('.s-time'));
            var depAirport = normText(target.querySelector('.port-dep'));
            var arrAirport = normText(target.querySelector('.port-arr'));
            var aircraft = normText(target.querySelector('.J_FlightType')) || normText(target.querySelector('[data-flight-type]'));

            return Array.prototype.slice.call(target.querySelectorAll('.J_AgentItem')).map(function(node) {{
                var priceText = normText(node.querySelector('.J_DisplayPrice')) || normText(node.querySelector('.pi-price')) || normText(node);
                var cabinText = cabinTextFromNode(node);
                return {{
                    flightText: flightText,
                    depTime: depTime,
                    arrTime: arrTime,
                    depAirport: depAirport,
                    arrAirport: arrAirport,
                    aircraft: aircraft,
                    price: parsePrice(priceText),
                    cabinText: cabinText,
                    taxText: taxText,
                    text: normText(node)
                }};
            }});
        """)
        return rows if isinstance(rows, list) else []

    def _rows_to_flights(self, rows: List[Dict[str, Any]], target_no: str) -> List[Dict[str, Any]]:
        flights: List[Dict[str, Any]] = []
        seen = set()
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            price_yuan = self._to_price_yuan(row.get("price"))
            if price_yuan <= 0:
                continue
            cabin_text = str(row.get("cabinText") or row.get("text") or "").strip()
            cabin_class = self._infer_cabin_class(cabin_text)
            cabin_name = self._extract_cabin_name(cabin_text) or self._cabin_name_from_class(cabin_class)
            tax_text = " ".join(
                str(row.get(key) or "")
                for key in ("text", "taxText", "flightText")
            )
            tax_components = self._extract_tax_components(tax_text)
            airport_tax = tax_components.get("airport_tax")
            oil_tax = tax_components.get("oil_tax")
            total = price_yuan + (airport_tax or 0.0) + (oil_tax or 0.0)
            key = (cabin_class, price_yuan)
            if key in seen:
                continue
            seen.add(key)
            flight_text = str(row.get("flightText") or "")
            airline = re.sub(r"[A-Z0-9]+", "", flight_text).strip()
            logger.info(
                "飞猪 v2 DOM 舱位价格: flight=%s cabin=%s base=%.2f airport_tax=%s oil_tax=%s total=%.2f tax_text=%s",
                target_no,
                cabin_class,
                price_yuan,
                airport_tax,
                oil_tax,
                total,
                tax_text[:160],
            )
            flights.append({
                "flight_no": target_no,
                "flight_number": target_no,
                "airline": airline,
                "dep_time": row.get("depTime") or "",
                "arr_time": row.get("arrTime") or "",
                "dep_airport": row.get("depAirport") or "",
                "arr_airport": row.get("arrAirport") or "",
                "aircraft": row.get("aircraft") or "",
                "base_fare": price_yuan,
                "price_yuan": total,
                "price": yuan_to_fen(total),
                "airport_tax": airport_tax,
                "oil_tax": oil_tax,
                "total": total,
                "total_price_yuan": total,
                "tax_supplemented": False,
                "cabin_class": cabin_class,
                "cabin_name": cabin_name,
                "booking_class": "",
                "source": "fliggy_v2",
            })
        flights.sort(key=lambda f: (self._cabin_order(f.get("cabin_class")), f.get("price_yuan", 0)))
        return flights

    def _parse_html(self, html: str, flight_number: Optional[str] = None) -> List[Dict[str, Any]]:
        flights: List[Dict[str, Any]] = []
        for data in self._extract_json_candidates(html):
            flights.extend(self._parse_data(data, flight_number=flight_number))

        seen = set()
        unique: List[Dict[str, Any]] = []
        for flight in flights:
            key = (
                flight.get("flight_no"),
                flight.get("cabin_class"),
                flight.get("booking_class"),
                flight.get("price_yuan"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(flight)
        unique.sort(key=lambda f: (f.get("flight_no") or "", self._cabin_order(f.get("cabin_class")), f.get("price_yuan", 0)))
        return unique

    def _parse_data(self, data: Any, flight_number: Optional[str] = None) -> List[Dict[str, Any]]:
        target = flight_number.upper().strip() if flight_number else None
        flights: List[Dict[str, Any]] = []
        seen = set()
        for item in self._iter_flight_items(data):
            base = self._extract_base_flight(item)
            flight_no = (base.get("flight_no") or "").upper().strip()
            if not flight_no:
                continue
            if target and flight_no != target:
                continue

            for cabin in self._extract_cabin_prices(item):
                row = {**base, **cabin}
                row["price"] = yuan_to_fen(row["price_yuan"])
                row["source"] = "fliggy_v2"
                dedupe_key = (
                    row.get("flight_no"),
                    row.get("cabin_class"),
                    row.get("booking_class"),
                    row.get("price_yuan"),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                flights.append(row)
        flights.sort(key=lambda f: (self._cabin_order(f.get("cabin_class")), f.get("price_yuan", 0)))
        return flights

    def _extract_json_candidates(self, html: str) -> List[Any]:
        candidates: List[Any] = []
        text = html_lib.unescape(html or "")

        for script in re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.DOTALL | re.IGNORECASE):
            if not self._contains_flight_price_hint(script):
                continue
            candidates.extend(self._loads_json_fragments(script))

        for attr in re.findall(r'(?:data-[\w-]+|value)=["\']([^"\']{20,})["\']', text):
            decoded = html_lib.unescape(attr)
            if self._contains_flight_price_hint(decoded):
                candidates.extend(self._loads_json_fragments(decoded))

        return candidates

    def _loads_json_fragments(self, text: str) -> List[Any]:
        values: List[Any] = []
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return [json.loads(stripped)]
            except json.JSONDecodeError:
                pass

        decoder = json.JSONDecoder()
        starts = [m.start() for m in re.finditer(r"[\[{]", text)]
        for start in starts:
            try:
                value, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if self._data_has_price_list(value):
                values.append(value)
        return values

    def _iter_flight_items(self, data: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(data, list):
            for item in data:
                yield from self._iter_flight_items(item)
            return
        if not isinstance(data, dict):
            return

        if self._is_flight_item(data):
            yield data

        for key in ("itemList", "flightList", "flights", "list", "items", "resultList"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    yield from self._iter_flight_items(item)

        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from self._iter_flight_items(value)

    def _extract_base_flight(self, item: Dict[str, Any]) -> Dict[str, Any]:
        segment = self._first_segment(item)
        last_segment = self._last_segment(item) or segment

        flight_no = self._first_text(
            segment, item,
            keys=("marketingTransportNo", "flightNo", "flight_no", "flightNumber", "flight_number", "transportNo"),
        )
        flight_no = self._normalize_flight_no(flight_no)

        dep_time = self._normalize_time(self._first_text(segment, item, keys=("depTime", "departTime", "depDateTime", "departDateTime")))
        arr_time = self._normalize_time(self._first_text(last_segment, item, keys=("arrTime", "arriveTime", "arrDateTime", "arriveDateTime")))

        return {
            "flight_no": flight_no,
            "flight_number": flight_no,
            "airline": self._first_text(segment, item, keys=("marketingTransportName", "airlineName", "airline", "carrierName")),
            "dep_time": dep_time,
            "arr_time": arr_time,
            "dep_airport": self._first_text(segment, item, keys=("depStationName", "depAirportName", "depAirport", "departAirport")),
            "arr_airport": self._first_text(last_segment, item, keys=("arrStationName", "arrAirportName", "arrAirport", "arriveAirport")),
            "aircraft": self._first_text(segment, item, keys=("transportName", "aircraft", "aircraftType", "planeType")),
        }

    def _extract_cabin_prices(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for key in (
            "cabinPriceList",
            "cabinPrices",
            "priceList",
            "fareList",
            "cabinFareList",
            "ticketPriceList",
            "agentList",
            "products",
            "productList",
        ):
            value = item.get(key)
            if isinstance(value, list):
                candidates.extend(v for v in value if isinstance(v, dict))

        for nested in self._nested_dicts(item):
            for key in ("cabinPriceList", "priceList", "fareList", "cabinFareList", "ticketPriceList"):
                value = nested.get(key)
                if isinstance(value, list):
                    candidates.extend(v for v in value if isinstance(v, dict))

        if not candidates:
            candidates = [item]

        rows: List[Dict[str, Any]] = []
        seen = set()
        for cabin in candidates:
            price_yuan = self._to_price_yuan(
                cabin.get("ticketPrice")
                or cabin.get("adultPrice")
                or cabin.get("price")
                or cabin.get("fare")
                or cabin.get("baseFare")
                or cabin.get("salePrice")
                or cabin.get("showPrice")
            )
            if price_yuan <= 0:
                continue

            cabin_name = self._first_text(cabin, keys=("seatClassName", "cabinName", "className", "seatType", "cabinInfo"))
            cabin_class = self._first_text(cabin, keys=("cabinClass", "cabin", "classCode", "seatClass", "seatClassCode"))
            if not cabin_class:
                cabin_class = self._infer_cabin_class(cabin_name)
            cabin_class = (cabin_class or "Y").upper()
            if cabin_class not in {"Y", "C", "F"}:
                cabin_class = self._infer_cabin_class(cabin_name)
            if not cabin_name:
                cabin_name = self._cabin_name_from_class(cabin_class)

            booking_class = self._first_text(cabin, keys=("bookingClass", "subCabinCode", "cabinCode", "subClass"))
            airport_tax = self._to_optional_price(
                cabin.get("airportTax")
                or cabin.get("airport_tax")
                or cabin.get("airportFee")
                or cabin.get("airportConstructionFee")
                or cabin.get("constructionFee")
            )
            oil_tax = self._to_optional_price(
                cabin.get("oilTax")
                or cabin.get("oil_tax")
                or cabin.get("fuelTax")
                or cabin.get("fuelSurcharge")
                or cabin.get("fuelFee")
            )
            combined_tax = self._to_optional_price(
                cabin.get("taxFee")
                or cabin.get("tax")
                or cabin.get("airportOilTax")
                or cabin.get("airportFuelTax")
            )
            if combined_tax is not None and airport_tax is None and oil_tax is None:
                airport_tax = combined_tax
                oil_tax = 0.0
            total = price_yuan + (airport_tax or 0.0) + (oil_tax or 0.0)
            key = (cabin_class, booking_class, price_yuan)
            if key in seen:
                continue
            seen.add(key)
            logger.info(
                "飞猪 v2 JSON 舱位价格: cabin=%s booking=%s base=%.2f airport_tax=%s oil_tax=%s total=%.2f",
                cabin_class,
                booking_class or "-",
                price_yuan,
                airport_tax,
                oil_tax,
                total,
            )
            rows.append({
                "base_fare": price_yuan,
                "price_yuan": total,
                "price": yuan_to_fen(total),
                "airport_tax": airport_tax,
                "oil_tax": oil_tax,
                "total": total,
                "total_price_yuan": total,
                "tax_supplemented": False,
                "cabin_class": cabin_class,
                "cabin_name": cabin_name,
                "booking_class": booking_class,
            })

        rows.sort(key=lambda row: (self._cabin_order(row["cabin_class"]), row["price_yuan"]))
        return rows

    @staticmethod
    def _first_text(*dicts: Dict[str, Any], keys: Iterable[str]) -> str:
        for data in dicts:
            if not isinstance(data, dict):
                continue
            for key in keys:
                value = data.get(key)
                if value not in (None, ""):
                    return str(value).strip()
        return ""

    @staticmethod
    def _normalize_flight_no(value: str) -> str:
        match = re.search(r"([A-Z0-9]{2}\d{3,4})", (value or "").upper())
        return match.group(1) if match else (value or "").upper().strip()

    @staticmethod
    def _normalize_time(value: str) -> str:
        text = str(value or "").strip()
        match = re.search(r"(\d{1,2}:\d{2})", text)
        return match.group(1) if match else text[:5]

    @staticmethod
    def _to_price_yuan(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").replace("¥", "").replace(",", "").strip()
        match = re.search(r"\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else 0.0

    @staticmethod
    def _to_optional_price(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        price = FliggyFlightSpiderV2._to_price_yuan(value)
        return price if price >= 0 else None

    @staticmethod
    def _infer_cabin_class(cabin_name: str) -> str:
        if "头等" in cabin_name:
            return "F"
        if "商务" in cabin_name or "公务" in cabin_name:
            return "C"
        return "Y"

    @staticmethod
    def _extract_cabin_name(text: str) -> str:
        match = re.search(r"((?:头等|商务|公务|经济)舱)", text or "")
        if not match:
            return ""
        name = match.group(1)
        return "商务舱" if name == "公务舱" else name

    @staticmethod
    def _extract_tax_components(text: str) -> Dict[str, Optional[float]]:
        text = str(text or "").replace(",", "")

        def amount_after(patterns: Iterable[str]) -> Optional[float]:
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return float(match.group(1))
            return None

        combined = amount_after((
            r"(?:机建\s*[+＋]\s*燃油|机建燃油)[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}(?:机建\s*[+＋]\s*燃油|机建燃油)",
        ))
        airport_tax = amount_after((
            r"(?:机建|机场建设|民航发展基金)[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}(?:机建|机场建设|民航发展基金)",
        ))
        oil_tax = amount_after((
            r"燃油[^\d¥￥]{0,8}[¥￥]?\s*(\d{1,4})",
            r"[¥￥]?\s*(\d{1,4})[^\d¥￥]{0,8}燃油",
        ))

        if combined is not None:
            return {
                "airport_tax": combined,
                "oil_tax": 0.0,
            }
        if airport_tax is not None or oil_tax is not None:
            return {
                "airport_tax": (airport_tax or 0.0) + (oil_tax or 0.0),
                "oil_tax": 0.0,
            }

        return {
            "airport_tax": None,
            "oil_tax": None,
        }

    @staticmethod
    def _cabin_name_from_class(cabin_class: str) -> str:
        code = (cabin_class or "").upper()
        if code == "F":
            return "头等舱"
        if code == "C":
            return "商务舱"
        return "经济舱"

    @staticmethod
    def _cabin_order(cabin_class: Any) -> int:
        return {"Y": 0, "C": 1, "F": 2}.get(str(cabin_class or "Y").upper(), 9)

    @staticmethod
    def _contains_flight_price_hint(text: str) -> bool:
        return any(key in text for key in ("cabinPriceList", "cabinFareList", "ticketPriceList", "priceList", "flightNo", "flight_number"))

    def _data_has_price_list(self, value: Any) -> bool:
        if isinstance(value, dict):
            if any(key in value for key in ("cabinPriceList", "cabinFareList", "ticketPriceList", "priceList")):
                return True
            return any(self._data_has_price_list(v) for v in value.values())
        if isinstance(value, list):
            return any(self._data_has_price_list(v) for v in value)
        return False

    def _is_flight_item(self, value: Dict[str, Any]) -> bool:
        has_flight_no = any(value.get(key) for key in ("flightNo", "flight_no", "flightNumber", "flight_number", "transportNo"))
        has_price = self._data_has_price_list(value) or any(value.get(key) for key in ("ticketPrice", "adultPrice", "price", "salePrice"))
        if has_flight_no and has_price:
            return True
        segment = self._first_segment(value)
        return bool(segment and self._extract_base_flight(value).get("flight_no") and has_price)

    @staticmethod
    def _nested_dicts(value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from FliggyFlightSpiderV2._nested_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from FliggyFlightSpiderV2._nested_dicts(child)

    @staticmethod
    def _first_segment(item: Dict[str, Any]) -> Dict[str, Any]:
        journeys = item.get("journeys") or item.get("journeyList") or []
        if isinstance(journeys, list) and journeys:
            segments = journeys[0].get("segments") if isinstance(journeys[0], dict) else None
            if isinstance(segments, list) and segments and isinstance(segments[0], dict):
                return segments[0]
        segments = item.get("segments") or item.get("segmentList") or []
        if isinstance(segments, list) and segments and isinstance(segments[0], dict):
            return segments[0]
        return {}

    @staticmethod
    def _last_segment(item: Dict[str, Any]) -> Dict[str, Any]:
        journeys = item.get("journeys") or item.get("journeyList") or []
        if isinstance(journeys, list) and journeys:
            segments = journeys[0].get("segments") if isinstance(journeys[0], dict) else None
            if isinstance(segments, list) and segments and isinstance(segments[-1], dict):
                return segments[-1]
        segments = item.get("segments") or item.get("segmentList") or []
        if isinstance(segments, list) and segments and isinstance(segments[-1], dict):
            return segments[-1]
        return {}

    @staticmethod
    def _looks_loaded(html: str) -> bool:
        return any(key in html for key in ("flight-list-item", "J_FlightItem", "J_FlightListPrice", "cabinPriceList"))

    def close(self):
        self._close_page()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
