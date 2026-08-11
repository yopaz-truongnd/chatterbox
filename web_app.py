import random
import os
import numpy as np
import torch
import gradio as gr
from pathlib import Path

from chatterbox.tts import ChatterboxTTS
from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES
from chatterbox.vc import ChatterboxVC
from config.constants import LANGUAGES_WITH_FLAGS, UI_LANGUAGES
from config.settings import settings_manager

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
VI_I18N = gr.I18n(vi={})

def set_seed(seed: int):
    torch.manual_seed(seed)
    if DEVICE == "cuda":
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)

# --- Global Model Cache ---
tts_model = None
mtl_model = None
vc_model = None

def get_tts_model():
    global tts_model
    if tts_model is None:
        print(f"Loading ChatterboxTTS on {DEVICE}...")
        tts_model = ChatterboxTTS.from_pretrained(DEVICE)
    return tts_model

def get_mtl_model():
    global mtl_model
    if mtl_model is None:
        print(f"Loading ChatterboxMultilingualTTS on {DEVICE}...")
        mtl_model = ChatterboxMultilingualTTS.from_pretrained(DEVICE)
    return mtl_model

def get_vc_model():
    global vc_model
    if vc_model is None:
        print(f"Loading ChatterboxVC on {DEVICE}...")
        vc_model = ChatterboxVC.from_pretrained(DEVICE)
    return vc_model


# --- TTS Generation ---
def generate_tts(text, audio_prompt, exaggeration, temp, seed_num, cfgw, min_p, top_p, rep_penalty):
    if not text or not text.strip():
        return None
    model = get_tts_model()
    if seed_num != 0:
        set_seed(int(seed_num))
    wav = model.generate(
        text,
        audio_prompt_path=audio_prompt,
        exaggeration=exaggeration,
        temperature=temp,
        cfg_weight=cfgw,
        min_p=min_p,
        top_p=top_p,
        repetition_penalty=rep_penalty
    )
    return (model.sr, wav.squeeze(0).numpy())


# --- Multilingual Generation ---
def generate_mtl(text, lang_code, audio_prompt, exaggeration, temp, seed_num, cfgw):
    if not text or not text.strip():
        return None
    model = get_mtl_model()
    if seed_num != 0:
        set_seed(int(seed_num))
    
    # Extract code e.g. "en" from "🇬🇧 English (en)"
    if "(" in lang_code and ")" in lang_code:
        code = lang_code.split("(")[-1].split(")")[0].strip()
    else:
        code = lang_code.strip()

    generate_kwargs = {
        "exaggeration": exaggeration,
        "temperature": temp,
        "cfg_weight": cfgw
    }
    if audio_prompt:
        generate_kwargs["audio_prompt_path"] = audio_prompt
    wav = model.generate(
        text[:300],
        language_id=code,
        **generate_kwargs
    )
    return (model.sr, wav.squeeze(0).numpy())


# --- Voice Conversion ---
def generate_vc(source_audio, target_audio):
    if not source_audio:
        return None
    model = get_vc_model()
    wav = model.generate(source_audio, target_voice_path=target_audio)
    return (model.sr, wav.squeeze(0).numpy())


# --- Settings Save/Load ---
def load_settings():
    settings_manager.load()
    return (
        settings_manager.get("export_dir", os.path.expanduser("~/Downloads")),
        settings_manager.get("model_cache_dir", str(Path("/var/www/chatterbox/models").absolute())),
        settings_manager.get("language", "🇻🇳 Tiếng Việt"),
        settings_manager.get("device", "auto"),
        settings_manager.get("default_startup_model", "Chatterbox Standard (500M)"),
        settings_manager.get("max_chunk_chars", 4000)
    )

def save_settings(exp_dir, cache_dir, lang, dev, model_name, max_chunk):
    settings_manager.set("export_dir", exp_dir)
    settings_manager.set("model_cache_dir", cache_dir)
    settings_manager.set("language", lang)
    settings_manager.set("device", dev)
    settings_manager.set("default_startup_model", model_name)
    settings_manager.set("max_chunk_chars", int(max_chunk))
    settings_manager.save()
    return "✓ Đã lưu cài đặt thành công vào config/settings.json!"


with gr.Blocks(title="Chatterbox TTS Studio - Web Interface") as demo:
    gr.Markdown("# 🎙️ Chatterbox TTS Studio (Web Interface)")

    with gr.Tabs():
        # TAB 1: TTS Studio
        with gr.Tab("🗣️ TTS Studio"):
            with gr.Row():
                with gr.Column():
                    tts_text = gr.Textbox(
                        value="Hello! This is Chatterbox TTS Studio. Enter your English script here.",
                        label="Văn bản cần sinh giọng nói",
                        lines=4
                    )
                    gr.Markdown("**Ngôn ngữ sinh giọng:** English")
                    tts_ref = gr.Audio(sources=["upload", "microphone"], type="filepath", label="File âm thanh mẫu (Giọng đọc mẫu)")
                    tts_exag = gr.Slider(0.25, 2.0, step=0.05, value=0.5, label="Cảm xúc / Độ nhấn nhá (Exaggeration)")
                    tts_cfg = gr.Slider(0.0, 1.0, step=0.05, value=0.5, label="Tốc độ / Độ bám CFG Weight")

                    with gr.Accordion("Tùy chọn nâng cao", open=False):
                        tts_seed = gr.Number(value=0, label="Seed ngẫu nhiên (0 là ngẫu nhiên)")
                        tts_temp = gr.Slider(0.05, 5.0, step=0.05, value=0.8, label="Sáng tạo (Temperature)")
                        tts_min_p = gr.Slider(0.00, 1.00, step=0.01, value=0.05, label="Min P")
                        tts_top_p = gr.Slider(0.00, 1.00, step=0.01, value=1.00, label="Top P")
                        tts_rep_pen = gr.Slider(1.00, 2.00, step=0.1, value=1.2, label="Phạt lặp (Repetition Penalty)")

                    tts_btn = gr.Button("🚀 Sinh giọng nói (Generate)", variant="primary")

                with gr.Column():
                    tts_output = gr.Audio(label="Kết quả âm thanh (Output Audio)")

            tts_btn.click(
                fn=generate_tts,
                inputs=[tts_text, tts_ref, tts_exag, tts_temp, tts_seed, tts_cfg, tts_min_p, tts_top_p, tts_rep_pen],
                outputs=tts_output
            )

        # TAB 2: Multilingual TTS
        with gr.Tab("🌐 Multilingual TTS"):
            with gr.Row():
                with gr.Column():
                    mtl_text = gr.Textbox(
                        value="Hello! This is Chatterbox Multilingual TTS.",
                        label="Văn bản đọc đa ngôn ngữ (Max 300 ký tự)",
                        lines=4
                    )
                    
                    mtl_lang_choices = [f"{v} ({k})" for k, v in LANGUAGES_WITH_FLAGS.items()]
                    mtl_lang = gr.Dropdown(
                        choices=mtl_lang_choices,
                        value="🇬🇧 English (en)",
                        label="Ngôn ngữ đọc (Language)",
                        info="Chọn ngôn ngữ mong muốn cho mô hình Multilingual TTS"
                    )
                    mtl_ref = gr.Audio(sources=["upload", "microphone"], type="filepath", label="Audio giọng đọc mẫu (Tùy chọn)")
                    mtl_exag = gr.Slider(0.25, 2.0, step=0.05, value=0.5, label="Độ biểu cảm (Exaggeration)")
                    mtl_cfg = gr.Slider(0.0, 1.0, step=0.05, value=0.5, label="CFG/Pace Weight")

                    with gr.Accordion("Nâng cao", open=False):
                        mtl_seed = gr.Number(value=0, label="Seed ngẫu nhiên")
                        mtl_temp = gr.Slider(0.05, 5.0, step=0.05, value=0.8, label="Nhiệt độ (Temperature)")

                    mtl_btn = gr.Button("🌐 Sinh giọng nói Multilingual", variant="primary")

                with gr.Column():
                    mtl_output = gr.Audio(label="Kết quả âm thanh Multilingual")

            mtl_btn.click(
                fn=generate_mtl,
                inputs=[mtl_text, mtl_lang, mtl_ref, mtl_exag, mtl_temp, mtl_seed, mtl_cfg],
                outputs=mtl_output
            )

        # TAB 3: Voice Conversion
        with gr.Tab("🔁 Voice Conversion"):
            with gr.Row():
                with gr.Column():
                    vc_src = gr.Audio(sources=["upload", "microphone"], type="filepath", label="File âm thanh nguồn (Source Audio)")
                    vc_tgt = gr.Audio(sources=["upload", "microphone"], type="filepath", label="File giọng mẫu đích (Target Voice Audio)")
                    vc_btn = gr.Button("🔁 Chuyển đổi giọng nói (Convert Voice)", variant="primary")
                with gr.Column():
                    vc_output = gr.Audio(label="Kết quả chuyển đổi giọng")

            vc_btn.click(
                fn=generate_vc,
                inputs=[vc_src, vc_tgt],
                outputs=vc_output
            )

        # TAB 4: Settings
        with gr.Tab("⚙️ Cài đặt (Settings)", elem_id="settings"):
            gr.Markdown("### ⚙️ Cài đặt hệ thống (System Settings)")
            curr_exp, curr_cache, curr_lang, curr_dev, curr_model, curr_chunk = load_settings()

            set_export_dir = gr.Textbox(value=curr_exp, label="Thư mục xuất âm thanh mặc định (Export Directory)")
            set_model_cache = gr.Textbox(value=curr_cache, label="Thư mục lưu Cache Model (Model Cache Directory)")
            
            lang_options = list(UI_LANGUAGES.values())
            set_lang = gr.Dropdown(
                choices=lang_options,
                value=curr_lang if curr_lang in lang_options else "🇻🇳 Tiếng Việt",
                label="Ngôn ngữ giao diện (Interface Language)"
            )
            set_dev = gr.Dropdown(
                choices=["auto", "cuda", "cpu"],
                value=curr_dev,
                label="Thiết bị tính toán (Device)"
            )
            set_model = gr.Dropdown(
                choices=[
                    "Chatterbox Standard (500M)",
                    "Chatterbox Turbo (350M - Fast)",
                    "Chatterbox Nano (110M - Light/CPU)",
                    "Multilingual V3 (500M)"
                ],
                value=curr_model,
                label="Mô hình mặc định khi nạp"
            )
            set_max_chunk = gr.Number(value=curr_chunk, label="Số ký tự cắt đoạn tối đa (Max Chunk Chars)")

            save_btn = gr.Button("💾 Lưu cài đặt (Save Settings)", variant="primary")
            save_msg = gr.Markdown("")

            save_btn.click(
                fn=save_settings,
                inputs=[set_export_dir, set_model_cache, set_lang, set_dev, set_model, set_max_chunk],
                outputs=save_msg
            )

    AUTO_TAB_JS = """
    () => {
        const params = new URLSearchParams(window.location.search);
        if (params.get("view") === "settings") {
            setTimeout(() => {
                const buttons = Array.from(document.querySelectorAll("button"));
                const settingsBtn = buttons.find(b => b.textContent.includes("Cài đặt") || b.textContent.includes("Settings"));
                if (settingsBtn) {
                    settingsBtn.click();
                }
            }, 300);
        }
    }
    """
    demo.load(fn=None, js=AUTO_TAB_JS)

if __name__ == "__main__":
    demo.queue().launch(server_name="127.0.0.1", server_port=7860, share=False, theme=gr.themes.Soft(), i18n=VI_I18N)
