# SRT Whiteboard Studio — hướng dẫn ứng dụng local

Ứng dụng biến một nhóm ảnh thành video bàn tay vẽ, sau đó ghép voice, nhạc nền, phụ đề và tên kênh thành MP4. Máy chủ chỉ lắng nghe tại `127.0.0.1`; hình ảnh, âm thanh, kịch bản và video nằm trong thư mục `workspace/` trên máy, không được gửi đến dịch vụ bên ngoài.

## Khởi động nhanh trên Windows

1. Giải nén hoặc clone repository vào đường dẫn không bị giới hạn quyền ghi.
2. Nhấp đúp `START_WHITEBOARD_APP.bat`.
3. Lần đầu, cửa sổ sẽ tạo `.venv` và cài thư viện. Sau đó trình duyệt tự mở tại `http://127.0.0.1:7860`.
4. Giữ cửa sổ lệnh đang chạy trong lúc sử dụng. Đóng cửa sổ để dừng ứng dụng.

Nếu trình duyệt không tự mở, nhập `http://127.0.0.1:7860` vào Edge hoặc Chrome.

## Quy trình dựng video

1. Chọn **Dự án mới**, nhập tên.
2. Chọn nhiều ảnh hoặc chọn cả thư mục. Ứng dụng sắp xếp tự nhiên theo số trong tên, ví dụ `1.png`, `2.png`, `10.png`.
3. Dán kịch bản hoặc tải TXT; chọn voice MP3/WAV và nhạc nền nếu có.
4. Bấm **Tạo và tự căn chỉnh**. Khi có voice, tổng thời gian cảnh được căn theo đúng độ dài voice; kịch bản được chia theo trọng lượng câu. Không có voice thì mỗi ảnh mặc định khoảng sáu giây.
5. Chọn tỷ lệ 9:16 hoặc 16:9, độ phân giải, FPS, màu nét, kiểu đường bút và cách tô màu. Điều chỉnh âm lượng voice/nhạc, tên kênh và phụ đề.
6. Với từng cảnh, sửa phụ đề, thời lượng và tốc độ vẽ. Tốc độ lớn hơn làm phần vẽ hoàn tất sớm hơn và giữ ảnh hoàn chỉnh lâu hơn trong cùng thời lượng cảnh.
7. Bấm **Dựng cảnh** để xem riêng. Nếu cảnh lỗi, sửa thông số rồi bấm **Dựng lại cảnh**; các cảnh khác được giữ nguyên.
8. Bấm **Dựng toàn bộ** để chạy lần lượt mọi cảnh và tự ghép MP4. Thanh tiến trình hiển thị trạng thái hiện tại.
9. Nếu đã dựng riêng tất cả cảnh, dùng **Ghép các cảnh đã dựng**. Nút **Tải MP4** xuất hiện khi hoàn tất.

## Cấu trúc dữ liệu

```text
workspace/projects/<ma-du-an>/
├── project.json                 # cấu hình, thứ tự, thời lượng và trạng thái
├── source/
│   ├── images/                  # ảnh đã đổi tên scene-001, scene-002...
│   ├── audio/                   # voice và nhạc nền
│   ├── subtitles.srt            # phụ đề rời được tạo tự động
│   └── subtitles.ass            # phụ đề/tên kênh dùng khi ghi hình
├── scenes/
│   ├── scene-001.annotation.json
│   └── scene-001.mp4            # video từng cảnh
├── outputs/
│   ├── visual.mp4               # hình đã chuẩn hóa tỷ lệ
│   └── <ma-du-an>-final.mp4      # thành phẩm
└── logs/                        # nhật ký giúp tìm cảnh lỗi
```

`workspace/` đã được Git bỏ qua để không vô tình commit tài nguyên riêng hoặc video dung lượng lớn.

## Căn chỉnh và phụ đề

Ứng dụng đọc chính xác thời lượng container của voice bằng PyAV. Kịch bản được tách theo xuống dòng và dấu câu, rồi phân bổ cho các cảnh dựa trên số ký tự. Đây là căn chỉnh tự động ở cấp cảnh, phù hợp khi mỗi ảnh tương ứng một đoạn lời. Bạn có thể sửa văn bản và thời lượng từng cảnh trước khi dựng.

Phụ đề được tạo ở hai dạng: `subtitles.srt` để dùng riêng và ASS để ghi trực tiếp vào MP4. Font phồn thể trên Windows dùng Microsoft JhengHei. Tên kênh nằm ở góc trên bên phải.

## Chạy bằng dòng lệnh

```powershell
python -X utf8 scripts/prepare_env.py
.\.venv\Scripts\python.exe -X utf8 -m app.server
```

Đổi cổng nếu 7860 đang được dùng:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.server --port 7861
```

## Khắc phục lỗi

- **Không mở được ứng dụng:** chạy lại `scripts/prepare_env.py`, sau đó kiểm tra `.venv` tồn tại.
- **Dựng cảnh thất bại:** mở `workspace/projects/<ma-du-an>/logs/scene-XXX.log`.
- **Ghép thất bại:** xem `logs/merge-visual.log` và `logs/final.log`.
- **Ảnh sai thứ tự:** đặt số ở đầu tên ảnh, chẳng hạn `01-mo-dau.png`, `02-noi-dung.png`.
- **Video có viền:** ứng dụng giữ nguyên toàn bộ ảnh và thêm nền giấy để vừa tỷ lệ đầu ra. Chuẩn bị ảnh cùng tỷ lệ 9:16 hoặc 16:9 để không có viền.

## Giới hạn hiện tại

- Căn voice thực hiện ở cấp cảnh, chưa nhận dạng từng từ.
- Ảnh được dùng làm nguồn vẽ; ứng dụng không tự tạo hình minh họa bằng AI.
- Mỗi tiến trình dựng xử lý một dự án tại một thời điểm để tránh dùng hết CPU và RAM.
