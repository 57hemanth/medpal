import { expect, test } from 'vitest';
import { SAMPLE_RATE, Segmenter, downsample, encodeWav } from './recorder';

const tone = (seconds: number, amplitude = 0.3) =>
  Float32Array.from(
    { length: Math.round(seconds * SAMPLE_RATE) },
    (_, i) => amplitude * Math.sin((2 * Math.PI * 220 * i) / SAMPLE_RATE),
  );
const silence = (seconds: number) =>
  new Float32Array(Math.round(seconds * SAMPLE_RATE));

/** Feed audio in 100 ms blocks, as the recorder does. */
function feed(segmenter: Segmenter, audio: Float32Array) {
  const pieces: Float32Array[] = [];
  const block = SAMPLE_RATE / 10;
  for (let i = 0; i < audio.length; i += block) {
    const piece = segmenter.push(audio.slice(i, i + block));
    if (piece) pieces.push(piece);
  }
  return pieces;
}

function concat(...parts: Float32Array[]) {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const p of parts) {
    out.set(p, offset);
    offset += p.length;
  }
  return out;
}

test('a WAV piece is 16-bit mono PCM at 16 kHz with the right length', async () => {
  const wav = encodeWav(tone(1));
  const bytes = new DataView(await wav.arrayBuffer());
  const text = (o: number) =>
    String.fromCharCode(...[0, 1, 2, 3].map((i) => bytes.getUint8(o + i)));
  expect(text(0)).toBe('RIFF');
  expect(text(8)).toBe('WAVE');
  expect(bytes.getUint16(22, true)).toBe(1); // mono
  expect(bytes.getUint32(24, true)).toBe(16_000);
  expect(bytes.getUint16(34, true)).toBe(16); // bits
  expect(bytes.getUint32(40, true)).toBe(16_000 * 2);
  expect(wav.size).toBe(44 + 16_000 * 2);
});

test('48 kHz input becomes 16 kHz', () => {
  expect(downsample(new Float32Array(48_000), 48_000)).toHaveLength(16_000);
});

test('pieces are cut at a pause, never before 8 seconds', () => {
  const segmenter = new Segmenter();
  // a pause at 4 s is too early to cut; the pause after 10 s of audio is where it cuts
  const pieces = feed(
    segmenter,
    concat(tone(4), silence(1), tone(5), silence(1), tone(3)),
  );
  expect(pieces).toHaveLength(1);
  expect(pieces[0].length / SAMPLE_RATE).toBeGreaterThanOrEqual(10);
  expect(pieces[0].length / SAMPLE_RATE).toBeLessThan(11);
  const rest = segmenter.flush();
  // the cut lands 0.7 s into the pause; the rest of that pause starts the next piece
  expect(rest && rest.length / SAMPLE_RATE).toBeCloseTo(3.3, 1);
});

test('someone who never pauses is still cut at 25 seconds', () => {
  const pieces = feed(new Segmenter(), tone(60));
  expect(pieces.map((p) => Math.round(p.length / SAMPLE_RATE))).toEqual([
    25, 25,
  ]);
});

test('silence alone is never sent for transcription', () => {
  const segmenter = new Segmenter();
  expect(feed(segmenter, silence(30))).toEqual([]);
  expect(segmenter.flush()).toBeNull();
});
