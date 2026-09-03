"""A local Parakeet transcription server, for the live path's local models.

**This is not part of Elicta and is not shipped.** The product deliberately
does not run a speech model: no weights are in the bundle, there is no
download, and the Settings screen says as much. What the live path does when
`live_model` names a local model is post each four-second window to an
OpenAI-compatible transcription API that somebody else is running. This is one
of those, small enough to read, for a machine that wants Parakeet and does not
already have a server.

It exists because the alternative on this platform is worse. `speaches` and
LocalAI are the general answer, and both run Parakeet on CPU inside a Linux
container on an Apple Silicon host — which is the one arrangement where the
model is slowest, on the one path whose entire budget is the conversational
window. `parakeet-mlx` runs the same model on the Neural Engine natively and
has no server, so the missing piece is exactly this file.

Run it:

    uv run --with parakeet-mlx --with fastapi --with uvicorn \\
           --with python-multipart python tools/local-asr/server.py

Then put `http://127.0.0.1:8178/v1` into Settings → Speech → Local
transcription server. The first run downloads the weights (about 2.5 GB) into
the HuggingFace cache; later runs start from disk.
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

LOG = logging.getLogger("local-asr")

#: What Elicta asks for, and where the weights actually live. Elicta sends the
#: plain model name from its own closed set; the MLX community publishes the
#: converted weights under its own namespace. One is not derivable from the
#: other, so the mapping is written down.
ALIASES = {
    "parakeet-tdt-0.6b-v2": "mlx-community/parakeet-tdt-0.6b-v2",
    "parakeet-tdt-0.6b-v3": "mlx-community/parakeet-tdt-0.6b-v3",
}

DEFAULT_MODEL = "parakeet-tdt-0.6b-v2"
DEFAULT_PORT = 8178


class Recogniser:
    """One loaded model, and the lock that keeps requests off each other.

    MLX arrays are not safe to use from two threads at once, and a four-second
    window arriving every four seconds is enough to overlap whenever one of
    them is slow. Serialised rather than batched: the queue is at most a
    window or two deep, and a batching layer here would be machinery guarding
    against a load this never sees.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.repo = ALIASES.get(name, name)
        self._lock = threading.Lock()
        LOG.info("loading %s (first run downloads the weights)", self.repo)
        started = time.monotonic()
        from parakeet_mlx import from_pretrained

        self._model = from_pretrained(self.repo)
        LOG.info("loaded in %.1fs", time.monotonic() - started)

    def warm(self) -> None:
        """Transcribe a moment of silence, so the first real window is not the
        one that pays for compilation.

        Without it the first request takes several seconds — which on the live
        path is a window that misses the conversation it was about.
        """

        import wave

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
        try:
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16_000)
                out.writeframes(b"\x00\x00" * 16_000)
            started = time.monotonic()
            self.transcribe(path)
            LOG.info("warmed in %.1fs", time.monotonic() - started)
        finally:
            path.unlink(missing_ok=True)

    def transcribe(self, path: Path) -> str:
        with self._lock:
            result = self._model.transcribe(str(path))
        # `AlignedResult` carries the sentences and a joined `text`; older
        # builds expose only the tokens, so the join is done here rather than
        # trusted to a property that may not be there.
        text = getattr(result, "text", None)
        if isinstance(text, str):
            return text.strip()
        return "".join(getattr(token, "text", "") for token in result.tokens).strip()


def build_app(recogniser: Recogniser) -> FastAPI:
    app = FastAPI(title="Local Parakeet transcription")

    @app.get("/v1/models")
    async def models() -> JSONResponse:
        """What this server has loaded, for anything that asks before sending."""

        return JSONResponse(
            {"object": "list", "data": [{"id": recogniser.name, "object": "model"}]}
        )

    @app.get("/health")
    async def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: UploadFile,
        model: str = Form(default=DEFAULT_MODEL),
        response_format: str = Form(default="json"),
    ):
        """One window of audio in, the words in it out.

        A model this server has not loaded is **refused**, not quietly
        transcribed with the one it has. A server that substitutes silently is
        a server whose model dropdown is decoration, and an operator who
        switched from Whisper to Parakeet to fix a bad transcript would get
        the same bad transcript with no way to tell why.
        """

        if model not in {recogniser.name, recogniser.repo}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"this server has {recogniser.name} loaded and cannot serve "
                    f"{model}; restart it with --model {model} to change that"
                ),
            )

        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="the uploaded audio was empty")

        suffix = Path(file.filename or "window.wav").suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(payload)
            path = Path(handle.name)
        try:
            started = time.monotonic()
            text = recogniser.transcribe(path)
        except Exception as cause:  # noqa: BLE001 — reported, never swallowed
            # Reported as a failure rather than as an empty transcript: read as
            # silence, a broken recogniser is a meeting that transcribes to
            # nothing with every screen showing a working lane.
            LOG.exception("transcription failed")
            raise HTTPException(status_code=500, detail=str(cause)) from cause
        finally:
            path.unlink(missing_ok=True)

        LOG.info("%.2fs · %d bytes · %r", time.monotonic() - started, len(payload), text[:80])

        if response_format == "text":
            return PlainTextResponse(text)
        return JSONResponse({"text": text})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("LOCAL_ASR_MODEL", DEFAULT_MODEL))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    recogniser = Recogniser(args.model)
    recogniser.warm()

    import uvicorn

    LOG.info("serving %s at http://%s:%d/v1", recogniser.name, args.host, args.port)
    uvicorn.run(build_app(recogniser), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
