#!/usr/bin/env python3
"""Runs MiniMax-Music3 in the mlx-audio venv with one change: the piece may not end early.

mlx_audio.music.generate treats --duration as a ceiling. The model decides for itself when a piece
is over and usually stops after 7 to 13 seconds, however long was asked for. This holds its "end"
token back until --min-seconds, then lets it end on its own, up to --duration. The words travel as
single arguments and nothing here is shell text.
"""
import argparse
import copy
import sys
from pathlib import Path

import mlx.core as mx
from mlx_audio.music.generate import generate_music
from mlx_audio.music.models.minimax_music3 import ar as ar_module
from mlx_audio.music.models.minimax_music3 import minimax_music3 as model_module


def frames_with_a_floor(min_seconds):
    def generate_frame_hiddens(language_model, depth, config, text_ids, max_frames, seed=0):
        floor = min(max_frames, int(min_seconds * config.frame_rate))
        no_end = copy.copy(config)
        object.__setattr__(no_end, "audio_end_token_id", -1)  # no token has this id, so it cannot be sampled
        mx.random.seed(seed)
        key = mx.random.key(seed)
        hidden, cache = ar_module.qwen3_hidden(language_model, language_model.model.embed_tokens(text_ids))
        last_hidden = hidden[:, -1]
        frames = []
        for frame_index in range(max_frames + 1):
            key, subkey = mx.random.split(key)
            result = ar_module.ar_one_frame(language_model, depth, no_end if len(frames) < floor else config,
                                            last_hidden, cache, subkey, emit_frame=frame_index > 0)
            last_hidden, cache = result.last_hidden, result.cache
            if result.ended:
                break
            if frame_index > 0:
                frames.append(result.frame_hidden)
                if len(frames) >= max_frames:
                    break
        if not frames:
            raise ValueError("no audio frames were generated")
        return mx.stack(frames, axis=1)
    return generate_frame_hiddens


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--caption", required=True)
    p.add_argument("--lyrics", required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--min-seconds", type=float, required=True)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.min_seconds > 0:
        model_module.generate_frame_hiddens = frames_with_a_floor(a.min_seconds)
    generate_music(caption=a.caption, lyrics=a.lyrics, model=a.model, duration=a.duration, steps=a.steps,
                   seed=a.seed, output_path=a.output, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
