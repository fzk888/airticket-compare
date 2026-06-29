"""
飞猪通用基础设施

搬自 RideClawAPI app/clients/spiders/fliggy_base.py。
唯一改动：DEFAULT_COOKIE_FILE 路径调整为指向 airticket 仓库 config/fliggy_cookie.txt。
其余逻辑零改动。

提供浏览器初始化、Cookie注入、mtop API调用、资源清理等公共能力，
供 flight / hotel 下的爬虫复用，避免重复代码。
"""
import os
import time
import json
import hashlib
import logging
import tempfile
from typing import Optional, Dict, Any, List

import requests

from DrissionPage import ChromiumPage, ChromiumOptions

logger = logging.getLogger(__name__)

# Cookie 文件默认路径（仓库根/config/fliggy_cookie.txt）
DEFAULT_COOKIE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config', 'fliggy_cookie.txt'
)

# 需要注入 Cookie 的域名列表
COOKIE_DOMAINS = [
    '.fliggy.com',
    '.alitrip.com',
    '.taobao.com',
    '.alibaba.com',
]

# mtop API 配置
MTOP_APP_KEY = "12574478"
MTOP_H5_GATEWAY = "https://h5api.m.taobao.com/h5/"
MTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Referer": "https://m.fliggy.com/",
    "Origin": "https://m.fliggy.com",
}


def parse_browser_cookies(cookie_str: str, default_domains: List[str]) -> List[Dict[str, Any]]:
    """兼容浏览器导出的 JSON Cookie 和普通 `a=b; c=d` Cookie 字符串。"""
    if not cookie_str:
        return []

    text = cookie_str.strip()
    cookies: List[Dict[str, Any]] = []

    if text.startswith("[") or text.startswith("{"):
        try:
            raw = json.loads(text)
            if isinstance(raw, dict):
                raw = raw.get("cookies") or raw.get("data") or [raw]
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    value = str(item.get("value") or "")
                    if not name:
                        continue
                    domain = str(item.get("domain") or "").strip()
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": domain or None,
                        "path": item.get("path") or "/",
                        "secure": bool(item.get("secure")) if item.get("secure") is not None else None,
                        "httpOnly": bool(item.get("httpOnly")) if item.get("httpOnly") is not None else None,
                    })
                return cookies
        except json.JSONDecodeError:
            logger.warning("Cookie JSON 解析失败，尝试按普通 Cookie 字符串解析")

    for item in text.replace("\n", ";").split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        for domain in default_domains:
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
            })

    return cookies


class FliggyBrowserMixin:
    """飞猪浏览器公共能力 Mixin

    子类只需:
    1. 调用 self._ensure_page(headless) 初始化浏览器
    2. 调用 self._inject_cookies(cookie_str) 注入 Cookie
    3. 调用 self._close_page() 清理资源
    """

    def __init__(self):
        self.page: Optional[ChromiumPage] = None
        self._user_data_dir: Optional[str] = None

    def _ensure_page(self, headless: bool = True, user_dir_name: str = 'drission_fliggy'):
        """初始化浏览器（幂等，已存在则跳过）"""
        if self.page:
            return

        co = ChromiumOptions()
        if headless:
            co.headless()
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--window-size=1920,1080')
        co.set_argument('--remote-allow-origins=*')
        co.set_argument('--disable-extensions')

        # 独立用户数据目录，避免和已打开 Chrome 冲突
        self._user_data_dir = os.path.join(tempfile.gettempdir(), user_dir_name)
        os.makedirs(self._user_data_dir, exist_ok=True)
        co.set_user_data_path(self._user_data_dir)
        co.auto_port()

        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )

        self.page = ChromiumPage(co)
        logger.info("浏览器初始化成功 (user_dir=%s)", user_dir_name)

    def _load_cookie_from_file(self, cookie_path: str = None) -> Optional[str]:
        """从文件加载 Cookie 字符串"""
        path = cookie_path or DEFAULT_COOKIE_FILE
        if not os.path.exists(path):
            logger.warning("Cookie 文件不存在: %s", path)
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content and not content.startswith('#'):
                return content
        except Exception as e:
            logger.warning("读取 Cookie 文件失败: %s", e)
        return None

    def _inject_cookies(self, cookie_str: str = None):
        """注入 Cookie（优先 CDP，失败回退到页面 API）

        Args:
            cookie_str: Cookie 字符串。为空时从文件加载。
        """
        if not cookie_str:
            cookie_str = self._load_cookie_from_file()
        if not cookie_str:
            logger.info("无 Cookie，跳过注入")
            return

        # 导航到 about:blank 以设置 Cookie
        try:
            self.page.get("about:blank")
        except Exception:
            pass

        # 方案1: CDP Network.setCookie（不需要先访问目标域名）
        try:
            count = 0
            cookies = parse_browser_cookies(cookie_str, COOKIE_DOMAINS)
            for cookie in cookies:
                domains = [cookie.get("domain")] if cookie.get("domain") else COOKIE_DOMAINS
                for domain in domains:
                    try:
                        kwargs = {
                            "name": cookie["name"],
                            "value": cookie["value"],
                            "domain": domain,
                            "path": cookie.get("path") or "/",
                        }
                        if cookie.get("secure") is not None:
                            kwargs["secure"] = cookie["secure"]
                        if cookie.get("httpOnly") is not None:
                            kwargs["httpOnly"] = cookie["httpOnly"]
                        self.page.run_cdp('Network.setCookie', **kwargs)
                    except Exception:
                        pass
                count += 1
            logger.info("Cookie 注入完成 (CDP), %d 个", count)
            return
        except Exception as e:
            logger.warning("CDP 注入 Cookie 失败，回退到页面 API: %s", e)

        # 方案2: 页面 set.cookies（需要先在目标域名下）
        try:
            self.page.get("https://sjipiao.fliggy.com/favicon.ico")
            time.sleep(0.5)
        except Exception:
            pass

        count = 0
        for cookie in parse_browser_cookies(cookie_str, ['.fliggy.com']):
            try:
                self.page.set.cookies({
                    'name': cookie["name"],
                    'value': cookie["value"],
                    'domain': cookie.get("domain") or '.fliggy.com',
                    'path': cookie.get("path") or '/',
                })
                count += 1
            except Exception:
                pass
        logger.info("Cookie 注入完成 (回退), %d 个", count)

    def _close_page(self):
        """关闭浏览器（安全关闭，不抛异常）"""
        if self.page:
            try:
                self.page.quit()
            except Exception as e:
                logger.debug("关闭浏览器异常: %s", e)
            self.page = None


def _parse_cookie_str(cookie_str: str) -> Dict[str, str]:
    """将 Cookie 字符串解析为字典"""
    cookies = {}
    for item in parse_browser_cookies(cookie_str, COOKIE_DOMAINS):
        cookies[item["name"]] = item["value"]
    return cookies


def mtop_call(
    api_name: str,
    data_dict: Dict[str, Any],
    cookie_str: str = None,
) -> Optional[Dict[str, Any]]:
    """
    调用飞猪 mtop API（通用签名 + token 刷新）

    Args:
        api_name: API 名称（如 "mtop.trip.hotel.hotelDetail"）
        data_dict: 业务参数字典
        cookie_str: Cookie 字符串（为空时从文件加载）

    Returns:
        响应 JSON dict，失败返回 None
    """
    if not cookie_str:
        cookie_str = _load_cookie_from_file_static()
    if not cookie_str:
        logger.warning("mtop_call: 无 Cookie，跳过调用")
        return None

    cookies = _parse_cookie_str(cookie_str)
    token = cookies.get("_m_h5_tk", "").split("_")[0]
    if not token:
        logger.warning("mtop_call: Cookie 中无 _m_h5_tk")
        return None

    t = str(int(time.time() * 1000))
    data = json.dumps(data_dict, separators=(",", ":"))
    sign_str = f"{token}&{t}&{MTOP_APP_KEY}&{data}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()

    params = {
        "jsv": "2.7.2",
        "appKey": MTOP_APP_KEY,
        "t": t,
        "sign": sign,
        "api": api_name,
        "v": "1.0",
        "type": "originaljson",
        "dataType": "json",
        "timeout": "20000",
        "H5Request": "true",
    }

    url = f"{MTOP_H5_GATEWAY}{api_name}/1.0/"

    try:
        resp = requests.post(
            url,
            params=params,
            data={"data": data},
            cookies=cookies,
            headers=MTOP_HEADERS,
            timeout=15,
        )
        result = resp.json()
        ret = str(result.get("ret", []))

        # Token 过期，刷新后重试一次
        if "TOKEN_EXOIRED" in ret or "FAIL_SYS_TOKEN_EXOIRED" in ret:
            logger.info("mtop token 过期，尝试刷新...")
            new_cookies = _refresh_token(cookies)
            if new_cookies:
                # 用新 token 重试
                new_token = new_cookies.get("_m_h5_tk", "").split("_")[0]
                if new_token:
                    t2 = str(int(time.time() * 1000))
                    sign2 = hashlib.md5(
                        f"{new_token}&{t2}&{MTOP_APP_KEY}&{data}".encode()
                    ).hexdigest()
                    params["t"] = t2
                    params["sign"] = sign2

                    resp2 = requests.post(
                        url,
                        params=params,
                        data={"data": data},
                        cookies=new_cookies,
                        headers=MTOP_HEADERS,
                        timeout=15,
                    )
                    result = resp2.json()
                    ret2 = str(result.get("ret", []))
                    if "SUCCESS" in ret2:
                        return result
                    logger.warning("mtop token 刷新后仍失败: %s", ret2)
                    return None

        if "SUCCESS" in ret:
            return result

        logger.warning("mtop_call(%s) 返回: %s", api_name, ret)
        return None

    except Exception as e:
        logger.error("mtop_call(%s) 异常: %s", api_name, e)
        return None


def _refresh_token(cookies: Dict[str, str]) -> Optional[Dict[str, str]]:
    """通过访问飞猪首页刷新 _m_h5_tk"""
    try:
        resp = requests.get(
            "https://m.fliggy.com/",
            cookies=cookies,
            headers=MTOP_HEADERS,
            timeout=15,
        )
        new_cookies = dict(cookies)
        for c in resp.cookies:
            if "h5_tk" in c.name:
                new_cookies[c.name] = c.value
                logger.info("token 刷新成功: %s=%s...", c.name, c.value[:16])
        return new_cookies
    except Exception as e:
        logger.warning("刷新 token 失败: %s", e)
        return None


def _load_cookie_from_file_static(cookie_path: str = None) -> Optional[str]:
    """静态方法：从文件加载 Cookie 字符串"""
    path = cookie_path or DEFAULT_COOKIE_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if content and not content.startswith('#'):
            return content
    except Exception:
        pass
    return None
