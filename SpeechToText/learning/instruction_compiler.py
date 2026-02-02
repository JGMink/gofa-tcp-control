"""
Instruction Compiler - Hierarchical instruction system for robot control.

Implements a von Neumann-style architecture where:
- Primitives are atomic operations (move_to, gripper_open, etc.)
- Composites are sequences of primitives or other composites
- LLM can generate new composites from natural language
- Confident interpretations are learned for future use
"""

import json
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

# Paths
LEARNING_DIR = os.path.dirname(__file__)
INSTRUCTION_SET_FILE = os.path.join(LEARNING_DIR, "instruction_set.json")
SCENE_CONTEXT_FILE = os.path.join(LEARNING_DIR, "scene_context.json")


@dataclass
class ExecutionStep:
    """A single step in an execution plan."""
    instruction: str
    params: Dict[str, Any]
    is_primitive: bool
    description: str = ""


@dataclass
class ExecutionPlan:
    """A compiled execution plan ready to run."""
    steps: List[ExecutionStep]
    source_command: str
    composite_name: Optional[str] = None
    confidence: float = 1.0


class InstructionCompiler:
    """
    Compiles natural language commands into executable instruction sequences.
    Manages the instruction set and learns new composites.
    """

    def __init__(self):
        self.instruction_set = self._load_instruction_set()
        self.scene_context = self._load_scene_context()
        self.execution_history: List[ExecutionPlan] = []

    def _load_instruction_set(self) -> Dict:
        """Load the instruction set from JSON."""
        try:
            with open(INSTRUCTION_SET_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[WARN] Instruction set not found at {INSTRUCTION_SET_FILE}")
            return {"primitives": {}, "composites": {}, "meta": {}}

    def _load_scene_context(self) -> Dict:
        """Load the scene context from JSON."""
        try:
            with open(SCENE_CONTEXT_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[WARN] Scene context not found at {SCENE_CONTEXT_FILE}")
            return {"items": {}, "locations": {}, "state": {}}

    def save_instruction_set(self):
        """Save the instruction set back to JSON."""
        with open(INSTRUCTION_SET_FILE, 'w') as f:
            json.dump(self.instruction_set, f, indent=2)

    def save_scene_context(self):
        """Save the scene context back to JSON."""
        with open(SCENE_CONTEXT_FILE, 'w') as f:
            json.dump(self.scene_context, f, indent=2)

    # -------------------------------------------------------------------------
    # Instruction Set Queries
    # -------------------------------------------------------------------------

    def get_primitives(self) -> Dict:
        """Get all primitive instructions."""
        return self.instruction_set.get("primitives", {})

    def get_composites(self) -> Dict:
        """Get all composite instructions."""
        return self.instruction_set.get("composites", {})

    def get_instruction(self, name: str) -> Optional[Dict]:
        """Get an instruction by name (primitive or composite)."""
        if name in self.get_primitives():
            return {"type": "primitive", **self.get_primitives()[name]}
        if name in self.get_composites():
            return {"type": "composite", **self.get_composites()[name]}
        return None

    def is_primitive(self, name: str) -> bool:
        """Check if an instruction is a primitive."""
        return name in self.get_primitives()

    def is_composite(self, name: str) -> bool:
        """Check if an instruction is a composite."""
        return name in self.get_composites()

    # -------------------------------------------------------------------------
    # Scene Context Queries
    # -------------------------------------------------------------------------

    def get_items(self) -> Dict:
        """Get all items in the scene."""
        return self.scene_context.get("items", {})

    def get_locations(self) -> Dict:
        """Get all locations in the scene."""
        return self.scene_context.get("locations", {})

    def get_location_position(self, location_name: str) -> Optional[Dict]:
        """Get the position of a named location."""
        locations = self.get_locations()
        if location_name in locations:
            return locations[location_name].get("position")
        return None

    def get_state(self) -> Dict:
        """Get current scene state."""
        return self.scene_context.get("state", {})

    def update_state(self, key: str, value: Any):
        """Update a state value."""
        if "state" not in self.scene_context:
            self.scene_context["state"] = {}
        self.scene_context["state"][key] = value

    # -------------------------------------------------------------------------
    # Parameter Substitution
    # -------------------------------------------------------------------------

    def _substitute_params(self, template: Any, params: Dict[str, Any]) -> Any:
        """
        Substitute {param_name} placeholders in a template.
        Works recursively on dicts, lists, and strings.
        """
        if isinstance(template, str):
            # Replace {param} with actual value
            result = template
            for key, value in params.items():
                result = result.replace(f"{{{key}}}", str(value))
            return result
        elif isinstance(template, dict):
            return {k: self._substitute_params(v, params) for k, v in template.items()}
        elif isinstance(template, list):
            return [self._substitute_params(item, params) for item in template]
        else:
            return template

    # -------------------------------------------------------------------------
    # Compilation
    # -------------------------------------------------------------------------

    def compile_instruction(self, name: str, params: Dict[str, Any] = None) -> Optional[ExecutionPlan]:
        """
        Compile a single instruction into an execution plan.
        Recursively expands composites into primitives.
        """
        params = params or {}
        instruction = self.get_instruction(name)

        if instruction is None:
            print(f"[ERROR] Unknown instruction: {name}")
            return None

        if instruction["type"] == "primitive":
            # Primitive - single step
            step = ExecutionStep(
                instruction=name,
                params=params,
                is_primitive=True,
                description=instruction.get("description", "")
            )
            return ExecutionPlan(
                steps=[step],
                source_command=f"{name}({params})",
                confidence=1.0
            )

        else:
            # Composite - expand sequence
            sequence = instruction.get("sequence", [])
            all_steps = []

            for seq_item in sequence:
                sub_instruction = seq_item["instruction"]
                sub_params = self._substitute_params(seq_item.get("params", {}), params)

                # Recursively compile
                sub_plan = self.compile_instruction(sub_instruction, sub_params)
                if sub_plan:
                    all_steps.extend(sub_plan.steps)

            return ExecutionPlan(
                steps=all_steps,
                source_command=f"{name}({params})",
                composite_name=name,
                confidence=instruction.get("confidence", 1.0)
            )

    def compile_sequence(self, instructions: List[Dict]) -> ExecutionPlan:
        """
        Compile a sequence of instructions into a single execution plan.
        Each item should have 'instruction' and optional 'params'.
        """
        all_steps = []
        source_parts = []

        for item in instructions:
            name = item.get("instruction")
            params = item.get("params", {})

            plan = self.compile_instruction(name, params)
            if plan:
                all_steps.extend(plan.steps)
                source_parts.append(plan.source_command)

        return ExecutionPlan(
            steps=all_steps,
            source_command=" -> ".join(source_parts)
        )

    # -------------------------------------------------------------------------
    # Learning New Composites
    # -------------------------------------------------------------------------

    def learn_composite(
        self,
        name: str,
        description: str,
        parameters: Dict[str, str],
        sequence: List[Dict],
        confidence: float = 0.9,
        source_phrase: str = ""
    ) -> bool:
        """
        Learn a new composite instruction.

        Args:
            name: Name for the new composite (e.g., "make_blt")
            description: Human-readable description
            parameters: Dict mapping param names to descriptions
            sequence: List of instruction steps
            confidence: LLM confidence in this interpretation
            source_phrase: Original voice command that triggered learning

        Returns:
            True if successfully learned
        """
        # Validate that all referenced instructions exist
        for step in sequence:
            inst_name = step.get("instruction")
            if not self.get_instruction(inst_name):
                print(f"[WARN] Cannot learn '{name}': unknown instruction '{inst_name}'")
                return False

        # Add to composites
        self.instruction_set["composites"][name] = {
            "description": description,
            "parameters": parameters,
            "sequence": sequence,
            "learned": True,
            "confidence": confidence,
            "source_phrase": source_phrase,
            "learned_at": datetime.now().isoformat()
        }

        # Save
        self.save_instruction_set()
        print(f"[LEARN] New composite: '{name}' ({len(sequence)} steps, conf={confidence:.2f})")
        return True

    # -------------------------------------------------------------------------
    # Context Generation for LLM
    # -------------------------------------------------------------------------

    def get_llm_context(self) -> str:
        """
        Generate context string for LLM prompt.
        Includes available instructions, items, locations, and state.
        """
        lines = []

        # Primitives
        lines.append("PRIMITIVE INSTRUCTIONS (atomic operations):")
        for name, info in self.get_primitives().items():
            params = info.get("parameters", {})
            param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "none"
            lines.append(f"  - {name}({param_str}): {info.get('description', '')}")

        lines.append("")

        # Composites
        lines.append("COMPOSITE INSTRUCTIONS (can be used as single commands):")
        for name, info in self.get_composites().items():
            params = info.get("parameters", {})
            param_str = ", ".join(params.keys()) if params else "none"
            learned = " [learned]" if info.get("learned") else ""
            lines.append(f"  - {name}({param_str}): {info.get('description', '')}{learned}")

        lines.append("")

        # Items
        lines.append("AVAILABLE ITEMS:")
        for name, info in self.get_items().items():
            lines.append(f"  - {name}: {info.get('description', '')} (at {info.get('stack_location', 'unknown')})")

        lines.append("")

        # Locations
        lines.append("NAMED LOCATIONS:")
        for name, info in self.get_locations().items():
            lines.append(f"  - {name}: {info.get('description', '')}")

        lines.append("")

        # Current state
        state = self.get_state()
        lines.append("CURRENT STATE:")
        lines.append(f"  - Gripper: {state.get('gripper', 'unknown')}")
        lines.append(f"  - Holding: {state.get('holding', 'nothing')}")
        lines.append(f"  - Assembly stack: {state.get('assembly_stack', [])}")

        # Recipes (for sandwich context)
        recipes = self.scene_context.get("recipes", {})
        if recipes:
            lines.append("")
            lines.append("KNOWN RECIPES:")
            for name, info in recipes.items():
                layers = " -> ".join(info.get("layers", []))
                lines.append(f"  - {name}: {layers}")

        return "\n".join(lines)

    def get_instruction_list_for_prompt(self) -> str:
        """Get a compact list of available instructions for LLM prompt."""
        instructions = []

        for name in self.get_primitives().keys():
            instructions.append(name)

        for name in self.get_composites().keys():
            instructions.append(name)

        return ", ".join(instructions)


# -----------------------------------------------------------------------------
# Instruction Executor - Runs compiled plans
# -----------------------------------------------------------------------------

class InstructionExecutor:
    """
    Executes compiled instruction plans.
    Each primitive has actual code that manipulates robot state.
    """

    # Scale factor for distances (cm to Unity units)
    DISTANCE_SCALE = 0.01

    def __init__(self, compiler: InstructionCompiler, command_queue_file: str = None):
        self.compiler = compiler
        self.command_queue_file = command_queue_file or os.path.join(
            LEARNING_DIR, "..", "..", "UnityProject", "tcp_commands.json"
        )

        # Current position (synced from scene context)
        self._sync_position_from_context()

    def _sync_position_from_context(self):
        """Sync current position from scene context."""
        state = self.compiler.get_state()
        current_loc = state.get("current_position", "home")
        pos = self.compiler.get_location_position(current_loc)
        if pos:
            self.current_position = pos.copy()
        else:
            self.current_position = {"x": 0.0, "y": 0.567, "z": -0.24}

    def _write_position_to_file(self, position: Dict):
        """Write position to the command queue file for Unity."""
        try:
            with open(self.command_queue_file, 'w') as f:
                json.dump(position, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to write position: {e}")

    # -------------------------------------------------------------------------
    # Primitive Executors
    # -------------------------------------------------------------------------

    def _execute_move_to(self, params: Dict) -> bool:
        """
        move_to(location) - Move to a named location.
        Updates current position and writes to file.
        """
        location = params.get("location")
        if not location:
            print("[ERROR] move_to: missing 'location' parameter")
            return False

        position = self.compiler.get_location_position(location)
        if not position:
            print(f"[ERROR] move_to: unknown location '{location}'")
            return False

        # Update state
        self.current_position = position.copy()
        self.compiler.update_state("current_position", location)

        # Write to file
        self._write_position_to_file(position)
        print(f"    [EXEC] move_to('{location}') -> {position}")
        return True

    def _execute_move_relative(self, params: Dict) -> bool:
        """
        move_relative(direction, distance) - Move relative to current position.
        Direction: right/left/up/down/forward/backward
        Distance: in cm (scaled by DISTANCE_SCALE)
        """
        direction = params.get("direction", "").lower()
        distance = float(params.get("distance", 1.0))

        # Direction to delta mapping
        direction_deltas = {
            "right":    {"x": 1, "y": 0, "z": 0},
            "left":     {"x": -1, "y": 0, "z": 0},
            "up":       {"x": 0, "y": 1, "z": 0},
            "down":     {"x": 0, "y": -1, "z": 0},
            "forward":  {"x": 0, "y": 0, "z": 1},
            "backward": {"x": 0, "y": 0, "z": -1},
        }

        if direction not in direction_deltas:
            print(f"[ERROR] move_relative: unknown direction '{direction}'")
            return False

        delta = direction_deltas[direction]
        scaled_distance = distance * self.DISTANCE_SCALE

        new_position = {
            "x": self.current_position["x"] + delta["x"] * scaled_distance,
            "y": self.current_position["y"] + delta["y"] * scaled_distance,
            "z": self.current_position["z"] + delta["z"] * scaled_distance,
        }

        self.current_position = new_position
        self._write_position_to_file(new_position)
        print(f"    [EXEC] move_relative('{direction}', {distance}) -> {new_position}")
        return True

    def _execute_gripper_open(self, params: Dict) -> bool:
        """
        gripper_open() - Open the gripper to release item.
        """
        state = self.compiler.get_state()
        holding = state.get("holding")

        self.compiler.update_state("gripper", "open")

        if holding:
            # Item is released at current location
            self.compiler.update_state("holding", None)
            print(f"    [EXEC] gripper_open() - released '{holding}'")
        else:
            print(f"    [EXEC] gripper_open()")

        return True

    def _execute_gripper_close(self, params: Dict) -> bool:
        """
        gripper_close() - Close the gripper to grab item.
        If at an item stack, picks up that item.
        """
        self.compiler.update_state("gripper", "closed")

        # Check if we're at an item stack
        state = self.compiler.get_state()
        current_loc = state.get("current_position", "")

        locations = self.compiler.get_locations()
        if current_loc in locations:
            loc_info = locations[current_loc]
            if loc_info.get("type") == "item_stack":
                item = loc_info.get("item")
                if item:
                    self.compiler.update_state("holding", item)
                    print(f"    [EXEC] gripper_close() - grabbed '{item}'")
                    return True

        print(f"    [EXEC] gripper_close()")
        return True

    def _execute_wait(self, params: Dict) -> bool:
        """
        wait(seconds) - Pause execution.
        """
        import time
        seconds = float(params.get("seconds", 0.5))
        print(f"    [EXEC] wait({seconds}s)")
        time.sleep(seconds)
        return True

    # -------------------------------------------------------------------------
    # Main Execution
    # -------------------------------------------------------------------------

    def execute_step(self, step: ExecutionStep) -> bool:
        """Execute a single step."""
        executors = {
            "move_to": self._execute_move_to,
            "move_relative": self._execute_move_relative,
            "gripper_open": self._execute_gripper_open,
            "gripper_close": self._execute_gripper_close,
            "wait": self._execute_wait,
        }

        executor = executors.get(step.instruction)
        if executor:
            return executor(step.params)
        else:
            print(f"[ERROR] No executor for primitive: {step.instruction}")
            return False

    def execute_plan(self, plan: ExecutionPlan) -> bool:
        """
        Execute a full execution plan.
        Returns True if all steps succeeded.
        """
        print(f"[EXEC] Running plan: {plan.source_command}")
        print(f"       ({len(plan.steps)} steps)")

        for i, step in enumerate(plan.steps):
            if not step.is_primitive:
                print(f"[ERROR] Step {i+1} is not a primitive: {step.instruction}")
                return False

            success = self.execute_step(step)
            if not success:
                print(f"[ERROR] Step {i+1} failed: {step.instruction}")
                return False

        print(f"[EXEC] Plan completed successfully")
        return True


# -----------------------------------------------------------------------------
# Singleton instances
# -----------------------------------------------------------------------------

_compiler_instance = None
_executor_instance = None

def get_compiler() -> InstructionCompiler:
    """Get the singleton InstructionCompiler instance."""
    global _compiler_instance
    if _compiler_instance is None:
        _compiler_instance = InstructionCompiler()
    return _compiler_instance

def get_executor() -> InstructionExecutor:
    """Get the singleton InstructionExecutor instance."""
    global _executor_instance, _compiler_instance
    if _executor_instance is None:
        compiler = get_compiler()
        _executor_instance = InstructionExecutor(compiler)
    return _executor_instance


# -----------------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------------

def test_compiler():
    """Test the instruction compiler."""
    compiler = InstructionCompiler()

    print("=== Instruction Compiler Test ===\n")

    # Show context
    print("LLM Context:")
    print(compiler.get_llm_context())
    print()

    # Test compilation
    print("Testing compilation of 'pick_up' with item='cheese':")
    plan = compiler.compile_instruction("pick_up", {"item": "cheese"})
    if plan:
        print(f"  Source: {plan.source_command}")
        print(f"  Steps ({len(plan.steps)}):")
        for i, step in enumerate(plan.steps):
            print(f"    {i+1}. {step.instruction}({step.params})")
    print()

    # Test transfer
    print("Testing compilation of 'transfer' with item='tomato', destination='assembly_zone':")
    plan = compiler.compile_instruction("transfer", {"item": "tomato", "destination": "assembly_zone"})
    if plan:
        print(f"  Steps ({len(plan.steps)}):")
        for i, step in enumerate(plan.steps):
            print(f"    {i+1}. {step.instruction}({step.params})")


if __name__ == "__main__":
    test_compiler()
