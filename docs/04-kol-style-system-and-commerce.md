# KOL Style System & Commerce Roles — 風格系統與商業角色

> Mục tiêu: chuẩn hoá cách thiết kế KOL theo **nhiều phong cách** (dễ thương, sexy, nữ tính,
> người bán hàng…) và **pha trộn** chúng một cách có hệ thống — thay vì mỗi KOL là một thiết kế
> rời rạc. Tài liệu này mở rộng `.claude/skills/kol-builder/references/flavors.md`.

Điểm cốt lõi: yêu cầu "các phong cách khác nhau" của bạn thực ra là **2 trục độc lập**, không phải
một danh sách phẳng. Tách 2 trục ra thì "pha trộn" trở thành phép nhân ma trận, phủ được mọi kiểu.

---

## Trục 1 — Persona Flavor（人格風格）: KOL trông & cảm giác thế nào

| # | Flavor | Cốt lõi (反差 / hook) | Màu & cảnh | Ví dụ có sẵn |
|---|--------|----------------------|-----------|--------------|
| F1 | **純欲 Innocent-Alluring** | Mặt ngây thơ + dáng gợi cảm (反差萌) | morandi/trắng/blush, mirror selfie, resort | `chloe-lin` |
| F2 | **Cute × Elegant Wholesome** | Thành đạt + chân thật, chia sẻ cả cuộc sống | kem/caramel/denim, café/travel/gym | `sienna-lai` |
| F3 | **Real-IP Sexy** | Sexy nhưng "người thật", ảnh điện thoại thô | available light, mirror/car/home candid | `mika-tran` |
| **F5** | **甜妹 Pure Cute（dễ thương thuần）** | Trẻ trung, tươi, playful, năng lượng "kẹo ngọt" | pastel/kem/hồng nhạt, café/công viên/phòng ngủ sáng | *(mới — cần build)* |
| **F6** | **溫柔知性 Feminine-Elegant（nữ tính）** | Dịu dàng, thanh lịch, mềm mại, "chị gái tinh tế" | be/tơ lụa/nâu ấm/trắng ngà, cửa sổ/hoa/bàn trà | *(mới — cần build)* |
| F4 | **Male Real-IP** | Nam, confident-casual, candid | festival/road-trip/streetwear | `jax-calloway` |

> F5 và F6 tách riêng khỏi F2 vì F2 là "cute + elegant + thành đạt" cùng lúc; còn bạn muốn **dễ
> thương thuần** (F5, trẻ hơn, ít "sang") và **nữ tính dịu dàng** (F6, ít "playful", nhiều "mềm")
> là hai vibe khác nhau. Có đủ 3 thì blend mới phong phú.

Ranh giới bất biến cho MỌI flavor (từ `style-guideline.md`): người lớn (≥22), mức mainstream
fashion/travel, **không bao giờ explicit/NSFW**, giữ da thật, kết bài bằng câu hỏi mở.

---

## Trục 2 — Commerce Role（商業角色）: "người bán hàng" nằm ở đây

Đây là chỗ đặt yêu cầu **"người bán hàng"** của bạn. Bán hàng KHÔNG phải một flavor ngang hàng với
"dễ thương/sexy" — nó là một **lớp vai trò** phủ lên bất kỳ flavor nào. Một KOL có thể là "dễ thương
+ bán hàng" hoặc "sexy + bán hàng". Cường độ bán tăng dần:

| Role | Tên | KOL làm gì | Đọc comment để làm gì | Phase |
|------|-----|-----------|----------------------|-------|
| **R0** | Pure Influencer | Xây hình ảnh, thẩm mỹ, độ nhận biết | Tương tác, nuôi cộng đồng | 1 |
| **R1** | Soft Seller / Tư vấn | Review chân thực, gợi ý nhẹ, affiliate | Trả lời "mua ở đâu / dùng sao" | 1 |
| **R2** | Active Seller / KOC | Demo sản phẩm, mã giảm giá, giỏ hàng | Lọc comment **có ý định mua** → rep + đẩy về DM | 1–2 |
| **R3** | Hard Seller / Live Closer | Chốt đơn realtime, tạo urgency | Đọc **live chat**, đọc tên → chốt tại chỗ | 3 (sau) |

**Vòng đọc-comment (chi tiết ở `research/local-ai-companion/11-...`)** chính là động cơ của trục
này: R0/R1 chỉ cần rep công khai; R2 cần **phân loại ý định mua** rồi kéo về DM 1-1; R3 cần realtime
(để sau, vì cần GPU/CUDA — Mac không chạy được).

---

## Ma trận Blend — Flavor × Role（bảng chọn nhân vật）

Mỗi ô là một "concept KOL" khả thi. ✅ = đề xuất build sớm cho mục tiêu bán hàng của bạn.

| Flavor ↓ \ Role → | R1 Soft Seller | R2 Active Seller (KOC) | R3 Live Closer |
|---|---|---|---|
| **F5 甜妹 Cute** | Cute reviewer mỹ phẩm/ăn vặt | ✅ **"em gái bán hàng dễ thương"** — hot cho FMCG/beauty | Live bán đồ teen |
| **F6 溫柔 Feminine** | ✅ Tư vấn skincare/đồ nữ nhẹ nhàng, đáng tin | Bán đồ nữ/nội y/trang sức thanh lịch | Live spa/skincare |
| **F2 Cute×Elegant** | ✅ Review travel/tech/lifestyle (đã có `sienna-lai`) | Bán khoá học/đồ cao cấp | — |
| **F1 純欲** | Gợi ý thời trang/đồ bơi | Bán fashion/activewear | Live thời trang |
| **F3 Real-IP Sexy** | Review "thật" đồ gym/going-out | ✅ Bán activewear/nightlife bằng độ tin "người thật" | Live đồ bơi/gym |

**Pha trộn flavor–flavor** (không chỉ flavor–role) cũng nằm trong hệ này, ví dụ:
- **F5×F1** = "dễ thương pha 純欲" → mặt kẹo ngọt nhưng dáng có đường cong (đây gần như `chloe-lin`).
- **F6×F3** = "nữ tính pha sexy" → dịu dàng nhưng bodycon buổi tối (elegant-sexy).
- **F5×F6** = "dễ thương pha nữ tính" →甜美溫柔, an toàn nhất cho beauty/mom-market.

Cách encode blend trong `profile.json`: `meta.category` giữ chính (vd `lifestyle`), thêm
`meta.tags: ["flavor:F5","flavor:F1","role:R2"]` và mô tả blend ở `persona.archetype`.

---

## Đề xuất danh mục KOL nên build + bản đồ thị trường (Đài Loan · Mỹ · Âu)

Mục tiêu thị trường: **Đài Loan (ưu tiên) · châu Mỹ · châu Âu**. Một KOL không phủ được cả 3 thị
trường một cách tự nhiên → phủ bằng **roster** (mỗi KOL mạnh ở 1-2 thị trường qua ngôn ngữ + gốc gác):

| # | KOL | Blend | Chức năng bán | Thị trường mạnh | Trạng thái |
|---|-----|-------|---------------|-----------------|-----------|
| 1 | **`lena-chen`** (flagship) | F5×F1 + **R2** | KOC beauty/FMCG, đọc comment→chốt DM | 🇹🇼 Đài + 🇺🇸 Mỹ (繁中/EN) | ✅ **đã dựng đủ 4 file + voice + comment policy** |
| 2 | KOL nữ tính tư vấn (build tiếp) | F6 + **R1/R2** | skincare/đồ nữ, tin cậy cao | 🇪🇺 Âu (EN + 1 tiếng Âu) | đề xuất — phủ Âu |
| 3 | `sienna-lai` (có sẵn) | F2 + R1 | lifestyle/tech/travel affiliate | 🇹🇼 Đài + 🇨🇦 Bắc Mỹ | nâng cấp thêm role |
| 4 | `mika-tran` (có sẵn) | F3 + R2 | activewear/nightlife "thật" | 🇺🇸 Mỹ | nâng cấp thêm role |
| 5 | `chloe-lin` (có sẵn) | F1 + R1 | fashion/đồ bơi | 🇹🇼 Đài + 🇺🇸 Mỹ | nâng cấp thêm role |
| 6 | `sofia-vargas` (có sẵn) | lifestyle + R1 | — | 🌎 Latin/Mỹ (ES/EN) | có thể thêm role |

**Lý do chọn ZH/EN cho flagship:** thị trường mới bỏ trọng tâm tiếng Việt → cặp **繁中 + English**
được stack giọng local (CosyVoice2 / IndexTTS-2) phủ rất tốt, **gỡ bỏ rủi ro #1** (license model
tiếng Việt) trong `research/local-ai-companion/10-local-voice-stack.md`.

**Để phủ châu Âu** (khoảng trống lớn nhất hiện tại): đề xuất build KOL #2 theo flavor **F6 溫柔知性**
gốc Âu-Á (vd Đài-Pháp/Đài-Đức), ngôn ngữ EN + 1 tiếng Âu, vai trò R1/R2 tư vấn skincare/đồ nữ.

→ `lena-chen` là **mẫu chuẩn** (reference build) để nhân bản cho các KOL/thị trường còn lại.

---

## Liên kết với 3 trụ kỹ thuật (research/local-ai-companion/)

- **Trông như thật** → `09-realistic-visual-stack.md` (Flux + LoRA/InstantID + khử "mùi AI").
- **Giọng nói** → `10-local-voice-stack.md` (mỗi flavor một `voice_id`; F5 giọng tươi cao, F6 giọng trầm ấm dịu).
- **Đọc comment & hành động** → `11-comment-read-and-act-loop.md` (động cơ của Trục 2 / Commerce Role).
- **Scheme thu hút khách** → xem master doc `research/local-ai-companion/12-growth-and-sales-scheme.md`.
