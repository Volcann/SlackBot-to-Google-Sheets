import re
import math
import json
import gspread
import os, logging

def get_gspread_client():
    raw = os.getenv("GS_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GS_CREDENTIALS_JSON is not set in the environment")

    try:
        creds_dict = json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error("Failed to parse GS_CREDENTIALS_JSON: %r", raw[:200])
        raise RuntimeError("Invalid JSON in GS_CREDENTIALS_JSON") from e

    return gspread.service_account_from_dict(creds_dict)

# Function to clean text encoding issues
def clean_text(text):
    if isinstance(text, str):
        text = text.replace("â¢", "•")  # Fix bullet points
        text = re.sub(r"\n+", "\n", text)  # Remove excessive newlines
        text = re.sub(r"(\d+)\s?h\s?r", r"\1 hrs", text)  # Fix broken 'hr' words
        text = text.replace("h r", "hr").replace("h\nr", "hr")  # Fix spacing issues
    return text.strip() if isinstance(text, str) else text

# Function to standardize time formats
def standardize_time(time_text):
    if isinstance(time_text, str):
        time_text = re.sub(r"(\d+)(hr|hrs|h)", r"\1 hrs", time_text)  # Ensure "hrs" format
        time_text = time_text.replace(" hrs hrs", " hrs")  # Remove duplicate "hrs"
        time_text = time_text.replace("hrs\n", " hrs\n")  # Ensure correct spacing
        return time_text.strip()
    return time_text

# Job of normalizing time values by removing spaces
def clean_time_column(value):
    if isinstance(value, str):  # Ensure the value is a string
        value = re.sub(r"\s+", "", value)  # Remove all spaces
        value = re.sub(r"hrs?", "hrs", value)  # Fix "hrss" to "hrs"
        return value.replace("\n", ", ")  # Convert newlines to commas
    return value

def clean_double_ss(text):
    """Removes duplicate consecutive 'ss' and replaces them with a single 's'."""
    if isinstance(text, str):
        return re.sub(r'ss+', 's', text)
    return text


def extract_yesterday_tasks(cell: str) -> list:
    """
    Extracts yesterday's tasks from a given cell string.
    Looks for text following the "Yesterday:" marker, stopping at "Today:" or "Blockers:".
    Returns a list of extracted task descriptions.
    """
    pattern = re.compile(
        r'Yesterday:\*?\s*\n(.*?)(?=\n\s*(?:\*?Today:|\*?Blockers:))',
        re.DOTALL | re.IGNORECASE
    )
    matches = pattern.findall(cell)
    return [match.strip() for match in matches]  # Remove leading/trailing whitespace

def extract_yesterday_time_spent(data: str) -> list:
    """
    Extracts time spent on yesterday's tasks from the provided text.
    Looks for numerical values followed by time units (hrs/mins).
    Returns a list of extracted times in a normalized format.
    """
    clean_data = data.replace("\n", " ").replace("\r", " ").strip()
    pattern = re.compile(
        r"(?:\|\s*|\(\s*|[-\s])?([\d\.]+)\s*-?\s*(hrs?|hr|minutes?|mins?)\b",
        re.IGNORECASE
    )
    matches = pattern.findall(clean_data)
    return [f"{num.strip()}{unit.strip().lower()}" for num, unit in matches] if matches else []

def parse_line(line: str) -> float:
    """
    Parses a time entry and returns its value in hours.
    - Handles cases with hours and minutes.
    - Rounds up when necessary.
    """
    line = line.strip()
    if not line:
        return 0.0
    
    hour_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*hrs?", re.IGNORECASE)
    min_pattern  = re.compile(r"(\d+)\s*(?:mins?|minutes?)", re.IGNORECASE)
    
    hours_tokens = hour_pattern.findall(line)
    min_tokens   = min_pattern.findall(line)
    
    has_decimal = any('.' in token for token in hours_tokens)
    hours_sum = sum(float(token) for token in hours_tokens) if hours_tokens else 0.0
    minutes_sum = sum(int(token) for token in min_tokens) if min_tokens else 0.0
    minutes_as_hours = minutes_sum / 60.0
    
    if hours_tokens:
        if not has_decimal and minutes_sum > 0:
            return math.ceil(hours_sum + minutes_as_hours)
        else:
            return hours_sum + minutes_as_hours
    else:
        return minutes_as_hours  # If only minutes, return fractional hour value

def extract_yesterday_total_time(data: str) -> str:
    """
    Sums up time entries from a multiline string and formats the total.
    """
    lines = data.splitlines()
    total = sum(parse_line(line) for line in lines)
    
    whole = int(total)
    frac = total - whole
    if abs(frac - 0.5) < 1e-6 and total != whole:
        return f"{whole}hrs 30mins"
    else:
        return f"{round(total)}hrs"

def extract_today_tasks(cell: str) -> list:
    """
    Extracts today's tasks from a given cell string.
    Looks for text following the "Today:" marker, stopping at "Blockers:".
    Returns a list of extracted task descriptions.
    """
    pattern = re.compile(
        r'Today:\*?\s*\n(.*?)(?=\n\s*(?:\*?Blockers:))',
        re.DOTALL | re.IGNORECASE
    )
    matches = pattern.findall(cell)
    return [match.strip() for match in matches]

def extract_today_time_spent(data: str) -> str:
    """
    Extracts time spent on today's tasks from the provided text.
    Looks for numerical values followed by time units (hrs/mins).
    Returns a formatted string of extracted times or "0" if none found.
    """
    clean_data = data.replace("\n", " ").replace("\r", " ").strip()
    today_sections = re.split(r"(?i)\*?Today:\*?", clean_data)
    time_entries = []
    
    for section in today_sections[1:]:
        section = re.split(r"(?i)\*?(Yesterday:|Blockers:|Status:)", section)[0].strip()
        pattern = re.compile(
            r"([\d\.]+)\s*(hrs?|hr|minutes?|mins?)\b",
            re.IGNORECASE
        )
        matches = pattern.findall(section)
        
        for num, unit in matches:
            unit = 'hr' if unit in ['hr', 'hrs'] else 'min'
            time_entries.append(f"{num.strip()}{unit}")
    
    return "".join(time_entries) if time_entries else "0"

def extract_blocker_tasks(cell: str) -> list:
    """
    Extracts blocker descriptions from a given cell string.
    Grabs everything after “Blockers:” up to “Status:” or end of cell.
    If no blockers are found, returns ['N/A'].
    """
    pattern = re.compile(
        r'Blockers:\*?\s*\n(.*?)(?=\n\s*(?:\*?Status:))?',
        re.DOTALL | re.IGNORECASE
    )
    matches = pattern.findall(cell)
    if not matches or all(not m.strip() for m in matches):
        return ['N/A']
    return [m.strip() for m in matches]

def extract_today_total_time(data: str) -> str:
    """
    Extracts and sums time spent on today's tasks from the provided text.
    Returns the total time in hours.
    """
    times = [float(t) for t in re.findall(r"Today:.*?\|\s*([\d\.]+)\s*hrs?", data, re.DOTALL)]
    return str(sum(times)) if times else "0"