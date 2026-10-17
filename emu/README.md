# Local LinuxONE emulator (`emu/`)

An s390x (big-endian) Ubuntu 24.04 container run under QEMU, with the repo mounted at `/work`.
It catches s390x install and endianness problems before we touch the real LinuxONE VM.

## Prerequisites
- Docker Desktop with QEMU/binfmt emulation (default on Windows/macOS).
- On Windows, run the script from Git Bash.

## Quickstart
```
bash emu/l1.sh check   # verify s390x emulation works
bash emu/l1.sh build   # build image (10-25 min first time)
bash emu/l1.sh info    # arch, byteorder, nproc, library versions
bash emu/l1.sh shell   # interactive shell in /work
bash emu/l1.sh run python -c "import sgp4"
bash emu/l1.sh test    # pytest tests -q
```
`requirements.txt` (if present) is pip-installed on each run; `.env` is passed in if present.

## Limitations
- QEMU is roughly 5-20x slower than native: timings are indicative only; real benchmarks come from the VM.
- apt package versions differ from the official VM image (see header of `emu/Dockerfile`).
- No Telum/NNPA accelerator.

## Exact-mirror option
On the real VM:
```
docker save registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest | gzip > l1cc-image.tar.gz
```
Copy it to your PC, then:
```
docker load -i l1cc-image.tar.gz
IMAGE=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest bash emu/l1.sh shell
```
