# Shared checks for the CI test scripts; source it, do not run it.
# Bash ignores the exit status of "! cmd" under set -e, so a line such as
# "! pacman -Q mesa" can never fail a test. Negative checks use these instead.

# refute CMD [ARG...]: CMD must fail; its success ends the test.
refute() {
  if "$@"; then
    printf 'unexpected success: %s\n' "$*" >&2
    exit 1
  fi
}

# nomatch [GREP-OPTION...] PATTERN [FILE...]: no line matches. Unlike
# "refute grep", a missing file or another grep error (status 2) fails too.
nomatch() {
  local status=0
  grep -q "$@" || status=$?
  case $status in
    1) return 0 ;;
    0) printf 'unexpected match: grep %s\n' "$*" >&2 ;;
    *) printf 'grep failed (%s): grep %s\n' "$status" "$*" >&2 ;;
  esac
  exit 1
}

# installed [ROOT] NAME: a package with exactly this name is installed (in the
# chroot ROOT if given). "pacman -Q NAME" also answers with a package that
# provides NAME, so it cannot tell the stock package from its replacement.
# A pacman failure ends the test instead of reading as "not installed".
installed() {
  local query=(pacman) names
  if (( $# == 2 )); then
    query=(chroot "$1" pacman)
    shift
  fi
  names=$("${query[@]}" -Qq) || { printf 'cannot list installed packages\n' >&2; exit 1; }
  grep -qxF -- "$1" <<< "$names"
}
