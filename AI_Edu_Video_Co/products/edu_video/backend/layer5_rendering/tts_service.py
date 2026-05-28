# products/edu_video/backend/layer5_rendering/tts_service.py
"""
TTSService: converts SSML narration to MP3 audio files using Google Cloud TTS.
One audio file per scene, written to /tmp/edu_video/{job_id}/audio/.

Cost model: Google Neural2 voices = $16 per 1M characters.
Fallback: FFmpeg-generated silence when TTS fails, so compositor never blocks.
"""

import asyncio
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import structlog
from google.cloud import texttospeech
from pydantic import BaseModel

from core.config import get_settings
from core.cost_tracker import CostTracker
from layer4_script_visual.schemas import FinalScenePackage, RefinedScript, TTSInstructions

__all__ = ["TTSService", "TTSRequest", "TTSResult", "tts_service"]

logger = structlog.get_logger(__name__)
settings = get_settings()

_MAX_CONCURRENT_TTS = 3
_RETRY_ATTEMPTS = 3
_NEURAL2_COST_PER_CHAR = 16.0 / 1_000_000  # $16 per 1M chars

# --------------------------------------------------------------------------- #
# Voice configuration                                                          #
# --------------------------------------------------------------------------- #

_PITCH_MAP: dict[str, float] = {
    "low":    -2.0,
    "medium":  0.0,
    "high":    2.0,
}

# Language code → Google TTS voice config
# Built at module level after settings are loaded so VOICE_MAP is a plain dict
def _build_voice_map() -> dict[str, dict]:
    return {
        "en-US": {
            "name": settings.GOOGLE_TTS_VOICE_EN,
            "gender": texttospeech.SsmlVoiceGender.MALE,
        },
        "id-ID": {
            "name": settings.GOOGLE_TTS_VOICE_ID,
            "gender": texttospeech.SsmlVoiceGender.FEMALE,
        },
        "es-ES": {"name": "es-ES-Neural2-B",   "gender": texttospeech.SsmlVoiceGender.MALE},
        "fr-FR": {"name": "fr-FR-Neural2-B",   "gender": texttospeech.SsmlVoiceGender.MALE},
        "de-DE": {"name": "de-DE-Neural2-B",   "gender": texttospeech.SsmlVoiceGender.MALE},
        "zh-CN": {"name": "cmn-CN-Standard-B", "gender": texttospeech.SsmlVoiceGender.MALE},
        "ar-XA": {"name": "ar-XA-Standard-B",  "gender": texttospeech.SsmlVoiceGender.MALE},
        "ja-JP": {"name": "ja-JP-Neural2-C",   "gender": texttospeech.SsmlVoiceGender.MALE},
        "pt-BR": {"name": "pt-BR-Neural2-B",   "gender": texttospeech.SsmlVoiceGender.MALE},
        "ko-KR": {"name": "ko-KR-Neural2-B",   "gender": texttospeech.SsmlVoiceGender.MALE},
    }


# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #

class TTSRequest(BaseModel):
    scene_index: int
    narration_ssml: str
    tts_instructions: TTSInstructions
    job_id: str


class TTSResult(BaseModel):
    scene_index: int
    audio_file_path: str
    duration_seconds: float
    file_size_bytes: int
    cost_usd: float
    language_code: str
    success: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# TTSService                                                                   #
# --------------------------------------------------------------------------- #

class TTSService:
    """
    Google Cloud TTS wrapper.
    Synthesizes all scenes concurrently (max 3 — Google rate limit).
    Falls back to FFmpeg silence on per-scene failure so the pipeline never stalls.
    """

    def __init__(self) -> None:
        self._client: texttospeech.TextToSpeechAsyncClient | None = None
        self._voice_map = _build_voice_map()
        self.log = structlog.get_logger(__name__)

    def _get_client(self) -> texttospeech.TextToSpeechAsyncClient:
        """Lazy-init client — avoids credentials error at import time."""
        if self._client is None:
            self._client = texttospeech.TextToSpeechAsyncClient()
        return self._client

    async def synthesize_all(
        self,
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> list[TTSResult]:
        """
        Synthesize TTS audio for all scenes concurrently.
        Returns list sorted by scene_index with silence fallback for failures.
        """
        log = self.log.bind(job_id=job_id, scene_count=len(packages))
        log.info("tts_service.started")

        audio_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_TTS)

        async def _synthesize_one(pkg: FinalScenePackage) -> TTSResult:
            async with semaphore:
                return await self._synthesize_scene(pkg.refined_script, job_id, audio_dir)

        raw_results = await asyncio.gather(
            *[_synthesize_one(pkg) for pkg in packages],
            return_exceptions=True,
        )

        results: list[TTSResult] = []
        for pkg, outcome in zip(packages, raw_results):
            if isinstance(outcome, Exception):
                log.error(
                    "tts_service.scene_failed",
                    scene_index=pkg.scene_index,
                    error=str(outcome),
                )
                silence_path = await self._generate_silence(
                    pkg.estimated_duration_seconds, audio_dir, pkg.scene_index
                )
                results.append(TTSResult(
                    scene_index=pkg.scene_index,
                    audio_file_path=str(silence_path),
                    duration_seconds=pkg.estimated_duration_seconds,
                    file_size_bytes=silence_path.stat().st_size if silence_path.exists() else 0,
                    cost_usd=0.0,
                    language_code=pkg.refined_script.tts_instructions.language_code,
                    success=False,
                    error=str(outcome),
                ))
            else:
                results.append(outcome)

        results.sort(key=lambda r: r.scene_index)
        total_cost = sum(r.cost_usd for r in results)
        log.info(
            "tts_service.completed",
            total_cost_usd=total_cost,
            failed=sum(1 for r in results if not r.success),
        )
        return results

    async def _synthesize_scene(
        self,
        script: RefinedScript,
        job_id: str,
        audio_dir: Path,
    ) -> TTSResult:
        """
        Synthesize a single scene with exponential backoff retry.
        Validates SSML before sending — invalid SSML causes TTS to reject the request.
        """
        log = self.log.bind(job_id=job_id, scene_index=script.scene_index)

        lang_code = script.tts_instructions.language_code
        voice_config = self._voice_map.get(lang_code, self._voice_map["en-US"])

        ssml = self._validate_ssml(script.narration_ssml)
        char_count = len(ssml)

        synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=voice_config["name"],
            ssml_gender=voice_config["gender"],
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=script.tts_instructions.speaking_rate,
            pitch=_PITCH_MAP.get(script.tts_instructions.pitch, 0.0),
        )

        client = self._get_client()
        last_exc: Exception | None = None

        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                response = await client.synthesize_speech(
                    input=synthesis_input,
                    voice=voice,
                    audio_config=audio_config,
                )
                break
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "tts_service.retry",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < _RETRY_ATTEMPTS:
                    await asyncio.sleep(2 ** (attempt - 1))
        else:
            raise RuntimeError(
                f"TTS failed after {_RETRY_ATTEMPTS} attempts: {last_exc}"
            ) from last_exc

        audio_path = audio_dir / f"scene_{script.scene_index:02d}.mp3"
        audio_path.write_bytes(response.audio_content)

        # Measure actual duration using mutagen
        actual_duration = _get_mp3_duration(audio_path, fallback=float(char_count / 15))

        cost_usd = char_count * _NEURAL2_COST_PER_CHAR

        log.info(
            "tts_service.scene_synthesized",
            duration_seconds=actual_duration,
            char_count=char_count,
            cost_usd=cost_usd,
        )

        return TTSResult(
            scene_index=script.scene_index,
            audio_file_path=str(audio_path),
            duration_seconds=actual_duration,
            file_size_bytes=audio_path.stat().st_size,
            cost_usd=cost_usd,
            language_code=lang_code,
            success=True,
        )

    def _validate_ssml(self, ssml: str) -> str:
        """
        Attempt to parse SSML as XML. If invalid, strip all tags and
        re-wrap in a clean <speak> block to prevent TTS API rejection.
        """
        try:
            ET.fromstring(ssml)
            return ssml
        except ET.ParseError:
            clean = re.sub(r"<[^>]+>", "", ssml).strip()
            return f"<speak>{clean}</speak>"

    async def _generate_silence(
        self,
        duration: float,
        audio_dir: Path,
        scene_index: int,
    ) -> Path:
        """
        Generate a silent MP3 using FFmpeg as a TTS fallback.
        Runs in a thread pool so we don't block the event loop.
        """
        import ffmpeg  # noqa: PLC0415

        path = audio_dir / f"scene_{scene_index:02d}_silence.mp3"

        def _run() -> None:
            (
                ffmpeg
                .input("anullsrc=r=44100:cl=stereo", f="lavfi", t=duration)
                .output(str(path), acodec="libmp3lame", q=4)
                .overwrite_output()
                .run(quiet=True)
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)
        return path


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _get_mp3_duration(path: Path, fallback: float) -> float:
    """Return MP3 duration in seconds using mutagen. Falls back on any error."""
    try:
        from mutagen.mp3 import MP3  # noqa: PLC0415
        return float(MP3(str(path)).info.length)
    except Exception:
        return fallback


tts_service = TTSService()
