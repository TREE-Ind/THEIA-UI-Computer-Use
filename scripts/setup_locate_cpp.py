#!/usr/bin/env python3
"""Setup script for locate-anything.cpp (GGUF q8_0) backend for THEIA.

This replaces the heavy torch/transformers LocateAnything-3B with the
lightweight C++ ggml port.

Run from the plugin directory:
  python scripts/setup_locate_cpp.py

It will:
- Create directories under the locate-worker
- Download the q8_0 model (if not present)
- Print build instructions for the CLI (requires CMake + C++ compiler)
- Suggest env vars for Hermes

After setup:
  set COMPUTER_USE_LOCATE_BACKEND=cpp
  (or leave auto; it will prefer cpp if binary + model present)

Then restart Hermes or /reset the session.
"""

from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".hermes"))) / "hermes" / "theia-ui-computer-use" / "locate-worker"
if os.name != "nt":
    WORKER_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "theia-ui-computer-use" / "locate-worker"

MODELS_DIR = WORKER_DIR / "models"
BIN_DIR = WORKER_DIR / "bin"
CPP_SRC = WORKER_DIR / "cpp-src"

MODEL_NAME = "locate-anything-q8_0.gguf"
MODEL_URL = "https://huggingface.co/mudler/locate-anything.cpp-gguf/resolve/main/" + MODEL_NAME

def main():
    print("=== THEIA locate-anything.cpp setup (q8_0 GGUF) ===")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODELS_DIR / MODEL_NAME
    if not model_path.exists():
        print(f"Downloading model (~6.3GB) to {model_path} ...")
        print("You can resume with curl -C - ...")
        try:
            subprocess.check_call([
                "curl", "-L", "-C", "-", "-o", str(model_path), MODEL_URL
            ], timeout=600)
            print("Download complete or resumed.")
        except Exception as e:
            print(f"Download failed or partial: {e}")
            print(f"Manually download: {MODEL_URL} to {model_path}")
    else:
        print(f"Model already present: {model_path}")

    print("\n=== Build the CLI ===")
    print("1. Ensure you have the cpp-src (git clone --recursive done in worker dir)")
    print("2. Install build tools: CMake, C++ compiler (Visual Studio Build Tools or WinLibs mingw via winget)")
    print("3. Run in the cpp-src dir:")
    print("   cmake -B build -DLA_BUILD_CLI=ON -DLA_BUILD_TESTS=OFF -DCMAKE_BUILD_TYPE=Release")
    print("   cmake --build build --config Release -j")
    print("4. Copy the binary:")
    print(f"   copy build\\bin\\locate-anything-cli.exe {BIN_DIR}\\")
    print("\nFor CUDA:")
    print("   add -DLA_GGML_CUDA=ON to cmake (requires CUDA toolkit)")

    print("\n=== Environment ===")
    print("Set these (or let auto detect):")
    print(f"  COMPUTER_USE_LOCATE_BACKEND=cpp")
    print(f"  COMPUTER_USE_LOCATE_CPP_CLI={BIN_DIR / 'locate-anything-cli.exe'}")
    print(f"  COMPUTER_USE_LOCATE_MODEL_PATH={model_path}")

    print("\nThen:")
    print("  hermes tools enable windows_computer_use")
    print("  (restart Hermes or new session)")

    cli = BIN_DIR / "locate-anything-cli.exe"
    if cli.exists():
        print(f"\nCLI found at {cli}")
    else:
        print(f"\nCLI not yet at {cli} -- build it!")

if __name__ == "__main__":
    main()
