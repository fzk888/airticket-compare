"""
飞猪酒店 FlyAI 客户端

使用 FlyAI CLI 查询飞猪实时酒店数据。

搬自 RideClawAPI app/clients/spiders/fliggy_hotel_flyai_spider.py。
改动：
- 移除 app.config.get_settings 依赖，改为从环境变量读取 FLYAI_BIN / FLYAI_API_KEY；
- import 改为 crawlers.core 路径。
抓取逻辑零改动。
"""
import json
import logging
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional
import requests

from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)

# FlyAI CLI 配置（环境变量优先，与 airticket 现有 scrapers/fliggy.py 一致）
FLYAI_BIN = os.environ.get("FLYAI_BIN", "flyai")
FLYAI_API_KEY = os.environ.get("FLYAI_API_KEY", "")

STAR_TEXT_TO_NUM = {
    "经济型": 1, "舒适型": 2, "高档型": 3, "豪华型": 4, "五星/豪华": 5,
    "五星级": 5, "四星级": 4, "三星级": 3, "二星级": 2,
    "五星": 5, "四星": 4, "三星": 3, "二星": 2, "一星": 1,
}


class FliggyHotelFlyAISpider:
    """飞猪酒店客户端 - 基于 FlyAI CLI"""

    def __init__(self):
        self.flyai_bin = FLYAI_BIN

    def search_hotels(
        self,
        city_name: str,
        checkin: str,
        checkout: str,
        hotel_name: Optional[str] = None,
        timeout: int = 60,
    ) -> List[Dict[str, Any]]:
        """搜索酒店并返回项目统一格式的结果列表。"""
        self._ensure_flyai_available()

        args = [
            "search-hotel",
            "--dest-name", city_name,
            "--check-in-date", checkin,
            "--check-out-date", checkout,
            "--sort", "price_asc",
        ]
        if hotel_name:
            args.extend(["--key-words", hotel_name])

        data = self._run_flyai(args, timeout=timeout)
        hotels = self._parse_response(data)
        if hotels:
            hotels.sort(key=lambda x: x.get("price_yuan") or 999999)
            return hotels
        if not hotel_name:
            return hotels

        logger.info(
            "FlyAI search-hotels 无结构化酒店价格: city=%s hotel=%s message=%s，尝试 keyword-search",
            city_name,
            hotel_name,
            data.get("message"),
        )
        keyword_data = self._run_flyai(
            ["keyword-search", "--query", f"{city_name} {hotel_name}"],
            timeout=timeout,
        )
        hotels = self._parse_keyword_response(keyword_data)
        hotels.sort(key=lambda x: x.get("price_yuan") or 999999)
        return hotels

    def _ensure_flyai_available(self) -> None:
        if shutil.which(self.flyai_bin):
            return
        raise RuntimeError(
            f"未找到 FlyAI CLI 可执行文件: {self.flyai_bin}。"
            "请先安装 `@fly-ai/flyai-cli`，或在环境变量中配置 FLYAI_BIN。"
        )

    def _run_flyai(self, args: List[str], timeout: int) -> Dict[str, Any]:
        cmd = [self.flyai_bin, *args]
        use_shell = platform.system() == "Windows"
        run_kwargs: Dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "shell": use_shell,
            "env": self._build_env(),
        }
        if use_shell:
            completed = subprocess.run(" ".join(cmd), **run_kwargs)
        else:
            completed = subprocess.run(cmd, **run_kwargs)

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()

        if completed.returncode != 0:
            raise RuntimeError(stderr or stdout or "FlyAI CLI 调用失败")
        if not stdout or "Usage:" in stdout:
            raise RuntimeError("FlyAI CLI 返回无效输出")

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"FlyAI 返回 JSON 解析失败: {e}") from e

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        api_key = FLYAI_API_KEY
        if api_key:
            env["FLYAI_API_KEY"] = api_key
        return env

    def _parse_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        items = data.get("data", {}).get("itemList", []) if data.get("data") else []
        if not items:
            return []

        hotels: List[Dict[str, Any]] = []
        for item in items:
            hotel_id = str(item.get("shId") or item.get("hotelId") or "").strip()
            hotel_name = (item.get("name") or item.get("hotelName") or "").strip()
            if not hotel_id and not hotel_name:
                continue

            star_type = item.get("star") or ""
            price_yuan = self._extract_price_yuan(item)
            interests_poi = item.get("interestsPoi") or ""

            hotels.append({
                "hotel_id": hotel_id,
                "hotel_name": hotel_name,
                "address": item.get("address") or "",
                "star_type": star_type,
                "star_rating": STAR_TEXT_TO_NUM.get(star_type, 0) if star_type else 0,
                "商圈": interests_poi,
                "score": 0,
                "score_text": "",
                "price_yuan": price_yuan,
                "price": yuan_to_fen(price_yuan) if price_yuan else 0,
                "image": item.get("mainPic") or "",
                "main_picture": item.get("mainPic") or "",
                "tags": [interests_poi] if interests_poi else [],
                "detail_url": item.get("detailUrl") or "",
                "brand_name": item.get("brandName") or "",
                "decoration_time": item.get("decorationTime") or "",
                "latitude": self._to_float(item.get("latitude")),
                "longitude": self._to_float(item.get("longitude")),
                "source": "fliggy_flyai",
            })

        hotels.sort(key=lambda x: x.get("price_yuan") or 999999)
        return hotels

    def _parse_keyword_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        items = data.get("data", {}).get("itemList", []) if data.get("data") else []
        if not items:
            return []

        hotels: List[Dict[str, Any]] = []
        for item in items:
            info = item.get("info") or item
            hotel_name = (info.get("title") or info.get("name") or "").strip()
            if not hotel_name:
                continue

            star_type = str(info.get("star") or "")
            price_yuan = self._extract_price_yuan(info)
            hotels.append({
                "hotel_id": str(info.get("shId") or info.get("hotelId") or "").strip(),
                "hotel_name": hotel_name,
                "address": info.get("address") or "",
                "star_type": star_type,
                "star_rating": STAR_TEXT_TO_NUM.get(star_type, 0) if star_type else 0,
                "商圈": "",
                "score": 0,
                "score_text": info.get("scoreDesc") or "",
                "price_yuan": price_yuan,
                "price": yuan_to_fen(price_yuan) if price_yuan else 0,
                "image": info.get("picUrl") or info.get("mainPic") or "",
                "main_picture": info.get("picUrl") or info.get("mainPic") or "",
                "tags": info.get("tags") or [],
                "detail_url": info.get("jumpUrl") or info.get("detailUrl") or "",
                "brand_name": "",
                "decoration_time": "",
                "latitude": self._to_float(info.get("latitude")),
                "longitude": self._to_float(info.get("longitude")),
                "source": "fliggy_flyai_keyword",
                "has_candidate": True,
                "candidate_only": price_yuan <= 0,
            })

        hotels.sort(key=lambda x: x.get("price_yuan") or 999999)
        return hotels

    @staticmethod
    def extract_shid(value: str) -> str:
        text = str(value or "")
        if text.isdigit() and len(text) >= 5:
            return text
        for pattern in [
            r"(?:shid|shId|hotelId|hid)[=:%22\"']+(\d{5,})",
            r"_pk=hotel_(\d{5,})",
            r"hotel_(\d{5,})",
        ]:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def resolve_shid_from_url(url: str) -> str:
        shid = FliggyHotelFlyAISpider.extract_shid(url)
        if shid:
            return shid
        if not url:
            return ""
        try:
            resp = requests.get(
                url,
                allow_redirects=True,
                timeout=20,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
                    ),
                },
            )
        except requests.RequestException as e:
            logger.info("飞猪短链展开失败: url=%s error=%s", url, e)
            return ""
        return (
            FliggyHotelFlyAISpider.extract_shid(resp.url)
            or FliggyHotelFlyAISpider.extract_shid(resp.text)
        )

    @staticmethod
    def _extract_price_yuan(item: Dict[str, Any]) -> float:
        for key in (
            "price",
            "priceText",
            "priceDesc",
            "priceStr",
            "displayPrice",
            "minPrice",
            "lowestPrice",
            "salePrice",
            "finalPrice",
            "amount",
        ):
            price_yuan = FliggyHotelFlyAISpider._to_price_yuan(item.get(key))
            if price_yuan > 0:
                return price_yuan

        price_info = item.get("priceInfo")
        if isinstance(price_info, dict):
            return FliggyHotelFlyAISpider._extract_price_yuan(price_info)
        return 0.0

    @staticmethod
    def _to_price_yuan(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value or "").strip().replace("￥", "¥").replace(",", "")
        if not text or any(mask in text.lower() for mask in ("x", "*")):
            return 0.0

        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return 0.0

        try:
            return float(match.group(0))
        except ValueError:
            return 0.0

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
