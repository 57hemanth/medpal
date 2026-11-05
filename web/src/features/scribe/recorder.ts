/**
 * Dictation for the consultation scribe: microphone -> 16 kHz mono PCM -> WAV pieces cut at pauses.
 *
 * Pieces are cut where the speaker pauses (never mid-word), at least MIN_SECONDS and at most
 * MAX_SECONDS long, so each one can be transcribed while the doctor keeps talking and the transcript is
 * ready moments after they stop. Audio is held in memory only and is never stored by the browser.
 */

export const SAMPLE_RATE = 16_000;
const MIN_SECONDS = 8;
const MAX_SECONDS = 25;
const PAUSE_SECONDS = 0.7;
const SILENCE_RMS = 0.012;

/** Float samples in [-1, 1] -> a 16-bit PCM mono WAV file. */
export function encodeWav(samples: Float32Array, rate = SAMPLE_RATE): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) =>
    [...value].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const s = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  });
  return new Blob([buffer], { type: 'audio/wav' });
}

/** Resample by averaging (input rate is always higher than 16 kHz on real devices). */
export function downsample(
  input: Float32Array,
  from: number,
  to = SAMPLE_RATE,
): Float32Array {
  if (from === to) return input;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

export function rms(block: Float32Array): number {
  let sum = 0;
  for (const s of block) sum += s * s;
  return block.length ? Math.sqrt(sum / block.length) : 0;
}

/**
 * Collects 16 kHz blocks and decides where to cut. `push` returns a finished piece when a pause
 * arrives after MIN_SECONDS of audio (or at MAX_SECONDS regardless); `flush` returns what's left.
 * Pieces with no speech in them are dropped.
 */
export class Segmenter {
  private blocks: Float32Array[] = [];
  private length = 0;
  private silentRun = 0;
  private heardSpeech = false;

  push(block: Float32Array): Float32Array | null {
    this.blocks.push(block);
    this.length += block.length;
    const quiet = rms(block) < SILENCE_RMS;
    this.silentRun = quiet ? this.silentRun + block.length : 0;
    if (!quiet) this.heardSpeech = true;
    const seconds = this.length / SAMPLE_RATE;
    const paused = this.silentRun / SAMPLE_RATE >= PAUSE_SECONDS;
    if ((seconds >= MIN_SECONDS && paused) || seconds >= MAX_SECONDS)
      return this.take();
    return null;
  }

  flush(): Float32Array | null {
    return this.length ? this.take() : null;
  }

  private take(): Float32Array | null {
    const speech = this.heardSpeech;
    const out = new Float32Array(this.length);
    let offset = 0;
    for (const block of this.blocks) {
      out.set(block, offset);
      offset += block.length;
    }
    this.blocks = [];
    this.length = 0;
    this.silentRun = 0;
    this.heardSpeech = false;
    return speech ? out : null;
  }
}

// Runs on the audio thread: copies each 128-frame block to the page.
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor('medpal-tap', Tap);
`;

export type Dictation = { stop: () => Promise<void> };

/**
 * Start dictating. `onPiece` gets each WAV piece in order; `onLevel` gets the input level (0..1)
 * for a meter. Resolves once the microphone is live; rejects if permission is refused.
 */
export async function startDictation({
  onPiece,
  onLevel,
}: {
  onPiece: (wav: Blob) => void;
  onLevel?: (level: number) => void;
}): Promise<Dictation> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const context = new AudioContext();
  const url = URL.createObjectURL(
    new Blob([WORKLET], { type: 'application/javascript' }),
  );
  try {
    await context.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const source = context.createMediaStreamSource(stream);
  const tap = new AudioWorkletNode(context, 'medpal-tap');
  const segmenter = new Segmenter();
  let pending: Float32Array[] = [];
  let pendingLength = 0;
  // Downsample in ~100 ms batches: per-128-frame resampling would drop fractional samples.
  const batch = Math.round(context.sampleRate / 10);
  tap.port.onmessage = (event: MessageEvent<Float32Array>) => {
    pending.push(event.data);
    pendingLength += event.data.length;
    if (pendingLength < batch) return;
    const joined = new Float32Array(pendingLength);
    let offset = 0;
    for (const part of pending) {
      joined.set(part, offset);
      offset += part.length;
    }
    pending = [];
    pendingLength = 0;
    const block = downsample(joined, context.sampleRate);
    onLevel?.(Math.min(1, rms(block) * 8));
    const piece = segmenter.push(block);
    if (piece) onPiece(encodeWav(piece));
  };
  source.connect(tap);
  return {
    stop: async () => {
      source.disconnect();
      tap.port.onmessage = null;
      stream.getTracks().forEach((track) => track.stop());
      await context.close();
      if (pendingLength) {
        const joined = new Float32Array(pendingLength);
        let offset = 0;
        for (const part of pending) {
          joined.set(part, offset);
          offset += part.length;
        }
        const piece = segmenter.push(downsample(joined, context.sampleRate));
        if (piece) onPiece(encodeWav(piece));
      }
      const rest = segmenter.flush();
      if (rest) onPiece(encodeWav(rest));
      onLevel?.(0);
    },
  };
}
