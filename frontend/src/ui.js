/**
 * UI renderer for SousChef Live.
 *
 * Subscribes to state changes and updates DOM elements.
 * Renders: timer ring cards, chat-bubble transcript, step progress,
 * connection quality bars, and audio waveform visualizer.
 */

import { getState, subscribe } from './state.js';
import { debugEvent } from './debug.js';

const $ = (sel) => document.querySelector(sel);

const STEP_ORDER = [
  'idle', 'recipe_selected', 'prep', 'cooking', 'resting', 'plating', 'done',
];

let _waveformCtx = null;
let _waveformAnimId = null;
let _analyserNode = null;

export function setAnalyserNode(node) {
  _analyserNode = node;
}

export function initUI() {
  subscribe(render);
  render(getState());
}

function render(state) {
  renderRecipe(state);
  renderStep(state);
  renderMonitor(state);
  renderStepProgress(state);
  renderTimers(state);
  renderTranscript(state);
  renderSessionBadge(state);
  renderConnectionBars(state);
  renderSpeaking(state);
  renderError(state);
  renderReconnecting(state);
}

function renderRecipe(state) {
  const el = $('#recipe-text');
  if (el) el.textContent = state.recipeName || '--';
}

function renderStep(state) {
  const el = $('#step-text');
  if (el) el.textContent = formatStep(state.currentStep);
}

function renderMonitor(state) {
  const el = $('#monitor-text');
  if (el) el.textContent = state.monitoringStatus;
}

function renderStepProgress(state) {
  const bar = $('#step-progress');
  const inner = $('#step-progress-inner');
  if (!bar || !inner) return;

  const idx = STEP_ORDER.indexOf(state.currentStep);
  if (idx <= 0) {
    bar.classList.remove('visible');
    inner.style.width = '0%';
    return;
  }

  bar.classList.add('visible');
  const pct = Math.round((idx / (STEP_ORDER.length - 1)) * 100);
  inner.style.width = `${pct}%`;
}

function renderTimers(state) {
  const area = $('#timer-area');
  if (!area) return;

  const existing = new Map();
  for (const child of area.children) {
    existing.set(child.dataset.id, child);
  }

  for (const t of state.timers) {
    const remaining = Math.max(0, Math.round(t.remaining_seconds || 0));
    const total = t.effective_seconds || 1;
    const pct = remaining / total;
    const isExpired = remaining <= 0;

    let card = existing.get(t.id);
    if (!card) {
      card = _createTimerCard(t);
      area.appendChild(card);
    }
    existing.delete(t.id);

    _updateTimerCard(card, t, remaining, pct, isExpired);
    debugEvent('ui', 'timer_card_rendered', { id: t.id, remaining });
  }

  for (const orphan of existing.values()) orphan.remove();

  const badgeTimers = $('#badge-timers');
  if (badgeTimers) {
    const active = state.timers.filter((t) => (t.remaining_seconds || 0) > 0).length;
    badgeTimers.textContent = `${active} timer${active !== 1 ? 's' : ''}`;
  }
}

const RING_RADIUS = 19;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function _createTimerCard(t) {
  const card = document.createElement('div');
  card.className = 'timer-card';
  card.dataset.id = t.id;
  card.innerHTML = `
    <div class="timer-ring-wrap">
      <svg width="48" height="48" viewBox="0 0 48 48">
        <circle class="timer-ring-bg" cx="24" cy="24" r="${RING_RADIUS}" />
        <circle class="timer-ring-fg" cx="24" cy="24" r="${RING_RADIUS}"
                stroke-dasharray="${RING_CIRCUMFERENCE}"
                stroke-dashoffset="0" />
      </svg>
      <span class="timer-ring-time"></span>
    </div>
    <div class="timer-info">
      <span class="timer-label">${t.label || 'Timer'}</span>
      <span class="timer-value"></span>
    </div>
  `;
  return card;
}

function _updateTimerCard(card, t, remaining, pct, isExpired) {
  const fg = card.querySelector('.timer-ring-fg');
  const ringTime = card.querySelector('.timer-ring-time');
  const value = card.querySelector('.timer-value');

  if (fg) {
    const offset = RING_CIRCUMFERENCE * (1 - pct);
    fg.style.strokeDashoffset = offset;
    fg.classList.toggle('expired', isExpired);
  }

  if (ringTime) ringTime.textContent = formatTimeShort(remaining);
  if (value) value.textContent = formatTime(remaining);

  card.classList.toggle('expired', isExpired);
}

function renderTranscript(state) {
  const body = $('#transcript-body');
  if (!body) return;

  while (body.children.length < state.transcript.length) {
    const entry = state.transcript[body.children.length];
    const div = document.createElement('div');
    div.className = `transcript-entry ${entry.role}`;

    const avatar = document.createElement('span');
    avatar.className = 'transcript-avatar';
    avatar.textContent = entry.role === 'cook' ? 'Y' : 'C';

    const bubble = document.createElement('span');
    bubble.className = 'transcript-bubble';
    bubble.textContent = entry.text;

    div.appendChild(avatar);
    div.appendChild(bubble);
    body.appendChild(div);
  }

  for (let i = 0; i < state.transcript.length; i++) {
    const bubble = body.children[i]?.querySelector('.transcript-bubble');
    if (bubble) bubble.textContent = state.transcript[i].text;
  }

  body.scrollTop = body.scrollHeight;
}

function renderSessionBadge(state) {
  const region = $('#badge-region');
  const rtt = $('#badge-rtt');
  const session = $('#badge-session');

  if (region) region.textContent = state.sessionInfo.region;
  if (rtt) rtt.textContent = `${state.sessionInfo.rttMs || '--'}ms`;
  if (session) session.textContent = state.sessionId ? `${state.sessionId.slice(0, 12)}…` : '--';
}

function renderConnectionBars(state) {
  const bars = $('.signal-bars');
  if (!bars) return;

  const rtt = state.sessionInfo.rttMs || 0;
  bars.classList.remove('quality-good', 'quality-ok', 'quality-poor');

  if (!state.isConnected || rtt === 0) return;

  if (rtt < 200) bars.classList.add('quality-good');
  else if (rtt < 500) bars.classList.add('quality-ok');
  else bars.classList.add('quality-poor');
}

function renderSpeaking(state) {
  const el = $('#speaking-indicator');
  if (!el) return;

  const wasSpeaking = !el.classList.contains('hidden');
  const isSpeaking = state.isAgentSpeaking;

  el.classList.toggle('hidden', !isSpeaking);

  if (isSpeaking && !wasSpeaking) {
    _startWaveform();
  } else if (!isSpeaking && wasSpeaking) {
    _stopWaveform();
  }
}

function _startWaveform() {
  const canvas = $('#waveform-canvas');
  if (!canvas) return;
  _waveformCtx = canvas.getContext('2d');

  if (_waveformAnimId) cancelAnimationFrame(_waveformAnimId);
  _drawWaveframe();
}

function _stopWaveform() {
  if (_waveformAnimId) {
    cancelAnimationFrame(_waveformAnimId);
    _waveformAnimId = null;
  }
  const canvas = $('#waveform-canvas');
  if (canvas && _waveformCtx) {
    _waveformCtx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

function _drawWaveframe() {
  _waveformAnimId = requestAnimationFrame(_drawWaveframe);
  if (!_waveformCtx) return;

  const canvas = _waveformCtx.canvas;
  const w = canvas.width;
  const h = canvas.height;
  _waveformCtx.clearRect(0, 0, w, h);

  let dataArray;
  if (_analyserNode) {
    dataArray = new Uint8Array(_analyserNode.frequencyBinCount);
    _analyserNode.getByteTimeDomainData(dataArray);
  }

  const barCount = 20;
  const barWidth = 3;
  const gap = (w - barCount * barWidth) / (barCount - 1);

  _waveformCtx.fillStyle = '#e94560';
  for (let i = 0; i < barCount; i++) {
    let amplitude;
    if (dataArray) {
      const idx = Math.floor((i / barCount) * dataArray.length);
      amplitude = Math.abs(dataArray[idx] - 128) / 128;
    } else {
      amplitude = 0.15 + 0.35 * Math.sin(Date.now() / 200 + i * 0.5);
    }

    const barH = Math.max(2, amplitude * h * 0.85);
    const x = i * (barWidth + gap);
    const y = (h - barH) / 2;
    _waveformCtx.beginPath();
    _waveformCtx.roundRect(x, y, barWidth, barH, 1.5);
    _waveformCtx.fill();
  }
}

function renderError(state) {
  const banner = $('#error-banner');
  const text = $('#error-text');
  if (banner && text) {
    if (state.error) {
      text.textContent = state.error;
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
    }
  }
}

function formatStep(step) {
  return step.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatTimeShort(seconds) {
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m`;
  return `${seconds}s`;
}

function renderReconnecting(state) {
  let overlay = $('#reconnecting-overlay');
  const isReconnecting = state.connectionPhase === 'reconnecting';

  if (isReconnecting && !overlay) {
    overlay = document.createElement('div');
    overlay.id = 'reconnecting-overlay';
    overlay.className = 'reconnecting-overlay glass';
    overlay.innerHTML = `
      <div class="reconnecting-spinner"></div>
      <span>Reconnecting&hellip;</span>
    `;
    const cook = $('#cooking-screen');
    if (cook) cook.appendChild(overlay);
  }

  if (overlay) {
    overlay.classList.toggle('hidden', !isReconnecting);
  }
}

export function setupTranscriptToggle() {
  const panel = $('#transcript-panel');
  const btn = $('#btn-toggle-transcript');
  const header = $('#transcript-header');
  if (panel && btn && header) {
    header.addEventListener('click', () => {
      panel.classList.toggle('collapsed');
    });
  }
}
