"""Build the labelled evaluation set from pinned public sources + the committed local slice.

Third-party text is downloaded at build time, never committed: HC3 is CC-BY-SA-4.0,
and the Liang et al. essays are published without a licence. Every download is
pinned to a commit and verified by SHA-256, so the set is identical on every machine
and in CI.

Groups (label 0 = human, 1 = AI-written or AI-assisted):

  web_qa            0  HC3 open_qa human answers (WikiQA-style)
  chatgpt_qa        1  HC3 ChatGPT answers to the same questions
  native_essay      0  Hewlett 8th-grade essays, US students (Liang et al.)
  non_native_essay  0  TOEFL essays (Liang et al.) — the bias check: FP rate here vs native
  gpt4_polished     1  those TOEFL essays polished by GPT-4 — "AI-assisted", not AI-written
  local_llm         1  Gemma / Qwen interview answers  (evals/data/local_llm.jsonl, committed)
  paraphrased       1  the same, rewritten by Qwen to sound spoken

Usage:
    python -m evals.build_dataset          # → evals/data/eval_set.jsonl (gitignored)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
CACHE = DATA / "cache"
OUT = DATA / "eval_set.jsonl"
LOCAL = DATA / "local_llm.jsonl"

SEED = 20261126
N_QA_PAIRS = 150          # questions sampled from HC3 open_qa (one human + one ChatGPT answer)
MIN_WORDS = 40            # both answers of a pair must have ≥ this many words (length confound)

_HC3 = "https://huggingface.co/datasets/Hello-SimpleAI/HC3/resolve/4d0ff18143b5a7e1b1e79beb540c04549d1e59d3"
_LIANG = (
    "https://raw.githubusercontent.com/Weixin-Liang/ChatGPT-Detector-Bias/"
    "1d05ed8242d4694a0ed7b73a79c52be8864470f9/Data_and_Results/Human_Data"
)

SOURCES: dict[str, tuple[str, str]] = {
    "open_qa.jsonl": (
        f"{_HC3}/open_qa.jsonl",
        "4d968e1e1473cbdf5978024872768f0c6f27dacf681f35166dc191733dccd664",
    ),
    "toefl_real.json": (
        f"{_LIANG}/TOEFL_real_91/data.json",
        "d5e2bf0bd4831262d60aa936b2ac8e532bd3859067411288b6c22ed16867666b",
    ),
    "toefl_gpt4polished.json": (
        f"{_LIANG}/TOEFL_gpt4polished_91/data.json",
        "8dcbce862bc54259666c77d68ed43927af9d4cfd350c57ff1b250c21860256c6",
    ),
    "hewlett_real.json": (
        f"{_LIANG}/HewlettStudentEssay_real_88/data.json",
        "6145e4e8bf36b780624626b31a783d7ca97696e1e14ae6d13c083b79da2f042d",
    ),
}


def _fetch(name: str) -> Path:
    url, sha = SOURCES[name]
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "trustsignal-evals"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - pinned https URL
            path.write_bytes(resp.read())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha:
        path.unlink()
        raise RuntimeError(f"{name}: checksum mismatch (got {digest}); source changed?")
    return path


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\n", " ")).strip()


def _words(text: str) -> int:
    return len(text.split())


def _row(rid: str, text: str, label: int, group: str, source: str) -> dict:
    return {"id": rid, "text": _clean(text), "label": label, "group": group, "source": source}


def build() -> list[dict]:
    rng = random.Random(SEED)  # noqa: S311 - reproducible sampling, not crypto
    rows: list[dict] = []

    qa = [json.loads(line) for line in _fetch("open_qa.jsonl").open(encoding="utf-8")]
    pairs = [
        (i, r["human_answers"][0], r["chatgpt_answers"][0])
        for i, r in enumerate(qa)
        if r.get("human_answers") and r.get("chatgpt_answers")
        and _words(r["human_answers"][0]) >= MIN_WORDS
        and _words(r["chatgpt_answers"][0]) >= MIN_WORDS
    ]
    for i, human, gpt in rng.sample(pairs, min(N_QA_PAIRS, len(pairs))):
        rows.append(_row(f"qa-h-{i}", human, 0, "web_qa", "HC3 open_qa (human)"))
        rows.append(_row(f"qa-c-{i}", gpt, 1, "chatgpt_qa", "HC3 open_qa (ChatGPT)"))

    essays = [
        ("toefl_real.json", 0, "non_native_essay", "Liang et al. TOEFL_real_91"),
        ("toefl_gpt4polished.json", 1, "gpt4_polished", "Liang et al. TOEFL_gpt4polished_91"),
        ("hewlett_real.json", 0, "native_essay", "Liang et al. HewlettStudentEssay_real_88"),
    ]
    for name, label, group, source in essays:
        for j, doc in enumerate(json.loads(_fetch(name).read_text(encoding="utf-8"))):
            rows.append(_row(f"{group}-{j}", doc["document"], label, group, source))

    if LOCAL.exists():
        for line in LOCAL.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                rows.append(_row(r["id"], r["text"], r["label"], r["group"], r["source"]))
    return rows


def main() -> None:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["group"]] = counts.get(r["group"], 0) + 1
    print(f"wrote {len(rows)} rows to {OUT}: {counts}")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
