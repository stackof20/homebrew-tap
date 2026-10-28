cask "stackof20" do
  version "1.0.0,19"
  sha256 "7f3ce52a05c6a7b188aad98370715e19d79c573f4b5628a0b1d18f808ea0eefa"

  url "https://github.com/stackof20/stackof20/releases/download/v#{version.csv.first}-#{version.csv.second}/stackof20-#{version.csv.first}-#{version.csv.second}.zip"
  name "stackof20"
  desc "Work through your inbox in small stacks"
  homepage "https://stackof20.com/"

  livecheck do
    url "https://stackof20.com/updates/v1/appcast.xml"
    strategy :sparkle
  end

  auto_updates true
  depends_on arch: :arm64
  depends_on macos: :sequoia

  app "stackof20.app"
end
