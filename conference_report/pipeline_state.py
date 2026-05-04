from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, write_json


STATE_FILE = "pipeline_state.json"
WAITING_FOR_AGENT = "waiting_for_agent"
COMPLETED = "completed"


GATE_MESSAGES = {
    "dedupe_review": {
        "label": "dedupe review",
        "validate_phase": "dedupe-review",
        "task_manifests": ["dedupe/agent_review_tasks.json"],
        "instructions": [
            "读取 dedupe/agent_review_tasks.json。",
            "逐个任务只写 output_paths 中列出的 JSON 文件。",
            "完成后运行 validate --phase dedupe-review。",
            "验证通过后运行 resume。",
        ],
    },
    "report_agent": {
        "label": "agent report writing",
        "validate_phase": "final",
        "task_manifests": [
            "agent_slide_cognition_tasks.json",
            "agent_qa_tasks.json",
            "agent_report_tasks.json",
            "agent_grounding_tasks.json",
        ],
        "instructions": [
            "按 slide_cognition、qa_detection、report_write、grounding_review 顺序执行 task manifests。",
            "每个任务只写 allowed_write_paths 中列出的文件。",
            "完成后运行 validate --phase final。",
            "验证通过后运行 resume。",
        ],
    },
    "report_revision": {
        "label": "report quality revision",
        "validate_phase": "final",
        "task_manifests": [
            "report_quality_validation.json",
            "agent_report_revision_tasks.json",
        ],
        "instructions": [
            "读取 report_quality_validation.json 和 agent_report_revision_tasks.json。",
            "只重写 revision task 的 allowed_write_paths 中列出的失败报告和 grounding review。",
            "不要把 OCR/ASR 机械填进报告；必须修复质量失败原因。",
            "完成后运行 validate --phase final。",
            "验证通过后运行 resume。",
        ],
    },
    "report_quality_repair": {
        "label": "report quality repair",
        "validate_phase": "final",
        "task_manifests": [
            "agent_quality_repair_plan.json",
            "agent_slide_cognition_revision_tasks.json",
            "agent_qa_revision_tasks.json",
            "agent_report_revision_tasks.json",
            "agent_grounding_revision_tasks.json",
        ],
        "instructions": [
            "读取 agent_quality_repair_plan.json。",
            "按 slide_cognition_revision、qa_revision、report_revision、grounding_revision 顺序完成 task manifests。",
            "每个任务只写 allowed_write_paths 中列出的文件。",
            "完成后运行 validate --phase final。",
            "验证通过后运行 resume。",
        ],
    },
}


def state_path(out_dir: Path) -> Path:
    return out_dir / STATE_FILE


def read_pipeline_state(out_dir: Path) -> dict[str, Any] | None:
    path = state_path(out_dir)
    if not path.exists():
        return None
    return read_json(path)


def is_waiting(state: dict[str, Any] | None) -> bool:
    return bool(state and state.get("current_status") == WAITING_FOR_AGENT)


def write_waiting_state(
    out_dir: Path,
    *,
    source: str | None,
    completed_stages: list[str],
    blocked_gate: str,
    config_path: Path | None = None,
    writer: str | None = None,
    manual_segments: Path | None = None,
    agent_gates: list[str] | None = None,
) -> dict[str, Any]:
    gate = GATE_MESSAGES[blocked_gate]
    validate_phase = gate["validate_phase"]
    config_arg = f" --config {config_path}" if config_path else ""
    state = {
        "source": source,
        "completed_stages": completed_stages,
        "current_status": WAITING_FOR_AGENT,
        "blocked_gate": blocked_gate,
        "next_allowed_command": f"conference-report validate --out {out_dir}{config_arg} --phase {validate_phase}",
        "resume_command": f"conference-report resume --out {out_dir}{config_arg}",
        "task_manifests": gate["task_manifests"],
        "human_message": waiting_message(blocked_gate),
    }
    if config_path:
        state["config_path"] = str(config_path)
    if writer:
        state["writer"] = writer
    if manual_segments:
        state["manual_segments"] = str(manual_segments)
    if agent_gates:
        state["agent_gates"] = agent_gates
    ensure_dir(out_dir)
    write_json(state_path(out_dir), state)
    return state


def write_completed_state(out_dir: Path, *, source: str | None, completed_stages: list[str]) -> dict[str, Any]:
    state = {
        "source": source,
        "completed_stages": completed_stages,
        "current_status": COMPLETED,
        "blocked_gate": None,
        "next_allowed_command": "",
        "resume_command": "",
        "task_manifests": [],
        "human_message": "Pipeline completed.",
    }
    ensure_dir(out_dir)
    write_json(state_path(out_dir), state)
    return state


def waiting_message(blocked_gate: str) -> str:
    gate = GATE_MESSAGES.get(blocked_gate, {})
    label = gate.get("label", blocked_gate)
    lines = [f"当前停在 {label}。"]
    lines.extend(str(item) for item in gate.get("instructions", []))
    return "\n".join(lines)


def format_state_for_human(state: dict[str, Any] | None) -> str:
    if not state:
        return "No pipeline_state.json found. The run is not currently paused by an agent gate."
    lines = [
        f"Status: {state.get('current_status')}",
        f"Gate: {state.get('blocked_gate')}",
        f"Completed stages: {', '.join(state.get('completed_stages') or [])}",
    ]
    task_manifests = state.get("task_manifests") or []
    if state.get("failed_report_count") is not None:
        lines.append(f"Failed reports: {state['failed_report_count']}")
    if task_manifests:
        lines.append("Task manifests:")
        lines.extend(f"- {item}" for item in task_manifests)
    if state.get("human_message"):
        lines.append(str(state["human_message"]))
    if state.get("next_allowed_command"):
        lines.append(f"Next: {state['next_allowed_command']}")
    if state.get("resume_command"):
        lines.append(f"Resume: {state['resume_command']}")
    return "\n".join(lines)


def blocked_command_message(command: str, state: dict[str, Any]) -> str:
    gate = state.get("blocked_gate") or "unknown"
    lines = [
        f"不能运行 {command}。",
        f"当前停在 {gate}。",
    ]
    if state.get("human_message"):
        lines.append(str(state["human_message"]))
    if state.get("next_allowed_command"):
        lines.append(f"下一步先运行: {state['next_allowed_command']}")
    if state.get("resume_command"):
        lines.append(f"验证通过后运行: {state['resume_command']}")
    return "\n".join(lines)
