vpn_location_script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.common/bin" && pwd)/vpn-location.sh
printf -v vpn_location_alias 'loc=bash %q logs' "$vpn_location_script"
alias "$vpn_location_alias"
printf -v vpn_location_alias 'loc2=bash %q live' "$vpn_location_script"
alias "$vpn_location_alias"
unset vpn_location_script vpn_location_alias
