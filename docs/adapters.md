# Storage, extraction, speech and model setup

All identified documents and audio processing belong inside the deployment boundary. These
adapters do not provision cloud infrastructure, credentials, model weights or external services.

## Record storage

The default is `MEDPAL_OBJECT_STORE_BACKEND=file`, rooted at `.medpal/objects`. Objects survive
API restarts. `.medpal/` is ignored by git. Files are private, and completed writes are published
atomically. `make up-all` uses the `objects` Docker volume; `make reset` deletes that volume too.

For S3-compatible storage set:

```dotenv
MEDPAL_OBJECT_STORE_BACKEND=s3
MEDPAL_OBJECT_STORE_BUCKET=your-private-bucket
MEDPAL_OBJECT_STORE_REGION=ap-south-1
# For a private S3-compatible endpoint only:
# MEDPAL_OBJECT_STORE_ENDPOINT_URL=https://your-private-endpoint
```

Provision the bucket in-region, deny public access and grant the service only object read/write
access within its private prefix. AWS workload credentials use the standard boto3 credential
chain; private services can use `MEDPAL_OBJECT_STORE_ACCESS_KEY_ID` and
`MEDPAL_OBJECT_STORE_SECRET_ACCESS_KEY`. Writes request AES256 server-side encryption. The
adapter neither creates buckets nor changes bucket policies. Keep filesystem storage for local
work; `MEDPAL_ENV=prod` requires `s3` (and the existing non-dev auth and chat-provider settings).
S3 connectivity/encryption needs validation against the actual configured service.

## PDF and OCR

`uv sync --all-groups` installs pypdf. Text PDFs work without system OCR tools. Scanned pages
require local `pdftoppm`, `tesseract`, and the `eng` and `hin` language packs. The application
Dockerfile installs these. On a host, install the corresponding OS packages yourself or use
`make up-all`.

Uploads accept UTF-8 text or PDFs up to 8 MiB. PDFs are limited to 40 pages and 500,000 extracted
characters. OCR subprocesses have per-command timeouts. Images use private temporary files
removed when extraction ends. No hosted OCR is used. An unreadable scan returns
`ocr_unavailable`; encrypted/invalid/empty PDFs are also rejected before persistence. Identifier
validation runs on extracted text (including OCR output), rather than scanning raw PDF bytes.
OCR accuracy still needs evaluation on representative synthetic scans.

Records are ingested inline, so OCR requests may take time. The UI shows processing/error states
and persisted job statuses. A background queue is a separate remaining milestone.

## Local speech

Enable the optional runtime:

```bash
uv sync --all-groups --extra speech
```

Provision a faster-whisper model directory on the host in advance, then set
`MEDPAL_SPEECH_MODEL_PATH=/absolute/path/to/model`. Runtime loading uses `local_files_only=True`;
no model download or hosted speech API runs on a consultation request. CPU int8 is the current
adapter configuration. For an application image with speech dependencies:

```bash
docker build --build-arg ENABLE_SPEECH=true -t medpal:speech -f infra/Dockerfile .
```

Mount the model directory read-only into that container and set the same variable to its
container path. Model provisioning and Hindi/Hinglish transcription quality require separate
validation; automated adapter tests use a fake model.

Doctors can upload PCM WAV audio in the Scribe page or `POST /api/scribe/transcribe` (raw WAV request body,
`Content-Type: audio/wav`). Limit: 16 MiB, 30 minutes, mono/stereo PCM. Other audio formats must first be
converted locally. Audio stays in memory, is never uploaded to object storage and is not kept
for a retention job. The returned transcript must be reviewed before drafting a note; no audio
upload drafts or signs anything automatically. With no local model configured the endpoint
returns 503, while typed transcript drafting remains available.

## Hosted models

All generation goes through the egress client, which de-identifies first. Without configuration a local
placeholder model keeps every flow working (it never invents clinical content). To use Gemini, copy
`.env.example` to `.env` and fill in the Gemini block:

| Setting | Meaning |
|---|---|
| `MEDPAL_CHAT_PROVIDER=gemini`, `MEDPAL_CHAT_API_KEY` | Provider and key (`openai`, `anthropic` and `openai-compatible` also work) |
| `MEDPAL_CHAT_MODEL` | Large tier: records answers, note drafts |
| `MEDPAL_CHAT_SMALL_MODEL` | Small tier: assistant routing |
| `MEDPAL_CHAT_SMALL_THINKING_LEVEL=low` | Reasoning effort for routing. Measured: same accuracy, half the latency. Leave the large tier on the default |
| `MEDPAL_CHAT_FALLBACK_*` | A second provider tried when the first fails, times out or returns invalid output |
| `MEDPAL_CHAT_TIMEOUT_SECONDS` (30), `MEDPAL_CHAT_MAX_RETRIES` (1) | Hard deadline per provider attempt; SDK retries kept low so the fallback chain decides |
| `MEDPAL_MODEL_PRICES`, `MEDPAL_PRICE_LIST_DATE` | USD per million tokens and the date you read the price list. Unpriced models report cost as "unpriced", never a guess |

After changing a model or prompt, run `make live-check` against the running API: it checks records
answers (value and cited page), refusals, assistant routing, scribe drafts, provider fallback and cost
metering, and writes a report to `evals/runs/`. Unit and integration tests always use the local model,
whatever `.env` says, so they stay free and deterministic.
