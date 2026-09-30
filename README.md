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

After Formula PR checks pass, the **brew pr-pull** workflow prepares a read-only
publication candidate and waits for the **homebrew-publish** Environment approval.
Review its PR-head SHA, successful CI run/attempt, and bottle artifact digest in
the Actions summary, then choose **Review deployments → Approve and deploy**.
Publication revalidates the candidate, downloads the exact tested artifact ID,
and uses `brew pr-pull` with the reviewed head and uniquely named artifact. It
publishes the bottles, updates the formula's bottle metadata, and merges that
reviewed change.

You can also dispatch **brew pr-pull** on `main` with the Formula PR number and
its full reviewed head SHA. Both inputs are required. A changed head, newer or
failed CI, replaced artifact, or expired artifact stops publication. Review the
new candidate and start a new approval rather than substituting an unreviewed
revision. Bottle artifacts are retained for 35 days. Code/documentation PRs and
CI completions without a Formula publication candidate are skipped.

In **Settings → Environments → homebrew-publish**, require the maintainer as a
reviewer, allow only the `main` branch, and disable administrator bypass. Leave
**Prevent self-review** off when that maintainer also initiates publication.
Build/test jobs and candidate validation are read-only; the short approved
publication job alone receives Contents/Pull requests write, attestation, and
identity-token permissions. No additional token or Environment secret is needed.

Publication guard tests use in-memory GitHub responses and run with:

```sh
python3 -B -m unittest discover -s scripts -p 'test_approved_bottles.py'
```

Once a formula is published, install it with `brew install lynnswap/tap/<name>`.
Use `brew upgrade <name>` and `brew uninstall <name>` to manage it.

See [Homebrew's tap guide](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
and [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook).

## License

MIT. See [LICENSE](LICENSE).
