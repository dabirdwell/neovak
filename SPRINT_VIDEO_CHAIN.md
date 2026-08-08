# Sprint: NeoVak Video — Chain Generation (Last Frame → First Frame)

**Date:** April 12, 2026
**Scope:** Add video chaining to the video generation panel

---

## Concept

Generate longer, coherent videos by chaining short clips. The last frame of clip N becomes the first frame of clip N+1. Each segment can have its own prompt, enabling storyboarded scene creation while maintaining visual continuity.

## Architecture

### Backend: Frame extraction + I2V chaining

In `neovak_backend.py`, add:

```python
def extract_last_frame(video_path: str, output_path: str = None) -> Optional[str]:
    """Extract the last frame from a video using ffmpeg.
    Returns path to the extracted frame PNG.
    """
    if output_path is None:
        output_path = str(Path(video_path).parent / f"{Path(video_path).stem}_lastframe.png")
    
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.04",   # Seek to 0.04s before end
        "-i", video_path,
        "-frames:v", "1",    # Extract 1 frame
        "-update", "1",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode == 0 and Path(output_path).exists():
        return output_path
    return None


def extract_first_frame(video_path: str, output_path: str = None) -> Optional[str]:
    """Extract the first frame from a video using ffmpeg."""
    if output_path is None:
        output_path = str(Path(video_path).parent / f"{Path(video_path).stem}_firstframe.png")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-frames:v", "1",
        "-update", "1",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode == 0 and Path(output_path).exists():
        return output_path
    return None


def concatenate_videos(video_paths: list, output_path: str = None) -> Optional[str]:
    """Concatenate multiple video files into one using ffmpeg.
    All videos should have the same resolution and framerate.
    """
    if output_path is None:
        ts = int(time.time())
        output_path = str(OUTPUT_DIR / f"neovak_chain_{ts}.mp4")
    
    # Create concat list file
    list_path = str(Path(output_path).parent / "concat_list.txt")
    with open(list_path, 'w') as f:
        for vp in video_paths:
            f.write(f"file '{vp}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    
    # Clean up list file
    Path(list_path).unlink(missing_ok=True)
    
    if result.returncode == 0 and Path(output_path).exists():
        return output_path
    
    # If copy fails (different codecs), try re-encoding
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]
    # Recreate list file
    with open(list_path, 'w') as f:
        for vp in video_paths:
            f.write(f"file '{vp}'\n")
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    Path(list_path).unlink(missing_ok=True)
    
    if result.returncode == 0 and Path(output_path).exists():
        return output_path
    return None


def generate_video_from_image(prompt_text: str, model_name: str, 
                               image_path: str, width: int, height: int,
                               num_frames: int, steps: int, cfg: float, 
                               seed: int, strength: float = 1.0,
                               progress_callback=None) -> tuple[Optional[str], str]:
    """Generate video using an image as the first frame (I2V mode).
    Uses the ltxv_i2v_api.json workflow.
    This is the core function for chain generation — the last frame of the 
    previous clip becomes the image_path input here.
    """
    # Load the I2V workflow
    # Set the image input to image_path
    # Set the LTXVImgToVideoInplace strength parameter
    # Rest is same as generate_video
    # (This function may already exist — verify and update if needed)
```

### Chain Generation Function

```python
def generate_video_chain(
    segments: list[dict],
    model_name: str,
    width: int, height: int,
    num_frames: int, steps: int, cfg: float,
    progress_callback=None
) -> tuple[Optional[str], str]:
    """Generate a chain of video clips, each using the last frame of the previous.
    
    segments: list of dicts, each with:
        - prompt: str (the prompt for this segment)
        - seed: int (-1 for random)
    
    First segment generates text-to-video.
    Subsequent segments generate image-to-video using the last frame.
    All clips are concatenated at the end.
    
    Returns: (final_video_path, status_message)
    """
    clips = []
    last_frame = None
    
    for i, segment in enumerate(segments):
        if progress_callback:
            progress_callback(
                int((i / len(segments)) * 90),
                f"Generating segment {i+1}/{len(segments)}: {segment['prompt'][:40]}..."
            )
        
        if i == 0 and last_frame is None:
            # First segment: text-to-video
            clip_path, status = generate_video(
                segment['prompt'], model_name, width, height,
                num_frames, steps, cfg, segment.get('seed', -1)
            )
        else:
            # Subsequent: image-to-video using last frame
            clip_path, status = generate_video_from_image(
                segment['prompt'], model_name, last_frame,
                width, height, num_frames, steps, cfg,
                segment.get('seed', -1), strength=0.95
            )
        
        if clip_path is None:
            return None, f"Segment {i+1} failed: {status}"
        
        clips.append(clip_path)
        
        # Extract last frame for next segment
        last_frame = extract_last_frame(clip_path)
        if last_frame is None:
            return None, f"Failed to extract last frame from segment {i+1}"
    
    # Concatenate all clips
    if progress_callback:
        progress_callback(92, "Stitching clips together...")
    
    final_path = concatenate_videos(clips)
    if final_path:
        total_dur = len(clips) * (num_frames / 24.0)  # approximate
        return final_path, f"Chain complete: {len(clips)} segments, ~{total_dur:.1f}s total"
    else:
        return None, "Failed to concatenate clips"
```

## UI: Chain Mode in Video Panel

Add a "Chain" mode alongside "Text → Video" and "Image → Video":

### Chain Mode UI Layout:
```
┌─────────────────────────────────────────────────────────────────┐
│  MODE: [Text→Video] [Image→Video] [● Chain]                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  STORYBOARD                                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Segment 1 (text-to-video)                                │   │
│  │ Prompt: [A campfire burning in a dark forest, warm glow] │   │
│  │ Seed: [-1]                                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Segment 2 (last frame → first frame)                     │   │
│  │ Prompt: [Camera slowly pulls back, revealing the trees ] │   │
│  │ Seed: [-1]                                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Segment 3 (last frame → first frame)                     │   │
│  │ Prompt: [An owl takes flight from a branch, moonlight  ] │   │
│  │ Seed: [-1]                                               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [+ Add Segment]  [- Remove Last]                               │
│                                                                  │
│  Segments: 3 | Est. duration: ~6-9s | Frames per segment: [49]  │
│                                                                  │
│  [🎬 Generate Chain]                                             │
│                                                                  │
│  PROGRESS                                                        │
│  Segment 2/3: Camera slowly pulls back...  [████████░░] 60%     │
│                                                                  │
│  OUTPUT                                                          │
│  [video player with concatenated result]                         │
│  Individual clips: [Clip 1 ▶] [Clip 2 ▶] [Clip 3 ▶]           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### UI Behaviors:
1. Start with 2 segments by default (minimum for a chain)
2. "Add Segment" appends a new segment card with empty prompt
3. Each segment card shows:
   - Segment number and mode label ("text-to-video" for first, "last frame → first frame" for rest)
   - Prompt textarea
   - Optional seed input
4. "Generate Chain" button:
   - Disables all inputs
   - Shows per-segment progress
   - Generates sequentially (each segment waits for the previous)
   - On completion: shows the concatenated video in the main player
   - Below the player: individual clips as mini-players
5. After generation, each segment card shows a thumbnail (first frame of that clip)
6. "Re-generate from segment N" — regenerate from segment N onward, keeping earlier clips

### Advanced: Continue from History
When a video is in the history strip, add a "Continue from this" button that:
1. Switches to Chain mode
2. Pre-loads the video as "Segment 0" (existing clip)
3. Extracts its last frame
4. Adds a new empty segment ready for a new prompt
5. Generates only the new segment, then concatenates with the original

This is the "extend any video" pattern — take a completed clip and keep going.

## Implementation Notes

### generate_video_from_image
The existing I2V workflow (ltxv_i2v_api.json) already has all the nodes needed. The backend function `generate_video_from_image` may already exist or may need to be connected to the workflow properly. Key parameters:
- `LTXVImgToVideoInplace` node: set `image` to the loaded image, `strength` controls how rigidly the first frame is matched (0.95 for chains — mostly faithful but allowing slight motion)
- The loaded image must be resized to match the video dimensions

### ffmpeg frame extraction
Use `-sseof -0.04` to get the last frame (seeks to 0.04s before end, which with 24fps videos gives us the actual last frame). Alternative: `-vf "select='eq(n,X)'"` where X is frame count - 1.

### WebM vs MP4
Our current workflows output WebM (VP9). For concatenation, same-codec concat via ffmpeg `-c copy` is fastest. If codecs differ, fall back to re-encode. Final output should be MP4 (H.264) for maximum compatibility.

## Testing
- [ ] extract_last_frame produces a valid PNG from a generated WebM
- [ ] extract_first_frame produces a valid PNG
- [ ] generate_video_from_image works with extracted frame
- [ ] 2-segment chain produces a concatenated video
- [ ] 3+ segment chain works
- [ ] "Continue from this" loads an existing clip and extends it
- [ ] Individual clip players work in the output area
- [ ] Progress shows per-segment updates

Commit message: "feat: video chain generation — last frame to first frame storyboarding"

## Related

- [[LTX2_Video_Generation]]
- [[AI Tools Image Generation]]
- [[SE_Post_Image_Generation_Spec]]
- [[Hero_Video_Prompts_v2]]
- [[First_Video_Opening_Statement]]
