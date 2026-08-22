
"""beatmaker web server — studio UI + API + MCP over HTTP."""
from __future__ import annotations
import os, hmac, secrets, json, asyncio, re, shutil, math
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from beatmaker.engine import INSTRUMENTS, GENRES, SITUATIONS, MOODS, KEYS, SITUATION_DEFAULTS
from beatmaker.vocabulary import (
    GENRES as V2_GENRES, MOOD_RULES, PROGRESSIONS as V2_PROGRESSIONS, MIX_PRESETS,
)
import beatmaker.mcp_server as mcp_mod

REPO = Path(__file__).resolve().parent.parent
WEB_DIR = REPO / "web"
OUT_DIR = REPO / "output"
SECRETS_FILE = Path.home() / ".hermes" / ".env"

def _load_secrets():
    env={}
    try:
        for line in SECRETS_FILE.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,_,v=line.partition("=")
            env[k.strip()]=v.strip()
    except: pass
    return env

def _ensure_token(env):
    tok = os.environ.get("BEATMAKER_TOKEN") or env.get("BEATMAKER_TOKEN")
    if not tok:
        tok=secrets.token_hex(24)
        with open(SECRETS_FILE,"a") as f: f.write(f"\nBEATMAKER_TOKEN={tok}\n")
    return tok

_env=_load_secrets()
TOKEN=_ensure_token(_env)

def token_valid(t): return bool(t) and hmac.compare_digest(t, TOKEN)

# FastMCP http app
mcp_app = mcp_mod.mcp.http_app(path="/mcp")

from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.lifespan(app):
        yield

app = FastAPI(title="beatmaker", version="0.1.0", lifespan=lifespan)

def _tok(req: Request):
    t=req.query_params.get("token")
    if t: return t
    a=req.headers.get("Authorization","")
    if a.lower().startswith("bearer "): return a[7:].strip()
    return None

def require_auth(req: Request):
    if not token_valid(_tok(req)): raise HTTPException(401,"invalid token")

LOGIN_HTML = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>beatmaker — access</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0f1a;color:#e8e6e3;font-family:monospace}.card{background:#141a2b;border:1px solid #2a3450;border-radius:12px;padding:36px 40px;width:340px;text-align:center}h1{font-size:20px;margin:0 0 6px;color:#a78bfa}p{font-size:13px;color:#8b93a8;margin:0 0 22px}input{width:100%;padding:11px 12px;border-radius:8px;border:1px solid #2a3450;background:#0b0f1a;color:#e8e6e3;font-family:monospace;box-sizing:border-box;outline:none}input:focus{border-color:#a78bfa}button{margin-top:14px;width:100%;padding:11px;border:0;border-radius:8px;background:#a78bfa;color:#0b0f1a;font-weight:bold;cursor:pointer;font-family:monospace}#err{color:#ff6b6b;font-size:12px;height:16px;margin-top:10px}</style></head><body><div class=card><h1>🎵 beatmaker</h1><p>Enter access token</p><input id=tok type=password placeholder="access token" autofocus><button onclick=login()>Open studio</button><div id=err></div></div><script>async function login(){const t=document.getElementById("tok").value.trim(),e=document.getElementById("err");e.textContent="";if(!t){e.textContent="token required";return}try{const r=await fetch("/api/auth/check",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:t})}),j=await r.json();if(j.ok){localStorage.setItem("beatmaker_token",t);location="/?token="+encodeURIComponent(t)}else e.textContent="wrong token"}catch(e2){e.textContent="server unreachable"}}document.getElementById("tok").addEventListener("keydown",e=>{if(e.key==="Enter")login()})</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not token_valid(_tok(request)): return LOGIN_HTML
    return (WEB_DIR/"index.html").read_text()

@app.post("/api/auth/check")
async def auth_check(request: Request):
    try: body=await request.json(); tok=body.get("token","")
    except: tok=""
    return {"ok": token_valid(str(tok))}

class BeatRequest(BaseModel):
    duration: int = 30
    genre: str = "lofi"
    situation: str = "chill"
    instruments: List[str] = ["drums","bass","piano"]
    bpm: Optional[int] = None
    mood: str = "chill"
    key: str = "C"
    seed: Optional[int] = None

@app.get("/api/options")
async def options():
    return {"instruments": INSTRUMENTS, "genres": GENRES, "situations": SITUATIONS, "moods": MOODS, "keys": KEYS, "defaults": SITUATION_DEFAULTS}

@app.post("/api/generate")
async def generate(req: Request, body: BeatRequest):
    require_auth(req)
    # LEGACY: direct-override path kept alive per spec §7 until Phase 5 confirmation.
    instruments = [i for i in body.instruments if i in INSTRUMENTS][:5]
    if not instruments: instruments=["drums","bass","piano"]
    from beatmaker.engine import generate_beat
    out = generate_beat(duration=body.duration, genre=body.genre, situation=body.situation,
                        instruments=instruments, bpm=body.bpm, mood=body.mood, key=body.key, seed=body.seed)
    files={}
    for k in ("midi","wav","mp3"):
        p = Path(out["files"][k])
        files[k] = f"/output/{p.name}" if p.exists() else None
    out["files"] = files
    tok = _tok(req) or ""
    out["download"] = {k: f"{v}?token={tok}" for k, v in files.items() if v}
    return out

@app.get("/output/{name}")
async def serve_output(name: str, request: Request):
    if not token_valid(_tok(request)): raise HTTPException(401,"invalid token")
    p = OUT_DIR / name
    if not p.exists() or ".." in name: raise HTTPException(404,"not found")
    return FileResponse(str(p))

# mount mcp
app.mount("/mcp", mcp_app)


# ── prompt → LLM → plan_beat → render_beat (coastal vibe etc) ──────────────
class PromptRequest(BaseModel):
    prompt: str
    duration: Optional[int] = None  # user override, else LLM picks
    mood: Optional[str] = None      # user override (semantic hint, also applied as plan override)
    bpm: Optional[int] = None       # user override
    instruments: Optional[List[str]] = None  # user override
    seed: Optional[int] = None


class LLMPromptError(Exception):
    pass


OPENCODE_MODEL = os.environ.get("BEATMAKER_LLM_MODEL", "opencode-go/muse-spark-1.2-contributor")
_OPENCODE_BIN: Optional[str] = shutil.which("opencode") or os.environ.get("OPENCODE_BIN")


async def _call_opencode(system: str, user: str) -> str:
    if not _OPENCODE_BIN:
        raise LLMPromptError("opencode binary not found — prompt box unavailable")
    prompt = f"{system}\n\n{user}\n\nReply with ONLY JSON. Nothing else."
    proc = await asyncio.create_subprocess_exec(
        _OPENCODE_BIN, "run", "--model", OPENCODE_MODEL, prompt,
        cwd=str(REPO),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        raise LLMPromptError("LLM timed out after 90s")
    if proc.returncode != 0:
        raise LLMPromptError(f"LLM exited {proc.returncode}: {err.decode(errors='replace')[:300]}")
    return out.decode(errors="replace").strip()


def _parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e <= s:
            raise ValueError(f"no JSON object found; raw: {text[:400]}")
        data = json.loads(text[s:e+1])
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _coerce_params(raw: Dict[str, Any], fallback_duration: Optional[int] = None) -> Dict[str, Any]:
    # LEGACY v1 coerce kept only for /api/generate fallback path; /api/prompt
    # now routes through planning.plan_beat directly (spec §3).
    genre = str(raw.get("genre", "chill")).lower()
    if genre not in GENRES:
        genre = "chill"
    mood = str(raw.get("mood", "chill")).lower()
    if mood not in MOODS:
        mood = "chill"
    key = str(raw.get("key", "C")).upper()
    if key not in KEYS:
        key = "C"
    insts = raw.get("instruments") or raw.get("instrument") or []
    if isinstance(insts, str):
        insts = [insts]
    insts = [str(x).lower() for x in insts if str(x).lower() in INSTRUMENTS][:5]
    if not insts:
        insts = ["drums", "bass", "piano"]
    bpm = raw.get("bpm")
    try:
        bpm = int(bpm) if bpm is not None else None
    except:
        bpm = None
    if bpm is not None:
        bpm = max(60, min(180, bpm))
    dur = fallback_duration if fallback_duration is not None else raw.get("duration")
    try:
        dur = int(dur) if dur is not None else 30
    except:
        dur = 30
    dur = max(10, min(120, dur))
    def _var(v):
        try: iv = int(v); return iv if 0 <= iv <= 2 else None
        except: return None
    def _prog(v):
        try: iv = int(v); return iv if 0 <= iv <= 5 else None
        except: return None
    variants = {
        "drums_variant": _var(raw.get("drums_variant")),
        "bass_variant": _var(raw.get("bass_variant")),
        "piano_variant": _var(raw.get("piano_variant")),
        "guitar_variant": _var(raw.get("guitar_variant")),
        "synth_variant": _var(raw.get("synth_variant")),
        "progression_idx": _prog(raw.get("progression_idx")),
    }
    return {"genre": genre, "mood": mood, "key": key, "instruments": insts, "bpm": bpm, "duration": dur, **variants}


def _llm_prompt_preamble():
    return (
        "You are a music director for 'beatmaker', a loop-based procedural studio.\n"
        "You own SEMANTIC decisions — genre/mood→key/mode, progression, energy arc, instrumentation.\n"
        "Do NOT invent sub-symbolic details; only pick from NAMED, DESCRIBED options. "
        "VARY your choices — different prompts/situations should produce different genre, "
        "key, bpm, drum_style and progressions; repeated prompts may still pick differently "
        "when the user clicks again.\n"
        f"Genres: {', '.join(sorted(V2_GENRES))} | Moods: {', '.join(sorted(MOOD_RULES))}\n"
        "Genre details (bpm_range, drum_style, default_instruments, progressions):\n"
        + "\n".join(
            f"- {g}: bpm={cfg['bpm_range']} drum={cfg['drum_style']} inst={cfg['default_instruments']} progs={cfg['progressions']}"
            for g, cfg in sorted(V2_GENRES.items())
        )
        + "\nNamed progressions (LLM-facing names with feel):\n"
        + "\n".join(f"- {n}: mode={c['mode']} feel={c['feel']} degrees={c['degrees']}"
                    for n, c in sorted(V2_PROGRESSIONS.items()))
        + "\n\nRespond with ONLY JSON."
    )

def _llm_response_schema_hint():
    return (
        "Reply with ONLY this JSON object: "
        '{"genre":"...","mood":"...","key":"C","mode":"major","bpm":92,'
        '"progression":"vi-IV-I-V","drum_style":"boom_bap",'
        '"energy_curve":["low","low","med","med"],"instruments":["drums","bass","piano"]}'
        " No prose, no fences. Always include mood, mode, progression, drum_style."
    )

def _parse_llm_plan_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e <= s:
            raise ValueError(f"no JSON object found; raw: {text[:400]}")
        data = json.loads(text[s:e+1])
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


@app.post("/api/prompt")
async def prompt_to_beat(req: Request, body: PromptRequest):
    require_auth(req)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "empty prompt")

    # LLM owns semantics; code owns cross-track structure. The LLM must pick
    # only from NAMED, DESCRIBED options — never indexes/ticks/velocities.
    system = _llm_prompt_preamble() + "\n" + _llm_response_schema_hint()
    user = f"Situation: {prompt}"
    nonce = secrets.token_hex(2)
    user_with_nonce = (
        f"{user} [variation seed: {nonce} — pick variants/progression "
        "differently each time even for similar prompts]"
    )

    raw: Optional[Dict[str, Any]] = None
    last_text = ""
    for attempt in range(2):
        try:
            text = await _call_opencode(
                system,
                user_with_nonce if attempt == 0
                else f"{user_with_nonce}\n\nPrevious reply was invalid JSON:\n{last_text[:400]}\nFix it — ONLY JSON.",
            )
            last_text = text
            raw = _parse_llm_plan_json(text)
            # quick shape guard — surface LLM hallucinations early
            if not all(k in raw for k in ("genre", "mood", "progression")):
                raise ValueError(f"LLM JSON missing required keys (genre/mood/progression): {list(raw.keys())}")
            break
        except Exception as e:
            last_text = str(e)
            if attempt == 1:
                raise HTTPException(500, f"LLM parse failed: {e}")
    assert raw is not None

    # ── requested duration (web controls override LLM suggestion) ──────────
    req_duration: float = body.duration or raw.get("duration") or 16
    try:
        req_duration = float(req_duration)
    except Exception:
        req_duration = 16.0
    req_duration = max(4, min(600, req_duration))

    # ── mood hint from front-end tweaks (body.mood/bpm/instruments) ─────────
    # If the user explicitly tweaked mood/bpm/instruments on the web UI, those
    # pin plan_beat overrides; otherwise the LLM's suggestions stand.
    tween_mood = (body.mood.strip().lower() if body.mood and body.mood.strip() else None)
    # body.mood is optional override — also used as the primary mood signal
    # for plan_beat when the LLM's mood is surprising / empty.
    effective_mood: str = (tween_mood or str(raw.get("mood", "")).lower().strip() or "chill")

    overrides: Dict[str, Any] = {}
    # genre/key/mode/bpm/progression/drum_style/instruments: apply LLM suggestion,
    # then let web overrides win on duration/bpm/instruments
    for k in ("genre", "key", "mode", "progression", "drum_style"):
        if raw.get(k) is not None and raw[k] not in ("", []):
            overrides[k] = raw[k]
    if raw.get("bpm") is not None:
        overrides["bpm"] = raw["bpm"]
    if raw.get("instruments") is not None:
        overrides["instruments"] = raw["instruments"]
    if raw.get("energy_curve") is not None:
        overrides["energy_curve"] = raw["energy_curve"]

    # web tweaks override LLM
    if body.bpm is not None:
        try: overrides["bpm"] = int(body.bpm)
        except Exception: pass
    if body.instruments is not None:
        insts = [str(x).lower() for x in body.instruments if str(x).lower() in INSTRUMENTS][:5]
        if insts:
            overrides["instruments"] = insts
    if tween_mood and tween_mood not in overrides.get("mood", ""):
        # tween mood is already the effective signal; plan_beat's mood param handles it,
        # but also surface it in overrides for docs. Nothing else needed.

        pass

    # ── spec §3 validation lives INSIDE plan_beat; every rejection names field
    # and lists valid values so the LLM can self-correct on next call ───────
    from beatmaker.planning import (
        Plan as V2Plan, ToolError as PlanningToolError,
        plan_beat as core_plan_beat, plan_to_dict, plan_from_dict,
    )
    from beatmaker.render_beat import render_beat as core_render_beat

    try:
        plan: V2Plan = core_plan_beat(
            prompt=prompt, mood=effective_mood,
            duration=req_duration, overrides=overrides,
        )
    except PlanningToolError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── per-hit variation within plan bounds (never overrides user's web tweaks):
    # 1) humanize jitter reseeded from OS entropy each render, so the same
    #    plan twice produces different micro-timing. 2) small bpm jitter ±2
    #    when the bpm came from the LLM (not from a pinned web override).
    if "bpm" not in overrides:
        import random as _rand2
        j = _rand2.randint(-2, 2)
        plan.bpm = max(30, min(240, int(plan.bpm) + j))

    rendered = core_render_beat(plan)
    # Shape response to keep web/index.html contract stable (genre/key/bpm/instruments/etc)
    files: Dict[str, Optional[str]] = {}
    # rendered files use keys mid/wav/mp3
    mid = rendered["files"].get("mid") or rendered["files"].get("midi")
    for k, p in (("midi", mid), ("wav", rendered["files"].get("wav")), ("mp3", rendered["files"].get("mp3"))):
        path = Path(p) if p else None
        files[k] = f"/output/{path.name}" if path and path.exists() else None
    bar_seconds = 240.0 / plan.bpm if plan.bpm else 4.0
    tok = _tok(req) or ""
    return {
        "genre": plan.genre, "key": plan.key, "mode": plan.mode,
        "bpm": plan.bpm, "progression": plan.progression,
        "drum_style": plan.drum_style, "energy_curve": list(plan.energy_curve),
        "instruments": list(plan.instruments),
        "duration": float(plan.duration), "rationale": plan.rationale,
        "bars": max(1, math.ceil(float(plan.duration) / bar_seconds)),
        "files": files, "download": {k: f"{v}?token={tok}" for k, v in files.items() if v},
        "parsed_prompt": raw, "resolved_params": plan_to_dict(plan),
        "prompt": prompt, "summary": rendered["musical_summary"],
        "pattern_preview": rendered["pattern_preview"],
    }
