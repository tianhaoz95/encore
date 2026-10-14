#!/usr/bin/env bash
# DGX Spark (GB10, aarch64 + CUDA): ComfyUI + encore GPU worker + model repos.
# Review before running. Downloads ~150 GB of weights into $OPT.
# If a pip wheel is unavailable for aarch64/CUDA, run the same steps inside
# NVIDIA's PyTorch container (nvcr.io/nvidia/pytorch:<recent>-py3) instead.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd)
: "${OPT:=$HOME/encore-opt}"
: "${TORCH_INDEX:=https://download.pytorch.org/whl/cu130}"
mkdir -p "$OPT"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get install -y ffmpeg git git-lfs
hf() { uvx --from "huggingface_hub[cli]" hf "$@"; }

# --- encore worker ---------------------------------------------------------
uv venv --python 3.12 .venv
uv pip install -e ".[cuda]"
uv pip install --index-url "$TORCH_INDEX" torch torchaudio
uv pip install chatterbox-tts f5-tts
[ -f worker.yaml ] || sed "s#/opt/#$OPT/#g" worker.example.yaml > worker.yaml

# --- ComfyUI (keyframes + Wan 2.2 b-roll) -------------------------------------
if [ ! -d "$OPT/ComfyUI" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI "$OPT/ComfyUI"
  (cd "$OPT/ComfyUI" && uv venv --python 3.12 && uv pip install --index-url "$TORCH_INDEX" torch torchvision torchaudio \
     && uv pip install -r requirements.txt)
fi
M="$OPT/ComfyUI/models"
get() { hf download "$1" "$2" --local-dir "$OPT/_dl" && mkdir -p "$M/$3" && mv "$OPT/_dl/$2" "$M/$3/"; }
get Comfy-Org/flux1-kontext-dev_ComfyUI split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors diffusion_models
get comfyanonymous/flux_text_encoders clip_l.safetensors text_encoders
get comfyanonymous/flux_text_encoders t5xxl_fp8_e4m3fn_scaled.safetensors text_encoders
get Comfy-Org/Lumina_Image_2.0_Repackaged split_files/vae/ae.safetensors vae
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors diffusion_models
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/vae/wan2.2_vae.safetensors vae
get Comfy-Org/Wan_2.1_ComfyUI_repackaged split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors text_encoders
# only for talking_backend: comfyui (Wan 2.2 S2V)
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors diffusion_models
get Comfy-Org/Wan_2.2_ComfyUI_Repackaged split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors audio_encoders
get Comfy-Org/Wan_2.1_ComfyUI_repackaged split_files/vae/wan_2.1_vae.safetensors vae

# --- InfiniteTalk (talking heads, multi-person lip sync) ----------------------
if [ ! -d "$OPT/InfiniteTalk" ]; then
  git clone https://github.com/MeiGen-AI/InfiniteTalk "$OPT/InfiniteTalk"
  (cd "$OPT/InfiniteTalk" && uv venv --python 3.10 && uv pip install --index-url "$TORCH_INDEX" torch torchvision torchaudio \
     && uv pip install -r requirements.txt)
fi
W="$OPT/InfiniteTalk/weights"
hf download Wan-AI/Wan2.1-I2V-14B-480P --local-dir "$W/Wan2.1-I2V-14B-480P"
hf download TencentGameMate/chinese-wav2vec2-base --local-dir "$W/chinese-wav2vec2-base"
hf download MeiGen-AI/InfiniteTalk --local-dir "$W/InfiniteTalk"

# --- Wan 2.2 reference repo (worker `wan_i2v` engine, alternative to ComfyUI) --
if [ ! -d "$OPT/Wan2.2" ]; then
  git clone https://github.com/Wan-Video/Wan2.2 "$OPT/Wan2.2"
  (cd "$OPT/Wan2.2" && uv venv --python 3.12 && uv pip install --index-url "$TORCH_INDEX" torch torchvision \
     && uv pip install -r requirements.txt)
  hf download Wan-AI/Wan2.2-TI2V-5B --local-dir "$OPT/Wan2.2/Wan2.2-TI2V-5B"
fi
echo "Done. Start with: scripts/start_spark.sh"
