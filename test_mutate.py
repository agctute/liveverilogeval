#!/usr/bin/env python3
"""
Test script for the mutate function with both AST-based and LLM-based mutation support.
Uses LLMs to analyze and describe changes between original and mutant designs.
"""

from utils.mutate import mutate
import re
import asyncio
import yaml
from typing import List, Dict, Tuple
from utils.LLM_call import LLMClient

async def analyze_design_functionality(verilog_code: str, client: LLMClient) -> str:
    """
    Use LLM to analyze and describe the functionality of a Verilog design.
    
    Args:
        verilog_code: Verilog code as string
        client: LLM client for API calls
        
    Returns:
        str: Description of the design functionality
    """
    prompt = f"""You are a Verilog design expert. Analyze the following Verilog module and provide a comprehensive description of its functionality.

Verilog Code:
```verilog
{verilog_code}
```

Please provide a detailed analysis including:
1. Module name and purpose
2. Input and output ports with their bit widths and purposes
3. Detailed description of the functionality and behavior
4. Clock and reset behavior
5. Any state machines, counters, or complex logic
6. Expected behavior under different input conditions

Focus on explaining what the module does in clear, technical terms that a hardware engineer would understand.

Provide your analysis:"""

    try:
        messages = [{"role": "system", "content": prompt}]
        response, metadata = await client.call_deepseek(messages, temperature=0.3)
        return response
    except Exception as e:
        return f"Error analyzing design functionality: {e}"



async def analyze_mutation_changes(original: str, mutant: str, client: LLMClient) -> Dict[str, str]:
    """
    Use LLM to analyze the changes between original and mutant designs.
    
    Args:
        original: Original Verilog code
        mutant: Mutated Verilog code
        client: LLM client for API calls
        
    Returns:
        Dict containing analysis of changes
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
   - How severe is this bug?

3. **Impact Assessment**: 
   - Which outputs will be affected?
   - Will the bug cause the design to fail completely or just produce incorrect results?
   - Are there any specific input patterns that will trigger the bug?

4. **Technical Details**:
   - Categorize the type of mutation (e.g., operator change, condition modification, timing change, etc.)
   - Explain the technical reason why this change introduces a bug

Provide your analysis in a clear, structured format that a hardware verification engineer would find useful.

Analysis:"""

    try:
        messages = [{"role": "system", "content": prompt}]
        response, metadata = await client.call_deepseek(messages, temperature=0.3)
        
        return {
            'analysis': response,
            'original': original,
            'mutant': mutant
        }
    except Exception as e:
        return {
            'analysis': f"Error analyzing mutation changes: {e}",
            'original': original,
            'mutant': mutant
        }



async def test_mutations_with_analysis():
    """Test both AST-based and LLM-based mutations with detailed analysis."""
    
    # Load configuration and initialize LLM client
    try:
        with open("config.yaml", 'r') as f:
            config = yaml.safe_load(f)
        client = LLMClient((config.get("calls_per_min", 200), 60), config["api_key"])
    except Exception as e:
        print(f"Error loading config: {e}")
        return
    
    # Test design
    test_design = """
module test_module(
    input clk,
    input rst,
    input [7:0] a,
    input [7:0] b,
    output reg [7:0] result
);

always @(posedge clk or posedge rst) begin
    if (rst) begin
        result <= 8'b0;
    end else begin
        if (a > b) begin
            result <= a + b;
        end else begin
            result <= a - b;
        end
    end
end

endmodule
"""
    
    print("=" * 80)
    print("COMPREHENSIVE MUTATION TESTING WITH LLM ANALYSIS")
    print("=" * 80)
    
    print("\nOriginal Design:")
    print(test_design)
    
    print("\n" + "=" * 80)
    print("ORIGINAL DESIGN ANALYSIS")
    print("=" * 80)
    original_analysis = await analyze_design_functionality(test_design, client)
    print(original_analysis)
    
    # Test AST-based mutation
    print("\n" + "=" * 80)
    print("AST-BASED MUTATION TESTING")
    print("=" * 80)
    
    try:
        ast_mutants = await mutate(test_design, 2, 3, llm_based=False)
        
        print(f"\nGenerated {len(ast_mutants)} AST-based mutants:")
        
        for i, mutant in enumerate(ast_mutants, 1):
            print(f"\n--- AST MUTANT {i} ---")
            print(f"Hash: {mutant['hash'][:16]}...")
            print("\nMutated Code:")
            print(mutant['content'])
            
            # Analyze changes using LLM
            print("\n" + "=" * 50)
            print("LLM ANALYSIS OF CHANGES")
            print("=" * 50)
            analysis = await analyze_mutation_changes(test_design, mutant['content'], client)
            print(analysis['analysis'])
            print("-" * 80)
            
    except Exception as e:
        print(f"Error in AST-based mutation: {e}")
    
    # Test LLM-based mutation
    print("\n" + "=" * 80)
    print("LLM-BASED MUTATION TESTING")
    print("=" * 80)
    
    try:
        llm_mutants = await mutate(test_design, 2, 3, llm_based=True)
        
        print(f"\nGenerated {len(llm_mutants)} LLM-based mutants:")
        
        for i, mutant in enumerate(llm_mutants, 1):
            print(f"\n--- LLM MUTANT {i} ---")
            print(f"Hash: {mutant['hash'][:16]}...")
            print("\nMutated Code:")
            print(mutant['content'])
            
            # Analyze changes using LLM
            print("\n" + "=" * 50)
            print("LLM ANALYSIS OF CHANGES")
            print("=" * 50)
            analysis = await analyze_mutation_changes(test_design, mutant['content'], client)
            print(analysis['analysis'])
            print("-" * 80)
            
    except Exception as e:
        print(f"Error in LLM-based mutation: {e}")
        print("Make sure config.yaml exists with a valid API key.")

async def test_complex_design_mutation():
    """Test mutations on a more complex design."""
    
    # Load configuration and initialize LLM client
    try:
        with open("config.yaml", 'r') as f:
            config = yaml.safe_load(f)
        client = LLMClient((config.get("calls_per_min", 200), 60), config["api_key"])
    except Exception as e:
        print(f"Error loading config: {e}")
        return
    
    complex_design = """
module counter_with_overflow(
    input clk,
    input rst,
    input enable,
    input [3:0] max_count,
    output reg [3:0] count,
    output reg overflow
);

always @(posedge clk or posedge rst) begin
    if (rst) begin
        count <= 4'b0;
        overflow <= 1'b0;
    end else if (enable) begin
        if (count == max_count) begin
            count <= 4'b0;
            overflow <= 1'b1;
        end else begin
            count <= count + 1'b1;
            overflow <= 1'b0;
        end
    end
end

endmodule
"""
    
    print("\n" + "=" * 80)
    print("COMPLEX DESIGN MUTATION TESTING")
    print("=" * 80)
    
    print("\nComplex Design:")
    print(complex_design)
    
    print("\nOriginal Design Analysis:")
    original_analysis = await analyze_design_functionality(complex_design, client)
    print(original_analysis)
    
    # Test both mutation types on complex design
    for mutation_type in ["AST-based", "LLM-based"]:
        print(f"\n--- {mutation_type.upper()} MUTATION ON COMPLEX DESIGN ---")
        
        try:
            llm_based = (mutation_type == "LLM-based")
            mutants = await mutate(complex_design, 1, 3, llm_based=llm_based)
            
            print(f"Generated {len(mutants)} {mutation_type} mutants:")
            
            for i, mutant in enumerate(mutants, 1):
                print(f"\n--- {mutation_type.upper()} MUTANT {i} ---")
                print(f"Hash: {mutant['hash'][:16]}...")
                print("\nMutated Code:")
                print(mutant['content'])
                
                # Analyze changes using LLM
                print("\n" + "=" * 50)
                print("LLM ANALYSIS OF CHANGES")
                print("=" * 50)
                analysis = await analyze_mutation_changes(complex_design, mutant['content'], client)
                print(analysis['analysis'])
                print("-" * 80)
                
        except Exception as e:
            print(f"Error in {mutation_type} mutation: {e}")

async def main():
    """Main function to run all tests."""
    await test_mutations_with_analysis()
    await test_complex_design_mutation()

if __name__ == "__main__":
    asyncio.run(main())
