# Embedded in each tool's install.sh by its release packager. Requires Bash 3.2.
set -euo pipefail
formula=$1
shift
case "$formula" in
    xcode-mcpkit|privateheaderkit|custom-xcode-build-service) ;;
    *) echo "Unknown formula: $formula" >&2; exit 1 ;;
esac
if [ "$EUID" -eq 0 ]; then
    if [ -n "${SUDO_UID:-}" ] && [ "$SUDO_UID" != 0 ]; then
        exec /usr/bin/sudo -H -u "#$SUDO_UID" /bin/bash -c "$BASH_EXECUTION_STRING" "$0" "$formula" "$@"
    fi
    echo 'Run this installer as your login user, not root.' >&2
    exit 1
fi
prefix=${PREFIX:-$HOME/.local}
bindir=${BINDIR:-}
dry_run=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --prefix|--bindir)
            [ "$formula" != custom-xcode-build-service ] || { echo "$1 is not supported for this tool." >&2; exit 1; }
            [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "$1 requires a path." >&2; exit 1; }
            case "$1" in
                --prefix) prefix=$2; if [ "$formula" = privateheaderkit ]; then bindir=; fi ;;
                --bindir) bindir=$2 ;;
            esac
            shift 2 ;;
        --help|-h)
            echo "Install lynnswap/tap/$formula with Homebrew and migrate its standalone entry points."
            echo 'Options: --dry-run (report without changing files or running Homebrew)'
            if [ "$formula" != custom-xcode-build-service ]; then
                echo '         --prefix PATH, --bindir PATH (the old standalone installation)'
            fi
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done
bindir=${bindir:-$prefix/bin}
# The Swift standalone installers accepted quoted home-directory paths too.
case "$bindir" in
    '~'|'~/'*) bindir=$HOME${bindir#\~} ;;
    '~'*)
        remainder=${bindir#\~}
        username=${remainder%%/*}
        user_home=$(dscacheutil -q user -a name "$username" | sed -n 's/^dir: //p')
        if [ -n "$user_home" ]; then bindir=$user_home${remainder#"$username"}; fi ;;
esac
case "$bindir" in /*) ;; *) bindir=$PWD/$bindir ;; esac
fail() { echo "$*" >&2; exit 1; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
verify_command() {
    "$@" || {
        result=$?
        echo 'Homebrew installation completed, but verification failed. Standalone entry points are unchanged.' >&2
        exit "$result"
    }
}
if "$dry_run"; then
    echo "Would install lynnswap/tap/$formula, verify it, then migrate recognized standalone entry points."
    if [ "$formula" = custom-xcode-build-service ]; then
        echo "Would ask the installed CLI to migrate its owned standalone selection and command link in $HOME."
    else
        echo "Would inspect: $bindir"
        for name in privateheaderkit xcode-mcp-proxy xcode-mcp-proxy-server XcodeMCPNativeHost.app; do
            case "$formula:$name" in privateheaderkit:privateheaderkit|xcode-mcpkit:xcode-*|xcode-mcpkit:XcodeMCPNativeHost.app)
                if exists "$bindir/$name"; then echo "  Existing entry: $bindir/$name"; fi ;;
            esac
        done
    fi
    exit 0
fi
if ! command -v brew >/dev/null 2>&1; then
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$candidate" ]; then export PATH="${candidate%/*}:$PATH"; break; fi
    done
fi
command -v brew >/dev/null 2>&1 || fail 'Homebrew is required. Install it from https://brew.sh, then rerun this installer.'
brew_root=$(brew --prefix)
brew_root=$(cd "$brew_root" && pwd -P)
# A first install may collide with a standalone command in Homebrew's bin.
# Existing Homebrew upgrades keep their normal linking and failure behavior.
if [ -d "$brew_root/opt/$formula" ]; then
    brew install "lynnswap/tap/$formula"
else
    brew install --skip-link "lynnswap/tap/$formula"
fi
opt=$(brew --prefix "lynnswap/tap/$formula")
case "$opt" in /*) ;; *) fail "Homebrew returned a non-absolute prefix: $opt" ;; esac
if [ "$formula" = custom-xcode-build-service ]; then
    verify_command "$opt/bin/custom-xcode-build-service" --version
    brew link "lynnswap/tap/$formula"
    exec "$opt/bin/custom-xcode-build-service" __migrate-standalone
fi
case "$formula" in
    xcode-mcpkit)
        verify_command "$opt/bin/xcode-mcp-proxy" --version
        verify_command "$opt/bin/xcode-mcp-proxy-server" --version
        [ -d "$opt/libexec/XcodeMCPNativeHost.app" ] || fail 'Homebrew native host is missing. Standalone entry points are unchanged.'
        names=(xcode-mcp-proxy xcode-mcp-proxy-server XcodeMCPNativeHost.app)
        targets=("$opt/bin/xcode-mcp-proxy" "$opt/bin/xcode-mcp-proxy-server" "$opt/libexec/XcodeMCPNativeHost.app") ;;
    privateheaderkit)
        verify_command "$opt/bin/privateheaderkit" --tool-version
        names=(privateheaderkit)
        targets=("$opt/bin/privateheaderkit") ;;
esac
[ -d "$bindir" ] || { brew link "lynnswap/tap/$formula"; echo "Installed $formula with Homebrew; no standalone entry points found."; exit 0; }
bindir=$(cd "$bindir" && pwd -P)
# Never modify a keg, even when --bindir reaches it through a directory symlink.
case "$bindir/" in "$brew_root/Cellar/"*|"$brew_root/opt/"*) fail "Refusing to change Homebrew files in $bindir" ;; esac
paths=()
links=()
for ((i=0; i<${#names[@]}; i++)); do
    path=$bindir/${names[i]}
    target=${targets[i]}
    exists "$path" || continue
    if [ "$path" -ef "$target" ]; then continue; fi
    owned=false
    if [ "$formula" = privateheaderkit ] && [ -L "$path" ]; then
        # This relative link was written by the standalone cohort installer.
        destination=$(readlink "$path")
        if [ "$destination" = ../libexec/privateheaderkit/current/privateheaderkit ]; then owned=true; fi
    elif [ ! -L "$path" ]; then
        # Read identity without executing an old binary or requiring it to work.
        identifier=$(codesign -dv "$path" 2>&1 | sed -n 's/^Identifier=//p') || identifier=
        expected=${names[i]}
        if [ "$expected" = XcodeMCPNativeHost.app ]; then
            expected=com.lynnswap.XcodeMCPNativeHost
            # Source installs before the stable helper identity used Xcode's ID.
            if [ "$identifier" = com.apple.dt.mcp-server ]; then owned=true; fi
        fi
        case "$identifier" in
            "$expected") owned=true ;;
            "$expected"-*)
                # Linker-signed release executables append a UUID to the name.
                suffix=${identifier#"$expected"-}
                if [[ "$suffix" =~ ^[[:xdigit:]]+$ ]]; then owned=true; fi ;;
        esac
    fi
    "$owned" || fail "Unrecognized standalone entry left unchanged: $path. Homebrew is installed at $opt."
    paths+=("$path")
    links+=("$target")
done
[ "${#paths[@]}" -gt 0 ] || { brew link "lynnswap/tap/$formula"; echo "Installed $formula with Homebrew; no migration needed."; exit 0; }
lock=$bindir/.lynnswap-homebrew-migration.lock
mkdir "$lock" || fail "Cannot acquire migration lock: $lock. Check for another installer before removing a stale lock."
backup=
moved=0
complete=false
finish() {
    status=$?
    trap - EXIT HUP INT TERM
    if ! "$complete"; then
        echo "Migration failed; Homebrew remains installed at $opt. Restoring standalone entry points." >&2
        for ((j=moved-1; j>=0; j--)); do
            path=${paths[j]}
            exists "$backup/${path##*/}" || continue
            if [ -L "$path" ] && { [ "$(readlink "$path")" = "${links[j]}" ] || [ "$path" -ef "${links[j]}" ]; }; then
                rm "$path" || { echo "Rollback could not remove $path; backup: $backup" >&2; continue; }
            fi
            if exists "$path"; then
                echo "Rollback left a changed entry untouched: $path; backup: $backup" >&2
            elif ! mv "$backup/${path##*/}" "$path"; then
                echo "Rollback could not restore $path; backup: $backup" >&2
            fi
        done
    fi
    rmdir "$lock" || { echo "Could not remove migration lock: $lock" >&2; status=1; }
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
backup=$(mktemp -d "$bindir/.${formula}-standalone-backup.XXXXXX")
for ((i=0; i<${#paths[@]}; i++)); do
    path=${paths[i]}
    moved=$((moved+1))
    mv "$path" "$backup/${path##*/}"
    if [ "$bindir" != "$brew_root/bin" ] || [ "${path##*/}" = XcodeMCPNativeHost.app ]; then
        ln -s "${links[i]}" "$path"
    fi
done
brew link "lynnswap/tap/$formula"
# Homebrew can already consider a keg linked after an interrupted migration.
for ((i=0; i<${#paths[@]}; i++)); do
    if ! exists "${paths[i]}"; then ln -s "${links[i]}" "${paths[i]}"; fi
done
complete=true
echo "Installed $formula with Homebrew. Existing command paths now follow Homebrew upgrades."
echo "Standalone entry points were saved in: $backup"
echo 'Legacy payloads and generated data were retained. Restart running tools to use the new installation.'
