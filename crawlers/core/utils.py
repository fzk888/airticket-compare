"""金额格式化工具

搬自 RideClawAPI app/utils/utils.py 的 yuan_to_fen / fen_to_yuan（纯函数）。
不引入 app.* 依赖。
"""
from typing import Optional, Union


def fen_to_yuan(fen: Optional[Union[int, float]]) -> float:
    """将分转换为元（保留2位小数）。"""
    if fen is None:
        return 0.00
    return round(fen / 100, 2)


def yuan_to_fen(yuan: Optional[Union[int, float]]) -> int:
    """将元转换为分（四舍五入）。"""
    if yuan is None:
        return 0
    return int(round(yuan * 100))
