"""为菜品库中缺少热量 / 宏量素的条目补全估算数据。

估算口径对齐「菜品热量估算表」：
- 按食堂常见出品重量与用油量估算一份总热量
- 每 100 g 热量 = 总热量 / 出品重量 * 100
- 宏量素占比为能量占比（碳水 / 蛋白 / 脂肪约等于 100%）
- features 为简短食用特点说明

结果写回 ``data/dishes.json``。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISHES = ROOT / "data" / "dishes.json"

sys.stdout.reconfigure(encoding="utf-8")


def _norm_pct(carb: float, protein: float, fat: float) -> tuple[float, float, float]:
    total = carb + protein + fat
    if total <= 0:
        return 40.0, 25.0, 35.0
    return (
        round(carb / total * 100, 1),
        round(protein / total * 100, 1),
        round(fat / total * 100, 1),
    )


def estimate(name: str, floors: list[str] | None = None) -> dict:
    """根据菜名关键词推断类别、出品、热量与宏量素。"""
    floors = floors or []
    n = name

    # ---- 显式覆盖：更贴近该菜常见做法 ----
    overrides: dict[str, dict] = {
        "三明治": dict(cat="主食-套餐", portion=220, total=420, c=45, p=20, f=35, feat="面包夹蛋肉蔬，碳水与脂肪并重，一份即可当早餐主食"),
        "三鲜豆腐": dict(cat="豆制品", portion=220, total=260, c=20, p=35, f=45, feat="豆腐配海鲜或菌菇，软嫩清淡，植物蛋白充足，热量适中"),
        "东坡肉": dict(cat="肉类-猪肉", portion=180, total=720, c=8, p=15, f=77, feat="五花肉慢炖，肥而不腻，脂肪含量极高，下饭但热量很高"),
        "五彩桃仁虾仁": dict(cat="肉类-水产", portion=200, total=320, c=15, p=40, f=45, feat="虾仁配核桃与彩蔬，优质蛋白高，坚果带来额外脂肪"),
        "什锦腐竹": dict(cat="豆制品", portion=200, total=280, c=25, p=30, f=45, feat="腐竹吸味，搭配杂蔬，植物蛋白丰富，口感筋道"),
        "农家小炒鸡": dict(cat="肉类-鸡肉", portion=230, total=420, c=12, p=40, f=48, feat="鸡肉小炒，香辣下饭，优质蛋白高，脂肪适中"),
        "冬笋炒肉片": dict(cat="肉类-猪肉", portion=210, total=310, c=25, p=30, f=45, feat="冬笋脆嫩配猪肉，家常小炒，热量适中"),
        "冬笋里肌丝": dict(cat="肉类-猪肉", portion=210, total=300, c=22, p=35, f=43, feat="里脊配冬笋，口感清爽，蛋白较好，脂肪低于五花类"),
        "剁椒肉末蒸蛋": dict(cat="蛋类", portion=220, total=280, c=8, p=40, f=52, feat="蒸蛋配剁椒肉末，嫩滑开胃，蛋白高、热量适中"),
        "南瓜饼": dict(cat="小吃", portion=120, total=290, c=55, p=8, f=37, feat="南瓜面糊煎炸，香甜软糯，碳水与脂肪偏高"),
        "咖喱牛肉": dict(cat="肉类-牛肉", portion=250, total=420, c=25, p=35, f=40, feat="咖喱炖牛肉，酱香浓郁，蛋白充足，适合配饭"),
        "咖喱鸡饭": dict(cat="主食-盖饭", portion=400, total=720, c=45, p=25, f=30, feat="咖喱鸡块配米饭，一餐主食热量较高，碳水占比大"),
        "咸菜": dict(cat="蔬菜类", portion=50, total=25, c=50, p=20, f=30, feat="腌制小菜，份量小、热量低，钠含量较高"),
        "固始鸡块": dict(cat="肉类-鸡肉", portion=230, total=380, c=10, p=45, f=45, feat="鸡块炖煮，汤鲜肉香，优质蛋白高"),
        "奥利奥面包": dict(cat="甜品", portion=90, total=350, c=50, p=8, f=42, feat="甜点面包，糖油充足，零食属性强，热量密度高"),
        "奥尔良烤鸡": dict(cat="肉类-鸡肉", portion=250, total=480, c=12, p=40, f=48, feat="奥尔良风味烤鸡，外香里嫩，蛋白高、脂肪适中偏高"),
        "孜然鸭丁": dict(cat="肉类-鸭肉", portion=200, total=380, c=8, p=30, f=62, feat="孜然爆炒鸭丁，香气足，脂肪高于鸡肉"),
        "家常豆腐": dict(cat="豆制品", portion=220, total=300, c=18, p=30, f=52, feat="豆腐煎后烧制，入味软嫩，脂肪来自用油较多"),
        "小炒鸡": dict(cat="肉类-鸡肉", portion=220, total=400, c=10, p=42, f=48, feat="家常小炒鸡，下饭菜，蛋白优质"),
        "小炒鸡块": dict(cat="肉类-鸡肉", portion=230, total=410, c=10, p=42, f=48, feat="鸡块小炒，口感结实，蛋白高"),
        "小笼包": dict(cat="主食-面食", portion=180, total=380, c=45, p=18, f=37, feat="皮薄馅香，汤汁足，碳水为主并含一定脂肪"),
        "小米粥": dict(cat="主食-粥品", portion=300, total=150, c=80, p=12, f=8, feat="小米熬粥，清淡易消化，热量低、碳水为主"),
        "尖椒炒鸡蛋": dict(cat="蛋类", portion=200, total=260, c=10, p=35, f=55, feat="尖椒配鸡蛋，家常快手菜，蛋白不错、用油带来脂肪"),
        "尖椒炒鸭血": dict(cat="肉类-鸭肉", portion=200, total=180, c=15, p=45, f=40, feat="鸭血配尖椒，低脂高蛋白，适合清口"),
        "尖椒豆腐丝": dict(cat="豆制品", portion=200, total=220, c=20, p=35, f=45, feat="豆腐丝配尖椒，清爽有嚼劲，植物蛋白好"),
        "尖椒鸭血": dict(cat="肉类-鸭肉", portion=200, total=175, c=15, p=45, f=40, feat="鸭血尖椒快炒，热量较低，蛋白密度高"),
        "山城辣子鸡": dict(cat="肉类-鸡肉", portion=230, total=520, c=12, p=35, f=53, feat="干辣炒鸡，用油偏多，香辣过瘾，热量偏高"),
        "山药西兰花": dict(cat="蔬菜类", portion=200, total=160, c=45, p=20, f=35, feat="山药配西兰花，清炒低负担，膳食纤维好"),
        "椒盐大虾": dict(cat="肉类-水产", portion=180, total=320, c=10, p=45, f=45, feat="椒盐处理大虾，蛋白优质，油炸或煎制会抬高脂肪"),
        "椒盐虾": dict(cat="肉类-水产", portion=160, total=280, c=10, p=45, f=45, feat="椒盐虾，鲜香脆口，蛋白高"),
        "清蒸鱼": dict(cat="肉类-水产", portion=220, total=240, c=5, p=60, f=35, feat="清蒸做法少油，优质蛋白极高，适合减脂"),
        "油泼豆腐": dict(cat="豆制品", portion=220, total=280, c=15, p=30, f=55, feat="豆腐浇热油香料，软嫩入味，脂肪来自泼油"),
        "油条": dict(cat="小吃", portion=100, total=380, c=40, p=10, f=50, feat="油炸面食，脂肪与热量密度都很高"),
        "油饼": dict(cat="小吃", portion=120, total=400, c=42, p=10, f=48, feat="煎炸面饼，香酥，碳水脂肪双高"),
        "炸薯饼": dict(cat="小吃", portion=120, total=320, c=50, p=8, f=42, feat="薯泥油炸成型，淀粉为主，外酥里软"),
        "烤肠": dict(cat="肉类-猪肉", portion=80, total=220, c=10, p=20, f=70, feat="烤制香肠，脂肪很高，早餐加餐属性"),
        "煎鸡蛋": dict(cat="蛋类", portion=60, total=110, c=2, p=35, f=63, feat="单份煎蛋，蛋白优质，脂肪来自蛋黄与用油"),
        "鸡蛋": dict(cat="蛋类", portion=55, total=80, c=2, p=35, f=63, feat="水煮或原味蛋，基础蛋白来源，热量可控"),
        "豆浆": dict(cat="豆制品", portion=300, total=120, c=40, p=35, f=25, feat="豆浆饮品，清淡，植物蛋白友好"),
        "豆腐脑": dict(cat="豆制品", portion=250, total=140, c=25, p=35, f=40, feat="嫩豆腐脑，口感滑嫩，热量较低"),
        "蛋挞": dict(cat="甜品", portion=70, total=230, c=40, p=10, f=50, feat="酥皮蛋液烘烤，糖油充足，甜点热量密度高"),
        "红烧排骨": dict(cat="肉类-猪肉", portion=220, total=480, c=12, p=30, f=58, feat="排骨红烧，肉香骨软，脂肪与蛋白都高"),
        "红烧肉": dict(cat="肉类-猪肉", portion=180, total=650, c=10, p=15, f=75, feat="五花红烧，经典高热量菜，脂肪极高"),
        "酸菜鱼": dict(cat="肉类-水产", portion=350, total=420, c=12, p=45, f=43, feat="酸菜鱼片汤菜，蛋白高，汤油抬高脂肪"),
        "西红柿炒鸡蛋": dict(cat="蛋类", portion=220, total=240, c=20, p=30, f=50, feat="经典家常菜，酸甜适口，蛋白不错"),
        "西红柿牛肉": dict(cat="肉类-牛肉", portion=250, total=380, c=20, p=40, f=40, feat="番茄炖牛腩，营养均衡，适合配饭"),
        "葱爆羊肉": dict(cat="肉类-羊肉", portion=200, total=360, c=8, p=35, f=57, feat="葱爆羊肉，香气足，脂肪偏高"),
        "蚝油牛肉": dict(cat="肉类-牛肉", portion=200, total=320, c=15, p=40, f=45, feat="蚝油滑炒牛肉，嫩滑，蛋白优质"),
        "黑米粥": dict(cat="主食-粥品", portion=300, total=170, c=78, p=12, f=10, feat="黑米熬粥，轻微甜香，碳水为主、热量不高"),
        "绿豆粥": dict(cat="主食-粥品", portion=300, total=160, c=78, p=14, f=8, feat="绿豆熬粥，清火感，热量低"),
        "疙瘩汤": dict(cat="汤类", portion=300, total=220, c=55, p=18, f=27, feat="面疙瘩蔬菜汤，暖胃，碳水为主"),
        "混沌": dict(cat="主食-面食", portion=280, total=360, c=50, p=20, f=30, feat="馄饨汤面食（菜单别字），馅皮包皮，碳水为主"),
        "馄饨": dict(cat="主食-面食", portion=280, total=360, c=50, p=20, f=30, feat="馄饨，皮薄馅嫩，一碗热量中等"),
        "肥牛米线米线": dict(cat="主食-面食", portion=450, total=620, c=50, p=20, f=30, feat="肥牛米线，主食量大，碳水与脂肪都可观"),
        "番茄米线": dict(cat="主食-面食", portion=420, total=520, c=55, p=15, f=30, feat="番茄汤米线，酸香开胃，碳水占比高"),
        "鸡汤米线": dict(cat="主食-面食", portion=420, total=540, c=52, p=18, f=30, feat="鸡汤米线，汤鲜粉滑，一餐主食热量较高"),
        "猪肉白菜水饺": dict(cat="主食-面食", portion=250, total=450, c=45, p=20, f=35, feat="猪肉白菜馅水饺，碳水脂肪并重"),
        "猪肉荠菜馄饨": dict(cat="主食-面食", portion=280, total=380, c=48, p=20, f=32, feat="荠菜猪肉馄饨，清香，热量中等"),
        "鸡蛋韭菜水饺": dict(cat="主食-面食", portion=250, total=420, c=48, p=18, f=34, feat="鸡蛋韭菜馅饺，相对猪肉馅更清淡些"),
        "梅花肉卤面": dict(cat="主食-面食", portion=420, total=680, c=45, p=20, f=35, feat="卤肉浇面，主食+肉卤，热量偏高"),
        "炸酱拉面": dict(cat="主食-面食", portion=420, total=700, c=45, p=18, f=37, feat="炸酱拌拉面，酱香浓，脂肪与碳水都高"),
        "红烧牛肉刀削面": dict(cat="主食-面食", portion=450, total=720, c=48, p=20, f=32, feat="牛肉刀削面，一碗管饱，热量高"),
        "糯米羊排": dict(cat="肉类-羊肉", portion=250, total=520, c=25, p=25, f=50, feat="羊排配糯米，碳水与脂肪双高，很顶饱"),
        "蒸糯米鸡腿": dict(cat="肉类-鸡肉", portion=250, total=480, c=30, p=30, f=40, feat="糯米蒸鸡腿，主食感强，热量偏高"),
        "酱烧棒骨": dict(cat="肉类-猪肉", portion=250, total=520, c=10, p=30, f=60, feat="棒骨酱烧，骨髓油脂多，热量高"),
        "酱肘块": dict(cat="肉类-猪肉", portion=220, total=560, c=8, p=25, f=67, feat="酱肘子切块，胶原与脂肪丰富，热量很高"),
        "酱香鸭腿": dict(cat="肉类-鸭肉", portion=200, total=420, c=5, p=30, f=65, feat="酱香鸭腿，肉香浓，脂肪高于鸡腿"),
        "麻辣半块鸭": dict(cat="肉类-鸭肉", portion=250, total=520, c=5, p=28, f=67, feat="麻辣鸭，刺激下饭，脂肪热量都高"),
        "鸭血粉丝": dict(cat="主食-面食", portion=400, total=480, c=45, p=20, f=35, feat="鸭血粉丝汤，粉类碳水高，鸭血补蛋白"),
        "黄金鸡柳": dict(cat="肉类-鸡肉", portion=160, total=380, c=25, p=30, f=45, feat="裹粉炸鸡柳，外酥里嫩，油炸抬高热量"),
        "黑椒鸡肉套餐": dict(cat="主食-套餐", portion=400, total=700, c=40, p=28, f=32, feat="黑椒鸡配主食套餐，一餐热量较高"),
        "玉米": dict(cat="蔬菜类", portion=200, total=200, c=80, p=12, f=8, feat="水煮玉米，膳食纤维好，碳水供能"),
        "杂粮煎饼": dict(cat="主食-面食", portion=180, total=360, c=55, p=15, f=30, feat="杂粮煎饼，通常加油蛋菜，热量中高"),
        "水煎包": dict(cat="主食-面食", portion=180, total=400, c=45, p=15, f=40, feat="水煎包，底部煎至焦香，脂肪高于蒸包"),
        "馅饼": dict(cat="主食-面食", portion=160, total=380, c=42, p=15, f=43, feat="烙制馅饼，皮酥馅香，脂肪偏高"),
        "肉笼": dict(cat="主食-面食", portion=180, total=390, c=45, p=18, f=37, feat="肉馅笼屉点心，类似小笼/包子，碳水脂肪并重"),
        "肉包子": dict(cat="主食-面食", portion=150, total=320, c=48, p=16, f=36, feat="猪肉包，早餐经典，热量中等"),
        "素包子": dict(cat="主食-面食", portion=150, total=250, c=55, p=14, f=31, feat="素馅包，相对肉包更清淡"),
        "糯米烧麦": dict(cat="主食-面食", portion=150, total=330, c=55, p=12, f=33, feat="糯米烧麦，黏香，碳水占比高"),
        "枣卷": dict(cat="甜品", portion=80, total=260, c=60, p=8, f=32, feat="枣泥面卷，甜食，糖分高"),
        "枣泥酥": dict(cat="甜品", portion=70, total=280, c=50, p=6, f=44, feat="酥皮枣泥，油糖双高"),
        "核桃酥": dict(cat="甜品", portion=60, total=300, c=40, p=8, f=52, feat="核桃酥饼，坚果油脂多，热量密度极高"),
        "豆沙酥": dict(cat="甜品", portion=70, total=270, c=55, p=8, f=37, feat="豆沙酥点，甜香，碳水脂肪高"),
        "豆沙饼": dict(cat="甜品", portion=80, total=250, c=58, p=8, f=34, feat="豆沙饼，甜口主食点心"),
        "糖火烧": dict(cat="主食-面食", portion=100, total=300, c=60, p=10, f=30, feat="甜味火烧，面香糖香，碳水为主"),
        "火腿烧饼": dict(cat="主食-面食", portion=120, total=340, c=45, p=15, f=40, feat="烧饼夹火腿，干香，脂肪不低"),
        "鸡蛋烧饼": dict(cat="主食-面食", portion=140, total=360, c=42, p=16, f=42, feat="烧饼配蛋，更顶饱"),
        "鸡蛋软饼": dict(cat="主食-面食", portion=160, total=320, c=45, p=18, f=37, feat="鸡蛋软饼，软韧，早餐友好"),
        "牛肉饼": dict(cat="肉类-牛肉", portion=120, total=300, c=20, p=30, f=50, feat="煎制牛肉饼，蛋白脂肪双高"),
        "肉饼": dict(cat="肉类-猪肉", portion=120, total=320, c=18, p=25, f=57, feat="猪肉馅饼/肉饼，油脂较多"),
        "芹菜火腿饼": dict(cat="主食-面食", portion=140, total=330, c=40, p=18, f=42, feat="菜肉烙饼，咸香"),
        "照烧汁炒饭": dict(cat="主食-炒饭", portion=350, total=580, c=55, p=15, f=30, feat="照烧风味炒饭，用油与酱汁抬高热量"),
        "照烧肉酱炒饭": dict(cat="主食-炒饭", portion=380, total=620, c=50, p=18, f=32, feat="肉酱照烧炒饭，更顶饱，热量高"),
        "豉椒牛肉炒饭": dict(cat="主食-炒饭", portion=380, total=640, c=48, p=20, f=32, feat="豉椒牛肉粒炒饭，香咸，一餐热量高"),
        "酱油炒饭": dict(cat="主食-炒饭", portion=320, total=520, c=58, p=12, f=30, feat="酱油炒饭，简单高碳，用油决定热量"),
        "糟辣子肉末炒饭": dict(cat="主食-炒饭", portion=360, total=600, c=50, p=16, f=34, feat="糟辣肉末炒饭，香辣下饭，热量偏高"),
        "番茄虫草牛腩盅": dict(cat="肉类-牛肉", portion=350, total=420, c=18, p=40, f=42, feat="炖盅牛腩，汤菜形式，蛋白好、热量中高"),
        "萝卜汆肥牛": dict(cat="肉类-牛肉", portion=300, total=360, c=15, p=40, f=45, feat="萝卜汆肥牛，汤鲜肉片，脂肪看肥牛部位"),
        "莲藕排骨": dict(cat="肉类-猪肉", portion=300, total=380, c=25, p=30, f=45, feat="莲藕排骨汤/炖，暖胃，热量中等偏高"),
        "芸豆排骨白汁": dict(cat="肉类-猪肉", portion=300, total=400, c=25, p=28, f=47, feat="芸豆烧排骨，软烂入味，脂肪不低"),
        "水煮什锦": dict(cat="肉类-综合", portion=350, total=480, c=12, p=30, f=58, feat="水煮系列浇红油，麻辣过瘾，油量高"),
        "青红椒丁炒鱼豆腐": dict(cat="豆制品", portion=220, total=280, c=18, p=35, f=47, feat="鱼豆腐配彩椒，弹嫩，用油决定热量"),
        "炒烤鱼豆腐": dict(cat="豆制品", portion=200, total=300, c=15, p=35, f=50, feat="烤香后炒制鱼豆腐，风味足，脂肪偏高"),
        "肉末白菜鱼豆腐": dict(cat="肉类-猪肉", portion=250, total=320, c=15, p=35, f=50, feat="肉末配白菜鱼豆腐，家常，热量适中"),
        "肉末粉丝": dict(cat="肉类-猪肉", portion=250, total=380, c=40, p=18, f=42, feat="肉末烧粉丝，粉丝吸油，碳水脂肪高"),
        "肉末粉丝圆白菜": dict(cat="肉类-猪肉", portion=260, total=360, c=35, p=20, f=45, feat="肉末粉丝配圆白菜，更均衡些"),
        "肉末炒白菜豆腐": dict(cat="肉类-猪肉", portion=250, total=300, c=15, p=30, f=55, feat="肉末白菜豆腐，软烂下饭"),
        "鲜肉炒腐竹": dict(cat="肉类-猪肉", portion=220, total=340, c=20, p=30, f=50, feat="猪肉炒腐竹，筋道吸味，脂肪不低"),
        "肉炖腐竹": dict(cat="肉类-猪肉", portion=230, total=360, c=18, p=28, f=54, feat="猪肉炖腐竹，软烂醇厚"),
        "肉炒土豆片": dict(cat="肉类-猪肉", portion=230, total=340, c=40, p=20, f=40, feat="土豆片炒肉，淀粉感强"),
        "肉炒芹菜": dict(cat="肉类-猪肉", portion=220, total=300, c=15, p=30, f=55, feat="芹菜炒肉丝，清香，用油影响热量"),
        "肉炒蒜黄": dict(cat="肉类-猪肉", portion=220, total=310, c=12, p=30, f=58, feat="蒜黄炒肉，香味足"),
        "肉炒青椒": dict(cat="肉类-猪肉", portion=220, total=300, c=12, p=30, f=58, feat="青椒肉丝经典，下饭"),
        "芹菜炒肉": dict(cat="肉类-猪肉", portion=220, total=300, c=15, p=30, f=55, feat="芹菜炒肉，清脆"),
        "青笋炒肉": dict(cat="肉类-猪肉", portion=220, total=290, c=18, p=30, f=52, feat="莴笋炒肉，水分高、负担相对小"),
        "肉片溜玉兰片": dict(cat="肉类-猪肉", portion=220, total=300, c=20, p=30, f=50, feat="玉兰片溜肉片，笋香清爽"),
        "肉西葫芦": dict(cat="肉类-猪肉", portion=230, total=280, c=18, p=28, f=54, feat="西葫芦炒肉，家常清淡向"),
        "肉丝韭菜香干": dict(cat="肉类-猪肉", portion=220, total=320, c=12, p=35, f=53, feat="肉丝配香干韭菜，豆香与蛋白双在"),
        "青椒肥牛": dict(cat="肉类-牛肉", portion=220, total=360, c=10, p=35, f=55, feat="青椒炒肥牛，油脂感强"),
        "青瓜鱼片": dict(cat="肉类-水产", portion=220, total=260, c=12, p=50, f=38, feat="黄瓜配鱼片，清爽高蛋白"),
        "西芹虾仁": dict(cat="肉类-水产", portion=200, total=240, c=12, p=50, f=38, feat="西芹虾仁，脆嫩低负担"),
        "西芹银杏虾仁": dict(cat="肉类-水产", portion=200, total=260, c=18, p=45, f=37, feat="西芹银杏配虾仁，清香，蛋白好"),
        "鱼丁鸡蛋": dict(cat="肉类-水产", portion=220, total=280, c=8, p=45, f=47, feat="鱼丁炒蛋，蛋白密度高"),
        "虾仁蒸鸡蛋": dict(cat="蛋类", portion=220, total=240, c=5, p=45, f=50, feat="蒸蛋镶虾仁，嫩滑，少油更友好"),
        "赛螃蟹": dict(cat="蛋类", portion=200, total=280, c=10, p=30, f=60, feat="鸡蛋模拟蟹味炒制，用油较多"),
        "香煎三黄鸡": dict(cat="肉类-鸡肉", portion=230, total=450, c=5, p=40, f=55, feat="三黄鸡香煎，皮香肉嫩，脂肪偏高"),
        "皮蒜薄荷鸡": dict(cat="肉类-鸡肉", portion=220, total=380, c=8, p=45, f=47, feat="薄荷蒜香手撕/凉拌鸡，风味清爽"),
        "手撕鸡柠檬": dict(cat="肉类-鸡肉", portion=200, total=320, c=8, p=50, f=42, feat="柠檬手撕鸡，酸香开胃，蛋白高"),
        "蜜制鸭翅根": dict(cat="肉类-鸭肉", portion=180, total=400, c=15, p=25, f=60, feat="蜜汁翅根，甜香，脂肪热量高"),
        "川香鸭柳": dict(cat="肉类-鸭肉", portion=200, total=380, c=8, p=30, f=62, feat="川香鸭柳，辣香，脂肪高于鸡"),
        "魔芋烧鸭": dict(cat="肉类-鸭肉", portion=230, total=360, c=15, p=30, f=55, feat="魔芋烧鸭，魔芋低卡但鸭肉油脂拉高整体"),
        "香辣排骨": dict(cat="肉类-猪肉", portion=220, total=500, c=12, p=28, f=60, feat="香辣排骨，干香或红烧向，热量高"),
        "酱爆鸡丁": dict(cat="肉类-鸡肉", portion=200, total=360, c=12, p=40, f=48, feat="酱爆鸡丁，咸香，蛋白好"),
        "酱爆果仁鸡丁": dict(cat="肉类-鸡肉", portion=200, total=400, c=15, p=35, f=50, feat="果仁酱爆鸡丁，坚果抬高脂肪热量"),
        "红烩牛腩": dict(cat="肉类-牛肉", portion=250, total=420, c=18, p=38, f=44, feat="红烩牛腩，酱汁浓，适合配主食"),
        "红烧日本豆腐": dict(cat="豆制品", portion=220, total=320, c=15, p=25, f=60, feat="日本豆腐易吸油，烧制后脂肪偏高"),
        "砂锅豆腐": dict(cat="豆制品", portion=300, total=280, c=15, p=30, f=55, feat="砂锅豆腐，汤菜，整体热量看浇头与油"),
        "香菇烧豆腐": dict(cat="豆制品", portion=220, total=240, c=20, p=30, f=50, feat="香菇烧豆腐，菌香，相对清淡"),
        "香菇烧千叶豆腐": dict(cat="豆制品", portion=220, total=250, c=18, p=35, f=47, feat="千叶豆腐配香菇，Q弹，蛋白友好"),
        "香菇芥蓝牛肉片": dict(cat="肉类-牛肉", portion=220, total=330, c=12, p=40, f=48, feat="芥蓝牛肉片，荤素搭配较均衡"),
        "豆豉鲮鱼油麦菜": dict(cat="蔬菜类", portion=200, total=180, c=20, p=25, f=55, feat="油麦菜配豆豉鲮鱼，清脆，鲮鱼带来脂肪"),
        "蒜蓉娃娃菜": dict(cat="蔬菜类", portion=200, total=140, c=30, p=15, f=55, feat="蒜蓉娃娃菜，低卡蔬菜，热量主要来自油"),
        "蒜蓉芥兰": dict(cat="蔬菜类", portion=180, total=150, c=25, p=18, f=57, feat="蒜蓉芥兰，纤维足，少油更友好"),
        "蒜香脆鲍菇": dict(cat="菌菇类", portion=180, total=200, c=30, p=20, f=50, feat="杏鲍菇煎香，嚼劲足，用油决定热量"),
        "白灼罗马生菜": dict(cat="蔬菜类", portion=180, total=120, c=25, p=15, f=60, feat="白灼生菜，极低食材热量，酱汁/油是关键"),
        "手撕圆白菜": dict(cat="蔬菜类", portion=180, total=130, c=35, p=15, f=50, feat="手撕圆白菜凉拌或快炒，清爽低负担"),
        "素炒圆白菜": dict(cat="蔬菜类", portion=200, total=150, c=35, p=12, f=53, feat="素炒圆白菜，家常素菜"),
        "素炒土豆丝": dict(cat="蔬菜类", portion=200, total=180, c=55, p=8, f=37, feat="土豆丝素炒，淀粉感，热量高于叶菜"),
        "素炒油菜": dict(cat="蔬菜类", portion=180, total=130, c=25, p=15, f=60, feat="清炒油菜，绿叶菜，热量低"),
        "素炒笋丝": dict(cat="蔬菜类", portion=180, total=120, c=40, p=15, f=45, feat="笋丝清炒，低热量高纤维"),
        "素炒西兰花": dict(cat="蔬菜类", portion=180, total=140, c=30, p=20, f=50, feat="清炒西兰花，营养密度高"),
        "炝炒绿豆芽": dict(cat="蔬菜类", portion=200, total=110, c=40, p=20, f=40, feat="豆芽炝炒，非常清淡"),
        "杏鲍菇炒芹菜": dict(cat="菌菇类", portion=200, total=160, c=30, p=20, f=50, feat="菌菇配芹菜，清香低负担"),
        "红枣南瓜": dict(cat="蔬菜类", portion=200, total=180, c=70, p=8, f=22, feat="红枣蒸/炖南瓜，甜软，碳水为主"),
        "醋溜白菜": dict(cat="蔬菜类", portion=200, total=140, c=35, p=12, f=53, feat="醋溜白菜，酸脆开胃"),
        "醋溜木须": dict(cat="肉类-猪肉", portion=220, total=300, c=15, p=30, f=55, feat="木须肉醋溜风味，蛋肉搭配"),
        "鸡蛋汤": dict(cat="汤类", portion=300, total=80, c=10, p=40, f=50, feat="蛋花汤，清淡低热量"),
        "鸡蛋炒芹菜": dict(cat="蛋类", portion=200, total=230, c=12, p=30, f=58, feat="芹菜炒蛋，清香"),
        "鸡蛋炒西葫芦": dict(cat="蛋类", portion=220, total=230, c=15, p=30, f=55, feat="西葫芦炒蛋，家常"),
        "鸡蛋笋片": dict(cat="蛋类", portion=200, total=220, c=12, p=32, f=56, feat="笋片炒蛋，清爽"),
        "鸡蛋炒米线": dict(cat="主食-面食", portion=380, total=520, c=55, p=15, f=30, feat="鸡蛋炒米线，主食向，碳水高"),
        "火腿煎蛋": dict(cat="蛋类", portion=150, total=280, c=5, p=30, f=65, feat="火腿配煎蛋，早餐高脂高蛋白"),
        "肉松卷": dict(cat="甜品", portion=80, total=280, c=45, p=12, f=43, feat="肉松蛋糕卷，甜咸，热量密度高"),
        "肉松土司片": dict(cat="甜品", portion=90, total=300, c=48, p=12, f=40, feat="肉松土司，方便加餐"),
        "肉松蛋糕卷": dict(cat="甜品", portion=90, total=310, c=45, p=12, f=43, feat="蛋糕卷夹肉松，甜品属性"),
        "草莓蛋糕": dict(cat="甜品", portion=100, total=320, c=50, p=8, f=42, feat="奶油蛋糕，糖油高"),
        "蜂蜜蛋糕杯": dict(cat="甜品", portion=100, total=330, c=52, p=8, f=40, feat="蜂蜜口味蛋糕杯，甜食"),
        "巧克力蛋糕": dict(cat="甜品", portion=100, total=380, c=45, p=8, f=47, feat="巧克力蛋糕，热量密度很高"),
        "巧克力斑马蛋糕": dict(cat="甜品", portion=100, total=370, c=48, p=8, f=44, feat="斑马纹蛋糕，糖油充足"),
        "巧克力马芬蛋糕": dict(cat="甜品", portion=90, total=360, c=45, p=8, f=47, feat="巧克力马芬，烘焙甜点"),
        "巧克力甜甜圈面包": dict(cat="甜品", portion=90, total=380, c=48, p=7, f=45, feat="甜甜圈面包，油炸或高油配方"),
        "巧克力雷神面包": dict(cat="甜品", portion=100, total=400, c=48, p=8, f=44, feat="巧克力夹心面包，热量高"),
        "岩烧乳酪面包": dict(cat="甜品", portion=100, total=360, c=45, p=12, f=43, feat="岩烧乳酪面包，乳酪增加脂肪蛋白"),
        "海盐芝士面包": dict(cat="甜品", portion=100, total=350, c=45, p=12, f=43, feat="海盐芝士面包，咸甜风"),
        "香肠芝士面包": dict(cat="甜品", portion=120, total=390, c=40, p=15, f=45, feat="香肠芝士面包，更顶饱"),
        "酸奶岩烧面包": dict(cat="甜品", portion=100, total=340, c=50, p=12, f=38, feat="酸奶岩烧风味面包"),
        "蓝莓果酱面包": dict(cat="甜品", portion=100, total=330, c=55, p=8, f=37, feat="果酱面包，糖分高"),
        "椰蓉芝士排包": dict(cat="甜品", portion=90, total=360, c=45, p=10, f=45, feat="椰蓉芝士排包，烘焙点心"),
        "蔓越莓饼": dict(cat="甜品", portion=70, total=280, c=55, p=6, f=39, feat="蔓越莓曲奇/饼，黄油感强"),
        "麻薯": dict(cat="甜品", portion=80, total=220, c=70, p=5, f=25, feat="麻薯糯米点心，高碳水"),
        "麻薯鲜奶棉花杯": dict(cat="甜品", portion=150, total=320, c=55, p=8, f=37, feat="麻薯鲜奶甜点杯，糖奶充足"),
        "黄油年糕": dict(cat="甜品", portion=100, total=300, c=60, p=5, f=35, feat="黄油年糕，黏甜，碳水脂肪高"),
        "黄油曲多多": dict(cat="甜品", portion=60, total=300, c=45, p=5, f=50, feat="黄油曲奇，热量密度极高"),
        "焦糖奶酪烧": dict(cat="甜品", portion=100, total=340, c=45, p=10, f=45, feat="焦糖奶酪烘焙，甜品高热"),
        "黑米奶酪三明治": dict(cat="主食-套餐", portion=180, total=380, c=45, p=15, f=40, feat="黑米面包配奶酪，早餐较顶饱"),
        "黑米奶酩三明治": dict(cat="主食-套餐", portion=180, total=380, c=45, p=15, f=40, feat="黑米三明治（奶酪），同奶酪三明治热量水平"),
        "热狗面包": dict(cat="主食-套餐", portion=160, total=400, c=40, p=15, f=45, feat="热狗面包夹肠，脂肪偏高"),
        "鸡肉汉堡": dict(cat="主食-套餐", portion=220, total=480, c=35, p=25, f=40, feat="鸡肉汉堡，一套热量中高"),
        "鸡腿堡": dict(cat="主食-套餐", portion=230, total=520, c=35, p=25, f=40, feat="鸡腿堡，炸制鸡腿抬高热量"),
        "鸡腿肉汉堡": dict(cat="主食-套餐", portion=230, total=500, c=35, p=25, f=40, feat="鸡腿肉汉堡，顶饱"),
        "黑胡椒雪鱼": dict(cat="肉类-水产", portion=200, total=280, c=10, p=50, f=40, feat="黑椒雪鱼，高蛋白少刺，脂肪相对可控"),
    }

    if n in overrides:
        o = overrides[n]
        c, p, f = _norm_pct(o["c"], o["p"], o["f"])
        portion = o["portion"]
        total = o["total"]
        return {
            "kcal": int(round(total * 100 / portion)),
            "carb_pct": c,
            "protein_pct": p,
            "fat_pct": f,
            "features": o["feat"],
            "total_kcal": total,
            "portion_g": portion,
            "category": o["cat"],
        }

    # ---- 规则模板 ----
    breakfast = "主食早餐" in floors

    def pack(cat, portion, total, c, p, f, feat):
        c, p, f = _norm_pct(c, p, f)
        return {
            "kcal": int(round(total * 100 / portion)),
            "carb_pct": c,
            "protein_pct": p,
            "fat_pct": f,
            "features": feat,
            "total_kcal": int(total),
            "portion_g": int(portion),
            "category": cat,
        }

    # 甜品 / 烘焙
    if any(k in n for k in ("蛋糕", "面包", "马芬", "甜甜圈", "曲奇", "酥", "麻薯", "蛋挞", "年糕")):
        return pack("甜品", 90, 340, 48, 8, 44, f"{n}属烘焙甜点，糖油含量高，热量密度大，宜作加餐少量食用")

    # 粥饮
    if n.endswith("粥") or n in {"豆浆", "豆腐脑"}:
        return pack("主食-粥品" if "豆浆" not in n and "豆腐脑" not in n else "豆制品", 300, 150, 75, 15, 10, f"{n}清淡易消化，热量较低，适合早餐搭配蛋白质食物")

    # 汤
    if "汤" in n:
        return pack("汤类", 300, 180, 40, 25, 35, f"{n}以汤为主，整体热量通常不高，具体看浇头用油")

    # 面 / 粉 / 米线 / 饺 / 馄饨 / 包子
    if any(k in n for k in ("面", "粉", "米线", "饺", "馄饨", "混沌", "包子", "烧麦", "煎饼", "烧饼", "火烧", "饼")) and "肉饼" not in n and "牛肉饼" not in n:
        return pack("主食-面食", 380 if any(k in n for k in ("面", "粉", "米线")) else 180, 560 if any(k in n for k in ("面", "粉", "米线")) else 340, 50, 18, 32, f"{n}主食属性强，碳水占比高，一份热量中高")

    # 炒饭 / 盖饭 / 套餐 / 汉堡
    if any(k in n for k in ("炒饭", "盖饭", "套餐", "汉堡", "堡", "焗饭")):
        return pack("主食-盖饭", 400, 680, 45, 22, 33, f"{n}含主食的一餐组合，总热量较高，注意搭配蔬菜")

    # 水产
    if any(k in n for k in ("鱼", "虾", "蟹", "鳕", "龙利", "雪鱼")):
        return pack("肉类-水产", 220, 300, 10, 50, 40, f"{n}水产优质蛋白高，清蒸类更低脂，干炸/椒盐会抬高脂肪")

    # 鸭
    if "鸭" in n:
        return pack("肉类-鸭肉", 200, 400, 8, 30, 62, f"{n}鸭肉脂肪通常高于鸡肉，香浓下饭，热量偏高")

    # 牛
    if any(k in n for k in ("牛", "肥牛", "牛排")):
        return pack("肉类-牛肉", 220, 360, 12, 38, 50, f"{n}牛肉优质蛋白好，肥牛/酱烧类脂肪更高")

    # 羊
    if "羊" in n:
        return pack("肉类-羊肉", 200, 360, 8, 35, 57, f"{n}羊肉膻香，爆炒类用油较多，脂肪偏高")

    # 猪/肉末/回锅/排骨/五花
    if any(k in n for k in ("猪", "肉末", "回锅", "排骨", "五花", "肘", "腊肉", "叉烧", "肉片", "肉丝", "肉丁", "炒肉", "小炒肉")):
        return pack("肉类-猪肉", 220, 360, 12, 28, 60, f"{n}猪肉类家常菜，脂肪含量看部位与用油，整体热量中高")

    # 鸡
    if "鸡" in n:
        return pack("肉类-鸡肉", 220, 380, 10, 42, 48, f"{n}鸡肉优质蛋白高，炸/干锅类热量显著高于炒煮")

    # 蛋
    if "蛋" in n:
        return pack("蛋类", 200, 240, 10, 35, 55, f"{n}以蛋为主，优质蛋白，脂肪来自蛋黄与用油")

    # 豆腐/豆制品
    if any(k in n for k in ("豆腐", "豆干", "腐竹", "豆花", "千叶")):
        return pack("豆制品", 220, 260, 18, 32, 50, f"{n}豆制品植物蛋白好，烧/油泼做法会增加脂肪")

    # 菌菇
    if any(k in n for k in ("菇", "蘑", "木耳")):
        return pack("菌菇类", 200, 170, 35, 20, 45, f"{n}菌菇低热量高纤维，热量主要来自用油与配菜")

    # 默认蔬菜
    if any(k in n for k in ("菜", "瓜", "笋", "茄", "椒", "洋葱", "萝卜", "南瓜", "玉米", "土豆", "藕")) or breakfast:
        if breakfast and any(k in n for k in ("肠",)):
            return pack("肉类-猪肉", 80, 220, 10, 20, 70, f"{n}加工肉类，脂肪高，建议少量")
        return pack("蔬菜类", 200, 150, 35, 15, 50, f"{n}蔬菜为主，食材热量低，实际热量主要看用油量")

    # 兜底
    return pack("其他", 220, 320, 30, 25, 45, f"{n}按食堂家常菜估算，热量中等，建议搭配主食与蔬菜")


def macros_from_category(name: str, category: str | None) -> tuple[float, float, float, str]:
    """给已有总热量但缺宏量素的菜补占比与特点。"""
    cat = category or ""
    n = name
    if cat.startswith("主食") or any(k in n for k in ("面", "饭", "粉", "米线", "饺")):
        return _norm_pct(50, 18, 32) + (f"{n}主食属性强，碳水供能占比高，一份热量通常不低",)
    if "甜品" in cat or "小吃" in cat:
        return _norm_pct(48, 8, 44) + (f"{n}偏零食/点心，糖油充足，热量密度高",)
    if "蔬菜" in cat or "菌菇" in cat:
        return _norm_pct(35, 15, 50) + (f"{n}蔬菜/菌菇为主，食材低热，脂肪主要来自烹调用油",)
    if "蛋" in cat:
        return _norm_pct(8, 35, 57) + (f"{n}蛋类优质蛋白，脂肪来自蛋黄与用油",)
    if "豆" in cat:
        return _norm_pct(18, 32, 50) + (f"{n}豆制品植物蛋白好，烧制用油会抬高脂肪占比",)
    if "水产" in cat or any(k in n for k in ("鱼", "虾")):
        return _norm_pct(10, 50, 40) + (f"{n}水产优质蛋白高，做法决定脂肪高低",)
    if "鸭" in cat:
        return _norm_pct(8, 30, 62) + (f"{n}鸭肉脂肪通常较高，香浓下饭",)
    if "牛" in cat:
        return _norm_pct(12, 38, 50) + (f"{n}牛肉蛋白优质，肥瘦与酱汁影响脂肪",)
    if "羊" in cat:
        return _norm_pct(8, 35, 57) + (f"{n}羊肉脂肪偏高，爆炒类热量上升明显",)
    if "鸡" in cat:
        return _norm_pct(10, 42, 48) + (f"{n}鸡肉高蛋白，炸烤类热量高于炒煮",)
    if "猪" in cat or "肉类" in cat:
        return _norm_pct(12, 28, 60) + (f"{n}猪肉类家常菜，脂肪含量中高",)
    return _norm_pct(30, 25, 45) + (f"{n}按食堂常见出品估算宏量素分布",)


def main() -> None:
    dishes = json.loads(DISHES.read_text(encoding="utf-8"))
    filled_full = 0
    filled_macros = 0

    for dish in dishes:
        name = dish["name"]
        floors = dish.get("floors") or []

        if not dish.get("total_kcal"):
            est = estimate(name, floors)
            dish.update(est)
            filled_full += 1
            continue

        # 已有热量但缺宏量素 / 特点
        if not (dish.get("carb_pct") or dish.get("protein_pct") or dish.get("fat_pct")):
            c, p, f, feat = macros_from_category(name, dish.get("category"))
            dish["carb_pct"] = c
            dish["protein_pct"] = p
            dish["fat_pct"] = f
            if not dish.get("features"):
                dish["features"] = feat
            # 若缺每100g，用总热量反推
            if not dish.get("kcal") and dish.get("portion_g"):
                dish["kcal"] = int(round(dish["total_kcal"] * 100 / dish["portion_g"]))
            filled_macros += 1
        elif not dish.get("features"):
            _, _, _, feat = macros_from_category(name, dish.get("category"))
            dish["features"] = feat

    DISHES.write_text(json.dumps(dishes, ensure_ascii=False, indent=2), encoding="utf-8")
    missing_left = sum(1 for d in dishes if not d.get("total_kcal"))
    no_macros = sum(1 for d in dishes if not (d.get("carb_pct") or d.get("protein_pct") or d.get("fat_pct")))
    print(f"filled_full={filled_full}, filled_macros={filled_macros}")
    print(f"remaining missing total_kcal={missing_left}, missing macros={no_macros}")
    print(f"total dishes={len(dishes)}")
    sample = next(d for d in dishes if d["name"] == "东坡肉")
    print("sample 东坡肉:", sample)


if __name__ == "__main__":
    main()
