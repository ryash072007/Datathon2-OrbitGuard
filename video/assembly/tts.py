"""Local TTS for the demo voice-over (Chatterbox primary, Kokoro fallback).

python video/tts.py --script video/vo_segments.json --out video/out/vo/ \
    [--engine chatterbox|kokoro] [--voice ref.wav] [--exaggeration 0.4] [--cfg 0.5] [--seed 42]

Input JSON: [{"id": "s01", "text": "..."}]. Output: <id>.wav (24 kHz mono, -16 LUFS,
silence trimmed to 0.15 s each side) and durations.json (id -> seconds).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

SR = 24000
KEEP_S = 0.15
TARGET_LUFS = -16

# Extend freely: regex (word-bounded, case-sensitive) -> spoken form. Longest keys first.
PRONUNCIATIONS: dict[str, str] = {
    "s390x": "S three-ninety X",
    "LinuxONE": "Linux One",
    "IBM Z": "I.B.M. Z",
    "IBM": "I.B.M.",
    "ISS": "I.S.S.",
    "TLEs": "T.L.Es",
    "TLE": "T.L.E.",
    "CDMs": "C.D.Ms",
    "CDM": "C.D.M.",
    "TCA": "T.C.A.",
    "LLM": "L.L.M.",
    "km/s": "kilometres per second",
    "m/s": "metres per second",
    "km": "kilometres",
    "Pc": "probability of collision",
    "Granite": "Granite",
    "SGP4": "S.G.P. four",
    "ESA": "E.S.A.",
    "AI": "A.I.",
    "GPU": "G.P.U.",
    "CPU": "C.P.U.",
}


def preprocess(text: str, extra: dict[str, str] | None = None) -> str:
    table = {**PRONUNCIATIONS, **(extra or {})}
    for key in sorted(table, key=len, reverse=True):
        text = re.sub(rf"(?<![\w.]){re.escape(key)}(?![\w])", table[key], text)
    return re.sub(r"\.\.(?!\.)", ".", text)  # "C.P.U." + "." -> single full stop


def seed_everything(seed: int) -> None:
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def split_sentences(text: str) -> list[str]:
    # don't split after letter-dot abbreviations such as "I.B.M." or "A.I." (single capital + dot)
    return [t for t in re.split(r"(?<=[.!?])(?<!\b[A-Z]\.)\s+", text.strip()) if t]


def trim_silence(x: np.ndarray, sr: int = SR, thresh_db: float = -45.0, keep_s: float = KEEP_S) -> np.ndarray:
    keep = int(keep_s * sr)
    peak = np.max(np.abs(x)) + 1e-9
    idx = np.where(np.abs(x) > peak * 10 ** (thresh_db / 20))[0]
    if idx.size == 0:
        return x
    a, b = max(0, idx[0] - keep), min(len(x), idx[-1] + 1 + keep)
    out = x[a:b]
    # pad if the original had less than KEEP_S of margin
    pre, post = keep - (idx[0] - a), keep - (b - idx[-1] - 1)
    return np.concatenate([np.zeros(max(pre, 0), x.dtype), out, np.zeros(max(post, 0), x.dtype)])


def write_wav(path: Path, x: np.ndarray, sr: int) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def loudnorm(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-af", f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "1",
         "-c:a", "pcm_s16le", str(dst)],
        check=True)


def make_engine(args):
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: CUDA not available, running on CPU (slow)")
    if args.engine == "chatterbox":
        from chatterbox.tts import ChatterboxTTS
        model = ChatterboxTTS.from_pretrained(device=device)

        def synth(text: str) -> tuple[np.ndarray, int]:
            wav = model.generate(text, audio_prompt_path=args.voice,
                                 exaggeration=args.exaggeration, cfg_weight=args.cfg,
                                 temperature=args.temperature)
            return wav.squeeze().cpu().numpy(), model.sr
        return synth, device
    if args.engine == "kokoro":
        from kokoro import KPipeline
        pipe = KPipeline(lang_code="a")
        voice = args.voice or "af_heart"

        def synth(text: str) -> tuple[np.ndarray, int]:
            parts = [a.cpu().numpy() if hasattr(a, "cpu") else np.asarray(a)
                     for _, _, a in pipe(text, voice=voice)]
            return np.concatenate(parts), 24000
        return synth, device
    if args.engine == "orpheus":
        # Run with video/.venv-orpheus. Weights: unsloth mirror of canopylabs/orpheus-3b-0.1-ft (ungated).
        from snac import SNAC
        from transformers import AutoModelForCausalLM, AutoTokenizer
        name = "unsloth/orpheus-3b-0.1-ft"
        tok = AutoTokenizer.from_pretrained(name)
        lm = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch.bfloat16).to(device)
        snac = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").to(device).eval()
        voice = args.voice or "tara"

        def synth(text: str) -> tuple[np.ndarray, int]:
            ids = tok(f"{voice}: {text}", return_tensors="pt").input_ids
            ids = torch.cat([torch.tensor([[128259]]), ids, torch.tensor([[128009, 128260]])], 1).to(device)
            out = lm.generate(ids, attention_mask=torch.ones_like(ids), max_new_tokens=2000, do_sample=True,
                              temperature=args.temperature if args.temperature != 0.8 else 0.6,
                              top_p=0.8, repetition_penalty=1.1, eos_token_id=128258)[0, ids.shape[1]:]
            out = out.tolist()
            if 128257 in out:
                out = out[len(out) - out[::-1].index(128257):]
            out = [t for t in out if t >= 128266]
            out = out[: len(out) // 7 * 7]
            c = [t - 128266 for t in out]
            l0, l1, l2 = [], [], []
            for i in range(0, len(c), 7):
                f = c[i:i + 7]
                l0.append(f[0]); l1 += [f[1] - 4096, f[4] - 4 * 4096]
                l2 += [f[2] - 2 * 4096, f[3] - 3 * 4096, f[5] - 5 * 4096, f[6] - 6 * 4096]
            codes = [torch.tensor(l, device=device)[None] for l in (l0, l1, l2)]
            codes = [x.clamp(0, 4095) for x in codes]
            with torch.no_grad():
                a = snac.decode(codes)
            return a.squeeze().float().cpu().numpy(), 24000
        return synth, device
    raise SystemExit(f"unknown engine {args.engine}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", default="chatterbox", choices=["chatterbox", "kokoro", "orpheus"])
    ap.add_argument("--voice", default=None, help="reference wav (chatterbox) or voice name (kokoro)")
    ap.add_argument("--exaggeration", type=float, default=0.4)
    ap.add_argument("--cfg", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--pause-ms", type=int, default=240, help="gap between sentences")
    args = ap.parse_args()

    segs = json.loads(Path(args.script).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import torch
    synth, device = make_engine(args)
    print(f"engine={args.engine} device={device} torch={torch.__version__}"
          + (f" gpu={torch.cuda.get_device_name(0)}" if device == "cuda" else ""))

    durations: dict[str, float] = {}
    total_audio = total_gen = 0.0
    for seg in segs:
        text = preprocess(seg["text"])
        seed_everything(args.seed)
        t0 = time.time()
        pieces = []
        for sent in split_sentences(text):
            seed_everything(args.seed)
            y, sr = synth(sent)
            if sr != SR:
                import torchaudio
                y = torchaudio.functional.resample(torch.from_numpy(y), sr, SR).numpy()
            pieces.append(trim_silence(y.astype(np.float32), keep_s=0.02))
            pieces.append(np.zeros(int(args.pause_ms / 1000 * SR), np.float32))
        x = trim_silence(np.concatenate(pieces[:-1]))
        gen = time.time() - t0
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.wav"
            write_wav(raw, x, SR)
            loudnorm(raw, out / f"{seg['id']}.wav")
        with wave.open(str(out / f"{seg['id']}.wav")) as w:
            dur = w.getnframes() / w.getframerate()
        durations[seg["id"]] = round(dur, 3)
        total_audio += dur
        total_gen += gen
        print(f"{seg['id']}: {dur:.2f}s audio in {gen:.2f}s (RTF {gen / dur:.2f})  <- {text!r}")

    (out / "durations.json").write_text(json.dumps(durations, indent=2), encoding="utf-8")
    print(f"total {total_audio:.1f}s audio, {total_gen:.1f}s gen, RTF {total_gen / max(total_audio, 1e-9):.2f}")


if __name__ == "__main__":
    main()
