"""Adapters, one module per engine. Later lanes add a module here and a line in
default_adapters(); the queue, the job record and the clients do not change.

Video is ltx_video.py (ltx-2-mlx, picked by the S2 probe). Animation's first adapter is
motion_anim.py (the show's plates/motion.py and typeset.py). Text is local_text.py (the 9B and 27B
officers; it must never set a fixed max_tokens cap). Still planned: the show's Blender scenes
through the Blender MCP server, and the June render queue at
an earlier render queue outside this repository.
"""
from .base import Adapter, AdapterError, RunContext


def default_adapters(config):
    from .mflux_image import MfluxImage
    from .mlx_speech import MlxSpeech
    from .minimax_music import MinimaxMusic
    from .image_tools import BackgroundCutout, FaceRestore, KontextEdit, SeedvrUpscale
    from .ltx_video import LtxVideo
    from .local_text import LocalText
    from .motion_anim import MotionAnimation
    from .join_sound import JoinSound
    from .timeline import Timeline
    return [MfluxImage(config), MlxSpeech(config), MinimaxMusic(config),
            KontextEdit(config), SeedvrUpscale(config), BackgroundCutout(config), FaceRestore(config),
            LtxVideo(config), MotionAnimation(config), LocalText(config), JoinSound(config), Timeline(config)]


__all__ = ["Adapter", "AdapterError", "RunContext", "default_adapters"]
