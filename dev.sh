#!/usr/bin/env bash
# ---------------------------------------------------------------------------
#  dev.sh — ebook2pdf development lifecycle script
#
#  Usage:  ./dev.sh <command>
#
#  Commands:
#    setup          Install system + Python dependencies
#    build          Build Python package (wheel + sdist)
#    deb            Build .deb package
#    install        Install .deb package system-wide
#    test           Run a quick smoke-test on one EPUB
#    font-audit     Run conversion + post-conversion font-size audit on one EPUB
#    clean          Remove build artifacts
#    git-init       Initialise git repo and create initial commit
#    git-remote     Configure git remote (GitHub or GitLab)
#    commit         Stage all changes and commit
#    push           Push current branch to remote
#    release        Run full release flow: test → version bump → commit → tag → push
#    release-bump   Bump version (patch/minor/major or set explicitly)
#    release-tag    Create and push annotated semver tag
#    release-start  Create release branch from tag
#    changelog      Show change log since last tag
#    full           Run: clean → setup → build → deb → test
#    help           Show this message
#
#  Examples:
#    ./dev.sh setup
#    ./dev.sh deb
#    ./dev.sh git-init
#    ./dev.sh git-remote github myuser ebook2pdf
#    ./dev.sh commit "Bump font sizes and add code-block heuristics"
#    ./dev.sh push
#    ./dev.sh release-bump patch
#    ./dev.sh release-tag
# ---------------------------------------------------------------------------
set -euo pipefail

APP_NAME="ebook2pdf"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEB_PACKAGE="$(ls "${APP_DIR}/../${APP_NAME}"_*.deb 2>/dev/null | head -1 || true)"
PYTHON="${PYTHON:-python3}"
VERBOSE="${VERBOSE:-1}"
CURRENT_VERSION="$(python3 -c "import sys; sys.path.insert(0, '${APP_DIR}/src'); import importlib.util; spec = importlib.util.spec_from_file_location('pkg', '${APP_DIR}/src/ebook2pdf/__init__.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print(mod.__version__)" 2>/dev/null || echo "1.0.0")"

log()  { [ "$VERBOSE" -ge 1 ] && printf "  \033[1;32m*\033[0m %s\n" "$*"; }
warn() { [ "$VERBOSE" -ge 1 ] && printf "  \033[1;33m!\033[0m %s\n" "$*" >&2; }
err()  { printf "  \033[1;31mERROR\033[0m %s\n" "$*" >&2; exit 1; }

# ---- commands ----------------------------------------------------------

cmd_setup() {
  log "Installing system dependencies…"
  sudo apt-get update -qq
  sudo apt-get install -y -qq calibre dpkg-dev python3-venv python3-pip build-essential python3-pymupdf 2>&1 | tail -2

  log "Creating Python virtual environment…"
  if [ ! -d "$APP_DIR/.venv" ]; then
    $PYTHON -m venv "$APP_DIR/.venv"
  fi

  log "Installing Python build dependencies…"
  "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip build setuptools wheel 2>&1 | tail -1

  log "Installing ebook2pdf in editable mode…"
  "$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR" 2>&1 | tail -1

  log "Setup complete. Activate with:  source $APP_DIR/.venv/bin/activate"
}

cmd_build() {
  log "Building Python package (wheel + sdist)…"
  cd "$APP_DIR"
  $PYTHON -m build --outdir dist/ 2>&1 | tail -3
  log "Built:"
  ls -lh dist/ 2>/dev/null || warn "No dist/ directory created"
}

cmd_deb() {
  log "Building .deb package…"
  chmod +x debian/rules 2>/dev/null || true
  if command -v dpkg-buildpackage >/dev/null 2>&1; then
    dpkg-buildpackage -us -uc -b -d 2>&1 | tail -5 || cmd_deb_fallback
  else
    cmd_deb_fallback
  fi
  log "Package built: $(ls -lh "$APP_DIR/../${APP_NAME}"_*.deb 2>/dev/null | awk '{print $5, $NF}')"
}

cmd_deb_fallback() {
  log "Building .deb with pure-bash fallback..."
  local version
  version=$(python3 -c "import sys; sys.path.insert(0,'$APP_DIR/src'); from ${APP_DIR##*/} import __version__; print(__version__)")

  local workdir
  workdir=$(mktemp -d)
  local pkgdir="$workdir/${APP_NAME}_${version}-1_all"
  local debdir="$pkgdir/DEBIAN"
  local datadir="$pkgdir/usr"
  mkdir -p "$debdir" "$datadir"

  if [ -d "$APP_DIR/debian/ebook2pdf/DEBIAN" ]; then
    cp -r "$APP_DIR/debian/ebook2pdf/DEBIAN/"* "$debdir/" 2>/dev/null || true
  fi

  if [ ! -f "$debdir/control" ] || [ -f "$APP_DIR/debian/control" ]; then
    mkdir -p "$debdir"
    if [ -f "$APP_DIR/debian/control" ]; then
      sed "s/^Version: .*/Version: ${version}-1/" "$APP_DIR/debian/control" > "$debdir/control" 2>/dev/null || true
    fi
    if [ ! -s "$debdir/control" ]; then
      printf 'Package: %s\nVersion: %s-1\nArchitecture: all\nMaintainer: %s\nDescription: %s\n' \
        "$APP_NAME" "$version" "$(git config user.email 2>/dev/null || echo ci-bot@local)" \
        "$APP_NAME package" > "$debdir/control"
    fi
  fi

  if [ -d "$APP_DIR/debian/ebook2pdf" ]; then
    cp -a "$APP_DIR/debian/ebook2pdf/." "$pkgdir/" 2>/dev/null || true
  fi

  if [ ! -d "$pkgdir/usr/lib/python3/dist-packages/${APP_NAME}" ]; then
    mkdir -p "$pkgdir/usr/lib/python3/dist-packages"
    cp -a "$APP_DIR/src/${APP_NAME}" "$pkgdir/usr/lib/python3/dist-packages/${APP_NAME}"
  fi

  mkdir -p "$pkgdir/usr/bin"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -e' \
    'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' \
    'PYTHONPATH="${DIR}/../lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"' \
    'export PYTHONPATH' \
    'exec python3 -m "${APP_NAME}" "$@"' \
    > "$pkgdir/usr/bin/${APP_NAME}"
  chmod 0755 "$pkgdir/usr/bin/${APP_NAME}"

  find "$pkgdir" -type f -exec chmod 0644 {} +
  find "$pkgdir" -type d -exec chmod 0755 {} +

  local md5sums
  md5sums="$debdir/md5sums"
  find "$pkgdir" -type f -not -path "$debdir/*" -exec md5sum {} + > "$md5sums" 2>/dev/null || true
  sed -i "s|$workdir/||g" "$md5sums" 2>/dev/null || true

  local size
  size=$(du -sk "$pkgdir" | awk '{print $1}')
  printf 'Installed-Size: %s\n' "$size" >> "$debdir/control"
  [ -f "$debdir/postinst" ] && chmod 0755 "$debdir/postinst"
  [ -f "$debdir/prerm" ] && chmod 0755 "$debdir/prerm"

  pushd "$workdir" >/dev/null
  ar rcs "${APP_NAME}_${version}-1_all.deb" \
    debian-binary \
    control.tar.gz \
    data.tar.gz
  popd >/dev/null

  cp "$pkgdir.deb" "$APP_DIR/../${APP_NAME}_${version}-1_all.deb" || cp "$workdir/${APP_NAME}_${version}-1_all.deb" "$APP_DIR/../${APP_NAME}_${version}-1_all.deb"
  rm -rf "$workdir"
}

cmd_install() {
  local deb
  deb=$(ls "$APP_DIR/../${APP_NAME}"_*.deb 2>/dev/null | head -1)
  if [ -z "$deb" ]; then
    log "No .deb found — building first…"
    cmd_deb
    deb=$(ls "$APP_DIR/../${APP_NAME}"_*.deb 2>/dev/null | head -1)
  fi
  log "Installing $deb …"
  sudo dpkg -i "$deb" 2>&1 | tail -2
  log "Verifying…"
  ${APP_NAME} --version
}

cmd_test() {
  local epub="${1:-}"
  if [ -z "$epub" ]; then
    # Pick the smallest EPUB in the sibling ebook folder
    epub=$(find "$APP_DIR/../ebook" -name '*.epub' 2>/dev/null | sort | head -1)
  fi
  if [ -z "$epub" ] || [ ! -f "$epub" ]; then
    # Fallback: generate a tiny test EPUB
    epub="/tmp/ebook2pdf_test.epub"
    log "Creating minimal test EPUB at $epub …"
    local d
    d=$(mktemp -d)
    echo "application/epub+zip" > "$d/mimetype"
    mkdir -p "$d/META-INF" "$d/OEBPS"
    cat > "$d/META-INF/container.xml" <<'XEOF'
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
XEOF
    cat > "$d/OEBPS/content.opf" <<'XEOF'
<?xml version="1.0"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id">
  <metadata><dc:identifier id="book-id">test</dc:identifier><dc:title>Test</dc:title></metadata>
  <manifest>
    <item id="html" href="page.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine><itemref idref="html"/></spine>
</package>
XEOF
    cat > "$d/OEBPS/page.xhtml" <<'XEOF'
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Test</title></head>
<body>
  <p>Hello world. This is a <code>test()</code> function.</p>
  <pre>def hello():
    print("code block")</pre>
  <p style="font-family: monospace">const x = 42;</p>
  <div class="listing">$ ls -la
# comment
> output</div>
</body></html>
XEOF
    cat > "$d/OEBPS/style.css" <<'XEOF'
body { font-family: serif; }
code { font-family: monospace; }
XEOF
    cd "$d" && zip -X0 "$epub" mimetype && zip -X9r "$epub" META-INF OEBPS >/dev/null
    rm -rf "$d"
  fi

  log "Testing conversion of: $(basename "$epub")"
  cd "$APP_DIR"
  if command -v ${APP_NAME} &>/dev/null; then
    ${APP_NAME} "$epub" -v 2>&1 | tail -10
  else
    log "ebook2pdf not installed — running from source…"
    $PYTHON -m ebook2pdf "$epub" -v 2>&1 | tail -10
  fi
  log "Test complete."
}

cmd_font_audit() {
  local epub="${1:-}"
  if [ -z "$epub" ]; then
    epub=$(find "$APP_DIR/../ebook" -name '*.epub' 2>/dev/null | sort | head -1)
  fi
  if [ -z "$epub" ] || [ ! -f "$epub" ]; then
    err "No EPUB provided for font audit. Usage: ./dev.sh font-audit <book.epub>"
  fi
  log "Running post-conversion font audit on: $(basename "$epub")"
  cd "$APP_DIR"
  if command -v ${APP_NAME} &>/dev/null; then
    ${APP_NAME} "$epub" -v 2>&1 | tail -12
  else
    log "ebook2pdf not installed — running from source…"
    $PYTHON -m ebook2pdf "$epub" -v 2>&1 | tail -12
  fi

  # Run post-conversion font verification if PyMuPDF is available
  if $PYTHON -c "import fitz" 2>/dev/null; then
    log "Running post-conversion font size verification..."
    out_pdf="/tmp/ebook2pdf_font_audit.pdf"
    rm -f "$out_pdf"
    if command -v ${APP_NAME} &>/dev/null; then
      ${APP_NAME} "$epub" -o "$out_pdf" --rewrite-toc-page-numbers >/dev/null 2>&1 || true
    else
      $PYTHON -m ebook2pdf "$epub" -o "$out_pdf" --rewrite-toc-page-numbers >/dev/null 2>&1 || true
    fi
    if [ -f "$out_pdf" ]; then
      $PYTHON - "$out_pdf" <<'PYEOF'
import sys
from ebook2pdf.font_audit_verify import verify_rendered_font_sizes
pdf = sys.argv[1]
report = verify_rendered_font_sizes(pdf, max_pages=20, sample_stride=1, strict=False)
if not report:
    print("No verifier available or no spans checked.")
else:
    print(f"Verifier: {report.get('verifier')}")
    print(f"Pages scanned: {report.get('pages_scanned')}")
    print(f"Spans checked: {report.get('spans_checked')}")
    print(f"Body min: {report.get('body_min_observed')}pt")
    print(f"Heading min: {report.get('heading_min_observed')}pt")
    print(f"Mono min: {report.get('mono_min_observed')}pt")
    print(f"Caption min: {report.get('caption_min_observed')}pt")
    print(f"Offenders: {len(report.get('offenders', []))}")
PYEOF
      log "Font audit complete."
    else
      warn "Post-conversion PDF not found; font verification skipped."
    fi
  else
    warn "PyMuPDF not available; skipping post-conversion font verification."
    warn "Install python3-pymupdf or run: ./dev.sh setup"
  fi
}

cmd_clean() {
  log "Cleaning build artifacts…"
  rm -rf "$APP_DIR/build/" "$APP_DIR/dist/" "$APP_DIR/src/*.egg-info" "$APP_DIR/.pybuild"
  rm -f "$APP_DIR/../${APP_NAME}"_*.deb "$APP_DIR/../${APP_NAME}"_*.changes "$APP_DIR/../${APP_NAME}"_*.buildinfo
  find "$APP_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
  find "$APP_DIR" -name '*.pyc' -delete
  log "Clean."
}

cmd_git_init() {
  if [ -d "$APP_DIR/.git" ]; then
    warn "Git repository already exists."
    return
  fi
  log "Initialising git repository…"
  cd "$APP_DIR"
  git init
  cat > .gitignore <<'EOF'
# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
.venv/
build/
dist/
.pybuild/

# Debian package artifacts
*.deb
*.changes
*.buildinfo
*.tar.gz
debian/.debhelper/
debian/files
debian/ebook2pdf/
debian/*.log
debian/*.substvars

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
EOF
  git add -A
  git commit -m "Initial commit: ebook2pdf v1.0.0

EPUB to PDF converter with comprehensive formatting fixes:
- Publisher detection (Manning, Wiley, Rheinwerk, Calibre, Google Docs)
- Table recovery heuristics (pipe, CSS, list, repeated-block)
- Code block detection & wrapping (7 strategies)
- Quality audit (font sizes, margin violations)
- Debian packaging with dpkg-buildpackage"
  log "Repository initialised with initial commit."
}

cmd_git_remote() {
  local provider="${1:-}"
  local user="${2:-}"
  local repo="${3:-${APP_NAME}}"

  if [ -z "$provider" ] || [ -z "$user" ]; then
    err "Usage: ./dev.sh git-remote <github|gitlab> <username> [repo-name]"
  fi

  cd "$APP_DIR"
  case "$provider" in
    github)
      local url="git@github.com:${user}/${repo}.git"
      ;;
    gitlab)
      local url="git@gitlab.com:${user}/${repo}.git"
      ;;
    *)
      err "Provider must be 'github' or 'gitlab'"
      ;;
  esac

  if git remote geturl origin &>/dev/null; then
    git remote set-url origin "$url"
    log "Updated remote origin → $url"
  else
    git remote add origin "$url"
    log "Added remote origin → $url"
  fi
}

cmd_commit() {
  local msg="${*:-}"
  if [ -z "$msg" ]; then
    err "Usage: ./dev.sh commit \"<commit message>\""
  fi
  cd "$APP_DIR"
  git add -A
  git commit -m "$msg"
  log "Committed: $msg"
}

cmd_push() {
  cd "$APP_DIR"
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  if [ -z "$branch" ]; then
    err "Not a git repository. Run ./dev.sh git-init first."
  fi
  if ! git remote geturl origin &>/dev/null; then
    err "No remote 'origin' configured. Run ./dev.sh git-remote first."
  fi
  log "Pushing $branch → origin…"
  git push -u origin "$branch"
  log "Push complete."
}

cmd_changelog() {
  cd "$APP_DIR"
  local tag
  tag=$(git describe --abbrev=0 --tags 2>/dev/null || echo "")
  if [ -z "$tag" ]; then
    log "No tags found. Showing all commits:"
    git log --oneline -20
  else
    log "Changes since $tag:"
    git log --oneline "$tag..HEAD"
  fi
}

_cmd_set_version() {
  local version="$1"
  local file="$APP_DIR/src/ebook2pdf/__init__.py"
  local old="__version__ = \"$CURRENT_VERSION\""
  local new="__version__ = \"$version\""
  if [ -f "$file" ]; then
    sed -i "s|$old|$new|g" "$file" || sed -i.bak "s|$old|$new|g" "$file"
    log "Version bumped: $CURRENT_VERSION → $version"
    CURRENT_VERSION="$version"
  else
    err "Version file not found: $file"
  fi
}

cmd_release_bump() {
  local scope="${1:-patch}"
  cd "$APP_DIR"

  if [[ ! "$scope" =~ ^(patch|minor|major|[0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    err "Usage: ./dev.sh release-bump [patch|minor|major|<version>]\nCurrent version: $CURRENT_VERSION"
  fi

  local IFS='.'
  read -r major minor patch <<EOF
$CURRENT_VERSION
EOF

  case "$scope" in
    major)
      major=$((major + 1)); minor=0; patch=0
      ;;
    minor)
      minor=$((minor + 1)); patch=0
      ;;
    patch)
      patch=$((patch + 1))
      ;;
    *)
      # Explicit version
      if [[ "$scope" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        major="${BASH_REMATCH[1]}"
        minor="${BASH_REMATCH[2]}"
        patch="${BASH_REMATCH[3]}"
      else
        err "Invalid version format: $scope"
      fi
      ;;
  esac

  local new_version="$major.$minor.$patch"
  _cmd_set_version "$new_version"

  # Update setup.py
  if [ -f "$APP_DIR/setup.py" ]; then
    if grep -q '^version="'"$CURRENT_VERSION"'"' "$APP_DIR/setup.py"; then
      sed -i "s|version=\"$CURRENT_VERSION\"|version=\"$new_version\"|g" "$APP_DIR/setup.py" || true
    else
      # setup.py now reads version from __init__.py dynamically; nothing to update there
      :
    fi
  fi

  # Update debian/changelog
  if [ -f "$APP_DIR/debian/changelog" ]; then
    local deb_version="${new_version}-1"
    local date
    date=$(date -R)
    cat > "$APP_DIR/debian/changelog" <<EOF
ebook2pdf ($deb_version) unstable; urgency=medium

  * Release $new_version.

 -- Hermes Agent <noreply@example.com>  $date
EOF
    log "Updated debian/changelog to $deb_version"
  fi

  log "Ready to commit version bump to $new_version"
}

cmd_release_tag() {
  local tag_spec="${1:-$CURRENT_VERSION}"
  local tag="v$tag_spec"
  cd "$APP_DIR"

  if git rev-parse "$tag" >/dev/null 2>&1; then
    err "Tag $tag already exists"
  fi

  local message="Release $tag

Changes in this release:
$(git log --oneline -10)"

  git tag -a "$tag" -m "$message"
  log "Created annotated tag: $tag"
  log "Push with: git push origin $tag"
}

cmd_release_start() {
  local tag="${1:-}"
  local branch="release/${tag#v}"
  cd "$APP_DIR"

  if [ -z "$tag" ]; then
    tag=$(git describe --abbrev=0 --tags 2>/dev/null || echo "")
    if [ -z "$tag" ]; then
      err "No tags found. Create a tag first with: ./dev.sh release-tag"
    fi
  fi

  if git rev-parse "$tag" >/dev/null 2>&1; then
    :
  else
    err "Tag $tag does not exist"
  fi

  if git show-ref --verify --quiet "refs/heads/$branch"; then
    warn "Branch $branch already exists"
    git checkout "$branch"
  else
    git checkout -b "$branch" "$tag"
    log "Created branch $branch from $tag"
  fi
}

cmd_release() {
  local scope="${1:-patch}"
  local run_tests="${RUN_TESTS:-1}"
  cd "$APP_DIR"

  log "=== Starting release flow for $APP_NAME ==="

  # 1. Run tests
  if [ "$run_tests" = "1" ]; then
    log "[1/5] Running tests..."
    cmd_test || err "Tests failed. Aborting release."
  fi

  # 2. Version bump
  log "[2/5] Bumping version ($scope)..."
  cmd_release_bump "$scope"

  # 3. Commit
  log "[3/5] Committing version bump..."
  cmd_commit "Release v$CURRENT_VERSION: bump version and update packaging metadata"

  # 4. Tag
  log "[4/5] Creating release tag..."
  cmd_release_tag "$CURRENT_VERSION"

  # 5. Push
  log "[5/5] Pushing to remote..."
  cmd_push
  git push origin "v$CURRENT_VERSION" || warn "Tag push may require explicit confirmation"

  log "=== Release complete: v$CURRENT_VERSION ==="
  log "Next steps:"
  log "  1. Create GitHub release at: $(git remote get-url origin | sed 's|git@github.com:|https://github.com/|g; s|\.git$||')/releases/new?tag=v$CURRENT_VERSION"
  log "  2. Upload .deb: $DEB_PACKAGE"
  log "  3. Or merge release/* branch and let CI build artifacts"
}

cmd_full() {
  cmd_clean
  cmd_setup
  cmd_build
  cmd_deb
  cmd_install
  cmd_test
  log "Full lifecycle complete."
}

# ---- CLI dispatcher ----------------------------------------------------

case "${1:-help}" in
  setup)       cmd_setup ;;
  build)       cmd_build ;;
  deb)         cmd_deb ;;
  install)     cmd_install ;;
  test)        shift; cmd_test "$@" ;;
  font-audit)  shift; cmd_font_audit "$@" ;;
  changelog)   cmd_changelog ;;
  release-bump) shift; cmd_release_bump "$@" ;;
  release-tag)  shift; cmd_release_tag "$@" ;;
  release-start) shift; cmd_release_start "$@" ;;
  release)     shift; cmd_release "$@" ;;
  clean)       cmd_clean ;;
  git-init)    cmd_git_init ;;
  git-remote)  shift; cmd_git_remote "$@" ;;
  commit)      shift; cmd_commit "$@" ;;
  push)        cmd_push ;;
  full)        cmd_full ;;
  help|--help|-h)
    sed -n '/^#  Usage/,/^#  Examples/p' "$0" | sed 's/^#  //; s/^#$//'
    exit 0
    ;;
  *)
    err "Unknown command: $1\n\nRun  ./dev.sh help  for usage."
    ;;
esac
