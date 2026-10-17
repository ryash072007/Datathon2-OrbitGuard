"""Download and extract the ESA Collision Avoidance Challenge dataset into data/raw/cac/. Idempotent."""
from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

URL = "https://zenodo.org/records/4463683/files/Collision%20Avoidance%20Challenge%20-%20Dataset.zip?download=1"
ZIP_SIZE = 221128642
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ZIP_PATH = RAW / "cac_dataset.zip"
OUT = RAW / "cac"
WANTED_PREFIX = "kelvins_competition_data/"
EXTRA = "raw_data/raw_data_2015-2019.txt"


def download() -> None:
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size == ZIP_SIZE:
        print(f"[skip] {ZIP_PATH.name} already present")
        return
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"[download] {URL}")
    tmp = ZIP_PATH.with_suffix(".part")
    with urllib.request.urlopen(URL) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if tmp.stat().st_size != ZIP_SIZE:
        raise RuntimeError(f"Unexpected download size {tmp.stat().st_size}, expected {ZIP_SIZE}")
    tmp.replace(ZIP_PATH)


def extract() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if info.filename.startswith(WANTED_PREFIX) or info.filename == EXTRA:
                dest = OUT / Path(info.filename).name
                if dest.exists() and dest.stat().st_size == info.file_size:
                    print(f"[skip] {dest.name}")
                    continue
                with z.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"[extract] {dest.name}")
    train_csv = OUT / "train_data.csv"
    train_zip = OUT / "train_data.zip"
    if train_csv.exists():
        print("[skip] train_data.csv")
    elif train_zip.exists():
        with zipfile.ZipFile(train_zip) as z:
            z.extract("train_data.csv", OUT)
        print("[extract] train_data.csv")
    else:
        raise FileNotFoundError("train_data.zip not found after extraction")


def main() -> None:
    download()
    extract()
    print("Data ready in", OUT)


if __name__ == "__main__":
    main()
