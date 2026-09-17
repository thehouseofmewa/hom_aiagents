import { PipecatClient } from "@pipecat-ai/client-js";
import { ProtobufFrameSerializer, WebSocketTransport } from "@pipecat-ai/websocket-transport";

const elements = {
  activity: document.querySelector("#activity"),
  audioTracks: document.querySelector("#audioTracks"),
  end: document.querySelector("#endButton"),
  headerState: document.querySelector("#headerState"),
  hint: document.querySelector("#hint"),
  live: document.querySelector("#liveLabel"),
  mute: document.querySelector("#muteButton"),
  room: document.querySelector("#roomState"),
  start: document.querySelector("#startButton"),
  state: document.querySelector("#stateBadge"),
  transport: document.querySelector("#transportState"),
  transcript: document.querySelector("#transcript"),
};

let client;
let sessionActive = false;
let muted = false;

function setStatus(state, activity = state) {
  const label = state.toUpperCase();
  elements.state.textContent = label;
  elements.transport.textContent = label;
  elements.headerState.textContent = label;
  elements.activity.textContent = activity;
  elements.live.textContent = state === "ready" ? "LIVE" : label;
  elements.live.classList.toggle("is-live", state === "ready");
}

function addTranscript(role, text, partial = false) {
  if (!text) return;
  const empty = elements.transcript.querySelector(".empty-state");
  empty?.remove();
  let entry = elements.transcript.querySelector(`[data-role="${role}"]`);
  if (!entry || !partial) {
    entry = document.createElement("div");
    entry.className = `transcript-entry ${role}`;
    entry.dataset.role = role;
    elements.transcript.append(entry);
  }
  entry.innerHTML = `<span>${role === "user" ? "YOU" : "BOT"}</span><p></p>`;
  entry.querySelector("p").textContent = text;
  elements.transcript.scrollTop = elements.transcript.scrollHeight;
}

function createClient() {
  return new PipecatClient({
    transport: new WebSocketTransport({
      serializer: new ProtobufFrameSerializer(),
      recorderSampleRate: 16000,
      playerSampleRate: 24000,
    }),
    enableMic: true,
    callbacks: {
      onConnected: () => setStatus("connected", "Connected. Waiting for the bot"),
      onBotReady: () => setStatus("ready", "Listening for your voice"),
      onDisconnected: () => resetSession("Session ended"),
      onTransportStateChanged: (state) => {
        elements.transport.textContent = String(state).toUpperCase();
      },
      onBotStartedSpeaking: () => setStatus("ready", "Bot is speaking"),
      onBotStoppedSpeaking: () => setStatus("ready", "Listening for your voice"),
      onUserStartedSpeaking: () => setStatus("ready", "Listening"),
      onUserTranscript: (data) => addTranscript("user", data.text, !data.final),
      onBotOutput: (data) => addTranscript("bot", data.text),
      onTrackStarted: (track, participant) => {
        if (participant?.local || track.kind !== "audio") return;
        const audio = document.createElement("audio");
        audio.autoplay = true;
        audio.srcObject = new MediaStream([track]);
        elements.audioTracks.append(audio);
      },
      onError: (error) => showError(error?.data?.error || "The bot reported an error."),
      onDeviceError: (error) => showError(error?.message || "Microphone access failed."),
    },
  });
}

function showError(message) {
  setStatus("error", message);
  elements.hint.textContent = message;
}

function resetSession(message = "Ready for another session") {
  sessionActive = false;
  muted = false;
  elements.start.disabled = false;
  elements.mute.disabled = true;
  elements.end.disabled = true;
  elements.mute.innerHTML = "<span>◉</span>";
  elements.room.textContent = "NOT CREATED";
  elements.hint.textContent = "Your browser will ask for microphone permission when the session starts.";
  elements.audioTracks.replaceChildren();
  setStatus("idle", message);
}

async function startSession() {
  elements.start.disabled = true;
  elements.hint.textContent = "Opening a WebSocket session…";
  setStatus("starting", "Opening a secure room");
  try {
    const response = await fetch("/pipeline", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not start the pipeline.");
    elements.room.textContent = "LOCAL WS";
    client = createClient();
    sessionActive = true;
    elements.mute.disabled = false;
    elements.end.disabled = false;
    elements.hint.textContent = "Microphone is live. Say hello when the bot is ready.";
    const wsUrl = data.wsUrl.startsWith("/")
      ? `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${data.wsUrl}`
      : data.wsUrl;
    elements.hint.textContent = `Connecting to ${new URL(wsUrl).host}…`;
    await client.connect({ wsUrl });
  } catch (error) {
    showError(error.message || "Could not connect to the voice bot.");
    resetSession("Connection failed");
  }
}

elements.start.addEventListener("click", startSession);
elements.mute.addEventListener("click", () => {
  if (!client) return;
  muted = !muted;
  client.enableMic(!muted);
  elements.mute.classList.toggle("is-muted", muted);
  elements.mute.innerHTML = muted ? "<span>⊘</span>" : "<span>◉</span>";
  elements.mute.title = muted ? "Unmute microphone" : "Mute microphone";
  elements.activity.textContent = muted ? "Microphone muted" : "Listening for your voice";
});
elements.end.addEventListener("click", async () => {
  if (sessionActive && client) await client.disconnect();
  resetSession();
});