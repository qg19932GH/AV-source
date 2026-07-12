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
    std_match = re.search(r'([a-zA-Z]{2,8})\s*-?\s*([0-9]{3,6})', name)
    if std_match:
        return f"{std_match.group(1).upper()}-{std_match.group(2)}"
        
    return ""
