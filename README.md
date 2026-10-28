# JARVIS Chat + Voice Backend

FastAPI backend for JARVIS chat. The Wix site can call `POST /api/chat` after the backend is deployed.

## Deploy on Render
1. In Render choose **New + → Web Service** and connect this repository.
2. Runtime: Python. Build command: `pip install -r requirements.txt`.
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
4. Plan: Free. Health check path: `/api/health`.
5. Set `ALLOWED_ORIGINS` to the exact Wix site origin shown in `render.yaml`.
6. In Environment add at least one provider API key, e.g. `GEMINI_API_KEY`. Never commit a real key.
7. Deploy. Test the generated Render URL plus `/api/health`; it should return JSON with `"ok": true`.
8. Put only the base Render URL (no `/api/chat` suffix) into the Wix chat widget's backend URL setting.

## Providers
- Gemini: `GEMINI_API_KEY`, optional `GEMINI_MODEL`
- OpenAI: `OPENAI_API_KEY`, optional `OPENAI_MODEL`
- Claude: `ANTHROPIC_API_KEY`, optional `CLAUDE_MODEL`
- DeepSeek: `DEEPSEEK_API_KEY`, optional `DEEPSEEK_MODEL`
- Groq: `GROQ_API_KEY`, optional `GROQ_MODEL`
- OpenRouter: `OPENROUTER_API_KEY`, optional `OPENROUTER_MODEL`
- Custom OpenAI-compatible: `CUSTOM_BASE_URL`, optional `CUSTOM_API_KEY`, `CUSTOM_MODEL`
- Ollama: `OLLAMA_BASE_URL`, optional `OLLAMA_MODEL`; the backend host must be able to reach it.

Real AI replies require a valid provider key and may use paid quota. Render free instances can sleep while idle, so the first request after inactivity may be slow.

## Endpoints
- `GET /api/health`: service and configured-provider flags (never returns secrets)
- `POST /api/chat`: `{ "provider": "gemini", "messages": [{"role":"user","content":"Namaste"}] }`
- `GET /docs`: interactive API documentation

## Local run
`pip install -r requirements.txt` then `uvicorn main:app --reload --port 8000`.
