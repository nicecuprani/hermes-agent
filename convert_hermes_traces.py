#!/usr/bin/env python3
"""
Hermes Traces → NeMo Relay Format Converter

Converts Hermes session traces (from SESSION_LOG.md, skill execution logs, agent turns)
into NeMo Relay trace format for NemoClaw Agent Optimization.

NeMo Relay Trace Schema (simplified):
{
  "trace_id": "uuid",
  "agent_id": "hermes-friday",
  "session_id": "session-uuid",
  "timestamp": "ISO8601",
  "turns": [
    {
      "turn_id": "uuid",
      "role": "user|assistant|tool",
      "content": "...",
      "tool_calls": [...],
      "tool_results": [...],
      "metadata": {
        "model": "...",
        "provider": "...",
        "skills_used": [...],
        "mcp_calls": [...],
        "plugins_used": [...],
        "latency_ms": 1234,
        "token_usage": {...}
      }
    }
  ],
  "outcome": "success|failure|partial",
  "failure_category": "hallucination|tool_misuse|memory_drift|security|verbosity|gender_slip|sycophancy|incomplete",
  "ethos_violations": [...]
}

Usage:
    python convert_hermes_traces.py --input C:\MindOS\Inbox\SESSION_LOG.md --output traces_nemo_relay.json
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import argparse


class HermesTraceConverter:
    def __init__(self, agent_id: str = "hermes-friday"):
        self.agent_id = agent_id
        self.failure_patterns = {
            "hallucination": [
                r"где\s+файл", r"не\s+найден", r"не\s+существует", r"файл\s+создан",
                r"работает", r"готово", r"успешно", r"деплой\s+прошел",
                r"API\s+ответ", r"вернул\s+200", r"база\s+данных\s+подключена"
            ],
            "tool_misuse": [
                r"парс[юи]\s+PDF", r"ручной\s+grep", r"читаю\s+логи\s+вручную",
                r"пишу\s+скрипт\s+для", r"sed\s+awk", r"cat\s+head\s+tail"
            ],
            "memory_drift": [
                r"я\s+помню", r"раньше\s+было", r"в\s+памяти\s+записано",
                r"system\s+memory", r"встроенн\w+\s+memory"
            ],
            "security": [
                r"nvapi-", r"sk-", r"Bearer\s+", r"password", r"secret",
                r"токен", r"ключ\s+в\s+чате"
            ],
            "verbosity": [
                r"отличный\s+вопрос", r"я\s+буду\s+рад\s+помочь", r"надеюсь\s+помогло",
                r"давайте\s+разберем", r"стоит\s+отметить", r"важно\s+подчеркнуть"
            ],
            "gender_slip": [
                r"\bсделал\b", r"\bпроверил\b", r"\bготов\b", r"\bнашел\b",
                r"\bуверен\b", r"\bпонимаю\b", r"\bсогласен\b"
            ],
            "sycophancy": [
                r"отличная\s+мысль", r"прекрасный\s+вопрос", r"молодец",
                r"замечательно", r"впечатляет"
            ],
            "incomplete": [
                r"план\s+готово", r"готов\s+к\s+реализации", r"осталось\s+только",
                r"надо\s+еще\s+сделать", r"следующий\s+шаг"
            ]
        }

    def detect_failure_category(self, text: str) -> Optional[str]:
        """Detect failure category from assistant response text."""
        text_lower = text.lower()
        for category, patterns in self.failure_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return category
        return None

    def detect_ethos_violations(self, text: str) -> List[str]:
        """Detect ETHOS.md violations in assistant response."""
        violations = []
        text_lower = text.lower()

        # Gender slip
        if re.search(r"\b(сделал|проверил|готов|нашел|уверен|понимаю|согласен)\b", text_lower):
            violations.append("gender_slip")

        # Sycophancy
        if re.search(r"(отличный\s+вопрос|я\s+буду\s+рад\s+помочь|надеюсь\s+помогло|прекрасный\s+вопрос|молодец|замечательно|впечатляет)", text_lower):
            violations.append("sycophancy")

        # Verbosity (heuristic: >15 lines without code/tool output)
        lines = text.strip().split('\n')
        content_lines = [l for l in lines if l.strip() and not l.strip().startswith('```')]
        if len(content_lines) > 15 and not any('tool_call' in l or 'execute_code' in l for l in lines):
            violations.append("verbosity")

        # Hallucination markers (claims without verification)
        if re.search(r"(файл\s+создан|работает|готово|успешно|деплой\s+прошел)\b", text_lower):
            if not re.search(r"(read_file|write_file|terminal.*exit_code|verified)", text_lower):
                violations.append("hallucination_marker")

        return violations

    def parse_session_log(self, log_path: Path) -> List[Dict]:
        """Parse SESSION_LOG.md into structured turns."""
        turns = []
        current_turn = None

        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split by turn markers (## Turn N or similar)
        # SESSION_LOG format varies - try common patterns
        turn_blocks = re.split(r'\n##\s+(?:Turn|Ход)\s+\d+', content)

        for i, block in enumerate(turn_blocks):
            if not block.strip():
                continue

            # Detect role from content
            if block.strip().startswith('**User**:') or block.strip().startswith('User:'):
                role = "user"
                text = re.sub(r'^\*\*User\*\*:?\s*', '', block.strip())
            elif block.strip().startswith('**Assistant**:') or block.strip().startswith('Assistant:'):
                role = "assistant"
                text = re.sub(r'^\*\*Assistant\*\*:?\s*', '', block.strip())
            elif 'tool_call' in block or 'execute_code' in block:
                role = "tool"
                text = block.strip()
            else:
                # Heuristic: first block usually user, then alternating
                role = "user" if i % 2 == 0 else "assistant"
                text = block.strip()

            turn = {
                "turn_id": str(uuid.uuid4()),
                "role": role,
                "content": text[:50000],  # Truncate very long turns
                "tool_calls": [],
                "tool_results": [],
                "metadata": {
                    "skills_used": self._extract_skills(text),
                    "mcp_calls": self._extract_mcp(text),
                    "plugins_used": self._extract_plugins(text),
                }
            }

            # Extract tool calls/results from assistant turns
            if role == "assistant":
                turn["tool_calls"] = self._extract_tool_calls(text)
                turn["metadata"]["failure_category"] = self.detect_failure_category(text)
                turn["metadata"]["ethos_violations"] = self.detect_ethos_violations(text)

            turns.append(turn)

        return turns

    def _extract_skills(self, text: str) -> List[str]:
        skills = []
        for match in re.finditer(r'skill[_\s]?(?:view|manage|load)\s*[\(\[]?\s*[\'"]([^\'")\]]+)[\'"]', text, re.IGNORECASE):
            skills.append(match.group(1))
        return list(set(skills))

    def _extract_mcp(self, text: str) -> List[str]:
        mcps = []
        for match in re.finditer(r'mcp__(\w+)__', text):
            mcps.append(match.group(1))
        return list(set(mcps))

    def _extract_plugins(self, text: str) -> List[str]:
        plugins = []
        for match in re.finditer(r'plugin[_\s]?([\w-]+)', text, re.IGNORECASE):
            plugins.append(match.group(1))
        return list(set(plugins))

    def _extract_tool_calls(self, text: str) -> List[Dict]:
        calls = []
        # Pattern: tool_name(arg1=val, arg2=val)
        for match in re.finditer(r'(\w+)\s*\(([^)]*)\)', text):
            calls.append({
                "tool": match.group(1),
                "args_raw": match.group(2)
            })
        return calls

    def convert(self, input_path: str, output_path: str, session_id: Optional[str] = None) -> Dict:
        """Main conversion entry point."""
        log_path = Path(input_path)
        if not log_path.exists():
            raise FileNotFoundError(f"Input not found: {input_path}")

        turns = self.parse_session_log(log_path)

        trace = {
            "trace_id": str(uuid.uuid4()),
            "agent_id": self.agent_id,
            "session_id": session_id or str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "turns": turns,
            "outcome": "success",
            "failure_category": None,
            "ethos_violations": []
        }

        # Aggregate failure category from turns
        for turn in turns:
            if turn["role"] == "assistant":
                fc = turn["metadata"].get("failure_category")
                if fc:
                    trace["failure_category"] = fc
                    trace["outcome"] = "failure"
                violations = turn["metadata"].get("ethos_violations", [])
                trace["ethos_violations"].extend(violations)

        trace["ethos_violations"] = list(set(trace["ethos_violations"]))

        # Write output
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)

        return trace


def main():
    parser = argparse.ArgumentParser(description="Convert Hermes traces to NeMo Relay format")
    parser.add_argument("--input", required=True, help="Path to SESSION_LOG.md or trace file")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--agent-id", default="hermes-friday", help="Agent identifier")
    parser.add_argument("--session-id", help="Session UUID (optional)")
    args = parser.parse_args()

    converter = HermesTraceConverter(agent_id=args.agent_id)
    trace = converter.convert(args.input, args.output, args.session_id)

    print(f"Converted {len(trace['turns'])} turns")
    print(f"Outcome: {trace['outcome']}")
    print(f"Failure category: {trace['failure_category']}")
    print(f"ETHOS violations: {trace['ethos_violations']}")
    print(f"Written to: {args.output}")


if __name__ == "__main__":
    main()