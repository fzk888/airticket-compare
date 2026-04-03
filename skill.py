"""机票比价 Skill 主入口"""
import asyncio
import os
from datetime import datetime
from scrapers import CtripScraper, FliggyScraper, ElongScraper, QunarScraper
from utils import CityMapper, Visualizer, setup_logger
from loguru import logger

# 自动设置 DISPLAY 环境变量（WSL2 环境需要）
if not os.environ.get('DISPLAY') and os.path.exists('/tmp/.X11-unix/X0'):
    os.environ['DISPLAY'] = ':0'
    logger.info("自动设置 DISPLAY=:0")

setup_logger()


def _looks_like_flight_no(s: str) -> bool:
    """判断字符串是否看起来像航班号（包含字母和数字）"""
    if not s or len(s) < 4:
        return False
    has_letter = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)
    return has_letter and has_digit


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


async def search_by_flight_no(origin: str, transport_no: str, dep_date: str, to_city: str = None):
    """按航班号查询飞猪 + 携程 + 去哪儿 + 同程价格"""
    from scrapers import FliggyScraper, CtripScraper, QunarScraper, ElongScraper
    from utils.city_mapper import CityMapper

    print(f"\n🔍 查询航班 {transport_no} | {origin} 出发 | {dep_date}\n")

    if to_city:
        # 用户指定了目的地，直接并发查询所有平台
        ctrip_code = CityMapper.get_ctrip_code(to_city)
        qunar_code = CityMapper.get_airports(to_city)[0] if CityMapper.get_airports(to_city) else None
        elong_code = qunar_code
        fliggy_result = None
    else:
        # 先用飞猪查出目的地
        print("  ⏳ 飞猪：查询中...")
        fliggy_result = await FliggyScraper().search_by_flight_no(origin, transport_no, dep_date)
        if fliggy_result.get("status") == "success":
            print(f"  ✓ 飞猪：¥{fliggy_result['price']}")
            to_city = fliggy_result["flight"].get("to_city")
        else:
            print(f"  ✗ 飞猪：{fliggy_result.get('error', '失败')}")
        ctrip_code = CityMapper.get_ctrip_code(to_city) if to_city else None
        qunar_code = CityMapper.get_airports(to_city)[0] if to_city and CityMapper.get_airports(to_city) else None
        elong_code = qunar_code

    # 并发查询携程、去哪儿、同程，以及（指定目的地时）飞猪
    async def query_fliggy():
        print("  ⏳ 飞猪：查询中...")
        r = await FliggyScraper().search_by_flight_no(origin, transport_no, dep_date, destination=to_city)
        if r.get("status") == "success":
            print(f"  ✓ 飞猪：¥{r['price']}")
        else:
            print(f"  ✗ 飞猪：{r.get('error', '失败')}")
        return r

    async def query_ctrip():
        print("  ⏳ 携程：查询中...")
        if not ctrip_code:
            print("  ✗ 携程：无法确定目的地")
            return {"platform": "携程", "status": "failed", "error": "无法确定目的地"}
        r = await CtripScraper().search_by_flight_no(origin, transport_no, dep_date,
                                                     to_city=to_city, to_code=ctrip_code)
        if r.get("status") == "success":
            print(f"  ✓ 携程：¥{r['price']}")
        else:
            print(f"  ✗ 携程：{r.get('error', '失败')}")
        return r

    async def query_qunar():
        print("  ⏳ 去哪儿：查询中...")
        if not qunar_code:
            print("  ✗ 去哪儿：无法确定目的地")
            return {"platform": "去哪儿", "status": "failed", "error": "无法确定目的地"}
        r = await QunarScraper().search_by_flight_no(origin, transport_no, dep_date,
                                                     to_city=to_city, to_code=qunar_code)
        if r.get("status") == "success":
            print(f"  ✓ 去哪儿：¥{r['price']}")
        else:
            print(f"  ✗ 去哪儿：{r.get('error', '失败')}")
        return r

    async def query_elong():
        print("  ⏳ 同程：查询中...")
        if not elong_code:
            print("  ✗ 同程：无法确定目的地")
            return {"platform": "同程", "status": "failed", "error": "无法确定目的地"}
        r = await ElongScraper().search_by_flight_no(origin, transport_no, dep_date,
                                                     to_city=to_city, to_code=elong_code)
        if r.get("status") == "success":
            print(f"  ✓ 同程：¥{r['price']}")
        else:
            print(f"  ✗ 同程：{r.get('error', '失败')}")
        return r

    if fliggy_result is None:
        # 用户指定了目的地，飞猪与其他平台并发查询
        fliggy_result, ctrip_result, qunar_result, elong_result = await asyncio.gather(
            query_fliggy(), query_ctrip(), query_qunar(), query_elong()
        )
    else:
        # 飞猪已查完（用于获取目的地），只并发查其余三个平台
        ctrip_result, qunar_result, elong_result = await asyncio.gather(
            query_ctrip(), query_qunar(), query_elong()
        )

    # 展示结果
    all_results = [r for r in [fliggy_result, ctrip_result, qunar_result, elong_result] if r is not None]
    successful = [r for r in all_results if r.get("status") == "success"]

    print()
    if successful:
        f = successful[0]["flight"]
        to_city_display = f.get("to_city", to_city or "")
        journey_type = f.get("journey_type", "")
        journey_label = f" ({journey_type})" if journey_type else ""
        print(f"✈️  {transport_no}{journey_label}  {origin} → {to_city_display}  {dep_date}")
        if f.get("departure") and f.get("arrival"):
            print(f"   {f['departure']} → {f['arrival']}  {f.get('duration', '')}")
        print()
        for r in all_results:
            if r.get("status") == "success":
                jt = r["flight"].get("journey_type", "")
                jt_label = f" ({jt})" if jt else ""
                print(f"   {r['platform']}：¥{r['price']}{jt_label}")
            else:
                print(f"   {r['platform']}：{r.get('error', '查询失败')}")
        lowest = min(successful, key=lambda x: x["price"])
        lowest_price = lowest["price"]
        lowest_platforms = [r["platform"] for r in successful if r["price"] == lowest_price]
        print(f"\n   最低价: ¥{lowest_price} ({' / '.join(lowest_platforms)})")

        # 有平台找不到且航班是中转，提示原因
        failed = [r for r in all_results if r.get("status") != "success"]
        if failed and journey_type == "中转":
            failed_names = "、".join(r["platform"] for r in failed)
            print(f"\n   ℹ️  {failed_names} 未找到该航班，中转航班号查询仅飞猪支持")
    else:
        print(f"❌ 所有平台查询失败")
        for r in all_results:
            print(f"   {r['platform']}：{r.get('error', '失败')}")

    return {"fliggy": fliggy_result, "ctrip": ctrip_result, "qunar": qunar_result, "elong": elong_result}


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

    # 并发查询四个平台
    scrapers = [CtripScraper(), FliggyScraper(), ElongScraper(), QunarScraper()]
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
    parser.add_argument("arg2", nargs="?", help="到达城市 或 航班号")
    parser.add_argument("arg3", nargs="?", help="航班号（当arg2为城市时） 或 日期")
    parser.add_argument("arg4", nargs="?", help="日期（当同时指定目的地和航班号时）")
    parser.add_argument("--from", dest="from_opt", help="出发城市(可选)")
    parser.add_argument("--to", dest="to_opt", help="到达城市(可选)")
    parser.add_argument("--date", dest="date_opt", help="日期(可选)")
    parser.add_argument("--transport-no", dest="transport_no", help="航班号（如 CZ3171），提供此参数则进入航班号查询模式")
    parser.add_argument("--flight-type", dest="flight_type", default="all",
                       choices=["all", "direct", "connecting"],
                       help="航班类型: all=全部, direct=直飞, connecting=中转")

    args = parser.parse_args()

    from_city = args.from_opt or args.from_city
    transport_no = args.transport_no
    flight_type = args.flight_type

    # 解析位置参数：支持三种格式
    #   深圳 CZ3171 2026-05-30            → 航班号模式（无目的地）
    #   深圳 北京 MU2478 2026-05-30        → 航班号模式（有目的地）
    #   深圳 北京 2026-05-30               → 比价模式
    arg2 = args.to_opt or args.arg2
    arg3 = args.arg3
    arg4 = args.arg4
    date = args.date_opt

    if arg4:
        # 4个位置参数：from 目的地 航班号 日期
        to_city = arg2
        transport_no = transport_no or arg3
        date = date or arg4
    elif arg3:
        if _looks_like_flight_no(arg3):
            # 3个位置参数，arg3 是航班号：from 目的地 航班号（日期用 --date）
            to_city = arg2
            transport_no = transport_no or arg3
        elif _looks_like_flight_no(arg2):
            # 3个位置参数，arg2 是航班号：from 航班号 日期
            to_city = None
            transport_no = transport_no or arg2
            date = date or arg3
        else:
            # 3个位置参数，都是字符串：from 目的地 日期（比价模式）
            to_city = arg2
            date = date or arg3
    elif arg2:
        if _looks_like_flight_no(arg2):
            # 2个位置参数，arg2 是航班号：from 航班号（日期用 --date）
            to_city = None
            transport_no = transport_no or arg2
        else:
            # 2个位置参数：from 目的地（日期用 --date）
            to_city = arg2
    else:
        to_city = None

    is_flight_no_mode = bool(transport_no)

    if is_flight_no_mode:
        # 航班号查询模式
        if not all([from_city, transport_no, date]):
            print("航班号查询用法: python skill.py <出发城市> <航班号> <日期>")
            print("       或指定目的地: python skill.py <出发城市> <目的地> <航班号> <日期>")
            sys.exit(1)
        asyncio.run(search_by_flight_no(from_city, transport_no, date, to_city=to_city))
        return

    # 比价模式
    if not all([from_city, to_city, date]):
        print("比价查询用法: python skill.py <出发城市> <到达城市> <日期> [--flight-type all|direct|connecting]")
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
            q = result["query"]
            print(f"\n{'='*50}")
            print(f"   {q['from']} → {q['to']}  {q['date']}")
            print(f"{'='*50}")
            print("✈️ 直飞最低价")

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
                    stopover = f.get("stopover", False)
                    stopover_note = "(经停)" if stopover else ""
                    print(f"    {platform}: ¥{f['price']} - {flight_no} {dep_time}{stopover_note}")
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
            q = result["query"]
            s = result["summary"]
            print(f"\n   {q['from']} → {q['to']}  {q['date']}")
            print(f"\n✅ 最低价: ¥{s['lowest_price']} ({s['lowest_platform']})")
            for r in result.get("results", []):
                if r.get("status") == "success":
                    f = r["flight"]
                    journey_type = f.get("journey_type", "")
                    stopover = f.get("stopover", False)
                    type_icon = "✈️" if journey_type == "直达" else "🔄"
                    stopover_note = "(经停)" if stopover else ""
                    print(f"   {r['platform']}: ¥{r['lowest_price']} - {f['number']} {f['departure']} {type_icon}{journey_type}{stopover_note}")
                else:
                    print(f"   {r['platform']}: {r.get('error', '失败')}")


if __name__ == "__main__":
    main()
