# 机票比价 Skill

支持携程、飞猪、同程三个平台的机票比价查询，返回最低价航班信息。

## 功能特性

- **三平台比价**：同时查询携程、飞猪、同程三个平台
- **真实价格**：实时查询，无缓存，返回最新价格
- **中文支持**：支持中文城市名输入（深圳、上海等）
- **自动登录**：携程cookies过期自动弹窗引导登录
- **图表可视化**：生成价格对比图表
- **直飞/中转筛选**：可选择查看全部、直飞或中转航班
- **OpenClaw集成**：可作为agent技能集成到OpenClaw工作流

## 安装依赖

```bash
pip install playwright loguru fake-useragent lxml matplotlib
playwright install chromium
```

## 使用方式

### 命令行

```bash
# 位置参数
python skill.py 深圳 上海 2026-04-20

# 命名参数
python skill.py --from 深圳 --to 上海 --date 2026-04-20

# 航班类型筛选 (all/直飞, direct/直飞, connecting/中转)
python skill.py 深圳 上海 2026-04-20 --flight-type all      # 全部（默认）
python skill.py 深圳 上海 2026-04-20 --flight-type direct    # 仅直飞
python skill.py 深圳 上海 2026-04-20 --flight-type connecting # 仅中转
```

### Python调用

```python
import asyncio
from scrapers import CtripScraper, FliggyScraper, ElongScraper

async def search():
    scrapers = [CtripScraper(), FliggyScraper(), ElongScraper()]
    tasks = [s.search_flights('深圳', '北京', '2026-04-20', flight_type='all') for s in scrapers]
    results = await asyncio.gather(*tasks)

    for r in results:
        if r['status'] == 'success':
            f = r['flight']
            print(f"{r['platform']}: ¥{r['lowest_price']} - {f['number']} {f['departure']} {f.get('journey_type', '')}")

asyncio.run(search())
```

### OpenClaw集成

参考 `SKILL.md` 文件进行配置。

> ⚠️ **重要**：首次使用OpenClaw前，请先手动运行一次登录：
> ```bash
> python skill.py 深圳 上海 2026-04-20
> ```
> 弹窗出现后登录携程账号，登录成功后cookies会自动保存。之后再给OpenClaw使用即可。

## 平台说明

| 平台 | 登录要求 | 说明 |
|------|---------|------|
| 飞猪 | 不需要 | 官方API，最稳定，支持直飞/中转筛选 |
| 同程 | 不需要 | 网页爬虫，仅直飞航班 |
| 携程 | **需要** | 网页爬虫，需要cookies，支持直飞/中转筛选 |

## 携程登录配置

携程需要登录才能查询价格。系统会自动处理：

1. **首次使用**：没有cookies时自动弹窗引导登录
2. **cookies保存**：登录后保存到 `cookies.json`
3. **过期处理**：cookies过期自动弹窗重新登录
4. **环境变量**：也可通过 `CTRIP_COOKIES` 环境变量配置

### 环境变量配置（可选）

```bash
# Windows
set CTRIP_COOKIES=[{"name":"cticket","value":"xxx",...},...]

# Linux/Mac
export CTRIP_COOKIES='[{"name":"cticket","value":"xxx",...},...]'
```

## 返回数据格式

```python
{
    "platform": "携程",           # 平台名称
    "status": "success",         # 状态
    "lowest_price": 580,         # 最低价
    "tax": 0,                    # 税费
    "currency": "CNY",           # 货币
    "flight": {
        "number": "SC4686",      # 航班号
        "airline": "山东航空",    # 航司
        "departure": "19:50",    # 出发时间
        "arrival": "22:50",      # 到达时间
        "duration": "",          # 飞行时长
        "from_airport": "宝安机场T3",  # 出发机场
        "to_airport": "首都机场T3",     # 到达机场
        "journey_type": "直达",       # 航班类型：直达/中转
        "segments_count": 1           # 航段数量
    },
    "flights_list": [            # 符合筛选条件的航班列表（最多10条）
        {
            "price": 580,
            "flightNo": "SC4686",
            "airline": "山东航空",
            "depTime": "19:50",
            "arrTime": "22:50",
            "journey_type": "直达",
            "segments_count": 1
        }
    ],
    "url": "https://flights.ctrip.com"
}
```

## 项目结构

```
price-comparison/
├── skill.py              # 主入口
├── config.py             # 配置文件
├── cookies.json          # 携程cookies（自动生成）
├── SKILL.md             # OpenClaw技能定义
├── scrapers/
│   ├── base.py          # 基础爬虫类
│   ├── ctrip.py         # 携程爬虫
│   ├── fliggy.py        # 飞猪爬虫
│   └── elong.py         # 同程爬虫
└── utils/
    ├── city_mapper.py   # 城市-机场代码映射
    └── visualizer.py    # 图表生成
```

## 城市代码

支持中文城市名输入，系统会自动转换为机场代码：

| 城市 | 机场代码 |
|------|---------|
| 深圳 | SZX |
| 上海 | PVG, SHA |
| 北京 | PEK |
| 广州 | CAN |

## 注意事项

1. **查询速度**：三个平台并行查询，总耗时约8-12秒
2. **价格波动**：实时价格随时变化，以查询结果为准
3. **携程cookies**：有效期有限，过期需重新登录
4. **航班类型**：飞猪和携程支持直飞/中转筛选，同程仅支持直飞
5. **反爬策略**：携程有反爬检测，已做基础规避

## 常见问题

**Q: 携程一直提示需要登录？**
A: cookies可能过期，删除 `cookies.json` 后重新运行，系统会弹窗引导登录。

**Q: 飞猪查询失败？**
A: 检查 FlyAI CLI 是否安装：`flyai --version`

**Q: 同程价格不对？**
A: 同程网页版仅显示直飞航班，中转需用APP或其他方式。

**Q: 如何加快查询速度？**
A: 可减少 `config.py` 中的等待时间，但可能影响稳定性。
