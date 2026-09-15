"""Voice AI agent pipeline for testing.

Transport : Daily (WebRTC)
STT       : Deepgram (nova-2)
LLM       : Google Gemini (gemini-2.0-flash)
TTS       : Deepgram (aura)

Required env vars:
    DAILY_API_KEY        - Daily REST API key (creates rooms on the fly)
    DEEPGRAM_API_KEY     - Deepgram API key (STT + TTS)
    GOOGLE_API_KEY       - Google Gemini API key

Optional env vars:
    DAILY_ROOM_URL       - Reuse an existing Daily room instead of creating one
    DAILY_ROOM_EXPIRY    - Seconds until the auto-created room expires (default 3600)
    GEMINI_MODEL         - LLM model id (default: gemini-2.0-flash)
    DEEPGRAM_STT_MODEL   - STT model (default: nova-2-general)
    DEEPGRAM_TTS_VOICE   - TTS voice (default: aura-asteria-en)
    AGENT_SYSTEM_PROMPT  - System prompt for the assistant
"""

import asyncio
import os
from dataclasses import dataclass, field

import aiohttp
from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.daily.transport import DailyParams, DailyTransport

load_dotenv()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly voice assistant being tested over a phone-like call. "
    "Keep your answers short and conversational (1-2 sentences). "
    "Do not use markdown, emojis, or special characters since your output "
    "will be spoken aloud."
)


@dataclass
class AgentConfig:
    """Runtime configuration for the voice agent pipeline."""

    daily_api_key: str = field(
        default_factory=lambda: os.environ.get("DAILY_API_KEY", "")
    )
    deepgram_api_key: str = field(
        default_factory=lambda: os.environ.get("DEEPGRAM_API_KEY", "")
    )
    google_api_key: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_API_KEY", "")
    )

    room_url: str = field(default_factory=lambda: os.getenv("DAILY_ROOM_URL", ""))
    room_expiry_seconds: int = field(
        default_factory=lambda: int(os.getenv("DAILY_ROOM_EXPIRY", "3600"))
    )

    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    )
    deepgram_stt_model: str = field(
        default_factory=lambda: os.getenv("DEEPGRAM_STT_MODEL", "nova-2-general")
    )
    deepgram_tts_voice: str = field(
        default_factory=lambda: os.getenv("DEEPGRAM_TTS_VOICE", "aura-asteria-en")
    )

    system_prompt: str = field(
        default_factory=lambda: os.getenv("AGENT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
    )

    def validate(self) -> None:
        missing = []
        if not self.deepgram_api_key:
            missing.append("DEEPGRAM_API_KEY")
        if not self.google_api_key:
            missing.append("GOOGLE_API_KEY")
        if not self.room_url and not self.daily_api_key:
            missing.append("DAILY_API_KEY (or DAILY_ROOM_URL)")
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


# --------------------------------------------------------------------------- #
# Daily room helpers
# --------------------------------------------------------------------------- #

async def create_daily_room(config: AgentConfig):
    """Create an expiring Daily room + owner meeting token via the REST API.

    Returns (room_url, token). Skipped entirely when DAILY_ROOM_URL is set.
    """
    if config.room_url:
        logger.info(f"Using existing Daily room: {config.room_url}")
        return config.room_url, ""

    import time

    headers = {
        "Authorization": f"Bearer {config.daily_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "properties": {
            "exp": int(time.time()) + config.room_expiry_seconds,
            "enable_chat": False,
            "enable_emoji_reactions": False,
            "eject_at_room_exp": True,
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.daily.co/v1/rooms", headers=headers, json=payload
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Daily room creation failed ({resp.status}): {body}")
            data = await resp.json()
            room_url: str = data["url"]
            logger.info(f"Created Daily room: {room_url}")

        # Owner token so the bot can join (and optionally record/transcribe)
        token_payload = {
            "properties": {
                "room_name": room_url.rsplit("/", 1)[-1],
                "is_owner": True,
            }
        }
        async with session.post(
            "https://api.daily.co/v1/meeting-tokens",
            headers=headers,
            json=token_payload,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Daily meeting-token creation failed ({resp.status}): {body}"
                )
            token = (await resp.json())["token"]

    return room_url, token


# --------------------------------------------------------------------------- #
# Pipeline construction
# --------------------------------------------------------------------------- #

def build_services(config: AgentConfig):
    """Instantiate STT / LLM / TTS services."""
    stt = DeepgramSTTService(
        api_key=config.deepgram_api_key,
        model=config.deepgram_stt_model,
        language=Language.EN,
    )

    llm = GoogleLLMService(
        api_key=config.google_api_key,
        model=config.gemini_model,
    )

    tts = DeepgramTTSService(
        api_key=config.deepgram_api_key,
        voice=config.deepgram_tts_voice,
    )

    return stt, llm, tts


async def run_pipeline(config: AgentConfig) -> None:
    """Build and run the Daily voice agent pipeline until the call ends."""
    config.validate()

    room_url, token = await create_daily_room(config)
    print(room_url)

    transport = DailyTransport(
        room_url,
        token or None,
        "HOM Voice Test Agent",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=16_000,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            transcription_enabled=False,  # Deepgram STT handles transcription
        ),
    )

    stt, llm, tts = build_services(config)

    messages = [{"role": "system", "content": config.system_prompt}]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),               # audio in from Daily
            stt,                             # Deepgram STT
            context_aggregator.user(),       # collect user turns
            llm,                             # Gemini LLM
            tts,                             # Deepgram TTS
            transport.output(),              # audio out to Daily
            context_aggregator.assistant(),  # collect assistant turns
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info(f"Participant joined: {participant['id']}")
        await transport.capture_participant_transcription(participant["id"])
        # Greet the first participant
        messages.append(
            {
                "role": "system",
                "content": (
                    "Greet the caller briefly and ask how you can help them today."
                ),
            }
        )
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']} ({reason})")
        await task.queue_frame(EndFrame())

    runner = PipelineRunner(handle_sigint=True)
    logger.info("Starting pipeline runner…")
    await runner.run(task)


async def main() -> None:
    config = AgentConfig()
    await run_pipeline(config)


if __name__ == "__main__":
    asyncio.run(main())
