import re
import hashlib

# Extended Greek symbol map (lower + upper case)
GREEK_SYMBOLS = {
    'α': 'alpha', 'Α': 'alpha',
    'β': 'beta',  'Β': 'beta',
    'γ': 'gamma', 'Γ': 'gamma',
    'δ': 'delta', 'Δ': 'delta',
    'ε': 'epsilon', 'Ε': 'epsilon',
    'ζ': 'zeta', 'Ζ': 'zeta',
    'η': 'eta', 'Η': 'eta',
    'θ': 'theta', 'Θ': 'theta',
    'ι': 'iota', 'Ι': 'iota',
    'κ': 'kappa', 'Κ': 'kappa',
    'λ': 'lambda', 'Λ': 'lambda',
    'μ': 'mu', 'Μ': 'mu',
    'ν': 'nu', 'Ν': 'nu',
    'ξ': 'xi', 'Ξ': 'xi',
    'ο': 'omicron', 'Ο': 'omicron',
    'π': 'pi', 'Π': 'pi',
    'ρ': 'rho', 'Ρ': 'rho',
    'σ': 'sigma', 'Σ': 'sigma',
    'τ': 'tau', 'Τ': 'tau',
    'υ': 'upsilon', 'Υ': 'upsilon',
    'φ': 'phi', 'Φ': 'phi',
    'χ': 'chi', 'Χ': 'chi',
    'ψ': 'psi', 'Ψ': 'psi',
    'ω': 'omega', 'Ω': 'omega'
}

# Escaped Unicode forms (\u03b1, \u0391, etc.)
GREEK_ESCAPED = {
    f"\\u{ord(symbol):04x}": word
    for symbol, word in GREEK_SYMBOLS.items()
}

# Precompile regex for performance
NON_ALPHANUMERIC = re.compile(r'[^a-z0-9]+')

def normalize_chemical_name(name: str) -> str:
    """
    Universal chemical name normalizer.
    Safe for:
    - Greek symbols (α, β, etc.)
    - Escaped unicode (\\u03b1)
    - Different formatting styles
    """

    if not name:
        return ""

    # Convert to string and lowercase
    name = str(name).strip().lower()

    # Replace escaped unicode first
    for esc, word in GREEK_ESCAPED.items():
        name = name.replace(esc.lower(), word)

    # Replace actual Greek symbols
    for symbol, word in GREEK_SYMBOLS.items():
        name = name.replace(symbol.lower(), word)

    # Normalize common separators explicitly
    name = name.replace('-', '')
    name = name.replace(' ', '')

    # Remove any remaining special characters
    name = NON_ALPHANUMERIC.sub('', name)

    return name


def generate_canonical_key(name: str) -> str:
    """
    Generates a deterministic unique key for a chemical name.
    Uses SHA-256 hashing.
    """
    normalized = normalize_chemical_name(name)

    if not normalized:
        return ""

    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()