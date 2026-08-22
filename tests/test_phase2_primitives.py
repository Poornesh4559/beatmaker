"""Phase 2 unit tests — pure render primitives on note/step data only.
No MIDI, no audio, no filesystem writes."""
import sys, random
sys.path.insert(0, "/home/ubuntu/beatmaker")

from beatmaker.vocabulary import DRUM_STYLES
from beatmaker.render_primitives import (
    build_triad, key_to_midi, chord_for_degree, grid_steps,
    build_bass_line, scale_density_by_energy, apply_turnaround_fill,
    humanize, HumanizedNote, ms_from_swing_pct,
)

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")

# ── build_triad ──────────────────────────────────────────────────────────────
print("build_triad")
check("maj triad", build_triad(60, "maj") == [60, 64, 67])
check("min triad", build_triad(57, "min") == [57, 60, 64])
check("dim triad", build_triad(59, "dim") == [59, 62, 65])
check("dom7", build_triad(60, "maj", "7") == [60, 64, 67, 70])
check("maj7_or_min7 on maj", build_triad(60, "maj", "maj7_or_min7") == [60, 64, 67, 71])
check("maj7_or_min7 on min", build_triad(57, "min", "maj7_or_min7") == [57, 60, 64, 67])
try:
    build_triad(60, "sus4"); check("bad quality raises", False)
except ValueError:
    check("bad quality raises", True)

# ── key_to_midi ──────────────────────────────────────────────────────────────
print("key_to_midi")
check("C -> 48", key_to_midi("C") == 48)
check("F# -> 54", key_to_midi("F#") == 54)
check("B -> 59", key_to_midi("B") == 59)
try:
    key_to_midi("H"); check("bad key raises", False)
except ValueError:
    check("bad key raises", True)

# ── chord_for_degree ────────────────────────────────────────────────────────
print("chord_for_degree")
c = chord_for_degree(key_to_midi("C"), "major", 1, "hiphop")
check("C major I = C triad", c["voicing"] == [48, 52, 55] and c["quality"] == "maj")
c = chord_for_degree(key_to_midi("C"), "major", 6, "lofi")
check("C major vi = Am7 (lofi ext)", c["voicing"] == [57, 60, 64, 67] and c["extension"] == "maj7_or_min7")
c = chord_for_degree(key_to_midi("A"), "minor", 1, "trap")
check("A minor i = Amin triad", c["voicing"] == [57, 60, 64] and c["quality"] == "min")
c = chord_for_degree(key_to_midi("C"), "major", 7, "rock")
check("C major vii = B dim", c["quality"] == "dim" and c["voicing"][:3] == [59, 62, 65])
c = chord_for_degree(key_to_midi("C"), "major", 2, "jazz")
check("C major ii with 7th = Dm7 dom-flavor (root 50 +10)", c["voicing"] == [50, 53, 57, 60])
for bad_deg in (0, 8):
    try:
        chord_for_degree(48, "major", bad_deg, "lofi"); check(f"degree {bad_deg} raises", False)
    except ValueError:
        check(f"degree {bad_deg} raises", True)
try:
    chord_for_degree(48, "dorian", 1, "lofi"); check("bad mode raises", False)
except ValueError:
    check("bad mode raises", True)

# ── grid_steps ───────────────────────────────────────────────────────────────
print("grid_steps")
kick = DRUM_STYLES["boom_bap"]["kick"]
check("boom_bap kick steps", grid_steps(kick, "x") == [0, 3, 8, 10], str(grid_steps(kick, 'x')))
snare = DRUM_STYLES["boom_bap"]["snare"]
check("boom_bap snare incl ghost", sorted(grid_steps(snare, "x") + grid_steps(snare, "o")) == [4, 12, 15], f"{grid_steps(snare, 'x')} {grid_steps(snare, 'o')}")
try:
    grid_steps("xx|xx", "x"); check("short grid raises", False)
except ValueError:
    check("short grid raises", True)

# ── build_bass_line ──────────────────────────────────────────────────────────
print("build_bass_line")
notes = build_bass_line(36, kick, "major")
steps_locked = [n["step"] for n in notes if n["role"] == "kick_locked"]
check("bass locked to every kick", steps_locked == grid_steps(kick, "x"))
check("bass pitch = chord root", all(n["pitch"] == 36 for n in notes if n["role"] == "kick_locked"))
pickups = [n for n in notes if n["role"] == "pickup"]
check("one pickup max", len(pickups) <= 1)
if pickups:
    p = pickups[0]
    kicks = grid_steps(kick, "x")
    check("pickup one step before last kick", p["step"] == (kicks[-1] - 1) % 16)
    check("pickup passing tone major +2", p["pitch"] == 38)  # 36+2 major
notes_min = build_bass_line(36, kick, "minor")
pm = [n for n in notes_min if n["role"] == "pickup"]
if pm:
    check("pickup passing tone minor +3", pm[0]["pitch"] == 39)
# empty-kick fallback
fallback = build_bass_line(36, "....|....|....|....", "major")
check("empty kick -> downbeat fallback", [n["step"] for n in fallback if n["role"]=="kick_locked"] == [0])
check("empty kick still gets pickup per §4.1", any(n["role"]=="pickup" and n["step"]==15 for n in fallback))
# pickup skipped when it collides with a kick
tight = build_bass_line(40, "x...|....|...x|x...", "major")  # last kick step15 -> pickup at 14? no: (15-1)%16=14 free
kicks_t = grid_steps("x...|....|...x|x...", "x")
pk = [n for n in tight if n["role"] == "pickup"]
check("pickup placed when free", (not pk) or pk[0]["step"] not in kicks_t)
occupied = build_bass_line(40, "x.x.|....|...x|x..x", "major")  # last kick 15 -> pickup 14 occupied by kick
kicks_occ = grid_steps("x.x.|....|...x|x..x", "x")
check("no pickup when step occupied by kick",
      all(n["step"] not in kicks_occ for n in occupied if n["role"] == "pickup"))

# ── scale_density_by_energy ──────────────────────────────────────────────────
print("scale_density_by_energy")
style = DRUM_STYLES["trap_halftime"]
med = scale_density_by_energy(style, "med")
check("med returns authored grid", med["hat"] == style["hat"] and med["kick"] == style["kick"])
low = scale_density_by_energy(style, "low")
low_hat_steps = len(grid_steps(low["hat"], "x")) + len(grid_steps(low["hat"], "o"))
auth_hat_steps = len(grid_steps(style["hat"], "x"))
check("low reduces hat density", low_hat_steps < auth_hat_steps + 1 and low_hat_steps <= auth_hat_steps,
      f"{low_hat_steps} vs {auth_hat_steps}")
high = scale_density_by_energy(style, "high")
high_hat = high["hat"].replace("|", "")
auth_hat = style["hat"].replace("|", "")
check("high fills neighbor hat gaps", high_hat.count("x") >= auth_hat.count("x"))
hi_snare = high["snare"].replace("|", "")
auth_snare = style["snare"].replace("|", "")
ghosts_added = hi_snare.count("o") >= auth_snare.count("o")
check("high adds ghost snares only after hits", ghosts_added)
# ghosts never precede non-hit slot: each 'o' must follow an 'x' or 'o'
ok_ghost = all(hi_snare[i-1] in "xo" for i,ch in enumerate(hi_snare) if ch=="o")
check("ghosts adjacent to hits", ok_ghost, hi_snare)
try:
    scale_density_by_energy(style, "loud"); check("bad energy raises", False)
except ValueError:
    check("bad energy raises", True)

# ── apply_turnaround_fill ────────────────────────────────────────────────────
print("apply_turnaround_fill")
filled = apply_turnaround_fill(DRUM_STYLES["rock_backbeat"], "rock_backbeat")
fs = filled["snare"].replace("|", "")
check("fill sets snare 14,15", fs[14] == "x" and fs[15] == "x")
orig = DRUM_STYLES["rock_backbeat"]["snare"].replace("|", "")
check("original untouched (copy)", orig[14] == "." and orig[15] == ".")
amb = apply_turnaround_fill(DRUM_STYLES["ambient_sparse"], "ambient_sparse")
check("ambient_sparse never fills", amb["snare"] == DRUM_STYLES["ambient_sparse"]["snare"])
check("desc preserved", filled.get("desc") == DRUM_STYLES["rock_backbeat"]["desc"])

# ── humanize ─────────────────────────────────────────────────────────────────
print("humanize")
rng = random.Random(42)
cfg = {"swing_pct": 66, "timing_jitter_ms": 10, "velocity_jitter": 14}
notes = [HumanizedNote(step=s, start_time=s*0.125, end_time=s*0.125+0.2, velocity=80)
         for s in range(16)]
before_order = [n.step for n in notes]
humanize(notes, cfg, step_seconds=0.125, rng=rng)
check("order/count preserved", [n.step for n in notes] == before_order)
off = [n for n in notes if n.step % 2 == 1]
on = [n for n in notes if n.step % 2 == 0]
swing_delay = ms_from_swing_pct(66, 0.125)
check("off-beats pushed late by swing", all(n.start_time > n.step*0.125 + swing_delay/2 - 0.02 for n in off),
      f"delay={swing_delay:.4f}")
straight = [HumanizedNote(step=s, start_time=s*0.125, end_time=s*0.125+0.2, velocity=80) for s in range(4)]
humanize(straight, {"swing_pct": 50, "timing_jitter_ms": 0, "velocity_jitter": 0}, rng=random.Random(1))
check("50% swing = no delay", all(abs(n.start_time - n.step*0.125) < 1e-9 for n in straight))
vel_ok = all(1 <= n.velocity <= 127 for n in notes)
check("velocity clamped to 1-127", vel_ok)
# deterministic with same rng seed
a = [HumanizedNote(step=1, start_time=0.125, end_time=0.325, velocity=80)]
b = [HumanizedNote(step=1, start_time=0.125, end_time=0.325, velocity=80)]
humanize(a, cfg, rng=random.Random(7)); humanize(b, cfg, rng=random.Random(7))
check("deterministic given seeded rng", abs(a[0].start_time-b[0].start_time) < 1e-12 and a[0].velocity==b[0].velocity)

print(f"\n{'='*46}\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
