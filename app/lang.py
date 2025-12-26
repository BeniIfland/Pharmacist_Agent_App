# is used to detect user language and allow bilinguality
# if user language isn't Hebrew it is asumed to be english
# An extension could be to notify the user that the agent only speaks Hebrew or English if they try to speak another language

def detect_lang(text: str) -> str:
    """
    Heuristically  (based on chars' encoding) determines if user language is hebrew,
    otherwise assumes its english.
    
    :param text: user message
    :type text: str
    :return: he or en i.e., determined language
    :rtype: str
    """
    # simlistic but effective: any Hebrew character => Hebrew
    return "he" if any("\u0590" <= ch <= "\u05FF" for ch in text) else "en"
