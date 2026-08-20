
"""beatmaker web server — studio UI + API + MCP over HTTP."""
from __future__ import annotations
import os, hmac, secrets, json, asyncio, re, shutil
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from beatmaker.engine import INSTRUMENTS, GENRES, SITUATIONS, MOODS, KEYS, SITUATION_DEFAULTS
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
    # clamp
    instruments = [i for i in body.instruments if i in INSTRUMENTS][:5]
    if not instruments: instruments=["drums","bass","piano"]
    result = mcp_mod.mcp  # use engine via mcp tool wrapper
    from beatmaker.engine import generate_beat
    out = generate_beat(duration=body.duration, genre=body.genre, situation=body.situation,
                        instruments=instruments, bpm=body.bpm, mood=body.mood, key=body.key, seed=body.seed)
    # expose relative urls
    stem = out["stem"]
    # check which files exist
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


# ── prompt → LLM → MCP generate_beat (coastal vibe etc) ──────────────
class PromptRequest(BaseModel):
    prompt: str
    duration: Optional[int] = None  # user override, else LLM picks
    mood: Optional[str] = None      # user override
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
    # per-instrument variants + progression — LLM can pin 0-2 / 0-5, or leave None for random
    def _var(v):
        try:
            iv = int(v)
            return iv if 0 <= iv <= 2 else None
        except: return None
    def _prog(v):
        try:
            iv = int(v)
            return iv if 0 <= iv <= 5 else None
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


@app.post("/api/prompt")
async def prompt_to_beat(req: Request, body: PromptRequest):
    require_auth(req)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "empty prompt")
    system = (
        "You are a music director for 'beatmaker', a loop-based procedural beat studio.\n"
        "The user describes a SITUATION/SCENE in plain English. Map it to beat params WITH VARIATION.\n"
        f"Genres: {', '.join(GENRES)} | Moods: {', '.join(MOODS)} | Keys: {', '.join(KEYS)} | Instruments: {', '.join(INSTRUMENTS)} (max 5).\n"
        "Situation defaults for reference (genre/bpm/mood):\n"
        + "\n".join(f"- {k}: {v}" for k, v in SITUATION_DEFAULTS.items()) + "\n"
        "VARIATION KNOBS (use them! different prompts should give different feels):\n"
        "- progression_idx 0-5: chord progression (0=warm, 2=tense, 5=jazzy). Pick differently per prompt mood.\n"
        "- drums_variant 0-2: 0=straight/boom,1=syncopated/rim,2=busy/fills.\n"
        "- bass_variant 0-2: 0=roots,1=syncopated,2=walking.\n"
        "- piano_variant 0-2: 0=arp,1=block,2=sparse.\n"
        "- guitar_variant 0-2: 0=strum,1=fingerpick,2=mutes.\n"
        "- synth_variant 0-2: 0=pad,1=arp,2=pulse.\n"
        "Rules:\n"
        "- Pick genre that fits scene energy (coastal morning=ambient/chill, club=edm, heist=trap).\n"
        "- Pick mood that fits emotion (serene=dreamy, tense=dark, joyful=happy).\n"
        "- Pick key: C/F=warm, G/D=bright, A#/E=dark. VARY key across prompts.\n"
        "- Pick instruments that fit texture. VARY them — coastal might be piano+synth one time, guitar+bass another.\n"
        "- Pick bpm 60-180 that fits tempo. VARY bpm even within same mood.\n"
        "- ALWAYS set at least 3 variant knobs to non-None values — this is how variation happens.\n"
        "Reply with ONLY this JSON: {\"genre\":\"...\",\"mood\":\"...\",\"key\":\"...\",\"instruments\":[\"...\"],\"bpm\":72,\"duration\":30,\"progression_idx\":2,\"drums_variant\":1,\"bass_variant\":0,\"piano_variant\":2,\"guitar_variant\":0,\"synth_variant\":1}\n"
        "No prose, no fences."
    )
    user = f"Situation: {prompt}"
    # Best practice for randomness per web research: LLMs at low temp are deterministic for same prompt.
    # Add a short random nonce to the user message so same text still samples differently (temperature + nonce).
    # Also instruct LLM to VARY — don't repeat same variant picks.
    nonce = secrets.token_hex(2)  # 4 hex chars, cheap entropy
    user_with_nonce = f"{user} [variation seed: {nonce} — pick variants/progression differently each time even for similar prompts]"
    # LLM parse, with one retry on bad JSON
    raw: Optional[Dict[str, Any]] = None
    last_text = ""
    for attempt in range(2):
        try:
            text = await _call_opencode(system, user_with_nonce if attempt == 0 else f"{user_with_nonce}\n\nPrevious reply was invalid JSON:\n{last_text[:400]}\nFix it — ONLY JSON.")
            last_text = text
            raw = _parse_json(text)
            break
        except Exception as e:
            last_text = str(e)
            if attempt == 1:
                raise HTTPException(500, f"LLM parse failed: {e}")
    assert raw is not None
    params = _coerce_params(raw, fallback_duration=body.duration)
    # user overrides win over LLM
    if body.duration is not None:
        params["duration"] = max(10, min(300, int(body.duration)))
    if body.mood is not None and str(body.mood).lower() in MOODS:
        params["mood"] = str(body.mood).lower()
    if body.bpm is not None:
        try: params["bpm"] = max(60, min(180, int(body.bpm)))
        except: pass
    if body.instruments is not None:
        insts = [str(x).lower() for x in body.instruments if str(x).lower() in INSTRUMENTS][:5]
        if insts: params["instruments"] = insts
    if body.seed is not None:
        seed = int(body.seed)
    else:
        # Random seed when user doesn't pin one — true per-call variation even for same prompt text.
        # Engine uses Random(seed) for prog/variant picks, so random seed = different feel each hit.
        seed = secrets.randbits(31)
    from beatmaker.engine import generate_beat
    out = generate_beat(duration=params["duration"], genre=params["genre"], situation="chill",
                        instruments=params["instruments"], bpm=params["bpm"], mood=params["mood"], key=params["key"], seed=seed,
                        drums_variant=params.get("drums_variant"), bass_variant=params.get("bass_variant"),
                        piano_variant=params.get("piano_variant"), guitar_variant=params.get("guitar_variant"),
                        synth_variant=params.get("synth_variant"), progression_idx=params.get("progression_idx"))
    files: Dict[str, Optional[str]] = {}
    for k in ("midi", "wav", "mp3"):
        p = Path(out["files"][k])
        files[k] = f"/output/{p.name}" if p.exists() else None
    tok = _tok(req) or ""
    out["files"] = files
    out["download"] = {k: f"{v}?token={tok}" for k, v in files.items() if v}
    out["parsed_prompt"] = raw
    out["resolved_params"] = params
    out["prompt"] = prompt
    return out
