import {
  ArrowDownRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleAlert,
  Clapperboard,
  CloudDownload,
  FileAudio,
  FileVideo,
  LockKeyhole,
  Mic2,
  Play,
  Sparkles,
  UploadCloud,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import { useRef, useState } from "react";

type Stage = {
  id: string;
  title: string;
  caption: string;
};

const stages: Stage[] = [
  { id: "parse", title: "စာတန်းထိုးကို ဖတ်နေပါတယ်", caption: "SRT timeline ကို စစ်ဆေးခြင်း" },
  { id: "voice", title: "မြန်မာအသံ ထုတ်နေပါတယ်", caption: "Edge TTS · my-MM-ThihaNeural" },
  { id: "clips", title: "Video clip တွေကို ညှိနေပါတယ်", caption: "စာကြောင်းတိုင်းရဲ့ အချိန်ကိုက်မှု" },
  { id: "mix", title: "အသံနဲ့ ရုပ်ပုံကို ပေါင်းနေပါတယ်", caption: "Original audio ကို မြန်မာအသံနဲ့ အစားထိုးခြင်း" },
  { id: "export", title: "Final video ထုတ်နေပါတယ်", caption: "Download လုပ်လို့ရမယ့် MP4" },
];

const faqs = [
  {
    question: "ဘယ်လိုဖိုင်တွေ တင်လို့ရလဲ?",
    answer: "MP4 video တစ်ဖိုင်နဲ့ မြန်မာစာတန်းထိုးထားတဲ့ UTF-8 .srt ဖိုင်တစ်ဖိုင် လိုပါတယ်။ Subtitle timeline က video အတွင်းက အချိန်နဲ့ ကိုက်ညီနေရင် output က ပိုကောင်းပါတယ်။",
  },
  {
    question: "အသံက ဘယ်လိုထွက်မလဲ?",
    answer: "ဒီ version မှာ Microsoft Edge TTS ရဲ့ မြန်မာအသံ my-MM-ThihaNeural ကို သတ်မှတ်အသုံးပြုထားပါတယ်။ စာကြောင်းတစ်ကြောင်းချင်းစီကို အချိန်နဲ့ချိန်ပြီး video ထဲမှာ ပြန်ထည့်ပေးပါတယ်။",
  },
  {
    question: "ဖိုင်တွေကို သိမ်းထားမလား?",
    answer: "Processing အတွက် ယာယီသိမ်းပြီး output ကို download လုပ်နိုင်အောင် အချိန်ကန့်သတ်ထားတဲ့ job storage ထဲမှာ ထားပါတယ်။ ဒီ prototype မှာ account history မပါသေးပါ။",
  },
];

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileDropzone({
  kind,
  file,
  onSelect,
  onRemove,
  disabled,
}: {
  kind: "video" | "srt";
  file: File | null;
  onSelect: (file: File | null) => void;
  onRemove: () => void;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const isVideo = kind === "video";

  const acceptFile = (candidate?: File) => {
    if (!candidate) return;
    const good = isVideo
      ? candidate.name.toLowerCase().endsWith(".mp4")
      : candidate.name.toLowerCase().endsWith(".srt");
    if (good) onSelect(candidate);
    else onSelect(null);
  };

  return (
    <div
      className={`dropzone ${dragging ? "dropzone--dragging" : ""} ${file ? "dropzone--selected" : ""}`}
      onDragOver={event => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={event => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) acceptFile(event.dataTransfer.files?.[0]);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={isVideo ? ".mp4,video/mp4" : ".srt,application/x-subrip"}
        hidden
        disabled={disabled}
        onChange={event => acceptFile(event.target.files?.[0])}
      />
      {file ? (
        <div className="file-picked">
          <div className="file-picked__icon">{isVideo ? <FileVideo size={20} /> : <FileAudio size={20} />}</div>
          <div className="file-picked__copy">
            <strong>{file.name}</strong>
            <span>{formatBytes(file.size)} · {isVideo ? "MP4 video" : "UTF-8 subtitle"}</span>
          </div>
          <button type="button" className="icon-button" aria-label="Remove file" onClick={onRemove} disabled={disabled}>
            <X size={17} />
          </button>
        </div>
      ) : (
        <button type="button" className="dropzone__button" onClick={() => inputRef.current?.click()} disabled={disabled}>
          <span className="dropzone__icon">{isVideo ? <FileVideo size={24} /> : <FileAudio size={24} />}</span>
          <span className="dropzone__title">{isVideo ? "MP4 video တင်ပါ" : "မြန်မာ SRT တင်ပါ"}</span>
          <span className="dropzone__hint">ဖိုင်ရွေးရန် နှိပ်ပါ၊ သို့မဟုတ် ဒီနေရာကို ဆွဲချပါ</span>
          <span className="dropzone__format">{isVideo ? "MP4 · max 500MB" : "SRT · UTF-8 encoding"}</span>
        </button>
      )}
    </div>
  );
}

export default function Home() {
  const [video, setVideo] = useState<File | null>(null);
  const [subtitles, setSubtitles] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "processing" | "complete" | "error">("idle");
  const [stageIndex, setStageIndex] = useState(0);
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");

  const canStart = Boolean(video && subtitles && status !== "processing");

  const startProcessing = async () => {
    if (!video || !subtitles) return;
    setStatus("processing");
    setStageIndex(0);
    setError("");
    setDownloadUrl("");
    const timer = window.setInterval(() => setStageIndex(current => Math.min(current + 1, stages.length - 1)), 2600);
    try {
      const body = new FormData();
      body.append("video", video);
      body.append("subtitles", subtitles);
      const response = await fetch("/api/dubbing/process", { method: "POST", body });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.message || "Processing မအောင်မြင်ပါ။");
      setStageIndex(stages.length - 1);
      setDownloadUrl(result.downloadUrl || "");
      setStatus("complete");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "မမျှော်လင့်ထားတဲ့ error ဖြစ်သွားပါတယ်။");
      setStatus("error");
    } finally {
      window.clearInterval(timer);
    }
  };

  const reset = () => {
    setStatus("idle");
    setStageIndex(0);
    setError("");
    setDownloadUrl("");
  };

  return (
    <div className="site-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="dubwave home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span>dubwave</span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a href="#studio">စတင်မယ်</a>
          <a href="#how-it-works">အသုံးပြုပုံ</a>
          <a href="#faq">မေးလေ့ရှိတာ</a>
        </nav>
        <a href="#studio" className="header-cta">Try it now <ArrowUpRight size={15} /></a>
      </header>

      <main id="top">
        <section className="hero-section page-width">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-dot" /> MYANMAR VOICE STUDIO <span className="eyebrow-line" /></div>
            <h1>ဗီဒီယိုတိုင်းကို<br /><em>မြန်မာလို</em> ပြောပါစေ။</h1>
            <p className="hero-lead">Video တင်ပါ။ မြန်မာစာတန်းထိုးပေးပါ။ အသံထွက်နေတဲ့ dubbing video ကို ပြန်ရယူပါ။ ရှုပ်ထွေးတဲ့ editing မလိုပါဘူး။</p>
            <a className="primary-link" href="#studio">စတင် dubbing လုပ်မယ် <ArrowDownRight size={18} /></a>
            <div className="hero-proof"><span className="proof-avatars"><i>MM</i><i>EN</i><i>TH</i></span><span>မြန်မာဖန်တီးရှင်တွေအတွက်<br /><strong>ရိုးရှင်းတဲ့ video workflow</strong></span></div>
          </div>
          <div className="hero-visual" aria-label="Animated waveform decoration">
            <div className="orb orb--cyan" />
            <div className="orb orb--violet" />
            <div className="wave-card">
              <div className="wave-card__top"><span>LIVE SIGNAL / 01</span><span><span className="signal-dot" /> READY</span></div>
              <div className="waveform">{Array.from({ length: 42 }).map((_, index) => <i key={index} style={{ height: `${24 + ((index * 37) % 60)}%` }} />)}</div>
              <div className="wave-card__bottom"><span>ဘာသာပြန်ပြီး အသံထည့်မယ်</span><span>00:00:42</span></div>
            </div>
            <div className="floating-note floating-note--top"><Sparkles size={14} /> AI voice sync</div>
            <div className="floating-note floating-note--bottom"><span className="mini-wave" /> Myanmar voice / ready</div>
          </div>
        </section>

        <section className="studio-section page-width" id="studio">
          <div className="section-intro">
            <div><span className="section-number">01 / STUDIO</span><h2>အသံတစ်ခုနဲ့<br /><span>ဗီဒီယိုအသစ်</span> တစ်ခု။</h2></div>
            <p>သင့်ရဲ့ source video နဲ့ မြန်မာ subtitle ကို ထည့်ပါ။ ကျန်တာကို dubwave က ကိုင်တွယ်ပေးပါမယ်။</p>
          </div>
          <div className="studio-card">
            <div className="studio-card__header"><div><span className="card-kicker"><Zap size={13} /> DUBBING CONSOLE</span><h3>ဖိုင်တွေကို ဒီမှာထည့်ပါ</h3></div><div className="secure-label"><LockKeyhole size={14} /> Secure processing</div></div>
            {status === "processing" ? (
              <div className="progress-view">
                <div className="processing-head"><div><span className="card-kicker"><span className="processing-pulse" /> PROCESSING NOW</span><h3>အသံထွက်နေပါပြီ</h3></div><span className="processing-percent">{Math.min(96, 18 + stageIndex * 18)}%</span></div>
                <div className="processing-bar"><span style={{ width: `${Math.min(96, 18 + stageIndex * 18)}%` }} /></div>
                <div className="stage-list">{stages.map((stage, index) => <div className={`stage-row ${index < stageIndex ? "is-done" : ""} ${index === stageIndex ? "is-active" : ""}`} key={stage.id}><span className="stage-check">{index < stageIndex ? <Check size={14} /> : index === stageIndex ? <span /> : index + 1}</span><span><strong>{stage.title}</strong><small>{stage.caption}</small></span>{index === stageIndex && <span className="stage-live">RUNNING</span>}</div>)}</div>
                <div className="processing-foot"><div className="processing-spinner" /> <span>ဖိုင်အရှည်နဲ့ subtitle အရ processing အချိန် ကွာနိုင်ပါတယ်။ ဒီ tab ကို မပိတ်ပါနဲ့။</span></div>
              </div>
            ) : status === "complete" ? (
              <div className="complete-view"><div className="complete-icon"><Check size={30} /></div><span className="card-kicker complete-kicker">EXPORT COMPLETE</span><h3>မြန်မာ dubbing video အဆင်သင့်ပါပြီ။</h3><p>သင့်ရဲ့ `final_output.mp4` ကို အခု download လုပ်နိုင်ပါပြီ။</p><div className="complete-actions"><a className="download-button" href={downloadUrl} download="final_output.mp4"><CloudDownload size={18} /> Download final_output.mp4 <ArrowUpRight size={15} /></a><button type="button" className="text-button" onClick={reset}>ဖိုင်အသစ်နဲ့ ပြန်စမယ်</button></div></div>
            ) : (
              <>
                <div className="drop-grid"><div><label className="input-label"><span>01</span> SOURCE VIDEO</label><FileDropzone kind="video" file={video} onSelect={file => { setVideo(file); if (!file) setError("MP4 video ဖိုင်ကို ရွေးပေးပါ။"); else setError(""); }} onRemove={() => setVideo(null)} disabled={false} /></div><div><label className="input-label"><span>02</span> MYANMAR SUBTITLE</label><FileDropzone kind="srt" file={subtitles} onSelect={file => { setSubtitles(file); if (!file) setError(".srt subtitle ဖိုင်ကို ရွေးပေးပါ။"); else setError(""); }} onRemove={() => setSubtitles(null)} disabled={false} /></div></div>
                {error && <div className="inline-error"><CircleAlert size={16} /> {error}</div>}
                <div className="setup-summary"><div className="summary-item"><span className="summary-icon"><Mic2 size={17} /></span><span><small>VOICE ENGINE</small><strong>my-MM-ThihaNeural</strong></span></div><div className="summary-item"><span className="summary-icon"><WandSparkles size={17} /></span><span><small>OUTPUT</small><strong>Synced MP4 · no watermark</strong></span></div><button className="start-button" type="button" disabled={!canStart} onClick={startProcessing}>Start dubbing <ArrowUpRight size={17} /></button></div>
                <div className="studio-footnote"><LockKeyhole size={13} /> Files are processed for this job and held temporarily for download.</div>
              </>
            )}
          </div>
        </section>

        <section className="workflow-section page-width" id="how-it-works">
          <div className="section-intro section-intro--compact"><div><span className="section-number">02 / HOW IT WORKS</span><h2>အဆင့်သုံးဆင့်။<br /><span>အသံတစ်ခုလုံး။</span></h2></div><p>Video editing tool တွေကို အများကြီး လေ့လာစရာမလိုဘဲ subtitle timeline ကို မြန်မာအသံနဲ့ ချိတ်ပေးပါတယ်။</p></div>
          <div className="workflow-rail">{[{ number: "01", icon: <UploadCloud size={20} />, title: "ဖိုင်နှစ်ခု တင်ပါ", copy: "MP4 video နဲ့ မြန်မာ SRT ကို ရွေးပါ။" }, { number: "02", icon: <Mic2 size={20} />, title: "အသံကို တည်ဆောက်ပါ", copy: "စာကြောင်းတစ်ကြောင်းချင်းစီကို မြန်မာအသံနဲ့ ဖန်တီးပါတယ်။" }, { number: "03", icon: <CloudDownload size={20} />, title: "ပြီးရင် download လုပ်ပါ", copy: "အချိန်ကိုက်ထားတဲ့ final_output.mp4 ကို ရယူပါ။" }].map((item, index) => <div className="workflow-item" key={item.number}><div className="workflow-item__number">{item.number}</div><div className="workflow-item__icon">{item.icon}</div><h3>{item.title}</h3><p>{item.copy}</p>{index < 2 && <span className="workflow-arrow"><ArrowUpRight size={17} /></span>}</div>)}</div>
        </section>

        <section className="feature-banner page-width"><div className="feature-banner__glow" /><div className="feature-banner__copy"><span className="section-number">BUILT FOR LOCAL VOICE</span><h2>မြန်မာအသံက<br /><em>နောက်ကျမနေသင့်ဘူး။</em></h2><p>သင်ကြိုက်တဲ့ content ကို မြန်မာ audience အတွက် ပြန်အသက်သွင်းပါ။ တစ်ကြောင်းချင်းစီကို subtitle time နဲ့ တိတိကျကျ ချိန်ညှိထားပါတယ်။</p></div><div className="feature-specs"><div><span>VOICE</span><strong>ThihaNeural</strong></div><div><span>FORMAT</span><strong>MP4 + SRT</strong></div><div><span>OUTPUT</span><strong>Synced audio</strong></div></div></section>

        <section className="faq-section page-width" id="faq"><div className="section-intro section-intro--compact"><div><span className="section-number">03 / FAQ</span><h2>သိချင်တာ<br /><span>ရှိသေးလား?</span></h2></div><p>မသေချာတာရှိရင် ဒီမှာ အရင်ကြည့်ပါ။</p></div><div className="faq-list">{faqs.map(faq => <details key={faq.question}><summary>{faq.question}<span><ChevronDown size={18} /></span></summary><p>{faq.answer}</p></details>)}</div></section>
      </main>

      <footer className="site-footer page-width"><div className="footer-brand"><a className="brand" href="#top"><span className="brand-mark"><span /><span /><span /><span /></span><span>dubwave</span></a><p>မြန်မာဖန်တီးရှင်တွေအတွက်<br />AI dubbing studio.</p></div><div className="footer-cta"><span>READY WHEN YOU ARE</span><a href="#studio">ဗီဒီယိုတင်ပြီး စတင်မယ် <ArrowUpRight size={16} /></a></div><div className="footer-bottom"><span>© 2026 dubwave studio</span><span>Built for clearer stories.</span></div></footer>
    </div>
  );
}
