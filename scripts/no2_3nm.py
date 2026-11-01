#!/usr/bin/env python3
"""Chạy thử tín hiệu NO2 Sentinel-5P cho 3 nhà máy khảo sát và 2 nhà máy đối chứng lớn.

Mục đích: trả lời sơ bộ câu R33 trong bộ câu hỏi viễn thám, tức vệ tinh có thấy được
tín hiệu NO2 của Cao Ngạn, Gang thép Thái Nguyên, Vicem Bút Sơn hay không, so với
hai nhà máy rất lớn (Duyên Hải, Mông Dương) làm đối chứng.

Cách làm, cho từng nhà máy và từng ngày 2021 đến 2025:
  * Hộp nhỏ quanh nhà máy (mặc định ±0,05 độ, khoảng 11 km) và hộp vùng (±0,3 độ).
  * Chỉ nhận điểm ảnh có dữ liệu hợp lệ (Sentinel Hub đã lọc qa_value theo mặc định)
    và tỷ lệ mây dưới 0,3 nếu có băng CLOUD_FRACTION.
  * Một ngày là "hợp lệ" khi ít nhất 50% điểm ảnh của hộp nhỏ có dữ liệu.
Kết quả theo tháng: số ngày hợp lệ, NO2 trung bình hộp nhỏ, hộp vùng, chênh lệch
(hộp nhỏ trừ hộp vùng) và tỷ lệ chênh lệch.

Cần biến môi trường CDSE_CLIENT_ID, CDSE_CLIENT_SECRET (đã có trong GitHub Secrets).
Kết quả ghi vào analysis/no2_3nm/: monthly.csv, summary.json, log.txt.
Chỉ dùng thư viện chuẩn Python.
"""
import csv, json, os, sys, time, traceback, urllib.error, urllib.parse, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "no2_3nm")
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

PLANTS = [
    # mã Climate TRACE, tên, vai trò
    ("25452804", "Cao Ngạn (nhiệt điện)", "khảo sát"),
    ("32441113", "Gang thép Thái Nguyên (TISCO)", "khảo sát"),
    ("32439388", "Vicem Bút Sơn (xi măng)", "khảo sát"),
    ("25454003", "Duyên Hải (nhiệt điện, đối chứng)", "đối chứng"),
    ("25453844", "Mông Dương (nhiệt điện, đối chứng)", "đối chứng"),
]
YEARS = [2021, 2022, 2023, 2024, 2025]
SMALL, LARGE, RES = 0.05, 0.3, 0.02

EVAL_CLOUD = """//VERSION=3
function setup(){return {input:[{bands:["NO2","CLOUD_FRACTION","dataMask"]}],
 output:[{id:"no2",bands:1,sampleType:"FLOAT32"},{id:"dataMask",bands:1}]};}
function evaluatePixel(s){var ok=s.dataMask==1&&s.CLOUD_FRACTION<0.3?1:0;return {no2:[s.NO2],dataMask:[ok]};}
"""
EVAL_PLAIN = """//VERSION=3
function setup(){return {input:[{bands:["NO2","dataMask"]}],
 output:[{id:"no2",bands:1,sampleType:"FLOAT32"},{id:"dataMask",bands:1}]};}
function evaluatePixel(s){return {no2:[s.NO2],dataMask:[s.dataMask]};}
"""
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, file=sys.stderr)
    LOG.append(s)


def post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def token():
    cid, sec = os.environ.get("CDSE_CLIENT_ID"), os.environ.get("CDSE_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("Thiếu CDSE_CLIENT_ID hoặc CDSE_CLIENT_SECRET.")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    return post(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def daily(tok, lon, lat, half, year, evalscript):
    body = {
        "input": {"bounds": {"bbox": [lon - half, lat - half, lon + half, lat + half],
                             "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                  "data": [{"type": "sentinel-5p-l2", "dataFilter": {"timeliness": "OFFL"}}]},
        "aggregation": {"timeRange": {"from": f"{year}-01-01T00:00:00Z", "to": f"{year + 1}-01-01T00:00:00Z"},
                        "aggregationInterval": {"of": "P1D"}, "evalscript": evalscript, "resx": RES, "resy": RES},
    }
    for attempt in range(4):
        try:
            r = post(STATS_URL, json.dumps(body).encode(), {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 422):
                raise ValueError(msg)
            log("  thử lại", e.code, msg)
            time.sleep(10 * (attempt + 1))
    else:
        raise RuntimeError("hết lượt thử")
    out = {}
    for it in r.get("data", []):
        try:
            st = it["outputs"]["no2"]["bands"]["B0"]["stats"]
            n, nd = st.get("sampleCount", 0), st.get("noDataCount", 0)
            m = st.get("mean")
            if n and m not in (None, "NaN"):
                out[it["interval"]["from"][:10]] = (float(m), (n - nd) / n)
        except (KeyError, TypeError, ValueError):
            pass
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    assets = {a["id"]: a for a in json.load(open(os.path.join(ROOT, "data", "assets.json"), encoding="utf-8"))["assets"]}
    tok, t0 = token(), time.time()
    evalscript, cloud = EVAL_CLOUD, True
    rows, summary = [], {"generated": date.today().isoformat(), "method": {
        "small_box_deg": SMALL, "large_box_deg": LARGE, "res_deg": RES, "valid_day_min_coverage": 0.5,
        "cloud_filter": None, "qa_filter": "mặc định của Sentinel Hub cho NO2", "timeliness": "OFFL"}, "plants": []}
    for pid, name, role in PLANTS:
        a = assets.get(pid)
        if not a:
            log("Không thấy", pid, name); continue
        lon, lat = a["lon"], a["lat"]
        log(f"{name}: {lat:.4f}, {lon:.4f}")
        per_month = {}
        for y in YEARS:
            if time.time() - t0 > 2400:
                tok, t0 = token(), time.time()
            try:
                s = daily(tok, lon, lat, SMALL, y, evalscript)
            except ValueError as e:
                if cloud:
                    log("  Không dùng được CLOUD_FRACTION, chuyển sang lọc mặc định:", e)
                    evalscript, cloud = EVAL_PLAIN, False
                    s = daily(tok, lon, lat, SMALL, y, evalscript)
                else:
                    raise
            l = daily(tok, lon, lat, LARGE, y, evalscript)
            for d, (v, cov) in s.items():
                k = d[:7]
                pm = per_month.setdefault(k, {"days": 0, "vs": [], "vl": []})
                if cov >= 0.5:
                    pm["days"] += 1
                    pm["vs"].append(v)
                    if d in l:
                        pm["vl"].append(l[d][0])
            log(f"  {y}: {sum(1 for v in s.values() if v[1] >= 0.5)} ngày hợp lệ")
            time.sleep(1)
        tot_days, enh = 0, []
        for y in YEARS:
            for m in range(1, 13):
                k = f"{y}-{m:02d}"
                pm = per_month.get(k, {"days": 0, "vs": [], "vl": []})
                ms = sum(pm["vs"]) / len(pm["vs"]) if pm["vs"] else None
                ml = sum(pm["vl"]) / len(pm["vl"]) if pm["vl"] else None
                e = (ms - ml) if (ms is not None and ml is not None) else None
                rows.append([pid, name, role, k, pm["days"],
                             f"{ms:.4e}" if ms is not None else "", f"{ml:.4e}" if ml is not None else "",
                             f"{e:.4e}" if e is not None else "", f"{e / ml * 100:.1f}" if (e is not None and ml) else ""])
                tot_days += pm["days"]
                if e is not None and pm["days"] >= 3:
                    enh.append(e / ml * 100 if ml else 0)
        months_ok = sum(1 for r in rows if r[0] == pid and r[4] >= 3)
        enh_sorted = sorted(enh)
        med = enh_sorted[len(enh_sorted) // 2] if enh_sorted else None
        summary["plants"].append({"id": pid, "name": name, "role": role, "lat": lat, "lon": lon,
                                  "climatetrace_t_co2e_2024": a.get("emissions_t_co2e"),
                                  "valid_days_2021_2025": tot_days, "months_with_3plus_valid_days": months_ok,
                                  "median_enhancement_pct": round(med, 1) if med is not None else None,
                                  "months_enhancement_positive": sum(1 for x in enh if x > 0), "months_counted": len(enh)})
    summary["method"]["cloud_filter"] = "CLOUD_FRACTION < 0.3" if cloud else "không có băng CLOUD_FRACTION, chỉ lọc mặc định"
    with open(os.path.join(OUT, "monthly.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "nha_may", "vai_tro", "thang", "so_ngay_hop_le", "no2_hop_nho_mol_m2", "no2_hop_vung_mol_m2",
                    "chenh_lech_mol_m2", "chenh_lech_pct"])
        w.writerows(rows)
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(OUT, "log.txt"), "w", encoding="utf-8").write("\n".join(LOG) + "\n")
    log("Xong")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        os.makedirs(OUT, exist_ok=True)
        LOG.append(traceback.format_exc())
        open(os.path.join(OUT, "log.txt"), "w", encoding="utf-8").write("\n".join(LOG) + "\n")
        raise
