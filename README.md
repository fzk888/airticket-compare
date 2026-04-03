# 机票比价 Skill

支持携程、飞猪、同程、去哪儿四个平台的机票比价查询，返回直飞/中转最低价。

## 功能特性

- **四平台比价**：同时查询携程、飞猪、同程、去哪儿四个平台
- **真实价格**：实时查询，无缓存，返回最新价格
- **中文支持**：支持中文城市名输入（深圳、上海等）
- **自动登录**：携程/去哪儿 cookies 过期自动弹窗引导登录
- **图表可视化**：生成价格对比图表
- **直飞/中转筛选**：可选择查看全部、直飞或中转航班
- **经停识别**：经停航班正确识别为直飞，并标注"(经停)"
- **OpenClaw集成**：可作为 agent 技能集成到 OpenClaw 工作流

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
from scrapers import CtripScraper, FliggyScraper, ElongScraper, QunarScraper

async def search():
    scrapers = [CtripScraper(), FliggyScraper(), ElongScraper(), QunarScraper()]
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

> **首次使用**：去哪儿需要登录才能查询完整航班。首次运行时会自动弹窗引导登录，登录成功后 cookies 保存到 `cookies_qunar.json`，之后无需再登录。

## 平台说明

| 平台 | 登录要求 | 直飞/中转 | 说明 |
|------|---------|---------|------|
| 飞猪 | 不需要 | 均支持 | 官方 API，最稳定 |
| 同程 | 不需要 | 仅直飞 | 网页爬虫，含经停识别 |
| 携程 | **需要** | 均支持 | 网页爬虫，cookies 登录 |
| 去哪儿 | **需要** | 均支持 | 网页爬虫，cookies 登录 |

## 去哪儿反爬虫机制

去哪儿使用了多层反爬虫保护：

### 1. CSS 字体混淆（价格加密）

价格数字通过 CSS 偏移技术混淆：多个 `<i>` 标签堆叠在一起，通过 `left: -XXpx` 偏移量决定显示哪个数字。`innerText` 读取到的是所有数字的混合值。

```html
<!-- 价格 844 的混淆结构 -->
<em class="rel">
  <b style="width:48px;left:-48px">
    <i title="844" style="width:16px;">8</i>
    <i title="844" style="width:16px;">0</i>
    <i title="844" style="width:16px;">4</i>
  </b>
  <b title="844" style="width:16px;left:-32px;">4</b>
</em>
```

**解决方案**：不依赖 `innerText`，从 `aria-label="报价：XXX元"` 和 `title="XXX"` 属性直接提取明文价格。

### 2. 动态渲染

航班列表通过 JavaScript 动态加载，`domcontentloaded` 时页面尚未渲染完成，需要轮询等待 `.b-airfly` 元素出现。

**解决方案**：使用 `page.locator('.b-airfly').count()` 轮询检测，最多等待 15 秒。

### 3. Selenium/Webdriver 检测

去哪儿通过 `navigator.webdriver`、`window.chrome`、`window.navigator.plugins` 等属性检测自动化工具。

**解决方案**：

```python
await context.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
""")
```

### 4. 强制登录

去哪儿航班列表页未登录只能看到少量数据，必须登录才能获取完整航班和价格。

**解决方案**：无 cookies 时弹窗引导用户扫码/账号登录，登录成功后保存 cookies 供后续查询使用。

## cookies 配置

| 平台 | cookies 文件 | 环境变量 |
|------|------------|---------|
| 携程 | `cookies.json` | `CTRIP_COOKIES` |
| 去哪儿 | `cookies_qunar.json` | `QUNAR_COOKIES` |

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
    "platform": "去哪儿",           # 平台名称
    "status": "success",            # 状态
    "lowest_price": 580,            # 总体最低价
    "lowest_direct_price": 939,     # 直飞最低价
    "lowest_connecting_price": 580, # 中转最低价
    "tax": 0,                       # 税费
    "currency": "CNY",              # 货币
    "flight": {
        "number": "CZ3589",         # 航班号
        "airline": "南方航空",       # 航司
        "departure": "20:00",       # 出发时间
        "arrival": "22:30",         # 到达时间
        "duration": "",             # 飞行时长
        "from_airport": "宝安机场T3", # 出发机场
        "to_airport": "虹桥机场T2",   # 到达机场
        "journey_type": "直达",       # 航班类型：直达/中转
        "segments_count": 1,        # 航段数量
        "stopover": False           # 是否经停（经停算直飞）
    },
    "flights_list": [               # 符合筛选条件的航班列表（最多10条）
        {
            "price": 580,
            "flightNo": "ZH9327",
            "airline": "Unknown",
            "depTime": "23:00",
            "arrTime": "00:25",
            "duration": "",
            "from_airport": "",
            "to_airport": "",
            "journey_type": "中转",
            "segments_count": 2,
            "stopover": False
        }
    ],
    "url": "https://flight.qunar.com"
}
```

## 项目结构

```
price-comparison/
├── skill.py              # 主入口
├── config.py             # 配置文件
├── cookies.json          # 携程 cookies（自动生成）
├── cookies_qunar.json    # 去哪儿 cookies（自动生成）
├── SKILL.md             # OpenClaw 技能定义
├── scrapers/
│   ├── __init__.py
│   ├── base.py          # 基础爬虫类
│   ├── ctrip.py         # 携程爬虫
│   ├── fliggy.py        # 飞猪爬虫
│   ├── elong.py          # 同程爬虫
│   └── qunar.py          # 去哪儿爬虫
└── utils/
    ├── city_mapper.py   # 城市-机场代码映射
    └── visualizer.py    # 图表生成
```

## 注意事项

1. **查询速度**：四平台并行查询，总耗时约 8-12 秒（去哪儿因需等待动态渲染略慢）
2. **价格波动**：实时价格随时变化，以查询结果为准
3. **cookies 有效期**：携程、去哪儿 cookies 有效期有限，过期需重新登录
4. **经停 vs 中转**：经停（中途短停，航班号相同）算直飞；中转（换航班段）算中转

## 常见问题

**Q: 去哪儿/携程一直提示需要登录？**
A: cookies 可能过期，删除对应 cookies 文件后重新运行，系统会弹窗引导登录。

**Q: 飞猪查询失败？**
A: 检查 FlyAI CLI 是否安装：`flyai --version`

**Q: 同程价格不对？**
A: 同程网页版仅显示直飞航班。

**Q: 去哪儿价格显示 N/A？**
A: cookies 过期，删除 `cookies_qunar.json` 后重新登录。
