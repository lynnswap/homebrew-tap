# lynnswap Homebrew tap

A shared Homebrew tap for lynnswap's command-line tools.

## Availability

No formulae are published yet. PrivateHeaderKit will be added after its first
source release with Homebrew packaging. Other tools can be added through their
own formula pull requests.

## Maintaining formulae

Each tool has a file under `Formula/`. Build dependencies, installation steps,
and functional tests belong to that formula. The shared workflows check changed
formulae and create bottles for formula pull requests.

The macOS builder uses Apple Silicon macOS 26 with Xcode 26.6. Homebrew registers
the resulting bottles for that build platform; older macOS versions are not
distribution or CI targets of this tap.

For PrivateHeaderKit, use `privateheaderkit.rb` from a published
[PrivateHeaderKit release](https://github.com/lynnswap/PrivateHeaderKit/releases).
Its source URL must already be available. Submit the file as a pull request to
this repository instead of adding it directly to `main`.

After the pull request checks pass, run the **brew pr-pull** workflow with the
pull request number and reviewed head SHA. It publishes the bottles, updates
the formula's bottle metadata, and merges the reviewed change.

Once a formula is published, install it with `brew install lynnswap/tap/<name>`.
Use `brew upgrade <name>` and `brew uninstall <name>` to manage it.

See [Homebrew's tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## License

MIT. See [LICENSE](LICENSE).

## Automated maintenance

Dependabot proposes weekly updates to pinned workflow actions. The
**Propose Homebrew updates** workflow runs Renovate daily at 08:17 Japan time,
with a manual dispatch available on `main`. It uses this repository's
`GITHUB_TOKEN`, proposes updates only for `Formula/privateheaderkit.rb`, and
never merges a PR. Its action and container image are pinned to immutable
identities; review both pins when updating Renovate.

The first Formula must be added from the first published PrivateHeaderKit source
release before Renovate can maintain it. Renovate updates the source URL and
SHA-256; changes to installation, dependencies, or tests must still be reviewed
and synchronized from the source release's Formula.

In **Settings → Actions → General**, keep workflow permissions read-only by
default and enable **Allow GitHub Actions to create and approve pull requests**.
Only the updater job requests Contents and Pull requests write permissions.
PRs created with `GITHUB_TOKEN` require a maintainer to choose **Approve workflows
to run** before their CI starts. Review the resulting Formula change and bottle
CI before publishing; PR creation does not authorize publication.

Renovate configuration is checked by its strict config validator and exercised
in a read-only, full dry-run workflow for configuration changes. Its manager and
file scope are forced by trusted
configuration, and repository-supplied Renovate configuration is ignored.
