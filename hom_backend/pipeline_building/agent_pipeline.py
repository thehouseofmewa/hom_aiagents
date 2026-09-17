"""Voice AI agent pipeline for testing.

Transport : FastAPI WebSocket
STT       : Deepgram (nova-2)
LLM       : Google Gemini (gemini-2.0-flash)
TTS       : Deepgram (aura)

Required env vars:
    DEEPGRAM_API_KEY     - Deepgram API key (STT + TTS)
    GOOGLE_API_KEY       - Google Gemini API key

Optional env vars:
    GEMINI_MODEL         - LLM model id (default: gemini-2.0-flash)
    DEEPGRAM_STT_MODEL   - STT model (default: nova-2-general)
    DEEPGRAM_TTS_VOICE   - TTS voice (default: aura-asteria-en)
    AGENT_SYSTEM_PROMPT  - System prompt for the assistant
"""

import asyncio
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from fastapi import WebSocket

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

    deepgram_api_key: str = field(
        default_factory=lambda: os.environ.get("DEEPGRAM_API_KEY", "")
    )
    google_api_key: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_API_KEY", "")
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
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


# --------------------------------------------------------------------------- #
# WebSocket transport
# --------------------------------------------------------------------------- #


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


async def run_pipeline(
    config: AgentConfig,
    websocket: WebSocket,
) -> None:
    """Build and run one WebSocket voice-agent session."""
    config.validate()

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            add_wav_header=False,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    stt, llm, tts = build_services(config)

    messages = [{"role": "system", "content": config.system_prompt}]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
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

    runner = PipelineRunner(handle_sigint=False)

    @task.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("Pipecat WebSocket client ready")
        await rtvi.set_bot_ready()
        messages.append(
            {
                "role": "system",
                "content": "Greet the caller briefly and ask how you can help them today.",
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat WebSocket client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat WebSocket client disconnected")
        await task.cancel()

    logger.info("Starting WebSocket pipeline worker")
    await runner.run(task)


async def main() -> None:
    config = AgentConfig()
    raise RuntimeError("Use the FastAPI WebSocket endpoint to start a session")


if __name__ == "__main__":
    asyncio.run(main())
