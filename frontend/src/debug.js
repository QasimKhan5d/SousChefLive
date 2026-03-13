/**
 * Frontend debug/observability module for SousChef Live.
 *
 * In dev/harness mode, buffers structured events in memory and exposes
 * them for automated assertions and live inspection.
 */

const MAX_BUFFER = 500;
const _buffer = [];
let _runId = `fe_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

export function getRunId() {
  return _runId;
}

export function resetRunId(id) {
  _runId = id || `fe_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function debugEvent(component, eventType, details = {}) {
  const event = {
    timestamp: new Date().toISOString(),
    run_id: _runId,
    component,
    event_type: eventType,
    details,
  };

  _buffer.push(event);
  if (_buffer.length > MAX_BUFFER) {
    _buffer.shift();
  }

  if (import.meta.env?.DEV || new URLSearchParams(location.search).has('harness')) {
    console.debug(`[${component}] ${eventType}`, details);
  }

  return event;
}

export function getEventBuffer() {
  return _buffer;
}

export function clearEventBuffer() {
  _buffer.length = 0;
}

export function getEventsByType(eventType) {
  return _buffer.filter((e) => e.event_type === eventType);
}

if (typeof window !== 'undefined') {
  window.__souschef_debug = {
    getEventBuffer,
    getEventsByType,
    clearEventBuffer,
    getRunId,
  };
}
