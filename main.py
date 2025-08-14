from utils.generators import create_generators, DebugLogger
from entry_types import DesignEntry, Database
from utils.LLM_call import LLMClient
import yaml
import asyncio
import json

async def run():
    # Load existing designs from JSONL file
    with open("./data/designs.jsonl", "r") as f:
        data = [json.loads(line) for line in f]

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    client = LLMClient((60, 60), config["api_key"])

    # Enable debug logging (set to False to disable)
    debug_enabled = True
    debug_log_file = "./logs/generator_debug.log"

    tests = [13, 14, 34]
    tasks = [
        val_single_design(data[t]["content"], client, debug_enabled, debug_log_file) for t in tests
    ]
    print(f"Validating {len(tasks)} designs")
    results = await asyncio.gather(*tasks)
    print(f"Validated {len(results)} designs")

    with open("./data/valid_questions.jsonl", "w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")
    return

async def val_single_design(verilog_code: str, client: LLMClient, debug_enabled: bool = False, debug_log_file: str = "./logs/generator_debug.log"):
    design_entry = DesignEntry(verilog_code)
    
    # Create all generators with shared debug logging
    qg, ag, vqg = create_generators(
        design_entry=design_entry,
        client=client,
        n_answers=2,
        max_concurrent_yosys=4,
        debug_enabled=debug_enabled,
        debug_log_file=debug_log_file
    )
    question = await qg.generate()
    ag.question = question
    
    print(f"Validating {design_entry.hash}")
    is_valid = await vqg.validate()
    print(is_valid, vqg.valid_question)
    return {"is_valid": is_valid, "question": question}

asyncio.run(run())