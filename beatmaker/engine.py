
"""beatmaker engine — procedural loop-based MIDI generation (no AI)."""
from __future__ import annotations
import random, math, subprocess, shlex, hashlib, time
from pathlib import Path
import pretty_midi

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "output"
SF2_CANDIDATES = [
    Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"),
    Path("/usr/share/sounds/sf2/default.sf2"),
    REPO / "data/soundfont/FluidR3_GM.sf2",
]

INSTRUMENTS = {
    "drums": {"program": 0, "is_drum": True, "color": "#ff6b6b", "label": "Drums"},
    "bass":  {"program": 32, "is_drum": False, "color": "#4ecdc4", "label": "Bass"},
    "piano": {"program": 0, "is_drum": False, "color": "#ffe66d", "label": "Piano"},
    "guitar":{"program": 25, "is_drum": False, "color": "#a8e6cf", "label": "Guitar"},
    "synth": {"program": 81, "is_drum": False, "color": "#a78bfa", "label": "Synth Pad"},
}
GENRES = ["lofi","hiphop","trap","edm","chill","ambient","rock","jazz"]
SITUATIONS = ["study","workout","sleep","party","focus","travel","romantic","gaming","meditation","chill"]
MOODS = ["happy","chill","dark","energetic","melancholic","dreamy","aggressive"]
KEYS = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
MAJOR = [0,2,4,5,7,9,11]
MINOR = [0,2,3,5,7,8,10]

PROGRESSIONS = {
    "lofi":    [[0,3,5,4],[0,3,5,4],[5,3,0,4]],
    "hiphop":  [[0,5,3,4],[0,3,4,4]],
    "trap":    [[5,3,0,4],[5,5,3,4]],
    "edm":     [[0,4,5,3],[0,5,3,3]],
    "chill":   [[0,3,4,4],[5,3,0,0]],
    "ambient": [[0,3,5,2],[0,0,3,3]],
    "rock":    [[0,3,4,0],[0,4,3,4]],
    "jazz":    [[1,4,0,5],[5,4,1,0]],
}
SITUATION_DEFAULTS = {
    "study": {"genre":"lofi","bpm":82,"mood":"chill"},
    "workout": {"genre":"edm","bpm":128,"mood":"energetic"},
    "sleep": {"genre":"ambient","bpm":68,"mood":"dreamy"},
    "party": {"genre":"edm","bpm":126,"mood":"energetic"},
    "focus": {"genre":"chill","bpm":90,"mood":"chill"},
    "travel": {"genre":"chill","bpm":100,"mood":"happy"},
    "romantic": {"genre":"lofi","bpm":76,"mood":"melancholic"},
    "gaming": {"genre":"trap","bpm":140,"mood":"aggressive"},
    "meditation":{"genre":"ambient","bpm":60,"mood":"dreamy"},
    "chill": {"genre":"lofi","bpm":85,"mood":"chill"},
}

def _key_to_root(key: str) -> int:
    m = {"C":0,"C#":1,"D":2,"D#":3,"E":4,"F":5,"F#":6,"G":7,"G#":8,"A":9,"A#":10,"B":11}
    return m.get(key.upper(), 0)

def _chord_notes(root_midi: int, degree: int, scale: str, seventh=False):
    intervals = MAJOR if scale=="major" else MINOR
    base = root_midi + intervals[degree % 7] + 12*(degree//7)
    third = base + (4 if scale=="major" else 3)
    fifth = base + 7
    notes = [base, third, fifth]
    if seventh:
        notes.append(base+10 if degree==4 else base+11)
    return notes

def find_sf2():
    for p in SF2_CANDIDATES:
        if p.exists(): return p
    return None

def situation_bpm(sit): return SITUATION_DEFAULTS.get(sit, {}).get("bpm", 90)

def build_midi(duration, genre, situation, instruments, bpm=None, key="C", mood="chill", seed=None):
    random.seed(seed)
    genre = genre if genre in GENRES else "lofi"
    key = key if key in KEYS else "C"
    mood = mood if mood in MOODS else "chill"
    if bpm is None:
        bpm = situation_bpm(situation)
    bpm = max(60, min(180, int(bpm)))
    duration = max(10, min(300, int(duration)))
    scale = "minor" if mood in ("melancholic","dark","dreamy") else "major"
    if genre in ("ambient","lofi") and mood=="chill":
        scale="major"
    prog = random.choice(PROGRESSIONS[genre])
    root_pc = _key_to_root(key)
    root_midi = 48 + root_pc
    sec_per_beat = 60.0 / bpm
    sec_per_bar = sec_per_beat * 4
    n_bars = max(1, math.ceil(duration / sec_per_bar))
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    def add_inst(name, fn):
        cfg = INSTRUMENTS[name]
        inst = pretty_midi.Instrument(program=cfg["program"], is_drum=cfg["is_drum"], name=name)
        fn(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm)
        pm.instruments.append(inst)
    avail = [i for i in instruments if i in INSTRUMENTS]
    if not avail: avail = ["drums","bass","piano"]
    if "drums" in avail: add_inst("drums", _write_drums_factory(genre))
    if "bass" in avail: add_inst("bass", _write_bass)
    if "piano" in avail: add_inst("piano", _write_piano_factory(genre))
    if "guitar" in avail: add_inst("guitar", _write_guitar)
    if "synth" in avail: add_inst("synth", _write_synth_factory(mood))
    return pm, bpm, n_bars, sec_per_bar

def _write_drums_factory(genre):
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm):
        K,S,HH=36,38,42
        for bar in range(n_bars):
            base = bar*sec_per_bar
            beat = 60.0/bpm
            if genre=="edm":
                for b in range(4):
                    inst.notes.append(pretty_midi.Note(100, K, base+b*beat, base+b*beat+0.15))
                for b in [1,3]:
                    inst.notes.append(pretty_midi.Note(90, S, base+b*beat, base+b*beat+0.15))
                for i in range(8):
                    inst.notes.append(pretty_midi.Note(60, HH, base+i*beat*0.5, base+i*beat*0.5+0.08))
            elif genre=="trap":
                for off in [0, 0.75, 2.5]:
                    inst.notes.append(pretty_midi.Note(100, K, base+off*beat, base+off*beat+0.12))
                inst.notes.append(pretty_midi.Note(90, S, base+2*beat, base+2*beat+0.12))
                for i in range(16):
                    v=55 if i%2==0 else 45
                    if i in (8,9,10) and bar%2==0:
                        inst.notes.append(pretty_midi.Note(70, HH, base+i*beat*0.25, base+i*beat*0.25+0.05))
                        inst.notes.append(pretty_midi.Note(70, HH, base+i*beat*0.25+0.06, base+i*beat*0.25+0.11))
                    else:
                        inst.notes.append(pretty_midi.Note(v, HH, base+i*beat*0.25, base+i*beat*0.25+0.05))
            elif genre in ("lofi","chill","ambient"):
                inst.notes.append(pretty_midi.Note(100, K, base+0*beat, base+0*beat+0.2))
                inst.notes.append(pretty_midi.Note(95, K, base+1.5*beat, base+1.5*beat+0.15))
                inst.notes.append(pretty_midi.Note(90, S, base+1*beat, base+1*beat+0.15))
                inst.notes.append(pretty_midi.Note(85, S, base+3*beat, base+3*beat+0.15))
                for i in range(8):
                    swing = 0.07 if i%2==1 else 0
                    inst.notes.append(pretty_midi.Note(50, HH, base+i*beat*0.5+swing, base+i*beat*0.5+swing+0.05))
            else:
                for b in [0,1.5]:
                    inst.notes.append(pretty_midi.Note(100, K, base+b*beat, base+b*beat+0.15))
                for b in [1,3]:
                    inst.notes.append(pretty_midi.Note(90, S, base+b*beat, base+b*beat+0.15))
                for i in range(8):
                    inst.notes.append(pretty_midi.Note(60, HH, base+i*beat*0.5, base+i*beat*0.5+0.06))
            if bar==0:
                inst.notes.append(pretty_midi.Note(80, 49, base, base+0.8))
    return _write

def _write_bass(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm):
    for bar in range(n_bars):
        deg = prog[bar % len(prog)]
        chord = _chord_notes(root_midi, deg, scale)
        root = chord[0] - 12
        base = bar*sec_per_bar
        beat = 60.0/bpm
        inst.notes.append(pretty_midi.Note(95, root, base, base+beat*1.8))
        inst.notes.append(pretty_midi.Note(85, root, base+2*beat, base+3.9*beat))
        if bar%4==2:
            inst.notes.append(pretty_midi.Note(70, root+12, base+3*beat, base+3.5*beat))

def _write_piano_factory(genre):
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm):
        for bar in range(n_bars):
            deg = prog[bar % len(prog)]
            seventh = genre in ("lofi","jazz","chill","ambient")
            chord = _chord_notes(root_midi+12, deg, scale, seventh=seventh)
            base = bar*sec_per_bar
            beat = 60.0/bpm
            if genre in ("lofi","ambient","chill"):
                for i, n in enumerate(chord):
                    inst.notes.append(pretty_midi.Note(65, n, base+i*beat*0.5, base+i*beat*0.5+beat*0.45))
                for i, n in enumerate(reversed(chord)):
                    inst.notes.append(pretty_midi.Note(60, n+12, base+2*beat+i*beat*0.5, base+2*beat+i*beat*0.5+0.4))
            elif genre=="edm":
                for b in range(4):
                    for n in chord:
                        inst.notes.append(pretty_midi.Note(80, n, base+b*beat, base+b*beat+0.35))
            else:
                for b in [0,2]:
                    for n in chord:
                        inst.notes.append(pretty_midi.Note(75, n, base+b*beat, base+b*beat+beat*1.8))
    return _write

def _write_guitar(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm):
    for bar in range(n_bars):
        deg = prog[bar % len(prog)]
        chord = _chord_notes(root_midi+12, deg, scale)
        base = bar*sec_per_bar
        beat = 60.0/bpm
        notes = chord[:3]
        for i in range(8):
            offset = base + i*beat*0.5
            for j, n in enumerate(notes):
                stagger = j*0.015 if i%2==0 else (len(notes)-j)*0.015
                vel = 70 if i%2==0 else 60
                inst.notes.append(pretty_midi.Note(vel, n, offset+stagger, offset+stagger+0.3))

def _write_synth_factory(mood):
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm):
        for bar in range(n_bars):
            deg = prog[bar % len(prog)]
            chord = _chord_notes(root_midi+12, deg, scale, seventh=True)
            base = bar*sec_per_bar
            for n in chord:
                inst.notes.append(pretty_midi.Note(55, n+12, base, base+sec_per_bar-0.05))
            if mood=="energetic" and bar%2==0:
                lead = chord[1]+12
                inst.notes.append(pretty_midi.Note(75, lead, base+1.5*60.0/bpm, base+2.5*60.0/bpm))
    return _write

def render_midi(pm, midi_path, wav_path, mp3_path):
    midi_path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(midi_path))
    sf2 = find_sf2()
    wav_done=False
    # try python fluidsynth via pretty_midi
    try:
        y = pm.fluidsynth(fs=str(sf2) if sf2 else None)
        import soundfile as sf, numpy as np
        if y.ndim>1: y=y.mean(axis=0)
        peak = float(abs(y).max()) if y.size else 1
        if peak>0.01: y=y/peak*0.85
        sf.write(str(wav_path), y, 44100)
        wav_done=True
    except Exception as e:
        print(f"python fluidsynth fallback: {e}")
    if not wav_done:
        if sf2 and Path("/usr/bin/fluidsynth").exists():
            cmd = f"fluidsynth -ni -F {shlex.quote(str(wav_path))} {shlex.quote(str(sf2))} {shlex.quote(str(midi_path))} -r 44100"
            subprocess.run(cmd, shell=True, timeout=30)
            wav_done = wav_path.exists()
        if not wav_done:
            dur = pm.get_end_time()
            subprocess.run(f"ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t {dur:.1f} {shlex.quote(str(wav_path))} 2>/dev/null", shell=True, timeout=10)
    if wav_path.exists():
        subprocess.run(f"ffmpeg -y -i {shlex.quote(str(wav_path))} -codec:a libmp3lame -qscale:a 2 {shlex.quote(str(mp3_path))} 2>/dev/null", shell=True, timeout=15)
    return {"midi": str(midi_path), "wav": str(wav_path), "mp3": str(mp3_path), "sf2": str(sf2) if sf2 else None}

def generate_beat(duration=30, genre="lofi", situation="chill", instruments=None, bpm=None, mood="chill", key="C", seed=None):
    if instruments is None: instruments = ["drums","bass","piano"]
    duration = int(duration)
    genre = str(genre).lower()
    situation = str(situation).lower()
    key = str(key).upper()
    mood = str(mood).lower()
    if genre not in GENRES:
        genre = SITUATION_DEFAULTS.get(situation, {}).get("genre","lofi")
    pm, eff_bpm, n_bars, _ = build_midi(duration, genre, situation, instruments, bpm, key, mood, seed)
    h = hashlib.md5(f"{genre}_{situation}_{key}_{eff_bpm}_{duration}_{seed}_{instruments}".encode()).hexdigest()[:6]
    stem = f"beat_{int(time.time())}_{h}"
    midi_path = OUT / f"{stem}.mid"
    wav_path = OUT / f"{stem}.wav"
    mp3_path = OUT / f"{stem}.mp3"
    outs = render_midi(pm, midi_path, wav_path, mp3_path)
    return {"stem": stem, "genre": genre, "situation": situation, "key": key, "bpm": eff_bpm,
            "duration": duration, "instruments": instruments, "mood": mood,
            "files": outs, "bars": n_bars}
