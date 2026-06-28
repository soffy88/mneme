from pathlib import Path
import tempfile
import uuid
import logging
from typing import Any
from obase.provider_registry import ProviderRegistry
from omodul.speaking_practice_workflow import speaking_practice_workflow, Config, InputData
from services.anon import anon_ref

logger = logging.getLogger(__name__)

async def wrap_tts(text: str, language: str = "en", voice: str = "default") -> str:
    from oprim import text_to_speech
    return await text_to_speech(text=text, language=language, voice=voice, provider="default")

async def wrap_stt(audio_b64: str, language: str = "en") -> str:
    from oprim import speech_to_text
    return await speech_to_text(audio_b64=audio_b64, language=language, provider="default")

async def wrap_pron(audio_b64: str, reference_text: str) -> Any:
    from oprim import evaluate_pronunciation
    return await evaluate_pronunciation(audio_b64=audio_b64, reference_text=reference_text, provider="default")

async def handle_speaking_practice(pool, student_id, topic, target_sentences, grade):
    """装配层：调 omodul.speaking_practice_workflow（只算），服务层用真实 id 落库（3O 边界）。"""
    config = Config(max_turns=5)

    # 结合 target_sentences 和 grade 形成完整的主题描述，引导 LLM
    full_topic = f"Topic: {topic} | Target Sentences: {target_sentences} | Grade: {grade}"

    llm_caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    input_data = InputData(
        topic=full_topic,
        # omodul 仅用于算 + 指纹/轨迹 → 传伪名（不接触真实 student_id）
        user_id=anon_ref(student_id),
        tts=wrap_tts,
        stt=wrap_stt,
        pronunciation_eval=wrap_pron,
        llm_caller=llm_caller,
    )

    output_dir = Path(tempfile.gettempdir()) / "mneme" / "speaking" / uuid.uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=True)

    result = await speaking_practice_workflow(
        config=config,
        input_data=input_data,
        output_dir=output_dir,
    )

    # 服务层持久化（业务主键用真实 student_id；持久化是服务层职责，不在 omodul）
    if result.get("status") == "completed" and result.get("session_id"):
        import json
        from obase.persistence import insert_one
        turns = result.get("turns")
        pron = result.get("pronunciation_scores")
        await insert_one(pool, table="speaking_sessions", data={
            "id": result["session_id"],
            "student_id": str(student_id),
            "topic": full_topic,
            "turns": json.dumps(turns) if isinstance(turns, (list, dict)) else turns,
            "pronunciation_scores": json.dumps(pron) if isinstance(pron, (list, dict)) else pron,
            "overall_progress": result.get("overall_progress"),
        })
    return result
