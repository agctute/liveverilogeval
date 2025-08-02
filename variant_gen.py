"""
OLD PROTOTYPING FILE: CURRENTLY NOT IN USE
"""
from utils.LLM_call import LLMClient
from pathlib import Path
import asyncio
import re
import yaml

PROPOSAL_GEN_PROMPT = """You are a Verilog description mutator. Given a description for a Verilog module, mutate the description by making small but significant changes . Return only the description of what is need from the Verilog design, not the design itself. 

Tips:
Please only return the newly-generated description, not the implementation or the original description. 

replay format:
###description
(mutated description)
###
"""

JUDGE_PROMPT = "You are a hardware specification judge. Given an initial specification and a list of numbered candidate specifications, identify the one that is the most similar in behavior from the initial. Return only the number of the most different specification surrounded by '$$$', for example: '$$$1$$$'\n"

PROMPT_PROPOSAL = [{'role': 'system', 'content': PROPOSAL_GEN_PROMPT}]

FILE_NAMING_SCHEME = "_desc_variant.txt"

TEST_DESC = """
Implement a module of a 3-bit comparator for comparing binary numbers.

Module name:  
    comparator_3bit               
Input ports:
    A [2:0]: First 3-bit input operand (the first binary number to compare).
    B [2:0]: Second 3-bit input operand (the second binary number to compare).
Output ports:
    A_greater: 1-bit output indicating if A is greater than B.
    A_equal: 1-bit output indicating if A is equal to B.
    A_less: 1-bit output indicating if A is less than B.

Implementation:
Comparison Logic: The module compares the two 3-bit binary numbers A and B using combinational logic.
- The outputs A_greater, A_equal, and A_less are determined based on the comparison of A and B.
- A_greater is set to 1 if A > B, A_equal is set to 1 if A == B, and A_less is set to 1 if A < B.

Output Encoding: The outputs are mutually exclusive, meaning only one of the three outputs will be high (1) at any given time, based on the comparison results.
"""

RTL_GEN_PROMPT = """
task:
Hello, you are a hardware engineering assistant. You will be given a description of an RTL circuit.
Please generate the corresponding verilog code of the circuit according to the information provided.

tips:
please only reply the RTL circuit code in verilog
you have enough tokens to response

reply format:
```verilog
(verilog code)
```

RTL problem description (this can help you understand the RTL code):
"""

def extract_spec(content: str) -> str:
    start = False
    lines = content.split('\n')
    started = False
    res = []
    for line in lines:
        if line.strip().startswith("###"):
            start = not start
        elif start:
            started = True
            res.append(line)

    if not started:
        raise ValueError("No code segment found in string!")
    out = "\n".join(res)
    return out

def extract_code(content: str) -> str:
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
        raise ValueError("No code segment found in string!")
    out = "\n".join(res)
    return out

def get_number(s):
    match = re.search(r'\$\$\$(\d+)\$\$\$', s)
    return int(match.group(1)) if match else None

class Proposal:
    def __init__(self, path: Path, description: str=""):
        self.proposal_path = path
        self.description = description

    def save(self):
        if self.description == "":
            raise ValueError(f"Writing empty Proposal to file! Proposal path: {self.proposal_path}")
        print(f"writing to {self.proposal_path}")
        self.proposal_path.write_text(self.description)

    def change_description(self, new_desc: str):
        self.description = new_desc
        self.save()

    def load(self):
        if self.description != "":
            return
        self.description = self.proposal_path.read_text()

class VariantGenTask:
    # First, given an RTL design, generate a bunch of proposals for mutants
    # Next, have a judge pick the most significant mutant
    # Finally, generate a variant using the mutant description. 
    
    # I should save the mutants since that would be good for later debugging and checks for consistency.
    def __init__(self, client: LLMClient, desc: str, proposal_dir: Path, n:int = 5) -> None:
        self.proposal_dir = proposal_dir
        self.proposals = []
        self.client: LLMClient = client
        self.initial_desc = desc
        self.final_desc = ""
        self.n = n

    def __call__(self):
        asyncio.run(self.create_proposals())
        final_idx = self.judge()
        self.final_desc = self.proposals[final_idx].description
        print("$$$$$$$$$$$$")
        print(self.final_desc)
        res = self.generate_rtl_variant(Path(self.proposal_dir, 'final.v'))
        return res

    def load_proposals(self):
        if self.proposal_dir.exists() == False:
            self.proposal_dir.mkdir(exist_ok=True)

        for proposal in self.proposal_dir.iterdir():
            new_prop = Proposal(proposal)
            new_prop.load()
            self.proposals.append(new_prop)

    async def create_single_proposal(self, prop_file_path: Path) -> Proposal:
        generated_prop, metadata = await self.client.call_deepseek(PROMPT_PROPOSAL)
        generated_prop = extract_spec(generated_prop)
        res = Proposal(prop_file_path, generated_prop)
        res.save()
        self.proposals.append(res)
        return res 

    async def create_proposals(self):
        tasks = [self.create_single_proposal(Path(self.proposal_dir, f"{i+1}{FILE_NAMING_SCHEME}")) for i in range(self.n)]
        return await asyncio.gather(*tasks)

    def judge(self) -> int:
        prompt = JUDGE_PROMPT
        for i in range(len(self.proposals)):
            number_prompt = f"\nHardware specification {i+1}:\n{self.proposals[i].description}\n"
            prompt = prompt + number_prompt
        orig_desc_prompt = f"\nOriginal specification: \n{self.initial_desc}\n"
        prompt = prompt + orig_desc_prompt
        print(prompt)
        msg = [{'role': 'system', 'content': prompt}]
        judge_res, metadata = asyncio.run(self.client.call_deepseek(msg))
        num = get_number(judge_res)
        if num == None: 
            print(judge_res)
            raise ValueError()
        return num - 1

    def generate_rtl_variant(self, path: Path):
        prompt = RTL_GEN_PROMPT + self.final_desc
        print(prompt)
        msg = [{'role': 'system', 'content': prompt}]
        answer, metadata = asyncio.run(self.client.call_deepseek(msg))
        answer = extract_code(answer)
        path.write_text(answer)

if __name__ == '__main__':
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
    # print(config["api_key"])
    client = LLMClient((200,60), config["api_key"])
    Path('./comparator_3_bit').mkdir(exist_ok=True)
    task = VariantGenTask(client, TEST_DESC,Path('./reverse_32_vec'))
    task()
    
