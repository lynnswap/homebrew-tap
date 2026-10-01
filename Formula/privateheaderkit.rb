class Privateheaderkit < Formula
  desc "Generate searchable private headers and symbol lists for Apple platforms"
  homepage "https://github.com/lynnswap/PrivateHeaderKit"
  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.7.1.tar.gz"
  sha256 "d4a8eb78003999b0f09702593d87cb606e24e6e513cedf2d6b63f989734aef9c"
  license "MIT"

  bottle do
    root_url "https://github.com/lynnswap/homebrew-tap/releases/download/privateheaderkit-0.7.0"
    rebuild 1
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "6911eed400f033160b0198ddd210826c43431308016c0d1eb69eb637d89ab472"
  end

  depends_on xcode: ["26.4", :build]
  depends_on arch: :arm64
  depends_on macos: :sonoma

  def install
    system "scripts/build-release.sh", "--version", "v#{version}",
           "--output-dir", buildpath/"products"
    libexec.install Dir["products/*"]
    bin.install_symlink libexec/"privateheaderkit"
  end

  test do
    (testpath/"Fixture.m").write <<~OBJC
      #import <Foundation/Foundation.h>
      @interface PHKFormulaFixture : NSObject
      @property(nonatomic) NSInteger value;
      @end
      @implementation PHKFormulaFixture
      @end
      int PHKFormulaSymbol(void) { return 42; }
    OBJC
    system ENV.cc, "-dynamiclib", "-fobjc-arc", "-framework", "Foundation",
           "Fixture.m", "-o", "libFixture.dylib"
    system libexec/"privateheaderkit-raw-helper", "-o", testpath/"headers", testpath/"libFixture.dylib"
    assert_match "@interface PHKFormulaFixture", (testpath/"headers/PHKFormulaFixture.h").read
    assert_match "PHKFormulaSymbol",
                 shell_output("#{bin}/privateheaderkit search PHKFormulaSymbol --in #{testpath}/headers")
  end
end
