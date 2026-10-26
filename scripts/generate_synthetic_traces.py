#!/usr/bin/env python3
"""
Generate Synthetic Traces for Changed Components

Creates NeMo Relay format traces from eval_heldout.yaml test cases
by running them through the current agent configuration.

Usage:
    python generate_synthetic_traces.py \
      --changed-files "prompts/agent.yaml,skills/tool_gate.yaml" \
      --output traces/synthetic_traces.json
"""

import json
import yaml
import uuid
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import argparse


class SyntheticTraceGenerator:
    def __init__(self, agent_id: str = "hermes-friday"):
        self.agent_id = agent_id

    def load_eval_cases(self, eval_path: Path) -> List[Dict]:
        with open(eval_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data.get('cases', [])

    def filter_by_changed_files(self, cases: List[Dict], changed_files: List[str]) -> List[Dict]:
        """Filter eval cases relevant to changed files."""
        if not changed_files:
            return cases

        # Map file patterns to case IDs
        file_to_cases = {
            'prompts/': ['vault_context_injection', 'secret_handling', 'gender_consistency', 'brevity', 'crisis_mode'],
            'skills/': ['tool_selection_gate', 'tool_gate'],
            'config/agent': ['vault_context_injection', 'gender_consistency', 'brevity', 'crisis_mode'],
            'config/tool': ['tool_selection_gate', 'tool_gate'],
            'rules.md': ['safety_gates', 'hallucination_guard', 'simple_first', 'verification_before_completion'],
        }

        relevant_case_ids = set()
        for changed in changed_files:
            for pattern, case_ids in file_to_cases.items():
                if pattern in changed:
                    relevant_case_ids.update(case_ids)

        if not relevant_case_ids:
            return cases  # Run all if no mapping

        return [c for c in cases if c['id'] in relevant_case_ids]

    def run_agent_on_prompt(self, prompt: str) -> Dict[str, Any]:
        """Run Hermes agent on a prompt and capture the trace.
        This is a placeholder - actual implementation depends on Hermes API.
        """
        # Option 1: Use Hermes CLI if available
        # result = subprocess.run(['hermes', 'run', '--prompt', prompt], capture_output=True, text=True)

        # Option 2: Use internal API (if exposed)
        # result = requests.post('http://localhost:8080/api/chat', json={'prompt': prompt})

        # Option 3: Simulate for CI (generate expected trace structure)
        # For now, return a mock trace structure
        return {
            "turn_id": str(uuid.uuid4()),
            "role": "assistant",
            "content": f"[SYNTHETIC RESPONSE TO: {prompt[:100]}...]",
            "tool_calls": [],
            "tool_results": [],
            "metadata": {
                "model": "z-ai/glm-5.3-flash",
                "provider": "nous",
                "skills_used": [],
                "mcp_calls": [],
                "plugins_used": [],
                "latency_ms": 0,
                "token_usage": {}
            }
        }

    def generate(self, eval_path: Path, changed_files: List[str], output_path: Path) -> Dict:
        cases = self.load_eval_cases(eval_path)
        filtered = self.filter_by_changed_files(cases, changed_files)

        print(f"Generating traces for {len(filtered)} cases (from {len(cases)} total)")

        turns = []
        for case in filtered:
            prompt = case['prompt']
            print(f"  Running: {case['id']}")

            # Run agent (or simulate)
            turn = self.run_agent_on_prompt(prompt)
            turn["metadata"]["eval_case_id"] = case['id']
            turn["metadata"]["expected_behavior"] = case.get('expected_behavior', [])
            turns.append(turn)

            # Also add user turn
            user_turn = {
                "turn_id": str(uuid.uuid4()),
                "role": "user",
                "content": prompt,
                "tool_calls": [],
                "tool_results": [],
                "metadata": {"eval_case_id": case['id']}
            }
            turns.insert(-1, user_turn)  # Insert before assistant turn

        trace = {
            "trace_id": str(uuid.uuid4()),
            "agent_id": self.agent_id,
            "session_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "turns": turns,
            "outcome": "success",
            "failure_category": None,
            "ethos_violations": [],
            "metadata": {
                "source": "synthetic",
                "eval_cases": [c['id'] for c in filtered],
                "changed_files": changed_files
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)

        return trace


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic traces for changed files")
    parser.add_argument("--changed-files", required=True, help="Comma-separated list of changed files")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--eval-file", default="eval_heldout.yaml", help="Eval cases YAML")
    parser.add_argument("--agent-id", default="hermes-friday", help="Agent ID")
    args = parser.parse_args()

    changed_files = [f.strip() for f in args.changed_files.split(',') if f.strip()]

    generator = SyntheticTraceGenerator(agent_id=args.agent_id)
    eval_path = Path(args.eval_file)
    output_path = Path(args.output)

    if not eval_path.exists():
        print(f"Eval file not found: {eval_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    trace = generator.generate(eval_path, changed_files, output_path)

    print(f"Generated trace with {len(trace['turns'])} turns")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()