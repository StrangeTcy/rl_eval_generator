from tokenizer import tokenize
from detokenizer import %%MODEL_CLASS%%

def test_basic_reconstruction():
    detok = %%MODEL_CLASS%%()
    text = "hello"
    tokens = tokenize(text)
    reconstructed = detok.detokenize(tokens)
    assert reconstructed == text
