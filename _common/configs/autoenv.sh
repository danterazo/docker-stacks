AUTOENV_ENV_FILENAME=.autoenv.sh
AUTOENV_VIEWER=cat
AUTOENV_ASSUME_YES=yes
unset AUTOENV_ENABLE_LEAVE

if [[ -r "$HOME/.autoenv/activate.sh" ]]; then
	source "$HOME/.autoenv/activate.sh"
elif command -v brew >/dev/null 2>&1; then
	if [[ -r "$(brew --prefix autoenv)/activate.sh" ]]; then
		source "$(brew --prefix autoenv)/activate.sh"
	fi
elif command -v npm >/dev/null 2>&1; then
	if [[ -r "$(npm root -g)/@hyperupcall/autoenv/activate.sh" ]]; then
		source "$(npm root -g)/@hyperupcall/autoenv/activate.sh"
	fi
fi
