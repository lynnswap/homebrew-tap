# Maintaining this tap

## Formulae

Add or update each tool in its own `Formula/<name>.rb` pull request. Keep build
dependencies, installation steps and functional tests in the Formula. Source URLs
must be public before bottle CI runs.

The shared **brew test-bot** workflow checks changed formulae and builds bottles.
Its current macOS builder uses Apple Silicon macOS 26 with Xcode 26.6; bottles
are registered for that build platform. Each tool documents its own requirements.

For PrivateHeaderKit, start with `privateheaderkit.rb` from its
[published release](https://github.com/lynnswap/PrivateHeaderKit/releases).
Keep its installation, dependency and test changes synchronized with that recipe.

See Homebrew's [tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## Publishing bottles

After Formula PR checks pass, **brew pr-pull** prepares a publication candidate
and waits for the **homebrew-publish** Environment approval. Review the PR head
SHA, successful CI run/attempt and bottle artifact digest in the Actions summary,
then choose **Review deployments → Approve and deploy**.

The publisher revalidates that candidate, downloads the exact tested artifact and
checks the Formula against Homebrew's tested recipe before uploading bottles and
updating `main`. The publication merge preserves the reviewed PR head in `main`
history so GitHub marks the PR as merged. Concurrent changes to the same Formula require new bottle CI and
approval; unrelated Formula or documentation changes can be preserved during push
recovery. Documentation-only PRs do not publish bottles.

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
python3 -B -m unittest discover -s scripts -p 'test_approved_bottles.py'
```

## Automated maintenance

Dependabot proposes weekly updates to workflow actions. **Propose Homebrew
updates** runs Renovate daily at 08:17 Japan time or on manual dispatch from
`main`. Renovate currently maintains only `Formula/privateheaderkit.rb`, updating
its source URL and SHA-256 through PRs without automerging. Adding a tool does not
automatically enable Renovate for it; review the scope in
[.github/renovate-config.json](.github/renovate-config.json) separately.

In **Settings → Actions → General**, keep workflow permissions read-only by
default and enable **Allow GitHub Actions to create and approve pull requests**.
Renovate uses this repository's `GITHUB_TOKEN`; PRs it creates require a maintainer
to choose **Approve workflows to run** before CI starts. Review the Formula and
bottle CI before approving publication.

Keep workflow actions and the Renovate image pinned to immutable identities.
Configuration changes run strict validation and a read-only full dry run; trusted
configuration controls Renovate's manager and file scope.
