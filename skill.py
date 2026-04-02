"""机票比价 Skill 主入口"""
import asyncio
from datetime import datetime
from scrapers import CtripScraper, FliggyScraper, ElongScraper
from utils import CityMapper, Visualizer, setup_logger
from loguru import logger

setup_logger()

async def search_single_platform(scraper, from_city, to_city, from_airports, to_airports, date, **kwargs):
    """查询单个平台"""
    platform_name = scraper.platform
    flight_type = kwargs.get("flight_type", "all")
    print(f"  ⏳ {platform_name}：查询中...")

    try:
        # 携程使用城市名搜索（URL 中需要城市名或机场代码）
        result = await scraper.search_flights(from_city, to_city, date,
                                              cabin_class=kwargs.get("cabin_class"),
                                              time_range=kwargs.get("time_range"),
                                              flight_type=flight_type)

        if result and result.get("status") == "success":
            price = result["lowest_price"]
            flight_no = result["flight"]["number"]
            print(f"  ✓ {platform_name}：已完成 (¥{price} - {flight_no})")
            return result
        else:
            error = result.get("error", "未知错误") if result else "无返回"
            print(f"  ✗ {platform_name}：{error}")
            return result or {"platform": platform_name, "status": "failed", "error": error}

    except Exception as e:
        logger.error(f"{platform_name} 查询异常: {e}")
        print(f"  ✗ {platform_name}：查询失败 - {e}")
        return {"platform": platform_name, "status": "failed", "error": str(e)}


async def compare_prices(from_city: str, to_city: str, depart_date: str,
                        return_date: str = None, cabin_class: str = "economy",
                        time_range: str = None, flight_type: str = "all"):
    """机票比价主函数

    Args:
        flight_type: 航班类型筛选 "all" | "direct" | "connecting"
    """

    # 验证城市
    if not CityMapper.is_valid_city(from_city):
        return {"error": f"无效的出发城市: {from_city}"}
    if not CityMapper.is_valid_city(to_city):
        return {"error": f"无效的到达城市: {to_city}"}

    from_airports = CityMapper.get_airports(from_city)
    to_airports = CityMapper.get_airports(to_city)

    # 航班类型描述
    type_desc = {"all": "全部", "direct": "直飞", "connecting": "中转"}.get(flight_type, "全部")

    print(f"\n🔍 正在查询机票价格...")
    print(f"   {from_city} ({', '.join(from_airports)}) → {to_city} ({', '.join(to_airports)})")
    print(f"   日期: {depart_date} | 类型: {type_desc}\n")

    # 并发查询三个平台
    scrapers = [CtripScraper(), FliggyScraper(), ElongScraper()]
    tasks = [search_single_platform(s, from_city, to_city, from_airports, to_airports, depart_date,
                                   cabin_class=cabin_class, time_range=time_range,
                                   flight_type=flight_type)
             for s in scrapers]

    results = await asyncio.gather(*tasks)

    # 生成摘要
    successful = [r for r in results if r.get("status") == "success"]
    if successful:
        lowest = min(successful, key=lambda x: x["lowest_price"])
        summary = {
            "lowest_platform": lowest["platform"],
            "lowest_price": lowest["lowest_price"],
            "query_time": datetime.now().isoformat()
        }
    else:
        summary = {"error": "所有平台查询失败"}

    output = {
        "query": {
            "from": f"{from_city} ({', '.join(from_airports)})",
            "to": f"{to_city} ({', '.join(to_airports)})",
            "date": depart_date,
            "cabin": cabin_class,
            "flight_type": flight_type
        },
        "results": results,
        "summary": summary
    }

    # 生成可视化
    print("\n📊 生成价格对比图表...")
    chart_path = Visualizer.create_price_chart(results)
    if chart_path:
        output["chart"] = chart_path
        print(f"✓ 图表已保存: {chart_path}")

    return output


def main():
    """命令行入口"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="机票比价工具")
    parser.add_argument("from_city", nargs="?", help="出发城市")
    parser.add_argument("to_city", nargs="?", help="到达城市")
    parser.add_argument("date", nargs="?", help="出发日期 (YYYY-MM-DD)")
    parser.add_argument("--from", dest="from_opt", help="出发城市(可选)")
    parser.add_argument("--to", dest="to_opt", help="到达城市(可选)")
    parser.add_argument("--date", dest="date_opt", help="日期(可选)")
    parser.add_argument("--flight-type", dest="flight_type", default="all",
                       choices=["all", "direct", "connecting"],
                       help="航班类型: all=全部, direct=直飞, connecting=中转")

    args = parser.parse_args()

    # 支持位置参数或命名参数
    from_city = args.from_opt or args.from_city
    to_city = args.to_opt or args.to_city
    date = args.date_opt or args.date
    flight_type = args.flight_type

    if not all([from_city, to_city, date]):
        print("用法: python skill.py <出发城市> <到达城市> <日期> [--flight-type all|direct|connecting]")
        print("或: python skill.py --from <城市> --to <城市> --date <日期> --flight-type <类型>")
        sys.exit(1)

    result = asyncio.run(compare_prices(from_city, to_city, date, flight_type=flight_type))

    if "error" in result.get("summary", {}):
        print(f"\n❌ {result['summary']['error']}")
        for r in result.get("results", []):
            print(f"   {r.get('platform', '?')}: {r.get('error', '?')}")
    else:
        flight_type = result.get("query", {}).get("flight_type", "all")

        if flight_type == "all":
            # all 模式：分别显示直飞最低价和中转最低价，每个平台的最低价都要显示
            print(f"\n{'='*50}")
            print("✈️ 直飞最低价")
            print(f"{'='*50}")

            # 从每个平台的 flights_list 收集直飞航班
            direct_by_platform = {}
            for r in result.get("results", []):
                if r.get("status") == "success":
                    flights_list = r.get("flights_list", [])
                    platform = r['platform']
                    f = r["flight"]
                    price = r["lowest_price"]

                    if flights_list:
                        # 有 flights_list 的平台，找直飞最低价
                        direct_flights = [fl for fl in flights_list if fl.get("journey_type") == "直达"]
                        if direct_flights:
                            best = min(direct_flights, key=lambda x: x["price"])
                            direct_by_platform[platform] = best
                    elif f.get("journey_type") == "直达":
                        # 没有 flights_list，用 flight 字段
                        direct_by_platform[platform] = {
                            "price": price,
                            "flightNo": f.get("number", ""),
                            "depTime": f.get("departure", "")
                        }

            if direct_by_platform:
                for platform, f in sorted(direct_by_platform.items(), key=lambda x: x[1]["price"]):
                    flight_no = f.get("flightNo", f.get("number", ""))
                    dep_time = f.get("depTime", f.get("departure", ""))
                    print(f"    {platform}: ¥{f['price']} - {flight_no} {dep_time}")
            else:
                print("  无直飞航班")

            print(f"\n{'='*50}")
            print("🔄 中转最低价")
            print(f"{'='*50}")

            # 从每个平台的 flights_list 收集中转航班
            connecting_by_platform = {}
            for r in result.get("results", []):
                if r.get("status") == "success":
                    flights_list = r.get("flights_list", [])
                    platform = r['platform']
                    f = r["flight"]
                    price = r["lowest_price"]

                    if flights_list:
                        # 有 flights_list 的平台，找中转最低价
                        connecting_flights = [fl for fl in flights_list if fl.get("journey_type") == "中转"]
                        if connecting_flights:
                            best = min(connecting_flights, key=lambda x: x["price"])
                            connecting_by_platform[platform] = best
                    elif f.get("journey_type") == "中转":
                        # 没有 flights_list，用 flight 字段
                        connecting_by_platform[platform] = {
                            "price": price,
                            "flightNo": f.get("number", ""),
                            "depTime": f.get("departure", "")
                        }

            if connecting_by_platform:
                for platform, f in sorted(connecting_by_platform.items(), key=lambda x: x[1]["price"]):
                    flight_no = f.get("flightNo", f.get("number", ""))
                    dep_time = f.get("depTime", f.get("departure", ""))
                    print(f"    {platform}: ¥{f['price']} - {flight_no} {dep_time}")
            else:
                print("  无中转航班")
            print()
        else:
            # direct 或 connecting 模式：直接显示结果
            s = result["summary"]
            print(f"\n✅ 最低价: ¥{s['lowest_price']} ({s['lowest_platform']})")
            for r in result.get("results", []):
                if r.get("status") == "success":
                    f = r["flight"]
                    journey_type = f.get("journey_type", "")
                    type_icon = "✈️" if journey_type == "直达" else "🔄"
                    print(f"   {r['platform']}: ¥{r['lowest_price']} - {f['number']} {f['departure']} {type_icon}{journey_type}")
                else:
                    print(f"   {r['platform']}: {r.get('error', '失败')}")


if __name__ == "__main__":
    main()
