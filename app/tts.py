"""本機語音（Kokoro）：把英文念成聲音檔。只用 CPU、最多 2 個執行緒、一次只念一句，不跟 Ollama 搶 GPU。
單字念過就存起來（data/tts_cache），文章句子即時產生、不存。模型第一次要念時才載入。"""
import hashlib
import io
import os
import shutil
import sys
import threading
import wave
from pathlib import Path

from . import config

MODEL_DIR = config.ROOT / "data" / "kokoro"
MODEL = MODEL_DIR / "kokoro-v1.0.onnx"
VOICES = MODEL_DIR / "voices-v1.0.bin"
CACHE_DIR = config.DATA / "tts_cache"
THREADS = 2          # 最多用幾個 CPU 執行緒（你的 CPU 有 16 個）
MAX_CHARS = 600
DEFAULT_VOICE = "af_heart"

# 給設定頁顯示的英文聲音（Kokoro 裡比較好聽的）
VOICE_LABELS = {
    "af_heart": "Heart（美式女聲，最自然）",
    "af_bella": "Bella（美式女聲）",
    "af_nicole": "Nicole（美式女聲，輕柔）",
    "af_sarah": "Sarah（美式女聲）",
    "am_michael": "Michael（美式男聲）",
    "am_fenrir": "Fenrir（美式男聲）",
    "am_puck": "Puck（美式男聲）",
    "bf_emma": "Emma（英式女聲）",
    "bm_george": "George（英式男聲）",
    "bm_fable": "Fable（英式男聲）",
}

_lock = threading.Lock()      # 一次只念一句
_kokoro = None
_load_error = ""


def available() -> bool:
    return MODEL.exists() and VOICES.exists()


def _ascii_espeak_data() -> str:
    """espeak 讀不了有中文字的路徑（G:\\學英文\\...），複製一份到只有英文字母的資料夾。"""
    import espeakng_loader
    src = Path(espeakng_loader.get_data_path())
    if str(src).isascii():
        return str(src)
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VocabApp" / "espeak-ng-data"
    if not str(base).isascii():
        base = Path("C:/VocabApp/espeak-ng-data")
    if not (base / "phontab").exists():
        if base.exists():
            shutil.rmtree(base)
        shutil.copytree(src, base)
    return str(base)


def _lower_priority() -> None:
    """念的時候讓別的程式優先用 CPU（只影響本程式，不影響 Ollama）。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE  # 不設的話 64 位元的 handle 會被截斷，呼叫無效
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        BELOW_NORMAL = 0x4000
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)

        # 視窗縮小時 Windows 會把程式當背景、丟到慢的節能核心（E-core），念一句要多 2～3 倍時間。
        # 告訴 Windows 不要對這個程式省電節流（還是只用 2 個執行緒）。
        class _Throttle(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        st = _Throttle(1, 1, 0)  # EXECUTION_SPEED：由我們控制，關掉
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(st), ctypes.sizeof(st))  # 4 = ProcessPowerThrottling
    else:
        try:
            os.nice(5)
        except OSError:
            pass


def _load():
    global _kokoro, _load_error
    if _kokoro is not None:
        return _kokoro
    if _load_error:
        raise RuntimeError(_load_error)
    try:
        import onnxruntime as rt
        from kokoro_onnx import Kokoro
        from kokoro_onnx.config import EspeakConfig
        opts = rt.SessionOptions()
        opts.intra_op_num_threads = THREADS
        opts.inter_op_num_threads = 1
        sess = rt.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
        _kokoro = Kokoro.from_session(sess, str(VOICES), espeak_config=EspeakConfig(data_path=_ascii_espeak_data()))
        _lower_priority()
    except Exception as e:  # noqa: BLE001  載入失敗就記下來，前端會改用瀏覽器發音
        _load_error = f"本機語音無法載入：{e}"
        raise RuntimeError(_load_error) from e
    return _kokoro


def voices() -> list[dict]:
    return [{"id": k, "label": v} for k, v in VOICE_LABELS.items()]


def _wav(samples, rate: int) -> bytes:
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _text_key(text: str) -> str:
    """快取檔名用的代號：同一個字（不分大小寫）不管哪個聲音、哪個速度都一樣，刪單字時才找得到。"""
    return hashlib.sha1(" ".join(text.split()).lower().encode()).hexdigest()[:20]


def forget(text: str) -> int:
    """刪除這個字的所有發音快取（各種聲音、速度）。回傳刪了幾個檔。"""
    n = 0
    if not text or not CACHE_DIR.exists():
        return 0
    key = _text_key(text)
    for f in CACHE_DIR.glob(f"*/{key}_*.wav"):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


def clean_old_cache() -> None:
    """舊版快取檔名（沒有底線）對不回單字、刪單字時刪不到，啟動時清掉（之後要念時會重新產生）。"""
    if not CACHE_DIR.exists():
        return
    for f in CACHE_DIR.glob("*/*.wav"):
        if "_" not in f.stem:
            try:
                f.unlink()
            except OSError:
                pass


def synthesize(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0, cache: bool = False) -> bytes:
    """回傳 WAV。cache=True（單字）會存起來，下次直接讀檔。"""
    text = " ".join((text or "").split())[:MAX_CHARS]
    if not text:
        raise ValueError("沒有要念的文字")
    if voice not in VOICE_LABELS:
        voice = DEFAULT_VOICE
    speed = round(min(max(speed, 0.6), 1.5), 2)
    path = None
    if cache:
        path = CACHE_DIR / voice / f"{_text_key(text)}_{speed:.2f}.wav"
        if path.exists():
            return path.read_bytes()
    with _lock:
        k = _load()
        samples, rate = k.create(text, voice=voice, speed=speed, lang="en-us")
    data = _wav(samples, rate)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return data


def status() -> dict:
    return {"available": available() and not _load_error, "error": _load_error, "voices": voices(),
            "default": DEFAULT_VOICE}
