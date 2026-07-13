from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from shared.llm_clients.tiers import TierRouter
from shared.normalizer.normalizer import NormalizationResult
from wrappers.safety_firewall import EGRESS_CANNED
from wrappers.safety_firewall import INGRESS_CANNED

if TYPE_CHECKING:
    from wrappers.hub_client import HubClient
    from wrappers.memory import MemoryStore
    from wrappers.safety_firewall import SafetyFirewall
    from wrappers.session import SessionStore
    from wrappers.skill_loader import SkillLoader

logger = logging.getLogger(__name__)

UNCERTAINTY_MARKERS = (
    "i can't",
    "i'm unable to",
    "i don't know",
    "i am unable",
    "i cannot",
    "i'm not able",
)

DEFAULT_COGNITION_CONFIG: dict = {
    "enabled": True,
    "strong_cycle": True,
    "session_window": 12,
    "reflect_on_daily": False,
    "soul_limit": 5000,
    "user_limit": 5000,
    "capabilities_limit": 3000,
    "recall_top_k": 5,
    "compaction_threshold": 60,
    "auto_push_lessons": True,
}

DEFAULT_NORMALIZATION_CONFIG: dict = {
    "llm_rewrite_on": [],
    "model": "daily",
}

CODING_TIER_REQUIRED_HUB_TIER = 2
CODING_DENIED_MESSAGE = (
    "`/code` requires Bot Master access (your tier: {tier}). "
    "Learn more or request an upgrade. `/think` (deep reasoning) is available to all tiers."
)

A2A_TASK_REQUEST = "task_request"
A2A_TASK_RESULT = "task_result"
A2A_TASK_REFUSE = "task_refuse"
A2A_TASK_FAILURE = "task_failure"

A2A_RESPONSE_TYPES = frozenset({A2A_TASK_RESULT, A2A_TASK_REFUSE, A2A_TASK_FAILURE})

CLASSIFY_SCHEMA: dict = {
    "name": "orientation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "complexity": {"type": "string", "enum": ["simple", "moderate", "complex"]},
            "emotion": {"type": "string"},
            "needs_tool": {"type": "boolean"},
            "needs_memory": {"type": "boolean"},
            "suggested_tier": {"type": "string", "enum": ["daily", "strong", "coding"]},
        },
        "required": ["intent", "complexity", "emotion", "needs_tool", "needs_memory", "suggested_tier"],
        "additionalProperties": False,
    },
}

PLAN_SCHEMA: dict = {
    "name": "plan",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "llm",
                                "hub_call",
                                "local_tool",
                                "memory_write",
                                "message_user",
                                "recall_more",
                                "user_script",
                                "delegate",
                            ],
                        },
                        "params": {"type": "object"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["action", "params", "rationale"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["steps"],
        "additionalProperties": False,
    },
}

REFLECT_SCHEMA: dict = {
    "name": "reflection",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "quality": {"type": "number"},
            "critique": {"type": "string"},
            "keep": {"type": "array", "items": {"type": "string"}},
            "self_edit": {
                "type": ["object", "null"],
                "properties": {
                    "persona": {"type": ["string", "null"]},
                    "human": {"type": ["string", "null"]},
                    "memory": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "lesson": {
                "type": ["object", "null"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "prompt_improvement",
                            "pattern",
                            "skill_proposal",
                            "tool_pattern",
                            "reflection",
                        ],
                    },
                    "title": {"type": "string"},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "what": {"type": "string"},
                            "why": {"type": "string"},
                            "how_to_use": {"type": "string"},
                            "example_before": {"type": "string"},
                            "example_after": {"type": "string"},
                            "tier_hint": {"type": "string", "enum": ["daily", "strong", "coding"]},
                        },
                        "required": [
                            "what",
                            "why",
                            "how_to_use",
                            "example_before",
                            "example_after",
                            "tier_hint",
                        ],
                        "additionalProperties": False,
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "is_network_useful": {"type": "boolean"},
                },
                "required": ["kind", "title", "summary", "tags", "is_network_useful"],
                "additionalProperties": False,
            },
        },
        "required": ["quality", "critique", "keep", "self_edit", "lesson"],
        "additionalProperties": False,
    },
}

REFLECT_PROMPT = (
    "You are the REFLECT phase of an edge cognitive engine. After responding to a user, "
    "you self-critique the turn and extract a learning. You are NOT shown the agent's persona, "
    "user-model, or capability blocks -- only the user message, the response, and a step trace "
    "(action/params/output/rationale). Never attempt to reconstruct or echo persona blocks.\n\n"
    "PII RULE (mandatory): Do NOT include real names, emails, phone numbers, or IDs in `keep`, "
    '`title`, or any `summary` field. Use placeholder names like "User X", "the customer", '
    'or "a client". Refer to the user only by placeholder.\n\n'
    "Produce a ReflectionDiff:\n"
    "- quality: 0.0-1.0 self-rating of the response.\n"
    "- critique: one-line self-critique (PII-free).\n"
    "- keep: local MEMORY.md lines to append (PII-free, placeholder names).\n"
    "- self_edit: optional replacements for the persona (SOUL) / human (USER) block bodies and "
    "extra memory lines. null if no edit. Keep replacements concise.\n"
    "- lesson: optional network-shareable lesson. Set only when `is_network_useful` is true. "
    "Use placeholder names in `title` and all `summary` fields (example_before/example_after).\n\n"
    "USER MESSAGE:\n{message}\n\nRESPONSE:\n{result}\n\nTRACE:\n{trace}\n\n"
    "Respond ONLY with the structured JSON."
)

PLAN_PROMPT = (
    "You are the PLAN phase of an edge cognitive engine. Decompose the user's turn into ordered "
    "steps. Each step has an action (one of llm, hub_call, local_tool, memory_write, message_user, "
    "recall_more, user_script), params, and a one-line rationale. Simple turns yield a single "
    "`llm` step. Do not include persona blocks in the plan.\n\n"
    "USER MESSAGE:\n{message}\n\nCLASSIFICATION:\n{classification}\n\n"
    "Respond ONLY with the structured JSON."
)

CLASSIFY_PROMPT = (
    "You are the ORIENT phase of an edge cognitive engine. Classify this user turn.\n"
    "USER MESSAGE:\n{message}\n\nRespond ONLY with the structured JSON."
)


@dataclass
class Step:
    action: str
    params: dict = field(default_factory=dict)
    rationale: str = ""


@dataclass
class Context:
    text: str
    source: str
    tier: str
    model: str
    classification: dict = field(default_factory=dict)
    normalization: NormalizationResult | None = None
    recall_block: str = ""
    session_history: list[dict] = field(default_factory=list)
    core_blocks: str = ""
    user_id: str = "default"
    skill_instructions: str | None = None


@dataclass
class ReflectionDiff:
    quality: float = 0.0
    critique: str = ""
    keep: list[str] = field(default_factory=list)
    self_edit: dict | None = None
    lesson: dict | None = None


def _has_uncertainty(text: str) -> bool:
    lower = text.lower().strip()
    if not lower:
        return True
    return any(marker in lower for marker in UNCERTAINTY_MARKERS)


class CognitiveEngine:
    """Stateful per-turn cognitive engine (ORIENT -> PLAN -> EXECUTE -> REFLECT -> LEARN -> RESPOND).

    The simple path (``daily`` + simple) collapses to today's behavior for
    latency parity: heuristic ORIENT + one LLM call + uncertainty escalation.
    The strong/coding path runs the full cycle. REFLECT/LEARN are tier-gated
    (``reflect_on_daily`` defaults false).
    """

    def __init__(
        self,
        *,
        factory,
        safety: SafetyFirewall,
        models: dict,
        system_prompt: str,
        provider_name: str,
        max_price: float,
        client: HubClient,
        memory: MemoryStore,
        sessions: SessionStore,
        cognition_config: dict | None = None,
        normalization_config: dict | None = None,
        agent_hub_tier: int = 1,
        skill_loader: SkillLoader | None = None,
        agent_id: str | None = None,
        is_orchestrator: bool = False,
    ) -> None:
        self.factory = factory
        self.safety = safety
        self.models = models
        self.system_prompt = system_prompt
        self.provider_name = provider_name
        self.max_price = max_price
        self.client = client
        self.memory = memory
        self.sessions = sessions
        self.cognition = {**DEFAULT_COGNITION_CONFIG, **(cognition_config or {})}
        self.normalization = {**DEFAULT_NORMALIZATION_CONFIG, **(normalization_config or {})}
        self.agent_hub_tier = agent_hub_tier
        self.skill_loader = skill_loader
        self.agent_id = agent_id
        self.is_orchestrator = is_orchestrator
        self._ensure_persona()

    def _ensure_persona(self) -> None:
        try:
            limits = {
                "SOUL.md": self.cognition.get("soul_limit", 5000),
                "USER.md": self.cognition.get("user_limit", 5000),
                "CAPABILITIES.md": self.cognition.get("capabilities_limit", 3000),
            }
            self.memory.ensure_default_blocks(limits=limits)
        except Exception:
            logger.exception("Could not seed default persona blocks — continuing")

    # ------------------------------------------------------------------
    # public entrypoint
    # ------------------------------------------------------------------
    def process(self, message: dict) -> None:
        msg_id = message.get("id")
        msg_type = message.get("type", "")
        payload = message.get("payload", {})
        source = payload.get("source", "")
        text = payload.get("text", "")
        discord_user_id = payload.get("discord_user_id")
        self._current_discord_user_id = discord_user_id

        if source in ("discord", "discord_dm", "a2a"):
            safe, reason = self.safety.check_ingress(text)
            if not safe:
                logger.warning("Ingress blocked: %s (msg=%s)", reason, msg_id)
                self.client.respond_to_message(
                    msg_id,
                    accepted=True,
                    result={"text": INGRESS_CANNED.format(reason=reason)},
                )
                return

        tier = TierRouter.resolve_tier(message)
        coding_denied = tier == "coding" and self.agent_hub_tier < CODING_TIER_REQUIRED_HUB_TIER
        if coding_denied:
            logger.info("Coding tier denied (hub tier=%s) — downgrading msg=%s", self.agent_hub_tier, msg_id)
            result = CODING_DENIED_MESSAGE.format(tier=self.agent_hub_tier)
            denied_ctx = Context(text=text, source=source, tier="daily", model="")
            self._append_session(source, denied_ctx, text, result, "daily", msg_id)
            self.client.respond_to_message(msg_id, accepted=True, result={"text": result})
            return
        if tier == "coding":
            model = self.models.get("coding", self.models.get("daily", ""))
        else:
            model = self.models.get(tier, self.models.get("daily", ""))

        context = self.orient(message, text, source, tier, model)

        if (
            self.cognition.get("enabled", True)
            and self.cognition.get("strong_cycle", True)
            and tier in ("strong", "coding")
        ):
            result, trace = self.execute_full(context)
        else:
            result, trace = self.execute_fast(context)

        # Egress safety runs BEFORE REFLECT/LEARN: reflection/learning writes
        # only happen for turns that have already cleared egress (spec §8.3).
        # An egress-blocked result is never learned into persona/memory.
        egress_passed, final_result = self._check_egress(source, result, msg_id)

        self._append_session(source, context, text, final_result, tier, msg_id)

        if self.cognition.get("enabled", True) and self._should_reflect(tier) and egress_passed:
            reflection = self.reflect(text, final_result, trace)
            self.learn(reflection, context)

        self.client.respond_to_message(msg_id, accepted=True, result={"text": final_result})

        if msg_type == A2A_TASK_REQUEST:
            from_agent_id = message.get("from_agent_id")
            if from_agent_id:
                try:
                    self.client.send_message(
                        to_agent_id=str(from_agent_id),
                        msg_type=A2A_TASK_RESULT,
                        payload={"text": final_result, "source": "a2a"},
                        reply_to=msg_id,
                    )
                except Exception:
                    logger.exception("Failed to send A2A task_result to %s", from_agent_id)

    def _should_reflect(self, tier: str) -> bool:
        # strong/coding always reflect; daily only when reflect_on_daily is set.
        if tier in ("strong", "coding"):
            return not self._is_fast(tier)
        return bool(self.cognition.get("reflect_on_daily", False))

    def _check_egress(self, source: str, result: str, msg_id: str) -> tuple[bool, str]:
        """Run egress safety. Returns (passed, final_result)."""
        if source not in ("discord", "discord_dm"):
            return True, result
        safe, reason = self.safety.check_egress(result)
        if not safe:
            logger.warning("Egress blocked: %s (msg=%s)", reason, msg_id)
            return False, EGRESS_CANNED.format(reason=reason)
        return True, result

    def _is_fast(self, tier: str) -> bool:
        if tier not in ("strong", "coding"):
            return True
        if not self.cognition.get("strong_cycle", True):
            return True
        return False

    # ------------------------------------------------------------------
    # ORIENT
    # ------------------------------------------------------------------
    def orient(self, message: dict, text: str, source: str, tier: str, model: str) -> Context:
        norm = self._normalize(text, tier)
        classification = self._classify(text, tier, model)
        cues = [classification.get("intent", ""), text]
        recall_block = self.memory.recall(cues, top_k=self.cognition.get("recall_top_k", 5))
        core_blocks = self.memory.load_core_blocks()
        session_history = []
        user_id = "default"
        skill_instructions = None
        if self.skill_loader:
            matched = self.skill_loader.find_skill(text)
            if matched:
                skill_instructions = self.skill_loader.get_skill_instructions(matched["id"])
                if skill_instructions:
                    logger.info("Matched skill '%s' for message", matched["name"])
        if source in ("discord", "discord_dm"):
            user_id = message.get("payload", {}).get("discord_user_id") or message.get(
                "metadata",
                {},
            ).get("discord_user_id", "default")
            session_history = self.sessions.tail(source, user_id, k=self.cognition.get("session_window", 12))
        return Context(
            text=text,
            source=source,
            tier=tier,
            model=model,
            classification=classification,
            normalization=norm,
            recall_block=recall_block,
            session_history=session_history,
            core_blocks=core_blocks,
            user_id=user_id,
            skill_instructions=skill_instructions,
        )

    def _normalize(self, text: str, tier: str) -> NormalizationResult:
        from wrappers.normalize import normalize

        do_llm = tier in set(self.normalization.get("llm_rewrite_on", []))
        return normalize(
            text,
            provider=self.factory,
            llm_rewrite_model=self.models.get(self.normalization.get("model", "daily"), ""),
            do_llm_rewrite=do_llm,
        )

    def _classify(self, text: str, tier: str, model: str) -> dict:
        # When cognition is disabled, always use heuristic to restore the linear loop.
        if not self.cognition.get("enabled", True) or tier == "daily":
            return self._heuristic_classify(text)
        try:
            return self.factory.complete_structured(
                messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(message=text)}],
                model=self.models.get("daily", model),
                response_schema=CLASSIFY_SCHEMA,
                temperature=0.0,
            )
        except Exception:
            logger.exception("ORIENT classify LLM failed — falling back to heuristic")
            return self._heuristic_classify(text)

    @staticmethod
    def _heuristic_classify(text: str) -> dict:
        lowered = text.lower()
        needs_tool = any(kw in lowered for kw in ("read", "write", "run", "file", "schedule", "send"))
        complexity = (
            "complex" if len(text.split()) > 24 else ("moderate" if len(text.split()) > 10 else "simple")
        )
        return {
            "intent": "question",
            "complexity": complexity,
            "emotion": "neutral",
            "needs_tool": needs_tool,
            "needs_memory": False,
            "suggested_tier": "daily",
        }

    def _build_messages(self, context: Context) -> list[dict]:
        system_tail_parts = [self.system_prompt]
        if context.core_blocks:
            system_tail_parts.append(context.core_blocks)
        if context.skill_instructions:
            system_tail_parts.append(context.skill_instructions)
        if self.skill_loader:
            index_summary = self.skill_loader.get_index_summary()
            if index_summary:
                system_tail_parts.append(index_summary)
        if context.recall_block:
            system_tail_parts.append("Relevant memory:\n" + context.recall_block)
        system_content = "\n\n".join(system_tail_parts)
        messages: list[dict] = [{"role": "system", "content": system_content}]
        for entry in context.session_history:
            role = entry.get("role")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": entry.get("text", "")})
        messages.append({"role": "user", "content": context.text})
        return messages

    # ------------------------------------------------------------------
    # EXECUTE (fast path -- daily parity)
    # ------------------------------------------------------------------
    def execute_fast(self, context: Context) -> tuple[str, list[dict]]:
        messages = self._build_messages(context)
        result = self._call_llm(messages, context.model, context.tier)
        trace = [
            {
                "action": "llm",
                "params": {"model": context.model},
                "output": result,
                "rationale": "daily fast path",
            },
        ]
        if context.tier == "daily" and _has_uncertainty(result):
            escalated = self._escalate(messages, result)
            if escalated != result:
                trace.append(
                    {
                        "action": "llm",
                        "params": {"model": self.models.get("strong", "")},
                        "output": escalated,
                        "rationale": "uncertainty escalation",
                    },
                )
            result = escalated
        return result, trace

    def _escalate(self, messages: list[dict], daily_result: str) -> str:
        strong_model = self.models.get("strong", "deepseek/deepseek-pro")
        logger.warning("Daily uncertain — escalating to %s", strong_model)
        try:
            escalated = self._call_llm(messages, strong_model, "strong")
            if not _has_uncertainty(escalated):
                return escalated
        except Exception:
            logger.exception("Strong escalation failed — using daily response")
        return daily_result

    # ------------------------------------------------------------------
    # PLAN + EXECUTE (full path -- strong/coding)
    # ------------------------------------------------------------------
    def plan(self, context: Context, hint: str = "") -> list[Step]:
        prompt = PLAN_PROMPT.format(
            message=context.text,
            classification=context.classification,
        )
        if hint:
            prompt += f"\n\nREPLAN NOTE: {hint}"
        try:
            data = self.factory.complete_structured(
                messages=[{"role": "user", "content": prompt}],
                model=self.models.get("strong", context.model),
                response_schema=PLAN_SCHEMA,
                temperature=0.0,
            )
            steps = [
                Step(
                    action=s.get("action", "llm"),
                    params=s.get("params", {}),
                    rationale=s.get("rationale", ""),
                )
                for s in data.get("steps", [])
            ]
            if steps:
                return steps
        except Exception:
            logger.exception("PLAN LLM failed — using degenerate single-step plan")
        return [Step(action="llm", params={}, rationale="degenerate plan")]

    def execute_full(self, context: Context) -> tuple[str, list[dict]]:
        steps = self.plan(context)
        self.memory.write_plan(context.text, [s.__dict__ for s in steps])
        messages = self._build_messages(context)
        trace: list[dict] = []
        result = ""
        replans_used = 0
        max_replans = 1
        i = 0
        while i < len(steps):
            step = steps[i]
            output = self._dispatch_step(step, messages, context)
            trace.append(
                {"action": step.action, "params": step.params, "output": output, "rationale": step.rationale},
            )
            if step.action == "llm":
                result = output
                if _has_uncertainty(output):
                    escalated = self._escalate(messages, output)
                    if escalated != output:
                        trace[-1]["output"] = escalated
                        result = escalated
                        output = escalated
                    if _has_uncertainty(output) and replans_used < max_replans:
                        replans_used += 1
                        logger.warning("Mid-step uncertainty — replanning (x%d)", replans_used)
                        new_steps = self.plan(
                            context,
                            hint="previous step was uncertain; try a different approach",
                        )
                        steps = steps[:i] + new_steps
                        continue
            elif step.action == "message_user":
                result = output
            i += 1
        if not result:
            result = "Done."
        return result, trace

    def _dispatch_step(self, step: Step, messages: list[dict], context: Context) -> str:
        action = step.action
        if action == "llm":
            model = step.params.get("model", context.model)
            return self._call_llm(messages, model, context.tier)
        if action == "hub_call":
            tool = step.params.get("tool", "")
            params = step.params.get("params", {})
            try:
                return str(self.client.hub_call(tool, params))
            except Exception:
                logger.exception("hub_call step failed: %s", tool)
                return "hub_call failed"
        if action == "local_tool":
            return self._run_local_tool(step.params)
        if action == "memory_write":
            tag = step.params.get("tag", "observation")
            line = step.params.get("line", "")
            self.memory.append_memory(tag, line, source="observation")
            return "memory written"
        if action == "message_user":
            from wrappers.tools import message_user

            msg = step.params.get("message", "")
            message_user(msg)
            return msg
        if action == "recall_more":
            cues = step.params.get("cues", [context.text])
            return self.memory.recall(cues, top_k=self.cognition.get("recall_top_k", 5))
        if action == "user_script":
            return "user_script step deferred (coding-tier sandbox)"
        if action == "delegate":
            return self._handle_delegation(step, context)
        return f"unknown action: {action}"

    def _handle_delegation(self, step: Step, context: Context) -> str:
        from wrappers.orchestrator import (
            delegate_task,
            load_worker_roster,
            select_worker,
        )

        task_text = step.params.get("task", context.text)
        task_type = step.params.get("task_type", "general")

        roster = load_worker_roster()
        if not roster:
            return "No workers available. All workers are offline or not configured."

        worker = select_worker(roster, task_type)
        if not worker:
            return "No worker matched for this task type."

        task_id = delegate_task(self.client, worker, task_text, task_type)
        if not task_id:
            return f"Failed to delegate to {worker['profile'].name}."

        if not hasattr(self, "_pending_delegations"):
            self._pending_delegations = {}
        self._pending_delegations[task_id] = {
            "worker_name": worker["profile"].name,
            "msg_id": task_id,
            "discord_user_id": getattr(self, "_current_discord_user_id", None),
        }

        logger.info(
            "Delegated task to %s (msg_id=%s, type=%s)",
            worker["profile"].name,
            task_id,
            task_type,
        )
        return f"Working on it — delegated to {worker['profile'].name}. I'll get back to you shortly."

    @staticmethod
    def _run_local_tool(params: dict) -> str:
        from wrappers import tools

        name = params.get("name", "")
        if name == "file_read":
            return tools.file_read(params.get("path", ""))
        if name == "file_append_markdown":
            tools.file_append_markdown(params.get("path", ""), params.get("content", ""))
            return "appended"
        return f"unknown local tool: {name}"

    def _call_llm(self, messages: list[dict], model: str, tier: str) -> str:
        try:
            kwargs: dict = {}
            if tier == "auto" and self.provider_name == "openrouter":
                kwargs["max_price"] = self.max_price
            return self.factory.complete(messages=messages, model=model, **kwargs)
        except Exception:
            logger.exception("LLM call failed (model=%s)", model)
            return "I had trouble processing that request. Please try again."

    # ------------------------------------------------------------------
    # REFLECT
    # ------------------------------------------------------------------
    def reflect(self, message_text: str, result: str, trace: list[dict]) -> ReflectionDiff:
        trace_repr = "\n".join(
            f"- action={t.get('action')}; params={t.get('params')}; output={t.get('output')!r}; rationale={t.get('rationale')}"
            for t in trace
        )
        prompt = REFLECT_PROMPT.format(message=message_text, result=result, trace=trace_repr or "(no steps)")
        try:
            data = self.factory.complete_structured(
                messages=[{"role": "user", "content": prompt}],
                model=self.models.get("strong", ""),
                response_schema=REFLECT_SCHEMA,
                temperature=0.0,
            )
            return self._coerce_reflection(data)
        except Exception:
            logger.exception("REFLECT LLM failed — skipping reflection this turn")
            return ReflectionDiff()

    @staticmethod
    def _coerce_reflection(data: dict) -> ReflectionDiff:
        return ReflectionDiff(
            quality=float(data.get("quality", 0.0) or 0.0),
            critique=data.get("critique", "") or "",
            keep=list(data.get("keep", []) or []),
            self_edit=data.get("self_edit"),
            lesson=data.get("lesson"),
        )

    # ------------------------------------------------------------------
    # LEARN
    # ------------------------------------------------------------------
    def learn(self, reflection: ReflectionDiff, context: Context | None = None) -> dict:
        outcomes: dict = {"keep": [], "self_edit": {}, "lesson": None}
        lesson = reflection.lesson or {}

        for line in reflection.keep:
            if not line:
                continue
            # keep lines are local reflections, tagged "reflection" (not the lesson's tag)
            self.memory.append_memory("reflection", line, source="reflection")
            outcomes["keep"].append("reflection")

        outcomes["self_edit"] = self._apply_self_edit(reflection.self_edit)

        if lesson and lesson.get("is_network_useful"):
            outcomes["lesson"] = self._maybe_push_lesson(lesson, context)
        elif lesson and lesson.get("kind") == "prompt_improvement":
            self._fold_prompt_improvement(lesson)
            outcomes["lesson"] = {"folded_into": "SOUL"}
        return outcomes

    def _apply_self_edit(self, self_edit: dict | None) -> dict:
        result: dict = {}
        if not self_edit:
            return result
        persona = self_edit.get("persona")
        human = self_edit.get("human")
        if persona:
            # limit=None lets write_block read the frontmatter limit (spec §4.1/§5.1).
            # The config soul_limit is the seed default set into frontmatter at boot.
            ok, reason = self.memory.write_block("SOUL.md", persona, limit=None)
            result["persona"] = {"applied": ok, "reason": reason}
        if human:
            ok, reason = self.memory.write_block("USER.md", human, limit=None)
            result["human"] = {"applied": ok, "reason": reason}
        for line in self_edit.get("memory", []) or []:
            if line:
                self.memory.append_memory("self-edit", line, source="reflection")
        return result

    def _fold_prompt_improvement(self, lesson: dict) -> None:
        note = f"- Prompt improvement: {lesson.get('title', '')} — {lesson.get('summary', {}).get('how_to_use', '')}"
        soul = self.memory.read_block("SOUL.md").body
        if not soul.endswith("\n"):
            soul += "\n"
        ok, reason = self.memory.write_block("SOUL.md", soul + note, limit=None)
        if not ok:
            logger.warning("prompt_improvement fold into SOUL rejected: %s — degrading to MEMORY", reason)
            self.memory.append_memory("prompt-improvement", note, source="reflection")

    def _maybe_push_lesson(self, lesson: dict, context: Context | None = None) -> dict | None:
        if not self.cognition.get("auto_push_lessons", True):
            logger.debug("auto_push_lessons disabled -- lesson not pushed")
            return None
        from wrappers.scrub import scrub

        kind = lesson.get("kind", "pattern")
        title = lesson.get("title", "")
        summary = lesson.get("summary", {}) or {}
        tags = list(lesson.get("tags", []) or [])
        scrubbed_summary = scrub(summary)
        scrubbed_title = scrub(title)
        scrubbed_tags = scrub(tags)
        domain_id = None
        action_id = None
        if context is not None and context.normalization is not None:
            domain_id = context.normalization.resolved_domain_id
            action_id = context.normalization.resolved_action_id
        try:
            response = self.client.push_lesson(
                kind=kind,
                title=scrubbed_title,
                summary=scrubbed_summary,
                tags=scrubbed_tags,
                domain_id=domain_id,
                action_id=action_id,
            )
            lesson_id = response.get("lesson_id")
            if lesson_id:
                self._track_pushed_lesson(lesson_id)
            logger.info("Pushed lesson: %s", response)
            from wrappers.tools import message_user
            msg = f"[Hermes] Shared 1 lesson with the KidEconomy network: \"{scrubbed_title}\" (id: {lesson_id})"
            message_user(msg)
            return response
        except Exception:
            logger.exception("push_lesson failed -- swallowed; turn continues")
            return None

    @staticmethod
    def _track_pushed_lesson(lesson_id: str) -> list:
        from pathlib import Path
        import json as _json
        path = Path.home() / "kidecon" / "memory" / ".pushed_lessons.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if path.exists():
            try:
                existing = _json.loads(path.read_text())
            except Exception:
                existing = []
        existing.append(lesson_id)
        path.write_text(_json.dumps(existing, indent=2))
        return existing

    # ------------------------------------------------------------------
    # session + respond
    # ------------------------------------------------------------------
    def _append_session(
        self,
        source: str,
        context: Context,
        text: str,
        result: str,
        tier: str,
        msg_id: str,
    ) -> None:
        if source not in ("discord", "discord_dm"):
            return
        from datetime import UTC
        from datetime import datetime

        user_id = context.user_id
        ts = datetime.now(UTC).isoformat()
        norm_meta = {}
        if context.normalization is not None:
            norm_meta = {
                "domain_id": context.normalization.resolved_domain_id,
                "action_id": context.normalization.resolved_action_id,
                "confidence": context.normalization.confidence,
                "source": context.normalization.source,
            }
        self.sessions.append(
            source,
            user_id,
            {"ts": ts, "role": "user", "text": text, "tier": tier, "msg_id": msg_id, "norm": norm_meta},
        )
        self.sessions.append(
            source,
            user_id,
            {"ts": ts, "role": "assistant", "text": result, "tier": tier, "msg_id": msg_id},
        )
