import re
import unicodedata

def normalize_term(term: str) -> str:
    # Unicode NFKC
    term = unicodedata.normalize('NFKC', term)
    # trim
    term = term.strip()
    # normalize apostrophe
    term = term.replace("‘", "'").replace("’", "'").replace("`", "'")
    # collapse repeated whitespace
    term = re.sub(r'\s+', ' ', term)
    # lowercase
    term = term.lower()
    return term

def get_lexeme_type(normalized_term: str) -> str:
    if " " in normalized_term:
        return "PHRASE"
    return "WORD"
