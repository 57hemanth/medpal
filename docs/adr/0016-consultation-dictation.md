# ADR-0016: Consultation dictation, local by default, Gemini by explicit opt-in

- **Status:** accepted (adds a hosted option to the speech adapter in [ADR-0008](0008-hybrid-deployment-egress-boundary.md)'s boundary)
- **Context:** Doctors should speak the consultation and see the transcript, not upload files. Transcription has to be fast enough to keep up, right on drug names and doses, and work for Hinglish. Text sent to AI providers is de-identified first (ADR-0006), but audio can't be: names, numbers and the voice itself are in it.
- **Options:**
  1. *Browser speech recognition (Web Speech API).* Free and instant, but Chrome sends the audio to Google with no agreement and no region control. Rejected.
  2. *Local Whisper only.* Audio never leaves; measured fast and exact on English, but the small model mistranscribes Hinglish.
  3. **Local Whisper by default; Gemini as a switch that also requires an explicit "audio may leave" setting.**
- **Decision:** Option 3 (`services/scribe/speech.py`, `web/src/features/scribe/recorder.ts`):
  - **Dictation:** the browser records the microphone, resamples to 16 kHz mono, and cuts pieces at pauses (8–25 s, never mid-word). Each piece is transcribed while the doctor keeps talking, in order, and appended to the editable transcript. Audio lives only in memory on both sides.
  - **Local (default):** faster-whisper small, int8 on CPU. WAV is decoded by our own code rather than the library's media decoder (see lessons learned #35). Language is fixed to English so Hinglish comes out in Latin script.
  - **Gemini:** `MEDPAL_SPEECH_PROVIDER=gemini` refuses to start unless `MEDPAL_ALLOW_AUDIO_EGRESS=true` is also set. The prompt asks for a verbatim transcript, untranslated, with Hinglish in Latin script. Calls are traced and costed like every other model call.
  - **Vocabulary:** both transcribers get a list of common medicines (`MEDPAL_SPEECH_VOCABULARY`). On a short piece, the local model wrote "Parasatomol" without it and "paracetamol" with it.
  - The page asks the API where audio goes and says so, rather than always claiming "processed locally".
- **Measured (Apple M5, 4 November 2026):**

  | | Local Whisper small | Gemini (small tier) |
  |---|---|---|
  | English consultation, 17 s | exact, 1.9 s | exact, 6.0 s |
  | Hinglish ("raat ko khansi bhi badh jaati hai") | wrong: "I have to go to the toilet at night" | exact, Latin script |
  | Browser dictation, 34 s with pauses | transcript grows as you talk; complete 0.5 s after Stop; exact with the vocabulary | not run in the browser |
  | Audio leaves the boundary | never | yes |

- **Consequences:**
  - *Easier:* doctors speak instead of typing; transcription keeps pace with speech.
  - *Harder:* running Gemini for audio needs a data processing agreement covering voice data, and ideally Vertex AI in an Indian region instead of the public Gemini API. A larger local model (Whisper medium or large-v3) is the alternative for Hinglish without egress, at more CPU.
- **Revisit trigger:** clinician review of transcription errors; a GPU in the boundary (larger local model); Gemini in an Indian region.
- **Proof:** `tests/unit/test_speech.py` (decoding, provider choice, opt-in guard, metering, vocabulary, truthful privacy note), `web/src/features/scribe/recorder.test.ts` (WAV format, resampling, cutting at pauses, the 25 s cap, silence never sent), and the browser run above.
- **Checked on:** 2026-11-04
