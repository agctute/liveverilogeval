from utils.generators import create_generators, DebugLogger
from entry_types import DesignEntry, Database
from utils.LLM_call import LLMClient
import yaml
import asyncio
import json
from pathlib import Path

async def run():
    # Load existing designs from JSONL file
    with open("./data/designs.jsonl", "r") as f:
        data = [json.loads(line) for line in f]

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    client = LLMClient((300, 60), config["api_key"])

    debug_enabled = True
    debug_log_file = "./logs/generator_debug.log"

    # Create output directory for results
    output_dir = Path("./results")
    output_dir.mkdir(exist_ok=True)

    tasks = [
        process_single_design(design["content"], client, debug_enabled, debug_log_file) for design in data
    ]
    print(f"Processing {len(tasks)} designs with mutation pipeline")
    results = await asyncio.gather(*tasks)
    
    # Flatten all questions from all designs into a single list
    all_questions = []
    successful_designs = 0
    failed_designs = 0
    
    for result in results:
        if "error" in result:
            failed_designs += 1
            continue
        
        successful_designs += 1
        if "questions" in result:
            all_questions.extend(result["questions"])
    
    # Save flattened questions to JSONL file
    with open("./results/questions_new.jsonl", "w") as f:
        for question in all_questions:
            f.write(json.dumps(question, ensure_ascii=False) + "\n")
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Total designs processed: {len(results)}")
    print(f"  Successful: {successful_designs}")
    print(f"  Failed: {failed_designs}")
    print(f"  Total questions generated: {len(all_questions)}")
    
    return all_questions

async def process_single_design(verilog_code: str, client: LLMClient, debug_enabled: bool = False, debug_log_file: str = "./logs/generator_debug.log"):
    """Process a single design through the complete mutation and question generation pipeline."""
    design_entry = DesignEntry(verilog_code)
    
    print(f"\nProcessing design: {design_entry.hash}")
    print("-" * 60)
    
    try:
        # Create all generators
        qg, ag, vqg, mg, mutg = create_generators(
            design_entry=design_entry,
            client=client,
            n_answers=8,
            max_concurrent_yosys=8,
            debug_enabled=debug_enabled,
            debug_log_file=debug_log_file
        )
        
        print("  Generating bug categories...")
        bug_categories = await mg.generate_bug_categories(temperature=0.7)
        print(f"  Generated {len(bug_categories)} bug categories")
        
        print("  Generating mutants...")
        mutants = await mutg.generate_mutants(bug_categories, temperature=0.8)
        print(f"  Generated {len(mutants)} mutants")

        print("  Generating questions for each mutant...")
        async def generate_questions_for_mutant(mutant_data, mutant_index):
            """Generate questions for a single mutant."""
            mutant_code, bug_type = mutant_data
            print(f"    Processing mutant {mutant_index + 1} (bug: {bug_type})...")
            
            # Create a new design entry for the mutant
            mutant_design_entry = DesignEntry(mutant_code)
            
            # Create generators for the mutant
            mutant_qg, mutant_ag, mutant_vqg, _, _ = create_generators(
                design_entry=mutant_design_entry,
                client=client,
                n_answers=8,
                max_concurrent_yosys=8,
                debug_enabled=debug_enabled,
                debug_log_file=debug_log_file
            )
            
            # Generate 3 questions for this mutant in parallel
            question_tasks = [mutant_qg.generate(temperature=0.6) for _ in range(3)]
            
            try:
                questions = await asyncio.gather(*question_tasks, return_exceptions=True)

                # Prepare validation tasks for all questions
                validation_tasks = []
                valid_question_generators = []
                for j, question in enumerate(questions):
                    if isinstance(question, Exception):
                        print(f"      Error generating question {j+1}: {question}")
                        validation_tasks.append(None)
                        valid_question_generators.append(None)
                        continue
                    
                    question_design_entry = DesignEntry(mutant_code)
                    
                    question_qg, question_ag, question_vqg, _, _ = create_generators(
                        design_entry=question_design_entry,
                        client=client,
                        n_answers=10,
                        max_concurrent_yosys=2,
                        debug_enabled=debug_enabled,
                        debug_log_file=debug_log_file
                    )
                    
                    # Set the question for the answer generator
                    question_ag.question = question
                    
                    valid_question_generators.append((question_vqg, question_ag, question, j))
                    validation_tasks.append(question_vqg.validate())

                # Run all validations in parallel (skip None entries)
                results = []
                if validation_tasks:
                    # Only run asyncio.gather on non-None tasks
                    filtered_tasks = [task for task in validation_tasks if task is not None]
                    validation_results = await asyncio.gather(*filtered_tasks, return_exceptions=True)
                else:
                    validation_results = []

                mutant_questions = []
                result_idx = 0
                for idx, vqg_tuple in enumerate(valid_question_generators):
                    if vqg_tuple is None:
                        continue  # This was an exception in question generation
                    question_vqg_instance, question_ag_instance, question, j = vqg_tuple
                    validation_result = validation_results[result_idx]
                    result_idx += 1
                    
                    try:
                        if isinstance(validation_result, Exception):
                            raise validation_result
                        
                        # The answers were already generated during validation
                        # We need to access them from the ValidQuestionGenerator
                        # Since validate() was called, the answers are stored in the AnswerGenerator
                        # but we need to get them from the validation process
                        
                        # Create question dictionary with all required information
                        question_dict = {
                            "question_valid": question_vqg_instance.valid_question,
                            "question_text": question,
                            "mutant_code": mutant_code,
                            "bug_type": bug_type,
                            "original_code": design_entry.content,
                            "original_design_hash": design_entry.hash,
                            "answers": question_vqg_instance.generated_answers,  # Use answers from validation
                            "question_number": j + 1,
                            "mutant_index": mutant_index + 1
                        }
                        
                        mutant_questions.append(question_dict)
                        print(f"      Completed question {j+1} with validation")
                        
                    except Exception as e:
                        print(f"      Error processing question {j+1}: {e}")
                        # Add question with error information
                        question_dict = {
                            "question_valid": False,
                            "question_text": question,
                            "mutant_code": mutant_code,
                            "bug_type": bug_type,
                            "original_code": design_entry.content,
                            "original_design_hash": design_entry.hash,
                            "answers": [],
                            "validation_result": False,
                            "question_number": j + 1,
                            "mutant_index": mutant_index + 1,
                            "error": str(e)
                        }
                        mutant_questions.append(question_dict)
                        continue
                
                print(f"    Generated {len(mutant_questions)} questions for mutant {mutant_index + 1}")
                return mutant_questions
                
            except Exception as e:
                print(f"    Error processing mutant {mutant_index + 1}: {e}")
                return []
        
        # Process all mutants in parallel
        mutant_tasks = [
            generate_questions_for_mutant(mutant_data, i) 
            for i, mutant_data in enumerate(mutants)
        ]
        
        all_questions_lists = await asyncio.gather(*mutant_tasks, return_exceptions=True)
        
        # Flatten the results
        all_questions = []
        for questions_list in all_questions_lists:
            if isinstance(questions_list, Exception):
                print(f"  Error processing mutant: {questions_list}")
                continue
            all_questions.extend(questions_list)
        
        # Store comprehensive results
        result = {
            "design_hash": design_entry.hash,
            "original_code": verilog_code,
            "bug_categories": bug_categories,
            "mutants": [
                {
                    "bug_type": bug_type,
                    "mutant_code": mutant_code,
                    "code_length": len(mutant_code)
                }
                for mutant_code, bug_type in mutants
            ],
            "questions": all_questions,
            "total_mutants": len(mutants),
            "total_questions": len(all_questions),
            "timestamp": asyncio.get_event_loop().time()
        }
        
        print(f"  ✓ Successfully processed design with {len(mutants)} mutants and {len(all_questions)} questions")
        return result
        
    except Exception as e:
        print(f"  ✗ Error processing design: {e}")
        return {
            "design_hash": design_entry.hash,
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

async def test_mutation_pipeline():
    """Test the complete mutation pipeline on sample designs."""
    
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
    
    client = LLMClient((60, 60), api_key)
    debug_enabled = True
    debug_log_file = "./logs/mutation_test_debug.log"
    
    # Sample designs to test
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
        }
    ]
    
    print(f"Testing mutation pipeline on {len(sample_designs)} sample designs...")
    print("=" * 80)
    
    async def process_test_design(design_data, design_index):
        """Process a single test design."""
        print(f"\nProcessing design {design_index + 1}: {design_data['name']}")
        print("-" * 60)
        
        try:
            design_entry = DesignEntry(design_data["content"])
            
            # Create all generators
            qg, ag, vqg, mg, mutg = create_generators(
                design_entry=design_entry,
                client=client,
                n_answers=5,
                max_concurrent_yosys=2,
                debug_enabled=debug_enabled,
                debug_log_file=debug_log_file
            )
            
            # Generate bug categories
            print("  Generating bug categories...")
            bug_categories = await mg.generate_bug_categories(temperature=0.7)
            print(f"  Generated {len(bug_categories)} bug categories")
            
            # Generate mutants
            print("  Generating mutants...")
            mutants = await mutg.generate_mutants(bug_categories, temperature=0.8)
            print(f"  Generated {len(mutants)} mutants")
            
            # Generate questions for each mutant in parallel
            print("  Generating questions for each mutant...")
            
            async def generate_questions_for_mutant(mutant_data, mutant_index):
                """Generate questions for a single mutant."""
                mutant_code, bug_type = mutant_data
                print(f"    Processing mutant {mutant_index + 1} (bug: {bug_type})...")
                
                mutant_design_entry = DesignEntry(mutant_code)
                
                mutant_qg, mutant_ag, mutant_vqg, _, _ = create_generators(
                    design_entry=mutant_design_entry,
                    client=client,
                    n_answers=5,
                    max_concurrent_yosys=2,
                    debug_enabled=debug_enabled,
                    debug_log_file=debug_log_file
                )
                
                # Generate 3 questions for this mutant in parallel
                question_tasks = [mutant_qg.generate(temperature=0.6) for _ in range(3)]
                
                try:
                    questions = await asyncio.gather(*question_tasks, return_exceptions=True)
                    mutant_questions = []
                    
                    # Process each question with answer generation and validation
                    for k, question in enumerate(questions):
                        if isinstance(question, Exception):
                            print(f"      Error generating question {k+1}: {question}")
                            continue
                        
                        # Validate the question using ValidQuestionGenerator (this will generate answers)
                        print(f"        Validating question {k+1}...")
                        mutant_ag.question = question
                        is_valid = await mutant_vqg.validate()
                        print(f"        Question validation result: {is_valid}")
                        
                        try:
                            mutant_questions.append({
                                "question_number": k + 1,
                                "question_text": question,
                                "bug_type": bug_type,
                                "answers": mutant_vqg.generated_answers,  # Use answers from validation
                                "validation_result": is_valid,
                                "valid_question": mutant_vqg.valid_question
                            })
                            print(f"      Completed question {k+1} with validation")
                            
                        except Exception as e:
                            print(f"      Error processing question {k+1}: {e}")
                            mutant_questions.append({
                                "question_number": k + 1,
                                "question_text": question,
                                "bug_type": bug_type,
                                "answers": [],
                                "validation_result": False,
                                "valid_question": False,
                                "error": str(e)
                            })
                            continue
                    
                    print(f"    Generated {len(mutant_questions)} questions for mutant {mutant_index + 1}")
                    return mutant_questions
                    
                except Exception as e:
                    print(f"    Error processing mutant {mutant_index + 1}: {e}")
                    return []
            
            # Process all mutants in parallel
            mutant_tasks = [
                generate_questions_for_mutant(mutant_data, j) 
                for j, mutant_data in enumerate(mutants)
            ]
            
            all_questions_lists = await asyncio.gather(*mutant_tasks, return_exceptions=True)
            
            # Flatten the results
            all_questions = []
            for questions_list in all_questions_lists:
                if isinstance(questions_list, Exception):
                    print(f"  Error processing mutant: {questions_list}")
                    continue
                all_questions.extend(questions_list)
            
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
                "questions": all_questions,
                "total_mutants": len(mutants),
                "total_questions": len(all_questions),
                "timestamp": asyncio.get_event_loop().time()
            }
            
            print(f"  ✓ Successfully processed {design_data['name']}")
            return result
            
        except Exception as e:
            print(f"  ✗ Error processing {design_data['name']}: {e}")
            return {
                "design_name": design_data["name"],
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time()
            }
    
    # Process all test designs in parallel
    test_tasks = [
        process_test_design(design_data, i) 
        for i, design_data in enumerate(sample_designs)
    ]
    
    all_results = await asyncio.gather(*test_tasks, return_exceptions=True)
    
    # Handle any exceptions from parallel execution
    processed_results = []
    for i, result in enumerate(all_results):
        if isinstance(result, Exception):
            print(f"Error processing design {i+1}: {result}")
            processed_results.append({
                "design_name": f"Design_{i+1}",
                "error": str(result),
                "timestamp": asyncio.get_event_loop().time()
            })
        else:
            processed_results.append(result)
    
    # Save results to JSONL file
    output_dir = Path("./mutants")
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / "mutants.jsonl"
    
    print(f"\nSaving results to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        for result in processed_results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    
    print(f"✓ Results saved to {output_file}")
    
    # Print summary
    successful_designs = [r for r in processed_results if "error" not in r]
    print(f"\nSummary:")
    print(f"  Total designs processed: {len(processed_results)}")
    print(f"  Successful: {len(successful_designs)}")
    print(f"  Failed: {len(processed_results) - len(successful_designs)}")
    
    if successful_designs:
        total_mutants = sum(len(d["mutants"]) for d in successful_designs)
        total_questions = sum(len(d["questions"]) for d in successful_designs)
        print(f"  Total mutants generated: {total_mutants}")
        print(f"  Total questions generated: {total_questions}")
    
    return processed_results

if __name__ == "__main__":
    print("Comprehensive Design Processing Pipeline")
    print("=" * 50)
    print("This pipeline will:")
    print("1. Load designs from data/designs.jsonl")
    print("2. Generate bug categories for each design")
    print("3. Generate 4 mutants for each design")
    print("4. Generate 3 questions for each mutant")
    print("5. Save results to results/comprehensive_results.jsonl")
    print("=" * 50)
    
    # Run the main pipeline
asyncio.run(run())
    
    # Uncomment to run the test pipeline instead
    # asyncio.run(test_mutation_pipeline())