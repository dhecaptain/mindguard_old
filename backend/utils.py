import re

from backend.services.risk_policy import risk_label  # noqa: F401

LOW_CONTEXT_MAX_WORDS = 6
LOW_CONTEXT_MAX_CHARS = 45
LOW_CONTEXT_BENIGN_SCORE = 0.05
LOW_CONTEXT_NO_CRISIS_CAP = 0.34

BENIGN_SHORT_PATTERNS = [
    r"^(hi|hello|hey|yo|sup)\W*$",
    r"^(ok|okay|sure|yes|yeah|yep|no|nope)\W*$",
    r"^(thanks|thank you|thx|ty)\W*$",
    r"^(great|nice|cool|awesome|perfect|fine|good)\W*$",
    r"^(good morning|good afternoon|good evening|good night|gn)\W*$",
    r"^(see you|see you then|see ya|talk soon|later|bye)\W*$",
    r"^(okay no problem|no problem|all good|sounds good)\W*$",
]

BENIGN_SHORT_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in BENIGN_SHORT_PATTERNS), re.IGNORECASE
)
CRISIS_TERMS_RE = re.compile(
    r"\b(suicide|suicidal|kill myself|end my life|self harm|self-harm|hurt myself|overdose|can't go on|cant go on|die|dying)\b",
    re.IGNORECASE,
)

STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "cannot",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "don't",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "get",
    "got",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "you",
    "your",
    "yours",
}


def calibrate_risk_score(text: str, raw_score: float) -> dict:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    words = re.findall(r"[A-Za-z0-9']+", cleaned)
    low_context = (
        len(words) <= LOW_CONTEXT_MAX_WORDS or len(cleaned) <= LOW_CONTEXT_MAX_CHARS
    )
    has_crisis_terms = bool(CRISIS_TERMS_RE.search(cleaned))
    benign_short = (
        low_context and bool(BENIGN_SHORT_RE.match(cleaned)) and not has_crisis_terms
    )

    adjusted_score = float(raw_score)
    reason = ""
    if benign_short:
        adjusted_score = min(adjusted_score, LOW_CONTEXT_BENIGN_SCORE)
        reason = "Short benign conversational phrase"
    elif low_context and not has_crisis_terms:
        adjusted_score = min(adjusted_score, LOW_CONTEXT_NO_CRISIS_CAP)
        reason = "Low-context text without crisis language"
    elif low_context:
        reason = "Short text has limited context"

    return {
        "raw_risk_score": float(raw_score),
        "risk_score": adjusted_score,
        "low_context": low_context,
        "adjustment_reason": reason,
        "word_count": len(words),
        "char_count": len(cleaned),
    }


SOCIOECONOMIC_KEYWORDS = {
    "Employment": [
        "unemployed",
        "fired",
        "jobless",
        "redundant",
        "laid off",
        "no income",
        "lost my job",
        "lost the job",
        "quit my job",
        "cant find work",
        "rejected from",
        "job rejection",
        "no work",
        "out of work",
        "terminated",
        "resignation",
        "job hunting",
        "no job",
        "between jobs",
        "struggling to find work",
        "cant get hired",
        "application rejected",
    ],
    "Housing": [
        "evicted",
        "homeless",
        "eviction",
        "foreclosure",
        "repossessed",
        "cant pay rent",
        "behind on rent",
        "losing my house",
        "lost my home",
        "no place to live",
        "sleeping rough",
        "couch surfing",
        "shelter",
        "kicked out",
        "thrown out",
        "living on the street",
        "no roof",
        "cant afford rent",
        "about to lose my home",
        "housing crisis",
    ],
    "Financial": [
        "broke",
        "debt",
        "bankrupt",
        "bankruptcy",
        "no money",
        "penniless",
        "cant afford",
        "struggling financially",
        "poverty",
        "poor",
        "destitute",
        "bills",
        "overdue",
        "repossession",
        "bailiff",
        "loan shark",
        "in debt",
        "maxed out",
        "credit card debt",
        "financial crisis",
        "cant make ends meet",
        "running out of money",
        "nothing in my account",
        "overdraft",
    ],
    "Relationships": [
        "divorce",
        "divorced",
        "breakup",
        "broke up",
        "separated",
        "cheated on",
        "alone",
        "abandoned",
        "nobody cares",
        "no one cares",
        "nobody loves me",
        "lost my partner",
        "widowed",
        "widower",
        "grief",
        "bereaved",
        "heartbroken",
        "relationship ended",
        "left me",
        "walked out",
        "abusive relationship",
        "domestic violence",
        "isolation",
        "no friends",
        "lost everyone",
        "nobody understands",
        "feel invisible",
        "completely alone",
    ],
    "Health": [
        "chronic pain",
        "terminal",
        "cancer",
        "diagnosis",
        "incurable",
        "disabled",
        "mental illness",
        "depression",
        "anxiety",
        "bipolar",
        "schizophrenia",
        "addiction",
        "addicted",
        "alcoholic",
        "alcohol abuse",
        "drug abuse",
        "overdose",
        "hospitalized",
        "hospital",
        "surgery",
        "treatment failed",
        "no health insurance",
        "cant afford medication",
        "sick",
        "illness",
        "eating disorder",
        "self harm",
        "self-harm",
        "cutting",
        "suicidal thoughts",
    ],
    "Social & Education": [
        "bullied",
        "bullying",
        "expelled",
        "suspended",
        "failed my exams",
        "dropped out",
        "academic failure",
        "social outcast",
        "no friends",
        "excluded",
        "isolated",
        "discriminated",
        "racism",
        "harassment",
        "abused",
        "victim",
        "trauma",
        "ptsd",
        "refugee",
        "asylum seeker",
    ],
}

RESOURCES = {
    "Kenya": [
        {
            "name": "Befrienders Kenya",
            "contact": "+254 722 178 177",
            "type": "Crisis line",
        },
        {"name": "Kenya Red Cross", "contact": "1199", "type": "Emergency"},
        {
            "name": "Chiromo Hospital Group",
            "contact": "+254 20 4291000",
            "type": "Mental health",
        },
        {
            "name": "Mathare Hospital MH Unit",
            "contact": "+254 20 2012185",
            "type": "Hospital",
        },
    ],
    "USA (National)": [
        {
            "name": "988 Suicide & Crisis Lifeline",
            "contact": "Call/text 988",
            "type": "Crisis line",
        },
        {
            "name": "Crisis Text Line",
            "contact": "Text HOME to 741741",
            "type": "Text-based",
        },
        {"name": "NAMI Helpline", "contact": "1-800-950-6264", "type": "Mental health"},
        {
            "name": "SAMHSA Helpline",
            "contact": "1-800-662-4357",
            "type": "Substance abuse & mental health",
        },
        {
            "name": "Veterans Crisis Line",
            "contact": "Call 988, press 1",
            "type": "Veterans",
        },
        {
            "name": "Trevor Project (LGBTQ+ youth)",
            "contact": "1-866-488-7386",
            "type": "Youth crisis",
        },
    ],
    "UK": [
        {"name": "Samaritans", "contact": "116 123", "type": "Crisis line"},
        {
            "name": "PAPYRUS (under 35s)",
            "contact": "0800 068 4141",
            "type": "Youth crisis",
        },
        {"name": "MIND", "contact": "0300 123 3393", "type": "Mental health"},
        {"name": "Shout", "contact": "Text SHOUT to 85258", "type": "Text-based"},
    ],
    "Australia": [
        {"name": "Lifeline", "contact": "13 11 14", "type": "Crisis line"},
        {"name": "Beyond Blue", "contact": "1300 22 4636", "type": "Mental health"},
        {"name": "Kids Helpline", "contact": "1800 55 1800", "type": "Youth (5-25)"},
    ],
    "Canada": [
        {
            "name": "Talk Suicide Canada",
            "contact": "1-833-456-4566",
            "type": "Crisis line",
        },
        {
            "name": "Crisis Text Line CA",
            "contact": "Text HOME to 686868",
            "type": "Text-based",
        },
        {"name": "Kids Help Phone", "contact": "1-800-668-6868", "type": "Youth"},
    ],
    "International": [
        {
            "name": "Find A Helpline",
            "contact": "findahelpline.com",
            "type": "Global directory",
        },
        {
            "name": "IASP",
            "contact": "https://www.iasp.info/resources/Crisis_Centres/",
            "type": "Global directory",
        },
        {
            "name": "Befrienders Worldwide",
            "contact": "https://www.befrienders.org",
            "type": "Global directory",
        },
    ],
}

US_STATE_RESOURCES = {
    "Alabama": [
        {
            "name": "Alabama Crisis Line",
            "contact": "1-800-273-8255",
            "type": "Crisis line",
        },
        {
            "name": "AltaPointe Health",
            "contact": "1-800-530-3727",
            "type": "Mental health",
        },
    ],
    "Alaska": [
        {
            "name": "Careline Crisis Intervention",
            "contact": "1-877-266-4357",
            "type": "Crisis line",
        },
        {
            "name": "Alaska Mental Health Trust",
            "contact": "907-274-7428",
            "type": "Mental health",
        },
    ],
    "Arizona": [
        {"name": "AZ Crisis Line", "contact": "1-800-631-1314", "type": "Crisis line"},
        {
            "name": "Crisis Response Network",
            "contact": "602-222-9444",
            "type": "Crisis line",
        },
    ],
    "Arkansas": [
        {"name": "AR Crisis Line", "contact": "1-888-274-7472", "type": "Crisis line"},
        {
            "name": "UAMS Psychiatric Research",
            "contact": "501-526-8100",
            "type": "Mental health",
        },
    ],
    "California": [
        {
            "name": "CA Suicide Prevention Hotline",
            "contact": "1-800-784-2433",
            "type": "Crisis line",
        },
        {
            "name": "Didi Hirsch Mental Health",
            "contact": "800-854-7771",
            "type": "Crisis line",
        },
    ],
    "Colorado": [
        {
            "name": "CO Crisis Services",
            "contact": "1-844-493-8255",
            "type": "Crisis line",
        },
        {
            "name": "Mental Health Center of Denver",
            "contact": "303-504-6500",
            "type": "Mental health",
        },
    ],
    "Connecticut": [
        {
            "name": "CT Behavioral Health",
            "contact": "1-800-467-3135",
            "type": "Crisis line",
        },
        {"name": "DMHAS Crisis Line", "contact": "211", "type": "Crisis line"},
    ],
    "Delaware": [
        {
            "name": "DE Crisis Hotline",
            "contact": "1-800-652-2929",
            "type": "Crisis line",
        },
        {
            "name": "Connections Community Support",
            "contact": "302-656-8308",
            "type": "Mental health",
        },
    ],
    "Florida": [
        {"name": "FL Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Crisis Center of Tampa Bay",
            "contact": "813-234-1234",
            "type": "Crisis line",
        },
    ],
    "Georgia": [
        {
            "name": "GA Crisis & Access Line",
            "contact": "1-800-715-4225",
            "type": "Crisis line",
        },
        {
            "name": "Behavioral Health Link",
            "contact": "800-715-4225",
            "type": "Crisis line",
        },
    ],
    "Hawaii": [
        {"name": "HI Crisis Line", "contact": "1-800-753-6879", "type": "Crisis line"},
        {
            "name": "AMHD Crisis Line",
            "contact": "808-832-3100",
            "type": "Mental health",
        },
    ],
    "Idaho": [
        {"name": "ID Careline", "contact": "211", "type": "Crisis line"},
        {"name": "Optum Idaho", "contact": "1-855-202-0973", "type": "Mental health"},
    ],
    "Illinois": [
        {"name": "IL Crisis Line", "contact": "1-800-345-9049", "type": "Crisis line"},
        {"name": "NAMI Illinois", "contact": "1-800-826-4890", "type": "Mental health"},
    ],
    "Indiana": [
        {"name": "IN Crisis Line", "contact": "1-800-662-3445", "type": "Crisis line"},
        {
            "name": "LifeLine Indiana",
            "contact": "1-800-273-8255",
            "type": "Crisis line",
        },
    ],
    "Iowa": [
        {"name": "IA Warm Line", "contact": "1-800-777-3957", "type": "Crisis line"},
        {
            "name": "MHDS Crisis Line",
            "contact": "1-855-581-8111",
            "type": "Crisis line",
        },
    ],
    "Kansas": [
        {"name": "KS Crisis Line", "contact": "1-888-363-2287", "type": "Crisis line"},
        {"name": "COMCARE Crisis", "contact": "316-660-7500", "type": "Crisis line"},
    ],
    "Kentucky": [
        {"name": "KY Crisis Line", "contact": "1-800-221-0446", "type": "Crisis line"},
        {"name": "Communicare", "contact": "270-769-1304", "type": "Mental health"},
    ],
    "Louisiana": [
        {"name": "LA Crisis Line", "contact": "1-800-259-0570", "type": "Crisis line"},
        {"name": "NAMI Louisiana", "contact": "504-835-7633", "type": "Mental health"},
    ],
    "Maine": [
        {"name": "ME Crisis Line", "contact": "1-888-568-1112", "type": "Crisis line"},
        {"name": "NAMI Maine", "contact": "1-800-464-5767", "type": "Mental health"},
    ],
    "Maryland": [
        {
            "name": "MD Crisis Hotline",
            "contact": "1-800-422-0009",
            "type": "Crisis line",
        },
        {"name": "Crisis Link", "contact": "703-527-4077", "type": "Crisis line"},
    ],
    "Massachusetts": [
        {"name": "MA Samaritans", "contact": "1-877-870-4673", "type": "Crisis line"},
        {
            "name": "NAMI Massachusetts",
            "contact": "800-370-9085",
            "type": "Mental health",
        },
    ],
    "Michigan": [
        {
            "name": "MI Crisis Text Line",
            "contact": "Text HOME to 741741",
            "type": "Text-based",
        },
        {"name": "NAMI Michigan", "contact": "517-485-4049", "type": "Mental health"},
    ],
    "Minnesota": [
        {"name": "MN Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Canvas Health Crisis",
            "contact": "651-777-5222",
            "type": "Crisis line",
        },
    ],
    "Mississippi": [
        {"name": "MS Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "NAMI Mississippi",
            "contact": "601-899-9227",
            "type": "Mental health",
        },
    ],
    "Missouri": [
        {"name": "MO Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Places for People",
            "contact": "314-622-4600",
            "type": "Mental health",
        },
    ],
    "Montana": [
        {"name": "MT Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "AWARE Inc", "contact": "406-443-1010", "type": "Mental health"},
    ],
    "Nebraska": [
        {"name": "NE Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Heartland Family Service",
            "contact": "402-553-3000",
            "type": "Mental health",
        },
    ],
    "Nevada": [
        {"name": "NV Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Crisis Support Services of NV",
            "contact": "775-784-8090",
            "type": "Crisis line",
        },
    ],
    "New Hampshire": [
        {"name": "NH Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "NAMI New Hampshire",
            "contact": "1-800-242-6264",
            "type": "Mental health",
        },
    ],
    "New Jersey": [
        {"name": "NJ Hopeline", "contact": "1-855-654-6735", "type": "Crisis line"},
        {
            "name": "NJ Mental Health Cares",
            "contact": "1-866-202-4357",
            "type": "Mental health",
        },
    ],
    "New Mexico": [
        {"name": "NM Crisis Line", "contact": "1-855-662-7474", "type": "Crisis line"},
        {"name": "NAMI New Mexico", "contact": "505-260-0154", "type": "Mental health"},
    ],
    "New York": [
        {
            "name": "NY OMH Crisis Line",
            "contact": "1-800-273-8255",
            "type": "Crisis line",
        },
        {"name": "NYC Well", "contact": "1-888-692-9355", "type": "Crisis line"},
        {"name": "NAMI NYC", "contact": "212-684-3264", "type": "Mental health"},
    ],
    "North Carolina": [
        {"name": "NC Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Trillium Health Resources",
            "contact": "1-877-685-2415",
            "type": "Mental health",
        },
    ],
    "North Dakota": [
        {"name": "ND Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "FirstStep Recovery",
            "contact": "701-255-3692",
            "type": "Mental health",
        },
    ],
    "Ohio": [
        {"name": "OH Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Crisis Intervention Center",
            "contact": "614-276-2273",
            "type": "Crisis line",
        },
    ],
    "Oklahoma": [
        {"name": "OK Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "NAMI Oklahoma", "contact": "405-230-1900", "type": "Mental health"},
    ],
    "Oregon": [
        {
            "name": "OR Lines for Life",
            "contact": "1-800-273-8255",
            "type": "Crisis line",
        },
        {
            "name": "Oregon Crisis Network",
            "contact": "503-652-4100",
            "type": "Crisis line",
        },
    ],
    "Pennsylvania": [
        {"name": "PA Crisis Line", "contact": "1-855-284-2494", "type": "Crisis line"},
        {
            "name": "NAMI Pennsylvania",
            "contact": "1-800-223-0500",
            "type": "Mental health",
        },
    ],
    "Rhode Island": [
        {"name": "RI Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Gateway Healthcare",
            "contact": "401-724-8400",
            "type": "Mental health",
        },
    ],
    "South Carolina": [
        {"name": "SC Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "NAMI South Carolina",
            "contact": "803-733-9592",
            "type": "Mental health",
        },
    ],
    "South Dakota": [
        {"name": "SD Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Volunteers of America Dakotas",
            "contact": "605-339-1783",
            "type": "Mental health",
        },
    ],
    "Tennessee": [
        {"name": "TN Crisis Line", "contact": "1-855-274-7471", "type": "Crisis line"},
        {"name": "NAMI Tennessee", "contact": "615-361-6608", "type": "Mental health"},
    ],
    "Texas": [
        {"name": "TX Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "Texas 211", "contact": "211", "type": "Local resources"},
        {"name": "NAMI Texas", "contact": "512-693-2000", "type": "Mental health"},
    ],
    "Utah": [
        {"name": "UT Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Utah Crisis Services",
            "contact": "801-587-3000",
            "type": "Crisis line",
        },
    ],
    "Vermont": [
        {"name": "VT Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "Howard Center", "contact": "802-488-6000", "type": "Mental health"},
    ],
    "Virginia": [
        {"name": "VA Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "NAMI Virginia", "contact": "888-486-8264", "type": "Mental health"},
    ],
    "Washington": [
        {"name": "WA Crisis Line", "contact": "1-866-427-4747", "type": "Crisis line"},
        {
            "name": "Crisis Connections",
            "contact": "866-427-4747",
            "type": "Crisis line",
        },
    ],
    "West Virginia": [
        {"name": "WV Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "NAMI West Virginia",
            "contact": "304-342-0497",
            "type": "Mental health",
        },
    ],
    "Wisconsin": [
        {"name": "WI Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {
            "name": "Journey Mental Health",
            "contact": "608-280-2600",
            "type": "Mental health",
        },
    ],
    "Wyoming": [
        {"name": "WY Crisis Line", "contact": "1-800-273-8255", "type": "Crisis line"},
        {"name": "NAMI Wyoming", "contact": "307-432-0837", "type": "Mental health"},
    ],
    "Washington D.C.": [
        {"name": "DC Crisis Line", "contact": "1-888-793-4357", "type": "Crisis line"},
        {
            "name": "DBH Access Helpline",
            "contact": "888-793-4357",
            "type": "Mental health",
        },
    ],
}

TEAM_MEMBERS = [
    {
        "name": "Diana Opiyo",
        "role": "Lead Developer & ML Architect",
        "bio": "Leads the MindGuard research workflow, model comparison, training pipeline, and deployment readiness for mental health risk screening.",
        "image": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=900&q=80",
        "linkedin": "https://www.linkedin.com/in/diana-opiyo/",
    },
    {
        "name": "Andrew Njiyo",
        "role": "Technical Lead",
        "bio": "Guides risk-tier language, crisis-resource framing, and responsible use so model output stays grounded in human support.",
        "image": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=900&q=80",
        "linkedin": "https://www.linkedin.com/in/andrew-njiyo/",
    },
    {
        "name": "Dr. Suhila Sawesi",
        "role": "Health Informatics Advisor",
        "bio": "Reviews dataset consistency, checks label quality, and tracks model performance across text, platform exports, and OCR inputs.",
        "image": "https://images.unsplash.com/photo-1508214751196-bcfd4ca60f91?auto=format&fit=crop&w=900&q=80",
        "linkedin": "https://www.linkedin.com/in/suhila-sawesi/",
    },
    {
        "name": "Bushra Rashrash",
        "role": "Bioinformatics Specialist",
        "bio": "Turns model workflows into practical analysis tools with accessible layouts, clearer actions, and safer reporting touchpoints.",
        "image": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=900&q=80",
        "linkedin": "https://www.linkedin.com/in/bushra-rashrash/",
    },
]


def clean_text(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"http\S+|www\S+", "", text)
    text = re.sub(r"[^a-z\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(w for w in text.split() if w not in STOPWORDS and len(w) > 2)


def detect_socioeconomic(posts: list) -> dict:
    result = {}
    for cat, kws in SOCIOECONOMIC_KEYWORDS.items():
        found = []
        for kw in kws:
            kw_clean = re.sub(r"[^a-z0-9\s]", " ", kw.lower()).strip()
            if not kw_clean:
                continue
            for post in posts:
                raw = re.sub(r"['\u2019\u2018`]", "", post["text"].lower())
                raw = re.sub(r"[^a-z0-9\s]", " ", raw)
                raw = re.sub(r"\s+", " ", raw)
                if kw_clean in raw:
                    idx = raw.find(kw_clean)
                    start = max(0, idx - 40)
                    end = min(len(raw), idx + len(kw_clean) + 40)
                    snippet = "..." + raw[start:end].strip() + "..."
                    found.append({"keyword": kw, "snippet": snippet})
                    break
        result[cat] = found
    return result
