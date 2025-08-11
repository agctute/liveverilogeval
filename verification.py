#!/usr/bin/env python3
"""
Verification script for generated questions.
This script:
1. Loads all generated .v and _q.txt files from the mutants directory
2. Uses questions to generate candidate solutions
3. Verifies if candidate solutions match the original mutant designs
4. Runs verification in parallel for all question/design pairs
5. Provides summary and saves results
"""

import json
import asyncio
import yaml
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from utils.LLM_call import LLMClient
from utils.hash_utils import hash_string
from utils.equivalence_check import check_equivalence
from utils.mutate import standardize

class QuestionVerifier:
    def __init__(self):
        """Initialize the question verifier with LLM client."""
        # Load configuration
        config_path = Path("config.yaml")
        if not config_path.exists():
            raise FileNotFoundError("config.yaml not found. Please ensure it exists with your API key.")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Initialize LLM client
        self.client = LLMClient((config.get("calls_per_min", 200), 60), config["api_key"])
        
        # Set up directories
        self.mutants_dir = Path("mutants")
        self.yosys_dir = Path("./yosys_files/")
        self.yosys_dir.mkdir(exist_ok=True)
        
        # Load RTL generation prompt
        self.rtl_gen_prompt = Path("./templates/rtl_gen.txt")
        if not self.rtl_gen_prompt.exists():
            raise FileNotFoundError("RTL generation prompt not found: ./templates/rtl_gen.txt")
        
        with open(self.rtl_gen_prompt, 'r') as f:
            self.rtl_prompt = f.read()
    
    def extract_code_from_response(self, response: str) -> str:
        """
        Extract Verilog code from LLM response.
        
        Args:
            response: LLM response containing code
            
        Returns:
            str: Extracted Verilog code
        """
        # Look for code blocks marked with ```verilog or ```
        lines = response.split('\n')
        code_start = -1
        code_end = -1
        
        for i, line in enumerate(lines):
            if line.strip().startswith('```') and (code_start == -1):
                code_start = i + 1
            elif line.strip().startswith('```') and (code_start != -1):
                code_end = i
                break
        
        if code_start != -1 and code_end != -1:
            verilog_code = '\n'.join(lines[code_start:code_end])
        else:
            # If no code blocks found, try to extract the entire response
            verilog_code = response.strip()
        
        return verilog_code
    
    async def generate_candidate_solutions(self, question: str, n: int = 5) -> List[Dict[str, str]]:
        """
        Generate candidate solutions using the question.
        
        Args:
            question: The question to generate solutions for
            n: Number of candidate solutions to generate
            
        Returns:
            List of dictionaries containing candidate solutions
        """
        prompt = self.rtl_prompt + question
        
        try:
            # Generate n candidate solutions in parallel
            messages = [{"role": "system", "content": prompt}]
            tasks = [self.client.call_deepseek(messages, temperature=0.8) for _ in range(n)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            candidates = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"    Error generating candidate {i+1}: {result}")
                    continue
                
                response, metadata = result
                try:
                    generated_code = self.extract_code_from_response(response)
                    standardized_code = standardize(generated_code)
                    candidate_hash = hash_string(standardized_code)
                    
                    candidates.append({
                        'content': standardized_code,
                        'hash': candidate_hash,
                        'candidate_idx': i + 1
                    })
                except Exception as e:
                    print(f"    Error processing candidate {i+1}: {e}")
                    continue
            
            return candidates
            
        except Exception as e:
            print(f"Error generating candidate solutions: {e}")
            return []
    
    async def verify_question(self, question_file: Path, design_file: Path) -> Dict:
        """
        Verify a single question by generating candidate solutions and checking equivalence.
        
        Args:
            question_file: Path to the question file
            design_file: Path to the design file
            
        Returns:
            Dict containing verification results
        """
        try:
            # Load question and design
            with open(question_file, 'r') as f:
                question = f.read()
            
            with open(design_file, 'r') as f:
                original_design = f.read()
            
            # Extract design and mutant indices from filename
            filename = design_file.stem  # e.g., "dut_1_2"
            match = re.match(r'dut_(\d+)_(\d+)', filename)
            if match:
                design_idx = int(match.group(1))
                mutant_idx = int(match.group(2))
            else:
                design_idx = 0
                mutant_idx = 0
            
            print(f"Verifying Design {design_idx}, Mutant {mutant_idx}...")
            
            # Generate candidate solutions
            print(f"  Generating 5 candidate solutions...")
            candidates = await self.generate_candidate_solutions(question, n=5)
            
            if not candidates:
                return {
                    'design_idx': design_idx,
                    'mutant_idx': mutant_idx,
                    'question_file': str(question_file),
                    'design_file': str(design_file),
                    'passed': False,
                    'reason': 'No valid candidates generated',
                    'candidates_generated': 0,
                    'matching_candidates': 0
                }
            
            print(f"  Generated {len(candidates)} valid candidates")
            
            # Check equivalence for each candidate
            print(f"  Checking equivalence with original design...")
            equivalence_tasks = []
            for candidate in candidates:
                task = check_equivalence(str(self.yosys_dir), candidate['content'], original_design)
                equivalence_tasks.append((candidate, task))
            
            # Run all equivalence checks in parallel
            results = await asyncio.gather(*[task for _, task in equivalence_tasks], return_exceptions=True)
            
            # Process results
            matching_candidates = []
            for i, result in enumerate(results):
                candidate, _ = equivalence_tasks[i]
                if isinstance(result, Exception):
                    print(f"    Equivalence check failed for candidate {candidate['candidate_idx']}: {result}")
                elif result:  # Equivalent
                    matching_candidates.append(candidate)
                    print(f"    Candidate {candidate['candidate_idx']} matches original design!")
            
            # Determine if verification passed
            passed = len(matching_candidates) > 0
            reason = f"Found {len(matching_candidates)} matching candidates" if passed else "No matching candidates found"
            
            return {
                'design_idx': design_idx,
                'mutant_idx': mutant_idx,
                'question_file': str(question_file),
                'design_file': str(design_file),
                'passed': passed,
                'reason': reason,
                'candidates_generated': len(candidates),
                'matching_candidates': len(matching_candidates),
                'candidates': candidates,
                'matching_candidates_list': matching_candidates
            }
            
        except Exception as e:
            return {
                'design_idx': design_idx if 'design_idx' in locals() else 0,
                'mutant_idx': mutant_idx if 'mutant_idx' in locals() else 0,
                'question_file': str(question_file),
                'design_file': str(design_file),
                'passed': False,
                'reason': f'Error during verification: {e}',
                'candidates_generated': 0,
                'matching_candidates': 0
            }
    
    async def verify_all_questions(self):
        """Verify all generated questions in parallel."""
        # Find all question and design files
        question_files = list(self.mutants_dir.glob("*_q.txt"))
        design_files = list(self.mutants_dir.glob("dut_*.v"))
        
        print(f"Found {len(question_files)} question files and {len(design_files)} design files")
        
        # Create mapping from question files to design files
        verification_pairs = []
        for question_file in question_files:
            # Extract base filename (e.g., "dut_1_2" from "dut_1_2_q.txt")
            base_name = question_file.stem.replace('_q', '')
            design_file = self.mutants_dir / f"{base_name}.v"
            
            if design_file.exists():
                verification_pairs.append((question_file, design_file))
            else:
                print(f"Warning: No design file found for {question_file}")
        
        print(f"Found {len(verification_pairs)} question/design pairs to verify")
        print("-" * 80)
        
        # Verify all pairs in parallel
        print("Starting parallel verification of all questions...")
        verification_tasks = []
        for question_file, design_file in verification_pairs:
            task = self.verify_question(question_file, design_file)
            verification_tasks.append(task)
        
        # Wait for all verifications to complete
        results = await asyncio.gather(*verification_tasks, return_exceptions=True)
        
        # Process results
        successful_verifications = []
        failed_verifications = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error in verification task {i+1}: {result}")
                failed_verifications.append({
                    'error': str(result),
                    'task_idx': i + 1
                })
            else:
                if result['passed']:
                    successful_verifications.append(result)
                else:
                    failed_verifications.append(result)
        
        # Generate summary
        await self.generate_verification_summary(successful_verifications, failed_verifications)
        
        return successful_verifications, failed_verifications
    
    async def generate_verification_summary(self, successful: List[Dict], failed: List[Dict]):
        """Generate a summary of verification results."""
        summary_file = self.mutants_dir / "verification_summary.txt"
        passed_questions_file = self.mutants_dir / "passed_questions.txt"
        
        total_questions = len(successful) + len(failed)
        pass_rate = (len(successful) / total_questions * 100) if total_questions > 0 else 0
        
        # Generate summary content
        summary_content = f"""QUESTION VERIFICATION SUMMARY
===============================

Total questions verified: {total_questions}
Questions passed: {len(successful)}
Questions failed: {len(failed)}
Pass rate: {pass_rate:.1f}%

PASSED QUESTIONS:
"""
        
        for result in successful:
            summary_content += f"""
Design {result['design_idx']}, Mutant {result['mutant_idx']}:
- Question file: {result['question_file']}
- Design file: {result['design_file']}
- Candidates generated: {result['candidates_generated']}
- Matching candidates: {result['matching_candidates']}
- Reason: {result['reason']}
"""
        
        summary_content += f"""

FAILED QUESTIONS:
"""
        
        for result in failed:
            if 'error' in result:
                summary_content += f"""
Task {result['task_idx']}:
- Error: {result['error']}
"""
            else:
                summary_content += f"""
Design {result['design_idx']}, Mutant {result['mutant_idx']}:
- Question file: {result['question_file']}
- Design file: {result['design_file']}
- Candidates generated: {result['candidates_generated']}
- Matching candidates: {result['matching_candidates']}
- Reason: {result['reason']}
"""
        
        # Write summary
        with open(summary_file, 'w') as f:
            f.write(summary_content)
        
        # Write passed questions list
        with open(passed_questions_file, 'w') as f:
            f.write("PASSED QUESTIONS:\n")
            f.write("================\n\n")
            for result in successful:
                f.write(f"Design {result['design_idx']}, Mutant {result['mutant_idx']}:\n")
                f.write(f"Question: {result['question_file']}\n")
                f.write(f"Design: {result['design_file']}\n")
                f.write(f"Reason: {result['reason']}\n")
                f.write("-" * 50 + "\n")
        
        print(f"\nVerification Summary:")
        print(f"Total questions: {total_questions}")
        print(f"Passed: {len(successful)}")
        print(f"Failed: {len(failed)}")
        print(f"Pass rate: {pass_rate:.1f}%")
        print(f"Summary saved to: {summary_file}")
        print(f"Passed questions list saved to: {passed_questions_file}")

async def main():
    """Main function to run the verification process."""
    try:
        verifier = QuestionVerifier()
        successful, failed = await verifier.verify_all_questions()
        
        print("\n" + "=" * 80)
        print("VERIFICATION COMPLETED")
        print("=" * 80)
        print(f"Total questions verified: {len(successful) + len(failed)}")
        print(f"Questions passed: {len(successful)}")
        print(f"Questions failed: {len(failed)}")
        print(f"Pass rate: {(len(successful) / (len(successful) + len(failed)) * 100):.1f}%")
        print(f"Check the 'mutants' directory for detailed results")
        
    except Exception as e:
        print(f"Error in main execution: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 