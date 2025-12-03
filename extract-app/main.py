import sys
import spacy
import fitz  # PyMuPDF
import re
import json
from spacy.matcher import Matcher

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        return full_text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

def extract_info(text):
    nlp = spacy.load("en_core_web_sm")
    doc = nlp(text[:1000000]) # Limit to 1MB of text to avoid memory issues for now
    
    data = {
        "company_name": None,
        "auditor": None,
        "address": None,
        "line_of_business": None,
        "directors": [],
        "revenue": None,
        "shares_traded": None,
        "employees": None,
        "parent_ownership": None,
        "subsidiaries_ownership": None,
        "contact_number": None,
        "former_name": None,
        "senior_management": [],
        "incorporation_date": None,
        "company_number": None,
        "type_of_company": None,
        "auditor_financial_report": None,
        "individual_profile": None,
        "listing_proof": None,
        "company_data": None
    }

    # 1. Company Name
    # Heuristic: Look for "Exact name of registrant as specified in its charter"
    # And ensure it has a legal entity suffix
    legal_suffixes = ["Inc", "Inc.", "Corp", "Corp.", "Corporation", "Ltd", "Ltd.", "Limited", "PLC", "P.L.C.", "LLC", "L.L.C.", "Co.", "Company"]
    
    registrant_idx = text.find("Exact name of registrant as specified in its charter")
    if registrant_idx != -1:
        # Look at the text immediately following
        snippet = text[registrant_idx:registrant_idx+500]
        lines = snippet.split('\n')
        for line in lines[1:]:
            clean_line = line.strip()
            if clean_line and len(clean_line) > 3 and "Commission" not in clean_line and "Exact name" not in clean_line:
                # Check for suffix
                if any(suffix in clean_line for suffix in legal_suffixes):
                    data["company_name"] = clean_line
                    break
                # Sometimes the name is just the name without suffix in the header, but let's be strict if requested
                # Or maybe the suffix is on the next line?
                # Let's try to grab it if it looks like a name (uppercase)
                if clean_line.isupper():
                     data["company_name"] = clean_line
                     break
    
    if not data["company_name"]:
        # Fallback: Search first page for lines containing legal suffixes
        # Annual reports often have the company name in large text on the first page
        first_page_text = text[:3000]
        lines = first_page_text.split('\n')
        for line in lines:
            clean_line = line.strip()
            # Check if line ends with a legal suffix or contains it prominently
            if any(clean_line.endswith(suffix) or clean_line.endswith(suffix.upper()) for suffix in legal_suffixes):
                # Filter out common noise
                if "Commission" in clean_line or "Securities" in clean_line or "Address" in clean_line or "Copyright" in clean_line:
                    continue
                if len(clean_line) < 100: # Company names are usually short
                    data["company_name"] = clean_line
                    break
    
    if not data["company_name"]:
        # Fallback: Look in "Item 1. Business" for "Company Name (the 'Company')" pattern
        # "CVS Health Corporation, together with its subsidiaries..."
        item1_idx = text.find("Item 1. Business")
        if item1_idx != -1:
            snippet = text[item1_idx:item1_idx+500]
            # Look for a sequence of capitalized words followed by "Corporation", "Inc", etc.
            # and maybe followed by "("
            match = re.search(r'([A-Z][a-zA-Z0-9\s,&]+(?:Inc|Corp|Corporation|Ltd|PLC|Co)\.?)', snippet)
            if match:
                candidate = match.group(1).strip()
                # Clean up leading newlines or noise
                if "\n" in candidate:
                    candidate = candidate.split('\n')[-1].strip()
                
                if len(candidate) > 3 and "The" not in candidate:
                     data["company_name"] = candidate

    # 2. Address
    # Heuristic: Look for "Address of principal executive offices"
    addr_idx = text.find("Address of principal executive offices")
    if addr_idx != -1:
        snippet = text[addr_idx:addr_idx+500]
        # The address is usually on the lines following the label
        lines = snippet.split('\n')
        address_lines = []
        capture = False
        for line in lines:
            if "Address of principal executive offices" in line:
                capture = True
                continue
            if capture:
                # Stop if we hit another field label like "Telephone" or "Securities"
                if "Telephone" in line or "Securities" in line or "Indicate by check mark" in line:
                    break
                
                # If line contains "Zip Code", try to extract the code
                if "Zip Code" in line:
                    # Check if the code is on this line
                    zip_match = re.search(r'\d{5}(?:-\d{4})?', line)
                    if zip_match:
                        address_lines.append(line[:zip_match.end()].strip())
                    else:
                        # Maybe it's just the label, and the code is next?
                        # Or maybe the previous lines were the address and this ends it.
                        # Let's assume this line is part of it but we need the code.
                        pass 
                    break
                
                if re.search(r'\d{5}', line):
                    address_lines.append(line.strip())
                    break
                if line.strip():
                    address_lines.append(line.strip())
        
        if address_lines:
            data["address"] = ", ".join(address_lines)
    
    if not data["address"]:
        # Fallback regex: Look for number followed by street name
        # Must match "123 Main St" format
        # Added more street types and relaxed the match slightly
        address_pattern = re.compile(r'\b\d+\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Way|Drive|Dr|Plaza|Parkway|Pkwy|Court|Ct|Circle|Cir|Lane|Ln|Plaza)\b.*?\d{5}(?:-\d{4})?', re.DOTALL | re.IGNORECASE)
        # Search in the first few pages only
        address_match = address_pattern.search(text[:5000]) 
        if address_match:
            # Validate it's not a law citation (e.g. 1934 Act)
            candidate = address_match.group(0).strip().replace('\n', ', ')
            if "Act" not in candidate and "Section" not in candidate and "Commission" not in candidate:
                data["address"] = candidate
        else:
            # Try searching for just City, State Zip if street is missing (e.g. "New York, New York 10001")
            city_state_zip = re.search(r'([A-Z][a-zA-Z\s]+,\s+[A-Z][a-zA-Z\s]+\s+\d{5})', text[:3000])
            if city_state_zip:
                 data["address"] = city_state_zip.group(1)

    # 3. Auditor
    # Look for "Report of Independent Registered Public Accounting Firm"
    # And find the auditor name usually at the bottom of the report (signature) or in the title
    auditor_keywords = ["Report of Independent Registered Public Accounting Firm", "Report of Independent Registered Public Accounting Firm"]
    
    # Common auditors to look for specifically
    known_auditors = ["Ernst & Young", "PricewaterhouseCoopers", "Deloitte", "KPMG", "Grant Thornton", "BDO"]
    
    for auditor in known_auditors:
        if auditor.lower() in text.lower():
            data["auditor"] = auditor
            break
            
    if not data["auditor"]:
        for keyword in auditor_keywords:
            idx = text.find(keyword)
            if idx != -1:
                # Look for ORG nearby (after the header)
                snippet = text[idx:idx+2000] # The report is usually a page long
                snippet_doc = nlp(snippet)
                for ent in snippet_doc.ents:
                    if ent.label_ == "ORG" and "LLP" in ent.text:
                         data["auditor"] = ent.text
                         break
            if data["auditor"]: break

    # 4. Number of Employees
    # Look for "employees" or "colleagues" (CVS uses colleagues)
    # "As of October 29, 2023, we had approximately 20,000 employees"
    employee_pattern = re.compile(r'As of.*?, we had approximately\s+(\d+(?:,\d+)*)\s+(?:full-time\s+)?(?:employees|colleagues)', re.IGNORECASE)
    emp_match = employee_pattern.search(text)
    if emp_match:
        data["employees"] = emp_match.group(1)
    else:
        # Fallback
        # Look for "full-time employees" specifically to avoid other large numbers
        employee_pattern = re.compile(r'(\d+(?:,\d+)*)\s+(?:full-time|part-time)\s+(?:employees|colleagues)', re.IGNORECASE)
        emp_match = employee_pattern.search(text)
        if emp_match:
            data["employees"] = emp_match.group(1)
        else:
             # Try "approximately X employees"
             employee_pattern = re.compile(r'(?:approximately|more than)\s+(\d+(?:,\d+)*)\s+(?:employees|colleagues)', re.IGNORECASE)
             emp_match = employee_pattern.search(text)
             if emp_match:
                 data["employees"] = emp_match.group(1)

    # 5. Revenue
    # Look for "Total net revenue" or similar in Consolidated Statements of Operations
    
    revenue_scale = ""
    # Check for scale indicators
    if "in millions" in text[:5000].lower() or "in millions" in text.lower():
        revenue_scale = " million"
    elif "in thousands" in text[:5000].lower() or "in thousands" in text.lower():
        revenue_scale = " thousand"
    elif "in billions" in text[:5000].lower() or "in billions" in text.lower():
        revenue_scale = " billion"
        
    # Regex to capture the number
    # Prioritize "Total Revenues" or "Total Net Revenues"
    revenue_pattern_high_pri = re.compile(r'Total\s+(?:Net\s+)?Revenues?.*?\$\s*(\d{1,3}(?:,\d{3})+)', re.IGNORECASE | re.DOTALL)
    revenue_pattern_gen = re.compile(r'(?:Net|Total)\s+Revenues?.*?\$\s*(\d{1,3}(?:,\d{3})+)', re.IGNORECASE | re.DOTALL)
    
    fin_idx = text.find("Consolidated Statements of Operations")
    if fin_idx != -1:
        snippet = text[fin_idx:fin_idx+5000]
        # Look for scale in this section specifically
        if "(in millions" in snippet.lower():
            revenue_scale = " million"
        elif "(in thousands" in snippet.lower():
            revenue_scale = " thousand"
            
        rev_match = revenue_pattern_high_pri.search(snippet)
        if not rev_match:
            rev_match = revenue_pattern_gen.search(snippet)
            
        if rev_match:
            data["revenue"] = "$" + rev_match.group(1) + revenue_scale
    
    if not data["revenue"]:
        rev_match = revenue_pattern_high_pri.search(text)
        if not rev_match:
            rev_match = revenue_pattern_gen.search(text)
            
        if rev_match:
            data["revenue"] = "$" + rev_match.group(1) + revenue_scale

    # 6. Shares Traded (Common Stock outstanding)
    # "As of November 28, 2023, there were 465,006,600 shares of the Registrant's common stock outstanding"
    shares_pattern = re.compile(r'(\d+(?:,\d+)*)[\s\n]+shares[\s\n]+of[\s\n]+(?:the[\s\n]+)?(?:Registrant[\u2019\']s[\s\n]+)?common[\s\n]+stock[\s\n]+outstanding', re.IGNORECASE)
    shares_match = shares_pattern.search(text)
    if shares_match:
        data["shares_traded"] = shares_match.group(1)

    # 7. Directors
    # Look for "Item 10. Directors"
    # Or "Election of Directors"
    # Or "Board of Directors" at the end of the document
    directors_idx = text.find("Item 10. Directors")
    if directors_idx == -1:
        directors_idx = text.find("Election of Directors")
        
    if directors_idx != -1:
        # Extract names following this header
        # This is still hard because it might just refer to a proxy statement.
        # "The information required by this item is incorporated by reference..."
        snippet = text[directors_idx:directors_idx+500]
        if "incorporated by reference" in snippet.lower():
             data["directors"] = ["Referenced in Proxy Statement"]
        else:
            snippet = text[directors_idx:directors_idx+2000]
            snippet_doc = nlp(snippet)
            for ent in snippet_doc.ents:
                if ent.label_ == "PERSON":
                    if ent.text not in data["directors"] and len(ent.text) > 3:
                        data["directors"].append(ent.text)
    
    if not data["directors"] or data["directors"] == ["Referenced in Proxy Statement"]:
        # Try searching for "Board of Directors" in the last 10% of the document
        # or just search for the header generally
        bod_indices = [m.start() for m in re.finditer(r'Board of Directors', text)]
        if bod_indices:
            # Check the last occurrence first as it's often the listing
            for idx in reversed(bod_indices):
                snippet = text[idx:idx+2000]
                # If it looks like a list (names on new lines)
                snippet_doc = nlp(snippet)
                found_directors = []
                for ent in snippet_doc.ents:
                    if ent.label_ == "PERSON" and len(ent.text) > 3 and ent.text not in found_directors:
                        # Filter out common non-names
                        if "Committee" not in ent.text and "Chair" not in ent.text and "Director" not in ent.text and "Officer" not in ent.text:
                            found_directors.append(ent.text)
                
                if len(found_directors) > 3: # If we found a good list
                    data["directors"] = found_directors
                    break
        
        # If still no directors, try looking for "Trustees" (common in some funds/companies)
        if not data["directors"]:
             trustees_indices = [m.start() for m in re.finditer(r'Board of Trustees', text)]
             if trustees_indices:
                for idx in reversed(trustees_indices):
                    snippet = text[idx:idx+2000]
                    snippet_doc = nlp(snippet)
                    found_directors = []
                    for ent in snippet_doc.ents:
                        if ent.label_ == "PERSON" and len(ent.text) > 3 and ent.text not in found_directors:
                             if "Committee" not in ent.text and "Chair" not in ent.text:
                                found_directors.append(ent.text)
                    if len(found_directors) > 3:
                        data["directors"] = found_directors
                        break

    # 8. Line of Business
    # "Item 1. Business"
    lob_idx = text.find("Item 1. Business")
    if lob_idx != -1:
        data["line_of_business"] = text[lob_idx:lob_idx+500].strip() + "..."

    # 9. Contact Number
    # "Registrant’s telephone number, including area code: (xxx) xxx-xxxx"
    phone_pattern = re.compile(r'telephone\s+number.*?:?\s*(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})', re.IGNORECASE)
    phone_match = phone_pattern.search(text[:5000])
    if phone_match:
        data["contact_number"] = phone_match.group(1)

    # 10. Company Number (Commission File Number or IRS EIN)
    # "Commission File Number 001-38449"
    cfn_pattern = re.compile(r'Commission\s+File\s+Number:?\s*([0-9-]+)', re.IGNORECASE)
    cfn_match = cfn_pattern.search(text[:5000])
    if cfn_match:
        data["company_number"] = cfn_match.group(1)
    else:
        # Try IRS EIN
        ein_pattern = re.compile(r'Employer\s+Identification\s+No\.:?\s*([0-9-]+)', re.IGNORECASE)
        ein_match = ein_pattern.search(text[:5000])
        if ein_match:
            data["company_number"] = "EIN: " + ein_match.group(1)

    # 11. Incorporation Date
    # "incorporated in Delaware in 1988" or "founded in"
    inc_pattern = re.compile(r'incorporated\s+in\s+[A-Z][a-z]+\s+(?:in|on)\s+([A-Z][a-z]+\s+\d{1,2},?\s+)?(\d{4})', re.IGNORECASE)
    inc_match = inc_pattern.search(text[:10000])
    if inc_match:
        data["incorporation_date"] = inc_match.group(0)
    else:
        # Try "organized under the laws of ... in [Year]"
        org_pattern = re.compile(r'organized\s+under\s+the\s+laws\s+of.*?\s+in\s+(\d{4})', re.IGNORECASE)
        org_match = org_pattern.search(text[:10000])
        if org_match:
            data["incorporation_date"] = org_match.group(1)

    # 12. Type of Company
    # Check for "Large accelerated filer", "Accelerated filer", etc.
    filer_types = ["Large accelerated filer", "Accelerated filer", "Non-accelerated filer", "Smaller reporting company", "Emerging growth company"]
    for ftype in filer_types:
        if ftype in text[:5000]:
            # Usually there is a check mark or "X" next to it.
            # Simple heuristic: if it's present, it's a candidate, but we need to see if it's checked.
            # This is hard with text extraction.
            # Let's just infer from the name suffix for now as a fallback
            pass
    
    if data["company_name"]:
        if "Inc" in data["company_name"] or "Corporation" in data["company_name"]:
            data["type_of_company"] = "Corporation"
        elif "LLC" in data["company_name"]:
            data["type_of_company"] = "LLC"
        elif "PLC" in data["company_name"]:
            data["type_of_company"] = "Public Limited Company"

    # 13. Listing Proof (Trading Symbol)
    # Look for table with "Trading Symbol"
    symbol_pattern = re.compile(r'Trading\s+Symbol\(s\).*?([A-Z]{1,5})\b', re.DOTALL | re.IGNORECASE)
    symbol_match = symbol_pattern.search(text[:5000])
    if symbol_match:
        data["listing_proof"] = "Trading Symbol: " + symbol_match.group(1)

    # 14. Auditor's Financial Report
    # Extract the first paragraph of the auditor's report
    if data["auditor"]:
        report_idx = text.find("Report of Independent Registered Public Accounting Firm")
        if report_idx != -1:
            # Find the start of the opinion
            opinion_idx = text.find("Opinion on the Financial Statements", report_idx)
            if opinion_idx != -1:
                data["auditor_financial_report"] = text[opinion_idx:opinion_idx+500].strip() + "..."
            else:
                data["auditor_financial_report"] = text[report_idx:report_idx+500].strip() + "..."

    # 15. Senior Management
    # "Information about our Executive Officers"
    mgmt_idx = text.find("Information about our Executive Officers")
    if mgmt_idx == -1:
        mgmt_idx = text.find("Executive Officers of the Registrant")
    
    if mgmt_idx != -1:
        snippet = text[mgmt_idx:mgmt_idx+3000]
        snippet_doc = nlp(snippet)
        for ent in snippet_doc.ents:
            if ent.label_ == "PERSON" and len(ent.text) > 3:
                if ent.text not in data["senior_management"] and ent.text not in data["directors"]:
                     data["senior_management"].append(ent.text)

    # 16. Subsidiaries Ownership
    # Look for "Exhibit 21"
    if "Exhibit 21" in text:
        data["subsidiaries_ownership"] = "Referenced in Exhibit 21"
    
    # 17. Parent Ownership
    # Look for "Parent" in Security Ownership section
    sec_own_idx = text.find("Security Ownership of Certain Beneficial Owners")
    if sec_own_idx != -1:
        snippet = text[sec_own_idx:sec_own_idx+2000]
        if "Parent" in snippet:
            data["parent_ownership"] = "Parent company mentioned in Security Ownership section"
        else:
            data["parent_ownership"] = "No parent company explicitly identified in Security Ownership section"

    # 18. Former Name
    # "formerly known as"
    former_pattern = re.compile(r'formerly\s+known\s+as\s+([A-Z][a-zA-Z0-9\s,&]+)', re.IGNORECASE)
    former_match = former_pattern.search(text[:5000])
    if former_match:
        data["former_name"] = former_match.group(1).strip()

    # 19. Company Data (Metadata)
    # Just grab the first 200 chars as a summary
    data["company_data"] = text[:200].strip().replace('\n', ' ')

    return data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    text = extract_text_from_pdf(pdf_path)
    
    if text:
        extracted_data = extract_info(text)
        print(json.dumps(extracted_data, indent=4))
