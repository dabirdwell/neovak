# 📦 Model Download Guide

This guide helps you get the right AI models for NeoVak.

## Quick Start (Minimum Setup)

For basic image generation, you only need **one checkpoint model**:

### Option A: Fast & Small (Recommended for 8GB RAM)
**DreamShaper 8** - 2 GB
- Great for: General images, artistic styles
- Download: [CivitAI](https://civitai.com/api/download/models/128713)
- Place in: `ComfyUI/models/checkpoints/`

### Option B: High Quality (Recommended for 16GB+ RAM)
**SDXL Lightning 4-step** - 6.5 GB
- Great for: High resolution, photorealistic, only 4 steps needed
- Download: [HuggingFace](https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step.safetensors)
- Place in: `ComfyUI/models/checkpoints/`

### Option C: Best Quality + Text Rendering (Recommended for 16GB+ RAM)
**Qwen Image 2.0 FP8** - ~21 GB total (3 files)
- Great for: Professional typography, posters, infographics, multilingual text, 2K images
- See: [Qwen Image 2.0 section](#-qwen-image-20-best-text-rendering) below for download links
- Place in: Multiple ComfyUI model folders (see section below)

---

## Full Model Setup by Tab

### 🖼️ Image Generation

| Model | Size | RAM | Best For | Download |
|-------|------|-----|----------|----------|
| DreamShaper 8 | 2 GB | 8GB+ | Artistic, versatile | [CivitAI](https://civitai.com/api/download/models/128713) |
| SDXL Lightning 4-step | 6.5 GB | 16GB+ | Fast, high quality | [HuggingFace](https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step.safetensors) |
| SDXL Turbo | 6.5 GB | 16GB+ | Real-time, 1-4 steps | [HuggingFace](https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0.safetensors) |
| RealVisXL V4 | 6.5 GB | 16GB+ | Photorealistic | [CivitAI](https://civitai.com/models/139562) |

**Place in:** `ComfyUI/models/checkpoints/`

### 🆕 Qwen Image 2.0 (Best Text Rendering)

Qwen Image 2.0 is a 20B parameter image model with **best-in-class text rendering**. It can generate posters, infographics, comics, and any image requiring professional typography in English, Chinese, Korean, and Japanese.

| Component | Size | Download |
|-----------|------|----------|
| Diffusion Model (FP8) | ~13 GB | [HuggingFace](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors) |
| Text Encoder (FP8) | ~8 GB | [HuggingFace](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors) |
| VAE | ~0.2 GB | [HuggingFace](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors) |
| 4-Step LoRA (optional) | ~0.5 GB | [HuggingFace](https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V1.0.safetensors) |

**File placement:**
- Diffusion model → `ComfyUI/models/diffusion_models/`
- Text encoder → `ComfyUI/models/text_encoders/`
- VAE → `ComfyUI/models/vae/`
- LoRA (optional) → `ComfyUI/models/loras/`

**RAM requirement:** 16GB+ recommended (FP8 quantization). 24GB+ for best quality.

**Tips:**
- Use 20 steps, CFG 2.5, euler sampler for FP8 model
- With 4-step LoRA: 4 steps, CFG 1.0 (much faster, slight quality tradeoff)
- Supports native 2K resolution and all common aspect ratios
- For text-heavy prompts, be specific about layout, font style, and placement

### 🔍 Upscalers (for Image Upscale mode)

| Model | Size | Best For | Download |
|-------|------|----------|----------|
| 4x-UltraSharp | 67 MB | Photos, sharp details | [OpenModelDB](https://openmodeldb.info/models/4x-UltraSharp) |
| 4x-AnimeSharp | 67 MB | Anime, illustrations | [OpenModelDB](https://openmodeldb.info/models/4x-AnimeSharp) |
| RealESRGAN_x4plus | 67 MB | General upscaling | [GitHub](https://github.com/xinntao/Real-ESRGAN/releases) |

**Place in:** `ComfyUI/models/upscale_models/`

### 🎬 Video Generation

| Model | Size | RAM | Notes | Download |
|-------|------|-----|-------|----------|
| LTX-Video 2B | 5 GB | 24GB+ | Text-to-video, Mac compatible | [HuggingFace](https://huggingface.co/Lightricks/LTX-Video) |

**Place in:** `ComfyUI/models/checkpoints/`

⚠️ Video generation requires significant RAM. Works best on M1 Pro/Max/Ultra or M2/M3/M4 with 24GB+.

### 🗣️ Voice Generation

**Built-in:** Chatterbox TTS downloads automatically on first use. No setup required!

For additional TTS models via ComfyUI:

| Model | Size | Notes | Download |
|-------|------|-------|----------|
| XTTS v2 | ~2 GB | Multi-language, voice cloning | Via ComfyUI-XTTS |
| F5-TTS | ~1.5 GB | High quality, natural | Via ComfyUI nodes |

**Place in:** `ComfyUI/models/TTS/` or as directed by ComfyUI custom nodes.

### 🎵 Music Generation

| Model | Size | Notes | Download |
|-------|------|-------|----------|
| MusicGen Small | 1.5 GB | Fast, good quality | Via ComfyUI-AudioCraft |
| MusicGen Medium | 3.5 GB | Better quality | Via ComfyUI-AudioCraft |
| Stable Audio Open | ~2 GB | Sound effects, music | [HuggingFace](https://huggingface.co/stabilityai/stable-audio-open-1.0) |

**Place in:** `ComfyUI/models/audio/` or as directed by ComfyUI custom nodes.

---

## Model Locations Summary

```
ComfyUI/
├── models/
│   ├── checkpoints/          # Image & video models (.safetensors, .ckpt)
│   ├── upscale_models/       # Upscalers (ESRGAN, etc.)
│   ├── TTS/                  # Voice models
│   ├── audio/                # Music models
│   └── vae/                  # VAE models (optional, usually embedded)
```

---

## Tips

### Memory Management

NeoVak shows memory warnings if a model might not fit:
- 🟢 Green = Should work fine
- 🟡 Yellow = Might be tight, close other apps
- 🟠 Orange = Risky, may fail or be slow
- 🔴 Red = Probably won't work

### Model Naming

NeoVak auto-detects model types from names:
- `lightning` → Uses 4 steps, low CFG
- `turbo` → Uses 4-8 steps, low CFG
- `xl` or `sdxl` → Uses SDXL settings
- Other → Standard SD 1.5 settings

### Downloading from CivitAI

1. Find a model you like
2. Click "Download"
3. Choose the `.safetensors` file (not `.ckpt` if available)
4. Move to appropriate folder
5. Restart NeoVak or click "Rescan for models"

### Downloading from HuggingFace

1. Navigate to the model page
2. Go to "Files and versions" tab
3. Download the `.safetensors` file
4. Move to appropriate folder

---

## Troubleshooting

### "No models found"
- Check that files are in `ComfyUI/models/checkpoints/`
- Make sure file extension is `.safetensors` or `.ckpt`
- Click "Rescan for models" in NeoVak

### Model shows but won't load
- Check RAM requirements
- Try starting ComfyUI with `--force-fp32`
- Close other memory-heavy applications

### Which model should I start with?
- 8GB RAM: DreamShaper 8 (2GB)
- 16GB RAM: SDXL Lightning (6.5GB)
- 24GB+ RAM: Any model should work

---

## Model Sources

- **[CivitAI](https://civitai.com)** — Community models, many styles
- **[HuggingFace](https://huggingface.co)** — Official models, research models
- **[OpenModelDB](https://openmodeldb.info)** — Upscaler models


## Related
- [[Products and Services Canon]]
- [[TTS_BACKENDS]]
- [[NEOVAK_PHASE1]]
- [[Foundation Canon]]
- [[Satellite_Signal_Interception_Threat_Model]]

