import json
from collections import defaultdict

results = []
with open('./results/questions.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        results.append(data)
# ['question_valid', 'question_text', 'mutant_code', 'bug_type', 'original_code', 'original_design_hash', 'answers', 'validation_result', 'question_number', 'mutant_index']
by_hash = defaultdict(list)
for result in results:
    by_hash[result['original_design_hash']].append(result)

total_counter = 0
total_mutant_questions = 0
for hash, results in by_hash.items():
    counter = 0
    mutant_questions = 0
    seen_mutants = set()
    for result in results:
        if result['question_valid']:
            counter += 1
            if result['mutant_index'] not in seen_mutants:
                mutant_questions += 1
                seen_mutants.add(result['mutant_index'])
    print(hash)
    print(len(results))
    print(counter)
    print(counter / len(results))
    if counter > 0:
        total_counter += 1
        total_mutant_questions += mutant_questions
print(total_counter)
print(total_mutant_questions)
print(total_mutant_questions / total_counter)

