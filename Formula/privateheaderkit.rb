class Privateheaderkit < Formula
  desc "Generate searchable private headers and symbol lists for Apple platforms"
  homepage "https://github.com/lynnswap/PrivateHeaderKit"
  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.7.0.tar.gz"
  sha256 "f852d894259e126220799bfdabb92d047a0bce0bd17906849fb010a41159b230"
  license "MIT"

  bottle do
    root_url "https://github.com/lynnswap/homebrew-tap/releases/download/privateheaderkit-0.7.0"
    sha256 cellar: :any_skip_relocation, arm64_tahoe: "77ceef31d4778fac45bc248a6813ba91753fc18a2ac8f77512852b7b9bbc279d"
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
