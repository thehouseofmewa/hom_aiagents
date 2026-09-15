"""Entrypoint for running the voice-agent test pipeline directly.

Usage:
    python -m pipeline_building.run

Requires the env vars documented in pipeline_building/agent_pipeline.py.
"""

import asyncio

from hom_backend.pipeline_building.agent_pipeline import main

if __name__ == "__main__":
    asyncio.run(main())
