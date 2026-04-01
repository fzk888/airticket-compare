---
name: flight-price-comparison
description: Compare flight prices across Ctrip, Fliggy, and Tongcheng platforms. Get real-time lowest prices for domestic flights in China with detailed flight information including flight number, airline, departure/arrival times, and booking links.
homepage: https://github.com/yourusername/flight-price-comparison
metadata:
  version: 1.0.0
  agent:
    type: tool
    runtime: python
    context_isolation: execution
    parent_context_access: read-only
  openclaw:
    emoji: "✈️"
    priority: 85
    requires:
      bins:
        - python
        - flyai
    intents:
      - flight_price_comparison
      - flight_search
      - price_compare
    patterns:
      - "((compare|check).*(flight|airfare|air ticket).*(price|cost))"
      - "((flight|airfare).*(compare|comparison|cheapest|best deal))"
      - "((search|find).*(cheap|cheapest|lowest).*(flight|ticket))"
      - "(比价|比较).*(机票|航班|价格)"
      - "(查询|搜索).*(最低价|最便宜).*(机票|航班)"
---
# Flight Price Comparison — 机票比价

Compare flight prices across **Ctrip (携程)**, **Fliggy (飞猪)**, and **Tongcheng (同程)** platforms to find the best deals.

## Quick Start

```bash
python skill.py <出发城市> <到达城市> <日期>
```

**Example:**

```bash
python skill.py 深圳 上海 2026-04-16
```

## Features

- ✅ **Real-time prices** from 3 major Chinese travel platforms
- ✅ **Parallel queries** for fast results
- ✅ **Visual comparison** with auto-generated price charts
- ✅ **Graceful degradation** - shows available results even if some platforms fail
- ✅ **Supports both direct and connecting flights**

## Output

The tool provides:

1. **Console output** with lowest prices from each platform
2. **Price comparison chart** (PNG image)
3. **Detailed flight info**: flight number, airline, departure/arrival times
4. **Booking links** for each platform

## Requirements

- Python 3.8+
- Playwright (for Ctrip)
- FlyAI CLI (for Fliggy)
- Ctrip cookies (optional, for better results)

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Install FlyAI CLI
npm i -g @fly-ai/flyai-cli
```

## Configuration

> ⚠️ **Important**: On first use, the tool will auto-prompt Ctrip login in browser. Complete login and captcha verification, then the tool will save cookies and continue automatically.

**Optional:** For Ctrip, you can also place cookies in `cookies.json`:

```json
{
  "your_account": [
    {"name": "cookie_name", "value": "cookie_value", "domain": ".ctrip.com"}
  ]
}
```

## Usage in OpenClaw

When integrated with OpenClaw, you can use natural language:

- "比较深圳到上海的机票价格"
- "Find the cheapest flight from Beijing to Shanghai on April 20"
- "Compare flight prices from Guangzhou to Chengdu next week"

## Supported Cities

Major Chinese cities including:

- 北京 (Beijing), 上海 (Shanghai), 深圳 (Shenzhen), 广州 (Guangzhou)
- 成都 (Chengdu), 杭州 (Hangzhou), 西安 (Xi'an), 重庆 (Chongqing)
- And 30+ more cities

## Technical Details

- **Ctrip**: Playwright + cookies + DOM extraction (auto login popup)
- **Fliggy**: Official FlyAI CLI API
- **Tongcheng**: Playwright + lxml HTML parsing (direct flights only)

## Limitations

- Currently supports domestic flights in China only
- Ctrip requires login (auto popup on first use)
- Tongcheng shows only direct flights (no connecting flights)

## License

MIT

## Author

Created for personal use. Use at your own risk.
