/**
 * Main entry point for SousChef Live frontend.
 *
 * Orchestrates: permission request -> media init -> WebSocket connect
 * -> setup message -> streaming loop.
 */

import { GeminiLiveClient } from './lib/gemini-live/geminilive.js';
import { createAudioStreamer, createVideoStreamer, AudioPlayer } from './lib/gemini-live/mediaUtils.js';
import {
  getState, setState, addTranscript, finishLastTranscript,
  updateFromServerEvent, startTimerTick, stopTimerTick, DEFAULT_REGION,
} from './state.js';
import { initUI, setupTranscriptToggle, setAnalyserNode } from './ui.js';
import { debugEvent } from './debug.js';

let client = null;
let audioStreamer = null;
let videoStreamer = null;
let audioPlayer = null;
let pingInterval = null;

const SESSION_RESET_STATE = {
  isConnected: false,
  connectionPhase: 'disconnected',
  isAgentSpeaking: false,
  currentStep: 'idle',
  monitoringStatus: 'Waiting for ingredients',
  recipeName: null,
  timers: [],
  transcript: [],
  error: null,
  sessionInfo: { region: DEFAULT_REGION, rttMs: 0 },
};

function generateSessionId() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

async function startSession() {
  const sessionId = generateSessionId();
  setState({ ...SESSION_RESET_STATE, sessionId });

  audioPlayer = new AudioPlayer();
  await audioPlayer.init();

  if (audioPlayer.analyserNode) {
    setAnalyserNode(audioPlayer.analyserNode);
  }

  client = new GeminiLiveClient();

  let _hadUserInputThisTurn = false;
  let _unsolicitedTurnActive = false;
  let _pendingProactiveMeta = null;
  let _currentProactiveMeta = null;

  client.onProactiveMeta = (meta) => {
    _pendingProactiveMeta = meta;
  };

  client.onAudioData = (data) => {
    const wasSpeaking = getState().isAgentSpeaking;
    setState({ isAgentSpeaking: true });
    audioPlayer.play(data);
    if (!wasSpeaking && !_hadUserInputThisTurn) {
      _unsolicitedTurnActive = true;
      _currentProactiveMeta = _pendingProactiveMeta;
      debugEvent('proactive', 'unsolicited_turn_started', {
        candidate_id: _currentProactiveMeta?.candidate_id || null,
        lane: _currentProactiveMeta?.lane || null,
        trigger_source: _currentProactiveMeta?.trigger_source || null,
        reason_code: _currentProactiveMeta?.reason_code || null,
      });
    }
  };

  client.onTranscriptInput = (text) => {
    _hadUserInputThisTurn = true;
    addTranscript('cook', text, { replace: true });
  };

  client.onTranscriptOutput = (text) => {
    addTranscript('chef', text, { replace: true });
  };

  client.onInterrupt = () => {
    audioPlayer.interrupt();
    setState({ isAgentSpeaking: false });
    if (_unsolicitedTurnActive) {
      debugEvent('proactive', 'barge_in_detected', {
        candidate_id: _currentProactiveMeta?.candidate_id || null,
      });
    }
    _unsolicitedTurnActive = false;
    _currentProactiveMeta = null;
    _pendingProactiveMeta = null;
  };

  client.onTurnComplete = () => {
    setState({ isAgentSpeaking: false });
    finishLastTranscript('cook');
    finishLastTranscript('chef');
    if (_unsolicitedTurnActive) {
      debugEvent('proactive', 'unsolicited_turn_completed', {
        candidate_id: _currentProactiveMeta?.candidate_id || null,
        lane: _currentProactiveMeta?.lane || null,
      });
    }
    _hadUserInputThisTurn = false;
    _unsolicitedTurnActive = false;
    _currentProactiveMeta = null;
    _pendingProactiveMeta = null;
  };

  client.onToolCall = (msg) => {
    updateFromServerEvent(msg);
  };

  client.onStateUpdate = (msg) => {
    updateFromServerEvent(msg);
  };

  client.onError = (err) => {
    setState({ error: err });
    debugEvent('main', 'error_banner_shown', { error: err });
  };

  client.onConnected = async () => {
    setState({ isConnected: true, connectionPhase: 'connected' });
    debugEvent('main', 'ws_open');

    client.sendSetup({
      generation_config: {
        response_modalities: ['AUDIO'],
        speech_config: {
          voice_config: {
            prebuilt_voice_config: { voice_name: 'Aoede' },
          },
        },
      },
      input_audio_transcription: {},
      output_audio_transcription: {},
    });

    try {
      const videoEl = document.getElementById('camera-feed');
      videoStreamer = createVideoStreamer((base64, mime) => {
        client.sendImage(base64, mime);
      });
      await videoStreamer.start(videoEl);
      debugEvent('main', 'permissions_granted');
    } catch (e) {
      debugEvent('main', 'video_permission_error', { error: e.message });
    }

    try {
      audioStreamer = createAudioStreamer((pcmBuffer) => {
        client.sendAudio(pcmBuffer);
      });
      await audioStreamer.start();
    } catch (e) {
      debugEvent('main', 'audio_permission_error', { error: e.message });
    }

    startTimerTick();
    startPing();
  };

  client.onDisconnected = (closeEvent) => {
    const code = closeEvent?.code ?? 1006;
    const isUserClose = code === 1000;
    const maxRetriesExhausted = client._reconnectAttempts >= client._maxReconnectAttempts;

    if (isUserClose || maxRetriesExhausted) {
      setState({ ...SESSION_RESET_STATE, sessionId: getState().sessionId });
      stopTimerTick();
      stopPing();
    } else {
      setState({ isConnected: false, connectionPhase: 'reconnecting', isAgentSpeaking: false });
      debugEvent('main', 'transient_disconnect', { code });
    }
  };

  client.connect(sessionId);
}

function stopSession() {
  if (audioStreamer) { audioStreamer.stop(); audioStreamer = null; }
  if (videoStreamer) { videoStreamer.stop(); videoStreamer = null; }
  if (audioPlayer) { audioPlayer.destroy(); audioPlayer = null; }
  if (client) {
    client.sendControl('end_session', true);
    client.disconnect();
    client = null;
  }
  setAnalyserNode(null);
  stopTimerTick();
  stopPing();
  setState({ ...SESSION_RESET_STATE, sessionId: '', connectionPhase: 'disconnected' });

  const perm = document.getElementById('permission-screen');
  const cook = document.getElementById('cooking-screen');
  cook.classList.remove('active');
  requestAnimationFrame(() => {
    perm.classList.add('active');
  });
}

function startPing() {
  const updateHealth = () => {
    const start = performance.now();
    fetch('/api/health').then(async (resp) => {
      const body = await resp.json();
      const rtt = Math.round(performance.now() - start);
      const info = getState().sessionInfo;
      setState({
        sessionInfo: {
          ...info,
          rttMs: rtt,
          region: body.deployment_region || info.region || DEFAULT_REGION,
        },
      });
    }).catch(() => {});
  };

  updateHealth();
  pingInterval = setInterval(() => {
    updateHealth();
  }, 5000);
}

function stopPing() {
  if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
}

document.addEventListener('DOMContentLoaded', () => {
  initUI();
  setupTranscriptToggle();

  document.getElementById('btn-start').addEventListener('click', async () => {
    const perm = document.getElementById('permission-screen');
    const cook = document.getElementById('cooking-screen');
    perm.classList.remove('active');
    requestAnimationFrame(() => {
      cook.classList.add('active');
    });
    await startSession();
  });

  document.getElementById('btn-stop').addEventListener('click', () => {
    stopSession();
  });

  document.getElementById('checkbox-demo-speed').addEventListener('change', (e) => {
    const val = e.target.checked;
    setState({ demoSpeed: val });
    if (client && client.connected) {
      client.sendControl('demo_speed', val);
    }
  });

  document.getElementById('btn-dismiss-error').addEventListener('click', () => {
    setState({ error: null });
  });
});
