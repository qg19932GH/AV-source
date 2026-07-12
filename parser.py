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
        
    # 4. Standard JAV style: Letters (optionally containing numbers) followed by numbers
    candidates = []
    
    # Pattern 1: With hyphen (dash is present). Prefix can be letters optionally followed by numbers.
    # We allow 1-8 letters optionally followed by 0-3 digits as prefix.
    pattern_with_dash = r'([a-zA-Z]{1,8}[0-9]{0,3})\s*-\s*([0-9]{3,6})'
    for match in re.finditer(pattern_with_dash, name):
        prefix = match.group(1)
        numbers = match.group(2)
        
        # Verify it has letters in the prefix
        letters_only = re.sub(r'[0-9]', '', prefix)
        if not letters_only:
            continue
            
        # Normalize leading zeros for numbers (keep at least 3 digits)
        if len(numbers) > 3 and numbers.startswith('0'):
            while len(numbers) > 3 and numbers.startswith('0'):
                numbers = numbers[1:]
                
        start_idx = match.start()
        end_idx = match.end()
        
        score = 10  # Base score of 10 because it has a dash
        
        after_match = name[end_idx:]
        if after_match.startswith('.'):
            m = re.match(r'^\.[a-zA-Z]{2,6}\b', after_match)
            if m:
                score -= 20
                
        if start_idx > 0 and name[start_idx-1] == '.':
            score -= 20
            
        if letters_only.lower() in {'com', 'net', 'org', 'xyz', 'club', 'vip', 'cc', 'co', 'info', 'me', 'top', 'win', 'space', 'icu', 'red', 'blue', 'www', 'http', 'https', 'html', 'htm'}:
            score -= 30
            
        candidates.append((score, start_idx, f"{prefix.upper()}-{numbers}"))
        
    # Pattern 2: Without hyphen (no dash). Prefix must be 2-8 letters only.
    pattern_without_dash = r'([a-zA-Z]{2,8})\s*([0-9]{3,6})'
    for match in re.finditer(pattern_without_dash, name):
        prefix = match.group(1)
        numbers = match.group(2)
        
        # Normalize leading zeros for numbers (keep at least 3 digits)
        if len(numbers) > 3 and numbers.startswith('0'):
            while len(numbers) > 3 and numbers.startswith('0'):
                numbers = numbers[1:]
                
        start_idx = match.start()
        end_idx = match.end()
        
        score = 0  # No dash, so base score is 0
        
        after_match = name[end_idx:]
        if after_match.startswith('.'):
            m = re.match(r'^\.[a-zA-Z]{2,6}\b', after_match)
            if m:
                score -= 20
                
        if start_idx > 0 and name[start_idx-1] == '.':
            score -= 20
            
        if prefix.lower() in {'com', 'net', 'org', 'xyz', 'club', 'vip', 'cc', 'co', 'info', 'me', 'top', 'win', 'space', 'icu', 'red', 'blue', 'www', 'http', 'https', 'html', 'htm'}:
            score -= 30
            
        candidates.append((score, start_idx, f"{prefix.upper()}-{numbers}"))
        
    if candidates:
        # Sort by score descending, then by start index ascending
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]
        
    return ""
