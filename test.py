from entry_types import Database
from pathlib import Path
from utils.mutate import mutate
import json
import difflib
import asyncio

async def mutate_database(db: Database, output_d_jsonl: Path, output_q_jsonl: Path):
    res = Database()
    for equiv_id, designs in db.designs.items():
        for design in designs:
            mutants = await mutate(design.content, 1, 3)
            for mutant in mutants:
                res.add_design(mutant['content'], mutant['hash'])
    res.write_db(output_d_jsonl, output_q_jsonl)
    return

async def test():
    db = Database()
    db.read_db("./data/designs.jsonl", "./data/questions.jsonl")
    await mutate_database(db, Path("./mutated_designs.jsonl"), Path("./mutated_questions.jsonl"))

def write_jsonl_to_files(jsonl_path: Path, output_dir: Path):
    output_dir.mkdir(exist_ok=True)
    with open(jsonl_path, 'r') as f:
        for i, line in enumerate(f, 1):
            entry = json.loads(line)
            with open(output_dir / f"dut{i}.v", 'w') as f:
                f.write(entry['content'])

def compare_directories_interactive(dir1: Path, dir2: Path):
    """
    Compare files between two directories and show diffs interactively.
    Press any key to continue to the next file.
    """
    # Get all files from both directories
    files1 = set(f.name for f in dir1.iterdir() if f.is_file())
    files2 = set(f.name for f in dir2.iterdir() if f.is_file())
    
    # Find matching filenames
    matching_files = files1.intersection(files2)
    
    if not matching_files:
        print(f"No matching files found between {dir1} and {dir2}")
        return
    
    print(f"Found {len(matching_files)} matching files to compare")
    print("Press Enter to view next diff, or 'q' to quit\n")
    
    for i, filename in enumerate(sorted(matching_files), 1):
        file1_path = dir1 / filename
        file2_path = dir2 / filename
        
        print(f"[{i}/{len(matching_files)}] Comparing: {filename}")
        print("=" * 60)
        
        try:
            # Read file contents
            with open(file1_path, 'r') as f1:
                content1 = f1.readlines()
            with open(file2_path, 'r') as f2:
                content2 = f2.readlines()
            
            # Generate diff
            diff = difflib.unified_diff(
                content1, content2,
                fromfile=str(file1_path),
                tofile=str(file2_path),
                lineterm=''
            )
            
            # Print diff
            diff_lines = list(diff)
            if diff_lines:
                for line in diff_lines:
                    print(line)
            else:
                print("Files are identical")
            
            print("\n" + "=" * 60)
            
            # Wait for user input
            user_input = input("Press Enter to continue, 'q' to quit: ").strip().lower()
            if user_input == 'q':
                print("Comparison stopped by user")
                break
                
        except Exception as e:
            print(f"Error comparing {filename}: {e}")
            input("Press Enter to continue...")

if __name__ == "__main__":
    # asyncio.run(test())
    # write_jsonl_to_files(Path("./data/designs.jsonl"), Path("./original_designs"))
    compare_directories_interactive(Path("./original_designs"), Path("./mutated_designs"))