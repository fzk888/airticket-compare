"""酒店比价 Skill 主入口（携程 / 飞猪 / 同程）

独立于 skill.py（机票比价），专门调用从 RideClaw 迁移过来的酒店爬虫。
三平台并发，返回各平台最低价与候选列表。

用法：
    # 城市名按行价排序
    python hotel_skill.py 上海 2026-07-01 2026-07-02

    # 指定酒店名（精确召回，便于横向比价同一酒店）
    python hotel_skill.py 上海 2026-07-01 2026-07-02 --hotel-name 桔子酒店真如

    # 指定数据源 / cookie 目录
    python hotel_skill.py 上海 2026-07-01 2026-07-02 --sources ctrip,fliggy --cookie-dir ./config
"""
import argparse
import asyncio
import logging
import os
import sys

from loguru import logger

from hotel_skill_adapters import compare_hotel_prices

# 兼容 WSL2（与 skill.py 一致）
if not os.environ.get('DISPLAY') and os.path.exists('/tmp/.X11-unix/X0'):
    os.environ['DISPLAY'] = ':0'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _print_results(results, hotel_name: str = None) -> None:
    """打印比价结果（按最低价升序，成功在前）。"""
    succeeded = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]

    succeeded.sort(key=lambda r: r.get("lowest_price", 0) or 0)

    print("\n" + "=" * 56)
    title = "酒店比价结果"
    if hotel_name:
        title += f" · {hotel_name}"
    print(f"  {title}")
    print("=" * 56)

    if not succeeded:
        print("  ⚠ 没有任何平台返回有效价格")
        print("    可能原因：Cookie 失效 / 无库存 / 城市-酒店不匹配")
        print("    请检查 config/*_cookie.txt 是否已配置真实登录 Cookie")
    else:
        for i, r in enumerate(succeeded, 1):
            hotel = r.get("hotel", {})
            price = r.get("lowest_price", 0)
            name = hotel.get("hotel_name") or "-"
            room = hotel.get("room_name") or "-"
            star = hotel.get("star_rating") or 0
            score = hotel.get("score") or 0
            district = hotel.get("district") or "-"
            total = r.get("total_hotels", 0)
            medal = "🥇" if i == 1 else f"  "
            print(f"\n  {medal} {r['platform']}  ¥{price:.0f}/晚  （共 {total} 个候选）")
            print(f"      酒店名  : {name}")
            print(f"      房型    : {room}")
            meta_bits = []
            if star:
                meta_bits.append(f"{star}星")
            if score:
                meta_bits.append(f"评分{score}")
            if district and district != "-":
                meta_bits.append(district)
            if meta_bits:
                print(f"      信息    : {' | '.join(meta_bits)}")

        print("\n  最低价排名：")
        for r in succeeded:
            print(f"    {r['platform']:<6} ¥{r['lowest_price']:.0f}/晚")

    for r in failed:
        print(f"\n  ✗ {r['platform']}：{r.get('error', '查询失败')}")
    print("=" * 56)


async def run(city: str, checkin: str, checkout: str, hotel_name, sources, cookie_dir, headless):
    print(f"\n🔍 酒店比价 | {city} | {checkin} → {checkout}", end="")
    if hotel_name:
        print(f" | 关键词「{hotel_name}」")
    else:
        print(" | 列表最低价")
    print(f"   数据源：{', '.join(sources)}\n")

    for s in sources:
        print(f"  ⏳ {s}：查询中...")

    results = await compare_hotel_prices(
        city=city,
        checkin=checkin,
        checkout=checkout,
        hotel_name=hotel_name,
        sources=sources,
        cookie_dir=cookie_dir,
        headless=headless,
    )

    for r in results:
        src = r["platform"]
        if r.get("status") == "success":
            print(f"  ✓ {src}：已完成 (¥{r['lowest_price']:.0f}，{r.get('total_hotels', 0)} 个候选)")
        else:
            print(f"  ✗ {src}：{r.get('error', '查询失败')}")

    _print_results(results, hotel_name)
    return results


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="酒店比价（携程 / 飞猪 / 同程）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n  python hotel_skill.py 上海 2026-07-01 2026-07-02 --hotel-name 桔子酒店真如",
    )
    p.add_argument("city", help="城市中文名，如 上海")
    p.add_argument("checkin", help="入住日期 YYYY-MM-DD")
    p.add_argument("checkout", help="离店日期 YYYY-MM-DD")
    p.add_argument("--hotel-name", default=None, help="酒店名关键词（可选，精确召回便于横向比价）")
    p.add_argument("--sources", default="ctrip,fliggy,tongcheng",
                   help="数据源，逗号分隔（默认 ctrip,fliggy,tongcheng）")
    p.add_argument("--cookie-dir", default="config", help="cookie 文件目录（默认 ./config）")
    p.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（调试用）")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        logger.error("--sources 不能为空")
        sys.exit(1)
    asyncio.run(run(
        city=args.city,
        checkin=args.checkin,
        checkout=args.checkout,
        hotel_name=args.hotel_name,
        sources=sources,
        cookie_dir=args.cookie_dir,
        headless=not args.no_headless,
    ))


if __name__ == "__main__":
    main()
