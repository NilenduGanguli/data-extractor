# Extract App

This application extracts specific fields from PDF documents (like 10-K forms and Annual Reports) using spaCy and PyMuPDF.

## Setup

1.  Create a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    python -m spacy download en_core_web_sm
    ```

## Usage

Run the `main.py` script with the path to the PDF file:

```bash
python main.py ../docs/broadcom-form10k.pdf
```

## Extracted Fields

The application attempts to extract the following fields:
-   Company Name
-   Auditor
-   Address
-   Line of Business
-   Directors
-   Revenue
-   Shares Traded
-   Number of Employees
