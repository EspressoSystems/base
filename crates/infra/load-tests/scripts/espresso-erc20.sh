#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
export FUNDER_KEY="${FUNDER_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
contracts_dir="${root}/crates/utilities/test-utils/contracts"
template="${root}/crates/infra/load-tests/examples/espresso-erc20.yaml.template"
rendered_config="$(mktemp "${TMPDIR:-/tmp}/espresso-erc20.XXXXXX.yaml")"
trap 'rm -f "$rendered_config"' EXIT

echo "Installing and building Foundry dependencies..."
(cd "$contracts_dir" && forge soldeer install && forge build)

echo "Deploying fixture ERC20 to Espresso quick devnet..."
deploy_output="$(
  cd "$contracts_dir"
  forge script script/DeployTestTokenPair.s.sol:DeployTestTokenPair \
    --rpc-url http://localhost:8546 \
    --private-key "$FUNDER_KEY" \
    --broadcast 2>&1
)"
printf '%s\n' "$deploy_output"
token="$(printf '%s\n' "$deploy_output" | awk '$1 == "Token" && $2 == "A:" { print $3; exit }')"
if [[ ! "$token" =~ ^0x[[:xdigit:]]{40}$ ]]; then
  echo "failed to parse fixture ERC20 address from forge output" >&2
  exit 1
fi

sed "s|__ERC20__|$token|g" "$template" > "$rendered_config"
echo "Running ERC20 load test with rendered config: $rendered_config"
cd "$root"
cargo run --release -p base-load-tester-bin --bin base-load-tester -- "$rendered_config" "$@"
