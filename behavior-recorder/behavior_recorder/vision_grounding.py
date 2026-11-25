"""Category token alignment shared by slow and fast text tokenizers."""
from .core import require


def category_token_indices(input_ids, category_ids):
    """Locate each complete category token sequence exactly once in the prompt."""
    require(isinstance(input_ids, list) and input_ids
            and all(type(value) is int and value >= 0 for value in input_ids), "invalid input token ids")
    require(isinstance(category_ids, dict) and category_ids, "category token ids required")
    positions, occupied = {}, set()
    for category, tokens in category_ids.items():
        require(isinstance(category, str) and category.strip(), "invalid category")
        require(isinstance(tokens, list) and tokens
                and all(type(value) is int and value >= 0 for value in tokens), "invalid category token ids")
        starts = [i for i in range(len(input_ids) - len(tokens) + 1)
                  if input_ids[i:i + len(tokens)] == tokens]
        require(len(starts) == 1, "category tokens must occur exactly once")
        indices = list(range(starts[0], starts[0] + len(tokens)))
        require(not occupied.intersection(indices), "category token spans overlap")
        positions[category] = indices
        occupied.update(indices)
    return positions
