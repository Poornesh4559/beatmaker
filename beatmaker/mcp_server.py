"""beatmaker MCP server — loop-based procedural beats."""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional
from fastmcp import FastMCP
from beatmaker.engine import INSTRUMENTS, GENRES, SITUATIONS, MOODS, KEYS, SITUATION_DEFAULTS, PROGRESSIONS, generate_beat as engine_generate

mcp = FastMCP("beatmaker", instructions=(
    "Loop-based beatmaker. Call generate_beat to produce MIDI+WAV+MP3. "
    "For max variation, vary progression_idx (0-5 per genre) and per-instrument variants drums/bass/piano/guitar/synth (0-2 each). "
    "Use list_variants + list_progressions to discover options."
))

@mcp.tool
def generate_beat(duration: int = 30, genre: str = "lofi", situation: str = "chill",
                  instruments: Optional[List[str]] = None, bpm: Optional[int] = None,
                  mood: str = "chill", key: str = "C", seed: Optional[int] = None,
                  drums_variant: Optional[int] = None, bass_variant: Optional[int] = None,
                  piano_variant: Optional[int] = None, guitar_variant: Optional[int] = None,
                  synth_variant: Optional[int] = None, progression_idx: Optional[int] = None) -> dict:
    """Generate a beat and render to MIDI/WAV/MP3.

    duration 10-300s, genre lofi/hiphop/trap/edm/chill/ambient/rock/jazz,
    situation study/workout/sleep/party/focus/travel/romantic/gaming/meditation/chill,
    instruments subset of [drums,bass,piano,guitar,synth] (max 5), bpm 60-180 (or None=auto),
    mood happy/chill/dark/energetic/melancholic/dreamy/aggressive, key C..B, seed optional for reproducibility.
    VARIATION KNOBS (new): progression_idx 0-5 (chord progression per genre), drums/bass/piano/guitar/synth variant 0-2 each
      (0=strict, 1=groovy, 2=busy — varies drum fills, bass walk, piano arps, guitar strum). Leave None for random.
    Returns {stem, genre, situation, key, bpm, duration, instruments, mood, bars, variants:{drums,bass,piano,guitar,synth,progression_idx}, files:{midi,wav,mp3,sf2}}.
    """
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
    """List the 5 locked instruments with program and color."""
    return {"instruments": INSTRUMENTS, "max": 5}

@mcp.tool
def list_options() -> dict:
    """List all valid genres, situations, moods, keys, and situation->defaults."""
    return {"genres": GENRES, "situations": SITUATIONS, "moods": MOODS, "keys": KEYS, "defaults": SITUATION_DEFAULTS}

@mcp.tool
def list_variants() -> dict:
    """List per-instrument variant knobs the LLM can set for variation.

    Each instrument has variants 0/1/2:
    - drums: 0=straight, 1=syncopated/claps, 2=busy/fills (EDM) / 0=boom-bap,1=rim,2=half-time (lofi) etc per genre.
    - bass: 0=steady roots, 1=syncopated, 2=walking.
    - piano: 0=arp, 1=block, 2=sparse (lofi) / 0=block,1=stab,2=octaves (hiphop) etc.
    - guitar: 0=strum16, 1=fingerpick, 2=mutes.
    - synth: 0=pad, 1=arp, 2=pulse+lead.
    Use None for random; set 0-2 to pin a feel. Combine with progression_idx for max variation.
    """
    return {
        "variants": {
            "drums_variant": {"0": "straight/boom", "1": "syncopated/rim", "2": "busy/fill"},
            "bass_variant": {"0": "roots", "1": "syncopated", "2": "walking"},
            "piano_variant": {"0": "arp/block", "1": "block/stab", "2": "sparse/octaves"},
            "guitar_variant": {"0": "strum", "1": "fingerpick", "2": "mutes"},
            "synth_variant": {"0": "pad", "1": "arp", "2": "pulse"},
        },
        "range": [0,1,2],
        "tip": "Random None gives variation; pin to explore a specific feel. The prompt endpoint lets LLM pick these."
    }

@mcp.tool
def list_progressions(genre: Optional[str] = None) -> dict:
    """List chord progressions per genre. Each genre has 6 progressions (idx 0-5), degrees over major/minor scale."""
    if genre and genre in PROGRESSIONS:
        return {"genre": genre, "progressions": {str(i): prog for i, prog in enumerate(PROGRESSIONS[genre])}, "count": len(PROGRESSIONS[genre])}
    return {"progressions": {g: {str(i): prog for i, prog in enumerate(progs)} for g, progs in PROGRESSIONS.items()}}

@mcp.tool
def preview_info(duration: int = 30, genre: str = "lofi", situation: str = "chill", key: str = "C", bpm: Optional[int] = None) -> dict:
    """Preview what a beat would sound like without rendering (returns resolved params + bars)."""
    from beatmaker.engine import situation_bpm, build_midi
    genre = genre if genre in GENRES else SITUATION_DEFAULTS.get(situation, {}).get("genre","lofi")
    eff_bpm = bpm if bpm is not None else situation_bpm(situation)
    pm, eff_bpm2, n_bars, spb, _ = build_midi(duration, genre, situation, ["drums","bass","piano"], eff_bpm, key, "chill", None)
    return {"genre": genre, "situation": situation, "bpm": eff_bpm2, "key": key, "bars": n_bars, "sec_per_bar": spb, "total_sec": n_bars*spb}

if __name__ == "__main__":
    mcp.run()
