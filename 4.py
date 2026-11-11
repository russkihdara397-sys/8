"""
Aurora Studio — десктопное приложение для работы со звуком (всё в одном файле).

pip install PyQt6 pyqtgraph numpy sounddevice soundfile
Для радио/всех форматов положите bass.dll (libbass.so / libbass.dylib) рядом с файлом.
Запуск: python aurora_studio.py
"""
from __future__ import annotations

import ctypes as C
import json
import sys
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
import sounddevice as sd
import soundfile as sf
from PyQt6.QtCore import (
    QObject, QRegularExpression, QThread, QTimer, Qt, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QKeySequence, QLinearGradient, QPainter, QPalette,
    QPen, QRegularExpressionValidator, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

# ===========================================================================
#                                   CONFIG
# ===========================================================================
APP_DIR = Path.home() / ".aurora_studio"
SETTINGS_FILE = APP_DIR / "settings.json"
STATIONS_FILE = APP_DIR / "stations.json"

SUPPORTED_AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus"}
SUPPORTED_FORMATS_LABEL = "WAV · MP3 · FLAC · OGG"

DEFAULT_SAVE_DIR = Path.home() / "Music"
if not DEFAULT_SAVE_DIR.exists():
    DEFAULT_SAVE_DIR = Path.home()

DEFAULTS: dict = {
    "engine": "sounddevice",
    "output_device": None,
    "input_device": None,
    "samplerate": 44100,
    "blocksize": 1024,
    "volume": 0.8,
    "pan": 0.0,
    "last_dir": str(Path.home()),
    "last_record_path": str(DEFAULT_SAVE_DIR / "aurora_record.wav"),
    "fft_size": 2048,
    "spectrum_mode": "bars",
    "smoothing": 0.6,
    "peak_hold": True,
    "tap_size": 32768,
    "record_limit_min": 60,
    "monitoring": True,
}

URL_PLACEHOLDER = "Вставьте прямую ссылку на поток (например, .mp3, .aac, .ogg ICY)"
URL_HINT = "Принимаются прямые ссылки на аудиопоток, а не страницы сайтов."
_URL_RE = QRegularExpression(r"^https?://[^\s]+$")


def is_valid_stream_url(text: str) -> bool:
    t = text.strip()
    if not t or not _URL_RE.match(t).hasMatch():
        return False
    u = QUrl(t)
    return u.isValid() and u.scheme() in ("http", "https") and bool(u.host())


class Settings:
    def __init__(self) -> None:
        self._data = dict(DEFAULTS)
        self.load()

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def load(self) -> None:
        try:
            if SETTINGS_FILE.exists():
                raw = json.loads(SETTINGS_FILE.read_text("utf-8"))
                if isinstance(raw, dict):
                    self._data.update(raw)
        except Exception:
            pass

    def save(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception:
            pass


# ===========================================================================
#                                  AUDIO TAP
# ===========================================================================
class AudioTap:
    def __init__(self, size: int = 1 << 15) -> None:
        self._size = int(size)
        self._buf = np.zeros(self._size, dtype=np.float32)
        self._pos = 0
        self._lock = threading.Lock()

    def write(self, samples) -> None:
        x = np.asarray(samples, dtype=np.float32)
        if x.ndim > 1:
            x = x.mean(axis=1)
        n = x.size
        if n == 0:
            return
        if n >= self._size:
            x = x[-self._size:]
            n = self._size
        with self._lock:
            end = self._pos + n
            if end <= self._size:
                self._buf[self._pos:end] = x
            else:
                k = self._size - self._pos
                self._buf[self._pos:] = x[:k]
                self._buf[: end - self._size] = x[k:]
            self._pos = end % self._size

    def read(self, n: int = 4096) -> np.ndarray:
        with self._lock:
            n = min(int(n), self._size)
            if n <= 0:
                return np.zeros(0, dtype=np.float32)
            idx = (self._pos - n + np.arange(n)) % self._size
            return self._buf[idx].copy()

    def clear(self) -> None:
        with self._lock:
            self._buf.fill(0.0)
            self._pos = 0


# ===========================================================================
#                               ENGINE BASE
# ===========================================================================
class AudioEngineError(Exception):
    pass


class AudioEngine(QObject):
    error = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    metadata_changed = pyqtSignal(str, str)
    record_level = pyqtSignal(float)
    recording_changed = pyqtSignal(bool)

    name = "base"
    supports_stream = False

    def __init__(self, settings: Settings, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.tap = AudioTap(int(settings.get("tap_size", 32768)))
        self._state = "stopped"
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(120)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _poll(self) -> None: ...

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    @property
    def state(self) -> str:
        return self._state

    def list_output_devices(self) -> list[tuple[int, str]]: return []
    def list_input_devices(self) -> list[tuple[int, str]]: return []

    def play_file(self, path: str) -> None:
        raise AudioEngineError("Воспроизведение файлов недоступно для этого движка.")

    def play_url(self, url: str, title: str = "") -> None:
        raise AudioEngineError(
            "Потоковое радио поддерживается только движком BASS.\n"
            "Переключите движок в Настройках."
        )

    def pause(self) -> None: raise AudioEngineError("Пауза недоступна.")
    def resume(self) -> None: raise AudioEngineError("Возобновление недоступно.")
    def stop(self) -> None: raise AudioEngineError("Остановка недоступна.")
    def seek(self, seconds: float) -> None: raise AudioEngineError("Перемотка недоступна.")
    def position(self) -> float: return 0.0
    def duration(self) -> float: return 0.0
    def set_volume(self, value: float) -> None: ...
    def set_pan(self, value: float) -> None: ...

    def start_record(self, path: str, device: Optional[int] = None) -> None:
        raise AudioEngineError("Запись недоступна для этого движка.")
    def stop_record(self) -> None: ...
    def start_monitoring(self, device: Optional[int] = None) -> None:
        raise AudioEngineError("Мониторинг входа недоступен для этого движка.")
    def stop_monitoring(self) -> None: ...

    @property
    def is_recording(self) -> bool: return False
    @property
    def is_monitoring(self) -> bool: return False
    @property
    def record_level_value(self) -> float: return 0.0

    def start_generator(self, fill: Callable[[int], np.ndarray],
                        device: Optional[int] = None) -> None:
        raise AudioEngineError("Вывод генератора недоступен для этого движка.")
    def stop_generator(self) -> None: ...

    def shutdown(self) -> None:
        self._poll_timer.stop()


# ===========================================================================
#                             SOUNDDEVICE ENGINE
# ===========================================================================
class SoundDeviceEngine(AudioEngine):
    name = "sounddevice"

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(settings, parent)
        self._lock = threading.Lock()
        self._out: Optional[sd.OutputStream] = None
        self._gen: Optional[sd.OutputStream] = None
        self._in_stream: Optional[sd.InputStream] = None
        self._rec_file: Optional[sf.SoundFile] = None
        self._monitoring = False
        self._data: Optional[np.ndarray] = None
        self._pos = 0
        self._sr = int(settings.get("samplerate", 44100))
        self._vol = float(settings.get("volume", 0.8))
        self._pan = float(settings.get("pan", 0.0))
        self._eof = False
        self._level = 0.0
        self._device = settings.get("output_device")

    def list_output_devices(self):
        out = []
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_output_channels", 0) > 0:
                    out.append((i, dev["name"]))
        except Exception:
            pass
        return out

    def list_input_devices(self):
        out = []
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0:
                    out.append((i, dev["name"]))
        except Exception:
            pass
        return out

    def _open_output(self, samplerate: int) -> None:
        self._close_output()
        try:
            self._out = sd.OutputStream(
                device=self._device, samplerate=samplerate, channels=2, dtype="float32",
                blocksize=int(self.settings.get("blocksize", 1024)),
                callback=self._audio_cb,
            )
            self._out.start()
        except Exception as exc:
            self._out = None
            raise AudioEngineError(
                f"Не удалось открыть устройство вывода: {exc}\n"
                "Проверьте выбранное устройство в Настройках."
            ) from exc

    def _close_output(self) -> None:
        if self._out is not None:
            try:
                self._out.stop(); self._out.close()
            except Exception:
                pass
            self._out = None

    def _audio_cb(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            if self._data is None:
                outdata.fill(0.0); return
            remaining = len(self._data) - self._pos
            n = min(frames, remaining)
            chunk = self._data[self._pos:self._pos + n]
            self._pos += n
            if n < frames:
                outdata[n:] = 0.0
                self._eof = True
            out = chunk.copy()
            lg = self._vol * min(1.0, 1.0 - self._pan)
            rg = self._vol * min(1.0, 1.0 + self._pan)
            out[:, 0] *= lg
            out[:, 1] *= rg
            outdata[:n] = out
        self.tap.write(chunk)

    def play_file(self, path: str) -> None:
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:
            raise AudioEngineError(
                f"Не удалось открыть файл «{Path(path).name}».\n"
                f"Проверьте, что это аудиофайл ({SUPPORTED_FORMATS_LABEL}).\n"
                f"Детали: {exc}"
            ) from exc
        if data.shape[0] == 0:
            raise AudioEngineError("Файл пуст.")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        self.stop()
        with self._lock:
            self._data = np.ascontiguousarray(data)
            self._sr = int(sr); self._pos = 0; self._eof = False
        self._open_output(self._sr)
        self._set_state("playing")

    def pause(self) -> None:
        if self._out is not None and self._state == "playing":
            self._out.stop(); self._set_state("paused")

    def resume(self) -> None:
        if self._out is not None and self._state == "paused":
            self._out.start(); self._set_state("playing")

    def stop(self) -> None:
        self._close_output()
        with self._lock:
            self._data = None; self._pos = 0
        self._set_state("stopped")

    def seek(self, seconds: float) -> None:
        with self._lock:
            if self._data is None:
                return
            self._pos = int(max(0, min(seconds, self.duration())) * self._sr)
            self._eof = False

    def position(self) -> float:
        with self._lock:
            return self._pos / self._sr if self._sr else 0.0

    def duration(self) -> float:
        with self._lock:
            if self._data is None:
                return 0.0
            return len(self._data) / self._sr if self._sr else 0.0

    def set_volume(self, value: float) -> None:
        self._vol = float(max(0.0, min(1.0, value)))

    def set_pan(self, value: float) -> None:
        self._pan = float(max(-1.0, min(1.0, value)))

    # ---- input ----
    def _open_input(self, device: Optional[int]) -> None:
        if self._in_stream is not None:
            return
        sr = int(self.settings.get("samplerate", 44100))
        try:
            self._in_stream = sd.InputStream(
                device=device, samplerate=sr, channels=2, dtype="float32",
                blocksize=int(self.settings.get("blocksize", 1024)),
                callback=self._input_cb,
            )
            self._in_stream.start()
        except Exception as exc:
            self._in_stream = None
            raise AudioEngineError(
                f"Не удалось открыть устройство ввода: {exc}\n"
                "Проверьте выбранное устройство и права доступа к микрофону."
            ) from exc

    def _close_input(self) -> None:
        if self._in_stream is not None:
            try:
                self._in_stream.stop(); self._in_stream.close()
            except Exception:
                pass
            self._in_stream = None
        self._level = 0.0

    def _input_cb(self, indata, frames, time_info, status) -> None:
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata
        self._level = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
        self.tap.write(mono)
        if self._rec_file is not None:
            try:
                self._rec_file.write(indata)
            except Exception:
                pass

    def start_monitoring(self, device: Optional[int] = None) -> None:
        self._monitoring = True
        self._open_input(device)

    def stop_monitoring(self) -> None:
        self._monitoring = False
        if self._rec_file is None:
            self._close_input()

    @property
    def is_monitoring(self) -> bool:
        return self._in_stream is not None and self._rec_file is None

    def start_record(self, path: str, device: Optional[int] = None) -> None:
        if self._rec_file is not None:
            raise AudioEngineError("Запись уже идёт.")
        sr = int(self.settings.get("samplerate", 44100))
        try:
            self._rec_file = sf.SoundFile(
                str(path), mode="w", samplerate=sr, channels=2, subtype="PCM_16"
            )
        except Exception as exc:
            raise AudioEngineError(
                f"Не удалось создать файл записи «{Path(path).name}».\n"
                f"Проверьте путь и права на запись.\nДетали: {exc}"
            ) from exc
        try:
            self._open_input(device)
        except AudioEngineError:
            self._rec_file.close(); self._rec_file = None
            raise
        self.recording_changed.emit(True)

    def stop_record(self) -> None:
        if self._rec_file is None:
            return
        try:
            self._rec_file.close()
        except Exception:
            pass
        self._rec_file = None
        if not self._monitoring:
            self._close_input()
        self.recording_changed.emit(False)

    @property
    def is_recording(self) -> bool:
        return self._rec_file is not None

    @property
    def record_level_value(self) -> float:
        return min(1.0, self._level * 4.0)

    def start_generator(self, fill, device=None) -> None:
        self.stop_generator()
        sr = int(self.settings.get("samplerate", 44100))

        def cb(outdata, frames, time_info, status):
            try:
                block = np.asarray(fill(frames), dtype=np.float32)
                outdata[:] = block
                self.tap.write(block)
            except Exception:
                outdata.fill(0.0)

        try:
            self._gen = sd.OutputStream(
                device=device if device is not None else self._device,
                samplerate=sr, channels=2, dtype="float32",
                blocksize=0, callback=cb,
            )
            self._gen.start()
        except Exception as exc:
            self._gen = None
            raise AudioEngineError(
                f"Не удалось запустить генератор: {exc}\n"
                "Проверьте устройство вывода и частоту дискретизации."
            ) from exc

    def stop_generator(self) -> None:
        if self._gen is not None:
            try:
                self._gen.stop(); self._gen.close()
            except Exception:
                pass
            self._gen = None

    def _poll(self) -> None:
        with self._lock:
            eof = self._eof
        if eof and self._state == "playing":
            self.stop()

    def shutdown(self) -> None:
        self.stop(); self.stop_record(); self.stop_generator(); self.stop_monitoring()
        super().shutdown()


# ===========================================================================
#                                BASS ENGINE
# ===========================================================================
CALLBACK = C.WINFUNCTYPE if sys.platform.startswith("win") else C.CFUNCTYPE
DWORD, QWORD, BOOL = C.c_uint32, C.c_uint64, C.c_int

BASS_SAMPLE_FLOAT = 0x100
BASS_UNICODE = 0x80000000
BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_PAUSED = 3
BASS_ATTRIB_VOL = 2
BASS_ATTRIB_PAN = 3
BASS_POS_BYTE = 0
BASS_SYNC_END = 2
BASS_SYNC_META = 4
BASS_TAG_META = 5
BASS_ERROR_ALREADY = 19
BASS_DEVICE_ENABLED = 1

_BASS_ERRORS = {
    1: "нехватка памяти", 2: "файл не открывается", 3: "драйвер не найден",
    4: "буфер уже используется", 5: "сэмпл не найден", 6: "формат не поддерживается",
    7: "устройство недоступно", 8: "инициализация не выполнена", 9: "запуск не удался",
    14: "канал не найден", 19: "уже инициализировано", 20: "неверный параметр",
    40: "неподдерживаемый кодек",
}


class _DeviceInfo(C.Structure):
    _fields_ = [("name", C.c_char_p), ("driver", C.c_char_p), ("flags", DWORD)]


DSPPROC = CALLBACK(None, DWORD, DWORD, C.c_void_p, DWORD, C.c_void_p)
SYNCPROC = CALLBACK(None, DWORD, DWORD, DWORD, C.c_void_p, C.c_void_p)
STREAMPROC = CALLBACK(DWORD, DWORD, C.c_void_p, DWORD, C.c_void_p)
RECORDPROC = CALLBACK(BOOL, DWORD, C.c_void_p, DWORD, C.c_void_p)


def _load_bass() -> C.CDLL:
    here = Path(__file__).resolve().parent
    if sys.platform.startswith("win"):
        names = [here / "bass.dll", Path("bass.dll"), "bass.dll"]
    elif sys.platform == "darwin":
        names = [here / "libbass.dylib", Path("libbass.dylib"), "libbass.dylib"]
    else:
        names = [here / "libbass.so", Path("libbass.so"), "libbass.so"]
    last: Optional[Exception] = None
    for n in names:
        try:
            return C.CDLL(str(n) if isinstance(n, Path) else n)
        except OSError as exc:
            last = exc
    raise AudioEngineError(
        "Библиотека BASS не найдена.\n"
        "Скачайте с https://www.un4seen.com и положите bass.dll рядом с "
        "aurora_studio.py.\n"
        f"Техническая деталь: {last}"
    )


class BassEngine(AudioEngine):
    name = "bass"
    supports_stream = True

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(settings, parent)
        self._lib = _load_bass()
        self._bind()
        self._handle = 0
        self._is_stream = False
        self._gen_handle = 0
        self._rec_handle = 0
        self._dsp = None
        self._sync_end = None
        self._sync_meta = None
        self._stream_proc = None
        self._rec_proc = None
        self._rec_wave: Optional[wave.Wave_write] = None
        self._monitoring = False
        self._gen_fill: Optional[Callable[[int], np.ndarray]] = None
        self._level = 0.0
        self._vol = float(settings.get("volume", 0.8))
        self._pan = float(settings.get("pan", 0.0))
        self._url = ""
        self._station = ""
        self._meta = ("", "")
        self._ended = False
        self._meta_pending = False

        if not self._lib.BASS_Init(-1, int(settings.get("samplerate", 44100)),
                                   0, None, None):
            code = self._lib.BASS_ErrorGetCode()
            if code != BASS_ERROR_ALREADY:
                raise AudioEngineError(f"BASS_Init: {_BASS_ERRORS.get(code, code)}")

    def _bind(self) -> None:
        L = self._lib
        L.BASS_ErrorGetCode.restype = C.c_int
        L.BASS_Init.argtypes = [C.c_int, DWORD, DWORD, C.c_void_p, C.c_void_p]
        L.BASS_Init.restype = BOOL
        L.BASS_Free.restype = BOOL
        L.BASS_GetDeviceInfo.argtypes = [DWORD, C.POINTER(_DeviceInfo)]
        L.BASS_GetDeviceInfo.restype = BOOL
        L.BASS_RecordGetDeviceInfo.argtypes = [DWORD, C.POINTER(_DeviceInfo)]
        L.BASS_RecordGetDeviceInfo.restype = BOOL
        L.BASS_StreamCreateFile.argtypes = [BOOL, C.c_void_p, QWORD, QWORD, DWORD]
        L.BASS_StreamCreateFile.restype = DWORD
        L.BASS_StreamCreateURL.argtypes = [C.c_char_p, DWORD, DWORD, C.c_void_p, C.c_void_p]
        L.BASS_StreamCreateURL.restype = DWORD
        L.BASS_StreamCreate.argtypes = [DWORD, DWORD, DWORD, STREAMPROC, C.c_void_p]
        L.BASS_StreamCreate.restype = DWORD
        L.BASS_ChannelPlay.argtypes = [DWORD, BOOL]; L.BASS_ChannelPlay.restype = BOOL
        L.BASS_ChannelPause.argtypes = [DWORD]; L.BASS_ChannelPause.restype = BOOL
        L.BASS_ChannelStop.argtypes = [DWORD]; L.BASS_ChannelStop.restype = BOOL
        L.BASS_ChannelIsActive.argtypes = [DWORD]; L.BASS_ChannelIsActive.restype = DWORD
        L.BASS_ChannelSetAttribute.argtypes = [DWORD, DWORD, C.c_float]
        L.BASS_ChannelSetAttribute.restype = BOOL
        L.BASS_ChannelGetPosition.argtypes = [DWORD, DWORD]
        L.BASS_ChannelGetPosition.restype = QWORD
        L.BASS_ChannelGetLength.argtypes = [DWORD, DWORD]
        L.BASS_ChannelGetLength.restype = QWORD
        L.BASS_ChannelSetPosition.argtypes = [DWORD, QWORD, DWORD]
        L.BASS_ChannelSetPosition.restype = BOOL
        L.BASS_ChannelBytes2Seconds.argtypes = [DWORD, QWORD]
        L.BASS_ChannelBytes2Seconds.restype = C.c_double
        L.BASS_ChannelSeconds2Bytes.argtypes = [DWORD, C.c_double]
        L.BASS_ChannelSeconds2Bytes.restype = QWORD
        L.BASS_ChannelSetDSP.argtypes = [DWORD, DSPPROC, C.c_void_p, C.c_int]
        L.BASS_ChannelSetDSP.restype = DWORD
        L.BASS_ChannelSetSync.argtypes = [DWORD, DWORD, QWORD, SYNCPROC, C.c_void_p]
        L.BASS_ChannelSetSync.restype = DWORD
        L.BASS_ChannelGetTags.argtypes = [DWORD, DWORD]
        L.BASS_ChannelGetTags.restype = C.c_void_p
        L.BASS_StreamFree.argtypes = [DWORD]; L.BASS_StreamFree.restype = BOOL
        L.BASS_RecordInit.argtypes = [C.c_int]; L.BASS_RecordInit.restype = BOOL
        L.BASS_RecordStart.argtypes = [DWORD, DWORD, DWORD, RECORDPROC, C.c_void_p]
        L.BASS_RecordStart.restype = DWORD

    def _err(self, prefix: str) -> str:
        code = self._lib.BASS_ErrorGetCode()
        return f"{prefix}: {_BASS_ERRORS.get(code, f'код {code}')}"

    def list_output_devices(self):
        out, info = [], _DeviceInfo(); i = 0
        while self._lib.BASS_GetDeviceInfo(i, C.byref(info)):
            if info.flags & BASS_DEVICE_ENABLED and info.name:
                out.append((i, info.name.decode("utf-8", "replace")))
            i += 1
        return out

    def list_input_devices(self):
        out, info = [], _DeviceInfo(); i = 0
        while self._lib.BASS_RecordGetDeviceInfo(i, C.byref(info)):
            if info.flags & BASS_DEVICE_ENABLED and info.name:
                out.append((i, info.name.decode("utf-8", "replace")))
            i += 1
        return out

    def _attach(self, handle: int, is_stream: bool) -> None:
        self._handle = handle
        self._is_stream = is_stream
        self._dsp = DSPPROC(self._dsp_cb)
        self._lib.BASS_ChannelSetDSP(handle, self._dsp, None, 0)
        self._lib.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL, self._vol)
        self._lib.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_PAN, self._pan)
        self._sync_end = SYNCPROC(self._end_cb)
        self._lib.BASS_ChannelSetSync(handle, BASS_SYNC_END, 0, self._sync_end, None)
        if is_stream:
            self._sync_meta = SYNCPROC(self._meta_cb)
            self._lib.BASS_ChannelSetSync(handle, BASS_SYNC_META, 0, self._sync_meta, None)
        if not self._lib.BASS_ChannelPlay(handle, True):
            raise AudioEngineError(self._err("Не удалось запустить воспроизведение"))
        self._set_state("playing")

    def _dsp_cb(self, hdsp, channel, buffer, length, user) -> None:
        if not buffer or length <= 0:
            return
        n = length // 4
        try:
            arr = np.frombuffer((C.c_float * n).from_address(buffer), dtype=np.float32)
            self.tap.write(arr)
        except Exception:
            pass

    def _end_cb(self, handle, channel, data, user) -> None: self._ended = True
    def _meta_cb(self, handle, channel, data, user) -> None: self._meta_pending = True

    def play_file(self, path: str) -> None:
        self.stop()
        p = Path(path)
        if not p.exists():
            raise AudioEngineError(
                f"Файл не найден: {p.name}\nПроверьте путь и права доступа."
            )
        if sys.platform.startswith("win"):
            cpath = C.c_wchar_p(str(p)); flags = BASS_SAMPLE_FLOAT | BASS_UNICODE
        else:
            cpath = C.c_char_p(str(p).encode("utf-8")); flags = BASS_SAMPLE_FLOAT
        handle = self._lib.BASS_StreamCreateFile(False, cpath, 0, 0, flags)
        if not handle:
            raise AudioEngineError(
                self._err("Не удалось открыть файл") +
                f"\nПоддерживаемые форматы: {SUPPORTED_FORMATS_LABEL}."
            )
        self._station = p.name
        self._attach(handle, is_stream=False)

    def play_url(self, url: str, title: str = "") -> None:
        self.stop()
        handle = self._lib.BASS_StreamCreateURL(
            url.encode("utf-8"), 0, BASS_SAMPLE_FLOAT, None, None
        )
        if not handle:
            raise AudioEngineError(
                self._err(f"Не удалось открыть поток «{title or url}»") +
                "\nПроверьте, что ссылка ведёт на аудиопоток, а не на веб-страницу."
            )
        self._url = url
        self._station = title or url
        self._attach(handle, is_stream=True)

    def pause(self) -> None:
        if self._handle and self._lib.BASS_ChannelIsActive(self._handle) == BASS_ACTIVE_PLAYING:
            self._lib.BASS_ChannelPause(self._handle)
            self._set_state("paused")

    def resume(self) -> None:
        if self._handle and self._lib.BASS_ChannelIsActive(self._handle) == BASS_ACTIVE_PAUSED:
            self._lib.BASS_ChannelPlay(self._handle, False)
            self._set_state("playing")

    def stop(self) -> None:
        if self._handle:
            try:
                self._lib.BASS_ChannelStop(self._handle)
                self._lib.BASS_StreamFree(self._handle)
            except Exception:
                pass
        self._handle = 0; self._is_stream = False; self._url = ""
        self._set_state("stopped")

    def seek(self, seconds: float) -> None:
        if not self._handle or self._is_stream:
            return
        pos = self._lib.BASS_ChannelSeconds2Bytes(self._handle, float(seconds))
        self._lib.BASS_ChannelSetPosition(self._handle, pos, BASS_POS_BYTE)

    def position(self) -> float:
        if not self._handle:
            return 0.0
        pos = self._lib.BASS_ChannelGetPosition(self._handle, BASS_POS_BYTE)
        return float(self._lib.BASS_ChannelBytes2Seconds(self._handle, pos))

    def duration(self) -> float:
        if not self._handle or self._is_stream:
            return 0.0
        length = self._lib.BASS_ChannelGetLength(self._handle, BASS_POS_BYTE)
        return float(self._lib.BASS_ChannelBytes2Seconds(self._handle, length))

    def set_volume(self, value: float) -> None:
        self._vol = float(max(0.0, min(1.0, value)))
        if self._handle:
            self._lib.BASS_ChannelSetAttribute(self._handle, BASS_ATTRIB_VOL, self._vol)

    def set_pan(self, value: float) -> None:
        self._pan = float(max(-1.0, min(1.0, value)))
        if self._handle:
            self._lib.BASS_ChannelSetAttribute(self._handle, BASS_ATTRIB_PAN, self._pan)

    # ---- input ----
    def _open_input(self, device: Optional[int]) -> None:
        if self._rec_handle:
            return
        sr = int(self.settings.get("samplerate", 44100))
        if device is not None:
            if not self._lib.BASS_RecordInit(int(device)):
                code = self._lib.BASS_ErrorGetCode()
                if code != BASS_ERROR_ALREADY:
                    raise AudioEngineError(self._err("Устройство ввода недоступно"))
        else:
            if not self._lib.BASS_RecordInit(-1):
                code = self._lib.BASS_ErrorGetCode()
                if code != BASS_ERROR_ALREADY:
                    raise AudioEngineError(self._err("Не удалось инициализировать вход"))
        self._rec_proc = RECORDPROC(self._record_cb)
        handle = self._lib.BASS_RecordStart(sr, 2, 0, self._rec_proc, None)
        if not handle:
            raise AudioEngineError(self._err("Не удалось открыть вход"))
        self._rec_handle = handle

    def _close_input(self) -> None:
        if self._rec_handle:
            self._lib.BASS_ChannelStop(self._rec_handle); self._rec_handle = 0
        self._level = 0.0

    def start_monitoring(self, device: Optional[int] = None) -> None:
        self._monitoring = True
        self._open_input(device)

    def stop_monitoring(self) -> None:
        self._monitoring = False
        if self._rec_wave is None:
            self._close_input()

    @property
    def is_monitoring(self) -> bool:
        return bool(self._rec_handle) and self._rec_wave is None

    def _record_cb(self, handle, buffer, length, user) -> int:
        if not buffer or length <= 0:
            return 1
        try:
            n = length // 2
            arr = np.frombuffer((C.c_int16 * n).from_address(buffer), dtype=np.int16)
            if self._rec_wave is not None:
                self._rec_wave.writeframes(arr.tobytes())
            f = arr.astype(np.float32) / 32768.0
            self._level = float(np.sqrt(np.mean(f * f)))
            self.tap.write(f)
        except Exception:
            pass
        return 1

    def start_record(self, path: str, device: Optional[int] = None) -> None:
        if self._rec_wave is not None:
            raise AudioEngineError("Запись уже идёт.")
        sr = int(self.settings.get("samplerate", 44100))
        try:
            self._rec_wave = wave.open(str(path), "wb")
            self._rec_wave.setnchannels(2)
            self._rec_wave.setsampwidth(2)
            self._rec_wave.setframerate(sr)
        except Exception as exc:
            raise AudioEngineError(
                f"Не удалось создать файл записи «{Path(path).name}».\n"
                f"Проверьте путь и права на запись.\nДетали: {exc}"
            ) from exc
        try:
            self._open_input(device)
        except AudioEngineError:
            self._rec_wave.close(); self._rec_wave = None
            raise
        self.recording_changed.emit(True)

    def stop_record(self) -> None:
        if self._rec_wave is not None:
            try:
                self._rec_wave.close()
            except Exception:
                pass
            self._rec_wave = None
        if not self._monitoring:
            self._close_input()
        self.recording_changed.emit(False)

    @property
    def is_recording(self) -> bool:
        return self._rec_wave is not None

    @property
    def record_level_value(self) -> float:
        return min(1.0, self._level * 4.0)

    def start_generator(self, fill, device=None) -> None:
        self.stop_generator()
        sr = int(self.settings.get("samplerate", 44100))
        self._gen_fill = fill
        self._stream_proc = STREAMPROC(self._gen_cb)
        handle = self._lib.BASS_StreamCreate(sr, 2, BASS_SAMPLE_FLOAT,
                                             self._stream_proc, None)
        if not handle:
            raise AudioEngineError(
                self._err("Не удалось создать поток генератора") +
                "\nПроверьте частоту дискретизации и выбранное устройство вывода."
            )
        self._gen_handle = handle
        self._lib.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL, 1.0)
        if not self._lib.BASS_ChannelPlay(handle, True):
            raise AudioEngineError(self._err("Не удалось запустить генератор"))

    def _gen_cb(self, handle, buffer, length, user) -> int:
        n = length // 8
        try:
            data = self._gen_fill(n) if self._gen_fill else np.zeros((n, 2), np.float32)
            data = np.ascontiguousarray(data, dtype=np.float32)
            C.memmove(buffer, data.ctypes.data, min(length, data.nbytes))
        except Exception:
            C.memset(buffer, 0, length)
        return length

    def stop_generator(self) -> None:
        if self._gen_handle:
            self._lib.BASS_ChannelStop(self._gen_handle)
            self._lib.BASS_StreamFree(self._gen_handle)
            self._gen_handle = 0
        self._gen_fill = None

    def _read_meta(self) -> tuple[str, str]:
        if not self._handle:
            return ("", "")
        title = ""
        ptr = self._lib.BASS_ChannelGetTags(self._handle, BASS_TAG_META)
        if ptr:
            raw = C.string_at(ptr).decode("utf-8", "replace")
            if "StreamTitle='" in raw:
                title = raw.split("StreamTitle='", 1)[1].split("';", 1)[0]
        return (title, self._station)

    def _poll(self) -> None:
        if self._meta_pending:
            self._meta_pending = False
            meta = self._read_meta()
            if meta != self._meta:
                self._meta = meta
                self.metadata_changed.emit(*meta)
        if self._handle:
            active = self._lib.BASS_ChannelIsActive(self._handle)
            if active == BASS_ACTIVE_STOPPED and self._state == "playing":
                self._set_state("stopped")

    def shutdown(self) -> None:
        self.stop(); self.stop_record(); self.stop_monitoring(); self.stop_generator()
        try:
            self._lib.BASS_Free()
        except Exception:
            pass
        super().shutdown()


def create_engine(name: str, settings: Settings) -> AudioEngine:
    if name == "bass":
        return BassEngine(settings)
    return SoundDeviceEngine(settings)


# ===========================================================================
#                              SIGNAL GENERATOR
# ===========================================================================
class SignalGenerator:
    WAVEFORMS = ("sine", "square", "triangle", "saw", "wav")
    MIN_FREQ = 1.0
    MAX_FREQ = 20000.0

    def __init__(self) -> None:
        self.waveform = "sine"
        self.freq = 440.0
        self.amplitude = 0.5
        self.duty = 0.5
        self.burst = False
        self.burst_ms = 200.0
        self.gap_ms = 200.0
        self.burst_count = 0
        self._phase = 0.0
        self._counter = 0
        self._done = False
        self._wav: Optional[np.ndarray] = None
        self._wav_pos = 0

    def load_wav(self, path: str, samplerate: int) -> None:
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as exc:
            raise AudioEngineError(
                f"Не удалось загрузить WAV «{Path(path).name}»: {exc}"
            ) from exc
        mono = data.mean(axis=1)
        if sr != samplerate and len(mono) > 1:
            x_old = np.linspace(0, 1, len(mono), endpoint=False)
            x_new = np.linspace(0, 1, int(len(mono) * samplerate / sr), endpoint=False)
            mono = np.interp(x_new, x_old, mono).astype(np.float32)
        self._wav = mono
        self._wav_pos = 0
        self.waveform = "wav"

    def reset(self) -> None:
        self._phase = 0.0; self._counter = 0
        self._done = False; self._wav_pos = 0

    def render(self, n: int, samplerate: int) -> np.ndarray:
        n = int(n)
        if self._done or n <= 0:
            return np.zeros((n, 2), dtype=np.float32)
        freq = max(self.MIN_FREQ, min(self.MAX_FREQ, self.freq))
        t = self._phase + np.arange(n) * (freq / samplerate)
        if self.waveform == "sine":
            s = np.sin(2.0 * np.pi * t)
        elif self.waveform == "square":
            s = np.where((t % 1.0) < self.duty, 1.0, -1.0)
        elif self.waveform == "triangle":
            ph = t % 1.0
            s = 1.0 - 4.0 * np.abs(ph - 0.5)
        elif self.waveform == "saw":
            s = 2.0 * (t % 1.0) - 1.0
        elif self.waveform == "wav" and self._wav is not None and len(self._wav):
            idx = (self._wav_pos + np.arange(n)) % len(self._wav)
            s = self._wav[idx]
            self._wav_pos = int((self._wav_pos + n) % len(self._wav))
        else:
            s = np.zeros(n)
        self._phase = float((self._phase + n * freq / samplerate) % 1.0)

        env = np.ones(n, dtype=np.float32)
        if self.burst:
            burst_len = max(1, int(samplerate * self.burst_ms / 1000.0))
            gap_len = max(1, int(samplerate * self.gap_ms / 1000.0))
            period = burst_len + gap_len
            idx = self._counter + np.arange(n)
            env = ((idx % period) < burst_len).astype(np.float32)
            completed = (self._counter + n) // period
            self._counter += n
            if self.burst_count > 0 and completed >= self.burst_count:
                self._done = True

        amp = float(max(0.0, min(1.0, self.amplitude)))
        out = (s * env * amp).astype(np.float32)
        return np.repeat(out[:, None], 2, axis=1)


# ===========================================================================
#                                RADIO
# ===========================================================================
@dataclass
class Station:
    name: str
    url: str


class StationStore:
    def __init__(self) -> None:
        self.stations: list[Station] = []
        self.load()

    def load(self) -> None:
        try:
            if STATIONS_FILE.exists():
                raw = json.loads(STATIONS_FILE.read_text("utf-8"))
                self.stations = [Station(**s) for s in raw if s.get("url")]
        except Exception:
            self.stations = []

    def save(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            STATIONS_FILE.write_text(
                json.dumps([asdict(s) for s in self.stations],
                           indent=2, ensure_ascii=False),
                "utf-8",
            )
        except Exception:
            pass

    def add(self, name: str, url: str) -> Station:
        st = Station(name.strip() or url.strip(), url.strip())
        self.stations.append(st); self.save(); return st

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.stations):
            self.stations.pop(index); self.save()


class RadioController(QObject):
    connection_changed = pyqtSignal(bool)
    status = pyqtSignal(str)
    state = pyqtSignal(str)  # "idle" | "connecting" | "buffering" | "playing" | "error"

    def __init__(self, engine: AudioEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._station: Optional[Station] = None
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._restart)

    def bind_engine(self, engine: AudioEngine) -> None:
        self.stop()
        self.engine = engine

    def play(self, station: Station) -> None:
        self._station = station
        self.connection_changed.emit(False)
        self.state.emit("connecting")
        self.status.emit("Подключение к потоку…")
        try:
            self.engine.play_url(station.url, station.name)
            self.state.emit("playing")
            self.status.emit(f"Воспроизведение · {station.name}")
            self.connection_changed.emit(True)
        except Exception as exc:
            self.state.emit("error")
            self.status.emit(f"Ошибка: {exc}")
            self._schedule_restart()

    def stop(self) -> None:
        self._station = None
        self._restart_timer.stop()
        try:
            self.engine.stop()
        except Exception:
            pass
        self.connection_changed.emit(False)
        self.state.emit("idle")
        self.status.emit("Готов к подключению")

    def on_state_changed(self, state: str) -> None:
        if self._station and state == "stopped":
            self.connection_changed.emit(False)
            self.state.emit("buffering")
            self.status.emit("Соединение потеряно — переподключение…")
            self._schedule_restart()

    def _schedule_restart(self) -> None:
        if self._station and not self._restart_timer.isActive():
            self._restart_timer.start(3000)

    def _restart(self) -> None:
        if self._station:
            self.state.emit("buffering")
            self.status.emit("Буферизация…")
            try:
                self.engine.play_url(self._station.url, self._station.name)
                self.state.emit("playing")
                self.status.emit(f"Воспроизведение · {self._station.name}")
                self.connection_changed.emit(True)
            except Exception:
                self._schedule_restart()


# ===========================================================================
#                                VIZ
# ===========================================================================
class Analyzer(QThread):
    frame = pyqtSignal(object)
    N_BINS = 96

    def __init__(self, tap: AudioTap, samplerate: int, fft_size: int = 2048,
                 smoothing: float = 0.6, peak_hold: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.tap = tap
        self.samplerate = samplerate
        self.fft_size = fft_size
        self.smoothing = smoothing
        self.peak_hold = peak_hold
        self._running = True
        self._smooth = np.full(self.N_BINS, -90.0, dtype=np.float32)
        self._peaks = np.full(self.N_BINS, -90.0, dtype=np.float32)
        self._build_bins()

    def _build_bins(self) -> None:
        sr = self.samplerate
        freqs = np.fft.rfftfreq(self.fft_size, 1.0 / sr)
        f_max = min(20000.0, sr / 2.0)
        edges = np.geomspace(20.0, f_max, self.N_BINS + 1)
        self.centers = ((edges[:-1] + edges[1:]) / 2.0).astype(np.float32)
        self._idx = []
        for i in range(self.N_BINS):
            lo, hi = edges[i], edges[i + 1]
            sel = np.where((freqs >= lo) & (freqs < hi))[0]
            if sel.size == 0:
                sel = np.array([min(len(freqs) - 1, int(np.searchsorted(freqs, lo)))])
            self._idx.append(sel)

    def run(self) -> None:
        window = np.hanning(self.fft_size).astype(np.float32)
        while self._running:
            scope = self.tap.read(4096)
            bars = self._smooth.copy()
            if scope.size >= self.fft_size:
                seg = scope[-self.fft_size:] * window
                mag = np.abs(np.fft.rfft(seg))
                db = 20.0 * np.log10(mag / (self.fft_size / 2.0) + 1e-9)
                db = np.clip(db, -90.0, 0.0)
                raw = np.array([db[idx].max() for idx in self._idx], dtype=np.float32)
                a = float(self.smoothing)
                self._smooth = a * self._smooth + (1.0 - a) * raw
                bars = self._smooth
                if self.peak_hold:
                    self._peaks = np.maximum(self._peaks - 0.9, bars)
                else:
                    self._peaks = bars
            self.frame.emit({"scope": scope, "bars": bars,
                             "peaks": self._peaks, "centers": self.centers})
            self.msleep(25)

    def stop(self) -> None:
        self._running = False
        self.wait(500)


class FreqAxis(pg.AxisItem):
    def __init__(self, centers, **kwargs) -> None:
        super().__init__(orientation="bottom", **kwargs)
        self.centers = centers

    def tickValues(self, minVal, maxVal, size):
        ticks = []
        for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            i = int(np.argmin(np.abs(self.centers - f)))
            if minVal <= i <= maxVal:
                ticks.append(i)
        return [(1, ticks)] if ticks else []

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            i = int(round(v))
            if 0 <= i < len(self.centers):
                f = float(self.centers[i])
                out.append(f"{f / 1000:.0f}k" if f >= 1000 else f"{f:.0f}")
            else:
                out.append("")
        return out


class TimeAxis(pg.AxisItem):
    def __init__(self, samplerate: int, n_samples: int, **kwargs) -> None:
        super().__init__(orientation="bottom", **kwargs)
        self.samplerate = samplerate
        self.n_samples = n_samples

    def tickValues(self, minVal, maxVal, size):  # noqa: ARG002
        total_ms = self.n_samples / self.samplerate * 1000.0
        step = max(1, int(total_ms / 4))
        ticks = [0, step, 2 * step, 3 * step, int(total_ms)]
        idx = [int(t / 1000.0 * self.samplerate) for t in ticks]
        return [(1, idx)]

    def tickStrings(self, values, scale, spacing):
        return [f"{v / self.samplerate * 1000:.0f}мс" for v in values]


class ScopeWidget(QWidget):
    def __init__(self, samplerate: int = 44100, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(axisItems={"bottom": TimeAxis(samplerate, 4096)})
        self.plot.setBackground("#0F131A")
        self.plot.showGrid(x=True, y=True, alpha=0.20)
        self.plot.setYRange(-1.05, 1.05)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.getAxis("left").setLabel("Амплитуда")
        self.plot.getAxis("bottom").setLabel("Время, мс")
        for ax in ("left", "bottom"):
            self.plot.getAxis(ax).setPen(pg.mkPen("#3A4252"))
            self.plot.getAxis(ax).setTextPen(pg.mkPen("#8B94A7"))
        # Контрастная линия: тёмная обводка + яркий основной цвет для читаемости
        self.curve_glow = self.plot.plot(pen=pg.mkPen("#0A0F18", width=5))
        self.curve = self.plot.plot(pen=pg.mkPen("#00E5FF", width=1.8))
        lay.addWidget(self.plot)

        self.placeholder = QLabel(
            "Нет входного сигнала.\nПодключите источник или запустите генератор.", self
        )
        self.placeholder.setObjectName("Muted")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(
            "color: #8B94A7; background: rgba(15,19,26,0.85); border-radius: 8px; padding: 12px;"
        )
        self.placeholder.hide()

    def show_placeholder(self, visible: bool) -> None:
        self.placeholder.setVisible(visible)
        self.placeholder.setGeometry(0, 0, self.width(), self.height())
        if visible:
            self.placeholder.raise_()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.placeholder.setGeometry(0, 0, self.width(), self.height())

    def update_scope(self, samples: np.ndarray) -> None:
        if samples is None or samples.size == 0:
            return
        self.curve.setData(samples, connect="finite")
        self.curve_glow.setData(samples, connect="finite")


class SpectrumWidget(QWidget):
    def __init__(self, centers: np.ndarray, mode: str = "bars", parent=None) -> None:
        super().__init__(parent)
        self.centers = np.asarray(centers, dtype=np.float32)
        x = np.arange(len(self.centers))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(axisItems={"bottom": FreqAxis(self.centers)})
        self.plot.setBackground("#0F131A")
        self.plot.showGrid(y=True, alpha=0.20)
        self.plot.setYRange(-90, 3)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.getAxis("left").setLabel("Амплитуда, дБ")
        self.plot.getAxis("bottom").setLabel("Частота, Гц")
        for ax in ("left", "bottom"):
            self.plot.getAxis(ax).setPen(pg.mkPen("#3A4252"))
            self.plot.getAxis(ax).setTextPen(pg.mkPen("#8B94A7"))
        self.bars_item = pg.BarGraphItem(
            x=x, height=np.full(len(x), -90.0), width=0.75,
            brush=pg.mkBrush("#8B6BFF"), pen=pg.mkPen(None),
        )
        self.plot.addItem(self.bars_item)
        self.line_item = self.plot.plot(
            x, np.full(len(x), -90.0), pen=pg.mkPen("#8B6BFF", width=2),
            fillLevel=-90, brush=pg.mkBrush(139, 107, 255, 70),
        )
        self.peak_item = self.plot.plot(
            x, np.full(len(x), -90.0), pen=pg.mkPen("#FFD166", width=1)
        )
        self.set_mode(mode)
        lay.addWidget(self.plot)

    def set_mode(self, mode: str) -> None:
        is_bars = mode == "bars"
        self.bars_item.setVisible(is_bars)
        self.line_item.setVisible(not is_bars)

    def set_peak_visible(self, visible: bool) -> None:
        self.peak_item.setVisible(visible)

    def update_frame(self, bars: np.ndarray, peaks: np.ndarray) -> None:
        if bars is None:
            return
        x = np.arange(len(bars))
        self.bars_item.setOpts(x=x, height=bars)
        self.line_item.setData(x, bars)
        self.peak_item.setData(x, peaks)


# ===========================================================================
#                                 THEME
# ===========================================================================
ACCENT = "#7C5CFF"
ACCENT_2 = "#22D3EE"
BG = "#0E1014"
SURFACE = "#151922"
CARD = "#1A1F2A"
BORDER = "#252B38"
TEXT = "#E7EAF0"
MUTED = "#8B94A7"
DANGER = "#FF5C7C"
OK = "#3DDC97"
WARN = "#FFD166"

QSS = f"""
* {{
    font-family: "Inter", "Segoe UI", "SF Pro Display", "Helvetica Neue", Arial;
    font-size: 13px; outline: none;
}}
QWidget {{ color: {TEXT}; background: transparent; }}
#Root {{ background: {BG}; }}
#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#Logo {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
#LogoSub {{ font-size: 10px; color: {MUTED}; letter-spacing: 3px; }}
QPushButton#Nav {{
    text-align: left; padding: 11px 14px; border-radius: 10px;
    color: {MUTED}; background: transparent; border: none;
    font-size: 13px; font-weight: 600;
}}
QPushButton#Nav:hover {{ background: {CARD}; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: rgba(124,92,255,0.16); color: {TEXT}; }}
#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px; }}
#Card[dragging="true"] {{
    background: #1C2230; border: 2px dashed {ACCENT};
}}
#H1 {{ font-size: 22px; font-weight: 700; }}
#H2 {{ font-size: 13px; font-weight: 700; color: {MUTED}; letter-spacing: 1px; }}
#Big {{ font-size: 26px; font-weight: 700; }}
#Muted {{ color: {MUTED}; }}
#Hint {{ color: {MUTED}; font-size: 12px; }}
#Badge {{
    background: rgba(124,92,255,0.15); color: {ACCENT};
    border-radius: 8px; padding: 3px 9px; font-size: 11px; font-weight: 700;
}}
#LiveBadge {{
    background: rgba(61,220,151,0.15); color: {OK};
    border-radius: 8px; padding: 2px 8px; font-size: 10px; font-weight: 800;
    letter-spacing: 1px;
}}
#StatusOk {{ color: {OK}; font-weight: 600; }}
#StatusWarn {{ color: {WARN}; font-weight: 600; }}
#StatusErr {{ color: {DANGER}; font-weight: 600; }}

QPushButton#Primary {{
    background: {ACCENT}; color: white; border: none;
    border-radius: 10px; padding: 10px 18px; font-weight: 700;
}}
QPushButton#Primary:hover {{ background: #8E72FF; }}
QPushButton#Primary:pressed {{ background: #6A4AE0; }}
QPushButton#Primary:disabled {{ background: #33384A; color: #79809A; }}

QPushButton#Ghost {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 16px;
}}
QPushButton#Ghost:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#Ghost:disabled {{ color: #555C6E; border-color: #1E222C; }}

QPushButton#Danger {{
    background: rgba(255,92,124,0.12); color: {DANGER};
    border: 1px solid rgba(255,92,124,0.30); border-radius: 10px; padding: 9px 16px;
}}
QPushButton#Danger:hover {{ background: rgba(255,92,124,0.20); }}

QPushButton#Play {{
    background: {ACCENT}; border: none; border-radius: 32px;
    min-width: 64px; min-height: 64px; max-width: 64px; max-height: 64px;
    font-size: 24px; color: white;
}}
QPushButton#Play:hover {{ background: #8E72FF; }}
QPushButton#Play:disabled {{ background: #33384A; color: #79809A; }}

/* Вторичная кнопка Stop: уменьшена, без заливки, только контур */
QPushButton#Stop {{
    background: transparent; border: 1px solid #3A4252;
    border-radius: 18px; min-width: 36px; min-height: 36px;
    max-width: 36px; max-height: 36px;
    font-size: 14px; color: {MUTED};
}}
QPushButton#Stop:hover {{ border-color: {DANGER}; color: {DANGER}; }}

QPushButton#Seek {{
    background: transparent; border: 1px solid {BORDER};
    border-radius: 16px; padding: 6px 12px;
    font-size: 12px; font-weight: 700; color: {MUTED};
}}
QPushButton#Seek:hover {{ border-color: {ACCENT_2}; color: {ACCENT_2}; }}

QSlider::groove:horizontal {{ height: 6px; background: #232936; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_2}; }}

/* Баланс с контрастной центральной риской */
QSlider#Balance::groove:horizontal {{ background: #232936; height: 8px; border-radius: 4px; }}
QSlider#Balance::sub-page:horizontal {{ background: transparent; }}
QSlider#Balance::add-page:horizontal {{ background: transparent; }}
QSlider#Balance::handle:horizontal {{
    background: {ACCENT_2}; width: 18px; height: 18px; margin: -6px 0;
    border-radius: 9px; border: 2px solid white;
}}

QComboBox, QLineEdit, QSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 8px 12px; color: {TEXT}; selection-background-color: {ACCENT};
    min-height: 18px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: #33405A; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {DANGER}; background: rgba(255,92,124,0.08); }}
QSpinBox[invalid="true"] {{ border-color: {DANGER}; background: rgba(255,92,124,0.08); }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    selection-background-color: rgba(124,92,255,0.25); padding: 4px;
}}
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 10px 12px; border-radius: 10px; color: {TEXT}; }}
QListWidget::item:hover {{ background: {SURFACE}; }}
QListWidget::item:selected {{ background: rgba(124,92,255,0.18); color: white; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #2C3444; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3B465C; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {BORDER}; background: {SURFACE};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{
    background: #232936; border: none; border-radius: 4px;
    height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT_2}; border-radius: 4px; }}
QToolTip {{
    background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 6px 8px; border-radius: 8px;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(CARD))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(p)
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet(QSS)


# ===========================================================================
#                                WIDGETS
# ===========================================================================
class Card(QFrame):
    def __init__(self, title: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 18, 20, 18)
        self._lay.setSpacing(14)
        if title:
            lbl = QLabel(title.upper())
            lbl.setObjectName("H2")
            self._lay.addWidget(lbl)

    def body(self) -> QVBoxLayout: return self._lay
    def add(self, widget: QWidget) -> QWidget:
        self._lay.addWidget(widget); return widget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(4)
        t = QLabel(title); t.setObjectName("H1")
        s = QLabel(subtitle); s.setObjectName("Muted")
        lay.addWidget(t); lay.addWidget(s)


class LevelMeter(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(14)
        self.setMaximumHeight(14)
        self._v = 0.0
        self._peak = 0.0

    def set_level(self, value: float) -> None:
        v = max(0.0, min(1.0, float(value)))
        self._v = v if v > self._v else self._v * 0.85 + v * 0.15
        self._peak = max(self._peak * 0.985, v)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#232936"))
        p.drawRoundedRect(r, 6, 6)
        w = int(r.width() * self._v)
        if w > 1:
            g = QLinearGradient(0, 0, r.width(), 0)
            g.setColorAt(0.0, QColor("#3DDC97"))
            g.setColorAt(0.65, QColor("#FFD166"))
            g.setColorAt(1.0, QColor("#FF5C7C"))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r.x(), r.y(), w, r.height(), 6, 6)
        px = int(r.width() * self._peak)
        if px > 2:
            p.setBrush(QColor("#FFFFFF"))
            p.drawRect(r.x() + px - 2, r.y(), 2, r.height())
        p.end()


class CenteredSlider(QSlider):
    """Слайдер с метками L/C/R и контрастной центральной риской."""
    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("Balance")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        w = self.width()
        margin = 9
        cx = margin + (w - 2 * margin) / 2.0
        pen = QPen(QColor(ACCENT_2)); pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(int(cx), 2, int(cx), h - 2)
        p.end()


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QCheckBox {{ spacing: 10px; color: {TEXT}; font-weight: 600; }}
            QCheckBox::indicator {{
                width: 40px; height: 20px; border-radius: 10px;
                background: {SURFACE}; border: 1px solid {BORDER};
            }}
            QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        """)


def hline() -> QFrame:
    line = QFrame(); line.setFixedHeight(1)
    line.setStyleSheet(f"background: {BORDER}; border: none;")
    return line


def fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def wrap_layout(layout) -> QWidget:
    w = QWidget(); w.setLayout(layout)
    layout.setContentsMargins(0, 0, 0, 0)
    return w


def set_invalid(widget: QWidget, invalid: bool) -> None:
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget); widget.style().polish(widget)


# ===========================================================================
#                                 PAGES
# ===========================================================================
DEFAULT_PLAYER_HINT = "Перетащите файл сюда или нажмите для выбора."


class PlayerPage(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine: Optional[AudioEngine] = None
        self.setAcceptDrops(True)
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def bind_engine(self, engine: AudioEngine) -> None:
        self.engine = engine
        engine.set_volume(self.vol_slider.value() / 100.0)
        engine.set_pan(self.pan_slider.value() / 100.0)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(PageHeader("Плеер", f"Локальные файлы · {SUPPORTED_FORMATS_LABEL}"))

        self.drop_card = Card("Сейчас играет")
        self.title = QLabel("Нет файла"); self.title.setObjectName("Big")
        self.drop_card.add(self.title)

        self.hint = QLabel(DEFAULT_PLAYER_HINT); self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        self.drop_card.add(self.hint)

        # Индикатор загрузки
        self.loading_row = QWidget()
        lr = QHBoxLayout(self.loading_row); lr.setContentsMargins(0, 0, 0, 0)
        self.loading_lbl = QLabel("Загрузка…")
        self.loading_lbl.setStyleSheet(f"color: {WARN}; font-weight: 600;")
        self.loading_bar = QProgressBar(); self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedHeight(6)
        lr.addWidget(self.loading_lbl); lr.addWidget(self.loading_bar, 1)
        self.loading_row.setVisible(False)
        self.drop_card.add(self.loading_row)

        self.path_lbl = QLabel(""); self.path_lbl.setObjectName("Muted")
        self.drop_card.add(self.path_lbl)
        self.drop_card.add(hline())

        row = QHBoxLayout()
        self.pos_lbl = QLabel("00:00"); self.pos_lbl.setObjectName("Muted")
        self.dur_lbl = QLabel("00:00"); self.dur_lbl.setObjectName("Muted")
        self.seek = QSlider(Qt.Orientation.Horizontal); self.seek.setRange(0, 1000)
        self.seek.sliderReleased.connect(self._on_seek)
        row.addWidget(self.pos_lbl); row.addWidget(self.seek, 1); row.addWidget(self.dur_lbl)
        self.drop_card.add(wrap_layout(row))

        tr = QHBoxLayout(); tr.setSpacing(10)
        self.btn_open = QPushButton("Открыть файл…"); self.btn_open.setObjectName("Ghost")
        self.btn_open.clicked.connect(lambda: self._open_file(""))
        self.btn_back = QPushButton("−5с"); self.btn_back.setObjectName("Seek")
        self.btn_back.setToolTip("Назад 5 секунд")
        self.btn_back.clicked.connect(lambda: self._seek_rel(-5))
        self.btn_play = QPushButton("▶"); self.btn_play.setObjectName("Play")
        self.btn_play.clicked.connect(self._toggle)
        self.btn_play.setToolTip("Play / Pause")
        self.btn_stop = QPushButton("■"); self.btn_stop.setObjectName("Stop")
        self.btn_stop.setToolTip("Стоп")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_fwd = QPushButton("+5с"); self.btn_fwd.setObjectName("Seek")
        self.btn_fwd.setToolTip("Вперёд 5 секунд")
        self.btn_fwd.clicked.connect(lambda: self._seek_rel(5))

        tr.addWidget(self.btn_open)
        tr.addStretch(1)
        tr.addWidget(self.btn_back)
        tr.addWidget(self.btn_stop)
        tr.addWidget(self.btn_play)
        tr.addWidget(self.btn_fwd)
        tr.addStretch(1)
        self.drop_card.add(wrap_layout(tr))
        root.addWidget(self.drop_card)

        # Громкость / баланс
        card2 = Card("Громкость и баланс")
        self.vol_slider = self._labeled_slider(card2, "Громкость", 0, 100, 80)
        self.vol_slider.valueChanged.connect(self._on_volume)

        # Баланс с L/C/R и центральной риской
        bal_row = QHBoxLayout()
        bal_lbl = QLabel("Баланс"); bal_lbl.setFixedWidth(90)
        l_lbl = QLabel("L"); l_lbl.setObjectName("Muted"); l_lbl.setFixedWidth(14)
        self.pan_slider = CenteredSlider(); self.pan_slider.setRange(-100, 100)
        self.pan_slider.setValue(0)
        self.pan_slider.setToolTip("Баланс: L — левый канал, C — центр, R — правый канал")
        r_lbl = QLabel("R"); r_lbl.setObjectName("Muted"); r_lbl.setFixedWidth(14)
        self.pan_val = QLabel("C"); self.pan_val.setObjectName("Muted")
        self.pan_val.setFixedWidth(32); self.pan_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pan_slider.valueChanged.connect(self._on_pan)
        bal_row.addWidget(bal_lbl); bal_row.addWidget(l_lbl)
        bal_row.addWidget(self.pan_slider, 1); bal_row.addWidget(r_lbl)
        bal_row.addWidget(self.pan_val)
        card2.add(wrap_layout(bal_row))
        root.addWidget(card2)
        root.addStretch(1)

    def _labeled_slider(self, card, name, lo, hi, val) -> QSlider:
        row = QHBoxLayout()
        lbl = QLabel(name); lbl.setFixedWidth(90)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi); s.setValue(val)
        row.addWidget(lbl); row.addWidget(s, 1)
        card.add(wrap_layout(row))
        return s

    # ---- DnD ----
    def _has_audio_urls(self, mime) -> bool:
        if not mime.hasUrls():
            return False
        for u in mime.urls():
            if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in SUPPORTED_AUDIO_EXT:
                return True
        return False

    def dragEnterEvent(self, event) -> None:
        if self._has_audio_urls(event.mimeData()):
            self._set_drag_state(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._has_audio_urls(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_state(False)

    def dropEvent(self, event) -> None:
        self._set_drag_state(False)
        for u in event.mimeData().urls():
            if u.isLocalFile():
                self._open_file(u.toLocalFile())
                return

    def _set_drag_state(self, dragging: bool) -> None:
        self.drop_card.setProperty("dragging", "true" if dragging else "false")
        self.drop_card.style().unpolish(self.drop_card)
        self.drop_card.style().polish(self.drop_card)
        if dragging:
            self.hint.setText("Отпустите файл, чтобы загрузить его")
            self.hint.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        else:
            self.hint.setText(DEFAULT_PLAYER_HINT)
            self.hint.setStyleSheet("")

    # ---- действия ----
    def _open_file(self, path: str) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Открыть аудиофайл", self.settings.get("last_dir"),
                "Аудио (*.wav *.mp3 *.flac *.ogg *.oga *.m4a *.aac *.opus);;Все файлы (*)",
            )
        if not path:
            return
        ext = Path(path).suffix.lower()
        if ext not in SUPPORTED_AUDIO_EXT:
            self._show_error(
                f"Формат «{ext}» не поддерживается.\n"
                f"Допустимые: {SUPPORTED_FORMATS_LABEL}."
            )
            return
        self.settings.set("last_dir", str(Path(path).parent)); self.settings.save()
        if self.engine is None:
            return

        self.hint.setVisible(False)
        self.path_lbl.setText(path); self.path_lbl.setStyleSheet("")
        self.loading_row.setVisible(True)
        self.title.setText(f"Загрузка: {Path(path).name}")
        QApplication.processEvents()

        try:
            self.engine.play_file(path)
        except AudioEngineError as exc:
            self.loading_row.setVisible(False)
            self._show_error(str(exc))
            return
        finally:
            self.loading_row.setVisible(False)

        self.title.setText(Path(path).name)
        self.btn_play.setText("⏸")

    def _show_error(self, text: str) -> None:
        self.title.setText("Ошибка")
        self.path_lbl.setText(text)
        self.path_lbl.setStyleSheet(f"color: {DANGER};")
        QMessageBox.warning(self, "Плеер", text)

    def _toggle(self) -> None:
        if self.engine is None:
            return
        if self.engine.state == "playing":
            self.engine.pause(); self.btn_play.setText("▶")
        elif self.engine.state == "paused":
            self.engine.resume(); self.btn_play.setText("⏸")

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop()
        self.btn_play.setText("▶")

    def _seek_rel(self, delta: float) -> None:
        if self.engine is None:
            return
        dur = self.engine.duration()
        if dur <= 0:
            return
        new_pos = max(0.0, min(dur, self.engine.position() + delta))
        self.engine.seek(new_pos)

    def _on_seek(self) -> None:
        if self.engine:
            self.engine.seek(self.seek.value() / 1000.0 * self.engine.duration())

    def _on_volume(self, v: int) -> None:
        self.settings.set("volume", v / 100.0)
        if self.engine:
            self.engine.set_volume(v / 100.0)

    def _on_pan(self, v: int) -> None:
        self.settings.set("pan", v / 100.0)
        if self.engine:
            self.engine.set_pan(v / 100.0)
        if v == 0:
            self.pan_val.setText("C")
        elif v < 0:
            self.pan_val.setText(f"L{abs(v)}")
        else:
            self.pan_val.setText(f"R{v}")

    def _tick(self) -> None:
        if self.engine is None:
            return
        pos, dur = self.engine.position(), self.engine.duration()
        self.pos_lbl.setText(fmt_time(pos))
        self.dur_lbl.setText(fmt_time(dur))
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / dur * 1000) if dur > 0 else 0)
            self.seek.blockSignals(False)
        self.btn_play.setText("⏸" if self.engine.state == "playing" else "▶")


class RecordPage(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine: Optional[AudioEngine] = None
        self._seconds = 0.0
        self._limit_s = int(settings.get("record_limit_min", 60)) * 60
        self._warned = False
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def bind_engine(self, engine: AudioEngine) -> None:
        self.engine = engine
        self._fill_devices()
        if self.chk_monitor.isChecked():
            try:
                engine.start_monitoring(self.devices.currentData())
            except AudioEngineError as exc:
                self.chk_monitor.setChecked(False)
                self._set_status(str(exc), "err")

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(PageHeader("Запись", "Захват звука с выбранного устройства ввода"))

        # ---- Параметры ----
        card = Card("Параметры записи")
        row = QHBoxLayout()
        row.addWidget(QLabel("Устройство ввода"))
        self.devices = QComboBox()
        self.devices.currentIndexChanged.connect(self._on_device_change)
        row.addWidget(self.devices, 1)
        card.add(wrap_layout(row))

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Лимит записи"))
        self.spin_limit = QSpinBox(); self.spin_limit.setRange(1, 600)
        self.spin_limit.setValue(int(self.settings.get("record_limit_min", 60)))
        self.spin_limit.setSuffix(" мин")
        self.spin_limit.setToolTip("Максимальная длительность записи (защита от случайной длинной тишины)")
        self.spin_limit.valueChanged.connect(self._on_limit_change)
        row3.addWidget(self.spin_limit)
        self.chk_monitor = QCheckBox("Мониторинг входа")
        self.chk_monitor.setToolTip("Показывать уровень входного сигнала без записи в файл")
        self.chk_monitor.setChecked(bool(self.settings.get("monitoring", True)))
        self.chk_monitor.toggled.connect(self._on_monitor_toggle)
        row3.addSpacing(20); row3.addWidget(self.chk_monitor); row3.addStretch(1)
        card.add(wrap_layout(row3))
        root.addWidget(card)

        # ---- Куда сохранить (всегда активно, с путем по умолчанию) ----
        save_card = Card("Куда сохранить")
        srow = QHBoxLayout()
        default_path = self.settings.get("last_record_path", str(DEFAULT_SAVE_DIR / "aurora_record.wav"))
        self.file_lbl = QLabel(default_path)
        self.file_lbl.setObjectName("Muted")
        self.file_lbl.setWordWrap(True)
        self.file_lbl.setToolTip("Путь для сохранения записи. Можно изменить.")
        btn_pick = QPushButton("📁 Изменить…")
        btn_pick.setObjectName("Ghost")
        btn_pick.setToolTip("Выберите файл для сохранения записи")
        btn_pick.clicked.connect(self._choose_file)
        srow.addWidget(QLabel("Файл:"))
        srow.addWidget(self.file_lbl, 1)
        srow.addWidget(btn_pick)
        save_card.add(wrap_layout(srow))
        root.addWidget(save_card)

        # ---- Уровень и запись ----
        card2 = Card("Уровень сигнала")
        lrow = QHBoxLayout()
        self.live_badge = QLabel("LIVE"); self.live_badge.setObjectName("LiveBadge")
        self.live_badge.setVisible(False)
        lrow.addWidget(self.live_badge); lrow.addStretch(1)
        card2.add(wrap_layout(lrow))
        self.meter = LevelMeter(); card2.add(self.meter)

        strow = QHBoxLayout()
        self.time_lbl = QLabel("00:00"); self.time_lbl.setObjectName("Big")
        self.status_lbl = QLabel("Готов"); self.status_lbl.setObjectName("Muted")
        strow.addWidget(self.time_lbl); strow.addStretch(1); strow.addWidget(self.status_lbl)
        card2.add(wrap_layout(strow))

        btns = QHBoxLayout()
        self.btn_rec = QPushButton("● Начать запись"); self.btn_rec.setObjectName("Primary")
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_stop = QPushButton("Остановить"); self.btn_stop.setObjectName("Danger")
        self.btn_stop.clicked.connect(self._stop); self.btn_stop.setEnabled(False)
        btns.addWidget(self.btn_rec); btns.addWidget(self.btn_stop); btns.addStretch(1)
        card2.add(wrap_layout(btns))
        root.addWidget(card2)
        root.addStretch(1)

    # ---------- вспомогательное ----------
    def _fill_devices(self) -> None:
        self.devices.blockSignals(True)
        self.devices.clear()
        self.devices.addItem("Системное по умолчанию", None)
        if self.engine:
            for idx, name in self.engine.list_input_devices():
                self.devices.addItem(name, idx)
        saved = self.settings.get("input_device")
        if saved is not None:
            i = self.devices.findData(saved)
            if i >= 0:
                self.devices.setCurrentIndex(i)
        self.devices.blockSignals(False)

    def _on_device_change(self) -> None:
        dev = self.devices.currentData()
        self.settings.set("input_device", dev); self.settings.save()
        if self.chk_monitor.isChecked() and self.engine is not None and not self.engine.is_recording:
            try:
                self.engine.stop_monitoring()
                self.engine.start_monitoring(dev)
            except AudioEngineError as exc:
                self._set_status(str(exc), "err")

    def _on_limit_change(self, v: int) -> None:
        self._limit_s = int(v) * 60
        self.settings.set("record_limit_min", int(v)); self.settings.save()

    def _on_monitor_toggle(self, checked: bool) -> None:
        if self.engine is None:
            return
        self.settings.set("monitoring", checked); self.settings.save()
        try:
            if checked and not self.engine.is_recording:
                self.engine.start_monitoring(self.devices.currentData())
            elif not checked:
                self.engine.stop_monitoring()
        except AudioEngineError as exc:
            self.chk_monitor.setChecked(False)
            QMessageBox.warning(self, "Мониторинг", str(exc))

    def _choose_file(self) -> None:
        current = self.settings.get("last_record_path", str(DEFAULT_SAVE_DIR / "aurora_record.wav"))
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить запись", current, "WAV (*.wav)")
        if path:
            self.settings.set("last_record_path", path); self.settings.save()
            self.file_lbl.setText(path)

    def _set_status(self, text: str, kind: str = "") -> None:
        self.status_lbl.setText(text)
        color = {"ok": OK, "warn": WARN, "err": DANGER}.get(kind, MUTED)
        self.status_lbl.setStyleSheet(f"color: {color};")

    def _toggle_record(self) -> None:
        if self.engine is None:
            return
        if self.engine.is_recording:
            self._stop(); return
        path = self.settings.get("last_record_path", "")
        if not path:
            self._choose_file()
            path = self.settings.get("last_record_path", "")
            if not path:
                return
        try:
            self.engine.start_record(path, self.devices.currentData())
        except AudioEngineError as exc:
            self._set_status(f"Ошибка: {exc}", "err")
            QMessageBox.warning(self, "Запись", str(exc))
            return
        self._seconds = 0.0; self._warned = False
        self.btn_rec.setEnabled(False); self.btn_stop.setEnabled(True)
        self._set_status(f"Идёт запись → {Path(path).name}", "ok")

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop_record()
        self.btn_rec.setEnabled(True); self.btn_stop.setEnabled(False)
        if self.chk_monitor.isChecked():
            self._set_status("Готов · мониторинг активен")
        else:
            self._set_status("Готов")

    def _tick(self) -> None:
        if self.engine is None:
            return
        self.meter.set_level(self.engine.record_level_value)
        live = self.engine.is_recording or self.engine.is_monitoring
        self.live_badge.setVisible(live)

        if self.engine.is_recording:
            self._seconds += 0.2
            self.time_lbl.setText(fmt_time(self._seconds))
            if not self._warned and self._seconds >= self._limit_s - 300:
                self._warned = True
                self._set_status("До лимита осталось 5 минут. Остановите запись, чтобы сохранить данные.", "warn")
            if self._seconds >= self._limit_s:
                self._stop()
                QMessageBox.information(
                    self, "Запись",
                    f"Достигнут лимит записи ({self._limit_s // 60} мин). "
                    "Запись остановлена автоматически."
                )
        else:
            self.time_lbl.setText(fmt_time(self._seconds))


class RadioPage(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = StationStore()
        self.controller: Optional[RadioController] = None
        self._build()
        self._refresh_list()

    def bind_engine(self, engine: AudioEngine) -> None:
        if self.controller is not None:
            self.controller.bind_engine(engine)
        else:
            self.controller = RadioController(engine, self)
            self.controller.status.connect(self._on_status)
            self.controller.state.connect(self._on_state)
            self.controller.connection_changed.connect(self._on_conn)
        try:
            engine.metadata_changed.disconnect(self._on_meta)
        except TypeError:
            pass
        try:
            engine.state_changed.disconnect(self.controller.on_state_changed)
        except TypeError:
            pass
        engine.metadata_changed.connect(self._on_meta)
        engine.state_changed.connect(self.controller.on_state_changed)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(PageHeader("Онлайн-радио",
                                  "ICY-потоки, метаданные и авто-переподключение"))

        card = Card("Новая станция")
        row = QHBoxLayout()
        self.inp_name = QLineEdit(); self.inp_name.setPlaceholderText("Название станции")
        self.inp_url = QLineEdit()
        self.inp_url.setPlaceholderText(URL_PLACEHOLDER)
        self.inp_url.setToolTip(URL_HINT)
        self.inp_url.textChanged.connect(self._validate_url)
        self.btn_add = QPushButton("Добавить"); self.btn_add.setObjectName("Primary")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add)
        row.addWidget(self.inp_name, 1); row.addWidget(self.inp_url, 2); row.addWidget(self.btn_add)
        card.add(wrap_layout(row))
        self.url_hint = QLabel(URL_HINT); self.url_hint.setObjectName("Hint"); self.url_hint.setWordWrap(True)
        card.add(self.url_hint)
        root.addWidget(card)

        card2 = Card("Мои станции")
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._play())
        self.list.setVisible(False); card2.add(self.list)
        self.empty_lbl = QLabel(
            "У вас пока нет станций. Добавьте первую, чтобы начать прослушивание."
        )
        self.empty_lbl.setObjectName("Muted")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setWordWrap(True); card2.add(self.empty_lbl)

        row2 = QHBoxLayout()
        self.btn_play = QPushButton("▶ Слушать"); self.btn_play.setObjectName("Primary")
        self.btn_play.clicked.connect(self._play)
        self.btn_stop = QPushButton("Стоп"); self.btn_stop.setObjectName("Ghost")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_del = QPushButton("Удалить"); self.btn_del.setObjectName("Danger")
        self.btn_del.clicked.connect(self._remove)
        row2.addWidget(self.btn_play); row2.addWidget(self.btn_stop)
        row2.addStretch(1); row2.addWidget(self.btn_del)
        card2.add(wrap_layout(row2))
        root.addWidget(card2, 1)

        card3 = Card("Состояние")
        self.track_lbl = QLabel("—"); self.track_lbl.setObjectName("Big")
        self.status_lbl = QLabel("Готов к подключению"); self.status_lbl.setObjectName("Muted")
        card3.add(self.track_lbl); card3.add(self.status_lbl)
        root.addWidget(card3)

    # ---------- валидация ----------
    def _validate_url(self) -> None:
        txt = self.inp_url.text().strip()
        valid = is_valid_stream_url(txt)
        self.btn_add.setEnabled(valid)
        set_invalid(self.inp_url, bool(txt) and not valid)
        if txt and not valid:
            self.url_hint.setText(
                "Проверьте формат ссылки. Принимаются прямые потоки, а не страницы сайтов."
            )
            self.url_hint.setStyleSheet(f"color: {DANGER};")
        else:
            self.url_hint.setText(URL_HINT)
            self.url_hint.setStyleSheet("")

    def _refresh_list(self) -> None:
        self.list.clear()
        for st in self.store.stations:
            self.list.addItem(QListWidgetItem(f"{st.name}\n{st.url}"))
        has = len(self.store.stations) > 0
        self.list.setVisible(has); self.empty_lbl.setVisible(not has)
        self.btn_play.setEnabled(has); self.btn_del.setEnabled(has)

    def _add(self) -> None:
        url = self.inp_url.text().strip()
        if not is_valid_stream_url(url):
            return
        self.store.add(self.inp_name.text(), url)
        self.inp_name.clear(); self.inp_url.clear()
        self._on_status("Станция добавлена", "ok")
        self._refresh_list()

    def _remove(self) -> None:
        i = self.list.currentRow()
        if i >= 0:
            self.store.remove(i); self._refresh_list()

    def _play(self) -> None:
        i = self.list.currentRow()
        if i < 0 or self.controller is None:
            self._on_status("Выберите станцию в списке", "warn")
            return
        self.controller.play(self.store.stations[i])

    def _stop(self) -> None:
        if self.controller:
            self.controller.stop()
        self.track_lbl.setText("—")

    def _on_status(self, text: str, kind: str = "") -> None:
        self.status_lbl.setText(text)
        color = {"ok": OK, "warn": WARN, "err": DANGER}.get(kind, MUTED)
        self.status_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _on_state(self, state: str) -> None:
        mapping = {
            "idle": ("Готов к подключению", ""),
            "connecting": ("Подключение…", "warn"),
            "buffering": ("Буферизация…", "warn"),
            "playing": ("Воспроизведение", "ok"),
            "error": ("Ошибка подключения. Проверьте URL потока.", "err"),
        }
        label, kind = mapping.get(state, ("", ""))
        if label:
            self._on_status(self.status_lbl.text() or label, kind)

    def _on_conn(self, ok: bool) -> None:
        if ok:
            self.status_lbl.setStyleSheet(f"color: {OK}; font-weight: 600;")

    def _on_meta(self, title: str, station: str) -> None:
        self.track_lbl.setText(title or station or "—")


class GeneratorPage(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine: Optional[AudioEngine] = None
        self.gen = SignalGenerator()
        self._running = False
        self._undo_stack: list[dict] = []
        self._suppress_undo = False
        self._build()

        # Ctrl+Z — отмена последнего изменения параметров
        sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc.activated.connect(self._undo)

    def bind_engine(self, engine: AudioEngine) -> None:
        self.engine = engine

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(PageHeader("Генератор сигналов", "Синтез в реальном времени без щелчков"))

        card = Card("Форма и параметры")
        row = QHBoxLayout()
        row.addWidget(QLabel("Форма"))
        self.wave = QComboBox()
        self.wave.addItems(["Синус", "Меандр", "Треугольник", "Пила", "WAV-файл"])
        self.wave.currentIndexChanged.connect(self._on_wave)
        row.addWidget(self.wave, 1)
        btn = QPushButton("Загрузить WAV…"); btn.setObjectName("Ghost")
        btn.clicked.connect(self._load_wav)
        row.addWidget(btn)
        card.add(wrap_layout(row))

        frow = QHBoxLayout()
        frow.addWidget(QLabel("Частота"))
        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(0, 1000); self.freq_slider.setValue(653)
        self.freq_slider.sliderPressed.connect(self._push_undo)
        self.freq_slider.valueChanged.connect(self._on_freq)
        self.freq_lbl = QLabel("440 Гц"); self.freq_lbl.setFixedWidth(90)
        frow.addWidget(self.freq_slider, 1); frow.addWidget(self.freq_lbl)
        card.add(wrap_layout(frow))

        arow = QHBoxLayout()
        arow.addWidget(QLabel("Амплитуда"))
        self.amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.amp_slider.setRange(0, 100); self.amp_slider.setValue(50)
        self.amp_slider.sliderPressed.connect(self._push_undo)
        self.amp_slider.valueChanged.connect(self._on_amp)
        self.amp_lbl = QLabel("50 %"); self.amp_lbl.setFixedWidth(90)
        arow.addWidget(self.amp_slider, 1); arow.addWidget(self.amp_lbl)
        card.add(wrap_layout(arow))

        drow = QHBoxLayout()
        drow.addWidget(QLabel("Скважность"))
        self.duty_slider = QSlider(Qt.Orientation.Horizontal)
        self.duty_slider.setRange(1, 99); self.duty_slider.setValue(50)
        self.duty_slider.sliderPressed.connect(self._push_undo)
        self.duty_slider.valueChanged.connect(self._on_duty)
        self.duty_lbl = QLabel("50 %"); self.duty_lbl.setFixedWidth(90)
        drow.addWidget(self.duty_slider, 1); drow.addWidget(self.duty_lbl)
        self.duty_row = wrap_layout(drow)
        card.add(self.duty_row)
        root.addWidget(card)

        # Превью формы сигнала
        prev_card = Card("Превью сигнала")
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setBackground("#0F131A"); self.preview_plot.setFixedHeight(120)
        self.preview_plot.setYRange(-1.1, 1.1)
        self.preview_plot.setMouseEnabled(x=False, y=False)
        self.preview_plot.getAxis("left").setLabel("Амплитуда")
        self.preview_plot.getAxis("bottom").setLabel("Время")
        for ax in ("left", "bottom"):
            self.preview_plot.getAxis(ax).setPen(pg.mkPen("#3A4252"))
            self.preview_plot.getAxis(ax).setTextPen(pg.mkPen("#8B94A7"))
        self.preview_curve = self.preview_plot.plot(pen=pg.mkPen("#00E5FF", width=2))
        prev_card.add(self.preview_plot)
        root.addWidget(prev_card)

        # Пакеты
        card2 = Card("Режим пакетов импульсов")
        self.chk_burst = ToggleSwitch("Режим пакетов: посылка/пауза")
        self.chk_burst.setToolTip("Генерирует сигнал сериями с заданной паузой между посылками")
        self.chk_burst.toggled.connect(self._on_burst_toggle)
        card2.add(self.chk_burst)

        brow = QHBoxLayout()
        blbl = QLabel("Посылка, мс")
        blbl.setToolTip("Длительность импульса в миллисекундах (1 мс = 0.001 с)")
        brow.addWidget(blbl)
        self.spin_burst = QSpinBox(); self.spin_burst.setRange(10, 10000); self.spin_burst.setValue(200)
        self.spin_burst.setToolTip("Длительность посылки в миллисекундах")
        self.spin_burst.valueChanged.connect(self._on_burst_param)
        brow.addWidget(self.spin_burst)
        glbl = QLabel("Пауза, мс")
        glbl.setToolTip("Длительность паузы между посылками в миллисекундах")
        brow.addWidget(glbl)
        self.spin_gap = QSpinBox(); self.spin_gap.setRange(10, 10000); self.spin_gap.setValue(200)
        self.spin_gap.setToolTip("Длительность паузы между посылками в миллисекундах")
        self.spin_gap.valueChanged.connect(self._on_burst_param)
        brow.addWidget(self.spin_gap)
        brow.addWidget(QLabel("Кол-во (0 = ∞)"))
        self.spin_count = QSpinBox(); self.spin_count.setRange(0, 100000); self.spin_count.setValue(0)
        self.spin_count.setToolTip("Число пакетов; 0 — бесконечный режим")
        self.spin_count.valueChanged.connect(self._on_burst_param)
        brow.addWidget(self.spin_count); brow.addStretch(1)
        card2.add(wrap_layout(brow))
        root.addWidget(card2)

        # Действия
        row3 = QHBoxLayout()
        self.btn_start = QPushButton("▶ Запустить генератор"); self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self._toggle)
        self.btn_undo = QPushButton("Отменить"); self.btn_undo.setObjectName("Ghost")
        self.btn_undo.setToolTip("Отменить последнее изменение параметров (Ctrl+Z)")
        self.btn_undo.clicked.connect(self._undo)
        self.btn_reset = QPushButton("Сбросить параметры"); self.btn_reset.setObjectName("Ghost")
        self.btn_reset.setToolTip("Вернуть все параметры генератора к значениям по умолчанию")
        self.btn_reset.clicked.connect(self._reset_params)
        self.status = QLabel("Остановлен"); self.status.setObjectName("Muted")
        row3.addWidget(self.btn_start); row3.addWidget(self.btn_undo); row3.addWidget(self.btn_reset)
        row3.addWidget(self.status); row3.addStretch(1)
        root.addWidget(wrap_layout(row3))
        root.addStretch(1)

        self._on_freq(self.freq_slider.value())
        self._on_wave(0)
        self._update_preview()

    # ---------- undo ----------
    def _snapshot(self) -> dict:
        return {
            "wave": self.wave.currentIndex(),
            "freq": self.freq_slider.value(),
            "amp": self.amp_slider.value(),
            "duty": self.duty_slider.value(),
            "burst": self.chk_burst.isChecked(),
            "burst_ms": self.spin_burst.value(),
            "gap_ms": self.spin_gap.value(),
            "count": self.spin_count.value(),
        }

    def _push_undo(self) -> None:
        if self._suppress_undo:
            return
        snap = self._snapshot()
        if not self._undo_stack or self._undo_stack[-1] != snap:
            self._undo_stack.append(snap)
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)

    def _undo(self) -> None:
        if not self._undo_stack:
            self._set_status("Нечего отменять", "warn"); return
        snap = self._undo_stack.pop()
        self._suppress_undo = True
        try:
            self.wave.setCurrentIndex(snap["wave"])
            self.freq_slider.setValue(snap["freq"])
            self.amp_slider.setValue(snap["amp"])
            self.duty_slider.setValue(snap["duty"])
            self.chk_burst.setChecked(snap["burst"])
            self.spin_burst.setValue(snap["burst_ms"])
            self.spin_gap.setValue(snap["gap_ms"])
            self.spin_count.setValue(snap["count"])
        finally:
            self._suppress_undo = False
        self._set_status("Изменение отменено", "ok")
        self._update_preview()

    # ---------- превью ----------
    def _update_preview(self) -> None:
        temp = SignalGenerator()
        temp.waveform = self.gen.waveform; temp.freq = self.gen.freq
        temp.amplitude = self.gen.amplitude; temp.duty = self.gen.duty
        temp.burst = self.gen.burst
        temp.burst_ms = float(self.spin_burst.value())
        temp.gap_ms = float(self.spin_gap.value())
        temp.burst_count = 0
        temp._wav = self.gen._wav
        sr = 44100
        if self.gen.waveform == "wav" and self.gen._wav is not None and len(self.gen._wav):
            n = min(len(self.gen._wav), 2000)
        else:
            n = int(sr * 3 / max(1.0, self.gen.freq))
            n = max(200, min(4000, n))
        data = temp.render(n, sr)[:, 0]
        self.preview_curve.setData(data)

    # ---------- обработчики ----------
    def _on_wave(self, index: int) -> None:
        keys = ("sine", "square", "triangle", "saw", "wav")
        self.gen.waveform = keys[index]
        self.duty_row.setVisible(self.gen.waveform == "square")
        self._update_preview()

    def _on_freq(self, value: int) -> None:
        freq = 10.0 ** (value / 1000.0 * np.log10(SignalGenerator.MAX_FREQ))
        self.gen.freq = float(max(SignalGenerator.MIN_FREQ,
                                  min(SignalGenerator.MAX_FREQ, freq)))
        in_range = SignalGenerator.MIN_FREQ <= self.gen.freq <= SignalGenerator.MAX_FREQ
        set_invalid(self.freq_slider, not in_range)
        if self.gen.freq >= 1000:
            self.freq_lbl.setText(f"{self.gen.freq / 1000:.2f} кГц")
        else:
            self.freq_lbl.setText(f"{self.gen.freq:.0f} Гц")
        self._update_preview()

    def _on_amp(self, value: int) -> None:
        self.gen.amplitude = max(0.0, min(1.0, value / 100.0))
        self.amp_lbl.setText(f"{value} %")
        self._update_preview()

    def _on_duty(self, value: int) -> None:
        self.gen.duty = value / 100.0
        self.duty_lbl.setText(f"{value} %")
        self._update_preview()

    def _on_burst_toggle(self, checked: bool) -> None:
        self.gen.burst = checked; self._update_preview()

    def _on_burst_param(self) -> None:
        self._update_preview()

    def _load_wav(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить WAV", self.settings.get("last_dir"), "WAV (*.wav)"
        )
        if not path:
            return
        try:
            self.gen.load_wav(path, int(self.settings.get("samplerate", 44100)))
        except AudioEngineError as exc:
            self._set_status(f"Ошибка: {exc}", "err"); return
        self._push_undo()
        self.wave.setCurrentIndex(4)
        self._set_status(f"Загружен: {Path(path).name}", "ok")
        self._update_preview()

    def _reset_params(self) -> None:
        self._push_undo()
        self.wave.setCurrentIndex(0)
        self.freq_slider.setValue(653)
        self.amp_slider.setValue(50)
        self.duty_slider.setValue(50)
        self.chk_burst.setChecked(False)
        self.spin_burst.setValue(200)
        self.spin_gap.setValue(200)
        self.spin_count.setValue(0)
        self._set_status("Параметры сброшены", "ok")

    def _set_status(self, text: str, kind: str = "") -> None:
        self.status.setText(text)
        color = {"ok": OK, "warn": WARN, "err": DANGER}.get(kind, MUTED)
        self.status.setStyleSheet(f"color: {color};")

    def _toggle(self) -> None:
        if self.engine is None:
            return
        if self._running:
            self.engine.stop_generator()
            self._running = False
            self.btn_start.setText("▶ Запустить генератор")
            self._set_status("Остановлен")
            return
        self.gen.burst = self.chk_burst.isChecked()
        self.gen.burst_ms = float(self.spin_burst.value())
        self.gen.gap_ms = float(self.spin_gap.value())
        self.gen.burst_count = int(self.spin_count.value())
        self.gen.reset()
        sr = int(self.settings.get("samplerate", 44100))
        try:
            self.engine.start_generator(lambda n: self.gen.render(n, sr))
        except AudioEngineError as exc:
            self._set_status(f"Ошибка: {exc}. Сбросьте параметры генератора.", "err")
            QMessageBox.warning(self, "Генератор", f"Ошибка запуска:\n{exc}\n\nРекомендация: сбросьте параметры генератора или проверьте устройство вывода."); return
        self._running = True
        self.btn_start.setText("■ Остановить")
        self._set_status("Работает", "ok")


class VisualizerPage(QWidget):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine: Optional[AudioEngine] = None
        self.analyzer: Optional[Analyzer] = None
        self._silent_since: Optional[float] = None
        self._build()

    def bind_engine(self, engine: AudioEngine) -> None:
        self.engine = engine
        self._restart_analyzer()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Визуализация",
                                  "Осциллограмма и спектроанализатор в реальном времени"))

        controls = Card("Отображение")
        row = QHBoxLayout()
        mode_lbl = QLabel("Вид спектра")
        mode_lbl.setToolTip("Столбики — дискретные полосы частот, Линия — непрерывная кривая")
        row.addWidget(mode_lbl)
        self.mode = QComboBox()
        self.mode.addItems(["Столбики", "Линия"])
        self.mode.setCurrentIndex(0 if self.settings.get("spectrum_mode") == "bars" else 1)
        self.mode.currentIndexChanged.connect(self._on_mode)
        self.mode.setToolTip("Столбики — дискретные полосы частот; Линия — непрерывная кривая")
        row.addWidget(self.mode); row.addSpacing(16)
        self.chk_peak = QCheckBox("Peak hold")
        self.chk_peak.setToolTip("Фиксировать пиковые значения спектра на короткое время")
        self.chk_peak.setChecked(bool(self.settings.get("peak_hold")))
        self.chk_peak.toggled.connect(self._on_peak)
        row.addWidget(self.chk_peak); row.addSpacing(16)
        smooth_lbl = QLabel("Сглаживание")
        smooth_lbl.setToolTip("Больше — плавнее, но медленнее реакция")
        row.addWidget(smooth_lbl)
        self.smooth = QSlider(Qt.Orientation.Horizontal)
        self.smooth.setRange(0, 95)
        self.smooth.setValue(int(float(self.settings.get("smoothing", 0.6)) * 100))
        self.smooth.valueChanged.connect(self._on_smooth)
        row.addWidget(self.smooth, 1)
        controls.add(wrap_layout(row))
        root.addWidget(controls)

        dummy = Analyzer(AudioTap(4096),
                         int(self.settings.get("samplerate", 44100)),
                         int(self.settings.get("fft_size", 2048)))
        centers = dummy.centers

        self.scope = ScopeWidget(int(self.settings.get("samplerate", 44100)))
        self.scope.setMinimumHeight(180)
        sc = Card("Осциллограмма"); sc.add(self.scope)
        root.addWidget(sc, 1)

        mode = "bars" if self.mode.currentIndex() == 0 else "line"
        self.spectrum = SpectrumWidget(centers, mode)
        self.spectrum.set_peak_visible(self.chk_peak.isChecked())
        self.spectrum.setMinimumHeight(220)
        sp = Card("Спектр (20 Гц – 20 кГц)"); sp.add(self.spectrum)
        root.addWidget(sp, 2)

    def _restart_analyzer(self) -> None:
        if self.analyzer is not None:
            self.analyzer.stop(); self.analyzer = None
        if self.engine is None:
            return
        self.analyzer = Analyzer(
            self.engine.tap,
            int(self.settings.get("samplerate", 44100)),
            int(self.settings.get("fft_size", 2048)),
            float(self.settings.get("smoothing", 0.6)),
            bool(self.settings.get("peak_hold")),
            parent=self,
        )
        self.analyzer.frame.connect(self._on_frame)
        self.analyzer.start()

    def _on_frame(self, data: dict) -> None:
        scope = data["scope"]
        if scope.size > 0:
            rms = float(np.sqrt(np.mean(scope * scope)))
            if rms > 0.005:
                self._silent_since = None
                self.scope.show_placeholder(False)
            else:
                if self._silent_since is None:
                    self._silent_since = time.monotonic()
                elif time.monotonic() - self._silent_since > 1.0:
                    self.scope.show_placeholder(True)
        self.scope.update_scope(scope)
        self.spectrum.update_frame(data["bars"], data["peaks"])

    def _on_mode(self, index: int) -> None:
        mode = "bars" if index == 0 else "line"
        self.spectrum.set_mode(mode)
        self.settings.set("spectrum_mode", mode); self.settings.save()

    def _on_peak(self, checked: bool) -> None:
        self.settings.set("peak_hold", checked); self.settings.save()
        self.spectrum.set_peak_visible(checked)

    def _on_smooth(self, value: int) -> None:
        s = value / 100.0
        self.settings.set("smoothing", s)
        if self.analyzer:
            self.analyzer.smoothing = s

    def hideEvent(self, event) -> None:
        self.settings.save()


# ===========================================================================
#                           SETTINGS DIALOG & MAIN
# ===========================================================================
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, engine: AudioEngine, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.engine_box = QComboBox()
        self.engine_box.addItem("sounddevice (без DLL)", "sounddevice")
        self.engine_box.addItem("BASS (радио, все форматы)", "bass")
        k = self.engine_box.findData(settings.get("engine"))
        self.engine_box.setCurrentIndex(max(0, k))
        form.addRow("Аудиодвижок", self.engine_box)

        self.out_box = QComboBox()
        self.out_box.addItem("Системное по умолчанию", None)
        for i, name in engine.list_output_devices():
            self.out_box.addItem(name, i)
        k = self.out_box.findData(settings.get("output_device"))
        if k >= 0:
            self.out_box.setCurrentIndex(k)
        form.addRow("Устройство вывода", self.out_box)

        self.in_box = QComboBox()
        self.in_box.addItem("Системное по умолчанию", None)
        for i, name in engine.list_input_devices():
            self.in_box.addItem(name, i)
        k = self.in_box.findData(settings.get("input_device"))
        if k >= 0:
            self.in_box.setCurrentIndex(k)
        form.addRow("Устройство ввода", self.in_box)

        self.sr_box = QComboBox()
        for sr in (22050, 44100, 48000, 96000):
            self.sr_box.addItem(f"{sr} Гц", sr)
        k = self.sr_box.findData(int(settings.get("samplerate", 44100)))
        self.sr_box.setCurrentIndex(max(0, k))
        form.addRow("Частота дискретизации", self.sr_box)

        self.bs_box = QComboBox()
        for bs in (256, 512, 1024, 2048, 4096):
            self.bs_box.addItem(str(bs), bs)
        k = self.bs_box.findData(int(settings.get("blocksize", 1024)))
        self.bs_box.setCurrentIndex(max(0, k))
        form.addRow("Размер буфера", self.bs_box)

        self.fft_box = QComboBox()
        for n in (1024, 2048, 4096, 8192):
            self.fft_box.addItem(str(n), n)
        k = self.fft_box.findData(int(settings.get("fft_size", 2048)))
        self.fft_box.setCurrentIndex(max(0, k))
        form.addRow("Размер БПФ", self.fft_box)

        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def result_values(self) -> dict:
        return {
            "engine": self.engine_box.currentData(),
            "output_device": self.out_box.currentData(),
            "input_device": self.in_box.currentData(),
            "samplerate": self.sr_box.currentData(),
            "blocksize": self.bs_box.currentData(),
            "fft_size": self.fft_box.currentData(),
        }


class MainWindow(QWidget):
    NAV = (("♫", "Плеер"), ("●", "Запись"), ("◎", "Радио"),
           ("≈", "Генератор"), ("▦", "Визуализация"))

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.engine: Optional[AudioEngine] = None
        self.setObjectName("Root")
        self.setWindowTitle("Aurora Studio")
        self.resize(1180, 780)
        self._build_ui()
        self._create_engine(self.settings.get("engine"))

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        side = QWidget(); side.setObjectName("Sidebar"); side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 22, 16, 18); sl.setSpacing(6)

        logo = QLabel("AURORA"); logo.setObjectName("Logo")
        sub = QLabel("AUDIO STUDIO"); sub.setObjectName("LogoSub")
        sl.addWidget(logo); sl.addWidget(sub); sl.addSpacing(22)

        self.nav_buttons: list[QPushButton] = []
        for i, (glyph, name) in enumerate(self.NAV):
            btn = QPushButton(f"  {glyph}   {name}")
            btn.setObjectName("Nav"); btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._switch(idx))
            sl.addWidget(btn); self.nav_buttons.append(btn)

        sl.addStretch(1)
        self.engine_badge = QLabel("движок: —"); self.engine_badge.setObjectName("Badge")
        sl.addWidget(self.engine_badge); sl.addSpacing(6)
        btn_settings = QPushButton("⚙  Настройки"); btn_settings.setObjectName("Ghost")
        btn_settings.clicked.connect(self._open_settings)
        sl.addWidget(btn_settings)

        root.addWidget(side)

        self.stack = QStackedWidget()
        self.player = PlayerPage(self.settings)
        self.record = RecordPage(self.settings)
        self.radio = RadioPage(self.settings)
        self.generator = GeneratorPage(self.settings)
        self.visualizer = VisualizerPage(self.settings)
        for page in (self.player, self.record, self.radio, self.generator, self.visualizer):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)
        self.nav_buttons[0].setChecked(True)

    def _create_engine(self, name: str) -> None:
        if self.engine is not None:
            try:
                self.engine.shutdown(); self.engine.deleteLater()
            except Exception:
                pass
            self.engine = None
        try:
            self.engine = create_engine(name, self.settings)
        except AudioEngineError as exc:
            QMessageBox.warning(self, "Аудиодвижок", str(exc))
            if name != "sounddevice":
                self.engine = create_engine("sounddevice", self.settings)
                self.settings.set("engine", "sounddevice")
            else:
                raise
        self.engine_badge.setText(f"движок: {self.engine.name}")
        for page in (self.player, self.record, self.radio, self.generator, self.visualizer):
            page.bind_engine(self.engine)

    def _switch(self, index: int) -> None:
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    def _open_settings(self) -> None:
        if self.engine is None:
            return
        dlg = SettingsDialog(self.settings, self.engine, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.result_values()
        old_engine = self.settings.get("engine")
        old_out = self.settings.get("output_device")
        old_sr = self.settings.get("samplerate")
        for k, v in values.items():
            self.settings.set(k, v)
        self.settings.save()
        if (values["engine"] != old_engine or values["output_device"] != old_out or
                values["samplerate"] != old_sr):
            try:
                self._create_engine(values["engine"])
            except AudioEngineError as exc:
                QMessageBox.critical(self, "Ошибка", str(exc))

    def closeEvent(self, event) -> None:
        self.settings.save()
        if self.engine is not None:
            try:
                self.engine.shutdown()
            except Exception:
                pass
        if self.visualizer.analyzer is not None:
            self.visualizer.analyzer.stop()
        super().closeEvent(event)


# ===========================================================================
#                                  MAIN
# ===========================================================================
def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Aurora Studio")
    app.setOrganizationName("Aurora")
    apply_theme(app)

    settings = Settings()
    try:
        window = MainWindow(settings)
    except Exception as exc:
        QMessageBox.critical(None, "Ошибка запуска", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
