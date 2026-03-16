/**
 * Reactive state management for SousChef Live.
 *
 * Simple pub/sub state object with typed fields. UI subscribes
 * to changes, server events mutate state via updateFromServerEvent().
 */

import { debugEvent } from './debug.js';

export function inferRegionFromHost() {
  const host = globalThis.location?.hostname || '';
  if (!host) return '--';
  if (host === 'localhost' || host === '127.0.0.1') return 'local';
  if (host.endsWith('-uc.a.run.app')) return 'us-central1';
  if (host.endsWith('-ew.a.run.app')) return 'europe-west1';
  return '--';
}

export const DEFAULT_REGION = inferRegionFromHost();

const state = {
  sessionId: '',
  isConnected: false,
  connectionPhase: 'disconnected',
  isAgentSpeaking: false,
  currentStep: 'idle',
  monitoringStatus: 'Waiting for ingredients',
  recipeName: null,
  timers: [],
  transcript: [],
  demoSpeed: false,
  sessionInfo: { region: DEFAULT_REGION, rttMs: 0 },
  error: null,
};

const _listeners = new Set();

export function getState() {
  return state;
}

export function subscribe(callback) {
  _listeners.add(callback);
  return () => _listeners.delete(callback);
}

function _notify() {
  for (const cb of _listeners) {
    try { cb(state); } catch (e) { console.error('State listener error:', e); }
  }
}

export function setState(partial) {
  Object.assign(state, partial);
  _notify();
}

/**
 * Add or update a transcript entry.
 *
 * @param {string}  role              - 'cook' or 'chef'
 * @param {string}  text              - the transcription text
 * @param {object}  [opts]
 * @param {boolean} [opts.replace]    - if true, replace the text of the last
 *   unfinished entry of the same role instead of appending.  Use for input
 *   transcription where Gemini sends the accumulated (refined) text each time.
 */
export function addTranscript(role, text, { replace = false } = {}) {
  if (!text || !text.trim()) return;

  // Scan backwards for the last unfinished entry of the *same* role.
  // This prevents interleaved input/output transcription events from
  // fragmenting one response into many bubbles.
  let target = null;
  for (let i = state.transcript.length - 1; i >= 0; i--) {
    if (state.transcript[i].role === role) {
      if (!state.transcript[i].finished) target = state.transcript[i];
      break; // stop at the most recent entry of this role regardless
    }
  }

  if (target) {
    if (replace) {
      target.text = text;
    } else {
      const needsSpace =
        target.text.length > 0 &&
        !target.text.endsWith(' ') &&
        !text.startsWith(' ');
      target.text += (needsSpace ? ' ' : '') + text;
    }
  } else {
    state.transcript.push({ role, text, finished: false, ts: Date.now() });
  }

  if (state.transcript.length > 50) state.transcript.shift();
  _notify();
  const last = state.transcript[state.transcript.length - 1];
  debugEvent('state', 'transcript_updated', {
    role,
    replace,
    finished: false,
    text,
    transcript_count: state.transcript.length,
    last_role: last?.role || null,
  });
}

export function finishLastTranscript(role) {
  for (let i = state.transcript.length - 1; i >= 0; i--) {
    if (state.transcript[i].role === role) {
      state.transcript[i].finished = true;
      debugEvent('state', 'transcript_finished', {
        role,
        text: state.transcript[i].text,
        transcript_count: state.transcript.length,
      });
      break;
    }
  }
  _notify();
}

export function updateFromServerEvent(msg) {
  if (msg.type === 'state_update') {
    const updates = {
      currentStep: msg.current_step || state.currentStep,
      monitoringStatus: msg.monitoring_status || state.monitoringStatus,
      recipeName: msg.recipe_name || state.recipeName,
      timers: msg.timers || state.timers,
    };

    // State hydration: server sends transcript history on reconnect
    if (msg.transcript && Array.isArray(msg.transcript) && msg.transcript.length > 0) {
      updates.transcript = msg.transcript.map((t) => ({
        role: t.role,
        text: t.text,
        finished: true,
        ts: Date.now(),
      }));
    }

    setState(updates);
    debugEvent('state', 'state_update_applied');
  }

  if (msg.type === 'tool_call') {
    if (msg.name === 'set_timer' && msg.result) {
      const existing = state.timers.find((t) => t.id === msg.result.timer_id);
      if (!existing) {
        state.timers.push({
          id: msg.result.timer_id,
          label: msg.result.label || msg.args?.label,
          effective_seconds: msg.result.effective_seconds,
          started_at: Date.now() / 1000,
          remaining_seconds: msg.result.effective_seconds,
        });
        _notify();
      }
    }
    if (msg.name === 'update_recipe' && msg.result) {
      setState({
        recipeName: msg.result.recipe_name || msg.args?.recipe_name,
      });
    }
    debugEvent('state', 'tool_call_processed', { name: msg.name });
  }

  if (msg.type === 'error') {
    setState({ error: msg.error });
  }
}

// Local timer countdown tick (1Hz)
let _timerInterval = null;

export function startTimerTick() {
  if (_timerInterval) return;
  _timerInterval = setInterval(() => {
    const now = Date.now() / 1000;
    let changed = false;
    for (const t of state.timers) {
      const elapsed = now - t.started_at;
      const remaining = Math.max(0, t.effective_seconds - elapsed);
      if (Math.abs(remaining - t.remaining_seconds) > 0.5) {
        t.remaining_seconds = remaining;
        changed = true;
      }
    }
    if (changed) _notify();
  }, 1000);
}

export function stopTimerTick() {
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
}
