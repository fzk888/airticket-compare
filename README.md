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

**比价模式**（对比多平台最低价）：

```bash
# 位置参数
python skill.py 深圳 上海 2026-04-20

# 命名参数
python skill.py --from 深圳 --to 上海 --date 2026-04-20

# 航班类型筛选
python skill.py 深圳 上海 2026-04-20 --flight-type all       # 全部（默认，分直飞/中转显示）
python skill.py 深圳 上海 2026-04-20 --flight-type direct     # 仅直飞
python skill.py 深圳 上海 2026-04-20 --flight-type connecting  # 仅中转
```

**航班号查询模式**（查询指定航班在各平台的价格）：

```bash
# 出发城市 + 航班号 + 日期（自动推断目的地）
python skill.py 深圳 CZ3171 2026-04-20

# 指定目的地（更快，4平台并发）
python skill.py 深圳 北京 CZ3171 2026-04-20

# 使用 --transport-no 参数
python skill.py 深圳 --to 北京 --transport-no CZ3171 --date 2026-04-20
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

| 平台 | 登录要求 | 直飞/中转 | 航班号查询 | 说明 |
|------|---------|---------|----------|------|
| 飞猪 | 不需要 | 均支持 | ✅ 支持（含中转） | 官方 API，最稳定 |
| 同程 | 不需要 | 仅直飞 | ✅ 支持（仅直飞） | 网页爬虫，含经停识别；**网页价格高于 App，仅供参考** |
| 携程 | **需要** | 均支持 | ✅ 支持 | 网页爬虫，cookies 登录 |
| 去哪儿 | **需要** | 均支持 | ✅ 支持 | 网页爬虫，cookies 登录；**App 价格略低于网页** |

> ⚠️ 本工具查询的均为各平台**官网/网页端**价格。同程 App 价格显著低于网页端，且网页端无中转航班；去哪儿 App 价格略低于网页端。实际购票建议以 App 为准。

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

## 酒店比价（crawlers/）

除机票外，本仓库还从 RideClaw 迁移了一套**多平台酒店 + 机票爬虫**，位于独立的 `crawlers/` 命名空间（与 `scrapers/` 互不影响，使用 DrissionPage 而非 Playwright）。

支持的酒店平台：

| 平台 | 登录要求 | 实现 | Cookie 文件 |
|------|---------|------|------------|
| 携程 | **需要** | requests 直连 H5 API | `config/ctrip_cookie.txt` |
| 飞猪 | **需要** | DrissionPage SSR 解析 | `config/fliggy_cookie.txt` |
| 同程 | **需要** | DrissionPage Vue DOM 解析 | `config/tongcheng_cookie.txt` |

> 飞猪还提供一个基于 FlyAI CLI 的变体 `FliggyHotelFlyAISpider`，走官方 API 更稳，但需要安装 `flyai` CLI 与 `FLYAI_API_KEY`。

### 使用方式

```bash
# 列表最低价（按城市查）
python hotel_skill.py 上海 2026-07-01 2026-07-02

# 指定酒店名（横向比价同一酒店）
python hotel_skill.py 上海 2026-07-01 2026-07-02 --hotel-name 桔子酒店真如

# 只查部分平台
python hotel_skill.py 上海 2026-07-01 2026-07-02 --sources ctrip,fliggy
```

### Cookie 配置

三平台酒店价格均为登录态接口，必须配置有效 Cookie：

```bash
cp config/ctrip_cookie.txt.example config/ctrip_cookie.txt     # 后填入真实 Cookie
cp config/fliggy_cookie.txt.example config/fliggy_cookie.txt
cp config/tongcheng_cookie.txt.example config/tongcheng_cookie.txt
```

Cookie 获取：浏览器登录对应平台后，从开发者工具 Network 中复制任一请求的 `Cookie` 头，整行粘贴即可。真实的 `*_cookie.txt` 不会被提交（见 `.gitignore`）。

### FlyAI（可选）

飞猪 FlyAI 爬虫（机票 + 酒店）走官方 API，比网页爬虫稳定，但需要：

```bash
npm i -g @fly-ai/flyai-cli      # 安装 CLI
flyai --help                     # 验证
# 配置 API Key（参考 config/flyai.env.example）
export FLYAI_API_KEY=your_key
```

### crawlers/ 也提供机票爬虫

`crawlers/flight/` 下同样有携程 H5 / 飞猪 / 同程的机票爬虫（DrissionPage 实现，与 `scrapers/` 下的 Playwright 版本是两套并行实现，按需选用）。例如：

```python
from crawlers.flight.ctrip_h5 import CtripH5Drission
with CtripH5Drission(headless=True) as spider:
    flights = spider.search_flights("SHA", "PEK", "2026-07-01")
```

## 项目结构

```
price-comparison/
├── skill.py              # 机票比价主入口（Playwright scrapers/）
├── hotel_skill.py        # 酒店比价主入口（RideClaw 迁移的 crawlers/）
├── hotel_skill_adapters.py  # 酒店 crawlers 的 async 适配胶水
├── config.py             # 机票配置
├── cookies.json          # 携程 cookies（机票，自动生成）
├── cookies_qunar.json    # 去哪儿 cookies（机票，自动生成）
├── SKILL.md             # OpenClaw 技能定义
├── scrapers/             # 机票爬虫（Playwright，原有）
│   ├── __init__.py
│   ├── base.py
│   ├── ctrip.py
│   ├── fliggy.py
│   ├── elong.py
│   └── qunar.py
├── crawlers/             # 酒店+机票爬虫（DrissionPage，从 RideClaw 迁移）
│   ├── core/             # 公共基础：browser_base / stdio / utils
│   ├── flight/           # 携程H5 / 飞猪 / 同程 机票
│   └── hotel/            # 携程 / 飞猪 / 同程 酒店
├── config/               # crawlers 用的 cookie 与 FlyAI 配置
│   ├── *_cookie.txt.example
│   └── flyai.env.example
└── utils/
    ├── city_mapper.py
    └── visualizer.py
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
