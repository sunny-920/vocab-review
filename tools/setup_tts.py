"""下載本機自然語音模型 Kokoro（約 340MB），放到 data\\kokoro。已經有了就略過。"""
import sys
import urllib.request
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "kokoro"
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
FILES = {
    "kokoro-v1.0.onnx": BASE + "model-files-v1.1/kokoro-v1.0.onnx",
    "voices-v1.0.bin": BASE + "model-files-v1.0/voices-v1.0.bin",
}


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        dest = DIR / name
        if dest.exists():
            print(f"    已經有 {name}，略過")
            continue
        print(f"    下載 {name}…")
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
