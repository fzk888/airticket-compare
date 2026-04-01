"""基础爬虫类 - 基于 Playwright"""
import asyncio
import random
from abc import ABC, abstractmethod
from fake_useragent import UserAgent
from loguru import logger
from config import PLATFORM_TIMEOUT, REQUEST_DELAY, MAX_RETRIES, RETRY_DELAY

class BaseScraper(ABC):
    """爬虫基类 - 使用 Playwright 模拟浏览器"""

    def __init__(self):
        self.ua = UserAgent()
        self.timeout = PLATFORM_TIMEOUT * 1000  # Playwright 用毫秒

    async def intercept_api(self, page, url_pattern: str, timeout: int = None):
        """拦截指定 API 响应，返回 JSON 数据"""
        timeout = timeout or self.timeout
        try:
            async with page.expect_response(
                lambda resp: url_pattern in resp.url,
                timeout=timeout
            ) as resp_info:
                response = await resp_info.value
                return await response.json()
        except Exception as e:
            logger.warning(f"拦截 API 超时: {url_pattern} - {e}")
            return None

    @abstractmethod
    async def search_flights(self, from_city: str, to_city: str,
                            date: str, **kwargs):
        """搜索航班（子类实现）"""
        pass
