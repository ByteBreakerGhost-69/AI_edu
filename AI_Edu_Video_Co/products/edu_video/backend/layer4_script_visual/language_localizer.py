# products/edu_video/backend/layer4_script_visual/language_localizer.py
"""
LanguageLocalizer: translates adapted narration from English to the target
language, applying cultural adaptations and preserving educational accuracy.
Layer 2 always outputs English — this layer handles all localisation.
"""

import json

import structlog

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import SubjectEnum
from layer4_script_visual.difficulty_adapter import _call_llm_json
from layer4_script_visual.schemas import AdaptedScene, LocalizedScene

__all__ = ["LanguageLocalizer", "language_localizer", "SUPPORTED_LANGUAGES"]

logger = structlog.get_logger(__name__)

_TRANSLATE_PROMPT_TOKENS = 1500
_TRANSLATE_COMPLETION_TOKENS = 2000

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

SUPPORTED_LANGUAGES: dict[str, dict] = {
    "en": {"name": "English",              "tts_code": "en-US", "rtl": False},
    "id": {"name": "Indonesian",           "tts_code": "id-ID", "rtl": False},
    "es": {"name": "Spanish",              "tts_code": "es-ES", "rtl": False},
    "fr": {"name": "French",               "tts_code": "fr-FR", "rtl": False},
    "de": {"name": "German",               "tts_code": "de-DE", "rtl": False},
    "zh": {"name": "Chinese (Simplified)", "tts_code": "zh-CN", "rtl": False},
    "ar": {"name": "Arabic",               "tts_code": "ar-SA", "rtl": True},
    "ja": {"name": "Japanese",             "tts_code": "ja-JP", "rtl": False},
    "pt": {"name": "Portuguese",           "tts_code": "pt-BR", "rtl": False},
    "ko": {"name": "Korean",               "tts_code": "ko-KR", "rtl": False},
}

NEVER_TRANSLATE: dict[str, list[str]] = {
    "mathematics":      ["LaTeX", "theorem", "lemma", "corollary", "QED", "∀", "∃", "∈", "ℝ", "ℤ"],
    "computer_science": ["function", "class", "array", "API", "algorithm", "Boolean", "null", "int"],
    "chemistry":        ["DNA", "RNA", "ATP", "pH", "IUPAC"],
    "physics":          ["Newton", "Einstein", "Joule", "Watt", "Pascal", "Kelvin"],
    "biology":          ["DNA", "RNA", "ATP", "mRNA", "CRISPR"],
    "general":          ["IB", "Cambridge", "AP", "URL", "GCS", "PDF"],
}

CULTURAL_ADAPTATIONS: dict[str, dict[str, str]] = {
    "id": {
        "pizza":        "nasi goreng",
        "basketball":   "badminton",
        "dollars":      "rupiah",
        "New York":     "Jakarta",
        "Shakespeare":  "Pramoedya Ananta Toer",
        "supermarket":  "pasar",
    },
    "es": {
        "New York":     "Madrid",
        "dollars":      "euros",
        "yard":         "metro",
    },
    "ar": {
        "dollars":      "دولار",
        "New York":     "القاهرة",
    },
    "zh": {
        "New York":     "北京",
        "dollars":      "人民币",
        "Shakespeare":  "鲁迅",
    },
    "ja": {
        "New York":     "東京",
        "dollars":      "円",
        "Shakespeare":  "夏目漱石",
    },
}


# --------------------------------------------------------------------------- #
# LanguageLocalizer                                                            #
# --------------------------------------------------------------------------- #

class LanguageLocalizer:
    """
    Translates all scenes in one batched LLM call for cost efficiency.
    Falls back to original English text on any translation failure —
    never crashes the pipeline over a translation error.
    """

    def __init__(self) -> None:
        self.llm = llm_factory.get_llm().with_fallbacks(
            [llm_factory.get_llm("grok")]
        )
        self.log = structlog.get_logger(__name__)

    async def localize(
        self,
        scenes: list[AdaptedScene],
        target_language: str,
        subject: SubjectEnum,
        job_id: str,
    ) -> list[LocalizedScene]:
        """
        Localize all scenes to the target language.
        If target is "en", wraps AdaptedScenes directly (no LLM call).
        """
        log = self.log.bind(
            job_id=job_id,
            target_language=target_language,
            subject=subject,
            scene_count=len(scenes),
        )
        log.info("language_localizer.started")

        # English passthrough — no translation needed
        if target_language == "en":
            log.info("language_localizer.passthrough_english")
            return [_adapted_to_localized(scene, "en") for scene in scenes]

        # Validate language support
        if target_language not in SUPPORTED_LANGUAGES:
            log.warning(
                "language_localizer.unsupported_language",
                language=target_language,
                fallback="en",
            )
            return [_adapted_to_localized(scene, "en") for scene in scenes]

        # Batch translate
        return await self._batch_translate(scenes, target_language, subject, job_id, log)

    async def _batch_translate(
        self,
        scenes: list[AdaptedScene],
        target_language: str,
        subject: SubjectEnum,
        job_id: str,
        log,
    ) -> list[LocalizedScene]:
        """
        Translate all scenes in a single LLM call.
        Falls back to English on any failure.
        """
        lang_info = SUPPORTED_LANGUAGES[target_language]
        never_translate = (
            NEVER_TRANSLATE.get(subject.value, [])
            + NEVER_TRANSLATE["general"]
        )
        cultural_swaps = CULTURAL_ADAPTATIONS.get(target_language, {})

        rtl_instruction = (
            "7. Output text direction is right-to-left — ensure natural RTL sentence flow.\n"
            if lang_info["rtl"]
            else ""
        )

        system_prompt = (
            f"You are an expert educational translator specialising in {subject.value}.\n"
            f"Translate the following scenes from English to {lang_info['name']}.\n\n"
            "=== TRANSLATION RULES ===\n"
            "1. Preserve educational accuracy above all else.\n"
            f"2. Use natural, educational {lang_info['name']} — not word-for-word literal.\n"
            f"3. Keep these terms in their original English form: {json.dumps(never_translate)}\n"
            f"4. Apply these cultural adaptations where appropriate: {json.dumps(cultural_swaps)}\n"
            "5. For mathematical/scientific notation: keep symbols, translate surrounding text.\n"
            "6. Maintain the same tone and difficulty level as the original.\n"
            f"{rtl_instruction}"
            "\n=== OUTPUT FORMAT ===\n"
            f"Return a JSON object with exactly {len(scenes)} translated scenes.\n"
            "{\n"
            '  "translated_scenes": [\n'
            "    {\n"
            '      "scene_index": 0,\n'
            '      "title": "translated title",\n'
            '      "narration_text": "translated narration",\n'
            '      "visual_description": "translated visual description",\n'
            '      "translation_notes": ["cultural adaptation made", ...],\n'
            '      "untranslated_terms": ["term kept in English", ...]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "No markdown. No prose outside the JSON."
        )

        scenes_payload = [
            {
                "scene_index": s.scene_index,
                "title": s.title,
                "narration_text": s.narration_text,
                "visual_description": s.visual_description,
            }
            for s in scenes
        ]

        user_prompt = (
            f"Translate these {len(scenes)} educational {subject.value} scenes:\n\n"
            f"{json.dumps(scenes_payload, ensure_ascii=False, indent=2)}"
        )

        raw = await _call_llm_json(
            llm=self.llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_keys=["translated_scenes"],
            log=self.log.bind(job_id=job_id),
        )

        translated_list = raw.get("translated_scenes")

        if not translated_list or not isinstance(translated_list, list):
            log.error(
                "language_localizer.translation_failed_using_english",
                reason="LLM returned no translated_scenes",
            )
            return [
                _adapted_to_localized(
                    scene,
                    "en",
                    notes=["translation_failed_using_english_fallback"],
                )
                for scene in scenes
            ]

        # Build lookup by scene_index for O(1) merge
        translation_map: dict[int, dict] = {}
        for entry in translated_list:
            if isinstance(entry, dict):
                idx = entry.get("scene_index")
                if idx is not None:
                    try:
                        translation_map[int(idx)] = entry
                    except (TypeError, ValueError):
                        pass

        localized: list[LocalizedScene] = []
        for scene in scenes:
            match = translation_map.get(scene.scene_index)
            if match is None:
                log.warning(
                    "language_localizer.missing_translation_for_scene",
                    scene_index=scene.scene_index,
                )
                localized.append(
                    _adapted_to_localized(
                        scene,
                        "en",
                        notes=["scene_translation_missing_using_english"],
                    )
                )
                continue

            localized.append(LocalizedScene(
                scene_index=scene.scene_index,
                title=str(match.get("title") or scene.title),
                narration_text=str(match.get("narration_text") or scene.narration_text),
                visual_description=str(match.get("visual_description") or scene.visual_description),
                renderer_type=scene.renderer_type,
                duration_seconds=scene.duration_seconds,
                render_metadata=scene.render_metadata,
                source_language="en",
                target_language=target_language,
                translation_notes=[
                    str(n) for n in (match.get("translation_notes") or [])
                    if isinstance(n, str)
                ],
                untranslated_terms=[
                    str(t) for t in (match.get("untranslated_terms") or [])
                    if isinstance(t, str)
                ],
            ))

        localized.sort(key=lambda s: s.scene_index)
        log.info(
            "language_localizer.completed",
            scenes_translated=len(localized),
            target_language=target_language,
        )
        return localized

    def get_tts_language_code(self, language: str) -> str:
        """Return BCP-47 TTS code for the given language."""
        return SUPPORTED_LANGUAGES.get(language, SUPPORTED_LANGUAGES["en"])["tts_code"]

    def is_rtl(self, language: str) -> bool:
        """Return True if the language is right-to-left."""
        return SUPPORTED_LANGUAGES.get(language, {}).get("rtl", False)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _adapted_to_localized(
    scene: AdaptedScene,
    language: str,
    notes: list[str] | None = None,
) -> LocalizedScene:
    """Wrap an AdaptedScene as a LocalizedScene without translation."""
    return LocalizedScene(
        scene_index=scene.scene_index,
        title=scene.title,
        narration_text=scene.narration_text,
        visual_description=scene.visual_description,
        renderer_type=scene.renderer_type,
        duration_seconds=scene.duration_seconds,
        render_metadata=scene.render_metadata,
        source_language="en",
        target_language=language,
        translation_notes=notes or [],
        untranslated_terms=[],
    )


language_localizer = LanguageLocalizer()
