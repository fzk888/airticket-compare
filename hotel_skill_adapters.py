"""酒店比价 async 适配胶水。

RideClaw 搬来的酒店爬虫是同步阻塞的（DrissionPage / requests / subprocess）。
这里用 asyncio.to_thread 把每个平台的同步调用包成协程，
让 hotel_skill.py 能用 asyncio.gather 三平台并发，同时不阻塞事件循环。

返回结构对齐 airticket 现有机票比价的 dict 风格：
  {
    "platform": "携程" | "飞猪" | "同程",
    "status":   "success" | "failed",
    "lowest_price": float,           # 各房型最低价
    "hotel": { ... },                # 最低价房型详情
    "hotels_list": [ ... ],          # 全部候选（按价格升序，截断到 N 条）
    "total_hotels": int,
    "from_cache": False,
    "error": None | str,
  }

注意：本文件只在 RideClaw 爬虫外层套壳，不改爬虫内部任何逻辑。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from crawlers.hotel.ctrip_hotel import CtripHotelSpider
from crawlers.hotel.fliggy_hotel import FliggyHotelSpider
from crawlers.hotel.tongcheng_hotel import TongchengHotelSpider

logger = logging.getLogger(__name__)

PLATFORM_NAME = {
    "ctrip": "携程",
    "fliggy": "飞猪",
    "tongcheng": "同程",
}

MAX_HOTELS_IN_LIST = 10


def _load_cookie_file(path: str) -> Optional[str]:
    """读取 cookie 文件内容（不存在或为空返回 None）。"""
    import os
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content and not content.startswith("#"):
            return content
    except Exception as e:
        logger.warning("读取 cookie 文件失败: %s error=%s", path, e)
    return None


def _resolve_cookie(source: str, cookie_dir: str, filename: str, explicit: Optional[str]) -> Optional[str]:
    """优先用显式传入的 cookie，否则从 cookie_dir/filename 加载。"""
    if explicit:
        return explicit
    return _load_cookie_file(f"{cookie_dir}/{filename}")


def _price_yuan(hotel: Dict[str, Any]) -> float:
    """从酒店 dict 取价格（元），兼容 price_yuan / price。"""
    for key in ("price_yuan", "price"):
        value = hotel.get(key)
        try:
            price = float(value) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            return price
    return 0.0


def _normalize_platform_result(source: str, hotels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把爬虫返回的酒店列表归一为统一的比价 dict。"""
    platform = PLATFORM_NAME.get(source, source)
    priced = [h for h in (hotels or []) if isinstance(h, dict) and _price_yuan(h) > 0]
    priced.sort(key=lambda h: _price_yuan(h))

    if not priced:
        return {
            "platform": platform,
            "status": "failed",
            "lowest_price": 0,
            "hotel": {},
            "hotels_list": [],
            "total_hotels": len(hotels or []),
            "from_cache": False,
            "error": "无有效价格（可能 Cookie 失效或无库存）",
        }

    lowest = priced[0]
    return {
        "platform": platform,
        "status": "success",
        "lowest_price": _price_yuan(lowest),
        "hotel": {
            "hotel_name": lowest.get("hotel_name") or "",
            "price_yuan": _price_yuan(lowest),
            "room_name": lowest.get("room_name") or "",
            "star_rating": lowest.get("star_rating") or 0,
            "score": lowest.get("score") or 0,
            "district": lowest.get("district") or "",
            "address": lowest.get("address") or "",
            "hotel_id": lowest.get("hotel_id") or lowest.get("ctrip_hotel_id") or "",
        },
        "hotels_list": [
            {
                "hotel_name": h.get("hotel_name") or "",
                "price_yuan": _price_yuan(h),
                "room_name": h.get("room_name") or "",
                "star_rating": h.get("star_rating") or 0,
                "score": h.get("score") or 0,
                "district": h.get("district") or "",
            }
            for h in priced[:MAX_HOTELS_IN_LIST]
        ],
        "total_hotels": len(priced),
        "from_cache": False,
        "error": None,
    }


# ────────────────── 单平台 async 包装 ──────────────────

async def search_ctrip_hotel(
    city: str,
    checkin: str,
    checkout: str,
    hotel_name: Optional[str] = None,
    cookie: Optional[str] = None,
    cookie_dir: str = "config",
) -> Dict[str, Any]:
    """携程酒店：requests 直连 API，同步，用 to_thread 包装。"""
    resolved = _resolve_cookie("ctrip", cookie_dir, "ctrip_cookie.txt", cookie)
    try:
        spider = CtripHotelSpider(cookie=resolved)
        hotels = await asyncio.to_thread(
            spider.search_hotels, city, checkin, checkout, hotel_name
        )
        return _normalize_platform_result("ctrip", hotels)
    except Exception as e:
        logger.error("携程酒店查询异常: %s", e, exc_info=True)
        return {"platform": PLATFORM_NAME["ctrip"], "status": "failed", "error": str(e)[:100],
                "lowest_price": 0, "hotel": {}, "hotels_list": [], "total_hotels": 0, "from_cache": False}


async def search_fliggy_hotel(
    city: str,
    checkin: str,
    checkout: str,
    hotel_name: Optional[str] = None,
    cookie: Optional[str] = None,
    cookie_dir: str = "config",
    headless: bool = True,
) -> Dict[str, Any]:
    """飞猪酒店：DrissionPage SSR 解析，同步，用 to_thread 包装。"""
    resolved = _resolve_cookie("fliggy", cookie_dir, "fliggy_cookie.txt", cookie)
    spider = FliggyHotelSpider(headless=headless, cookie=resolved)
    try:
        hotels = await asyncio.to_thread(spider.search_hotels, city, checkin, checkout, hotel_name)
        return _normalize_platform_result("fliggy", hotels)
    except Exception as e:
        logger.error("飞猪酒店查询异常: %s", e, exc_info=True)
        return {"platform": PLATFORM_NAME["fliggy"], "status": "failed", "error": str(e)[:100],
                "lowest_price": 0, "hotel": {}, "hotels_list": [], "total_hotels": 0, "from_cache": False}
    finally:
        await asyncio.to_thread(spider.close)


async def search_tongcheng_hotel(
    city: str,
    checkin: str,
    checkout: str,
    hotel_name: Optional[str] = None,
    cookie: Optional[str] = None,
    cookie_dir: str = "config",
    headless: bool = True,
) -> Dict[str, Any]:
    """同程酒店：DrissionPage Vue DOM 解析，同步，用 to_thread 包装。"""
    resolved = _resolve_cookie("tongcheng", cookie_dir, "tongcheng_cookie.txt", cookie)
    spider = TongchengHotelSpider(headless=headless, cookie=resolved)
    try:
        hotels = await asyncio.to_thread(
            spider.search_hotels, city, checkin, checkout, hotel_name
        )
        return _normalize_platform_result("tongcheng", hotels)
    except Exception as e:
        logger.error("同程酒店查询异常: %s", e, exc_info=True)
        return {"platform": PLATFORM_NAME["tongcheng"], "status": "failed", "error": str(e)[:100],
                "lowest_price": 0, "hotel": {}, "hotels_list": [], "total_hotels": 0, "from_cache": False}
    finally:
        await asyncio.to_thread(spider.close)


# ────────────────── 三平台并发入口 ──────────────────

DEFAULT_SOURCES = ("ctrip", "fliggy", "tongcheng")


async def compare_hotel_prices(
    city: str,
    checkin: str,
    checkout: str,
    hotel_name: Optional[str] = None,
    sources=DEFAULT_SOURCES,
    cookie_dir: str = "config",
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """三平台并发酒店比价，返回每个平台的结果 dict 列表。

    各 adapter 签名略有差异（携程走 requests 不需要 headless），这里按 source 分派。
    """
    common = dict(city=city, checkin=checkin, checkout=checkout,
                  hotel_name=hotel_name, cookie_dir=cookie_dir)
    coros = []
    for source in sources:
        if source == "ctrip":
            coros.append(search_ctrip_hotel(**common))
        elif source == "fliggy":
            coros.append(search_fliggy_hotel(**common, headless=headless))
        elif source == "tongcheng":
            coros.append(search_tongcheng_hotel(**common, headless=headless))
        else:
            logger.warning("未知酒店数据源: %s，跳过", source)
    results = await asyncio.gather(*coros, return_exceptions=False)
    return list(results)
