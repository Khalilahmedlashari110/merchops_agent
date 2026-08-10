import re

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "ought",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "through", "before", "after", "above", "below", "from",
    "up", "down", "out", "off", "over", "under", "again", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "both", "each",
    "few", "more", "most", "other", "some", "no", "nor", "not", "only",
    "same", "so", "than", "too", "very", "just", "and", "but", "or",
    "as", "if", "this", "that", "these", "those", "i", "me", "my", "we",
    "our", "you", "your", "he", "she", "it", "his", "her", "its", "they",
    "their", "what", "which", "who", "whom", "hi", "hello", "dear",
    "regards", "thanks", "thank", "please", "kindly", "see", "let",
    "know", "get", "any", "much", "many", "also", "well", "into", "onto",
    "sir", "madam", "team", "hope", "write", "writing", "regarding",
    "subject", "attached", "find", "attached", "following",
}

_DATA_REQUEST_SIGNALS = [
    "?", "could you", "can you", "please provide", "let me know",
    "what is", "what are", "how many", "how much", "show me",
    "send me", "need", "require", "request", "check", "confirm",
    "provide", "update", "report", "details", "data", "information",
    "info", "figures", "numbers", "analysis", "status", "breakdown",
    "summary", "total", "count", "list", "share", "wanted",
    "looking for", "would like", "can i get", "please send",
]


def _is_data_request(subject, body):
    text = f"{subject} {body}".lower()
    return any(signal in text for signal in _DATA_REQUEST_SIGNALS)


def detect_urgency(text):
    text = (text or "").lower()
    urgent_words = [
        "urgent", "asap", "immediately", "tomorrow", "today",
        "priority", "critical", "emergency", "right away", "as soon as",
    ]
    return any(w in text for w in urgent_words)


def extract_key_terms(text):
    """Extract meaningful search terms from email text.

    Returns lowercase words/codes that could match values in any data column.
    Filters stop words and short tokens; preserves alphanumeric codes.
    """
    text = (text or "").lower()
    cleaned = re.sub(r"[^\w\s\-]", " ", text)
    words = cleaned.split()
    terms = [
        w for w in words
        if len(w) >= 2 and w not in _STOP_WORDS
    ]
    return list(dict.fromkeys(terms))  # deduplicate, preserve order


def parse_email_request(subject, body):
    full_text = f"{subject}\n\n{body}"
    is_data_req = _is_data_request(subject, body)

    return {
        "is_data_request": is_data_req,
        "is_inventory_request": is_data_req,  # backward compat for logging
        "is_urgent": detect_urgency(full_text),
        "key_terms": extract_key_terms(full_text),
        "raw_text": full_text,
    }
