Dưới đây là phần **Hướng dẫn triển khai** thay thế cho **Cách chạy dự án**, bao gồm hướng dẫn triển khai trên GitHub Actions và Render.com:

---

# Crawl Non-Margin List

Dự án này được thiết kế để thu thập và xử lý dữ liệu liên quan đến danh sách cổ phiếu không có margin. Dự án sử dụng Python và các thư viện liên quan để thực hiện việc thu thập dữ liệu từ các nguồn như sàn giao dịch chứng khoán.

## Mục tiêu
- Thu thập dữ liệu về cổ phiếu không có margin từ các sàn giao dịch chính.
- Xử lý và lưu trữ dữ liệu một cách hiệu quả.
- Cung cấp API để truy xuất dữ liệu đã thu thập.

## Các thành phần chính
- **Cấu hình**: Thiết lập ban đầu cho dự án, bao gồm thông tin kết nối đến cơ sở dữ liệu hoặc API.
- **Models**: Định nghĩa cấu trúc của dữ liệu được thu thập.
- **HSX & HNX Crawler**: Các module chuyên biệt để thu thập dữ liệu từ Sàn Giao dịch Chứng khoán TP.HCM (HOSE) và Sàn Giao dịch Chứng khoán Hà Nội (HNX).
- **API Endpoints**:
  - `/health`: Kiểm tra tình trạng hoạt động của ứng dụng.
  - `/stocks`: Trả về danh sách cổ phiếu đã được thu thập, với định dạng theo mô hình `APIResponse`.

## Hướng dẫn triển khai

### Triển khai trên GitHub Actions
[Đang cập nhật]

### Triển khai trên Render.com

1. Tạo một tài khoản trên Render.com nếu chưa có.
2. Kết nối tài khoản GitHub của bạn với Render.com[6].
3. Tạo một web service mới trong dashboard của Render.com bằng cách chọn repository chứa dự án này. Lưu ý:
   - Khai báo biến môi trường PORT:10000
   - Building command: pip install -r requirements.txt && playwright install
   - Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
4. Sau khi tạo xong service, có thể lấy danh sách Non-margin thông qua API có dạng https://***.onrender.com/stock
