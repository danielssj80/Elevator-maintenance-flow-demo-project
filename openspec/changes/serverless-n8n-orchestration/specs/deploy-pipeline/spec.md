## ADDED Requirements

### Requirement: Lambda images are published to private ECR and the functions follow them
The system SHALL build the orchestrator and scorer images in CI on every push to `main`, in a workflow separate from the GHCR build. It SHALL push them to their private ECR repositories tagged with the commit SHA, because Lambda pulls neither from GHCR nor from ECR Public.

The separation is deliberate: the application deploy runs when the GHCR build workflow succeeds. A Lambda publish failing inside that workflow would block the application deploy for a reason unrelated to it.

Every Lambda image SHALL be built without provenance or SBOM attestations, in CI and in the bootstrap push script alike. Lambda accepts a single image manifest, and BuildKit wraps the image in an index whenever it attaches attestations. Docker 29 with the containerd store does that by default, even for a plain `docker build`.

Every layer of a Lambda image SHALL be recompressed to gzip when the image is built. The n8n base image ships zstd layers, and a builder that keeps those bytes under a gzip media type produces an image Lambda refuses (`UnsupportedImageLayerDetected`).

It SHALL then point each function at the image of that commit. Once all updates are issued, it SHALL wait until each function reports the update as successful.

ECR SHALL keep only the three most recent images per repository. CI SHALL authenticate through the existing OIDC deploy role, extended with exactly the permissions this requires:
- ECR push to the two repositories;
- `lambda:UpdateFunctionCode` and `lambda:GetFunction` on the two functions.

#### Scenario: A merge publishes both Lambda images and updates both functions
- **WHEN** a commit is pushed to `main`
- **THEN** `elevator-orchestrator:<sha>` and `elevator-scorer:<sha>` exist in ECR
- **AND** each function's image URI ends in that SHA once the workflow finishes

#### Scenario: A Lambda publish failure does not block the application deploy
- **WHEN** the Lambda image workflow fails
- **THEN** the GHCR build and the application deploy still run for that commit

#### Scenario: A failed image build leaves the functions unchanged
- **WHEN** either Lambda image fails to build or push
- **THEN** neither function is updated
- **AND** the workflow fails

#### Scenario: A pushed image is one Lambda accepts
- **WHEN** a Lambda image build is inspected, in the workflow or in the bootstrap push script
- **THEN** it disables provenance and SBOM attestations

#### Scenario: Every layer is what its media type says
- **WHEN** a Lambda image published by CI or the bootstrap script is inspected
- **THEN** every layer is declared `tar+gzip` and its bytes are gzip

#### Scenario: Old images are expired
- **WHEN** a repository holds more than three images
- **THEN** the lifecycle policy expires the oldest beyond three

#### Scenario: The deploy role cannot touch other functions
- **WHEN** the deploy role's policy is inspected
- **THEN** its Lambda and ECR permissions are scoped to the two functions and two repositories, with no wildcard resource
