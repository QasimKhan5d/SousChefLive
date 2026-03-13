/**
 * Unit tests for frontend state management.
 *
 * Tests the reactive store, event processing, transcript management,
 * and timer countdown behavior.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

let stateModule;

beforeEach(async () => {
  vi.useFakeTimers();
  vi.resetModules();
  stateModule = await import('../src/state.js');
});

afterEach(() => {
  stateModule.stopTimerTick();
  vi.useRealTimers();
});

describe('getState / setState', () => {
  it('returns initial state with expected fields', () => {
    const s = stateModule.getState();
    expect(s.sessionId).toBe('');
    expect(s.isConnected).toBe(false);
    expect(s.currentStep).toBe('idle');
    expect(s.timers).toEqual([]);
    expect(s.transcript).toEqual([]);
  });

  it('merges partial state', () => {
    stateModule.setState({ isConnected: true, sessionId: 'abc' });
    const s = stateModule.getState();
    expect(s.isConnected).toBe(true);
    expect(s.sessionId).toBe('abc');
    expect(s.currentStep).toBe('idle');
  });
});

describe('subscribe', () => {
  it('notifies listeners on state change', () => {
    const cb = vi.fn();
    stateModule.subscribe(cb);
    stateModule.setState({ isConnected: true });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('unsubscribe stops notifications', () => {
    const cb = vi.fn();
    const unsub = stateModule.subscribe(cb);
    unsub();
    stateModule.setState({ isConnected: true });
    expect(cb).not.toHaveBeenCalled();
  });
});

describe('addTranscript', () => {
  it('adds a new transcript entry', () => {
    stateModule.addTranscript('cook', 'hello chef');
    const s = stateModule.getState();
    expect(s.transcript).toHaveLength(1);
    expect(s.transcript[0].role).toBe('cook');
    expect(s.transcript[0].text).toBe('hello chef');
    expect(s.transcript[0].finished).toBe(false);
  });

  it('appends to same-role unfinished entry', () => {
    stateModule.addTranscript('chef', 'part one');
    stateModule.addTranscript('chef', ' part two');
    const s = stateModule.getState();
    expect(s.transcript).toHaveLength(1);
    expect(s.transcript[0].text).toBe('part one part two');
  });

  it('starts new entry for different role', () => {
    stateModule.addTranscript('cook', 'hi');
    stateModule.addTranscript('chef', 'hello');
    expect(stateModule.getState().transcript).toHaveLength(2);
  });

  it('ignores empty text', () => {
    stateModule.addTranscript('cook', '');
    stateModule.addTranscript('cook', '   ');
    expect(stateModule.getState().transcript).toHaveLength(0);
  });

  it('caps transcript at 50 entries', () => {
    for (let i = 0; i < 55; i++) {
      stateModule.addTranscript(i % 2 === 0 ? 'cook' : 'chef', `msg ${i}`);
      stateModule.finishLastTranscript(i % 2 === 0 ? 'cook' : 'chef');
    }
    expect(stateModule.getState().transcript.length).toBeLessThanOrEqual(50);
  });
});

describe('finishLastTranscript', () => {
  it('marks the last entry as finished', () => {
    stateModule.addTranscript('chef', 'hello');
    stateModule.finishLastTranscript('chef');
    expect(stateModule.getState().transcript[0].finished).toBe(true);
  });

  it('does not finish entry with wrong role', () => {
    stateModule.addTranscript('chef', 'hello');
    stateModule.finishLastTranscript('cook');
    expect(stateModule.getState().transcript[0].finished).toBe(false);
  });
});

describe('updateFromServerEvent', () => {
  it('handles state_update event', () => {
    stateModule.updateFromServerEvent({
      type: 'state_update',
      current_step: 'heat',
      monitoring_status: 'Monitoring pan heat',
      recipe_name: 'chicken',
      timers: [],
    });
    const s = stateModule.getState();
    expect(s.currentStep).toBe('heat');
    expect(s.monitoringStatus).toBe('Monitoring pan heat');
    expect(s.recipeName).toBe('chicken');
  });

  it('handles set_timer tool_call event', () => {
    stateModule.updateFromServerEvent({
      type: 'tool_call',
      name: 'set_timer',
      args: { duration_seconds: 120, label: 'sear' },
      result: { timer_id: 'tmr_1', label: 'sear', effective_seconds: 120 },
    });
    const s = stateModule.getState();
    expect(s.timers).toHaveLength(1);
    expect(s.timers[0].id).toBe('tmr_1');
    expect(s.timers[0].label).toBe('sear');
  });

  it('does not duplicate timers', () => {
    const evt = {
      type: 'tool_call',
      name: 'set_timer',
      result: { timer_id: 'tmr_dup', label: 'sear', effective_seconds: 10 },
    };
    stateModule.updateFromServerEvent(evt);
    stateModule.updateFromServerEvent(evt);
    expect(stateModule.getState().timers).toHaveLength(1);
  });

  it('handles update_recipe tool_call event', () => {
    stateModule.updateFromServerEvent({
      type: 'tool_call',
      name: 'update_recipe',
      args: { recipe_name: 'garlic chicken' },
      result: { recipe_name: 'garlic chicken' },
    });
    expect(stateModule.getState().recipeName).toBe('garlic chicken');
  });

  it('handles error event', () => {
    stateModule.updateFromServerEvent({ type: 'error', error: 'test error' });
    expect(stateModule.getState().error).toBe('test error');
  });

  it('handles malformed JSON gracefully', () => {
    expect(() => stateModule.updateFromServerEvent({})).not.toThrow();
    expect(() => stateModule.updateFromServerEvent({ type: 'unknown' })).not.toThrow();
  });
});

describe('timer tick', () => {
  it('counts down timer remaining seconds', () => {
    const now = Date.now() / 1000;
    stateModule.setState({
      timers: [{
        id: 'tmr_tick',
        label: 'test',
        effective_seconds: 60,
        started_at: now,
        remaining_seconds: 60,
      }],
    });

    stateModule.startTimerTick();
    vi.advanceTimersByTime(3000);

    const t = stateModule.getState().timers[0];
    expect(t.remaining_seconds).toBeLessThan(60);
  });

  it('does not go below zero', () => {
    const now = Date.now() / 1000;
    stateModule.setState({
      timers: [{
        id: 'tmr_neg',
        label: 'test',
        effective_seconds: 1,
        started_at: now - 100,
        remaining_seconds: 0,
      }],
    });

    stateModule.startTimerTick();
    vi.advanceTimersByTime(2000);

    expect(stateModule.getState().timers[0].remaining_seconds).toBe(0);
  });
});
