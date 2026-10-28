# Compile a compiler

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`. Return a deterministic certificate for both tasks below.

## L1 and its machine

The `bootstrap` input is
`[version, stage_count, opcode_shift, null, trusted_seed, program_depth, salt]`.
The null slot deliberately supplies no compiler implementation. Write an L1
compiler source expression. The trusted seed is executable machine code that
accepts `[source_expression, output_opcode_shift]` and returns compiled code.

An L1 expression is a tagged array. Values are signed integers or finite
sequences. Literal payloads are integers. Evaluation has one argument and a
root program; a self call evaluates that root with a new argument.

| Source | Meaning |
|---|---|
| `[0,n]` | integer literal |
| `[1]` | current argument |
| `[12]` | empty sequence |
| `[2,e]`, `[3,e]`, `[6,e]` | first element, remaining sequence, sequence length |
| `[4,a,b]` | prepend value a to sequence b |
| `[5,a,b]` | concatenate sequences |
| `[7,a,b]`, `[8,a,b]` | integer addition, subtraction |
| `[9,a,b]` | equality, returning 1 or 0 |
| `[10,c,a,b]` | evaluate c, then only a if nonzero or only b if zero |
| `[11,e]` | call the root program with argument e |
| `[13,a,b]` | evaluate a, evaluate b with that argument, then restore the caller argument |

Operands evaluate left to right. There is no modular reduction in L1. Invalid
operations such as taking the first element of an empty sequence fail.

Machine code is a sequence of `[opcode_shift + opcode, operand]` instructions.
The program counter starts at zero; the stack starts empty. Fetch increments
the counter before executing the instruction. Ordinary operands are zero.

| Opcode | Machine effect |
|---|---|
| 0 | push integer operand |
| 1 | push current argument |
| 2, 3, 6 | replace top with first, remaining sequence, or length |
| 4, 5, 7, 8, 9 | pop b then a; apply the corresponding source operation |
| 10 | pop condition; add operand to counter if condition is zero |
| 11 | unconditionally add operand to counter |
| 12 | pop new argument; save continuation and remaining stack; call this code at counter zero |
| 14 | push empty sequence |
| 15 | replace top by saved argument and use the former top as current argument |
| 16 | stack ends in saved argument, result; restore argument, leaving result |
 
Reaching exactly the end of code requires a single stack value. Return it to
the caller or finish if there is no continuation. Jumping beyond the end,
stack errors, unknown opcodes, and fuel exhaustion fail. No instruction
performs compilation.

Return `"bootstrap": [your_source, compiled_stages]`. The first submitted stage
must equal the trusted seed's output on your source. Each subsequent stage
must equal the preceding submitted compiler's output on the same source.
The sequence must have exactly `stage_count` entries. Every compiler stage
must preserve semantics on independent source/VM checks. The final compiler
is tested on additional programs containing every construct, changed
constants, conditional branches, self calls, and deeper expression trees.
These checks allow alternative compiler source and alternative correct
instruction sequences. Supported program depths are 1 through 4; larger
requests fail explicitly. A depth d requests d+1 executed compilation stages.

## Finite decoder control

The other fields describe a separate, smaller task. Its source is an integer
or `["add",left,right]`, evaluated modulo `modulus`. Compilation emits
`["push",n]` for integers and child code followed by `["add"]` for addition,
then a trailing `["halt"]`. An encoding assigns distinct ids 0,1,2 to these
three instructions. Decode the final stage using `claimed_decoder`.

Decide whether all listed `programs` preserve their source values. Revealed
inputs include `encodings`; otherwise infer the last encoding from
`calibration` source/byte pairs. The decoder control concerns only the listed
programs. Its height bound is `program_height`.

Return `"equivalent": true` when the claim holds. Otherwise return false and
`"counterexample": {"source": expression, "source_value": n, "decoded_value": m}`.
Use null for decoded_value when a well-formed source produces a decoding or
machine error. Malformed source and fuel exhaustion are not counterexamples.

The L1 bootstrap certificate is mandatory with either decoder verdict.
The visible decoder-only demonstration uses bootstrap=null and requires only
the decoder answer. Every generated grading input has a non-null bootstrap
and requires both tasks. Visible checks establish only basic API behavior.
