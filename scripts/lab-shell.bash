# Interactive shell opened by enter-lab.ps1, from the repository root.
[[ -f ~/.bashrc ]] && source ~/.bashrc
profile="${DAY14_PROFILE:-core}"
case "$profile" in
  core|gateway|observability) ;;
  *) echo 'Unknown environment profile.' >&2; return 1 ;;
esac
if [[ ! -f ".venv/$profile/bin/activate" ]]; then
  echo 'Environment missing. Run: bash scripts/setup-wsl.sh'
else
  source ".venv/$profile/bin/activate"
  export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
  printf '\nDay 14 | Ubuntu WSL2 | Python environment: %s\n' "$profile"
  printf 'Project: %s\n' "$PWD"
  echo 'Start Part 1: cd 01-localhost-vs-production/develop && python app.py'
fi
unset profile
