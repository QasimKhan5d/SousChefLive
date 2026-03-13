/**
 * Unit tests for the WebSocket client message parser.
 *
 * Mocks WebSocket and validates callback routing for all message types.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 1; // OPEN
    this.binaryType = '';
    this.sentMessages = [];
    MockWebSocket._last = this;
  }
  send(data) { this.sentMessages.push(data); }
  close(code, reason) { this._closedWith = { code, reason }; }
}
MockWebSocket.OPEN = 1;

vi.stubGlobal('WebSocket', MockWebSocket);
vi.stubGlobal('location', { protocol: 'http:', host: 'localhost:5173' });

const { GeminiLiveClient } = await import('../src/lib/gemini-live/geminilive.js');

describe('GeminiLiveClient', () => {
  let client;

  beforeEach(() => {
    client = new GeminiLiveClient();
  });

  it('connects and fires onConnected', () => {
    const cb = vi.fn();
    client.onConnected = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    expect(cb).toHaveBeenCalledOnce();
    expect(client.connected).toBe(true);
  });

  it('routes binary data to onAudioData', () => {
    const cb = vi.fn();
    client.onAudioData = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({ data: new ArrayBuffer(10) });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('routes input transcription', () => {
    const cb = vi.fn();
    client.onTranscriptInput = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({
        serverContent: { inputTranscription: { text: 'hello', finished: true } }
      })
    });
    expect(cb).toHaveBeenCalledWith('hello');
  });

  it('routes output transcription', () => {
    const cb = vi.fn();
    client.onTranscriptOutput = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({
        serverContent: { outputTranscription: { text: 'hi cook', finished: true } }
      })
    });
    expect(cb).toHaveBeenCalledWith('hi cook');
  });

  it('routes interrupt event', () => {
    const cb = vi.fn();
    client.onInterrupt = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({ serverContent: { interrupted: true } })
    });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('routes turnComplete event', () => {
    const cb = vi.fn();
    client.onTurnComplete = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({ serverContent: { turnComplete: true } })
    });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('routes tool_call event', () => {
    const cb = vi.fn();
    client.onToolCall = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({ type: 'tool_call', name: 'set_timer', args: {}, result: {} })
    });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('routes state_update event', () => {
    const cb = vi.fn();
    client.onStateUpdate = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({ type: 'state_update', current_step: 'heat' })
    });
    expect(cb).toHaveBeenCalledOnce();
  });

  it('routes error event', () => {
    const cb = vi.fn();
    client.onError = cb;
    client.connect('sess1');
    MockWebSocket._last.onopen();
    MockWebSocket._last.onmessage({
      data: JSON.stringify({ type: 'error', error: 'something broke' })
    });
    expect(cb).toHaveBeenCalledWith('something broke');
  });

  it('handles malformed JSON gracefully', () => {
    client.connect('sess1');
    MockWebSocket._last.onopen();
    expect(() => {
      MockWebSocket._last.onmessage({ data: '{invalid json' });
    }).not.toThrow();
  });

  it('sendSetup sends JSON with setup key', () => {
    client.connect('sess1');
    MockWebSocket._last.onopen();
    client.sendSetup({ generation_config: {} });
    const sent = JSON.parse(MockWebSocket._last.sentMessages[0]);
    expect(sent.setup).toBeDefined();
  });

  it('sendAudio sends binary data', () => {
    client.connect('sess1');
    MockWebSocket._last.onopen();
    const buf = new ArrayBuffer(10);
    client.sendAudio(buf);
    expect(MockWebSocket._last.sentMessages[0]).toBe(buf);
  });

  it('sendControl sends control payload', () => {
    client.connect('sess1');
    MockWebSocket._last.onopen();
    client.sendControl('demo_speed', true);
    const sent = JSON.parse(MockWebSocket._last.sentMessages[0]);
    expect(sent.type).toBe('control');
    expect(sent.action).toBe('demo_speed');
    expect(sent.value).toBe(true);
  });

  it('disconnect closes cleanly', () => {
    client.connect('sess1');
    MockWebSocket._last.onopen();
    client.disconnect();
    expect(client.connected).toBe(false);
    expect(MockWebSocket._last._closedWith.code).toBe(1000);
  });
});
