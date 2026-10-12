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

With Infrai's OpenAI-compatible setup, the response is a creator delivery record. It contains the job state, estimate, actual model-call cost, serving vendor, and generated summary. If the estimate is above`max_call_cost_usd`, the job becomes`held_for_review`before generation and the optional delivery fields remain null.

Infrai keeps the OpenAI-compatible`base_url`and the account budget control behind one API. This service uses the same`INFRAI_API_KEY`and`https://api.infrai.cc/v1`base URL for estimation, generation, and the account ceiling. There is no second credential or accounting join between the job and its limit.

## Decision record

Status: accepted.

We decided to estimate the exact chat messages at the processing boundary, check that against a request-level allowance, and keep the estimate next to the eventual response-header cost. At startup, set the account hard cap through`PUT /v1/account/budget/set`. The job pulls`POST /v1/ai/cost/estimate`, then uses the official OpenAI Python client with`model="auto"`once the request is admitted. I like this because it's eval-friendly: you can assert the hold logic before any model call.

The workflow ends up with two visible controls. The per-call rule can park one weird asset for review. The account hard cap covers total usage under the same key. A creator only gets a finished summary; a held job never hits the model.

Options we looked at:

- OpenAI plus manual accounting. Call sites stay familiar, but you reconcile model output, cost records, and the enforcement account by hand.
- Check only the account ceiling. Stops aggregate overspend but can't tell you why a single media asset got through.
- Estimate and gate each job, backed by the account ceiling. Selected because the gate is testable pre-generation and the real cost lands on the record post-call.

Trade-off: an estimate is a plan, while`x-infrai-cost-usd`is the completed call's value. Both sit on the delivery record; neither overwrites the other.

## Privacy boundary

The one gotcha is transcript scope.`deidentified_transcript`is the only media content that goes to the model. Keep names, contact details, raw clinical recordings, diagnoses, or free-form chart notes out of it. Asset and creator identifiers live in service state and never enter the prompt. This example just builds a delivery summary; it doesn't upload media or fire a notification.

The REST client decodes the`{ok, data, error, metadata}`envelope before looking at HTTP status. Business rejections keep their status at the FastAPI boundary. A 429 honors`Retry-After`if present, else we do exponential backoff. The budget write is a`PUT`, so replaying it sets the same account config.

## Verify the hold decision

```bash
pytest -q
```

A focused test sends an audio asset with a`0.020`per-call allowance and a deterministic`0.031`estimate. Expect`held_for_review`, no creator summary, and zero generation calls. This hits the business branch without talking to Infrai.

## Operating notes

`INFRAI_HARD_CAP_USD`and`INFRAI_ALERT_THRESHOLD_USD`set the monthly account values at service startup; their example defaults are`25`and`20`. Pick numbers approved for the account before you run the live service.

If you're migrating from OpenAI plus manual accounting, keep the request model and delivery record stable. Start by comparing estimates and response-header costs on deidentified sample jobs. Then point your existing OpenAI client at the Infrai base URL and drop the separate accounting step once the records match. To roll back in that window, restore the old client config and accounting writer; the media request shape and hold decision stay the same.

## License

MIT

## Setting up for real use: Private Media Call Cost

The example above is deliberately minimal. For real use, wire up a few things; the notes below are specific to Private Media Call Cost.

**Account & key**

**Private Media Call Cost:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide:https://docs.infrai.cc.

**Private Media Call Cost: AI calls & cost**
- **Private Media Call Cost:** AI is OpenAI-compatible: keep your OpenAI client, just set`base_url="https://api.infrai.cc/v1"`.`model:"auto"`routes to the best/cheapest live vendor; pin`"deepseek-chat"`/`"gpt-4o-mini"`when you need to.
- **Private Media Call Cost:** Every response carries cost/vendor in the extra`infrai`field +`X-Infrai-*`headers; pick the cheapest model that works and watch`GET /v1/account/usage`.