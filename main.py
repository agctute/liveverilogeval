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

# Initialize database
db = Database()

# Load existing designs from JSONL file
with open("./data/designs.jsonl") as f:
    data = [json.loads(line) for line in f]

# Get the traffic light design (index 36)
traffic_light_design = data[36]
traffic_light_content = standardize(traffic_light_design['content'])

# Add the original traffic light design to database
db.add_design(traffic_light_content, hash_string(traffic_light_content))

# Generate mutants
mutants = mutate(traffic_light_content, 4, 3)

# Add mutants to database with temporary equivalence groups
for i, mutant in enumerate(mutants):
    temp_equiv_id = hash_string(mutant['content'])
    db.add_design(mutant['content'], temp_equiv_id)

# Check equivalence between mutants and merge groups if needed
temp_groups = [f"temp_{i+1}" for i in range(len(mutants))]
for i, group1 in enumerate(temp_groups):
    for j, group2 in enumerate(temp_groups[i+1:], i+1):
        if group1 == group2:
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
                # Update temp_groups list after merge
                temp_groups = [g for g in temp_groups if g in db.designs]

# Check equivalence with original design and merge if needed
original_equiv_id = traffic_light_design['equivalence_group']
for temp_group in temp_groups:
    if temp_group in db.designs:
        temp_designs = db.designs[temp_group]
        if temp_designs:
            equivalent = check_equivalence(batch_file_path, temp_designs[0].content, traffic_light_content)
            if equivalent:
                db.merge_equiv_groups(original_equiv_id, temp_group)

# Generate questions for each equivalence group
questions = []
design_strs = []

# Get one design from each equivalence group
for equiv_id, designs in db.designs.items():
    if designs:  # Make sure group is not empty
        design_strs.append(designs[0].content)
        questions.append(equiv_id)  # Placeholder for question generation

# Generate questions in bulk
questions_content = asyncio.run(gen_question_bulk(design_strs))

# Verify questions and add to database
for i, question in enumerate(questions_content):
    flag, generated_designs = asyncio.run(verify_question(question, design_strs[i], 100, 5))
    
    # Get the equivalence group ID for this design
    equiv_id = list(db.designs.keys())[i] if i < len(db.designs) else None
    
    if equiv_id:
        # Add the generated designs to the same equivalence group
        for generated_design in generated_designs:
            db.add_design(generated_design, equiv_id)
        
        # Add the question to the database
        if flag:
            # Question verification succeeded - add to the same equivalence group
            db.add_question(question, {equiv_id})
        else:
            # Question verification failed - create new equivalence group for each non-equivalent design
            for generated_design in generated_designs:
                new_equiv_id = hash_string(generated_design)
                db.add_design(generated_design, new_equiv_id)
                db.add_question(question, {new_equiv_id})

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
    


