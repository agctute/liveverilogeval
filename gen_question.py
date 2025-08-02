from pathlib import Path
import json
import yaml
import asyncio
from utils.LLM_call import LLMClient
from typing import List, Tuple
import asyncio
from collections import Counter
from utils.mutate import standardize
from utils.hash_utils import hash_string
from utils.equivalence_check import check_equivalence

# Import RTL_GEN_PROMPT from variant_gen.py
RTL_GEN_PROMPT = open('./templates/rtl_gen.txt', 'r').read()

def extract_question(passage: str):
    """
    Extracts the question from a passage by searching for 'QUESTION BEGIN' and 'QUESTION END' markers.

    Args:
        passage (str): The input string containing the question between markers.

    Returns:
        str: The extracted question, or an empty string if markers are not found.
    """
    begin_marker = "QUESTION BEGIN"
    end_marker = "QUESTION END"
    start_idx = passage.find(begin_marker)
    end_idx = passage.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return ""
    # Move start_idx to the end of the begin_marker
    start_idx += len(begin_marker)
    question = passage[start_idx:end_idx]
    return question.strip()

def extract_code(content: str) -> str:
    """
    Extracts code from a response by looking for ```verilog blocks.
    
    Args:
        content (str): The response content containing code blocks.
        
    Returns:
        str: The extracted code, or the original content if no code blocks found.
    """
    start = False
    lines = content.split('\n')
    started = False
    res = []
    for line in lines:
        if line.strip().startswith("```") or line.strip().startswith("---"):
            start = not start
        elif start:
            started = True
            res.append(line)

    if not started:
        # If no code blocks found, return the original content
        return content
    out = "\n".join(res)
    return out

async def gen_question(design: str):
    # Load the prompt from gen_q.json
    with open("prompts/gen_q.json", "r") as f:
        prompt_data = json.load(f)
    base_prompt = prompt_data["prompt"]
    # Append the design string to the prompt
    full_prompt = base_prompt + design
    # Prepare the message for LLMClient
    msg = [{'role': 'system', 'content': full_prompt}]
    # You may need to load API key/config as in other files
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    client = LLMClient((config["calls_per_min"], 60), config["api_key"])
    response, metadata = await client.call_deepseek(msg)
    question = extract_question(response)
    return question 

async def gen_question_bulk(designs: List[str]):
    """
    Generates questions for a list of design strings.

    Args:
        designs: List of design descriptions.

    Returns:
        List[str]: List of generated questions (responses from LLM).
    """
    # Load the prompt from gen_q.json
    with open("prompts/gen_q.json", "r") as f:
        prompt_data = json.load(f)
    base_prompt = prompt_data["prompt"]

    # Prepare messages for each design
    msgs = []
    for design in designs:
        full_prompt = base_prompt + design
        msg = [{'role': 'system', 'content': full_prompt}]
        msgs.append(msg)

    # Load config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    client = LLMClient((config["calls_per_min"], 60), config["api_key"])
    tasks = [client.call_deepseek(msg) for msg in msgs]
    results = await asyncio.gather(*tasks)
    # results is a list of (response, metadata) tuples
    responses = [resp for resp, _ in results]
    return responses


async def verify_question(question: str, design: str, n: int) -> Tuple[bool, List[str]]:
    """
    Verifies a question by generating n modules and checking equivalence with the original design.
    
    Args:
        question: The question to verify
        design: The original design string
        n: Number of modules to generate
        
    Returns:
        tuple: (True/False for equivalence, List of designs that are/are not equivalent)
    """
    
    # Load config for LLM client
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    client = LLMClient((config["calls_per_min"], 60), config["api_key"])
    
    # Generate n modules using the question - all at once
    prompt = RTL_GEN_PROMPT + question
    
    # Prepare messages for batch generation
    msgs = []
    for i in range(n):
        msg = [{'role': 'system', 'content': prompt}]
        msgs.append(msg)
    
    # Generate all designs in parallel
    tasks = [client.call_deepseek(msg) for msg in msgs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    generated_designs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Error generating design {i}: {result}")
            continue
        
        response, metadata = result
        try:
            generated_code = extract_code(response)
            generated_designs.append({
                'content': generated_code,
                'hash': None
            })
        except Exception as e:
            print(f"Error processing design {i}: {e}")
            continue
    
    if not generated_designs:
        print("No designs were successfully generated")
        return False, ""
    
    # Standardize each design and compute hash
    new_designs = []
    for design_info in generated_designs:
        try: 
            standardized_code = standardize(design_info['content'])
            design_info['content'] = standardized_code
            design_info['hash'] = hash_string(standardized_code)
            new_designs.append(design_info)
        except Exception as e:
            continue
    generated_designs = new_designs

    
    # Find the design with the most unique hash (or first valid one)
    valid_designs = [d for d in generated_designs if d['hash'] is not None]
    if not valid_designs:
        print("No valid designs after standardization")
        return False, ""
    
    # Implement sophisticated design selection based on frequency
    
    # Count the frequency of each hash
    hash_counts = Counter(design['hash'] for design in valid_designs)
    
    # Print summary of design distribution
    print(f"Generated {len(valid_designs)} valid designs:")
    for hash_val, count in hash_counts.most_common():
        print(f"  - Hash {hash_val[:16]}... appears {count} time(s)")
    
    """old verification code that would only verify for the most frequently-occurring generated design"""
    # most_common_hash, count = hash_counts.most_common(1)[0]
    # if count > 1:
    #     # Multiple designs with the same hash - select the most frequent one
    #     print(f"✓ Selected most frequent design (appears {count} times)")
    #     selected_design = next(d for d in valid_designs if d['hash'] == most_common_hash)
    #     final_design = selected_design['content']
    # else:
    #     # All designs are unique - select the first one
    #     print(f"✓ All designs are unique, selected the first design")
    #     selected_design = valid_designs[0]
    #     final_design = selected_design['content']
    
    batch_file_path = "./yosys_files/"
    equivalents = []
    non_equivalents = []
    equiv_flag = False
    for des in generated_designs:
        is_equivalent = check_equivalence(batch_file_path, des['content'], design)
        if is_equivalent:
            equiv_flag = True
            equivalents.append(des['content'])
        else:
            non_equivalents.append(des['content'])
    if equiv_flag:
        print(f"✓ Question verification successful - design is equivalent")
        return True, equivalents
    else:
        print(f"✗ Question verification failed - design is not equivalent")
        return False, non_equivalents
    # except Exception as e:
    #     print(f"Error in verify_question: {e}")
    #     return False, ""

if __name__ == "__main__":
    # Run the test
    pass
