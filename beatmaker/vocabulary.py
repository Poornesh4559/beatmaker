"""beatmaker v2 vocabulary — semantic data layer (spec §1).

Pure data only. No rendering, no MIDI, no side effects.
LLM-facing names carry descriptions so choices are grounded, never indexed.
"""
from __future__ import annotations

# ── §1.1 GENRES ──────────────────────────────────────────────────────────────
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

# ── §1.2 DRUM_STYLES — 16-step grids, '|' groups bars-of-4-steps for readability.
# x=hit, o=ghost(soft), .=rest ────────────────────────────────────────────────
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

# ── §1.3 Scale degrees & progressions — all diatonic ─────────────────────────
MAJOR_SCALE_OFFSETS  = [0, 2, 4, 5, 7, 9, 11]   # semitones from key root, degrees 1-7
MINOR_SCALE_OFFSETS  = [0, 2, 3, 5, 7, 8, 10]   # natural minor

DEGREE_QUALITY = {
    "major": {1: "maj", 2: "min", 3: "min", 4: "maj", 5: "maj", 6: "min", 7: "dim"},
    "minor": {1: "min", 2: "dim", 3: "maj", 4: "min", 5: "min", 6: "maj", 7: "maj"},
}

# roman numeral -> (scale degrees, mode this progression assumes)
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

# ── §1.4 MOOD_RULES — semantic fallback table (only when LLM omits a field) ──
MOOD_RULES = {
    "happy":       {"mode": "major", "energy_bias": "high", "genres": ["hiphop","edm","rock"]},
    "chill":       {"mode": "major", "energy_bias": "low",  "genres": ["lofi","chill","ambient"]},
    "dark":        {"mode": "minor", "energy_bias": "med",  "genres": ["trap","rock","ambient"]},
    "energetic":   {"mode": "major", "energy_bias": "high", "genres": ["edm","trap","rock"]},
    "melancholic": {"mode": "minor", "energy_bias": "low",  "genres": ["lofi","ambient","jazz"]},
    "dreamy":      {"mode": "major", "energy_bias": "low",  "genres": ["ambient","lofi","chill"]},
    "aggressive":  {"mode": "minor", "energy_bias": "high", "genres": ["trap","rock","edm"]},
}

# ── §1.5 SWING_TABLE — humanize config per drum_style ────────────────────────
SWING_TABLE = {
    "boom_bap":       {"swing_pct": 60, "timing_jitter_ms": 8,  "velocity_jitter": 10},
    "trap_halftime":  {"swing_pct": 54, "timing_jitter_ms": 5,  "velocity_jitter": 8},
    "four_on_floor":  {"swing_pct": 50, "timing_jitter_ms": 3,  "velocity_jitter": 6},
    "rock_backbeat":  {"swing_pct": 51, "timing_jitter_ms": 4,  "velocity_jitter": 8},
    "swing_ride":      {"swing_pct": 66, "timing_jitter_ms": 10, "velocity_jitter": 14},
    "ambient_sparse":  {"swing_pct": 50, "timing_jitter_ms": 15, "velocity_jitter": 16},
}

# ── §1.6 MIX_PRESETS — per-genre stem gains (replaces static gain table) ─────
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
