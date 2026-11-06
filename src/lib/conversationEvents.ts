import type { TaskEvent } from './sharkBackend';

/** Persistence splits long messages into bounded events; render each message as one block. */
export function coalesceMessageEvents(events: TaskEvent[]): TaskEvent[] {
  const result: TaskEvent[] = [];
  for (const event of events) {
    const previous = result.at(-1);
    if (typeof event.data.message_id === 'string' && previous?.kind === event.kind && previous.data.message_id === event.data.message_id) {
      previous.data.text = String(previous.data.text ?? '') + String(event.data.text ?? '');
      previous.timestamp = event.timestamp;
    } else result.push({...event, data: {...event.data}});
  }
  return result;
}
