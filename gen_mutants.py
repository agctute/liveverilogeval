#!/usr/bin/env python3
"""
Generate LLM-based mutants for designs and create Leetcode-style questions.
This script:
1. Generates 2 unique LLM-based mutants for every design in ./data/designs.jsonl
2. Analyzes differences between original and mutants using LLM
3. Creates Leetcode-style questions that target the mutants
4. Saves all outputs to organized files
"""

import json
import asyncio
import yaml
from pathlib import Path
from typing import List, Dict, Tuple
from utils.mutate import mutate
from utils.LLM_call import LLMClient

class MutantGenerator:
    def __init__(self):
        """Initialize the mutant generator with LLM client."""
        # Load configuration
        config_path = Path("config.yaml")
        if not config_path.exists():
            raise FileNotFoundError("config.yaml not found. Please ensure it exists with your API key.")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Initialize LLM client
        self.client = LLMClient((config.get("calls_per_min", 200), 60), config["api_key"])
        
        # Create mutants directory
        self.mutants_dir = Path("mutants")
        self.mutants_dir.mkdir(exist_ok=True)
    
    async def analyze_mutant_differences(self, original: str, mutant: str) -> str:
        """
        Use LLM to analyze the differences between original and mutant designs.
        
        Args:
            original: Original Verilog code
            mutant: Mutated Verilog code
            
        Returns:
            str: LLM analysis of the differences
        """
        prompt = f"""You are a Verilog bug analysis expert. Compare the original and mutated Verilog designs and provide a comprehensive analysis.

Original Design:
```verilog
{original}
```

Mutated Design:
```verilog
{mutant}
```

Please provide a detailed analysis including:

1. **Changes Made**: List all the specific changes between the original and mutated designs, including:
   - Line-by-line differences
   - Modified operators, conditions, or logic
   - Changed values, constants, or assignments
   - Any structural changes

2. **Bug Analysis**: Describe the bug that was introduced:
   - What type of bug is it? (e.g., timing issue, logic error, boundary condition, etc.)
   - Under what conditions will this bug manifest?
   - What is the expected behavior vs. the buggy behavior?

3. **Impact Assessment**: 
   - Which outputs will be affected?
   - Are there any specific input patterns that will trigger the bug?

Provide your analysis in a clear, structured format that a hardware verification engineer would find useful.

Analysis:"""

        try:
            messages = [{"role": "system", "content": prompt}]
            response, metadata = await self.client.call_deepseek(messages, temperature=0.3)
            return response
        except Exception as e:
            return f"Error analyzing mutation changes: {e}"
    
    async def generate_question(self, original: str, mutant: str, analysis: str) -> str:
        """
        Generate a Leetcode-style question that describes the mutated design.
        
        Args:
            original: Original Verilog code
            mutant: Mutated Verilog code
            analysis: LLM analysis of the differences
            
        Returns:
            str: Leetcode-style question
        """
        prompt = f"""You are an expert at creating Leetcode-style programming questions. Create a question that describes the new mutant design.
Original Design:
```verilog
{original}
```

Mutated Design:
```verilog
{mutant}
```

Mutant Analysis:
{analysis}

Create a Leetcode-style question with the following requirements:

1. **Question Format**: Follow standard Leetcode question format with:
   - Clear problem description
   - Input/Output specifications

2. **Target the Bug**: The question should be designed so that:
   - The correct solution should implement the MUTATED design behavior
   - The original solution (mutant) would fail on specific test cases

3. **Question Structure**:
   - Problem statement that describes what the module should do
   - Input format and constraints
   - Expected output format

4. **Focus on the Mutant**: 
   - The question should be crafted to request the new mutant design.
   - The question should be solvable by implementing the mutated design correctly

5. **Clear and Concise**: 
   - Use clear, professional language
   - Make the problem statement easy to understand
   - Provide sufficient detail without being overly verbose

Write the complete Leetcode-style question:"""

        try:
            messages = [{"role": "system", "content": prompt}]
            response, metadata = await self.client.call_deepseek(messages, temperature=0.4)
            return response
        except Exception as e:
            return f"Error generating Leetcode question: {e}"
    
    async def process_design(self, design_idx: int, design_content: str) -> List[Dict]:
        """
        Process a single design to generate mutants and analysis.
        
        Args:
            design_idx: Index of the design (for file naming)
            design_content: Verilog code of the design
            
        Returns:
            List of dictionaries containing mutant info
        """
        print(f"Processing design {design_idx + 1}...")
        
        try:
            # Generate 2 LLM-based mutants
            mutants = await mutate(design_content, 2, 3, llm_based=True)
            
            if not mutants:
                print(f"  No mutants generated for design {design_idx + 1}")
                return []
            
            results = []
            
            for mutant_idx, mutant in enumerate(mutants):
                print(f"  Analyzing mutant {mutant_idx + 1}...")
                
                # Analyze differences
                analysis = await self.analyze_mutant_differences(design_content, mutant['content'])
                
                # Generate Leetcode question
                question = await self.generate_question(design_content, mutant['content'], analysis)
                
                # Save files
                base_filename = f"dut_{design_idx + 1}_{mutant_idx + 1}"
                
                # Save mutant design
                mutant_file = self.mutants_dir / f"{base_filename}.v"
                with open(mutant_file, 'w') as f:
                    f.write(mutant['content'])
                
                # Save analysis
                analysis_file = self.mutants_dir / f"{base_filename}_desc.txt"
                with open(analysis_file, 'w') as f:
                    f.write(analysis)
                
                # Save question
                question_file = self.mutants_dir / f"{base_filename}_q.txt"
                with open(question_file, 'w') as f:
                    f.write(question)
                
                results.append({
                    'design_idx': design_idx + 1,
                    'mutant_idx': mutant_idx + 1,
                    'mutant_hash': mutant['hash'],
                    'mutant_file': str(mutant_file),
                    'analysis_file': str(analysis_file),
                    'question_file': str(question_file),
                    'analysis': analysis,
                    'question': question
                })
                
                print(f"    Saved: {base_filename}.v, {base_filename}_desc.txt, {base_filename}_q.txt")
            
            return results
            
        except Exception as e:
            print(f"  Error processing design {design_idx + 1}: {e}")
            return []
    
    async def generate_all_mutants(self):
        """Generate mutants for all designs in the JSONL file."""
        # Load designs from JSONL file
        designs_file = Path("./data/designs.jsonl")
        if not designs_file.exists():
            raise FileNotFoundError("Designs file not found: ./data/designs.jsonl")
        
        with open(designs_file, 'r') as f:
            designs = [json.loads(line) for line in f]
        
        print(f"Found {len(designs)} designs to process")
        print(f"Will generate 2 mutants per design = {len(designs) * 2} total mutants")
        print(f"Output directory: {self.mutants_dir.absolute()}")
        print("-" * 80)
        
        # Process all designs in parallel
        print("Starting parallel processing of all designs...")
        processing_tasks = []
        for design_idx, design_data in enumerate(designs):
            task = self.process_design(design_idx, design_data['content'])
            processing_tasks.append(task)
        
        # Wait for all designs to be processed
        results = await asyncio.gather(*processing_tasks, return_exceptions=True)
        
        # Count successful and failed processing
        successful_processing = sum(1 for r in results if not isinstance(r, Exception))
        failed_processing = len(results) - successful_processing
        print(f"Design processing completed: {successful_processing} successful, {failed_processing} failed")
        
        # Collect all results
        all_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error processing design {i+1}: {result}")
            else:
                all_results.extend(result)
        
        # Generate summary
        await self.generate_summary(all_results, len(designs))
        
        return all_results
    
    async def generate_summary(self, results: List[Dict], total_designs: int):
        """Generate a summary of all generated mutants."""
        summary_file = self.mutants_dir / "summary.txt"
        
        summary_content = f"""MUTANT GENERATION SUMMARY
============================

Total designs processed: {total_designs}
Total mutants generated: {len(results)}
Success rate: {len(results) / (total_designs * 2) * 100:.1f}%

Generated Files:
"""
        
        for result in results:
            summary_content += f"""
Design {result['design_idx']}, Mutant {result['mutant_idx']}:
- Mutant design: {result['mutant_file']}
- Analysis: {result['analysis_file']}
- Question: {result['question_file']}
- Hash: {result['mutant_hash'][:16]}...
"""
        
        with open(summary_file, 'w') as f:
            f.write(summary_content)
        
        print(f"\nSummary saved to: {summary_file}")
        print(f"Generated {len(results)} mutants from {total_designs} designs")

async def main():
    """Main function to run the mutant generation process."""
    try:
        generator = MutantGenerator()
        results = await generator.generate_all_mutants()
        
        print("\n" + "=" * 80)
        print("MUTANT GENERATION COMPLETED")
        print("=" * 80)
        print(f"Total mutants generated: {len(results)}")
        print(f"Check the 'mutants' directory for all generated files")
        
    except Exception as e:
        print(f"Error in main execution: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 