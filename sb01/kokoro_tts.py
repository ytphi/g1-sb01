"""
Offline TTS for sb01: Kokoro-82M (ONNX, CPU) on the laptop, the backup voice when edge-tts
(Microsoft's online voices) is unreachable. About 5x faster than real time on the laptop CPU,
so a sentence is ready well before the previous one finishes playing.

English and Spanish go through Kokoro's built-in espeak phonemizer. Chinese needs misaki's
G2P instead (espeak's Mandarin comes out unintelligible).

Model files (~350 MB) live in ~/.cache/kokoro-onnx:
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

Standalone check (writes a 16 kHz wav, no robot needed):
  python3 sb01/kokoro_tts.py "Hi, I'm Yotie." out.wav
"""

import os

import numpy as np
from pydub import AudioSegment

MODEL_DIR = os.path.expanduser("~/.cache/kokoro-onnx")
MODEL     = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
VOICES    = os.path.join(MODEL_DIR, "voices-v1.0.bin")
VOICE = {             # lang → (Kokoro voice, espeak language); female voices, like the edge-tts ones
    "en": ("af_heart", "en-us"),
    "es": ("ef_dora", "es"),
    "zh": ("zf_xiaoxiao", None),    # phonemized by misaki, not espeak
}


class KokoroTTS:
    def __init__(self):
        """Load the model (under a second). Raises if the model files or packages are missing."""
        from kokoro_onnx import Kokoro
        self.kokoro = Kokoro(MODEL, VOICES)
        self._zh_g2p = None

    def synthesize(self, text: str, lang: str, sample_rate: int = 16000) -> bytes:
        """Mono int16 PCM at sample_rate for one sentence; lang is "en", "zh" or "es"."""
        voice, espeak_lang = VOICE.get(lang, VOICE["en"])
        if lang == "zh":
            if self._zh_g2p is None:
                from misaki import zh
                self._zh_g2p = zh.ZHG2P()
            phonemes, _ = self._zh_g2p(text)
            samples, sr = self.kokoro.create(phonemes, voice=voice, is_phonemes=True)
        else:
            samples, sr = self.kokoro.create(text, voice=voice, lang=espeak_lang)
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
        audio = AudioSegment(data=pcm, sample_width=2, frame_rate=sr, channels=1)
        return audio.set_frame_rate(sample_rate).raw_data


if __name__ == "__main__":
    import sys
    import time
    import wave
    text = sys.argv[1] if len(sys.argv) > 1 else "Hi, I'm Yotie. Nice to meet you!"
    out = sys.argv[2] if len(sys.argv) > 2 else "kokoro_test.wav"
    lang = "zh" if any('一' <= c <= '鿿' for c in text) else "en"
    tts = KokoroTTS()
    t = time.time()
    pcm = tts.synthesize(text, lang)
    print(f"[kokoro] {len(pcm) / 32000:.1f}s of audio in {time.time() - t:.2f}s → {out}")
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(pcm)
