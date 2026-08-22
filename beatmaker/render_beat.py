"""beatmaker v2 — render_beat end-to-end (spec §4.5).

Composes a Plan into MIDI using the Phase 2 primitives, then renders through
the existing FluidSynth stem pipeline (per-stem peak 0.72 → genre gains →
final 0.85) with gains sourced from MIX_PRESETS instead of the old static table.

The legacy path in engine.py is untouched.
"""
from __future__ import annotations

import math
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pretty_midi

from beatmaker.vocabulary import (
    GENRES,
    DRUM_STYLES,
    PROGRESSIONS,
    SWING_TABLE,
    MIX_PRESETS,
)
from beatmaker.render_primitives import (
    chord_for_degree,
    key_to_midi,
    build_bass_line,
    scale_density_by_energy,
    apply_turnaround_fill,
    humanize,
    HumanizedNote,
)

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output"

# GM program map (mirrors engine.INSTRUMENTS; kept local so v2 is self-contained)
GM_PROGRAM = {
    "drums": 0,   # channel-9 percussion, program irrelevant
    "bass": 32,
    "piano": 0,
    "guitar": 25,
    "synth": 81,
}
HARMONIC_INSTS = ("piano", "guitar", "synth")

# drum lane -> GM pitch
LANE_PITCH = {"kick": 36, "snare": 38, "hat": 42, "ride": 51}
LANE_VELOCITY = {"kick": 102, "snare": 96, "hat": 62, "ride": 58, "ghost": 48}


# ── Plan ─────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    genre: str
    key: str
    mode: str
    bpm: int
    progression: str
    drum_style: str
    energy_curve: List[str]
    instruments: List[str]
    duration: float
    rationale: str = ""


def default_energy_curve(energy_bias: str, duration: float, phrase_bars: int) -> List[str]:
    """4-slot curve cycled per bar; slot picked by global_bar % len."""
    if energy_bias == "high":
        return ["med", "high", "high", "high"]
    if energy_bias == "low":
        return ["low", "low", "med", "med"]
    return ["low", "med", "med", "high"]


# ── composition ──────────────────────────────────────────────────────────────

def _add_grid_notes(inst: pretty_midi.Instrument, grid: Dict[str, str],
                    bar_start: float, step_seconds: float):
    """Drum lanes for one bar. 'x' full vel, 'o' ghost soft."""
    for lane, pattern in grid.items():
        if lane == "desc" or not isinstance(pattern, str):
            continue
        stripped = pattern.replace("|", "")
        pitch = LANE_PITCH.get(lane)
        if pitch is None:
            continue
        for i, ch in enumerate(stripped):
            if ch == ".":
                continue
            vel = LANE_VELOCITY["ghost"] if ch == "o" else LANE_VELOCITY.get(lane, 80)
            start = bar_start + i * step_seconds
            inst.notes.append(pretty_midi.Note(
                velocity=vel, pitch=pitch, start=start, end=start + min(0.18, step_seconds)))


def _add_bass_notes(inst: pretty_midi.Instrument, bass_notes: List[Dict],
                    bar_start: float, step_seconds: float, next_bar_start: float):
    """Bass events sit on their step and ring until the next event (or bar end)."""
    events = sorted(bass_notes, key=lambda n: n["step"])
    for idx, ev in enumerate(events):
        start = bar_start + ev["step"] * step_seconds
        if idx + 1 < len(events):
            end = bar_start + events[idx + 1]["step"] * step_seconds
        else:
            end = next_bar_start
        end = max(start + 0.08, end - 0.02)  # tiny gap, never zero-length
        vel = 88 if ev["role"] == "kick_locked" else 68
        inst.notes.append(pretty_midi.Note(
            velocity=vel, pitch=ev["pitch"], start=start, end=end))


def _voice_chord_for_instruments(chord: Dict, instruments: List[str]):
    """Assign the chord voicing to whichever harmonic instruments are present.
    Returns {inst_name: [pitches]}."""
    voicing = chord["voicing"]
    out = {}
    for name in instruments:
        if name == "piano":
            out["piano"] = list(voicing)
        elif name == "guitar":
            # guitar sits an octave up, triad only
            out["guitar"] = [p + 12 for p in voicing[:3]]
        elif name == "synth":
            # pad: full voicing octave up
            out["synth"] = [p + 12 for p in voicing]
    return out


def _add_chord_notes(pm: pretty_midi.Instrument, pitches: List[int],
                     bar_start: float, bar_seconds: float, energy: str, kind: str):
    """Harmony for one bar. Sustain by default; piano re-strikes on backbeats
    when energy is high; synth pads swell (longer notes)."""
    if kind == "piano":
        if energy == "high":
            for beat in (0, 2):  # half-bar stabs
                start = bar_start + beat * bar_seconds / 4 * 2
                for p in pitches:
                    pm.notes.append(pretty_midi.Note(
                        velocity=64, pitch=p, start=start, end=start + bar_seconds / 4 * 1.6))
        else:
            for i, p in enumerate(pitches):
                start = bar_start + i * 0.012  # gentle roll
                pm.notes.append(pretty_midi.Note(
                    velocity=58, pitch=p, start=start, end=bar_start + bar_seconds - 0.05))
    elif kind == "guitar":
        for i, p in enumerate(pitches):
            start = bar_start + i * 0.01
            pm.notes.append(pretty_midi.Note(
                velocity=56, pitch=p, start=start, end=bar_start + bar_seconds / 2))
            pm.notes.append(pretty_midi.Note(
                velocity=52, pitch=p, start=bar_start + bar_seconds / 2,
                end=bar_start + bar_seconds - 0.05))
    else:  # synth pad
        for p in pitches:
            pm.notes.append(pretty_midi.Note(
                velocity=50, pitch=p, start=bar_start, end=bar_start + bar_seconds - 0.03))


def compose_midi(plan: Plan) -> pretty_midi.PrettyMIDI:
    """§4.5 assembly — bars from grids/bass/chords, loop-safe fills."""
    bar_seconds = 240.0 / plan.bpm
    step_seconds = bar_seconds / 16.0
    phrase_bars = GENRES[plan.genre]["phrase_bars"]
    total_bars = max(1, math.ceil(plan.duration / bar_seconds))
    phrases_count = math.ceil(total_bars / phrase_bars)

    degrees = PROGRESSIONS[plan.progression]["degrees"]
    style = DRUM_STYLES[plan.drum_style]

    pm = pretty_midi.PrettyMIDI(initial_tempo=plan.bpm)
    tracks: Dict[str, pretty_midi.Instrument] = {}

    def track(name: str) -> Optional[pretty_midi.Instrument]:
        if name not in plan.instruments:
            return None
        if name not in tracks:
            cfg_prog = GM_PROGRAM.get(name, 0)
            tracks[name] = pretty_midi.Instrument(
                program=cfg_prog, is_drum=(name == "drums"), name=name)
            pm.instruments.append(tracks[name])
        return tracks[name]

    drum_inst = track("drums")
    bass_inst = track("bass")
    last_bass_notes: List[Dict] = []

    for phrase_i in range(phrases_count):
        is_last_phrase = (phrase_i == phrases_count - 1)
        for bar_i in range(phrase_bars):
            global_bar = phrase_i * phrase_bars + bar_i
            if global_bar >= total_bars:
                break

            energy = plan.energy_curve[global_bar % len(plan.energy_curve)]
            degree = degrees[bar_i % len(degrees)]
            chord = chord_for_degree(key_to_midi(plan.key), plan.mode, degree, plan.genre)

            grid = scale_density_by_energy(style, energy)
            is_phrase_end = (bar_i == phrase_bars - 1)
            is_final_bar = is_last_phrase and (global_bar == total_bars - 1)
            if is_phrase_end and not is_final_bar:
                grid = apply_turnaround_fill(grid, plan.drum_style)

            bar_start = global_bar * bar_seconds
            next_bar_start = (global_bar + 1) * bar_seconds

            if drum_inst is not None:
                _add_grid_notes(drum_inst, grid, bar_start, step_seconds)

            bass_notes = build_bass_line(chord["root_pitch"] - 12, grid["kick"], plan.mode)
            last_bass_notes = bass_notes
            if bass_inst is not None:
                _add_bass_notes(bass_inst, bass_notes, bar_start, step_seconds, next_bar_start)

            voiced = _voice_chord_for_instruments(chord, plan.instruments)
            for name, pitches in voiced.items():
                inst = track(name)
                if inst is not None:
                    _add_chord_notes(inst, pitches, bar_start, bar_seconds, energy, name)

    # stash for preview (first-bar bass of the composition)
    pm._v2_last_bass_notes = last_bass_notes  # type: ignore[attr-defined]
    return pm


def apply_humanize(plan: Plan, pm: pretty_midi.PrettyMIDI, seed=None) -> None:
    """§4.6 across all tracks — swing on odd 16ths + jitter.

    When seed is None the jitter is non-deterministic (fresh OS entropy) so
    the same Plan rendered twice produces subtly different timing/velocities.
    Pass an int seed for deterministic tests. No pattern structure is changed.
    """
    import random as _random, secrets as _secrets
    if seed is None:
        seed = _secrets.randbits(31)
    rng = _random.Random(seed)
    step_seconds = (240.0 / plan.bpm) / 16.0
    cfg = SWING_TABLE[plan.drum_style]
    for inst in pm.instruments:
        notes = [HumanizedNote(step=0, start_time=n.start, end_time=n.end,
                               velocity=n.velocity, pitch=n.pitch)
                 for n in inst.notes]
        # map step index from original position for swing decision
        bar_len = step_seconds * 16
        for hn, orig in zip(notes, inst.notes):
            pos_in_bar = orig.start % bar_len
            hn.step = round(pos_in_bar / step_seconds)
        humanize(notes, cfg, step_seconds=step_seconds, rng=rng)
        for hn, orig in zip(notes, inst.notes):
            orig.start = max(0.0, hn.start_time)
            orig.end = max(orig.start + 0.02, hn.end_time)
            orig.velocity = hn.velocity


# ── audio pipeline (existing stem-render reused, gains swapped) ──────────────

def _find_sf2():
    from beatmaker.engine import find_sf2
    return find_sf2()


def render_stems_and_mix(pm: pretty_midi.PrettyMIDI, midi_path: Path,
                         wav_path: Path, mp3_path: Path, gains: Dict[str, float]):
    """Per-stem FluidSynth → peak-normalize each stem to 0.72 → genre gains →
    sum → final peak 0.85 → WAV + MP3. Falls back to single-file render."""
    import numpy as np
    import soundfile as sf

    midi_path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(midi_path))
    sf2_path = _find_sf2()
    STEM_PEAK = 0.72
    FINAL_PEAK = 0.85

    stems: List[np.ndarray] = []
    if sf2_path and Path("/usr/bin/fluidsynth").exists():
        try:
            tempo = float(pm.get_tempo_changes()[1][0])
        except Exception:
            tempo = 120.0
        for inst in pm.instruments:
            try:
                pm_one = pretty_midi.PrettyMIDI(initial_tempo=tempo)
                clone = pretty_midi.Instrument(program=inst.program,
                                               is_drum=inst.is_drum, name=inst.name)
                clone.notes = list(inst.notes)
                pm_one.instruments.append(clone)
                with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tf:
                    pm_one.write(tf.name)
                stem_wav = tf.name + ".wav"
                cmd = (f"fluidsynth -ni -F {shlex.quote(stem_wav)} "
                       f"{shlex.quote(str(sf2_path))} {shlex.quote(tf.name)} -r 44100 2>/dev/null")
                subprocess.run(cmd, shell=True, timeout=30)
                if Path(stem_wav).exists():
                    y, _sr = sf.read(stem_wav)
                    if y.ndim > 1:
                        y = y.mean(axis=1)
                    y = np.asarray(y, dtype=np.float32)
                    peak = float(np.abs(y).max()) if y.size else 0.0
                    if peak > 0.005:
                        y = y / peak * STEM_PEAK
                    y = y * gains.get(inst.name, 0.85)
                    stems.append(y)
                Path(stem_wav).unlink(missing_ok=True)
                Path(tf.name).unlink(missing_ok=True)
            except Exception as e:  # keep going — drop this stem
                print(f"[render_beat] stem {inst.name} failed: {e}")

    mixed_ok = False
    if stems:
        max_len = max(len(s) for s in stems)
        mix = np.zeros(max_len, dtype=np.float32)
        for s in stems:
            mix[:len(s)] += s
        peak = float(np.abs(mix).max()) if mix.size else 1.0
        if peak > 0.01:
            mix = mix / peak * FINAL_PEAK
        mix = np.clip(mix, -1.0, 1.0)
        sf.write(str(wav_path), mix, 44100)
        mixed_ok = True

    if not mixed_ok:
        # fallback: single-file render (same as legacy)
        if sf2_path and Path("/usr/bin/fluidsynth").exists():
            subprocess.run(
                f"fluidsynth -ni -F {shlex.quote(str(wav_path))} "
                f"{shlex.quote(str(sf2_path))} {shlex.quote(str(midi_path))} -r 44100",
                shell=True, timeout=30)
        if not wav_path.exists():
            dur = pm.get_end_time()
            subprocess.run(
                f"ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t {dur:.1f} "
                f"{shlex.quote(str(wav_path))} 2>/dev/null", shell=True, timeout=10)

    if wav_path.exists():
        subprocess.run(
            f"ffmpeg -y -i {shlex.quote(str(wav_path))} -codec:a libmp3lame -qscale:a 2 "
            f"{shlex.quote(str(mp3_path))} 2>/dev/null", shell=True, timeout=20)

    return {"midi": str(midi_path), "wav": str(wav_path), "mp3": str(mp3_path)}


# ── public entry ─────────────────────────────────────────────────────────────

def render_beat(plan: Plan, out_dir: Path = OUT_DIR,
                tag: str = "v2", humanize_seed=None) -> Dict:
    """Deterministic when humanize_seed is pinned; non-deterministic (and
    therefore creative) by default. Returns files + musical summary + preview."""
    pm = compose_midi(plan)
    apply_humanize(plan, pm, seed=humanize_seed)

    stamp = __import__("time").strftime("%Y%m%d_%H%M%S")
    stem = f"{tag}_{plan.genre}_{stamp}"
    midi_path = out_dir / f"{stem}.mid"
    wav_path = out_dir / f"{stem}.wav"
    mp3_path = out_dir / f"{stem}.mp3"

    gains = MIX_PRESETS[plan.genre]
    files = render_stems_and_mix(pm, midi_path, wav_path, mp3_path, gains)

    style = DRUM_STYLES[plan.drum_style]
    first_chord_deg = PROGRESSIONS[plan.progression]["degrees"][0]
    first_chord = chord_for_degree(key_to_midi(plan.key), plan.mode, first_chord_deg, plan.genre)
    bass_first = build_bass_line(first_chord["root_pitch"] - 12, style["kick"], plan.mode)

    return {
        "files": files,
        "musical_summary": {
            "genre": plan.genre, "key": plan.key, "mode": plan.mode,
            "bpm": plan.bpm, "progression": plan.progression,
            "drum_style": plan.drum_style,
        },
        "pattern_preview": {
            "drums": style,
            "bass_first_bar": bass_first,
            "chord_first_bar": {"degree": first_chord["degree"],
                                 "voicing": first_chord["voicing"],
                                 "quality": first_chord["quality"],
                                 "extension": first_chord["extension"]},
        },
    }
