import random
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np
import torch
import gradio as gr
from chatterbox.tts import ChatterboxTTS
from utils.platform_tools import select_device


DEVICE = select_device()


def set_seed(seed: int):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)


def load_model():
    model = ChatterboxTTS.from_pretrained(DEVICE)
    return model


def generate(model, text, audio_prompt_path, exaggeration, temperature, seed_num, cfgw, min_p, top_p, repetition_penalty):
    if model is None:
        model = ChatterboxTTS.from_pretrained(DEVICE)

    if seed_num != 0:
        set_seed(int(seed_num))

    wav = model.generate(
        text,
        audio_prompt_path=audio_prompt_path,
        exaggeration=exaggeration,
        temperature=temperature,
        cfg_weight=cfgw,
        min_p=min_p,
        top_p=top_p,
        repetition_penalty=repetition_penalty,
    )
    return (model.sr, wav.squeeze(0).numpy())


with gr.Blocks(title="Chatterbox TTS Studio") as demo:
    model_state = gr.State(None)  # Loaded once per session/user

    gr.Markdown("# 🎙️ Chatterbox TTS Studio")
    gr.Markdown("Chuyển đổi văn bản thành giọng nói AI chất lượng cao với khả năng nhái giọng và điều chỉnh cảm xúc.")

    with gr.Row():
        with gr.Column():
            text = gr.Textbox(
                value="Hello! This is Chatterbox TTS. Enter your English script here.",
                label="Văn bản cần sinh giọng nói (Tối đa 300 ký tự)",
                max_lines=5
            )
            gr.Markdown("**Ngôn ngữ sinh giọng:** English")
            ref_wav = gr.Audio(sources=["upload", "microphone"], type="filepath", label="File âm thanh mẫu (Giọng đọc mẫu)", value=None)
            exaggeration = gr.Slider(0.25, 2, step=.05, label="Cảm xúc / Độ nhấn nhá (Mặc định = 0.5, giá trị cực đoan có thể kém ổn định)", value=.5)
            cfg_weight = gr.Slider(0.0, 1, step=.05, label="CFG / Tốc độ đọc (Pace)", value=0.5)

            with gr.Accordion("Tùy chọn cấu hình nâng cao", open=False):
                seed_num = gr.Number(value=0, label="Seed ngẫu nhiên (Nhập 0 để chọn ngẫu nhiên)")
                temp = gr.Slider(0.05, 5, step=.05, label="Nhiệt độ sáng tạo (Temperature)", value=.8)
                min_p = gr.Slider(0.00, 1.00, step=0.01, label="Min P (Bộ lấy mẫu mới, đề xuất 0.02 - 0.1, 0.00 để tắt)", value=0.05)
                top_p = gr.Slider(0.00, 1.00, step=0.01, label="Top P (Bộ lấy mẫu gốc, đề xuất 1.0)", value=1.00)
                repetition_penalty = gr.Slider(1.00, 2.00, step=0.1, label="Phạt lặp từ (Repetition Penalty)", value=1.2)

            run_btn = gr.Button("🚀 Sinh giọng nói (Generate)", variant="primary")

        with gr.Column():
            audio_output = gr.Audio(label="Kết quả âm thanh (Output Audio)")

    demo.load(fn=load_model, inputs=[], outputs=model_state)

    run_btn.click(
        fn=generate,
        inputs=[
            model_state,
            text,
            ref_wav,
            exaggeration,
            temp,
            seed_num,
            cfg_weight,
            min_p,
            top_p,
            repetition_penalty,
        ],
        outputs=audio_output,
    )

if __name__ == "__main__":
    demo.queue(
        max_size=50,
        default_concurrency_limit=1,
    ).launch(share=True)
