# ADR-0008: Hybrid deployment with an enforced egress boundary

- **Status:** accepted
- **Context:** Identified health data must stay in-region and inside the deployment boundary. Only de-identified text may reach a hosted model. The model vendor must be swappable. A policy that exists only in code ("we always scrub before calling") is one bug away from a leak; it needs a second, structural control.
- **Options:**
  1. *Everything on-premise, including the model.* Strongest residency, but weakest model access and the highest operations burden.
  2. *Private cloud with in-region hosted models.* Strong, but depends on a vendor contract in-region.
  3. *Public cloud and a public model, with no network boundary.* Fastest, but residency depends on application code alone.
  4. **Hybrid:** identified stores and processing inside an **internal network with no route out**, one ingress, and one **allowlisting egress proxy** to the configured model APIs. De-identification (ADR-0006) runs before anything reaches the proxy.
- **Decision:** Option 4 (`infra/docker-compose.boundary.yml`):
  - The API, worker, Postgres and Redis sit only on an `internal: true` network, which Docker gives no gateway.
  - Ingress is nginx, on the public and boundary networks.
  - Egress is `services/egress_proxy`. It allows HTTP `CONNECT` only to allowlisted `host:443`, sees no content (end-to-end TLS) and logs only host and decision.
  - Model SDKs reach it through `HTTPS_PROXY`; internal services are in `NO_PROXY`.
- **Revisit trigger:** an in-region hosted model under contract (collapse to option 2), or clinical review finding de-identified drafts too weak (move drafting in-boundary with a local model).
- **Consequences:**
  - *Easier:* a leak needs two independent failures (scrubber and network); the allowlist is auditable configuration.
  - *Harder:* two networks to operate; every new external dependency (SMS, OTP) must be added to the allowlist deliberately; local development uses the simpler `docker-compose.yml`.
- **Proof:**
  - `tests/unit/test_egress_proxy.py`: allowlisted tunnels work; everything else returns 403, including internal ports; plain HTTP returns 405.
  - `make up-boundary && make boundary-check`: from inside the API container, a direct internet connection fails, a non-allowlisted host is refused and an allowlisted model API is reachable.
- **Checked on:** 2026-11-03 (unit-tested; the live `boundary-check` needs a working Docker).
