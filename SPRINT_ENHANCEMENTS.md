# Sprint: NeoVak Music Tab — Full Feature Expansion

**Date:** April 12, 2026
**Prerequisites:** SPRINT_ACESTEP.md already completed. ACE-Step server running on port 8001.
**Scope:** 12 enhancements to the music generation system

---

## READ FIRST

- `acestep_client.py` — existing REST client, add new functions here
- `neovak_ui.py` — existing UI, music panel starts at `def music_generation_panel()`
- `neovak_backend.py` — backend config and helpers
- ACE-Step API is at http://localhost:8001
- Test each feature as you build it by importing and calling functions

---

## Feature 1: "Surprise Me" Button

The ACE-Step API has `/create_random_sample` that generates amazing random prompts.

### In `acestep_client.py`, add:
```python
def get_random_sample(url: str, mode: str = "custom_mode") -> dict:
    """POST /create_random_sample — get random song params.
    mode: "simple_mode" (just description) or "custom_mode" (full caption+lyrics+bpm+key+duration)
    Returns dict with caption, lyrics, bpm, duration, keyscale, etc.
    """
    r = requests.post(f"{url}/create_random_sample", 
                      json={"sample_type": mode}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", {})
```

### In `neovak_ui.py` music panel, add a "Surprise Me" button:
- Place it next to the "Expand with AI" button
- On click: call `get_random_sample(ACESTEP_URL, "custom_mode")`
- Fill the caption field with `result["caption"]` or `result["description"]`
- Fill the lyrics field with `result["lyrics"]` if present
- Set duration from `result["duration"]` if present
- Show a fun notification: "Rolling the dice..." then "Got it! {genre} in {key}"
- Style: make it visually distinct — amber/gold color, dice icon or sparkle

---

## Feature 2: Song Structure Templates

### In `neovak_backend.py`, add:
```python
SONG_STRUCTURE_TEMPLATES = {
    "Pop Song": "[Verse 1]\n(Your verse here)\n\n[Chorus]\n(Your chorus here)\n\n[Verse 2]\n(Second verse)\n\n[Chorus]\n(Chorus repeat)\n\n[Bridge]\n(Bridge section)\n\n[Chorus]\n(Final chorus)",
    "Ballad": "[Intro]\n(Gentle intro)\n\n[Verse 1]\n(Set the scene)\n\n[Verse 2]\n(Deepen the story)\n\n[Chorus]\n(Emotional peak)\n\n[Verse 3]\n(Resolution)\n\n[Chorus]\n(Final chorus)\n\n[Outro]\n(Fade out)",
    "Lo-fi Loop": "[Loop]\n(Repeating phrase or melody)\n\n[Variation]\n(Slight change)\n\n[Loop]\n(Return to main phrase)",
    "Epic Anthem": "[Intro]\n(Building atmosphere)\n\n[Verse 1]\n(Call to action)\n\n[Pre-Chorus]\n(Building tension)\n\n[Chorus]\n(Anthemic hook)\n\n[Verse 2]\n(Raise the stakes)\n\n[Pre-Chorus]\n(Building again)\n\n[Chorus]\n(Bigger this time)\n\n[Bridge]\n(Breakdown / spoken word)\n\n[Final Chorus]\n(Everything at once)\n\n[Outro]\n(Triumphant close)",
    "Spoken Word": "[Intro]\n(Setting / ambient sound)\n\n[Part 1]\n(Opening thought)\n\n[Part 2]\n(Development)\n\n[Part 3]\n(Climax)\n\n[Outro]\n(Reflection)",
    "Instrumental": "[Instrumental]",
    "Hip-Hop": "[Intro]\n(Beat drop)\n\n[Verse 1]\n(16 bars)\n\n[Hook]\n(Catchy hook)\n\n[Verse 2]\n(16 bars)\n\n[Hook]\n(Hook repeat)\n\n[Bridge]\n(Switch up)\n\n[Verse 3]\n(Final verse)\n\n[Hook]\n(Outro hook)",
}
```

### In `neovak_ui.py` music panel:
- Add a row of template buttons below the lyrics textarea
- Label: "TEMPLATES" with small buttons for each template name
- On click: replace lyrics textarea content with the template
- Ask confirmation if lyrics field is not empty: ui.notify with "Replace current lyrics?" or just replace

---

## Feature 3: Cover Mode

ACE-Step supports the "cover" task type — upload audio + new style tags.

### In `acestep_client.py`, add:
```python
def generate_cover(
    url: str,
    audio_path: str,
    caption: str,
    lyrics: str = "",
    duration: int = 0,  # 0 = match source duration
    seed: int = -1,
    thinking: bool = True,
    infer_step: int = 30,
    guidance_scale: float = 15.0,
    progress_callback=None,
) -> tuple[Optional[str], str]:
    """Generate a cover version of an existing song with new style.
    Upload the source audio and provide new style tags.
    """
    # Read audio file as base64 for the API
    import base64
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()
    
    payload = {
        "caption": caption,
        "lyrics": lyrics,
        "duration": duration if duration > 0 else 0,
        "infer_step": infer_step,
        "guidance_scale": guidance_scale,
        "seed": seed,
        "batch_size": 1,
        "thinking": thinking,
        "task_type": "cover",
        "audio_data": audio_b64,
    }
    
    # Submit and poll same as generate_music
    # ... (reuse the submit/poll/download pattern from generate_music)
```

Note: Check the actual ACE-Step API docs for the correct field names for audio upload in cover mode. The API might use `audio_path` pointing to a server-local file, or accept base64. Test with:
```bash
curl -s http://localhost:8001/openapi.json | python3 -c "import sys,json; s=json.load(sys.stdin); print(json.dumps(s['paths'].get('/release_task',{}), indent=2))" 2>/dev/null | head -60
```

### In `neovak_ui.py` music panel:
- Add a MODE toggle at the top: "Create" vs "Cover"
- In Cover mode, show:
  - File upload area for source audio (drag-drop or click)
  - Style tags input (same as Create mode)
  - Optional lyrics override
  - Generate button → calls generate_cover
- When switching modes, show/hide appropriate UI elements

---

## Feature 4: Seed Explorer ("Lucky 4")

### In `acestep_client.py`, add:
```python
def generate_music_batch(
    url: str,
    caption: str,
    lyrics: str = "",
    duration: int = 120,
    batch_size: int = 4,
    thinking: bool = True,
    infer_step: int = 30,
    guidance_scale: float = 15.0,
    progress_callback=None,
) -> list[tuple[Optional[str], str, dict]]:
    """Generate multiple variations with different seeds.
    Returns list of (output_path, status_msg, metadata) tuples.
    """
    # Same as generate_music but with batch_size=4
    # The result_list will have multiple entries
    # Download each one separately
    # Return all results
```

### In `neovak_ui.py` music panel:
- Add a "Lucky 4" button next to "Generate Music"
- On click: generates with batch_size=4
- Shows a 2x2 grid of mini audio players
- Each cell has: play button, seed number, "Use This" button
- "Use This" loads that track into the main player and copies the seed to the seed field
- Style: compact cards with the seed as a label

---

## Feature 5: LM Model Switcher

### In `acestep_client.py`, add:
```python
def get_model_inventory(url: str) -> dict:
    """GET /v1/model_inventory — available DiT and LM models."""
    r = requests.get(f"{url}/v1/model_inventory", timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})

def switch_lm_model(url: str, lm_model: str) -> bool:
    """Switch the active LM model. Larger = smarter planning, slower."""
    # Use /v1/reinitialize or pass lm_model in generate request
    pass
```

### In `neovak_ui.py` music panel:
- In Advanced Settings, add an "LM Quality" selector
- Options based on available models: "Fast (0.6B)" / "Standard (1.7B)" / "Premium (4B)"
- Pass the selected lm_model name in the generate call
- Show a tooltip: "Larger models produce better song structures but take longer"

---

## Feature 6: MP3 Metadata Embedding

### In `acestep_client.py`, after downloading the audio file:
```python
def embed_metadata(filepath: str, caption: str, lyrics: str, 
                   seed: str, bpm: int, key: str, duration: float,
                   model: str = "", lm_model: str = ""):
    """Embed generation metadata into MP3 ID3 tags."""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TALB, TPE1, COMM, TKEY, TBPM, USLT
    except ImportError:
        return  # mutagen not installed, skip silently
    
    audio = MP3(filepath, ID3=ID3)
    try:
        audio.add_tags()
    except:
        pass
    
    audio.tags.add(TIT2(encoding=3, text=caption[:60]))
    audio.tags.add(TALB(encoding=3, text="NeoVak Generated"))
    audio.tags.add(TPE1(encoding=3, text="NeoVak + ACE-Step 1.5"))
    audio.tags.add(TBPM(encoding=3, text=str(bpm)))
    audio.tags.add(TKEY(encoding=3, text=key))
    if lyrics:
        audio.tags.add(USLT(encoding=3, lang='eng', desc='Lyrics', text=lyrics))
    audio.tags.add(COMM(encoding=3, lang='eng', desc='NeoVak',
        text=f"seed={seed} model={model} lm={lm_model} duration={duration}s"))
    audio.save()
```

Call `embed_metadata()` right after saving the downloaded MP3 in `generate_music()`.

Add `mutagen` to requirements.txt.

---

## Feature 7: Smart Duration from Lyrics

### In `neovak_backend.py`, add:
```python
def estimate_duration_from_lyrics(lyrics: str) -> int:
    """Estimate song duration from lyrics content.
    Rough heuristic: ~3 seconds per lyric line, 
    +15s for each instrumental/intro/outro marker.
    """
    if not lyrics.strip():
        return 120  # default 2 min for instrumental
    
    lines = [l.strip() for l in lyrics.split('\n') if l.strip()]
    lyric_lines = [l for l in lines if not l.startswith('[')]
    marker_lines = [l for l in lines if l.startswith('[')]
    
    # Count instrumental markers
    instrumental_markers = sum(1 for m in marker_lines 
        if any(x in m.lower() for x in ['intro', 'outro', 'instrumental', 'solo', 'break']))
    
    estimated = (len(lyric_lines) * 3) + (instrumental_markers * 15) + 10  # +10 buffer
    # Clamp to reasonable range
    return max(15, min(600, estimated))
```

### In `neovak_ui.py`:
- When lyrics change (on blur/defocus of lyrics textarea), calculate estimated duration
- Show it as a subtle hint: "Estimated: ~3:15" below the lyrics field
- Add a "Use estimate" link that sets the duration to the estimated value

---

## Feature 8: Mood Compass

### In `neovak_backend.py`, add:
```python
MOOD_COMPASS = {
    # (energy, valence) -> style tags
    # energy: 0=calm, 1=intense
    # valence: 0=dark, 1=bright
    (0.0, 0.0): "dark ambient, drone, minimal, haunting",
    (0.0, 0.5): "ambient, lo-fi, chill, mellow, soft",
    (0.0, 1.0): "peaceful, acoustic, warm, gentle, lullaby",
    (0.5, 0.0): "melancholic, indie, minor key, introspective",
    (0.5, 0.5): "indie pop, mid-tempo, thoughtful, breezy",
    (0.5, 1.0): "folk, acoustic, uplifting, hopeful, warm",
    (1.0, 0.0): "metal, aggressive, dark, intense, heavy",
    (1.0, 0.5): "rock, energetic, driving, powerful",
    (1.0, 1.0): "dance, euphoric, upbeat, festival, bright synths",
}

def mood_to_tags(energy: float, valence: float) -> str:
    """Convert mood compass position to style tags using nearest neighbor."""
    best_dist = float('inf')
    best_tags = ""
    for (e, v), tags in MOOD_COMPASS.items():
        dist = (energy - e)**2 + (valence - v)**2
        if dist < best_dist:
            best_dist = dist
            best_tags = tags
    return best_tags
```

### In `neovak_ui.py` music panel:
- Add a visual mood selector using a 2D grid/compass
- Implementation: a 200x200px HTML canvas or grid of clickable cells
- X-axis: Energy (Calm → Intense), Y-axis: Valence (Dark → Bright)
- Labels at corners: "Dark & Calm" (bottom-left), "Bright & Intense" (top-right)
- On click: calculate (energy, valence) from position, get tags, fill caption field
- Visual: gradient background hinting at mood (cool blues bottom-left, warm oranges top-right)
- Use NiceGUI's ui.html() or ui.element() for the interactive grid

Alternative simpler approach: a 3x3 grid of mood buttons:
```
[Peaceful]  [Hopeful]   [Euphoric]
[Chill]     [Balanced]  [Energetic]  
[Haunting]  [Moody]     [Aggressive]
```
Each button fills style tags. This is simpler and still effective.

---

## Feature 9: Voice + Music Cross-Tab Pipeline

This is the most complex feature. It connects the Music and Voice tabs.

### In `neovak_backend.py`, add:
```python
def mix_audio(music_path: str, voice_path: str, 
              music_volume: float = 0.3,
              voice_volume: float = 1.0,
              output_path: str = None) -> Optional[str]:
    """Mix a music track with a voice track using ffmpeg.
    music_volume: 0.0-1.0, how loud the music is
    voice_volume: 0.0-1.0, how loud the voice is
    """
    if output_path is None:
        ts = int(time.time())
        output_path = str(OUTPUT_DIR / f"neovak_mix_{ts}.mp3")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", music_path,
        "-i", voice_path,
        "-filter_complex",
        f"[0:a]volume={music_volume}[music];[1:a]volume={voice_volume}[voice];[music][voice]amix=inputs=2:duration=longest",
        "-ac", "2",
        "-ar", "48000",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode == 0 and Path(output_path).exists():
        return output_path
    return None
```

### In `neovak_ui.py`:
- On the music output card, add a "Add Voiceover" button
- Clicking it opens a mini voice panel inline (or navigates to Voice tab with the music path stored)
- After voice generation, offer "Mix" with a volume slider for music (default 30%) and voice (default 100%)
- "Mix" calls mix_audio and plays the result
- The mixed file goes to history

Simpler alternative: Just add a "Mix with Voice" section below the music output:
- Drag-drop or select a voice file
- Music volume slider (0-100%, default 30%)
- Voice volume slider (0-100%, default 100%)
- "Mix" button → creates mixed file → plays it

---

## Feature 10: Image → Album Art

### In `acestep_client.py`, add:
```python
def embed_album_art(mp3_path: str, image_path: str):
    """Embed album art image into MP3 file."""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, APIC
    except ImportError:
        return False
    
    audio = MP3(mp3_path, ID3=ID3)
    try:
        audio.add_tags()
    except:
        pass
    
    with open(image_path, 'rb') as f:
        img_data = f.read()
    
    mime = 'image/png' if image_path.endswith('.png') else 'image/jpeg'
    audio.tags.add(APIC(
        encoding=3, mime=mime, type=3,  # 3 = Cover (front)
        desc='Cover', data=img_data
    ))
    audio.save()
    return True
```

### In `neovak_ui.py` music output card:
- Add "Create Album Art" button
- On click: take the current caption/style tags, generate a prompt like:
  "Album cover art, {caption}, abstract, artistic, high contrast"
- If Image tab has a generate function accessible, call it
- Or: open a small dialog with the generated prompt and a "Generate" button that uses the image generation backend
- After image is generated, call embed_album_art to put it in the MP3
- Show the album art as a thumbnail on the output card

Simpler approach: just add "Upload Cover Art" — user can drag-drop an image, and it gets embedded in the MP3. This is useful even without auto-generation.

---

## Feature 11: LoRA Management UI

### In `acestep_client.py`, add:
```python
def get_lora_status(url: str) -> dict:
    """GET /v1/lora/status — current LoRA state."""
    r = requests.get(f"{url}/v1/lora/status", timeout=5)
    r.raise_for_status()
    return r.json().get("data", {})

def load_lora(url: str, lora_path: str, scale: float = 1.0) -> bool:
    """POST /v1/lora/load — load a LoRA adapter."""
    r = requests.post(f"{url}/v1/lora/load", 
                      json={"lora_path": lora_path, "scale": scale}, timeout=30)
    return r.status_code == 200

def unload_lora(url: str) -> bool:
    """POST /v1/lora/unload — unload current LoRA."""
    r = requests.post(f"{url}/v1/lora/unload", json={}, timeout=10)
    return r.status_code == 200

def set_lora_scale(url: str, scale: float) -> bool:
    """POST /v1/lora/scale — adjust LoRA influence."""
    r = requests.post(f"{url}/v1/lora/scale", json={"scale": scale}, timeout=5)
    return r.status_code == 200

def toggle_lora(url: str, enabled: bool) -> bool:
    """POST /v1/lora/toggle — enable/disable LoRA without unloading."""
    r = requests.post(f"{url}/v1/lora/toggle", json={"use_lora": enabled}, timeout=5)
    return r.status_code == 200
```

### In `neovak_ui.py` Advanced Settings:
- Add "LoRA" section with:
  - File path input for LoRA safetensors
  - "Load" / "Unload" buttons
  - Scale slider (0.0 - 2.0, default 1.0)
  - On/Off toggle
  - Status indicator showing current LoRA state

---

## Feature 12: Repaint Mode

ACE-Step supports "repaint" — replace a section of audio.

### In `acestep_client.py`, add:
```python
def repaint_section(
    url: str,
    audio_path: str,
    caption: str,
    lyrics: str = "",
    repaint_start: float = 0.0,  # seconds
    repaint_end: float = 0.0,    # seconds (0 = end of track)
    seed: int = -1,
    infer_step: int = 30,
    guidance_scale: float = 15.0,
    progress_callback=None,
) -> tuple[Optional[str], str]:
    """Repaint a section of existing audio with new content.
    Keep everything outside [repaint_start, repaint_end] and regenerate the section.
    """
    # Similar to generate_music but with task_type="repaint" and audio file
    # Need to pass audio as file path or base64
```

### In `neovak_ui.py`:
- In Cover mode or as a third mode ("Create" / "Cover" / "Repaint")
- Repaint mode shows:
  - Source audio upload + player
  - Start time / End time inputs (seconds)
  - New style tags for the section
  - Generate button
- This enables iterative composition: generate a track, repaint the weak section

---

## Implementation Order

Build in this order (each builds on the previous):
1. Features 1, 2 (Surprise Me + Templates) — instant wins, no API complexity
2. Feature 6 (MP3 Metadata) — small, adds value to everything
3. Feature 7 (Smart Duration) — small helper
4. Feature 8 (Mood Compass) — use the 3x3 grid approach
5. Feature 5 (LM Model Switcher) — quick Advanced Settings addition  
6. Feature 4 (Seed Explorer) — batch generation
7. Feature 3 (Cover Mode) — requires audio upload UI
8. Feature 12 (Repaint) — similar to Cover
9. Feature 11 (LoRA) — power user feature
10. Feature 10 (Album Art) — nice-to-have
11. Feature 9 (Voice + Music Mixer) — cross-tab, most complex

## Testing

After building all features, verify:
- [ ] "Surprise Me" fills fields and generates
- [ ] All 7 song templates fill lyrics correctly
- [ ] MP3 files have embedded metadata (check with: `python3 -c "from mutagen.mp3 import MP3; print(MP3('output/music/test.mp3').tags.pprint())"`)
- [ ] Smart duration estimate appears when lyrics change
- [ ] Mood grid buttons fill style tags
- [ ] LM model selector passes model name to API
- [ ] Seed Explorer generates 4 variations
- [ ] Cover mode accepts audio upload
- [ ] LoRA controls work (load/unload/toggle/scale)
- [ ] Mix audio produces combined file

## Dependencies

Add to requirements.txt:
```
mutagen>=1.47.0
```

Install in the NeoVak venv:
```bash
cd /Users/david/Documents/Fawkes/Products\ and\ Services/NeoVak
source venv/bin/activate
pip install mutagen
```

Commit message: "feat: music tab full feature expansion — surprise me, templates, cover mode, seed explorer, mood compass, metadata, mixer, LoRA UI"

## Related

- [[SPRINT_VIDEO_CHAIN]]
- [[SPRINT_ACESTEP]]
- [[SPRINT_LUMINA_WORLD]]
- [[Show_Style_Influences]]
- [[The_Forty_Second_Sprint]]
