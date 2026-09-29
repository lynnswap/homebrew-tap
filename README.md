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

For PrivateHeaderKit, use `privateheaderkit.rb` from a published
[PrivateHeaderKit release](https://github.com/lynnswap/PrivateHeaderKit/releases).
Its source URL must already be available. Submit the file as a pull request to
this repository instead of adding it directly to `main`.

After the pull request checks pass, run the **brew pr-pull** workflow with the
pull request number and reviewed head SHA. It publishes the bottles, updates
the formula's bottle metadata, and merges the reviewed change.

Tools that build with a newer SDK but also run on older macOS versions may opt
into `.github/bottle-compatibility.json`. Each entry names the bottle tag and the
Apple Silicon runners that must pass ordinary bottle installation and `brew test`.
PrivateHeaderKit uses `arm64_sequoia` and is checked on macOS 15, 26, and 27.
Other formulae keep the platform selected by `brew test-bot` unless configured.

The compatibility step changes the published filenames and bottle JSON, preserving
the archive bytes, SHA-256, recorded build environment, and provenance metadata.
It does not rebuild or repackage the binaries on older hosts. All compatibility
jobs must pass before running the publication workflow. This is a tap-maintainer
compatibility declaration, not a guarantee provided by Homebrew or a requirement
for admission to `homebrew/core`.

Once a formula is published, install it with `brew install lynnswap/tap/<name>`.
Use `brew upgrade <name>` and `brew uninstall <name>` to manage it.

See [Homebrew's tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## License

MIT. See [LICENSE](LICENSE).
