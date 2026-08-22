# Beatmaker v2 — Plan → Render Spec

## 0. Principle

LLM owns **semantic decisions** (genre, mood→key/mode, progression choice, energy arc, instrumentation).
Code owns **everything sub-symbolic and cross-track** (exact grids, bass-locked-to-kick, swing timing,
mix gains). No tool ever asks the LLM to compute an index, a tick offset, or a velocity curve — only to
pick from *named, described* options. This is the fix for the current "technically valid but off" output:
today, drum/bass/chord variants are chosen independently per instrument, so nothing locks together, and
`progression_idx 0-5` / `variant 0-2` carry no meaning the LLM can reason about.

---

## 1. Vocabulary data (new module: `engine/vocabulary.py`)

### 1.1 GENRES

```python
GENRES = {
    "lofi":    {"bpm_range": (70, 90),   "drum_style": "boom_bap",       "phrase_bars": 8,
                "default_instruments": ["drums", "bass", "piano"],
                "progressions": ["vi-IV-I-V", "I-V-vi-IV", "i-iv-v"]},
    "hiphop":  {"bpm_range": (80, 100),  "drum_style": "boom_bap",       "phrase_bars": 4,
                "default_instruments": ["drums", "bass", "piano", "synth"],
                "progressions": ["I-V-vi-IV", "i-VII-VI-VII"]},
    "trap":    {"bpm_range": (130, 150), "drum_style": "trap_halftime",  "phrase_bars": 4,
                "default_instruments": ["drums", "bass", "synth"],
                "progressions": ["i-VII-VI-VII", "i-VI-III-VII"]},
    "edm":     {"bpm_range": (124, 130), "drum_style": "four_on_floor",  "phrase_bars": 8,
                "default_instruments": ["drums", "bass", "synth"],
                "progressions": ["vi-IV-I-V", "I-V-vi-IV"]},
    "chill":   {"bpm_range": (85, 105),  "drum_style": "boom_bap",       "phrase_bars": 8,
                "default_instruments": ["drums", "bass", "piano", "guitar"],
                "progressions": ["I-V-vi-IV", "vi-IV-I-V"]},
    "ambient": {"bpm_range": (60, 80),   "drum_style": "ambient_sparse", "phrase_bars": 8,
                "default_instruments": ["piano", "synth"],
                "progressions": ["i-iv-v", "I-V-vi-IV"]},
    "rock":    {"bpm_range": (100, 140), "drum_style": "rock_backbeat",  "phrase_bars": 4,
                "default_instruments": ["drums", "bass", "guitar"],
                "progressions": ["I-IV-V-IV", "i-VI-III-VII"]},
    "jazz":    {"bpm_range": (70, 110),  "drum_style": "swing_ride",     "phrase_bars": 8,
                "default_instruments": ["drums", "bass", "piano"],
                "progressions": ["ii-V-I"]},
}
```

### 1.2 DRUM_STYLES — 16-step grids, grouped in 4s for readability. `x`=hit, `o`=ghost(soft), `.`=rest

```python
DRUM_STYLES = {
    "boom_bap": {  # lofi / hiphop / chill — swung, ghost notes
        "kick":  "x..x|....|x.x.|....",
        "snare": "....|x...|....|x..o",
        "hat":   "x.x.|x.x.|x.x.|x.x.",
        "desc":  "kick on 1 and the 'and' of 2/3, snare 2 & 4, swung 8th hats, ghost snare pickup"
    },
    "trap_halftime": {  # trap
        "kick":  "x...|..x.|...x|x...",
        "snare": "....|....|x...|....",   # half-time: snare only on beat 3
        "hat":   "x.xx|x.xx|x.xx|x.xx",   # rolled subdivisions
        "desc":  "half-time snare on beat 3, syncopated kick, rolled hi-hats"
    },
    "four_on_floor": {  # edm
        "kick":  "x...|x...|x...|x...",
        "snare": "....|x...|....|x...",  # functions as clap
        "hat":   ".x..|.x..|.x..|.x..",  # off-beat open hat
        "desc":  "kick every quarter, clap on 2 & 4, off-beat open hat"
    },
    "rock_backbeat": {  # rock
        "kick":  "x...|..x.|x...|..x.",
        "snare": "....|x...|....|x...",
        "hat":   "x.x.|x.x.|x.x.|x.x.",
        "desc":  "standard backbeat, snare 2 & 4, straight 8th hats"
    },
    "swing_ride": {  # jazz
        "kick":  "x...|....|x...|....",
        "snare": "..o.|.o..|..o.|.o..",  # sparse comping, mostly ghosted — humanized heavily
        "ride":  "x.x.|x.x.|x.x.|x.x.",  # triplet swing applied at render time, not in grid
        "desc":  "walking-adjacent sparse kick, ride cymbal swung ~66%, brushed ghost snare comping"
    },
    "ambient_sparse": {  # ambient
        "kick":  "x...|....|....|....",
        "snare": "....|....|....|....",
        "hat":   "....|....|....|....",
        "desc":  "downbeat only or fully omitted — texture carries the rhythm, not drums"
    },
}
```

### 1.3 Scale degrees & progressions — all diatonic, no borrowed chords needed

```python
MAJOR_SCALE_OFFSETS  = [0, 2, 4, 5, 7, 9, 11]   # semitones from key root, degrees 1-7
MINOR_SCALE_OFFSETS  = [0, 2, 3, 5, 7, 8, 10]   # natural minor

DEGREE_QUALITY = {
    "major": {1: "maj", 2: "min", 3: "min", 4: "maj", 5: "maj", 6: "min", 7: "dim"},
    "minor": {1: "min", 2: "dim", 3: "maj", 4: "min", 5: "min", 6: "maj", 7: "maj"},
}

# roman numeral -> (scale degree, mode this progression assumes)
PROGRESSIONS = {
    "I-V-vi-IV":     {"degrees": [1, 5, 6, 4], "mode": "major", "feel": "bright, uplifting"},
    "vi-IV-I-V":     {"degrees": [6, 4, 1, 5], "mode": "major", "feel": "wistful pop"},
    "I-IV-V-IV":     {"degrees": [1, 4, 5, 4], "mode": "major", "feel": "classic rock"},
    "ii-V-I":        {"degrees": [2, 5, 1],    "mode": "major", "feel": "jazz turnaround"},
    "i-VII-VI-VII":  {"degrees": [1, 7, 6, 7], "mode": "minor", "feel": "dark, cinematic"},
    "i-VI-III-VII":  {"degrees": [1, 6, 3, 7], "mode": "minor", "feel": "epic, dramatic"},
    "i-iv-v":        {"degrees": [1, 4, 5],    "mode": "minor", "feel": "dark blues/ambient"},
}

# optional per-genre chord extension (triad -> add a 7th) for flavor
CHORD_EXTENSIONS = {"jazz": "7", "lofi": "maj7_or_min7", "default": "triad"}
```

### 1.4 MOOD_RULES — the semantic fallback table (used only when LLM omits a field)

```python
MOOD_RULES = {
    "happy":       {"mode": "major", "energy_bias": "high", "genres": ["hiphop","edm","rock"]},
    "chill":       {"mode": "major", "energy_bias": "low",  "genres": ["lofi","chill","ambient"]},
    "dark":        {"mode": "minor", "energy_bias": "med",  "genres": ["trap","rock","ambient"]},
    "energetic":   {"mode": "major", "energy_bias": "high", "genres": ["edm","trap","rock"]},
    "melancholic": {"mode": "minor", "energy_bias": "low",  "genres": ["lofi","ambient","jazz"]},
    "dreamy":      {"mode": "major", "energy_bias": "low",  "genres": ["ambient","lofi","chill"]},
    "aggressive":  {"mode": "minor", "energy_bias": "high", "genres": ["trap","rock","edm"]},
}
```

### 1.5 SWING_TABLE (humanize config per drum_style)

```python
SWING_TABLE = {
    "boom_bap":       {"swing_pct": 60, "timing_jitter_ms": 8,  "velocity_jitter": 10},
    "trap_halftime":  {"swing_pct": 54, "timing_jitter_ms": 5,  "velocity_jitter": 8},
    "four_on_floor":  {"swing_pct": 50, "timing_jitter_ms": 3,  "velocity_jitter": 6},
    "rock_backbeat":  {"swing_pct": 51, "timing_jitter_ms": 4,  "velocity_jitter": 8},
    "swing_ride":      {"swing_pct": 66, "timing_jitter_ms": 10, "velocity_jitter": 14},
    "ambient_sparse":  {"swing_pct": 50, "timing_jitter_ms": 15, "velocity_jitter": 16},
}
```

### 1.6 MIX_PRESETS (per-genre stem gains, replaces one static gain table)

```python
MIX_PRESETS = {
    "trap":    {"drums": 1.00, "bass": 1.00, "piano": 0.75, "guitar": 0.70, "synth": 0.85},
    "lofi":    {"drums": 0.85, "bass": 0.90, "piano": 0.90, "guitar": 0.80, "synth": 0.55},
    "edm":     {"drums": 1.00, "bass": 0.95, "piano": 0.70, "guitar": 0.70, "synth": 1.00},
    "rock":    {"drums": 1.00, "bass": 0.90, "piano": 0.60, "guitar": 1.00, "synth": 0.50},
    "jazz":    {"drums": 0.80, "bass": 0.95, "piano": 1.00, "guitar": 0.75, "synth": 0.40},
    "ambient": {"drums": 0.50, "bass": 0.70, "piano": 0.80, "guitar": 0.60, "synth": 1.00},
    "hiphop":  {"drums": 1.00, "bass": 0.95, "piano": 0.80, "guitar": 0.75, "synth": 0.65},
    "chill":   {"drums": 0.80, "bass": 0.85, "piano": 0.90, "guitar": 0.85, "synth": 0.70},
}
```

---

## 2. MCP tools (4, replacing the current 6)

```
get_music_vocabulary() -> {genres, drum_styles, progressions, moods}
    Returns sections 1.1–1.4 above (names + one-line descriptions, not raw code).
    No params. Called once per session so the LLM's later choices are grounded
    in real names instead of invented or indexed ones.

plan_beat(prompt: str, mood: str, duration: float, overrides: dict = {}) -> Plan
    overrides may include any of: genre, key, mode, bpm, progression,
    drum_style, energy_curve, instruments (list).
    Does NOT render audio. Returns the full resolved plan + rationale.
    See §3 for fill/validation logic.

render_beat(plan: Plan) -> {files, musical_summary, pattern_preview}
    Deterministic. No LLM discretion inside. See §4.

refine_beat(plan: Plan, overrides: dict) -> Plan
    Same override schema as plan_beat. Applies a delta on top of an existing
    plan and re-validates. Does NOT render — the LLM calls render_beat again
    once satisfied. IMPORTANT: this tool does no NLP. The LLM must translate
    the user's free-text refinement request ("make it darker", "less busy")
    into structured overrides itself (e.g. {"mood": "dark"} or
    {"energy_curve": ["low","low","low","med"]}) before calling this.
```

---

## 3. `plan_beat` pseudocode

```python
def plan_beat(prompt, mood, duration, overrides=None):
    overrides = overrides or {}

    genre = overrides.get("genre") or pick_first(MOOD_RULES[mood]["genres"])
    if genre not in GENRES:
        raise ToolError(f"Unknown genre '{genre}'. Valid: {list(GENRES)}")

    mode = overrides.get("mode") or MOOD_RULES[mood]["mode"]
    key  = overrides.get("key")  or "C"  # default tonic; extend with a key_bias table if desired
    bpm  = overrides.get("bpm")  or midpoint(GENRES[genre]["bpm_range"])

    valid_progs = [p for p in GENRES[genre]["progressions"]
                   if PROGRESSIONS[p]["mode"] == mode]
    progression = overrides.get("progression") or pick_first(valid_progs)
    if progression not in PROGRESSIONS:
        raise ToolError(f"Unknown progression '{progression}'. Valid: {list(PROGRESSIONS)}")
    if PROGRESSIONS[progression]["mode"] != mode:
        raise ToolError(f"Progression '{progression}' requires mode={PROGRESSIONS[progression]['mode']}")

    drum_style = overrides.get("drum_style") or GENRES[genre]["drum_style"]
    if drum_style not in DRUM_STYLES:
        raise ToolError(f"Unknown drum_style '{drum_style}'. Valid: {list(DRUM_STYLES)}")

    energy_bias  = MOOD_RULES[mood]["energy_bias"]
    energy_curve = overrides.get("energy_curve") or default_energy_curve(energy_bias, duration, GENRES[genre]["phrase_bars"])
    instruments  = overrides.get("instruments") or GENRES[genre]["default_instruments"]

    plan = Plan(genre=genre, key=key, mode=mode, bpm=bpm, progression=progression,
                drum_style=drum_style, energy_curve=energy_curve,
                instruments=instruments, duration=duration)
    plan.rationale = (f"{genre} in {key} {mode} at {bpm} BPM, '{drum_style}' groove, "
                       f"'{progression}' ({PROGRESSIONS[progression]['feel']}) — for a {mood} feel.")
    return plan
```

**Validation contract:** every rejection names the bad field and lists valid values (never a bare
"invalid input") — this is what lets the LLM self-correct in the same turn instead of repeating the
same mistake.

---

## 4. `render_beat` pseudocode — this is the part that fixes "sounds generic/incoherent"

### 4.1 Bass locked to kick (the single highest-impact change)

```python
def build_bass_line(chord_root_pitch, kick_grid, mode):
    """kick_grid: 16-char string like 'x..x|....|x.x.|....' (bar boundaries stripped before use)"""
    kick_steps = [i for i, ch in enumerate(kick_grid) if ch == 'x']
    if not kick_steps:
        kick_steps = [0]  # fallback: downbeat, never silent

    notes = []
    for step in kick_steps:
        notes.append({"step": step, "pitch": chord_root_pitch, "role": "kick_locked"})

    # optional syncopated pickup one 16th before the last kick hit of the bar
    pickup_step = (kick_steps[-1] - 1) % 16
    if pickup_step not in kick_steps:
        passing_tone = chord_root_pitch + (2 if mode == "major" else 3)  # scale-appropriate 2nd
        notes.append({"step": pickup_step, "pitch": passing_tone, "role": "pickup"})

    return notes
```

Bass rhythm is *derived from* the drum grid, not independently randomized — this is what makes
drums+bass groove together instead of feeling like two unrelated random picks.

### 4.2 Chord voicing

```python
def chord_for_degree(key_root_midi, mode, degree, genre):
    scale = MAJOR_SCALE_OFFSETS if mode == "major" else MINOR_SCALE_OFFSETS
    root = key_root_midi + scale[degree - 1]
    quality = DEGREE_QUALITY[mode][degree]
    extension = CHORD_EXTENSIONS.get(genre, CHORD_EXTENSIONS["default"])
    return build_triad(root, quality, extension)
```

### 4.3 Energy → density (not a re-roll, a scale)

```python
def scale_density_by_energy(grid, energy):
    if energy == "low":  return remove_ghost_and_roll_hits(grid)   # drop 'o' and rolled subdivisions
    if energy == "high": return add_ghost_and_roll_hits(grid)      # add extra 16th hats / ghost snare
    return grid  # "med" = grid as authored in DRUM_STYLES
```

### 4.4 Turnaround fill (last bar of every phrase, except the very last bar of the whole render)

```python
def apply_turnaround_fill(grid, drum_style):
    grid = grid.copy()
    if drum_style != "ambient_sparse":
        grid.snare[14] = 'x'
        grid.snare[15] = 'x'
    return grid
```

Loop-safety rule: **never** apply a fill to the final bar of the final phrase — that bar must be
identical in shape to a normal bar so the render loops cleanly when repeated by a player/DAW.

### 4.5 Full assembly, with duration→bar math

```python
def render_beat(plan):
    bar_seconds   = 240 / plan.bpm
    phrase_bars   = GENRES[plan.genre]["phrase_bars"]
    total_bars    = ceil(plan.duration / bar_seconds)
    phrases_count = ceil(total_bars / phrase_bars)

    degrees = PROGRESSIONS[plan.progression]["degrees"]
    midi = MidiComposition(bpm=plan.bpm)

    for phrase_i in range(phrases_count):
        is_last_phrase = (phrase_i == phrases_count - 1)
        for bar_i in range(phrase_bars):
            global_bar = phrase_i * phrase_bars + bar_i
            if global_bar >= total_bars:
                break

            energy = plan.energy_curve[global_bar % len(plan.energy_curve)]
            degree = degrees[bar_i % len(degrees)]
            chord  = chord_for_degree(key_to_midi(plan.key), plan.mode, degree, plan.genre)

            grid = scale_density_by_energy(DRUM_STYLES[plan.drum_style], energy)
            is_phrase_end = (bar_i == phrase_bars - 1)
            is_final_bar  = is_last_phrase and (global_bar == total_bars - 1)
            if is_phrase_end and not is_final_bar:
                grid = apply_turnaround_fill(grid, plan.drum_style)

            bass_notes  = build_bass_line(chord.root_pitch, grid["kick"], plan.mode)
            chord_notes = voice_chord_for_instruments(chord, plan.instruments)

            midi.add_bar(grid, bass_notes, chord_notes, energy)

    midi = humanize(midi, SWING_TABLE[plan.drum_style])
    midi_path = midi.write_to(...)

    stems = {inst: fluidsynth_render_stem(midi_path, inst, GM_PROGRAM[inst])
             for inst in plan.instruments}
    mixed = mix_stems(stems, MIX_PRESETS[plan.genre])   # replaces the old static gain table
    wav_path, mp3_path = finalize_audio(mixed, peak=0.72, final_gain=0.85)  # keep existing normalize step

    return {
        "files": {"mid": midi_path, "wav": wav_path, "mp3": mp3_path},
        "musical_summary": {"genre": plan.genre, "key": plan.key, "mode": plan.mode,
                             "bpm": plan.bpm, "progression": plan.progression,
                             "drum_style": plan.drum_style},
        "pattern_preview": {"drums": DRUM_STYLES[plan.drum_style],
                             "bass_first_bar": bass_notes},
    }
```

### 4.6 Humanize (swing applied at render time, never restructures the pattern)

```python
def humanize(midi, swing_cfg):
    for note in midi.notes:
        if note.step % 2 == 1:  # off-beat 16ths get pushed late = swing feel
            note.start_time += ms_from_swing_pct(swing_cfg["swing_pct"])
        note.start_time += random_uniform(-swing_cfg["timing_jitter_ms"], swing_cfg["timing_jitter_ms"])
        note.velocity = clamp(note.velocity + random_int(-swing_cfg["velocity_jitter"],
                                                          swing_cfg["velocity_jitter"]), 1, 127)
    return midi
```

---

## 5. `refine_beat` pseudocode

```python
def refine_beat(plan, overrides):
    new_plan = plan.copy()
    for field, value in overrides.items():
        validate_field(field, value)   # same checks/errors as plan_beat
        setattr(new_plan, field, value)
    new_plan.rationale += f" | refined: {overrides}"
    return new_plan
```

No NLP lives here — the instruction-to-override translation is the LLM's job (language-shaped,
in-distribution). The tool only applies structured deltas deterministically.

---

## 6. Tool-use contract (paste into the agent's system prompt)

```
- Call get_music_vocabulary() once at the start of a session.
- Only use genre / progression / drum_style / mood values that appear in that
  response — never invent or index into a numbered list.
- Call plan_beat with your semantic choices (it's fine to omit fields and let
  the tool fill sensible defaults). Read the returned rationale.
- Only call render_beat once you're satisfied with the plan — rendering costs
  real compute, planning doesn't.
- For a user refinement request ("make it darker", "drop the piano"),
  translate it yourself into structured override fields, call refine_beat,
  then call render_beat again.
- If a tool call errors, the error names the bad field and lists valid values —
  retry with a corrected value instead of guessing.
```

---

## 7. Migration notes vs. current code

| Old | New |
|---|---|
| `generate_beat` (does plan+render in one opaque call) | split into `plan_beat` + `render_beat` |
| `list_instruments/list_options/list_variants/list_progressions/preview_info` | folded into `get_music_vocabulary` (+ `plan_beat(dry_run≈plan only)`) |
| `progression_idx 0-5`, `variant 0-2` | named progressions (§1.3), named drum_styles (§1.2) |
| independent per-instrument variant choice | bass rhythm derived from kick grid (§4.1) |
| static gain table | `MIX_PRESETS` per genre (§1.6) |
| generic humanize | `SWING_TABLE` per drum_style (§1.5) |

`REST` layer: `POST /api/prompt {prompt,duration,mood}` → LLM call → `plan_beat` → `render_beat` →
return files (single call for the simple web UI). Optionally expose `POST /api/plan` and
`POST /api/refine` later if you want a "preview before render" step in `web/index.html`.
