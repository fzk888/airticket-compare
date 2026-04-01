"""配置文件"""

# 超时设置
PLATFORM_TIMEOUT = 15  # 单平台超时（秒）
TOTAL_TIMEOUT = 45     # 总查询超时（秒）

# 重试设置
MAX_RETRIES = 2
RETRY_DELAY = 2  # 重试延迟（秒）

# 请求延迟
REQUEST_DELAY = (1, 2)  # 随机延迟范围（秒）

# 舱位映射
CABIN_CLASS_MAP = {
    "economy": "经济舱",
    "business": "商务舱",
    "first": "头等舱"
}
