from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from entry_types import DesignEntry
from utils.LLM_call import LLMClient, extract_between_markers
from utils.equivalence_check import check_equivalence
from utils.mutate import standardize


class DebugLogger:
    """Centralized debug logging system for all generators."""
    
    def __init__(self, enabled: bool = False, log_file: str = "generator_debug.log"):
        self.enabled = enabled
        self.log_file = log_file
        self._log_file_path = Path(log_file)
        
        # Ensure log directory exists
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp and level."""
        if not self.enabled:
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(log_entry + '\n')
        except Exception as e:
            print(f"Error writing to log file: {e}")
    
    def log_llm_call(self, messages: List[Dict[str, str]], response: str, metadata: Dict):
        """Log LLM API calls with request and response."""
        if not self.enabled:
            return
            
        self.log("=" * 50)
        self.log("LLM API CALL")
        self.log(f"Messages: {messages}")
        self.log(f"Response: {response}")
        self.log(f"Metadata: {metadata}")
        self.log("=" * 50)


class QuestionGenerator:
    """
    Generates natural-language questions for a given design.

    Holds a `DesignEntry` and an `LLMClient` for reuse. Also provides a
    convenience classmethod to generate a question without instantiating.
    """

    def __init__(self, design_entry: DesignEntry, client: LLMClient, debug_logger: Optional[DebugLogger] = None) -> None:
        self.design_entry = design_entry
        self.client = client
        self.debug_logger = debug_logger or DebugLogger(enabled=False)

    @staticmethod
    def _build_prompt(verilog_module: str) -> List[Dict[str, str]]:
        """
        Construct a prompt that asks for a LeetCode-style problem statement whose
        unique correct answer is the provided Verilog module. The model should
        NOT output any code, only the problem text between markers so callers
        can reliably extract it.
        """
        system_msg = (
            "You are an expert hardware interview question writer. You craft clear,\n"
            "concise, LeetCode-style problem statements about designing RTL modules.\n"
            "Only output the problem statement; do not include any solution code."
        )

        user_msg = (
            "Create a LeetCode-style question whose unique correct answer is the\n"
            "following Verilog module. The question should:\n"
            "- Clearly describe the required behavior, I/O interface, and any timing/edge conditions.\n"
            "- Avoid revealing implementation details or providing code.\n"
            "- Be self-contained and unambiguous.\n"
            "- Fit within 150-300 words.\n\n"
            "Return ONLY the question text between the exact markers below.\n"
            "QUESTION BEGIN\n"
            "<write the problem statement here>\n"
            "QUESTION END\n\n"
            "Target Verilog module (ground-truth answer):\n"
            "----- BEGIN VERILOG -----\n"
            f"{verilog_module}\n"
            "----- END VERILOG -----\n"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    async def generate(self, temperature: float = 0.6) -> str:
        """Instance method: generate a question for the held design."""
        msgs = self._build_prompt(self.design_entry.content)
        response, metadata = await self.client.call_deepseek(msgs, temperature=temperature)
        
        # Log the LLM call if debug is enabled
        self.debug_logger.log_llm_call(msgs, response, metadata)
        
        question = extract_between_markers(response, "QUESTION BEGIN", "QUESTION END")
        self.debug_logger.log(f"Generated question: {question[:100]}...")
        return question

    @classmethod
    async def orig_gen(
        cls,
        design_entry: DesignEntry,
        client: LLMClient,
        temperature: float = 0.6,
        debug_logger: Optional[DebugLogger] = None
    ) -> str:
        """
        Class method: prompts DeepSeek to generate a LeetCode-style question
        whose answer is the Verilog module found in `design_entry`.

        Returns the extracted question text.
        """
        msgs = cls._build_prompt(design_entry.content)
        response, metadata = await client.call_deepseek(msgs, temperature=temperature)
        
        # Log the LLM call if debug is enabled
        if debug_logger:
            debug_logger.log_llm_call(msgs, response, metadata)
        
        question = extract_between_markers(response, "QUESTION BEGIN", "QUESTION END")
        return question


class AnswerGenerator:
    """
    Generates Verilog answers (modules) for a given natural-language question.

    Usage:
        ag = AnswerGenerator(question_text, client)
        answers: List[str] = await ag.generate_answers(n)
    """

    def __init__(self, question: str, client: LLMClient, prompt_path: str = "./templates/rtl_gen.txt", debug_logger: Optional[DebugLogger] = None) -> None:
        self.question = question
        self.client = client
        self.prompt = self._load_prompt(prompt_path)
        self.debug_logger = debug_logger or DebugLogger(enabled=False)

    @staticmethod
    def _load_prompt(prompt_path: str) -> str:
        path = Path(prompt_path)
        return path.read_text(encoding="utf-8")

    def _build_messages(self) -> List[Dict[str, str]]:
        # Mirror the pattern used elsewhere: pass the generation prompt, then append the question
        full_prompt = f"{self.prompt}{self.question}"
        return [{"role": "system", "content": full_prompt}]

    async def generate_answers(self, n: int, temperature: float = 0.6) -> List[str]:
        """
        Generate n candidate Verilog answers for the stored question.
        Returns a list of n strings (best-effort; may be fewer if some calls fail).
        """
        msgs = self._build_messages()
        tasks = [self.client.call_deepseek(msgs, temperature=temperature) for _ in range(n)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        answers: List[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.debug_logger.log(f"Error generating answer {i+1}: {result}", "ERROR")
                continue
                
            response, metadata = result
            self.debug_logger.log(f"Generated answer {i+1}: {response[:100]}...")
            
            # Extract Verilog code from response
            code = extract_between_markers(response, "```verilog", "```")
            if not code.strip():
                # Fallback: try without verilog marker
                code = extract_between_markers(response, "```", "```")
            
            if code.strip():
                # Standardize the code
                try:
                    standardized_code = standardize(code)
                    answers.append(standardized_code)
                    self.debug_logger.log(f"Standardized answer {i+1}: {standardized_code[:100]}...")
                except Exception as e:
                    self.debug_logger.log(f"Error standardizing answer {i+1}: {e}", "ERROR")
                    # Use original code if standardization fails
                    answers.append(code)
            else:
                self.debug_logger.log(f"No code found in answer {i+1}, using raw response", "WARNING")
                answers.append(response)
        
        self.debug_logger.log(f"Generated {len(answers)} valid answers out of {n} attempts")
        return answers


class ValidQuestionGenerator:
    """
    Validates that a generated question is sound by checking whether at least
    one of n generated answers is formally equivalent to the original design.

    - Takes a `QuestionGenerator`, an `AnswerGenerator`, and an integer n.
    - Exposes a `valid_question` flag (default False).
    - `validate()` generates n answers and sets `valid_question` True if any
      answer verifies against the original design.
    """

    def __init__(self, qg: QuestionGenerator, ag: AnswerGenerator, n: int, max_concurrent_yosys: int = 4, debug_logger: Optional[DebugLogger] = None) -> None:
        self.qg = qg
        self.ag = ag
        self.n = n
        self.valid_question: bool = False
        # Limit concurrent Yosys processes to prevent resource exhaustion
        self.semaphore = asyncio.Semaphore(max_concurrent_yosys)
        self.debug_logger = debug_logger or DebugLogger(enabled=False)

    async def validate(self) -> bool:
        """Validate the question by generating answers and checking equivalence."""
        self.debug_logger.log("Starting question validation...")
        
        # Ensure yosys batch dir exists
        batch_dir = Path("./yosys_files/")
        batch_dir.mkdir(parents=True, exist_ok=True)

        # Generate n candidate answers
        self.debug_logger.log(f"Generating {self.n} candidate answers...")
        answers: List[str] = await self.ag.generate_answers(self.n)
        answers = [a for a in answers if isinstance(a, str) and a.strip()]
        
        if not answers:
            self.debug_logger.log("No valid answers generated", "WARNING")
            self.valid_question = False
            return self.valid_question

        self.debug_logger.log(f"Generated {len(answers)} valid answers, checking equivalence...")

        # Verify all answers in parallel against the ground truth design
        ground_truth = self.qg.design_entry.content
        
        async def check_with_semaphore(ans):
            async with self.semaphore:
                return await check_equivalence(str(batch_dir), ans, ground_truth)
        
        tasks = [
            check_with_semaphore(ans) for ans in answers
        ]
        
        self.debug_logger.log(f"Running {len(tasks)} equivalence checks in parallel...")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        valid_count = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                self.debug_logger.log(f"Equivalence check {i+1} failed: {res}", "ERROR")
            elif isinstance(res, bool) and res:
                valid_count += 1
                self.debug_logger.log(f"Answer {i+1} is equivalent to ground truth")
                self.valid_question = True
                break

        if self.valid_question:
            self.debug_logger.log(f"Question validation successful! {valid_count} equivalent answer(s) found.")
        else:
            self.debug_logger.log(f"Question validation failed. No equivalent answers found.")
        
        return self.valid_question


# Convenience function to create all generators with shared debug logging
def create_generators(
    design_entry: DesignEntry, 
    client: LLMClient, 
    n_answers: int = 10, 
    max_concurrent_yosys: int = 4,
    debug_enabled: bool = False,
    debug_log_file: str = "generator_debug.log"
) -> Tuple[QuestionGenerator, AnswerGenerator, ValidQuestionGenerator]:
    """
    Create all three generators with shared debug logging.
    
    Args:
        design_entry: The design entry to generate questions for
        client: LLM client for API calls
        n_answers: Number of answers to generate for validation
        max_concurrent_yosys: Maximum concurrent Yosys processes
        debug_enabled: Whether to enable debug logging
        debug_log_file: Path to debug log file
        
    Returns:
        Tuple of (QuestionGenerator, AnswerGenerator, ValidQuestionGenerator)
    """
    debug_logger = DebugLogger(enabled=debug_enabled, log_file=debug_log_file)
    
    qg = QuestionGenerator(design_entry, client, debug_logger)
    ag = AnswerGenerator("", client, debug_logger=debug_logger)  # Question will be set later
    vqg = ValidQuestionGenerator(qg, ag, n_answers, max_concurrent_yosys, debug_logger)
    
    return qg, ag, vqg

# Backward compatibility aliases
__all__ = [
    'QuestionGenerator',
    'AnswerGenerator', 
    'ValidQuestionGenerator',
    'DebugLogger',
    'create_generators'
]
