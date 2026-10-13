from typing import Tuple

try:
    import tiktoken
    _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_ENCODER = None


def count_tokens(text: str) -> Tuple[int, str]:
    """
    Returns (token_count, method_label).
    Does NOT count characters as exact tokens.
    Uses tiktoken cl100k_base if available, else standard BPE heuristic (words / 0.75).
    """
    if not text:
        return 0, "exact_empty"
        
    if _TIKTOKEN_ENCODER is not None:
        try:
            return len(_TIKTOKEN_ENCODER.encode(text, disallowed_special=())), "tiktoken_cl100k_base"
        except Exception:
            pass
            
    # BPE heuristic fallback (labeled accurately)
    # Average ~3.8 - 4 chars per token in code / ~1.3 tokens per whitespace-delimited word
    words = len(text.split())
    approx = max(1, int(words * 1.35))
    return approx, "heuristic_bpe_approximation"
