"""Voice input handler – record from mic → transcribe via Foundry Local Whisper."""

from __future__ import annotations

import io
import os
import tempfile
import time
import wave
from typing import Any, Dict, Optional

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

# ── Cached Whisper pipeline (loaded once, reused) ────────────────
_whisper_cache: Dict[str, Any] = {}


def _get_whisper_pipeline(whisper_alias: str) -> Optional[Dict[str, Any]]:
    """Return a cached Whisper pipeline (encoder, decoder, tokenizer, etc.).

    Loads ONNX sessions + tokenizer on first call only.  Subsequent calls
    return the cached instances, saving ~10-15 s of startup per request.
    """
    if whisper_alias in _whisper_cache:
        return _whisper_cache[whisper_alias]

    try:
        import numpy as np
        import onnxruntime as ort
        import librosa
        from transformers import WhisperFeatureExtractor, WhisperTokenizer
        from foundry_local import FoundryLocalManager
    except ImportError as exc:
        print(
            f"[voice] missing dependency for Whisper transcription: {exc}\n"
            "  → pip install foundry-local-sdk onnxruntime transformers librosa numpy"
        )
        return None

    t0 = time.perf_counter()
    try:
        manager = FoundryLocalManager(whisper_alias)
        model_info = manager.get_model_info(whisper_alias)
        cache_location = manager.get_cache_location()
    except Exception as exc:
        print(f"[voice] failed to load Whisper model via Foundry Local: {exc}")
        return None

    model_parent = os.path.join(
        cache_location, "Microsoft",
        model_info.id.replace(":", "-"),
    )

    # Find the first available variant directory (cuda-fp16, cpu-fp32, etc.)
    model_dir = None
    if os.path.isdir(model_parent):
        # Prefer cuda-fp16 > cpu-fp32 > cpu-fp16 > any
        for variant in ["cuda-fp16", "cpu-fp32", "cpu-fp16"]:
            candidate = os.path.join(model_parent, variant)
            if os.path.isdir(candidate):
                model_dir = candidate
                break
        if model_dir is None:
            # Fall back to first subdirectory that contains .onnx files
            for entry in os.listdir(model_parent):
                candidate = os.path.join(model_parent, entry)
                if os.path.isdir(candidate) and any(
                    f.endswith(".onnx") for f in os.listdir(candidate)
                ):
                    model_dir = candidate
                    break

    if model_dir is None:
        print(f"[voice] no ONNX model directory found under {model_parent}")
        return None

    print(f"[voice] using model dir: {model_dir}")

    encoder_path = decoder_path = None
    for fname in os.listdir(model_dir):
        if fname.endswith(".onnx"):
            lower = fname.lower()
            if "encoder" in lower:
                encoder_path = os.path.join(model_dir, fname)
            elif "decoder" in lower:
                decoder_path = os.path.join(model_dir, fname)

    if not encoder_path or not decoder_path:
        print(f"[voice] ONNX files not found in {model_dir}")
        return None

    # Prefer GPU if available, fall back to CPU
    providers = ort.get_available_providers()
    ep = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in providers else ["CPUExecutionProvider"]

    try:
        encoder_session = ort.InferenceSession(encoder_path, providers=ep)
        decoder_session = ort.InferenceSession(decoder_path, providers=ep)
    except Exception as exc:
        print(f"[voice] failed to load ONNX sessions: {exc}")
        return None

    try:
        feature_extractor = WhisperFeatureExtractor.from_pretrained(model_dir)
        tokenizer = WhisperTokenizer.from_pretrained(model_dir)
    except Exception as exc:
        print(f"[voice] failed to load tokenizer/feature extractor: {exc}")
        return None

    # Detect model dimensions from encoder output
    # whisper-medium: 24 layers, 16 heads, 64 head_size
    # whisper-small:  12 layers, 12 heads, 64 head_size
    # whisper-base:    6 layers,  8 heads, 64 head_size
    # whisper-tiny:    4 layers,  6 heads, 64 head_size
    alias_lower = whisper_alias.lower()
    if "medium" in alias_lower or "large" in alias_lower:
        num_layers, num_heads = 24, 16
    elif "small" in alias_lower:
        num_layers, num_heads = 12, 12
    elif "base" in alias_lower:
        num_layers, num_heads = 6, 8
    else:  # tiny
        num_layers, num_heads = 4, 6

    sot = tokenizer.convert_tokens_to_ids("<|startoftranscript|>")
    eot = tokenizer.convert_tokens_to_ids("<|endoftext|>")
    notimestamps = tokenizer.convert_tokens_to_ids("<|notimestamps|>")
    forced_ids = tokenizer.get_decoder_prompt_ids(language="en", task="transcribe")
    initial_tokens = [sot] + [tid for _, tid in forced_ids] + [notimestamps]

    # Detect precision from the variant directory name
    is_fp16 = "fp16" in model_dir.lower()
    float_dtype = np.float16 if is_fp16 else np.float32
    print(f"[voice] model precision: {'fp16' if is_fp16 else 'fp32'}", flush=True)

    pipeline = {
        "encoder": encoder_session,
        "decoder": decoder_session,
        "feature_extractor": feature_extractor,
        "tokenizer": tokenizer,
        "num_layers": num_layers,
        "num_heads": num_heads,
        "head_size": 64,
        "initial_tokens": initial_tokens,
        "eot": eot,
        "dtype": float_dtype,
    }
    _whisper_cache[whisper_alias] = pipeline
    dt = time.perf_counter() - t0
    print(f"[voice] Whisper pipeline loaded in {dt:.1f}s (cached for reuse)")
    return pipeline


def record_audio(seconds: float = 5.0) -> Optional[str]:
    """Record *seconds* of audio from the default mic and save to a temp WAV.

    Returns the path to the WAV file, or None on failure.
    """
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print(
            "[voice] 'sounddevice' is required for voice mode.\n"
            "  → pip install sounddevice"
        )
        return None

    print(f"[voice] 🎤  Recording for {seconds}s – speak now …")
    try:
        audio = sd.rec(
            int(seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
        )
        sd.wait()
    except Exception as exc:
        print(f"[voice] recording failed: {exc}")
        return None

    print("[voice] recording complete.")

    # Write WAV to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
    except Exception as exc:
        print(f"[voice] failed to write WAV: {exc}")
        return None

    return tmp.name


def transcribe_audio_foundry(wav_path: str, whisper_alias: str = "whisper-medium") -> Optional[str]:
    """Transcribe *wav_path* using the cached Foundry Local Whisper pipeline."""
    import numpy as np
    import librosa

    pipeline = _get_whisper_pipeline(whisper_alias)
    if pipeline is None:
        return None

    t0 = time.perf_counter()

    encoder = pipeline["encoder"]
    decoder = pipeline["decoder"]
    fe = pipeline["feature_extractor"]
    tokenizer = pipeline["tokenizer"]
    NL = pipeline["num_layers"]
    NH = pipeline["num_heads"]
    HS = pipeline["head_size"]
    initial_tokens = pipeline["initial_tokens"]
    eot = pipeline["eot"]
    dtype = pipeline["dtype"]

    audio, _ = librosa.load(wav_path, sr=16000)
    features = fe(audio, sampling_rate=16000, return_tensors="np")
    audio_features = features["input_features"].astype(dtype)

    # Encoder pass
    encoder_outputs = encoder.run(None, {"audio_features": audio_features})
    cross_kv_list = encoder_outputs[1:]

    cross_kv = {}
    for i in range(NL):
        cross_kv[f"past_key_cross_{i}"] = cross_kv_list[i * 2]
        cross_kv[f"past_value_cross_{i}"] = cross_kv_list[i * 2 + 1]

    self_kv = {}
    for i in range(NL):
        self_kv[f"past_key_self_{i}"] = np.zeros((1, NH, 0, HS), dtype=dtype)
        self_kv[f"past_value_self_{i}"] = np.zeros((1, NH, 0, HS), dtype=dtype)

    input_ids = np.array([initial_tokens], dtype=np.int32)
    generated = []

    # Robot commands are short — cap at 128 tokens (vs 448 default)
    for _ in range(128):
        feeds = {"input_ids": input_ids}
        feeds.update(cross_kv)
        feeds.update(self_kv)

        outputs = decoder.run(None, feeds)
        logits = outputs[0]
        next_token = int(np.argmax(logits[0, -1, :]))

        if next_token == eot:
            break

        generated.append(next_token)

        for i in range(NL):
            self_kv[f"past_key_self_{i}"] = outputs[1 + i * 2]
            self_kv[f"past_value_self_{i}"] = outputs[2 + i * 2]

        input_ids = np.array([[next_token]], dtype=np.int32)

    text = tokenizer.decode(generated, skip_special_tokens=True).strip()
    dt = time.perf_counter() - t0
    print(f"[voice] transcription ({dt:.1f}s): \"{text}\"")
    return text


def get_voice_command(
    record_seconds: float = 5.0,
    whisper_alias: str = "whisper-medium",
) -> Optional[str]:
    """Record audio and transcribe to text. Returns the transcribed command."""
    wav_path = record_audio(record_seconds)
    if wav_path is None:
        return None
    try:
        return transcribe_with_chunking(wav_path, whisper_alias)
    finally:
        # Clean up temp file
        try:
            os.unlink(wav_path)
        except OSError:
            pass


# ── Chunking for long audio ──────────────────────────────────────

WHISPER_MAX_SECONDS = 30  # Whisper's max segment length


def transcribe_with_chunking(
    wav_path: str,
    whisper_alias: str = "whisper-medium",
    max_chunk_seconds: float = WHISPER_MAX_SECONDS,
) -> Optional[str]:
    """Transcribe audio, chunking into ≤30 s segments if needed.

    Whisper can only handle 30-second segments.  For longer audio,
    we split into chunks and concatenate the results.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        return transcribe_audio_foundry(wav_path, whisper_alias)

    audio, sr = librosa.load(wav_path, sr=SAMPLE_RATE)
    duration = len(audio) / sr

    # Short audio → direct transcription
    if duration <= max_chunk_seconds:
        return transcribe_audio_foundry(wav_path, whisper_alias)

    # Split into chunks
    chunk_samples = int(max_chunk_seconds * sr)
    chunks = [audio[i:i + chunk_samples] for i in range(0, len(audio), chunk_samples)]
    print(f"[voice] audio is {duration:.1f}s – splitting into {len(chunks)} chunk(s)")

    import tempfile
    import wave

    transcripts: list[str] = []
    for idx, chunk in enumerate(chunks):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((chunk * 32767).astype(np.int16).tobytes())
            text = transcribe_audio_foundry(tmp.name, whisper_alias)
            if text:
                transcripts.append(text)
                print(f"[voice] chunk {idx + 1}/{len(chunks)}: \"{text}\"")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    return " ".join(transcripts) if transcripts else None
