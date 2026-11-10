#!/usr/bin/env python3
"""mflux-upscale-seedvr2, with one fix applied at run time and nothing in the venv changed.

mflux 0.19.1 calls mx.repeat(array, mx.array(counts), axis=0), repeating each row a different
number of times. The MLX installed here only accepts a single whole number for repeats, so every
upscale fails with a TypeError. This replaces mx.repeat with one that also accepts per-row counts,
then runs the normal mflux command with the arguments given.
"""
import sys

import mlx.core as mx

_repeat = mx.repeat


def repeat(array, repeats, axis=None, **kw):
    if not isinstance(repeats, mx.array):
        return _repeat(array, repeats, axis=axis, **kw)
    counts = repeats.tolist()
    if not isinstance(counts, list):
        return _repeat(array, int(counts), axis=axis, **kw)
    if axis is None:
        array, axis = array.reshape(-1), 0
    parts = [_repeat(mx.take(array, mx.array([i]), axis=axis), int(c), axis=axis)
             for i, c in enumerate(counts) if int(c) > 0]
    return mx.concatenate(parts, axis=axis)


mx.repeat = repeat

from mflux.models.seedvr2.cli.seedvr2_upscale import main  # noqa: E402

sys.exit(main())
