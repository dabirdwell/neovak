# Sprint: NeoVak — Lumina's World (Cross-Tab Enhancement + Unified Theme)

**Date:** April 12, 2026  
**Prerequisites:** Previous sprints completed. ACE-Step running on port 8001.  
**Scope:** Enhance all media tabs + enforce cohesive Lumina's Whisper design language

---

## READ FIRST

- `neovak_ui.py` — all panels, CSS starts at CUSTOM_CSS variable (~line 126)
- `neovak_backend.py` — backend helpers, generation functions
- `VISION.md` — "NeoVak's aesthetic is inspired by vacuum tube technology from Lumina's Whisper — warm amber glows, analog indicators, retro-futuristic controls. The philosophy: warm, analog, alive."
- The existing CSS already has Edison tungsten palette (--accent: #d4912a, copper, brass, patina). BUILD ON THIS, don't replace it.

---

## PART 1: LUMINA DESIGN SYSTEM (CSS + Theme Cohesion)

### 1A. Hexagonal Elements

The hexagonal lattice is Lumina's fundamental geometry. Introduce hexagonal motifs:

**In CUSTOM_CSS, add:**
```css
/* Hexagonal progress indicator - replaces linear progress during generation */
.neovak-hex-progress {
    background: repeating-linear-gradient(
        60deg,
        var(--surface-2) 0px,
        var(--surface-2) 10px,
        var(--surface-3) 10px,
        var(--surface-3) 20px
    );
    border-radius: 4px;
    overflow: hidden;
    height: 6px;
}
.neovak-hex-progress .bar {
    height: 100%;
    background: linear-gradient(90deg, var(--tube-warm), var(--tube-hot), var(--filament-bright));
    transition: width 0.3s ease;
}

/* Tube warming animation for generation states */
@keyframes tube-warmup {
    0% { background-color: var(--tube-cold); }
    30% { background-color: var(--tube-warm); }
    60% { background-color: var(--tube-hot); }
    100% { background-color: var(--filament-bright); }
}
.neovak-warming { animation: tube-warmup 2s ease forwards; }

/* Whisper pulse - subtle ambient presence indicator when backend is connected */
@keyframes whisper-pulse {
    0%, 100% { opacity: 0.6; transform: scale(1); }
    50% { opacity: 1.0; transform: scale(1.15); }
}
.neovak-whisper-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--tube-warm);
    animation: whisper-pulse 3s ease-in-out infinite;
    display: inline-block;
}

/* Foam animation for loading/processing states */
@keyframes foam-drift {
    0% { background-position: 0% 0%; }
    100% { background-position: 100% 100%; }
}
.neovak-foam-loading {
    background: radial-gradient(circle at 20% 50%, var(--accent-muted) 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, var(--accent-muted) 0%, transparent 50%),
                radial-gradient(circle at 50% 80%, var(--accent-muted) 0%, transparent 50%);
    background-size: 200% 200%;
    animation: foam-drift 4s ease-in-out infinite;
}
```

### 1B. Status Indicators — The Whisper

Replace all green circle status indicators with the "whisper dot" — a warm amber pulse that suggests presence rather than just connectivity. When a backend is connected (ComfyUI, ACE-Step, voice models), show the whisper pulse. When disconnected, show a cold dark dot (--tube-cold).

**Apply across ALL tabs:**
- Image tab: ComfyUI status → whisper dot
- Video tab: ComfyUI status → whisper dot
- Music tab: ACE-Step status → whisper dot (already has status bar, upgrade the icon)
- Voice tab: Model loaded status → whisper dot
- SFX tab: AudioGen status → whisper dot

### 1C. Tab Header Consistency

Each tab currently uses emoji (🗣️, 🔊, 🎵). Replace with a unified pattern:

```python
# Each tab gets a Lumina-world subtitle
TAB_SUBTITLES = {
    "image": "Paint with light",
    "video": "Set time in motion", 
    "voice": "Give breath to words",
    "music": "Compose from nothing",
    "sfx": "Shape the air",
}
```

Remove emoji from titles. Use clean text: "Image Generation", "Video Generation", etc.
Below each title, show the Lumina-style subtitle in --text-muted italic.

### 1D. Generation States — Tube Warming

When a generation starts, the Generate button should:
1. Change text from "Create" to "Warming tubes..." briefly
2. Then show a progress state with the hex progress bar
3. On completion: brief flash of --filament-bright, then show result

This applies to ALL tabs' generate buttons.

---

## PART 2: IMAGE TAB ENHANCEMENTS

The image tab is the most mature (541 lines). Add:

### 2A. "Surprise Me" for Images
Same pattern as music — a button that generates a random creative prompt.

In `neovak_backend.py`, add:
```python
IMAGE_SURPRISE_PROMPTS = [
    "A cozy bookshop at twilight with warm amber light spilling from hexagonal windows",
    "An octopus librarian organizing books on coral shelves, deep sea bioluminescence",
    "A steampunk observatory with brass telescopes and copper piping, warm tungsten glow",
    "A grandmother's kitchen where the pots and pans float in mid-air, morning light",
    "A fox wearing a tiny backpack walking through an autumn forest, golden hour",
    "An abandoned space station overgrown with glowing plants, zero gravity flowers",
    "A midnight jazz bar where the instruments play themselves, blue and amber smoke",
    "A lighthouse keeper's desk covered in maps and mechanical insects, candlelight",
    "A paper airplane flying over a miniature city made of old books, afternoon light",
    "An underwater tea party with jellyfish lanterns and seahorse waiters",
    "A clockwork bird perched on a wire above a rainy street, copper and glass",
    "A child discovering a door in a tree trunk that opens to a starfield",
    "A mechanical garden where flowers are made of brass gears and crystal petals",
    "An old radio that plays colors instead of sound, warm vacuum tube glow",
    "A cat sleeping on a stack of letters in a post office from the future",
]

import random
def get_random_image_prompt() -> str:
    return random.choice(IMAGE_SURPRISE_PROMPTS)
```

Add a "Surprise Me" button next to the enhance button in the image command bar.

### 2B. Style Presets for Images
Like the mood compass for music — quick style shortcuts:

```python
IMAGE_STYLE_PRESETS = {
    "Cinematic": "cinematic lighting, dramatic, volumetric fog, anamorphic lens flare",
    "Analog Photo": "35mm film grain, warm tones, soft focus, vintage photography",
    "Watercolor": "watercolor painting, soft edges, paper texture, loose brushstrokes",
    "Neon Noir": "neon lights, rain, dark alley, cyberpunk, reflective wet surfaces",
    "Studio Ghibli": "anime style, lush scenery, whimsical, soft colors, hand-drawn feel",
    "Golden Hour": "golden hour sunlight, warm glow, long shadows, soft atmosphere",
    "Lumina": "warm amber glow, vacuum tube technology, hexagonal lattice, brass and copper, retro-futuristic",
}
```

Show as clickable chips that APPEND to the prompt (don't replace).
Note: Include a "Lumina" style preset that generates images in the NeoVak aesthetic.

### 2C. Image History with Thumbnails
The image panel has a history strip area but verify it shows actual thumbnails.
Each history item should show: thumbnail, seed, prompt preview on hover.
Add "Re-generate" (same seed + prompt) and "Vary" (same prompt, new seed) quick actions.

### 2D. Cross-Tab: "Animate This" Button
On the image output, add an "Animate" button that:
- Takes the current generated image
- Switches to the Video tab
- Pre-loads the image as the first frame for Image→Video mode
- This is the Image→Video pipeline that's in the design doc but may not be wired up

---

## PART 3: VIDEO TAB ENHANCEMENTS

The video tab is 225 lines — the shortest content panel. Needs the most work.

### 3A. Image-to-Video Mode
If not already implemented, add mode toggle: "Text → Video" / "Image → Video"
In I2V mode:
- Show image upload area
- Strength slider (how much the image influences the video)
- Motion prompt (what should happen)
- Uses the ltxv_i2v_api.json workflow

### 3B. Video History Gallery
Like the music history but with video thumbnails (first frame).
Each entry shows: thumbnail, duration, prompt preview on hover.
Clicking loads into the main player.

### 3C. "Surprise Me" for Video
Random motion prompts:
```python
VIDEO_SURPRISE_PROMPTS = [
    "Clouds forming and dissolving over a mountain peak, time-lapse, golden hour",
    "A candle flame dancing in slow motion, warm amber light against dark background",
    "Rain drops falling in slow motion on a copper surface, macro, beautiful reflections",
    "Northern lights flowing across a starry sky, gentle motion, vivid greens and purples",
    "A flower blooming in time-lapse, soft natural light, delicate petals unfolding",
    "Waves gently lapping on a moonlit shore, serene, slow motion, silver light",
    "Embers drifting upward from a campfire, dark background, warm amber particles",
    "A hummingbird hovering at a flower, iridescent feathers, slow motion, bokeh",
]
```

### 3D. Loop Toggle
Add a "Make Loop" toggle that, after generation, attempts to create a seamless loop.
For quick implementation: just set the video player to loop mode.
For better: add post-processing that blends the last frames into the first.

---

## PART 4: VOICE TAB ENHANCEMENTS

Voice tab is 140 lines — very bare.

### 4A. Voice Presets Gallery
Show pre-built voice presets from the `voices/` directory as a visual gallery:
```python
# In voice panel, show available voice presets as cards
voice_presets = get_voice_presets()  # already exists in backend
# Display as: [Default] [Narrator] [Warm] [Dramatic] etc.
# Each one is a .wav file in voices/ directory
```

### 4B. Emotion Slider (Quality Mode)
The Chatterbox "quality" mode accepts an `emotion` parameter (0-1).
Add a slider labeled "Expression Level" that maps to this parameter.
Show: "Neutral 0.0 ←——— 1.0 Expressive"

### 4C. Quick Text Templates
Pre-written texts for testing voices:
```python
VOICE_QUICK_TEXTS = {
    "Greeting": "Hello there! It's wonderful to meet you. I hope you're having a great day.",
    "Narration": "The sun had barely risen when the first birds began their morning chorus. A gentle mist clung to the valley floor.",
    "Excitement": "Oh my goodness, you won't believe what just happened! [laugh] This is absolutely incredible!",
    "Dramatic": "In the depths of the ancient forest, [sigh] a single light flickered. And then... silence.",
    "Podcast": "Welcome back to the show, everyone. Today we're diving into something that's been on my mind for weeks.",
}
```
Show as clickable chips that fill the text area.

### 4D. Voice History with Playback
Track generated voice clips in a history strip.
Each entry: duration, first few words of text, play button.

### 4E. Cross-Tab: "Read This Over Music"
When a music track exists in the music history, offer "Add background music" in the voice tab:
- Select a music track from recent generations
- Set music volume (default 20%)
- Generate voice → auto-mix → play result
- Uses the mix_audio function from the music enhancements

---

## PART 5: SFX TAB ENHANCEMENTS

### 5A. Sound Board Mode
After generating sounds, show them as a "sound board" — a grid of buttons that play on click.
Each cell: category icon, short description, play on click.
Persist the sound board during the session so users can build up a library of sounds.

### 5B. SFX Quick Prompts by Category
When a category is selected, show 3-4 specific example prompts that can be clicked to fill:
```python
SFX_QUICK_PROMPTS = {
    "Nature": ["Rain on a tin roof", "Thunder rolling in the distance", "Wind through pine trees", "Crackling campfire"],
    "Mechanical": ["Old clock ticking", "Steam hissing from a pipe", "Gears grinding slowly", "Typewriter keys clacking"],
    "Sci-Fi": ["Spaceship engine humming", "Laser beam charging up", "Teleporter activation", "Robot servo whirring"],
    "Musical": ["Piano key pressed softly", "Guitar string plucked", "Drum hit, reverberant room", "Glass harmonica tone"],
}
```

### 5C. SFX Variations
"Generate 3 variations" button — creates 3 versions of the same prompt with different seeds.
Display as a mini sound board row.

---

## PART 6: GLOBAL CROSS-TAB FEATURES

### 6A. Output Gallery (All Media)
Add a "Gallery" or "Creations" tab (or section at the bottom of each tab) that shows ALL recent creations across all media types.
Each entry shows: type icon (image/video/voice/music/sfx), thumbnail/waveform, timestamp, prompt snippet.
Clicking loads the item back into its respective tab's player/viewer.

### 6B. "Create Soundtrack" Workflow
A guided workflow accessible from any tab:
1. Generate background music (Music tab)
2. Generate voiceover (Voice tab)  
3. Mix them together
4. Optionally generate an image as cover art (Image tab)
5. Package as a single MP3 with embedded lyrics, cover art, and metadata

This can be a simple "Workflow" button that opens a step-by-step guide, not full automation.

### 6C. Consistent Empty States
Every tab currently shows different empty states. Unify them:
- When no models found: show a warm amber-tinted card with the NeoVak logo
- Text: "Your [media type] studio is ready. Add a model to begin creating."
- Link to docs/MODEL_GUIDE.md
- Consistent "QUICK START" section showing recommended models

---

## PART 7: FOOTER / APP CHROME

### 7A. System Status Bar
At the bottom of the app, show a persistent status bar:
```
[whisper●] ComfyUI: Connected  |  [whisper●] ACE-Step: Connected  |  [●] Voice: Ready  |  RAM: 42/192 GB
```
- Uses whisper pulse dots for connected services
- Shows memory usage (already have SystemInfo for this)
- Amber for connected, cold for disconnected

### 7B. App Header Update
Currently shows "NeoVak v1.2.0" with platform tagline.
Update to:
- "NeoVak" in a warm serif or display font feel
- Subtitle: "Create images, video, voice, and music with AI — privately, on your Mac."  
- Below: connected services whisper dots in a row

---

## Implementation Order

1. CSS additions (Part 1: hex progress, whisper dots, tube warming, foam loading) — apply everywhere
2. Tab header consistency (1C) — quick unification pass
3. Image enhancements (Part 2) — Surprise Me, style presets, Animate button
4. Video enhancements (Part 3) — I2V mode, history, Surprise Me
5. Voice enhancements (Part 4) — presets, emotion slider, templates, history
6. SFX enhancements (Part 5) — sound board, quick prompts, variations
7. Global features (Part 6) — output gallery, empty states
8. App chrome (Part 7) — status bar, header

## Testing Checklist

- [ ] Whisper pulse dots animate on all connected services
- [ ] Tube warming animation plays on all Generate buttons
- [ ] Hex progress bar replaces linear progress in all tabs
- [ ] "Surprise Me" works in Image, Video, and Music tabs
- [ ] Image style presets append to prompt
- [ ] "Animate This" button on image output loads into Video I2V mode
- [ ] Voice emotion slider appears in quality mode
- [ ] Voice quick texts fill textarea
- [ ] SFX sound board retains generated sounds
- [ ] SFX quick prompts fill description when clicked
- [ ] All tab headers use consistent style (no emoji, Lumina subtitles)
- [ ] System status bar shows at bottom with whisper dots
- [ ] Empty states are consistent across all tabs

Commit message: "feat: Lumina's World — unified theme, cross-tab enhancements, all media tabs upgraded"

## Related

- [[SPRINT_VIDEO_CHAIN]]
- [[SPRINT_ENHANCEMENTS]]
- [[Lumina_Whisper]]
- [[Lumina's Whisper full 2]]
- [[SPRINT_gallery_qc]]
