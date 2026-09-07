"""把「菜品热量估算表」中的「总热量(kcal)」「出品重量(g)」「类别」合并进 dishes.json。

按菜名精确匹配；匹配不上的菜保留原字段，新增字段置为 null。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DISHES_JSON = ROOT / "data" / "dishes.json"
XLSX_PATH = Path(
    r"C:\Users\luzih\Documents\xwechat_files\wxid_kzabuv4uymt322_792e\msg\file\2026-08\菜品热量估算表.xlsx"
)

sys.stdout.reconfigure(encoding="utf-8")


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def load_portion_map(path: Path) -> dict[str, dict[str, object]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["全部菜品热量"]
    mapping: dict[str, dict[str, object]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        name = str(row[0]).strip()
        # 类别=col1, 出品重量(g)=col6, 总热量(kcal)=col9
        mapping[name] = {
            "total_kcal": _to_float(row[9]),
            "portion_g": _to_float(row[6]),
            "category": str(row[1]).strip() if row[1] else None,
        }
    return mapping


def main() -> None:
    portion = load_portion_map(XLSX_PATH)
    dishes = json.loads(DISHES_JSON.read_text(encoding="utf-8"))

    matched = 0
    for dish in dishes:
        name = str(dish.get("name", "")).strip()
        info = portion.get(name, {})
        total = info.get("total_kcal")
        weight = info.get("portion_g")
        if total is not None:
            dish["total_kcal"] = round(float(total))
            matched += 1
        else:
            dish["total_kcal"] = None
        dish["portion_g"] = round(float(weight)) if weight is not None else None
        dish["category"] = info.get("category")

    DISHES_JSON.write_text(
        json.dumps(dishes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Merged {matched}/{len(dishes)} dishes with portion calories -> {DISHES_JSON}")
    sample = next((d for d in dishes if d["name"] == "宫保鸡丁"), None)
    if sample:
        print(f"Sample 宫保鸡丁: {sample}")


if __name__ == "__main__":
    main()
