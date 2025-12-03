import sys
import spacy
import fitz  # PyMuPDF
import re
import json

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        # Read first 20 pages for metadata, and maybe search specific sections later
        # For 10-Ks, metadata is on page 1.
        for i, page in enumerate(doc):
            full_text += page.get_text()
            # If we just want metadata, we don't need the whole 100 page doc, 
            # but for "Ownership" which is Item 12, it might be deep in the doc.
            # Let's read all for now, it's safer.
        return full_text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

def extract_sec_info(text):
    nlp = spacy.load("en_core_web_sm")
    # Truncate for NLP processing to avoid memory issues, but keep full text for regex searches
    doc = nlp(text[:1000000]) 
    
    data = {
        "name": None,
        "address": None,
        "incorporation_date": None,
        "incorporation_country": None,
        "registered_country": None,
        "ownership": None
    }

    # 1. Name
    # "Exact name of registrant as specified in its charter"
    # Use regex for case insensitivity (Registrant vs registrant) and whitespace
    registrant_match = re.search(r"Exact name of registrant.*?specified in its charter", text, re.IGNORECASE | re.DOTALL)
    if registrant_match:
        registrant_idx = registrant_match.start()
        # Look backwards first
        snippet_before = text[max(0, registrant_idx-200):registrant_idx]
        lines_before = snippet_before.split('\n')
        # Iterate backwards
        found_name = False
        for line in reversed(lines_before):
            clean_line = line.strip()
            if clean_line and len(clean_line) > 3 and "Commission" not in clean_line:
                data["name"] = clean_line
                found_name = True
                break
        
        if not found_name:
            # Look forwards if not found backwards (fallback)
            snippet = text[registrant_idx:registrant_idx+500]
            lines = snippet.split('\n')
            for line in lines[1:]:
                clean_line = line.strip()
                if clean_line and len(clean_line) > 3 and "Commission" not in clean_line and "Exact name" not in clean_line:
                    data["name"] = clean_line
                    break
    
    # Fallback for 13F (FILER section) - Check this BEFORE generic spaCy fallback
    if not data["name"] and "FORM 13F" in text[:1000]:
        filer_idx = text.find("FILER")
        if filer_idx != -1:
            snippet = text[filer_idx:filer_idx+200]
            lines = snippet.split('\n')
            if len(lines) > 1:
                candidate = lines[1].strip()
                if candidate and "CIK" not in candidate:
                    data["name"] = candidate
        
        if not data["name"]:
             # Try "Name:" under "Institutional Investment Manager"
             name_idx = text.find("Institutional Investment Manager Filing this Report")
             if name_idx != -1:
                 snippet = text[name_idx:name_idx+300]
                 lines = snippet.split('\n')
                 for i, line in enumerate(lines):
                     if "Name:" in line:
                         if i + 1 < len(lines):
                             data["name"] = lines[i+1].strip()
                         break

    if not data["name"]:
        # Fallback: Look for large ORG entity on first page
        for ent in doc.ents[:20]:
            if ent.label_ == "ORG" and "Commission" not in ent.text and "Business Address" not in ent.text and "Mailing Address" not in ent.text:
                data["name"] = ent.text
                break

    # 2. Address
    # "Address of principal executive offices"
    # Regex to handle variations like "Address and telephone number... of principal executive offices"
    addr_match = re.search(r"Address.*?principal executive\s+offices", text, re.IGNORECASE | re.DOTALL)
    if addr_match:
        addr_idx = addr_match.start()
        
        # Strategy 1: Look backwards (Common in 10-Ks)
        snippet_before = text[max(0, addr_idx-300):addr_idx]
        lines_before = snippet_before.split('\n')
        address_lines_back = []
        
        # Iterate backwards, collecting lines until we hit a label or empty space gap
        for line in reversed(lines_before):
            clean_line = line.strip()
            if not clean_line:
                continue
            # Stop if we hit another label (like IRS No or State)
            if "I.R.S." in clean_line or "State or other" in clean_line or "incorporation" in clean_line or "Identification No." in clean_line:
                break
            if "Zip Code" in clean_line or clean_line.startswith('('): # Skip Zip Code label or open paren
                continue
            
            address_lines_back.insert(0, clean_line)
            if len(address_lines_back) >= 4: # Assume max 4 lines for address
                break
        
        if address_lines_back:
             data["address"] = ", ".join(address_lines_back)
        else:
            # Strategy 2: Look forwards (Fallback)
            snippet = text[addr_idx:addr_idx+500]
            lines = snippet.split('\n')
            address_lines = []
            capture = False
            for line in lines:
                if "Address of principal executive offices" in line:
                    capture = True
                    continue
                if capture:
                    if "Zip Code" in line or "Telephone" in line:
                        if "Zip Code" in line:
                             # Try to grab the zip code line
                             address_lines.append(line.strip())
                        break
                    if line.strip():
                        address_lines.append(line.strip())
            if address_lines:
                data["address"] = ", ".join(address_lines)

    # 3. Incorporation Country (Jurisdiction)
    # "State or other jurisdiction of incorporation or organization"
    jurisdiction_match = re.search(r"State or other jurisdiction.*?incorporation or organization", text, re.IGNORECASE | re.DOTALL)
    if jurisdiction_match:
        jurisdiction_idx = jurisdiction_match.start()
        
        # Look backwards first
        snippet_before = text[max(0, jurisdiction_idx-200):jurisdiction_idx]
        lines_before = snippet_before.split('\n')
        for line in reversed(lines_before):
            clean_line = line.strip()
            # Skip IRS number (XX-XXXXXXX) or empty parens
            # Also skip lines that are just punctuation
            if re.match(r'^\d{2}-\d{7}$', clean_line) or clean_line.startswith('('):
                continue
            if clean_line and len(clean_line) > 2:
                data["incorporation_country"] = clean_line
                break
        
        if not data["incorporation_country"]:
            # Look forwards
            snippet = text[jurisdiction_idx:jurisdiction_idx+300]
            lines = snippet.split('\n')
            for line in lines[1:]:
                clean_line = line.strip()
                if clean_line and len(clean_line) > 2:
                    data["incorporation_country"] = clean_line
                    break
    
    if not data["incorporation_country"]:
        # Fallback regex
        inc_country_pattern = re.compile(r'incorporated\s+in\s+([A-Z][a-zA-Z\s]+)', re.IGNORECASE)
        match = inc_country_pattern.search(text[:5000])
        if match:
            data["incorporation_country"] = match.group(1).strip()

    # 4. Registered Country
    # Usually same as incorporation country, or inferred from address
    if data["incorporation_country"]:
        data["registered_country"] = data["incorporation_country"]
    elif data["address"]:
        # Try to find country in address
        # Simple check for common countries
        if "United States" in data["address"] or re.search(r'\b[A-Z]{2}\s+\d{5}', data["address"]):
            data["registered_country"] = "United States"
        elif "United Kingdom" in data["address"] or "UK" in data["address"]:
            data["registered_country"] = "United Kingdom"
        # Add more as needed

    # 5. Incorporation Date
    # "incorporated in [State] on [Date]" or "founded in [Year]"
    # Normalize text for regex (remove newlines)
    text_normalized = text[:20000].replace('\n', ' ')
    # Updated regex to include "established" and "founded", and Month Year format
    # Also handle "founded Amazon.com in 1994"
    inc_date_pattern = re.compile(r'(?:incorporated|established|founded)(?:\s+[A-Za-z\.\,]+){0,5}?\s+(?:on|in)\s+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|[A-Z][a-z]+\s+\d{4}|\d{4})', re.IGNORECASE)
    match = inc_date_pattern.search(text_normalized)
    if match:
        data["incorporation_date"] = match.group(1)

    # 6. Ownership
    # For 10-K: "Item 12. Security Ownership of Certain Beneficial Owners"
    # For 13F: It IS the report of holdings.
    
    # Check for 10-K style ownership section
    # Find all occurrences of "Security Ownership"
    ownership_matches = [m.start() for m in re.finditer(r"Security Ownership of Certain Beneficial Owners", text)]
    
    for own_idx in ownership_matches:
        snippet = text[own_idx:own_idx+2000]
        
        # Check if it says "incorporated by reference"
        if "incorporated" in snippet.lower() and "reference" in snippet.lower() and "proxy statement" in snippet.lower():
            data["ownership"] = "Incorporated by reference from Proxy Statement"
            break
        
        # Check if there is a table with "Name of Beneficial Owner"
        if "Name of Beneficial Owner" in snippet:
             # Try to extract rows? This is hard without table structure.
             # But we can say we found the table.
             data["ownership"] = "Contains Security Ownership table (Item 12)"
             break

    # Check for 13F style (Name of Manager)
    if "FORM 13F" in text[:1000]:
        # The filer is the owner/manager
        holdings = []
        
        # Logic for line-by-line extraction (Name, Class, CUSIP on separate lines)
        lines = text.split('\n')
        for i in range(len(lines) - 2):
            line = lines[i].strip()
            next_line = lines[i+1].strip()
            next_next_line = lines[i+2].strip()
            
            # Check if next_line is Class and next_next_line is CUSIP
            # Class regex: COM, CL A, etc.
            # CUSIP regex: 9 chars alphanumeric
            
            is_class = re.match(r'^(COM|CL [A-Z]|PFD|WTS|UNIT|SPON|ADR|COM SER [A-Z])$', next_line)
            is_cusip = re.match(r'^[A-Z0-9]{9}$', next_next_line)
            
            if is_class and is_cusip:
                # Then current line is likely the Name
                name = line
                if len(name) > 2 and name not in ["COLUMN 1", "NAME OF ISSUER", "SOLE", "SHARED", "NONE"]:
                    holdings.append(name)

        if holdings:
            # Return top 20 unique holdings
            unique_holdings = sorted(list(set(holdings)))
            data["ownership"] = f"Holdings include: {', '.join(unique_holdings[:20])}..."
        elif data["name"]:
             data["ownership"] = f"Report filed by {data['name']} (Institutional Investment Manager)"

    # Check for Form 4 (Statement of Changes in Beneficial Ownership)
    if "FORM 4" in text[:1000]:
        # Look for "Name of Reporting Person"
        rep_person_idx = text.find("Name of Reporting Person")
        if rep_person_idx != -1:
             # Extract next line
             snippet = text[rep_person_idx:rep_person_idx+200]
             lines = snippet.split('\n')
             for line in lines[1:]:
                 if line.strip():
                     data["ownership"] = f"Reporting Person: {line.strip()}"
                     break

    return data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    text = extract_text_from_pdf(pdf_path)
    
    if text:
        extracted_data = extract_sec_info(text)
        print(json.dumps(extracted_data, indent=4))
