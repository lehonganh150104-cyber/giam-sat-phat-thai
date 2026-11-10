#!/usr/bin/env python3
"""Thống kê NO2 Sentinel-5P theo cụm nhà máy (bản 2, sửa theo góp ý chuyên gia viễn thám, 11/2026).

Mục đích:
  * Đếm số ngày đo hợp lệ theo tháng cho từng cụm (R8: bảng nên làm ngay).
  * So NO2 hộp nhỏ quanh cụm với hộp vùng để xem có tín hiệu nổi lên nền không.
  * Đối chiếu theo cụm khi các nguồn cách nhau dưới khoảng 10 km (R12), không gán cho từng nhà máy.

Thay đổi so với bản 1:
  * Lọc chất lượng: qa_value ≥ 0,75 (minQa = 75, theo hướng dẫn sản phẩm KNMI) là bộ lọc chính.
    Lọc tỷ lệ mây < 0,3 chỉ chạy khi đặt biến môi trường CLOUD_SENS=1 (phân tích độ nhạy).
  * Thêm cụm lớn ít mây (Vĩnh Tân, Duyên Hải) và các cụm Quảng Ninh, Formosa, Dung Quất, Nghi Sơn;
    3 nhà máy khảo sát giữ lại để biết chúng nằm ngoài hay trong khả năng phát hiện.
  * Giai đoạn 2019 đến 2025.
  * Quy tắc tháng: từ 5 ngày hợp lệ tính theo tháng; 2 đến 4 ngày gộp quý; dưới 2 ngày ghi thiếu dữ liệu.
Chưa làm ở bản này (cần thêm ERA5 qua CDS API và thư viện ddeq): lọc ngày gió yếu, ước tính phát thải
bằng phân kỳ thông lượng, gắn cờ cháy theo ngày bằng FIRMS.

Cần biến môi trường CDSE_CLIENT_ID, CDSE_CLIENT_SECRET (GitHub Secrets).
Kết quả ghi vào analysis/no2_3nm/: monthly.csv, summary.json, log.txt.
Chỉ dùng thư viện chuẩn Python.
"""
import csv, json, os, sys, time, traceback, urllib.error, urllib.parse, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "no2_3nm")
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

# Cụm: các nguồn cách nhau dưới khoảng 10 km được đối chiếu chung (mã Climate TRACE).
CLUSTERS = [
    ("VT", "Cụm Vĩnh Tân (nhiệt điện)", "kiểm chứng vệ tinh", ["25453850"]),
    ("DH", "Cụm Duyên Hải (nhiệt điện)", "kiểm chứng vệ tinh", ["25454003"]),
    ("MD", "Cụm Mông Dương, Cẩm Phả (nhiệt điện, xi măng)", "kiểm chứng vệ tinh", ["25453844", "25453145", "32439395"]),
    ("HL", "Cụm Quảng Ninh, Thăng Long (nhiệt điện, xi măng)", "kiểm chứng vệ tinh", ["25451625", "25454671", "32439372"]),
    ("FM", "Cụm Formosa, Vũng Áng (thép lò cao, nhiệt điện)", "kiểm chứng vệ tinh", ["1567170", "450569", "25453855"]),
    ("DQ", "Cụm Hòa Phát Dung Quất (thép lò cao, nhiệt điện)", "kiểm chứng vệ tinh", ["1567174", "25455896"]),
    ("NS", "Cụm Nghi Sơn (nhiệt điện, xi măng, thép)", "tham khảo", ["25454585", "42547280", "32439376", "1567175"]),
    ("CN", "Cao Ngạn (nhiệt điện)", "khảo sát", ["25452804"]),
    ("TN", "Gang thép Thái Nguyên (TISCO)", "khảo sát", ["32441113"]),
    ("HN", "Cụm xi măng Hà Nam (Bút Sơn, Vissai)", "khảo sát", ["32439388", "1898087"]),
]
YEARS = list(range(2019, 2026))
SMALL, LARGE, RES = 0.05, 0.3, 0.02
MIN_QA = 75
CLOUD_SENS = os.environ.get("CLOUD_SENS") == "1"

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
                  "data": [{"type": "sentinel-5p-l2", "dataFilter": {"timeliness": "OFFL"}, "processing": {"minQa": MIN_QA}}]},
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


def month_rule(days):
    return "thang" if days >= 5 else ("gop_quy" if days >= 2 else "thieu_du_lieu")


def main():
    os.makedirs(OUT, exist_ok=True)
    assets = {a["id"]: a for a in json.load(open(os.path.join(ROOT, "data", "assets.json"), encoding="utf-8"))["assets"]}
    tok, t0 = token(), time.time()
    evalscript, cloud = (EVAL_CLOUD, True) if CLOUD_SENS else (EVAL_PLAIN, False)
    rows, summary = [], {"generated": date.today().isoformat(), "method": {
        "small_box_deg_min": SMALL, "large_box_deg": LARGE, "res_deg": RES, "valid_day_min_coverage": 0.5,
        "qa_filter": f"qa_value >= {MIN_QA / 100}", "cloud_filter": None, "timeliness": "OFFL",
        "month_rule": ">=5 ngày: tháng; 2 đến 4: gộp quý; <2: thiếu dữ liệu",
        "chua_lam": "lọc gió yếu (ERA5), phân kỳ thông lượng (ddeq), gắn cờ cháy (FIRMS)"}, "clusters": []}
    for cid, name, role, ids in CLUSTERS:
        mem = [assets[i] for i in ids if i in assets]
        if not mem:
            log("Không thấy", cid, name); continue
        lat = sum(a["lat"] for a in mem) / len(mem)
        lon = sum(a["lon"] for a in mem) / len(mem)
        spread = max(max(abs(a["lat"] - lat), abs(a["lon"] - lon)) for a in mem)
        half = max(SMALL, round(spread + 0.03, 3))
        ct = sum(a.get("emissions_t_co2e") or 0 for a in mem)
        log(f"{name}: {lat:.4f}, {lon:.4f}, hộp ±{half}")
        per_month = {}
        for y in YEARS:
            if time.time() - t0 > 2400:
                tok, t0 = token(), time.time()
            try:
                s_ = daily(tok, lon, lat, half, y, evalscript)
            except ValueError as e:
                if cloud:
                    log("  Không dùng được CLOUD_FRACTION, chuyển sang chỉ lọc qa_value:", e)
                    evalscript, cloud = EVAL_PLAIN, False
                    s_ = daily(tok, lon, lat, half, y, evalscript)
                else:
                    raise
            l_ = daily(tok, lon, lat, LARGE, y, evalscript)
            for d, (v, cov) in s_.items():
                k = d[:7]
                pm = per_month.setdefault(k, {"days": 0, "vs": [], "vl": []})
                if cov >= 0.5:
                    pm["days"] += 1
                    pm["vs"].append(v)
                    if d in l_:
                        pm["vl"].append(l_[d][0])
            log(f"  {y}: {sum(1 for v in s_.values() if v[1] >= 0.5)} ngày hợp lệ")
            time.sleep(1)
        tot_days, enh, rules = 0, [], {"thang": 0, "gop_quy": 0, "thieu_du_lieu": 0}
        by_month_of_year = {m: [] for m in range(1, 13)}
        for y in YEARS:
            for m in range(1, 13):
                k = f"{y}-{m:02d}"
                pm = per_month.get(k, {"days": 0, "vs": [], "vl": []})
                ms = sum(pm["vs"]) / len(pm["vs"]) if pm["vs"] else None
                ml = sum(pm["vl"]) / len(pm["vl"]) if pm["vl"] else None
                e = (ms - ml) if (ms is not None and ml is not None) else None
                rule = month_rule(pm["days"])
                rules[rule] += 1
                by_month_of_year[m].append(pm["days"])
                rows.append([cid, name, role, ";".join(ids), k, pm["days"], rule,
                             f"{ms:.4e}" if ms is not None else "", f"{ml:.4e}" if ml is not None else "",
                             f"{e:.4e}" if e is not None else "", f"{e / ml * 100:.1f}" if (e is not None and ml) else ""])
                tot_days += pm["days"]
                if e is not None and rule == "thang":
                    enh.append(e / ml * 100 if ml else 0)
        enh_sorted = sorted(enh)
        med = enh_sorted[len(enh_sorted) // 2] if enh_sorted else None
        summary["clusters"].append({"id": cid, "name": name, "role": role, "members": ids, "lat": round(lat, 4), "lon": round(lon, 4),
                                    "box_half_deg": half, "climatetrace_t_co2e_total": ct,
                                    "valid_days_total": tot_days, "months_by_rule": rules,
                                    "mean_valid_days_by_calendar_month": {m: round(sum(v) / len(v), 1) for m, v in by_month_of_year.items()},
                                    "median_enhancement_pct_valid_months": round(med, 1) if med is not None else None,
                                    "months_enhancement_positive": sum(1 for x in enh if x > 0), "months_counted": len(enh)})
    summary["method"]["cloud_filter"] = "CLOUD_FRACTION < 0.3 (phân tích độ nhạy)" if cloud else "không, chỉ qa_value"
    with open(os.path.join(OUT, "monthly.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cum", "ten_cum", "vai_tro", "ma_climate_trace", "thang", "so_ngay_hop_le", "quy_tac",
                    "no2_hop_nho_mol_m2", "no2_hop_vung_mol_m2", "chenh_lech_mol_m2", "chenh_lech_pct"])
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
