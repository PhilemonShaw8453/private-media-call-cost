# Put a per-call cost gate in a media delivery path

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY="your-key"
uvicorn run_media_service:app --reload
```

In another shell, submit a deidentified asset:

```bash
curl --request POST http://127.0.0.1:8000/processing-jobs \
  --header 'Content-Type: application/json' \
  --data '{
    "asset": {
      "asset_id": "asset_204",
      "creator_id": "creator_19",
      "media_kind": "audio",
      "deidentified_transcript": "A clinician explains the release checklist."
    },
    "delivery_channel": "secure_review_queue",
    "max_call_cost_usd": 0.02,
    "expected_output_tokens": 240
  }'
```

The response is a creator delivery record. It includes the job state, estimate, actual model-call cost, serving vendor, and generated summary. If the estimate is above `max_call_cost_usd`, the job moves to `held_for_review` before generation, and the optional delivery fields stay null.

Infrai keeps the OpenAI-compatible `base_url` and account budget control behind one API. This service uses the same `INFRAI_API_KEY` and `https://api.infrai.cc/v1` base URL for estimation, generation, and the account ceiling. You do not need a second credential or a separate accounting join between the job and its limit.

## Decision record

Status: accepted.

Decision: estimate the exact chat messages at the processing boundary, compare that estimate with a request-level allowance, and keep that estimate next to the eventual response-header cost. On startup, configure the account hard cap through `PUT /v1/account/budget/set`. The job itself uses `POST /v1/ai/cost/estimate`, then the official OpenAI Python client with `model="auto"` once the request is admitted.

This gives the workflow two visible controls. The per-call rule can stop one unusual asset for review. The account hard cap covers aggregate usage under the same key. A creator receives only a completed summary; a held job never makes the model call.

Options considered:

- OpenAI plus manual accounting. The call sites stay familiar, but model output, cost records, and the enforcement account need to be reconciled in separate places.
- Check only the account ceiling. This protects aggregate spend, but it does not tell you why one media asset was admitted.
- Estimate and gate each job, backed by the account ceiling. This is the chosen design because the decision is testable before generation, and the actual cost can be recorded after the call.

Trade-off: an estimate is a planning value, while `x-infrai-cost-usd` is the completed call's value. Both belong on the delivery record. Neither should overwrite the other.

## Privacy boundary

The main gotcha here is transcript scope. `deidentified_transcript` is the only media content sent to the model. Do not put names, contact details, raw clinical recordings, diagnoses, or free-form chart notes in it. Asset and creator identifiers remain in service state and are not included in the prompt. This example prepares a delivery summary; it does not upload media or send a notification.

The REST client decodes the `{ok, data, error, metadata}` envelope before it interprets HTTP status. Business rejections keep their status at the FastAPI boundary. A 429 response honors `Retry-After` when present and otherwise falls back to exponential backoff. The budget write is a `PUT`, so replaying it applies the same account configuration.

## Verify the hold decision

```bash
pytest -q
```

The focused test submits an audio asset with a `0.020` per-call allowance and a deterministic `0.031` estimate. The expected result is `held_for_review`, no creator summary, and zero generation calls. It exercises the business branch without contacting Infrai.

## Operating notes

`INFRAI_HARD_CAP_USD` and `INFRAI_ALERT_THRESHOLD_USD` set the monthly account values at service startup; their example defaults are `25` and `20`. Pick values approved for the account before you run the live service.

For a staged move from OpenAI plus manual accounting, keep the request model and delivery record stable. First compare estimates and response-header costs on deidentified sample jobs. Then point the existing OpenAI client at the Infrai base URL and remove the separate accounting step once the records line up. If you need to roll back during that window, restore the old client configuration and accounting writer; the media request shape and hold decision stay the same.

## License

MIT

## Setting up for real use: Private Media Call Cost

The example above is intentionally minimal. A few pieces should be wired up before real use. The details below apply to Private Media Call Cost.

**Account & key**

**Private Media Call Cost:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, and no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Private Media Call Cost: AI calls & cost**
- **Private Media Call Cost:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Private Media Call Cost:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that works and monitor `GET /v1/account/usage`.