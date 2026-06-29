#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
携程酒店爬虫 - requests直接调用API

API: POST https://m.ctrip.com/restapi/soa2/34951/fetchHotelList
不需要DrissionPage，直接HTTP请求。
需要有效Cookie来通过认证。

搬自 RideClawAPI app/clients/spiders/ctrip_hotel_spider.py。
改动：
- 移除 app.clients.spiders.stdio import 与模块级 ensure_utf8_stdio() 副作用调用；
- __main__ 自测块改用标准库 logging。
抓取逻辑（含城市映射、详情页解析）零改动。
"""
import os

from crawlers.core.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

import json
import logging
import asyncio
import re
import time
import random
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

# API 端点
API_URL = "https://m.ctrip.com/restapi/soa2/34951/fetchHotelList"

# 默认请求头
DEFAULT_HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Origin': 'https://m.ctrip.com',
    'Referer': 'https://m.ctrip.com/',
    'X-Requested-With': 'XMLHttpRequest',
}

def _normalize_hotel_keyword(value: str) -> str:
    return re.sub(r"[\s·・（）()\-_/]", "", value or "").lower()


APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CTRIP_COOKIE_FILES = [
    os.path.join(APP_DIR, 'config', 'ctrip_cookie.txt'),
]

# 城市ID映射（来源：API遍历实测 1~300 + 301~2000 扩展扫描，2026-04-20，共约139个城市）
# 城市ID映射（297市全覆盖：4直辖市 + 293地级市，2026-04-20实测）
# cityId来源：1~2000 API遍历扫描 + 2000+ 手动验证（南阳385/大庆231/河池3969/雅安3277/贺州4146）
CITY_ID_MAP = {
    # 一线城市 / 热门（★=实测修正）
    "北京": 1, "上海": 2, "广州": 32,
    "深圳": 30,          # ★ 旧34 → 30
    "杭州": 17, "成都": 28,
    "南京": 12, "重庆": 4,
    "西安": 10,          # ★ 旧252 → 10
    "苏州": 14,
    "长沙": 206,         # ★ 旧268 → 206
    "天津": 3,
    "青岛": 7,           # ★ 旧278 → 7
    "大连": 6,
    "三亚": 43, "昆明": 34,   # ★ 旧100 → 34
    "济南": 144,         # ★ 旧269 → 144
    # 江苏
    "无锡": 13, "扬州": 15, "镇江": 16, "南通": 82, "常州": 213,
    # 浙江
    "舟山": 19, "绍兴": 22, "温州": 85, "湖州": 86,
    # 安徽
    "黄山": 23, "合肥": 278,
    # 福建
    "福州": 258, "泉州": 270, "漳州": 25,    # ★ 福州/泉州实测修正
    # 江西
    "九江": 24, "南昌": 21, "景德镇": 18,
    # 湖南
    "张家界": 27,
    # 广东
    "珠海": 31, "佛山": 251, "东莞": 223,    # ★ 东莞实测修正
    # 广西
    "桂林": 33, "北海": 189, "南宁": 51,
    # 海南
    "海口": 42, "万宁": 45, "五指山": 46, "屯昌": 47,
    "东方": 48, "乐东": 49, "定安": 50, "琼海": 52,
    "琼中": 53, "保亭": 54, "陵水": 55, "昌江": 56, "儋州": 57,
    # 西南
    "西双版纳": 35, "大理": 36, "丽江": 37, "贵阳": 38,
    "香格里拉": 143, "玉溪": 186, "保山": 197, "眉山": 95,
    # 西北
    "乌鲁木齐": 39, "吐鲁番": 40, "拉萨": 41, "敦煌": 11,
    "银川": 99, "兰州": 100, "喀什": 109, "西宁": 124,
    "延安": 110, "咸阳": 111, "宝鸡": 112, "渭南": 117,
    "铜川": 118, "汉中": 129, "格尔木": 132, "伊宁": 98,
    "克拉玛依": 166, "阿勒泰": 175, "哈密": 285, "和田": 294,
    # 东北
    "哈尔滨": 5,           # ★ 实测确认
    "齐齐哈尔": 149, "牡丹江": 150, "鸡西": 157,
    "长春": 158, "吉林": 159, "丹东": 221, "朝阳": 211,
    "抚顺": 252,
    # 华北 / 山东
    "秦皇岛": 147, "保定": 185, "沧州": 216, "邯郸": 275,
    "衡水": 290,
    # 内蒙古
    "呼和浩特": 103, "包头": 141, "赤峰": 202,    # ★ 呼市/包头新增
    # 东北其他
    "鞍山": 178,           # ★ 新增
    # 港澳
    "澳门": 59,
    # 其他
    "武夷山": 26, "日喀则": 92, "安顺": 179,
    # 华北 / 山东（补）
    "张家口": 550, "承德": 562, "邢台": 947,
    # 山东（补）
    "济宁": 318, "临沂": 569, "淄博": 542, "烟台": 533,
    "潍坊": 475, "威海": 479, "泰安": 454,
    # 浙江（补）
    "丽水": 346, "龙岩": 348, "宁德": 378, "衢州": 407, "上饶": 411,
    # 江西（补）
    "吉安": 933,
    # 河南（补）
    "洛阳": 350,
    # 湖北（补）
    "武汉": 477, "荆州": 328,
    # 广东（补）
    "汕头": 447, "韶关": 422, "肇庆": 552, "梅州": 954, "梧州": 492,
    # 广西（补）
    "廊坊": 340,
    # 东北（补）
    "盘锦": 387, "铁岭": 1048, "葫芦岛": 1050,
    "白城": 1116, "绥化": 1128, "营口": 1300, "白山": 1466,
    # 中部（补）
    "郑州": 559, "菏泽": 1696, "马鞍山": 1024,
    # 从1~2000扫描新发现的161个城市（2026-04-20）
    # 山西
    "太原": 105, "大同": 136, "长治": 137, "临汾": 139, "运城": 140, "晋中": 134,
    # 安徽
    "蚌埠": 182, "阜阳": 257, "淮北": 272, "淮南": 287, "滁州": 214, "池州": 218,
    "安庆": 177, "宣城": 1006, "宿州": 521, "亳州": 1078, "六安": 1705,
    # 浙江
    "宁波": 375, "金华": 308, "嘉兴": 571, "台州": 470,
    # 江苏
    "徐州": 512, "连云港": 353, "淮安": 577, "泰州": 579, "宿迁": 1472, "盐城": 1200,
    # 山东
    "枣庄": 614, "东营": 236, "日照": 1106, "德州": 888, "聊城": 1071,
    "滨州": 1820,
    # 河南
    "开封": 331, "安阳": 181, "新乡": 507, "焦作": 1093, "濮阳": 1072,
    "许昌": 1094, "漯河": 1088, "三门峡": 436, "南阳": 385, "信阳": 510,
    "驻马店": 551, "鹤壁": 951, "商丘": 441, "平顶山": 1077, "周口": 1064,
    # 湖北
    "黄石": 292, "十堰": 452, "襄阳": 496, "孝感": 1490, "荆门": 1121,
    "宜昌": 515,
    "咸宁": 937, "黄冈": 941, "随州": 1117, "鄂州": 992,
    # 湖南
    "株洲": 441, "衡阳": 297, "邵阳": 1111, "岳阳": 539, "常德": 201,
    "益阳": 1125, "郴州": 612, "永州": 970, "怀化": 282, "娄底": 918,
    "湘潭": 598,
    # 江西
    "赣州": 268, "宜春": 518, "鹰潭": 534, "新余": 603, "景德镇": 18,
    "抚州": 1151,
    "九江": 24, "上饶": 411, "吉安": 933,
    # 广东
    "中山": 305, "惠州": 299, "江门": 291, "汕头": 447, "湛江": 547,
    "茂名": 1105, "韶关": 422, "梅州": 954, "汕尾": 1436, "河源": 693,
    "阳江": 692, "清远": 732, "潮州": 215, "揭阳": 956, "云浮": 339, "梧州": 492,
    # 广西
    "柳州": 354, "北海": 189, "防城港": 1677, "钦州": 1899, "贵港": 1518,
    "玉林": 1113, "百色": 1140, "河池": 3969, "来宾": 1892, "崇左": 1895,
    "贺州": 4146, "南宁": 51,
    # 河北
    "唐山": 468, "石家庄": 428, "阳泉": 537,
    # 辽宁
    "沈阳": 451, "锦州": 327, "阜新": 254, "辽阳": 351, "辽源": 352,
    "通化": 456, "通辽": 458, "本溪": 1155,
    # 吉林
    "吉林": 159,
    # 黑龙江
    "大庆": 231, "伊春": 517, "佳木斯": 317, "七台河": 1599, "鹤岗": 1611,
    "双鸭山": 1617, "黑河": 281,
    # 内蒙古
    "呼伦贝尔": 1136, "乌海": 1133, "鄂尔多斯": 3976,
    "乌兰察布": 7518, "巴彦淖尔": 3887,
    # 山西（补）\n    "晋城": 1092, "朔州": 1317, "忻州": 513, "吕梁": 7631,
    # 吉林（补）\n    "松原": 1303, "四平": 440,
    # 安徽（补）\n    "铜陵": 459, "芜湖": 478,
    # 山东（补）\n    "莱芜": 44972,
    # 江西（补）\n    "萍乡": 1840,
    # 陕西
    "铜川": 118, "榆林": 527, "安康": 171, "商洛": 1905,
    # 甘肃
    "天水": 464, "武威": 664, "张掖": 663, "酒泉": 662, "平凉": 388,
    "庆阳": 404, "定西": 1021, "嘉峪关": 326, "金昌": 1158, "白银": 1541,
    "陇南": 1106,
    # 宁夏
    "吴忠": 1033, "中卫": 556, "固原": 321, "石嘴山": 1304,
    # 青海
    "海东": 654,
    # 新疆
    "哈密": 285,
    # 四川
    "绵阳": 370, "德阳": 237, "广元": 267, "遂宁": 1371, "内江": 1491,
    "泸州": 355, "广安": 1100,
    "乐山": 345, "南充": 377, "宜宾": 514, "达州": 1233, "雅安": 3277,
    "巴中": 1160,
    "资阳": 1560, "自贡": 544, "攀枝花": 1097,
    # 贵州
    "遵义": 558, "六盘水": 605, "铜仁": 982, "毕节": 1315,
    # 云南
    "曲靖": 984, "临沧": 1236, "昭通": 555, "普洱": 1118,
    # 福建
    "莆田": 667, "三明": 437, "南平": 606, "厦门": 446,
    # 港澳台
    "香港": 58, "台北": 617,
}


class CtripHotelSpider:
    """携程酒店爬虫 - 直接HTTP API调用"""

    # Cookie 配置文件路径
    COOKIE_FILE = CTRIP_COOKIE_FILES[-1]

    def __init__(self, cookie: str = None):
        """
        Args:
            cookie: 携程Cookie字符串（可选）。
                    如果不传，尝试读取 app/config/ctrip_cookie.txt。
        """
        self.cookie = cookie or self._load_cookie()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        if self.cookie:
            self.session.headers['Cookie'] = self.cookie
            logger.info("携程酒店爬虫: 已加载Cookie")

    @classmethod
    def _load_cookie(cls) -> Optional[str]:
        """从 app/config/ctrip_cookie.txt 加载Cookie"""
        for cookie_file in CTRIP_COOKIE_FILES:
            if not os.path.exists(cookie_file):
                continue
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content and not content.startswith('#'):
                    logger.info(f"携程Cookie已从配置文件加载: {cookie_file}")
                    return content
            except Exception as e:
                logger.warning(f"读取Cookie配置文件失败: {e}")

        logger.info("携程酒店爬虫: 未配置Cookie，价格字段将为空")
        return None

    def set_cookie(self, cookie: str):
        """设置Cookie"""
        self.cookie = cookie
        self.session.headers['Cookie'] = cookie

    def _get_city_id(self, city_name: str) -> int:
        """根据城市名获取携程城市ID"""
        return CITY_ID_MAP.get(city_name, 1)

    def _build_payload(self, city_id: int, checkin: str, checkout: str,
                       page_index: int = 1, page_size: int = 20,
                       keyword: str = None) -> dict:
        """构造请求体

        Args:
            city_id: 城市ID
            checkin: 入住日期 YYYY-MM-DD
            checkout: 离店日期 YYYY-MM-DD
            page_index: 页码
            page_size: 每页数量
            keyword: 酒店名称关键词
        """
        payload = {
            "date": {
                "dateType": 1,
                "dateInfo": {
                    "checkInDate": checkin.replace("-", ""),
                    "checkOutDate": checkout.replace("-", "")
                }
            },
            "destination": {
                "type": 1,
                "geo": {
                    "cityId": city_id
                }
            },
            "paging": {
                "pageIndex": page_index,
                "pageSize": page_size
            },
            "head": {
                "platform": "H5",
                "group": "ctrip",
                "locale": "zh-CN",
                "currency": "CNY",
                "extension": [
                    {"name": "cityId", "value": str(city_id)},
                    {"name": "checkIn", "value": checkin.replace("-", "")},
                    {"name": "checkOut", "value": checkout.replace("-", "")}
                ]
            }
        }

        # 关键词搜索
        if keyword:
            # 携程 PC/Online 搜索语义：type=3 + keyword.word 才会按酒店名精确召回。
            # 旧的 H5 type=1 + keyword.name 会退化成城市推荐列表，导致翻很多页也找不到目标酒店。
            payload["destination"]["type"] = 3
            payload["destination"]["keyword"] = {"word": keyword}
            payload["head"]["platform"] = "PC"
            payload["head"]["bu"] = "HBU"

        return payload

    def search_hotels(self, city_name: str, checkin: str, checkout: str,
                      hotel_name: str = None,
                      max_pages: Optional[int] = None,
                      timeout: int = 15,
                      current_room_name: str = None) -> List[Dict[str, Any]]:
        """
        搜索酒店列表

        Args:
            city_name: 城市中文名
            checkin: 入住日期 YYYY-MM-DD
            checkout: 离店日期 YYYY-MM-DD
            hotel_name: 酒店名称关键词（可选）
            max_pages: 最大翻页数
            timeout: 超时时间（秒）

        Returns:
            酒店列表
        """
        if max_pages is None:
            max_pages = 3 if hotel_name else 5

        hotels = []
        city_id = self._get_city_id(city_name)

        for page_idx in range(1, max_pages + 1):
            try:
                payload = self._build_payload(
                    city_id=city_id,
                    checkin=checkin,
                    checkout=checkout,
                    page_index=page_idx,
                    page_size=20,
                    keyword=hotel_name
                )

                logger.info(f"请求 fetchHotelList (page={page_idx}, city={city_name})...")
                resp = self.session.post(API_URL, json=payload, timeout=timeout)

                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    break

                data = resp.json()
                # hotelList 在 data.hotelList 里
                hotel_list = data.get('hotelList', [])
                if not hotel_list:
                    inner = data.get('data', {})
                    hotel_list = inner.get('hotelList', []) if isinstance(inner, dict) else []

                if not hotel_list:
                    logger.info("hotelList 为空，搜索结束")
                    break

                logger.info(f"第{page_idx}页获取 {len(hotel_list)} 条酒店")

                for item in hotel_list:
                    h = self._extract(item, target_room_name=current_room_name)
                    if h:
                        hotels.append(h)

                logger.info(f"累计 {len(hotels)} 条酒店, 当前页酒店: {[h.get('hotel_name','') for h in hotels[-5:]]}")

                # 关键词搜索时，找到匹配就提前停止翻页
                if hotel_name:
                    keyword = _normalize_hotel_keyword(hotel_name)
                    for h in hotels:
                        candidate = _normalize_hotel_keyword(h.get('hotel_name', ''))
                        if keyword and (keyword in candidate or candidate in keyword):
                            list_price = h.get("price_yuan") or h.get("price")
                            if list_price and not current_room_name:
                                logger.info(
                                    "第%s页找到目标酒店: %s (ctrip_hotel_id=%s), 使用列表价格 price=%s room=%s",
                                    page_idx,
                                    h.get("hotel_name"),
                                    h.get("ctrip_hotel_id") or h.get("hotel_id"),
                                    list_price,
                                    h.get("room_name") or "",
                                )
                                return [h]

                            logger.info(f"第{page_idx}页找到目标酒店: {h.get('hotel_name')} (ctrip_hotel_id={h.get('ctrip_hotel_id') or h.get('hotel_id')}), 列表无价格，进入详情页取价")
                            detail = self._fallback_hotel_detail(
                                city_name,
                                checkin,
                                checkout,
                                hotel_name,
                                ctrip_hotel_id=h.get("ctrip_hotel_id") or h.get("hotel_id"),
                                target_room_name=current_room_name,
                            )
                            if detail:
                                return [detail]
                            return hotels

                # 控制请求频率
                if page_idx < max_pages:
                    time.sleep(random.uniform(1, 3))

            except requests.exceptions.Timeout:
                logger.error(f"请求超时 (page={page_idx})")
                break
            except Exception as e:
                logger.error(f"搜索失败 (page={page_idx}): {e}", exc_info=True)
                break

        logger.info(f"共获取 {len(hotels)} 条酒店")
        fallback = self._fallback_hotel_detail(
            city_name,
            checkin,
            checkout,
            hotel_name,
            target_room_name=current_room_name,
        )
        if fallback:
            logger.info(
                "携程列表未命中，使用详情页候选: %s (id=%s)",
                fallback.get("hotel_name"),
                fallback.get("ctrip_hotel_id") or fallback.get("hotel_id"),
            )
            hotels.append(fallback)
        return hotels

    def _fallback_hotel_detail(
        self,
        city_name: str,
        checkin: str,
        checkout: str,
        hotel_name: Optional[str],
        ctrip_hotel_id: Optional[str] = None,
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not hotel_name:
            return None

        normalized_target = _normalize_hotel_keyword(hotel_name)
        hotel_id = str(ctrip_hotel_id or "").strip() or None

        if not hotel_id:
            return None

        try:
            url = (
                f"https://m.ctrip.com/html5/hotel/hoteldetail/{hotel_id}.html"
                f"?checkIn={checkin}&checkOut={checkout}"
            )
            rendered = self._fetch_detail_price_with_browser(url, hotel_name, target_room_name)
            if rendered:
                rendered["hotel_id"] = hotel_id
                rendered["ctrip_hotel_id"] = hotel_id
                rendered["detail_url"] = url
                return rendered

            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                logger.warning("携程详情页候选请求失败: hotel_id=%s status=%s", hotel_id, resp.status_code)
                return None

            text = resp.text.replace('\\"', '"').replace("\\u0026", "&")
            name_match = re.search(r'"nameInfo":\{"name":"([^"]+)"', text)
            name = name_match.group(1) if name_match else hotel_name
            if not (_normalize_hotel_keyword(hotel_name) in _normalize_hotel_keyword(name) or _normalize_hotel_keyword(name) in _normalize_hotel_keyword(hotel_name)):
                return None

            star_match = re.search(r'"starInfo":\{"level":(\d+)', text)
            address_match = re.search(r'"hotelPositionInfo":\{"address":"([^"]+)"', text)
            image_match = re.search(r'"imgUrl":"([^"]+)"', text)

            star = int(star_match.group(1)) if star_match else 0
            address = address_match.group(1) if address_match else ""
            image = image_match.group(1) if image_match else ""

            return {
                "hotel_id": hotel_id,
                "ctrip_hotel_id": hotel_id,
                "hotel_name": name,
                "star_rating": star,
                "score": 0,
                "price_yuan": 0,
                "price": 0,
                "room_name": name,
                "address": address,
                "district": "",
                "lat": 0,
                "lon": 0,
                "comment_count": 0,
                "comment_desc": "",
                "score_tag": "",
                "env_score": 0,
                "hygiene_score": 0,
                "service_score": 0,
                "facility_score": 0,
                "tags": ["详情页候选"],
                "image": image,
                "source": "ctrip_detail_fallback",
                "has_candidate": True,
                "candidate_only": True,
                "detail_url": url,
            }
        except Exception as e:
            logger.warning("携程详情页候选解析失败: hotel=%s error=%s", hotel_name, e)
            return None

    def _fetch_detail_price_with_browser(
        self,
        url: str,
        hotel_name: Optional[str],
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            return asyncio.run(self._fetch_detail_price_with_browser_async(url, hotel_name, target_room_name))
        except Exception as e:
            logger.warning("携程详情页浏览器价格解析失败: hotel=%s error=%s", hotel_name, e)
            return None

    async def _fetch_detail_price_with_browser_async(
        self,
        url: str,
        hotel_name: Optional[str],
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        from playwright.async_api import async_playwright

        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        launch_kwargs = {"headless": True}
        if os.path.exists(chrome_path):
            launch_kwargs["executable_path"] = chrome_path

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    viewport={"width": 390, "height": 844},
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                        "Mobile/15E148 Safari/604.1"
                    ),
                )
                await self._add_playwright_cookies(context)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(8000)
                for _ in range(4):
                    await page.mouse.wheel(0, 900)
                    await page.wait_for_timeout(800)

                body = await page.locator("body").inner_text(timeout=10000)
                return self._parse_rendered_detail_text(body, hotel_name, target_room_name)
            finally:
                await browser.close()

    async def _add_playwright_cookies(self, context) -> None:
        cookie_file = next((path for path in CTRIP_COOKIE_FILES if os.path.exists(path)), "")
        if not cookie_file:
            return

        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception:
            return

        if not content:
            return

        cookies = []
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            raw = None

        if raw is None:
            for part in content.replace("\n", ";").split(";"):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name = name.strip()
                value = value.strip()
                if not name:
                    continue
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": ".ctrip.com",
                    "path": "/",
                    "sameSite": "Lax",
                })
        for item in raw if isinstance(raw, list) else []:
            domain = item.get("domain")
            name = item.get("name")
            value = item.get("value")
            if not domain or not name or value is None:
                continue

            same_site = item.get("sameSite")
            if same_site == "no_restriction":
                same_site = "None"
            elif same_site not in ("Strict", "Lax", "None"):
                same_site = "Lax"

            cookie = {
                "name": name,
                "value": str(value),
                "domain": domain,
                "path": item.get("path") or "/",
                "httpOnly": bool(item.get("httpOnly", False)),
                "secure": bool(item.get("secure", False)),
                "sameSite": same_site,
            }
            if item.get("expirationDate"):
                cookie["expires"] = int(float(item["expirationDate"]))
            cookies.append(cookie)

        if cookies:
            await context.add_cookies(cookies)

    def _parse_rendered_detail_text(
        self,
        text: str,
        hotel_name: Optional[str],
        target_room_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not text or "¥" not in text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        lines = self._slice_room_price_lines(lines)
        prices: List[tuple[str, float]] = []
        current_room = ""
        skip_next_price = False
        for idx, line in enumerate(lines):
            if self._looks_like_room_name(line):
                current_room = line
                continue
            if line == "¥" and idx + 1 < len(lines):
                price_text = lines[idx + 1]
                if not re.fullmatch(r"\d+(?:\.\d+)?", price_text):
                    continue
                price = float(price_text)
                if price < 400:
                    continue
                if skip_next_price:
                    skip_next_price = False
                    continue
                if idx + 2 < len(lines) and lines[idx + 2] == "¥":
                    skip_next_price = True
                    continue
                prices.append((current_room or hotel_name or "", price))

        if not prices:
            compact = re.sub(r"\s+", "", "\n".join(lines))
            for match in re.finditer(r"¥(\d{3,5})", compact):
                price = float(match.group(1))
                if price >= 400:
                    prices.append((hotel_name or "", price))

        if not prices:
            return None

        selected = self._select_room_price(prices, target_room_name)
        if not selected:
            return None
        room_name, price = selected
        return {
            "hotel_id": "",
            "ctrip_hotel_id": "",
            "hotel_name": hotel_name or "",
            "star_rating": 0,
            "score": 0,
            "price_yuan": price,
            "price": price,
            "room_name": room_name or hotel_name or "",
            "address": "",
            "district": "",
            "lat": 0,
            "lon": 0,
            "comment_count": 0,
            "comment_desc": "",
            "score_tag": "",
            "env_score": 0,
            "hygiene_score": 0,
            "service_score": 0,
            "facility_score": 0,
            "tags": ["详情页价格"],
            "image": "",
            "source": "ctrip_detail_browser",
            "has_candidate": True,
        }

    @classmethod
    def _select_room_price(
        cls,
        prices: List[tuple[str, float]],
        target_room_name: Optional[str] = None,
    ) -> Optional[tuple[str, float]]:
        normalized_target = cls._normalize_room_name(target_room_name or "")
        if normalized_target:
            for room_name, price in prices:
                normalized_room = cls._normalize_room_name(room_name)
                if cls._room_name_matches(normalized_target, normalized_room):
                    return room_name, price
            return None
        return min(prices, key=lambda item: item[1])

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
    def _normalize_room_name(value: str) -> str:
        return re.sub(r"[\s·・（）()\\-_/]", "", value or "").lower()

    @staticmethod
    def _looks_like_room_name(value: str) -> bool:
        if not value or len(value) > 40:
            return False
        if any(word in value for word in ("洗衣房", "健身房", "钟点房", "套餐", "早餐")):
            return False
        return any(word in value for word in ("房", "套房")) and any(word in value for word in ("大床", "双床", "亲子", "商务", "高级", "豪华", "舒适", "园景", "家庭"))

    @staticmethod
    def _slice_room_price_lines(lines: List[str]) -> List[str]:
        start = 0
        for idx, line in enumerate(lines):
            if line in ("筛选", "大床房", "双床房") or line == "舒适双床房":
                start = idx
                break

        end = len(lines)
        for idx in range(start, len(lines)):
            if lines[idx] in ("住客点评", "预售套餐", "钟点房(1)"):
                end = idx
                break

        return lines[start:end]

    def _extract(self, item: Dict, target_room_name: Optional[str] = None) -> Dict[str, Any]:
        """提取单条酒店信息

        字段映射（基于 fetchHotelList API）：
        - 酒店名称: hotelInfo.nameInfo.name
        - 酒店ID: hotelInfo.summary.hotelId
        - 图片: hotelInfo.hotelImages.url
        - 星级: hotelInfo.hotelStar.star
        - 评分: hotelInfo.commentInfo.commentScore (字符串)
        - 价格: roomInfo[0].priceInfo.price (需登录)
        - 区域: hotelInfo.positionInfo.zoneNames[0]
        """
        try:
            hotel_info = item.get('hotelInfo', {})
            room_info_list = item.get('roomInfo', [])

            # 酒店名称
            name_info = hotel_info.get('nameInfo', {})
            hotel_name = name_info.get('name', '')

            # 酒店ID - 在 summary 里
            summary = hotel_info.get('summary', {})
            hotel_id = str(summary.get('hotelId', ''))

            # 图片 - hotelImages.url 有值，multiImgs 可能为空
            images_info = hotel_info.get('hotelImages', {})
            image = images_info.get('url', '')

            # 区域和地址
            position_info = hotel_info.get('positionInfo', {})
            zone_names = position_info.get('zoneNames', [])
            district = zone_names[0] if zone_names else ''
            address = position_info.get('address', '')

            # 经纬度 - 在 mapCoordinate 里
            map_coords = position_info.get('mapCoordinate', [])
            lat = 0
            lon = 0
            if map_coords:
                lat = float(map_coords[0].get('latitude', 0))
                lon = float(map_coords[0].get('longitude', 0))

            # 评分 - commentScore 是字符串，如 "4.8"
            comment_info = hotel_info.get('commentInfo', {})
            score_raw = comment_info.get('commentScore', 0)
            try:
                score = float(score_raw) if score_raw else 0
            except (ValueError, TypeError):
                score = 0

            # 评论数 - commenterNumber 是字符串如 "2,342条点评"
            commenter_num = comment_info.get('commenterNumber', '0')
            comment_count = 0
            try:
                # 提取数字部分
                import re
                nums = re.findall(r'[\d,]+', str(commenter_num))
                if nums:
                    comment_count = int(nums[0].replace(',', ''))
            except Exception:
                pass

            # 评分描述
            comment_desc = comment_info.get('commentDescription', '')

            # 一句话评论
            one_sentence = comment_info.get('oneSentenceComment', [])
            score_tag = one_sentence[0].get('tagTitle', '') if one_sentence else ''

            # 分项评分 - number 也是字符串
            sub_scores = comment_info.get('subScore', [])
            def _parse_score(idx):
                if len(sub_scores) > idx:
                    raw = sub_scores[idx].get('number', 0)
                    try:
                        return float(raw) if raw else 0
                    except (ValueError, TypeError):
                        return 0
                return 0

            env_score = _parse_score(2)      # 环境
            hygiene_score = _parse_score(0)   # 卫生
            service_score = _parse_score(3)   # 服务
            facility_score = _parse_score(1)  # 设施

            # 星级/钻级 - hotelStar.star 是 int
            hotel_star = hotel_info.get('hotelStar', {})
            star = hotel_star.get('star', 0) if isinstance(hotel_star, dict) else 0
            try:
                star = int(star) if star else 0
            except (ValueError, TypeError):
                star = 0

            # 最低价格和房间名
            min_price = 0
            room_name = ''
            tags = []
            room_prices: List[tuple[str, float]] = []

            if room_info_list:
                for room in room_info_list:
                    price_info = room.get('priceInfo', {})
                    price = price_info.get('price', 0)
                    if price and (min_price == 0 or price < min_price):
                        min_price = price
                    room_summary = room.get('summary', {})
                    rn = room_summary.get('saleRoomName', '')
                    if rn and not room_name:
                        room_name = rn
                    if rn and isinstance(price, (int, float)) and price > 0:
                        room_prices.append((rn, float(price)))

                    # 收集标签
                    room_tags = room.get('roomTags', {})
                    for tag_type in ['advantageTags', 'promotionTags', 'discountTags', 'encourageTags']:
                        tag_list = room_tags.get(tag_type, [])
                        for tag in tag_list:
                            tag_title = tag.get('tagTitle', '')
                            if tag_title and tag_title not in tags:
                                tags.append(tag_title)

                if room_prices:
                    selected_room_price = self._select_room_price(room_prices, target_room_name)
                    if selected_room_price:
                        room_name, min_price = selected_room_price
                    elif target_room_name:
                        min_price = 0

            return {
                'hotel_id': hotel_id,
                'ctrip_hotel_id': hotel_id,
                'hotel_name': hotel_name,
                'star_rating': star,
                'score': score,
                'price_yuan': float(min_price) if isinstance(min_price, (int, float)) else 0,
                'price': float(min_price) if isinstance(min_price, (int, float)) else 0,
                'room_name': room_name,
                'address': address,
                'district': district,
                'lat': lat,
                'lon': lon,
                'comment_count': comment_count,
                'comment_desc': comment_desc,
                'score_tag': score_tag,
                'env_score': env_score,
                'hygiene_score': hygiene_score,
                'service_score': service_score,
                'facility_score': facility_score,
                'tags': tags[:10] if tags else [],
                'image': image,
                'source': 'ctrip_api',
            }

        except Exception as e:
            logger.warning(f"提取酒店信息失败: {e}")
            return None


# 兼容旧的 CtripHotelDrission 接口名
CtripHotelDrission = CtripHotelSpider


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    spider = CtripHotelSpider()
    hotels = spider.search_hotels(
        city_name="上海",
        checkin="2026-04-18",
        checkout="2026-04-19",
        hotel_name="桔子酒店真如"
    )

    if hotels:
        logger.info("[Spider][CtripHotel] 成功获取 %d 条酒店", len(hotels))
        for h in hotels[:20]:
            logger.info(
                "[Spider][CtripHotel] %s ¥%s 评分%s %s",
                h["hotel_name"],
                h["price"],
                h["score"],
                h["district"],
            )
            if h['tags']:
                logger.info("[Spider][CtripHotel] 标签: %s", ", ".join(h["tags"][:5]))
    else:
        logger.info("[Spider][CtripHotel] 未获取到酒店（可能需要设置Cookie）")
