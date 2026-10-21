"""Light-weight language detection and text normalisation (English, French, Arabic).

Good enough to pick the reply language and the speech-synthesis voice; Claude itself needs
none of this. Tunisian Darija written in Latin letters with digits ("3aslema", "7ell") is
treated as Arabic.
"""

import re
import unicodedata


def _ranges(*pairs: tuple[int, int]) -> str:
    return "".join(f"{chr(a)}-{chr(b)}" for a, b in pairs)


# Arabic blocks (letters, supplement, presentation forms A and B)
_ARABIC = re.compile(
    f"[{_ranges((0x600, 0x6FF), (0x750, 0x77F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFE))}]"
)
# Vowel marks (tashkeel), superscript alef and tatweel
_TASHKEEL = re.compile(f"[{_ranges((0x64B, 0x65F))}{chr(0x670)}{chr(0x640)}]")
_NOT_ARABIZI = re.compile(r"\bp\s?[1-9]\b|\b\d+\s?(min|mn|h|dt|tnd|d)\b")
_ARABIZI = re.compile(r"\b\w*[a-z][3579]\w*\b|\b[3579][a-z]\w*\b")

_FRENCH = set(
    """je j tu vous nous le la les des une un est et bonjour bonsoir salut merci svp stp
    place places libre libres ouvrir ouvre ouvrez reserver reservation combien prix tarif
    solde payer paiement sortir quitter pars entrer barriere voudrais veux pouvez peux mon
    ma mes quelle quel pour annuler recharger credit heure heures aide oui non il y a""".split()
)
_ENGLISH = set(
    """i you the a is are and hello hi hey thanks please spot spots free open reserve book
    booking how much price balance pay leave exit enter gate want can my what for cancel
    top up help yes no any there parking available""".split()
)


def fold(text: str) -> str:
    """Lower case, no Latin accents, Arabic letter variants unified, no vowel marks."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch) or _ARABIC.match(ch))
    text = _TASHKEEL.sub("", unicodedata.normalize("NFC", text))
    for variants, plain in (("أإآٱ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        for v in variants:
            text = text.replace(v, plain)
    return text


def detect_language(text: str, default: str = "en") -> str:
    if not text.strip():
        return default
    letters = [ch for ch in text if ch.isalpha()]
    arabic = sum(1 for ch in letters if _ARABIC.match(ch))
    if letters and arabic / len(letters) > 0.3:
        return "ar"
    folded = fold(text)
    # Spot names (P1..P4) and amounts with units ("30min", "5dt") are not Arabizi
    if _ARABIZI.search(_NOT_ARABIZI.sub(" ", folded)):
        return "ar"
    words = re.findall(r"[a-z']+", folded)
    words = [w for part in words for w in part.split("'") if w]
    fr = sum(w in _FRENCH for w in words) + 2 * bool(re.search(r"[éèêàçùôî]", text.lower()))
    en = sum(w in _ENGLISH for w in words)
    if fr > en:
        return "fr"
    if en > fr:
        return "en"
    return default
