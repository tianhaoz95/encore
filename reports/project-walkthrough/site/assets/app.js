/* Encore walkthrough: interactive visualizations. No dependencies. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

  /* ------------------------------------------------------------ theme */
  const root = document.documentElement;
  try { const t = localStorage.getItem("encore-theme"); if (t) root.dataset.theme = t; } catch (e) {}
  $("#themeBtn").onclick = () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("encore-theme", root.dataset.theme); } catch (e) {}
    redrawAll();
  };

  /* ------------------------------------------------------- filmstrip */
  const track = $("#filmTrack");
  const srcCols = [["#3b0a45", "#e5487a"], ["#14063b", "#5b4ee6"], ["#2a0838", "#ff7ab8"], ["#0a1640", "#47a8ff"]];
  const genCols = [["#3a2617", "#f2b36b"], ["#2b2a1f", "#e6cf8b"], ["#2a1d1a", "#ff9e7a"], ["#1e2a24", "#9fd8b2"]];
  const labels = ["stage · wide", "crowd", "close-up", "lights", "studio · wide", "close-up", "two-shot", "b-roll"];
  let html = "";
  for (let rep = 0; rep < 4; rep++) {
    for (let i = 0; i < 8; i++) {
      const gen = i >= 4;
      const [a, b] = (gen ? genCols : srcCols)[i % 4];
      html += `<div class="frame" style="background:radial-gradient(circle at ${30 + (i * 17) % 50}% ${40 + (i * 13) % 30}%, ${b}, ${a} 70%)">
        <svg viewBox="0 0 168 96" style="position:absolute;inset:0;opacity:.55">${gen
          ? `<circle cx="60" cy="44" r="13" fill="#fff8"/><rect x="44" y="58" width="32" height="40" rx="12" fill="#fff6"/><circle cx="112" cy="46" r="12" fill="#fff6"/><rect x="97" y="59" width="30" height="40" rx="12" fill="#fff5"/>`
          : `<circle cx="84" cy="40" r="12" fill="#fff9"/><rect x="69" y="53" width="30" height="45" rx="12" fill="#fff7"/>${[...Array(9)].map((_, k) => `<circle cx="${8 + k * 19}" cy="92" r="7" fill="#0006"/>`).join("")}`}
        </svg><span>${gen ? "GEN" : "SRC"} · ${labels[i]}</span></div>`;
    }
  }
  track.innerHTML = html + html;

  /* ------------------------------------------------- reveal & triggers */
  const onVisible = new Map();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("in");
      const fns = onVisible.get(e.target);
      if (fns) { onVisible.delete(e.target); fns.forEach((fn) => fn()); }
    }
  }, { threshold: 0.18 });
  $$(".reveal").forEach((el) => io.observe(el));
  const whenVisible = (el, fn) => {
    if (!el) return;
    if (el.classList.contains("in")) return fn();
    onVisible.set(el, [...(onVisible.get(el) || []), fn]);
    io.observe(el);
  };

  /* --------------------------------------------------- nav highlight */
  const links = $$(".navlinks a");
  const secObs = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + e.target.id));
  }, { rootMargin: "-40% 0px -55% 0px" });
  $$("section[id]").forEach((s) => secObs.observe(s));

  /* ---------------------------------------------------- copy buttons */
  $$("pre").forEach((pre) => {
    const b = document.createElement("button");
    b.className = "copy"; b.textContent = "copy";
    b.onclick = async () => {
      const text = pre.querySelector("code").innerText.replace(/\s+#.*$/gm, "").replace(/\s+\/\/.*$/gm, "");
      try { await navigator.clipboard.writeText(text); b.textContent = "copied"; } catch (e) { b.textContent = "select + ⌘C"; }
      setTimeout(() => (b.textContent = "copy"), 1400);
    };
    pre.appendChild(b);
  });

  /* ------------------------------------------------------------ tabs */
  $$("#testTabs .tab").forEach((t) => t.onclick = () => {
    $$("#testTabs .tab").forEach((x) => x.classList.toggle("active", x === t));
    $$("#testing .tabpanel").forEach((p) => p.classList.toggle("active", p.id === t.dataset.tab));
  });

  /* ======================================================== PIPELINE */
  const A = (attrs) => Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ");
  const anim = (attr, values, dur, extra = "") => `<animate attributeName="${attr}" values="${values}" dur="${dur}" repeatCount="indefinite" ${extra}/>`;
  const T = (x, y, s, opt = {}) => `<text x="${x}" y="${y}" font-family="var(--sans)" font-size="${opt.size || 12}" text-anchor="${opt.anchor || "middle"}" fill="${opt.fill || "var(--ink)"}" font-weight="${opt.weight || 500}">${s}</text>`;

  const vizzes = {
    analyze: () => {
      let s = "";
      for (let i = 0; i < 6; i++) s += `<rect x="${20 + i * 60}" y="20" width="54" height="36" rx="4" fill="${i < 3 ? "#5b4ee6" : "#e5487a"}" opacity=".75"/>`;
      s += `<line x1="197" y1="12" x2="197" y2="64" stroke="var(--accent-2)" stroke-width="3">${anim("opacity", "0;1;1;0", "2.4s")}</line>${T(197, 76, "cut detected", { size: 10, fill: "var(--accent-2)" })}`;
      let wave = "", voc = "", mus = "";
      for (let i = 0; i < 68; i++) {
        const x = 20 + i * 4, h = 6 + Math.abs(Math.sin(i * 0.7) * 16 + Math.sin(i * 0.23) * 10);
        wave += `<rect x="${x}" y="${120 - h / 2}" width="2.5" height="${h}" fill="var(--muted)"/>`;
        const hv = (i % 22 < 12) ? 4 + Math.abs(Math.sin(i * 1.3)) * 14 : 1;
        voc += `<rect x="${x}" y="${180 - hv / 2}" width="2.5" height="${hv}" fill="var(--accent)"/>`;
        const hm = 4 + Math.abs(Math.sin(i * 0.4)) * 12;
        mus += `<rect x="${x}" y="${222 - hm / 2}" width="2.5" height="${hm}" fill="var(--spark)" opacity=".7"/>`;
      }
      s += wave + T(410, 124, "mix", { anchor: "end", size: 11, fill: "var(--muted)" });
      s += `<g>${anim("opacity", "0;0;1;1", "4s")}${voc}${T(410, 184, "vocals → ASR", { anchor: "end", size: 11, fill: "var(--accent)" })}${mus}${T(410, 226, "instrumental", { anchor: "end", size: 11, fill: "var(--spark)" })}</g>`;
      s += `<rect x="236" y="22" width="26" height="30" fill="none" stroke="#ffd166" stroke-width="2">${anim("opacity", "0;1;1;0", "2s", 'begin="0.8s"')}</rect>`;
      return `<svg viewBox="0 0 420 250">${s}</svg>`;
    },
    bible: () => {
      const pts = [[60, 60], [80, 80], [70, 50], [95, 65], [180, 160], [200, 140], [170, 150], [190, 175], [60, 180]];
      let s = pts.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="7" fill="${i < 4 ? "var(--accent)" : i < 8 ? "var(--accent-2)" : "var(--muted)"}">${anim("r", "7;9;7", "2s", `begin="${i * 0.15}s"`)}</circle>`).join("");
      s += `<circle cx="76" cy="64" r="34" fill="none" stroke="var(--accent)" stroke-dasharray="4 4"/><circle cx="185" cy="156" r="32" fill="none" stroke="var(--accent-2)" stroke-dasharray="4 4"/>`;
      s += T(60, 210, "noise", { size: 10, fill: "var(--muted)" });
      const card = (y, col, name, desc) => `<g transform="translate(250 ${y})"><rect width="160" height="80" rx="10" fill="var(--panel)" stroke="${col}"/>
        <rect x="10" y="12" width="40" height="40" rx="6" fill="${col}" opacity=".35"/><circle cx="30" cy="28" r="9" fill="${col}"/>
        ${T(58, 28, name, { anchor: "start", weight: 700 })}${T(58, 46, desc, { anchor: "start", size: 10, fill: "var(--muted)" })}
        <g transform="translate(10 60)">${[...Array(14)].map((_, k) => `<rect x="${k * 10}" y="${6 - (3 + (k * 7) % 6)}" width="6" height="${2 * (3 + (k * 7) % 6)}" fill="${col}" opacity=".6"/>`).join("")}</g></g>`;
      s += card(20, "var(--accent)", "char_0", "silver hair · voice ✓") + card(130, "var(--accent-2)", "char_1", "red jacket · voice ✓");
      s += `<path d="M110 64 C 180 60, 200 50, 250 56" stroke="var(--accent)" fill="none" stroke-dasharray="5 5">${anim("stroke-dashoffset", "20;0", "1s")}</path>`;
      s += `<path d="M217 156 C 230 160, 236 168, 250 168" stroke="var(--accent-2)" fill="none" stroke-dasharray="5 5">${anim("stroke-dashoffset", "20;0", "1s")}</path>`;
      return `<svg viewBox="0 0 420 230">${s}</svg>`;
    },
    script: () => {
      const lines = ['{ "id": "s01", "kind": "talking",', '  "framing": "wide",', '  "setting": "podcast studio",', '  "lines": [{"speaker": "host",', '     "text": "Welcome back!"}] }', '{ "id": "s02", "kind": "talking", …'];
      let s = `<rect x="10" y="80" width="110" height="70" rx="12" fill="var(--accent-soft)" stroke="var(--accent)"/>${T(65, 110, "local LLM", { weight: 700 })}${T(65, 128, "Qwen3 · JSON schema", { size: 10, fill: "var(--muted)" })}`;
      s += `<rect x="150" y="16" width="260" height="200" rx="10" fill="var(--code-bg)"/>`;
      lines.forEach((l, i) => {
        s += `<text x="162" y="${44 + i * 28}" font-family="var(--mono)" font-size="11" fill="#e8e6f0" opacity="0">${l.replace(/</g, "&lt;")}<animate attributeName="opacity" values="0;1" dur="0.3s" begin="${0.4 + i * 0.45}s" fill="freeze"/></text>`;
      });
      s += `<path d="M120 115 H150" stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 4">${anim("stroke-dashoffset", "16;0", ".8s")}</path>`;
      s += T(65, 180, "normalize()", { size: 11, fill: "var(--spark)", weight: 700 }) + T(65, 196, "repairs ids & speakers", { size: 10, fill: "var(--muted)" });
      return `<svg viewBox="0 0 420 230">${s}</svg>`;
    },
    voices: () => {
      let s = "";
      const rows = [["mix", "var(--ink-2)", [[0.05, 0.35], [0.42, 0.9]]], ["host", "var(--muted)", [[0.05, 0.35]]], ["char_0", "var(--accent)", [[0.42, 0.9]]]];
      rows.forEach(([name, col, spans], r) => {
        const y = 40 + r * 64;
        s += T(56, y + 4, name, { anchor: "end", size: 11, fill: "var(--muted)" });
        s += `<rect x="64" y="${y - 22}" width="340" height="44" rx="6" fill="var(--panel)"/>`;
        for (let i = 0; i < 85; i++) {
          const t = i / 85, on = spans.some(([a, b]) => t >= a && t <= b);
          const h = on ? 4 + Math.abs(Math.sin(i * 1.7) * 14 + Math.sin(i * 0.5) * 8) : 1.2;
          s += `<rect x="${66 + i * 4}" y="${y - h / 2}" width="2.6" height="${h}" fill="${col}"/>`;
        }
      });
      s += `<line x1="64" y1="10" x2="64" y2="220" stroke="var(--accent-2)" stroke-width="2"><animate attributeName="x1" values="64;404" dur="4s" repeatCount="indefinite"/><animate attributeName="x2" values="64;404" dur="4s" repeatCount="indefinite"/></line>`;
      return `<svg viewBox="0 0 420 230">${s}</svg>`;
    },
    keyframes: () => {
      let s = `<rect x="20" y="70" width="150" height="90" rx="10" fill="var(--accent-soft)" stroke="var(--accent)"/>${T(95, 108, "MASTER", { weight: 700 })}${T(95, 126, "everyone · wide", { size: 10, fill: "var(--muted)" })}`;
      const kids = ["s02 closeup", "s03 medium", "s04 b-roll"];
      kids.forEach((k, i) => {
        const y = 14 + i * 74;
        s += `<g opacity="0"><animate attributeName="opacity" values="0;1" dur=".4s" begin="${0.5 + i * 0.5}s" fill="freeze"/><rect x="260" y="${y}" width="140" height="58" rx="8" fill="var(--panel)" stroke="var(--talking)"/>${T(330, y + 26, k, { weight: 600 })}<text x="330" y="${y + 44}" text-anchor="middle" font-size="10" fill="var(--spark)" font-family="var(--sans)">identity ${[0.71, 0.64, "—"][i]}</text></g>`;
        s += `<path d="M170 115 C 215 115, 215 ${y + 29}, 260 ${y + 29}" stroke="var(--muted)" fill="none" stroke-dasharray="4 4">${anim("stroke-dashoffset", "16;0", "1s")}</path>`;
      });
      return `<svg viewBox="0 0 420 230">${s}</svg>`;
    },
    shoot: () => {
      let s = `<rect x="16" y="70" width="110" height="70" rx="8" fill="var(--panel)" stroke="var(--line)"/>${T(71, 100, "keyframe", { weight: 600 })}${T(71, 118, "+ dialogue.wav", { size: 10, fill: "var(--muted)" })}`;
      s += `<rect x="146" y="80" width="80" height="50" rx="8" fill="var(--spark-soft)" stroke="var(--spark)"/>${T(186, 102, "Spark", { weight: 700, fill: "var(--spark)" })}${T(186, 118, "lip sync / i2v", { size: 9, fill: "var(--muted)" })}`;
      for (let i = 0; i < 5; i++) {
        s += `<g><rect x="${244 + i * 34}" y="80" width="30" height="50" rx="4" fill="var(--talking)" opacity="${0.35 + i * 0.13}"/><circle cx="${259 + i * 34}" cy="98" r="6" fill="#fff9"/><ellipse cx="${259 + i * 34}" cy="110" rx="4" ry="${1 + (i % 3)}" fill="#0008">${anim("ry", "1;3;1", ".5s", `begin="${i * 0.1}s"`)}</ellipse></g>`;
      }
      s += `<path d="M126 105 H146 M226 105 H244" stroke="var(--muted)" stroke-width="2"/>`;
      s += T(320, 160, "frames, then mp4", { size: 11, fill: "var(--muted)" });
      return `<svg viewBox="0 0 420 230">${s}</svg>`;
    },
    edit: () => {
      const parts = [["src", "#595966", 70], ["s01", "var(--talking)", 60], ["s02", "var(--talking)", 80], ["s03", "var(--broll)", 50], ["s04", "var(--talking)", 70]];
      let s = "", x = 20;
      parts.forEach(([n, c, w], i) => {
        s += `<g><animateTransform attributeName="transform" type="translate" values="0 ${-30 + i * 12};0 0" dur=".6s" begin="${i * 0.25}s" fill="freeze"/><rect x="${x}" y="60" width="${w - 3}" height="40" rx="6" fill="${c}"/>${T(x + w / 2, 85, n, { fill: "#fff", weight: 700 })}</g>`;
        x += w;
      });
      s += `<rect x="20" y="112" width="330" height="18" rx="4" fill="var(--panel)" stroke="var(--line)"/>${T(185, 125, "dialogue · loudnorm −16 LUFS", { size: 10, fill: "var(--muted)" })}`;
      s += `<rect x="20" y="136" width="330" height="18" rx="4" fill="var(--panel)" stroke="var(--line)" stroke-dasharray="3 3"/>${T(185, 149, "subtitles.srt", { size: 10, fill: "var(--muted)" })}`;
      s += `<rect x="270" y="66" width="74" height="14" rx="3" fill="#0007"/>${T(307, 77, "AI-GENERATED", { size: 8, fill: "#fff", weight: 700 })}`;
      s += `<rect x="20" y="172" width="330" height="40" rx="8" fill="none" stroke="var(--accent)" stroke-width="2" opacity="0"><animate attributeName="opacity" values="0;1" dur=".5s" begin="1.6s" fill="freeze"/></rect>`;
      s += `<text x="185" y="197" text-anchor="middle" font-family="var(--sans)" font-size="13" font-weight="700" fill="var(--accent)" opacity="0">output/final.mp4<animate attributeName="opacity" values="0;1" dur=".5s" begin="1.6s" fill="freeze"/></text>`;
      return `<svg viewBox="0 0 370 230">${s}</svg>`;
    },
  };

  const STAGES = [
    { id: "analyze", where: "mac", title: "Analyze the clip",
      blurb: "Learn everything the later stages need from the source clip.",
      inp: "source/clip.mp4", out: "analysis/analysis.json, frames, face crops, stems",
      bullets: ["Shot cuts via PySceneDetect or ffmpeg's scene score; one keyframe per scene", "Demucs splits vocals from the music, so concert audio can be transcribed", "Whisper (MLX on Mac, faster-whisper on CUDA) + optional pyannote speaker labels", "Faces at 2 fps → ArcFace embeddings → identity clusters", "VLM describes summary, setting, visual style; Lab color stats saved for grading"],
      code: "stages/analyze.py · analyze/*.py" },
    { id: "bible", where: "mac", title: "Build the Story Bible",
      blurb: "Turn face clusters into named characters with a look and a voice.",
      inp: "analysis.json", out: "bible.json, cast/char_*/ref_*.jpg, voice_ref.wav, embedding.npy",
      bullets: ["Top clusters become characters (max 8); --names pre-fills names", "Best 6 crops by confidence × size × sharpness, spread over time", "VLM writes a one-line appearance description for image prompts (no names)", "Speech segments are linked to characters by on-screen co-occurrence, giving 12 s voice samples", "Checkpoint 1: rename, disable extras, upload a better voice"],
      code: "stages/bible.py" },
    { id: "script", where: "mac", title: "Write the script",
      blurb: "A local LLM writes dialogue and the shot list as strict JSON.",
      inp: "bible.json + your prompt", out: "script.json",
      bullets: ["The prompt includes the clip summary, style, transcript excerpt and cast ids", "Requests a json_schema response; falls back gracefully; errors fed back for retries", "normalize() repairs ids, speakers and shot kinds", "`encore revise` / UI 'Revise' applies natural-language edits", "Template backend for runs without an LLM"],
      code: "write/scriptwriter.py" },
    { id: "voices", where: "spark", title: "Voice the lines",
      blurb: "Voice-cloned TTS per line, laid out into a timed dialogue track.",
      inp: "script.json, voice refs", out: "audio/<shot>.wav, <shot>.<char>.wav, <shot>.json",
      bullets: ["Chatterbox Multilingual (incl. Korean) or F5-TTS via the worker", "Speakers not in the clip (host, narrator) use stock voices", "Content-hash cache: edit one line and only that line re-renders", "Per-speaker tracks for multi-person lip sync", "Shot durations are rewritten to match the real audio"],
      code: "stages/voices.py · backends/tts.py" },
    { id: "keyframes", where: "spark", title: "Generate keyframes",
      blurb: "One approved still per shot, consistent across shots.",
      inp: "script, face refs, source frames", out: "keyframes/master_*.png, <shot>.png",
      bullets: ["A master frame per setting from stitched face references (FLUX Kontext)", "Other shots are edits of the master plus the relevant face reference", "extend shots use the source's real last frame", "ArcFace QC: retry below 0.35 identity similarity, keep the best", "Checkpoint 2: regenerate stills before spending video minutes"],
      code: "stages/keyframes.py · backends/image.py" },
    { id: "shoot", where: "spark", title: "Shoot the shots",
      blurb: "Animate each still: lip-synced talking or motion b-roll.",
      inp: "keyframes, dialogue tracks", out: "shots/<shot>.mp4",
      bullets: ["talking → InfiniteTalk/MultiTalk (worker) or Wan S2V (ComfyUI)", "Multi-speaker: faces matched to characters, tracks ordered left→right, bboxes sent", "broll / extend → Wan 2.2 image-to-video via ComfyUI", "Shots over ~5 s are chained from each segment's last frame", "kenburns fallback for dry runs"],
      code: "stages/shoot.py · backends/video.py" },
    { id: "edit", where: "mac", title: "Edit the film",
      blurb: "Assemble a finished, labeled film.",
      inp: "shots, dialogue, source", out: "output/final.mp4, final.srt",
      bullets: ["Conform to 1280×720 at 25 fps; hold the last frame if the video is shorter than the audio", "Reinhard Lab transfer baked into a 3D LUT (ffmpeg lut3d) + grain", "Source clip first, optional crossfades, optional ducked music bed", "loudnorm to −16 LUFS, SRT with speaker names, optional burn-in", "AI-GENERATED watermark + metadata note"],
      code: "stages/edit.py · core/color.py" },
  ];

  let stageIdx = 0, playing = false;
  const stagesEl = $("#stages");
  stagesEl.innerHTML = STAGES.map((s, i) => `<button class="stage-btn" data-i="${i}"><div class="n">${i + 1}</div><div class="nm">${s.id}</div><div class="wh"><span class="pill ${s.where}">${s.where === "mac" ? "Mac" : "Spark"}</span></div></button>`).join("");
  $$(".stage-btn").forEach((b) => b.onclick = () => { playing = false; showStage(+b.dataset.i); });

  function showStage(i) {
    stageIdx = (i + STAGES.length) % STAGES.length;
    const s = STAGES[stageIdx];
    $$(".stage-btn").forEach((b, k) => { b.classList.toggle("active", k === stageIdx); b.classList.toggle("done", k < stageIdx); });
    $("#railFill").style.width = `${((stageIdx + 1) / STAGES.length) * 100}%`;
    $("#stageDetail").innerHTML = `<div>
        <div class="row" style="display:flex;gap:8px;align-items:center"><span class="pill ${s.where}">${s.where === "mac" ? "runs on Mac Studio" : "runs on DGX Spark"}</span><code>${s.code}</code></div>
        <h3 style="margin:12px 0 4px">${stageIdx + 1}. ${s.title}</h3>
        <p style="margin:0">${s.blurb}</p>
        <div class="io"><div><b>reads</b>${s.inp}</div><div><b>writes</b>${s.out}</div></div>
        <ul>${s.bullets.map((b) => `<li>${b.replace(/`([^`]+)`/g, "<code>$1</code>")}</li>`).join("")}</ul>
      </div>
      <div class="stage-viz">${vizzes[s.id]()}</div>`;
    $("#stageHint").textContent = `stage ${stageIdx + 1} of ${STAGES.length}`;
  }
  $("#prevBtn").onclick = () => { playing = false; showStage(stageIdx - 1); };
  $("#nextBtn").onclick = () => { playing = false; showStage(stageIdx + 1); };
  $("#playBtn").onclick = async () => {
    if (playing) { playing = false; return; }
    playing = true; $("#playBtn").textContent = "❚❚ Pause";
    for (let i = stageIdx === STAGES.length - 1 ? 0 : stageIdx; i < STAGES.length && playing; i++) {
      showStage(i);
      await sleep(4200);
    }
    playing = false; $("#playBtn").textContent = "▶ Play run";
  };
  showStage(0);

  /* ================================================== SCRIPT TIMELINE */
  const SHOTS = [
    { id: "source", kind: "src", d: 8, lines: [] },
    { id: "s01 extend", kind: "extend", d: 4, lines: [] },
    { id: "s02 wide", kind: "talking", d: 6.4, lines: [["Host", "Welcome back! Tonight we have the whole group."]] },
    { id: "s03 close", kind: "talking", d: 7.5, lines: [["Host", "How did the encore feel?"], ["Mina", "Honestly? I cried."]] },
    { id: "s04 b-roll", kind: "broll", d: 4, lines: [] },
    { id: "s05 two", kind: "talking", d: 8, lines: [["Jun", "We practiced that for months."], ["Mina", "And we still messed up the ending!"]] },
  ];
  const total = SHOTS.reduce((a, s) => a + s.d, 0);
  function renderTimeline() {
    let v = "", sub = "", t = 0;
    for (const s of SHOTS) {
      v += `<div class="tl-seg ${s.kind}" style="left:${(t / total) * 100}%;width:calc(${(s.d / total) * 100}% - 3px)">${s.id}</div>`;
      let lt = t + 0.3;
      const per = s.lines.length ? (s.d - 0.8) / s.lines.length : 0;
      for (const [who, text] of s.lines) {
        sub += `<div class="tl-seg sub" data-t0="${lt}" data-t1="${lt + per - 0.35}" style="left:${(lt / total) * 100}%;width:calc(${((per - 0.35) / total) * 100}% - 2px)" title="${who}: ${text}">${who}: ${text}</div>`;
        lt += per;
      }
      t += s.d;
    }
    $("#scriptTimeline").innerHTML = `
      <div class="tl-row"><div class="tl-label">video</div><div class="tl-track">${v}<div class="playhead" id="ph1"></div></div></div>
      <div class="tl-row"><div class="tl-label">dialogue</div><div class="tl-track"><canvas id="tlWave" height="36" style="height:36px;border-radius:0;background:none"></canvas><div class="playhead" id="ph2"></div></div></div>
      <div class="tl-row"><div class="tl-label">subtitles</div><div class="tl-track">${sub}<div class="playhead" id="ph3"></div></div></div>
      <div class="tl-row"><div class="tl-label"></div><div style="flex:1;display:flex;justify-content:space-between;font:11px var(--mono);color:var(--muted)"><span>0s</span><span>${(total / 2).toFixed(0)}s</span><span>${total.toFixed(0)}s</span></div></div>`;
    drawTlWave();
  }
  function drawTlWave() {
    const c = $("#tlWave"); if (!c) return;
    const w = c.clientWidth || 600; c.width = w * 2; c.height = 72;
    const g = c.getContext("2d"); g.scale(2, 2);
    const subs = $$("#scriptTimeline .tl-seg.sub").map((e) => [+e.dataset.t0, +e.dataset.t1]);
    g.fillStyle = css("--accent");
    for (let x = 0; x < w; x += 3) {
      const t = (x / w) * total, on = subs.some(([a, b]) => t >= a && t <= b);
      const h = on ? 4 + Math.abs(Math.sin(x * 0.31) * 12 + Math.sin(x * 0.07) * 8) : 0.8;
      g.fillRect(x, 18 - h / 2, 2, h);
    }
  }
  renderTimeline();
  let tlRaf = null;
  $("#tlPlay").onclick = () => {
    cancelAnimationFrame(tlRaf);
    const start = performance.now(), dur = reduced ? 1 : 9000;
    const step = (now) => {
      const p = Math.min((now - start) / dur, 1), t = p * total;
      ["#ph1", "#ph2", "#ph3"].forEach((id) => { const e = $(id); if (e) e.style.left = `${p * 100}%`; });
      let acc = 0, cur = SHOTS[0];
      for (const s of SHOTS) { if (t >= acc) cur = s; acc += s.d; }
      const live = $$("#scriptTimeline .tl-seg.sub").find((e) => t >= +e.dataset.t0 && t <= +e.dataset.t1);
      $("#tlNow").textContent = `${t.toFixed(1)}s · ${cur.id}${live ? " · “" + live.title + "”" : ""}`;
      if (p < 1) tlRaf = requestAnimationFrame(step);
    };
    tlRaf = requestAnimationFrame(step);
  };

  /* ================================================ FACE CLUSTERING */
  const cv = $("#clusterCanvas");
  let clusterTimer = null;
  function clusterDemo() {
    clearTimeout(clusterTimer);
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const centers = [[130, 110], [360, 120], [250, 250]];
    const cols = [css("--accent"), css("--accent-2"), css("--spark")];
    const pts = [];
    centers.forEach(([cx, cy], k) => { for (let i = 0; i < 12 - k * 2; i++) pts.push({ x: cx + (rnd() - .5) * 90, y: cy + (rnd() - .5) * 70, k }); });
    for (let i = 0; i < 4; i++) pts.push({ x: 40 + rnd() * (W - 80), y: 30 + rnd() * (H - 60), k: -1 });
    let clusters = pts.map((p, i) => ({ m: [i] }));
    const cen = (c) => { const xs = c.m.map((i) => pts[i]); return [xs.reduce((a, p) => a + p.x, 0) / xs.length, xs.reduce((a, p) => a + p.y, 0) / xs.length]; };
    const avgDist = (a, b) => { let s = 0; for (const i of a.m) for (const j of b.m) s += Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y); return s / (a.m.length * b.m.length); };
    const THR = 85;
    const draw = (done) => {
      g.clearRect(0, 0, W, H);
      g.font = "12px " + css("--sans").split(",")[0];
      for (const c of clusters) {
        const big = c.m.length >= 3, [cx, cy] = cen(c);
        const label = big ? clusters.filter((x) => x.m.length >= 3).sort((a, b) => b.m.length - a.m.length).indexOf(c) : -1;
        const col = big ? cols[label % 3] : css("--muted");
        if (c.m.length > 1) for (const i of c.m) { g.strokeStyle = col + "66"; g.beginPath(); g.moveTo(cx, cy); g.lineTo(pts[i].x, pts[i].y); g.stroke(); }
        for (const i of c.m) { g.fillStyle = col; g.beginPath(); g.arc(pts[i].x, pts[i].y, 5, 0, 7); g.fill(); }
        if (done && big) { g.fillStyle = col; g.fillText(`char_${label} · ${c.m.length} faces`, cx - 40, cy - 48); }
      }
    };
    let steps = 0;
    const tick = () => {
      let best = null, bd = 1e9;
      for (let a = 0; a < clusters.length; a++) for (let b = a + 1; b < clusters.length; b++) { const d = avgDist(clusters[a], clusters[b]); if (d < bd) { bd = d; best = [a, b]; } }
      if (!best || bd > THR) {
        draw(true);
        const n = clusters.filter((c) => c.m.length >= 3).length, noise = clusters.filter((c) => c.m.length < 3).reduce((a, c) => a + c.m.length, 0);
        $("#clusterInfo").textContent = `stopped: closest pair above threshold · ${n} characters, ${noise} noise faces`;
        return;
      }
      const [a, b] = best;
      clusters[a] = { m: clusters[a].m.concat(clusters[b].m) };
      clusters.splice(b, 1);
      steps++;
      $("#clusterInfo").textContent = `merge ${steps}: average-linkage distance ${bd.toFixed(0)}`;
      draw(false);
      clusterTimer = setTimeout(tick, reduced ? 0 : 140);
    };
    draw(false);
    clusterTimer = setTimeout(tick, 500);
  }
  whenVisible(cv.closest(".reveal"), clusterDemo);
  $("#clusterReplay").onclick = clusterDemo;

  /* ======================================================== VOICES */
  const VOICE_LINES = [["host", 0.3, 2.4, "How did the encore feel?"], ["char_0", 2.75, 5.9, "Honestly? I cried."], ["char_1", 6.25, 9.2, "We practiced for months!"]];
  const VT = 9.7;
  function renderVoices() {
    const rows = [["mix", null], ["host", "host"], ["char_0", "char_0"], ["char_1", "char_1"]];
    const colors = { host: "--muted", char_0: "--accent", char_1: "--accent-2" };
    $("#voiceTracks").innerHTML = rows.map(([label]) => `<div class="tl-row"><div class="tl-label" style="width:64px">${label}</div><div class="tl-track"><canvas data-row="${label}" height="36" style="height:36px;border-radius:0;background:none"></canvas><div class="playhead vph"></div></div></div>`).join("") +
      `<div class="muted" style="font-size:12px;margin-top:6px" id="voiceNow">mix = all lines; each character track is silent while others speak</div>`;
    $$("#voiceTracks canvas").forEach((c) => {
      const w = c.clientWidth || 400; c.width = w * 2; c.height = 72;
      const g = c.getContext("2d"); g.scale(2, 2);
      const row = c.dataset.row;
      for (let x = 0; x < w; x += 3) {
        const t = (x / w) * VT;
        const line = VOICE_LINES.find(([, a, b]) => t >= a && t <= b);
        const on = line && (row === "mix" || line[0] === row);
        g.fillStyle = css(colors[line ? line[0] : "host"]) || "#888";
        const h = on ? 4 + Math.abs(Math.sin(x * 0.37) * 11 + Math.sin(x * 0.09) * 8) : 0.8;
        if (!on) g.fillStyle = css("--line");
        g.fillRect(x, 18 - h / 2, 2, h);
      }
    });
  }
  renderVoices();
  $("#voicePlay").onclick = () => {
    const start = performance.now(), dur = reduced ? 1 : 6000;
    const step = (now) => {
      const p = Math.min((now - start) / dur, 1), t = p * VT;
      $$(".vph").forEach((e) => (e.style.left = `${p * 100}%`));
      const line = VOICE_LINES.find(([, a, b]) => t >= a && t <= b);
      $("#voiceNow").textContent = line ? `${t.toFixed(1)}s · ${line[0]}: “${line[3]}” → drives ${line[0] === "host" ? "no on-screen mouth (host is off-camera)" : line[0] + "'s mouth"}` : `${t.toFixed(1)}s · gap`;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  whenVisible($("#voiceTracks").closest(".reveal"), () => $("#voicePlay").click());

  /* ============================================================ QC */
  async function qcDemo() {
    const box = $("#qcBars");
    $$(".bar", box).forEach((b) => b.remove());
    const attempts = [["master try 1", 0.22], ["master try 2", 0.41], ["s02 try 1", 0.58], ["s03 try 1", 0.29], ["s03 try 2", 0.31], ["s03 try 3", 0.52]];
    for (const [name, v] of attempts) {
      const bar = document.createElement("div");
      bar.className = "bar"; bar.title = name;
      bar.innerHTML = `<span>${v.toFixed(2)}</span>`;
      box.appendChild(bar);
      await sleep(60);
      bar.style.height = `${v * 130}%`;
      bar.style.maxHeight = "100%";
      await sleep(450);
      bar.classList.add(v >= 0.35 ? "ok" : "no");
      $("#qcInfo").textContent = `${name}: ${v >= 0.35 ? "accepted ✓" : "below threshold → new seed"}`;
      await sleep(500);
    }
    $("#qcInfo").textContent = "master accepted on try 2 · s03 needed 3 tries";
  }
  whenVisible($("#qcBars").closest(".reveal"), qcDemo);
  $("#qcReplay").onclick = qcDemo;
  whenVisible($("#masterTree").closest(".reveal"), () => {
    $$("#masterTree .kf").forEach((g, i) => { g.style.opacity = 0; g.style.transition = "opacity .5s"; setTimeout(() => (g.style.opacity = 1), 400 + i * 350); });
  });

  /* ======================================================== CHAINING */
  async function chainDemo() {
    const svg = $("#chainSvg");
    const segs = 3, w = 140, gap = 30;
    let s = `<text x="10" y="20" font-family="var(--sans)" font-size="12" fill="var(--muted)">12 s b-roll shot → 3 × 4 s segments</text>`;
    for (let i = 0; i < segs; i++) {
      const x = 10 + i * (w + gap);
      s += `<g class="seg${i}" opacity="0"><rect x="${x}" y="40" width="${w}" height="70" rx="8" fill="var(--broll)" opacity=".85"/>`;
      for (let f = 0; f < 6; f++) s += `<rect x="${x + 8 + f * 21}" y="52" width="17" height="46" rx="3" fill="#fff" opacity="${0.15 + f * 0.08}"/>`;
      s += `<text x="${x + w / 2}" y="128" text-anchor="middle" font-family="var(--sans)" font-size="11" fill="var(--ink-2)">seg ${i + 1} ← ${i === 0 ? "keyframe" : "last frame of " + i}</text></g>`;
      if (i < segs - 1) s += `<path class="arr${i}" d="M${x + w - 10} 75 C ${x + w + 10} 20, ${x + w + gap + 10} 20, ${x + w + gap + 12} 70" fill="none" stroke="var(--accent-2)" stroke-width="2" stroke-dasharray="4 4" opacity="0"/>`;
    }
    s += `<rect class="cat" x="10" y="146" width="${segs * w + (segs - 1) * gap}" height="14" rx="4" fill="var(--broll)" opacity="0"/>`;
    svg.innerHTML = s;
    for (let i = 0; i < segs; i++) {
      await sleep(350); svg.querySelector(`.seg${i}`).setAttribute("opacity", 1);
      if (i < segs - 1) { await sleep(450); svg.querySelector(`.arr${i}`).setAttribute("opacity", 1); }
    }
    await sleep(400); svg.querySelector(".cat").setAttribute("opacity", 0.9);
  }
  whenVisible($("#chainSvg").closest(".reveal"), chainDemo);
  $("#chainReplay").onclick = chainDemo;

  /* ============================================================ LUT */
  const srgb2lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const lin2srgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  function rgb2lab([r, g, b]) {
    [r, g, b] = [r, g, b].map((v) => srgb2lin(v / 255));
    let x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047, y = r * 0.2126 + g * 0.7152 + b * 0.0722, z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    [x, y, z] = [f(x), f(y), f(z)];
    return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
  }
  function lab2rgb([L, a, b]) {
    let y = (L + 16) / 116, x = a / 500 + y, z = y - b / 200;
    const fi = (t) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
    [x, y, z] = [fi(x) * 0.95047, fi(y), fi(z) * 1.08883];
    const r = x * 3.2406 + y * -1.5372 + z * -0.4986, g = x * -0.9689 + y * 1.8758 + z * 0.0415, bb = x * 0.0557 + y * -0.204 + z * 1.057;
    return [r, g, bb].map((v) => Math.round(Math.min(1, Math.max(0, lin2srgb(Math.max(0, v)))) * 255));
  }
  const SRC = [[58, 12, 70], [140, 30, 110], [229, 72, 122], [91, 78, 230], [20, 10, 40], [255, 140, 200], [60, 40, 120], [200, 60, 160]];
  const GEN = [[205, 190, 170], [150, 140, 120], [230, 215, 190], [120, 130, 140], [80, 75, 70], [245, 235, 220], [170, 160, 150], [190, 170, 140]];
  const stats = (cols) => {
    const labs = cols.map(rgb2lab), m = [0, 1, 2].map((k) => labs.reduce((a, l) => a + l[k], 0) / labs.length);
    const s = [0, 1, 2].map((k) => Math.sqrt(labs.reduce((a, l) => a + (l[k] - m[k]) ** 2, 0) / labs.length) + 1e-3);
    return { m, s, labs };
  };
  const sSrc = stats(SRC), sGen = stats(GEN);
  $("#swSrc").innerHTML = SRC.map((c) => `<div style="background:rgb(${c})"></div>`).join("");
  $("#swGen").innerHTML = GEN.map(() => `<div></div>`).join("");
  function applyLut(strength) {
    $("#lutVal").textContent = strength.toFixed(2);
    $$("#swGen div").forEach((d, i) => {
      const lab = sGen.labs[i];
      const moved = lab.map((v, k) => (v - sGen.m[k]) * Math.min(2, Math.max(0.5, sSrc.s[k] / sGen.s[k])) + sSrc.m[k]);
      d.style.background = `rgb(${lab2rgb(lab.map((v, k) => v + (moved[k] - v) * strength))})`;
    });
  }
  $("#lutStrength").oninput = (e) => applyLut(+e.target.value);
  applyLut(0);
  whenVisible($("#lutStrength").closest(".reveal"), async () => {
    for (let s = 0; s <= 0.7001; s += 0.02) { $("#lutStrength").value = s; applyLut(s); await sleep(30); }
  });

  /* =========================================================== EDIT */
  function renderEdit() {
    const parts = [["source clip", "src", 8], ["s01", "extend", 4], ["s02", "talking", 6.4], ["s03", "talking", 7.5], ["s04", "broll", 4], ["s05", "talking", 8]];
    const tot = parts.reduce((a, p) => a + p[2], 0);
    let v = "", t = 0;
    for (const [n, k, d] of parts) { v += `<div class="tl-seg ${k}" style="left:${(t / tot) * 100}%;width:calc(${(d / tot) * 100}% - 3px)">${n}</div>`; t += d; }
    const genStart = (8 / tot) * 100;
    $("#editTracks").innerHTML = `
      <div class="tl-row"><div class="tl-label">video + LUT</div><div class="tl-track">${v}<div style="position:absolute;right:6px;top:8px;font:700 9px var(--sans);background:#0008;color:#fff;padding:2px 5px;border-radius:3px">AI-GENERATED</div></div></div>
      <div class="tl-row"><div class="tl-label">dialogue</div><div class="tl-track"><canvas id="edDlg" height="36" style="height:36px;border-radius:0;background:none"></canvas></div></div>
      <div class="tl-row"><div class="tl-label">music (ducked)</div><div class="tl-track"><svg class="wave" viewBox="0 0 1000 36" preserveAspectRatio="none" id="edMus"></svg></div></div>
      <div class="tl-row"><div class="tl-label">subtitles</div><div class="tl-track" id="edSub"></div></div>`;
    const dl = [[8.3, 11.6], [12.6, 14], [14.4, 19.4], [24.2, 27], [27.4, 31.6]];
    const c = $("#edDlg"), w = c.clientWidth || 600; c.width = w * 2; c.height = 72;
    const g = c.getContext("2d"); g.scale(2, 2);
    for (let x = 0; x < w; x += 3) {
      const tt = (x / w) * tot, on = dl.some(([a, b]) => tt >= a && tt <= b);
      g.fillStyle = on ? css("--accent") : css("--line");
      const h = on ? 4 + Math.abs(Math.sin(x * 0.29) * 12 + Math.sin(x * 0.05) * 6) : (tt < 8 ? 3 + Math.abs(Math.sin(x * 0.5) * 9) : 0.8);
      if (tt < 8) g.fillStyle = "#777";
      g.fillRect(x, 18 - h / 2, 2, h);
    }
    let path = "M0 36";
    for (let x = 0; x <= 1000; x += 4) {
      const tt = (x / 1000) * tot;
      let level = tt < 8 ? 0 : 14;
      if (dl.some(([a, b]) => tt >= a - 0.2 && tt <= b + 0.4)) level = 4;
      path += ` L${x} ${36 - level - (level ? Math.abs(Math.sin(x * 0.2)) * 3 : 0)}`;
    }
    $("#edMus").innerHTML = `<path d="${path} L1000 36 Z" fill="${css("--spark")}" opacity=".55"/><line x1="${genStart * 10}" y1="0" x2="${genStart * 10}" y2="36" stroke="${css("--muted")}" stroke-dasharray="3 3"/>`;
    $("#edSub").innerHTML = dl.map(([a, b], i) => `<div class="tl-seg sub" style="left:${(a / tot) * 100}%;width:calc(${((b - a) / tot) * 100}% - 2px)">${["Host", "Host", "Mina", "Jun", "Mina"][i]}</div>`).join("");
  }
  renderEdit();

  /* ======================================================= SEQUENCE */
  const seq = $("#seqCard");
  const playSeq = () => { seq.classList.remove("play"); void seq.offsetWidth; seq.classList.add("play"); };
  whenVisible(seq, playSeq);
  $("#seqReplay").onclick = playSeq;

  /* ====================================================== redraw */
  function redrawAll() {
    setTimeout(() => { drawTlWave(); renderVoices(); renderEdit(); showStage(stageIdx); }, 30);
  }
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(redrawAll, 200); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawAll);
})();
