"""
同程旅行酒店爬虫 - DrissionPage headless + Vue DOM 解析

同程酒店搜索走 www.ly.com/hotel/hotellist（Vue CSR），需等待渲染后解析DOM。
- 容器: a[href*="hoteldetail"] 包裹 li
- 酒店名: dd 元素
- 星级/类型: span > em（名称行第一个 em）
- 评分: .commentScore div
- 评价数: 评分行第二个 em（如 "7110条点评"）
- 价格: .discountPrice（需 cookie 登录，通过 JS 读取异步加载的 DOM）
- 图片: img src
- 酒店ID: href 中 hotelId=(数字)
搬自 RideClawAPI app/clients/spiders/tongcheng_hotel_spider.py。
改动：
- import 改为 crawlers.core 路径。
抓取逻辑（含城市ID映射）零改动。
"""
import re
import time
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import quote

from crawlers.core.browser_base import FliggyBrowserMixin, parse_browser_cookies
from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)

# 同程城市ID映射（中文城市名 → 城市ID）
TONGCHENG_CITY_IDS: Dict[str, int] = {
    "北京": 53, "上海": 321, "广州": 80, "深圳": 91, "南京": 224,
    "杭州": 383, "成都": 324, "厦门": 61, "青岛": 292, "三亚": 133,
    "苏州": 226, "西安": 317, "长沙": 199, "贵阳": 114, "桂林": 102,
    "佛山": 79, "天津": 343, "宁波": 388, "武汉": 192, "合肥": 42,
    "郑州": 163, "南昌": 239, "重庆": 394, "昆明": 177, "大连": 64,
    "沈阳": 310, "哈尔滨": 116, "长春": 56, "济南": 155, "福州": 77,
    "南宁": 241, "海口": 117, "乌鲁木齐": 349, "兰州": 183, "银川": 374,
    "西宁": 316, "呼和浩特": 140, "太原": 336, "石家庄": 313, "南通": 243,
    "无锡": 352, "常州": 57, "温州": 356, "嘉兴": 153, "绍兴": 308,
    "台州": 335, "金华": 157, "扬州": 376, "镇江": 393, "徐州": 369,
    "烟台": 373, "威海": 353, "潍坊": 354, "淄博": 395, "东莞": 67,
    "珠海": 392, "中山": 391, "惠州": 143, "汕头": 302, "湛江": 382,
    "珠海": 392, "丽江": 186, "张家界": 381, "黄山": 144, "九寨沟": 159,
}

TONGCHENG_COOKIE_FILE = None  # 由服务层传入


class TongchengHotelSpider(FliggyBrowserMixin):
    """同程旅行酒店爬虫 (DrissionPage + Vue DOM 解析)"""

    BASE_URL = "https://www.ly.com/hotel/hotellist"

    def __init__(self, headless: bool = True, cookie: Optional[str] = None):
        super().__init__()
        self.headless = headless
        self.cookie = cookie

    def search_hotels(
        self,
        city_name: str,
        checkin: str,
        checkout: str,
        hotel_name: Optional[str] = None,
        current_room_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索酒店

        Args:
            city_name: 城市中文名（如"北京"、"上海"）
            checkin: 入住日期 YYYY-MM-DD
            checkout: 离店日期 YYYY-MM-DD
            hotel_name: 酒店名称关键词（可选）

        Returns:
            酒店列表
        """
        try:
            start = time.time()
            self._ensure_page(headless=self.headless, user_dir_name='drission_tongcheng_hotel')

            # 注入 Cookie（CDP方式）
            self._inject_cookies_for_domain(cookie_str=self.cookie, domain='.ly.com')

            city_id = TONGCHENG_CITY_IDS.get(city_name)
            if not city_id:
                logger.warning("同程不支持城市: %s，尝试用城市名搜索", city_name)
                city_id = 53  # 默认北京

            keyword = hotel_name or ""
            url = (
                f"{self.BASE_URL}"
                f"?city={city_id}"
                f"&inDate={checkin}"
                f"&outDate={checkout}"
                f"&keywords={quote(keyword)}"
            )
            logger.info("同程酒店搜索: %s(id=%s) %s~%s keyword=%s", city_name, city_id, checkin, checkout, keyword)
            self.page.get(url)

            # 等待 Vue 渲染完成（等待酒店列表出现）
            loaded = False
            deadline = time.time() + 10.0
            attempt = 0
            while time.time() < deadline:
                html_snapshot = self.page.html or ""
                if self._is_risk_page(html_snapshot):
                    logger.warning("同程酒店页面触发账号风险提示，停止等待")
                    return []
                try:
                    if self.page.ele('css:a[href*="hoteldetail"]', timeout=0.3):
                        logger.info("同程酒店页面加载完成, 耗时 %.1fs", time.time() - start)
                        loaded = True
                        break
                except Exception:
                    pass
                attempt += 1
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                wait = min(0.5 * attempt, 2.0, remaining)
                time.sleep(wait)
            if not loaded:
                logger.warning("等待同程酒店元素超时，用已加载的HTML解析")

            html = self.page.html
            logger.info("页面HTML长度: %d", len(html))

            # 价格是异步加载的，用 JS 直接读取 DOM 中的价格
            price_map = self._fetch_prices_via_js()
            logger.info("JS 获取到 %d 个酒店价格", len(price_map))

            hotels = self._parse_html(html, price_map)
            if hotel_name and hotels:
                hotels = self._enrich_first_detail_price(hotels, checkin, checkout, current_room_name)
            logger.info("解析到 %d 条同程酒店", len(hotels))

            if len(hotels) < 3 and len(html) > 10000:
                logger.warning(
                    "⚠️ 同程酒店解析数量异常: 仅 %d 条 (HTML %d 字符)，可能DOM结构变更",
                    len(hotels), len(html),
                )
            return hotels

        except Exception as e:
            logger.error("同程酒店搜索失败: %s", e, exc_info=True)
            return []

    def _enrich_first_detail_price(
        self,
        hotels: List[Dict[str, Any]],
        checkin: str,
        checkout: str,
        target_room_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """用酒店详情页补齐目标酒店的房型级价格。"""
        if not hotels:
            return hotels

        detail = self.fetch_detail_price(hotels[0], checkin, checkout, target_room_name)
        if not detail:
            return hotels

        enriched = dict(hotels[0])
        enriched.update(detail)
        enriched["source"] = hotels[0].get("source", "tongcheng")
        enriched["has_room_price"] = True
        return [enriched] + hotels[1:]

    def fetch_detail_price(
        self,
        hotel: Dict[str, Any],
        checkin: str,
        checkout: str,
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """打开同程详情页，读取房型级报价。"""
        detail_url = self._build_detail_url(hotel.get("detail_url", ""), checkin, checkout)
        if not detail_url:
            return None

        try:
            logger.info("同程酒店详情取价: hotel_id=%s room=%s", hotel.get("hotel_id"), target_room_name or "")
            self.page.get(detail_url)
            text = ""
            parsed = None
            deadline = time.time() + 15.0
            while time.time() < deadline:
                try:
                    text = self.page.run_js('return document.body && document.body.innerText || ""') or ""
                except Exception:
                    text = ""
                parsed = self._parse_detail_text(text, target_room_name)
                if parsed:
                    break
                time.sleep(0.8)

            if not parsed:
                logger.info("同程详情页未解析到房型价格: hotel_id=%s", hotel.get("hotel_id"))
                return None
            parsed["detail_url"] = detail_url
            return parsed
        except Exception as e:
            logger.warning("同程详情页房型取价失败: hotel_id=%s error=%s", hotel.get("hotel_id"), e)
            return None

    @staticmethod
    def _build_detail_url(detail_url: str, checkin: str, checkout: str) -> str:
        if not detail_url:
            return ""
        separator = "&" if "?" in detail_url else "?"
        url = detail_url
        if "inDate=" not in url:
            url = f"{url}{separator}inDate={checkin}"
            separator = "&"
        if "outDate=" not in url:
            url = f"{url}{separator}outDate={checkout}"
        return url

    @classmethod
    def _parse_detail_text(
        cls,
        text: str,
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        room_prices: List[Dict[str, Any]] = []
        current_room = ""
        in_policy_section = False

        for idx, line in enumerate(lines):
            if cls._starts_non_room_price_section(line):
                in_policy_section = True
                current_room = ""
                continue

            if cls._looks_like_room_name(line):
                in_policy_section = False
                current_room = line

            if in_policy_section or cls._is_non_room_fee_line(line):
                continue

            price = cls._extract_price_from_line(line)
            if price is None and line in ("¥", "￥") and idx + 1 < len(lines):
                next_line = lines[idx + 1]
                if not cls._is_non_room_fee_line(next_line):
                    price = cls._extract_price_from_line(next_line, allow_plain_number=True)

            if price is None or price < 100:
                continue

            room_name = current_room or cls._find_nearest_room_name(lines, idx)
            if not room_name:
                continue
            room_prices.append({"room_name": room_name, "price_yuan": price, "price": yuan_to_fen(price)})

        if not room_prices:
            return None

        normalized_target = cls._normalize_room_name(target_room_name or "")
        if normalized_target:
            for item in room_prices:
                normalized_room = cls._normalize_room_name(item["room_name"])
                if cls._room_name_matches(normalized_target, normalized_room):
                    return item

        return min(room_prices, key=lambda item: item["price_yuan"])

    @classmethod
    def _room_name_matches(cls, normalized_target: str, normalized_room: str) -> bool:
        if not normalized_target or not normalized_room:
            return False
        if normalized_target in normalized_room or normalized_room in normalized_target:
            return True

        target_tokens = cls._room_name_tokens(normalized_target)
        room_tokens = cls._room_name_tokens(normalized_room)
        if not target_tokens:
            return False
        return target_tokens.issubset(room_tokens)

    @staticmethod
    def _room_name_tokens(normalized_name: str) -> set:
        tokens = set()
        for token in ("大床", "双床", "亲子", "家庭", "商务", "高级", "豪华", "标准", "舒适", "套房"):
            if token in normalized_name:
                tokens.add(token)
        return tokens

    @staticmethod
    def _extract_price_from_line(line: str, allow_plain_number: bool = False) -> Optional[float]:
        clean = line.replace(",", "")
        if re.search(r"(?:每人|押金|收费|早餐|加早|CNY|费用)", clean, re.IGNORECASE):
            return None

        match = re.search(r"[¥￥]\s*(\d{2,5}(?:\.\d+)?)", clean)
        if not match and allow_plain_number:
            match = re.search(r"^\s*(\d{2,5}(?:\.\d+)?)\s*$", clean)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @classmethod
    def _find_nearest_room_name(cls, lines: List[str], price_idx: int) -> str:
        start = max(0, price_idx - 6)
        for line in reversed(lines[start:price_idx]):
            if cls._looks_like_room_name(line):
                return line
        return ""

    @staticmethod
    def _looks_like_room_name(value: str) -> bool:
        if not value or len(value) > 60:
            return False
        if any(word in value for word in ("酒店", "宾馆", "早餐", "取消", "预订", "点评", "政策")):
            return False
        return any(word in value for word in ("房", "套")) and any(
            word in value
            for word in ("大床", "双床", "亲子", "家庭", "商务", "高级", "豪华", "标准", "舒适", "套房")
        )

    @staticmethod
    def _starts_non_room_price_section(value: str) -> bool:
        return value in ("酒店介绍", "基础信息", "酒店政策", "设施服务", "收费说明", "证件提示", "证照信息")

    @staticmethod
    def _is_non_room_fee_line(value: str) -> bool:
        return bool(re.search(r"(?:每人|押金|收费|早餐|加早|CNY|费用)", value, re.IGNORECASE))

    @staticmethod
    def _normalize_room_name(value: str) -> str:
        return re.sub(r"[\s·・（）()\\-_/]", "", value or "").lower()

    @staticmethod
    def _is_risk_page(content: str) -> bool:
        if not content:
            return False
        return any(
            keyword in content
            for keyword in (
                "账号风险提示",
                "访问风险",
                "账号可能存在风险",
                "为了您的账号安全请验证通过后使用",
                "前往验证",
            )
        )

    def _inject_cookies_for_domain(self, cookie_str: Optional[str], domain: str = '.ly.com'):
        """为同程域名注入 Cookie（CDP 直接注入，不依赖 fliggy_base 的域名列表）"""
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

    def _fetch_prices_via_js(self) -> Dict[str, float]:
        """通过 JS 直接读取 DOM 中的价格，返回 {hotel_id: price_yuan} 映射"""
        try:
            result = self.page.run_js("""
                var map = {};
                var links = document.querySelectorAll('a[href*="hoteldetail"]');
                links.forEach(function(a) {
                    var href = a.getAttribute('href') || '';
                    var idMatch = href.match(/hotelId=(\\d+)/);
                    if (!idMatch) return;
                    var hotelId = idMatch[1];
                    var priceEl = a.querySelector('.discountPrice');
                    if (priceEl) {
                        var text = priceEl.textContent.trim().replace(/,/g, '');
                        var numMatch = text.match(/(\\d+)/);
                        if (numMatch) map[hotelId] = parseFloat(numMatch[1]);
                    }
                });
                return JSON.stringify(map);
            """)
            if result:
                import json
                raw = json.loads(result)
                return {k: float(v) for k, v in raw.items()}
        except Exception as e:
            logger.warning("JS 获取价格失败: %s", e)
        return {}

    def _parse_html(self, html: str, price_map: Dict[str, float] = None) -> List[Dict[str, Any]]:
        """从HTML中提取酒店数据"""
        if price_map is None:
            price_map = {}

        hotels = []

        # 同程 DOM 结构：<a href="/hotel/hoteldetail?hotelId=...&prc=280..."><li>...</li></a>
        # 价格是异步加载的，通过 price_map（JS 读取）注入
        blocks = re.split(r'(?=<a\s[^>]*href="[^"]*hoteldetail[^"]*")', html)

        logger.info("找到 %d 个候选块", len(blocks) - 1)

        for block in blocks[1:]:
            try:
                hotel = self._extract_hotel(block, price_map)
                if hotel:
                    hotels.append(hotel)
            except Exception as e:
                logger.debug("提取单个同程酒店失败: %s", e)
                continue

        # 去重（按 hotel_id）
        seen = set()
        unique = []
        for h in hotels:
            hid = h.get('hotel_id', '')
            if hid and hid not in seen:
                seen.add(hid)
                unique.append(h)
            elif not hid:
                unique.append(h)

        return unique

    def _extract_hotel(self, block: str, price_map: Dict[str, float] = None) -> Optional[Dict[str, Any]]:
        """从单个块中提取酒店数据"""
        # 必须包含 hoteldetail 链接才是酒店条目
        if 'hoteldetail' not in block:
            return None

        # ── 酒店ID ──
        hotel_id = ''
        id_match = re.search(r'hotelId=(\d+)', block)
        if id_match:
            hotel_id = id_match.group(1)
        if not hotel_id:
            return None

        # ── 详情链接 ──
        detail_url = ''
        url_match = re.search(r'href="(/hotel/hoteldetail[^"]*)"', block)
        if url_match:
            detail_url = 'https://www.ly.com' + url_match.group(1)
        else:
            url_match2 = re.search(r'href="(https?://[^"]*hoteldetail[^"]*)"', block)
            if url_match2:
                detail_url = url_match2.group(1)

        # ── 酒店名（dd 元素）──
        name = ''
        for pattern in [
            r'<dd[^>]*>\s*([^<\n]{2,50})\s*</dd>',
            r'class="[^"]*hotelName[^"]*"[^>]*>([^<]+)<',
            r'class="[^"]*hotel-name[^"]*"[^>]*>([^<]+)<',
        ]:
            name_match = re.search(pattern, block)
            if name_match:
                candidate = name_match.group(1).strip()
                # 过滤掉纯数字、太短的、包含HTML的
                if len(candidate) >= 2 and '<' not in candidate and not candidate.isdigit():
                    name = candidate
                    break

        if not name:
            return None

        # ── 星级/类型（span > em，名称行第一个 em）──
        star_type = ''
        star_match = re.search(r'<em[^>]*>\s*([^<]{2,10}(?:星级?|型|星))\s*</em>', block)
        if star_match:
            star_type = star_match.group(1).strip()

        # ── 评分 ──
        score = 0.0
        score_match = re.search(
            r'commentScore[^>]*>[^<]*<[^>]*>\s*(\d+\.?\d*)\s*<',
            block
        )
        if not score_match:
            score_match = re.search(r'(\d+\.\d+)\s*(?:分|<)', block)
        if score_match:
            try:
                score = float(score_match.group(1))
                if score > 10:
                    score = 0.0
            except ValueError:
                pass

        # ── 评价描述（超棒/很好等）──
        score_desc = ''
        desc_match = re.search(r'<em[^>]*>\s*(超棒|很好|不错|一般|较差)\s*</em>', block)
        if desc_match:
            score_desc = desc_match.group(1)

        # ── 评价数 ──
        comment_count = 0
        count_match = re.search(r'(\d+)\s*条点评', block)
        if count_match:
            comment_count = int(count_match.group(1))

        # ── 价格：优先从 JS price_map 获取（异步加载），其次从 href 的 prc= 参数 ──
        price_yuan = 0.0
        if price_map and hotel_id in price_map:
            price_yuan = price_map[hotel_id]
        else:
            prc_match = re.search(r'[?&]prc=(\d+)', block)
            if prc_match:
                price_yuan = float(prc_match.group(1))

        # ── 图片 ──
        image = ''
        img_match = re.search(r'<img[^>]+src="(https?://[^"]+(?:\.jpg|\.png|\.webp)[^"]*)"', block)
        if img_match:
            image = img_match.group(1)

        # ── 位置/商圈 ──
        location = ''
        loc_match = re.search(r'靠近([^<]{2,30})<', block)
        if loc_match:
            location = '靠近' + loc_match.group(1).strip()

        # ── 标签 ──
        tags = re.findall(r'tag-style-02[^>]*>([^<]+)<', block)
        tags = [t.strip() for t in tags if t.strip()]

        return {
            'hotel_id': hotel_id,
            'hotel_name': name,
            'star_type': star_type,
            'star_rating': _star_text_to_num(star_type),
            'score': score,
            'score_desc': score_desc,
            'comment_count': comment_count,
            'price_yuan': price_yuan,
            'price': yuan_to_fen(price_yuan),
            'image': image,
            'location': location,
            'tags': tags,
            'detail_url': detail_url,
            'source': 'tongcheng',
        }

    def close(self):
        self._close_page()


def _star_text_to_num(star_text: str) -> int:
    mapping = {
        "五星级": 5, "五星": 5, "豪华型": 4, "四星级": 4, "四星": 4,
        "高档型": 3, "三星级": 3, "三星": 3, "舒适型": 2, "二星级": 2,
        "经济型": 1, "一星级": 1,
    }
    for k, v in mapping.items():
        if k in star_text:
            return v
    return 0
