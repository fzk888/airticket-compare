"""城市到机场代码映射"""

class CityMapper:
    """城市名到机场代码映射"""

    # 城市 -> 机场代码列表
    CITY_AIRPORT_MAP = {
        "北京": ["PEK", "PKX"],
        "上海": ["PVG", "SHA"],
        "深圳": ["SZX"],
        "广州": ["CAN"],
        "成都": ["CTU", "TFU"],
        "杭州": ["HGH"],
        "西安": ["XIY"],
        "重庆": ["CKG"],
        "青岛": ["TAO"],
        "南京": ["NKG"],
        "厦门": ["XMN"],
        "昆明": ["KMG"],
        "大连": ["DLC"],
        "天津": ["TSN"],
        "郑州": ["CGO"],
        "长沙": ["CSX"],
        "武汉": ["WUH"],
        "哈尔滨": ["HRB"],
        "济南": ["TNA"],
        "福州": ["FOC"],
        "海口": ["HAK"],
        "三亚": ["SYX"],
        "贵阳": ["KWE"],
        "南宁": ["NNG"],
        "乌鲁木齐": ["URC"],
        "兰州": ["LHW"],
        "银川": ["INC"],
        "西宁": ["XNN"],
        "拉萨": ["LXA"],
        "呼和浩特": ["HET"],
        "石家庄": ["SJW"],
        "太原": ["TYN"],
        "沈阳": ["SHE"],
        "长春": ["CGQ"],
        "南昌": ["KHN"],
        "合肥": ["HFE"],
        "珠海": ["ZUH"],
        "温州": ["WNZ"],
        "宁波": ["NGB"],
        "无锡": ["WUX"],
    }

    # 携程 URL 中使用的城市拼音/英文缩写
    CITY_CTRIP_CODE = {
        "北京": "BJS", "上海": "SHA", "深圳": "SZX", "广州": "CAN",
        "成都": "CTU", "杭州": "HGH", "西安": "SIA", "重庆": "CKG",
        "青岛": "TAO", "南京": "NKG", "厦门": "XMN", "昆明": "KMG",
        "大连": "DLC", "天津": "TSN", "郑州": "CGO", "长沙": "CSX",
        "武汉": "WUH", "哈尔滨": "HRB", "济南": "TNA", "福州": "FOC",
        "海口": "HAK", "三亚": "SYX", "贵阳": "KWE", "南宁": "NNG",
        "乌鲁木齐": "URC", "兰州": "LHW", "银川": "INC", "西宁": "XNN",
        "拉萨": "LXA", "呼和浩特": "HET", "石家庄": "SJW", "太原": "TYN",
        "沈阳": "SHE", "长春": "CGQ", "南昌": "KHN", "合肥": "HFE",
        "珠海": "ZUH", "温州": "WNZ", "宁波": "NGB", "无锡": "WUX",
    }

    @classmethod
    def get_airports(cls, city_name: str) -> list:
        return cls.CITY_AIRPORT_MAP.get(city_name, [])

    @classmethod
    def get_ctrip_code(cls, city_name: str) -> str:
        return cls.CITY_CTRIP_CODE.get(city_name, "")

    @classmethod
    def is_valid_city(cls, city_name: str) -> bool:
        return city_name in cls.CITY_AIRPORT_MAP
