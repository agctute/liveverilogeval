import pyverilog
import os
import sys
import io
import random
import copy
from typing import List, Dict
from pathlib import Path
from pyverilog.vparser.parser import VerilogCodeParser
from pyverilog.ast_code_generator.codegen import ASTCodeGenerator
from utils.hash_utils import hash_file, hash_string
from utils.equivalence_check import rename_modules_and_instantiations

# Import all the AST node classes we'll need for mutations
from pyverilog.vparser.ast import (
    # Operators
    Plus, Minus, Times, Divide, Mod, Power,
    And, Or, Xor, Xnor, Land, Lor,
    LessThan, GreaterThan, LessEq, GreaterEq, Eq, NotEq, Eql, NotEql,
    Sll, Srl, Sla, Sra,
    # Unary operators
    Uplus, Uminus, Ulnot, Unot, Uand, Unand, Uor, Unor, Uxor, Uxnor,
    # Constants and identifiers
    IntConst, Identifier,
    # Statements
    IfStatement, Assign, BlockingSubstitution, NonblockingSubstitution,
    Always, Block, Cond
)

def get_pyverilog_ast(verilog_input: str | Path) -> pyverilog.vparser.ast.ModuleDef:
    """Takes a string (Verilog code) or a path to a Verilog file and returns the pyverilog AST.
    Args:
        verilog_input: A string (Verilog code) or a path to a Verilog file.
    Returns:
        The pyverilog AST Object.
    """

    # Check if input is a path to a file
    if isinstance(verilog_input, Path) and verilog_input.exists():
        # Suppress warnings and output during parsing
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            parser = VerilogCodeParser([str(verilog_input)])
            ast = parser.parse()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        return ast
    elif isinstance(verilog_input, str):
        # Assume it's Verilog code as a string
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.v', delete=False) as tmpfile:
            tmpfile.write(verilog_input)
            tmpfile_path = tmpfile.name
        try:
            # Suppress warnings and output during parsing
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                parser = VerilogCodeParser([tmpfile_path])
                ast = parser.parse()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
        finally:
            os.remove(tmpfile_path)
        return ast
    elif hasattr(verilog_input, 'read'):
        # File-like object
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.v', delete=False) as tmpfile:
            tmpfile.write(verilog_input.read())
            tmpfile_path = tmpfile.name
        try:
            # Suppress warnings and output during parsing
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                parser = VerilogCodeParser([tmpfile_path])
                ast = parser.parse()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
        finally:
            os.remove(tmpfile_path)
        return ast
    else:
        raise ValueError("Input must be a Verilog code string, a file path, or a file-like object.")

def ast_to_verilog(ast: pyverilog.vparser.ast.ModuleDef) -> str:
    """
    Converts a pyverilog AST (from pyverilog.vparser.ast) back into Verilog code.
    Args:
        ast: The root node of the pyverilog AST (usually a Source object).
    Returns:
        A string containing the Verilog code.
    """
    # Use ASTCodeGenerator to convert AST back to Verilog code
    codegen = ASTCodeGenerator()
    return codegen.visit(ast)

def collect_identifiers(ast):
    """Collect all identifiers from the AST for variable name mutations."""
    identifiers = set()
    
    def traverse(node):
        if isinstance(node, Identifier):
            identifiers.add(node.name)
        elif hasattr(node, 'children'):
            for child in node.children():
                traverse(child)
    
    traverse(ast)
    return list(identifiers)

def collect_operators(ast):
    """Collect all operator nodes from the AST for operator mutations."""
    operators = []
    
    def traverse(node):
        if isinstance(node, (Plus, Minus, Times, Divide, Mod, Power, And, Or, Xor, Xnor, 
                           Land, Lor, LessThan, GreaterThan, LessEq, GreaterEq, Eq, NotEq, 
                           Eql, NotEql, Sll, Srl, Sla, Sra, Uplus, Uminus, Ulnot, Unot, 
                           Uand, Unand, Uor, Unor, Uxor, Uxnor)):
            operators.append(node)
        elif hasattr(node, 'children'):
            for child in node.children():
                traverse(child)
    
    traverse(ast)
    return operators

def collect_assignments(ast):
    """Collect all assignment nodes from the AST."""
    assignments = []
    
    def traverse(node):
        if isinstance(node, (Assign, BlockingSubstitution, NonblockingSubstitution)):
            assignments.append(node)
        elif hasattr(node, 'children'):
            for child in node.children():
                traverse(child)
    
    traverse(ast)
    return assignments

def collect_conditions(ast):
    """Collect all condition nodes from if statements and other conditional constructs."""
    conditions = []
    
    def traverse(node):
        if isinstance(node, IfStatement):
            conditions.append(node.cond)
        elif hasattr(node, 'children'):
            for child in node.children():
                traverse(child)
    
    traverse(ast)
    return conditions

def stuck_at_mutant(ast, p=1):
    """Stuck-at Mutants (SM): Force the signal to a fixed value."""
    assignments = collect_assignments(ast)
    if not assignments:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_assignments = collect_assignments(mutated_ast)
    
    for _ in range(p):
        if not mutated_assignments:
            break
        
        assignment = random.choice(mutated_assignments)
        # Replace the right-hand side with a constant (0 or 1)
        stuck_value = random.choice([IntConst('0'), IntConst('1')])
        assignment.right = stuck_value
        mutated_assignments = collect_assignments(mutated_ast)
    
    return mutated_ast

def negation_mutant(ast, p=1):
    """Negation Mutants (FLIP): Negates or flips the concerned signal."""
    assignments = collect_assignments(ast)
    if not assignments:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_assignments = collect_assignments(mutated_ast)
    
    for _ in range(p):
        if not mutated_assignments:
            break
        
        assignment = random.choice(mutated_assignments)
        # Wrap the right-hand side with a negation operator
        if isinstance(assignment.right, (IntConst, Identifier)):
            assignment.right = Unot(assignment.right)
        mutated_assignments = collect_assignments(mutated_ast)
    
    return mutated_ast

def operator_mutant(ast, p=1):
    """Operator Mutants (OM): Changes an expression by replacing or adding an operator."""
    operators = collect_operators(ast)
    if not operators:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_operators = collect_operators(mutated_ast)
    
    # Define operator replacement mappings
    operator_replacements = {
        Plus: [Minus, Times],
        Minus: [Plus, Times],
        Times: [Plus, Minus, Divide],
        Divide: [Times, Mod],
        And: [Or, Xor],
        Or: [And, Xor],
        LessThan: [GreaterThan, LessEq, GreaterEq],
        GreaterThan: [LessThan, LessEq, GreaterEq],
        Eq: [NotEq, LessThan, GreaterThan],
        NotEq: [Eq, LessThan, GreaterThan]
    }
    
    for _ in range(p):
        if not mutated_operators:
            break
        
        operator = random.choice(mutated_operators)
        operator_type = type(operator)
        
        if operator_type in operator_replacements:
            new_operator_class = random.choice(operator_replacements[operator_type])
            new_operator = new_operator_class(operator.left, operator.right)
            
            # Find and replace the operator in the AST
            def replace_operator(node):
                if hasattr(node, 'children'):
                    children = list(node.children())
                    for i, child in enumerate(children):
                        if child == operator:
                            children[i] = new_operator
                        else:
                            replace_operator(child)
                    # Update the node's children
                    if hasattr(node, 'left') and hasattr(node, 'right'):
                        if hasattr(node, 'left') and node.left == operator:
                            node.left = new_operator
                        if hasattr(node, 'right') and node.right == operator:
                            node.right = new_operator
        
        mutated_operators = collect_operators(mutated_ast)
    
    return mutated_ast

def variable_name_mutant(ast, p=1):
    """Change of Variable Name (CVM): Replaces a signal name with another signal name of the same type."""
    identifiers = collect_identifiers(ast)
    if len(identifiers) < 2:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    
    for _ in range(p):
        if len(identifiers) < 2:
            break
        
        old_name = random.choice(identifiers)
        new_name = random.choice([id for id in identifiers if id != old_name])
        
        def replace_identifier(node):
            if isinstance(node, Identifier) and node.name == old_name:
                node.name = new_name
            elif hasattr(node, 'children'):
                for child in node.children():
                    replace_identifier(child)
        
        replace_identifier(mutated_ast)
        identifiers = collect_identifiers(mutated_ast)
    
    return mutated_ast

def branch_operator_mutant(ast, p=1):
    """Branch Operator Mutant (BOM): Replaces an operator in the branch condition."""
    conditions = collect_conditions(ast)
    if not conditions:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_conditions = collect_conditions(mutated_ast)
    
    # Define relational operator replacements
    relational_operators = {
        LessThan: [GreaterThan, LessEq, GreaterEq, Eq, NotEq],
        GreaterThan: [LessThan, LessEq, GreaterEq, Eq, NotEq],
        LessEq: [LessThan, GreaterThan, GreaterEq, Eq, NotEq],
        GreaterEq: [LessThan, GreaterThan, LessEq, Eq, NotEq],
        Eq: [NotEq, LessThan, GreaterThan, LessEq, GreaterEq],
        NotEq: [Eq, LessThan, GreaterThan, LessEq, GreaterEq]
    }
    
    for _ in range(p):
        if not mutated_conditions:
            break
        
        condition = random.choice(mutated_conditions)
        
        # Find relational operators in the condition
        def find_and_replace_relational(node):
            if isinstance(node, tuple(relational_operators.keys())):
                operator_type = type(node)
                if operator_type in relational_operators:
                    new_operator_class = random.choice(relational_operators[operator_type])
                    return new_operator_class(node.left, node.right)
            elif hasattr(node, 'children'):
                for child in node.children():
                    result = find_and_replace_relational(child)
                    if result is not None:
                        return result
            return None
        
        new_condition = find_and_replace_relational(condition)
        if new_condition is not None:
            # Replace the condition in the if statement
            def replace_condition(node):
                if isinstance(node, IfStatement) and node.cond == condition:
                    node.cond = new_condition
                elif hasattr(node, 'children'):
                    for child in node.children():
                        replace_condition(child)
            
            replace_condition(mutated_ast)
        mutated_conditions = collect_conditions(mutated_ast)
    
    return mutated_ast

def surplus_condition_mutant(ast, p=1):
    """Surplus Conditions Mutant (SCM): Adds an additional condition to the branch condition."""
    conditions = collect_conditions(ast)
    if not conditions:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_conditions = collect_conditions(mutated_ast)
    
    for _ in range(p):
        if not mutated_conditions:
            break
        
        condition = random.choice(mutated_conditions)
        
        # Create a simple additional condition (e.g., comparing with 0 or 1)
        additional_condition = random.choice([
            Eq(condition, IntConst('0')),
            Eq(condition, IntConst('1')),
            NotEq(condition, IntConst('0')),
            NotEq(condition, IntConst('1'))
        ])
        
        # Combine with AND operator
        new_condition = And(condition, additional_condition)
        
        # Replace the condition in the if statement
        def replace_condition(node):
            if isinstance(node, IfStatement) and node.cond == condition:
                node.cond = new_condition
            elif hasattr(node, 'children'):
                for child in node.children():
                    replace_condition(child)
        
        replace_condition(mutated_ast)
        mutated_conditions = collect_conditions(mutated_ast)
    
    return mutated_ast

def missing_condition_mutant(ast, p=1):
    """Missing Condition Mutant (MCM): Removes a sub-expression in the branch condition."""
    conditions = collect_conditions(ast)
    if not conditions:
        return ast
    
    mutated_ast = copy.deepcopy(ast)
    mutated_conditions = collect_conditions(mutated_ast)
    
    for _ in range(p):
        if not mutated_conditions:
            break
        
        condition = random.choice(mutated_conditions)
        
        # If the condition is a compound expression (AND/OR), simplify it
        if isinstance(condition, (And, Or)):
            # Choose one of the operands to keep
            simplified_condition = random.choice([condition.left, condition.right])
            
            # Replace the condition in the if statement
            def replace_condition(node):
                if isinstance(node, IfStatement) and node.cond == condition:
                    node.cond = simplified_condition
                elif hasattr(node, 'children'):
                    for child in node.children():
                        replace_condition(child)
            
            replace_condition(mutated_ast)
        mutated_conditions = collect_conditions(mutated_ast)
    
    return mutated_ast

def mutate(design: str, n: int, p: int) -> List[Dict[str, str]]:
    """
    Mutates a Verilog design n times, applying p mutations per iteration.
    
    Args:
        design: Verilog code as string or path to Verilog file
        n: Number of mutants to generate
        p: Number of mutations to apply per mutant
    
    Returns:
        List of dictionaries, each containing:
        - 'mutant': mutated Verilog code
        - 'hash': SHA256 hash of the mutated code
    """
    # Parse the original design
    ast = get_pyverilog_ast(design)
    
    # Define mutation types
    mutation_types = [
        stuck_at_mutant,
        negation_mutant,
        operator_mutant,
        variable_name_mutant,
        branch_operator_mutant,
        surplus_condition_mutant,
        missing_condition_mutant
    ]
    
    mutants = []
    
    for i in range(n):
        # Create a deep copy of the original AST
        mutated_ast = copy.deepcopy(ast)
        
        # Apply p random mutations
        for _ in range(p):
            mutation_func = random.choice(mutation_types)
            # print(mutation_func)
            mutated_ast = mutation_func(mutated_ast, 1)
        
        # Convert back to Verilog code
        try:
            mutant_code = ast_to_verilog(mutated_ast)
            mutant_hash = hash_string(mutant_code)
            flag = 0
            for mut in mutants:
                if mutant_hash == mut['hash']:
                    flag = 1
                    break
            if flag:
                continue
            mutants.append({
                'content': mutant_code,
                'hash': mutant_hash
            })
        except Exception as e:
            print(f"Error generating mutant {i}: {e}")
            continue
    
    return mutants

def standardize(verilog_code: str | Path) -> str:
    verilog_code, _ = rename_modules_and_instantiations(verilog_code, obscure_names=True)
    ast = get_pyverilog_ast(verilog_code)
    output = ast_to_verilog(ast)
    return output

def test_ast_to_verilog():
    rtllm_dir = Path("./rtllm_modules").absolute()
    output_dir = Path("./rtllm_modules_pyverilog").absolute()
    error_count = 0
    for design_dir in rtllm_dir.iterdir():
        if design_dir.is_dir():
            verified_file = design_dir / f"verified_{design_dir.name}.v"
            if verified_file.exists():
                try:
                    print(f"Parsing: {verified_file}")
                    ast = get_pyverilog_ast(verified_file)
                    verilog_code = ast_to_verilog(ast)
                    output_file = output_dir / f"{design_dir.name}.v"
                    with open(output_file, 'w') as f:
                        f.write(verilog_code)
                except Exception as e:
                    error_count += 1
                    print(f"[{error_count}] Error parsing {verified_file}: {e}")
            

def test_get_pyverilog_ast():
    rtllm_dir = Path("./rtllm_modules").absolute()
    error_count = 0
    for design_dir in rtllm_dir.iterdir():
        if design_dir.is_dir():
            verified_file = design_dir / f"verified_{design_dir.name}.v"
            if verified_file.exists():
                try:
                    print(f"Parsing: {verified_file}")
                    ast = get_pyverilog_ast(verified_file)
                    # ast.show()
                except Exception as e:
                    error_count += 1
                    print(f"[{error_count}] Error parsing {verified_file}: {e}")

def test_mutation():
    """Test the mutation function with a simple design."""
    test_design = """
module test_module(
    input clk,
    input rst,
    input [7:0] a,
    input [7:0] b,
    output reg [7:0] result
);

always @(posedge clk or posedge rst) begin
    if (rst) begin
        result <= 8'b0;
    end else begin
        if (a > b) begin
            result <= a + b;
        end else begin
            result <= a - b;
        end
    end
end

endmodule
"""
    
    print("Testing mutation function...")
    mutants = mutate(test_design, 2, 8)
    
    print(f"Generated {len(mutants)} mutants:")
    for i, mutant in enumerate(mutants):
        print(f"Mutant {i+1}:")
        print(f"Hash: {mutant['hash']}")
        print("Code:")
        print(mutant['mutant'])
        print("-" * 50)

def compare_generated_and_original_hashes():
    """
    Compares all newly generated files in ./rtllm_modules_pyverilog with their originals in ./rtllm_modules
    by comparing their SHA256 hashes. Prints the result for each file.
    """
    rtllm_dir = Path("./rtllm_modules").absolute()
    pyverilog_dir = Path("./rtllm_modules_pyverilog").absolute()
    mismatch_count = 0
    total_count = 0

    for pyverilog_file in pyverilog_dir.glob("*.v"):
        # The original file is expected to be ./rtllm_modules/<design>/verified_<design>.v
        design_name = pyverilog_file.stem
        original_dir = rtllm_dir / design_name
        original_file = original_dir / f"verified_{design_name}.v"
        if not original_file.exists():
            print(f"Original file not found for {pyverilog_file.name}: {original_file}")
            continue
        total_count += 1
        hash_original = hash_file(str(original_file))
        hash_generated = hash_file(str(pyverilog_file))
        if hash_original == hash_generated:
            print(f"[OK] {pyverilog_file.name} matches original.")
        else:
            print(f"[MISMATCH] {pyverilog_file.name} does NOT match original.")
            mismatch_count += 1

    print(f"\nCompared {total_count} files. {mismatch_count} mismatches found.")

def sanity_check_hash_file():
    """
    Sanity check for compare_generated_and_original_hashes.
    For each file in ./rtllm_modules_pyverilog, compute its hash twice and ensure the hashes match.
    """
    pyverilog_dir = Path("./rtllm_modules_pyverilog").absolute()
    error_count = 0
    total_count = 0

    for pyverilog_file in pyverilog_dir.glob("*.v"):
        total_count += 1
        hash1 = hash_file(str(pyverilog_file))
        hash2 = hash_file(str(pyverilog_file))
        if hash1 == hash2:
            print(f"[OK] {pyverilog_file.name} hash is consistent.")
        else:
            print(f"[ERROR] {pyverilog_file.name} hash is NOT consistent!")
            error_count += 1

    print(f"\nSanity checked {total_count} files. {error_count} inconsistencies found.")




if __name__ == "__main__":
    # test_get_pyverilog_ast()
    test_ast_to_verilog()
    # compare_generated_and_original_hashes()
    # sanity_check_hash_file()
    # test_mutation()