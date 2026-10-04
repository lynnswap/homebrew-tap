class CustomXcodeBuildService < Formula
  desc "Select a custom Swift Build service for Xcode"
  homepage "https://github.com/lynnswap/swift-build"
  url "https://github.com/lynnswap/swift-build/archive/refs/tags/v0.3.4.tar.gz"
  sha256 "1ef6e5be89f7611d61f5babf9f8a9859acc5d919b1a9d3a16635b1026183b7aa"
  license "Apache-2.0" => { with: "Swift-exception" }

  bottle do
    root_url "https://github.com/lynnswap/homebrew-tap/releases/download/custom-xcode-build-service-0.3.2"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "771dccbe284e32e0fe5724668e37d2bfda826e95dfffd927036517b3cc163535"
  end

  depends_on "python@3.14" => [:build, :test]
  depends_on xcode: ["27.0", :build, :test]
  depends_on arch: :arm64
  depends_on macos: :tahoe

  def install
    distribution = buildpath/"Utilities/CustomXcodeBuildService/Distribution"
    system "python3", distribution/"release.py", "build", "--disable-sandbox",
           "--source-dir", buildpath, "--source-archive", cached_download,
           "--version", "v#{version}", "--output-dir", buildpath/"products",
           "--jobs", ENV.make_jobs
    libexec.install Dir["products/payload/*"]
    # Keep the opt path in the launcher's argv[0] and the saved login configuration.
    bin.write_exec_script opt_libexec/"bin/custom-xcode-build-service"
    pkgshare.install distribution/"release.py" => "verify.py"
    pkgshare.install "Tests/SwiftBuildTests/TestData/CommandLineTool"
  end

  def caveats
    <<~EOS
      Select the service for your macOS user account:
        custom-xcode-build-service use custom
      Restart Xcode, Xcode Service (for MCP), terminals, and AI agents afterward.

      Finish builds before upgrading; then run:
        custom-xcode-build-service reload

      Before uninstalling, restore Xcode's bundled service:
        custom-xcode-build-service use bundled
    EOS
  end

  test do
    assert_equal "v#{version}", shell_output("#{bin}/custom-xcode-build-service --version").strip
    # Xcode's package manifest sandbox cannot nest inside Homebrew's test sandbox.
    system "python3", pkgshare/"verify.py", "verify-payload", "--disable-sandbox", "--payload", libexec,
           "--fixture-dir", pkgshare/"CommandLineTool", "--skip-xcode-package-tests"
  end
end
