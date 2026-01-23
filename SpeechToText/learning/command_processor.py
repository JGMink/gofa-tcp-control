"""
Command Processor - The main entry point that orchestrates phrase bank, LLM, and executor.
"""

from typing import Optional, Dict, Any, Tuple

from .config import (
    ENABLE_LLM_FALLBACK,
    SILENT_LEARNING,
    VERBOSE_LOGGING,
    CLU_CONFIDENCE_THRESHOLD
)
from .phrase_bank import get_phrase_bank, PhraseBank
from .llm_interpreter import get_llm_interpreter, LLMInterpreter
from .intent_executor import get_executor, IntentExecutor


class CommandProcessor:
    """
    Main processor that handles the full flow:
    1. Phrase bank lookup (instant)
    2. LLM interpretation if needed (slower)
    3. Learning new phrases
    4. Executing commands
    """
    
    def __init__(self):
        self.phrase_bank: PhraseBank = get_phrase_bank()
        self.llm: LLMInterpreter = get_llm_interpreter()
        self.executor: IntentExecutor = get_executor()
        
        # Pending confirmation (for low-confidence matches)
        self.pending_confirmation: Optional[Dict[str, Any]] = None
    
    def process(self, utterance: str, clu_result: dict = None) -> Dict[str, Any]:
        """
        Process an utterance and return the result.
        
        Args:
            utterance: The speech-to-text result
            clu_result: Optional CLU result (if you want to use it)
        
        Returns:
            {
                "success": bool,
                "intent": str or None,
                "command": dict or None,
                "message": str,
                "learned": bool,
                "needs_confirmation": bool,
                "confirmation_prompt": str or None
            }
        """
        utterance = utterance.strip()
        if not utterance:
            return self._result(False, message="Empty utterance")
        
        # Check for confirmation response
        if self.pending_confirmation:
            return self._handle_confirmation(utterance)
        
        if VERBOSE_LOGGING:
            print(f"\n[CommandProcessor] Processing: '{utterance}'")
        
        # Step 1: Try phrase bank lookup
        match, confidence, needs_confirm = self.phrase_bank.lookup(utterance)
        
        if match and not needs_confirm:
            # Good match - execute directly
            intent = match["intent"]
            parameters = match.get("parameters", {})
            
            if VERBOSE_LOGGING:
                print(f"[CommandProcessor] Phrase bank match: {intent} (confidence: {confidence:.2f})")
            
            command = self.executor.execute(intent, parameters)
            return self._result(
                success=True,
                intent=intent,
                command=command,
                message=f"Executing: {intent}",
                source="phrase_bank"
            )
        
        if match and needs_confirm:
            # Low confidence match - ask for confirmation
            self.pending_confirmation = {
                "original_utterance": utterance,
                "suggested_intent": match["intent"],
                "suggested_parameters": match.get("parameters", {}),
                "confidence": confidence
            }
            
            intent_info = self.phrase_bank.get_intent_info(match["intent"])
            intent_desc = intent_info.get("description", match["intent"]) if intent_info else match["intent"]
            
            return self._result(
                success=False,
                needs_confirmation=True,
                confirmation_prompt=f"Did you mean '{intent_desc}'? Say 'yes' or 'no'.",
                message=f"Low confidence match ({confidence:.0%}), asking for confirmation"
            )
        
        # Step 2: Try CLU if provided and confident
        if clu_result and self._is_clu_confident(clu_result):
            intent, params = self._extract_clu_intent(clu_result)
            if intent:
                if VERBOSE_LOGGING:
                    print(f"[CommandProcessor] CLU match: {intent}")
                
                command = self.executor.execute(intent, params)
                return self._result(
                    success=True,
                    intent=intent,
                    command=command,
                    message=f"Executing from CLU: {intent}",
                    source="clu"
                )
        
        # Step 3: Fall back to LLM
        if ENABLE_LLM_FALLBACK:
            return self._try_llm_interpretation(utterance)
        
        # No match anywhere
        return self._result(
            success=False,
            message=f"I don't understand '{utterance}'. Try rephrasing or say something like 'move right 5 centimeters'."
        )
    
    def _try_llm_interpretation(self, utterance: str) -> Dict[str, Any]:
        """Use LLM to interpret an unknown utterance."""
        if VERBOSE_LOGGING:
            print("[CommandProcessor] Falling back to LLM interpretation...")
        
        state = self.executor.get_state()
        
        llm_result = self.llm.interpret(
            utterance=utterance,
            current_position=state["current_position"],
            previous_position=state["previous_position"],
            gripper_state=state["gripper_state"]
        )
        
        if not llm_result.get("understood"):
            explanation = llm_result.get("explanation", "Could not understand the command")
            return self._result(
                success=False,
                message=f"I couldn't understand that. {explanation}"
            )
        
        intent = llm_result.get("intent")
        parameters = llm_result.get("parameters", {})
        confidence = llm_result.get("confidence", 0)
        phrase_to_save = llm_result.get("phrase_to_save")
        needs_confirm = llm_result.get("needs_confirmation", False)
        
        if needs_confirm and not SILENT_LEARNING:
            # Low confidence - ask for confirmation
            self.pending_confirmation = {
                "original_utterance": utterance,
                "suggested_intent": intent,
                "suggested_parameters": parameters,
                "phrase_to_save": phrase_to_save,
                "confidence": confidence,
                "from_llm": True
            }
            
            intent_info = self.phrase_bank.get_intent_info(intent)
            intent_desc = intent_info.get("description", intent) if intent_info else intent
            
            return self._result(
                success=False,
                needs_confirmation=True,
                confirmation_prompt=f"I think you want to '{intent_desc}'. Is that right?",
                message=f"LLM interpretation ({confidence:.0%}), asking for confirmation"
            )
        
        # Confident enough - execute and learn
        command = self.executor.execute(intent, parameters)
        
        # Learn the phrase if provided
        learned = False
        if phrase_to_save and intent:
            learned = self.phrase_bank.add_phrase(
                phrase=phrase_to_save,
                intent=intent,
                parameters=parameters,
                source="llm_learned"
            )
        
        return self._result(
            success=True,
            intent=intent,
            command=command,
            message=f"Executing: {intent}" + (" (learned)" if learned else ""),
            learned=learned,
            source="llm"
        )
    
    def _handle_confirmation(self, response: str) -> Dict[str, Any]:
        """Handle a yes/no confirmation response."""
        response_lower = response.lower().strip()
        pending = self.pending_confirmation
        self.pending_confirmation = None  # Clear pending state
        
        is_yes = response_lower in ["yes", "yeah", "yep", "correct", "right", "sure", "ok", "okay", "affirmative"]
        is_no = response_lower in ["no", "nope", "wrong", "incorrect", "cancel", "nevermind"]
        
        if is_yes:
            intent = pending["suggested_intent"]
            parameters = pending["suggested_parameters"]
            
            command = self.executor.execute(intent, parameters)
            
            # Learn the phrase
            learned = False
            phrase_to_save = pending.get("phrase_to_save") or pending.get("original_utterance")
            if phrase_to_save:
                learned = self.phrase_bank.add_phrase(
                    phrase=phrase_to_save,
                    intent=intent,
                    parameters=parameters,
                    source="confirmed_learned"
                )
            
            return self._result(
                success=True,
                intent=intent,
                command=command,
                message=f"Confirmed and executing: {intent}" + (" (learned)" if learned else ""),
                learned=learned
            )
        
        elif is_no:
            return self._result(
                success=False,
                message="Okay, cancelled. Please try rephrasing your command."
            )
        
        else:
            # Didn't understand confirmation response - restore pending state
            self.pending_confirmation = pending
            return self._result(
                success=False,
                needs_confirmation=True,
                confirmation_prompt="Please say 'yes' or 'no'.",
                message="Didn't understand confirmation response"
            )
    
    def _is_clu_confident(self, clu_result: dict) -> bool:
        """Check if CLU result is confident enough to use."""
        try:
            prediction = clu_result.get("result", {}).get("prediction", {})
            top_intent = prediction.get("topIntent")
            intents = prediction.get("intents", [])
            
            for intent in intents:
                if intent.get("category") == top_intent:
                    confidence = intent.get("confidenceScore", 0)
                    return confidence >= CLU_CONFIDENCE_THRESHOLD
            
            return False
        except Exception:
            return False
    
    def _extract_clu_intent(self, clu_result: dict) -> Tuple[Optional[str], dict]:
        """Extract intent and parameters from CLU result."""
        try:
            prediction = clu_result.get("result", {}).get("prediction", {})
            intent = prediction.get("topIntent")
            entities = prediction.get("entities", [])
            
            # Map CLU intents to our intents (adjust based on your CLU model)
            intent_map = {
                "MoveDirection": "move_relative",
                "MoveToLocation": "move_to_named",
                "GoBack": "move_to_previous",
                "Grab": "gripper_close",
                "Release": "gripper_open",
                "Stop": "emergency_stop",
            }
            
            mapped_intent = intent_map.get(intent, intent)
            
            # Extract parameters from entities
            params = {}
            for entity in entities:
                category = entity.get("category", "")
                text = entity.get("text", "")
                
                if category == "Direction":
                    params["direction"] = text.lower()
                elif category == "Distance":
                    try:
                        params["distance"] = float(text)
                    except ValueError:
                        pass
                elif category == "Location":
                    params["location_name"] = text.lower()
            
            return mapped_intent, params
            
        except Exception as e:
            print(f"[CommandProcessor] Error extracting CLU intent: {e}")
            return None, {}
    
    def _result(self, success: bool, intent: str = None, command: dict = None,
                message: str = "", learned: bool = False, needs_confirmation: bool = False,
                confirmation_prompt: str = None, source: str = None) -> Dict[str, Any]:
        """Build a result dict."""
        return {
            "success": success,
            "intent": intent,
            "command": command,
            "message": message,
            "learned": learned,
            "needs_confirmation": needs_confirmation,
            "confirmation_prompt": confirmation_prompt,
            "source": source
        }
    
    def get_state(self) -> dict:
        """Get current system state."""
        return self.executor.get_state()


# Singleton instance
_processor_instance = None

def get_processor() -> CommandProcessor:
    """Get the singleton CommandProcessor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = CommandProcessor()
    return _processor_instance