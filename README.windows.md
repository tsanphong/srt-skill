# Chạy trên Windows

Đây là bản sao từ [geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation), giữ nguyên README.md, SKILL.md và giấy phép MIT. Đọc hai tài liệu gốc trước khi tạo dự án.

Đã kiểm tra với Python 3.12.14, OpenCV, NumPy, PyAV và Pillow. Bản này sửa lỗi gọi hàm khi vùng không có nét, giữ thời lượng vùng bị che hoàn toàn, và sửa mốc thời gian khi ghép từ cảnh thứ hai bằng PyAV.

## Chuẩn bị môi trường riêng

Trong PowerShell, tại thư mục kho:

```powershell
python -X utf8 scripts/prepare_env.py
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_env.py --check
.\.venv\Scripts\python.exe -m pip check
```

Nếu lệnh `python` không có trong PATH, thay bằng đường dẫn đầy đủ đến Python 3.12. Dùng `-X utf8` khi chạy các script để hiển thị văn bản Unicode trên Windows.

## Render ví dụ

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/render_stream_whiteboard.py examples/scene-01-monkey-mountain-banana.png examples/scene-01-monkey-mountain-banana.annotation.json outputs/demo.mp4 assets/drawing-hand.png --fps 30 --cap-long-edge 1080
```

Ví dụ xuất video H.264 không âm thanh, 1080×600, khoảng 8,6 giây. Tham số cạnh dài 1080 không có nghĩa là Full HD. Trình chỉnh vùng là `assets/preview.html`, mở bằng Edge/Chrome rồi chọn thư mục chứa cặp PNG và annotation cùng tên. Trình chỉnh vùng không trực tiếp xuất video có nét vẽ thật; cần chạy renderer.

## Ghép cảnh và kiểm tra

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/merge_scenes.py --inputs outputs/demo.mp4 outputs/demo.mp4 --output outputs/merge-check.mp4
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

PyAV mã hóa H.264 và ghép cảnh được khi không có FFmpeg hệ thống. Nên dùng cùng độ phân giải và FPS cho mọi cảnh; nhánh ghép PyAV dùng FPS của cảnh đầu và chỉ xử lý luồng hình ảnh.

## Dùng làm skill Codex

Cài cả thư mục kho dưới tên `srt-whiteboard-animation`. Khi gửi file SRT, gọi `$srt-whiteboard-animation` và yêu cầu giao tiếp bằng tiếng Việt. Skill hỗ trợ lập phân cảnh, tổ chức ảnh và thời gian vẽ; không kèm mô hình AI tạo ảnh hay giọng đọc chạy ngoại tuyến. Ảnh mới có thể được tạo bằng công cụ tạo ảnh của Codex hoặc do bạn cung cấp.
