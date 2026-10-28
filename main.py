import os, time
from collections import defaultdict, deque
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "JARVIS Chat + Voice Backend"
app = FastAPI(title=APP_NAME, version="1.0.0")
allowed_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])
hits = defaultdict(deque)
def check_rate_limit(request: Request):
    key = request.client.host if request.client else "unknown"
    now = time.time()
    q = hits[key]
    while q and now - q[0] > 60: q.popleft()
    if len(q) >= int(os.getenv("RATE_LIMIT_PER_MINUTE", "20")):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")
    q.append(now)

Provider = Literal["openai", "gemini", "claude", "deepseek", "groq", "openrouter", "custom", "ollama"]
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)
class ChatRequest(BaseModel):
    provider: Provider = "gemini"
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    model: str | None = Field(default=None, max_length=120)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=4096)

def provider_config(provider: str, requested_model: str | None):
    configs = {
        "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"),
        "deepseek": ("https://api.deepseek.com/chat/completions", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-chat"),
        "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile"),
        "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "custom": (os.getenv("CUSTOM_BASE_URL", "").rstrip("/") + "/chat/completions", "CUSTOM_API_KEY", "CUSTOM_MODEL", ""),
        "ollama": (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/") + "/chat/completions", "OLLAMA_API_KEY", "OLLAMA_MODEL", "llama3.2"),
    }
    if provider in configs:
        url, key_name, model_name, default_model = configs[provider]
        key = os.getenv(key_name, "")
        model = requested_model or os.getenv(model_name, default_model)
        if provider == "custom" and not os.getenv("CUSTOM_BASE_URL"):
            raise HTTPException(status_code=503, detail="Set CUSTOM_BASE_URL in the backend environment.")
        if provider != "ollama" and not key:
            raise HTTPException(status_code=503, detail=f"Backend secret {key_name} is not configured.")
        return {"kind": "openai-compatible", "url": url, "key": key, "model": model}
    if provider == "gemini":
        key = os.getenv("GEMINI_API_KEY", "")
        if not key: raise HTTPException(status_code=503, detail="Backend secret GEMINI_API_KEY is not configured.")
        return {"kind": "gemini", "key": key, "model": requested_model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")}
    if provider == "claude":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key: raise HTTPException(status_code=503, detail="Backend secret ANTHROPIC_API_KEY is not configured.")
        return {"kind": "claude", "key": key, "model": requested_model or os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-latest")}
    raise HTTPException(status_code=400, detail="Unsupported provider.")

async def ask_provider(cfg: dict, provider: str, messages: list[dict], temperature: float, max_tokens: int):
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        if cfg["kind"] == "openai-compatible":
            headers = {"Content-Type": "application/json"}
            if cfg["key"]: headers["Authorization"] = f"Bearer {cfg['key']}"
            if provider == "openrouter":
                headers["HTTP-Referer"] = os.getenv("APP_PUBLIC_URL", "http://localhost:8000")
                headers["X-Title"] = "JARVIS Chat"
            resp = await client.post(cfg["url"], headers=headers, json={"model": cfg["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens})
            if resp.status_code >= 400:
                detail = "AI provider returned an error."
                try: detail = resp.json().get("error", {}).get("message") or detail
                except Exception: pass
                raise HTTPException(status_code=502, detail=detail[:500])
            try: return resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError): raise HTTPException(status_code=502, detail="Unexpected response from AI provider.")
        if cfg["kind"] == "gemini":
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
            body = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
            if system: body["systemInstruction"] = {"parts": [{"text": system}]}
            resp = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent", params={"key": cfg["key"]}, json=body)
            if resp.status_code >= 400: raise HTTPException(status_code=502, detail="Gemini request failed. Check model and API key in backend settings.")
            try: return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError): raise HTTPException(status_code=502, detail="Gemini returned no text.")
        if cfg["kind"] == "claude":
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
            body = {"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature, "messages": msgs}
            if system: body["system"] = system
            resp = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=body)
            if resp.status_code >= 400: raise HTTPException(status_code=502, detail="Claude request failed. Check model and API key in backend settings.")
            try: return "".join(p.get("text", "") for p in resp.json()["content"] if p.get("type") == "text")
            except (KeyError, TypeError): raise HTTPException(status_code=502, detail="Claude returned no text.")

@app.get("/api/health")
async def health():
    return {"ok": True, "service": APP_NAME, "configured_providers": {
        "openai": bool(os.getenv("OPENAI_API_KEY")), "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")), "deepseek": bool(os.getenv("DEEPSEEK_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")), "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "custom": bool(os.getenv("CUSTOM_BASE_URL")), "ollama": bool(os.getenv("OLLAMA_BASE_URL"))}}

@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    check_rate_limit(request)
    if sum(len(m.content) for m in body.messages) > 24000: raise HTTPException(status_code=413, detail="Conversation too long. Start a new chat.")
    cfg = provider_config(body.provider, body.model)
    try: answer = await ask_provider(cfg, body.provider, [m.model_dump() for m in body.messages], body.temperature, body.max_tokens)
    except httpx.TimeoutException: raise HTTPException(status_code=504, detail="AI provider timed out. Please retry.")
    except httpx.RequestError: raise HTTPException(status_code=502, detail="Could not connect to AI provider.")
    return {"ok": True, "provider": body.provider, "model": cfg["model"], "reply": answer}

@app.get("/")
async def index():
    return FileResponse("static/index.html")
app.mount("/static", StaticFiles(directory="static"), name="static")
