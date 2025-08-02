"""
Script to process all .v files in rtllm_modules_pyverilog and add them to data/designs.jsonl
with hash, equivalence_group, and content fields.
"""
import json
import hashlib
from pathlib import Path
from utils.equivalence_check import yosys_sanity_check

batch_file_path = './yosys_files/'
def hash_file_content(content: str) -> str:
    """Generate SHA256 hash of file content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def process_designs():
    """Process all .v files and create JSONL entries."""
    
    # Define paths
    pyverilog_dir = Path("./rtllm_modules_pyverilog").absolute()
    output_file = Path("./data/designs.jsonl").absolute()
    
    # Ensure output directory exists
    output_file.parent.mkdir(exist_ok=True)
    
    # Get all .v files
    v_files = list(pyverilog_dir.glob("*.v"))
    
    if not v_files:
        print("No .v files found in rtllm_modules_pyverilog directory")
        return
    
    print(f"Found {len(v_files)} .v files to process")
    
    # Process each file
    entries = []
    equivalence_group = 1
    
    for v_file in sorted(v_files):
        try:
            print(f"Processing: {v_file.name}")
            
            # Read file content
            with open(v_file, 'r', encoding='utf-8') as f:
                content = f.read()
            sane_flag = yosys_sanity_check(batch_file_path, content)
            if not sane_flag:
                raise ValueError("Failed sanity check")
            # Generate hash
            file_hash = hash_file_content(content)
            
            # Create JSONL entry
            entry = {
                "hash": file_hash,
                "equivalence_group": equivalence_group,
                "content": content
            }
            
            entries.append(entry)
            equivalence_group += 1
            
            print(f"  ✓ Added entry with hash: {file_hash[:16]}...")
            
        except Exception as e:
            print(f"  ✗ Error processing {v_file.name}: {e}")
            continue
    
    # Write to JSONL file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
        
        print(f"\n✓ Successfully processed {len(entries)} files")
        print(f"✓ Output written to: {output_file}")
        
    except Exception as e:
        print(f"✗ Error writing to {output_file}: {e}")

def verify_jsonl():
    """Verify the generated JSONL file."""
    output_file = Path("./data/designs.jsonl").absolute()
    
    if not output_file.exists():
        print("JSONL file does not exist")
        return
    
    try:
        entries = []
        with open(output_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    entry = json.loads(line.strip())
                    entries.append(entry)
                except json.JSONDecodeError as e:
                    print(f"✗ JSON decode error at line {line_num}: {e}")
                    return
        
        print(f"✓ JSONL file verification successful")
        print(f"✓ Total entries: {len(entries)}")
        
        # Check structure
        for i, entry in enumerate(entries):
            if not all(key in entry for key in ['hash', 'equivalence_group', 'content']):
                print(f"✗ Entry {i+1} missing required fields")
                return
        
        print("✓ All entries have required fields")
        
        # Show sample entry
        if entries:
            print(f"\nSample entry:")
            sample = entries[0]
            print(f"  Hash: {sample['hash'][:16]}...")
            print(f"  Equivalence group: {sample['equivalence_group']}")
            print(f"  Content length: {len(sample['content'])} characters")
        
    except Exception as e:
        print(f"✗ Error verifying JSONL file: {e}")

if __name__ == "__main__":
    print("Processing .v files and creating JSONL entries...")
    print("=" * 60)
    
    process_designs()
    
    print("\n" + "=" * 60)
    print("Verifying generated JSONL file...")
    verify_jsonl() 