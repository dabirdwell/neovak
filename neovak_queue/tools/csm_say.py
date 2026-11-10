#!/usr/bin/env python3
"""Runs CSM-1B in NeoVak's venv with one change from mlx_audio.tts.generate: voice_match is off.

With it on (the library's default, and not settable from its command line) the model is handed the
sample voice's transcript with the new words added to the end, and is asked to carry on from the
sample's unfinished audio. It therefore starts by finishing the sample's sentence, adding stray words
("that like", "is") or losing the first words of the text. With it off, the sample is a finished turn
and the new words are a turn of their own, so it reads what it was given.
"""
import argparse

from mlx_audio.tts.generate import generate_audio


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--output_path", required=True)
    p.add_argument("--speed", type=float, default=1.0)
    a = p.parse_args()
    generate_audio(text=a.text, model=a.model, voice=None, speed=a.speed, output_path=a.output_path,
                   join_audio=True, voice_match=False, verbose=True)


if __name__ == "__main__":
    main()
