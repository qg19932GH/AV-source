import re

def parse_filename(filename):
    # Remove extension
    name = filename.rsplit('.', 1)[0]
    
    # 1. Check FC2 patterns
    fc2_match = re.search(r'(fc2-ppv-\d+|fc2-\d+)', name, re.IGNORECASE)
    if fc2_match:
        return fc2_match.group(1).upper()
        
    # 2. Check Caribbeancom style (six digits - three digits)
    carib_match = re.search(r'(\d{6}-\d{3})', name)
    if carib_match:
        return carib_match.group(1)
        
    # 3. Check Tokyo-Hot style (nXXXX or kbXXXX)
    th_match = re.search(r'\b(n\d{4}|kb\d{4})\b', name, re.IGNORECASE)
    if th_match:
        return th_match.group(1).lower()
        
    # 4. Standard JAV style: Letters followed by numbers (with optional dash/space)
    # We restrict letters to 2-8 chars, numbers to 3-6 chars.
    # Scan all candidates, rank them by a confidence score to filter out domain names and advertising keywords.
    candidates = []
    for match in re.finditer(r'([a-zA-Z]{2,8})\s*(-?)\s*([0-9]{3,6})', name):
        letters = match.group(1)
        dash = match.group(2)
        numbers = match.group(3)
        
        # Normalize leading zeros for standard JAV code number (keep at least 3 digits)
        if len(numbers) > 3 and numbers.startswith('0'):
            while len(numbers) > 3 and numbers.startswith('0'):
                numbers = numbers[1:]
        
        start_idx = match.start()
        end_idx = match.end()
        
        score = 0
        
        # A hyphen between letters and numbers is a strong indicator of a real JAV code
        if dash == '-':
            score += 10
            
        # If followed by '.' and 2-6 letters (e.g. '.com', '.xyz'), it's likely a domain label (e.g. hhd800.com)
        after_match = name[end_idx:]
        if after_match.startswith('.'):
            m = re.match(r'^\.[a-zA-Z]{2,6}\b', after_match)
            if m:
                score -= 20
                
        # If preceded by '.', it is likely a domain extension (e.g. '.com' in madoubt.com)
        if start_idx > 0 and name[start_idx-1] == '.':
            score -= 20
            
        # Common domain extensions / ad words that shouldn't be matched as JAV code prefixes
        if letters.lower() in {'com', 'net', 'org', 'xyz', 'club', 'vip', 'cc', 'co', 'info', 'me', 'top', 'win', 'space', 'icu', 'red', 'blue', 'www', 'http', 'https', 'html', 'htm'}:
            score -= 30
            
        candidates.append((score, start_idx, f"{letters.upper()}-{numbers}"))
        
    if candidates:
        # Sort by score descending (highest first), then by start index ascending (earliest first)
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]
        
    return ""
