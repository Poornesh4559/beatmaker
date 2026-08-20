# beatmaker 🎵

Loop-based procedural beat studio — **no AI**. Turn duration + genre + situation + mood + key + instruments(5) → MIDI → FluidSynth → WAV/MP3. Play in browser + download. MCP-native.

```
User form → FastAPI → engine (pretty_midi + FluidSynth) → /output/*.mp3 (play + download)
LLM → MCP tools (generate_beat, list_instruments, list_options, preview_info) → same engine
```

## Quick start

```bash
# web studio (token in ~/.hermes/.env as BEATMAKER_TOKEN)
PYTHONPATH=/home/ubuntu/beatmaker .venv/bin/uvicorn beatmaker.web_server:app --host 127.0.0.1 --port 8767

# MCP over stdio
PYTHONPATH=/home/ubuntu/beatmaker .venv/bin/python -m beatmaker.mcp_server
# MCP over HTTP
http://127.0.0.1:8767/mcp  (when web server is running)
```

Open `http://127.0.0.1:8767/?token=YOUR_TOKEN` — dark studio UI.

## MCP tools

| Tool | Args | Returns |
|------|------|---------|
| `generate_beat` | `duration 10-300, genre, situation, instruments[≤5], bpm 60-180?, mood, key, seed?` | `{stem, genre, situation, key, bpm, duration, instruments, mood, bars, files:{midi,wav,mp3,sf2}}` |
| `list_instruments` | — | 5 locked instruments |
| `list_options` | — | genres / situations / moods / keys / defaults |
| `preview_info` | `duration, genre, situation, key, bpm?` | resolved params + bars without rendering |

## 5 Instruments (locked)

- **drums** (kit), **bass** (32), **piano** (0), **guitar** (25 steel), **synth** (81 sawtooth) — colors: #ff6b6b #4ecdc4 #ffe66d #a8e6cf #a78bfa

## Inputs

- **duration** 10–300s, **genre** lofi/hiphop/trap/edm/chill/ambient/rock/jazz, **situation** study/workout/sleep/party/focus/travel/romantic/gaming/meditation/chill (auto-sets bpm+mood), **mood** happy/chill/dark/energetic/melancholic/dreamy/aggressive (minor vs major), **key** C..B, **bpm** 60–180 or auto, **seed** for reproducibility.
- Progression + drum pattern selected by genre; situation defaults fill bpm/genre/mood; scale switches minor for dark/dreamy/melancholic.

## Engine

- `pretty_midi` + `FluidR3_GM.sf2` (142 MB at `/usr/share/sounds/sf2/FluidR3_GM.sf2`) via `fluidsynth` binary. Fallback chain: python fluidsynth → binary → silence.
- Patterns: EDM 4-on-floor, trap sparse kick + hat rolls, lofi boom-bap swing, hiphop/rock kit. Bass roots, piano arps/blocks/stabs, guitar 16th strums, synth pad + energetic lead.
- `output/*.mid|wav|mp3` — gitignored.
