# app.py
import html
import re
from typing import Dict, Optional, Tuple

import requests
import streamlit as st
from bs4 import BeautifulSoup

# -----------------------------
# Configuration
# -----------------------------

st.set_page_config(
    page_title="SAFE CINEMA HUB",
    page_icon="🎬",
    layout="wide",
)

OMDB_URL = "https://www.omdbapi.com/"
IMDB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/123.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# -----------------------------
# Styling
# -----------------------------

st.markdown(
    """
    <style>
        .main {
            max-width: 1200px;
            margin: auto;
        }

        .badge {
            display: inline-block;
            padding: 0.55rem 1rem;
            border-radius: 999px;
            color: white;
            font-size: 1.1rem;
            font-weight: 700;
            margin: 0.4rem 0 1rem 0;
        }

        .kids {
            background-color: #159957;
        }

        .family {
            background-color: #e09f00;
        }

        .adults {
            background-color: #c0392b;
        }

        .category-card {
            border: 1px solid rgba(128, 128, 128, 0.35);
            border-radius: 12px;
            padding: 1rem;
            margin-bottom: 0.8rem;
            min-height: 150px;
        }

        .category-title {
            font-weight: 700;
            font-size: 1.08rem;
            margin-bottom: 0.45rem;
        }

        .severity {
            font-weight: 700;
            margin-bottom: 0.4rem;
        }

        .muted {
            color: #777;
            font-size: 0.9rem;
        }

        .summary {
            border-left: 5px solid #4c78a8;
            background: rgba(76, 120, 168, 0.10);
            padding: 1rem;
            border-radius: 6px;
            margin: 1rem 0;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# API and scraping functions
# -----------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_movie(title: str, year: int, api_key: str) -> Dict:
    """Fetch movie metadata from OMDb."""
    params = {
        "apikey": api_key,
        "t": title,
        "y": year,
        "type": "movie",
        "plot": "full",
    }

    response = requests.get(OMDB_URL, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if data.get("Response") == "False":
        raise ValueError(data.get("Error", "Movie not found."))

    return data

def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def extract_severity(text: str) -> str:
    """
    Finds common IMDb severity labels inside a block of text.
    """
    text_lower = text.lower()

    severities = [
        "severe",
        "moderate",
        "mild",
        "none",
        "unknown",
    ]

    for severity in severities:
        if re.search(rf"\b{re.escape(severity)}\b", text_lower):
            return severity.title()

    return "Not rated"

def parse_imdb_category(container) -> Tuple[str, str]:
    """
    Attempts to extract a severity label and description from an IMDb
    Parents Guide category element.
    """
    text = clean_text(container.get_text(" ", strip=True))

    severity = extract_severity(text)

    # Remove common severity words from the description.
    description = re.sub(
        r"\b(severe|moderate|mild|none|unknown)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    description = clean_text(description)

    # Prevent very long page fragments from overwhelming the interface.
    if len(description) > 1400:
        description = description[:1400].rstrip() + "..."

    return severity, description

@st.cache_data(show_spinner=False, ttl=3600)
def scrape_parents_guide(imdb_id: str) -> Dict[str, Dict[str, str]]:
    """
    Scrape the IMDb Parents Guide page.

    IMDb's markup can change. Multiple selectors are used as fallbacks.
    """
    url = f"https://www.imdb.com/title/{imdb_id}/parentalguide/"
    result = {
        "Sex & Nudity": {
            "severity": "Not available",
            "description": "",
        },
        "Violence & Gore": {
            "severity": "Not available",
            "description": "",
        },
        "Profanity": {
            "severity": "Not available",
            "description": "",
        },
        "Alcohol/Drugs": {
            "severity": "Not available",
            "description": "",
        },
        "Frightening Scenes": {
            "severity": "Not available",
            "description": "",
        },
    }

    response = requests.get(
        url,
        headers=IMDB_HEADERS,
        timeout=25,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    category_aliases = {
        "Sex & Nudity": [
            "sex & nudity",
            "sex and nudity",
            "sex nudity",
        ],
        "Violence & Gore": [
            "violence & gore",
            "violence and gore",
            "violence gore",
        ],
        "Profanity": [
            "profanity",
            "language",
        ],
        "Alcohol/Drugs": [
            "alcohol/drugs",
            "alcohol and drugs",
            "alcohol drugs",
        ],
        "Frightening Scenes": [
            "frightening scenes",
            "frightening",
        ],
    }

    # Strategy 1: Find headings containing category names and inspect
    # their nearest useful parent container.
    headings = soup.find_all(
        ["h1", "h2", "h3", "h4", "span", "div"]
    )

    found = set()

    for heading in headings:
        heading_text = clean_text(heading.get_text(" ", strip=True)).lower()

        matched_category: Optional[str] = None
        for category, aliases in category_aliases.items():
            if any(alias in heading_text for alias in aliases):
                matched_category = category
                break

        if not matched_category or matched_category in found:
            continue

        candidate = heading

        # Walk up a few levels looking for a meaningful content block.
        for _ in range(4):
            if candidate.parent is None:
                break
            candidate = candidate.parent
            candidate_text = clean_text(
                candidate.get_text(" ", strip=True)
            )

            if len(candidate_text) >= 30:
                break

        severity, description = parse_imdb_category(candidate)

        if severity != "Not rated" or description:
            result[matched_category] = {
                "severity": severity,
                "description": description,
            }
            found.add(matched_category)

    # Strategy 2: Fallback to text scanning around category headings.
    page_text = clean_text(soup.get_text(" ", strip=True))

    for category, aliases in category_aliases.items():
        if category in found:
            continue

        start = -1
        matched_alias = ""

        for alias in aliases:
            index = page_text.lower().find(alias)
            if index >= 0 and (start == -1 or index < start):
                start = index
                matched_alias = alias

        if start >= 0:
            snippet = page_text[start:start + 1200]
            severity = extract_severity(snippet)
            description = clean_text(
                re.sub(
                    re.escape(matched_alias),
                    "",
                    snippet,
                    flags=re.IGNORECASE,
                )
            )

            result[category] = {
                "severity": severity,
                "description": description,
            }

    return result

# -----------------------------
# Classification engine
# -----------------------------

SEVERITY_POINTS = {
    "not available": 0,
    "not rated": 0,
    "unknown": 0,
    "none": 0,
    "mild": 1,
    "moderate": 3,
    "severe": 6,
}

CATEGORY_WEIGHTS = {
    "Sex & Nudity": 1.5,
    "Violence & Gore": 1.0,
    "Profanity": 0.8,
    "Alcohol/Drugs": 1.0,
    "Frightening Scenes": 1.0,
}

def classify_movie(
    categories: Dict[str, Dict[str, str]],
    imdb_rating: str,
    certificate: str,
) -> Tuple[str, int, str]:
    """
    Heuristic classification.

    This is a parental screening aid, not an official age rating.
    """
    score = 0.0
    severe_categories = []
    moderate_categories = []

    for category, details in categories.items():
        severity = details.get("severity", "Not available").lower()
        points = SEVERITY_POINTS.get(severity, 0)
        weighted_points = points * CATEGORY_WEIGHTS.get(category, 1.0)
        score += weighted_points

        if severity == "severe":
            severe_categories.append(category)
        elif severity == "moderate":
            moderate_categories.append(category)

    certificate_lower = (certificate or "").lower()

    # Use OMDb's certificate as a supporting signal, not the only signal.
    if any(value in certificate_lower for value in ["r", "nc-17", "18"]):
        score += 3
    elif any(value in certificate_lower for value in ["pg-13", "12a", "15"]):
        score += 1.5

    if severe_categories or score >= 8:
        verdict = "Adults Only"
        summary = (
            "This title contains one or more strong advisory signals. "
            "Parents should review the detailed categories before allowing "
            "children or younger teens to watch."
        )
    elif score >= 3.5 or moderate_categories:
        verdict = "Family Friendly"
        summary = (
            "This title may be suitable for families with supervision, but "
            "some content could be unsuitable for younger children. Review "
            "the highlighted categories and the child's sensitivity."
        )
    else:
        verdict = "Kids Safe"
        summary = (
            "The available advisory information indicates relatively low "
            "content concerns. Parents should still consider the child's age "
            "and individual sensitivities."
        )

    return verdict, round(score), summary

def badge_class(verdict: str) -> str:
    return {
        "Kids Safe": "kids",
        "Family Friendly": "family",
        "Adults Only": "adults",
    }.get(verdict, "family")

# -----------------------------
# Streamlit interface
# -----------------------------

st.title("🎬 Movie Parent Guide")
st.caption(
    "Look up a movie and review parental-advisory information before watching."
)

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input(
        "OMDb API key",
        type="password",
        help=(
            "Store this as OMDB_API_KEY in Streamlit secrets, or enter it "
            "temporarily here."
        ),
    )

    if not api_key:
        try:
            api_key = st.secrets["OMDB_API_KEY"]
        except Exception:
            api_key = ""

    st.info(
        "The classification is a heuristic screening aid. It is not an "
        "official age rating and should not replace parental judgment."
    )

with st.form("movie_form"):
    col1, col2 = st.columns([3, 1])

    with col1:
        movie_title = st.text_input(
            "Movie title",
            placeholder="Example: Finding Nemo",
        )

    with col2:
        release_year = st.number_input(
            "Release year",
            min_value=1888,
            max_value=2100,
            value=2020,
            step=1,
        )

    submitted = st.form_submit_button(
        "Check movie",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not api_key:
        st.error(
            "Enter an OMDb API key or configure OMDB_API_KEY in Streamlit secrets."
        )
        st.stop()

    if not movie_title.strip():
        st.error("Enter a movie title.")
        st.stop()

    with st.spinner("Fetching movie details and parental guidance..."):
        try:
            movie = fetch_movie(
                movie_title.strip(),
                int(release_year),
                api_key,
            )
        except requests.RequestException as exc:
            st.error(f"Network error while contacting OMDb: {exc}")
            st.stop()
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        imdb_id = movie.get("imdbID")

        if not imdb_id:
            st.error("OMDb did not return an IMDb ID for this movie.")
            st.stop()

        try:
            guide = scrape_parents_guide(imdb_id)
            guide_available = True
        except requests.RequestException:
            guide = {
                category: {
                    "severity": "Unavailable",
                    "description": (
                        "IMDb Parents Guide could not be retrieved. "
                        "Try opening the guide manually."
                    ),
                }
                for category in [
                    "Sex & Nudity",
                    "Violence & Gore",
                    "Profanity",
                    "Alcohol/Drugs",
                    "Frightening Scenes",
                ]
            }
            guide_available = False
        except Exception:
            guide = {
                category: {
                    "severity": "Unavailable",
                    "description": "Could not parse this IMDb Parents Guide.",
                }
                for category in [
                    "Sex & Nudity",
                    "Violence & Gore",
                    "Profanity",
                    "Alcohol/Drugs",
                    "Frightening Scenes",
                ]
            }
            guide_available = False

    verdict, score, parent_summary = classify_movie(
        guide,
        movie.get("imdbRating", ""),
        movie.get("Rated", ""),
    )

    # Movie header
    poster_col, details_col = st.columns([1, 2])

    with poster_col:
        poster = movie.get("Poster", "")
        if poster and poster != "N/A":
            st.image(poster, use_container_width=True)
        else:
            st.info("Poster unavailable.")

    with details_col:
        st.subheader(f"{movie.get('Title', movie_title)} ({movie.get('Year', release_year)})")

        st.markdown(
            f'<div class="badge {badge_class(verdict)}">{verdict}</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="summary"><strong>Parent summary:</strong> '
            f'{parent_summary}</div>',
            unsafe_allow_html=True,
        )

        info_col1, info_col2 = st.columns(2)

        with info_col1:
            st.write(f"**Genre:** {movie.get('Genre', 'N/A')}")
            st.write(f"**Runtime:** {movie.get('Runtime', 'N/A')}")
            st.write(f"**Certificate:** {movie.get('Rated', 'N/A')}")

        with info_col2:
            st.write(f"**IMDb rating:** {movie.get('imdbRating', 'N/A')}")
            st.write(f"**Director:** {movie.get('Director', 'N/A')}")
            st.write(f"**Classification score:** {score}")

        if movie.get("Plot") and movie.get("Plot") != "N/A":
            st.markdown("**Plot**")
            st.write(movie["Plot"])

    st.divider()
    st.subheader("Parental advisory details")

    if not guide_available:
        st.warning(
            "The IMDb Parents Guide could not be read automatically. "
            "The sections below may be incomplete."
        )

    category_columns = st.columns(2)

    for index, (category, details) in enumerate(guide.items()):
        with category_columns[index % 2]:
            severity = details.get("severity", "Not available")
            description = details.get(
                "description",
                "No description available.",
            )

            st.markdown(
                f"""
                <div class="category-card">
                    <div class="category-title">{category}</div>
                    <div class="severity">Severity: {severity}</div>
                    <div>{description or "No description available."}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        f"[Open the IMDb Parents Guide](https://www.imdb.com/title/"
        f"{imdb_id}/parentalguide/)"
    )

    with st.expander("Data and classification notes"):
        st.write(
            "OMDb supplies the movie metadata, poster, genre, IMDb rating, "
            "and certificate. The advisory categories are obtained from "
            "IMDb's Parents Guide when available."
        )
        st.write(
            "The verdict is generated from advisory severity labels and "
            "should be treated as an approximate parent-facing summary."
        )
