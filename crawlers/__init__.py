"""crawlers — 从 RideClaw 迁移过来的多平台比价爬虫。

与 airticket 现有 scrapers/（机票 Playwright）完全独立，命名空间隔离。

机票（crawlers.flight）：
- CtripH5Drission        携程 H5（DrissionPage）
- FliggyFlightSpider     飞猪 PC SSR（DrissionPage）
- FliggyFlightSpiderV2   飞猪 v2 多舱位（DrissionPage）
- FliggyFlyAISpider      飞猪 FlyAI CLI
- TongchengFlightSpider  同程（DrissionPage）

酒店（crawlers.hotel）：
- CtripHotelSpider       携程（requests API）
- CtripHotelDrission     = CtripHotelSpider（旧别名）
- FliggyHotelSpider      飞猪（DrissionPage）
- FliggyHotelFlyAISpider 飞猪 FlyAI CLI
- TongchengHotelSpider   同程（DrissionPage）

公共能力（crawlers.core）：browser_base / stdio / utils
"""
