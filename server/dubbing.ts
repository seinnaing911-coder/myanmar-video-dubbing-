import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import type { Express, Request } from "express";
import multer from "multer";

const upload = multer({
  dest: path.join(os.tmpdir(), "dubwave-uploads"),
  limits: { fileSize: 500 * 1024 * 1024 },
});

const jobs = new Map<string, { outputPath: string; expiresAt: number }>();
const pipelinePath = path.join(process.cwd(), "server", "dubbing", "pipeline.py");

function uploadedFiles(req: Request) {
  const files = req.files as { [fieldname: string]: Express.Multer.File[] } | undefined;
  return {
    video: files?.video?.[0],
    subtitles: files?.subtitles?.[0],
  };
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

function runPipeline(videoPath: string, subtitlePath: string, outputPath: string) {
  return new Promise<void>((resolve, reject) => {
    const child = spawn("python3", [pipelinePath, "--video", videoPath, "--srt", subtitlePath, "--output", outputPath], {
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let stderr = "";
    child.stderr.on("data", chunk => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", code => {
      if (code === 0) resolve();
      else reject(new Error(stderr.trim().slice(-2500) || `Pipeline exited with code ${code ?? "unknown"}`));
    });
  });
}

export function registerDubbingRoutes(app: Express) {
  app.post("/api/dubbing/process", upload.fields([
    { name: "video", maxCount: 1 },
    { name: "subtitles", maxCount: 1 },
  ]), async (req, res) => {
    const { video, subtitles } = uploadedFiles(req);
    if (!video || !subtitles) {
      await removeUploadedFiles(video, subtitles);
      return res.status(400).json({ message: "ဗီဒီယိုနဲ့ SRT ဖိုင်နှစ်ခုလုံး တင်ပေးပါ။" });
    }
    if (!validVideo(video)) {
      await removeUploadedFiles(video, subtitles);
      return res.status(400).json({ message: "MP4 ဗီဒီယိုဖိုင်ကိုသာ အသုံးပြုနိုင်ပါတယ်။" });
    }
    if (!validSubtitles(subtitles)) {
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

    try {
      await fs.rename(video.path, videoPath);
      await fs.rename(subtitles.path, subtitlePath);
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
      const message = error instanceof Error ? error.message : "Dubbing pipeline failed";
      console.error("[Dubbing]", message);
      return res.status(500).json({ message: "Dubbing ပြုလုပ်ရာမှာ အမှားတစ်ခု ဖြစ်သွားပါတယ်။ Python/FFmpeg runtime ကို စစ်ပေးပါ။" });
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
