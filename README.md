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

Once a formula is published, install it with `brew install lynnswap/tap/<name>`.
Use `brew upgrade <name>` and `brew uninstall <name>` to manage it.

See [Homebrew's tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## License

MIT. See [LICENSE](LICENSE).
