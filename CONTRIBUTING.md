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

After Formula PR checks pass, **brew pr-pull** prepares a publication candidate
and waits for the **homebrew-publish** Environment approval. Review the PR head
SHA, successful CI run/attempt and bottle artifact digest in the Actions summary,
then choose **Review deployments → Approve and deploy**.
GitHub sends a deployment-review request to the required reviewer. Enable
deployment-review push notifications in GitHub Mobile to receive this approval
request on a phone.

The publisher revalidates that candidate, downloads the exact tested artifact and
checks the Formula against Homebrew's tested recipe before uploading bottles and
updating `main`. The publication merge preserves the reviewed PR head in `main`
history so GitHub marks the PR as merged. Each push checks changes from the main
commit recorded before that merge and binds the push to the checked remote tip.
Concurrent changes to the same Formula require new bottle CI and approval;
unrelated Formula or documentation changes can be preserved during push recovery.
Documentation-only PRs do not publish bottles.

To retry, dispatch **brew pr-pull** on `main` with the Formula PR number and its
full reviewed head SHA. A changed head, newer or failed CI, replaced artifact or
expired artifact requires a new candidate and approval. Bottle artifacts are
retained for 35 days.

In **Settings → Environments → homebrew-publish**, require a maintainer reviewer,
allow only `main` and disable administrator bypass. Leave **Prevent self-review**
off when the sole maintainer also initiates publication. Build and validation
jobs are read-only; only the approved publication job receives Contents write,
attestation and identity-token permissions. No additional token or Environment
secret is needed.

Run the publication guard tests locally with:

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

## Automated maintenance

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
and immutable bottle artifact. Review the Formula and bottle CI when the
`homebrew-publish` approval request arrives; the protected publisher uploads the
tested bottles and merges the PR automatically after approval.
Discovery also starts a missing publisher for successful CI, including a bot PR
approved before this automatic dispatch flow was installed. Existing publication
runs and actual CI/publication failures are not repeatedly retried.

Keep workflow actions and the Renovate image pinned to immutable identities.
Configuration changes run strict validation and a read-only full dry run; trusted
configuration controls Renovate's manager and file scope.
