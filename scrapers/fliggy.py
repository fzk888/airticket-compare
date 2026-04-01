"""飞猪爬虫 - 使用 FlyAI CLI"""
import json
import subprocess
import os
from .base import BaseScraper
from loguru import logger

class FliggyScraper(BaseScraper):
    """飞猪机票爬虫 - 使用 FlyAI CLI"""

    def __init__(self):
        super().__init__()
        self.platform = "飞猪"

    async def search_flights(self, from_city: str, to_city: str, date: str, **kwargs):
        """使用 FlyAI CLI 查询航班"""
        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date})")

            # Windows 和 WSL 兼容的 flyai 调用
            import platform
            if platform.system() == "Windows":
                # Windows: 直接调用 flyai 命令（npm 已在 PATH 中）
                cmd = ["flyai", "search-flight",
                       "--origin", from_city,
                       "--destination", to_city,
                       "--dep-date", date,
                       "--sort-type", "3"]
                # Windows 需要 shell=True 来找到 npm 命令
                result = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=30, shell=True)
            else:
                # WSL/Linux: 直接调用
                cmd = ["flyai", "search-flight",
                       "--origin", from_city,
                       "--destination", to_city,
                       "--dep-date", date,
                       "--sort-type", "3"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.error(f"{self.platform} CLI 错误: {result.stderr}")
                return {"platform": self.platform, "status": "failed", "error": result.stderr[:100]}

            # 检查输出是否为空或是帮助信息
            if not result.stdout or "Usage:" in result.stdout:
                logger.error(f"{self.platform} CLI 返回无效输出")
                return {"platform": self.platform, "status": "failed", "error": "CLI 调用失败"}

            data = json.loads(result.stdout)
            return self.parse_response(data)

        except subprocess.TimeoutExpired:
            logger.error(f"{self.platform} 查询超时")
            return {"platform": self.platform, "status": "failed", "error": "查询超时"}
        except json.JSONDecodeError as e:
            logger.error(f"{self.platform} JSON 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": "数据解析失败"}
        except Exception as e:
            logger.error(f"{self.platform} 查询失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": str(e)[:100]}

    def parse_response(self, data):
        """解析 FlyAI 响应"""
        try:
            items = data.get("data", {}).get("itemList", [])
            if not items:
                return {"platform": self.platform, "status": "failed", "error": "无航班数据"}

            # 找到真正的最低价（遍历所有航班）
            lowest = min(items, key=lambda x: float(x["ticketPrice"]))
            journey = lowest["journeys"][0]
            segment = journey["segments"][0]

            price = float(lowest["ticketPrice"])

            return {
                "platform": self.platform,
                "status": "success",
                "lowest_price": int(price),
                "tax": 0,
                "currency": "CNY",
                "flight": {
                    "number": segment["marketingTransportNo"],
                    "airline": segment["marketingTransportName"],
                    "departure": segment["depDateTime"].split(" ")[1][:5],
                    "arrival": segment["arrDateTime"].split(" ")[1][:5],
                    "duration": f"{segment['duration']}分钟",
                    "from_airport": segment["depStationName"],
                    "to_airport": segment["arrStationName"],
                    "journey_type": journey["journeyType"]
                },
                "url": lowest.get("jumpUrl", "https://www.fliggy.com")
            }

        except Exception as e:
            logger.error(f"{self.platform} 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": f"解析失败: {e}"}
