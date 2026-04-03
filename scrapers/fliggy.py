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
        flight_type_filter = kwargs.get("flight_type", "all")
        try:
            logger.info(f"{self.platform}: 查询 {from_city} -> {to_city} ({date}) [筛选:{flight_type_filter}]")

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
            return self.parse_response(data, flight_type_filter=flight_type_filter)

        except subprocess.TimeoutExpired:
            logger.error(f"{self.platform} 查询超时")
            return {"platform": self.platform, "status": "failed", "error": "查询超时"}
        except json.JSONDecodeError as e:
            logger.error(f"{self.platform} JSON 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": "数据解析失败"}
        except Exception as e:
            logger.error(f"{self.platform} 查询失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": str(e)[:100]}

    async def search_by_flight_no(self, origin: str, transport_no: str, date: str, destination: str = None):
        """按航班号查询指定航班价格。有目的地时先查直飞，找不到则回退到中转模式过滤"""
        try:
            logger.info(f"{self.platform}: 按航班号查询 {transport_no} 从 {origin} ({date})")
            import platform as _platform
            is_win = (_platform.system() == "Windows")

            # 直飞查询（--transport-no 只对直飞有效）
            cmd = ["flyai", "search-flight", "--origin", origin,
                   "--transport-no", transport_no, "--dep-date", date]
            if destination:
                cmd += ["--destination", destination]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=is_win)

            if result.returncode == 0 and result.stdout and "Usage:" not in result.stdout:
                data = json.loads(result.stdout)
                parsed = self._parse_flight_no_response(data, transport_no)
                if parsed.get("status") == "success":
                    return parsed

            # 直飞找不到且有目的地 → 中转模式，按第一段航班号过滤
            if destination:
                logger.info(f"{self.platform}: 直飞未找到，尝试中转模式查询 {transport_no}")
                cmd2 = ["flyai", "search-flight", "--origin", origin, "--destination", destination,
                        "--dep-date", date, "--journey-type", "2"]
                result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30, shell=is_win)
                if result2.returncode == 0 and result2.stdout and "Usage:" not in result2.stdout:
                    data2 = json.loads(result2.stdout)
                    return self._parse_flight_no_response(data2, transport_no)

            msg = "无航班数据"
            try:
                msg = json.loads(result.stdout).get("message", msg)
            except Exception:
                pass
            return {"platform": self.platform, "status": "failed", "error": msg}

        except subprocess.TimeoutExpired:
            return {"platform": self.platform, "status": "failed", "error": "查询超时"}
        except json.JSONDecodeError:
            return {"platform": self.platform, "status": "failed", "error": "数据解析失败"}
        except Exception as e:
            return {"platform": self.platform, "status": "failed", "error": str(e)[:100]}

    def _parse_flight_no_response(self, data, transport_no: str):
        """解析按航班号查询的响应，按第一段航班号过滤"""
        try:
            items = data.get("data", {}).get("itemList", []) if data.get("data") else []
            if not items:
                msg = data.get("message", "无航班数据")
                return {"platform": self.platform, "status": "failed", "error": msg}

            # 按第一段航班号过滤
            no_upper = transport_no.upper()
            matched = [i for i in items
                       if i["journeys"][0]["segments"][0]["marketingTransportNo"].upper() == no_upper]
            if not matched:
                return {"platform": self.platform, "status": "failed", "error": "未找到该航班号"}
            item = min(matched, key=lambda i: float(i["ticketPrice"]))
            journey = item["journeys"][0]
            first_seg = journey["segments"][0]
            last_seg = journey["segments"][-1]
            price = float(item["ticketPrice"])

            return {
                "platform": self.platform,
                "status": "success",
                "transport_no": transport_no,
                "price": int(price),
                "currency": "CNY",
                "flight": {
                    "number": first_seg["marketingTransportNo"],
                    "airline": first_seg["marketingTransportName"],
                    "from_city": first_seg["depCityName"],
                    "to_city": last_seg["arrCityName"],
                    "from_airport": first_seg["depStationName"],
                    "to_airport": last_seg["arrStationName"],
                    "departure": first_seg["depDateTime"].split(" ")[1][:5],
                    "arrival": last_seg["arrDateTime"].split(" ")[1][:5],
                    "duration": f"{journey['totalDuration']}分钟",
                    "seat_class": first_seg.get("seatClassName", ""),
                    "journey_type": journey["journeyType"],
                },
                "url": item.get("jumpUrl", "https://www.fliggy.com")
            }
        except Exception as e:
            logger.error(f"{self.platform} 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": f"解析失败: {e}"}

    def parse_response(self, data, flight_type_filter: str = "all"):
        """解析 FlyAI 响应

        Args:
            data: API 返回的原始数据
            flight_type_filter: 筛选类型 "all" | "direct" | "connecting"
        """
        try:
            items = data.get("data", {}).get("itemList", [])
            if not items:
                return {"platform": self.platform, "status": "failed", "error": "无航班数据"}

            # 按类型筛选
            if flight_type_filter == "direct":
                filtered = [x for x in items if x["journeys"][0]["journeyType"] == "直达"]
                items = filtered if filtered else items
            elif flight_type_filter == "connecting":
                filtered = [x for x in items if x["journeys"][0]["journeyType"] == "中转"]
                items = filtered if filtered else items

            # 找到真正的最低价（遍历所有有效航班）
            lowest = min(items, key=lambda x: float(x["ticketPrice"]))
            journey = lowest["journeys"][0]
            first_seg = journey["segments"][0]
            last_seg = journey["segments"][-1]  # 中转航班取最后一个航段

            price = float(lowest["ticketPrice"])
            is_connecting = journey["journeyType"] == "中转"

            # 构建所有符合筛选条件的航班列表（用于展示）
            all_flights = []
            for x in items[:10]:  # 最多返回10条
                j = x["journeys"][0]
                first = j["segments"][0]
                last = j["segments"][-1]
                is_conn = j["journeyType"] == "中转"
                all_flights.append({
                    "price": int(float(x["ticketPrice"])),
                    "flightNo": first["marketingTransportNo"],
                    "airline": first["marketingTransportName"],
                    "depTime": first["depDateTime"].split(" ")[1][:5],
                    # 中转航班的到达时间是最后一个航段的到达时间
                    "arrTime": last["arrDateTime"].split(" ")[1][:5],
                    "duration": f"{j['totalDuration']}分钟",
                    "from_airport": first["depStationName"],
                    "to_airport": last["arrStationName"],
                    "journey_type": j["journeyType"],
                    "segments_count": len(j["segments"])
                })

            return {
                "platform": self.platform,
                "status": "success",
                "lowest_price": int(price),
                "tax": 0,
                "currency": "CNY",
                "flight": {
                    "number": first_seg["marketingTransportNo"],
                    "airline": first_seg["marketingTransportName"],
                    "departure": first_seg["depDateTime"].split(" ")[1][:5],
                    # 中转航班的到达时间是最后一个航段的到达时间和目的地
                    "arrival": last_seg["arrDateTime"].split(" ")[1][:5],
                    "duration": f"{journey['totalDuration']}分钟",
                    "from_airport": first_seg["depStationName"],
                    "to_airport": last_seg["arrStationName"],
                    "journey_type": journey["journeyType"],
                    "segments_count": len(journey["segments"])
                },
                "flights_list": all_flights,
                "url": lowest.get("jumpUrl", "https://www.fliggy.com")
            }

        except Exception as e:
            logger.error(f"{self.platform} 解析失败: {e}")
            return {"platform": self.platform, "status": "failed", "error": f"解析失败: {e}"}
