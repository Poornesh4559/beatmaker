"""beatmaker v2 render primitives — pure functions on note/step data (spec §4).

No MIDI objects, no audio, no filesystem. Deterministic except where an RNG
is explicitly passed in. These are the building blocks Phase 3's render_beat
assembles into a composition.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from beatmaker.vocabulary import (
    MAJOR_SCALE_OFFSETS,
    MINOR_SCALE_OFFSETS,
    DEGREE_QUALITY,
    CHORD_EXTENSIONS,
)


# ── §4.2 chord construction ──────────────────────────────────────────────────

def build_triad(root_midi: int, quality: str, extension: str = "triad") -> List[int]:
    """Build a chord from a root pitch.

    quality: 'maj' | 'min' | 'dim'
    extension: 'triad' | '7' (dominant/min7-flavor) | 'maj7_or_min7' (quality-aware maj7)
    """
    if quality == "maj":
        third = 4
    elif quality == "min":
        third = 3
    elif quality == "dim":
        third = 3
    else:
        raise ValueError(f"unknown quality '{quality}' (valid: maj, min, dim)")
    notes = [root_midi, root_midi + third]
    # fifth: diminished chords flatten it
    notes.append(root_midi + (6 if quality == "dim" else 7))
    if extension == "7":
        notes.append(root_midi + 10)
    elif extension == "maj7_or_min7":
        notes.append(root_midi + (11 if quality == "maj" else 10))
    return notes


def key_to_midi(key: str) -> int:
    """Key name -> MIDI pitch class in octave 4 region (C4=60 base for tonic)."""
    table = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
             "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    k = key.strip()
    if k not in table:
        raise ValueError(f"unknown key '{key}' (valid: {', '.join(table)})")
    return 48 + table[k]


def chord_for_degree(key_root_midi: int, mode: str, degree: int, genre: str):
    """Diatonic chord for a scale degree (1-7). Returns dict with root pitch,
    full voicing, quality and the applied extension."""
    if mode not in ("major", "minor"):
        raise ValueError(f"unknown mode '{mode}' (valid: major, minor)")
    if not 1 <= int(degree) <= 7:
        raise ValueError(f"degree {degree} out of range 1-7")
    scale = MAJOR_SCALE_OFFSETS if mode == "major" else MINOR_SCALE_OFFSETS
    root = key_root_midi + scale[int(degree) - 1]
    quality = DEGREE_QUALITY[mode][int(degree)]
    extension = CHORD_EXTENSIONS.get(genre, CHORD_EXTENSIONS["default"])
    voicing = build_triad(root, quality, extension)
    return {
        "root_pitch": root,
        "voicing": voicing,
        "quality": quality,
        "extension": extension,
        "degree": int(degree),
    }


# ── grid helpers ─────────────────────────────────────────────────────────────

def grid_steps(grid: str, char: str) -> List[int]:
    """16-char grid string ('x..x|....') -> list of step indices matching char.
    Bar-boundary pipes are stripped before scanning."""
    stripped = grid.replace("|", "")
    if len(stripped) != 16 or any(c not in "xo." for c in stripped):
        raise ValueError(f"bad grid '{grid}' — must be 16 steps of x/o/.")
    return [i for i, c in enumerate(stripped) if c == char]


# ── §4.1 bass locked to kick ────────────────────────────────────────────────

def build_bass_line(chord_root_pitch: int, kick_grid: str, mode: str) -> List[Dict]:
    """Derive bass rhythm FROM the kick grid — never independently randomized.

    kick_grid: 16-step string like 'x..x|....|x.x.|....'.
    Returns note dicts: {step, pitch, role} where role is kick_locked|pickup.
    """
    kick_steps = grid_steps(kick_grid, "x")
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

    notes.sort(key=lambda n: n["step"])
    return notes


# ── §4.3 energy → density ────────────────────────────────────────────────────

def _remove_ghost_and_roll_hits(grid: Dict[str, str]) -> Dict[str, str]:
    """low energy: drop ghosts ('o') and de-cluster rolls (keep first hit of each
    consecutive run beyond it)."""
    out = {}
    for lane, pattern in grid.items():
        if lane == "desc" or not isinstance(pattern, str):
            out[lane] = pattern
            continue
        steps = pattern.replace("|", "")
        cleaned = []
        prev_hit = False
        for ch in steps:
            if ch == "o":
                cleaned.append(".")
                prev_hit = False
            elif ch == "x":
                # keep only the first of consecutive runs (de-roll)
                cleaned.append("x" if not prev_hit else ".")
                prev_hit = True
            else:
                cleaned.append(".")
                prev_hit = False
        out[lane] = "".join(cleaned)
    return out


def _add_ghost_and_roll_hits(grid: Dict[str, str]) -> Dict[str, str]:
    """high energy: add ghost snare pickups on empty 16ths adjacent to snare hits,
    and roll hats by filling empty hat slots that neighbor existing hits."""
    out = {}
    for lane, pattern in grid.items():
        if lane == "desc" or not isinstance(pattern, str):
            out[lane] = pattern
            continue
        steps = list(pattern.replace("|", ""))
        if lane == "snare":
            for i, ch in enumerate(steps):
                if ch == "x" and i + 1 < 16 and steps[i + 1] == ".":
                    steps[i + 1] = "o"
        elif lane in ("hat", "ride"):
            for i, ch in enumerate(steps):
                if ch == ".":
                    left = steps[i - 1] if i > 0 else "."
                    right = steps[i + 1] if i < 15 else "."
                    if left in "xo" or right in "xo":
                        steps[i] = "x"
        out[lane] = "".join(steps)
    return out


def scale_density_by_energy(grid: Dict[str, str], energy: str) -> Dict[str, str]:
    """Energy scales density; 'med' returns the authored grid untouched.
    Accepts full style dict (with desc) or bare lanes dict."""
    if energy == "med":
        return dict(grid)
    lanes_only = {k: v for k, v in grid.items() if isinstance(v, str)}
    if energy == "low":
        scaled = _remove_ghost_and_roll_hits(lanes_only)
    elif energy == "high":
        scaled = _add_ghost_and_roll_hits(lanes_only)
    else:
        raise ValueError(f"unknown energy '{energy}' (valid: low, med, high)")
    result = dict(grid)
    result.update(scaled)
    return result


# ── §4.4 turnaround fill ─────────────────────────────────────────────────────

def apply_turnaround_fill(grid: Dict[str, str], drum_style: str) -> Dict[str, str]:
    """Last bar of a phrase: snare hits on steps 14+15 (loop-safety handled by caller).
    ambient_sparse never fills — texture carries it."""
    if drum_style == "ambient_sparse":
        return dict(grid)
    out = dict(grid)
    if "snare" in out and isinstance(out["snare"], str):
        steps = list(out["snare"].replace("|", ""))
        steps[14] = "x"
        steps[15] = "x"
        out["snare"] = "".join(steps)
    return out


# ── §4.6 humanize ────────────────────────────────────────────────────────────

class HumanizedNote:
    """Lightweight timing/velocity carrier. start_time/end_time in seconds,
    velocity 1-127. `step` kept for tests/debugging."""
    __slots__ = ("step", "start_time", "end_time", "velocity", "pitch")

    def __init__(self, step: float, start_time: float, end_time: float,
                 velocity: int, pitch: int = 0):
        self.step = step
        self.start_time = start_time
        self.end_time = end_time
        self.velocity = velocity
        self.pitch = pitch

    def __repr__(self):  # pragma: no cover
        return (f"HumanizedNote(step={self.step}, t={self.start_time:.4f}-"
                f"{self.end_time:.4f}, vel={self.velocity})")


def ms_from_swing_pct(swing_pct: float, step_seconds: float) -> float:
    """Swing delay in seconds for off-beat 16ths. 50% = straight (no delay),
    66% ≈ triplet feel. Max useful delay is one full 16th (step_seconds * 0.5)."""
    delay_frac = (swing_pct - 50.0) / 100.0  # 0 at straight, 0.16 at 66%
    return max(0.0, min(step_seconds * 0.5, delay_frac * 2.0 * step_seconds))


def humanize(notes: List[HumanizedNote], swing_cfg: Dict,
             step_seconds: float = 0.125, rng=None) -> List[HumanizedNote]:
    """Apply swing to odd 16th-steps + timing/velocity jitter IN PLACE-ish
    (returns same note objects, mutated). Never restructures the pattern —
    order and count of notes are preserved.

    swing_cfg keys: swing_pct, timing_jitter_ms, velocity_jitter
    rng: injectable random.Random for deterministic tests.
    """
    import random as _random
    rng = rng or _random.Random()
    timing_s = swing_cfg.get("timing_jitter_ms", 0) / 1000.0
    vel_jitter = swing_cfg.get("velocity_jitter", 0)
    swing_pct = swing_cfg.get("swing_pct", 50)

    for note in notes:
        if note.step % 2 == 1:  # off-beat 16ths pushed late = swing feel
            note.start_time += ms_from_swing_pct(swing_pct, step_seconds)
            note.end_time += ms_from_swing_pct(swing_pct, step_seconds)
        jitter = rng.uniform(-timing_s, timing_s)
        note.start_time += jitter
        note.end_time += max(0.01, note.end_time + jitter - note.start_time)
        note.velocity = max(1, min(127, note.velocity + rng.randint(-vel_jitter, vel_jitter)))
    return notes
