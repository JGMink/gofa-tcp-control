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
import time
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
        self._on_change_callbacks: List = []  # called when ISA changes (e.g. learn_composite)

    def on_change(self, callback):
        """Register a callback to be notified when the instruction set changes."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self):
        """Notify all registered listeners that the ISA has changed."""
        for cb in self._on_change_callbacks:
            try:
                cb()
            except Exception as e:
                print(f"[WARN] ISA change callback failed: {e}")

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
        """Get all primitive instructions, excluding metadata keys."""
        return {
            k: v for k, v in self.instruction_set.get("primitives", {}).items()
            if not k.startswith("_") and isinstance(v, dict)
        }

    def get_composites(self) -> Dict:
        """Get all composite instructions, excluding metadata keys and learned composites."""
        composites = {
            k: v for k, v in self.instruction_set.get("composites", {}).items()
            if not k.startswith("_") and isinstance(v, dict)
        }
        learned = {
            k: v for k, v in self.instruction_set.get("learned_composites", {}).items()
            if not k.startswith("_") and isinstance(v, dict)
        }
        return {**composites, **learned}

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
        self._notify_change()
        return True

    # -------------------------------------------------------------------------
    # Context Generation for LLM
    # -------------------------------------------------------------------------

    def get_llm_context(self) -> str:
        """
        Generate context string for the sequence interpreter LLM prompt.
        Only includes llm_visible instructions. Reads speed/distance params
        from motion_params in scene_context (v3.0 schema).
        """
        lines = []

        # ── Primitives (llm_visible only) + Composites ───────────────────────
        lines.append("AVAILABLE INSTRUCTIONS (call these by name in your sequence):")
        for name, info in self.get_primitives().items():
            if not info.get("llm_visible", False):
                continue
            params = info.get("parameters", {})
            param_str = ", ".join(params.keys()) if params else ""
            desc = info.get("description", "").split(".")[0]
            lines.append(f"  - {name}({param_str}): {desc} [primitive]")
        for name, info in self.get_composites().items():
            if not info.get("llm_visible", True):
                continue
            params = info.get("parameters", {})
            param_str = ", ".join(params.keys()) if params else ""
            learned = " [learned]" if info.get("learned") else ""
            runtime = " [runtime]" if info.get("runtime") else ""
            desc = info.get("description", "").split(".")[0]
            lines.append(f"  - {name}({param_str}): {desc}{runtime}{learned}")

        lines.append("")

        # ── Items ─────────────────────────────────────────────────────────────
        lines.append("AVAILABLE ITEMS (valid values for 'item' parameter):")
        for name, info in self.get_items().items():
            if name.startswith("_"):
                continue
            fragile = " [fragile]" if info.get("properties", {}).get("fragile") else ""
            desc = info.get("description", "")
            # Strip physical dimensions — keep only the alias hint after the em dash
            if " — " in desc:
                desc = desc.split(" — ", 1)[1]
            lines.append(f"  - {name}{fragile}: {desc}")

        lines.append("")

        # ── Locations ─────────────────────────────────────────────────────────
        lines.append("NAMED LOCATIONS (valid values for 'location' parameter):")
        for name, info in self.get_locations().items():
            if name.startswith("_"):
                continue
            desc = info.get("description", "")
            # Trim to first sentence only
            desc = desc.split(".")[0].split(" Also aliased")[0].strip()
            lines.append(f"  - {name}: {desc}")

        lines.append("")

        # ── Current state ─────────────────────────────────────────────────────
        state = self.get_state()
        gripper = state.get("gripper", "open")
        holding = state.get("holding") or "nothing"
        speed = state.get("speed", "normal")

        # Stack state — v3.0 uses state.stacks dict
        stacks = state.get("stacks", {})
        stack_lines = []
        if stacks:
            for zone, sdata in stacks.items():
                if isinstance(sdata, dict):
                    items = sdata.get("items", [])
                    height = sdata.get("height", len(items))
                    constraints = self.scene_context.get("constraints", {})
                    max_h = constraints.get("max_stack_height", 8)
                    status = "FULL" if height >= max_h else ("occupied" if items else "empty")
                    stack_lines.append(f"      {zone}: {items} ({status}, height {height}/{max_h})")
        else:
            # fallback for old schema
            fallback = state.get("assembly_stack", [])
            stack_lines.append(f"      assembly_fixture: {fallback}")
        stack_str = "\n".join(stack_lines) if stack_lines else "      (none)"

        active_zone = state.get("active_zone", "assembly_fixture")
        lines.append("CURRENT STATE:")
        lines.append(f"  - Gripper: {gripper}")
        lines.append(f"  - Holding: {holding}")
        lines.append(f"  - Speed: {speed}")
        lines.append(f"  - Active zone: {active_zone}")
        lines.append(f"  - Assembly zones:")
        lines.append(stack_str)

        lines.append("")

        # ── Speed aliases ─────────────────────────────────────────────────────
        motion = self.scene_context.get("motion_params", {})
        speed_profiles = motion.get("speed_profiles", {})
        if not speed_profiles:
            # fallback for old schema
            speed_profiles = self.scene_context.get("speed_modifiers", {})
        if speed_profiles:
            lines.append("SPEED WORDS (use with adjust_speed):")
            for level, info in speed_profiles.items():
                if isinstance(info, dict):
                    aliases = ", ".join(info.get("aliases", [level]))
                    lines.append(f"  - \"{level}\": {aliases}")
            lines.append("")

        # ── Recipes ───────────────────────────────────────────────────────────
        recipes = self.scene_context.get("recipes", {})
        if recipes:
            lines.append("KNOWN RECIPES:")
            for name, info in recipes.items():
                if name.startswith("_") or not isinstance(info, dict):
                    continue
                layers = " → ".join(info.get("layers", []))
                aliases = ", ".join(info.get("aliases", []))
                lines.append(f"  - {name}: {layers}")
                if aliases:
                    lines.append(f"    also called: {aliases}")
            lines.append("")

        # ── Modifiers ─────────────────────────────────────────────────────────
        modifiers = self.scene_context.get("modifiers", {})
        if modifiers:
            lines.append("RECIPE MODIFIERS:")
            for word, info in modifiers.items():
                if word.startswith("_") or not isinstance(info, dict):
                    continue
                examples = ", ".join(info.get("examples", []))
                lines.append(f"  - \"{word}\": {info.get('description', '')}  e.g. {examples}")
            lines.append("")

        # ── Constraints ───────────────────────────────────────────────────────
        constraints = self.scene_context.get("constraints", {})
        if constraints:
            lines.append("CONSTRAINTS:")
            lines.append(f"  - Max stack height: {constraints.get('max_stack_height', 8)} layers")
            tile_h = motion.get("defaults", {}).get("tile_height_cm",
                     constraints.get("tile_height_cm", 1.0))
            lines.append(f"  - Each tile = {tile_h}cm height")
            lines.append("")

        # ── Learned composites summary (names only) ───────────────────────────
        learned = {
            k: v for k, v in self.instruction_set.get("learned_composites", {}).items()
            if not k.startswith("_") and isinstance(v, dict)
        }
        if learned:
            lines.append("ALREADY LEARNED (call by name — do not redefine):")
            for name, info in learned.items():
                lines.append(f"  - {name}: {info.get('description', '')}")
            lines.append("")

        # ── Canonical examples ────────────────────────────────────────────────
        lines.append("EXAMPLE — \"make a classic sandwich\":")
        lines.append('  [')
        lines.append('    {"instruction": "add_layer", "params": {"item": "bread"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "meat"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "lettuce"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "tomato"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "bread"}},')
        lines.append('    {"instruction": "go_home", "params": {}}')
        lines.append('  ]')
        lines.append("")
        lines.append("EXAMPLE — \"BLT, nice and slow, double lettuce, no tomato\":")
        lines.append('  [')
        lines.append('    {"instruction": "adjust_speed", "params": {"modifier": "slow"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "bread"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "meat"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "lettuce"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "lettuce"}},')
        lines.append('    {"instruction": "add_layer", "params": {"item": "bread"}},')
        lines.append('    {"instruction": "go_home", "params": {}}')
        lines.append('  ]')

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

    # How long to wait for Unity to acknowledge a move (seconds)
    ACK_TIMEOUT      = 10.0
    # How often to poll tcp_ack.json while waiting (seconds)
    ACK_POLL_INTERVAL = 0.05

    def __init__(self, compiler: InstructionCompiler, command_queue_file: str = None):
        self.compiler = compiler
        self.command_queue_file = command_queue_file or os.path.join(
            LEARNING_DIR, "..", "..", "UnityProject", "tcp_commands.json"
        )
        # Acknowledgement file — Unity writes here after each move completes
        self.ack_file = self.command_queue_file.replace(
            "tcp_commands.json", "tcp_ack.json"
        )

        # Gripper position in metres (0.0 = closed, 0.11 = fully open — RG2 range)
        self.gripper_position: float = self._load_gripper_from_file()

        # Current position (synced from scene context, then overridden by live file)
        self._sync_position_from_context()
        self._sync_position_from_file()

    # ------------------------------------------------------------------
    # Startup sync helpers
    # ------------------------------------------------------------------

    def _load_gripper_from_file(self) -> float:
        """Read gripper_position from tcp_commands.json so we start from the live state."""
        try:
            path = self.command_queue_file
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                return float(data.get("gripper_position", 0.11))
        except Exception:
            pass
        return 0.11  # default: fully open

    def _sync_position_from_file(self):
        """Override context position with the live tcp_commands.json value if available."""
        try:
            path = self.command_queue_file
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                if all(k in data for k in ("x", "y", "z")):
                    self.current_position = {"x": data["x"], "y": data["y"], "z": data["z"]}
        except Exception:
            pass  # keep context position on failure

    def _sync_position_from_context(self):
        """Sync current position from scene context (fallback)."""
        state = self.compiler.get_state()
        current_loc = state.get("current_position", "home")
        pos = self.compiler.get_location_position(current_loc)
        if pos:
            self.current_position = pos.copy()
        else:
            self.current_position = {"x": 0.0, "y": 0.567, "z": -0.24}

    # ------------------------------------------------------------------
    # File write + ack-wait
    # ------------------------------------------------------------------

    def _write_position_to_file(self, position: Dict):
        """
        Write position + gripper state to tcp_commands.json (fire-and-forget).
        Used for gripper-only updates where no arm movement occurs and no
        Unity ack is expected.
        """
        try:
            output = dict(position)
            output["gripper_position"] = self.gripper_position
            with open(self.command_queue_file, 'w') as f:
                json.dump(output, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to write position: {e}")

    def _send_and_wait(self, position: Dict) -> Dict:
        """
        Write a move command to tcp_commands.json, then poll tcp_ack.json
        until Unity confirms the move completed (ack timestamp is newer than
        our write time).  Returns the Unity-confirmed position dict so
        current_position can be updated from the authoritative source.

        Falls back to the locally-computed position if no ack arrives within
        ACK_TIMEOUT seconds (simulation mode / Unity not running).
        """
        output = dict(position)
        output["gripper_position"] = self.gripper_position

        # Record write time just before writing so any ack that arrives
        # after this point is definitely a response to this command.
        write_time = time.time()

        try:
            with open(self.command_queue_file, 'w') as f:
                json.dump(output, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to write command: {e}")
            return output  # fall back to local position

        # ── Poll tcp_ack.json for Unity's acknowledgement ──────────────
        # Use file mtime to detect a fresh ack: any write to tcp_ack.json
        # whose mtime is >= write_time is a response to this command.
        deadline = write_time + self.ACK_TIMEOUT
        while time.time() < deadline:
            time.sleep(self.ACK_POLL_INTERVAL)
            try:
                if not os.path.exists(self.ack_file):
                    continue

                ack_mtime = os.path.getmtime(self.ack_file)
                if ack_mtime < write_time:
                    continue  # stale ack from a previous command

                with open(self.ack_file, 'r') as f:
                    ack = json.load(f)

                if ack.get("completed", False):
                    # Unity confirmed this move — read back the authoritative position
                    confirmed = ack.get("position", {})
                    confirmed_pos = {
                        "x": float(confirmed.get("x", output["x"])),
                        "y": float(confirmed.get("y", output["y"])),
                        "z": float(confirmed.get("z", output["z"])),
                    }
                    # Sync gripper from ack if Unity echoed it
                    if "gripper_position" in confirmed:
                        self.gripper_position = float(confirmed["gripper_position"])
                    return confirmed_pos

            except (json.JSONDecodeError, OSError):
                continue  # file mid-write — retry

        # Timeout — Unity not responding (simulation / disconnected)
        print(f"[WARN] No ack received within {self.ACK_TIMEOUT}s — using local position")
        return output  # return locally-computed position as fallback

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

        # Send command and wait for Unity to confirm arrival
        confirmed = self._send_and_wait(position)
        self.current_position = confirmed
        self.compiler.update_state("current_position", location)
        print(f"    [EXEC] move_to('{location}') -> {confirmed}")
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

        # Send command and wait for Unity to confirm arrival
        confirmed = self._send_and_wait(new_position)
        self.current_position = confirmed
        print(f"    [EXEC] move_relative('{direction}', {distance}) -> {confirmed}")
        return True

    def _execute_gripper_open(self, params: Dict) -> bool:
        """
        gripper_open() - Open the gripper to release item.
        Updates gripper_position to fully open and writes to tcp_commands.json.
        """
        state = self.compiler.get_state()
        holding = state.get("holding")

        self.compiler.update_state("gripper", "open")
        self.gripper_position = 0.11  # fully open (110 mm)

        if holding:
            self.compiler.update_state("holding", None)
            print(f"    [EXEC] gripper_open() - released '{holding}'")
        else:
            print(f"    [EXEC] gripper_open()")

        # Write to file so Unity sees the gripper change immediately
        self._write_position_to_file(self.current_position)
        return True

    def _execute_gripper_close(self, params: Dict) -> bool:
        """
        gripper_close() - Close the gripper to grab item.
        If at an item stack, picks up that item.
        Writes updated gripper_position to tcp_commands.json.
        """
        self.compiler.update_state("gripper", "closed")
        self.gripper_position = 0.0  # fully closed

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
                    self._write_position_to_file(self.current_position)
                    return True

        print(f"    [EXEC] gripper_close()")
        self._write_position_to_file(self.current_position)
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

    def _execute_set_speed(self, params: Dict) -> bool:
        """
        set_speed(speed) - Set robot movement speed.
        Delegates to SandwichExecutor for the actual speed mapping logic.
        """
        try:
            from .sandwich_executor import get_sandwich_executor
            return get_sandwich_executor().execute_set_speed(params)
        except ImportError:
            print(f"    [EXEC] set_speed('{params.get('speed', 'normal')}') - stub, no sandwich executor")
            return True

    # -------------------------------------------------------------------------
    # Main Execution
    # -------------------------------------------------------------------------

    def execute_step(self, step: ExecutionStep) -> bool:
        """Execute a single step. Delegates to SandwichExecutor for sandwich-specific instructions."""
        executors = {
            "move_to": self._execute_move_to,
            "move_relative": self._execute_move_relative,
            "gripper_open": self._execute_gripper_open,
            "gripper_close": self._execute_gripper_close,
            "wait": self._execute_wait,
            "set_speed": self._execute_set_speed,
        }

        executor = executors.get(step.instruction)
        if executor:
            return executor(step.params)

        # Delegate to SandwichExecutor for sandwich-level instructions
        try:
            from .sandwich_executor import get_sandwich_executor
            sandwich_exec = get_sandwich_executor()
            if sandwich_exec.can_handle(step.instruction):
                return sandwich_exec.execute(step.instruction, step.params)
        except ImportError:
            pass

        print(f"[ERROR] No executor for instruction: {step.instruction}")
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
