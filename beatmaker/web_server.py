
"""beatmaker web server — studio UI + API + MCP over HTTP."""
from __future__ import annotations
import os, hmac, secrets, json, asyncio
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

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
