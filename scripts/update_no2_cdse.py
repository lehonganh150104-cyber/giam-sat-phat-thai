#!/usr/bin/env python3
"""Lấy NO2 Sentinel-5P (TROPOMI) trung bình tháng quanh từng nhà máy, qua Copernicus Data Space.

Cần tài khoản miễn phí tại https://dataspace.copernicus.eu, rồi tạo OAuth client
(Dashboard > User settings > OAuth clients). Đặt hai biến môi trường:
    CDSE_CLIENT_ID, CDSE_CLIENT_SECRET
Cách chạy:  python3 scripts/update_no2_cdse.py
Kết quả:    data/no2.json; trang web tự hiện biểu đồ NO2 trong phần chi tiết nhà máy.
Mặc định chỉ lấy 15 cơ sở phát thải lớn nhất, 24 tháng gần nhất (chỉnh trong config/settings.json, khóa "no2").
Chỉ dùng thư viện chuẩn của Python.

LƯU Ý: script viết theo tài liệu Sentinel Hub Statistical API trên CDSE, chưa chạy thử được
từ môi trường phát triển. Lần chạy đầu nên thử với 1 nhà máy ("top": 1) để kiểm tra.
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

EVALSCRIPT = """//VERSION=3
function setup() {
  return { input: [{ bands: ["NO2", "dataMask"] }],
           output: [{ id: "no2", bands: 1, sampleType: "FLOAT32" }, { id: "dataMask", bands: 1 }] };
}
function evaluatePixel(s) { return { no2: [s.NO2], dataMask: [s.dataMask] }; }
"""


def post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def token():
    cid, sec = os.environ.get("CDSE_CLIENT_ID"), os.environ.get("CDSE_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("Thiếu CDSE_CLIENT_ID hoặc CDSE_CLIENT_SECRET.")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    return post(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def month_back(d, n):
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12; y -= 1
    return date(y, m, 1)


def main():
    try:
        conf = json.load(open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8")).get("no2", {})
    except Exception:
        conf = {}
    top, months, half = int(conf.get("top", 15)), int(conf.get("months", 24)), float(conf.get("boxDeg", 0.1))
    assets = json.load(open(os.path.join(ROOT, "data", "assets.json"), encoding="utf-8"))["assets"]
    assets = sorted(assets, key=lambda a: -(a.get("emissions_t_co2e") or 0))[:top]
    tok = token()
    start = month_back(date.today().replace(day=1), months)
    end = date.today().replace(day=1)
    series = {}
    for a in assets:
        lon, lat = a["lon"], a["lat"]
        body = {
            "input": {"bounds": {"bbox": [lon - half, lat - half, lon + half, lat + half],
                                 "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                      "data": [{"type": "sentinel-5p-l2", "dataFilter": {"timeliness": "OFFL"}}]},
            "aggregation": {"timeRange": {"from": start.isoformat() + "T00:00:00Z", "to": end.isoformat() + "T00:00:00Z"},
                            "aggregationInterval": {"of": "P1M"}, "evalscript": EVALSCRIPT,
                            "resx": 0.05, "resy": 0.05},
        }
        try:
            r = post(STATS_URL, json.dumps(body).encode(), {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        except Exception as e:
            print(f"Lỗi với {a['name']}: {e}", file=sys.stderr); continue
        rows = []
        for it in r.get("data", []):
            try:
                st = it["outputs"]["no2"]["bands"]["B0"]["stats"]
                if st.get("sampleCount", 0) - st.get("noDataCount", 0) > 0 and st.get("mean") not in (None, "NaN"):
                    rows.append({"m": it["interval"]["from"][:7], "v": float(st["mean"])})
            except (KeyError, TypeError, ValueError):
                pass
        if rows:
            series[a["id"]] = rows
        print(f"{a['name']}: {len(rows)} tháng", file=sys.stderr)
        time.sleep(1)
    json.dump({"meta": {"source": "Sentinel-5P TROPOMI NO2 qua Copernicus Data Space", "fetched": date.today().isoformat(),
                        "unit": "mol/m2", "boxDeg": half}, "series": series},
              open(os.path.join(ROOT, "data", "no2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
