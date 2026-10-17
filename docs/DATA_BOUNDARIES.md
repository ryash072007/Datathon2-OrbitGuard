# Data boundaries: what can see what

OrbitGuard mixes a learned forecast, a physics safety gate and an LLM narrator. This page says which of them can read which data, and which test fails if that ever changes. Everything below is checked by `tests/test_boundaries.py` (static AST checks, plus a few runtime checks).

```
 Raw CDM (ESA) --> validation --+--> ML forecast inputs (time_to_tca >= 2 d, no label fields)
                                |
                                +--> evaluation-only labels (sealed member, opened after the model is frozen)

 TLEs (CelesTrak) --> SGP4 --> physics gate (Pc rule, all-object check) --> accepted / rejected

 learned burn search --proposes--> physics gate --verifies--> only verified burns returned

 computed outputs (facts.py) --> LLM brief (Granite) --> grounding guard   (narration only)
```

| Component | Can read | Can never read | Enforced by (test) |
|---|---|---|---|
| Sealed test labels (`ml/data.py`, `test_labels_member.bin`) | Itself | Opened by anything but evaluation entry points | `test_only_ml_data_names_sealed_label_member`, `test_label_readers_called_only_from_evaluation_entry_points`, `test_evaluation_allow_list_is_not_stale`, `test_label_reader_refuses_unfrozen_artifact` |
| Evaluation entry points (`decision/evaluate.py`, `decision/workload.py`, `ml/{model,triage,guard,accuracy}.py`) | Labels, only after the artefact exists and its SHA-256 is recorded | n/a | same tests (this is the allow-list) |
| Serving code (`api.py`, `live.py`, `ml/service.py`, `decision/predict.py`, `brief/*`, `catalog/*`, `physics/*`, `optimise/*`) | Frozen models, CDMs, TLEs | Label readers | `test_serving_code_never_imports_or_calls_label_readers` |
| Forecast service (`ml/service.py`) | CDMs with `time_to_tca >= 2` days | Label-like fields (`true_risk`, `label`, `target`), CDMs closer than 2 days | `test_forecast_service_rejects_labels_and_late_cdms`; fuller case in `tests/test_ml.py::test_inference_rejects_mixed_events_labels_and_sparse_failures` |
| Physics safety gate (`physics/*`, `catalog/{screen,collision,propagate,catalog,burns,parallel}.py`) | TLEs, covariances, burns | `brief`, `ml`, `decision`, `optimise`, `zai`, `live`, `api`, `audit` (so no Granite text, learned score or operator choice reaches it) | `test_physics_gate_imports_nothing_learned_or_generated` |
| Learned burn search (`optimise/*`) | Physics evaluator results | Skipping the physics check: every returned burn goes through `select_verified` -> `problem.verify`, backed by `catalog.screen.run_burns` | `test_learned_search_only_returns_physics_verified_burns`, `test_live_problem_uses_the_all_object_physics_rule`; runtime in `tests/test_optimise.py::test_bo_recommendation_is_physics_feasible` |
| LLM brief (`brief/*`) | A facts dict computed by `facts.py` | Label readers; network code except the opt-in OpenAI-compatible backend (`brief/backends.py`, urllib) | `test_brief_never_imports_label_readers`, `test_brief_network_code_is_only_the_openai_compatible_backend`, `test_granite_prompt_facts_come_from_facts_module` |
| Decision path (`decision/*`, `ml/*`, `physics/*`, `catalog/screen.py`, `optimise/*`) | Numbers, models, physics | `orbitguard.brief`, `llama_cpp` (no LLM in the decision path) | `test_no_llm_in_decision_path` |

Notes on how the tests were adapted to the real code: the sealed member is `test_labels_member.bin`; the readers are `read_labels` and `read_labels_after_freeze` (both call `unseal_labels`). `zai` has no label access, so it is not on the allow-list. `ml/service.py` imports `digest` from `ml.data`, which is fine; the test bans the reader functions, not the module. The runtime checks are deliberately small; the grounding guard itself is covered by its own tests.
