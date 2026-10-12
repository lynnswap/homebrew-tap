class Privateheaderkit < Formula
  desc "Generate searchable private headers and symbol lists for Apple platforms"
  homepage "https://github.com/lynnswap/PrivateHeaderKit"
  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.8.2.tar.gz"
  sha256 "b169e3a11f1b691c26f3db5ee9655624f4ef63d9babc09e9722f91e8f18337cb"
  license "MIT"

  bottle do
    root_url "https://github.com/lynnswap/homebrew-tap/releases/download/privateheaderkit-0.8.2"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "b164382eb11459fbc789719686664d0948e2c2d23db40241cfec5995720d6b9d"
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
