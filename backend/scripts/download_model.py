"""Download MindGuard model weights from HuggingFace.

Used during Docker build. Expects HF_TOKEN env var or no-op if unset.
"""

import os
import shutil

TOKEN = os.environ.get("HF_TOKEN", "")
if not TOKEN:
    print("No HF_TOKEN set — skipping model download (base model will be used)")
    os.makedirs("./weights", exist_ok=True)
    for fname in ["tokenizer_config.json", "vocab.json", "merges.txt"]:
        open(f"./{fname}", "a").close()
    raise SystemExit(0)

import huggingface_hub as hf  # noqa: E402

REPO = "kopiyodiana/mindguard-mental-roberta"
WEIGHTS_FILE = "mindguard_best_weights.pt"

print(f"Downloading tokenizer from {REPO}...")
hf.snapshot_download(
    repo_id=REPO,
    allow_patterns="mindguard_tokenizer/*",
    token=TOKEN,
    local_dir="./download",
)

src = "./download/mindguard_tokenizer"
for fname in os.listdir(src):
    shutil.move(os.path.join(src, fname), "./")
    print(f"  moved {fname}")
shutil.rmtree(src)

print(f"Downloading {WEIGHTS_FILE}...")
hf.hf_hub_download(
    repo_id=REPO,
    filename=WEIGHTS_FILE,
    token=TOKEN,
    local_dir="./weights",
)
print("Done.")
