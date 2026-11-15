import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import type { Express, Request } from "express";
import multer from "multer";
import { ENV } from "./_core/env";
import { invokeLLM } from "./_core/llm";

const upload = multer({
  dest: path.join(os.tmpdir(), "dubwave-uploads"),
  limits: { fileSize: 500 * 1024 * 1024 },
});

const jobs = new Map<string, { outputPath: string; expiresAt: number }>();
const pipelinePath = path.join(process.cwd(), "server", "dubbing", "pipeline.py");

type TranscriptSegment = { start: number; end: number; text: string };
type BurmeseSegment = { start: number; end: number; text: string };

function uploadedFiles(req: Request) {
  const files = req.files as { [fieldname: string]: Express.Multer.File[] } | undefined;
  return { video: files?.video?.[0], subtitles: files?.subtitles?.[0] };
}

function validVideo(file: Express.Multer.File) {
  return Boolean(file && (file.originalname.toLowerCase().endsWith(".mp4") || file.mimetype === "video/mp4"));
}

function validSubtitles(file: Express.Multer.File) {
  return Boolean(file && file.originalname.toLowerCase().endsWith(".srt"));
}

async function removeUploadedFiles(...files: Array<Express.Multer.File | undefined>) {
  await Promise.all(files.filter(Boolean).map(file => fs.rm(file!.path, { force: true })));
}

function run(command: string[], label: string) {
  return new Promise<void>((resolve, reject) => {
    const child = spawn(command[0], command.slice(1), { env: { ...process.env, PYTHONUNBUFFERED: "1" } });
    let stderr = "";
    child.stderr.on("data", chunk => { stderr += chunk.toString(); });
    child.on("error", reject);
    child.on("close", code => {
      if (code === 0) resolve();
      else reject(new Error(`${label}: ${stderr.trim().slice(-2500) || `exit code ${code ?? "unknown"}`}`));
    });
  });
}

function runPipeline(videoPath: string, subtitlePath: string, outputPath: string) {
  return run(["python3", pipelinePath, "--video", videoPath, "--srt", subtitlePath, "--output", outputPath], "Dubbing pipeline failed");
}

function stamp(seconds: number) {
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const whole = Math.floor(safe % 60);
  const milliseconds = Math.round((safe - Math.floor(safe)) * 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(whole).padStart(2, "0")},${String(milliseconds).padStart(3, "0")}`;
}

async function transcribe(videoPath: string, audioPath: string): Promise<TranscriptSegment[]> {
  if (!ENV.forgeApiUrl || !ENV.forgeApiKey) {
    throw new Error("MANUS_API_URL နဲ့ MANUS_API_KEY မသတ်မှတ်ရသေးပါ။");
  }
  await run(["ffmpeg", "-y", "-i", videoPath, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", audioPath], "အသံထုတ်ယူခြင်း မအောင်မြင်ပါ");
  const buffer = await fs.readFile(audioPath);
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(buffer)], { type: "audio/mpeg" }), "audio.mp3");
  form.append("model", "whisper-1");
  form.append("response_format", "verbose_json");
  const response = await fetch(`${ENV.forgeApiUrl.replace(/\/$/, "")}/v1/audio/transcriptions`, {
    method: "POST",
    headers: { authorization: `Bearer ${ENV.forgeApiKey}` },
    body: form,
  });
  if (!response.ok) throw new Error(`Transcription မအောင်မြင်ပါ (${response.status})`);
  const data = await response.json() as { segments?: Array<{ start: number; end: number; text: string }> };
  const segments = (data.segments || []).map(item => ({ start: item.start, end: item.end, text: item.text.trim() })).filter(item => item.text && item.end > item.start);
  if (!segments.length) throw new Error("Video ထဲမှာ ပြောဆိုသံ မတွေ့ပါ။");
  return segments;
}

async function translateToBurmese(segments: TranscriptSegment[]): Promise<BurmeseSegment[]> {
  const result = await invokeLLM({
    model: "gemini-3.8-flash",
    maxTokens: 12000,
    responseFormat: {
      type: "json_schema",
      json_schema: {
        name: "burmese_dubbing_segments",
        strict: true,
        schema: {
          type: "object",
          properties: { segments: { type: "array", items: { type: "object", properties: { id: { type: "integer" }, text: { type: "string" } }, required: ["id", "text"], additionalProperties: false } } },
          required: ["segments"],
          additionalProperties: false,
        },
      },
    },
    messages: [
      { role: "system", content: "You translate video narration into natural spoken Burmese. Preserve every segment in order, keep the same meaning, names, and emotional tone. Return only JSON matching the requested schema. Do not summarize or omit anything." },
      { role: "user", content: JSON.stringify(segments.map((segment, id) => ({ id, text: segment.text }))) },
    ],
  });
  const raw = result.choices[0]?.message?.content;
  const content = typeof raw === "string" ? raw : "";
  const parsed = JSON.parse(content) as { segments?: Array<{ id: number; text: string }> };
  if (!parsed.segments || parsed.segments.length !== segments.length) throw new Error("ဘာသာပြန်ရလဒ် မပြည့်စုံပါ။");
  return segments.map((segment, id) => ({ start: segment.start, end: segment.end, text: parsed.segments!.find(item => item.id === id)?.text?.trim() || segment.text }));
}

async function createSrt(videoPath: string, srtPath: string, autoAudioPath: string) {
  const transcript = await transcribe(videoPath, autoAudioPath);
  const translated = await translateToBurmese(transcript);
  const body = translated.map((segment, index) => `${index + 1}\n${stamp(segment.start)} --> ${stamp(segment.end)}\n${segment.text}\n`).join("\n");
  await fs.writeFile(srtPath, body, "utf8");
}

export function registerDubbingRoutes(app: Express) {
  app.post("/api/dubbing/process", upload.fields([
    { name: "video", maxCount: 1 },
    { name: "subtitles", maxCount: 1 },
  ]), async (req, res) => {
    const { video, subtitles } = uploadedFiles(req);
    if (!video) {
      await removeUploadedFiles(video, subtitles);
      return res.status(400).json({ message: "MP4 ဗီဒီယိုဖိုင်တစ်ဖိုင် တင်ပေးပါ။" });
    }
    if (!validVideo(video)) {
      await removeUploadedFiles(video, subtitles);
      return res.status(400).json({ message: "MP4 ဗီဒီယိုဖိုင်ကိုသာ အသုံးပြုနိုင်ပါတယ်။" });
    }
    if (subtitles && !validSubtitles(subtitles)) {
      await removeUploadedFiles(video, subtitles);
      return res.status(400).json({ message: "မြန်မာစာတန်းထိုး .srt ဖိုင်ကိုသာ အသုံးပြုနိုင်ပါတယ်။" });
    }

    const jobId = crypto.randomUUID();
    const jobDir = path.join(os.tmpdir(), "dubwave-jobs", jobId);
    const inputDir = path.join(jobDir, "input");
    const outputPath = path.join(jobDir, "final_output.mp4");
    await fs.mkdir(inputDir, { recursive: true });
    const videoPath = path.join(inputDir, "source.mp4");
    const subtitlePath = path.join(inputDir, "source.srt");
    const audioPath = path.join(inputDir, "source.mp3");

    try {
      await fs.rename(video.path, videoPath);
      if (subtitles) await fs.rename(subtitles.path, subtitlePath);
      else await createSrt(videoPath, subtitlePath, audioPath);
      await runPipeline(videoPath, subtitlePath, outputPath);
      jobs.set(jobId, { outputPath, expiresAt: Date.now() + 60 * 60 * 1000 });
      setTimeout(() => {
        const job = jobs.get(jobId);
        if (job?.outputPath === outputPath) jobs.delete(jobId);
        void fs.rm(jobDir, { recursive: true, force: true });
      }, 60 * 60 * 1000).unref();
      return res.json({ jobId, fileName: "final_output.mp4", downloadUrl: `/api/dubbing/download/${jobId}` });
    } catch (error) {
      await fs.rm(jobDir, { recursive: true, force: true });
      await removeUploadedFiles(video, subtitles);
      const message = error instanceof Error ? error.message : "Dubbing pipeline failed";
      console.error("[Dubbing]", message);
      return res.status(500).json({ message: message || "Dubbing ပြုလုပ်ရာမှာ အမှားတစ်ခု ဖြစ်သွားပါတယ်။" });
    }
  });

  app.get("/api/dubbing/download/:jobId", async (req, res) => {
    const job = jobs.get(req.params.jobId);
    if (!job || job.expiresAt < Date.now()) {
      jobs.delete(req.params.jobId);
      return res.status(404).json({ message: "ဒီ output ဖိုင်ကို မတွေ့တော့ပါ။" });
    }
    try {
      await fs.access(job.outputPath);
      return res.download(job.outputPath, "final_output.mp4");
    } catch {
      jobs.delete(req.params.jobId);
      return res.status(404).json({ message: "ဒီ output ဖိုင်ကို မတွေ့တော့ပါ။" });
    }
  });
}
