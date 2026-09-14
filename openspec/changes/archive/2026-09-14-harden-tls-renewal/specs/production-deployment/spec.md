# Spec Delta: production-deployment

> The capability's main spec is migrated in this change from the legacy `S1…S9`
> prose format to the `Requirement` / `Scenario` schema, because it is the only
> capability `openspec validate` rejects. The requirement below **replaces legacy
> scenario `S7 — Certificate auto-renewal`**. The other eight scenarios are
> carried over with their meaning unchanged and are deliberately not restated
> here as additions — see `design.md` §8.

## MODIFIED Requirements

### Requirement: The production certificate renews itself without human intervention
The system SHALL renew the production TLS certificate before expiry with no
operator action, and the mechanism that does so SHALL satisfy all of the
following:

- Its definition SHALL live in version control and SHALL be installed onto the
  host by the deployment pipeline, so that it is reproducible on a rebuilt
  instance and visible to the test suite.
- It SHALL invoke the certbot binary by **absolute path**. An invocation that
  relies on the scheduler's `PATH` is non-conforming, whether or not it happens
  to work in an interactive shell.
- It SHALL attempt renewal at least twice per day, and SHALL run a trigger that
  was missed while the instance was powered off.
- Reloading the web server SHALL be performed by certbot on successful renewal,
  not by a shell operator chained to the renewal command, and SHALL require no
  controlling terminal.
- Exactly one renewal mechanism SHALL be active in root's crontab and the
  system timers. `/etc/cron.d`, `/etc/crontab` and other users' crontabs are
  neither inspected nor claimed.
- Installation SHALL exercise the mechanism by running it once in the unit's own
  environment, and SHALL fail when that run fails. Any previous mechanism SHALL
  be removed only after that run has succeeded, so a host that cannot renew
  keeps whatever was renewing before rather than being left with nothing.

Verification of this requirement SHALL be performed under the environment the
scheduler provides, not in an interactive shell. A dry run typed by an operator
is **not** evidence for it: that is what was accepted for the legacy scenario,
and the certificate then went 93 days without a renewal.

#### Scenario: Renewal succeeds under the scheduler's environment
- **WHEN** renewal is invoked with the environment the scheduler provides, with
  no inherited shell configuration and a `PATH` of `/usr/bin:/bin`
- **THEN** certbot executes and reports the renewal check as successful
- **AND** an invocation naming the binary without a path fails, and is therefore
  not what the installed unit contains

#### Scenario: A renewed certificate reaches the running web server
- **WHEN** a renewal completes successfully
- **THEN** certbot runs the deploy hook that reloads nginx, with no terminal
  attached
- **AND** the certificate presented to clients afterwards is the renewed one

#### Scenario: A trigger missed while the instance was off is caught up
- **WHEN** the scheduled time passes while the instance is powered off
- **THEN** the renewal check runs after the instance next boots, rather than
  waiting for the following scheduled time

#### Scenario: Only one mechanism renews the certificate
- **WHEN** the renewal configuration has been installed
- **THEN** no entry invoking certbot remains in root's crontab, including one
  reformatted beyond the exact wording of the entry that failed (an absolute
  path, a reordered flag)
- **AND** the previous crontab content has been preserved as a backup that a
  later run cannot overwrite

#### Scenario: Installation proves the unit can renew before trusting it
- **WHEN** the renewal configuration is installed
- **THEN** the renewal service is run once, in its own environment, and the
  installation fails if that run fails
- **AND** a mechanism that was renewing before is left in place when it does

#### Scenario: A hand edit on the host does not survive
- **WHEN** the installed unit or hook is edited directly on the instance
- **THEN** the next deployment restores it from version control

#### Scenario: A reload that fails does not pass silently
- **WHEN** a renewal succeeds but the web server cannot be reloaded
- **THEN** the failure is reported as an error by the renewal run and recorded in
  the certbot log
- **AND** the externally scheduled expiry check reports the stale served
  certificate while there is still time to act on it

## ADDED Requirements

### Requirement: Certificate expiry is detected from outside the host before it happens
The system SHALL check, from outside the production instance and at least once
per day, the certificate that each production hostname actually **serves**, and
SHALL fail when fewer than 21 days remain before its expiry.

The threshold SHALL sit inside the renewal window — renewal begins at 30 days
remaining — so that a failure means the renewal mechanism is broken rather than
that renewal is merely due. The check SHALL validate the served chain without
trust overrides, SHALL fail rather than pass when the host cannot be reached, and
SHALL be runnable both on demand and by the deployment pipeline.

The check SHALL be bounded in time. A host that accepts a connection and then
never completes the handshake SHALL fail the check rather than block: an
unbounded check reports nothing, which is the failure mode this requirement
exists to end, and in a serialized deployment pipeline it would also delay every
later deployment behind it.

The subject of the check is the served certificate, not the file on disk: a file
check cannot distinguish a healthy host from one that renewed successfully and is
still presenting the expired certificate it holds in memory.

#### Scenario: A healthy certificate passes on every hostname
- **WHEN** the check runs against `elevator.dsaavedra.dev` and `dsaavedra.dev`
- **THEN** each host's served certificate validates and has at least 21 days
  remaining
- **AND** the check reports the expiry date it read for each host

#### Scenario: A stale served certificate fails even though the file is current
- **WHEN** the certificate on disk has been renewed but the server still presents
  the previous one
- **THEN** the check fails for that hostname

#### Scenario: An unreachable host fails the check
- **WHEN** the TLS connection cannot be established
- **THEN** the check fails, reporting that it could not read a certificate
- **AND** it does not report success for want of an expiry date to compare

#### Scenario: A silent host fails the check instead of hanging
- **WHEN** a host accepts the TCP connection but never completes the TLS handshake
- **THEN** the check fails within seconds, reporting that it could not read a
  certificate

#### Scenario: An untrusted chain fails regardless of the dates
- **WHEN** the served chain does not validate against the public trust store
- **THEN** the check fails even if the certificate's own dates are still in range

#### Scenario: A deployment reports certificate health
- **WHEN** a deployment completes its health check
- **THEN** it runs the same expiry check and reports the result in the run log
