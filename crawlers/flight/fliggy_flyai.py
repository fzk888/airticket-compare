"""
飞猪机票 FlyAI 客户端

使用 FlyAI CLI 查询飞猪实时机票数据。

搬自 RideClawAPI app/clients/spiders/fliggy_flyai_spider.py。
改动：
- 移除 app.config.get_settings 依赖，改为从环境变量读取 FLYAI_BIN / FLYAI_API_KEY；
- import 改为 crawlers.core 路径。
抓取逻辑零改动。
"""
import json
import logging
import os
import platform
import shutil
import subprocess
from typing import List, Dict, Any, Optional

from crawlers.core.utils import yuan_to_fen

logger = logging.getLogger(__name__)

# FlyAI CLI 配置（环境变量优先，与 airticket 现有 scrapers/fliggy.py 一致）
FLYAI_BIN = os.environ.get("FLYAI_BIN", "flyai")
FLYAI_API_KEY = os.environ.get("FLYAI_API_KEY", "")


class FliggyFlyAISpider:
    """飞猪机票客户端 - 基于 FlyAI CLI"""

    def __init__(self):
        self.flyai_bin = FLYAI_BIN

    def search_flights(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        transport_no: Optional[str] = None,
        timeout: int = 60,
    ) -> List[Dict[str, Any]]:
        """搜索航班并返回项目统一格式的结果列表。"""
        self._ensure_flyai_available()

        if transport_no:
            direct_args = [
                "search-flight",
                "--origin", origin,
                "--dep-date", dep_date,
                "--transport-no", transport_no,
            ]
            if destination:
                direct_args.extend(["--destination", destination])

            direct_data = self._run_flyai(direct_args, timeout=timeout)
            direct_flights = self._parse_response(direct_data, transport_no=transport_no)
            if direct_flights:
                return direct_flights

            if not destination:
                return direct_flights

            logger.info("[FlyAI] 直飞未命中 %s，尝试中转模式回退 %s->%s", transport_no, origin, destination)
            connecting_data = self._run_flyai(
                [
                    "search-flight",
                    "--origin", origin,
                    "--destination", destination,
                    "--dep-date", dep_date,
                    "--journey-type", "2",
                ],
                timeout=timeout,
            )
            return self._parse_response(connecting_data, transport_no=transport_no)

        data = self._run_flyai(
            [
                "search-flight",
                "--origin", origin,
                "--destination", destination,
                "--dep-date", dep_date,
                "--sort-type", "3",
            ],
            timeout=timeout,
        )
        return self._parse_response(data)

    def _ensure_flyai_available(self) -> None:
        # FlyAI CLI 需要先在运行环境中安装，例如：npm i -g @fly-ai/flyai-cli
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

        logger.info("[FlyAI] cmd=%s returncode=%d", " ".join(cmd), completed.returncode)
        if stderr:
            logger.warning("[FlyAI] stderr: %s", stderr[:500])
        if completed.returncode != 0:
            raise RuntimeError(stderr or stdout or "FlyAI CLI 调用失败")
        if not stdout or "Usage:" in stdout:
            raise RuntimeError("FlyAI CLI 返回无效输出")
        logger.debug("[FlyAI] stdout(前500): %s", stdout[:500])

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"FlyAI 返回 JSON 解析失败: {e}") from e

    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if FLYAI_API_KEY:
            env["FLYAI_API_KEY"] = FLYAI_API_KEY
        return env

    def _parse_response(self, data: Dict[str, Any], transport_no: Optional[str] = None) -> List[Dict[str, Any]]:
        items = data.get("data", {}).get("itemList", []) if data.get("data") else []
        logger.info("[FlyAI] 响应 itemList 数量: %d, transport_no=%s", len(items), transport_no)
        if not items:
            logger.warning("[FlyAI] 响应无 itemList, data keys=%s", list((data.get("data") or {}).keys()))
            return []

        flights: List[Dict[str, Any]] = []
        transport_no_upper = transport_no.upper().strip() if transport_no else None
        skipped_no_journey = 0
        skipped_no_segments = 0
        skipped_transport_mismatch: List[str] = []
        skipped_no_cabin_price = 0

        for item in items:
            journey = (item.get("journeys") or [None])[0]
            if not journey:
                skipped_no_journey += 1
                continue

            segments = journey.get("segments") or []
            if not segments:
                skipped_no_segments += 1
                continue

            first_seg = segments[0]
            last_seg = segments[-1]
            current_flight_no = (first_seg.get("marketingTransportNo") or "").upper().strip()

            if transport_no_upper and current_flight_no != transport_no_upper:
                skipped_transport_mismatch.append(current_flight_no)
                continue

            dep_dt = first_seg.get("depDateTime", "")
            arr_dt = last_seg.get("arrDateTime", "")
            dep_time = dep_dt.split(" ")[1][:5] if " " in dep_dt else dep_dt[:5]
            arr_time = arr_dt.split(" ")[1][:5] if " " in arr_dt else arr_dt[:5]
            price_yuan = self._to_price_yuan(item.get("ticketPrice") or item.get("adultPrice") or 0)
            if price_yuan <= 0:
                skipped_no_cabin_price += 1
                logger.warning(
                    "[FlyAI] 航班 %s 无价格, item keys=%s",
                    current_flight_no, list(item.keys()),
                )
                continue
            seat_class_name = first_seg.get("seatClassName") or item.get("seatClassName") or ""
            cabin_class = self._normalize_cabin_class(
                first_seg.get("cabinClass") or item.get("cabinClass") or seat_class_name
            )
            cabin_name = seat_class_name or self._cabin_name_from_class(cabin_class)

            flights.append({
                "flight_no": first_seg.get("marketingTransportNo", ""),
                "flight_number": first_seg.get("marketingTransportNo", ""),
                "airline": first_seg.get("marketingTransportName", ""),
                "dep_time": dep_time,
                "arr_time": arr_time,
                "dep_airport": first_seg.get("depStationName", ""),
                "arr_airport": last_seg.get("arrStationName", ""),
                "aircraft": first_seg.get("transportName", "") or first_seg.get("aircraft", ""),
                "price_yuan": price_yuan,
                "price": yuan_to_fen(price_yuan),
                "cabin_class": cabin_class,
                "cabin_name": cabin_name,
                "journey_type": journey.get("journeyType"),
                "segments_count": len(segments),
                "from_city": first_seg.get("depCityName", ""),
                "to_city": last_seg.get("arrCityName", ""),
                "jump_url": item.get("jumpUrl", "https://www.fliggy.com"),
                "source": "fliggy_flyai",
            })

        cabin_samples = [
            {
                "flight_no": f.get("flight_no"),
                "price_yuan": f.get("price_yuan"),
                "cabin_class": f.get("cabin_class"),
                "cabin_name": f.get("cabin_name"),
            }
            for f in flights[:3]
        ]
        logger.info(
            "[FlyAI] 解析完成: input=%d, output=%d (skip_no_journey=%d, skip_no_segments=%d, skip_transport_mismatch=%d %s, skip_no_cabin_price=%d) cabin_samples=%s",
            len(items), len(flights),
            skipped_no_journey, skipped_no_segments,
            len(skipped_transport_mismatch),
            skipped_transport_mismatch[:5],
            skipped_no_cabin_price,
            json.dumps(cabin_samples, ensure_ascii=False),
        )
        flights.sort(key=lambda x: x.get("price_yuan", 999999))
        return flights[:10]


    @staticmethod
    def _normalize_cabin_class(value: Any) -> str:
        text = str(value or "").strip().upper()
        if text in {"Y", "S", "C", "F"}:
            return text
        if "头等" in text:
            return "F"
        if "商务" in text or "公务" in text:
            return "C"
        if "豪华经济" in text or "超级经济" in text:
            return "S"
        return "Y"

    @staticmethod
    def _cabin_name_from_class(cabin_class: str) -> str:
        code = (cabin_class or "").upper()
        if code == "F":
            return "头等舱"
        if code == "C":
            return "商务舱"
        if code == "S":
            return "豪华经济舱"
        return "经济舱"

    @staticmethod
    def _to_price_yuan(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("¥", "").replace(",", "")
        try:
            return float(text)
        except ValueError:
            return 0.0
