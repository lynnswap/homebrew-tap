# Maintaining this tap

## Formulae

Add or update each tool in its own `Formula/<name>.rb` pull request. Keep build
dependencies, installation steps and functional tests in the Formula. Source URLs
must be public before bottle CI runs.

The shared **brew test-bot** workflow checks changed formulae and builds bottles.
PrivateHeaderKit builds on Apple Silicon macOS 26 with Xcode 26.6, matching its
source release's published-bottle verification. Custom Xcode Build Service uses
the `xcode-27` runner with Xcode 27.0 (macOS 27), targeting macOS 26. Its bottle is
registered as `arm64_tahoe`, so Homebrew installs it on macOS 26 and later.
The receipt retains the actual build environment. CI also installs that bottle
on macOS 26 without forcing bottle selection and runs the packaged verification.
Each tool documents its own requirements. Keep Formulae requiring
different builders in separate PRs; `scripts/formula_builder.py` selects the
builder from the changed Formula paths.

For PrivateHeaderKit, use the verified `privateheaderkit.rb` from its release
workflow and follow the owning project's
[source-preparation guide](https://github.com/lynnswap/PrivateHeaderKit/blob/main/CONTRIBUTING.md#releases).
Keep installation, dependency and test changes synchronized with that recipe.

For Custom Xcode Build Service, use the generated
`custom-xcode-build-service.rb` from its first `v*` release. The recipe reads the
source commit from the downloaded Git archive, so URL/checksum updates do not
leave stale commit metadata behind. See its
[distribution guide](https://github.com/lynnswap/swift-build/blob/main/Utilities/CustomXcodeBuildService/README.md#releases).

See Homebrew's [tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## Publishing bottles

Native Formula CI calls **brew pr-pull** as its final dependent job after the
producer checks and applicable macOS 26 bottle installation succeed. It does not
rely on a `workflow_run` event to start publication for a dispatched native PR.
Standalone publication and periodic discovery remain recovery paths for already
completed CI. If the dependent publisher fails, a manual publication retry reuses
its successful producer checks and original bottle artifact; real producer
failures still require new CI. Periodic discovery does not retry real publication
failures automatically. The final job verifies the canonical parent run, completed producer
checks, PR head, and immutable artifact before any publication side effects.

After Formula PR checks pass, **brew pr-pull** prepares a publication candidate
from the same-repository maintainer/bot PR and its successful CI run. Review the
head SHA, CI run/attempt, and exact bottle artifact digest in the Actions summary.
The tested candidate is published automatically; the `homebrew-publish`
Environment retains its main-only branch policy without a required reviewer.
The owning source repository requires approval before using its GitHub App key
to start a tap update. XcodeMCPKit also requires `release-signing` approval in
this tap before Developer ID and notarization keys are used; Formula publication
and merge remain automatic after the signed bottle passes installation checks.

The publisher revalidates that candidate, downloads the exact tested artifact and
checks the Formula against Homebrew's tested recipe before uploading bottles and
updating `main`. The publication merge preserves the reviewed PR head in `main`
history so GitHub marks the PR as merged. Each push checks changes from the main
commit recorded before that merge and binds the push to the checked remote tip.
Concurrent changes to the same Formula require new bottle CI and validation;
unrelated Formula or documentation changes can be preserved during push recovery.
Documentation-only PRs do not publish bottles.

To retry, dispatch **brew pr-pull** on `main` with the Formula PR number and its
full reviewed head SHA. A changed head, newer or failed CI, replaced artifact or
expired artifact requires new candidate validation. Bottle artifacts are
retained for 35 days.

In **Settings → Environments → homebrew-publish**, allow only `main` and leave
required reviewers and wait timers empty. Build and validation jobs are read-only;
only the publication job receives Contents write, attestation, and identity-token
permissions. Publication does not require an additional token or secret.

For XcodeMCPKit, configure a separate `release-signing` Environment with a required
maintainer reviewer, `main` as its only deployment branch, and administrator
bypass disabled. The sole maintainer may approve their own run. Set secrets
`DEVELOPER_ID_P12_BASE64`, `DEVELOPER_ID_P12_PASSWORD`, and
`NOTARY_API_PRIVATE_KEY`; set variables `APPLE_TEAM_ID` (`58KPFKMJJW`),
`NOTARY_API_KEY_ID`, and `NOTARY_API_ISSUER_ID`. Build, PR, and installation jobs
never receive these secrets. The signing job checks out trusted workflow scripts,
revalidates the approved artifact, and handles its payload only as data. It imports
the certificate into a temporary keychain and removes its credentials before
uploading the signed artifact.

Only same-repository PRs authored by `lynnswap` or `github-actions[bot]` can enter
CI and publication. Fork PRs and other authors are rejected even if a CI completion
or manual publication request is received. This also excludes Dependabot proposals.
The public tap remains forkable; a fork is never an accepted publication source.
The sole repository collaborator with write access is `lynnswap`; GitHub Actions
receives write permission only in its trusted maintenance/publication jobs.
GitHub's collaborators-only interaction limit expires after six months; the CI
and publication policy remains in code after that limit expires.

Run the publication guard tests locally with:

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

## Automated maintenance

### Approved XcodeMCPKit releases

XcodeMCPKit dispatches `update-formula.yml` from its approved `release-publish`
job using a GitHub App token scoped to this tap and `Actions: write`. The request
contains the public source tag, approved commit, source archive SHA-256, and
prepared Formula SHA-256. The trusted updater checks those values, reproduces the
Formula from the tagged template, and creates or reuses a native Formula PR.
The first release uses this same path; no placeholder Formula is needed.

The updater starts the existing read-only bottle workflow with the PR number and
full head SHA. XcodeMCPKit builds on `xcode-27` and keeps the builder's native
bottle tag. It does not run the custom build service's retagging or macOS 26 test.
Its Formula checks the installed CLI versions, options, and native signature.
A separate read-only job installs the built bottle and exercises direct and
proxy MCP sessions against a disposable project outside Homebrew's test sandbox.
After that job succeeds, review the exact artifact ID and SHA-256 digest in the
publication summary and approve `release-signing`. The signing job signs both
commands, nested Swift libraries, and the helper, submits the payload to Apple,
and staples the accepted ticket to the app. The helper keeps signing identifier
`com.lynnswap.XcodeMCPNativeHost` so Xcode recognizes it across upgrades.

A separate job installs the signed bottle, checks Developer ID, Team ID, hardened
runtime, and notarization, and repeats the native/proxy smoke tests. The publisher
then uploads that exact signed artifact and merges the Formula PR automatically.
The bottle must have `any_skip_relocation`: relocation could invalidate the
Developer ID signature. Other Formulae retain their existing publication path.
A retry can reuse the tested raw bottle; if signing runs again it requires a new
Environment approval. Rerunning only failed downstream jobs preserves the signed
artifact from the successful signing job.

The updater uses this tap's `GITHUB_TOKEN` for its PR. Repeated source requests
reuse the open matching proposal and its CI, while a changed or closed proposal
stops with a diagnostic. XcodeMCPKit is not part of the Renovate source discovery
or update scope. The existing tools below retain their Renovate flow.

### Renovate-managed tools

Dependabot proposes weekly updates to workflow actions. **Propose Homebrew
updates** runs Renovate daily at 08:17 Japan time or on manual dispatch from
`main`. A short read-only check also runs every 15 minutes: a newer public stable
tag for a configured tool starts Renovate unless an open Formula PR already proposes
it. Existing proposals do not repeatedly start the update writer. After discovery
or maintenance, a separate trusted job starts read-only bottle CI for native
Formula proposals that do not already have CI. Source tags initiate tap builds before core
stable publication; the daily/manual runs still perform regular maintenance.
Maintenance and discovery runs share a FIFO queue, so a discovery tick cannot
replace a pending manual or daily maintenance request.

A prepared source can dispatch **Propose Homebrew updates** immediately on
`main` with `source_repository` and `source_tag`. The read-only discovery job
accepts only a configured source and a public stable `vX.Y.Z` tag, then checks
whether its Formula needs a proposal. A repeated notification reuses an existing
proposal. A valid release notification removes Renovate's hourly PR throttle for
that run; scheduled and ordinary manual maintenance keep the configured limit.
The existing native PR CI and publisher still own validation, bottle publication,
and merge. Periodic discovery remains available for recovery.

Renovate maintains `Formula/privateheaderkit.rb` and
`Formula/custom-xcode-build-service.rb`, updating their source URL and SHA-256
through PRs without automerging. Both use stable `vX.Y.Z` source tags; older
`custom-v*` build-service tags are not update candidates. Discovery starts for a
tool after its first released Formula is added; absent recipes are not synthesized.
For a new tool, update `scripts/prepared_update.py` and the scope in
[.github/renovate-config.json](.github/renovate-config.json) separately.

In **Settings → Actions → General**, keep workflow permissions read-only by
default and enable **Allow GitHub Actions to create and approve pull requests**.
Renovate uses this repository's `GITHUB_TOKEN`. Its native Formula PRs run CI
through an automatic `workflow_dispatch` on `main`, with their PR number and full
head SHA pinned in the server-rendered run title. This does not require a separate
**Approve workflows to run** action. The read-only builder validates the native
proposal, checks out that exact head and tests the named Formulae. Publication
accepts only successful CI from the canonical workflow bound to that same PR head
and immutable bottle artifact. The publisher uploads the exact tested bottles and merges the PR automatically
after successful CI and candidate validation.
Discovery also starts a missing publisher for successful CI, including a bot PR
approved before this automatic dispatch flow was installed. Existing publication
runs and actual CI/publication failures are not repeatedly retried.

Keep workflow actions and the Renovate image pinned to immutable identities.
Configuration changes run strict validation and a read-only full dry run; trusted
configuration controls Renovate's manager and file scope.

## Standalone installer entry points

`scripts/install-homebrew.sh` owns the shared installation and migration behavior
for XcodeMCPKit, PrivateHeaderKit, and Custom Xcode Build Service. Source release
packagers fetch this file at a full tap commit SHA, verify its SHA-256, and embed
it in a POSIX `install.sh` launcher that invokes macOS Bash. No migration code is
downloaded when a user runs the generated installer. The first argument to the
embedded script is the formula name; remaining arguments are installer options.

The installer runs outside the Homebrew sandbox. Already linked Formula upgrades use
Homebrew's normal linking behavior. First installations and retries with an
unlinked keg defer linking to avoid collisions with standalone commands. It installs and checks the new
CLI before replacing recognized standalone commands with stable Homebrew `opt`
links. Existing prefixes and bindirs can be supplied for XcodeMCPKit and
PrivateHeaderKit. Fresh installations do not create legacy aliases. Existing
aliases are idempotent and can be removed when callers no longer use those paths.
`--dry-run` reports the targeted locations without running Homebrew or writing files.

Replaced entries are retained in a private backup directory beside the old
commands. A failed switch attempts to restore them and reports any rollback
failure with the backup path. PrivateHeaderKit payloads and generated headers
remain in place, including resources an already running command may need. Custom
Xcode Build Service delegates selection migration to its packaged CLI through
`__migrate-standalone`; that command owns the installation lock, settings, and
rollback. Neither the shared installer nor the formula changes shell profiles
or unrelated client configurations. Running clients need a restart.

Run `brew style scripts/install-homebrew.sh` for the ShellCheck and Homebrew
formatting checks required by `brew test-bot --only-tap-syntax`.
Run the installer fixtures with the script tests above. They use temporary homes,
commands, and Homebrew prefixes; they never migrate the developer's installation.
Each source repository must update its pin deliberately and include `install.sh`
in its verified release checksums. Merge shared changes before publishing a
source release that uses the new pin.

The Custom Xcode Build Service installer must first ship in a source release
whose CLI implements `__migrate-standalone` (v0.3.4 does not). Its source release
workflow must verify publication of that release's Homebrew formula and bottle
before publishing `install.sh`. Adding the shared script here does not publish
an installer or change the current formula; the corresponding source integration
is tracked in [swift-build #38](https://github.com/lynnswap/swift-build/issues/38).
