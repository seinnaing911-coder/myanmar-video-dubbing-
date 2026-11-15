# Myanmar Video Dubbing

This repository contains two ways to run the Myanmar video dubbing workflow:

1. **dubwave web app** — a responsive React/Express website where users upload an MP4, automatically transcribe and translate the source speech into Burmese, run the Edge TTS + FFmpeg pipeline, and download `final_output.mp4`. A Burmese `.srt` can also be supplied optionally.
2. **Streamlit app** — the original private studio in `app.py`, including Gemini-based video understanding and timeline-driven dubbing.

## dubwave web app

The web app uses React, Vite, Express, TypeScript, and the adapted pipeline in `server/dubbing/pipeline.py`.

```bash
pnpm install
pnpm dev
```

The server honors `PORT` and defaults to `3000`. Run `pnpm check` for TypeScript diagnostics and `pnpm build` for a production build.

For the real dubbing endpoint, the runtime needs Python 3, FFmpeg, and the dependencies in `server/dubbing/requirements.txt`:

```bash
python3 -m pip install -r server/dubbing/requirements.txt
```

The API accepts `POST /api/dubbing/process` with `video` (MP4) and an optional `subtitles` (SRT) multipart field. Without SRT, it extracts the audio, calls the configured transcription service, translates timestamped segments into natural spoken Burmese through the built-in LLM helper, then passes the generated SRT to the Edge TTS + FFmpeg pipeline. It returns a temporary download URL for `final_output.mp4`.

The automatic mode requires the platform-provided `MANUS_API_URL` and `MANUS_API_KEY` for transcription and translation. These must be configured as deployment secrets and must never be committed to the repository.

## Streamlit app

The original Streamlit implementation remains in `app.py`. It supports the existing private password gate, Gemini video analysis, and Thiha/Nilar Burmese voices.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Keep existing Streamlit secrets in `.streamlit/secrets.toml` or the deployment secret store:

```toml
APP_PASSWORD = "your-existing-password"
GEMINI_API_KEY = "your-gemini-api-key"
```

Do not commit real secrets. FFmpeg must be available on the host for either workflow.

## Project notes

- `client/src/pages/Home.tsx` contains the Burmese-first dubwave landing page and upload console.
- `server/dubbing.ts` handles upload validation, Python process execution, and temporary downloads.
- `server/dubbing/pipeline.py` is the parameterized version of the user-provided subtitle-to-Burmese-dubbing script.
- `plan.md` contains the implementation and design plan; `TODO.md` records the product outcomes.
