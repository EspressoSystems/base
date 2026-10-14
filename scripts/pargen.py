#!/usr/bin/env python3
#
# Run multiple load generators in parallel against a set of Espresso stack chains.
#
# Usage: pargen.py [options] --config config.yaml -o /tmp/loadgen -c http://c1-seq:8545 -c http://c2-seq:8545 ...
#
# Outputs a summary of each chain + aggregate TPS. Full output from each run can be found in
# $OUTDIR/output_i.json (i ranges from 0 to # chains - 1) and $OUTDIR/logs_i.txt.
#
# Example config (leave out chain-specific fields):
#
# sender_count: 20
# in_flight_per_sender: 256
# max_total_in_flight: 400000
# max_concurrent_submit_requests: 64
# batch_size: 2000
# 
# duration: "60s"
# block_time: "1000ms"
# target_gps: 2300000000
# seed: 10000
# 
# funding_amount: "1000000000000"
# skip_drain: true
# 
# transactions:
#   - weight: 100
#     type: calldata
#     max_size: 200

from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import re

def config_path(outdir: str, i: int):
    return outdir + f'/config_{i}.yaml'

def output_path(outdir: str, i: int):
    return outdir + f'/output_{i}.json'

def logs_path(outdir: str, i: int):
    return outdir + f'/logs_{i}.txt'

def generate_configs(base: str, chains: list[str], outdir: str):
    for i, seq in enumerate(chains):
        with open(config_path(outdir, i), 'w') as f:
            f.write(
f"""
transaction_submission_rpcs:
  - "{seq}"
query_rpc: "{seq}"

""")
            f.write(base)

def load_gen(cmd: str, outdir: str, i: int, funder: str):
    os.putenv('FUNDER_KEY', funder)
    os.putenv('LOAD_TEST_OUTPUT', output_path(outdir, i))

    logs = open(logs_path(outdir, i), 'w')
    return subprocess.Popen(
        cmd.split() + [config_path(outdir, i)],
        stdout=logs,
        stderr=logs,
    )

class ChainSummary(object):
    def __init__(self, outdir=None, i=None, tps=None, steady_tps=None, tx_submitted=None, tx_confirmed=None, blocks=None, mean_block_time=None):
        if outdir is not None:
            with open(output_path(outdir, i), 'r') as f:
                results = json.load(f)
            with open(logs_path(outdir, i), 'r') as f:
                logs = f.read()
                match = re.search(r'actual_tps\s*=\s*([0-9\.]+)', logs)
                if match is None:
                    raise Exception(f'logs for run {i} do not contain actual_tps line')
                self._tps = float(match.group(1))
                # Only logged when the config sets measurement_skip.
                match = re.search(r'steady_tps\s*=\s*([0-9\.]+)', logs)
                self._steady_tps = float(match.group(1)) if match is not None else None
            self._tx_submitted = results['throughput']['total_submitted']
            self._tx_confirmed = results['throughput']['total_confirmed']
            self._blocks = results['block_range']['block_count']
            block_latency = results['block_latency']['mean']
            self._mean_block_time = block_latency['secs'] + float(block_latency['nanos'])/1e9
        else:
            self._tps = tps or 0
            self._steady_tps = steady_tps
            self._tx_submitted = tx_submitted or 0
            self._tx_confirmed = tx_confirmed or 0
            self._blocks = blocks or 0
            self._mean_block_time = mean_block_time or 0

    def has_steady_tps(self):
        return self._steady_tps is not None

    def format(self, steady: bool):
        tps = self._steady_tps if steady else self._tps
        return f'TPS: {tps}; confirmed {100 * (float(self._tx_confirmed) / self._tx_submitted)}% ({self._tx_confirmed}/{self._tx_submitted}); blocks: {self._blocks}, mean block time: {self._mean_block_time}'

    def __add__(self, other: ChainSummary):
        # A sum of one steady and one actual TPS would mean nothing, and dropping steady_tps
        # would lose it silently.
        if self.has_steady_tps() != other.has_steady_tps():
            raise Exception('cannot add a summary with steady_tps to one without')
        return ChainSummary(
            tps=self._tps + other._tps,
            steady_tps=self._steady_tps + other._steady_tps if self.has_steady_tps() else None,
            tx_submitted=self._tx_submitted + other._tx_submitted,
            tx_confirmed=self._tx_confirmed + other._tx_confirmed,
            blocks=self._blocks + other._blocks,
            mean_block_time=(self._mean_block_time*self._blocks + other._mean_block_time*other._blocks)/(self._blocks + other._blocks),
        )

def print_settings(outdir: str):
    # From the run's own generated config rather than --config, which may have changed since.
    # generate_configs writes every chain's config as a header naming that chain's RPC, followed
    # by the same shared settings, so chain 0's config without its header shows them for the run.
    try:
        with open(config_path(outdir, 0), 'r') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        # Results copied without their configs still summarize; only the settings are missing.
        print(f'Settings: {config_path(outdir, 0)} not found')
        return
    shared = next((n + 1 for n, l in enumerate(lines) if l.startswith('query_rpc:')), 0)
    settings = [l for l in lines[shared:] if l.strip() and not l.lstrip().startswith('#')]
    print(f'Settings ({config_path(outdir, 0)}):')
    for l in settings:
        print(f'  {l}')

def main():
    parser = argparse.ArgumentParser(description="run load generators for multiple stacks in parallel, aggregating the results")
    parser.add_argument("--config", required=True, help="shared config for each generator")
    parser.add_argument("-o", "--output", required=True, help="directory for storing generated configs, logs, and results")
    parser.add_argument("-c", "--chain", required=True, action='append', help="sequencer URLs for chains under test")
    parser.add_argument("--command", help="command to run the load generator", default="cargo run --release -p base-load-tester-bin --bin base-load-tester --")
    parser.add_argument("--funder", help="private key used to fund load gen accounts", default="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
    parser.add_argument("--summarize", action='store_true', help="summarize results from a previous run, do not do a new run")

    args = parser.parse_args()

    if not args.summarize:
        os.makedirs(args.output, exist_ok=True)
        with open(args.config, 'r') as base:
            generate_configs(base.read(), args.chain, args.output)

        print(f"Running {len(args.chain)} load generators")
        procs = [load_gen(args.command, args.output, i, args.funder) for i in range(len(args.chain))]
        any_failed = False
        for i, proc in enumerate(procs):
            ret = proc.wait()
            if ret != 0:
                print(f'load generator {i} failed with exit code {ret}; see {logs_path(args.output, i)}')
                any_failed = True

        if any_failed:
            sys.exit(1)

    chains = [ChainSummary(args.output, i) for i in range(len(args.chain))]
    # Steady TPS, which leaves out the prefill and the first blocks, is only logged when the config
    # sets measurement_skip. Every chain runs the same config, so they either all have it or none do.
    steady = chains[0].has_steady_tps()
    if any(c.has_steady_tps() != steady for c in chains):
        raise Exception('some chains logged steady_tps and some did not, though they share one config')
    print_settings(args.output)
    print(f'type: {"steady" if steady else "actual"}')
    print("=" * 80)
    summary = None
    for i, chain_summary in enumerate(chains):
        print(f'Chain {i}: {chain_summary.format(steady)}')
        summary = chain_summary if summary is None else summary + chain_summary
    print("=" * 80)
    print(f"Total: {summary.format(steady)}")

if __name__ == '__main__':
    main()
