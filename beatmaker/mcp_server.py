
"""beatmaker MCP server — loop-based procedural beats."""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional
from fastmcp import FastMCP
from beatmaker.engine import INSTRUMENTS, GENRES, SITUATIONS, MOODS, KEYS, SITUATION_DEFAULTS, generate_beat as engine_generate

mcp = FastMCP("beatmaker", instructions="Loop-based beatmaker. Call generate_beat to produce MIDI+WAV+MP3. No AI — procedural patterns.")

@mcp.tool
def generate_beat(duration: int = 30, genre: str = "lofi", situation: str = "chill",
                  instruments: Optional[List[str]] = None, bpm: Optional[int] = None,
                  mood: str = "chill", key: str = "C", seed: Optional[int] = None) -> dict:
    """Generate a beat and render to MIDI/WAV/MP3.

    duration 10-300s, genre lofi/hiphop/trap/edm/chill/ambient/rock/jazz,
    situation study/workout/sleep/party/focus/travel/romantic/gaming/meditation/chill,
    instruments subset of [drums,bass,piano,guitar,synth] (max 5), bpm 60-180 (or None=auto from situation),
    mood happy/chill/dark/energetic/melancholic/dreamy/aggressive, key C..B, seed optional int for reproducibility.
    Returns {stem, genre, situation, key, bpm, duration, instruments, mood, bars, files:{midi,wav,mp3,sf2}}.
    """
    if instruments is None: instruments = ["drums","bass","piano"]
    # clamp instruments to 5 valid
    instruments = [i for i in instruments if i in INSTRUMENTS][:5]
    if not instruments: instruments = ["drums","bass","piano"]
    return engine_generate(duration=duration, genre=genre, situation=situation,
                           instruments=instruments, bpm=bpm, mood=mood, key=key, seed=seed)

@mcp.tool
def list_instruments() -> dict:
    """List the 5 locked instruments with program and color."""
    return {"instruments": INSTRUMENTS, "max": 5}

@mcp.tool
def list_options() -> dict:
    """List all valid genres, situations, moods, keys, and situation->defaults."""
    return {"genres": GENRES, "situations": SITUATIONS, "moods": MOODS, "keys": KEYS, "defaults": SITUATION_DEFAULTS}

@mcp.tool
def preview_info(duration: int = 30, genre: str = "lofi", situation: str = "chill", key: str = "C", bpm: Optional[int] = None) -> dict:
    """Preview what a beat would sound like without rendering (returns resolved params + bars)."""
    from beatmaker.engine import situation_bpm, build_midi
    genre = genre if genre in GENRES else SITUATION_DEFAULTS.get(situation, {}).get("genre","lofi")
    eff_bpm = bpm if bpm is not None else situation_bpm(situation)
    pm, eff_bpm2, n_bars, spb = build_midi(duration, genre, situation, ["drums","bass","piano"], eff_bpm, key, "chill", None)
    return {"genre": genre, "situation": situation, "bpm": eff_bpm2, "key": key, "bars": n_bars, "sec_per_bar": spb, "total_sec": n_bars*spb}

if __name__ == "__main__":
    mcp.run()
