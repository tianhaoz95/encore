# Encore

Give it a movie clip and a sentence, and it shoots the follow-up scene. For example: *"a K-pop concert clip → a backstage podcast with the members"*. Every model runs on your own hardware: a **Mac Studio** and an **NVIDIA DGX Spark**. No cloud APIs are used.

```
 clip.mp4 + "make a podcast with the members"
   │
   ├─ 1 analyze    scenes · vocal separation (Demucs) · ASR (Whisper) · diarization
   │               face detection + identity clustering (ArcFace) · VLM clip description
   ├─ 2 bible      characters = face clusters → reference crops, voice sample, appearance
   ├─ 3 script     local LLM → JSON shot list (talking / broll / extend shots, dialogue)
   ├─ 4 voices     voice-cloned TTS per line → dialogue mix + per-speaker tracks
   ├─ 5 keyframes  master frame per setting (ref-conditioned image edit) → per-shot edits
   │               ArcFace identity QC with automatic retries
   ├─ 6 shoot      talking: audio-driven lip sync (InfiniteTalk / MultiTalk)
   │               b-roll / continuation: image-to-video (Wan 2.2), chained past 5 s
   └─ 7 edit       conform · colour-match to source (3D LUT) · grain · loudness
                   source clip + new footage · subtitles · "AI-GENERATED" watermark
```

**Visual walkthrough** of the design, implementation and testing: `reports/project-walkthrough/script/serve.sh`, which serves `reports/project-walkthrough/site` at http://127.0.0.1:8765.

Each stage writes its outputs into the project directory, so you can stop, review, edit and re-run at any point. Two human checkpoints matter most:

1. **Cast and script.** Rename the detected people, drop extras, swap in a better voice sample, and edit the lines or ask the LLM to revise them.
2. **Keyframes.** Regenerate bad stills before spending GPU-minutes on video.

## Which machine does what

| Stage | Machine | Default backend |
|---|---|---|
| LLM (script) | Mac Studio | Ollama or `mlx_lm.server`: Qwen3 32B / 235B-A22B, gpt-oss-120b |
| VLM (understanding) | Mac Studio | Qwen2.5-VL / Qwen3-VL via Ollama |
| ASR, Demucs, faces, edit, UI | Mac Studio | mlx-whisper, htdemucs, InsightFace, ffmpeg |
| TTS (voice cloning) | DGX Spark | Chatterbox Multilingual (incl. Korean), F5-TTS, CosyVoice via worker |
| Keyframes | DGX Spark | ComfyUI + FLUX.1 Kontext dev |
| Talking shots | DGX Spark | InfiniteTalk / MultiTalk via worker (or Wan 2.2 S2V in ComfyUI) |
| B-roll / continuation | DGX Spark | ComfyUI + Wan 2.2 TI2V-5B (swap in I2V-14B, HunyuanVideo-I2V, LTX…) |

The Mac drives everything over the LAN. The Spark runs two services: **ComfyUI** (`:8188`) and the **encore worker** (`:8100`), a small job server that wraps model repos which have no ComfyUI nodes. Any stage can be moved to either machine by editing `config.yaml`.

## Quick start: dry run (no GPU, no model servers)

```bash
brew install ffmpeg uv
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
.venv/bin/python tests/make_fixture.py /tmp/clip.mp4          # or use your own clip
.venv/bin/encore new /tmp/clip.mp4 "a podcast where they talk about the concert" \
    --name demo --names "Mina" -c configs/dryrun.yaml
.venv/bin/encore run demo -c configs/dryrun.yaml
open projects/demo/output/final.mp4
```

`configs/dryrun.yaml` replaces every model with a fallback: a template script, macOS `say` voices, composited stills and Ken Burns moves. The result is a timed animatic with the real cut structure and subtitles, which is useful for checking the pipeline end to end.

## Full setup

**DGX Spark**

```bash
scripts/setup_spark.sh     # ComfyUI + weights, InfiniteTalk, Wan2.2, Chatterbox/F5, worker.yaml
scripts/start_spark.sh     # ComfyUI :8188 + worker :8100 (listening on the LAN)
```

**Mac Studio**

```bash
scripts/setup_mac.sh       # venv with mlx-whisper/demucs/insightface, Ollama models, config.yaml
# edit config.yaml → replace spark.local with the Spark's hostname/IP
.venv/bin/encore doctor  # checks every backend is installed / reachable
scripts/start_mac.sh       # UI at http://127.0.0.1:8700
```

Read both setup scripts before running them. Together they download roughly 150 GB of weights.

## Usage

### Web UI (`encore serve`)

1. Upload a clip and a prompt. The pipeline runs analyze → script automatically.
2. Review the cast and script, then click **Voices + keyframes**.
3. Regenerate any bad keyframe, then click **Shoot + edit**.

Each shot has buttons to re-voice, regenerate the keyframe, or re-shoot just that shot. Clicking a stage chip re-runs from that stage.

### CLI

```bash
encore new clip.mp4 "an interview with the group about their world tour" \
    --seconds 90 --language ko --names "Jisoo,Jennie,Rosé,Lisa"
encore run <proj> --until script            # stop for review
encore status <proj>
encore rename <proj> char_2 "Rosé"
encore revise <proj> "make s04 funnier and add a shot of the fans outside"
encore run <proj> --from voices --until keyframes
encore run <proj> --stages keyframes --shots s03,s05   # redo two stills
encore run <proj> --from shoot                          # final film
encore lora-dataset <proj> char_0                       # optional identity-LoRA training set
```

Use `-s key=value` to override any config value for one run, for example `-s tts.backend=say -s video.talking_backend=kenburns`.

## Swapping models

- **ComfyUI stages.** Build the graph in ComfyUI, export it with *Export (API)*, and put placeholders in string inputs: `{{PROMPT}} {{NEGATIVE}} {{IMAGE}} {{AUDIO}} {{WIDTH}} {{HEIGHT}} {{FRAMES}} {{FPS}} {{SEED}} {{STEPS}} {{LORA}} {{PREFIX}}`. Then point `image.workflow` or `video.workflows.*` at the file. File placeholders are uploaded automatically. A string that is exactly one numeric placeholder becomes a number.
- **Worker engines.** Edit `worker.yaml`. The `command` type wraps any CLI with an argv template, such as `{image} {prompt} {frames} {out} {text_file} {ref_audio}`. Built-in types are `chatterbox`, `f5`, `infinitetalk`, `say` and `kenburns`.
- **LLM / VLM.** Any OpenAI-compatible local server works: Ollama, `mlx_lm.server`, vLLM, llama.cpp, LM Studio.

## Project layout

```
projects/<name>/
  project.json          prompt, options, stage status
  source/clip.mp4
  analysis/             analysis.json, scene frames, face crops + embeddings, stems
  bible.json            characters (refs, voice, description), clip summary/style
  cast/<char>/          ref_*.jpg, voice_ref.wav, embedding.npy, lora_dataset/
  script.json           shot list
  audio/                <shot>.wav, <shot>.<char>.wav, <shot>.json timings, lines/ cache
  keyframes/            master_<setting>.png, <shot>.png
  shots/                <shot>.mp4
  output/               final.mp4, final.srt, parts/
  log.txt
```

## Code map

`encore/core`: config, schemas, project store, ffmpeg helpers, LLM client, colour LUTs ·
`encore/analyze`: scenes, audio (Demucs/Whisper/pyannote), faces, VLM ·
`encore/write`: script writer ·
`encore/backends`: TTS, image, video, ComfyUI client, worker client ·
`encore/stages`: the seven stages ·
`encore/pipeline.py` · `encore/cli.py` · `encore/server` (FastAPI + single-page UI) ·
`encore/workers` (GPU worker + engines) · `workflows/` (ComfyUI templates) · `tests/`

## Status / what's verified

- **Verified on a 16 GB M2 with ffmpeg only:**
  - the full pipeline with fallbacks (`configs/dryrun.yaml`), including OpenCV face clustering and mlx-whisper ASR → voice-reference extraction;
  - the web API, including script edits and single-shot regeneration;
  - the worker HTTP protocol, with test engines;
  - `pytest` (11 tests).
- **Written against the published interfaces but not executed here** (no CUDA, and no heavy weights on this machine):
  - Chatterbox / F5 engines;
  - the InfiniteTalk engine, whose CLI flags are configurable in `worker.yaml`;
  - the ComfyUI workflow JSONs, whose node names follow current ComfyUI core;
  - Demucs / pyannote / InsightFace paths;
  - real LLM / VLM structured output.

  Expect to tune these on the first run on the Spark and the Studio. `encore doctor` and the per-stage logs (`projects/<name>/log.txt`) are where to look.
- **Quality levers:**
  - per-character identity LoRA (`lora-dataset` → train → set `lora` on the character and add a LoRA loader to the keyframe workflow);
  - `image.identity_threshold`;
  - InfiniteTalk 720p.

## Responsible use

This tool clones real people's faces and voices. Keep the output private unless you have the rights to share it. The `AI-GENERATED` watermark and the MP4 metadata note are on by default. Leave them on for anything that leaves your machine. The script prompt tells the LLM to stay respectful and avoid defamatory or explicit content.
