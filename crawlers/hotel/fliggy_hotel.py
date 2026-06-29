"""
飞猪酒店爬虫 - DrissionPage headless + SSR 正则解析

飞猪酒店搜索走 travelsearch.fliggy.com（综合搜索），SSR渲染，酒店数据直接在HTML DOM中。
- 容器: div.product-wrap
- 酒店名: .main-title div
- 地址: .sub-title
- 星级/类型: .hotel-star
- 评分: .rate-msg span (如 "4.7分 很好")
- 价格: .price (如 "¥2228起")
- 图片: .lazy-image data-src
- 酒店ID: a[href*=hotel_detail2.htm?shid=XXX] 中的 shid

搬自 RideClawAPI app/clients/spiders/fliggy_hotel_spider.py。
改动：
- import 改为 crawlers.core 路径。
抓取逻辑零改动。
"""
from crawlers.core.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

import time, re, json, logging, os
from typing import List, Dict, Any, Optional
from urllib.parse import quote

from crawlers.core.browser_base import FliggyBrowserMixin
from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)


class FliggyHotelSpider(FliggyBrowserMixin):
    """飞猪酒店爬虫 (DrissionPage + SSR 正则解析)"""

    def __init__(self, headless: bool = True, cookie: Optional[str] = None):
        super().__init__()
        self.headless = headless
        self.cookie = cookie

    def search_hotels(self, city_name: str, checkin: str, checkout: str,
                      hotel_name: str = None) -> List[Dict[str, Any]]:
        """
        搜索酒店

        Args:
            city_name: 城市中文名（如"杭州"、"上海"）
            checkin: 入住日期 YYYY-MM-DD
            checkout: 离店日期 YYYY-MM-DD
            hotel_name: 酒店名称关键词（可选）

        Returns:
            酒店列表
        """
        try:
            start = time.time()
            self._ensure_page(headless=self.headless, user_dir_name='drission_fliggy_hotel')

            # 1. 注入 Cookie（CDP方式，不需要先访问飞猪首页）
            self._inject_cookies(cookie_str=self.cookie)

            # 2. 直接构造搜索URL并访问
            keyword = hotel_name if hotel_name else city_name
            url = (
                f'https://travelsearch.fliggy.com/index.htm'
                f'?searchType=hotel'
                f'&keyword={quote(keyword)}'
                f'&checkIn={checkin}'
                f'&checkOut={checkout}'
            )
            logger.info("搜索酒店: %s %s~%s", keyword, checkin, checkout)
            self.page.get(url)

            # 智能轮询等待SSR渲染（递增间隔，最多等10秒）
            loaded = False
            for i in range(20):
                wait = min(0.5 * (i + 1), 2.0)
                time.sleep(wait)
                try:
                    if self.page.ele('css:.product-wrap', timeout=0.3):
                        logger.info("酒店页面加载完成, 等待 %.1f秒", time.time() - start)
                        loaded = True
                        break
                except Exception:
                    pass
            if not loaded:
                logger.warning("等待酒店元素超时，用已加载的HTML解析")

            # 3. 拿到页面HTML后直接用正则解析
            html = self.page.html
            logger.info("页面HTML长度: %d", len(html))
            hotels = self._parse_html(html)
            logger.info("解析到 %d 条酒店", len(hotels))

            # 解析数量异常告警（正常10-30条，低于3条可能DOM变了）
            if len(hotels) < 3 and len(html) > 10000:
                logger.warning(
                    "⚠️ 飞猪酒店解析数量异常: 仅 %d 条 (HTML %d 字符)，"
                    "可能是飞猪DOM结构变更，请检查选择器",
                    len(hotels), len(html),
                )
            return hotels

        except Exception as e:
            logger.error("飞猪酒店搜索失败: %s", e, exc_info=True)
            return []

    def fetch_detail_price(
        self,
        shid: str,
        checkin: str,
        checkout: str,
    ) -> Optional[Dict[str, Any]]:
        """打开飞猪 PC 酒店详情页，读取指定入住日期下的最低房型价。"""
        if not shid:
            return None

        try:
            self._ensure_page(headless=self.headless, user_dir_name='drission_fliggy_hotel')
            self._inject_cookies(cookie_str=self.cookie)

            url = (
                f"https://hotel.fliggy.com/hotel_detail2.htm"
                f"?shid={shid}&checkIn={checkin}&checkOut={checkout}"
            )
            logger.info("飞猪酒店详情取价: shid=%s %s~%s", shid, checkin, checkout)
            self.page.get(url)

            text = ""
            html = ""
            for _ in range(20):
                time.sleep(1)
                try:
                    text = self.page.run_js('return document.body && document.body.innerText || ""') or ""
                except Exception:
                    text = ""
                html = self.page.html
                if "login.taobao.com" in (self.page.url or ""):
                    logger.info("飞猪酒店详情页需要登录: shid=%s url=%s", shid, self.page.url)
                    return None
                if "报价列表" in text and re.search(r"[¥￥]\s*\d+", text):
                    break

            logger.info("飞猪详情页文本长度: %d url=%s", len(text), self.page.url)
            parsed = self._parse_detail_text(text, shid, checkin, checkout)
            if parsed:
                return parsed

            logger.info("飞猪详情页未解析到指定日期价格: shid=%s html_len=%d", shid, len(html))
            return None
        except Exception as e:
            logger.error("飞猪酒店详情取价失败: shid=%s error=%s", shid, e, exc_info=True)
            return None

    @staticmethod
    def _parse_detail_text(
        text: str,
        shid: str,
        checkin: str,
        checkout: str,
    ) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        price_match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)\s*起", text)
        if not price_match:
            price_match = re.search(r"报价列表\s*[¥￥]\s*(\d+(?:\.\d+)?)", text)
        if not price_match:
            return None

        try:
            price_yuan = float(price_match.group(1))
        except ValueError:
            return None

        room_name = ""
        after_price = text[price_match.end(): price_match.end() + 300]
        room_match = re.search(r"(?:\|\s*)?([^|\n]{2,80}?(?:房|套))\s*查看房型图片", after_price)
        if not room_match:
            room_match = re.search(r"\|\s*([^|\n]{2,80}?(?:房|套))\s*(?:床型|卖家|报价列表|\|)", after_price)
        if room_match:
            room_name = room_match.group(1).strip()
        else:
            before_price = text[max(0, price_match.start() - 300): price_match.start()]
            room_matches = re.findall(r"([^|\n]{2,80}?(?:房|套))\s*(?:查看房型图片|床型)", before_price)
            if room_matches:
                room_name = room_matches[-1].strip()

        return {
            "hotel_id": shid,
            "price_yuan": price_yuan,
            "price": yuan_to_fen(price_yuan),
            "room_name": room_name,
            "checkin": checkin,
            "checkout": checkout,
            "source": "fliggy_pc_detail",
        }

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """从HTML字符串中用正则提取酒店数据"""
        hotels = []

        # 按 product-wrap 分割（多选择器）
        blocks = []
        for splitter in [
            r'<div\s+class="product-wrap\s+clear-fix">',
            r'<div\s+class="product-wrap[^"]*">',
        ]:
            blocks = re.split(splitter, html)
            if len(blocks) > 1:
                break

        logger.info("找到 %d 个 product-wrap 块", len(blocks) - 1)

        for block in blocks[1:]:
            try:
                hotel = self._extract_from_html(block)
                if hotel:
                    hotels.append(hotel)
            except Exception as e:
                logger.debug("提取单个酒店失败: %s", e)
                continue

        return hotels

    def _extract_from_html(self, block: str) -> Optional[Dict[str, Any]]:
        """从单个product-wrap的HTML块中提取酒店数据（多选择器降级）"""

        # ── 判断是否是酒店（tag-value中包含"酒店"）──
        is_hotel = True
        tag_match = re.search(r'<span\s+class="tag-value"[^>]*>([^<]+)</span>', block)
        if tag_match:
            tag_text = tag_match.group(1).strip()
            if '酒店' not in tag_text and 'Hotel' not in tag_text.lower():
                is_hotel = False
        # 降级：如果没找到 tag-value，通过链接判断
        if not is_hotel and 'hotel' not in block.lower():
            return None

        # ── 酒店名（多选择器）──
        name = ''
        for pattern in [
            r'class="main-title"[^>]*>\s*<[^>]*>\s*<div>([^<]+)</div>',
            r'class="main-title"[^>]*>(.*?)</h3>',
            r'class="hotel-name[^"]*"[^>]*>([^<]+)<',
            r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)<',
        ]:
            name_match = re.search(pattern, block, re.DOTALL)
            if name_match:
                name = name_match.group(1).strip()
                # 第2个 pattern 可能匹配到带HTML的文本，需要二次提取
                if '<' in name:
                    div_match = re.search(r'>([^<]+)<', name)
                    name = div_match.group(1).strip() if div_match else ''
                if name:
                    break

        if not name:
            return None

        # ── 地址（多选择器）──
        address = ''
        for pattern in [
            r'class="sub-title"[^>]*>(.*?)</h4>',
            r'class="address[^"]*"[^>]*>([^<]+)<',
            r'<h4[^>]*class="[^"]*sub[^"]*"[^>]*>(.*?)</h4>',
        ]:
            addr_match = re.search(pattern, block, re.DOTALL)
            if addr_match:
                address = addr_match.group(1).strip()
                address = re.sub(r'^[\s|·\-]+', '', address)
                if address:
                    break

        # ── 星级/类型（多选择器）──
        star_text = ''
        business_area = ''
        for pattern in [
            r'class="hotel-star"[^>]*>(.*?)</p>',
            r'class="star-type[^"]*"[^>]*>(.*?)</(?:p|div|span)>',
            r'<p[^>]*class="[^"]*(?:star|level)[^"]*"[^>]*>(.*?)</p>',
        ]:
            star_match = re.search(pattern, block, re.DOTALL)
            if star_match:
                star_html = star_match.group(1)
                star_clean = re.sub(r'<[^>]+>', '|', star_html)
                star_clean = re.sub(r'\s*\|+\s*', '|', star_clean).strip('| ')
                parts = star_clean.split('|', maxsplit=1)
                star_text = parts[0].strip() if parts else ''
                business_area = parts[1].strip().strip('| ') if len(parts) > 1 else ''
                if star_text:
                    break

        # ── 评分（多选择器）──
        score = 0.0
        score_text = ''
        for pattern in [
            r'class="rate-msg"[^>]*>(.*?)</p>',
            r'class="score[^"]*"[^>]*>(.*?)</(?:p|div|span)>',
            r'class="rating[^"]*"[^>]*>(.*?)</(?:p|div|span)>',
        ]:
            rate_match = re.search(pattern, block, re.DOTALL)
            if rate_match:
                rate_html = rate_match.group(1)
                score_text = re.sub(r'<[^>]+>', ' ', rate_html).strip()
                m = re.search(r'(\d+\.?\d*)分', score_text)
                if m:
                    score = float(m.group(1))
                if score > 0:
                    break

        # ── 价格（多选择器）──
        price = 0.0
        for pattern in [
            r'class="real-price"[^>]*>.*?class="price"[^>]*>(.*?)</span>',
            r'class="price"[^>]*>\s*<em[^>]*>[¥￥]</em>\s*(\d+)',
            r'data-price="(\d+)"',
            r'class="real-price"[^>]*>(.*?)</(?:div|span)>',
        ]:
            price_match = re.search(pattern, block, re.DOTALL)
            if price_match:
                price_html = price_match.group(1)
                m = re.search(r'[¥￥]\s*(\d+)', price_html)
                if m:
                    price = float(m.group(1))
                    break
                else:
                    nums = re.findall(r'\d+', price_html)
                    if nums:
                        price = float(nums[0])
                        break

        # ── 图片（多选择器）──
        image = ''
        for pattern in [
            r'class="lazy-image"[^>]*data-src="([^"]+)"',
            r'class="lazy-image"[^>]*src="([^"]+)"',
            r'<img[^>]*class="[^"]*hotel-img[^"]*"[^>]*src="([^"]+)"',
        ]:
            img_match = re.search(pattern, block)
            if img_match:
                image = img_match.group(1)
                break

        # ── 酒店ID（多选择器）──
        hotel_id = ''
        for pattern in [
            r'hotel_detail[^"?]*\?[^"]*shid=(\d+)',
            r'shid=(\d+)',
            r'data-hotel-id="(\d+)"',
        ]:
            id_match = re.search(pattern, block)
            if id_match:
                hotel_id = id_match.group(1)
                break

        # ── 详情链接（多选择器）──
        detail_url = ''
        for pattern in [
            r'href="(https?://[^"]*hotel_detail[^"]*)"',
            r'href="(https?://[^"]*hotel[^"]*\.htm[^"]*)"',
        ]:
            url_match = re.search(pattern, block)
            if url_match:
                detail_url = url_match.group(1)
                break

        # ── 标签（多选择器）──
        tags = []
        for pattern in [
            r'class="tag-list"[^>]*>.*?<li\s+class="tag"[^>]*>([^<]+)</li>',
            r'class="tag-list-item[^"]*"[^>]*>([^<]+)<',
        ]:
            tags = re.findall(pattern, block, re.DOTALL)
            if tags:
                break
        tags = [t.strip() for t in tags if t.strip() and t.strip() not in ('会员价',)]

        return {
            'hotel_id': hotel_id,
            'hotel_name': name,
            'address': address,
            'star_type': star_text,
            '商圈': business_area,
            'score': score,
            'score_text': score_text,
            'price_yuan': price,
            'price': yuan_to_fen(price),
            'image': image,
            'tags': tags,
            'detail_url': detail_url,
            'source': 'fliggy_pc',
        }

    def close(self):
        self._close_page()


if __name__ == '__main__':
    import logging as _logging
    _logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    spider = FliggyHotelSpider(headless=True)
    hotels = spider.search_hotels('杭州', '2026-04-20', '2026-04-21')
    spider.close()

    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'tools', 'fliggy_hotel_result.json'
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(hotels, f, ensure_ascii=False, indent=2)

    logger.info("[Spider][FliggyHotel] 找到 %d 条酒店, 已保存到 %s", len(hotels), out_path)
    if hotels:
        for h in hotels[:5]:
            logger.info(
                "[Spider][FliggyHotel] %s | %s | %s分 | ¥%s | %s",
                h["hotel_name"],
                h["star_type"],
                h["score"],
                h["price_yuan"],
                h["address"],
            )
