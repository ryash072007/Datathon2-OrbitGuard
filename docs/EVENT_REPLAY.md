# Event-to-alert demonstration

In **Encounters**, select a historical ESA encounter and press **Replay messages one by one**. Each step sends its encounter ID and message position to LinuxONE. The server selects only the messages available at that position, recomputes the forecast and compares the alert with the preceding message's forecast. Playback waits for the result instead of skipping updates when inference is slower than the display interval.

The small **Update → forecast → alert** timeline shows the last five inspected positions, high-risk or experimental-review alerts, changes, server processing time and browser round-trip time. Pause or use the slider to inspect any prefix. Failure pauses playback and offers retry. Monitor means continue observing, not safe to ignore.

Example request against your running API:

```sh
curl -s http://127.0.0.1:8082/api/replay/update \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"1051","message_count":1}'
```

The JSON response includes a combined input/output fingerprint (`update_id`), server timestamps, forecast and alert transition. Repeating the request returns the same decision identity with new timing measurements, without creating a screening job. An update ID is not a persistent event record; save the JSON externally if you need an audit artifact.

## What to tell judges

“This is historical event replay processed on our connected LinuxONE server, not a live orbital feed. Every incoming replay step triggers risk inference and an operator-facing alert decision. We measure processing and transport separately. The later reference risk is displayed only for retrospective comparison and is not used by this endpoint.”

Then demonstrate **Manoeuvre planning** separately: its synthetic geometry supports checking whether a candidate burn creates another hazard and withholding a recommendation. Do not imply the anonymised ESA event supplies those simulated orbits.

## Verification

The isolated LinuxONE preview passed all 63 Python tests, the real-browser smoke check (including actual screening), and a sequential replay of all 13 messages for ESA encounter 1051. That encounter changed from monitor to experimental additional review at message 13. Repeating the final request returned the same update identity. The fixture browser checks additionally cover ordered playback, request failure/retry and superseded responses. The original deployment was not replaced.

## Operational limits

This closes the demonstrable message-to-forecast-to-alert loop, not production live-data integration. There is no continuous upstream subscription, durable ingestion queue, delivery guarantee, authentication or spacecraft command. Production ingestion would need an authorised orbital-data source and those operational controls. The default forecasting model and its held-out accuracy have not changed.

`processing_ms` includes history selection plus current and previous prefix forecasts, and can include cold model loading. It is not the existing single-forecast benchmark or observation-to-action latency. Browser round-trip measurements start when sending the request, after the intentional replay pacing/debounce.
