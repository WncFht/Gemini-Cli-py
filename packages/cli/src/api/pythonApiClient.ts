import EventSource from 'eventsource';
import { Config } from '../../config/config.js';

// Define the structure of the events from the Python server
// This should align with the JSON format we designed.
export interface ApiEvent {
  type: string;
  payload: any;
}

export class PythonApiClient {
  private sessionId: string | null = null;
  private eventSource: EventSource | null = null;
  private baseUrl: string;

  constructor(private config: Config, port: number = 8000) {
    this.baseUrl = `http://localhost:${port}`;
  }

  async startSession(): Promise<void> {
    const response = await fetch(`${this.baseUrl}/session/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // TODO: We need a proper way to serialize the config
      body: JSON.stringify({ config: { /* placeholder */ } }),
    });

    if (!response.ok) {
      throw new Error('Failed to start session');
    }

    const data = await response.json();
    this.sessionId = data.session_id;
    console.log(`Python session started with ID: ${this.sessionId}`);
  }

  async *sendMessageStream(messages: any[]): AsyncGenerator<ApiEvent> {
    if (!this.sessionId) {
      throw new Error('Session not started');
    }

    // Close any existing connection
    this.closeEventSource();

    const url = `${this.baseUrl}/chat`;
    this.eventSource = new EventSource(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        messages: messages,
      }),
    });

    // A queue to handle backpressure and stream events
    const eventQueue: (ApiEvent | null)[] = [];
    let resolveQueue: ((value: void) => void) | null = null;

    const waitForEvent = () => {
      return new Promise<void>((resolve) => {
        resolveQueue = resolve;
      });
    };

    this.eventSource.onmessage = (event: any) => {
      const parsedData = JSON.parse(event.data);
      eventQueue.push(parsedData);
      if (resolveQueue) resolveQueue();
    };

    this.eventSource.onerror = (error: any) => {
      console.error('EventSource failed:', error);
      eventQueue.push(null); // Signal stream end
      if (resolveQueue) resolveQueue();
      this.closeEventSource();
    };

    try {
      while (true) {
        if (eventQueue.length > 0) {
          const event = eventQueue.shift();
          if (event === null) {
            break; // Stream ended
          }
          yield event!;
        } else {
          await waitForEvent();
        }
      }
    } finally {
      this.closeEventSource();
    }
  }

  async confirmTool(callId: string, outcome: string): Promise<void> {
    if (!this.sessionId) throw new Error('Session not started');

    await fetch(`${this.baseUrl}/tool/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        call_id: callId,
        outcome,
      }),
    });
  }

  async cancel(): Promise<void> {
    if (!this.sessionId) return;
    await fetch(`${this.baseUrl}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: this.sessionId }),
    });
    this.closeEventSource();
  }

  private closeEventSource(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
} 