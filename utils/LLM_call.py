from openai import OpenAI
from typing import List, Dict, Tuple
import asyncio
import time
import yaml
from pathlib import Path
from asynciolimiter import Limiter

class LLMClient:
    """Client class for interacting with LLMs
        Args:
        limiter_params - rate limiter settings (# of calls / # of seconds)
        log_path - path of output logs
    """
    def __init__(self, limiter_params: Tuple[int, int], api_key: str) -> None:
        """Init class

        Args:
        limiter_params - rate limiter settings (# of calls / # of seconds)
        log_path - path of output logs
        """
        self.limiter = Limiter(limiter_params[0]/limiter_params[1])
        self.deepseek_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def llm_call(self, msgs: List[Dict[str, str]], model: str="deepseek") -> None:
        """Generate something w/ an LLM
        
        Args:
        msgs - what to input to the LLM (Ex: [{'system': 'Hello World!'}])
        """
        pass

    async def call_deepseek(self, msgs, reasoner: bool=False, temperature: float=0.6):
        """Generate something w/ Deepseek

        Args:
        msgs - what to input to the LLM (Example: [{"role": "system", "content": "Hello"}])
        reasoner - whether or not to use the deepseek-reasoner model
        """
        await self.limiter.wait()
        def sync_call():
            start_time = time.time()
            res = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=msgs,
                temperature=temperature,
            )
            end_time = time.time()
            execution_time = end_time - start_time
            return res, start_time, execution_time
        response, start_time, exec_time = await asyncio.to_thread(sync_call)
        answer = response.choices[0].message.content
        if answer == None:
            raise ValueError("Deepseek API Call Failed!")
        system_fingerprint = response.system_fingerprint
        usage = {"completion_tokens": response.usage.completion_tokens, "prompt_tokens": response.usage.prompt_tokens, "total_tokens": response.usage.total_tokens}
        model = response.model
        response_metadata = {"messages": msgs, "call_time": start_time, "execution_time": exec_time, "system_fingerprint": system_fingerprint, "model": model, "usage": usage}
        return (answer, response_metadata)

async def test():
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
    # print(config["api_key"])
    client = LLMClient((300,60), config["api_key"])
    test_msg = [{"role": "system", "content": "Hello"}]
    response, metadata = await client.call_deepseek(test_msg)
    print(response)
    print("------------------------------------")
    print(metadata)
    return


if __name__ == "__main__":
    asyncio.run(test())


