class XcodeMcpkit < Formula
  desc "Use Xcode build, test, preview, and editing tools through MCP"
  homepage "https://github.com/lynnswap/XcodeMCPKit"
  url "https://github.com/lynnswap/XcodeMCPKit/archive/refs/tags/v0.21.0.tar.gz"
  sha256 "b1e714c2fb7db31cbdd79e0208ca85c2aa2484f09b63f6719c63c5b210544e39"
  license "MIT"

  bottle do
    root_url "https://github.com/lynnswap/homebrew-tap/releases/download/xcode-mcpkit-0.21.0"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "d0c720e8001a2978ec9f26f28c0e65b3f45eb79a154b3347fec9c65a6cb050a2"
  end

  depends_on "python@3.14" => [:build, :test]
  depends_on xcode: ["27.0", :build, :test]
  depends_on arch: :arm64
  depends_on macos: :sequoia

  def install
    system "scripts/build-release.sh", "--version", "v#{version}", "--dist-root", buildpath/"products"
    libexec.install Dir["products/arm64/bin/*"]
    bin.install_symlink libexec/"xcode-mcp-proxy", libexec/"xcode-mcp-proxy-server"
    pkgshare.install "scripts/smoke-homebrew.py"
    pkgshare.install "Fixtures/ProxyToolVerifierFixture"
  end

  def caveats
    <<~EOS
      Start the server before connecting MCP clients:
        xcode-mcp-proxy-server

      Xcode is required at runtime. Headless tools require Xcode's native service contracts.
      Restart the server after upgrading. If an older standalone installation is on PATH,
      use the Homebrew executable at #{opt_bin}/xcode-mcp-proxy-server.
    EOS
  end

  test do
    %w[xcode-mcp-proxy xcode-mcp-proxy-server].each do |command|
      assert_equal "v#{version}", shell_output("#{bin}/#{command} --version").strip
    end
    assert_equal "xcode-mcp-proxy-server --listen 127.0.0.1:0",
                 shell_output("#{bin}/xcode-mcp-proxy-server --host 127.0.0.1 --port 0 --dry-run").strip
    system "codesign", "--verify", "--deep", "--strict", libexec/"XcodeMCPNativeHost.app"
  end
end
