"""Unit tests for system instruction and tool declarations."""

from server.prompts import SYSTEM_INSTRUCTION, build_tool_declarations, TOOL_DECLARATIONS


class TestSystemInstruction:
    def test_not_empty(self):
        assert len(SYSTEM_INSTRUCTION) > 100

    def test_identity_section(self):
        assert "SousChef" in SYSTEM_INSTRUCTION

    def test_no_as_an_ai(self):
        assert "as an AI" in SYSTEM_INSTRUCTION  # rule about not saying it

    def test_proactive_timer_rule(self):
        assert "set_timer" in SYSTEM_INSTRUCTION

    def test_intervention_rules(self):
        assert "interrupt" in SYSTEM_INSTRUCTION.lower()

    def test_knife_grip_safety_instruction(self):
        assert "curl" in SYSTEM_INSTRUCTION.lower()
        assert "finger" in SYSTEM_INSTRUCTION.lower()

    def test_substitution_instruction(self):
        assert "substitute" in SYSTEM_INSTRUCTION.lower()

    def test_recipe_tool_called_immediately(self):
        assert "SAME turn" in SYSTEM_INSTRUCTION or "same turn" in SYSTEM_INSTRUCTION

    def test_under_token_budget(self):
        # Rough estimate: ~4 chars per token
        approx_tokens = len(SYSTEM_INSTRUCTION) / 4
        assert approx_tokens < 2000


class TestToolDeclarations:
    def test_four_tools(self):
        decls = build_tool_declarations()
        assert len(decls) == 4

    def test_tool_names(self):
        names = {d["name"] for d in build_tool_declarations()}
        assert names == {"update_recipe", "set_timer", "update_cooking_step", "get_cooking_state"}

    def test_set_timer_params(self):
        decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "set_timer")
        props = decl["parameters"]["properties"]
        assert "duration_seconds" in props
        assert "label" in props
        assert decl["parameters"]["required"] == ["duration_seconds", "label"]

    def test_update_step_enum(self):
        decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "update_cooking_step")
        enum = decl["parameters"]["properties"]["step_name"]["enum"]
        assert "idle" in enum
        assert "done" in enum
        assert len(enum) == 9

    def test_get_state_no_required(self):
        decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "get_cooking_state")
        assert "required" not in decl["parameters"] or decl["parameters"].get("required") is None
