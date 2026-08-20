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

# Expanded: 5-6 distinct progressions per genre
PROGRESSIONS = {
    "lofi":    [[0,3,5,4],[5,3,0,4],[0,5,3,4],[3,5,0,4],[0,4,5,3],[1,4,0,5]],
    "hiphop":  [[0,5,3,4],[0,3,4,4],[5,3,4,0],[0,4,3,5],[3,5,4,0],[0,3,5,2]],
    "trap":    [[5,3,0,4],[5,5,3,4],[0,5,3,4],[5,0,3,4],[3,5,0,2],[0,3,2,4]],
    "edm":     [[0,4,5,3],[0,5,3,3],[4,5,0,3],[5,3,0,4],[0,3,4,5],[3,0,4,5]],
    "chill":   [[0,3,4,4],[5,3,0,0],[0,4,3,5],[3,0,5,4],[0,5,4,3],[4,3,0,5]],
    "ambient": [[0,3,5,2],[0,0,3,3],[3,5,0,2],[0,4,2,5],[5,3,2,0],[0,5,3,2]],
    "rock":    [[0,3,4,0],[0,4,3,4],[4,0,3,5],[0,5,4,3],[3,4,0,5],[5,0,4,3]],
    "jazz":    [[1,4,0,5],[5,4,1,0],[1,5,0,3],[0,1,4,5],[3,5,1,4],[1,0,4,3]],
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

def _human_vel(base: int, rng, jitter=8):
    return max(20, min(127, base + rng.randint(-jitter, jitter)))

def _human_time(t: float, rng, jitter=0.015):
    return max(0, t + rng.uniform(-jitter, jitter))

def build_midi(duration, genre, situation, instruments, bpm=None, key="C", mood="chill", seed=None,
             drums_variant: int | None = None, bass_variant: int | None = None,
             piano_variant: int | None = None, guitar_variant: int | None = None,
             synth_variant: int | None = None, progression_idx: int | None = None):
    rng = random.Random(seed) if seed is not None else random.Random()
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
    # progression: LLM can pin it, else random
    if progression_idx is not None and 0 <= progression_idx < len(PROGRESSIONS[genre]):
        prog = PROGRESSIONS[genre][progression_idx]
    else:
        prog = rng.choice(PROGRESSIONS[genre])
    # occasionally randomize one chord for variation (10% bars get substitute)
    root_pc = _key_to_root(key)
    root_midi = 48 + root_pc
    sec_per_beat = 60.0 / bpm
    sec_per_bar = sec_per_beat * 4
    n_bars = max(1, math.ceil(duration / sec_per_bar))
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    # resolve variants: LLM pin or rng pick, exposed in return for caller
    dv = drums_variant if drums_variant in (0,1,2) else rng.randint(0,2)
    bv = bass_variant if bass_variant in (0,1,2) else rng.randint(0,2)
    gv = guitar_variant if guitar_variant in (0,1,2) else rng.randint(0,2)
    pv = piano_variant if piano_variant in (0,1,2) else rng.randint(0,2)
    sv = synth_variant if synth_variant in (0,1,2) else rng.randint(0,2)
    prog_idx_used = PROGRESSIONS[genre].index(prog) if prog in PROGRESSIONS[genre] else 0
    chosen = {"drums": dv, "bass": bv, "piano": pv, "guitar": gv, "synth": sv, "progression_idx": prog_idx_used}
    def add_inst(name, fn):
        cfg = INSTRUMENTS[name]
        inst = pretty_midi.Instrument(program=cfg["program"], is_drum=cfg["is_drum"], name=name)
        fn(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng)
        pm.instruments.append(inst)
    avail = [i for i in instruments if i in INSTRUMENTS]
    if not avail: avail = ["drums","bass","piano"]
    if "drums" in avail: add_inst("drums", _write_drums_factory(genre, rng, dv))
    if "bass" in avail: add_inst("bass", lambda inst, spb, nb, prog, rm, sc, bpm, rng=rng, _bv=bv: _write_bass(inst, spb, nb, prog, rm, sc, bpm, rng, _bv))
    if "piano" in avail: add_inst("piano", _write_piano_factory(genre, rng, pv))
    if "guitar" in avail: add_inst("guitar", lambda inst, spb, nb, prog, rm, sc, bpm, rng=rng, _gv=gv: _write_guitar(inst, spb, nb, prog, rm, sc, bpm, rng, _gv))
    if "synth" in avail: add_inst("synth", _write_synth_factory(mood, rng, sv))
    return pm, bpm, n_bars, sec_per_bar, chosen

def _write_drums_factory(genre, rng, variant_override=None):
    # variant can be pinned by LLM, else captured rng pick
    variant = variant_override if variant_override is not None else rng.randint(0, 2)
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng_inner=None):
        rng2 = rng_inner or rng
        K,S,HH,OH,CR=36,38,42,46,49
        # velocity base varies by mood via genre
        for bar in range(n_bars):
            base = bar*sec_per_bar
            beat = 60.0/bpm
            is_fill_bar = (bar+1) % 4 == 0 and bar != 0
            swing = rng2.uniform(0.02, 0.08) if genre in ("lofi","chill") else 0
            if genre=="edm":
                if variant==0:  # four-on-floor
                    for b in range(4):
                        inst.notes.append(pretty_midi.Note(_human_vel(102,rng2,6), K, _human_time(base+b*beat,rng2,0.01), _human_time(base+b*beat+0.15,rng2,0.01)))
                    for b in [1,3]:
                        inst.notes.append(pretty_midi.Note(_human_vel(92,rng2,6), S, _human_time(base+b*beat,rng2,0.012), _human_time(base+b*beat+0.13,rng2,0.01)))
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(_human_vel(58,rng2,8), HH, base+i*beat*0.5, base+i*beat*0.5+0.07))
                elif variant==1:  # off-beat hats, claps
                    for b in range(4):
                        inst.notes.append(pretty_midi.Note(100, K, base+b*beat, base+b*beat+0.14))
                    inst.notes.append(pretty_midi.Note(92, 39, base+1*beat, base+1*beat+0.12))  # clap
                    inst.notes.append(pretty_midi.Note(88, S, base+3*beat, base+3*beat+0.12))
                    for i in range(8):
                        vel = 62 if i%2==0 else 38
                        inst.notes.append(pretty_midi.Note(vel, HH if i%4!=3 else OH, base+i*beat*0.5, base+i*beat*0.5+0.06))
                else:  # syncopated
                    for b in [0, 1.3, 2, 3.5]:
                        inst.notes.append(pretty_midi.Note(_human_vel(100,rng2,5), K, base+b*beat, base+b*beat+0.13))
                    for b in [1, 3]:
                        inst.notes.append(pretty_midi.Note(90, S, base+b*beat, base+b*beat+0.13))
                    for i in range(16):
                        inst.notes.append(pretty_midi.Note(rng2.randint(42,58), HH, base+i*beat*0.25, base+i*beat*0.25+0.04))
            elif genre=="trap":
                # variant affects kick placement and hat rolls
                kicks = [[0,0.75,2.5],[0,1.1,2,3.3],[0,0.5,2.5,3.75]][variant]
                for off in kicks:
                    inst.notes.append(pretty_midi.Note(_human_vel(102,rng2,5), K, _human_time(base+off*beat,rng2,0.012), base+off*beat+0.12))
                inst.notes.append(pretty_midi.Note(92, S, base+2*beat, base+2*beat+0.12))
                if is_fill_bar and rng2.random() < 0.5:
                    inst.notes.append(pretty_midi.Note(85, S, base+3.5*beat, base+3.5*beat+0.1))
                # hat pattern varies
                if variant==0:
                    for i in range(16):
                        v=58 if i%2==0 else 44
                        inst.notes.append(pretty_midi.Note(v, HH, base+i*beat*0.25, base+i*beat*0.25+0.04))
                        if i in (10,11) and rng2.random()<0.6:
                            inst.notes.append(pretty_midi.Note(70, HH, base+i*beat*0.25+0.06, base+i*beat*0.25+0.1))
                elif variant==1:  # triplet hats
                    for i in range(12):
                        inst.notes.append(pretty_midi.Note(rng2.randint(45,62), HH, base+i*beat*(1/3), base+i*beat*(1/3)+0.04))
                else:  # sparse with rolls
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(55, HH, base+i*beat*0.5, base+i*beat*0.5+0.05))
                    # roll at end
                    if rng2.random()<0.7:
                        for r in range(6):
                            inst.notes.append(pretty_midi.Note(68, HH, base+3*beat+r*0.06, base+3*beat+r*0.06+0.03))
            elif genre in ("lofi","chill","ambient"):
                v = variant  # 0 boom bap, 1 brushed, 2 rim
                if v==0:
                    inst.notes.append(pretty_midi.Note(_human_vel(100,rng2,4), K, base+0*beat, base+0*beat+0.2))
                    if rng2.random()<0.7:
                        inst.notes.append(pretty_midi.Note(90, K, base+1.5*beat, base+1.5*beat+0.15))
                    inst.notes.append(pretty_midi.Note(88, S, base+1*beat, base+1*beat+0.15))
                    inst.notes.append(pretty_midi.Note(84, S, base+3*beat, base+3*beat+0.15))
                    for i in range(8):
                        sw = swing if i%2==1 else 0
                        inst.notes.append(pretty_midi.Note(_human_vel(48,rng2,6), HH, base+i*beat*0.5+sw, base+i*beat*0.5+sw+0.05))
                elif v==1:  # softer, rim + shaker
                    inst.notes.append(pretty_midi.Note(88, K, base, base+0.18))
                    inst.notes.append(pretty_midi.Note(72, 37, base+1*beat, base+1*beat+0.12))  # rim
                    inst.notes.append(pretty_midi.Note(80, 38, base+3*beat, base+3*beat+0.14))
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(rng2.randint(38,52), 42 if i%2==0 else 44, base+i*beat*0.5+rng2.uniform(-0.01,0.02), base+i*beat*0.5+0.04))
                else:  # half-time
                    inst.notes.append(pretty_midi.Note(96, K, base, base+0.22))
                    inst.notes.append(pretty_midi.Note(86, S, base+2*beat, base+2*beat+0.16))
                    for i in range(4):
                        inst.notes.append(pretty_midi.Note(44, HH, base+i*beat, base+i*beat+0.06))
                        if rng2.random()<0.3:
                            inst.notes.append(pretty_midi.Note(42, HH, base+i*beat+0.5*beat, base+i*beat+0.5*beat+0.04))
                if is_fill_bar and rng2.random()<0.4:
                    # ghost snare fill
                    for f in [3.25, 3.5, 3.75]:
                        inst.notes.append(pretty_midi.Note(rng2.randint(55,75), S, base+f*beat, base+f*beat+0.08))
            elif genre=="hiphop":
                patterns = [[[0,1.5],[1,3]], [[0,2],[1,3]], [[0,0.75,2],[1,3]]][variant]
                k_pos, s_pos = patterns
                for b in k_pos:
                    inst.notes.append(pretty_midi.Note(_human_vel(100,rng2,5), K, _human_time(base+b*beat,rng2,0.015), base+b*beat+0.15))
                for b in s_pos:
                    inst.notes.append(pretty_midi.Note(90, S, _human_time(base+b*beat,rng2,0.01), base+b*beat+0.15))
                for i in range(8):
                    inst.notes.append(pretty_midi.Note(rng2.randint(48,64), HH, base+i*beat*0.5+rng2.uniform(-0.008,0.008), base+i*beat*0.5+0.06))
                if is_fill_bar:
                    inst.notes.append(pretty_midi.Note(70, 47, base+3.75*beat, base+3.75*beat+0.07))
            elif genre=="rock":
                # variants: straight, half-time, punk
                if variant==0:
                    for b in [0,1,2,3]:
                        inst.notes.append(pretty_midi.Note(102, K, base+b*beat, base+b*beat+0.13))
                        if b%2==1:
                            inst.notes.append(pretty_midi.Note(94, S, base+b*beat, base+b*beat+0.13))
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(62, HH, base+i*beat*0.5, base+i*beat*0.5+0.06))
                elif variant==1:
                    inst.notes.append(pretty_midi.Note(100, K, base, base+0.16))
                    inst.notes.append(pretty_midi.Note(100, K, base+2*beat, base+2*beat+0.16))
                    inst.notes.append(pretty_midi.Note(96, S, base+1*beat, base+1*beat+0.14))
                    inst.notes.append(pretty_midi.Note(96, S, base+3*beat, base+3*beat+0.14))
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(70, CR if i==0 else HH, base+i*beat*0.5, base+i*beat*0.5+0.08))
                else:
                    for b in [0,0.5,1,1.5,2,2.5,3,3.5]:
                        inst.notes.append(pretty_midi.Note(92, K if b%1==0 else S, base+b*beat, base+b*beat+0.1))
                    for i in range(8):
                        inst.notes.append(pretty_midi.Note(76, OH, base+i*beat*0.5, base+i*beat*0.5+0.07))
                if bar==0:
                    inst.notes.append(pretty_midi.Note(90, CR, base, base+0.9))
                continue
            elif genre=="jazz":
                # swing, brushes, ride
                for b in [0, 1.5]:
                    inst.notes.append(pretty_midi.Note(88, K, base+b*beat, base+b*beat+0.14))
                inst.notes.append(pretty_midi.Note(80, S, base+1*beat, base+1*beat+0.13))
                if variant==2 and rng2.random()<0.5:
                    inst.notes.append(pretty_midi.Note(64, S, base+2.5*beat, base+2.5*beat+0.1))  # ghost
                # ride pattern with swing
                for i in range(4):
                    # ding ding-a-ding
                    inst.notes.append(pretty_midi.Note(62, 51, base+i*beat, base+i*beat+0.18))
                    inst.notes.append(pretty_midi.Note(48, 51, base+i*beat+0.67*beat, base+i*beat+0.67*beat+0.1))
                    if variant==1:
                        inst.notes.append(pretty_midi.Note(42, HH, base+i*beat+0.33*beat, base+i*beat+0.33*beat+0.05))
            else:
                for b in [0,1.5]:
                    inst.notes.append(pretty_midi.Note(100, K, base+b*beat, base+b*beat+0.15))
                for b in [1,3]:
                    inst.notes.append(pretty_midi.Note(90, S, base+b*beat, base+b*beat+0.15))
                for i in range(8):
                    inst.notes.append(pretty_midi.Note(60, HH, base+i*beat*0.5, base+i*beat*0.5+0.06))
            if bar==0 and genre not in ("rock",):
                # crash only once, but vary vel
                inst.notes.append(pretty_midi.Note(rng2.randint(76,88), CR, base, base+0.8))
            # fill variation
            if is_fill_bar and genre in ("hiphop","trap","edm","rock") and rng2.random()<0.5:
                # quick fill
                for f in [3.5, 3.75]:
                    inst.notes.append(pretty_midi.Note(rng2.randint(68,88), 41 if genre=="rock" else S, base+f*beat, base+f*beat+0.09))
    return _write

def _write_bass(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng, variant_override=None):
    variant = variant_override if variant_override is not None else rng.randint(0,2)
    for bar in range(n_bars):
        deg = prog[bar % len(prog)]
        # 5% chance of chromatic passing chord
        if rng.random() < 0.08 and bar>0:
            deg = rng.choice([d for d in range(7) if d != deg])
        chord = _chord_notes(root_midi, deg, scale)
        root = chord[0] - 12
        fifth = root + 7
        base = bar*sec_per_bar
        beat = 60.0/bpm
        if variant==0:  # steady roots
            inst.notes.append(pretty_midi.Note(_human_vel(96,rng,5), root, _human_time(base,rng,0.012), base+beat*1.85))
            # sometimes walk to fifth
            if rng.random()<0.5:
                inst.notes.append(pretty_midi.Note(_human_vel(86,rng,5), fifth if rng.random()<0.5 else root, base+2*beat, base+3.92*beat))
            else:
                inst.notes.append(pretty_midi.Note(_human_vel(84,rng,5), root, base+2*beat, base+3.92*beat))
        elif variant==1:  # syncopated
            inst.notes.append(pretty_midi.Note(94, root, base, base+0.95*beat))
            inst.notes.append(pretty_midi.Note(82, root+2 if rng.random()<0.4 else root, base+1.25*beat, base+2.05*beat))
            inst.notes.append(pretty_midi.Note(88, fifth if rng.random()<0.6 else root, base+2.5*beat, base+3.88*beat))
        else:  # walking
            inst.notes.append(pretty_midi.Note(92, root, base, base+0.9*beat))
            # passing tone
            passing = root+2 if scale=="major" else root+1
            inst.notes.append(pretty_midi.Note(76, passing, base+1*beat, base+1.9*beat))
            inst.notes.append(pretty_midi.Note(84, chord[1]-12, base+2*beat, base+2.9*beat))
            inst.notes.append(pretty_midi.Note(80, root if rng.random()<0.5 else fifth, base+3*beat, base+3.9*beat))
        if bar%4==3 and rng.random()<0.35:
            # octave jump fill
            inst.notes.append(pretty_midi.Note(72, root+12, base+3.5*beat, base+3.85*beat))

def _write_piano_factory(genre, rng, variant_override=None):
    variant = variant_override if variant_override is not None else rng.randint(0,2)
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng_inner=None):
        rng2 = rng_inner or rng
        for bar in range(n_bars):
            deg = prog[bar % len(prog)]
            seventh = genre in ("lofi","jazz","chill","ambient")
            if rng2.random()<0.15:
                seventh = not seventh
            chord = _chord_notes(root_midi+12, deg, scale, seventh=seventh)
            # inversion
            inv = rng2.randint(0,1) if genre in ("lofi","jazz","chill") else 0
            if inv==1 and len(chord)>=3:
                chord = [chord[1], chord[2], chord[0]+12] + chord[3:]
            base = bar*sec_per_bar
            beat = 60.0/bpm
            is_break = (bar % 8 == 6) and rng2.random()<0.4
            if is_break:
                # break: sustain single note
                for n in chord[:2]:
                    inst.notes.append(pretty_midi.Note(52, n, base, base+sec_per_bar-0.1))
                continue
            if genre in ("lofi","ambient","chill"):
                if variant==0:  # arpeggio up
                    for i, n in enumerate(chord):
                        inst.notes.append(pretty_midi.Note(_human_vel(64,rng2,6), n, _human_time(base+i*beat*0.5,rng2,0.015), base+i*beat*0.5+beat*0.48))
                    for i, n in enumerate(reversed(chord)):
                        inst.notes.append(pretty_midi.Note(_human_vel(60,rng2,6), n+12, base+2*beat+i*beat*0.5, base+2*beat+i*beat*0.5+0.4))
                elif variant==1:  # block with soft rhythm
                    for b in [0,2]:
                        vel = _human_vel(68,rng2,5) if b==0 else _human_vel(62,rng2,5)
                        for n in chord:
                            inst.notes.append(pretty_midi.Note(vel, n, _human_time(base+b*beat,rng2,0.018), base+b*beat+beat*1.75))
                        # add 9th occasionally
                        if rng2.random()<0.3:
                            inst.notes.append(pretty_midi.Note(52, chord[0]+14, base+b*beat, base+b*beat+beat*1.75))
                else:  # sparse single notes
                    for i, b in enumerate([0, 1.5, 3]):
                        n = chord[i % len(chord)]
                        inst.notes.append(pretty_midi.Note(_human_vel(66,rng2,6), n+ (12 if i==2 else 0), _human_time(base+b*beat,rng2,0.02), base+b*beat+0.9*beat))
            elif genre=="edm":
                if variant==0:
                    for b in range(4):
                        for n in chord:
                            inst.notes.append(pretty_midi.Note(_human_vel(80,rng2,6), n, base+b*beat, base+b*beat+0.34))
                elif variant==1:  # sidechain feel: accent 1 and 3
                    for b, vel in [(0,88),(1,52),(2,84),(3,50)]:
                        for n in chord:
                            inst.notes.append(pretty_midi.Note(vel, n, base+b*beat, base+b*beat+0.32))
                else:  # pluck
                    for i in range(8):
                        n = chord[i % len(chord)]
                        inst.notes.append(pretty_midi.Note(_human_vel(74,rng2,6), n+12, base+i*beat*0.5, base+i*beat*0.5+0.22))
            elif genre=="jazz":
                # shell voicing + occasional stab
                rootless = chord[1:]  # 3-7-9
                for n in rootless:
                    inst.notes.append(pretty_midi.Note(_human_vel(62,rng2,5), n+12, _human_time(base,rng2,0.015), base+sec_per_bar*0.48))
                for n in chord:
                    inst.notes.append(pretty_midi.Note(_human_vel(58,rng2,5), n+12, _human_time(base+2*beat,rng2,0.015), base+sec_per_bar-0.05))
                if variant==2 and rng2.random()<0.4:
                    inst.notes.append(pretty_midi.Note(70, chord[0]+19, base+1*beat, base+1*beat+0.25))
            else:  # hiphop/trap/rock
                if variant==0:
                    for b in [0,2]:
                        for n in chord:
                            inst.notes.append(pretty_midi.Note(_human_vel(74,rng2,5), n, _human_time(base+b*beat,rng2,0.015), base+b*beat+beat*1.78))
                elif variant==1:  # stab
                    for n in chord:
                        inst.notes.append(pretty_midi.Note(84, n, base, base+0.4*beat))
                    for n in chord:
                        inst.notes.append(pretty_midi.Note(76, n, base+2*beat, base+2*beat+1.7*beat))
                else:  # octaves
                    for n in chord[:1]:
                        inst.notes.append(pretty_midi.Note(78, n, base, base+1.9*beat))
                        inst.notes.append(pretty_midi.Note(78, n+12, base, base+1.9*beat))
                        inst.notes.append(pretty_midi.Note(74, chord[1], base+2*beat, base+3.85*beat))
                        inst.notes.append(pretty_midi.Note(74, chord[1]+12, base+2*beat, base+3.85*beat))
    return _write

def _write_guitar(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng, variant_override=None):
    variant = variant_override if variant_override is not None else rng.randint(0,2)
    for bar in range(n_bars):
        deg = prog[bar % len(prog)]
        chord = _chord_notes(root_midi+12, deg, scale)
        base = bar*sec_per_bar
        beat = 60.0/bpm
        notes = chord[:3]
        if rng.random()<0.12:
            # add sus2 occasionally
            notes[1] = chord[0]+2
        if variant==0:  # strum 16ths
            for i in range(8):
                offset = base + i*beat*0.5
                for j, n in enumerate(notes):
                    stagger = j*0.016 if i%2==0 else (len(notes)-j)*0.016
                    vel = _human_vel(70 if i%2==0 else 60, rng, 5)
                    inst.notes.append(pretty_midi.Note(vel, n, _human_time(offset+stagger,rng,0.008), offset+stagger+0.32))
        elif variant==1:  # fingerpicking
            pattern = [0,2,1,2,0,2,1,0]  # travis-ish
            for i, idx in enumerate(pattern):
                n = notes[idx % len(notes)] + (12 if i%4==3 else 0)
                inst.notes.append(pretty_midi.Note(_human_vel(62,rng,6), n, _human_time(base+i*beat*0.5,rng,0.012), base+i*beat*0.5+0.34))
        else:  # muted chops
            for b in [0,1,2,3]:
                # chop on beat
                for n in notes[:2]:
                    inst.notes.append(pretty_midi.Note(_human_vel(78,rng,5), n, base+b*beat, base+b*beat+0.2))
                # ghost between
                if rng.random()<0.5:
                    inst.notes.append(pretty_midi.Note(42, notes[0], base+b*beat+0.5*beat, base+b*beat+0.5*beat+0.12))

def _write_synth_factory(mood, rng, variant_override=None):
    variant = variant_override if variant_override is not None else rng.randint(0,2)
    def _write(inst, sec_per_bar, n_bars, prog, root_midi, scale, bpm, rng_inner=None):
        rng2 = rng_inner or rng
        for bar in range(n_bars):
            deg = prog[bar % len(prog)]
            # 7th more often for jazzy, less for aggressive
            seventh = rng2.random()<0.65 if mood in ("dreamy","chill") else rng2.random()<0.35
            chord = _chord_notes(root_midi+12, deg, scale, seventh=seventh)
            base = bar*sec_per_bar
            if variant==0:  # pad hold
                for n in chord:
                    inst.notes.append(pretty_midi.Note(_human_vel(54,rng2,6), n+12, _human_time(base,rng2,0.01), base+sec_per_bar-0.05))
                if mood=="energetic" and bar%2==0 and rng2.random()<0.7:
                    lead = chord[1]+12
                    inst.notes.append(pretty_midi.Note(_human_vel(74,rng2,5), lead, base+1.5*60.0/bpm, base+2.5*60.0/bpm))
                # 20% chance of filter sweep: velocity swell
                if rng2.random()<0.2:
                    inst.notes.append(pretty_midi.Note(48, chord[0]+12, base+2*60.0/bpm, base+3*60.0/bpm))
            elif variant==1:  # arp
                arp = chord + [chord[0]+12]
                for i in range(8):
                    n = arp[i % len(arp)]
                    # every 4th bar double time
                    dur = 0.22 if (bar%4==3 and i>=4) else 0.28
                    inst.notes.append(pretty_midi.Note(_human_vel(60,rng2,7), n+12, base+i*sec_per_bar/8, base+i*sec_per_bar/8+dur))
            else:  # pulse + lead
                # pulse on beats
                for b in range(4):
                    for n in chord[:2]:
                        inst.notes.append(pretty_midi.Note(48, n+12, base+b*60.0/bpm, base+b*60.0/bpm+0.18))
                if rng2.random()<0.5:
                    lead = rng2.choice(chord)+12
                    inst.notes.append(pretty_midi.Note(72, lead+7, base+1*60.0/bpm, base+2*60.0/bpm))
    return _write

def render_midi(pm, midi_path, wav_path, mp3_path):
    midi_path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(midi_path))
    sf2 = find_sf2()
    wav_done=False
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

def generate_beat(duration=30, genre="lofi", situation="chill", instruments=None, bpm=None, mood="chill", key="C", seed=None,
                drums_variant=None, bass_variant=None, piano_variant=None, guitar_variant=None, synth_variant=None, progression_idx=None):
    if instruments is None: instruments = ["drums","bass","piano"]
    duration = int(duration)
    genre = str(genre).lower()
    situation = str(situation).lower()
    key = str(key).upper()
    mood = str(mood).lower()
    if genre not in GENRES:
        genre = SITUATION_DEFAULTS.get(situation, {}).get("genre","lofi")
    pm, eff_bpm, n_bars, _, chosen = build_midi(duration, genre, situation, instruments, bpm, key, mood, seed,
                                                 drums_variant=drums_variant, bass_variant=bass_variant,
                                                 piano_variant=piano_variant, guitar_variant=guitar_variant,
                                                 synth_variant=synth_variant, progression_idx=progression_idx)
    h = hashlib.md5(f"{genre}_{situation}_{key}_{eff_bpm}_{duration}_{seed}_{instruments}_{chosen}_{time.time()}".encode()).hexdigest()[:6]
    stem = f"beat_{int(time.time())}_{h}"
    midi_path = OUT / f"{stem}.mid"
    wav_path = OUT / f"{stem}.wav"
    mp3_path = OUT / f"{stem}.mp3"
    outs = render_midi(pm, midi_path, wav_path, mp3_path)
    return {"stem": stem, "genre": genre, "situation": situation, "key": key, "bpm": eff_bpm,
            "duration": duration, "instruments": instruments, "mood": mood,
            "files": outs, "bars": n_bars, "variants": chosen}
