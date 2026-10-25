#!/usr/bin/env python3
"""Tải lại dữ liệu phát thải từng cơ sở của Việt Nam từ Climate TRACE API v6.

Cách chạy:  python3 scripts/update_climatetrace.py
Kết quả:    data/assets.json (năm gốc) và data/yearly.json (chuỗi nhiều năm)
Chỉ dùng thư viện chuẩn của Python 3.9 trở lên, không cần cài thêm gì.
Chỉnh danh sách ngành, quốc gia, các năm trong config/settings.json (khóa "data").
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.climatetrace.org/v6/assets"
PAGE = 100


def cfg():
    p = os.path.join(ROOT, "config", "settings.json")
    try:
        d = json.load(open(p, encoding="utf-8")).get("data", {})
    except Exception:
        d = {}
    return {
        "country": d.get("country", "VNM"),
        "subsectors": d.get("subsectors", ["electricity-generation", "iron-and-steel", "cement"]),
        "baseYear": int(d.get("baseYear", 2024)),
        "years": [int(y) for y in d.get("years", [2021, 2022, 2023, 2024, 2025])],
    }


def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ghg-sat-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_all(country, sub, year):
    out, off = [], 0
    while True:
        d = get({"countries": country, "subsectors": sub, "year": year, "limit": PAGE, "offset": off})
        rows = d.get("assets") if isinstance(d, dict) else d
        rows = rows or []
        out += rows
        if len(rows) < PAGE:
            return out
        off += PAGE


def co2e(asset):
    for s in asset.get("EmissionsSummary") or []:
        if s.get("Gas") == "co2e_100yr":
            return s
    return {}


def conf(asset, year):
    for block in asset.get("Confidence") or []:
        v = block.get(str(year)) if isinstance(block, dict) else None
        if v:
            item = v[0] if isinstance(v, list) else v
            return item.get("co2_emissions", "")
    return ""


def num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def main():
    c = cfg()
    assets, yearly = {}, {}
    for sub in c["subsectors"]:
        for y in c["years"]:
            rows = fetch_all(c["country"], sub, y)
            print(f"{sub} {y}: {len(rows)} cơ sở", file=sys.stderr)
            for a in rows:
                s = co2e(a)
                e = num(s.get("EmissionsQuantity"))
                aid = str(a.get("Id"))
                if e is not None:
                    yearly.setdefault(aid, {})[str(y)] = round(e, 1)
                if y == c["baseYear"]:
                    cen = (a.get("Centroid") or {}).get("Geometry") or [None, None]
                    owners = a.get("Owners") or []
                    ranks = a.get("SectorRanks") or {}
                    assets[aid] = {
                        "id": aid, "name": a.get("Name"), "sector": a.get("Sector") or sub,
                        "asset_type": a.get("AssetType") or "",
                        "lon": num(cen[0]), "lat": num(cen[1]),
                        "capacity": num(s.get("Capacity")), "capacity_units": s.get("CapacityUnits") or "",
                        "activity": num(s.get("Activity")), "activity_units": s.get("ActivityUnits") or "",
                        "ef": num(s.get("EmissionsFactor")), "emissions_t_co2e": e or 0,
                        "owner": owners[0].get("CompanyName", "") if owners else "",
                        "rank2025": ranks.get("2025") if isinstance(ranks, dict) else None,
                        "conf_co2": conf(a, 2025) or conf(a, c["baseYear"]),
                    }
    # bỏ cơ sở không phát thải hoặc thiếu tọa độ
    kept = [a for a in assets.values() if (a["emissions_t_co2e"] or 0) > 0 and a["lon"] is not None]
    kept.sort(key=lambda a: -a["emissions_t_co2e"])
    ids = {a["id"] for a in kept}
    meta = {"source": "Climate TRACE API v6 (api.climatetrace.org)", "fetched": date.today().isoformat(),
            "baseYear": c["baseYear"], "country": c["country"], "sectors": c["subsectors"]}
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump({"meta": meta, "assets": kept}, open(os.path.join(ROOT, "data", "assets.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"meta": meta, "yearly": {k: v for k, v in yearly.items() if k in ids}},
              open(os.path.join(ROOT, "data", "yearly.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Đã ghi {len(kept)} cơ sở vào data/assets.json", file=sys.stderr)


if __name__ == "__main__":
    main()
