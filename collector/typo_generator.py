"""
Typo Generator Module
=====================
Generates realistic, intentional typo permutations for a given seed keyword.

Examples:
  - "Donald Trump" -> ["Dnoald Trump", "Donlad Trump", "Donadl Trump", "Donald Turmp", "Donald Trmup"]
  - "Immigrants"   -> ["Iminmigrants", "Imimgrants", "Immgirants", "Immirgants", "Immigartns"]
"""

from typing import List


def generate_adjacent_swaps(text: str) -> List[str]:
    """
    Generate typos by swapping adjacent non-whitespace characters.
    e.g. 'Donald' -> 'Dnoald' (swap pos 1,2), 'Donlad' (swap pos 2,3), etc.
    """
    results = []
    n = len(text)
    
    for i in range(n - 1):
        # Do not swap spaces with letters or spaces with spaces
        if text[i].isspace() or text[i + 1].isspace():
            continue
        # Do not swap identical characters (e.g. 'mm' -> 'mm' produces no visible change)
        if text[i].lower() == text[i + 1].lower():
            continue
        
        # Create swap
        swapped = text[:i] + text[i + 1] + text[i] + text[i + 2:]
        if swapped != text and swapped not in results:
            results.append(swapped)
            
    return results


def generate_typos(root: str, count: int = 5) -> List[str]:
    """
    Generate up to `count` distinct typo permutations for a given root string.

    Strategy:
    1. Primary: Adjacent character swaps (e.g., pos 1 & 2 -> 'Dnoald', pos 2 & 3 -> 'Donlad').
    2. Fallback (if word is short or has many identical letters):
       - Character duplication (repeating a character)
       - Character omission (skipping a character)
    """
    root = root.strip()
    if not root:
        return []

    typos: List[str] = []

    # 1. Adjacent character swaps
    swaps = generate_adjacent_swaps(root)
    for s in swaps:
        if s not in typos:
            typos.append(s)
        if len(typos) >= count:
            return typos[:count]

    # 2. Fallback: single character duplication (e.g. 'Donald' -> 'Donnald')
    for i in range(len(root)):
        if root[i].isspace():
            continue
        dup = root[:i] + root[i] + root[i:]
        if dup not in typos and dup != root:
            typos.append(dup)
        if len(typos) >= count:
            return typos[:count]

    # 3. Fallback: single character omission (e.g. 'Donald' -> 'Doald')
    for i in range(1, len(root) - 1):
        if root[i].isspace():
            continue
        omitted = root[:i] + root[i + 1:]
        if omitted not in typos and omitted != root and len(omitted) >= 2:
            typos.append(omitted)
        if len(typos) >= count:
            return typos[:count]

    return typos[:count]


if __name__ == '__main__':
    test_keywords = ["Donald Trump", "Immigrants", "Climate Change", "AI"]
    for kw in test_keywords:
        res = generate_typos(kw, count=5)
        print(f"\nRoot: '{kw}'")
        for idx, t in enumerate(res, 1):
            print(f"  Typo {idx}: '{t}'")
