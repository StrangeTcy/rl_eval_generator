# Transport around two loops

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

The input contains a finite `domain`, named maps, and two loops `paths.path_a`
and `paths.path_b` based at the same vertex. Apply names in listed order.
`transport_edges` gives the corresponding source vertex, target vertex, and
map name for every edge. Each loop has its own interior vertices.
`cycle` is path_a. Module names describe presentation, not extra constraints.

Map families:
- multiplicative: y = q*x modulo prime p, on nonzero field elements;
- affine: y = a*x+b modulo prime p, with nonzero a;
- permutation: y = image[x], on 0 through n-1. Here `modulus` is n and need
  not be prime.

Revealed and explicit inputs supply `maps`. Explicit inputs also supply the
expanded path_a factors. Inferred inputs supply sufficient `calibration`
pairs to recover every map. For affine maps two distinct input probes
determine a and b; permutation probes cover the domain.

A global section exists exactly when a base state returns to itself along
**both** loops. Equality of the two complete transport maps is a different
question. Call the two-loop connection `flat` only when both loop maps are
identity maps. Equal nonidentity loop maps are `curved`; curved transport can
still have compatible base states.

Return:
```json
{
  "status": "sat",
  "state": 0,
  "maps": {},
  "path_consistent": true,
  "transport": [ [[0,0]], [[0,0]], "flat" ],
  "sections": [0]
}
```
The numbers and empty maps above illustrate the shape, not a solution.
`transport` must contain the full [input,output] table for each loop and its
flat/curved classification. Table rows may be reordered.
`sections` must list every compatible base state exactly once.
`path_consistent` says whether the two complete maps agree.
For sat, `state` is any member of sections. For unsat, sections is empty and
state can be omitted. Inferred answers must supply all calibrated maps,
including on unsat inputs. All these conditions are mandatory.
