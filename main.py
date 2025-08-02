import json
from gen_question import gen_question_bulk, verify_question
from utils.mutate import mutate, standardize
import threading
from utils.equivalence_check import check_equivalence
from utils.hash_utils import hash_string
import asyncio
from pathlib import Path

batch_file_path = './yosys_files'
with open("./data/designs.jsonl") as f:
    data = [json.loads(line) for line in f]

M = data[36] #traffic light
M['content'] = standardize(M['content'])
mutants = mutate(M['content'], 4, 3)
increment = 1
for m in mutants:
    m['equivalence_group'] = increment
    increment += 1

n = len(mutants)
for i in range(n):
    for j in range(i+1, n):
        if mutants[i]['equivalence_group'] == mutants[j]['equivalence_group']:
            continue
        check = check_equivalence(batch_file_path, mutants[i]['content'], mutants[j]['content'])
        if check:
            mutants[j]['equivalence_group'] = mutants[i]['equivalence_group'] 

s = set()
for m in mutants:
    if m['equivalence_group'] not in s:
        equivalent = check_equivalence(batch_file_path, m['content'], M['content'])
        s.add(m['equivalence_group'])
        if equivalent:
            for mut in mutants:
                if mut['equivalence_group'] == m['equivalence_group']:
                    mut['equivalence_group'] = M['equivalence_group']
            m['equivalence_group'] = M['equivalence_group']
            
group = mutants
mutants.append(M)
# Split mutants into a list of lists by equivalence_group
from collections import defaultdict

equiv_groups = defaultdict(list)
for m in mutants:
    equiv_groups[m['equivalence_group']].append(m)

designs = [group[0] for group in equiv_groups.values()]
design_strs = [d['content'] for d in designs]
question_json = []
questions = asyncio.run(gen_question_bulk(design_strs))
for i in range(len(questions)):
    flag, design = asyncio.run(verify_question(questions[i], design_strs[i], 20))
    eg = designs[i]['equivalence_group']
    h = hash_string(design)
    design_entry = {
        'hash': h,
        'equivalence_group': eg,
        'content': design
    }
    q_entry = {
        'hash': hash_string(questions[i]),
        'equivalence_group': eg,
        'question': questions[i]
    }
    if not flag:
        q_entry['equivalence_group'] = h
        design_entry['equivalence_group'] = h
    equiv_groups[design_entry['equivalence_group']].append(design_entry)
    question_json.append(q_entry)

mutants_grouped = list(equiv_groups.values())
Path("data_temp").mkdir(exist_ok=True)
with open("data_temp/designs.jsonl", "w") as f:
    for design in mutants_grouped:
        for item in design:
            f.write(json.dumps(item) + '\n')

# Prepare data for questions.jsonl: all question_json entries
with open("data_temp/questions.jsonl", "w") as f:
    for question in question_json:
        f.write(json.dumps(question) + '\n')
    


