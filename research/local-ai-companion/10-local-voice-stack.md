# 10 — Local Voice Stack: TTS + Voice Cloning cho KOL ảo (VI/ZH/EN)

> **Status (2026-07-13)**: draft. Trả lời một mục tiêu mới — **mỗi KOL ảo phải CÓ GIỌNG NÓI
> riêng, nghe như người thật, chạy LOCAL** (tiết kiệm API), hỗ trợ **tiếng Việt / tiếng Trung /
> tiếng Anh**. Đây là lớp TTS/voice-clone còn thiếu: `01` mới liệt kê tên công cụ ở mức
> "Phase 2/3 預留"; `04`/`08` đã chốt **LiveTalking** cho digital human và chỉ định TTS ở mức
> module hoá (EdgeTTS / GPT-SoVITS / CosyVoice). File này **không mở lại** quyết định LiveTalking,
> mà lấp đầy lớp giọng nói: chọn model, tạo `voice_id` cho mỗi KOL, và điểm nối vào LiveTalking.
>
> **本文件用途 / Purpose**: bổ sung mảng TTS/voice-clone local vào research, tránh trùng `01`
> (chỉ có tên) và `04`/`08` (chỉ nói LiveTalking hỗ trợ TTS nào).
>
> **Chưa kiểm chứng end-to-end**: sandbox này không có GPU. Số liệu latency/VRAM/RTF lấy từ
> README/model card/benchmark công khai (2025-2026), cần đo lại trên máy GPU thật của user.

---

## 0. Bối cảnh & ràng buộc (đọc trước)

- Hiện trạng repo: giọng KOL đang là **ElevenLabs API** (cloud, trả phí). Xem
  `kols/sofia-vargas/profile.json → productions.self_intro.voiceover` (model
  `text2speech_v2_elevenlabs`, 3 bản Isabella/Harper/Roxie, chọn Roxie) và 3 file mp3 trong
  `kols/sofia-vargas/videos/self_intro/voiceover_*.mp3`. Mục tiêu: có phương án **local** thay/bổ
  sung để tiết kiệm API và chạy offline.
- Ràng buộc cứng: **local**, **VI + ZH + EN**, **clone từ mẫu ngắn (vài giây → 1 phút)**, dùng
  thương mại (KOL ảo → cần license cho phép commercial), và **nối được vào LiveTalking** (lip-sync).
- Latency budget (nguyên tắc của lớp này): với livestream trả lời comment, tổng vòng
  `comment → LLM token stream → TTS first-chunk → lip-sync → WebRTC` cần cảm giác < ~2s. TTS phải
  **streaming** (phát chunk đầu sớm), không chờ tổng hợp cả câu. Đây là tiêu chí loại/chọn chính,
  không phải chỉ chất lượng.

---

## 1. Bảng so sánh model TTS/voice-clone local (2025-2026)

| Model | Clone (mẫu) | VI | ZH | EN | Streaming / realtime | VRAM | License | Ghi chú cho dự án |
|---|---|---|---|---|---|---|---|---|
| **CosyVoice 2** (FunAudioLLM) | ✅ ~5–10s zero-shot | ⚠️ không chính thức | ✅ mạnh | ✅ | ✅ **first-packet ~150ms**, bi-streaming | ~4–6GB | **Apache-2.0** ✅ | **Top realtime**; native trong LiveTalking; +Cantonese/dialect; VI phải fine-tune |
| **GPT-SoVITS** (v2Pro/v4) | ✅ **1 phút** train, 5s zero-shot | ⚠️ fine-tune được | ✅ | ✅ | ⚠️ nhanh (~vài s/câu), có streaming | ~4GB | **MIT** ✅ (code) | Native trong LiveTalking; **license sạch nhất** để clone thương mại; cross-lingual timbre |
| **F5-TTS** | ✅ zero-shot + fine-tune | ✅ **F5-TTS-Vietnamese** (100h/1000h) | ✅ | ✅ | ❌ chủ yếu offline (flow-matching, ổn định long-form) | ~4–8GB | code MIT / **weights CC-BY-NC** ⚠️ | **Tốt nhất cho VI offline**; code-switch tốt; weights non-commercial → tự train mới dùng TM |
| **IndexTTS-2** (bilibili) | ✅ zero-shot | ❌ | ✅ **SOTA** | ✅ | ❌ chậm (offline, ~vài phút/đoạn) | ~6–8GB | riêng (kiểm tra) ⚠️ | **Offline ZH/EN cao cấp**: kiểm soát cảm xúc + duration tới ms → lồng tiếng video |
| **XTTS-v2 / viXTTS** | ✅ **6s** zero-shot, 17-18 lang | ✅ **viXTTS** (fine-tune VN) | ✅ | ✅ | ⚠️ có streaming (Coqui) | ~4GB | **CPML non-commercial** ⛔ | Model duy nhất **một giọng phủ cả VI+ZH+EN**, nhưng license chặn TM; Coqui đã ngừng |
| **Fish-Speech / OpenAudio S1** | ✅ zero-shot | ⚠️ | ✅ | ✅ | ⚠️ | ~4GB | CC-BY-NC-SA ⚠️ | Native LiveTalking; license non-commercial |
| **Kokoro** (82M) | ❌ giọng cố định | ❌ | ✅(有限) | ✅ | ✅ **realtime cả trên CPU** | <2GB / CPU | **Apache-2.0** ✅ | Rất nhẹ/rẻ nhưng **không clone**, không VI → chỉ làm fallback/placeholder |
| **Piper** | ❌ giọng cố định | ✅ có voice VI | — | ✅ | ✅ nhanh nhất trên CPU | CPU | **MIT** ✅ | Không clone; hữu ích khi cần VI rẻ/nhanh không cần clone |
| **RVC** (voice conversion) | 🔁 chuyển timbre, không phải TTS | n/a | n/a | n/a | ✅ realtime-capable | ~4GB | MIT-style | **Hậu kỳ**: đồng nhất/tinh chỉnh timbre sau TTS, hoặc chuẩn hoá giọng giữa các engine |

**Đọc bảng theo 3 câu hỏi của dự án**:
1. **Realtime + license thương mại + native LiveTalking** → **CosyVoice 2 (Apache-2.0)** và
   **GPT-SoVITS (MIT)** là hai lựa chọn sạch nhất. IndexTTS/F5/XTTS quá chậm hoặc vướng license
   cho luồng livestream.
2. **Chất lượng offline cao nhất để làm video**: ZH/EN → **IndexTTS-2** (cảm xúc + duration control)
   hoặc **GPT-SoVITS/F5**; **VI → F5-TTS-Vietnamese** (bản 1000h cho voice-clone tốt).
3. **Tiếng Việt là điểm nghẽn**: chưa model nào vừa (native VI) + (clone) + (Apache/MIT) + (realtime).
   viXTTS/F5-VI làm VI tốt nhưng non-commercial → với KOL thương mại phải **tự fine-tune** trên data
   VI có bản quyền (dùng code MIT của GPT-SoVITS/F5) để weights thuộc về mình.

---

## 2. Tiếng Việt — xử lý riêng (ràng buộc quyết định)

- **Không có "một model phủ đẹp cả VI+ZH+EN + clone + commercial"**. Vì vậy dùng **định tuyến theo
  ngôn ngữ (per-language routing)** với **cùng một mẫu giọng tham chiếu** cho mỗi KOL:
  - VI → F5-TTS-Vietnamese (offline) hoặc GPT-SoVITS fine-tune VN (realtime).
  - ZH/EN → CosyVoice 2 / GPT-SoVITS (cả offline lẫn realtime).
- **Nhất quán timbre giữa engine**: dùng chung 1 file reference audio; nếu nghe lệch chất giọng
  giữa VI-engine và ZH/EN-engine, cho qua **RVC** với cùng một model timbre để chuẩn hoá.
- **License cho VI thương mại**: F5-VI/viXTTS weights là non-commercial. Cách hợp lệ: lấy **code**
  (MIT của GPT-SoVITS hoặc F5) + **fine-tune trên data tiếng Việt có quyền dùng** (ví dụ viVoice
  dataset kiểm tra điều khoản, hoặc thu âm riêng) → weights của mình dùng thương mại. Cần
  `livestream-tech-specialist`/pháp lý xác nhận trước khi phát hành.

---

## 3. Stack giọng nói local đề xuất (2 tầng)

### 3.1 Tầng REALTIME — livestream trả lời comment
- **Engine chính: CosyVoice 2** (Apache-2.0, first-packet ~150ms, bi-streaming, native LiveTalking,
  ZH/EN + Cantonese). VI: fine-tune hoặc tạm dùng GPT-SoVITS-VN.
- **Engine thay thế: GPT-SoVITS** (MIT, native LiveTalking, clone 1 phút) — chọn khi cần license
  MIT tuyệt đối hoặc khi CosyVoice cài đặt trục trặc.
- **Latency budget**: TTS first-chunk ~150–300ms; giữ `inferfps`/`finalfps` ≥ 25 (điều kiện realtime
  của LiveTalking, xem `04` §2.1). TTS **phải** feed chunk vào `/human` dạng streaming, đồng bộ với
  token stream của LLM (`03` Orchestrator đã yêu cầu streaming — khớp sẵn).

### 3.2 Tầng OFFLINE — dựng video chất lượng cao (thay ElevenLabs)
- **ZH/EN: IndexTTS-2** (kiểm soát cảm xúc + duration tới ms, hợp lồng tiếng khớp hình) hoặc
  **GPT-SoVITS/F5-TTS** nếu muốn dùng lại đúng engine của tầng realtime.
- **VI: F5-TTS-Vietnamese** (bản 100h/1000h) — chất lượng VI clone tốt nhất hiện có.
- Không cần streaming ở tầng này → ưu tiên chất lượng, chấp nhận render chậm.

### 3.3 Hậu kỳ (tuỳ chọn)
- **RVC**: tinh chỉnh/đồng nhất timbre sau TTS, hoặc kéo giọng zero-shot về gần chất giọng KOL hơn.

### 3.4 Khi nào dùng API (ElevenLabs) & fallback rẻ
- **Dùng ElevenLabs khi**: cần chất lượng VI đỉnh ngay lập tức mà local chưa fine-tune xong; deadline
  gấp; hoặc A/B chọn giọng (như flow hiện tại của `sofia-vargas`). Đây là **fallback chất lượng**,
  không phải mặc định (vì tốn API).
- **Fallback rẻ/miễn phí**: **EdgeTTS** (LiveTalking hỗ trợ sẵn, 0đ, không clone) để prototype nhanh
  luồng echo; **Piper/Kokoro** cho placeholder offline/CPU khi chưa có giọng clone.

---

## 4. Yêu cầu phần cứng

| Kịch bản | GPU tối thiểu | Ghi chú VRAM |
|---|---|---|
| TTS realtime (CosyVoice2 / GPT-SoVITS) đơn lẻ | RTX 3060 8GB | TTS ~4–6GB |
| TTS realtime **+ LiveTalking (Wav2Lip256)** cùng máy | RTX 3060–3070 12GB | LiveTalking Wav2Lip nhẹ; tổng vừa 8–12GB |
| TTS + LiveTalking (MuseTalk) + LLM chat cùng máy | RTX 3090/4090 24GB | **Cạnh tranh VRAM 3 chiều** — xem cảnh báo dưới |
| TTS offline (F5/IndexTTS-2) dựng video | RTX 3060+; không cần realtime | Chấp nhận render chậm |
| Fallback CPU (Piper/Kokoro) | Không cần GPU | Không clone, chỉ placeholder |

**Cạnh tranh VRAM (quan trọng)**: giọng nói ăn chung VRAM với LiveTalking và với local LLM (`03`
chat mode). Ưu tiên: chế độ **echo** (không LLM) để TTS+lip-sync gọn nhất; nếu chạy chat cùng máy,
dùng Wav2Lip (tiết kiệm VRAM) + LLM nhỏ, hoặc tách LLM sang card/máy khác. Mac mini / không NVIDIA:
realtime clone không khả thi (giống kết luận `04`/`06`), lùi về offline hoặc CPU-fallback.

---

## 5. Quy trình tạo `voice_id` cho mỗi KOL

1. **Thu/chọn mẫu tham chiếu**: 6–30s (hoặc tới 1 phút cho GPT-SoVITS train) audio sạch, 1 người
   nói, không nhạc nền, đúng "voice_tone" trong `kols/{id}/profile.json → persona.voice_tone`.
   Nguồn hợp lệ: giọng do dự án tự sản xuất / có quyền dùng (KHÔNG clone người thật khi chưa có đồng
   ý — xem `04` §8 rủi ro hình ảnh/giọng nói).
2. **Chuẩn hoá**: 24kHz mono, cắt khoảng lặng, khử ồn.
3. **Đăng ký voice**:
   - CosyVoice2/F5/XTTS: lưu thẳng file reference (zero-shot, không cần train).
   - GPT-SoVITS: (tuỳ chọn) fine-tune ~1 phút → ra weight `.ckpt/.pth` riêng cho KOL.
4. **(Tuỳ chọn) RVC model** cho timbre nhất quán giữa các ngôn ngữ.
5. **Ghi vào profile.json** (đề xuất field, xem §6), tham chiếu tới file mẫu + config engine.
6. **Nghiệm thu**: sinh 1 câu mỗi ngôn ngữ (VI/ZH/EN), nghe khớp voice_tone; đo latency first-chunk.

---

## 6. Đề xuất schema — lưu voice vào `profile.json`

Đặt **cạnh `ai_assets.soul_*`** (visual identity) để voice là "định danh giọng" song song với
"định danh hình" — cùng cấp, tái sử dụng cho mọi production. Đề xuất thêm `ai_assets.voice`:

```jsonc
"ai_assets": {
  "soul_v3": { /* ... hình ảnh, đã có ... */ },
  "voice": {
    "voice_id": "sofia-vargas-v1",
    "reference_audio": "kols/sofia-vargas/voice/ref_sofia_30s.wav",
    "voice_tone_ref": "persona.voice_tone",          // liên kết mô tả sẵn có
    "engines": {
      "realtime": { "engine": "cosyvoice2", "mode": "zero_shot" },
      "offline":  { "engine": "f5-tts", "vi_model": "f5-tts-vietnamese-1000h" },
      "post":     { "engine": "rvc", "model": "kols/sofia-vargas/voice/rvc_sofia.pth" }
    },
    "languages": ["vi", "zh", "en"],
    "gptsovits_ckpt": null,                            // nếu có fine-tune riêng
    "license_note": "voice tự sản xuất / có quyền TM",
    "status": "draft"
  }
}
```

- Vì sao `ai_assets.voice` chứ không `persona.voice`: `persona.voice_tone` là **mô tả người** (giữ
  nguyên, dùng để hướng dẫn tạo giọng); `ai_assets.voice` là **artifact kỹ thuật** (file + engine)
  song song với higgsfield soul. Field mới, không phá schema hiện tại (thêm optional).
- Cần cập nhật `kols/schema.json` (thêm `ai_assets` vốn chưa có trong schema — hiện `sofia-vargas`
  đã dùng `ai_assets` nhưng schema chưa định nghĩa; đây là dịp bổ sung cả `soul_*` lẫn `voice`).

---

## 7. Điểm tích hợp với LiveTalking (`04`/`08`)

- LiveTalking đã **module hoá TTS**: hỗ trợ `edgetts`, `gpt-sovits`, `cosyvoice`, `fish-speech`,
  `xtts`, `tencent`. → stack đề xuất **khớp native**: chọn `cosyvoice` hoặc `gpt-sovits` là xong,
  không cần tự viết cầu nối.
- Luồng: `voice_id` (reference/ckpt) → cấu hình TTS backend của LiveTalking → `/human` (echo: đọc
  văn bản; chat: nối `03` Orchestrator) → Wav2Lip/MuseTalk lip-sync → WebRTC/RTMP/virtual-cam.
- **Không đổi** kiến trúc `04`: đây chỉ là "điền engine TTS" mà `04` §3 để ngỏ. MVP echo dùng
  EdgeTTS trước (0đ), rồi thay bằng CosyVoice2/GPT-SoVITS đã clone giọng KOL.
- Giới hạn đã biết (`08` Issue #510): khả năng "ngắt lời" realtime yếu (~3s) — không ảnh hưởng echo
  đọc kịch bản, nhưng ảnh hưởng chat trả lời comment tức thời; TTS streaming giúp giảm phần latency
  thuộc về giọng, phần còn lại là giới hạn kiến trúc LiveTalking.

---

## 8. Rủi ro chính

1. **Tiếng Việt + commercial license**: model VI tốt nhất (viXTTS/F5-VI) là non-commercial; phải tự
   fine-tune trên data có quyền để dùng thương mại → tốn công + cần rà pháp lý.
2. **Nhất quán timbre đa engine/đa ngôn ngữ**: định tuyến 2 engine (VI vs ZH/EN) có thể lệch chất
   giọng cùng một KOL; phụ thuộc RVC để chuẩn hoá, chưa chắc hoàn hảo.
3. **VRAM 3 chiều**: TTS + lip-sync (LiveTalking) + LLM chat tranh chung 1 GPU; realtime + chất
   lượng khó đạt đồng thời trên card tầm trung.
4. **Chưa đo thực**: mọi số latency/VRAM lấy từ tài liệu công khai, chưa chạy trên GPU dự án.

---

## 9. Bước triển khai (đề xuất, chưa chạy)

1. **MVP echo, 0đ**: LiveTalking + EdgeTTS đọc 1 câu VI/ZH/EN, xác nhận luồng chạy (khớp `05` POC).
2. **Realtime clone**: cài CosyVoice2 (Apache) trong LiveTalking, nạp reference 1 KOL, đo first-chunk
   + `inferfps/finalfps`. Nếu cài trục trặc → thử GPT-SoVITS (MIT).
3. **VI**: dựng F5-TTS-Vietnamese (offline) cho video; đánh giá GPT-SoVITS-VN cho realtime.
4. **Offline video**: benchmark IndexTTS-2 (ZH/EN) vs F5 để thay ElevenLabs trong pipeline
   `productions.*.voiceover`.
5. **Ghi `ai_assets.voice`** cho 1 KOL thử (gợi ý `sofia-vargas`: đã có mp3 tham chiếu sẵn) và cập
   nhật `kols/schema.json`.
6. **Điền số thực** vào bảng §1/§4 và cập nhật `04`/`05` khi có kết quả GPU thật.

---

## Nguồn (tra cứu 2026-07)

- [LiveTalking (GitHub) — TTS module: edgetts/gpt-sovits/cosyvoice/fish-speech/xtts/tencent](https://github.com/lipku/LiveTalking)
- [LiveTalking docs — CosyVoice TTS](https://doc.livetalking.ai/en/docs/tts/cosyvoice/)
- [CosyVoice 2 (FunAudioLLM, Apache-2.0, first-packet ~150ms, streaming)](https://github.com/FunAudioLLM/CosyVoice) · [CosyVoice2 page](https://funaudiollm.github.io/cosyvoice2/)
- [GPT-SoVITS (RVC-Boss, MIT, 1-min few-shot clone)](https://github.com/RVC-Boss/GPT-SoVITS)
- [F5-TTS-Vietnamese-ViVoice / 100h (hynt, HuggingFace)](https://huggingface.co/hynt/F5-TTS-Vietnamese-ViVoice) · [F5-TTS-Vietnamese-100h](https://huggingface.co/hynt/F5-TTS-Vietnamese-100h) · [F5-TTS-Vietnamese (GitHub)](https://github.com/nguyenthienhy/F5-TTS-Vietnamese)
- [viXTTS (XTTS-v2 fine-tune tiếng Việt, 18 lang)](https://www.promptlayer.com/models/vixtts/)
- [IndexTTS / IndexTTS-2 (bilibili, ZH/EN, emotion + duration control)](https://index-tts.github.io/) · [arXiv 2502.05512](https://arxiv.org/html/2502.05512v1)
- [Kokoro TTS (82M, Apache-2.0, realtime CPU, không clone)](https://localaimaster.com/blog/kokoro-tts-local-setup)
- [So sánh clone giọng 2026: IndexTTS-2/CosyVoice/GPT-SoVITS/Fish/VoxCPM (liudon)](https://liudon.com/posts/voice-cloning-solution-comparison/)
- [Best Local TTS Models 2026 (Local AI Master)](https://localaimaster.com/blog/best-local-tts-models)
- [Which Open Source TTS Model — license & tradeoffs (DataRoot Labs)](https://datarootlabs.com/blog/text-to-speech-models)
- [Best TTS Models 2026 — Elo / open-weight (CodeSOTA)](https://www.codesota.com/guides/tts-models)
</content>
</invoke>
