import { useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { type AuthContext, api } from '../../api/client';
import { Button, humanError } from '../../components/ui';
import { type Dictation, startDictation } from './recorder';

function clock(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Speak and the transcript fills in. Each piece (cut at a pause) is transcribed while the doctor keeps
 * talking, in order, and appended. Audio stays in memory and is discarded once transcribed.
 */
export function DictationPanel({
  auth,
  disabled,
  onStart,
  onText,
  onError,
}: {
  auth: AuthContext;
  disabled?: boolean;
  onStart: () => void;
  onText: (text: string) => void;
  onError: (message: string) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [inFlight, setInFlight] = useState(0);
  const dictation = useRef<Dictation | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const timer = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [recording]);

  // Never leave the microphone on when the page goes away.
  useEffect(() => () => void dictation.current?.stop(), []);

  function transcribePiece(wav: Blob) {
    setInFlight((n) => n + 1);
    queue.current = queue.current.then(async () => {
      try {
        const { transcript } = await api<{ transcript: string }>(
          '/api/scribe/transcribe',
          {
            method: 'POST',
            body: wav,
            headers: { 'content-type': 'audio/wav' },
          },
          auth,
        );
        onText(transcript);
      } catch (cause) {
        const message = humanError(cause);
        if (!message.includes('no_speech_detected')) onError(message);
      } finally {
        setInFlight((n) => n - 1);
      }
    });
  }

  async function start() {
    setStarting(true);
    try {
      dictation.current = await startDictation({
        onPiece: transcribePiece,
        onLevel: setLevel,
      });
      onStart();
      setSeconds(0);
      setRecording(true);
    } catch (cause) {
      onError(
        cause instanceof DOMException && cause.name === 'NotAllowedError'
          ? 'Microphone access was blocked. Allow it in the browser’s address bar, then try again.'
          : 'No microphone is available on this device.',
      );
    } finally {
      setStarting(false);
    }
  }

  async function stop() {
    setRecording(false);
    await dictation.current?.stop();
    dictation.current = null;
  }

  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-4">
      <div className="flex flex-wrap items-center gap-4">
        {recording ? (
          <Button variant="danger" onClick={() => void stop()}>
            <Square size={14} aria-hidden="true" />
            Stop
          </Button>
        ) : (
          <Button
            onClick={() => void start()}
            busy={starting}
            disabled={disabled}
          >
            <Mic size={15} aria-hidden="true" />
            Dictate
          </Button>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold" aria-live="polite">
            {recording
              ? `Listening · ${clock(seconds)}`
              : inFlight
                ? 'Finishing the transcript…'
                : 'Speak the consultation; the transcript fills in as you talk'}
          </p>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-white"
            aria-hidden="true"
          >
            <div
              className="h-full rounded-full bg-brand-600 transition-[width] duration-100"
              style={{ width: `${Math.round((recording ? level : 0) * 100)}%` }}
            />
          </div>
          <p className="mt-1.5 text-[11px] text-muted">
            {inFlight
              ? `Transcribing ${inFlight} ${inFlight === 1 ? 'part' : 'parts'}…`
              : 'Audio is transcribed in parts and never saved.'}
          </p>
        </div>
      </div>
    </div>
  );
}
