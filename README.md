# NeoVak

NeoVak makes pictures, short video clips, voices, music, animations and writing on your own Mac, with models that run on the Mac itself. Nothing you make leaves the machine. There is no account, no cloud and no key to paste in. If you have the models on disk, it works with the network off.

Fun, useful, local, yours.

## What you need

- A Mac with Apple Silicon (M1 or later). Nothing else is supported. 32 GB of memory is enough for the smaller picture and voice models; the larger picture models want 48 GB or more free. The Models page tells you what fits as you go.
- macOS 14 or later, with Homebrew.
- Python 3.11 or later (`brew install python@3.13`) and ffmpeg (`brew install ffmpeg`).
- Disk space for the models you choose. They are not included. The sizes are below.

## Setup, one command

```
git clone <this repository> neovak
cd neovak
./setup.sh
```

setup.sh checks the Mac, makes NeoVak's own Python environment in `venv/`, installs the Python packages for the picture and voice lanes, writes an example settings file to `~/.config/neovak/settings.toml` if you have none, and then runs the doctor.

## The doctor comes first

```
venv/bin/python3 -m neovak_queue.doctor
```

The doctor prints, lane by lane, what this Mac has and what it is missing, with a plain line for each missing thing saying what it is for. Read it before anything else. A lane the doctor marks as switched off is switched off on the screen too, for the same reason, so nothing pretends to work.

The doctor does not download anything, load any model, or send anything off the machine.

## Tell NeoVak where things are

Open `~/.config/neovak/settings.toml`. The one line most people change is the models folder:

```
[models]
mflux = "~/.cache"      # its huggingface subfolder is where picture and voice weights live
```

Everything about your machine is in that one file: where finished work goes, where models are, the paths of the optional tools for video, music and face repair, how memory is checked, and which addresses the engine and the screen answer to. `venv/bin/python3 -m neovak_queue.settings` prints every value in use and where it came from.

## Getting models

Weights are not in this repository and NeoVak never fetches them on its own while it is making things. Fetch the ones you want once, while you are online, into the Hugging Face cache under your models folder:

```
HF_HOME=~/.cache/huggingface venv/bin/hf download Tongyi-MAI/Z-Image-Turbo
```

Replace the path with your own `[models] mflux` folder plus `/huggingface`. Then run the doctor again. A few of the models are gated on Hugging Face: you accept their terms on the model's page, sign in once with `venv/bin/hf auth login`, and fetch. NeoVak itself never needs that sign-in, and never reads the token.

The Models page in the screen can also add a small voice (Soprano, 0.22 GB) with one press when the Mac is online.

## The models, and their licences

These are the licence tags as the Hugging Face model pages listed them on Nov 9 2026. The tag is a summary, not the licence. Read the full text on the model's page before you use a model for anything beyond your own work, especially the ones marked non-commercial.

| Lane | Name on the screen | Model | About | Licence tag |
|---|---|---|---|---|
| Pictures | Quick | black-forest-labs/FLUX.2-klein-4B | 16 GB | Apache 2.0 |
| Pictures | Polished | Tongyi-MAI/Z-Image-Turbo | 33 GB | Apache 2.0 |
| Pictures | Careful | Tongyi-MAI/Z-Image | 20 GB | Apache 2.0 |
| Pictures | Fast draft | black-forest-labs/FLUX.1-schnell | 58 GB | Apache 2.0, gated |
| Pictures | Highest detail | black-forest-labs/FLUX.1-dev | 34 GB | FLUX.1 dev non-commercial licence, gated |
| Pictures | Photo look | black-forest-labs/FLUX.1-Krea-dev | 34 GB | FLUX.1 dev non-commercial licence, gated |
| Pictures | Precise | briaai/FIBO | 26 GB | Bria FIBO licence (CC BY-NC 4.0), gated |
| Pictures | Words in pictures | Qwen/Qwen-Image | 58 GB | Apache 2.0 |
| Voices | Clear narrator | mlx-community/Kokoro-82M-bf16 | 0.4 GB | Apache 2.0 |
| Voices | Conversational | mlx-community/csm-1b | 6 GB | Apache 2.0 |
| Voices | Expressive | mlx-community/chatterbox-fp16 | 3 GB | Apache 2.0 |
| Voices | Described voice | Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign | 5 GB | Apache 2.0 |
| Voices | Quick and light | mlx-community/Soprano-80M-bf16 | 0.2 GB | Apache 2.0 |
| Music | Music | mlx-community/MiniMax-Music3-4bit | 9 GB | MiniMax Music3 community licence |
| Picture tools | Change something | black-forest-labs/FLUX.1-Kontext-dev | 34 GB | FLUX.1 dev non-commercial licence, gated |
| Picture tools | Make it bigger | numz/SeedVR2_comfyUI | 7 GB | Apache 2.0 |
| Picture tools | Repair faces | GFPGAN v1.4 weights, in a separate environment | 0.3 GB | Apache 2.0, with third-party parts under their own terms |
| Video | Best clip, Lighter on memory | LTX-2 packs for ltx-2-mlx, in a separate environment | 20 to 30 GB | LTX-2 community licence agreement |

The engines are open source: mflux (MIT), mlx-audio (MIT), MLX (MIT), ffmpeg (LGPL or GPL depending on the build). The video engine, ltx-2-mlx, has its own repository and licence; read it there. Video, music and face repair run from their own Python environments that you set up separately and name in the settings file; the doctor says whether they are there.

Nothing in this repository is a model, and no model is redistributed here.

## Starting it

```
./run_rest.sh                # the engine, on 127.0.0.1:8100, in this window
people_screen/start.sh       # the screen, on 127.0.0.1:8102
```

The screen asks for a passcode, and none exists until you make one. Make one per person:

```
cd people_screen && ../venv/bin/python3 people.py add "Your name"
```

It prints the passcode once and keeps only a scrambled form of it. `people.py list` shows who has one, and `people.py remove "Your name"` takes it away and signs that person out everywhere.

Open http://127.0.0.1:8102, type the passcode (capitals and spaces do not matter), press a picture on the opening wall, press Generate, and watch it arrive. You stay signed in on that device for 30 days.

To reach the screen from a phone or another computer on your own private network, add that address under `[hosts]` in the settings file. Everyone who reaches it still needs a passcode, but open it only on a network you control.

## What it does on your machine, and what it does not

- Every job goes through one line, one at a time, and asks the memory check before any model loads. When something will not fit, the screen says how much is short and what would run instead.
- It runs offline while making things. A missing model is reported in one plain sentence, and nothing starts a download.
- It never runs shell text built from what you type; every outside program is started from an argument list.
- Files are served only from the output folder, with a check against paths that try to leave it.
- Nothing phones home. There is no telemetry, no update check and no analytics.

## Tests

```
venv/bin/python3 -m unittest discover tests
venv/bin/python3 people_screen/test_people_screen.py
```

They use temporary folders and stand-in engines. No models are loaded.

## Chat tools

`venv/bin/python3 setup.py` adds NeoVak's tools to Claude Desktop, pointing at this folder. The tools send work to the running engine and never load a model themselves.

## Licence for this code

MIT, in the file LICENSE. You may use, change and share this code, in your own projects too, as long as you keep the copyright notice and the licence text with it. The licence covers this code only. Each model has its own licence, listed above.
