"""
Sandwich Executor - Executes sandwich-level instructions.

Extends the InstructionExecutor with sandwich-specific logic:
- add_layer: height-aware stacking at the assembly fixture
- serve: transfer completed stack to a serving plate
- clear_assembly: return all items from assembly to ingredient slots
- set_speed: change robot movement speed multiplier
- adjust_speed: map qualitative modifiers to speed settings

Each function here corresponds to a composite or primitive in
instruction_set.json that needs runtime logic beyond simple
sequence expansion (e.g., dynamic height calculation).
"""

import json
import os
from typing import Dict, Optional, List, Any

from .instruction_compiler import InstructionCompiler, InstructionExecutor, get_compiler, get_executor

LEARNING_DIR = os.path.dirname(__file__)
SCENE_CONTEXT_FILE = os.path.join(LEARNING_DIR, "scene_context.json")


# ---------------------------------------------------------------------------
# Speed modifier mapping
# ---------------------------------------------------------------------------

SPEED_MAP = {
    # Qualitative words -> canonical speed level
    "slow": "slow",
    "slower": "slow",
    "careful": "slow",
    "gentle": "slow",
    "easy": "slow",
    "nice and neat": "slow",
    "normal": "normal",
    "regular": "normal",
    "default": "normal",
    "fast": "fast",
    "faster": "fast",
    "quick": "fast",
    "hurry": "fast",
    "speed up": "fast",
}

SPEED_MULTIPLIERS = {
    "slow": 0.5,
    "normal": 1.0,
    "fast": 1.5,
}


class SandwichExecutor:
    """
    Handles sandwich-specific execution logic that requires runtime
    state beyond what the static instruction_set.json sequences provide.

    Wraps the base InstructionExecutor and adds height tracking,
    stack management, and speed control.
    """

    def __init__(self, base_executor: InstructionExecutor = None):
        self.base = base_executor or get_executor()
        self.compiler = self.base.compiler

        # Speed state
        self.speed = "normal"
        self.speed_multiplier = 1.0

        # Load assembly state from scene_context
        state = self.compiler.get_state()
        self.assembly_stack: List[str] = state.get("assembly_stack", [])
        self.assembly_stack_height: int = state.get("assembly_stack_height", 0)

    # ------------------------------------------------------------------
    # State persistence helpers
    # ------------------------------------------------------------------

    def _save_state(self):
        """Persist assembly state back to scene_context.json."""
        self.compiler.update_state("assembly_stack", self.assembly_stack.copy())
        self.compiler.update_state("assembly_stack_height", self.assembly_stack_height)
        self.compiler.update_state("speed", self.speed)
        self.compiler.save_scene_context()

    # ------------------------------------------------------------------
    # set_speed (primitive)
    # ------------------------------------------------------------------

    def execute_set_speed(self, params: Dict) -> bool:
        """
        Set the robot movement speed.

        Params:
            speed: "slow", "normal", or "fast"

        Returns True on success.
        """
        raw_speed = str(params.get("speed", "normal")).lower().strip()

        # Map qualitative words to canonical speed
        canonical = SPEED_MAP.get(raw_speed, raw_speed)
        if canonical not in SPEED_MULTIPLIERS:
            print(f"[SandwichExec] Unknown speed '{raw_speed}', defaulting to normal")
            canonical = "normal"

        self.speed = canonical
        self.speed_multiplier = SPEED_MULTIPLIERS[canonical]

        print(f"    [EXEC] set_speed('{canonical}') -> multiplier {self.speed_multiplier}x")

        self._save_state()
        return True

    # ------------------------------------------------------------------
    # adjust_speed (composite - but needs mapping logic)
    # ------------------------------------------------------------------

    def execute_adjust_speed(self, params: Dict) -> bool:
        """
        Change speed using a qualitative modifier.
        Maps words like "slower", "careful", "quick" to set_speed values.

        Params:
            modifier: qualitative word (e.g. "slower", "careful", "quick")
        """
        modifier = str(params.get("modifier", "normal")).lower().strip()
        canonical = SPEED_MAP.get(modifier, "normal")
        return self.execute_set_speed({"speed": canonical})

    # ------------------------------------------------------------------
    # add_layer (composite - needs height offset calculation)
    # ------------------------------------------------------------------

    def execute_add_layer(self, params: Dict) -> bool:
        """
        Add one ingredient layer to the assembly fixture.

        1. Pick up the item from its ingredient slot
        2. Calculate the drop-off height: base_y + (stack_height * tile_height)
        3. Place the item at the assembly fixture at that height
        4. Increment stack height and record the layer

        Params:
            item: ingredient name (bread, cheese, lettuce, tomato, meat)

        Returns True on success.
        """
        item = params.get("item")
        if not item:
            print("[SandwichExec] add_layer: missing 'item' parameter")
            return False

        # Validate item exists
        items = self.compiler.get_items()
        if item not in items:
            print(f"[SandwichExec] add_layer: unknown item '{item}'")
            return False

        # Check stack height constraint
        constraints = self.compiler.scene_context.get("constraints", {})
        max_height = constraints.get("max_stack_height", 8)
        if self.assembly_stack_height >= max_height:
            print(f"[SandwichExec] add_layer: stack full ({self.assembly_stack_height}/{max_height})")
            return False

        tile_height_cm = constraints.get("tile_height_cm", 1.0)

        # --- Step 1: Pick up from ingredient slot ---
        item_slot = f"{item}_slot"
        success = self.base._execute_move_to({"location": item_slot})
        if not success:
            return False

        success = self.base._execute_gripper_close({})
        if not success:
            return False

        # Lift up clear of the tray
        success = self.base._execute_move_relative({"direction": "up", "distance": 5.0})
        if not success:
            return False

        # --- Step 2: Move to assembly fixture ---
        success = self.base._execute_move_to({"location": "assembly_fixture"})
        if not success:
            return False

        # --- Step 3: Lower to correct stack height ---
        # The place height = move down by (clearance - stack_offset)
        # where stack_offset = stack_height * tile_height_cm
        # We go down a base amount, adjusted for current stack height
        base_lower_cm = 3.0  # base lowering distance
        stack_offset_cm = self.assembly_stack_height * tile_height_cm
        actual_lower = max(base_lower_cm - stack_offset_cm, 0.5)  # never less than 0.5cm

        success = self.base._execute_move_relative({"direction": "down", "distance": actual_lower})
        if not success:
            return False

        # --- Step 4: Release ---
        success = self.base._execute_gripper_open({})
        if not success:
            return False

        # Lift back up
        success = self.base._execute_move_relative({"direction": "up", "distance": actual_lower})
        if not success:
            return False

        # --- Step 5: Update state ---
        self.assembly_stack.append(item)
        self.assembly_stack_height += 1

        self.compiler.update_state("holding", None)
        self._save_state()

        print(f"    [EXEC] add_layer('{item}') -> stack: {self.assembly_stack} (height: {self.assembly_stack_height})")
        return True

    # ------------------------------------------------------------------
    # serve (composite - needs stack reset logic)
    # ------------------------------------------------------------------

    def execute_serve(self, params: Dict) -> bool:
        """
        Pick up the completed sandwich from the assembly fixture
        and place it on a serving plate.

        1. Move to assembly fixture
        2. Close gripper (grab stack from bottom via relief slots)
        3. Lift
        4. Move to target plate
        5. Lower and release
        6. Reset assembly state

        Params:
            plate: plate name (plate_1, plate_2, plate_3)
        """
        plate = params.get("plate", "plate_1")

        # Validate plate exists
        locations = self.compiler.get_locations()
        if plate not in locations:
            print(f"[SandwichExec] serve: unknown plate '{plate}'")
            return False

        if not self.assembly_stack:
            print("[SandwichExec] serve: nothing in assembly to serve")
            return False

        # Pick up stack from assembly
        success = self.base._execute_move_to({"location": "assembly_fixture"})
        if not success:
            return False

        success = self.base._execute_gripper_close({})
        if not success:
            return False

        success = self.base._execute_move_relative({"direction": "up", "distance": 5.0})
        if not success:
            return False

        # Place on plate
        success = self.base._execute_move_to({"location": plate})
        if not success:
            return False

        success = self.base._execute_move_relative({"direction": "down", "distance": 3.0})
        if not success:
            return False

        success = self.base._execute_gripper_open({})
        if not success:
            return False

        success = self.base._execute_move_relative({"direction": "up", "distance": 3.0})
        if not success:
            return False

        # Update plate state
        plates_state = self.compiler.get_state().get("plates", {})
        plates_state[plate] = self.assembly_stack.copy()
        self.compiler.update_state("plates", plates_state)

        # Reset assembly
        served_stack = self.assembly_stack.copy()
        self.assembly_stack = []
        self.assembly_stack_height = 0

        self.compiler.update_state("holding", None)
        self._save_state()

        print(f"    [EXEC] serve('{plate}') -> delivered {served_stack}")
        return True

    # ------------------------------------------------------------------
    # clear_assembly (dynamic - reverses the stack)
    # ------------------------------------------------------------------

    def execute_clear_assembly(self, params: Dict) -> bool:
        """
        Remove all items from the assembly fixture and return them
        to their ingredient slots. Iterates in reverse (top to bottom).

        No params required.
        """
        if not self.assembly_stack:
            print("[SandwichExec] clear_assembly: assembly already empty")
            return True

        print(f"    [EXEC] clear_assembly: returning {len(self.assembly_stack)} items")

        # Work top-to-bottom
        while self.assembly_stack:
            item = self.assembly_stack[-1]
            item_slot = f"{item}_slot"

            # Pick from assembly
            success = self.base._execute_move_to({"location": "assembly_fixture"})
            if not success:
                return False

            # Adjust height for current stack
            constraints = self.compiler.scene_context.get("constraints", {})
            tile_height_cm = constraints.get("tile_height_cm", 1.0)
            stack_offset = (self.assembly_stack_height - 1) * tile_height_cm
            lower_dist = max(3.0 - stack_offset, 0.5)

            success = self.base._execute_move_relative({"direction": "down", "distance": lower_dist})
            if not success:
                return False

            success = self.base._execute_gripper_close({})
            if not success:
                return False

            success = self.base._execute_move_relative({"direction": "up", "distance": 5.0})
            if not success:
                return False

            # Return to ingredient slot
            success = self.base._execute_move_to({"location": item_slot})
            if not success:
                return False

            success = self.base._execute_move_relative({"direction": "down", "distance": 3.0})
            if not success:
                return False

            success = self.base._execute_gripper_open({})
            if not success:
                return False

            success = self.base._execute_move_relative({"direction": "up", "distance": 3.0})
            if not success:
                return False

            # Update state
            self.assembly_stack.pop()
            self.assembly_stack_height -= 1

        self.compiler.update_state("holding", None)
        self._save_state()

        print("    [EXEC] clear_assembly: done, assembly is empty")
        return True

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def can_handle(self, instruction_name: str) -> bool:
        """Check if this executor handles the given instruction."""
        return instruction_name in self._handlers()

    def _handlers(self) -> Dict:
        return {
            "add_layer": self.execute_add_layer,
            "serve": self.execute_serve,
            "clear_assembly": self.execute_clear_assembly,
            "set_speed": self.execute_set_speed,
            "adjust_speed": self.execute_adjust_speed,
        }

    def execute(self, instruction_name: str, params: Dict) -> bool:
        """
        Execute an instruction if this executor handles it.
        Returns True on success, False on failure.
        Raises KeyError if instruction is not handled by this executor.
        """
        handlers = self._handlers()
        if instruction_name not in handlers:
            raise KeyError(f"SandwichExecutor does not handle '{instruction_name}'")
        return handlers[instruction_name](params)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_sandwich_executor_instance = None


def get_sandwich_executor() -> SandwichExecutor:
    """Get the singleton SandwichExecutor instance."""
    global _sandwich_executor_instance
    if _sandwich_executor_instance is None:
        _sandwich_executor_instance = SandwichExecutor()
    return _sandwich_executor_instance
