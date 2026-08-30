# Spec Delta: risk-inference

## ADDED Requirements

### Requirement: Temperatures are converted to the model's unit at exactly one boundary
The model was trained on absolute temperatures in Kelvin (`Air_temperature__K ≈ 300`, `Process_temperature__K ≈ 310`). The system SHALL convert stored Celsius values to Kelvin as `K = C + 273.15` at exactly one place — the construction of the feature matrix — and SHALL NOT convert anywhere else. Feeding Celsius to the booster produces no exception and no log line, so the system SHALL additionally assert, at that same boundary, that both temperature columns fall inside a plausible absolute-temperature band before any row is scored, and SHALL fail the run rather than score outside it.

The obvious alternative guard — asserting that the resulting fleet scores are not all identical — SHALL NOT be relied upon. It was measured against this model and does not work: with Celsius input the remaining five features still discriminate, so the fleet comes back with 51 distinct scores out of 70 and a standard deviation within 0.002 of the correct one, while 10 of 70 elevators land in the wrong risk band. Corrupted output that passes every distributional check is the reason the guard has to sit on the input, not on the output.

#### Scenario: Celsius is converted once on the way into the model
- **WHEN** a feature matrix is built from a reading with `ambient_temperature_c` of `27.0`
- **THEN** the `Air_temperature__K` column holds `300.15`
- **AND** no other stage of the run applies a further offset

#### Scenario: An unconverted temperature is rejected before scoring
- **WHEN** a feature matrix is built in which a temperature column falls outside the plausible absolute-temperature band
- **THEN** the run fails with an error naming the column and the offending value
- **AND** no elevator is scored, and no score, feature or trend point is written

#### Scenario: Plausible Kelvin values pass the boundary check
- **WHEN** a feature matrix is built from readings between -40 °C and 80 °C
- **THEN** every temperature column lands inside the accepted band
- **AND** the run proceeds

### Requirement: The feature matrix follows the booster's own column order
The system SHALL build the feature matrix in the order reported by the loaded booster's `feature_names`, and SHALL NOT rely on a hardcoded column list. A silently reordered column produces a valid-looking score from the wrong feature values.

#### Scenario: Columns are ordered by the model, not by the caller
- **WHEN** a feature matrix is built for scoring
- **THEN** its column order equals the booster's `feature_names`

#### Scenario: A missing feature is an error, not a default
- **WHEN** the booster expects a feature the mapping cannot supply
- **THEN** the run fails with an explicit error naming that feature

### Requirement: Scoring runs in a dedicated service that the backend can survive without
The system SHALL compute scores and feature contributions in a separate stateless service exposing `POST /score`, which takes feature names and rows and returns scores, contributions and a model version, and which has no database access. The backend SHALL reach it over HTTP, and SHALL translate a connection failure or timeout into HTTP 503 — never HTTP 500 and never a stack trace — because the service is deliberately absent in production.

#### Scenario: The backend scores a batch through the inference service
- **WHEN** an inference run is triggered and the inference service is reachable
- **THEN** the backend sends one request containing the feature names and one row per in-scope elevator
- **AND** it receives one score and one contribution vector per row

#### Scenario: The inference service is unreachable
- **WHEN** an inference run is triggered and the inference service refuses the connection
- **THEN** the endpoint responds with HTTP 503
- **AND** no elevator score, feature or trend point is modified

#### Scenario: The inference service times out
- **WHEN** the inference service does not respond within the configured timeout
- **THEN** the endpoint responds with HTTP 503
- **AND** the database is left exactly as it was

### Requirement: Contributions are exact TreeSHAP from the booster itself
The system SHALL obtain feature contributions from `Booster.predict(..., pred_contribs=True)`, which returns exact TreeSHAP values, rather than from the separate `shap` package. The top three features by absolute contribution SHALL be persisted with impacts normalised to sum to 1.0, and a run SHALL assert that sum lies within `[0.99, 1.01]`, matching the assertion the offline script already makes.

#### Scenario: Three features are persisted per scored elevator
- **WHEN** an elevator is scored
- **THEN** exactly three features are persisted for it
- **AND** their impacts sum to within 0.01 of 1.0
- **AND** each carries a direction of `increases` or `decreases` matching the sign of its contribution

### Requirement: Online and offline scoring cannot drift
The feature mapping, value formatting, risk-level thresholds and natural-language explanation SHALL live in a single module imported by both `backend/ml/generate_predictions.py` and the online inference service. Duplicating them would let the same reading render a different displayed value online and offline, which no test would catch. The extracted scorer SHALL reproduce the committed `predictions.json` risk scores to within 1e-6.

#### Scenario: The refactored offline script reproduces its committed output
- **WHEN** `generate_predictions.py` is run after the extraction with its seeded RNG
- **THEN** every model-derived field of the regenerated `predictions.json` — `risk_score`, `risk_level`, `features`, `trend` and `nl_explanation` — is identical to the committed file for all 100 elevators
- **AND** the only field permitted to differ is `last_visit_date`, which `_days_ago()` derives from the current date and which no seed can pin

#### Scenario: The online scorer reproduces committed scores
- **WHEN** the inference service scores the feature vectors behind the committed predictions
- **THEN** each score matches the committed `risk_score` to within 1e-6

### Requirement: Only in-scope elevators with data in the window are re-scored
The system SHALL re-score only elevators marked in model scope, aggregating each one's readings over the run window. An in-scope elevator with no readings in the window SHALL be skipped entirely — not scored, not trend-shifted, not zeroed — so that a unit which stopped reporting appears stale rather than suddenly low-risk. Out-of-scope elevators SHALL never be touched.

#### Scenario: An out-of-scope elevator is left alone
- **WHEN** a run executes and an out-of-scope elevator has telemetry in the window
- **THEN** its risk score, features and trend are unchanged

#### Scenario: An in-scope elevator with no telemetry is skipped
- **WHEN** a run executes and an in-scope elevator has no readings in the window
- **THEN** its risk score, features and trend are unchanged
- **AND** the run reports it as skipped rather than failing

#### Scenario: Aggregation summarises the window
- **WHEN** an in-scope elevator has several readings in the window
- **THEN** its temperatures, speed and torque are averaged
- **AND** its cumulative run hours are taken as the maximum
- **AND** the number of readings that fed the score is reported

#### Scenario: Missing cumulative run hours fall back to the documented proxy
- **WHEN** an elevator's readings carry no `motor_run_hours_cumulative`
- **THEN** the run derives motor life from age, average hourly trips and the building-type run parameters
- **AND** uses the same proxy the offline script uses, so online and offline agree

### Requirement: The risk level is derived by the existing rule
The system SHALL derive `risk_level` from the score using the service layer's existing threshold rule (`high` above 0.80, `medium` from 0.50 to 0.80, `low` below 0.50) rather than reimplementing it.

#### Scenario: Thresholds match the existing rule
- **WHEN** scores of 0.85, 0.60 and 0.20 are persisted by a run
- **THEN** their levels are `high`, `medium` and `low` respectively

### Requirement: The six-day trend window shifts on date change, not on every run
`ElevatorTrendPoint` holds exactly six points per elevator with `day_index` 0 to 5, where index 5 is today. Because a run may fire more than once a day — a daily schedule plus manual runs during a demo — the system SHALL overwrite index 5 when the newest existing point already belongs to today, and SHALL shift the window and append only when it belongs to an earlier day. The shift SHALL be performed by deleting all six rows and inserting six within the run's transaction, never by decrementing `day_index` in place: the table's unique constraint on `(elevator_id, day_index)` is checked per row and non-deferrable, so an in-place decrement can raise a duplicate-key violation depending on row order even though the final state is unique.

#### Scenario: A second run on the same day overwrites today's point
- **WHEN** a run executes and the newest trend point for an elevator is dated today
- **THEN** the point at index 5 is replaced with the new score
- **AND** the trend still holds exactly six points
- **AND** indices 0 to 4 are unchanged

#### Scenario: The first run of a new day shifts the window
- **WHEN** a run executes and the newest trend point is dated before today
- **THEN** the oldest point is dropped and the new score is appended at index 5
- **AND** the trend still holds exactly six points

#### Scenario: Repeated shifts never violate the unique constraint
- **WHEN** the trend window is shifted ten times in succession for the same elevator
- **THEN** every shift succeeds without a constraint violation
- **AND** the trend holds exactly six points after each one
- **AND** index 5 always equals the score written by that shift

### Requirement: A run is atomic and never overlaps another run
The system SHALL apply all score, feature and trend changes for a run inside a single transaction, so that a failure part-way through leaves no fleet in which some elevators are scored from the new window and others from the previous one. The run has no transaction of its own — the request-scoped session commits only after the handler returns — so a failing run SHALL raise rather than return a summary; swallowing its own error would let the request complete and commit whatever partial state the loop had written, under a 200.

The system SHALL also serialise concurrent runs for the duration of the transaction. Two overlapping runs each read `last_scored_at` before the other commits, both conclude the elevator has not been scored today, and both shift the trend window — advancing a single day twice and dropping the oldest real point. This is precisely the overlap the date-change rule exists to make safe (a manual trigger landing on top of the schedule), so the rule requires the lock in order to hold.

#### Scenario: A failure mid-run leaves no partial state
- **WHEN** a run fails after scoring some elevators but before completing
- **THEN** no elevator's score, features or trend points are changed
- **AND** the failure propagates to the caller rather than being reported as a completed run

#### Scenario: A degenerate contribution vector is rejected, not divided by
- **WHEN** the scoring service returns a contribution vector whose top three magnitudes sum to zero
- **THEN** the run fails with an explicit error about normalisation
- **AND** not with an unhandled division by zero

#### Scenario: Two overlapping runs do not double-shift the trend
- **WHEN** two inference runs are triggered concurrently
- **THEN** the second waits for the first to complete
- **AND** it observes the first run's `last_scored_at`, so the trend window advances once for the day
- **AND** both runs report success
