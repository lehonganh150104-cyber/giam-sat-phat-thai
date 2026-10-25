# Giám sát phát thải cơ sở công nghiệp bằng vệ tinh

Trang web tĩnh hiển thị phát thải khí nhà kính của 127 nhà máy điện, thép và xi măng tại Việt Nam theo ước tính vệ tinh của Climate TRACE, kèm công cụ đối chiếu với số liệu kiểm kê của doanh nghiệp. Không cần máy chủ, không cần cơ sở dữ liệu.

## Trong thư mục có gì

| Đường dẫn | Dùng để làm gì |
|---|---|
| `index.html` | Toàn bộ trang web: giao diện, biểu đồ, bản đồ, công cụ đối chiếu. Có sẵn một bản dữ liệu dự phòng bên trong. |
| `data/assets.json` | Danh sách cơ sở, tọa độ, công suất, sản lượng, phát thải năm gốc 2024. |
| `data/yearly.json` | Phát thải từng cơ sở các năm 2021 đến 2025. |
| `data/no2.json` | (Tùy chọn, tạo ra khi chạy script Copernicus) NO2 Sentinel-5P theo tháng quanh nhà máy. |
| `config/settings.json` | Cài đặt mặc định cho cả nhóm: ngưỡng, hệ số nhiên liệu, GWP, hệ số lưới điện, danh sách ngành cần tải. |
| `scripts/update_climatetrace.py` | Tải lại dữ liệu mới nhất từ Climate TRACE API. |
| `scripts/update_no2_cdse.py` | Lấy NO2 Sentinel-5P qua Copernicus Data Space bằng tài khoản của bạn. |
| `.github/workflows/update-data.yml` | Lịch tự cập nhật dữ liệu mỗi sáng thứ Hai khi đưa lên GitHub. |

## Chạy thử trên máy

Cần Python 3.9 trở lên. Mở Terminal trong thư mục này rồi chạy:

```
python3 -m http.server 8000
```

Mở trình duyệt vào `http://localhost:8000`. Nếu mở thẳng file `index.html` bằng cách bấm đúp, trang vẫn chạy nhưng dùng bản dữ liệu dự phòng bên trong, không đọc thư mục `data`.

## Đưa lên mạng thành web của riêng bạn

**Cách 1, GitHub Pages (miễn phí, có tự cập nhật dữ liệu):**
1. Tạo kho mới trên GitHub, ví dụ `giam-sat-phat-thai`, tải toàn bộ thư mục này lên (giữ nguyên thư mục `.github`).
2. Vào Settings, Pages, chọn Deploy from a branch, nhánh `main`, thư mục `/ (root)`, bấm Save.
3. Vào Settings, Actions, General, mục Workflow permissions chọn Read and write permissions.
4. Sau 1 đến 2 phút trang có địa chỉ dạng `https://<tên-tài-khoản>.github.io/giam-sat-phat-thai/`. Muốn dùng tên miền riêng, khai báo ở mục Custom domain của Pages.
5. Thử cập nhật ngay: tab Actions, chọn "Cập nhật dữ liệu vệ tinh", bấm Run workflow.

**Cách 2, Netlify hoặc Vercel:** kéo thả cả thư mục vào trang Deploy của Netlify (app.netlify.com/drop). Cách này không tự cập nhật; muốn có dữ liệu mới thì chạy script trên máy rồi kéo thả lại.

## Thiết lập và sửa

- **Trên giao diện:** tab Cài đặt cho sửa ngưỡng khớp, độ bất định theo mức tin cậy, hệ số nhiên liệu, hệ số clinker và thép, GWP, hệ số lưới điện, đơn vị, giao diện sáng tối. Thay đổi lưu trong trình duyệt của từng người.
- **Cho cả nhóm:** sửa `config/settings.json` rồi đưa lên lại. Trang chỉ dùng file này khi người xem chưa tự chỉnh trong trình duyệt (bấm Khôi phục mặc định để quay về file này).
- **Đổi phạm vi dữ liệu:** trong `config/settings.json`, khóa `data`: đổi `subsectors` (ví dụ thêm `"oil-and-gas-refining"`, `"coal-mining"`), `years`, `baseYear`. Ngành mới cần thêm tên và màu trong biến `SECTORS` ở đầu phần script của `index.html`.
- **Sửa giao diện:** phần `<style>` đầu file `index.html` là màu sắc và bố cục (các biến màu `--elec`, `--steel`, `--cement`, `--accent`). Phần `<script>` cuối file là logic; khối `<script type="application/json" id="seed">` rất dài là dữ liệu dự phòng, không cần sửa.
- **Nạp dữ liệu khác:** tab Cài đặt, mục Dữ liệu, chọn file CSV cùng định dạng với nút Xuất CSV ở tab Danh sách cơ sở.

## Cập nhật dữ liệu bằng tay

```
python3 scripts/update_climatetrace.py
```

Script chỉ dùng thư viện chuẩn của Python. Climate TRACE cập nhật dữ liệu định kỳ; năm gốc nên chuyển sang năm mới khi năm đó đủ số liệu cả năm.

## Thêm ảnh NO2 Sentinel-5P (tùy chọn)

1. Đăng ký tài khoản miễn phí tại `dataspace.copernicus.eu`.
2. Vào Dashboard, User settings, OAuth clients, tạo client mới, lưu lại Client ID và Client secret (secret chỉ hiện một lần).
3. Chạy trên máy:
   ```
   export CDSE_CLIENT_ID=...
   export CDSE_CLIENT_SECRET=...
   python3 scripts/update_no2_cdse.py
   ```
   Trên GitHub: Settings, Secrets and variables, Actions, thêm hai secret cùng tên; lịch hằng tuần sẽ tự chạy phần này.
4. Mở chi tiết một nhà máy để xem biểu đồ NO2 theo tháng.

Script này viết theo tài liệu Statistical API của Copernicus nhưng chưa được chạy thử với tài khoản thật; lần đầu nên đặt `"top": 1` trong khóa `no2` của `config/settings.json` để thử một nhà máy. Hạn mức miễn phí của Copernicus đủ cho vài chục nhà máy mỗi tuần.

## Giới hạn

- Số liệu là ước tính độc lập của Climate TRACE, không phải số liệu chính thức, chưa được cơ quan quản lý Việt Nam công nhận cho kiểm kê, thẩm định hay tính thuế carbon.
- Ngưỡng khớp 20% và độ bất định theo mức tin cậy là giả định, cần chuyên gia kiểm kê xác nhận.
- Nút Giải thích bằng AI chỉ chạy khi mở trang trong Claude; ở web tự triển khai nút này bị tắt.
- Dữ liệu Climate TRACE theo giấy phép CC BY 4.0: giữ dòng ghi nguồn ở chân trang khi dùng lại.
