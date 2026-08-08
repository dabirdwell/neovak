# 💡 NeoVak

**Local AI Creative Suite**

Generate images, videos, voice, and music using AI models running entirely on your machine. No cloud, no subscriptions, no limits.

*Think "LM Studio for multimedia"*

---

## ✨ Features

### 🖼️ Image Generation

- **Create** — Generate images from text with SD 1.5, SDXL, Flux, Lightning, Turbo
- **Edit** — Transform existing images with img2img
- **Upscale** — Enhance resolution 4x with AI upscalers
- Smart model detection with memory-aware recommendations

### 🎬 Video Generation

- Text-to-video with LTX-Video
- Duration presets (1-3 seconds)
- Motion strength control

### 🗣️ Voice Generation

- Text-to-speech with Chatterbox TTS (built-in)
- Expression tags: `[laugh]`, `[sigh]`, `[gasp]`
- Voice cloning from short samples
- BYOM: XTTS, F5-TTS, Bark via ComfyUI

### 🎵 Music Generation

- MusicGen, Stable Audio, AudioCraft support
- Duration presets, style tags
- Melody conditioning

---

## 🚀 Quick Start

```bash
# Clone NeoVak
git clone https://github.com/dabirdwell/neovak.git
cd neovak

# Run (creates venv automatically on first run)
./run.sh
```

Open <http://localhost:7861> in your browser.

### Requirements

- **macOS** with Apple Silicon (Intel works but slower) or **Linux/Windows** with NVIDIA GPU
- **Python 3.10+**
- [**ComfyUI**](https://github.com/comfyanonymous/ComfyUI) installed
- At least one AI model

---

## 📦 Model Setup

NeoVak auto-discovers models from ComfyUI.

TypePathExamples**Image**`ComfyUI/models/checkpoints/`SD 1.5, SDXL, Flux**Video**`ComfyUI/models/checkpoints/`LTX-Video**Upscalers**`ComfyUI/models/upscale_models/`ESRGAN, UltraSharp**Voice**Built-inChatterbox TTS**Music**`ComfyUI/models/audio/`MusicGen

### Starter Models

ModelSizeUse[DreamShaper 8](https://civitai.com/models/4384)2 GBGeneral images[SDXL Lightning](https://huggingface.co/ByteDance/SDXL-Lightning)6.5 GBFast, high quality[LTX-Video 2B](https://huggingface.co/Lightricks/LTX-Video)5 GBText-to-video[4x-UltraSharp](https://openmodeldb.info/models/4x-UltraSharp)67 MBPhoto upscaling

---

## ⚙️ Configuration

Copy `neovak_config.example.json` to `neovak_config.json`:

```json
{
  "comfyui_path": "~/ComfyUI",
  "comfyui_url": "http://127.0.0.1:8188",
  "output_dir": "~/Documents/NeoVak-Output",
  "model_paths": ["~/ComfyUI/models"]
}
```

### Voice Presets

Drop `.wav` files in `voices/` folder:

```
voices/
├── Narrator.wav     → "Narrator" in dropdown
└── Warm.wav         → "Warm" in dropdown
```

---

## 🐛 Troubleshooting

**"ComfyUI not running"** — Use `./start.sh` which auto-starts ComfyUI

**"No models found"** — Add `.safetensors` files to `ComfyUI/models/checkpoints/`

**Black images on Mac** — Start ComfyUI with `python main.py --force-fp32`

**Model memory warning** — Close other apps or use a smaller model

---

## 📁 Project Structure

```
neovak/
├── run.sh                    # Quick launcher
├── start.sh                  # Full launcher (starts ComfyUI too)
├── neovak_ui.py              # Main UI
├── neovak_backend.py         # ComfyUI integration
├── neovak_config.json        # Your config (gitignored)
├── voices/                   # Voice presets
├── output/                   # Generated files
├── workflows/                # ComfyUI templates
└── docs/                     # Documentation
```

---

## 🎨 Design

NeoVak's warm amber aesthetic is inspired by vacuum tube technology from the novel series *Lumina's Whisper*. The retro-futuristic design philosophy: **warm, analog, alive**.

---

## 📄 License

MIT License

---

Built with [NiceGUI](https://nicegui.io) and [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

## Related

- [[Products and Services Canon]]
- [[CHANGELOG]]
- [[NeoVak_Project]]
- [[Foundation Canon]]
- [[SPRINT_ACESTEP]]
- [[SPRINT_ENHANCEMENTS]]
- [[SPRINT_LUMINA_WORLD]]
- [[SPRINT_VIDEO_CHAIN]]
- [[ACESTEP_SETUP]]
