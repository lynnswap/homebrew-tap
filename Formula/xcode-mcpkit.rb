class XcodeMcpkit < Formula
  desc "Use Xcode build, test, preview, and editing tools through MCP"
  homepage "https://github.com/lynnswap/XcodeMCPKit"
  url "https://github.com/lynnswap/XcodeMCPKit/archive/refs/tags/v0.24.2.tar.gz"
  sha256 "b19156643ea7157ff0d3bd78cc6befde36d9064158a3b78116f0d40e3f6da4dd"
  license "MIT"

  depends_on "python@3.14" => [:build, :test]
  depends_on xcode: ["27.0", :build, :test]
  depends_on arch: :arm64
  depends_on macos: :sequoia

  def install
    system "scripts/build-release.sh", "--version", "v#{version}", "--dist-root", buildpath/"products"
    libexec.install Dir["products/arm64/bin/*"]
    bin.install_symlink libexec/"xcode-mcp-proxy-server"
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
    assert_equal "v#{version}", shell_output("#{bin}/xcode-mcp-proxy-server --version").strip
    assert_equal "xcode-mcp-proxy-server --listen 127.0.0.1:0",
                 shell_output("#{bin}/xcode-mcp-proxy-server --host 127.0.0.1 --port 0 --dry-run").strip
    system "codesign", "--verify", "--deep", "--strict", libexec/"XcodeMCPNativeHost.app"
  end
end
