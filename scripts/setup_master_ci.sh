#!/bin/sh
# Install the master-ci quality toolchain locally (latest main 2026-11-20,
# pinned by commit SHA — the same engine the CI workflow and the
# .quality-baseline.json floor use).
#
# 1. checks out WasewaseX/master-ci (latest main 2026-11-20, SHA-pinned) to
#    _ci/ (helper checkout; the same layout the CI workflows use, ignored by git)
# 2. installs .git/hooks/pre-commit gating every commit's staged files with
#    the same engines CI runs: advisory findings print, blocking findings
#    fail the commit — the classes cleaned in the 2026-11-21 sweep
#    (swallowed-exception, eval-usage, innerhtml, go-ignored-error, ...)
#    cannot be re-committed locally either.
#
# Python deps for full detector fidelity (CI installs the same pins):
#   pip install lizard tree-sitter tree-sitter-language-pack pyyaml
set -e
cd "$(git rev-parse --show-toplevel)"

if [ ! -d _ci/.git ]; then
    git clone https://github.com/WasewaseX/master-ci _ci
    git -C _ci checkout --quiet 5e70bfea253800e9541bda5fe6dbb817fad9663e
else
    echo "_ci already present - keeping the pinned checkout (delete it to re-clone)"
fi

mkdir -p .git/hooks
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
# master-ci per-commit gate (installed by scripts/setup_master_ci.sh).
changed=$(git diff --cached --name-only --diff-filter=ACMR)
[ -z "$changed" ] && exit 0
exec python3 _ci/scripts/hook_gate.py $changed
HOOK
chmod +x .git/hooks/pre-commit
echo "master-ci installed: _ci @ v2.18.0 + .git/hooks/pre-commit gate"
