import json
import yaml
from gen_question import gen_question_bulk, verify_question
from utils.mutate import mutate, standardize
from utils.equivalence_check import check_equivalence
from utils.hash_utils import hash_string
from utils.LLM_call import LLMClient
import asyncio
from pathlib import Path
from entry_types import Database

# Load configuration from config.yaml
with open("config.yaml", "r") as config_file:
    config = yaml.safe_load(config_file)

batch_file_path = config['batch_dir_path']

# Global semaphore to limit concurrent equivalence checks
equivalence_semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent checks

async def process_design_with_mutants(db: Database, design_content: str, num_mutants: int = 4, mutation_level: int = 3):
    """
    Process a design by generating mutants and checking equivalence.
    Optimized to run all equivalence checks in parallel for maximum speed.
    
    Args:
        db: Database instance to store designs
        design_content: The original design content
        num_mutants: Number of mutants to generate
        mutation_level: Level of mutation to apply
    """
    # Standardize the design content
    standardized_content = standardize(design_content)
    
    # Add the original design to database
    original_equiv_id = hash_string(standardized_content)
    db.add_design(standardized_content, original_equiv_id)
    
    # Generate mutants
    mutants = mutate(standardized_content, num_mutants, mutation_level)
    
    # Add mutants to database with their hash as equivalence group ID
    mutant_groups = []
    for mutant in mutants:
        mutant_equiv_id = hash_string(mutant['content'])
        db.add_design(mutant['content'], mutant_equiv_id)
        mutant_groups.append(mutant_equiv_id)
    
    mutant_groups.append(original_equiv_id)
    
    # Remove any duplicate or invalid groups
    mutant_groups = [g for g in mutant_groups if g in db.designs]
    
    if len(mutant_groups) <= 1:
        return  # No equivalence checks needed
    
    # Create all pairwise combinations for equivalence checking
    equivalence_tasks = []
    group_pairs = []
    
    for i, group1 in enumerate(mutant_groups):
        for j, group2 in enumerate(mutant_groups[i+1:], i+1):
            if group1 == group2:
                continue
            
            # Get designs from each group
            designs1 = db.designs[group1]
            designs2 = db.designs[group2]
            
            if designs1 and designs2:
                # Create task for equivalence check with semaphore
                async def check_with_semaphore():
                    async with equivalence_semaphore:
                        return await check_equivalence(batch_file_path, designs1[0].content, designs2[0].content)
                
                task = check_with_semaphore()
                equivalence_tasks.append(task)
                group_pairs.append((group1, group2))
    
    if not equivalence_tasks:
        return  # No equivalence checks needed
    
    # Run all equivalence checks in parallel
    print(f"Running {len(equivalence_tasks)} equivalence checks in parallel...")
    results = await asyncio.gather(*equivalence_tasks, return_exceptions=True)
    
    # Count successful and failed checks
    successful_checks = sum(1 for r in results if not isinstance(r, Exception))
    failed_checks = len(results) - successful_checks
    print(f"Equivalence checks completed: {successful_checks} successful, {failed_checks} failed")
    
    # Process results and merge groups
    # Use union-find approach: collect all equivalent pairs, then merge connected components
    equivalent_pairs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Equivalence check failed for pair {group_pairs[i]}: {result}")
            continue
        
        if result:  # Equivalent
            equivalent_pairs.append(group_pairs[i])
    
    # Merge equivalent groups using union-find
    if equivalent_pairs:
        # Create a graph of equivalent groups
        graph = {}
        for group1, group2 in equivalent_pairs:
            if group1 not in graph:
                graph[group1] = set()
            if group2 not in graph:
                graph[group2] = set()
            graph[group1].add(group2)
            graph[group2].add(group1)
        
        # Find connected components (equivalence classes)
        visited = set()
        components = []
        
        for group in graph:
            if group in visited:
                continue
            
            # BFS to find connected component
            component = set()
            queue = [group]
            visited.add(group)
            
            while queue:
                current = queue.pop(0)
                component.add(current)
                
                for neighbor in graph.get(current, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            
            if len(component) > 1:  # Only merge if there are multiple groups
                components.append(component)
        
        # Merge each component into a single group
        for component in components:
            component_list = list(component)
            # Merge all groups in component into the lexicographically smallest one
            target_group = min(component_list)
            
            for group in component_list:
                if group != target_group:
                    db.merge_equiv_groups(target_group, group)
    
    return

async def main():
    # Initialize database
    db = Database()

    # Load existing designs from JSONL file
    with open("./data/designs.jsonl") as f:
        data = [json.loads(line) for line in f]

    # Process all designs with mutants in parallel
    print(f"Processing {len(data)} designs in parallel...")
    processing_tasks = []
    for i, design_data in enumerate(data):
        print(f"Starting processing for design {i+1}/{len(data)}")
        task = process_design_with_mutants(db, design_data['content'])
        processing_tasks.append(task)
    
    # Wait for all designs to be processed
    results = await asyncio.gather(*processing_tasks, return_exceptions=True)
    
    # Count successful and failed processing
    successful_processing = sum(1 for r in results if not isinstance(r, Exception))
    failed_processing = len(results) - successful_processing
    print(f"Design processing completed: {successful_processing} successful, {failed_processing} failed")

    # Generate questions for each equivalence group
    questions = []
    design_strs = []

    # Get one design from each equivalence group
    for equiv_id, designs in db.designs.items():
        if not designs:
            del db.designs[equiv_id]
            continue

        design_strs.append(designs[0].content)
        questions.append(equiv_id)  # Placeholder for question generation

    # Generate questions in bulk
    questions_content = await gen_question_bulk(design_strs)

    # Verify questions and add to database in parallel
    print(f"Verifying {len(questions_content)} questions")
    verification_tasks = []
    question_data = []
    
    client = LLMClient((config["calls_per_min"], 60), config["api_key"])
    for i, question in enumerate(questions_content):
        equiv_id = list(db.designs.keys())[i] if i < len(db.designs) else None
        if equiv_id:
            task = verify_question(question, design_strs[i], 10, 2, client)
            verification_tasks.append(task)
            question_data.append((question, equiv_id, i))
    
    # Run all verifications in parallel
    verification_results = await asyncio.gather(*verification_tasks, return_exceptions=True)
    
    # Count successful and failed verifications
    successful_verifications = sum(1 for r in verification_results if not isinstance(r, Exception))
    failed_verifications = len(verification_results) - successful_verifications
    print(f"Question verifications completed: {successful_verifications} successful, {failed_verifications} failed")
    
    # Process results
    for i, result in enumerate(verification_results):
        if isinstance(result, Exception):
            print(f"Question verification failed for question {i+1}: {result}")
            continue
        
        question, equiv_id, design_idx = question_data[i]
        flag, generated_designs = result
        
        # Add the question to the database
        if flag:
            # Question verification succeeded - add to the same equivalence group
            # Add the generated designs to the same equivalence group
            for generated_design in generated_designs:
                db.add_design(generated_design, equiv_id)
            db.add_question(question, set([equiv_id]))
        else:
            # Question verification failed - create new equivalence group for each non-equivalent design
            new_ids = set()
            for generated_design in generated_designs:
                new_equiv_id = hash_string(generated_design)
                db.add_design(generated_design, new_equiv_id)
                new_ids.add(new_equiv_id)
            db.add_question(question, new_ids)

    # Create output directory
    Path("data_temp").mkdir(exist_ok=True)

    # Write database to JSONL files
    db.write_db("data_temp/designs.jsonl", "data_temp/questions.jsonl", replace=True)
    for design in db.designs:
        if len(db.designs[design]) == 0:
            del db.designs[design]

    print(f"Database contains {len(db.designs)} equivalence groups")
    print(f"Database contains {len(db.questions)} unique questions")
    print("Data written to data_temp/designs.jsonl and data_temp/questions.jsonl")

if __name__ == "__main__":
    asyncio.run(main())
    


