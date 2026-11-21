J.A.R.V.I.S. OpenRouter AI Chat — Setup

1. Extract this project folder.
2. Copy .env.example to .env.
3. Open .env and set OPENROUTER_API_KEY to your own OpenRouter API key.
   (Optional) set OPENROUTER_MODEL to a preferred model.
4. Open PowerShell in this folder and run:
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m streamlit run ai_chat_app.py
5. Open http://localhost:8501 in your browser.

The app flow:
- On first load it asks for your OpenRouter API key (sk-or-v1-...).
- After you enter it, the app saves it to .env and uses YOUR key for all AI calls.
- Chat like a human: type a message, press SEND, get a quick answer.
- Models: Claude Sonnet 4 / GPT-4.1 / Gemini 2.5 Pro (most intelligent) or
  GPT-4.1 Mini / Gemini 2.5 Flash (fast). Use Fast mode for quick answers within seconds.
- Camera object detection: use "Take photo with camera" and point at any object;
  with "Auto-detect objects (camera mode)" ON (default), JARVIS detects the object
  and answers. Vision-capable models required.

Notes:
- Unlimited usage enforced by JARVIS app-side; subject to your OpenRouter plan/credits.
- Enable web search in the sidebar for up-to-date web-based answers.
- Web search and model inference may consume OpenRouter credits.
- Voice output / wake listener features live in the original app.py (JARVIS voice mode).
