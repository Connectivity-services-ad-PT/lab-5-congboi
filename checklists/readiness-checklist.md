# Readiness Checklist – Lab 05
 
Đây là danh sách kiểm tra (checklist) để đảm bảo stack Docker Compose của bạn đã sẵn sàng trước khi gửi bài. Hãy tick vào mỗi mục sau khi hoàn thành.
 
- [x] **Database ready:** container DB đã chạy và phản hồi `pg_isready`. Kiểm tra bằng `docker exec -it fit4110-db-lab05 pg_isready -U $POSTGRES_USER`.
- [x] **AI service ready:** container AI service trả về `200` cho endpoint `/health` và `/predict` hoạt động.
- [x] **API ready:** container API trả `200` cho `/health` và có thể tạo/lấy readings khi token hợp lệ.
- [x] **Environment variables:** `.env` đã được thiết lập đúng (APP_PORT, POSTGRES_USER, AUTH_TOKEN,…). Không sử dụng secret thật; lưu secret vào `.env` cục bộ, commit `.env.example`.
- [x] **Network & Ports:** mạng `team-internal` và `class-net` hoạt động; API gọi được AI bằng hostname `ai-service`.
- [x] **Image tags:** bạn đã build image thành công.
 
Ghi chú thêm những vấn đề gặp phải hoặc điều chỉnh tại đây:
 
```
- Đã sửa lỗi thiếu dependencies trong ai-service bằng cách tạo Dockerfile.ai.
- Đã sửa lỗi AttributeError trong exception handler của main.py.
- Toàn bộ 19 test case trong Postman đã PASS trên môi trường Docker Compose.
```