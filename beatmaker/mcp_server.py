"""beatmaker MCP server — v2 plan→render + legacy v1 tools (Phase 4).

4 new tools (spec §2) are the primary surface: get_music_vocabulary, plan_beat,
render_beat, refine_beat. The old 6 remain registered but the web flow will
stop calling them in Phase 5.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Any

from fastmcp import FastMCP

from beatmaker.vocabulary import GENRES, DRUM_STYLES, PROGRESSIONS, MOOD_RULES
from beatmaker.planning import (
    Plan, ToolError as PlanningToolError,
    plan_beat as planning_plan_beat,
    refine_beat as planning_refine_beat,
    plan_to_dict, plan_from_dict,
)
from beatmaker.render_beat import render_beat as v2_render_beat

# legacy v1 imports (kept, unused by v2 flow)
from beatmaker.engine import (
    INSTRUMENTS, GENRES as V1_GENRES, SITUATIONS, MOODS, KEYS,
    SITUATION_DEFAULTS, PROGRESSIONS as V1_PROGRESSIONS,
    generate_beat as engine_generate,
)

mcp = FastMCP("beatmaker", instructions=(
    "Beatmaker v2. Call get_music_vocabulary() once, then plan_beat(prompt, "
    "mood, duration) to build a Plan, and render_beat(plan) to produce "
    "MIDI+WAV+MP3. For refinements, translate user text into structured "
    "overrides and call refine_beat(plan, overrides) before re-rendering."
))

# ── v2 — primary surface (spec §2) ─────────────────────────────────────────

@mcp.tool
def get_music_vocabulary() -> dict:
    """One-call grounding for the LLM: returns genres, drum styles,
    progressions, and mood rules with names + one-line descriptions.
    Call once per session before any plan_beat.
    """
    return {
        "genres": {
            g: {
                "bpm_range": cfg["bpm_range"],
                "drum_style": cfg["drum_style"],
                "phrase_bars": cfg["phrase_bars"],
                "default_instruments": cfg["default_instruments"],
                "progressions": cfg["progressions"],
            }
            for g, cfg in GENRES.items()
        },
        "drum_styles": {
            s: {"grid": {k: v for k, v in cfg.items() if k != "desc"}, "desc": cfg["desc"]}
            for s, cfg in DRUM_STYLES.items()
        },
        "progressions": {
            name: {"degrees": cfg["degrees"], "mode": cfg["mode"], "feel": cfg["feel"]}
            for name, cfg in PROGRESSIONS.items()
        },
        "moods": MOOD_RULES,
    }


@mcp.tool
def plan_beat(prompt: str, mood: str, duration: float,
              overrides: Optional[Dict[str, Any]] = None) -> dict:
    """Build a fully-resolved Plan from semantic choices (LLM-picked, user-pinned).

    mood is required (sets mode + genre defaults). duration is seconds (4-600).
    overrides may include: genre, key, mode, bpm, progression, drum_style,
    energy_curve, instruments. All cross-validated; every rejection names the
    bad field and lists valid values.

    Returns the Plan as a plain dict — pass it to render_beat().
    """
    try:
        plan = planning_plan_beat(prompt=prompt, mood=mood,
                                  duration=duration, overrides=overrides)
        return plan_to_dict(plan)
    except PlanningToolError as e:
        return {"error": str(e)}


@mcp.tool
def render_beat(plan: Dict) -> dict:
    """Deterministic render of a plan (no LLM discretion inside).
    plan must be the dict returned by plan_beat/refine_beat.
    Returns {files:{mid,wav,mp3}, musical_summary, pattern_preview}.
    """
    try:
        p = plan_from_dict(plan)
        return v2_render_beat(p)
    except PlanningToolError as e:
        return {"error": str(e)}


@mcp.tool
def refine_beat(plan: Dict, overrides: Dict) -> dict:
    """Apply structured deltas onto an existing plan.
    Does no NLP — the caller must translate user text like 'make it darker'
    into fields before calling (e.g. {'mood':'dark'} or
    {'energy_curve':['low','low','low','med']}).
    Returns the updated Plan dict; caller re-renders via render_beat().
    """
    try:
        p = plan_from_dict(plan)
        new_plan = planning_refine_beat(p, overrides or {})
        return plan_to_dict(new_plan)
    except PlanningToolError as e:
        return {"error": str(e)}


# ── legacy v1 — kept registered, unused by v2 web flow ──────────────────────

@mcp.tool
def generate_beat(duration: int = 30, genre: str = "lofi", situation: str = "chill",
                  instruments: Optional[List[str]] = None, bpm: Optional[int] = None,
                  mood: str = "chill", key: str = "C", seed: Optional[int] = None,
                  drums_variant: Optional[int] = None, bass_variant: Optional[int] = None,
                  piano_variant: Optional[int] = None, guitar_variant: Optional[int] = None,
                  synth_variant: Optional[int] = None, progression_idx: Optional[int] = None) -> dict:
    """Legacy v1 single-call render. Prefer plan_beat → render_beat."""
    if instruments is None: instruments = ["drums","bass","piano"]
    instruments = [i for i in instruments if i in INSTRUMENTS][:5]
    if not instruments: instruments = ["drums","bass","piano"]
    return engine_generate(duration=duration, genre=genre, situation=situation,
                           instruments=instruments, bpm=bpm, mood=mood, key=key, seed=seed,
                           drums_variant=drums_variant, bass_variant=bass_variant,
                           piano_variant=piano_variant, guitar_variant=guitar_variant,
                           synth_variant=synth_variant, progression_idx=progression_idx)

@mcp.tool
def list_instruments() -> dict:
    """Legacy: list the 5 locked instruments."""
    return {"instruments": INSTRUMENTS, "max": 5}

@mcp.tool
def list_options() -> dict:
    """Legacy: list v1 genres/situations/moods/keys/defaults."""
    return {"genres": V1_GENRES, "situations": SITUATIONS, "moods": MOODS, "keys": KEYS, "defaults": SITUATION_DEFAULTS}

@mcp.tool
def list_variants() -> dict:
    """Legacy: per-instrument variant knobs (0-2 each)."""
    return {
        "variants": {
            "drums_variant": {"0": "straight/boom", "1": "syncopated/rim", "2": "busy/fill"},
            "bass_variant": {"0": "roots", "1": "syncopated", "2": "walking"},
            "piano_variant": {"0": "arp/block", "1": "block/stab", "2": "sparse/octaves"},
            "guitar_variant": {"0": "strum", "1": "fingerpick", "2": "mutes"},
            "synth_variant": {"0": "pad", "1": "arp", "2": "pulse"},
        }, "range": [0,1,2],
    }

@mcp.tool
def list_progressions(genre: Optional[str] = None) -> dict:
    """Legacy: list v1 indexed progressions."""
    if genre and genre in V1_PROGRESSIONS:
        return {"genre": genre, "progressions": {str(i): prog for i, prog in enumerate(V1_PROGRESSIONS[genre])}, "count": len(V1_PROGRESSIONS[genre])}
    return {"progressions": {g: {str(i): prog for i, prog in enumerate(progs)} for g, progs in V1_PROGRESSIONS.items()}}

@mcp.tool
def preview_info(duration: int = 30, genre: str = "lofi", situation: str = "chill", key: str = "C", bpm: Optional[int] = None) -> dict:
    """Legacy: bar preview without rendering."""
    from beatmaker.engine import situation_bpm, build_midi
    genre = genre if genre in V1_GENRES else SITUATION_DEFAULTS.get(situation, {}).get("genre","lofi")
    eff_bpm = bpm if bpm is not None else situation_bpm(situation)
    pm, eff_bpm2, n_bars, spb, _ = build_midi(duration, genre, situation, ["drums","bass","piano"], eff_bpm, key, "chill", None)
    return {"genre": genre, "situation": situation, "bpm": eff_bpm2, "key": key, "bars": n_bars, "sec_per_bar": spb, "total_sec": n_bars*spb}

if __name__ == "__main__":
    mcp.run()
