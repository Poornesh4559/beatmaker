"""beatmaker v2 — plan_beat / refine_beat (spec §3, §5).

LLM owns semantic choices; this module resolves them against the vocabulary,
validates strictly (every rejection names the bad field AND lists valid values),
and never touches audio. render_beat consumes the resulting Plan.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from beatmaker.vocabulary import (
    GENRES,
    DRUM_STYLES,
    PROGRESSIONS,
    MOOD_RULES,
    MIX_PRESETS,
)
from beatmaker.render_beat import Plan, default_energy_curve

VALID_KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
VALID_MODES = ["major", "minor"]
VALID_INSTRUMENTS = ["drums", "bass", "piano", "guitar", "synth"]
VALID_ENERGIES = ["low", "med", "high"]
VALID_OVERRIDES = ["genre", "key", "mode", "bpm", "progression",
                   "drum_style", "energy_curve", "instruments"]
MIN_BPM, MAX_BPM = 40, 220
MIN_DURATION_S, MAX_DURATION_S = 4, 600


class ToolError(ValueError):
    """Raised with a message that names the bad field and lists valid values."""


# ── field validators ─────────────────────────────────────────────────────────

def _v_genre(value):
    if value not in GENRES:
        raise ToolError(f"Unknown genre '{value}'. Valid: {sorted(GENRES)}")
    return value


def _v_mood(value):
    if value not in MOOD_RULES:
        raise ToolError(f"Unknown mood '{value}'. Valid: {sorted(MOOD_RULES)}")
    return value


def _v_key(value):
    k = str(value).strip()
    # accept 'Bb' style flats by normalizing to sharps
    norm = {"Cb": "B", "Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#",
            "Ab": "G#", "Bb": "A#"}.get(k, k)
    if norm not in VALID_KEYS:
        raise ToolError(f"Invalid key '{value}'. Valid: {VALID_KEYS}")
    return norm


def _v_mode(value):
    if value not in VALID_MODES:
        raise ToolError(f"Invalid mode '{value}'. Valid: {VALID_MODES}")
    return value


def _v_bpm(value):
    try:
        bpm = int(round(float(value)))
    except (TypeError, ValueError):
        raise ToolError(f"Invalid bpm '{value}'. Valid: integer {MIN_BPM}-{MAX_BPM}")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise ToolError(f"bpm {bpm} out of range. Valid: {MIN_BPM}-{MAX_BPM}")
    return bpm


def _v_duration(value):
    try:
        dur = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"Invalid duration '{value}'. Valid: seconds {MIN_DURATION_S}-{MAX_DURATION_S}")
    if not MIN_DURATION_S <= dur <= MAX_DURATION_S:
        raise ToolError(f"duration {dur}s out of range. Valid: {MIN_DURATION_S}-{MAX_DURATION_S}")
    return dur


def _v_progression(value, mode: Optional[str] = None):
    if value not in PROGRESSIONS:
        raise ToolError(f"Unknown progression '{value}'. Valid: {sorted(PROGRESSIONS)}")
    pmode = PROGRESSIONS[value]["mode"]
    if mode is not None and pmode != mode:
        raise ToolError(
            f"Progression '{value}' requires mode='{pmode}' but plan mode is '{mode}'. "
            f"Either pick a '{mode}' progression "
            f"{[p for p, cfg in PROGRESSIONS.items() if cfg['mode'] == mode]} "
            f"or override mode='{pmode}'.")
    return value


def _v_drum_style(value):
    if value not in DRUM_STYLES:
        raise ToolError(f"Unknown drum_style '{value}'. Valid: {sorted(DRUM_STYLES)}")
    return value


def _v_energy_curve(value):
    if not isinstance(value, (list, tuple)) or not (1 <= len(value) <= 16):
        raise ToolError("energy_curve must be a list of 1-16 energy slots")
    for slot in value:
        if slot not in VALID_ENERGIES:
            raise ToolError(f"Invalid energy slot '{slot}' in energy_curve. Valid: {VALID_ENERGIES}")
    return list(value)


def _v_instruments(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise ToolError(f"instruments must be a non-empty list. Valid: {VALID_INSTRUMENTS} (max 5)")
    cleaned = []
    for inst in value:
        if inst not in VALID_INSTRUMENTS:
            raise ToolError(f"Unknown instrument '{inst}'. Valid: {VALID_INSTRUMENTS}")
        if inst not in cleaned:
            cleaned.append(inst)
    if len(cleaned) > 5:
        raise ToolError(f"Too many instruments ({len(cleaned)}). Max 5. Valid: {VALID_INSTRUMENTS}")
    return cleaned


def _check_unknown_overrides(overrides: Dict):
    bad = [k for k in overrides if k not in VALID_OVERRIDES]
    if bad:
        raise ToolError(f"Unknown override field(s) {bad}. Valid: {VALID_OVERRIDES}")


# ── §3 plan_beat ─────────────────────────────────────────────────────────────

def plan_beat(prompt: str, mood: str, duration: float, overrides: Optional[Dict] = None) -> Plan:
    overrides = dict(overrides or {})
    _check_unknown_overrides(overrides)

    mood_v = _v_mood(mood)
    duration_v = _v_duration(duration)

    genre = overrides.get("genre")
    if genre is not None:
        genre = _v_genre(genre)
    else:
        genre = MOOD_RULES[mood_v]["genres"][0]  # pick_first per spec

    mode = overrides.get("mode")
    if mode is not None:
        mode = _v_mode(mode)
    else:
        mode = MOOD_RULES[mood_v]["mode"]

    key = _v_key(overrides["key"]) if overrides.get("key") is not None else "C"
    bpm = _v_bpm(overrides["bpm"]) if overrides.get("bpm") is not None \
        else (GENRES[genre]["bpm_range"][0] + GENRES[genre]["bpm_range"][1]) // 2

    progression = overrides.get("progression")
    if progression is not None:
        progression = _v_progression(progression, mode)
    else:
        valid_progs = [p for p in GENRES[genre]["progressions"]
                       if PROGRESSIONS[p]["mode"] == mode]
        # pick_first of the genre's mode-matching progressions
        if not valid_progs:
            raise ToolError(
                f"Genre '{genre}' has no '{mode}'-mode progressions. "
                f"Its listed progressions are {GENRES[genre]['progressions']} — "
                f"override mode to one of "
                f"{sorted({PROGRESSIONS[p]['mode'] for p in GENRES[genre]['progressions']})}.")
        progression = valid_progs[0]

    drum_style = overrides.get("drum_style")
    if drum_style is not None:
        drum_style = _v_drum_style(drum_style)
    else:
        drum_style = GENRES[genre]["drum_style"]

    energy_bias = MOOD_RULES[mood_v]["energy_bias"]
    energy_curve = overrides.get("energy_curve")
    if energy_curve is not None:
        energy_curve = _v_energy_curve(energy_curve)
    else:
        energy_curve = default_energy_curve(energy_bias, duration_v,
                                            GENRES[genre]["phrase_bars"])

    instruments = overrides.get("instruments")
    if instruments is not None:
        instruments = _v_instruments(instruments)
    else:
        instruments = list(GENRES[genre]["default_instruments"])

    feel = PROGRESSIONS[progression]["feel"]
    plan = Plan(
        genre=genre, key=key, mode=mode, bpm=bpm, progression=progression,
        drum_style=drum_style, energy_curve=energy_curve,
        instruments=instruments, duration=duration_v,
    )
    plan.rationale = (
        f"{genre} in {key} {mode} at {bpm} BPM, '{drum_style}' groove, "
        f"'{progression}' ({feel}) — for a {mood_v} feel."
        + (f" Prompt context: {prompt[:120]}" if prompt else ""))
    return plan


# ── §5 refine_beat ───────────────────────────────────────────────────────────

_FIELD_VALIDATORS = {
    "genre": lambda v: _v_genre(v),
    "key": lambda v: _v_key(v),
    "mode": lambda v: _v_mode(v),
    "bpm": lambda v: _v_bpm(v),
    "progression": lambda v: _v_progression(v),          # mode checked post-apply
    "drum_style": lambda v: _v_drum_style(v),
    "energy_curve": lambda v: _v_energy_curve(v),
    "instruments": lambda v: _v_instruments(v),
}


def refine_beat(plan: Plan, overrides: Dict) -> Plan:
    """Apply a structured delta onto an existing plan, then re-validate the whole
    plan (catches e.g. mode flips that strand the current progression).
    No NLP here — translating user text into overrides is the caller's job."""
    if not isinstance(plan, Plan):
        raise ToolError("refine_beat expects the full plan object returned by plan_beat")
    overrides = dict(overrides or {})
    _check_unknown_overrides(overrides)

    new_plan = Plan(**{**plan.__dict__})
    for field_name, value in overrides.items():
        if value is None:
            continue
        validated = _FIELD_VALIDATORS[field_name](value)
        setattr(new_plan, field_name, validated)

    # whole-plan consistency re-validation
    _v_genre(new_plan.genre)
    _v_key(new_plan.key)
    _v_mode(new_plan.mode)
    _v_bpm(new_plan.bpm)
    _v_duration(new_plan.duration)
    _v_drum_style(new_plan.drum_style)
    _v_energy_curve(new_plan.energy_curve)
    _v_instruments(new_plan.instruments)
    _v_progression(new_plan.progression, new_plan.mode)

    # genre↔style sanity warning is unnecessary (any style is playable), but
    # progression must belong to a mode consistent with plan.mode — enforced above.
    new_plan.rationale = f"{plan.rationale} | refined: {overrides}"
    return new_plan


# ── serialization (MCP transport) ────────────────────────────────────────────

def plan_to_dict(plan: Plan) -> Dict:
    d = dict(plan.__dict__)
    d["energy_curve"] = list(plan.energy_curve)
    d["instruments"] = list(plan.instruments)
    return d


def plan_from_dict(d: Dict) -> Plan:
    try:
        return Plan(
            genre=d["genre"], key=d["key"], mode=d["mode"], bpm=int(d["bpm"]),
            progression=d["progression"], drum_style=d["drum_style"],
            energy_curve=list(d["energy_curve"]), instruments=list(d["instruments"]),
            duration=float(d["duration"]), rationale=d.get("rationale", ""),
        )
    except KeyError as e:
        raise ToolError(f"plan object missing required field {e}. "
                        f"Required: genre, key, mode, bpm, progression, drum_style, "
                        f"energy_curve, instruments, duration.")
