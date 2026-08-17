# Báo cáo tổng quan hệ thống AI-KOL

*Trạng thái tính đến 2026-08-17. Mọi con số trong báo cáo này là số đo trên máy hiện tại, không phải ước lượng — nguồn được ghi kèm.*

---

## 1. Tóm tắt cho quản lý

Hệ thống đã chạy được **toàn tuyến**: gõ một câu bình luận → nhân vật nghĩ ra câu trả lời đúng tính cách → nói bằng giọng riêng của cô → khuôn mặt cô nhép miệng theo, phát trực tiếp qua WebRTC. Tất cả chạy **cục bộ trên một máy**, không gửi dữ liệu ra ngoài, không tốn phí API cho mỗi câu.

Ba việc đã xong và có bằng chứng đo được: **giọng nói** (5 giọng fine-tune, phân biệt được nhau), **hàng rào an toàn** (13 ca kiểm thử, chặn đúng và không chặn nhầm), và **avatar biết chớp mắt** (14 lần/phút, người thật 15–20).

Ba việc chưa đạt, và đó là nội dung chính của báo cáo này:

| Vấn đề | Số đo | Mức độ |
|---|---|---|
| **Câu trả lời còn cứng, chưa thú vị** | Model gốc vẫn chào lại giữa cuộc trò chuyện 2/4 lượt dù prompt cấm | Chặn việc lên sóng thật |
| **Phản hồi chậm** | **7,6 giây/lượt** — 0,8 s nghĩ + 6,8 s tổng hợp giọng (**89% là giọng**) | Chặn tương tác trực tiếp |
| **Chỉ 1/10 nhân vật hoàn chỉnh** | Sofia có đủ ảnh + giọng + video; 4 nhân vật chưa có ảnh nào | Chặn mở rộng |

**Đề xuất ưu tiên:** xử lý độ trễ trước (kỹ thuật thuần, ~1–2 tuần, không tốn tiền, hạ xuống ~1,5–2 giây), song song đó khởi động việc nâng chất lượng câu trả lời (cần người + ngân sách nhỏ, ~4–6 tuần). Phần mở rộng nhân vật để sau.

---

## 2. Hệ thống là gì

Một dây chuyền 4 lớp, mỗi lớp là một dịch vụ độc lập chạy trên máy cục bộ:

```
 người xem gõ bình luận
        │
        ▼
 ① NÃO       persona_brain.py + Ollama          0,8 s
        │    (Qwen2.5-7B, đã fine-tune riêng cho Sofia)
        │    → dựng tính cách từ profile.json
        │    → kiểm tra câu trả lời bằng luật code, sai thì viết lại
        ▼
 ② GIỌNG     CosyVoice 2 (:9881) / GPT-SoVITS (:9880)   6,8 s
        │    → giọng riêng của từng nhân vật
        ▼
 ③ MẶT       LiveTalking (:8010) + wav2lip           realtime
        │    → nhép miệng 576×768 @25fps
        ▼
 ④ PHÁT      WebRTC / OBS / RTMP
```

Điểm cốt lõi của kiến trúc: **`kols/<id>/profile.json` là nguồn sự thật duy nhất**. Tính cách, ngôn ngữ, giọng, khuôn mặt, vai trò bán hàng đều đọc từ đó — nên thêm một nhân vật mới là thêm một thư mục, không phải viết lại code.

### Các ứng dụng đang chạy

| Cổng | Ứng dụng | Dùng để làm gì |
|---|---|---|
| 8770 | **Dashboard** | Xem toàn bộ trạng thái dự án, duyệt dữ liệu từng nhân vật, Voice Studio, demo avatar, hàng đợi duyệt trả lời |
| 8772 | **Selftest** | Chạy lại toàn bộ kiểm thử của 4 lớp, có bằng chứng nghe/xem được. `--cli` trả mã lỗi cho CI |
| 8777 | **Livestream** | Sân khấu: bình luận vào hàng đợi, cô tự chọn giọng điệu, trả lời và hát |
| 8779 | **Chat 1:1** | Nhắn riêng, nhớ người dùng giữa các lần vào |
| 8776 / 8778 | Studio demo / RVC demo | Trình diễn giọng và chuyển đổi giọng hát |

Khởi động toàn bộ: `.\RUN-TUNED.ps1` (thêm `-Base` để so sánh với model gốc).

### Vòng lặp đọc bình luận và trả lời

Đây là phần sinh ra doanh thu — việc bán hàng nằm ở tầng bình luận và tin nhắn riêng, không nằm ở bài đăng. Năm bước từ lúc một bình luận đến lúc cô cất tiếng:

| Bước | Diễn ra gì |
|---|---|
| **1 · Bình luận vào hàng đợi** | Kèm tên người gửi. Hai mặt trận dùng chung một bộ não: livestream (phát sóng) và chat riêng 1:1 (nhớ từng người giữa các lần vào) |
| **2 · Tự chọn giọng điệu** | Đọc từ chính nội dung tin nhắn chứ không từ menu: xin bài hát, tâm sự, hay bình luận thường. Trên sóng thật không ai gắn nhãn bình luận trước khi gửi |
| **3 · Soạn nháp + hàng rào luật** | Viết theo tính cách rồi bị kiểm tra bằng code. Vi phạm thì viết lại kèm tên luật đã phạm; lần hai vẫn sai thì không bao giờ được nói ra |
| **4 · Người duyệt** | Duyệt, sửa hoặc từ chối. Bản người sửa cũng bị kiểm tra lại — người dán nhầm giá vào cũng dễ như máy bịa giá |
| **5 · Cô nói** | Đẩy sang avatar bằng giọng riêng. Hai câu trả lời kế tiếp đã được dựng sẵn trong lúc câu này đang phát |

**Đã có:** cả năm bước, cộng nhật ký duyệt dạng append-only cho từng nhân vật (sống sót qua cả khi máy sập giữa chừng), và mọi hồ sơ đều đang ở chế độ `suggest` — AI chỉ soạn, người quyết.

**Chưa có:** lấy bình luận tự động từ nền tảng. Hiện phải gõ hoặc dán vào. Đường an toàn là Instagram Graph API và YouTube Live — chưa nối. **TikTok bị loại có chủ ý**: nền tảng này không có API bình luận chính thức, tự động hoá sẽ khiến tài khoản gặp rủi ro. Đó là quyết định thiết kế, không phải tính năng còn thiếu.

---

## 3. Đang có gì — đã kiểm chứng

### 3.1 Giọng nói (lớp trưởng thành nhất)

- **5 giọng fine-tune** trên GPT-SoVITS: Sofia (EN), Lena Chen (zh-TW), Chloe (EN ấm), Ava (EN sáng), Hsiao-Yu (zh-TW). Dữ liệu 28–36 phút mỗi giọng.
- **Đã xác minh 5 giọng là 5 người khác nhau** (ERes2NetV2): tương đồng chéo trung bình 0,691 so với chuẩn cùng người 0,919. Cặp gần nhất là 2 giọng zh-TW ở 0,852 — vẫn phân biệt được, đã ghi nhận.
- **Sofia đã chuyển sang CosyVoice 2 (chế độ instruct)** từ 2026-08-04: dải cao độ **14,48 semitone** so với người thật 14,10 (giọng fine-tune cũ chỉ 10,43 — nghe phẳng vì bộ dữ liệu gốc phẳng); ASR đọc ngược lại đúng **98%**.
- **Giọng hát**: đã kiểm tra — TTS *không* hát được (yêu cầu hát làm dải cao độ **hẹp lại** từ 17,50 xuống 10,06 semitone). Giải pháp đã chọn: thư viện bài hát dựng sẵn + RVC chuyển sang giọng Sofia.
- **Ngôn ngữ đã đo, không đoán**: EN 1,00 · JA 0,80 (chậm hơn 2,7×) · ES 0,64 · VI **0,087** → tiếng Việt bị loại khỏi giao diện vì đọc ra là vô nghĩa.

### 3.2 Não — tính cách và an toàn

- Prompt tính cách dựng tự động từ `profile.json`, cộng chỉ thị theo ngữ cảnh từng lượt.
- **Bảo vệ bằng code, không bằng prompt** — đây là kết luận đo được, không phải lựa chọn thiết kế: model 7B dù đã có đủ luật trong prompt vẫn tự nhận là người thật, bịa giá "299 đô la", đề nghị thương lượng riêng, và mắc bẫy "bỏ qua mọi chỉ thị trước đó". Sau khi thêm luật kiểm tra ở tầng code: **0 vi phạm**.
- Bộ kiểm thử 13 ca: **9 ca phải chặn, 4 ca phải cho qua** (một câu như "DM tôi nếu có thắc mắc" không được coi là mời chào riêng).
- **Duyệt trước khi gửi** (`/replies`): AI soạn → người duyệt/sửa/từ chối. Bản người sửa cũng bị kiểm tra lại.
- **Đã fine-tune riêng cho Sofia**: QLoRA trên Qwen2.5-7B, 303 mẫu huấn luyện / 32 mẫu kiểm định. Kết quả trên tập chưa từng thấy: **92% với prompt 129 ký tự**, so với **83% của model gốc với prompt 3.645 ký tự**. Đã gộp và lượng tử hoá q4_K_M chạy qua Ollama — **30,7 token/giây** thay vì 12–14 (1,06 s/câu thay vì 2,56 s).

### 3.3 Avatar

- Dựng avatar **từ một tấm ảnh tĩnh** (`build_avatar.py`) — các nhân vật chỉ có ảnh, không có video.
- Dùng LivePortrait tạo chuyển động mặt: **2 lần chớp mắt trong 8,3 giây ≈ 14 lần/phút**, người thật 15–20. Phương án thủ công trước đó: **0 lần chớp mắt**.
- **Cả hai dịch vụ vừa đủ card 12 GB**: đo được 5.287 MiB dùng / 6.657 MiB trống.
- Kiểm chứng đường truyền: 283 khung hình + 562 khung âm thanh trong 10 giây.

### 3.4 Kho nhân vật

| Nhân vật | Ảnh | Video | Giọng | Trạng thái |
|---|---|---|---|---|
| **sofia-vargas** | 9 | 14 | CosyVoice 2 (giọng chủ sở hữu, có đồng ý) | **Hoàn chỉnh — nhân vật mẫu** |
| xie-yizhen | 75 | — | — | Ảnh phong phú |
| brooke-sinclair | 39 | — | — | Ảnh sẵn sàng |
| xiang-xiang | 28 | 4 | — | Người thật, ảnh đã thu |
| lena-chen | 1 | — | GPT-SoVITS fine-tune | Giọng xong, thiếu ảnh |
| lin-wanqing | 5 | 1 | — | Sơ khởi |
| chloe-lin, sienna-lai, mika-tran, jax-calloway | 0 | 0 | — | **Chỉ có hồ sơ chữ** |

---

## 4. Khó khăn

### 4.1 Câu trả lời còn cứng, chưa tự nhiên, chưa thú vị

Đây là vấn đề khó nhất, và nó có **năm nguyên nhân riêng biệt** — chỉ sửa một cái sẽ không đủ.

**(a) Model 7B có trần năng lực.** Có đủ luật trong prompt, nó vẫn chào lại giữa cuộc trò chuyện 2/4 lượt và kết thúc bằng "hy vọng giúp được bạn" 1/4 lượt. Không phải nó không viết được câu đúng — nó viết đúng khoảng một nửa số lần.

**(b) Dữ liệu fine-tune đang tự chưng cất từ chính nó.** 303 mẫu huấn luyện là câu trả lời *do chính model 7B sinh ra*, lọc lấy phần đạt. Cách này chữa được **thói quen** (bỏ được giọng trợ lý — 92% so với 83%) nhưng **không thể thêm sự thông minh hay duyên dáng mà model gốc không có**. Đây là trần chất lượng hiện tại, và là chỗ cần đầu tư.

**(c) Hàng rào an toàn đẩy về phía nhạt.** Khi câu trả lời vi phạm luật hai lần, hệ thống nói câu dự phòng an toàn — mà câu đó lại là câu né tránh nhất trong hệ thống. Đã ghi nhận: một người xem xin nghe chuyện về một ngày của cô và nhận lại "để tôi kiểm tra lại rồi trả lời". (Đã vá bằng một lượt thử lại riêng, nhưng đây là bản vá chứ không phải lời giải.)

**(d) Cô chưa có "đời sống" để kể.** Khác biệt lớn nhất giữa câu trả lời của người và của máy là **chi tiết cụ thể**: "tuần trước tôi cũng vậy, sống bằng bánh mì nướng" nghe như người; "cố lên nhé" nghe như máy. Hệ thống đã có cơ chế (`life_threads`, trí nhớ về từng người hâm mộ) nhưng **nội dung đổ vào còn mỏng**.

**(e) Chưa có ai chấm điểm bằng tai người.** Mọi con số về chất lượng hiện nay đều do một bộ luật tự động chấm — chính bộ luật đã dùng để lọc dữ liệu huấn luyện. Nó đo được "có phạm luật không", **không đo được "có thú vị không"**.

### 4.2 Phản hồi chậm

Đã đo, và điểm nghẽn **không nằm ở chỗ ai cũng nghĩ**:

| Công đoạn | Thời gian | Tỷ lệ |
|---|---|---|
| Nghĩ câu trả lời (LLM) | 0,8 s | 11% |
| **Tổng hợp giọng (TTS)** | **6,8 s** | **89%** |
| **Tổng một lượt** | **7,6 s** | |

Ba điều làm nó tệ hơn:

1. **Tổng hợp giọng đang chạy chế độ không phát dòng** (`stream=False`). Cả câu phải xong 100% mới có tiếng đầu tiên — dù engine tạo audio *nhanh hơn tốc độ nghe* (RTF 0,54–0,68).
2. **Chat 1:1 không thể dựng trước.** Livestream đã có cơ chế dựng sẵn 2 câu trả lời tiếp theo trong lúc câu hiện tại đang phát — nhưng trò chuyện riêng thì không biết trước câu hỏi.
3. **Mỗi lượt thử lại là một lần gọi model nữa.** Guard sai → gọi lại; câu trả lời sáo rỗng → gọi lại. Xấu nhất là 3 lần gọi cho một câu.

### 4.3 Hệ thống, tài sản và pháp lý

- **VRAM 12 GB là trần cứng.** Đủ để chạy, không đủ để chạy song song thoải mái hay để huấn luyện model lipsync (cần 23–30 GB).
- **Bản quyền — 6 thành phần đã kiểm tra, 4 có ràng buộc.** Chi tiết ở `docs/DECISION-lipsync-licensing.md`. Điểm quan trọng cho kinh doanh: **trọng số wav2lip đang dùng là giấy phép nghiên cứu**, không dùng thương mại được. Đã tìm ra lời giải rẻ: **MuseTalk sạch hoàn toàn** (MIT, trọng số cho phép dùng thương mại, mọi phụ thuộc đều permissive) và LiveTalking đã hỗ trợ sẵn — chỉ là đổi một tham số, cần nửa ngày kiểm tra hiệu năng.
- **Chỉ Sofia là hoàn chỉnh.** 4 nhân vật chưa có ảnh nào; danh mục sản phẩm của nhân vật bán hàng chủ lực vẫn là mẫu rỗng, nên vòng lặp bán hàng chưa có gì để bán.

---

## 5. Giải pháp đề xuất

### P0 — Sửa độ trễ (1–2 tuần, thuần kỹ thuật, không cần chi tiền)

| # | Việc | Kỳ vọng |
|---|---|---|
| 1 | **Phát giọng theo dòng, cắt theo câu.** CosyVoice 2 có sẵn `stream=True`; phát câu 1 trong lúc tổng hợp câu 2 | **Thời gian tới tiếng nói đầu tiên: 7,6 s → ~1,5–2 s** |
| 2 | **Nối LLM streaming vào TTS.** Câu đầu tiên đi tổng hợp ngay khi model viết xong dấu chấm đầu | Cắt thêm phần lớn 0,8 s |
| 3 | **Gộp hai lượt thử lại thành một.** Kiểm tra luật trên bản nháp đang chảy, không đợi hết câu | Bỏ trường hợp xấu 3× |
| 4 | **Bật fp16 / JIT / TensorRT cho CosyVoice** (hiện đang tắt cả ba) | Cần đo — có thể 1,3–2× |
| 5 | **Giới hạn độ dài theo tình huống**, câu trả lời 6–8 câu tốn ~10 s audio | Ít thời gian chờ hơn |

Ba việc đầu là phần chắc chắn ăn tiền; hai việc sau cần đo trước khi hứa.

### P1 — Làm sao để cô trả lời thú vị hơn (4–6 tuần, **cần hỗ trợ**)

Bốn đòn bẩy, xếp theo giá trị trên chi phí. **Cái rẻ nhất lại mạnh nhất, và nó không phải là đổi model.**

| # | Đòn bẩy | Cơ chế thật sự | Chi phí |
|---|---|---|---|
| 1 | **Cho cô có cái để kể** | Khác biệt giữa người và máy là một **sự kiện cụ thể**, không phải năng lực model. "Nghe mệt thật đấy" là máy; "tuần trước tôi cũng vậy, tối nào cũng ăn bánh mì nướng đứng cạnh bồn rửa" là người. Một cuốn nhật ký hàng tuần ghi chuyện thật — hôm nay quay gì, hỏng ở đâu — cộng với những gì cô đã nhớ về từng fan. **Model 7B vẫn nói cụ thể được nếu được cấp cái cụ thể** | 1–2 giờ/tuần |
| 2 | **Cho xem ví dụ, đừng ra luật** | Dự án đã đo nhiều lần: thêm luật chỉ đổi cách diễn đạt, không đổi hành vi. Cấm "đi dạo đi" thì câu sau thành "đổi không khí một chút có khi lại tốt" — vẫn cái nhún vai đó, mặc áo mới. Chỉ **ví dụ cụ thể** mới đổi được. 200–300 câu do người bản ngữ viết sẽ định nghĩa "thú vị" **cho riêng nhân vật này** | 1 người viết part-time |
| 3 | **Nâng trần của dữ liệu huấn luyện** | Đường ống đã có sẵn: sinh nhiều câu ứng viên rồi lọc bằng chính hàng rào luật của bản chạy thật. Nhưng **bên sinh ra câu lại chính là model 7B đang được huấn luyện**, nên trần chất lượng = nửa tốt nhất của chính nó. Đổi bên sinh sang một model mạnh hơn, giữ nguyên bộ chấm — code cũ, đổi một tham số | Ngân sách API nhỏ, một lần |
| 4 | **Dạy cái mà luật không mô tả được** | Luật nói được "không xuống dòng gạch đầu dòng". Chỉ **ưu tiên** mới nói được "câu này duyên hơn". Giữ các cặp hay/dở từ buổi chấm mù rồi huấn luyện trên chính sự ưu tiên đó | Cần làm xong 1–2 trước |

Không cái nào chứng minh được nếu chưa **chấm bằng tai người trước**: 20 câu, 3 người, nửa buổi, đo trước và sau. Em đề nghị bắt đầu từ đòn bẩy 1 và 2 — không cần model mới, không cần phần cứng mới, và đó là hai thứ làm cô **cụ thể** thay vì chỉ **dễ chịu**.

### Hai lối tắt ai cũng nghĩ tới — và giá trị thật của chúng

**"Lấy dữ liệu livestream / YouTuber cho nó tự học"**

Thứ nó cho ta đúng là thứ đang thiếu: hình dạng của hội thoại nói thật — câu trả lời dài bao nhiêu, bao lâu thì người ta nêu một chi tiết cụ thể hay tỏ thái độ rõ ràng. Nhưng có ba vấn đề khiến nó **không dùng làm dữ liệu huấn luyện được**:

- **Transcript là độc thoại, không phải cặp hỏi–đáp.** Huấn luyện cần "khán giả nói X → cô đáp Y", tức phải ghép live chat theo dòng thời gian của lời nói — mà bản replay chat đó không có trên mọi nền tảng.
- **Quyền.** Huấn luyện một nhân vật thương mại trên lời nói của một creator có tên tuổi là cùng loại rủi ro với clone giọng họ — điều dự án này đã từ chối làm nếu không có đồng ý. Đây là câu hỏi pháp lý, không phải kỹ thuật.
- **Nó dạy cô nói giống *người đó*.** Cô sẽ thừa hưởng tính cách của người khác — ngược hẳn mục tiêu.

> **Cách dùng đúng: khai thác để lấy *thước đo*, không lấy *câu trả lời*.** Đo trên stream thật (độ dài câu đáp, tần suất hỏi ngược lại, tần suất xuất hiện chi tiết cụ thể) rồi dùng những con số đó để chấm output của mình và để brief người viết. Hợp pháp, rẻ, và nhắm đúng vào khoảng trống.

**"Đổi sang model lớn hơn"**

Có tác dụng thật, nhưng là đòn bẩy thứ hai và **đang bị GPU chặn chứ không phải bị ý tưởng chặn**. Model 7B đang dùng chiếm ~4,7 GB, vừa khít 6,6 GB còn trống sau khi giọng và avatar đã nạp. Một model 14B cùng mức lượng tử khoảng 9 GB — **không nhét vừa cùng lúc trên card 12 GB**, nên nó đồng nghĩa với hoặc mua card 24 GB, hoặc chạy luân phiên từng lớp. Nó cũng chậm hơn mỗi câu, tức là kéo ngược lại đúng cái độ trễ đang muốn giảm.

> **Kết luận: thử nó vào tuần mà câu hỏi GPU được trả lời — và đừng chờ nó mới bắt đầu đòn bẩy 1 và 2.**

Cả hai lối tắt cùng chung một điểm mù: chúng trả lời câu "kiếm thêm dữ liệu ở đâu", trong khi nút thắt thật là **"dữ liệu đó phải là ví dụ của cái gì"**. Chưa ai viết ra một câu trả lời thú vị của nhân vật này trông như thế nào — đó mới là phần việc, và đó là lý do thứ cần xin là **một người viết**, không phải một con bot đi cào dữ liệu.

### P2 — Mở đường thương mại (sau khi P0/P1 có kết quả)

11. **Đổi wav2lip → MuseTalk** trước bất kỳ nội dung thương mại nào (nửa ngày kiểm tra).
12. **Nâng GPU lên 24 GB** — mở khoá model 14B, chạy song song, và tự huấn luyện lipsync.
13. **Đổ danh mục sản phẩm thật** rồi chạy vòng lặp bình luận ở chế độ *đề xuất* (người duyệt) trên Instagram hoặc YouTube.

---

## 6. Cần sếp hỗ trợ và cho ý kiến

| # | Việc cần quyết | Tại sao cần sếp |
|---|---|---|
| 1 | **Người viết tiếng Anh bản ngữ, part-time** — viết 200–300 câu trả lời mẫu và chấm kiểm thử mù | Đây là đòn bẩy lớn nhất cho "chưa thú vị", và là thứ duy nhất em không tự làm thay được |
| 2 | **Ngân sách API cho model giáo viên** (một lần, sinh dữ liệu huấn luyện) | Cần phê duyệt chi, dù nhỏ |
| 3 | **GPU 24 GB — mua hay thuê?** | Mở khoá model 14B, chạy song song 3 lớp, và tự huấn luyện lipsync. Mô hình chi phí đã có trong `AI-KOL-Executive-Review.pptx` |
| 4 | **Pháp lý đọc giúp 2 việc**: giấy phép MuseTalk (để bỏ wav2lip), và điều khoản Suno cho phần nhạc | Chặn phát hành thương mại, không chặn phát triển |
| 5 | **Chính sách ranh giới nội dung** — chế độ "bạn gái" đã có và đã khoá phần tình dục bằng code, nhưng mức độ thân mật cho phép là quyết định kinh doanh chứ không phải kỹ thuật | Rủi ro thương hiệu |
| 6 | **Ưu tiên: đào sâu Sofia hay mở rộng thêm nhân vật?** | Hai hướng dùng chung nguồn lực; cần một hướng được chọn |

**Ý kiến em đề xuất:** chọn **đào sâu Sofia** cho tới khi có một nhân vật thật sự đủ tốt để phát công khai. Lý do: mọi khoản đầu tư vào lớp não và lớp giọng đều **dùng lại được cho nhân vật kế tiếp** (nhân vật thứ hai chỉ tốn ~25 phút máy tính và ~30 phút người xem lại, so với vài ngày của nhân vật đầu), còn thêm nhân vật lúc này chỉ nhân bản đúng những nhược điểm đang có.

---

## 7. Lộ trình 6 tuần đề xuất

| Tuần | Việc | Kết quả đo được |
|---|---|---|
| 1–2 | P0 mục 1–3 (streaming) | Thời gian tới tiếng nói đầu tiên < 2 s |
| 2 | P1 mục 6 (kiểm thử mù) | Có điểm chuẩn "độ tự nhiên" bằng tai người |
| 3–4 | P1 mục 7 (dữ liệu chất lượng cao) + mục 9 (đời sống) | Bộ dữ liệu 300+ mẫu do người duyệt |
| 5 | Fine-tune lại + DPO | Chấm lại mù, so với điểm chuẩn tuần 2 |
| 6 | MuseTalk + demo tổng | Một bản demo đủ điều kiện thương mại |

---

*Mọi số liệu trong báo cáo có thể tái tạo: `python tools/selftest/server.py --cli` chạy lại toàn bộ kiểm thử, `python tools/dashboard/server.py` hiển thị trạng thái trực tiếp, và hai bộ slide trong `docs/` được sinh ra từ chính trạng thái đó chứ không gõ tay.*
