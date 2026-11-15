# Myanmar AI Video Dubbing — Implementation Plan

## Product scope

Build a responsive Burmese-first web app inspired by Stream Wave's focused AI dubbing flow. The primary user journey is: upload an MP4 video, upload a Burmese `.srt` subtitle file, review the fixed Burmese Edge TTS voice, start processing, follow clear progress stages, and download the resulting `final_output.mp4`.

The user-provided Python script remains the core processing logic. It will be adapted into a command-line script that accepts explicit input/output paths, creates temporary audio and clip folders, uses `my-MM-ThihaNeural`, synchronizes clip duration to generated audio, concatenates the processed clips, and writes the final MP4. The Express server will receive multipart uploads, invoke the script with `python3`, and return a downloadable output URL.

## Design

Three possible directions considered:

- **Soft SaaS lavender** — friendly, rounded, light product UI. Probability 0.06.
- **Dark waveform editorial** — deep ink canvas, cyan/violet signal glow, strong typographic hierarchy, and a focused studio-like upload surface. Probability 0.07.
- **Paper utility** — warm neutral background, black type, and dense tool panels. Probability 0.04.

### Chosen direction: Dark waveform editorial

- **Design Movement:** Dark-mode creative tooling with a contemporary audio waveform / broadcast control-room sensibility.
- **Core Principles:** Make the dubbing action immediately visible; use contrast to guide attention; show progress as a tangible production pipeline; keep controls generous and understandable on small screens.
- **Color Philosophy:** Ink black and midnight blue create a calm production surface. Electric cyan is the ownable “signal” color for active controls and progress. Violet is reserved for AI moments and secondary emphasis. Warm white text keeps Burmese copy readable without feeling clinical.
- **Layout Paradigm:** A full-width editorial landing page with an offset hero, a central “dubbing console” card, and asymmetrical section rails rather than a generic centered SaaS grid.
- **Signature Elements:** Thin waveform lines, soft cyan/violet bloom behind key surfaces, and numbered production stages with a vertical signal rail.
- **Interaction Philosophy:** Every action confirms what will happen next. Upload states show selected filenames; disabled start states explain what is missing; processing states reveal one active stage at a time.
- **Animation:** Slow ambient waveform drift in the hero, small hover lifts on cards, and a clean progress sweep during processing. Avoid noisy motion; animation should feel like a signal coming alive.
- **Typography System:** Use `Manrope` for Latin UI copy and system Burmese fallbacks for Myanmar text. Large headlines are compact and bold; supporting text uses generous line-height. Labels are uppercase/letter-spaced only for small English metadata.
- **Brand Essence:** A practical Burmese dubbing studio for creators who want to make existing videos understandable to more people. Personality: clear, confident, local.
- **Brand Voice:** Direct and encouraging. Example lines: “ဗီဒီယိုတစ်ခုတင်ပါ။ မြန်မာအသံနဲ့ ပြန်ရယူပါ။” and “အသံထွက်နေပါပြီ — နောက်တစ်ဆင့်ကို စောင့်ကြည့်နိုင်ပါတယ်။”
- **Wordmark & Logo:** A compact “MM” signal mark made from two offset waveform strokes, paired with the `dubwave` wordmark.
- **Signature Brand Color:** Signal Cyan `#7CF7E5`.

## Technical approach

- Frontend: React + TypeScript + Tailwind CSS using the existing Webdev starter.
- Backend: Express route `POST /api/dubbing/process` with `multer` for multipart uploads and a child process that runs `python3 server/dubbing/pipeline.py`.
- Processing: Python dependencies are declared in `server/dubbing/requirements.txt`; FFmpeg and Python are installed in the production Dockerfile. The script writes temporary job folders under the OS temp directory and returns a JSON result with a download URL.
- Download: Express serves generated MP4 files through `GET /api/dubbing/download/:jobId` for the current job lifetime. The UI provides a direct download action.
- Validation: Client and server both enforce MP4 video input and `.srt` subtitle input. Empty subtitles and invalid timeline entries fail with a useful message.
- Scope boundary: no accounts, payments, permanent history, or unrelated AI features in this first implementation.

## Project structure

- `client/src/pages/Home.tsx`: landing page, upload console, workflow explanation, FAQ, and completion state.
- `client/src/index.css`: global theme, typography, waveform styling, responsive layout helpers.
- `server/_core/index.ts`: upload route registration and download route.
- `server/dubbing/pipeline.py`: adapted user-provided subtitle-to-Burmese-dubbing pipeline.
- `server/dubbing/requirements.txt`: Python runtime dependencies.
- `server/dubbing.ts`: upload validation, process spawning, job storage, and download lookup.
- `public/manus-routes.json`: route manifest for `/` and `/404`.
- `Dockerfile`: production runtime with Node, Python, pip packages, and FFmpeg.

## Delivery behavior

The first delivered version runs locally in Preview with a complete visual workflow and a real backend processing path. If the Preview environment does not have the Python packages or network access needed by Edge TTS, the UI reports the backend error rather than silently pretending a file was produced.
