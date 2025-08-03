import json
import yaml
from gen_question import gen_question_bulk, verify_question
from utils.mutate import mutate, standardize
from utils.equivalence_check import check_equivalence
from utils.hash_utils import hash_string
import asyncio
from pathlib import Path
from entry_types import Database

# Load configuration from config.yaml
with open("config.yaml", "r") as config_file:
    config = yaml.safe_load(config_file)

batch_file_path = config['batch_dir_path']

def process_design_with_mutants(db: Database, design_content: str, num_mutants: int = 4, mutation_level: int = 3):
    """
    Process a design by generating mutants and checking equivalence.
    
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
    
    for i, group1 in enumerate(mutant_groups):
        for j, group2 in enumerate(mutant_groups[i+1:], i+1):
            if group1 == group2 or group1 not in db.designs or group2 not in db.designs:
                continue
            
            # Get designs from each group
            designs1 = db.designs[group1]
            designs2 = db.designs[group2]
            
            if designs1 and designs2:
                # Check equivalence between first design in each group
                check = check_equivalence(batch_file_path, designs1[0].content, designs2[0].content)
                if check:
                    # Merge the groups
                    db.merge_equiv_groups(group1, group2)
                    # Update mutant_groups list after merge
                    mutant_groups = [g for g in mutant_groups if g in db.designs]
    return

# Initialize database
db = Database()

# Load existing designs from JSONL file
with open("./data/designs.jsonl") as f:
    data = [json.loads(line) for line in f]

# Process all designs with mutants
print(f"Processing {len(data)} designs...")
for i, design_data in enumerate(data):
    print(f"Processing design {i+1}/{len(data)}")
    process_design_with_mutants(db, design_data['content'])

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
questions_content = asyncio.run(gen_question_bulk(design_strs))

# Verify questions and add to database
for i, question in enumerate(questions_content):
    print(f"Verifying question {i+1}/{len(questions_content)}")
    flag, generated_designs = asyncio.run(verify_question(question, design_strs[i], 100, 5))
    
    # Get the equivalence group ID for this design
    equiv_id = list(db.designs.keys())[i] if i < len(db.designs) else None
    
    if equiv_id:
        
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
    


