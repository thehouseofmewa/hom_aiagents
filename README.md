# hom_aiagents

## API

Start the API and voice test console locally with `make run`. The Docker image
starts the same server automatically on port 8080. Open `http://localhost:8080`
to use the browser client. Restart the server after pulling this UI into an
already-running process.

Request a WebSocket voice-agent session with:

```sh
curl -X POST http://localhost:8080/pipeline
```

The endpoint returns `202 Accepted` with a `wsUrl`. The pipeline starts when the
browser connects to that WebSocket and returns `409 Conflict` if another session
is already running.

The console uses Pipecat Client JS with the WebSocket transport. It requests
microphone access, connects to `/ws` returned by `/pipeline`, plays bot audio,
and displays live user and bot transcript events.
