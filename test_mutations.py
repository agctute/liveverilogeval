"""
Test script for the mutation pipeline.
Generates bug categories and mutants for sample RTL designs.
"""

import asyncio
import json
import yaml
from pathlib import Path
from typing import List, Dict, Any

from utils.generators import create_generators, DebugLogger
from entry_types import DesignEntry
from utils.LLM_call import LLMClient


async def test_mutation_pipeline():
    """Test the complete mutation pipeline on sample designs."""
    
    # Load configuration
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        api_key = config["api_key"]
    except FileNotFoundError:
        print("Error: config.yaml not found. Please create it with your API key.")
        return
    except KeyError:
        print("Error: config.yaml missing 'api_key' field.")
        return
    
    # Initialize LLM client
    client = LLMClient((60, 60), api_key)
    
    # Enable debug logging
    debug_enabled = True
    debug_log_file = "./logs/mutation_test_debug.log"
    
    # Sample designs to test (you can modify these or load from file)
    sample_designs = [
        {
            "name": "8-bit Adder",
            "content": """module adder_8bit(
    input [7:0] a,
    input [7:0] b,
    input cin,
    output [7:0] sum,
    output cout
);
    assign {cout, sum} = a + b + cin;
endmodule"""
        },
        {
            "name": "4-bit Counter",
            "content": """module counter_4bit(
    input clk,
    input reset,
    input enable,
    output reg [3:0] count
);
    always @(posedge clk or posedge reset) begin
        if (reset)
            count <= 4'b0000;
        else if (enable)
            count <= count + 1'b1;
    end
endmodule"""
        },
        {
            "name": "2-to-1 Multiplexer",
            "content": """module mux_2to1(
    input [3:0] a,
    input [3:0] b,
    input sel,
    output reg [3:0] out
);
    always @(*) begin
        if (sel)
            out = b;
        else
            out = a;
    end
endmodule"""
        }
    ]
    
    print(f"Testing mutation pipeline on {len(sample_designs)} sample designs...")
    print("=" * 80)
    
    all_results = []
    
    for i, design_data in enumerate(sample_designs):
        print(f"\nProcessing design {i+1}: {design_data['name']}")
        print("-" * 60)
        
        try:
            # Create design entry
            design_entry = DesignEntry(design_data["content"])
            
            # Create all generators
            qg, ag, vqg, mg, mutg = create_generators(
                design_entry=design_entry,
                client=client,
                n_answers=3,
                max_concurrent_yosys=2,
                debug_enabled=debug_enabled,
                debug_log_file=debug_log_file
            )
            
            # Step 1: Generate bug categories
            print("  Generating bug categories...")
            bug_categories = await mg.generate_bug_categories(temperature=0.7)
            print(f"  Generated {len(bug_categories)} bug categories")
            
            # Display bug categories
            for j, bug in enumerate(bug_categories):
                print(f"    {j+1}. {bug['bug_type']}: {bug['description']}")
            
            # Step 2: Generate mutants
            print("  Generating mutants...")
            mutants = await mutg.generate_mutants(bug_categories, temperature=0.8)
            print(f"  Generated {len(mutants)} mutants")
            
            # Display mutants
            for j, (mutant_code, bug_type) in enumerate(mutants):
                print(f"    {j+1}. Bug: {bug_type}")
                print(f"       Code length: {len(mutant_code)} characters")
                print(f"       Preview: {mutant_code[:100]}...")
            
            # Store results
            result = {
                "design_name": design_data["name"],
                "design_hash": design_entry.hash,
                "original_code": design_data["content"],
                "bug_categories": bug_categories,
                "mutants": [
                    {
                        "bug_type": bug_type,
                        "mutant_code": mutant_code,
                        "code_length": len(mutant_code)
                    }
                    for mutant_code, bug_type in mutants
                ],
                "timestamp": asyncio.get_event_loop().time()
            }
            
            all_results.append(result)
            print(f"  ✓ Successfully processed {design_data['name']}")
            
        except Exception as e:
            print(f"  ✗ Error processing {design_data['name']}: {e}")
            # Add error result
            all_results.append({
                "design_name": design_data["name"],
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time()
            })
            continue
    
    # Save results to JSONL file
    output_dir = Path("./mutants")
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / "mutants.jsonl"
    
    print(f"\nSaving results to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        for result in all_results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    
    print(f"✓ Results saved to {output_file}")
    
    # Print summary
    successful_designs = [r for r in all_results if "error" not in r]
    print(f"\nSummary:")
    print(f"  Total designs processed: {len(all_results)}")
    print(f"  Successful: {len(successful_designs)}")
    print(f"  Failed: {len(all_results) - len(successful_designs)}")
    
    if successful_designs:
        total_bugs = sum(len(d["bug_categories"]) for d in successful_designs)
        total_mutants = sum(len(d["mutants"]) for d in successful_designs)
        print(f"  Total bug categories generated: {total_bugs}")
        print(f"  Total mutants generated: {total_mutants}")
    
    return all_results


async def test_single_design(design_name: str, verilog_code: str):
    """Test mutation pipeline on a single design."""
    
    # Load configuration
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    client = LLMClient((60, 60), config["api_key"])
    debug_logger = DebugLogger(enabled=True, log_file="./logs/single_test_debug.log")
    
    print(f"Testing single design: {design_name}")
    print("=" * 60)
    
    # Create design entry
    design_entry = DesignEntry(verilog_code)
    
    # Create generators
    qg, ag, vqg, mg, mutg = create_generators(
        design_entry=design_entry,
        client=client,
        n_answers=2,
        max_concurrent_yosys=2,
        debug_enabled=True,
        debug_log_file="./logs/single_test_debug.log"
    )
    
    # Generate bug categories
    print("Generating bug categories...")
    bug_categories = await mg.generate_bug_categories(temperature=0.7)
    
    print(f"Generated {len(bug_categories)} bug categories:")
    for i, bug in enumerate(bug_categories):
        print(f"  {i+1}. {bug['bug_type']}: {bug['description']}")
    
    # Generate mutants
    print("\nGenerating mutants...")
    mutants = await mutg.generate_mutants(bug_categories, temperature=0.8)
    
    print(f"Generated {len(mutants)} mutants:")
    for i, (mutant_code, bug_type) in enumerate(mutants):
        print(f"  {i+1}. Bug: {bug_type}")
        print(f"     Code preview: {mutant_code[:150]}...")
        print()
    
    return bug_categories, mutants


if __name__ == "__main__":
    print("Mutation Pipeline Test")
    print("=" * 50)
    
    # Run the full pipeline test
    asyncio.run(test_mutation_pipeline())
    
    # Uncomment to test a single design
    # test_code = '''module test_module(
    #     input [7:0] a,
    #     input [7:0] b,
    #     output [7:0] result
    # );
    #     assign result = a + b;
    # endmodule'''
    # asyncio.run(test_single_design("Test Module", test_code)) 